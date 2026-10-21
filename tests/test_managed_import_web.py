"""Real BFF/private API integration on temporary SQLite; no device calls."""

import asyncio
import json
import re
import time
from dataclasses import replace
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_cancellations import ImportCancellations
from ftd_shun_manager.managed_import_web import operation_key
from ftd_shun_manager.managed_imports import ManagedImports
from ftd_shun_manager.managed_restoration import ManagedRestorations
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    inventory = tmp_path / "synthetic.json"
    inventory.write_text(json.dumps([{"id": device, "hostname": f"synthetic-{device}", "management_ip": f"192.0.2.{device}",
        "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"],
        "addition_profile": "fpr1010-766-single-vf-management-v1"} for device in (1, 2)]))
    store = Store(tmp_path / "synthetic.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=inventory,
                       development_auth=False, agent_mode="socket", managed_policy_admission_enabled=True)
    api = create_app(settings, store, DisabledAgentClient())
    ManagedShuns(store).initialize()
    ManagedRestorations(store, OperationQueue(store)).initialize()
    imports = ManagedImports(store)
    imports.preparations.initialize()
    imports.initialize()
    ImportCancellations(store).initialize()
    calls, behavior = [], {}

    def internal(request):
        calls.append(request)

        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
                return await client.request(request.method, request.url.path, content=request.content, headers=request.headers)

        response = asyncio.run(call())
        if request.url.path == "/api/v1/status" and behavior.get("api_gate_off"):
            return httpx.Response(200, json={**response.json(), "managed_policy_admission_enabled": False})
        if request.url.path.endswith(("/confirm", "/cancel-confirmed")):
            if behavior.pop("lost", False):
                raise httpx.ReadTimeout("Synthetic reply lost after commit")
            if behavior.get("malformed"):
                return httpx.Response(200, json={**response.json(), "device_work_admitted": True})
            if behavior.pop("lose_followup", False):
                behavior["reads_off"] = True
        if behavior.get("reads_off") and request.url.path.endswith(("/preparation", "/receipt")):
            raise httpx.ConnectError("Synthetic read outage")
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://synthetic"))
    return {"store": store, "imports": imports, "api": api, "web": web.create_app(settings), "settings": settings,
            "calls": calls, "behavior": behavior}


def browser(lab, *, subject="alice", group="ftd-shun-operators", app=None):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app or lab["web"]), base_url="https://synthetic.test",
        headers={"Remote-User": subject, "Remote-Name": "Alice", "Remote-Groups": group})


def field(page, name):
    return re.search(r'name="' + name + r'"[^>]*value="([^"]*)"', page.text)[1]


async def prepare(client, *, text="198.51.100.1", devices=None):
    await client.get("/managed-imports")
    return await client.post("/managed-imports/prepare", data={"csrf": client.cookies.get("ftd_shun_csrf"),
        "text": text, "device_ids": devices or ["1"], "label": "<b>Fixture</b>", "reason": "Synthetic only"})


async def review(client, **changes):
    page = await prepare(client, **changes)
    assert page.status_code == 200, page.text
    return await client.post("/managed-imports/review", data={"csrf": client.cookies.get("ftd_shun_csrf"),
        "preparation_id": field(page, "preparation_id")})


def submit_fields(client, page, **changes):
    values = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": field(page, "review"), "kind": field(page, "kind"),
              "confirm_count": field(page, "confirm_count"), "maintain_present": "yes"}
    values["confirm_count"] = re.search(r'Type (\d+) to confirm', page.text)[1]
    values.update(changes)
    return values


def mutations(lab):
    return [request for request in lab["calls"] if request.url.path.endswith(("/confirm", "/cancel-confirmed"))]


