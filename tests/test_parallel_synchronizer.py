"""Actual shared semantic rounds with disposable journals and blocking fake RPCs."""

import asyncio
from datetime import timedelta
from ipaddress import IPv4Address
from threading import Event, Lock

import pytest
from test_bulk_policy import dump
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import grant
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture
from test_managed_discovery import Agent, Console

from ftd_shun_manager.agent_client import AgentUnavailable
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.parallel_synchronizer import ParallelSynchronizer
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


class BlockingAgent(Agent):
    def __init__(self):
        super().__init__()
        self.entries = {i: [] for i in range(1, 11)}
        self.lock = Lock()
        self.active, self.maximum, self.seen = set(), 0, set()
        self.block_open, self.block_add = set(), set()
        self.fail_open, self.fail_add, self.fail_final = set(), set(), set()
        self.entered = {i: Event() for i in self.entries}
        self.releases = {i: Event() for i in self.entries}
        self.finished = {i: Event() for i in self.entries}
        self.removals = []

    def open_cycle(self, device):
        with self.lock:
            assert device not in self.active
            self.active.add(device)
            self.seen.add(device)
            self.maximum = max(self.maximum, len(self.active))
        if device in self.block_open:
            self.entered[device].set()
            assert self.releases[device].wait(10), 'Synthetic open release was not supplied.'
        if device in self.fail_open:
            with self.lock: self.active.remove(device)
            raise AgentUnavailable('Synthetic failed opening RPC')
        self.reads.append(('initial', device))
        agent = self

        class Session(Console):
            closed = False

            def add_shun(self, ip):
                if device in agent.block_add:
                    agent.entered[device].set()
                    assert agent.releases[device].wait(10), 'Synthetic ADD release was not supplied.'
                if device in agent.fail_add:
                    agent.writes.append((device, ip))
                    raise AgentUnavailable('Synthetic lost ADD reply')
                return super().add_shun(ip)

            def finish(self):
                if device in agent.fail_final:
                    raise AgentUnavailable('Synthetic lost final read')
                return super().finish()

            def remove_shun(self, ip):
                agent.removals.append((device, ip))
                present = any(entry.ip == ip for entry in agent.entries[device])
                agent.entries[device] = [entry for entry in agent.entries[device] if entry.ip != ip]
                return present

            def abort(self):
                if not self.closed:
                    self.closed = True
                    with agent.lock: agent.active.remove(device)
                    agent.finished[device].set()

        return Session(self, device)


@pytest.fixture
def runtime(bulk, leases):
    # The sealed synthetic profile has four configured devices, not ten enabled
    # inventory entries silently omitted by a scheduler.
    with leases.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    agent = BlockingAgent()
    scheduler = ParallelSynchronizer(leases.store, agent, enabled=True, agent_concurrency=2,
                                     addition_device_ids=frozenset({1, 2}), bulk_dispatch_enabled=True)
    return scheduler, agent


async def wait(event):
    assert await asyncio.to_thread(event.wait, 5), 'Synthetic worker did not reach its checkpoint.'


def test_disabled_construction_and_sweep_never_initialize(tmp_path):
    store = Store(tmp_path / 'absent.db')
    scheduler = ParallelSynchronizer(store, BlockingAgent())
    assert asyncio.run(scheduler.sweep())['enabled'] is False
    assert not store.path.exists()


@pytest.mark.parametrize('changes', [
    {'enabled': 1}, {'bulk_dispatch_enabled': 1}, {'agent_concurrency': True},
    {'agent_concurrency': 0}, {'agent_concurrency': 11}, {'operation_timeout_seconds': 241},
    {'operation_timeout_seconds': 0}, {'poll_interval_seconds': True},
    {'interactive_min_interval_seconds': 0}, {'addition_device_ids': {1}},
    {'addition_device_ids': frozenset({True})},
])
def test_invalid_configuration_never_initializes(tmp_path, changes):
    store = Store(tmp_path / 'absent.db')
    with pytest.raises(ValueError): ParallelSynchronizer(store, BlockingAgent(), **changes)
    assert not store.path.exists()


def test_transport_deadline_cannot_outlive_configured_lease_bound(tmp_path):
    agent = BlockingAgent()
    agent.timeout_seconds = 126
    with pytest.raises(ValueError): ParallelSynchronizer(Store(tmp_path / 'absent'), agent)


def test_missing_profile_fails_before_agent_or_any_migration(bulk):
    scheduler = ParallelSynchronizer(bulk[0].store, BlockingAgent(), enabled=True)
    before = dump(bulk[0].store)
    with pytest.raises(BulkUnavailable): asyncio.run(scheduler.sweep())
    assert dump(bulk[0].store) == before and not scheduler.agent.seen


