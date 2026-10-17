"""Caller-owned admission transactions; synthetic SQLite only, no device dispatch."""

import json
import sqlite3
from contextlib import contextmanager
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_shuns import ManagedShuns, canonical_managed_change
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.252")
TABLES = ("operation_requests", "operation_jobs", "operation_links", "operation_executor",
          "manual_import_batches", "shun_import_origins", "shun_state", "shun_events")


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f"lab-{device}", IPv4Address(f"192.0.2.{device}"), True),
                            "ssh-ed25519 AAAA")
    queue = OperationQueue(store)
    queue.initialize()
    return queue


def values(**overrides):
    return {"request_id": str(uuid4()), "targets": [(1, IP)], "subject": "alice",
            "display_name": "Alice", "roles": ("Operator",), **overrides}


def state(queue):
    with queue.store._connection() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in TABLES}


def managed_values(registry, action):
    revision = registry.snapshot()["revision"]
    return {"request_id": str(uuid4()), "action": action, "targets": [(1, IP)],
            "managed_revision": revision, "protected_revision": 0,
            "confirmation_digest": canonical_managed_change(action, [(1, IP)], revision, 0)[2],
            "subject": "alice", "display_name": "Alice", "roles": ("Operator",)}


def test_requires_outer_transaction_without_opening_one_or_initializing_policy(queue):
    before = state(queue)
    with queue.store._connection() as db:
        with pytest.raises(ValueError, match="caller-owned transaction"):
            queue.apply_enqueue(db, **values())
        assert not db.in_transaction
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_shun_%'").fetchall()
    assert state(queue) == before


def test_composed_admission_stays_invisible_and_silent_until_outer_commit(queue, capsys):
    request = values()
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result, logs = queue.apply_enqueue(db, **request)
        assert db.in_transaction
        assert result == {"operation_id": request["request_id"], "status": "accepted", "replayed": False}
        assert len(logs) == 1 and logs[0]["event"] == "queue.request.accepted"
        assert state(queue) == before  # Another connection cannot see uncommitted work.
        assert db.execute("SELECT COUNT(*) FROM operation_jobs").fetchone()[0] == 1
        assert not capsys.readouterr().out
    assert state(queue) != before
    assert not capsys.readouterr().out, "Only the caller can emit returned logs after commit"
    with queue.store._connection() as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_outer_rollback_discards_admission_events_revision_and_all_logs(queue, capsys):
    before = state(queue)
    with pytest.raises(RuntimeError, match="later failure"), queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _, logs = queue.apply_enqueue(db, **values())
        assert logs
        raise RuntimeError("Synthetic later failure")
    assert state(queue) == before
    assert not capsys.readouterr().out


@pytest.mark.parametrize("source", ["manual", "manual_import"])
def test_caught_late_failure_restores_savepoint_but_preserves_earlier_caller_work(queue, source, capsys):
    targets = [(1, IP), (9, OTHER)]  # Fail only after the first target was inserted/audited.
    request = values(targets=targets, source=source)
    if source == "manual_import":
        request.update(scope="import", policy_revision=0,
                       confirmation_digest=canonical_import(targets, 0)[2])
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE devices SET hostname='caller-change' WHERE id=2")
        with pytest.raises(ValueError, match="unknown or disabled"):
            queue.apply_enqueue(db, **request)
        assert db.in_transaction
        assert db.execute("SELECT hostname FROM devices WHERE id=2").fetchone()[0] == "caller-change"
        assert db.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM shun_events").fetchone()[0] == 0
    assert state(queue) == before
    assert not capsys.readouterr().out
    assert next(device for device in queue.store.list_devices() if device.id == 2).hostname == "caller-change"


def test_injected_audit_failure_rolls_back_even_if_caller_catches_it(queue, monkeypatch, capsys):
    original = queue._event
    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        if args[1] == "SHUN_REMOVE_REQUESTED":
            raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(queue, "_event", fail_after_insert)
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="audit failure"):
            queue.apply_enqueue(db, **values())
    assert state(queue) == before
    assert not capsys.readouterr().out


def test_same_key_replay_is_silent_does_not_bump_revision_or_renew_authority(queue, capsys):
    request = values()
    queue.enqueue(**request)
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["request_id"] == request["request_id"]
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result, logs = queue.apply_enqueue(db, **request)
        assert result["replayed"] and logs == []
        with pytest.raises(QueueConflict, match="key"):
            queue.apply_enqueue(db, **{**request, "subject": "bob"})
    assert state(queue) == before
    assert not capsys.readouterr().out


