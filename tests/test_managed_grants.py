"""Frozen standing consent and policy-only admission; synthetic ASGI/SQLite."""

import asyncio
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.import_preview import classify_targets
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_grant_review import ManagedGrantReviews
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_retirement_review import ManagedRetirementReviews
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.store import Store

IP = IPv4Address("198.51.100.251")
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    inventory = tmp_path / "synthetic-inventory.json"
    inventory.write_text(json.dumps([{"id": 1, "hostname": "synthetic-1", "management_ip": "192.0.2.1",
                                     "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"],
                                     "addition_profile": "fpr1010-766-single-vf-management-v1"}]))
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
                result = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(result.status_code, content=result.content, headers=result.headers)
        result = asyncio.run(send())
        if request.url.path == "/api/v1/managed-shuns/maintain":
            if behavior.pop("lost", False):
                raise httpx.ReadTimeout("Synthetic committed response lost")
            if behavior.pop("bad_receipt", False):
                return httpx.Response(200, json={**result.json(), "changed_targets": True})
            if behavior.get("status_after_error"):
                behavior["status_error"] = True
        if request.url.path == "/api/v1/status":
            if behavior.get("gate_off"):
                return httpx.Response(200, json={**result.json(), "managed_policy_admission_enabled": False})
            if behavior.get("status_error"):
                return httpx.Response(503, json={"detail": "Synthetic status error"})
        return result

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, registry, api, web.create_app(settings), calls, behavior, settings


def body(lab, **kwargs):
    managed = lab[1].snapshot()["revision"]
    protected = lab[2].state.synchronizer.policy.revision()
    return {"actor": ACTOR, "device_id": 1, "ip": str(IP), "managed_revision": managed,
            "protected_revision": protected, "maintain_present": True, "label": "Fixture", "reason": "Synthetic",
            "confirmation_digest": canonical_managed_change("MAINTAIN", [(1, IP)], managed, protected, "Fixture", "Synthetic")[2], **kwargs}


async def api_post(lab, payload=None, key=None, app=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app or lab[2]), base_url="http://internal") as client:
        return await client.post("/api/v1/managed-shuns/maintain", headers={"Idempotency-Key": key or str(uuid4())},
                                 json=payload or body(lab))


def browser(lab, *, subject="alice", group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[3]), base_url="https://synthetic.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


async def prepare(client, **overrides):
    await client.get("/managed-shuns")
    return await client.post("/managed-shuns/grant-review", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                             "device_id": "1", "ip": str(IP), "label": "<b>Fixture</b>",
                             "reason": "<script>not executable</script>", **overrides})


def token(page):
    return re.search(r'name="review" value="([^"]+)"', page.text)[1]


async def confirm(client, review, **overrides):
    return await client.post("/managed-shuns/grant-confirm", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                             "review": review, "confirm_ip": str(IP), "maintain_present": "yes", **overrides})


def unchanged_queue(lab):
    with lab[0]._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_requests").fetchone()
        assert not db.execute("SELECT 1 FROM operation_jobs").fetchone()
        assert not db.execute("SELECT 1 FROM managed_restoration_attempts").fetchone()
        assert not db.execute("SELECT 1 FROM manual_import_batches").fetchone()
        assert db.execute("SELECT restoration_suspended FROM managed_shun_registry").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_api_saves_standing_authority_only_and_old_key_never_reenables_retired_policy(lab):
    payload, key = body(lab), str(uuid4())
    result = asyncio.run(api_post(lab, payload, key))
    assert result.status_code == 200 and result.json()["changed_targets"] == 1
    entry = lab[1].snapshot()["entries"][0]
    assert entry["enabled"] and entry["generation"] == 1 and entry["actor_subject"] == "alice"
    revision = lab[1].snapshot()["revision"]
    lab[1].change(str(uuid4()), "RETIRE", [(1, IP)], revision, 0,
                  canonical_managed_change("RETIRE", [(1, IP)], revision, 0)[2], "alice", "Alice", ("Operator",))
    events = lab[0].list_events()
    repeated = asyncio.run(api_post(lab, payload, key))
    assert repeated.status_code == 200 and repeated.json()["replayed"]
    assert not lab[1].snapshot()["entries"][0]["enabled"] and lab[0].list_events() == events
    fresh = asyncio.run(api_post(lab))
    assert fresh.status_code == 200 and lab[1].snapshot()["entries"][0]["generation"] == 2
    unchanged_queue(lab)