@pytest.mark.parametrize('mismatch', ['agent', 'inventory', 'addition', 'missing'])
def test_scope_or_capacity_mismatch_fails_without_rpc_or_claim(bulk, runtime, mismatch, monkeypatch):
    scheduler, agent = runtime
    if mismatch == 'agent': scheduler.agent_concurrency = 1
    elif mismatch == 'addition': scheduler.configuration['addition_device_ids'] = frozenset({5})
    elif mismatch == 'missing':
        original = scheduler.store.list_devices
        monkeypatch.setattr(scheduler.store, 'list_devices', lambda: [device for device in original() if device.id != 4])
    else:
        with scheduler.store._connection() as db:
            db.execute('UPDATE devices SET enabled=1 WHERE id=5')
    before = dump(scheduler.store)
    with pytest.raises(QueueConflict): asyncio.run(scheduler.sweep())
    assert dump(scheduler.store) == before and not agent.seen


def test_slow_device_does_not_block_healthy_devices_and_limit_is_real(runtime):
    scheduler, agent = runtime
    agent.block_open = {1}

    async def scenario():
        task = asyncio.create_task(scheduler.sweep())
        try:
            await wait(agent.entered[1])
            await wait(agent.finished[4])
            assert not task.done() and agent.active == {1}
            assert agent.maximum == 2
            with pytest.raises(QueueConflict): await scheduler.sweep()
        finally:
            agent.releases[1].set()
            result = await task
        assert not result['running']
        assert {row['state'] for row in result['devices'].values()} == {'success'}
        assert not agent.active
    asyncio.run(scenario())
    assert all(row['state'] == 'IDLE' for row in scheduler.leases.status()['devices'])


