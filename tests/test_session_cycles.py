import asyncio
from ipaddress import IPv4Address
from threading import Event
from uuid import uuid4

from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer


class FakeCycle:
    def __init__(self, agent):
        self.agent = agent
        self.initial_snapshot = list(agent.entries)
        self.closed = False

    def remove_shun(self, ip):
        self.agent.calls.append(("remove", str(ip)))
        number = len([call for call in self.agent.calls if call[0] == "remove"])
        if number in self.agent.gates:
            started, release = self.agent.gates[number]
            started.set()
            assert release.wait(5), "test operation release timed out"
        if number == self.agent.fail_at:
            raise AgentUnavailable("write response lost")
        if number == self.agent.defer_at:
            return None
        self.agent.entries = [entry for entry in self.agent.entries if entry.ip != ip]
        self.agent.write_finished.set()
        return True

    def snapshot(self):
        self.agent.calls.append(("priority",))
        if self.agent.defer_priority:
            return None
        return list(self.agent.entries)

    def finish(self):
        self.agent.calls.append(("final",))
        if self.agent.fail_final:
            raise AgentUnavailable("final snapshot lost")
        self.closed = True
        return list(self.agent.entries)

    def abort(self):
        self.closed = True


class CycleAgent(AgentClient):
    def __init__(self, count):
        self.entries = [ObservedShun(IPv4Address(f"198.51.100.{index}"), "outside")
                        for index in range(1, count + 1)]
        self.calls = []
        self.gates = {}
        self.fail_at = self.defer_at = None
        self.fail_final = False
        self.defer_priority = False
        self.cycle = None
        self.write_finished = Event()

    def open_cycle(self, device_id):
        self.calls.append(("open", device_id))
        self.cycle = FakeCycle(self)
        return self.cycle

    def list_shuns(self, device_id):
        raise AssertionError("session failure must not fall back to legacy RPC")

    def remove_shun(self, device_id, ip):
        raise AssertionError("session work must not use legacy writes")


def setup(tmp_path, count):
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab-ftd", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    agent = CycleAgent(count)
    sync = Synchronizer(store, agent, 300, 60, session_cycles_enabled=True)
    requests = []
    for index, entry in enumerate(agent.entries):
        request_id = str(uuid4())
        sync.queue.enqueue(request_id, [(1, entry.ip)], f"user-{index // 10}", "Operator", ("Operator",))
        requests.append(request_id)
    return store, agent, sync, requests


def test_many_removals_share_one_cycle_and_obey_count_limit(tmp_path):
    store, agent, sync, _ = setup(tmp_path, 18)
    asyncio.run(sync._sweep())
    assert agent.calls[0] == ("open", 1)
    assert agent.calls[-1] == ("final",)
    assert len([call for call in agent.calls if call[0] == "remove"]) == 16
    assert sync.queue.status()["counts"] == {"QUEUED": 2, "VERIFIED": 16}
    assert len(store.list_active_shuns()) == 2
    assert sync.queue.delay() > 0
    assert agent.cycle.closed


def test_priority_read_runs_after_verification_before_next_item_and_publishes(tmp_path):
    store, agent, sync, requests = setup(tmp_path, 3)
    first_started, first_release, second_started, second_release = [Event() for _ in range(4)]
    agent.gates = {1: (first_started, first_release), 2: (second_started, second_release)}

    async def scenario():
        task = asyncio.create_task(sync._sweep())
        try:
            assert await asyncio.to_thread(first_started.wait, 5)
            # A recent initial snapshot satisfies demand without another command.
            assert sync.request_activity()["interactive_refresh_state"] == "snapshot_recent"
            assert not sync._priority_pending
            sync._device_success_at[1] -= 61
            assert sync.status()["priority_refresh_available"]
            initial_revision = sync.status()["data_revision"]
            for _ in range(3):
                assert sync.request_activity()["interactive_refresh_state"] == "checkpoint_pending"
            first_release.set()
            assert await asyncio.to_thread(second_started.wait, 5)
            assert agent.calls[:4] == [("open", 1), ("remove", "198.51.100.1"),
                                      ("priority",), ("remove", "198.51.100.2")]
            assert sync.status()["data_revision"] > initial_revision
            assert not task.done()
            assert sync.queue.status()["counts"] == {"VERIFIED": 1, "RUNNING": 1, "QUEUED": 1}
            # Later demand joins the final snapshot, never a second priority read.
            sync._device_success_at[1] -= 61
            assert sync.request_activity()["interactive_refresh_state"] == "running"
            sync.queue.cancel(requests[2], "user-0", False)
            # New manual work must wait, even while the session is still running.
            sync.queue.enqueue(str(uuid4()), [(1, IPv4Address("203.0.113.9"))],
                               "new-user", "New user", ("Operator",))
            second_release.set()
            await task
            assert len([call for call in agent.calls if call[0] == "priority"]) == 1
            assert sync.queue.status()["counts"] == {"VERIFIED": 2, "CANCELLED": 1, "QUEUED": 1}
            assert len(store.list_active_shuns()) == 1
        finally:
            first_release.set()
            second_release.set()
            await task

    asyncio.run(scenario())


