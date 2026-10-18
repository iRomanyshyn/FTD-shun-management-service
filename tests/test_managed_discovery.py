"""Default-off snapshot discovery and shared dispatch, entirely synthetic."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from time import monotonic
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_shuns
from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable
from ftd_shun_manager.agent_protocol import AdditionResult, ObservedShun
from ftd_shun_manager.config import Settings
from ftd_shun_manager.managed_discovery import RestorationContext
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull, stamp
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer

IP = IPv4Address("198.51.100.251")


class Console:
    version = 3

    def __init__(self, agent, device):
        self.agent, self.device = agent, device
        self.initial_snapshot = list(agent.entries[device])

    def add_shun(self, ip):
        self.agent.writes.append((self.device, ip))
        if self.agent.lost:
            raise AgentUnavailable("synthetic lost reply")
        if self.agent.defer:
            return None
        self.agent.entries[self.device].append(ObservedShun(ip, "management"))
        return AdditionResult(True, "management")

    def finish(self):
        self.agent.reads.append(("final", self.device))
        return list(self.agent.entries[self.device])

    def snapshot(self):
        self.agent.reads.append(("priority", self.device))
        return None if self.agent.partial else list(self.agent.entries[self.device])

    def abort(self):
        pass


class Agent(AgentClient):
    def __init__(self):
        self.entries = {1: [], 2: []}
        self.writes, self.reads = [], []
        self.lost = self.fail = self.defer = self.partial = False

    def open_cycle(self, device):
        self.reads.append(("initial", device))
        if self.fail:
            raise AgentUnavailable("synthetic failed complete read")
        return Console(self, device)

    def list_shuns(self, *args):
        pytest.fail("No separate reader or fallback")

    def remove_shun(self, *args):
        pytest.fail("No separate writer or fallback")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    clock = [datetime.now(UTC) + timedelta(seconds=1)]
    monkeypatch.setattr(OperationQueue, "_now", lambda self: clock[0])
    monkeypatch.setattr(managed_shuns, "now", lambda: stamp(clock[0]))
    agent = Agent()
    sync = Synchronizer(store, agent, 300, 60, session_cycles_enabled=True,
                        import_execution_enabled=True, addition_device_ids=frozenset({1, 2}),
                        managed_restoration_enabled=True)
    registry = ManagedShuns(store)
    registry.initialize()
    sync.managed_discovery.source.initialize()
    with store._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")  # Disposable fixture only.
    return [store, agent, sync, registry, clock]


def change(lab, pairs=None, action="MAINTAIN"):
    registry = lab[3]
    pairs = pairs or [(1, IP)]
    revision = registry.snapshot()["revision"]
    with lab[0]._connection() as db:
        protected = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), action, pairs, revision, protected,
                    canonical_managed_change(action, pairs, revision, protected)[2],
                    "authorizer", "Authorizer", ("Operator",))


def sweep(lab, seconds=0):
    lab[4][0] += timedelta(seconds=seconds)
    asyncio.run(lab[2]._sweep())


def snapshot(lab, **kwargs):
    return CompleteSnapshot(**{"id": str(uuid4()), "device_id": 1, "started_at": lab[4][0],
                               "completed_at": lab[4][0], "present_ips": frozenset(), **kwargs})


def hold(lab):
    return lab[3].snapshot(restoration_context=lab[2].managed_discovery.context,
                           restoration_now=lab[4][0])["entries"][0]["restoration_hold"]


def test_two_reads_admit_once_then_next_cycle_dispatches_under_cooldown(lab):
    change(lab)
    sweep(lab)
    sync, agent = lab[2], lab[1]
    assert agent.writes == [] and sync._has_pending()
    assert sync.queue.status()["counts"] == {"QUEUED": 1}
    assert hold(lab) == "pending_work"
    assert sync.status()["queue"]["items"][0]["execution_enabled"]
    assert sync.status()["managed_restoration"]["admitted_this_cycle"] == 1
    with lab[0]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] == 1
    sweep(lab, 59)
    assert not agent.writes
    sweep(lab, 2)
    assert agent.writes == [(1, IP)] and not sync._has_pending()
    assert hold(lab) == "present"
    entry = lab[3].snapshot()["entries"][0]
    assert entry["restoration_state"] == "VERIFIED" and entry["last_verified_restoration_at"]
    lab[1].entries[1] = []  # Synthetic disappearance, never a live command.
    sweep(lab, 61)
    assert hold(lab) == "backoff" and not sync._has_pending()
    sweep(lab, 240)
    assert sync._has_pending() and agent.writes == [(1, IP)]
    sweep(lab, 61)
    assert agent.writes == [(1, IP), (1, IP)]


def test_disabled_controller_even_with_standing_policy_never_admits_or_initializes(tmp_path):
    store = Store(tmp_path / "disabled.db")
    store.initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    sync = Synchronizer(store, Agent(), 300, 60, session_cycles_enabled=True)
    asyncio.run(sync._sweep())
    assert not sync._has_pending() and sync.status()["managed_restoration"]["enabled"] is False
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()


def test_enabling_configuration_without_optional_migration_keeps_monitoring(tmp_path):
    store = Store(tmp_path / "absent.db")
    store.initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    sync = Synchronizer(store, Agent(), 300, 60, session_cycles_enabled=True,
                        import_execution_enabled=True, managed_restoration_enabled=True,
                        addition_device_ids=frozenset({1}))
    asyncio.run(sync._sweep())
    assert sync.status()["last_error"] is None and not sync._has_pending()
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()


def test_bound_and_restart_fairness_apply_across_devices_and_snapshots(lab):
    pairs = [(device, IPv4Address(0xC6336401 + i)) for device in (1, 2) for i in range(20)]
    change(lab, pairs)
    sweep(lab)
    assert lab[2].managed_discovery.status()["admitted_this_cycle"] == 16
    with lab[0]._connection() as db:
        assert dict(db.execute("SELECT device_id,COUNT(*) FROM managed_restoration_attempts GROUP BY device_id")) == {1: 16}
    lab[2] = Synchronizer(lab[0], lab[1], 300, 60, session_cycles_enabled=True,
                          import_execution_enabled=True, addition_device_ids=frozenset({1, 2}),
                          managed_restoration_enabled=True)
    sweep(lab, 61)
    with lab[0]._connection() as db:
        assert dict(db.execute("SELECT device_id,COUNT(*) FROM managed_restoration_attempts GROUP BY device_id")) == {1: 16, 2: 16}
    assert len(lab[1].writes) == 16 and {device for device, _ in lab[1].writes} == {1}
    assert lab[2].managed_discovery.ordered_devices(lab[0].list_devices())[0].id == 1


@pytest.mark.parametrize("failure,expected", [(QueueFull, "capacity"), (QueueConflict, "cycle_budget")])
def test_backpressure_and_conflict_work_are_bounded(lab, monkeypatch, failure, expected):
    change(lab, [(1, IPv4Address(0xC6336401+i)) for i in range(80)])
    discovery, queue = lab[2].managed_discovery, lab[2].queue
    assert queue.claim_cycle("synthetic-worker", 135)
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise failure("synthetic hold")
    monkeypatch.setattr(discovery.source, "admit_absence", fail)
    assert discovery.discover(snapshot(lab), "synthetic-worker") == 0
    assert len(calls) == (1 if failure is QueueFull else 64)
    assert discovery.status()["counts"][expected] > 0
    assert discovery.status()["checked_this_cycle"] <= 64


def test_generation_race_cannot_rebase_absence_onto_new_authority(lab, monkeypatch):
    change(lab)
    discovery, queue = lab[2].managed_discovery, lab[2].queue
    assert queue.claim_cycle("synthetic-worker", 135)
    original = discovery.source.admit_absence
    def race(*args, **kwargs):
        change(lab, action="RETIRE")
        change(lab)  # Same timestamp, new explicit intent UUID.
        return original(*args, **kwargs)
    monkeypatch.setattr(discovery.source, "admit_absence", race)
    assert discovery.discover(snapshot(lab), "synthetic-worker") == 0
    assert discovery.status()["counts"] == {"state_changed": 1}
    assert queue.status()["counts"] == {}


@pytest.mark.parametrize("invalid", ["partial", "stale", "future", "reversed"])
def test_incomplete_or_unusable_read_is_never_admitted(lab, invalid):
    change(lab)
    overrides = {"partial": {"complete": False}, "stale": {"started_at": lab[4][0]-timedelta(seconds=121)},
                 "future": {"completed_at": lab[4][0]+timedelta(seconds=1)},
                 "reversed": {"started_at": lab[4][0]+timedelta(seconds=1)}}[invalid]
    with pytest.raises(ValueError):
        lab[2].managed_discovery.discover(snapshot(lab, **overrides), "synthetic-worker")
    assert lab[2].queue.status()["counts"] == {}


def test_failed_read_does_not_turn_cached_presence_into_absence(lab):
    change(lab)
    lab[0].record_observed_shun(1, IP, "management")
    lab[1].fail = True
    sweep(lab)
    assert lab[2].queue.status()["counts"] == {} and lab[0].list_active_shuns()
    assert lab[2].status()["managed_restoration"]["devices"] == {}


def test_discovery_audit_failure_rolls_back_and_preserves_final_monitoring(lab, monkeypatch):
    change(lab)
    lab[2].queue.enqueue(str(uuid4()), [(1, IPv4Address("203.0.113.1"))], "operator", "Operator", ("Operator",))
    original = lab[0]._insert_event
    def fail(db, event, *args, **kwargs):
        if event == "MANAGED_SHUN_RESTORATION_QUEUED":
            raise sqlite3.OperationalError("synthetic private SQL detail")
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(lab[0], "_insert_event", fail)
    sweep(lab)
    assert not lab[1].writes and ("final", 1) in lab[1].reads and ("final", 2) in lab[1].reads
    status = lab[2].status()
    assert "mutations skipped" in status["managed_restoration_error"]
    assert "private SQL" not in str(status) and status["queue"]["counts"] == {"QUEUED": 1}
    with lab[0]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] == 0


def test_priority_and_final_reads_have_distinct_evidence_but_no_cutoff_bypass(lab, monkeypatch):
    change(lab)
    lab[1].entries[1] = [ObservedShun(IP, "management")]
    sync = lab[2]
    seen = []
    original_discover = sync.managed_discovery.discover
    def discover(evidence, owner):
        seen.append(evidence)
        return original_discover(evidence, owner)
    monkeypatch.setattr(sync.managed_discovery, "discover", discover)
    original_publish = sync._publish_snapshot
    def publish(device, entries):
        original_publish(device, entries)
        if device == 1 and len(seen) == 0:
            sync._priority_pending = True
            sync._device_success_at[device] = monotonic()-61
            lab[1].entries[1] = []
    monkeypatch.setattr(sync, "_publish_snapshot", publish)
    sweep(lab)
    first_device = [e for e in seen if e.device_id == 1]
    assert len(first_device) == 3 and len({e.id for e in first_device}) == 3
    assert first_device[0].present_ips == frozenset({IP})
    assert first_device[1].present_ips == first_device[2].present_ips == frozenset()
    assert ("priority", 1) in lab[1].reads
    assert not lab[1].writes and sync.queue.status()["counts"] == {"QUEUED": 1}
    with lab[0]._connection() as db:
        assert db.execute("SELECT snapshot_id FROM managed_restoration_attempts").fetchone()[0] == first_device[1].id


def test_turning_controller_off_holds_previously_admitted_work(lab):
    change(lab)
    sweep(lab)
    lab[2] = Synchronizer(lab[0], lab[1], 300, 60, session_cycles_enabled=True,
                          import_execution_enabled=True, addition_device_ids=frozenset({1}))
    assert not lab[2]._has_pending()
    assert not lab[2].status()["queue"]["items"][0]["execution_enabled"]
    sweep(lab, 61)
    assert not lab[1].writes and lab[2].queue.status()["counts"] == {"QUEUED": 1}


def test_existing_controller_with_revoked_executor_lease_cannot_admit(lab):
    change(lab)
    queue, discovery = lab[2].queue, lab[2].managed_discovery
    assert queue.claim_cycle("synthetic-worker", 135)
    with lab[0]._connection() as db:
        db.execute("UPDATE operation_executor SET owner='different-owner'")
    with pytest.raises(QueueConflict, match="lease"):
        discovery.discover(snapshot(lab), "synthetic-worker")
    assert queue.status()["counts"] == {}


def test_lost_add_result_is_visible_and_never_automatically_replayed(lab):
    change(lab)
    sweep(lab)
    lab[1].lost = True
    sweep(lab, 61)
    assert hold(lab) == "needs_review"
    lab[1].lost = False
    sweep(lab, 301)
    assert lab[1].writes == [(1, IP)] and not lab[2]._has_pending()
    assert hold(lab) == "needs_review"


@pytest.mark.parametrize("reason", ["controller_disabled", "no_addition_profile", "suspended", "not_initialized", "present", "stopped"])
def test_readonly_holds_do_not_admit_or_initialize(lab, reason):
    change(lab)
    context = lab[2].managed_discovery.context
    if reason == "controller_disabled":
        context = RestorationContext(False, frozenset({1}))
    elif reason == "no_addition_profile":
        context = RestorationContext(True, frozenset())
    elif reason == "suspended":
        with lab[0]._connection() as db:
            db.execute("UPDATE managed_shun_registry SET restoration_suspended=1")
    elif reason == "not_initialized":
        with lab[0]._connection() as db:
            db.execute("DROP TABLE managed_restoration_attempts")  # Disposable empty fixture only.
    elif reason == "present":
        lab[0].record_observed_shun(1, IP, "management")
    elif reason == "stopped":
        change(lab, action="RETIRE")
    before = lab[0].list_events()
    view = lab[3].snapshot(restoration_context=context, restoration_now=lab[4][0])
    assert view["entries"][0]["restoration_hold"] == reason
    assert lab[0].list_events() == before and lab[2].queue.status()["counts"] == {}


@pytest.mark.parametrize("raw", ["1", "yes", "TRUE", "", "False"])
def test_restoration_environment_is_strict_boolean(monkeypatch, raw):
    monkeypatch.setenv("FTD_SHUN_MANAGED_RESTORATION_ENABLED", raw)
    with pytest.raises(ValueError, match="RESTORATION|restoration"):
        Settings.from_environment()


def test_restoration_configuration_requires_existing_execution_controls(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_MANAGED_RESTORATION_ENABLED", raising=False)
    settings = Settings.from_environment()
    assert settings.managed_restoration_enabled is False
    with pytest.raises(ValueError, match="restoration"):
        replace(settings, managed_restoration_enabled=True)
    enabled = replace(settings, agent_mode="socket", agent_cycles_enabled=True,
                      large_snapshots_enabled=True, import_execution_enabled=True,
                      managed_restoration_enabled=True)
    assert enabled.managed_restoration_enabled
