"""All-or-nothing browser standing consent; synthetic ASGI and disposable SQLite."""

import asyncio
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_preview import classify_targets
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_batch_review import (
    ManagedBatchReviews,
    parse_standing_list,
    validate_batch_receipt,
)
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.store import Store

IPS = [IPv4Address("198.51.100.250"), IPv4Address("198.51.100.251")]
PAIRS = [(device, ip) for device in (1, 2) for ip in IPS]
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    inventory = tmp_path / "synthetic.json"
    inventory.write_text(json.dumps([{"id": device, "hostname": f"synthetic-{device}", "management_ip": f"192.0.2.{device}",
        "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"],
        "addition_profile": "fpr1010-766-single-vf-management-v1"} for device in (1, 2)]))
    store = Store(tmp_path / "synthetic.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=inventory,
                       agent_mode="socket", development_auth=False, managed_policy_admission_enabled=True)
    api = create_app(settings, store, DisabledAgentClient())
    registry = ManagedShuns(store)
    registry.initialize()
    api.state.synchronizer.managed_discovery.source.initialize()
    calls, behavior = [], {}

    def internal(request):
        calls.append(request)
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                return await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
        response = asyncio.run(send())
        if request.url.path.endswith("/maintain-batch"):
            if behavior.pop("lost", False):
                raise httpx.ReadTimeout("Synthetic committed reply lost")
            if behavior.get("malformed"):
                return httpx.Response(200, json={**response.json(), "unexpected": True})
        if request.url.path == "/api/v1/status" and behavior.get("upstream_off"):
            return httpx.Response(200, json={**response.json(), "managed_policy_admission_enabled": False})
        if request.url.path == "/api/v1/managed-shuns" and behavior.get("uninitialized"):
            return httpx.Response(200, json={**response.json(), "initialized": False, "revision": 0, "entries": []})
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return {"store": store, "registry": registry, "api": api, "web": web.create_app(settings),
            "calls": calls, "behavior": behavior, "settings": settings}


def payload(lab, *, pairs=PAIRS):
    revision = lab["registry"].snapshot()["revision"]
    protected = lab["api"].state.synchronizer.policy.revision()
    return {"actor": {**ACTOR, "roles": list(ACTOR["roles"])}, "targets": [{"device_id": device, "ip": str(ip)} for device, ip in pairs],
            "managed_revision": revision, "protected_revision": protected, "label": "Fixture", "reason": "Synthetic",
            "maintain_present": True, "confirmation_digest": canonical_managed_change("MAINTAIN", pairs, revision, protected, "Fixture", "Synthetic")[2]}


async def api_post(lab, body=None, *, key=None, app=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app or lab["api"]), base_url="http://internal") as client:
        return await client.post("/api/v1/managed-shuns/maintain-batch", json=body or payload(lab),
                                 headers={"Idempotency-Key": key or str(uuid4())})


def browser(lab, *, app=None, subject="alice", group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app or lab["web"]), base_url="https://synthetic.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


async def prepare(client, **overrides):
    await client.get("/managed-shuns/bulk")
    return await client.post("/managed-shuns/bulk-review", data={"csrf": client.cookies.get("ftd_shun_csrf"),
        "text": "198.51.100.250\nSource 198.51.100.251 detected\n198.51.100.250 # duplicate", "device_ids": ["1", "2"],
        "label": "<b>Fixture</b>", "reason": "Synthetic list", **overrides})


def token(page):
    return re.search(r'name="review" value="([^"]+)"', page.text)[1]


async def confirm(client, review, **overrides):
    return await client.post("/managed-shuns/bulk-confirm", data={"csrf": client.cookies.get("ftd_shun_csrf"),
        "review": review, "confirm_count": "4", "maintain_present": "yes", **overrides})