def test_full_adoption_exclusions_confirmation_receipt_and_cancellation(lab):
    policy = ProtectedPolicy(lab["store"])
    policy.change("add", IPv4Address("198.51.100.3"), policy.revision(), "fixture", "Fixture", ())
    lab["store"].record_observed_shun(1, IPv4Address("198.51.100.2"), "management")

    async def scenario():
        async with browser(lab) as client:
            page = await review(client, text="198.51.100.1\n198.51.100.2\n198.51.100.3\ninvalid\n198.51.100.1")
            assert page.status_code == 200 and "EXCLUDED_PROTECTED: 1" in page.text
            assert "PROPOSE_ADOPT: 1" in page.text and "Invalid: 1" in page.text
            assert "&lt;b&gt;Fixture&lt;/b&gt;" in page.text and "<b>Fixture</b>" not in page.text
            assert not mutations(lab)
            values = submit_fields(client, page)
            result = await client.post("/managed-imports/submit", data=values)
            assert result.status_code == 200 and "Standing policy recorded" in result.text
            operation_id = mutations(lab)[0].headers["Idempotency-Key"]
            report = await client.post("/managed-imports/report", data={"csrf": values["csrf"], "operation_id": operation_id})
            assert report.status_code == 200 and "Historical import receipt" in report.text
            cancellation = await client.post("/managed-imports/cancellation-review", data={"csrf": values["csrf"], "operation_id": operation_id})
            assert cancellation.status_code == 200 and "This does not unblock already added addresses" in cancellation.text
            cancelled = await client.post("/managed-imports/submit", data=submit_fields(client, cancellation))
            assert cancelled.status_code == 200 and "Cancellation decision recorded" in cancelled.text
            current = await client.post("/managed-imports/cancellation", data={"csrf": values["csrf"], "operation_id": operation_id})
            assert current.status_code == 200 and "RETAINED_ADOPTED: 1" in current.text and "STOPPED_UNSENT: 1" in current.text
            assert "no-store" in current.headers["cache-control"]

    asyncio.run(scenario())
    with lab["store"]._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs").fetchall()
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 1
        assert db.execute("SELECT active FROM shun_state").fetchone()[0] == 1
    assert not any("refresh-hint" in request.url.path for request in lab["calls"])


@pytest.mark.parametrize("kind", ["confirm", "cancel"])
def test_lost_reply_explicit_retry_keeps_body_and_original_key(lab, kind):
    async def scenario():
        async with browser(lab) as client:
            page = await review(client)
            if kind == "cancel":
                assert (await client.post("/managed-imports/submit", data=submit_fields(client, page))).status_code == 200
                operation_id = mutations(lab)[0].headers["Idempotency-Key"]
                page = await client.post("/managed-imports/cancellation-review", data={"csrf": client.cookies.get("ftd_shun_csrf"), "operation_id": operation_id})
            values = submit_fields(client, page)
            lab["behavior"]["lost"] = True
            failed = await client.post("/managed-imports/submit", data=values)
            assert failed.status_code == 503 and "Outcome is unconfirmed" in failed.text
            assert field(failed, "review") == values["review"] and field(failed, "confirm_count") == values["confirm_count"]
            count = len(mutations(lab))
            assert count == (1 if kind == "confirm" else 2)  # No automatic replay.
            result = await client.post("/managed-imports/submit", data=values)
            assert result.status_code == 200 and "Original request replayed" in result.text
            assert mutations(lab)[-1].content == mutations(lab)[-2].content
            assert mutations(lab)[-1].headers["Idempotency-Key"] == mutations(lab)[-2].headers["Idempotency-Key"]

    asyncio.run(scenario())


def test_restart_rebuilds_same_confirmation_key_not_a_new_policy(lab):
    async def scenario():
        async with browser(lab) as client:
            prepared = await prepare(client)
            preparation_id = field(prepared, "preparation_id")
            page = await client.post("/managed-imports/review", data={"csrf": client.cookies.get("ftd_shun_csrf"), "preparation_id": preparation_id})
            restarted = web.create_app(lab["settings"])
            async with browser(lab, app=restarted) as new_client:
                await new_client.get("/managed-imports")
                expired = await new_client.post("/managed-imports/submit", data=submit_fields(new_client, page))
                assert expired.status_code == 409
                new_page = await new_client.post("/managed-imports/review", data={"csrf": new_client.cookies.get("ftd_shun_csrf"), "preparation_id": preparation_id})
                assert (await new_client.post("/managed-imports/submit", data=submit_fields(new_client, new_page))).status_code == 200
                assert mutations(lab)[0].headers["Idempotency-Key"] == operation_key(preparation_id)
            # Original browser's same key returns receipt, not another grant.
            assert (await client.post("/managed-imports/submit", data=submit_fields(client, page))).status_code == 200
            assert mutations(lab)[-1].headers["Idempotency-Key"] == operation_key(preparation_id)

    asyncio.run(scenario())


