"""Offline desired-state lifecycle; temporary SQLite only, never FTD/queue dispatch."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_shuns
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_shuns import (
    ManagedCapacity,
    ManagedConflict,
    ManagedShuns,
    canonical_managed_change,
)
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.252")


@pytest.fixture
def registry(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f"lab-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    registry = ManagedShuns(store)
    registry.initialize()
    return registry


def arguments(registry, *, request_id=None, action="MAINTAIN", targets=None,
              revision=None, protected_revision=None, subject="alice", roles=("Operator",),
              label="Fixture", reason="Maintain after disappearance"):
    targets = [(1, IP)] if targets is None else targets
    revision = registry.snapshot()["revision"] if revision is None else revision
    if protected_revision is None:
        with registry.store._connection() as db:
            protected_revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    return {"request_id": request_id or str(uuid4()), "action": action, "targets": targets,
            "managed_revision": revision, "protected_revision": protected_revision,
            "confirmation_digest": canonical_managed_change(action, targets, revision, protected_revision, label, reason)[2],
            "subject": subject, "display_name": subject.title(), "roles": roles, "label": label, "reason": reason}


def change(registry, **values):
    return registry.change(**arguments(registry, **values))


def rows(store, table):
    with store._connection() as db:
        return [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]


def test_registry_is_opt_in_and_normal_application_does_not_initialize_it(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "normal.db")
    settings = replace(Settings.from_environment(), database_path=store.path,
                       device_inventory_path=None, agent_mode="disabled")
    app = create_app(settings, store)
    with store._connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'managed_shun_%'").fetchall()
    assert {route.path for route in app.routes if "managed" in route.path} == {
        "/api/v1/managed-shuns", "/api/v1/managed-shuns/page", "/api/v1/managed-removal-handoffs",
        "/api/v1/managed-shuns/retire", "/api/v1/managed-shuns/maintain", "/api/v1/managed-removal-handoffs/{request_id}/cancel",
        "/api/v1/managed-shuns/maintain-batch",
        "/api/v1/managed-removal-scope/{ip}",
        "/api/v1/managed-fleet-removals", "/api/v1/managed-fleet-removals/{request_id}/cancel",
        "/api/v1/managed-removals/device", "/api/v1/managed-removals/fleet",
    }
    assert next(route for route in app.routes if route.path == "/api/v1/managed-shuns").methods == {"GET"}
    assert app.state.synchronizer.queue.status()["counts"] == {}


def test_initialize_is_empty_repeatable_and_never_adopts_one_time_history(registry):
    queue = OperationQueue(registry.store)
    queue.initialize()
    targets = [(1, IP)]
    request = queue.enqueue(str(uuid4()), targets, "alice", "Alice", ("Operator",),
                            source="manual_import", scope="import", policy_revision=0,
                            confirmation_digest=canonical_import(targets, 0)[2])
    registry.store.record_observed_shun(1, IP, "management")
    before = {table: rows(registry.store, table) for table in
              ("operation_jobs", "operation_requests", "manual_import_batches", "shun_state", "shun_events")}
    registry.initialize()
    assert registry.snapshot() == {"revision": 0, "restoration_suspended": True, "limit": 1000, "entries": []}
    assert before == {table: rows(registry.store, table) for table in before}
    with pytest.raises(ManagedConflict, match="One-time"):
        registry.change(**arguments(registry, request_id=request["operation_id"]))
    assert registry.snapshot()["entries"] == []


def test_mode_scope_order_metadata_and_revisions_bind_confirmation(registry):
    targets = [(2, OTHER), (1, IP)]
    ordered = canonical_managed_change("MAINTAIN", targets, 0, 0, " Label ", " Reason ")
    assert ordered == canonical_managed_change("MAINTAIN", targets[::-1], 0, 0, "Label", "Reason")
    payload = json.loads(ordered[1])
    assert payload["mode"] == "maintain_present" and payload["scope"] == "managed_shuns"
    digests = {ordered[2], canonical_import(targets, 0, "Label", "Reason")[2],
               canonical_managed_change("RETIRE", targets, 0, 0, "Label", "Reason")[2],
               canonical_managed_change("MAINTAIN", targets, 1, 0, "Label", "Reason")[2],
               canonical_managed_change("MAINTAIN", targets, 0, 1, "Label", "Reason")[2]}
    assert len(digests) == 5
    values = arguments(registry)
    with pytest.raises(ValueError, match="Confirmation"):
        registry.change(**{**values, "confirmation_digest": canonical_import([(1, IP)], 0)[2]})
    assert registry.snapshot()["revision"] == 0


def test_authority_survives_absence_retirement_replay_and_explicit_new_generation(registry):
    create = arguments(registry)
    result = registry.change(**create)
    first = registry.snapshot()["entries"][0]
    assert first["enabled"] and not first["observed_present"]
    assert first["actor_roles"] == ["Operator"] and first["actor_subject"] == "alice"
    assert first["generation"] == 1 and first["authorization_request_id"] == create["request_id"]
    registry.store.record_observed_shun(1, IP, "management")
    registry.store.reconcile_snapshot(1, [])
    assert registry.snapshot()["entries"][0] == first
    retired = change(registry, action="RETIRE", subject="bob")
    current = registry.snapshot()["entries"][0]
    assert not current["enabled"] and current["retired_at"]
    assert current["intent_id"] == first["intent_id"] and current["generation"] == 1
    before = registry.store.list_events()
    assert registry.change(**create) == {**result, "replayed": True}
    assert not registry.snapshot()["entries"][0]["enabled"]
    assert registry.snapshot()["revision"] == retired["managed_revision"]
    assert registry.store.list_events() == before
    change(registry, subject="carol")
    new = registry.snapshot()["entries"][0]
    assert new["enabled"] and new["generation"] == 2 and new["intent_id"] != first["intent_id"]
    assert new["actor_subject"] == "carol"
    assert ManagedShuns(registry.store).snapshot() == registry.snapshot()
    assert not registry.store.list_active_shuns(IP), "Policy is not an observed/verified creation"


def test_duplicate_user_intentions_keep_one_authority_and_actor_noop_audit(registry):
    change(registry)
    first = registry.snapshot()["entries"][0]
    result = change(registry, subject="bob")
    assert result["changed_targets"] == 0
    assert registry.snapshot()["entries"] == [first]
    event = registry.store.list_events()[0]
    assert event["event_type"] == "MANAGED_SHUN_POLICY_NOOP" and event["actor_subject"] == "bob"
    assert event["details"]["intent_id"] == first["intent_id"]


@pytest.mark.parametrize("value", [[], [(True, IP)], [(0, IP)], [(65536, IP)], [(1, "198.51.100.251")], [(1, IP), (1, IP)]])
def test_strict_typed_targets_reject_invalid_scope(registry, value):
    with pytest.raises(ValueError):
        canonical_managed_change("MAINTAIN", value, 0, 0)
    assert registry.snapshot()["revision"] == 0


@pytest.mark.parametrize("revision", [-1, True, "0"])
def test_revision_types_are_strict(revision):
    with pytest.raises(ValueError):
        canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)


def test_role_digest_key_and_actor_cannot_be_spoofed(registry):
    values = arguments(registry)
    for extra in ({"subject": " "}, {"roles": ()}, {"roles": ("Viewer",)}):
        with pytest.raises(PermissionError):
            registry.change(**{**values, **extra})
    for key in ("arbitrary", "", "00000000-0000-4000-8000-00000000000A"):
        with pytest.raises(ValueError, match="UUID"):
            registry.change(**{**values, "request_id": key})
    for digest in ("wrong", "неправильно"):
        with pytest.raises(ValueError, match="Confirmation"):
            registry.change(**{**values, "confirmation_digest": digest})
    registry.change(**values)
    for extra in ({"subject": "bob"}, {"targets": [(2, IP)]}):
        changed = {**values, **extra}
        changed["confirmation_digest"] = canonical_managed_change(
            changed["action"], changed["targets"], 0, 0, changed["label"], changed["reason"],
        )[2]
        with pytest.raises(ManagedConflict, match="key"):
            registry.change(**changed)


def test_parallel_same_key_replays_once_and_different_keys_conflict_on_revision(registry):
    values = arguments(registry)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: registry.change(**values), range(6)))
    assert sum(not result["replayed"] for result in results) == 1
    assert len(registry.snapshot()["entries"]) == len(rows(registry.store, "managed_shun_requests")) == 1
    first = arguments(registry, targets=[(1, OTHER)])
    second = arguments(registry, targets=[(2, OTHER)])
    def try_change(value):
        try:
            return registry.change(**value)
        except ManagedConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_change, [first, second]))
    assert sum(result is not None for result in results) == 1
    assert registry.snapshot()["revision"] == 2


def test_protection_device_and_adoption_rejections_are_whole_batch_atomic(registry):
    policy = ProtectedPolicy(registry.store)
    policy.change("add", OTHER, 0, "fixture", "Fixture", ())
    before = registry.store.list_events()
    with pytest.raises(ManagedConflict, match="Protected"):
        change(registry, targets=[(1, IP), (1, OTHER)])
    assert registry.snapshot()["entries"] == [] and registry.store.list_events() == before
    for targets in ([(1, IP), (9, IP)], [(1, IP), (2, OTHER)]):
        with pytest.raises(ManagedConflict):
            change(registry, targets=targets)
    registry.store.record_observed_shun(2, IP, "management")
    with pytest.raises(ManagedConflict, match="adoption"):
        change(registry, targets=[(1, IP), (2, IP)])
    registry.store.upsert_device(Device(2, "lab-2", IPv4Address("192.0.2.2"), False), "ssh-ed25519 AAAA")
    with pytest.raises(ManagedConflict, match="disabled"):
        change(registry, targets=[(2, IP)])
    assert registry.snapshot()["revision"] == 0 and not rows(registry.store, "managed_shun_requests")


def test_retirement_can_revoke_missing_disabled_or_protected_targets(registry):
    change(registry, targets=[(1, IP), (2, IP)])
    reviewed = arguments(registry, action="RETIRE", targets=[(1, IP)])
    policy = ProtectedPolicy(registry.store)
    policy.change("add", IP, 0, "fixture", "Fixture", (), managed_revision=registry.snapshot()["revision"])
    registry.store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), False), "ssh-ed25519 AAAA")
    assert registry.snapshot()["entries"][0]["protected"]
    with pytest.raises(ManagedConflict, match="changed"):
        registry.change(**reviewed)  # Protection retired the whole scope; old review cannot be rebased.
    change(registry, action="RETIRE", targets=[(1, IP)])  # Fresh revocation remains valid/no-op.
    entries = registry.snapshot()["entries"]
    assert not entries[0]["enabled"] and not entries[1]["enabled"]
    assert not entries[0]["device_enabled"]
    assert entries[0]["actor_subject"] == "alice", "Keep original authorization, audit retiring actor separately"


def test_caller_can_atomically_compose_or_roll_back_retirement(registry, capsys):
    change(registry)
    capsys.readouterr()
    values = arguments(registry, action="RETIRE")
    before = registry.snapshot()
    with pytest.raises(RuntimeError), registry.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        registry.apply_change(db, **values)
        raise RuntimeError("Simulated later removal admission failure")
    assert registry.snapshot() == before
    assert not capsys.readouterr().out
    assert not any(row[0] == values["request_id"] for row in rows(registry.store, "managed_shun_requests"))
    with registry.store._connection() as db:
        with pytest.raises(ValueError, match="transaction"):
            registry.apply_change(db, **values)
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ManagedConflict):
            registry.apply_change(db, **arguments(registry, action="RETIRE", targets=[(1, IP), (2, IP)]))
        assert db.execute("SELECT enabled FROM managed_shun_targets").fetchone()[0] == 1
        registry.apply_change(db, **values)
    assert not registry.snapshot()["entries"][0]["enabled"]


def test_stale_protection_review_and_legacy_removal_key_do_not_grant_policy(registry):
    reviewed = arguments(registry)
    ProtectedPolicy(registry.store).change("add", OTHER, 0, "fixture", "Fixture", ())
    with pytest.raises(ManagedConflict, match="Protected IPs changed"):
        registry.change(**reviewed)
    queue = OperationQueue(registry.store)
    queue.initialize()
    key = str(uuid4())
    queue.enqueue(key, [(1, IP)], "alice", "Alice", ("Operator",))
    with pytest.raises(ManagedConflict, match="One-time"):
        registry.change(**arguments(registry, request_id=key))
    assert not registry.snapshot()["entries"]
    admin = arguments(registry, roles=("Administrator",))
    with pytest.raises(ManagedConflict, match="Removal is pending"):
        registry.change(**admin)
    queue.cancel(key, "alice", False)
    registry.change(**admin)
    assert registry.snapshot()["entries"][0]["actor_roles"] == ["Administrator"]


def test_target_capacity_and_retirement_ledger_reserve_never_silently_evict(registry, monkeypatch):
    monkeypatch.setattr(managed_shuns, "MAX_MANAGED_TARGETS", 2)
    monkeypatch.setattr(managed_shuns, "MAX_MANAGED_REQUESTS", 4)
    change(registry, targets=[(1, IP), (2, IP)])
    change(registry, subject="bob")  # Last non-reserved request slot.
    before = registry.snapshot()
    with pytest.raises(ManagedCapacity, match="retirement"):
        change(registry, subject="carol")
    assert registry.snapshot() == before
    change(registry, action="RETIRE", targets=[(1, IP)])
    with pytest.raises(ManagedCapacity, match="retirement"):
        change(registry, action="RETIRE", targets=[(1, IP)])  # New NOOP key cannot consume reserve.
    change(registry, action="RETIRE", targets=[(2, IP)])
    assert not any(row["enabled"] for row in registry.snapshot()["entries"])
    assert len(rows(registry.store, "managed_shun_requests")) == 4
    with pytest.raises(ManagedCapacity):
        change(registry, targets=[(1, OTHER)])


def test_retired_tombstones_count_toward_target_capacity(registry, monkeypatch):
    monkeypatch.setattr(managed_shuns, "MAX_MANAGED_TARGETS", 1)
    change(registry)
    change(registry, action="RETIRE")
    with pytest.raises(ManagedCapacity, match="target limit"):
        change(registry, targets=[(1, OTHER)])
    change(registry)  # Explicit new generation can reuse this exact target, not a new slot.
    assert registry.snapshot()["entries"][0]["generation"] == 2


def test_maximum_batch_is_complete_and_never_manipulates_observed_state(registry):
    targets = [(1, IPv4Address(0xC6120000 + index)) for index in range(1000)]
    result = change(registry, targets=targets)
    state = registry.snapshot()
    assert result["changed_targets"] == len(state["entries"]) == 1000
    assert [(entry["device_id"], IPv4Address(entry["ip"])) for entry in state["entries"]] == targets
    assert all(not entry["observed_present"] for entry in state["entries"])
    assert registry.store.list_active_shuns() == []
    before = state
    with pytest.raises(ManagedCapacity):
        change(registry, targets=[(2, IP)])
    assert registry.snapshot() == before
    with pytest.raises(ValueError):
        canonical_managed_change("MAINTAIN", [*targets, (2, IP)], 1, 0)


def test_audit_failure_rolls_back_savepoint_even_if_caller_catches_error(registry, monkeypatch):
    values = arguments(registry, targets=[(1, IP), (1, OTHER)])
    original = registry.store._insert_event
    def fail_second(*args, **kwargs):
        original(*args, **kwargs)
        if args[3] == OTHER:
            raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(registry.store, "_insert_event", fail_second)
    with registry.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError):
            registry.apply_change(db, **values)
        assert db.execute("SELECT COUNT(*) FROM managed_shun_targets").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM shun_events").fetchone()[0] == 0
    assert registry.snapshot()["revision"] == 0


def test_sqlite_backup_preserves_retirement_and_does_not_enable_restoration(registry, tmp_path):
    create = arguments(registry)
    registry.change(**create)
    change(registry, action="RETIRE")
    backup = tmp_path / "backup.db"
    with registry.store._connection() as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    restored = ManagedShuns(Store(backup))
    restored.initialize()
    assert restored.snapshot() == registry.snapshot()
    assert restored.snapshot()["restoration_suspended"]
    restored.change(**create)
    assert not restored.snapshot()["entries"][0]["enabled"]


def test_history_retention_keeps_authority_tombstones_ledger_and_no_false_provenance(registry):
    change(registry, targets=[(1, IP), (2, IP)])
    change(registry, action="RETIRE", targets=[(2, IP)])
    before = registry.snapshot()
    registry.store.prune_expired_history(366, datetime.now(UTC) + timedelta(days=367))
    OperationQueue(registry.store).initialize()
    OperationQueue(registry.store).prune_completed(366)
    assert registry.snapshot() == before
    assert len(rows(registry.store, "managed_shun_requests")) == 2
    assert rows(registry.store, "shun_import_origins") == []
    assert rows(registry.store, "operation_jobs") == []
    with registry.store._connection() as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        for statement in ("UPDATE managed_shun_requests SET actor_subject='forged'", "DELETE FROM managed_shun_requests"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)


def test_canonical_metadata_and_logs_do_not_expose_full_targets_or_comments(registry, capsys):
    for label in ("x" * 101, "bad\x00label"):
        with pytest.raises(ValueError):
            arguments(registry, label=label)
    change(registry, label="<b>Batch</b>", reason="Private review note")
    log = json.loads(capsys.readouterr().out)
    assert "Private review note" not in json.dumps(log) and "<b>Batch</b>" not in json.dumps(log)
    assert log["event"] == "managed_shun.policy.changed"
    row = registry.snapshot()["entries"][0]
    assert row["label"] == "<b>Batch</b>" and row["reason"] == "Private review note"
    assert "payload_json" not in row and "management_ip" not in row