def unchanged_work(lab):
    with lab["store"]._connection() as db:
        for table in ("operation_jobs", "operation_requests", "manual_import_batches", "managed_restoration_attempts"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("SELECT restoration_suspended FROM managed_shun_registry").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert not any(request.url.path == "/api/v1/refresh-hint" for request in lab["calls"])


def test_whole_batch_is_one_authority_and_no_queue_or_import_provenance(lab):
    result = asyncio.run(api_post(lab))
    assert result.status_code == 200 and result.json()["changed_targets"] == 4, result.text
    assert len(lab["registry"].snapshot()["entries"]) == 4
    with lab["store"]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='MANAGED_SHUN_AUTHORIZED'").fetchone()[0] == 4
    unchanged_work(lab)


@pytest.mark.parametrize("block", ["protected", "observed", "disabled", "pending", "uncertain", "enabled"])
def test_last_member_conflict_never_partially_grants_first_members(lab, block):
    with lab["store"]._connection() as db:
        if block == "protected":
            db.execute("INSERT INTO protected_ips VALUES (?,'','',1,'2026-10-19T00:00:00Z')", (IPS[-1].packed,))
        elif block == "disabled":
            db.execute("UPDATE devices SET enabled=0 WHERE id=2")
        elif block in {"pending", "uncertain"}:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,2,?,?,'2026-10-19T00:00:00Z','ADD')",
                       (str(uuid4()), IPS[-1].packed, "QUEUED" if block == "pending" else "UNVERIFIED"))
    if block == "observed":
        lab["store"].record_observed_shun(2, IPS[-1], "management")
    if block == "enabled":
        assert asyncio.run(api_post(lab, payload(lab, pairs=[PAIRS[-1]]))).status_code == 200
    before = lab["registry"].snapshot()
    events = lab["store"].list_events()
    response = asyncio.run(api_post(lab))
    assert response.status_code == 409
    assert lab["registry"].snapshot() == before and lab["store"].list_events() == events


def test_late_audit_failure_rolls_back_every_target_and_the_single_request(lab, monkeypatch):
    original = lab["store"]._insert_event
    count = [0]
    def fail(*args, **kwargs):
        count[0] += 1
        if count[0] == 3:
            raise sqlite3.OperationalError("Synthetic late audit failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(lab["store"], "_insert_event", fail)
    response = asyncio.run(api_post(lab))
    assert response.status_code == 503 and lab["registry"].snapshot()["entries"] == []
    with lab["store"]._connection() as db:
        assert not db.execute("SELECT 1 FROM managed_shun_requests").fetchone()
        assert not db.execute("SELECT 1 FROM shun_events WHERE event_type='MANAGED_SHUN_AUTHORIZED'").fetchone()


def test_old_key_replay_after_retirement_does_not_reenable_any_member(lab):
    body, key = payload(lab), str(uuid4())
    assert asyncio.run(api_post(lab, body, key=key)).status_code == 200
    lab["registry"].change(str(uuid4()), "RETIRE", PAIRS, 1, 0, canonical_managed_change("RETIRE", PAIRS, 1, 0)[2],
                           "alice", "Alice", ("Operator",))
    events = lab["store"].list_events()
    response = asyncio.run(api_post(lab, body, key=key))
    assert response.status_code == 200 and response.json()["replayed"]
    assert all(not entry["enabled"] for entry in lab["registry"].snapshot()["entries"])
    assert lab["store"].list_events() == events
    unchanged_work(lab)


def test_concurrent_same_key_is_one_whole_commit_and_other_keys_cannot_double_grant(lab):
    body, key = payload(lab), str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: asyncio.run(api_post(lab, body, key=key)), range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert sum(not response.json()["replayed"] for response in responses) == 1
    assert asyncio.run(api_post(lab, body)).status_code == 409
    unchanged_work(lab)


@pytest.mark.parametrize("field,value", [("maintain_present", False), ("maintain_present", "yes"), ("managed_revision", True),
    ("protected_revision", "0"), ("action", "ADD"), ("targets", [{"device_id": True, "ip": "198.51.100.250"}]),
    ("targets", [{"device_id": 1, "ip": 3325256954}]), ("targets", [{"device_id": 1, "ip": "198.51.100.250", "command": "shun"}])])
def test_strict_body_rejects_coercion_and_arbitrary_fields(lab, field, value):
    body = payload(lab)
    body[field] = value
    assert asyncio.run(api_post(lab, body)).status_code == 422
    assert lab["registry"].snapshot()["entries"] == []


def test_duplicate_pairs_and_disabled_gate_or_role_never_admit(lab):
    body = payload(lab)
    body["targets"].append(body["targets"][0])
    assert asyncio.run(api_post(lab, body)).status_code == 422
    body = payload(lab)
    body["actor"]["roles"] = ["Viewer"]
    assert asyncio.run(api_post(lab, body)).status_code == 403
    app = create_app(replace(lab["settings"], managed_policy_admission_enabled=False), lab["store"], DisabledAgentClient())
    assert asyncio.run(api_post(lab, app=app)).status_code == 503
    unchanged_work(lab)


def test_browser_prepares_frozen_consent_and_saves_every_pair(lab):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            assert page.status_code == 200 and '4 device/IP pairs' in page.text
            assert '&lt;b&gt;Fixture&lt;/b&gt;' in page.text and '<b>Fixture</b>' not in page.text
            assert '1 duplicate input rows' in page.text and lab["registry"].snapshot()["entries"] == []
            result = await confirm(client, token(page))
            assert result.status_code == 200 and "Standing batch policy recorded" in result.text
            assert "not verified creation" in result.text and len(lab["registry"].snapshot()["entries"]) == 4
    asyncio.run(scenario())
    unchanged_work(lab)


def test_committed_lost_reply_keeps_key_body_count_consent_and_replay_after_retirement(lab):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            review = token(page)
            lab["behavior"]["lost"] = True
            unknown = await confirm(client, review)
            assert unknown.status_code == 503 and 'outcome is unknown' in unknown.text
            assert token(unknown) == review and 'value="4"' in unknown.text and 'checked' in unknown.text
            lab["registry"].change(str(uuid4()), "RETIRE", PAIRS, 1, 0, canonical_managed_change("RETIRE", PAIRS, 1, 0)[2],
                                   "alice", "Alice", ("Operator",))
            repeated = await confirm(client, review)
            assert repeated.status_code == 200 and "Original-key replay" in repeated.text
            sent = [request for request in lab["calls"] if request.url.path.endswith("/maintain-batch")]
            assert sent[0].content == sent[1].content and sent[0].headers["Idempotency-Key"] == sent[1].headers["Idempotency-Key"]
            assert all(not entry["enabled"] for entry in lab["registry"].snapshot()["entries"])
    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["csrf", "role", "count", "consent", "extra", "other_subject", "other_cookie"])
