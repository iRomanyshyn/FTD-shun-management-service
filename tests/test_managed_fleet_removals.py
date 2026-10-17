"""Offline atomic fleet admission: temporary SQLite, no deployed state/device."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4, uuid5

import pytest

from ftd_shun_manager import managed_fleet_removals
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.maintenance import apply_recovery_control, run_offline
from ftd_shun_manager.managed_fleet_removals import ManagedFleetRemovals
from ftd_shun_manager.managed_intent import (
    canonical_managed_change,
    canonical_managed_fleet_removal,
    canonical_managed_removal,
)
from ftd_shun_manager.managed_removals import ManagedRemovals
from ftd_shun_manager.managed_scope import ManagedRemovalScopes
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.250")
NOW = datetime(2026, 10, 17, tzinfo=UTC)


def policy_change(registry, action, targets, key=None):
    revision = registry.snapshot()["revision"]
    return registry.change(key or str(uuid4()), action, [(device, IP) for device in targets], revision, 0,
                           canonical_managed_change(action, [(device, IP) for device in targets], revision, 0)[2],
                           "creator", "Creator", ("Operator",))


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device in range(1, 5):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    registry, queue = ManagedShuns(store), OperationQueue(store)
    registry.initialize()
    queue.initialize()
    monkeypatch.setattr(queue, "_now", lambda: NOW)
    policy_change(registry, "MAINTAIN", [1, 2, 4])
    policy_change(registry, "RETIRE", [4])
    store.record_observed_shun(3, IP, "outside")
    store.record_observed_shun(3, IP, "inside")
    fleet = ManagedFleetRemovals(registry, queue)
    fleet.initialize()
    return fleet


def arguments(fleet, **overrides):
    values = {"request_id": str(uuid4()), "reviewed": ManagedRemovalScopes(fleet.store).snapshot(IP),
              "subject": "alice", "display_name": "Alice", "roles": ("Operator",),
              "ttl_seconds": 900, "reason": "Reviewed fleet cleanup", **overrides}
    scope = {k: v for k, v in values["reviewed"].items() if k not in {"scope_digest", "read_only", "execution_available"}}
    values["confirmation_digest"] = canonical_managed_fleet_removal(scope, values["ttl_seconds"], values["reason"])[1]
    return values


def fingerprint(fleet):
    with fleet.store._connection() as db:
        return tuple(db.iterdump())


def add(fleet, device, running=False):
    key = str(uuid4())
    fleet.queue.enqueue(key, [(device, IP)], "adder", "Adder", ("Operator",), source="manual_import",
                        scope="import", policy_revision=0, confirmation_digest=canonical_import([(device, IP)], 0)[2])
    if running:
        assert fleet.queue.claim_cycle("worker", 135)
        assert fleet.queue.claim_addition(device, "worker", fleet.queue.cutoff(), execution_enabled=True)
    return key


def test_normal_startup_and_reads_do_not_initialize_or_expose_fleet_admission(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "normal.db")
    app = create_app(replace(Settings.from_environment(), database_path=store.path,
                             device_inventory_path=None, agent_mode="disabled"), store)
    app.state.synchronizer.queue.status()
    ManagedShuns(store).metadata()
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_fleet_removals'").fetchone()
    assert all(route.methods == {"GET"} for route in app.routes if "managed-removal-scope" in route.path)
    assert not any("fleet" in route.path for route in app.routes)


def test_whole_union_is_atomic_one_request_one_retirement_and_no_unmanaged_adoption(fleet, capsys):
    values = arguments(fleet, reason="Private reason not for stdout")
    before = fleet.registry.snapshot()["revision"]
    capsys.readouterr()
    result = fleet.admit(**values)
    assert result == {"operation_id": values["request_id"], "status": "accepted", "replayed": False,
                      "target_count": 3, "retired_targets": 2, "managed_revision": before + 1}
    assert "Private reason" not in capsys.readouterr().out
    assert fleet.queue.status()["counts"] == {"QUEUED": 3}
    entries = fleet.registry.snapshot()["entries"]
    assert all(not entry["enabled"] for entry in entries) and len(entries) == 3
    assert {entry["device_id"] for entry in entries} == {1, 2, 4}
    assert len(fleet.store.list_active_shuns()) == 2  # No device result was invented.
    with fleet.store._connection() as db:
        root = db.execute("SELECT * FROM managed_fleet_removals").fetchone()
        request = db.execute("SELECT * FROM operation_requests").fetchone()
        assert root["phase"] == "ADMITTED" and root["id"] == request["id"] == values["request_id"]
        assert request["requested_at"] == root["requested_at"]
        assert request["expires_at"] <= root["expires_at"]
        assert datetime.fromisoformat(root["expires_at"]) - datetime.fromisoformat(root["requested_at"]) == timedelta(seconds=900)
        assert db.execute("SELECT COUNT(*) FROM operation_links").fetchone()[0] == 3
        assert not db.execute("SELECT 1 FROM managed_shun_targets WHERE device_id=3").fetchone()
        assert not db.execute("SELECT 1 FROM manual_import_batches").fetchone()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    aggregate = next(event for event in fleet.store.list_events() if event["event_type"] == "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED")
    assert aggregate["actor_subject"] == "alice" and aggregate["details"]["target_count"] == 3


def test_observed_only_fleet_queues_cleanup_without_policy_ledger_churn(fleet):
    policy_change(fleet.registry, "RETIRE", [1, 2])
    before = fleet.registry.snapshot()
    result = fleet.admit(**arguments(fleet))
    assert result["target_count"] == 1 and result["retired_targets"] == 0
    assert fleet.registry.snapshot() == before
    with fleet.store._connection() as db:
        assert db.execute("SELECT retirement_request_id FROM managed_fleet_removals").fetchone()[0] is None


@pytest.mark.parametrize("device,running", [(1, False), (1, True), (3, False), (3, True)])
def test_any_unfinished_add_refuses_entire_fleet_without_cancelling_or_retiring(fleet, device, running, capsys):
    add(fleet, device, running)
    values = arguments(fleet)
    before = fingerprint(fleet)
    capsys.readouterr()
    with pytest.raises(QueueConflict, match="unfinished ADD"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_disabled_device_remains_in_scope_and_rejects_all_targets(fleet):
    fleet.store.upsert_device(Device(2, "disabled", IPv4Address("192.0.2.2"), False), "ssh-ed25519 AAAA")
    values = arguments(fleet)
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="disabled device"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before


@pytest.mark.parametrize("mutation", ["observation", "retirement", "inventory", "protection"])
def test_stale_scope_refuses_without_rebasing(fleet, mutation):
    values = arguments(fleet)
    with fleet.store._connection() as db:
        if mutation == "observation":
            db.execute("UPDATE shun_state SET active=0 WHERE device_id=3")
        elif mutation == "inventory":
            db.execute("UPDATE devices SET hostname='changed' WHERE id=1")
        elif mutation == "protection":
            db.execute("UPDATE protected_policy SET revision=revision+1")
    if mutation == "retirement":
        policy_change(fleet.registry, "RETIRE", [1])
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="scope changed"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before


def test_late_capacity_failure_rolls_back_every_policy_job_link_receipt_audit(fleet, capsys):
    with fleet.store._connection() as db:
        db.executemany("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at) VALUES (?,1,?,'QUEUED',?)",
                       [(str(uuid4()), IPv4Address(0xC6120000 + i).packed, NOW.isoformat()) for i in range(998)])
    before = fingerprint(fleet)
    capsys.readouterr()
    with pytest.raises(QueueFull, match="queue is full"):
        fleet.admit(**arguments(fleet))
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_caught_late_audit_failure_rolls_back_savepoint_but_not_outer_transaction(fleet, monkeypatch, capsys):
    values = arguments(fleet)
    before = fingerprint(fleet)
    original = fleet.store._insert_event
    def fail(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED":
            raise RuntimeError("Synthetic late audit failure")
    monkeypatch.setattr(fleet.store, "_insert_event", fail)
    capsys.readouterr()
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE devices SET hostname='outer-edit' WHERE id=4")
        with pytest.raises(RuntimeError, match="audit failure"):
            fleet.apply_admit(db, **values)
        assert db.in_transaction and db.execute("SELECT hostname FROM devices WHERE id=4").fetchone()[0] == "outer-edit"
        db.execute("UPDATE devices SET hostname='synthetic-4' WHERE id=4")
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_apply_does_not_commit_or_log_and_outer_rollback_discards_acceptance(fleet, capsys):
    values = arguments(fleet)
    before = fingerprint(fleet)
    capsys.readouterr()
    with fleet.store._connection() as db:
        with pytest.raises(ValueError, match="transaction"):
            fleet.apply_admit(db, **values)
        db.execute("BEGIN IMMEDIATE")
        result, logs = fleet.apply_admit(db, **values)
        assert result["status"] == "accepted" and logs and db.in_transaction
        assert not capsys.readouterr().out
        db.rollback()
    assert fingerprint(fleet) == before


def test_replay_after_cancellation_new_generation_pruning_restart_and_pause_is_observational(fleet, monkeypatch):
    values = arguments(fleet)
    fleet.admit(**values)
    fleet.queue.cancel(values["request_id"], "alice", False)
    policy_change(fleet.registry, "MAINTAIN", [1, 2])
    monkeypatch.setattr(fleet.queue, "_now", lambda: NOW + timedelta(days=367))
    fleet.queue.prune_completed(366)
    with fleet.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_requests WHERE id=?", (values["request_id"],)).fetchone()
        db.execute("UPDATE operation_executor SET mutations_suspended=1")
    restarted = ManagedFleetRemovals(ManagedShuns(fleet.store), fleet.queue)
    before = fingerprint(fleet)
    result = restarted.admit(**values)
    assert result["replayed"] and result["retired_targets"] == 2 and result["managed_revision"] == 3
    assert fingerprint(fleet) == before
    assert all(entry["generation"] == 2 and entry["enabled"] for entry in fleet.registry.snapshot()["entries"] if entry["device_id"] in {1, 2})


def test_same_key_concurrency_commits_once_different_keys_same_review_conflict(fleet):
    values = arguments(fleet)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: fleet.admit(**values), range(6)))
    assert sum(not result["replayed"] for result in results) == 1
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="scope changed"):
        fleet.admit(**{**values, "request_id": str(uuid4())})
    assert fingerprint(fleet) == before


def test_request_limit_counts_fleet_once_not_per_target_and_replay_bypasses_full_ledger(fleet, monkeypatch):
    for _ in range(9):
        fleet.queue.enqueue(str(uuid4()), [(3, OTHER)], "alice", "Alice", ("Operator",))
    values = arguments(fleet)
    fleet.admit(**values)
    with pytest.raises(QueueFull, match="10 operation"):
        fleet.admit(**arguments(fleet))
    monkeypatch.setattr(managed_fleet_removals, "MAX_FLEET_RECORDS", 1)
    before = fingerprint(fleet)
    with pytest.raises(QueueFull, match="ledger"):
        fleet.admit(**arguments(fleet, subject="bob"))
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before


def test_queue_coalescing_cancellation_preserves_independent_remove_and_retirement(fleet):
    existing = str(uuid4())
    fleet.queue.enqueue(existing, [(3, IP)], "bob", "Bob", ("Operator",))
    values = arguments(fleet)
    fleet.admit(**values)
    assert fleet.queue.status()["counts"] == {"QUEUED": 3}
    fleet.queue.cancel(values["request_id"], "alice", False)
    assert fleet.queue.status()["counts"] == {"CANCELLED": 2, "QUEUED": 1}
    assert all(not entry["enabled"] for entry in fleet.registry.snapshot()["entries"])


def test_recovery_backup_cancels_queue_but_preserves_immutable_receipt_and_retirement(fleet, tmp_path):
    values = arguments(fleet)
    fleet.admit(**values)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    result = run_offline(fleet.store.path, directory / "before-suspend.db", "suspend", "synthetic-operator")
    assert result["queued_cancelled"] == 3 and result["requests_cancelled"] == 1
    before = fingerprint(fleet)
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before
    assert fleet.queue.mutations_suspended()
    assert all(not entry["enabled"] for entry in fleet.registry.snapshot()["entries"])
    with pytest.raises(QueueConflict, match="suspended"):
        fleet.admit(**arguments(fleet))


@pytest.mark.parametrize("purpose", ["queue", "import", "policy", "handoff"])
def test_fleet_key_cannot_acquire_another_purpose_even_after_queue_pruning(fleet, purpose):
    values = arguments(fleet)
    fleet.admit(**values)
    fleet.queue.cancel(values["request_id"], "alice", False)
    # Synthetic retention leaves the retained authority in place.
    with fleet.store._connection() as db:
        db.execute("DELETE FROM operation_links WHERE request_id=?", (values["request_id"],))
        db.execute("DELETE FROM operation_requests WHERE id=?", (values["request_id"],))
    before = fingerprint(fleet)
    with pytest.raises((QueueConflict, ManagedConflict), match="[Ff]leet"):
        if purpose == "queue":
            fleet.queue.enqueue(values["request_id"], [(1, IP), (2, IP), (3, IP)], "alice", "Alice", ("Operator",), scope="managed_fleet_removal")
        elif purpose == "import":
            fleet.queue.enqueue(values["request_id"], [(1, IP)], "alice", "Alice", ("Operator",), source="manual_import",
                                scope="import", policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
        elif purpose == "policy":
            policy_change(fleet.registry, "RETIRE", [1], values["request_id"])
        else:
            single = ManagedRemovals(fleet.registry, fleet.queue)
            single.initialize()
            before = fingerprint(fleet)
            revision = fleet.registry.snapshot()["revision"]
            single.admit(values["request_id"], 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                         "alice", "Alice", ("Operator",))
    assert fingerprint(fleet) == before


def test_replay_binds_actor_exact_scope_ttl_reason_digest_and_current_role(fleet):
    values = arguments(fleet)
    fleet.admit(**values)
    before = fingerprint(fleet)
    for overrides in ({"subject": "bob"}, {"ttl_seconds": 60}, {"reason": "changed"}):
        changed = arguments(fleet, **{**values, **overrides})
        with pytest.raises(ManagedConflict, match="another fleet"):
            fleet.admit(**changed)
    for overrides in ({"confirmation_digest": "0" * 64}, {"confirmation_digest": "неправильно"}, {"request_id": "invalid"}):
        with pytest.raises(ValueError):
            fleet.admit(**{**values, **overrides})
    with pytest.raises(PermissionError):
        fleet.admit(**{**values, "roles": ("Viewer",)})
    assert fingerprint(fleet) == before


def test_authority_is_immutable_retained_and_phase_cannot_be_rearmed(fleet):
    values = arguments(fleet)
    fleet.admit(**values)
    for statement in ("DELETE FROM managed_fleet_removals", "UPDATE managed_fleet_removals SET payload_json='{}'",
                      "UPDATE managed_fleet_removals SET expires_at='2099'", "UPDATE managed_fleet_removals SET phase='ADMITTING'"):
        with fleet.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(statement)


def test_expiry_inside_admission_rolls_back_and_does_not_extend_deadline(fleet, monkeypatch):
    values = arguments(fleet, ttl_seconds=1)
    clock = iter([NOW, NOW + timedelta(seconds=2)])
    monkeypatch.setattr(fleet.queue, "_now", lambda: next(clock))
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="expired during admission"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before


def test_expiry_after_queue_and_audit_still_rolls_back_whole_admission(fleet, monkeypatch, capsys):
    values = arguments(fleet, ttl_seconds=1)
    clock = [NOW]
    monkeypatch.setattr(fleet.queue, "_now", lambda: clock[0])
    original = fleet.queue.apply_enqueue
    def slow_enqueue(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(seconds=2)
        return result
    monkeypatch.setattr(fleet.queue, "apply_enqueue", slow_enqueue)
    before = fingerprint(fleet)
    capsys.readouterr()
    with pytest.raises(QueueConflict, match="expired during admission"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_subsecond_admission_preserves_valid_one_second_ttl_without_extending_it(fleet, monkeypatch):
    values = arguments(fleet, ttl_seconds=1)
    clock = iter([NOW])
    monkeypatch.setattr(fleet.queue, "_now", lambda: next(clock, NOW + timedelta(milliseconds=500)))
    assert fleet.admit(**values)["status"] == "accepted"
    with fleet.store._connection() as db:
        root = db.execute("SELECT requested_at,expires_at FROM managed_fleet_removals").fetchone()
        queued = db.execute("SELECT requested_at,expires_at FROM operation_requests").fetchone()
        assert tuple(root) == tuple(queued)
        assert datetime.fromisoformat(root["expires_at"]) - datetime.fromisoformat(root["requested_at"]) == timedelta(seconds=1)


def test_preused_derived_retirement_key_refuses_even_with_matching_current_scope(fleet):
    key = str(uuid4())
    derived = str(uuid5(UUID(key), "managed-fleet-retirement"))
    policy_change(fleet.registry, "RETIRE", [4], derived)
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="Derived retirement key"):
        fleet.admit(**arguments(fleet, request_id=key))
    assert fingerprint(fleet) == before


def test_recovery_refuses_inconsistent_committed_transitional_fleet_authority(fleet):
    values = arguments(fleet)
    fleet.admit(**values)
    with fleet.store._connection() as db:
        db.execute("DROP TRIGGER managed_fleet_phase_monotonic")
        db.execute("UPDATE managed_fleet_removals SET phase='ADMITTING'")
    before = fingerprint(fleet)
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="Transitional fleet"):
            apply_recovery_control(db, fleet.store, "suspend", "synthetic-operator", now=NOW)
    assert fingerprint(fleet) == before


@pytest.mark.parametrize("purpose", ["queue", "import", "policy", "handoff"])
def test_existing_keys_cannot_acquire_fleet_semantics(fleet, purpose):
    key = str(uuid4())
    if purpose == "queue":
        fleet.queue.enqueue(key, [(3, OTHER)], "alice", "Alice", ("Operator",))
    elif purpose == "import":
        fleet.queue.enqueue(key, [(3, OTHER)], "alice", "Alice", ("Operator",), source="manual_import",
                            scope="import", policy_revision=0, confirmation_digest=canonical_import([(3, OTHER)], 0)[2])
    elif purpose == "policy":
        policy_change(fleet.registry, "RETIRE", [4], key)
    else:
        single = ManagedRemovals(fleet.registry, fleet.queue)
        single.initialize()
        revision = fleet.registry.snapshot()["revision"]
        single.admit(key, 4, IP, revision, canonical_managed_removal(4, IP, revision)[1],
                     "alice", "Alice", ("Operator",))
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="existing key"):
        fleet.admit(**arguments(fleet, request_id=key))
    assert fingerprint(fleet) == before


def test_retirement_child_key_is_not_a_cleanup_or_import_key(fleet):
    fleet.admit(**arguments(fleet))
    with fleet.store._connection() as db:
        key = db.execute("SELECT retirement_request_id FROM managed_fleet_removals").fetchone()[0]
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="reserved"):
        fleet.queue.enqueue(key, [(3, IP)], "alice", "Alice", ("Operator",))
    assert fingerprint(fleet) == before


def test_successful_apply_logs_are_returned_only_and_caller_can_commit(fleet, capsys):
    values = arguments(fleet)
    capsys.readouterr()
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result, logs = fleet.apply_admit(db, **values)
        assert db.in_transaction and result["target_count"] == 3 and len(logs) == 4
        assert not capsys.readouterr().out
    before = fingerprint(fleet)
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before
    assert not capsys.readouterr().out


def test_racing_different_keys_with_same_review_have_one_winner(fleet):
    first = arguments(fleet)
    def attempt(_):
        try:
            return fleet.admit(**{**first, "request_id": str(uuid4())})
        except ManagedConflict:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(result is not None for result in results) == 1
    assert fleet.queue.status()["counts"] == {"QUEUED": 3}


def test_queue_and_lease_rules_are_not_bypassed_and_failed_cleanup_keeps_retirement(fleet):
    fleet.admit(**arguments(fleet))
    with pytest.raises(QueueConflict, match="lease"):
        fleet.queue.claim_removal(1, "missing-worker", fleet.queue.cutoff())
    assert fleet.queue.claim_cycle("worker", 135)
    assert fleet.queue.claim_removal(1, "worker", 0) is None
    job = fleet.queue.claim_removal(1, "worker", fleet.queue.cutoff())
    fleet.queue.finish_removal(job["id"], "worker", "UNVERIFIED")
    assert all(not entry["enabled"] for entry in fleet.registry.snapshot()["entries"])
    assert fleet.queue.status()["counts"]["UNVERIFIED"] == 1


def test_fleet_only_orphan_schema_is_unknown_to_policy_reads_and_recovery(fleet):
    with fleet.store._connection() as db:
        for table in ("managed_shun_targets", "managed_shun_requests", "managed_shun_registry"):
            db.execute(f"DROP TABLE {table}")
    with pytest.raises(ValueError, match="unavailable"):
        fleet.registry.metadata()
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="Fleet authority without"):
            apply_recovery_control(db, fleet.store, "suspend", "synthetic-operator", now=NOW)


def test_waiting_single_target_cleanup_is_not_absorbed_by_fleet_request(fleet):
    single = ManagedRemovals(fleet.registry, fleet.queue)
    single.initialize()
    add(fleet, 1, running=True)
    revision = fleet.registry.snapshot()["revision"]
    single.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                 "alice", "Alice", ("Operator",))
    # Target 1 remains in the reviewed union through an independent observation.
    fleet.store.record_observed_shun(1, IP, "outside")
    with fleet.store._connection() as db:
        job = db.execute("SELECT * FROM operation_jobs WHERE action='ADD'").fetchone()
        fleet.queue._finish(db, job, "UNVERIFIED", "Synthetic settlement")
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="waiting cleanup"):
        fleet.admit(**arguments(fleet))
    assert fingerprint(fleet) == before
