"""Recovery uses disposable SQLite only, never the lab database or device."""

import asyncio
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager.agent_client import AgentClient
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.maintenance import apply_recovery_control, main, run_offline
from ftd_shun_manager.managed_removals import ManagedRemovals, canonical_managed_removal
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns, canonical_managed_change
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer

IP = IPv4Address("198.51.100.251")
NOW = datetime(2026, 10, 17, tzinfo=UTC)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    queue = OperationQueue(store)
    queue.initialize()
    monkeypatch.setattr(queue, "_now", lambda: NOW)
    return queue


def enqueue(queue, ip=IP, *, add=False, request_id=None):
    kwargs = ({"source": "manual_import", "scope": "import", "policy_revision": 0,
               "confirmation_digest": canonical_import([(1, ip)], 0)[2]} if add else {})
    return queue.enqueue(request_id or str(uuid4()), [(1, ip)], "alice", "Alice", ("Operator",), **kwargs)


def control(queue, action="suspend", now=NOW):
    with queue.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return apply_recovery_control(db, queue.store, action, "lab-operator", now=now)


def handoff(queue):
    registry = ManagedShuns(queue.store)
    registry.initialize()
    revision = registry.snapshot()["revision"]
    registry.change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, 0,
                    canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)[2],
                    "alice", "Alice", ("Operator",))
    cleanup = ManagedRemovals(registry, queue)
    cleanup.initialize()
    enqueue(queue, add=True)
    assert queue.claim_cycle("old-worker", 135)
    job = queue.claim_addition(1, "old-worker", queue.cutoff(), execution_enabled=True)
    revision = registry.snapshot()["revision"]
    reason = "Stop maintenance and remove"
    cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision, 900, reason)[1],
                  "alice", "Alice", ("Operator",), reason=reason)
    return cleanup, job


def test_suspend_is_atomic_preserves_uncertainty_cancels_wait_and_survives_restart(queue):
    cleanup, job = handoff(queue)
    enqueue(queue, IPv4Address("198.51.100.250"))
    result = control(queue)
    assert result["running_unverified"] == result["queued_cancelled"] == result["waiting_cancelled"] == 1
    assert result["requests_cancelled"] == 2
    queue.initialize()
    assert queue.mutations_suspended()
    assert queue.status()["mutations_suspended"]
    assert queue.status()["counts"] == {"UNVERIFIED": 1, "CANCELLED": 1}
    assert cleanup.snapshot()["items"][0]["state"] == "CANCELLED"
    assert cleanup.registry.snapshot()["restoration_suspended"]
    assert not cleanup.has_waiting() and cleanup.advance("anyone") == 0
    assert not queue.has_pending() and queue.claim_removal(1, "old-worker", queue.cutoff()) is None
    with pytest.raises(QueueConflict, match="suspended"):
        enqueue(queue)
    assert queue.delay() == 60
    queue._now = lambda: NOW + timedelta(seconds=61)
    assert queue.claim_cycle("read-only", 135)  # Monitoring is deliberately not paused.
    with queue.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "UNVERIFIED"
    records = [e for e in queue.store.list_events() if "RECOVERY" in e["event_type"]]
    assert len(records) == 4
    assert all(e["actor_subject"] == "maintenance:lab-operator" and not e["actor_roles"] for e in records)


def test_resume_never_resurrects_jobs_or_desired_restoration_and_old_key_is_read_only(queue):
    request_id = str(uuid4())
    original = enqueue(queue, request_id=request_id)
    control(queue)
    assert enqueue(queue, request_id=request_id) == {**original, "replayed": True}
    control(queue, "resume-mutations")
    assert not queue.mutations_suspended()
    assert queue.status()["counts"] == {"CANCELLED": 1}
    enqueue(queue)
    assert queue.status()["counts"] == {"CANCELLED": 1, "QUEUED": 1}
    with pytest.raises(ValueError, match="not suspended"):
        control(queue, "resume-mutations")


def test_managed_creation_and_cleanup_admission_blocked_but_retirement_allowed(queue):
    cleanup, _ = handoff(queue)
    control(queue)
    revision = cleanup.registry.snapshot()["revision"]
    with pytest.raises(ManagedConflict, match="suspended"):
        cleanup.registry.change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, 0,
                                canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)[2],
                                "alice", "Alice", ("Operator",))
    with pytest.raises(QueueConflict, match="suspended"):
        cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision, 900, "")[1],
                      "alice", "Alice", ("Operator",))
    cleanup.registry.change(str(uuid4()), "RETIRE", [(1, IP)], revision, 0,
                            canonical_managed_change("RETIRE", [(1, IP)], revision, 0)[2],
                            "alice", "Alice", ("Operator",))
    control(queue, "resume-mutations")
    assert cleanup.registry.snapshot()["restoration_suspended"]


