"""Optional fleet observations and waiting-only revocation; synthetic data only."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_fleet_removals import ManagedFleetRemovals
from ftd_shun_manager.managed_fleet_state import ManagedFleetState
from ftd_shun_manager.managed_intent import canonical_managed_fleet_removal
from ftd_shun_manager.managed_scope import ManagedRemovalScopes
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       agent_mode="disabled", development_auth=False)
    api = create_app(settings, store)
    for device in range(1, 4):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
        store.record_observed_shun(device, IP, "outside")
    calls, behavior = [], {}

    def internal(request):
        calls.append(request)

        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                reply = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)
        response = asyncio.run(send())
        if request.method == "POST" and behavior.pop("lost", False):
            raise httpx.ReadTimeout("Synthetic committed response lost")
        if request.method == "POST" and behavior.pop("malformed", False):
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "GET" and behavior.get("fleet_error") and request.url.path.endswith("managed-fleet-removals"):
            return httpx.Response(503, json={"detail": "Synthetic optional read failure"})
        return response

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, api, web.create_app(settings), calls, behavior


def browser(lab, subject="alice", group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[2]), base_url="https://lab.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


def root(lab, *, waiting=True, subject="alice", ip=IP):
    store, api, *_ = lab
    sync = api.state.synchronizer
    registry = ManagedShuns(store)
    registry.initialize()
    fleet = ManagedFleetRemovals(registry, sync.queue)
    fleet.initialize()
    predecessor = None
    if waiting:
        revision = sync.policy.revision()
        sync.queue.enqueue(str(uuid4()), [(1, ip)], "adder", "Adder", ("Operator",), source="manual_import",
                           scope="import", policy_revision=revision, confirmation_digest=canonical_import([(1, ip)], revision)[2])
        assert sync.queue.claim_cycle("synthetic-worker", 135)
        predecessor = sync.queue.claim_addition(1, "synthetic-worker", sync.queue.cutoff(), execution_enabled=True)
    reviewed = ManagedRemovalScopes(store).snapshot(ip)
    scope = {key: value for key, value in reviewed.items() if key not in {"scope_digest", "execution_available", "read_only"}}
    key = str(uuid4())
    fleet.admit(key, reviewed, canonical_managed_fleet_removal(scope, 900, "Fixture only", ordered_wait=waiting)[1],
                subject, "<script>Fixture</script>", ("Operator",), reason="Fixture only", ordered_wait=waiting)
    return key, predecessor


def snapshot(lab):
    return ManagedFleetState(lab[0]).snapshot_if_present()


def fingerprint(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def test_reads_and_absent_cancellation_do_not_initialize_schemas_or_work(lab):
    before = fingerprint(lab[0])

    async def scenario():
        async with browser(lab) as client:
            page = await client.get("/managed-shuns")
            assert page.status_code == 200 and "No fleet cleanup ledger" in page.text
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[1]), base_url="http://internal") as client:
            state = await client.get("/api/v1/managed-fleet-removals")
            assert state.status_code == 200 and state.json()["initialized"] is False
            assert state.headers["cache-control"] == "no-store"
            assert (await client.post("/api/v1/managed-fleet-removals", json={})).status_code == 405
            assert (await client.post(f"/api/v1/managed-fleet-removals/{uuid4()}/cancel", json=ACTOR)).status_code == 503
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before


def test_waiting_view_is_bounded_escaped_and_separate_from_queue_success(lab):
    key, job = root(lab)
    before = fingerprint(lab[0])
    view = snapshot(lab)
    assert view["counts"] == {"active": 1} and view["read_only"] and not view["admission_enabled"]
    item = view["items"][0]
    assert item["id"] == key and item["target_count"] == 3 and item["predecessor_counts"] == {"RUNNING": 1}
    assert item["outcomes"] == {} and item["settled_targets"] == 0 and not item["verified"]

    async def scenario():
        async with browser(lab) as client:
            page = await client.get("/managed-shuns")
            assert "Waiting for all captured ADDs" in page.text and "Cancel waiting fleet cleanup only" in page.text
            assert "&lt;script&gt;Fixture&lt;/script&gt;" in page.text and "<script>Fixture</script>" not in page.text
        async with browser(lab, "other") as client:
            assert "Cancel waiting fleet cleanup only" not in (await client.get("/managed-shuns")).text
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before and job["action"] == "ADD"
    assert all(call.method == "GET" for call in lab[3])


@pytest.mark.parametrize("subject,group", [("alice", "ftd-shun-operators"), ("admin", "ftd-shun-administrators")])
def test_current_owner_or_admin_cancels_only_wait_with_strict_csrf_and_no_hint(lab, subject, group):
    key, job = root(lab)
    sync = lab[1].state.synchronizer
    before_jobs = sync.queue.status()["counts"]

    async def scenario():
        async with browser(lab, "other") as other:
            await other.get("/managed-shuns")
            assert (await other.post(f"/managed-shuns/fleet-waits/{key}/cancel", data={"csrf": other.cookies.get("ftd_shun_csrf")})).status_code == 403
        async with browser(lab, subject, group) as client:
            await client.get("/managed-shuns")
            fields = {"csrf": client.cookies.get("ftd_shun_csrf")}
            path = f"/managed-shuns/fleet-waits/{key}/cancel"
            assert (await client.post(path, data={"csrf": "wrong"})).status_code == 403
            assert (await client.post(path, files={"csrf": (None, fields["csrf"])})).status_code == 415
            assert (await client.post(path, data={**fields, "roles": "Administrator"})).status_code == 422
            response = await client.post(path, data=fields, headers={"Accept": "application/json"})
            assert response.status_code == 200
            events = len(lab[0].list_events())
            assert (await client.post(path, data=fields)).status_code == 303
            assert len(lab[0].list_events()) == events
            assert "Cancel waiting fleet cleanup only" not in (await client.get("/managed-shuns")).text
            client.headers["Remote-Groups"] = "ftd-shun-viewers"
            assert (await client.post(path, data=fields)).status_code == 403
            client.headers.pop("Remote-User")
            assert (await client.post(path, data=fields)).status_code == 401
    asyncio.run(scenario())
    assert snapshot(lab)["items"][0]["state"] == "CANCELLED"
    assert sync.queue.status()["counts"] == before_jobs
    assert all("refresh-hint" not in str(call.url) for call in lab[3])
    events = [event for event in lab[0].list_events() if event["event_type"] == "MANAGED_SHUN_FLEET_CLEANUP_CANCELLED"]
    assert len(events) == 1 and events[0]["actor_subject"] == subject
    with lab[0]._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "RUNNING"
        assert not db.execute("SELECT 1 FROM operation_requests WHERE id=?", (key,)).fetchone()


@pytest.mark.parametrize("failure", ["lost", "malformed"])
def test_uncertain_cancel_reply_never_reports_success_and_retry_is_audit_free(lab, failure):
    key, _ = root(lab)

    async def scenario():
        async with browser(lab) as client:
            await client.get("/managed-shuns")
            path, fields = f"/managed-shuns/fleet-waits/{key}/cancel", {"csrf": client.cookies.get("ftd_shun_csrf")}
            lab[4][failure] = True
            assert (await client.post(path, data=fields)).status_code == 503
            events = len(lab[0].list_events())
            assert (await client.post(path, data=fields)).status_code == 303
            assert len(lab[0].list_events()) == events
    asyncio.run(scenario())


def test_promotion_wins_cancel_conflicts_without_touching_queue(lab):
    key, job = root(lab)
    sync = lab[1].state.synchronizer
    sync.queue.finish_addition(job["id"], "synthetic-worker", "UNVERIFIED")
    assert sync.managed_fleet_waits.advance("synthetic-worker") == 1
    before = fingerprint(lab[0])

    async def scenario():
        async with browser(lab) as client:
            await client.get("/managed-shuns")
            assert (await client.post(f"/managed-shuns/fleet-waits/{key}/cancel", data={"csrf": client.cookies.get("ftd_shun_csrf")})).status_code == 409
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before
    item = snapshot(lab)["items"][0]
    assert item["outcomes"] == {"QUEUED": 3} and item["predecessor_counts"] == {"UNVERIFIED": 1}
    assert item["active"] and not item["verified"]


@pytest.mark.parametrize("outcome", ["VERIFIED", "NOOP", "UNVERIFIED", "FAILED", "CANCELLED", "RECONCILED_ABSENT"])
def test_settlement_progress_does_not_conflate_terminal_states_with_verified_removal(lab, outcome):
    key, _ = root(lab, waiting=False)
    with lab[0]._connection() as db:
        db.execute("UPDATE operation_jobs SET state=?,completed_at=requested_at", (outcome,))
    item = snapshot(lab)["items"][0]
    assert item["id"] == key and item["settled_targets"] == 3 and not item["active"]
    assert item["verified"] is (outcome == "VERIFIED")
    assert item["attention"] is (outcome in {"FAILED", "UNVERIFIED"})
    assert item["outcomes"] == {outcome: 3}


def test_old_ready_ledger_and_pruned_history_never_imply_verified_success_or_migration(lab):
    key, _ = root(lab, waiting=False)
    with lab[0]._connection() as db:
        db.execute("DROP TABLE managed_fleet_waits")
        db.execute("DELETE FROM operation_requests WHERE id=?", (key,))
    before = fingerprint(lab[0])
    state = snapshot(lab)
    assert not state["waiting_initialized"] and state["initialized"]
    item = state["items"][0]
    assert item["unknown_targets"] == 3 and item["settled_targets"] == 0
    assert not item["verified"] and item["attention"]
    assert fingerprint(lab[0]) == before


def test_cancelled_delegation_is_not_shown_as_active_shared_job(lab):
    key, _ = root(lab, waiting=False)
    with lab[0]._connection() as db:
        db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (key,))
    item = snapshot(lab)["items"][0]
    assert item["queue_request_state"] == "CANCELLED" and not item["active"] and not item["verified"]
    assert item["outcomes"] == {"QUEUED": 3} and item["settled_targets"] == 0

    async def scenario():
        async with browser(lab) as client:
            page = await client.get("/managed-shuns")
            assert "Delegation cancelled — inspect shared jobs" in page.text
            assert "Linked jobs settled — inspect outcomes" not in page.text
    asyncio.run(scenario())


def test_audit_failure_rolls_back_cancellation_and_suppresses_success(lab, monkeypatch, capsys):
    key, _ = root(lab)
    capsys.readouterr()
    before = fingerprint(lab[0])
    insert = lab[0]._insert_event

    def fail(db, event, *args, **kwargs):
        if event == "MANAGED_SHUN_FLEET_CLEANUP_CANCELLED":
            raise sqlite3.OperationalError("Synthetic sensitive failure")
        return insert(db, event, *args, **kwargs)
    monkeypatch.setattr(lab[0], "_insert_event", fail)

    async def scenario():
        async with browser(lab) as client:
            await client.get("/managed-shuns")
            response = await client.post(f"/managed-shuns/fleet-waits/{key}/cancel", data={"csrf": client.cookies.get("ftd_shun_csrf")})
            assert response.status_code == 503 and "Synthetic sensitive" not in response.text
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before and "fleet_cleanup.cancelled" not in capsys.readouterr().out


def test_optional_read_error_remains_visible_without_hiding_managed_state(lab):
    lab[4]["fleet_error"] = True

    async def scenario():
        async with browser(lab) as client:
            page = await client.get("/managed-shuns")
            assert page.status_code == 200 and "Fleet cleanup state is unavailable" in page.text
            assert "The managed registry has not been initialized" in page.text
    asyncio.run(scenario())


def test_bounded_display_prioritizes_waiting_and_counts_all_retained_roots(lab):
    waiting_key, _ = root(lab)
    for number in range(23):
        ip = IPv4Address(f"203.0.113.{number + 1}")
        lab[0].record_observed_shun(1, ip, "outside")
        root(lab, waiting=False, subject=f"owner-{number}", ip=ip)
    with lab[0]._connection() as db:
        db.execute("UPDATE operation_jobs SET state='NOOP',completed_at=requested_at WHERE action='REMOVE'")
    state = snapshot(lab)
    assert len(state["items"]) == 20 and state["items"][0]["id"] == waiting_key
    assert state["counts"] == {"active": 1, "settled": 23}


@pytest.mark.parametrize("corruption", ["payload", "orphan", "predecessor", "wrong_job"])
def test_malformed_optional_evidence_is_unavailable_not_empty_or_verified(lab, corruption):
    key, _ = root(lab)
    with lab[0]._connection() as db:
        if corruption == "payload":
            db.execute("DROP TRIGGER managed_fleet_authority_immutable")
            db.execute("UPDATE managed_fleet_removals SET payload_json='{}' WHERE id=?", (key,))
        elif corruption == "orphan":
            db.execute("DROP TABLE managed_fleet_waits")
            db.execute("DROP TABLE managed_fleet_removals")
            db.execute("CREATE TABLE managed_fleet_waits(id TEXT)")
        elif corruption == "predecessor":
            db.execute("DROP TRIGGER fleet_wait_authority_immutable")
            db.execute("UPDATE managed_fleet_waits SET predecessors_json='[1]'")
        else:
            db.execute("UPDATE operation_jobs SET device_id=2")
    before = fingerprint(lab[0])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[1]), base_url="http://internal") as client:
            response = await client.get("/api/v1/managed-fleet-removals")
            assert response.status_code == 503 and "nothing was submitted" in response.text
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before


def test_unavailable_predecessor_history_is_explicit_not_settled_success(lab):
    root(lab)
    with lab[0]._connection() as db:
        db.execute("DROP TRIGGER fleet_wait_authority_immutable")
        db.execute("UPDATE managed_fleet_waits SET predecessors_json=?", (json.dumps([{"device_id": 2, "job_id": str(uuid4())}]),))
    item = snapshot(lab)["items"][0]
    assert item["predecessor_counts"] == {"UNAVAILABLE": 1} and not item["verified"]
    assert item["attention"]


def test_snapshot_counts_and_jobs_share_one_read_transaction(lab, monkeypatch):
    root(lab, waiting=False)
    original = ManagedFleetState._item

    def settle_concurrently(db, row):
        with lab[0]._connection() as writer:
            writer.execute("UPDATE operation_jobs SET state='VERIFIED',completed_at=requested_at")
        return original(db, row)
    monkeypatch.setattr(ManagedFleetState, "_item", staticmethod(settle_concurrently))
    view = snapshot(lab)
    assert view["counts"] == {"active": 1}
    assert view["items"][0]["outcomes"] == {"QUEUED": 3} and not view["items"][0]["verified"]


def test_private_cancel_rejects_extra_actor_fields_and_viewer(lab):
    key, _ = root(lab)
    before = fingerprint(lab[0])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[1]), base_url="http://internal") as client:
            path = f"/api/v1/managed-fleet-removals/{key}/cancel"
            assert (await client.post(path, json={**ACTOR, "targets": []})).status_code == 422
            assert (await client.post(path, json={**ACTOR, "roles": ["Viewer"]})).status_code == 403
            assert (await client.post(path, json={**ACTOR, "subject": " "})).status_code == 403
            assert (await client.post("/api/v1/managed-fleet-removals/not-a-uuid/cancel", json=ACTOR)).status_code == 422
    asyncio.run(scenario())
    assert fingerprint(lab[0]) == before


def test_scope_sample_is_explicitly_limited_without_losing_whole_scope_counts(lab):
    for device in range(4, 9):
        lab[0].upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
        lab[0].record_observed_shun(device, IP, "outside")
    root(lab, waiting=False)
    state = snapshot(lab)
    assert state["items"][0]["target_count"] == 8 and len(state["items"][0]["scope_sample"]) == 5

    async def scenario():
        async with browser(lab) as client:
            assert "first 5 of 8 targets only" in (await client.get("/managed-shuns")).text
    asyncio.run(scenario())