def test_bff_freezes_scope_consent_current_actor_and_policy_receipt_without_work(lab):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            assert page.status_code == 200 and "Persistent policy, not a one-time import" in page.text
            assert "&lt;b&gt;Fixture&lt;/b&gt;" in page.text and "<script>not executable</script>" not in page.text
            assert lab[1].snapshot()["entries"] == []
            saved = await confirm(client, token(page))
            assert saved.status_code == 200 and "Standing policy recorded" in saved.text
            assert "not verified creation" in saved.text
            sent = [r for r in lab[4] if r.url.path.endswith("/maintain")]
            assert len(sent) == 1
            assert json.loads(sent[0].content)["actor"] == {"subject": "alice", "display_name": "alice", "roles": ["Operator"]}
            assert not any("refresh-hint" in r.url.path for r in lab[4])
            assert not lab[2].state.synchronizer._activity.is_set()
    asyncio.run(scenario())
    unchanged_queue(lab)


@pytest.mark.parametrize("failure", ["lost", "bad_receipt"])
def test_unknown_reply_preserves_original_review_body_key_and_acknowledgement(lab, failure):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            review = token(page)
            lab[5][failure] = True
            uncertain = await confirm(client, review)
            assert uncertain.status_code == 503 and "outcome is unknown" in uncertain.text
            assert token(uncertain) == review and 'value="yes" checked' in uncertain.text
            events = lab[0].list_events()
            result = await confirm(client, review)
            assert result.status_code == 200 and "Original-key replay" in result.text
            assert lab[0].list_events() == events
            sent = [r for r in lab[4] if r.url.path.endswith("/maintain")]
            assert sent[0].content == sent[1].content
            assert sent[0].headers["Idempotency-Key"] == sent[1].headers["Idempotency-Key"]
    asyncio.run(scenario())
    unchanged_queue(lab)


@pytest.mark.parametrize("field,value", [("maintain_present", False), ("maintain_present", 1),
                                         ("managed_revision", True), ("protected_revision", "1"),
                                         ("device_id", True), ("mode", "one_time"), ("action", "RETIRE"),
                                         ("targets", []), ("confirmation_digest", "0"*64), ("ip", 0xC63364FB)])
def test_api_rejects_ambiguous_authority_without_writes(lab, field, value):
    before = lab[0].list_events()
    response = asyncio.run(api_post(lab, body(lab, **{field: value})))
    assert response.status_code == 422
    assert lab[1].snapshot()["entries"] == [] and lab[0].list_events() == before
    unchanged_queue(lab)


@pytest.mark.parametrize("group", ["", "ftd-shun-viewers"])
def test_bff_and_api_recheck_current_roles(lab, group):
    async def scenario():
        async with browser(lab, group=group) as client:
            assert (await prepare(client)).status_code == 403
        async with browser(lab) as client:
            page = await prepare(client)
            client.headers["Remote-Groups"] = group
            assert (await confirm(client, token(page))).status_code == 403
        assert (await api_post(lab, body(lab, actor={**ACTOR, "roles": ["Viewer"]}))).status_code == 403
    asyncio.run(scenario())
    assert lab[1].snapshot()["entries"] == []


@pytest.mark.parametrize("override", [{"maintain_present": ""}, {"confirm_ip": "198.51.100.250"},
                                      {"actor": "spoofed"}, {"device_id": "2"}, {"csrf": "wrong"}])
def test_bff_requires_exact_consent_csrf_and_no_injected_scope(lab, override):
    async def scenario():
        async with browser(lab) as client:
            review = token(await prepare(client))
            assert (await confirm(client, review, **override)).status_code in (403, 422)
    asyncio.run(scenario())
    assert not any(r.url.path.endswith("/maintain") for r in lab[4])


def test_uninitialized_preview_never_becomes_confirmable_after_migration(lab):
    with lab[0]._connection() as db:
        for table in ("managed_restoration_attempts", "managed_shun_targets", "managed_shun_requests", "managed_shun_registry"):
            db.execute(f"DROP TABLE {table}")  # Empty disposable fixture only.
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            assert page.status_code == 200 and "Policy was not initialized" in page.text
            lab[1].initialize()
            lab[2].state.synchronizer.managed_discovery.source.initialize()
            assert (await confirm(client, token(page))).status_code == 503
    asyncio.run(scenario())
    assert lab[1].snapshot()["entries"] == []
    assert not any(r.url.path.endswith("/maintain") for r in lab[4])


