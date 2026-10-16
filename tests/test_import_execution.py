"""Gated worker integration with synthetic SQLite, consoles and local sockets only."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from socket import AF_UNIX, SOCK_SEQPACKET, socket
from struct import pack
from threading import Event
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable, UnixAgentClient
from ftd_shun_manager.agent_protocol import AdditionResult, ObservedShun
from ftd_shun_manager.api import _agent, create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.252")
PROFILE = "fpr1010-766-single-vf-management-v1"


class FakeCycle:
    def __init__(self, agent, device):
        self.agent, self.device = agent, device
        self.version = agent.versions.get(device, 2)
        self.initial_snapshot = list(agent.entries.get(device, []))
        self.closed = False

    def add_shun(self, ip):
        self.agent.calls.append(("add", self.device, ip))
        if self.agent.before_add:
            self.agent.before_add(ip)
        behavior = self.agent.behaviors.get(ip)
        if behavior == "defer":
            return None
        if behavior == "malformed":
            return self.agent.bad_result
        if any(entry.ip == ip for entry in self.agent.entries.get(self.device, [])):
            return AdditionResult(False)
        self.agent.entries.setdefault(self.device, []).append(ObservedShun(ip, "management"))
        self.agent.writes.append(("add", self.device, ip))
        if behavior == "lost":
            raise AgentUnavailable("write result lost")
        self.agent.write_finished.set()
        return AdditionResult(True, "management")

    def remove_shun(self, ip):
        self.agent.calls.append(("remove", self.device, ip))
        self.agent.entries[self.device] = [
            entry for entry in self.agent.entries.get(self.device, []) if entry.ip != ip
        ]
        self.agent.writes.append(("remove", self.device, ip))
        return True

    def snapshot(self):
        self.agent.calls.append(("priority", self.device))
        if self.agent.defer_priority:
            return None
        return list(self.agent.entries.get(self.device, []))

    def finish(self):
        self.agent.calls.append(("final", self.device))
        if self.agent.fail_final:
            raise AgentUnavailable("final read lost")
        self.closed = True
        return list(self.agent.entries.get(self.device, []))

    def abort(self):
        self.closed = True


class FakeAgent(AgentClient):
    def __init__(self):
        self.entries = {}
        self.versions = {1: 3}
        self.calls, self.writes, self.cycles = [], [], []
        self.behaviors = {}
        self.bad_result = False
        self.before_add = None
        self.fail_final = self.defer_priority = False
        self.write_finished = Event()

    def open_cycle(self, device):
        self.calls.append(("open", device))
        cycle = FakeCycle(self, device)
        self.cycles.append(cycle)
        return cycle

    def list_shuns(self, *args):
        pytest.fail("No independent read or legacy fallback allowed")

    def remove_shun(self, *args):
        pytest.fail("No independent writer or legacy fallback allowed")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    agent = FakeAgent()
    sync = Synchronizer(
        store,
        agent,
        300,
        60,
        session_cycles_enabled=True,
        import_execution_enabled=True,
        addition_device_ids=frozenset({1}),
    )
    return store, agent, sync


def admit(sync, ips=(IP,), *, device=1, subject="alice", ttl_seconds=900):
    targets = [(device, ip) for ip in ips]
    revision = sync.policy.revision()
    digest = canonical_import(targets, revision, "Fixture", "Synthetic only")[2]
    return sync.queue.enqueue(
        str(uuid4()),
        targets,
        subject,
        subject.title(),
        ("Operator",),
        source="manual_import",
        ttl_seconds=ttl_seconds,
        scope="import",
        batch_label="Fixture",
        batch_reason="Synthetic only",
        policy_revision=revision,
        confirmation_digest=digest,
    )


def advance(sync, monkeypatch, seconds=61):
    clock = sync.queue._now
    monkeypatch.setattr(sync.queue, "_now", lambda: clock() + timedelta(seconds=seconds))


def test_mixed_fifo_shares_sixteen_steps_cooldown_and_one_session(setup):
    store, agent, sync = setup
    expected = []
    for index in range(9):
        added, removed = IPv4Address(0xC6336401 + index), IPv4Address(0xCB007101 + index)
        agent.entries.setdefault(1, []).append(ObservedShun(removed, "management"))
        admit(sync, (added,), subject=f"actor-{index}")
        sync.queue.enqueue(str(uuid4()), [(1, removed)], "bob", "Bob", ("Operator",))
        expected.extend([("add", 1, added), ("remove", 1, removed)])
    assert sync._has_pending()
    asyncio.run(sync._sweep())
    assert agent.writes == expected[:16]
    assert agent.calls[0] == ("open", 1) and agent.calls[-1] == ("final", 1)
    assert len(agent.cycles) == 1 and agent.cycles[0].closed
    assert sync.queue.status()["counts"] == {"VERIFIED": 16, "QUEUED": 2}
    assert sum(bool(row.manual_imports) for row in store.list_active_shuns()) == 8
    assert sync.status()["device_cycle"]["completed"] == 16
    assert sync.status()["device_cycle"]["budget_deferred"]
    assert sync.queue.delay() > 0
    asyncio.run(sync._sweep())
    assert len(agent.cycles) == 1, "A second user/request cannot bypass the persisted cooldown"


@pytest.mark.parametrize("enabled,profiles", [(False, {1}), (True, set())])
def test_missing_gate_or_profile_holds_add_but_keeps_reads_and_removals(setup, enabled, profiles):
    store, agent, _ = setup
    sync = Synchronizer(
        store,
        agent,
        300,
        60,
        session_cycles_enabled=True,
        import_execution_enabled=enabled,
        addition_device_ids=frozenset(profiles),
    )
    agent.versions[1] = 2
    admit(sync)
    assert not sync._has_pending()
    assert not sync.status()["queue"]["items"][0]["execution_enabled"]
    agent.entries[1] = [ObservedShun(OTHER, "management")]
    sync.queue.enqueue(str(uuid4()), [(1, OTHER)], "bob", "Bob", ("Operator",))
    asyncio.run(sync._sweep())
    assert agent.writes == [("remove", 1, OTHER)]
    assert sync.queue.status()["counts"] == {"VERIFIED": 1, "QUEUED": 1}
    assert sync.status()["last_error"] is None
    assert store.list_active_shuns() == []


def test_version_mismatch_refuses_before_claim_without_fallback(setup):
    _, agent, sync = setup
    admit(sync)
    agent.versions[1] = 2
    asyncio.run(sync._sweep())
    assert agent.calls == [("open", 1)]
    assert agent.cycles[0].closed
    assert sync.queue.status()["counts"] == {"QUEUED": 1}
    assert "exact cycle version 3" in sync.status()["last_error"]


@pytest.mark.parametrize("behavior", ["defer", "lost"])
def test_prewrite_deferral_only_requeues_lost_result_never_replays(setup, monkeypatch, behavior):
    store, agent, sync = setup
    admit(sync)
    agent.behaviors[IP] = behavior
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"QUEUED" if behavior == "defer" else "UNVERIFIED": 1}
    assert not any(row.manual_imports for row in store.list_active_shuns())
    if behavior == "defer":
        assert not agent.writes
        assert agent.calls[-1] == ("final", 1)
        assert sync.status()["device_cycle"]["budget_deferred"]
        with store._connection() as db:
            assert db.execute("SELECT dispatch_kind FROM operation_jobs").fetchone()[0] is None
    else:
        assert agent.calls[-1] == ("add", 1, IP)
        advance(sync, monkeypatch)
        asyncio.run(sync._sweep())
        assert [call for call in agent.calls if call[0] == "add"] == [("add", 1, IP)]
        assert sync.queue.status()["counts"] == {"UNVERIFIED": 1}
        assert store.list_active_shuns()[0].manual_imports == ()


@pytest.mark.parametrize(
    "result", [True, "FAILED", AdditionResult(True), AdditionResult(False, "management")]
)
def test_malformed_typed_result_is_uncertain_not_success_or_deferral(setup, result):
    store, agent, sync = setup
    admit(sync)
    agent.behaviors[IP] = "malformed"
    agent.bad_result = result
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"UNVERIFIED": 1}
    assert store.list_active_shuns() == []
    assert ("final", 1) not in agent.calls
    assert agent.cycles[0].closed


def test_noop_does_not_claim_origin_or_issue_add_write(setup):
    store, agent, sync = setup
    agent.entries[1] = [ObservedShun(IP, "management")]
    admit(sync)
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"NOOP": 1}
    assert not agent.writes
    assert store.list_active_shuns()[0].manual_imports == ()
    assert not any(e["event_type"] == "SHUN_ADDED_BY_IMPORT" for e in store.list_events())


def test_final_failure_keeps_verified_origin_and_restart_never_replays(setup, monkeypatch):
    store, agent, sync = setup
    admit(sync)
    agent.fail_final = True
    asyncio.run(sync._sweep())
    assert sync.queue.status()["counts"] == {"VERIFIED": 1}
    origin = store.list_active_shuns()[0].manual_imports
    assert len(origin) == 1
    assert sync.status()["devices"]["1"]["stale"]
    restarted = Synchronizer(
        store,
        agent,
        300,
        60,
        session_cycles_enabled=True,
        import_execution_enabled=True,
        addition_device_ids=frozenset({1}),
    )
    advance(restarted, monkeypatch)
    agent.fail_final = False
    asyncio.run(restarted._sweep())
    assert store.list_active_shuns()[0].manual_imports == origin
    assert agent.writes == [("add", 1, IP)]


def test_shared_actors_receive_one_verified_execution_with_separate_origins(setup):
    store, agent, sync = setup
    admit(sync, subject="alice")
    admit(sync, subject="bob")
    asyncio.run(sync._sweep())
    assert agent.writes == [("add", 1, IP)]
    assert store.list_active_shuns()[0].manual_import_count == 2
    events = [e for e in store.list_events(IP) if e["event_type"] == "SHUN_ADDED_BY_IMPORT"]
    assert {e["actor_subject"] for e in events} == {"alice", "bob"}


def test_expired_coalesced_actor_does_not_acquire_origin_from_later_valid_claim(setup, monkeypatch):
    store, agent, sync = setup
    admit(sync)
    admit(sync, (OTHER,), subject="expired", ttl_seconds=1)
    admit(sync, (OTHER,), subject="valid")

    def advance_after_first(ip):
        if ip == IP:
            advance(sync, monkeypatch, 2)

    agent.before_add = advance_after_first
    asyncio.run(sync._sweep())
    row = store.active_shuns_for_device_ip(1, OTHER)[0]
    assert row.manual_import_count == 1
    assert row.manual_imports[0]["actor_subject"] == "valid"
    events = [e for e in store.list_events(OTHER) if e["event_type"] == "SHUN_ADDED_BY_IMPORT"]
    assert [e["actor_subject"] for e in events] == ["valid"]
    with store._connection() as db:
        assert (
            db.execute(
                "SELECT state FROM operation_requests WHERE actor_subject='expired'"
            ).fetchone()[0]
            == "EXPIRED"
        )


def test_shutdown_leaves_lease_then_recovery_observes_presence_without_replay_or_origin(
    setup, monkeypatch
):
    store, agent, sync = setup
    admit(sync)
    started, release = Event(), Event()

    def block(ip):
        started.set()
        assert release.wait(5)

    agent.before_add = block

    async def scenario():
        task = asyncio.create_task(sync._sweep())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sync.queue.status()["counts"] == {"RUNNING": 1}
            assert sync.queue.delay() > 60
            assert agent.cycles[0].closed
            release.set()
            assert await asyncio.to_thread(agent.write_finished.wait, 5)
            restarted = Synchronizer(
                store,
                agent,
                300,
                60,
                session_cycles_enabled=True,
                import_execution_enabled=True,
                addition_device_ids=frozenset({1}),
            )
            await restarted._sweep()
            assert len(agent.cycles) == 1, "Another owner must wait for the abandoned lease"
            advance(restarted, monkeypatch, 136)
            await restarted._sweep()
            assert restarted.queue.status()["counts"] == {"UNVERIFIED": 1}
            assert agent.writes == [("add", 1, IP)]
            assert store.list_active_shuns()[0].manual_imports == ()
        finally:
            release.set()

    asyncio.run(scenario())


def test_priority_read_between_verified_adds_preserves_cutoff_cancellation_and_provenance(setup):
    store, agent, sync = setup
    third, later = IPv4Address("203.0.113.3"), IPv4Address("203.0.113.4")
    admit(sync, (IP, OTHER))
    cancelled = admit(sync, (third,), subject="bob")
    started, release, second_started, second_release = [Event() for _ in range(4)]

    def block(ip):
        first = ip == IP
        (started if first else second_started).set()
        assert (release if first else second_release).wait(5)

    agent.before_add = block

    async def scenario():
        task = asyncio.create_task(sync._sweep())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert sync.status()["device_cycle"]["action"] == "add_and_verify"
            sync._device_success_at[1] -= 61
            old_revision = sync.status()["data_revision"]
            for _ in range(3):
                assert sync.request_activity()["interactive_refresh_state"] == "checkpoint_pending"
            release.set()
            assert await asyncio.to_thread(second_started.wait, 5)
            assert agent.calls[:4] == [
                ("open", 1),
                ("add", 1, IP),
                ("priority", 1),
                ("add", 1, OTHER),
            ]
            assert sync.status()["data_revision"] > old_revision
            assert store.list_active_shuns()[0].manual_import_count == 1
            sync.queue.cancel(cancelled["operation_id"], "bob", False)
            admit(sync, (later,), subject="charlie")
            second_release.set()
            await task
            assert sync.queue.status()["counts"] == {"VERIFIED": 2, "CANCELLED": 1, "QUEUED": 1}
            assert len([call for call in agent.calls if call[0] == "priority"]) == 1
            assert len(agent.writes) == 2
        finally:
            release.set()
            second_release.set()
            await task

    asyncio.run(scenario())


def test_live_policy_enable_and_authorization_expiry_are_rechecked_before_next_claim(
    setup, monkeypatch
):
    _, agent, sync = setup
    protected, expired = OTHER, IPv4Address("203.0.113.3")
    admit(sync, (IP, protected, expired))

    def change(ip):
        assert ip == IP
        sync.policy.change(
            "add", protected, sync.policy.revision(), "admin", "Admin", ("Administrator",)
        )
        advance(sync, monkeypatch, 901)
        # Keep the current worker lease alive; expire only queued authorizations.
        with sync.store._connection() as db:
            db.execute(
                "UPDATE operation_executor SET lease_until=?",
                ((sync.queue._now() + timedelta(seconds=135)).isoformat(),),
            )

    agent.before_add = change
    asyncio.run(sync._sweep())
    assert agent.writes == [("add", 1, IP)]
    assert sync.queue.status()["counts"] == {"VERIFIED": 1, "FAILED": 2}


def test_other_unprofiled_device_keeps_ordinary_mode_and_does_not_starve(setup):
    store, agent, sync = setup
    store.upsert_device(Device(2, "lab-2", IPv4Address("192.0.2.2"), True), "ssh-ed25519 AAAA")
    admit(sync, device=1)
    admit(sync, (OTHER,), device=2)
    asyncio.run(sync._sweep())
    assert agent.writes == [("add", 1, IP)]
    assert [cycle.version for cycle in agent.cycles] == [3, 2]
    assert sync.status()["devices"]["2"]["state"] == "ready"
    assert not sync._has_pending()
    held = next(item for item in sync.status()["queue"]["items"] if item["state"] == "QUEUED")
    assert held["device_id"] == 2 and not held["execution_enabled"]


def test_api_selector_requires_explicit_gate_and_device_set(monkeypatch):
    settings = replace(
        Settings.from_environment(),
        agent_mode="socket",
        agent_cycles_enabled=True,
        large_snapshots_enabled=True,
        import_execution_enabled=True,
    )
    monkeypatch.setattr(agent_client, "UnixAgentCycle", lambda *args, **kwargs: kwargs["version"])
    client = _agent(settings, addition_device_ids=frozenset({1}))
    assert client.open_cycle(1) == 3 and client.open_cycle(2) == 2
    assert _agent(settings).open_cycle(1) == 2, "No set may imply all devices"
    assert (
        _agent(
            replace(settings, import_execution_enabled=False), addition_device_ids=frozenset({1})
        ).open_cycle(1)
        == 2
    )


def test_gate_defaults_strict_dependencies_and_intake_independence(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_IMPORT_EXECUTION_ENABLED", raising=False)
    assert not Settings.from_environment().import_execution_enabled
    monkeypatch.setenv("FTD_SHUN_IMPORT_EXECUTION_ENABLED", "TRUE")
    with pytest.raises(ValueError, match="true or false"):
        Settings.from_environment()
    monkeypatch.setenv("FTD_SHUN_IMPORT_EXECUTION_ENABLED", "true")
    for mode, cycles, large in [
        ("mock", "true", "true"),
        ("socket", "false", "true"),
        ("socket", "true", "false"),
    ]:
        monkeypatch.setenv("FTD_SHUN_AGENT_MODE", mode)
        monkeypatch.setenv("FTD_SHUN_AGENT_CYCLES_ENABLED", cycles)
        monkeypatch.setenv("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", large)
        with pytest.raises(ValueError, match="requires socket"):
            Settings.from_environment()
    monkeypatch.setenv("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", "true")
    monkeypatch.setenv("FTD_SHUN_IMPORT_ADMISSION_ENABLED", "false")
    assert Settings.from_environment().import_execution_enabled


def test_private_admission_wakes_only_eligible_new_work_and_reports_device_capability(
    setup, tmp_path, monkeypatch
):
    store, agent, _ = setup
    inventory = tmp_path / "fixture-inventory.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "id": index,
                    "hostname": f"lab-{index}",
                    "management_ip": f"192.0.2.{index}",
                    "ssh_host_key": "ssh-ed25519 AAAA",
                    "allowed_interfaces": ["management"],
                    "addition_profile": PROFILE if index == 1 else None,
                }
                for index in [1, 2]
            ]
        )
    )
    settings = replace(
        Settings.from_environment(),
        database_path=store.path,
        device_inventory_path=inventory,
        agent_mode="socket",
        agent_cycles_enabled=True,
        large_snapshots_enabled=True,
        import_admission_enabled=True,
        import_execution_enabled=True,
    )
    app = create_app(settings, store=store, agent_client=agent)
    signals = []
    monkeypatch.setattr(app.state.synchronizer, "signal_work", lambda: signals.append("work"))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://internal"
        ) as client:
            for device in [1, 2]:
                revision = app.state.synchronizer.policy.revision()
                body = {
                    "actor": {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]},
                    "targets": [{"device_id": device, "ip": str(IP)}],
                    "policy_revision": revision,
                    "confirmation_digest": canonical_import([(device, IP)], revision)[2],
                }
                headers = {"Idempotency-Key": str(uuid4())}
                result = await client.post("/api/v1/imports", json=body, headers=headers)
                assert result.status_code == 202
                assert result.json()["execution_enabled"] == (device == 1)
                assert (await client.post("/api/v1/imports", json=body, headers=headers)).json()[
                    "replayed"
                ]
            status = (await client.get("/api/v1/status")).json()
            assert status["addition_device_count"] == 1 and status["import_execution_enabled"]
            assert [item["execution_enabled"] for item in status["queue"]["items"]] == [True, False]
            assert signals == ["work"] and agent.calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("lost", [False, True])
def test_real_seqpacket_worker_commits_verified_only_and_never_retries(setup, tmp_path, lost):
    store, _, sync = setup
    path = str(tmp_path / "agent.sock")
    sync.agent = UnixAgentClient(
        path, 2, large_snapshots=True, additions_enabled=True, addition_device_ids=frozenset({1})
    )
    admit(sync)

    def frames(opcode, sequence, present=False):
        prefix = bytes([0, 3, opcode, sequence])
        data = IP.packed + b"\x0amanagement" if present else b""
        result = [prefix + b"\0" + pack(">IIH", int(present), len(data), int(present))]
        if present:
            result.append(prefix + b"\1\0\0" + data)
        return result + [prefix + b"\2" + hashlib.sha256(data).digest()]

    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                assert connection.recv(100) == bytes([16, 3, 0, 1])
                for frame in frames(16, 0):
                    connection.send(frame)
                assert connection.recv(100) == bytes([20, 3, 1]) + IP.packed
                if lost:
                    return  # Possible write without result: no retry or invented provenance.
                connection.send(bytes([0, 3, 20, 1, 1, 10]) + b"management")
                assert connection.recv(100) == bytes([19, 3, 2])
                for frame in frames(19, 2, True):
                    connection.send(frame)
                assert connection.recv(100) == b""

        worker = pool.submit(server)
        asyncio.run(sync._sweep())
        worker.result(timeout=3)
    assert sync.queue.status()["counts"] == {"UNVERIFIED" if lost else "VERIFIED": 1}
    assert len(store.list_active_shuns()) == (0 if lost else 1)
    if not lost:
        assert store.list_active_shuns()[0].manual_import_count == 1
