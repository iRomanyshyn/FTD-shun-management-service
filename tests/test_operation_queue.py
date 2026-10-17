from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4

import pytest

from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def queue(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    result = OperationQueue(store)
    result.initialize()
    clock = [datetime(2026, 10, 15, tzinfo=UTC)]
    monkeypatch.setattr(result, "_now", lambda: clock[0])
    result.test_clock = clock
    return result


def enqueue(queue, subject="alice", ip="198.51.100.10", request_id=None):
    return queue.enqueue(request_id or str(uuid4()), [(1, IPv4Address(ip))],
                         subject, subject.title(), ("Operator",))


def test_simultaneous_users_share_one_job_and_keep_all_actors(queue):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda index: enqueue(queue, subject=f"user-{index}"), range(12)))

    status = queue.status()
    assert status["counts"] == {"QUEUED": 1}
    assert len(status["items"][0]["requests"]) == 12
    assert len({result["operation_id"] for result in results}) == 12
    assert len([event for event in queue.store.list_events() if event["event_type"] == "SHUN_OPERATION_QUEUED"]) == 12


def test_status_independently_bounds_active_attention_and_completed_work(queue):
    # Large fixture: no device activity; exercise display selection only.
    with queue.store._connection() as db:
        for index in range(105):
            db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at)
                VALUES (?,1,?,'QUEUED',?)""", (f"queued-{index}", IPv4Address(index + 1).packed,
                                             "2026-10-15T00:00:00.000Z"))
        # A newer RUNNING job must stay visible even behind a large FIFO backlog.
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at)
            VALUES ('running',1,?,'RUNNING',?)""", (IPv4Address(500).packed, "2026-10-15T00:00:00.000Z"))
        for index in range(25):
            for group, state in (("attention", "UNVERIFIED"), ("completed", "VERIFIED")):
                db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,completed_at)
                    VALUES (?,1,?,?,?,?)""", (f"{group}-{index}", IPv4Address(1000 + index).packed,
                        state, "2026-10-14T00:00:00.000Z", f"2026-10-15T00:00:{index:02d}.000Z"))
    result = queue.status()
    assert result["counts"] == {"QUEUED": 105, "RUNNING": 1, "UNVERIFIED": 25, "VERIFIED": 25}
    assert result["display_limits"] == {"active": 100, "attention": 20, "completed": 20}
    assert len(result["items"]) == 140
    assert result["items"][0]["id"] == "running"
    assert [item["id"] for item in result["items"][1:100]] == [f"queued-{index}" for index in range(99)]
    assert [item["id"] for item in result["items"][100:120]] == [f"attention-{index}" for index in range(24, 4, -1)]
    assert [item["id"] for item in result["items"][120:]] == [f"completed-{index}" for index in range(24, 4, -1)]
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs").fetchone()[0] == 156


def test_status_counts_and_groups_share_one_snapshot_during_concurrent_completion(queue, monkeypatch):
    enqueue(queue)
    original = queue.store._connection

    @contextmanager
    def concurrent_completion():
        with original() as db:
            fired = False

            def trace(statement):
                nonlocal fired
                if not fired and statement.startswith("SELECT j.*"):
                    fired = True
                    with original() as writer:
                        writer.execute("""UPDATE operation_jobs SET state='VERIFIED',
                            completed_at='2026-10-15T00:01:00.000Z'""")

            db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(queue.store, "_connection", concurrent_completion)
    result = queue.status()
    assert result["counts"] == {"QUEUED": 1}
    assert [item["state"] for item in result["items"]] == ["QUEUED"]
    assert result["progress"]["requests"][0]["processed"] == 0
    with original() as db:
        assert db.execute("SELECT state FROM operation_jobs").fetchone()[0] == "VERIFIED"


def test_request_progress_uses_linked_jobs_and_separates_uncertain_results(queue):
    request_id = str(uuid4())
    targets = [(1, IPv4Address(f"198.51.100.{index}")) for index in range(1, 4)]
    queue.enqueue(request_id, targets, "alice", "Alice", ("Operator",))
    assert queue.claim_cycle("worker", 135)
    first = queue.claim_removal(1, "worker", queue.cutoff())
    queue.finish_removal(first["id"], "worker", "VERIFIED")
    second = queue.claim_removal(1, "worker", queue.cutoff())
    queue.finish_removal(second["id"], "worker", "UNVERIFIED", "reply lost")
    third = queue.claim_removal(1, "worker", queue.cutoff())
    progress = queue.status()["progress"]
    assert progress["total_requests"] == 1
    item = progress["requests"][0]
    assert item["id"] == request_id
    assert item["total"] == 3
    assert item["processed"] == 2
    assert item["counts"] == {"VERIFIED": 1, "UNVERIFIED": 1, "RUNNING": 1}
    # No-op completes processing, not an additional verified write.
    queue.finish_removal(third["id"], "worker", "NOOP")
    assert queue.status()["progress"] == {"requests": [], "total_requests": 0, "limit": 20}
    assert queue.status()["counts"] == {"VERIFIED": 1, "UNVERIFIED": 1, "NOOP": 1}


def test_cancelled_requester_does_not_inherit_coalesced_job_progress(queue):
    alice = enqueue(queue)
    bob = enqueue(queue, "bob")
    queue.cancel(alice["operation_id"], "alice", False)
    progress = queue.status()["progress"]
    assert progress["total_requests"] == 1
    assert progress["requests"][0]["id"] == bob["operation_id"]
    assert progress["requests"][0]["counts"] == {"QUEUED": 1}


def test_request_progress_is_bounded_independently_of_shared_jobs(queue):
    for index in range(25):
        enqueue(queue, subject=f"user-{index}")
    status = queue.status()
    assert status["counts"] == {"QUEUED": 1}  # One shared execution, not 25.
    assert status["progress"]["total_requests"] == 25
    assert len(status["progress"]["requests"]) == 20
    assert all(item["total"] == 1 and item["processed"] == 0 for item in status["progress"]["requests"])


def test_idempotency_key_survives_completion_and_scope_is_bound(queue):
    request_id = str(uuid4())
    enqueue(queue, request_id=request_id)
    assert queue.claim_cycle("worker", 135)
    job = queue.claim_removal(1, "worker", queue.cutoff())
    queue.finish_removal(job["id"], "worker", "VERIFIED")

    replay = queue.replay(request_id, "alice", "device", IPv4Address("198.51.100.10"), 1)
    assert replay["replayed"] is True
    assert queue.status()["counts"] == {"VERIFIED": 1}
    for subject, scope, ip in [
        ("bob", "device", "198.51.100.10"),
        ("alice", "all", "198.51.100.10"),
        ("alice", "device", "198.51.100.11"),
    ]:
        with pytest.raises(QueueConflict):
            queue.replay(request_id, subject, scope, IPv4Address(ip), 1)


def test_transactional_capacity_failure_does_not_leave_partial_admission(queue):
    targets = [(1, IPv4Address(0xC6330000 + index)) for index in range(1000)]
    queue.enqueue(str(uuid4()), targets, "alice", "Alice", ("Operator",))
    with pytest.raises(QueueFull):
        queue.enqueue(str(uuid4()), [targets[0], (1, IPv4Address("203.0.113.1"))],
                      "bob", "Bob", ("Operator",))

    assert queue.status()["counts"] == {"QUEUED": 1000}
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 1


def test_user_admission_rate_is_shared_across_connections(queue):
    for index in range(10):
        enqueue(queue, ip=f"198.51.100.{index}")
    with pytest.raises(QueueFull, match="10 operation submissions"):
        enqueue(queue)


def test_only_one_executor_and_completion_gate_survives_new_worker(queue, monkeypatch):
    assert queue.claim_cycle("first", 135)
    assert not queue.claim_cycle("second", 135)
    with pytest.raises(QueueConflict):
        queue.renew("second", 135)
    queue.finish_cycle("first", 60)
    another = OperationQueue(queue.store)
    monkeypatch.setattr(another, "_now", queue._now)
    assert another.delay() == 60
    assert not another.claim_cycle("second", 135)
    queue.test_clock[0] += timedelta(seconds=60)
    assert another.claim_cycle("second", 135)


def test_abandoned_write_is_not_replayed_and_absence_is_not_verified_success(queue):
    enqueue(queue)
    assert queue.claim_cycle("lost", 135)
    job = queue.claim_removal(1, "lost", queue.cutoff())
    queue.test_clock[0] += timedelta(seconds=136)

    assert queue.claim_cycle("recovery", 135)
    assert queue.status()["items"][0]["state"] == "UNVERIFIED"
    assert queue.claim_removal(1, "recovery", queue.cutoff()) is None
    queue.reconcile_unknown(1, set())
    assert queue.status()["items"][0]["id"] == job["id"]
    assert queue.status()["items"][0]["state"] == "RECONCILED_ABSENT"
    assert not any(event["event_type"] == "SHUN_REMOVED_BY_UI" for event in queue.store.list_events())


def test_cancellation_removes_only_the_requester_and_preserves_other_intent(queue):
    alice = enqueue(queue)
    bob = enqueue(queue, "bob")
    with pytest.raises(PermissionError):
        queue.cancel(alice["operation_id"], "bob", False)
    queue.cancel(alice["operation_id"], "alice", False)
    assert queue.status()["counts"] == {"QUEUED": 1}
    queue.cancel(bob["operation_id"], "admin", True, "Administrator", ("Administrator",))
    assert queue.status()["counts"] == {"CANCELLED": 1}
    events = [event for event in queue.store.list_events() if event["event_type"] == "SHUN_OPERATION_CANCELLED"]
    assert {event["actor_subject"] for event in events} == {"alice", "admin"}
    assert not queue.has_pending()


def test_cancel_running_request_is_rejected_and_expired_work_never_runs(queue):
    request = enqueue(queue)
    assert queue.claim_cycle("worker", 135)
    queue.claim_removal(1, "worker", queue.cutoff())
    with pytest.raises(QueueConflict, match="running"):
        queue.cancel(request["operation_id"], "alice", False)
    enqueue(queue, "bob", ip="203.0.113.2")
    queue.test_clock[0] += timedelta(seconds=901)
    assert queue.claim_cycle("recovery", 135)
    assert queue.claim_removal(1, "recovery", queue.cutoff()) is None
    assert queue.status()["counts"] == {"FAILED": 1, "UNVERIFIED": 1}


def test_cycle_freezes_manual_work_even_if_timestamps_are_identical(queue):
    cutoff = queue.cutoff()
    enqueue(queue)
    assert queue.claim_cycle("worker", 135)
    assert queue.claim_removal(1, "worker", cutoff) is None
    assert queue.claim_removal(1, "worker", queue.cutoff()) is not None


def test_retention_preserves_unfinished_jobs(queue):
    enqueue(queue)
    assert queue.claim_cycle("worker", 135)
    job = queue.claim_removal(1, "worker", queue.cutoff())
    queue.finish_removal(job["id"], "worker", "VERIFIED")
    enqueue(queue, "bob", "203.0.113.1")
    queue.test_clock[0] += timedelta(days=367)

    queue.prune_completed(366)

    assert queue.status()["counts"] == {"QUEUED": 1}
    assert any(event["event_type"] == "HISTORY_RETENTION_PURGED" for event in queue.store.list_events())


def test_expired_work_stops_driving_the_scheduler_without_a_device_read(queue):
    enqueue(queue)
    queue.test_clock[0] += timedelta(seconds=901)
    queue.expire_requests()
    assert not queue.has_pending()
    assert queue.status()["counts"] == {"FAILED": 1}
    assert any(event["event_type"] == "SHUN_OPERATION_FAILED" for event in queue.store.list_events())


def test_policy_changes_cancel_only_policy_authorization(queue):
    queue.enqueue(str(uuid4()), [(1, IPv4Address("198.51.100.10"))], "system:trusted-ip-policy",
                  "Policy", (), source="trusted_policy")
    enqueue(queue, "alice")
    queue.cancel_obsolete_policy()
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert {r["state"] for r in queue.status()["items"][0]["requests"]} == {"ACTIVE", "CANCELLED"}


def test_initialization_is_additive_and_repeatable(queue):
    target = IPv4Address("198.51.100.10")
    queue.store.record_observed_shun(1, target, "outside")
    enqueue(queue)
    queue.initialize()
    queue.initialize()
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert queue.store.list_active_shuns()[0].ip == target
    assert any(e["event_type"] == "SHUN_DETECTED" for e in queue.store.list_events())


def test_documented_restore_procedure_suspends_old_work(queue):
    from ftd_shun_manager.maintenance import main

    enqueue(queue)
    enqueue(queue, "bob", "203.0.113.2")
    assert queue.claim_cycle("old-worker", 135)
    queue.claim_removal(1, "old-worker", queue.cutoff())
    manual = Path(__file__).resolve().parents[1] / "docs/manual/operation-queue.md"
    assert "[Offline Recovery](recovery.md)" in manual.read_text()
    procedure = (manual.parent / "recovery.md").read_text()
    assert "ftd-shun-maintenance suspend" in procedure and "--confirm-offline" in procedure
    backup_dir = queue.store.path.parent / "private"
    backup_dir.mkdir(mode=0o700)
    assert main(["suspend", "--database", str(queue.store.path), "--backup", str(backup_dir / "before.sqlite3"),
                 "--actor", "synthetic-operator", "--confirm-offline"]) == 0
    queue.initialize()
    assert queue.status()["counts"] == {"CANCELLED": 1, "UNVERIFIED": 1}
    assert not queue.has_pending()
    assert queue.mutations_suspended()
    assert any(e["event_type"] == "RECOVERY_MUTATIONS_SUSPENDED" for e in queue.store.list_events())