def test_failure_rolls_back_controls_and_audit(queue, monkeypatch):
    enqueue(queue)
    before = queue.status()
    original = queue.store._insert_event

    def fail(*args, **kwargs):
        if args[1] == "RECOVERY_MUTATIONS_SUSPENDED":
            raise sqlite3.OperationalError("synthetic audit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(queue.store, "_insert_event", fail)
    with pytest.raises(sqlite3.OperationalError):
        control(queue)
    assert queue.status() == before
    assert not any("RECOVERY" in e["event_type"] for e in queue.store.list_events())


def test_checked_backup_is_private_prechange_and_never_overwritten(queue, tmp_path):
    enqueue(queue)
    parent = tmp_path / "backups"
    parent.mkdir(mode=0o700)
    backup = parent / "before.sqlite3"
    result = run_offline(queue.store.path, backup, "suspend", "trusted-host")
    assert result["queued_cancelled"] == 1 and queue.mutations_suspended()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT mutations_suspended FROM operation_executor").fetchone()[0] == 0
        assert db.execute("SELECT state FROM operation_jobs").fetchone()[0] == "QUEUED"
    with pytest.raises(FileExistsError):
        run_offline(queue.store.path, backup, "resume-mutations", "trusted-host")
    assert queue.mutations_suspended()
    parent.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        run_offline(queue.store.path, parent / "no.sqlite3", "suspend", "trusted-host")


def test_cli_requires_offline_and_resume_review_assertions_before_backup(queue, tmp_path):
    backup = tmp_path / "no.sqlite3"
    args = ["--database", str(queue.store.path), "--backup", str(backup), "--actor", "operator"]
    for flags in (["suspend"], ["resume-mutations", "--confirm-offline"]):
        with pytest.raises(SystemExit) as error:
            main([*flags, *args])
        assert error.value.code == 2 and not backup.exists()
    assert not queue.mutations_suspended()


def test_no_queue_initialization_partial_registry_refusal_and_transaction_required(queue):
    with queue.store._connection() as db:
        with pytest.raises(ValueError, match="transaction"):
            apply_recovery_control(db, queue.store, "suspend", "operator")
        db.execute("CREATE TABLE managed_shun_registry(id INTEGER)")
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="Partial"):
            apply_recovery_control(db, queue.store, "suspend", "operator")
    assert not queue.mutations_suspended()


class ReadOnlyAgent(AgentClient):
    def list_shuns(self, device_id):
        return [ObservedShun(IP, "management")]

    def remove_shun(self, *args):
        raise AssertionError("Recovery monitoring must never write")


def test_suspended_monitor_reads_without_trusted_policy_admission(queue):
    sync = Synchronizer(queue.store, ReadOnlyAgent(), 300, 60)
    control(queue)
    queue._now = lambda: NOW + timedelta(seconds=61)
    sync.queue._now = queue._now
    # Synthetic protected policy discovery must not produce work while paused.
    sync.policy.enabled_ips = lambda: frozenset({IP})
    asyncio.run(sync._sweep())
    assert sync.status()["last_error"] is None
    assert sync.store.list_active_shuns()[0].ip == IP
    assert queue.status()["counts"] == {}


