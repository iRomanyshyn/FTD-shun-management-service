"""Offline cleanup handoffs: real temporary SQLite/queue, no FTD or real agent."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4, uuid5

import pytest

from ftd_shun_manager import managed_removals
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_removals import ManagedRemovals, canonical_managed_removal
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns, canonical_managed_change
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")


@pytest.fixture
def handoffs(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    registry, queue = ManagedShuns(store), OperationQueue(store)
    registry.initialize()
    queue.initialize()
    handoffs = ManagedRemovals(registry, queue)
    handoffs.initialize()
    clock = [datetime(2026, 10, 17, tzinfo=UTC)]
    monkeypatch.setattr(queue, "_now", lambda: clock[0])
    handoffs.test_clock = clock
    maintain(handoffs)
    return handoffs


def maintain(handoffs, request_id=None):
    revision = handoffs.registry.snapshot()["revision"]
    return handoffs.registry.change(
        request_id or str(uuid4()), "MAINTAIN", [(1, IP)], revision, 0,
        canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)[2], "alice", "Alice", ("Operator",),
    )


def arguments(handoffs, **overrides):
    values = {"request_id": str(uuid4()), "device_id": 1, "ip": IP,
              "managed_revision": handoffs.registry.snapshot()["revision"],
              "subject": "alice", "display_name": "Alice", "roles": ("Operator",),
              "ttl_seconds": 900, "reason": "Explicit stop and remove", **overrides}
    values["confirmation_digest"] = canonical_managed_removal(
        values["device_id"], values["ip"], values["managed_revision"], values["ttl_seconds"], values["reason"],
    )[1]
    return values


def add(handoffs, *, running=True):
    queue = handoffs.queue
    queue.enqueue(str(uuid4()), [(1, IP)], "creator", "Creator", ("Operator",), source="manual_import",
                  scope="import", policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
    if not running:
        return None
    assert queue.claim_cycle("worker", 135)
    return queue.claim_addition(1, "worker", queue.cutoff(), execution_enabled=True)


def row(handoffs):
    return handoffs.snapshot()["items"][0]


def test_application_does_not_initialize_or_expose_handoffs(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "normal.db")
    app = create_app(replace(Settings.from_environment(), database_path=store.path,
                             device_inventory_path=None, agent_mode="disabled"), store)
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_removal_handoffs'").fetchone()
    assert not any("handoff" in route.path for route in app.routes)


def test_no_running_add_retires_and_queues_atomically_without_claiming_success(handoffs):
    request = arguments(handoffs)
    result = handoffs.admit(**request)
    assert not result["waiting_for_add"] and result["status"] == "accepted"
    assert row(handoffs)["state"] == "ADMITTED" and row(handoffs)["queue_state"] == "QUEUED"
    assert handoffs.queue.status()["counts"] == {"QUEUED": 1}
    assert not handoffs.registry.snapshot()["entries"][0]["enabled"]
    assert not handoffs.store.list_active_shuns()
    with handoffs.store._connection() as db:
        grant = db.execute("SELECT * FROM operation_requests WHERE id=?", (request["request_id"],)).fetchone()
        original = db.execute("SELECT * FROM managed_removal_handoffs").fetchone()
        assert grant["requested_at"] == original["requested_at"]
        assert grant["expires_at"] <= original["expires_at"]


def test_running_add_is_not_cancelled_or_overlapped_and_wait_reserves_capacity(handoffs):
    original = add(handoffs)
    result = handoffs.admit(**arguments(handoffs))
    assert result["waiting_for_add"]
    assert row(handoffs)["state"] == "WAITING_ADD" and row(handoffs)["predecessor_id"] == original["id"]
    assert handoffs.advance("worker") == 0
    assert handoffs.queue.status()["counts"] == {"RUNNING": 1}
    assert not handoffs.registry.snapshot()["entries"][0]["enabled"]
    with handoffs.store._connection() as db:
        assert handoffs.queue._pending_count(db) == 2
        assert handoffs.queue._active_request_count(db) == 2
    with pytest.raises(ManagedConflict, match="cleanup"):
        maintain(handoffs)
    with pytest.raises(QueueConflict, match="waiting"):
        handoffs.queue.enqueue(str(uuid4()), [(1, IP)], "other", "Other", ("Operator",),
                               source="manual_import", scope="import", policy_revision=0,
                               confirmation_digest=canonical_import([(1, IP)], 0)[2])


@pytest.mark.parametrize("outcome", ["UNVERIFIED", "NOOP", "VERIFIED"])
def test_settled_add_allows_separately_authorized_remove_without_replaying_add(handoffs, outcome):
    original = add(handoffs)
    values = arguments(handoffs, ttl_seconds=120)
    handoffs.admit(**values)
    handoffs.test_clock[0] += timedelta(seconds=30)
    result = (AdditionResult(True, "management") if outcome == "VERIFIED" else
              AdditionResult(False) if outcome == "NOOP" else outcome)
    handoffs.queue.finish_addition(original["id"], "worker", result)
    old_cutoff = handoffs.queue.cutoff()
    assert handoffs.advance("worker") == 1
    assert handoffs.advance("worker") == 0
    # Materialized cleanup is new queue work: do not bypass the cycle cutoff.
    assert handoffs.queue.claim_removal(1, "worker", old_cutoff) is None
    cleanup = handoffs.queue.claim_removal(1, "worker", handoffs.queue.cutoff())
    assert cleanup is not None and cleanup["action"] == "REMOVE"
    assert cleanup["id"] != original["id"]
    with handoffs.store._connection() as db:
        original_state = db.execute("SELECT state FROM operation_jobs WHERE id=?", (original["id"],)).fetchone()[0]
        grant = db.execute("SELECT * FROM operation_requests WHERE id=?", (values["request_id"],)).fetchone()
        assert original_state == outcome
        assert grant["actor_subject"] == "alice"
        assert grant["expires_at"] == "2026-10-17T00:02:00.000Z"
        assert grant["requested_at"] == "2026-10-17T00:00:00.000Z"
    if outcome != "VERIFIED":
        assert not handoffs.store.list_active_shuns()


def test_known_prewrite_deferral_is_superseded_not_sent_again(handoffs):
    original = add(handoffs)
    handoffs.admit(**arguments(handoffs))
    handoffs.queue.defer_addition(original["id"], "worker")
    assert handoffs.advance("worker") == 1
    assert handoffs.queue.status()["counts"] == {"CANCELLED": 1, "QUEUED": 1}
    assert handoffs.queue.claim_addition(1, "worker", handoffs.queue.cutoff(), execution_enabled=True) is None


def test_lease_recovery_retains_add_uncertainty_but_permits_valid_cleanup(handoffs):
    original = add(handoffs)
    handoffs.admit(**arguments(handoffs))
    handoffs.test_clock[0] += timedelta(seconds=136)
    assert handoffs.queue.claim_cycle("recovery", 135)
    with pytest.raises(QueueConflict, match="lease"):
        handoffs.advance("worker")
    assert handoffs.advance("recovery") == 1
    with handoffs.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (original["id"],)).fetchone()[0] == "UNVERIFIED"


def test_expiry_leaves_maintenance_stopped_and_does_not_touch_running_add(handoffs):
    add(handoffs)
    handoffs.admit(**arguments(handoffs, ttl_seconds=10))
    handoffs.test_clock[0] += timedelta(seconds=10)
    assert handoffs.advance("worker") == 0
    assert row(handoffs)["state"] == "EXPIRED"
    assert handoffs.queue.status()["counts"] == {"RUNNING": 1}
    assert not handoffs.registry.snapshot()["entries"][0]["enabled"]


def test_cancel_waiting_only_preserves_add_and_actor_attribution(handoffs):
    add(handoffs)
    values = arguments(handoffs)
    handoffs.admit(**values)
    with pytest.raises(PermissionError):
        handoffs.cancel_waiting(values["request_id"], "bob", "Bob", ("Operator",))
    handoffs.cancel_waiting(values["request_id"], "admin", "Administrator", ("Administrator",))
    handoffs.cancel_waiting(values["request_id"], "admin", "Administrator", ("Administrator",))
    assert handoffs.advance("worker") == 0
    assert row(handoffs)["state"] == "CANCELLED"
    assert handoffs.queue.status()["counts"] == {"RUNNING": 1}
    assert not handoffs.registry.snapshot()["entries"][0]["enabled"]
    events = handoffs.store.list_events()
    assert next(e for e in events if e["event_type"] == "MANAGED_SHUN_CLEANUP_CANCELLED")["actor_subject"] == "admin"


def test_replay_after_cancel_and_new_generation_never_retires_again_or_requeues(handoffs):
    values = arguments(handoffs)
    handoffs.admit(**values)
    handoffs.queue.cancel(values["request_id"], "alice", False)
    maintain(handoffs)
    before = handoffs.registry.snapshot()
    assert handoffs.admit(**values)["replayed"]
    assert handoffs.registry.snapshot() == before
    assert before["entries"][0]["generation"] == 2 and before["entries"][0]["enabled"]
    with pytest.raises(ManagedConflict, match="key"):
        handoffs.admit(**{**values, "subject": "bob"})


def test_unstarted_import_conflict_is_not_silently_cancelled(handoffs):
    add(handoffs, running=False)
    before = handoffs.registry.snapshot()
    with pytest.raises(QueueConflict, match="Unstarted"):
        handoffs.admit(**arguments(handoffs))
    assert handoffs.registry.snapshot() == before
    assert handoffs.snapshot()["counts"] == {}


def test_namespace_binding_roles_digest_and_current_revision(handoffs):
    values = arguments(handoffs)
    for override, error in [({"subject": " "}, PermissionError), ({"roles": ("Viewer",)}, PermissionError),
                            ({"confirmation_digest": "bad"}, ValueError), ({"request_id": "not-uuid"}, ValueError)]:
        with pytest.raises(error):
            handoffs.admit(**{**values, **override})
    add(handoffs)
    handoffs.admit(**values)
    with pytest.raises(QueueConflict, match="reserved"):
        handoffs.queue.enqueue(values["request_id"], [(1, IP)], "alice", "Alice", ("Operator",))
    with pytest.raises(ManagedConflict, match="keys"):
        maintain(handoffs, values["request_id"])
    with pytest.raises(QueueConflict, match="waiting"):
        handoffs.admit(**arguments(handoffs, subject="bob"))


def test_late_admission_failure_rolls_back_retirement_ledger_events_and_logs(handoffs, monkeypatch, capsys):
    before = handoffs.registry.snapshot()
    events = handoffs.store.list_events()
    capsys.readouterr()
    def fail(*args, **kwargs):
        raise QueueFull("Synthetic later admission failure")
    monkeypatch.setattr(handoffs.queue, "apply_enqueue", fail)
    with pytest.raises(QueueFull):
        handoffs.admit(**arguments(handoffs))
    assert handoffs.registry.snapshot() == before
    assert handoffs.store.list_events() == events
    assert handoffs.snapshot()["counts"] == {}
    assert not capsys.readouterr().out


def test_missing_predecessor_is_attention_not_permission_to_send_cleanup(handoffs):
    original = add(handoffs)
    handoffs.admit(**arguments(handoffs))
    with handoffs.store._connection() as db:
        db.execute("DELETE FROM operation_jobs WHERE id=?", (original["id"],))
    assert handoffs.advance("worker") == 0
    assert row(handoffs)["state"] == "ATTENTION"
    assert handoffs.queue.status()["counts"] == {}
    with pytest.raises(ManagedConflict, match="attention"):
        maintain(handoffs)


def test_retention_preserves_waiting_predecessor_and_immutable_authority(handoffs, tmp_path):
    original = add(handoffs)
    values = arguments(handoffs)
    handoffs.admit(**values)
    handoffs.queue.finish_addition(original["id"], "worker", "UNVERIFIED")
    handoffs.test_clock[0] += timedelta(days=367)
    handoffs.queue.prune_completed(366)
    with handoffs.store._connection() as db:
        assert db.execute("SELECT 1 FROM operation_jobs WHERE id=?", (original["id"],)).fetchone()
        for sql in ("UPDATE managed_removal_handoffs SET expires_at='2099-01-01'", "DELETE FROM managed_removal_handoffs"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
        db.rollback()  # Failed writes can retain a transaction; backup needs no writer.
        with sqlite3.connect(tmp_path / "backup.db") as target:
            db.backup(target)
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    restored = Store(tmp_path / "backup.db")
    view = ManagedRemovals(ManagedShuns(restored), OperationQueue(restored))
    assert view.snapshot() == handoffs.snapshot()
    assert view.admit(**values)["replayed"]


def test_ledger_full_refuses_before_retirement_and_logs_omit_reason(handoffs, monkeypatch, capsys):
    capsys.readouterr()
    values = arguments(handoffs, reason="Private operator note")
    handoffs.admit(**values)
    assert "Private operator note" not in capsys.readouterr().out
    monkeypatch.setattr(managed_removals, "MAX_HANDOFF_RECORDS", 1)
    with pytest.raises(QueueFull, match="ledger"):
        handoffs.admit(**arguments(handoffs))
    assert handoffs.admit(**values)["replayed"]
    payload = canonical_managed_removal(1, IP, 1)[0]
    assert json.loads(payload)["mode"] == "stop_maintenance_and_remove"


def test_simultaneous_same_key_admission_records_one_retirement_and_wait(handoffs):
    add(handoffs)
    values = arguments(handoffs)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: handoffs.admit(**values), range(6)))
    assert sum(not result["replayed"] for result in results) == 1
    assert handoffs.snapshot()["counts"] == {"WAITING_ADD": 1}
    assert handoffs.registry.snapshot()["revision"] == 2


def seed_pending_jobs(handoffs, count):
    with handoffs.store._connection() as db:
        db.executemany("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at)
            VALUES (?,1,?,'QUEUED','2026-10-17T00:00:00.000Z')""",
            [(str(uuid4()), IPv4Address(0xC6120000 + i).packed) for i in range(count)])