def test_browser_confirmation_guards_do_not_submit(lab, mutation):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            fields = {}
            if mutation == "csrf": fields["csrf"] = "wrong"
            elif mutation == "count": fields["confirm_count"] = "3"
            elif mutation == "consent": fields["maintain_present"] = ""
            elif mutation == "extra": fields["targets"] = "other"
            elif mutation == "role": client.headers["Remote-Groups"] = "ftd-shun-viewers"
            elif mutation == "other_subject": client.headers["Remote-User"] = "bob"
            else:
                client.cookies.clear()
                client.cookies.set("ftd_shun_csrf", "different")
            response = await confirm(client, token(page), **fields)
            assert response.status_code in {403, 409, 422}
    asyncio.run(scenario())
    assert not any(request.url.path.endswith("/maintain-batch") for request in lab["calls"])


def test_default_off_local_bff_cannot_be_enabled_by_upstream_metadata(lab):
    async def scenario():
        app = web.create_app(replace(lab["settings"], managed_policy_admission_enabled=False))
        async with browser(lab, app=app) as client:
            page = await prepare(client)
            response = await confirm(client, token(page))
            assert response.status_code == 503 and 'not submitted' in response.text
    asyncio.run(scenario())
    assert not any(request.url.path.endswith("/maintain-batch") for request in lab["calls"])


def test_malformed_committed_receipt_keeps_original_review_and_explicit_retry(lab):
    async def scenario():
        async with browser(lab) as client:
            review = token(await prepare(client))
            lab["behavior"]["malformed"] = True
            response = await confirm(client, review)
            assert response.status_code == 503 and "outcome is unknown" in response.text
            assert token(response) == review and len(lab["registry"].snapshot()["entries"]) == 4
            lab["behavior"]["malformed"] = False
            response = await confirm(client, review)
            assert response.status_code == 200 and "Original-key replay" in response.text
            sent = [request for request in lab["calls"] if request.url.path.endswith("/maintain-batch")]
            assert sent[0].content == sent[1].content
            assert sent[0].headers["Idempotency-Key"] == sent[1].headers["Idempotency-Key"]
    asyncio.run(scenario())
    unchanged_work(lab)


@pytest.mark.parametrize("block", ["upstream_off", "uninitialized"])
def test_current_gate_or_frozen_uninitialized_review_cannot_submit(lab, block):
    async def scenario():
        async with browser(lab) as client:
            if block == "uninitialized":
                lab["behavior"][block] = True
            review = token(await prepare(client))
            lab["behavior"][block] = block == "upstream_off"
            response = await confirm(client, review)
            assert response.status_code == 503 and "not submitted" in response.text
    asyncio.run(scenario())
    assert not any(request.url.path.endswith("/maintain-batch") for request in lab["calls"])
    assert lab["registry"].snapshot()["entries"] == []