def test_gate_off_is_authoritative_and_missing_optional_state_never_initializes(lab):
    disabled = create_app(replace(lab[6], managed_policy_admission_enabled=False), lab[0], DisabledAgentClient())
    assert asyncio.run(api_post(lab, app=disabled)).status_code == 503
    lab[5]["gate_off"] = True
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client)
            assert (await confirm(client, token(page))).status_code == 503
    asyncio.run(scenario())
    assert not any(r.url.path.endswith("/maintain") for r in lab[4])
    with lab[0]._connection() as db:
        db.execute("DROP TABLE managed_restoration_attempts")
    assert asyncio.run(api_post(lab)).status_code == 503
    with lab[0]._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_restoration_attempts'").fetchone()


def test_disabling_admission_after_lost_reply_never_claims_old_policy_was_unsaved(lab):
    async def scenario():
        async with browser(lab) as client:
            review = token(await prepare(client))
            lab[5]["lost"] = True
            assert (await confirm(client, review)).status_code == 503
            assert lab[1].snapshot()["entries"][0]["enabled"]
            lab[5]["gate_off"] = True
            held = await confirm(client, review)
            assert held.status_code == 503 and "Earlier attempts may have saved policy" in held.text
            assert token(held) == review and len([r for r in lab[4] if r.url.path.endswith("/maintain")]) == 1
            lab[5]["gate_off"] = False
            assert "Original-key replay" in (await confirm(client, review)).text
    asyncio.run(scenario())
    unchanged_queue(lab)


@pytest.mark.parametrize("blocker", ["profile", "protected", "observed", "paused", "disabled", "queued_add", "queued_remove", "stale"])
def test_atomic_policy_checks_reject_changed_or_conflicting_state(lab, blocker):
    payload = body(lab)
    sync = lab[2].state.synchronizer
    if blocker == "profile":
        lab[6].device_inventory_path.write_text(lab[6].device_inventory_path.read_text().replace('"addition_profile": "fpr1010-766-single-vf-management-v1"', '"addition_profile": null'))
        app = create_app(lab[6], lab[0], DisabledAgentClient())
    else:
        app = lab[2]
    if blocker == "protected":
        sync.policy.change("add", IP, sync.policy.revision(), "protector", "Protector", ("Operator",))
    if blocker == "observed":
        lab[0].record_observed_shun(1, IP, "management")
    if blocker == "paused":
        with lab[0]._connection() as db:
            db.execute("UPDATE operation_executor SET mutations_suspended=1")
    if blocker == "disabled":
        with lab[0]._connection() as db:
            db.execute("UPDATE devices SET enabled=0")
    if blocker == "queued_add":
        sync.queue.enqueue(str(uuid4()), [(1, IP)], "other", "Other", ("Operator",), source="manual_import",
                           scope="import", policy_revision=payload["protected_revision"],
                           confirmation_digest=canonical_import([(1, IP)], payload["protected_revision"])[2])
    if blocker == "queued_remove":
        sync.queue.enqueue(str(uuid4()), [(1, IP)], "other", "Other", ("Operator",))
    if blocker == "stale":
        with lab[0]._connection() as db:
            db.execute("UPDATE managed_shun_registry SET revision=revision+1")
    before = lab[0].list_events()
    response = asyncio.run(api_post(lab, payload, app=app))
    assert response.status_code == 409 and lab[1].snapshot()["entries"] == []
    assert lab[0].list_events() == before