def test_worker_default_off_strict_flag_and_socket_requirement(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED", raising=False)
    assert not Settings.from_environment().managed_removal_worker_enabled
    monkeypatch.setenv("FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED", "TRUE")
    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_environment()
    monkeypatch.setenv("FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED", "true")
    monkeypatch.setenv("FTD_SHUN_AGENT_MODE", "mock")
    with pytest.raises(ValueError, match="socket"):
        Settings.from_environment()
    monkeypatch.setenv("FTD_SHUN_AGENT_MODE", "socket")
    assert Settings.from_environment().managed_removal_worker_enabled


class SyntheticCycle:
    def __init__(self, agent):
        self.agent = agent
        self.closed = False
        self.initial_snapshot = list(agent.entries)

    def remove_shun(self, ip):
        self.agent.calls.append("remove")
        self.agent.entries = []
        return True

    def finish(self):
        self.agent.calls.append("final")
        self.closed = True
        return self.agent.entries

    def abort(self):
        if not self.closed:
            self.agent.calls.append("abort")
            self.closed = True


class SyntheticCycleAgent(ReadOnlyAgent):
    def __init__(self):
        self.entries = [ObservedShun(IP, "management")]
        self.calls = []

    def open_cycle(self, device_id):
        self.calls.append("initial")
        return SyntheticCycle(self)


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_uses_same_lease_before_cutoff_and_fresh_snapshot_without_add_replay(queue, enabled):
    cleanup, original = handoff(queue)
    queue.finish_addition(original["id"], "old-worker", "UNVERIFIED")
    queue.finish_cycle("old-worker", 60)
    agent = SyntheticCycleAgent()
    sync = Synchronizer(queue.store, agent, 300, 60, session_cycles_enabled=True,
                        managed_removal_worker_enabled=enabled)
    sync.queue._now = lambda: NOW + timedelta(seconds=61)
    assert sync._has_pending() is enabled
    asyncio.run(sync._sweep())
    assert agent.calls == (["initial", "remove", "final"] if enabled else ["initial", "final"])
    state = cleanup.snapshot()["items"][0]
    assert state["state"] == ("ADMITTED" if enabled else "WAITING_ADD")
    if enabled:
        assert state["queue_state"] == "VERIFIED"
    with queue.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (original["id"],)).fetchone()[0] == "UNVERIFIED"
    assert sync.managed_removals.snapshot_if_present()["scheduler_integration_available"] is enabled
    assert sync.status()["managed_removal_worker_error"] is None


def test_worker_error_blocks_all_mutations_but_preserves_fresh_monitoring(queue, monkeypatch):
    enqueue(queue)
    agent = SyntheticCycleAgent()
    sync = Synchronizer(queue.store, agent, 300, 60, session_cycles_enabled=True,
                        managed_removal_worker_enabled=True)
    sync.queue._now = lambda: NOW
    calls = []

    def fail(owner):
        calls.append(owner)
        raise sqlite3.OperationalError("synthetic private schema detail")

    monkeypatch.setattr(sync.managed_removals, "advance_if_present", fail)
    asyncio.run(sync._sweep())
    assert calls == [sync.instance_id]
    assert agent.calls == ["initial", "final"]
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert sync.store.list_active_shuns()[0].ip == IP
    assert sync.status()["managed_removal_worker_error"] == "Managed cleanup handoff failed; mutations skipped for this cycle."
    assert "synthetic private" not in str(sync.status())


def test_worker_optional_schema_is_not_initialized_by_cycles(queue):
    sync = Synchronizer(queue.store, ReadOnlyAgent(), 300, 60, managed_removal_worker_enabled=True)
    asyncio.run(sync._sweep())
    assert not sync.managed_removals.snapshot_if_present()["initialized"]
    assert sync.status()["last_error"] is None
    with queue.store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()


def test_concurrent_commit_during_backup_refuses_mutation(queue, tmp_path, monkeypatch):
    from ftd_shun_manager import maintenance

    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    backup = parent / "before.sqlite3"
    real_open = maintenance.os.open

    def concurrent_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        with queue.store._connection() as writer:
            writer.execute("UPDATE operation_executor SET revision=revision+1")
        return fd

    monkeypatch.setattr(maintenance.os, "open", concurrent_open)
    with pytest.raises(ValueError, match="Another process committed"):
        run_offline(queue.store.path, backup, "suspend", "operator")
    assert backup.exists() and not queue.mutations_suspended()


def test_older_queue_migration_preserves_pause_and_running_remove_uncertainty(queue):
    enqueue(queue)
    assert queue.claim_cycle("old-worker", 135)
    job = queue.claim_removal(1, "old-worker", queue.cutoff())
    enqueue(queue, IPv4Address("198.51.100.250"), add=True)
    with queue.store._connection() as db:
        db.execute("ALTER TABLE operation_executor DROP COLUMN mutations_suspended")
    result = control(queue)
    assert result["running_unverified"] == result["queued_cancelled"] == 1
    queue.initialize()
    assert queue.mutations_suspended()
    with queue.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "UNVERIFIED"


def test_resume_refuses_unsuspended_desired_policy_and_keeps_global_pause(queue):
    cleanup, _ = handoff(queue)
    control(queue)
    with queue.store._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0 WHERE id=1")
    with pytest.raises(ValueError, match="restoration must remain suspended"):
        control(queue, "resume-mutations")
    assert queue.mutations_suspended()
    # Suspending again repairs the policy pause, never its retired desired target.
    control(queue)
    assert cleanup.registry.snapshot()["restoration_suspended"]
