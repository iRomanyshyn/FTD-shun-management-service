"""Slow local SQL must not freeze API timers/status or escape lease drain."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from test_continuous_dispatch import TracedAgent, grant, wait
from test_continuous_dispatch import bulk as bulk_fixture
from test_continuous_dispatch import cancellation_controls as cancellation_fixture
from test_continuous_dispatch import continuous as continuous_fixture
from test_continuous_dispatch import dispatch as dispatch_fixture
from test_continuous_dispatch import journal as journal_fixture
from test_continuous_dispatch import leases as leases_fixture
from test_continuous_dispatch import waits as waits_fixture

from ftd_shun_manager.bulk_discovery import BulkDiscovery
from ftd_shun_manager.parallel_synchronizer import _DeviceWorker

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
continuous = continuous_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


def test_status_never_waits_on_the_discovery_database_lock(continuous):
    discovery = BulkDiscovery(continuous[0].runner.store, continuous[0].runner.queue)
    entered, release = Event(), Event()

    def locked():
        with discovery._lock:
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(locked)
        assert entered.wait(1)
        try:
            started = monotonic()
            status = discovery.status()
            assert monotonic() - started < 0.2
            status['devices']['forged'] = {}
            assert not discovery.status()['devices']
        finally:
            release.set()
            future.result(timeout=1)


def test_repeated_cancellation_joins_already_dispatched_local_work():
    worker = SimpleNamespace(_stop_mutations=False)
    entered, release = Event(), Event()
    completions = []

    def blocked():
        entered.set()
        assert release.wait(3)
        completions.append('settled')

    async def scenario():
        task = asyncio.create_task(_DeviceWorker._local_call(worker, blocked))
        await wait(entered)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and worker._stop_mutations
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert completions == ['settled']


def test_blocked_discovery_keeps_event_loop_and_status_responsive_but_stop_drains(continuous, monkeypatch):
    service, _, _ = continuous
    entered, release = Event(), Event()
    original = _DeviceWorker._discover_snapshot

    def blocked(self, *args):
        entered.set()
        assert release.wait(5), 'Synthetic local SQL release missing'
        return original(self, *args)
    monkeypatch.setattr(_DeviceWorker, '_discover_snapshot', blocked)

    async def scenario():
        await service.start()
        try:
            await wait(entered)
            started = monotonic()
            status = service.refresh_status()
            assert monotonic() - started < 1
            assert status['refresh_in_progress']
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0.05)
            assert not stopping.done(), 'Stop must not abandon local work or its lease'
            release.set()
            await stopping
            assert not service.runner._broken
        finally:
            release.set()
            await service.stop()
    asyncio.run(scenario())


def test_one_ssh_session_processes_a_verified_chunk_not_one_login_per_address(continuous, bulk):
    service, agent, _ = continuous
    assert isinstance(agent, TracedAgent)
    grant(bulk, devices=(1,), count=40)

    async def scenario():
        await service.start()
        try:
            async with asyncio.timeout(15):
                while sum(kind == 'add' for kind, device, _ in agent.trace if device == 1) < 32:
                    await asyncio.sleep(0.01)
        finally:
            await service.stop()
    asyncio.run(scenario())
    chunks, current = [], None
    for kind, device, _ in agent.trace:
        if device != 1:
            continue
        if kind == 'open':
            if current is not None:
                chunks.append(current)
            current = 0
        elif kind == 'add':
            assert current is not None
            current += 1
    if current is not None:
        chunks.append(current)
    assert max(chunks) == 16 and all(value <= 16 for value in chunks)
    assert len(chunks) < sum(chunks), 'A shared SSH session must amortize login across addresses'
