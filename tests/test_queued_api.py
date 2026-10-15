import asyncio
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx

from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.store import Device, Store


class RecordingAgent(AgentClient):
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.snapshot = [ObservedShun(IPv4Address("198.51.100.10"), "outside")]

    def list_shuns(self, device_id):
        self.calls.append(("list", device_id))
        return list(self.snapshot)

    def remove_shun(self, device_id, ip):
        self.calls.append(("remove", device_id, str(ip)))
        if self.fail:
            raise AgentUnavailable("reply lost")
        self.snapshot = [entry for entry in self.snapshot if entry.ip != ip]


def settings(tmp_path):
    return Settings(
        database_path=tmp_path / "state.db", device_inventory_path=None,
        agent_socket="/unused/agent.sock", web_socket="/unused/web.sock",
        api_socket="/unused/api.sock", agent_mode="mock", agent_timeout_seconds=45,
        poll_interval_seconds=300, interactive_refresh_min_interval_seconds=60,
        history_retention_days=366, sensitive_action_max_age_seconds=86400,
        development_auth=False, trusted_auto_remove_ips=frozenset(),
    )


def setup_app(tmp_path, agent):
    config = settings(tmp_path)
    store = Store(config.database_path)
    store.initialize()
    store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    store.record_observed_shun(1, IPv4Address("198.51.100.10"), "outside")
    return create_app(config, store, agent), store


def test_admission_is_not_execution_and_bulk_idempotency_freezes_targets(tmp_path):
    agent = RecordingAgent()
    app, store = setup_app(tmp_path, agent)
    operator = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}
    key = str(uuid4())

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            response = await client.post("/api/v1/shuns/198.51.100.10/remove-all", json=operator,
                                         headers={"Idempotency-Key": key})
            assert response.status_code == 202
            assert response.json()["operation_id"] == key
            assert agent.calls == []
            assert store.list_active_shuns()
            assert not any(e["event_type"] == "SHUN_REMOVED_BY_UI" for e in store.list_events())
            duplicate = await client.post("/api/v1/shuns/198.51.100.10/remove-all", json=operator,
                                          headers={"Idempotency-Key": key})
            assert duplicate.json()["replayed"] is True
            # Only the owning scheduler dispatches agent RPC.
            await app.state.synchronizer._sweep()
            assert agent.calls == [("list", 1), ("remove", 1, "198.51.100.10")]
            assert store.list_active_shuns() == []
            assert app.state.synchronizer.queue.status()["counts"] == {"VERIFIED": 1}
            replay = await client.post("/api/v1/shuns/198.51.100.10/remove-all", json=operator,
                                       headers={"Idempotency-Key": key})
            assert replay.status_code == 202
            assert replay.json()["replayed"] is True
            conflict = await client.post("/api/v1/shuns/203.0.113.1/remove-all", json=operator,
                                         headers={"Idempotency-Key": key})
            assert conflict.status_code == 409
            denied = await client.request("DELETE", "/api/v1/devices/1/shuns/198.51.100.10",
                json={**operator, "roles": ["Viewer"]})
            assert denied.status_code == 403
            assert len(agent.calls) == 2

    asyncio.run(scenario())


def test_unverified_write_is_not_automatically_retried(tmp_path, monkeypatch):
    agent = RecordingAgent(fail=True)
    app, store = setup_app(tmp_path, agent)
    synchronizer = app.state.synchronizer
    synchronizer.queue.enqueue(str(uuid4()), [(1, IPv4Address("198.51.100.10"))],
                               "alice", "Alice", ("Operator",))

    async def scenario():
        await synchronizer._sweep()
        assert synchronizer.queue.status()["counts"] == {"UNVERIFIED": 1}
        assert store.list_active_shuns()
        assert not any(e["event_type"] == "SHUN_REMOVED_BY_UI" for e in store.list_events())
        original_clock = synchronizer.queue._now
        monkeypatch.setattr(synchronizer.queue, "_now", lambda: original_clock() + timedelta(seconds=61))
        await synchronizer._sweep()
        assert len([call for call in agent.calls if call[0] == "remove"]) == 1
        assert synchronizer.queue.status()["counts"] == {"UNVERIFIED": 1}

    asyncio.run(scenario())


def test_cancel_request_before_dispatch_and_persisted_cycle_cooldown(tmp_path):
    agent = RecordingAgent()
    app, store = setup_app(tmp_path, agent)
    operator = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            response = await client.request("DELETE", "/api/v1/devices/1/shuns/198.51.100.10", json=operator)
            operation_id = response.json()["operation_id"]
            denied = await client.post(f"/api/v1/operations/{operation_id}/cancel", json={**operator, "subject": "bob"})
            assert denied.status_code == 403
            cancelled = await client.post(f"/api/v1/operations/{operation_id}/cancel", json=operator)
            assert cancelled.status_code == 200
            await app.state.synchronizer._sweep()
            assert agent.calls == [("list", 1)]
            restarted = create_app(settings(tmp_path), store, agent)
            await restarted.state.synchronizer._sweep()
            assert agent.calls == [("list", 1)]
            assert restarted.state.synchronizer.queue.delay() > 0

    asyncio.run(scenario())


def test_a_device_executes_only_one_removal_per_eligible_cycle(tmp_path, monkeypatch):
    agent = RecordingAgent()
    second = IPv4Address("203.0.113.2")
    agent.snapshot.append(ObservedShun(second, "outside"))
    app, store = setup_app(tmp_path, agent)
    store.record_observed_shun(1, second, "outside")
    synchronizer = app.state.synchronizer
    for ip in (IPv4Address("198.51.100.10"), second):
        synchronizer.queue.enqueue(str(uuid4()), [(1, ip)], "alice", "Alice", ("Operator",))

    async def scenario():
        await synchronizer._sweep()
        assert synchronizer.queue.status()["counts"] == {"VERIFIED": 1, "QUEUED": 1}
        await synchronizer._sweep()
        assert len([call for call in agent.calls if call[0] == "remove"]) == 1
        original_clock = synchronizer.queue._now
        monkeypatch.setattr(synchronizer.queue, "_now", lambda: original_clock() + timedelta(seconds=61))
        await synchronizer._sweep()
        assert synchronizer.queue.status()["counts"] == {"VERIFIED": 2}
        assert len([call for call in agent.calls if call[0] == "remove"]) == 2
        assert store.list_active_shuns() == []

    asyncio.run(scenario())