def test_two_actors_can_compose_coalesced_admissions_without_changing_public_result(queue, capsys):
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        first, first_logs = queue.apply_enqueue(db, **values())
        second, second_logs = queue.apply_enqueue(db, **values(subject="bob", display_name="Bob"))
        assert first["operation_id"] != second["operation_id"]
        assert first_logs[0]["operation_id"] == second_logs[0]["operation_id"]
        assert not first_logs[0]["coalesced"] and second_logs[0]["coalesced"]
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert len(queue.status()["items"][0]["requests"]) == 2
    assert not capsys.readouterr().out


def test_capacity_failure_rolls_back_partial_coalescing_inside_caught_savepoint(queue, capsys):
    targets = [(1, IPv4Address(0xC6120000 + index)) for index in range(1000)]
    queue.enqueue(**values(targets=targets))
    capsys.readouterr()
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(QueueFull):
            queue.apply_enqueue(db, **values(subject="bob", targets=[targets[0], (2, IP)]))
    assert state(queue) == before
    assert not capsys.readouterr().out


@pytest.mark.parametrize("overrides,error", [
    ({"roles": ("Viewer",)}, PermissionError),
    ({"ttl_seconds": 901}, ValueError),
    ({"source": "managed_policy"}, ValueError),  # No new system admission authority.
    ({"source": "manual_import", "scope": "import", "policy_revision": 0,
      "confirmation_digest": "wrong"}, ValueError),
])
def test_composition_cannot_bypass_existing_role_ttl_source_or_confirmation_checks(queue, overrides, error):
    before = state(queue)
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(error):
            queue.apply_enqueue(db, **values(**overrides))
    assert state(queue) == before


def test_queue_and_retirement_share_one_outer_commit_with_no_false_observation(queue, capsys):
    registry = ManagedShuns(queue.store)
    registry.initialize()
    registry.change(**managed_values(registry, "MAINTAIN"))
    capsys.readouterr()
    # Transaction composition is a prerequisite, not an executable managed workflow.
    policy_request = managed_values(registry, "RETIRE")
    queue_request = values()
    before = registry.snapshot()
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        registry.apply_change(db, **policy_request)
        queue.apply_enqueue(db, **queue_request)
        assert registry.snapshot() == before
        assert queue.status()["counts"] == {}
    assert not registry.snapshot()["entries"][0]["enabled"]
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert queue.store.list_active_shuns() == []
    assert state(queue)["shun_import_origins"] == []
    assert not capsys.readouterr().out


@pytest.mark.parametrize("failure", ["disabled_device", "opposite_add", "later_failure"])
def test_queue_failure_rolls_back_managed_retirement_and_its_immutable_ledger(queue, failure, capsys):
    registry = ManagedShuns(queue.store)
    registry.initialize()
    registry.change(**managed_values(registry, "MAINTAIN"))
    if failure == "disabled_device":
        queue.store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), False), "ssh-ed25519 AAAA")
    if failure == "opposite_add":
        queue.enqueue(**values(source="manual_import", scope="import", policy_revision=0,
                               confirmation_digest=canonical_import([(1, IP)], 0)[2]))
    capsys.readouterr()
    before, before_policy = state(queue), registry.snapshot()
    with pytest.raises((ValueError, RuntimeError)), queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        registry.apply_change(db, **managed_values(registry, "RETIRE"))
        queue.apply_enqueue(db, **values())
        raise RuntimeError("Synthetic later_failure")
    assert state(queue) == before
    assert registry.snapshot() == before_policy
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 1
    assert not capsys.readouterr().out


def test_running_add_remains_running_and_conflict_is_not_bypassed_by_composition(queue, capsys):
    registry = ManagedShuns(queue.store)
    registry.initialize()
    registry.change(**managed_values(registry, "MAINTAIN"))
    queue.enqueue(**values(source="manual_import", scope="import", policy_revision=0,
                           confirmation_digest=canonical_import([(1, IP)], 0)[2]))
    assert queue.claim_cycle("synthetic-worker", 135)
    job = queue.claim_addition(1, "synthetic-worker", queue.cutoff(), execution_enabled=True)
    assert job is not None
    capsys.readouterr()
    before = state(queue)
    with pytest.raises(QueueConflict, match="Opposite"), queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        registry.apply_change(db, **managed_values(registry, "RETIRE"))
        queue.apply_enqueue(db, **values())
    assert state(queue) == before
    assert registry.snapshot()["entries"][0]["enabled"]
    assert queue.status()["counts"] == {"RUNNING": 1}
    assert not capsys.readouterr().out


def test_wrapper_does_not_emit_acceptance_if_outer_commit_fails(queue, monkeypatch, capsys):
    original = queue.store._connection
    @contextmanager
    def failed_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError("Synthetic commit failure")
    monkeypatch.setattr(queue.store, "_connection", failed_commit)
    with pytest.raises(sqlite3.OperationalError, match="commit failure"):
        queue.enqueue(**values())
    monkeypatch.setattr(queue.store, "_connection", original)
    assert queue.status()["counts"] == {}
    assert not capsys.readouterr().out
