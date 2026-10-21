"""Protected/managed policy races using disposable SQLite and synthetic ASGI."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_intent import canonical_managed_change, canonical_managed_removal
from ftd_shun_manager.managed_removals import ManagedRemovals
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.250")
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device_id in (1, 2, 3):
        store.upsert_device(Device(device_id, f"synthetic-{device_id}", IPv4Address(f"192.0.2.{device_id}"), True), "ssh-ed25519 AAAA")
    policy = ProtectedPolicy(store)
    registry = ManagedShuns(store)
    registry.initialize()
    return store, policy, registry


def change(registry, policy, *, action="MAINTAIN", targets=None, **overrides):
    targets = targets or [(1, IP)]
    revision, protected = registry.snapshot()["revision"], policy.revision()
    values = {"request_id": str(uuid4()), "action": action, "targets": targets,
              "managed_revision": revision, "protected_revision": protected,
              "confirmation_digest": canonical_managed_change(action, targets, revision, protected)[2],
              "subject": "alice", "display_name": "Alice", "roles": ("Operator",), **overrides}
    return registry.change(**values)


def protect(policy, *, action="add", ip=IP, **kwargs):
    kwargs.setdefault("managed_revision", policy.snapshot()["managed_revision"])
    return policy.change(action, ip, policy.revision(), "viewer", "Viewer", ("Viewer",), **kwargs)


def test_counts_include_missing_disabled_devices_but_not_retired_intents_and_get_has_no_side_effects(state):
    store, policy, registry = state
    change(registry, policy, targets=[(1, IP), (2, IP), (3, IP)])
    change(registry, policy, action="RETIRE", targets=[(3, IP)])
    store.upsert_device(Device(2, "disabled", IPv4Address("192.0.2.2"), False), "ssh-ed25519 AAAA")
    protect(policy)
    before = registry.snapshot(), store.list_events(), policy.queue.status()
    snapshot = policy.snapshot()
    assert snapshot["managed_policy_available"] and snapshot["managed_revision"] == registry.snapshot()["revision"]
    assert snapshot["entries"][0]["maintained_devices"] == 0
    assert not any(entry["enabled"] for entry in registry.snapshot()["entries"])
    assert snapshot["entries"][0]["active_devices"] == 0
    assert (registry.snapshot(), store.list_events(), policy.queue.status()) == before


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_weakening_never_resumes_retired_policy_or_adds_work_and_rejects_stale_revision(state, action):
    store, policy, registry = state
    change(registry, policy)
    protect(policy)
    revision = registry.snapshot()["revision"]
    before = policy.snapshot(), registry.snapshot(), store.list_events()
    with pytest.raises(QueueConflict):
        protect(policy, action=action, enabled=False, managed_revision=revision - 1, confirm_maintenance_resume=True)
    assert (policy.snapshot(), registry.snapshot(), store.list_events()) == before
    protect(policy, action=action, enabled=False, managed_revision=revision)
    expected = {**before[1], "entries": [{**entry, "protected": False} for entry in before[1]["entries"]]}
    assert registry.snapshot() == expected and not policy.queue.status()["counts"]
    audit = next(e for e in store.list_events() if e["event_type"] == ("PROTECTED_IP_DELETED" if action == "delete" else "PROTECTED_IP_UPDATED"))
    assert audit["actor_roles"] == ["Viewer"]
    assert audit["details"]["managed_context"] == {"revision": revision, "maintained_devices": 0,
        "retired_targets": 0, "retirement_deferred": False, "maintenance_reenabled": False}
    assert store.list_active_shuns() == []


def test_stale_review_is_not_rebased_after_managed_scope_changes(state):
    _, policy, registry = state
    change(registry, policy, targets=[(1, IP), (2, IP)])
    reviewed = registry.snapshot()["revision"]
    protect(policy)
    change(registry, policy, action="RETIRE", targets=[(2, IP)])
    with pytest.raises(QueueConflict, match="Managed policy changed"):
        protect(policy, action="edit", enabled=False, managed_revision=reviewed, confirm_maintenance_resume=True)
    assert policy.enabled_ips() == {IP}


def test_metadata_edits_and_strengthening_do_not_require_resume_ack(state):
    _, policy, registry = state
    change(registry, policy)
    protect(policy, enabled=False)
    protect(policy, action="edit", enabled=False, name="Rename only")
    protect(policy, action="edit", enabled=True)
    protect(policy, action="edit", enabled=True, name="Still protected")
    assert policy.enabled_ips() == {IP}


@pytest.mark.parametrize("corruption", ["partial", "bad_columns", "bad_metadata", "bad_authorization_column"])
def test_bad_optional_policy_means_unknown_not_zero_and_blocks_weakening_not_strengthening(state, corruption):
    store, policy, _ = state
    protect(policy)
    with store._connection() as db:
        if corruption == "partial":
            db.execute("ALTER TABLE managed_shun_requests RENAME TO unavailable_requests")
        elif corruption == "bad_columns":
            db.execute("ALTER TABLE managed_shun_targets RENAME COLUMN enabled TO unavailable_enabled")
        elif corruption == "bad_authorization_column":
            db.execute("ALTER TABLE managed_shun_targets RENAME COLUMN authorization_request_id TO unavailable_authorization")
        else:
            db.execute("DELETE FROM managed_shun_registry")
    result = policy.snapshot()
    assert not result["managed_policy_available"] and result["managed_revision"] is None
    assert result["entries"][0]["maintained_devices"] is None
    with pytest.raises(ManagedStateUnavailable):
        protect(policy, action="delete", confirm_maintenance_resume=True, managed_revision=0)
    protect(policy, ip=OTHER)  # Strengthening still works during optional corruption.
    assert policy.enabled_ips() == {IP, OTHER}
    with pytest.raises(ManagedStateUnavailable):
        policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",))


def test_protection_cancels_only_unsent_add_and_preserves_running_add_waiting_cleanup(state):
    store, policy, registry = state
    change(registry, policy)
    queue = policy.queue
    cleanup = ManagedRemovals(registry, queue)
    cleanup.initialize()
    for device_id in (1, 2):
        queue.enqueue(str(uuid4()), [(device_id, IP)], "creator", "Creator", ("Operator",), source="manual_import",
                      scope="import", policy_revision=policy.revision(),
                      confirmation_digest=canonical_import([(device_id, IP)], policy.revision())[2])
    assert queue.claim_cycle("synthetic", 135)
    running = queue.claim_addition(1, "synthetic", queue.cutoff(), execution_enabled=True)
    revision, key = registry.snapshot()["revision"], str(uuid4())
    cleanup.admit(key, 1, IP, revision, canonical_managed_removal(1, IP, revision)[1], "alice", "Alice", ("Operator",))
    before = cleanup.snapshot()["items"][0]
    protect(policy)
    assert cleanup.snapshot()["items"][0] == before
    assert queue.status()["counts"] == {"RUNNING": 1, "FAILED": 1}
    with store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (running["id"],)).fetchone()[0] == "RUNNING"
    assert not registry.snapshot()["entries"][0]["enabled"]


def test_policy_audit_failure_rolls_back_enabling_and_queued_add_cancellation(state, monkeypatch):
    store, policy, registry = state
    change(registry, policy)
    policy.queue.enqueue(str(uuid4()), [(1, IP)], "creator", "Creator", ("Operator",), source="manual_import",
                         scope="import", policy_revision=policy.revision(),
                         confirmation_digest=canonical_import([(1, IP)], policy.revision())[2])
    before = policy.snapshot(), policy.queue.status(), store.list_events()
    original = policy._audit

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("Synthetic late policy audit failure")

    monkeypatch.setattr(policy, "_audit", fail)
    with pytest.raises(sqlite3.OperationalError):
        protect(policy)
    assert (policy.snapshot(), policy.queue.status(), store.list_events()) == before


@pytest.mark.parametrize("scope", ["device", "all", "managed_device_removal", ""])
def test_ordinary_admission_cannot_bypass_enabled_policy_even_using_scope_label(state, scope):
    store, policy, registry = state
    change(registry, policy)
    before = policy.queue.status(), store.list_events()
    with pytest.raises(QueueConflict, match="Managed maintenance"):
        policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",), scope=scope)
    assert (policy.queue.status(), store.list_events()) == before


def test_fleet_guard_includes_missing_maintained_device_outside_observed_targets(state):
    _, policy, registry = state
    change(registry, policy, targets=[(2, IP)])
    with pytest.raises(QueueConflict, match="Managed maintenance"):
        policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",), scope="all")
    policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",), scope="device")
    assert policy.queue.status()["counts"] == {"QUEUED": 1}


def test_protected_removal_remains_available_after_permanent_retirement(state):
    _, policy, registry = state
    change(registry, policy)
    protect(policy)
    before = registry.snapshot()
    policy.queue.enqueue(str(uuid4()), [(1, IP)], "system:trusted-ip-policy", "Protected policy", (), source="trusted_policy")
    assert policy.queue.claim_cycle("synthetic", 135)
    assert policy.queue.claim_removal(1, "synthetic", policy.queue.cutoff())
    assert registry.snapshot() == before


@pytest.mark.parametrize("running", [False, True])
def test_cannot_grant_maintenance_over_queued_or_running_removal(state, running):
    _, policy, registry = state
    policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",))
    if running:
        assert policy.queue.claim_cycle("synthetic", 135)
        assert policy.queue.claim_removal(1, "synthetic", policy.queue.cutoff())
    with pytest.raises(ManagedConflict, match="Removal is pending"):
        change(registry, policy)
    assert registry.snapshot()["entries"] == []


def test_simultaneous_grant_and_ordinary_removal_cannot_both_commit(state):
    _, policy, registry = state

    def grant():
        try:
            change(registry, policy)
            return "grant"
        except ManagedConflict:
            return "conflict"

    def remove():
        try:
            policy.queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",))
            return "remove"
        except QueueConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(grant), pool.submit(remove)
        result = [first.result(), second.result()]
    assert result.count("conflict") == 1


def test_combined_coordinator_retires_before_guard_under_one_transaction(state):
    _, policy, registry = state
    change(registry, policy)
    cleanup = ManagedRemovals(registry, policy.queue)
    cleanup.initialize()
    revision = registry.snapshot()["revision"]
    result = cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                           "alice", "Alice", ("Operator",))
    assert result["status"] == "accepted" and policy.queue.status()["counts"] == {"QUEUED": 1}
    assert not registry.snapshot()["entries"][0]["enabled"]


def test_private_api_strict_ack_errors_and_legacy_missing_fleet_guard(state):
    store, policy, registry = state
    change(registry, policy, targets=[(2, IP)])
    app = create_app(replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                             agent_mode="mock"), store)  # Synthetic only; no lifecycle worker started.

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            for path, method in ((f"/api/v1/shuns/{IP}/remove-all", "POST"), (f"/api/v1/devices/2/shuns/{IP}", "DELETE")):
                response = await client.request(method, path, json=ACTOR)
                assert response.status_code == 409 and "Managed maintenance" in response.text
            protect(policy)
            body = {"actor": {**ACTOR, "roles": ["Viewer"]}, "revision": policy.revision(),
                    "enabled": False, "managed_revision": registry.snapshot()["revision"]}
            for invalid in ({"managed_revision": True}, {"managed_revision": "1"}, {"confirm_maintenance_resume": "true"}):
                assert (await client.post(f"/api/v1/protected-ips/{IP}/edit", json={**body, **invalid})).status_code == 422
            assert (await client.post(f"/api/v1/protected-ips/{IP}/edit", json=body)).status_code == 200
    asyncio.run(scenario())
    assert policy.queue.status()["counts"] == {} and not app.state.synchronizer._activity.is_set()


def test_partial_policy_availability_propagates_to_status_without_breaking_monitoring(state):
    store, policy, _ = state
    protect(policy)
    app = create_app(replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                             agent_mode="mock"), store)
    with store._connection() as db:
        db.execute("ALTER TABLE managed_shun_targets RENAME COLUMN enabled TO unavailable_enabled")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            result = await client.get("/api/v1/status")
            assert result.status_code == 200 and result.json()["managed_policy_available"] is False
            response = await client.post(f"/api/v1/protected-ips/{IP}/edit", json={
                "actor": ACTOR, "revision": policy.revision(), "enabled": False,
                "managed_revision": 0, "confirm_maintenance_resume": True})
            assert response.status_code == 503
            assert (await client.post(f"/api/v1/shuns/{IP}/remove-all", json=ACTOR)).status_code == 503
            assert (await client.get("/api/v1/shuns")).status_code == 200
    asyncio.run(scenario())
    assert policy.enabled_ips() == {IP} and policy.queue.status()["counts"] == {}


def test_bff_forwards_reviewed_ack_and_real_identity_without_device_hint(state, monkeypatch):
    store, policy, registry = state
    change(registry, policy)
    protect(policy)
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode="disabled", development_auth=False)
    api, calls = create_app(config, store), []

    def internal(request):
        calls.append(request)

        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                r = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(r.status_code, content=r.content, headers=r.headers)
        return asyncio.run(send())

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://fixture.test",
                                     headers={"Remote-User": "viewer", "Remote-Groups": "ftd-shun-viewers"}) as client:
            page = await client.get("/protected-ips")
            assert page.status_code == 200 and "permanently stops matching managed maintenance" in page.text
            assert 'name="managed_revision"' in page.text and 'name="confirm_maintenance_resume"' not in page.text
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "ip": str(IP), "revision": policy.revision(),
                      "enabled": "false", "managed_revision": registry.snapshot()["revision"] - 1}
            assert (await client.post("/protected-ips/edit", data=fields)).status_code == 409
            assert (await client.post("/protected-ips/edit", data={**fields, "confirm_maintenance_resume": "yes"})).status_code == 422
            assert (await client.post("/protected-ips/edit", data={**fields, "managed_revision": registry.snapshot()["revision"]})).status_code == 303
    asyncio.run(scenario())
    event = next(e for e in store.list_events() if e["event_type"] == "PROTECTED_IP_UPDATED")
    assert event["actor_subject"] == "viewer" and event["actor_roles"] == ["Viewer"]
    assert not any(r.url.path == "/api/v1/refresh-hint" for r in calls)
    assert policy.queue.status()["counts"] == {}


def test_retirement_preserves_identity_authorization_and_real_viewer_audit_without_ledger_slot(state, monkeypatch):
    from ftd_shun_manager import managed_shuns

    store, policy, registry = state
    change(registry, policy, targets=[(1, IP), (2, IP), (3, OTHER)])
    before = registry.snapshot()
    monkeypatch.setattr(managed_shuns, "MAX_MANAGED_REQUESTS", 1)
    protect(policy)
    after = registry.snapshot()
    assert after["revision"] == before["revision"] + 1
    for old, new in zip(before["entries"], after["entries"], strict=True):
        assert (new["intent_id"], new["generation"], new["authorization_request_id"]) == (
            old["intent_id"], old["generation"], old["authorization_request_id"])
        assert new["enabled"] is (new["ip"] != str(IP))
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 1
    events = [e for e in store.list_events() if e["event_type"] == "MANAGED_SHUN_RETIRED"]
    root = next(e for e in store.list_events() if e["event_type"] == "PROTECTED_IP_ADDED")
    assert len(events) == root["details"]["managed_context"]["retired_targets"] == 2
    assert all(e["request_id"] == root["request_id"] and e["actor_roles"] == ["Viewer"]
               and e["actor_subject"] == "viewer" for e in events)


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_deferred_protection_is_durable_until_repair_and_retirement_before_release(state, action):
    store, policy, registry = state
    change(registry, policy)
    with store._connection() as db:
        db.execute("ALTER TABLE managed_shun_requests RENAME TO unavailable_requests")
    protect(policy)
    assert policy.enabled_ips() == {IP}
    event = next(e for e in store.list_events() if e["event_type"] == "PROTECTED_IP_ADDED")
    assert event["details"]["managed_context"]["retirement_deferred"] is True
    restarted = ProtectedPolicy(Store(store.path))
    with pytest.raises(ManagedStateUnavailable):
        protect(restarted, action=action, enabled=False)
    with store._connection() as db:
        db.execute("ALTER TABLE unavailable_requests RENAME TO managed_shun_requests")
    assert registry.snapshot()["entries"][0]["enabled"]
    protect(restarted, action=action, enabled=False)
    assert not registry.snapshot()["entries"][0]["enabled"]
    assert not restarted.enabled_ips() and not restarted.queue.status()["counts"]


def test_deleting_disabled_entry_preserves_new_explicit_maintenance(state):
    _, policy, registry = state
    change(registry, policy)
    protect(policy)
    protect(policy, action="edit", enabled=False)
    change(registry, policy)
    before = registry.snapshot()
    protect(policy, action="delete")
    assert registry.snapshot() == before and before["entries"][0]["enabled"]


def test_old_grant_key_replay_after_protection_release_cannot_reenable(state):
    _, policy, registry = state
    key, revision = str(uuid4()), registry.snapshot()["revision"]
    protected = policy.revision()
    digest = canonical_managed_change("MAINTAIN", [(1, IP)], revision, protected)[2]
    args = (key, "MAINTAIN", [(1, IP)], revision, protected, digest, "alice", "Alice", ("Operator",))
    registry.change(*args)
    protect(policy)
    protect(policy, action="delete")
    before = registry.snapshot()
    assert registry.change(*args)["replayed"]
    assert registry.snapshot() == before and not before["entries"][0]["enabled"]


def test_retirement_audit_failure_rolls_back_all_policy_target_and_queue_rows(state, monkeypatch):
    store, policy, registry = state
    change(registry, policy, targets=[(1, IP), (2, IP)])
    with store._connection() as db:
        before = tuple(db.iterdump())
    original = store._insert_event

    def fail(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == "MANAGED_SHUN_RETIRED":
            raise sqlite3.OperationalError("Synthetic retirement audit failure")

    monkeypatch.setattr(store, "_insert_event", fail)
    with pytest.raises(sqlite3.OperationalError):
        protect(policy)
    with store._connection() as db:
        assert tuple(db.iterdump()) == before


def test_stale_enable_cannot_silently_retire_new_concurrent_scope(state):
    _, policy, registry = state
    reviewed = registry.snapshot()["revision"]
    change(registry, policy)
    with pytest.raises(QueueConflict, match="Managed policy changed"):
        protect(policy, managed_revision=reviewed)
    assert registry.snapshot()["entries"][0]["enabled"] and not policy.enabled_ips()


def test_private_api_audit_failure_returns_unconfirmed_without_partial_retirement(state, monkeypatch):
    store, policy, registry = state
    change(registry, policy)
    app = create_app(replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                             agent_mode="disabled"), store)
    before = registry.snapshot(), policy.snapshot(), store.list_events()
    original = app.state.synchronizer.policy._audit

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("Synthetic protected audit failure")

    monkeypatch.setattr(app.state.synchronizer.policy, "_audit", fail)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            response = await client.post(f"/api/v1/protected-ips/{IP}/add", json={
                "actor": ACTOR, "revision": policy.revision(), "managed_revision": registry.snapshot()["revision"]})
            assert response.status_code == 503 and "not confirmed" in response.text
    asyncio.run(scenario())
    assert (registry.snapshot(), policy.snapshot(), store.list_events()) == before