def test_frozen_pagination_preserves_token_input_and_consent_without_mutations(lab):
    async def scenario():
        async with browser(lab) as client:
            page = await review(client, text="\n".join(str(IPv4Address(int(IPv4Address("198.51.100.0")) + index)) for index in range(102)))
            values = submit_fields(client, page, confirm_count="draft-count")
            second = await client.post("/managed-imports/review-page", data={**values, "page": "2"})
            assert second.status_code == 200 and "Page 2 of 2" in second.text
            assert field(second, "review") == values["review"] and field(second, "confirm_count") == "draft-count"
            assert 'value="yes" checked' in second.text
            assert second.text.count('<tr><td>synthetic-1') == 2
            assert not mutations(lab)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["no_csrf", "wrong_cookie", "other_subject", "viewer", "expired", "wrong_kind", "count", "consent", "target", "duplicate"])
def test_invalid_sensitive_submission_never_calls_admission(lab, monkeypatch, change):
    async def scenario():
        async with browser(lab) as client:
            page = await review(client)
            values = submit_fields(client, page)
            if change == "no_csrf":
                values.pop("csrf")
            elif change == "wrong_cookie":
                client.cookies.clear()
                client.cookies.set("ftd_shun_csrf", "other")
                values["csrf"] = "other"
            elif change == "other_subject":
                client.headers["Remote-User"] = "other"
            elif change == "viewer":
                client.headers["Remote-Groups"] = "ftd-shun-viewers"
            elif change == "expired":
                current = time.monotonic()
                monkeypatch.setattr("ftd_shun_manager.managed_review.time.monotonic", lambda: current + 601)
            elif change == "wrong_kind":
                values["kind"] = "cancel"
            elif change == "count":
                values["confirm_count"] = "999"
            elif change == "consent":
                values.pop("maintain_present")
            elif change == "target":
                values["device_ids"] = "2"
            elif change == "duplicate":
                values["review"] = [values["review"], values["review"]]
            failed = await client.post("/managed-imports/submit", data=values)
            assert failed.status_code in {403, 409, 422}
            assert not mutations(lab)

    asyncio.run(scenario())


@pytest.mark.parametrize("which", ["bff", "api"])
def test_confirmation_requires_both_gates_but_cancellation_does_not(lab, which):
    async def scenario():
        async with browser(lab) as client:
            page = await review(client)
            assert (await client.post("/managed-imports/submit", data=submit_fields(client, page))).status_code == 200
            operation_id = mutations(lab)[0].headers["Idempotency-Key"]
            if which == "bff":
                app = web.create_app(replace(lab["settings"], managed_policy_admission_enabled=False))
            else:
                app = lab["web"]
                lab["behavior"]["api_gate_off"] = True
            async with browser(lab, app=app) as disabled:
                await disabled.get("/managed-imports")
                another = await review(disabled, text="198.51.100.2")
                assert another.status_code == 200
                count = len(mutations(lab))
                refused = await disabled.post("/managed-imports/submit", data=submit_fields(disabled, another))
                assert refused.status_code == 503 and len(mutations(lab)) == count
                cancel = await disabled.post("/managed-imports/cancellation-review", data={"csrf": disabled.cookies.get("ftd_shun_csrf"), "operation_id": operation_id})
                assert (await disabled.post("/managed-imports/submit", data=submit_fields(disabled, cancel))).status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("behavior", ["malformed", "lose_followup"])
def test_unconfirmed_or_missing_followup_keeps_review_and_explicit_recovery(lab, behavior):
    async def scenario():
        async with browser(lab) as client:
            page = await review(client)
            values = submit_fields(client, page)
            lab["behavior"][behavior] = True
            result = await client.post("/managed-imports/submit", data=values)
            assert result.status_code == 503
            assert field(result, "review") == values["review"] if behavior == "malformed" else "Standing policy recorded" in result.text
            assert len(mutations(lab)) == 1

    asyncio.run(scenario())


