import asyncio
from ipaddress import IPv4Address
from time import monotonic

from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer


class SnapshotAgent(AgentClient):
    def __init__(self, snapshot: list[ObservedShun] | None = None) -> None:
        self.snapshot = snapshot or []

    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        assert device_id == 1
        return self.snapshot

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        raise AssertionError("not used by the synchronizer")


class FailingAgent(SnapshotAgent):
    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        raise AgentUnavailable("agent did not return a valid shun snapshot")


class AutoRemovingAgent(SnapshotAgent):
    def __init__(self, snapshot: list[ObservedShun] | None = None, fail: bool = False) -> None:
        super().__init__(snapshot)
        self.removals: list[tuple[int, IPv4Address]] = []
        self.fail = fail

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        self.removals.append((device_id, ip))
        if self.fail:
            raise AgentUnavailable("verified removal was not returned")


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    return store


async def _immediate(function, *args):
    return function(*args)


def test_synchronizer_reconciles_a_typed_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _immediate)
    synchronizer = Synchronizer(
        _store(tmp_path),
        SnapshotAgent([ObservedShun(IPv4Address("198.51.100.250"), "management")]),
        300,
        60,
    )

    asyncio.run(synchronizer._sweep())

    status = synchronizer.status()
    assert status["last_successful_refresh"] is not None
    assert status["last_error"] is None
    assert status["devices"][1]["last_successful_refresh"] is not None
    assert status["devices"][1]["last_error"] is None


def test_synchronizer_surfaces_agent_failure_without_reconciling(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _immediate)
    store = _store(tmp_path)
    synchronizer = Synchronizer(store, FailingAgent(), 300, 60)

    asyncio.run(synchronizer._sweep())

    status = synchronizer.status()
    assert status["last_successful_refresh"] is None
    assert status["last_error"] == "device 1: agent did not return a valid shun snapshot"
    assert store.list_active_shuns() == []


def test_synchronizer_rate_limits_browser_hints_after_any_sweep(tmp_path) -> None:
    synchronizer = Synchronizer(_store(tmp_path), SnapshotAgent(), 300, 60)
    synchronizer._last_sweep_at = monotonic()

    synchronizer._queue_activity()

    assert synchronizer.status()["interactive_refresh_state"] == "rate_limited"
    assert not synchronizer._activity.is_set()


def test_synchronizer_exposes_interactive_cooldown_after_queueing_first_refresh(tmp_path) -> None:
    synchronizer = Synchronizer(_store(tmp_path), SnapshotAgent(), 300, 60)

    synchronizer._queue_activity()

    assert synchronizer.status()["interactive_refresh_state"] == "queued"
    assert synchronizer.status()["next_interactive_refresh"] is not None


def test_synchronizer_defers_manual_hint_to_imminent_baseline(tmp_path) -> None:
    synchronizer = Synchronizer(_store(tmp_path), SnapshotAgent(), 300, 60)
    synchronizer._last_sweep_at = monotonic() - 120
    synchronizer._next_baseline_at = monotonic() + 30

    synchronizer._queue_activity()

    assert synchronizer.status()["interactive_refresh_state"] == "baseline_pending"
    assert not synchronizer._activity.is_set()


def test_synchronizer_queues_manual_hint_when_baseline_is_not_imminent(tmp_path) -> None:
    synchronizer = Synchronizer(_store(tmp_path), SnapshotAgent(), 300, 60)
    synchronizer._last_sweep_at = monotonic() - 120
    synchronizer._next_baseline_at = monotonic() + 180

    synchronizer._queue_activity()

    assert synchronizer.status()["interactive_refresh_state"] == "queued"
    assert synchronizer._activity.is_set()


def test_synchronizer_automatically_removes_exact_trusted_ip_after_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _immediate)
    target = IPv4Address("198.51.100.250")
    store = _store(tmp_path)
    agent = AutoRemovingAgent([ObservedShun(target, "management")])
    synchronizer = Synchronizer(store, agent, 300, 60, frozenset({target}))

    asyncio.run(synchronizer._sweep())

    assert agent.removals == [(1, target)]
    assert store.list_active_shuns() == []
    event_types = [event["event_type"] for event in store.list_events(target)]
    assert "SHUN_TRUSTED_AUTO_REMOVE_REQUESTED" in event_types
    assert "SHUN_TRUSTED_AUTO_REMOVED" in event_types


def test_synchronizer_records_trusted_auto_removal_failure_without_claiming_success(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _immediate)
    target = IPv4Address("198.51.100.250")
    store = _store(tmp_path)
    agent = AutoRemovingAgent([ObservedShun(target, "management")], fail=True)
    synchronizer = Synchronizer(store, agent, 300, 60, frozenset({target}))

    asyncio.run(synchronizer._sweep())

    assert agent.removals == [(1, target)]
    assert [(str(shun.ip), shun.interface) for shun in store.list_active_shuns()] == [
        ("198.51.100.250", "management")
    ]
    event_types = [event["event_type"] for event in store.list_events(target)]
    assert "SHUN_TRUSTED_AUTO_REMOVE_FAILED" in event_types
    assert "SHUN_TRUSTED_AUTO_REMOVED" not in event_types