def test_wait_reservation_cannot_exceed_queue_capacity_or_leak_retirement(handoffs):
    add(handoffs)
    seed_pending_jobs(handoffs, 999)
    before = handoffs.registry.snapshot()
    with pytest.raises(QueueFull, match="reserved cleanups"):
        handoffs.admit(**arguments(handoffs))
    assert handoffs.registry.snapshot() == before
    assert handoffs.snapshot()["counts"] == {}


def test_ordinary_admissions_respect_reserved_cleanup_capacity(handoffs):
    add(handoffs)
    handoffs.admit(**arguments(handoffs))
    seed_pending_jobs(handoffs, 998)
    with pytest.raises(QueueFull):
        handoffs.queue.enqueue(str(uuid4()), [(1, IPv4Address("198.51.100.252"))], "bob", "Bob", ("Operator",))
    with handoffs.store._connection() as db:
        assert handoffs.queue._pending_count(db) == 1000
        assert db.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 1


def test_wait_only_requests_share_normal_actor_rate_limit_even_after_cancel(handoffs):
    add(handoffs)
    for _ in range(10):
        values = arguments(handoffs)
        handoffs.admit(**values)
        handoffs.cancel_waiting(values["request_id"], "alice", "Alice", ("Operator",))
        maintain(handoffs)
    before = handoffs.registry.snapshot()
    with pytest.raises(QueueFull, match="10 operation"):
        handoffs.admit(**arguments(handoffs))
    assert handoffs.registry.snapshot() == before