def test_late_audit_failure_rolls_back_grant_and_suppresses_success_log(lab, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic audit failure")
    monkeypatch.setattr(lab[0], "_insert_event", fail)
    assert asyncio.run(api_post(lab)).status_code == 503
    assert lab[1].snapshot()["revision"] == 0 and lab[1].snapshot()["entries"] == []
    assert "managed_shun.policy.changed" not in capsys.readouterr().out
    unchanged_queue(lab)


def test_grant_cache_is_session_purpose_bound_immutable_and_expires(lab, monkeypatch):
    cache = ManagedGrantReviews(ttl=1)
    policy = lab[1].snapshot_if_present()
    classified = classify_targets(lab[0], [IP], [1])
    review = cache.prepare("alice", "cookie", policy, classified, 1, IP)
    for subject, cookie in (("bob", "cookie"), ("alice", "different")):
        with pytest.raises(ReviewUnavailable):
            cache.get(review.token, subject, cookie)
    with pytest.raises(AttributeError):
        review.ip = IPv4Address("198.51.100.250")
    monkeypatch.setattr("ftd_shun_manager.managed_review.time.monotonic", lambda: review.expires+1)
    with pytest.raises(ReviewUnavailable):
        cache.get(review.token, "alice", "cookie")


def test_grant_cache_bounds_do_not_evict_original_or_share_retirement_tokens(lab):
    cache = ManagedGrantReviews()
    policy, classified = lab[1].snapshot_if_present(), classify_targets(lab[0], [IP], [1])
    first = cache.prepare("alice", "cookie", policy, classified, 1, IP)
    for _ in range(4):
        cache.prepare("alice", "cookie", policy, classified, 1, IP)
    with pytest.raises(ReviewUnavailable, match="Too many"):
        cache.prepare("alice", "cookie", policy, classified, 1, IP)
    for index in range(251):
        cache.prepare(f"other-{index}", "cookie", policy, classified, 1, IP)
    with pytest.raises(ReviewUnavailable, match="Too many"):
        cache.prepare("one-more", "cookie", policy, classified, 1, IP)
    assert cache.get(first.token, "alice", "cookie") is first
    assert asyncio.run(api_post(lab)).status_code == 200
    retirement = ManagedRetirementReviews()
    stopped = retirement.prepare("alice", "cookie", lab[1].snapshot_if_present(), 1, IP)
    with pytest.raises(ReviewUnavailable):
        cache.get(stopped.token, "alice", "cookie")
    with pytest.raises(ReviewUnavailable):
        retirement.get(first.token, "alice", "cookie")


@pytest.mark.parametrize("outcome", ["FAILED", "UNVERIFIED"])
def test_new_grant_cannot_rearm_retained_failure_after_retirement(lab, monkeypatch, outcome):
    assert asyncio.run(api_post(lab)).status_code == 200
    sync = lab[2].state.synchronizer
    clock = datetime.now(UTC)+timedelta(seconds=1)
    monkeypatch.setattr(sync.queue, "_now", lambda: clock)
    with lab[0]._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")  # Disposable fixture only.
    assert sync.queue.claim_cycle("synthetic-worker", 135)
    sync.managed_discovery.source.admit_absence(CompleteSnapshot(str(uuid4()), 1, clock, clock, frozenset()),
                                               IP, "synthetic-worker", enabled=True)
    job = sync.queue.claim_addition(1, "synthetic-worker", sync.queue.cutoff(), execution_enabled=True,
                                    managed_restoration_enabled=True)
    sync.queue.finish_addition(job["id"], "synthetic-worker", outcome)
    revision = lab[1].snapshot()["revision"]
    lab[1].change(str(uuid4()), "RETIRE", [(1, IP)], revision, 0,
                  canonical_managed_change("RETIRE", [(1, IP)], revision, 0)[2], "alice", "Alice", ("Operator",))
    assert asyncio.run(api_post(lab)).status_code == 409
    assert not lab[1].snapshot()["entries"][0]["enabled"]


def test_explicit_canonical_key_and_actor_binding_are_required(lab):
    assert asyncio.run(api_post(lab, key="NOT-A-UUID")).status_code == 422
    payload, key = body(lab), str(uuid4())
    assert asyncio.run(api_post(lab, payload, key)).status_code == 200
    assert asyncio.run(api_post(lab, {**payload, "actor": {**ACTOR, "subject": "bob"}}, key)).status_code == 409


def test_concurrent_same_key_grant_is_one_policy_authority(lab):
    payload, key = body(lab), str(uuid4())
    def grant(_):
        return lab[1].grant_reviewed(key, 1, IP, payload["managed_revision"], payload["protected_revision"],
                                    payload["confirmation_digest"], "alice", "Alice", ("Operator",),
                                    addition_device_ids=frozenset({1}), label="Fixture", reason="Synthetic")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(grant, range(4)))
    assert sum(not r["replayed"] for r in results) == 1
    with pytest.raises(ManagedConflict):
        lab[1].grant_reviewed(str(uuid4()), 1, IP, 1, payload["protected_revision"],
                canonical_managed_change("MAINTAIN", [(1, IP)], 1, payload["protected_revision"])[2],
                "alice", "Alice", ("Operator",), addition_device_ids=frozenset({1}))
    unchanged_queue(lab)


@pytest.mark.parametrize("value", ["yes", "1", "TRUE", "", "False"])
def test_standing_admission_configuration_is_strict(monkeypatch, value):
    monkeypatch.setenv("FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED", value)
    with pytest.raises(ValueError, match="POLICY_ADMISSION"):
        Settings.from_environment()


def test_standing_admission_does_not_enable_execution(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED", raising=False)
    settings = Settings.from_environment()
    assert not settings.managed_policy_admission_enabled
    with pytest.raises(ValueError, match="socket"):
        replace(settings, agent_mode="mock", managed_policy_admission_enabled=True)
    enabled = replace(settings, agent_mode="socket", managed_policy_admission_enabled=True)
    assert not enabled.import_execution_enabled and not enabled.managed_restoration_enabled