def test_actual_add_results_use_independent_scopes_without_global_cooldown(bulk, runtime):
    scheduler, agent = runtime
    root = grant(bulk, count=2)
    with scheduler.store._connection() as db:
        original = tuple(db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (root,)).fetchone())
    asyncio.run(scheduler.sweep())  # Fresh reads admit, frozen cutoff prevents same-round ADD.
    assert not agent.writes
    assert sum(item['admitted_this_cycle'] for item in scheduler.status()['bulk_discovery'].values()) == 4
    asyncio.run(scheduler.sweep())  # No clock advance/legacy minute-long write cooldown.
    assert sorted(device for device, _ in agent.writes) == [1, 1, 2, 2]
    with scheduler.store._connection() as db:
        assert tuple(db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (root,)).fetchone()) == original
        assert {row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')} == {'VERIFIED'}
        assert tuple(db.execute('SELECT owner,lease_until FROM operation_executor').fetchone()) == (None, None)
    assert all(row['epoch'] == 2 for row in scheduler.leases.status()['devices'])
    asyncio.run(scheduler.sweep())
    assert len(agent.writes) == 4  # Observation is neither new authority nor a repeated ADD.


def test_rpc_error_retains_fence_and_does_not_stall_other_devices(bulk, runtime):
    scheduler, agent = runtime
    agent.fail_open = {1}
    asyncio.run(scheduler.sweep())
    rows = scheduler.leases.status()['devices']
    assert rows[0]['state'] == 'LEASED' and all(row['state'] == 'IDLE' for row in rows[1:])
    assert scheduler.status()['devices']['1']['state'] == 'held'
    agent.fail_open.clear()
    before = len(agent.reads)
    bulk[1][0] += timedelta(seconds=156)
    asyncio.run(scheduler.sweep())
    assert scheduler.leases.status()['devices'][0]['state'] == 'ATTENTION'
    assert len(agent.reads) == before + 6  # Only healthy devices get initial/final reads.


def test_lost_add_reply_keeps_original_uncertainty_and_other_results(bulk, runtime):
    scheduler, agent = runtime
    grant(bulk)
    asyncio.run(scheduler.sweep())
    agent.fail_add = {1}
    asyncio.run(scheduler.sweep())
    with scheduler.store._connection() as db:
        outcomes = dict(db.execute('SELECT device_id,state FROM managed_bulk_attempts'))
    assert outcomes == {1: 'UNVERIFIED', 2: 'VERIFIED'}
    assert scheduler.status()['devices']['1']['state'] == 'held'
    agent.fail_add.clear()
    bulk[1][0] += timedelta(seconds=156)
    asyncio.run(scheduler.sweep())
    assert len(agent.writes) == 2
    assert scheduler.leases.status()['devices'][0]['state'] == 'ATTENTION'


def test_cancellation_during_open_waits_for_rpc_and_does_not_start_waiting_devices(runtime):
    scheduler, agent = runtime
    agent.block_open = {1, 2}

    async def scenario():
        task = asyncio.create_task(scheduler.sweep())
        try:
            await wait(agent.entered[1])
            await wait(agent.entered[2])
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()  # Repeated cancellation still cannot free the slots.
            await asyncio.sleep(0)
            assert not task.done() and agent.active == {1, 2}
            assert all(row['state'] == 'LEASED' for row in scheduler.leases.status()['devices'][:2])
        finally:
            agent.releases[1].set()
            agent.releases[2].set()
            with pytest.raises(asyncio.CancelledError): await task
        assert not agent.active and agent.seen == {1, 2}
        assert scheduler.status()['devices']['3']['state'] == 'not_started'
    asyncio.run(scenario())
    assert all(row['state'] == 'IDLE' for row in scheduler.leases.status()['devices'])


def test_cancellation_during_add_finishes_current_verification_only(bulk, runtime):
    scheduler, agent = runtime
    grant(bulk, devices=(1,), count=2)
    asyncio.run(scheduler.sweep())
    agent.block_add = {1}

    async def scenario():
        task = asyncio.create_task(scheduler.sweep())
        try:
            await wait(agent.entered[1])
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            with scheduler.store._connection() as db:
                assert [row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts ORDER BY requested_at,id')].count('RUNNING') == 1
        finally:
            agent.releases[1].set()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    assert len(agent.writes) == 1
    with scheduler.store._connection() as db:
        assert sorted(row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')) == ['QUEUED', 'VERIFIED']
    assert scheduler.leases.status()['devices'][0]['state'] == 'IDLE'


def test_read_only_status_is_detached_and_never_recovers(runtime):
    scheduler, _ = runtime
    asyncio.run(scheduler.sweep())
    before = dump(scheduler.store)
    status = scheduler.status()
    status['devices']['1']['state'] = 'invented'
    status['cycles']['1']['action'] = 'invented'
    assert scheduler.status()['devices']['1']['state'] == 'success'
    assert scheduler.status()['cycles']['1']['action'] == 'completed'
    assert dump(scheduler.store) == before


def test_protected_removal_reuses_real_policy_admission_and_fenced_result(runtime):
    scheduler, agent = runtime
    ip = IPv4Address('203.0.113.250')
    agent.entries[1] = [ObservedShun(ip, 'management')]
    ProtectedPolicy(scheduler.store).change('add', ip, 0, 'synthetic:policy', 'Synthetic policy', ('Viewer',))
    asyncio.run(scheduler.sweep())
    assert agent.removals == [(1, ip)] and not agent.entries[1]
    with scheduler.store._connection() as db:
        row = db.execute('SELECT action,state FROM operation_jobs WHERE device_id=1').fetchone()
        assert tuple(row) == ('REMOVE', 'VERIFIED')
        assert db.execute('SELECT actor_subject FROM operation_requests').fetchone()[0] == 'system:trusted-ip-policy'


def test_expiry_during_add_cannot_publish_late_success_or_replay(bulk, runtime):
    scheduler, agent = runtime
    grant(bulk, devices=(1,))
    asyncio.run(scheduler.sweep())
    agent.block_add = {1}

    async def scenario():
        task = asyncio.create_task(scheduler.sweep())
        try:
            await wait(agent.entered[1])
            bulk[1][0] += timedelta(seconds=156)
        finally:
            agent.releases[1].set()
            await task
    asyncio.run(scenario())
    with scheduler.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'RUNNING'
    asyncio.run(scheduler.sweep())
    with scheduler.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'UNVERIFIED'
    assert len(agent.writes) == 1 and scheduler.leases.status()['devices'][0]['state'] == 'ATTENTION'


def test_verified_add_survives_failed_final_snapshot(bulk, runtime):
    scheduler, agent = runtime
    grant(bulk, devices=(1,))
    asyncio.run(scheduler.sweep())
    agent.fail_final = {1}
    asyncio.run(scheduler.sweep())
    with scheduler.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'VERIFIED'
    assert scheduler.status()['devices']['1']['state'] == 'held' and len(agent.writes) == 1


def test_exact_deferral_requeues_without_unknown_or_extra_session_writes(bulk, runtime):
    scheduler, agent = runtime
    grant(bulk, devices=(1,), count=2)
    asyncio.run(scheduler.sweep())
    agent.defer = True
    asyncio.run(scheduler.sweep())
    assert len(agent.writes) == 1
    with scheduler.store._connection() as db:
        assert {row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')} == {'QUEUED'}
    assert scheduler.leases.status()['devices'][0]['state'] == 'IDLE'


def test_forced_internal_task_cancellation_never_spins_or_admits_replacements(runtime):
    scheduler, agent = runtime
    agent.block_open = {1}

    async def scenario():
        task = asyncio.create_task(scheduler.sweep())
        try:
            await wait(agent.entered[1])
            scheduler._round.cancel()  # Simulate forced loop/internal shutdown, not public stop.
            with pytest.raises(asyncio.CancelledError): await task
            assert scheduler.status()['broken']
            with pytest.raises(QueueConflict): await scheduler.sweep()
            assert 1 in agent.active
        finally:
            agent.releases[1].set()
    asyncio.run(scenario())
    assert scheduler.leases.status()['devices'][0]['state'] == 'LEASED'