def test_late_handoff_audit_failure_rolls_back_admission_and_suppresses_success_logs(handoffs, monkeypatch, capsys):
    original = add(handoffs)
    handoffs.admit(**arguments(handoffs))
    handoffs.queue.finish_addition(original["id"], "worker", "UNVERIFIED")
    events = handoffs.store.list_events()
    capsys.readouterr()
    event = handoffs._event
    def fail_after_event(db, row, name, *args, **kwargs):
        event(db, row, name, *args, **kwargs)
        if name == "MANAGED_SHUN_CLEANUP_QUEUED":
            raise RuntimeError("Synthetic later audit failure")
    monkeypatch.setattr(handoffs, "_event", fail_after_event)
    with pytest.raises(RuntimeError, match="audit failure"):
        handoffs.advance("worker")
    assert row(handoffs)["state"] == "WAITING_ADD"
    assert handoffs.queue.status()["counts"] == {"UNVERIFIED": 1}
    assert handoffs.store.list_events() == events
    assert not capsys.readouterr().out


def test_pruned_queue_key_cannot_requeue_old_cleanup_or_revoke_new_generation(handoffs):
    values = arguments(handoffs)
    handoffs.admit(**values)
    assert handoffs.queue.claim_cycle("worker", 135)
    cleanup = handoffs.queue.claim_removal(1, "worker", handoffs.queue.cutoff())
    handoffs.queue.finish_removal(cleanup["id"], "worker", "NOOP")
    maintain(handoffs)
    before = handoffs.registry.snapshot()
    handoffs.test_clock[0] += timedelta(days=367)
    handoffs.queue.prune_completed(366)
    assert handoffs.admit(**values)["replayed"]
    assert handoffs.registry.snapshot() == before
    assert handoffs.queue.status()["counts"] == {}
    with pytest.raises(QueueConflict, match="reserved"):
        handoffs.queue.enqueue(values["request_id"], [(1, IP)], "alice", "Alice", ("Operator",),
                               scope="managed_device_removal")


