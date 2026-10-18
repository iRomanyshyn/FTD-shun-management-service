"""Whole-scope barriers with temporary SQLite/synthetic settlement only."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager.agent_client import AgentClient
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.maintenance import apply_recovery_control, run_offline
from ftd_shun_manager.managed_fleet_removals import ManagedFleetRemovals
from ftd_shun_manager.managed_fleet_waits import ManagedFleetWaits
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
from ftd_shun_manager.synchronizer import Synchronizer

NOW = datetime(2026, 10, 18, tzinfo=UTC)
IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.250")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device in range(1, 5):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    queue, registry = OperationQueue(store), ManagedShuns(store)
    queue.initialize()
    registry.initialize()
    clock = [NOW]
    monkeypatch.setattr(queue, "_now", lambda: clock[0])
    change(registry, "MAINTAIN", [1, 2])
    store.record_observed_shun(3, IP, "outside")
    fleet = ManagedFleetRemovals(registry, queue)
    fleet.initialize()
    return fleet, ManagedFleetWaits(store, queue), clock


def change(registry, action, devices):
    revision = registry.snapshot()["revision"]
    targets = [(device, IP) for device in devices]
    registry.change(str(uuid4()), action, targets, revision, 0,
                    canonical_managed_change(action, targets, revision, 0)[2], "owner", "Owner", ("Operator",))


def arguments(fleet, **overrides):
    values = {"request_id": str(uuid4()), "reviewed": ManagedRemovalScopes(fleet.store).snapshot(IP),
              "subject": "owner", "display_name": "Owner", "roles": ("Operator",), "ttl_seconds": 900,
              "reason": "Reviewed ordered cleanup", "ordered_wait": True, **overrides}
    scope = {k: v for k, v in values["reviewed"].items() if k not in {"scope_digest", "read_only", "execution_available"}}
    values["confirmation_digest"] = canonical_managed_fleet_removal(
        scope, values["ttl_seconds"], values["reason"], ordered_wait=values["ordered_wait"],
    )[1]
    return values


def add(fleet, device=1, running=True, ip=IP):
    key = str(uuid4())
    fleet.queue.enqueue(key, [(device, ip)], "adder", "Adder", ("Operator",), source="manual_import",
                        scope="import", policy_revision=0, confirmation_digest=canonical_import([(device, ip)], 0)[2])
    if running:
        with fleet.store._connection() as db:
            if db.execute("SELECT owner FROM operation_executor WHERE id=1").fetchone()[0] is None:
                assert fleet.queue.claim_cycle("worker", 135)
        return fleet.queue.claim_addition(device, "worker", fleet.queue.cutoff(), execution_enabled=True)
    return None


def settle(fleet, job, state="UNVERIFIED"):
    with fleet.store._connection() as db:
        if state == "QUEUED":
            db.execute("UPDATE operation_jobs SET state='QUEUED',dispatch_kind=NULL WHERE id=?", (job["id"],))
        else:
            current = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()
            fleet.queue._finish(db, current, state, "Synthetic predecessor settlement")


def state(waits):
    with waits.store._connection() as db:
        return dict(db.execute("SELECT * FROM managed_fleet_waits").fetchone())


def counts(fleet):
    with fleet.store._connection() as db:
        return fleet.queue._pending_count(db), fleet.queue._active_request_count(db)


def fingerprint(fleet):
    with fleet.store._connection() as db:
        return tuple(db.iterdump())


def test_barrier_retires_whole_scope_reserves_every_target_and_never_overlaps_running_add(fixture):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    values = arguments(fleet)
    receipt = fleet.admit(**values)
    assert receipt["waiting_for_add"] and receipt["target_count"] == 3 and receipt["retired_targets"] == 2
    assert state(waits)["state"] == "WAITING_ADD"
    assert json.loads(state(waits)["predecessors_json"]) == [{"device_id": 1, "job_id": predecessor["id"]}]
    assert counts(fleet) == (4, 2)  # Existing ADD plus three slots/one reserved root.
    assert fleet.queue.status()["counts"] == {"RUNNING": 1}
    assert all(not row["enabled"] for row in fleet.registry.snapshot()["entries"])
    before = fingerprint(fleet)
    assert waits.advance("worker") == 0 and fingerprint(fleet) == before
    assert waits.has_waiting()


def test_mode_is_explicit_digest_separated_and_old_ready_semantics_are_preserved(fixture):
    fleet, waits, _ = fixture
    add(fleet)
    ordered = arguments(fleet)
    ready = arguments(fleet, ordered_wait=False)
    assert ordered["confirmation_digest"] != ready["confirmation_digest"]
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="unfinished ADD"):
        fleet.admit(**ready)
    with pytest.raises(ValueError, match="Confirmation"):
        fleet.admit(**{**ordered, "confirmation_digest": ready["confirmation_digest"]})
    with pytest.raises(TypeError, match="boolean"):
        arguments(fleet, ordered_wait=1)
    assert fingerprint(fleet) == before
    fleet.admit(**ordered)
    before = fingerprint(fleet)
    assert fleet.admit(**ordered)["replayed"]
    with pytest.raises(ManagedConflict):
        fleet.admit(**arguments(fleet, request_id=ordered["request_id"], ordered_wait=False))
    assert fingerprint(fleet) == before and state(waits)["state"] == "WAITING_ADD"


@pytest.mark.parametrize("outcome", ["VERIFIED", "NOOP", "FAILED", "UNVERIFIED", "CANCELLED", "QUEUED"])
def test_settled_predecessor_promotes_all_targets_once_under_original_actor_deadline(fixture, outcome):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    settle(fleet, predecessor, outcome)
    clock[0] += timedelta(seconds=30)
    assert waits.advance("worker") == 1
    assert state(waits)["state"] == "ADMITTED" and not waits.has_waiting()
    assert fleet.queue.status()["counts"]["QUEUED"] == 3
    assert counts(fleet) == (3, 1)
    with fleet.store._connection() as db:
        original = db.execute("SELECT * FROM operation_jobs WHERE id=?", (predecessor["id"],)).fetchone()
        assert original["state"] == ("CANCELLED" if outcome == "QUEUED" else outcome)
        assert original["action"] == "ADD"
        request = db.execute("SELECT * FROM operation_requests WHERE id=?", (values["request_id"],)).fetchone()
        root = db.execute("SELECT * FROM managed_fleet_removals WHERE id=?", (values["request_id"],)).fetchone()
        assert request["actor_subject"] == "owner" and request["requested_at"] == root["requested_at"]
        assert request["expires_at"] <= root["expires_at"]
        assert db.execute("SELECT COUNT(*) FROM operation_links WHERE request_id=?", (values["request_id"],)).fetchone()[0] == 3
    before = fingerprint(fleet)
    assert waits.advance("worker") == 0 and fingerprint(fleet) == before
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before


def test_all_captured_adds_must_settle_before_any_ready_target_is_queued(fixture):
    fleet, waits, _ = fixture
    first, second = add(fleet, 1), add(fleet, 2)
    fleet.admit(**arguments(fleet))
    settle(fleet, first)
    assert waits.advance("worker") == 0
    assert fleet.queue.status()["counts"] == {"RUNNING": 1, "UNVERIFIED": 1}
    settle(fleet, second, "NOOP")
    assert waits.advance("worker") == 1 and fleet.queue.status()["counts"]["QUEUED"] == 3


def test_queued_add_conflicts_entire_scope_even_in_ordered_mode(fixture):
    fleet, _, _ = fixture
    add(fleet, running=False)
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="QUEUED ADD"):
        fleet.admit(**arguments(fleet))
    assert fingerprint(fleet) == before


@pytest.mark.parametrize("target", [1, 2, 3])
def test_new_add_cannot_coalesce_or_bypass_any_reserved_target(fixture, target):
    fleet, _, _ = fixture
    add(fleet)
    fleet.admit(**arguments(fleet))
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="fleet cleanup is waiting"):
        add(fleet, target, running=False)
    assert fingerprint(fleet) == before


def test_maintenance_cannot_reenable_reserved_or_attention_targets(fixture):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    with pytest.raises(ManagedConflict, match="Fleet cleanup"):
        change(fleet.registry, "MAINTAIN", [2])
    settle(fleet, predecessor)
    fleet.store.upsert_device(Device(2, "changed", IPv4Address("192.0.2.2"), True), "ssh-ed25519 AAAA")
    assert waits.advance("worker") == 0 and state(waits)["state"] == "ATTENTION"
    with pytest.raises(ManagedConflict, match="Fleet cleanup"):
        change(fleet.registry, "MAINTAIN", [1])


def test_expiry_releases_whole_reservation_without_cancelling_running_command(fixture):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    values = arguments(fleet, ttl_seconds=60)
    fleet.admit(**values)
    clock[0] += timedelta(seconds=61)
    assert waits.advance("worker") == 0 and state(waits)["state"] == "EXPIRED"
    assert counts(fleet)[0] == 1
    with fleet.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (predecessor["id"],)).fetchone()[0] == "RUNNING"
    assert not any(row["enabled"] for row in fleet.registry.snapshot()["entries"])
    before = fingerprint(fleet)
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before


@pytest.mark.parametrize("actor,roles", [("owner", ("Operator",)), ("admin", ("Administrator",))])
def test_cancel_is_owner_or_admin_idempotent_and_does_not_cancel_add(fixture, actor, roles):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    with pytest.raises(PermissionError):
        waits.cancel_waiting(values["request_id"], "other", "Other", ("Operator",))
    with pytest.raises(PermissionError):
        waits.cancel_waiting(values["request_id"], "owner", "Owner", ("Viewer",))
    assert waits.cancel_waiting(values["request_id"], actor, actor, roles)
    before = fingerprint(fleet)
    assert not waits.cancel_waiting(values["request_id"], actor, actor, roles)
    assert fingerprint(fleet) == before and counts(fleet)[0] == 1
    settle(fleet, predecessor)
    assert waits.advance("worker") == 0
    assert not any(row["enabled"] for row in fleet.registry.snapshot()["entries"])


def test_cancel_promotion_race_has_one_winner_no_partial_scope(fixture):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    settle(fleet, predecessor)
    def cancel():
        try:
            return waits.cancel_waiting(values["request_id"], "owner", "Owner", ("Operator",))
        except QueueConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        promoted, cancelled = pool.submit(waits.advance, "worker"), pool.submit(cancel)
        promoted, cancelled = promoted.result(), cancelled.result()
    assert bool(promoted) != bool(cancelled)
    assert state(waits)["state"] == ("ADMITTED" if promoted else "CANCELLED")
    assert fleet.queue.status()["counts"].get("QUEUED", 0) == (3 if promoted else 0)


@pytest.mark.parametrize("mutation", ["missing", "wrong_device", "new_generation", "disabled", "new_intent"])
def test_missing_evidence_or_changed_scope_latches_attention_without_partial_work(fixture, mutation):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    with fleet.store._connection() as db:
        if mutation == "missing":
            db.execute("DELETE FROM operation_jobs WHERE id=?", (predecessor["id"],))
        elif mutation == "wrong_device":
            db.execute("UPDATE operation_jobs SET device_id=4 WHERE id=?", (predecessor["id"],))
        elif mutation == "new_generation":
            db.execute("UPDATE managed_shun_targets SET generation=generation+1 WHERE device_id=1")
        elif mutation == "disabled":
            db.execute("UPDATE devices SET enabled=0 WHERE id=2")
        else:
            db.execute("UPDATE managed_shun_targets SET intent_id=? WHERE device_id=1", (str(uuid4()),))
    assert waits.advance("worker") == 0 and state(waits)["state"] == "ATTENTION"
    assert fleet.queue.status()["counts"].get("QUEUED", 0) == 0


def test_queue_capacity_counts_all_reserved_targets_and_admission_failure_rolls_back_retirement(fixture):
    fleet, _, _ = fixture
    add(fleet)
    with fleet.store._connection() as db:
        db.executemany("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at) VALUES (?,4,?,'QUEUED',?)",
                       [(str(uuid4()), IPv4Address(0xC6120000 + i).packed, NOW.isoformat()) for i in range(997)])
    before = fingerprint(fleet)
    with pytest.raises(QueueFull, match="reserved fleet targets"):
        fleet.admit(**arguments(fleet))
    assert fingerprint(fleet) == before


def test_other_admissions_respect_wait_capacity_and_original_root_rate_accounting(fixture):
    fleet, waits, _ = fixture
    add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    with fleet.store._connection() as db:
        assert fleet.queue._recent_request_count(db, "owner", NOW) == 1
        assert fleet.queue._recent_request_count(db, "owner", NOW, values["request_id"]) == 0
        db.executemany("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at) VALUES (?,4,?,'QUEUED',?)",
                       [(str(uuid4()), IPv4Address(0xC6120000 + i).packed, NOW.isoformat()) for i in range(996)])
    with pytest.raises(QueueFull):
        fleet.queue.enqueue(str(uuid4()), [(4, OTHER)], "other", "Other", ("Operator",))
    waits.cancel_waiting(values["request_id"], "owner", "Owner", ("Operator",))
    with fleet.store._connection() as db:
        assert fleet.queue._recent_request_count(db, "owner", NOW) == 1  # Cancellation does not refund intake.


def test_promotion_is_atomic_on_late_audit_error_and_does_not_erase_add_uncertainty(fixture, monkeypatch, capsys):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    before = fingerprint(fleet)
    original = waits._event
    def fail(db, row, event, **kwargs):
        original(db, row, event, **kwargs)
        if event == "MANAGED_SHUN_FLEET_CLEANUP_QUEUED":
            raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(waits, "_event", fail)
    capsys.readouterr()
    with pytest.raises(RuntimeError, match="audit failure"):
        waits.advance("worker")
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_failed_promotion_restores_known_deferral_and_releases_slots_to_attention(fixture, monkeypatch):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor, "QUEUED")
    def full(*args, **kwargs):
        raise QueueFull("Synthetic capacity failure")
    monkeypatch.setattr(fleet.queue, "apply_enqueue", full)
    assert waits.advance("worker") == 0 and state(waits)["state"] == "ATTENTION"
    with fleet.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (predecessor["id"],)).fetchone()[0] == "QUEUED"


def test_recovery_backup_cancels_barrier_and_preserves_running_uncertainty(fixture, tmp_path):
    fleet, waits, _ = fixture
    add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    result = run_offline(fleet.store.path, directory / "before.db", "suspend", "synthetic-operator")
    assert result["waiting_cancelled"] == result["running_unverified"] == 1
    assert state(waits)["state"] == "CANCELLED" and counts(fleet)[0] == 0
    before = fingerprint(fleet)
    assert fleet.admit(**values)["replayed"] and fingerprint(fleet) == before
    assert waits.advance("anyone") == 0 and not waits.has_waiting()
    assert not any(row["enabled"] for row in fleet.registry.snapshot()["entries"])


def test_retention_preserves_captured_add_evidence_while_waiting(fixture):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    clock[0] += timedelta(days=367)
    fleet.queue.prune_completed(366)
    with fleet.store._connection() as db:
        assert db.execute("SELECT 1 FROM operation_jobs WHERE id=?", (predecessor["id"],)).fetchone()
    # A real next executor recovers its expired lease before expiring the barrier.
    assert fleet.queue.claim_cycle("recovered", 135)
    assert waits.advance("recovered") == 0 and state(waits)["state"] == "EXPIRED"
    fleet.queue.prune_completed(366)
    with fleet.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE id=?", (predecessor["id"],)).fetchone()


def test_evidence_is_immutable_retained_and_terminal_state_cannot_be_rearmed(fixture):
    fleet, waits, _ = fixture
    add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    for sql in ("DELETE FROM managed_fleet_waits", "UPDATE managed_fleet_waits SET target_count=1",
                "UPDATE managed_fleet_waits SET predecessors_json='[]'"):
        with fleet.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    waits.cancel_waiting(values["request_id"], "owner", "Owner", ("Operator",))
    with fleet.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE managed_fleet_waits SET state='WAITING_ADD'")


class ReadOnlyAgent(AgentClient):
    def __init__(self):
        self.reads = 0

    def list_shuns(self, device_id):
        self.reads += 1
        return [ObservedShun(IP, "outside")]

    def remove_shun(self, device_id, ip):
        raise AssertionError("Worker error must retain reads but block all mutations")


def test_worker_integration_stays_default_off_and_never_initializes_schema(fixture, monkeypatch):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    # Release fixture lease so the shared scheduler can become sole owner.
    fleet.queue.finish_cycle("worker", 60)
    clock[0] += timedelta(seconds=61)
    agent = ReadOnlyAgent()
    sync = Synchronizer(fleet.store, agent, 300, 60, managed_removal_worker_enabled=False)
    sync.queue._now = lambda: clock[0]
    assert not sync._has_pending()
    asyncio.run(sync._sweep())
    assert state(waits)["state"] == "WAITING_ADD" and agent.reads == 4


def test_worker_budgets_single_and_fleet_before_cutoff_and_error_skips_mutations(fixture, monkeypatch):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    fleet.queue.finish_cycle("worker", 60)
    clock[0] += timedelta(seconds=61)
    agent = ReadOnlyAgent()
    sync = Synchronizer(fleet.store, agent, 300, 60, managed_removal_worker_enabled=True)
    sync.queue._now = lambda: clock[0]
    calls = []
    def single(owner, limit):
        assert limit == 8
        calls.append("single")
    def fleet_fail(owner, limit):
        assert limit == 8
        calls.append("fleet")
        raise sqlite3.OperationalError("Synthetic private schema detail")
    monkeypatch.setattr(sync.managed_removals, "advance_if_present", single)
    monkeypatch.setattr(sync.managed_fleet_waits, "advance_if_present", fleet_fail)
    assert sync._has_pending()
    asyncio.run(sync._sweep())
    assert calls == ["single", "fleet"] and agent.reads == 4
    assert state(waits)["state"] == "WAITING_ADD"
    assert sync.status()["managed_removal_worker_error"] is not None


def test_resume_refuses_pending_fleet_barrier_even_if_ordinary_jobs_settled(fixture):
    fleet, _, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    with fleet.store._connection() as db:
        db.execute("UPDATE operation_executor SET mutations_suspended=1")
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="Pending jobs/handoffs"):
            apply_recovery_control(db, fleet.store, "resume-mutations", "synthetic-operator", now=NOW)


def test_still_running_root_does_not_starve_later_ready_root_with_bounded_limit(fixture):
    fleet, waits, _ = fixture
    add(fleet)
    first = arguments(fleet)
    fleet.admit(**first)
    fleet.store.record_observed_shun(4, OTHER, "outside")
    second_add = add(fleet, 4, ip=OTHER)
    second = arguments(fleet, reviewed=ManagedRemovalScopes(fleet.store).snapshot(OTHER))
    fleet.admit(**second)
    settle(fleet, second_add)
    assert waits.advance("worker", limit=1) == 1
    with fleet.store._connection() as db:
        states = dict(db.execute("SELECT id,state FROM managed_fleet_waits"))
        assert states == {first["request_id"]: "WAITING_ADD", second["request_id"]: "ADMITTED"}
    for limit in (0, 17, True):
        with pytest.raises(ValueError):
            waits.advance("worker", limit)


def test_expiry_during_materialization_rolls_back_all_targets_then_releases_barrier(fixture, monkeypatch):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet, ttl_seconds=30))
    settle(fleet, predecessor)
    clock[0] += timedelta(seconds=29)
    original = fleet.queue.apply_enqueue
    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(seconds=2)
        return result
    monkeypatch.setattr(fleet.queue, "apply_enqueue", slow)
    assert waits.advance("worker") == 0 and state(waits)["state"] == "EXPIRED"
    assert fleet.queue.status()["counts"] == {"UNVERIFIED": 1}
    assert counts(fleet) == (0, 0)


def test_lease_expiry_during_materialization_rolls_back_without_settling_or_success_logs(fixture, monkeypatch, capsys):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    before = fingerprint(fleet)
    original = fleet.queue.apply_enqueue
    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(seconds=136)
        return result
    monkeypatch.setattr(fleet.queue, "apply_enqueue", slow)
    capsys.readouterr()
    with pytest.raises(QueueConflict, match="lease lost"):
        waits.advance("worker")
    assert fingerprint(fleet) == before and not capsys.readouterr().out


def test_normal_queue_key_cannot_materialize_wait_or_extend_original_authority(fixture):
    fleet, _, _ = fixture
    add(fleet)
    values = arguments(fleet)
    fleet.admit(**values)
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="reserved"):
        fleet.queue.enqueue(values["request_id"], [(1, IP), (2, IP), (3, IP)],
                            "owner", "Owner", ("Operator",), scope="managed_fleet_removal")
    assert fingerprint(fleet) == before


def test_old_ready_only_schema_refuses_wait_without_implicit_migration(fixture):
    fleet, _, _ = fixture
    with fleet.store._connection() as db:
        db.execute("DROP TABLE managed_fleet_waits")
    add(fleet)
    before = fingerprint(fleet)
    with pytest.raises(ManagedConflict, match="schema is not initialized"):
        fleet.admit(**arguments(fleet))
    assert fingerprint(fleet) == before


class RemovalAgent(ReadOnlyAgent):
    def __init__(self):
        super().__init__()
        self.calls = []

    def list_shuns(self, device_id):
        self.calls.append(("read", device_id))
        return super().list_shuns(device_id)

    def remove_shun(self, device_id, ip):
        assert ip == IP and ("read", device_id) in self.calls
        self.calls.append(("remove", device_id))


def test_opted_in_worker_promotes_once_before_cutoff_with_fresh_reads_and_no_add_replay(fixture):
    fleet, waits, clock = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    fleet.queue.finish_cycle("worker", 60)
    clock[0] += timedelta(seconds=61)
    agent = RemovalAgent()
    sync = Synchronizer(fleet.store, agent, 300, 60, managed_removal_worker_enabled=True)
    sync.queue._now = lambda: clock[0]
    assert sync._has_pending()
    asyncio.run(sync._sweep())
    assert state(waits)["state"] == "ADMITTED"
    assert agent.calls == [("read", 1), ("remove", 1), ("read", 2), ("remove", 2),
                           ("read", 3), ("remove", 3), ("read", 4)]
    assert fleet.queue.status()["counts"] == {"UNVERIFIED": 1, "VERIFIED": 3}
    assert sync.status()["managed_removal_worker_error"] is None


def test_wait_admission_late_audit_failure_rolls_back_root_retirement_evidence_and_slots(fixture, monkeypatch, capsys):
    fleet, _, _ = fixture
    add(fleet)
    values = arguments(fleet)
    before = fingerprint(fleet)
    original = fleet.store._insert_event
    def fail(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED":
            raise RuntimeError("Synthetic root audit failure")
    monkeypatch.setattr(fleet.store, "_insert_event", fail)
    capsys.readouterr()
    with pytest.raises(RuntimeError, match="root audit failure"):
        fleet.admit(**values)
    assert fingerprint(fleet) == before and not capsys.readouterr().out
    assert counts(fleet) == (1, 1)


def test_waiting_root_counts_once_for_actor_rate_and_cancellation_does_not_refund_it(fixture):
    fleet, waits, _ = fixture
    add(fleet)
    for _ in range(9):
        fleet.queue.enqueue(str(uuid4()), [(4, OTHER)], "owner", "Owner", ("Operator",))
    values = arguments(fleet)
    fleet.admit(**values)
    with fleet.store._connection() as db:
        assert fleet.queue._recent_request_count(db, "owner", NOW) == 10
    for cancelled in (False, True):
        if cancelled:
            waits.cancel_waiting(values["request_id"], "owner", "Owner", ("Operator",))
        with pytest.raises(QueueFull, match="10 operation"):
            fleet.queue.enqueue(str(uuid4()), [(4, OTHER)], "owner", "Owner", ("Operator",))


def test_single_target_handoff_cannot_absorb_existing_whole_scope_barrier(fixture):
    fleet, _, _ = fixture
    add(fleet)
    fleet.admit(**arguments(fleet))
    single = ManagedRemovals(fleet.registry, fleet.queue)
    single.initialize()
    revision = fleet.registry.snapshot()["revision"]
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="Fleet cleanup is already waiting"):
        single.admit(str(uuid4()), 2, IP, revision, canonical_managed_removal(2, IP, revision)[1],
                     "owner", "Owner", ("Operator",))
    assert fingerprint(fleet) == before


@pytest.mark.parametrize("corruption", ["predecessors", "payload", "deadline"])
def test_invalid_evidence_is_attention_not_empty_or_success(fixture, corruption):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    with fleet.store._connection() as db:
        if corruption == "predecessors":
            db.execute("DROP TRIGGER fleet_wait_authority_immutable")
            db.execute("UPDATE managed_fleet_waits SET predecessors_json='[null]'")
        elif corruption == "payload":
            db.execute("DROP TRIGGER managed_fleet_authority_immutable")
            db.execute("UPDATE managed_fleet_removals SET payload_json='{}'")
        else:
            db.execute("DROP TRIGGER managed_fleet_authority_immutable")
            db.execute("UPDATE managed_fleet_removals SET expires_at=?", ((NOW + timedelta(seconds=901)).isoformat(),))
    assert waits.advance("worker") == 0 and state(waits)["state"] == "ATTENTION"
    assert fleet.queue.status()["counts"].get("QUEUED", 0) == 0


def test_current_lease_required_and_pause_prevents_promotion_without_rearming(fixture):
    fleet, waits, _ = fixture
    predecessor = add(fleet)
    fleet.admit(**arguments(fleet))
    settle(fleet, predecessor)
    before = fingerprint(fleet)
    with pytest.raises(QueueConflict, match="lease lost"):
        waits.advance("other")
    assert fingerprint(fleet) == before
    with fleet.store._connection() as db:
        db.execute("UPDATE operation_executor SET mutations_suspended=1")
    before = fingerprint(fleet)
    assert waits.advance("other") == 0 and fingerprint(fleet) == before


def test_orphaned_wait_reservation_fails_recovery_instead_of_disappearing(fixture):
    fleet, _, _ = fixture
    add(fleet)
    fleet.admit(**arguments(fleet))
    with fleet.store._connection() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TRIGGER managed_fleet_key_retained")
        db.execute("DELETE FROM managed_fleet_removals")
    with fleet.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="missing its root authority"):
            apply_recovery_control(db, fleet.store, "suspend", "synthetic-operator", now=NOW)