def test_stale_batch_revision_never_rebases_or_partially_saves(lab):
    async def scenario():
        async with browser(lab) as client:
            review = token(await prepare(client))
            with lab["store"]._connection() as db:
                db.execute("UPDATE protected_policy SET revision=revision+1")
            response = await confirm(client, review)
            assert response.status_code == 409 and token(response) == review
    asyncio.run(scenario())
    assert lab["registry"].snapshot()["entries"] == []
    unchanged_work(lab)


def test_frozen_pagination_retains_token_fields_and_never_reclassifies_or_submits(lab):
    async def scenario():
        async with browser(lab) as client:
            addresses = "\n".join(f"198.18.0.{i}" for i in range(1, 103))
            page = await prepare(client, text=addresses, device_ids=["1"])
            review = token(page)
            assert page.text.count("data-standing-target") == 100 and "Page 1 of 2" in page.text
            mark = len(lab["calls"])
            result = await client.post("/managed-shuns/bulk-review-page", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                "review": review, "page": "2", "confirm_count": "102", "maintain_present": "yes"})
            assert result.status_code == 200 and "Page 2 of 2" in result.text and result.text.count("data-standing-target") == 2
            assert token(result) == review and 'value="102"' in result.text and 'checked' in result.text
            assert [request.url.path for request in lab["calls"][mark:]] == ["/api/v1/status"]
    asyncio.run(scenario())
    unchanged_work(lab)


@pytest.mark.parametrize("text", ["198.51.100.250\n555.555.555.666", "198.51.100.250/24", "198.51.100.250:22",
    "198.51.100.250 to 198.51.100.251", "2001:db8::1", "# empty only"])
def test_invalid_paste_is_not_silently_filtered_and_input_is_retained(lab, text):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client, text=text)
            assert page.status_code == 422 and 'No policy was saved by preparation' in page.text
            assert text in page.text
    asyncio.run(scenario())
    assert not any(request.url.path.endswith("/maintain-batch") for request in lab["calls"])


def test_parser_deduplicates_and_rejects_oversized_scope_without_truncation():
    assert len(parse_standing_list("198.51.100.250\n198.51.100.250", [1, 2])["ips"]) == 1
    text = "\n".join(f"198.18.{i // 256}.{i % 256}" for i in range(501))
    with pytest.raises(ValueError, match="1000"):
        parse_standing_list(text, [1, 2])
    with pytest.raises(ValueError, match="1 MiB"):
        parse_standing_list("ї" * 524289, [1])


def test_pure_review_cache_and_receipt_reject_wrong_session_expiry_or_extra_fields(lab):
    parsed = parse_standing_list("198.51.100.250\n198.51.100.251", [1, 2])
    reviews = ManagedBatchReviews()
    frozen = reviews.prepare("alice", "cookie", lab["registry"].snapshot_if_present(),
        classify_targets(lab["store"], IPS, [1, 2]), parsed, [1, 2])
    assert len(frozen.targets) == 4 and not hasattr(frozen, "source_text")
    with pytest.raises(ReviewUnavailable): reviews.get(frozen.token, "bob", "cookie")
    with pytest.raises(ReviewUnavailable): reviews.get(frozen.token, "alice", "other")
    receipt = {"operation_id": frozen.request_id, "status": "policy_saved", "managed_revision": 1, "changed_targets": 4, "replayed": False}
    assert validate_batch_receipt(frozen, receipt) == receipt
    for changes in ({"extra": True}, {"changed_targets": True}, {"managed_revision": "1"}, {"replayed": 1}):
        with pytest.raises(ValueError): validate_batch_receipt(frozen, {**receipt, **changes})
    for _ in range(4):
        reviews.prepare("alice", "cookie", lab["registry"].snapshot_if_present(), classify_targets(lab["store"], IPS, [1, 2]), parsed, [1, 2])
    with pytest.raises(ReviewUnavailable, match="Too many"):
        reviews.prepare("alice", "cookie", lab["registry"].snapshot_if_present(), classify_targets(lab["store"], IPS, [1, 2]), parsed, [1, 2])


def test_maximum_thousand_pairs_commit_atomically(lab):
    pairs = [(1, IPv4Address(0xC6120000 + value)) for value in range(1000)]
    result = asyncio.run(api_post(lab, payload(lab, pairs=pairs)))
    assert result.status_code == 200 and result.json()["changed_targets"] == 1000
    assert len(lab["registry"].snapshot()["entries"]) == 1000
    unchanged_work(lab)