def test_failed_cleanup_admission_keeps_retirement_and_original_add_uncertainty(handoffs):
    original = add(handoffs)
    handoffs.admit(**arguments(handoffs))
    handoffs.queue.finish_addition(original["id"], "worker", "UNVERIFIED")
    handoffs.store.upsert_device(Device(1, "lab", IPv4Address("192.0.2.1"), False), "ssh-ed25519 AAAA")
    assert handoffs.advance("worker") == 0
    assert row(handoffs)["state"] == "ATTENTION"
    assert handoffs.queue.status()["counts"] == {"UNVERIFIED": 1}
    assert not handoffs.registry.snapshot()["entries"][0]["enabled"]


def test_preused_derived_retirement_key_cannot_leave_new_generation_enabled(handoffs):
    root = str(uuid4())
    key = str(uuid5(UUID(root), "managed-retirement"))
    revision = handoffs.registry.snapshot()["revision"]
    digest = canonical_managed_change("RETIRE", [(1, IP)], revision, 0, reason="Explicit stop and remove")[2]
    handoffs.registry.change(key, "RETIRE", [(1, IP)], revision, 0, digest,
                             "alice", "Alice", ("Operator",), reason="Explicit stop and remove")
    maintain(handoffs)
    before = handoffs.registry.snapshot()
    with pytest.raises(ManagedConflict, match="Derived retirement"):
        handoffs.admit(**arguments(handoffs, request_id=root, managed_revision=revision))
    assert handoffs.registry.snapshot() == before
    assert before["entries"][0]["enabled"]
    assert handoffs.snapshot()["counts"] == {} and handoffs.queue.status()["counts"] == {}