def test_oversize_accepted_scope_reported_but_not_truncated_or_reviewed(lab):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client, text="\n".join(str(IPv4Address(int(IPv4Address("198.18.0.0")) + index)) for index in range(1001)))
            assert page.status_code == 200 and "PROPOSE_ADD: 1001" in page.text
            refused = await client.post("/managed-imports/review", data={"csrf": client.cookies.get("ftd_shun_csrf"), "preparation_id": field(page, "preparation_id")})
            assert refused.status_code == 409 and not mutations(lab)

    asyncio.run(scenario())


def test_no_anonymous_or_viewer_access_before_internal_api_calls(lab):
    async def scenario():
        async with browser(lab, group="ftd-shun-viewers") as client:
            count = len(lab["calls"])
            assert (await client.get("/managed-imports")).status_code == 403
            assert len(lab["calls"]) == count
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=lab["web"]), base_url="https://synthetic.test") as client:
            assert (await client.get("/managed-imports")).status_code == 401

    asyncio.run(scenario())


def test_base_only_startup_and_home_never_initialize_optional_import_schemas(tmp_path, monkeypatch):
    settings = replace(Settings.from_environment(), database_path=tmp_path / "base.db", device_inventory_path=None,
                       development_auth=False, agent_mode="disabled", managed_policy_admission_enabled=False)
    store = Store(settings.database_path)
    api = create_app(settings, store, DisabledAgentClient())

    def internal(request):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
                response = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        return asyncio.run(call())

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://synthetic"))
    app = web.create_app(settings)

    async def scenario():
        async with browser({"web": app}) as client:
            home = await client.get("/managed-imports")
            assert home.status_code == 200 and "storage is not initialized" in home.text
            assert "Confirmation journal is not initialized" in home.text
            assert 'disabled>Prepare managed import' in home.text

    asyncio.run(scenario())
    with store._connection() as db:
        assert not db.execute("""SELECT 1 FROM sqlite_master WHERE name GLOB 'import_preparation_*'
            OR name GLOB 'confirmed_import_*' OR name GLOB 'import_cancellation_*' OR name GLOB 'managed_shun_*'""").fetchone()


def test_retained_receipts_read_after_preparation_pruning_and_no_repeat_cancellation(lab):
    from datetime import UTC, datetime, timedelta

    async def scenario():
        async with browser(lab) as client:
            page = await review(client)
            saved = await client.post("/managed-imports/submit", data=submit_fields(client, page))
            assert saved.status_code == 200
            operation_id = mutations(lab)[0].headers["Idempotency-Key"]
            lab["imports"].preparations.clock = lambda: datetime.now(UTC) + timedelta(minutes=11)
            assert lab["imports"].preparations.prune_expired() == 1
            home = await client.get("/managed-imports")
            assert operation_id in home.text
            csrf = client.cookies.get("ftd_shun_csrf")
            report = await client.post("/managed-imports/report", data={"csrf": csrf, "operation_id": operation_id})
            assert report.status_code == 200 and "Historical import receipt" in report.text
            cancellation = await client.post("/managed-imports/cancellation-review", data={"csrf": csrf, "operation_id": operation_id})
            assert (await client.post("/managed-imports/submit", data=submit_fields(client, cancellation))).status_code == 200
            count = len(mutations(lab))
            repeated = await client.post("/managed-imports/cancellation-review", data={"csrf": csrf, "operation_id": operation_id})
            assert repeated.status_code == 200 and "All captured outcomes settled" in repeated.text
            assert len(mutations(lab)) == count

    asyncio.run(scenario())


@pytest.mark.parametrize("path,key", [("preparation", "preparation_id"), ("report", "operation_id"), ("cancellation", "operation_id")])
def test_reference_report_posts_require_csrf_and_do_not_accept_actor_or_targets(lab, path, key):
    async def scenario():
        async with browser(lab) as client:
            await client.get("/managed-imports")
            count = len(lab["calls"])
            bad = await client.post("/managed-imports/" + path, data={key: "ignored"})
            assert bad.status_code == 403
            bad = await client.post("/managed-imports/" + path, data={"csrf": client.cookies.get("ftd_shun_csrf"), key: "ignored", "actor": "other"})
            assert bad.status_code == 422 and len(lab["calls"]) == count

    asyncio.run(scenario())