def test_exact_prewrite_deferral_requeues_but_lost_response_does_not(tmp_path):
    _, agent, sync, _ = setup(tmp_path, 3)
    agent.defer_at = 2
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"VERIFIED": 1, "QUEUED": 2}
    assert sync.status()["device_cycle"]["budget_deferred"]
    assert agent.calls[-1] == ("final",)
    assert any(event["event_type"] == "SHUN_OPERATION_DEFERRED" for event in sync.store.list_events())


def test_priority_budget_exhaustion_joins_final_snapshot_and_defers_next_write(tmp_path):
    _, agent, sync, _ = setup(tmp_path, 2)
    agent.defer_priority = True
    started, release = Event(), Event()
    agent.gates = {1: (started, release)}

    async def scenario():
        task = asyncio.create_task(sync._sweep())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            sync._device_success_at[1] -= 61
            assert sync.request_activity()["interactive_refresh_state"] == "checkpoint_pending"
            release.set()
            await task
            assert agent.calls == [("open", 1), ("remove", "198.51.100.1"), ("priority",), ("final",)]
            assert sync.queue.status()["counts"] == {"VERIFIED": 1, "QUEUED": 1}
            assert sync.status()["device_cycle"]["budget_deferred"]
        finally:
            release.set()
            await task

    asyncio.run(scenario())


def test_later_failure_preserves_verified_results_and_does_not_dispatch_rest(tmp_path):
    store, agent, sync, _ = setup(tmp_path, 3)
    agent.fail_at = 2
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"VERIFIED": 1, "UNVERIFIED": 1, "QUEUED": 1}
    assert len(store.list_active_shuns()) == 2
    assert ("final",) not in agent.calls
    assert agent.cycle.closed
    assert sync.status()["cycle_outcome"] == "partial"
    assert sync.status()["devices"]["1"]["last_error"]


def test_final_snapshot_failure_does_not_revoke_verified_write(tmp_path):
    store, agent, sync, _ = setup(tmp_path, 1)
    agent.fail_final = True
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"VERIFIED": 1}
    assert store.list_active_shuns() == []
    assert sync.status()["devices"]["1"]["stale"]


def test_unsupported_cycles_fail_without_fallback(tmp_path):
    _, _, sync, _ = setup(tmp_path, 1)
    sync.agent = AgentClient()
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"QUEUED": 1}
    assert sync.status()["cycle_outcome"] == "failed"


def test_device_failure_does_not_hide_following_healthy_device(tmp_path):
    store, agent, sync, _ = setup(tmp_path, 1)
    store.upsert_device(Device(2, "lab-second", IPv4Address("192.0.2.2"), True), "ssh-ed25519 AAAA")
    original = agent.open_cycle

    def open_cycle(device_id):
        if device_id == 1:
            raise AgentUnavailable("device unavailable")
        return original(device_id)

    agent.open_cycle = open_cycle
    asyncio.run(sync._sweep())
    assert sync.status()["cycle_outcome"] == "partial"
    assert sync.status()["devices"]["1"]["state"] == "error"
    assert sync.status()["devices"]["2"]["state"] == "ready"
    assert agent.calls == [("open", 2), ("final",)]


def test_new_policy_discovery_uses_same_session_budget(tmp_path):
    store, agent, sync, _ = setup(tmp_path, 0)
    agent.entries = [ObservedShun(IPv4Address("203.0.113.8"), "outside"),
                     ObservedShun(IPv4Address("203.0.113.9"), "outside")]
    sync.trusted_auto_remove_ips = frozenset(entry.ip for entry in agent.entries)
    asyncio.run(sync._sweep())
    assert agent.calls == [("open", 1), ("remove", "203.0.113.8"),
                           ("remove", "203.0.113.9"), ("final",)]
    assert sync.queue.status()["counts"] == {"VERIFIED": 2}
    assert store.list_active_shuns() == []
    events = [event for event in store.list_events() if event["event_type"] == "SHUN_TRUSTED_AUTO_REMOVED"]
    assert len(events) == 2
    assert all(event["actor_subject"] == "system:trusted-ip-policy" for event in events)


def test_shutdown_keeps_lease_and_restart_reconciles_without_replay(tmp_path, monkeypatch):
    from datetime import timedelta

    store, agent, sync, _ = setup(tmp_path, 1)
    started, release = Event(), Event()
    agent.gates = {1: (started, release)}

    async def scenario():
        task = asyncio.create_task(sync._sweep())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert sync.queue.status()["counts"] == {"RUNNING": 1}
            assert sync.queue.delay() > 60
            assert agent.cycle.closed
            release.set()
            assert await asyncio.to_thread(agent.write_finished.wait, 5)
            restarted = Synchronizer(store, agent, 300, 60, session_cycles_enabled=True)
            await restarted._sweep()
            assert len([call for call in agent.calls if call[0] == "open"]) == 1
            clock = restarted.queue._now
            monkeypatch.setattr(restarted.queue, "_now", lambda: clock() + timedelta(seconds=136))
            await restarted._sweep()
            assert restarted.queue.status()["counts"] == {"RECONCILED_ABSENT": 1}
            assert len([call for call in agent.calls if call[0] == "remove"]) == 1
            assert not any(event["event_type"] == "SHUN_REMOVED_BY_UI" for event in store.list_events())
        finally:
            release.set()

    asyncio.run(scenario())
