"""Actual fenced worker with synthetic staged transport; no Cisco access."""

import asyncio
from ipaddress import IPv4Address

import pytest
from test_batch_queue import bulk as bulk_fixture
from test_batch_queue import cancellation_controls as cancellation_fixture
from test_batch_queue import dispatch as dispatch_fixture
from test_batch_queue import journal as journal_fixture
from test_batch_queue import leases as leases_fixture
from test_batch_queue import waits as waits_fixture
from test_continuous_dispatch import TracedAgent, admitted_removal
from test_device_leases import acquire, discover, grant

from ftd_shun_manager.agent_client import AgentUnavailable
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    ObservedShun,
    PendingAddition,
    VerifiedAdditionBatch,
)
from ftd_shun_manager.parallel_synchronizer import ParallelSynchronizer

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


class Agent(TracedAgent):
    tracked_cycles = batch_additions = True

    def __init__(self):
        super().__init__()
        self.on_stage = None
        self.fail_stage = self.defer_stage = None
        self.fail_group = False
        self.fail_settlement = None
        self.verifications = []
        self.lookup = []

    def open_tracked_cycle(self, device, owner):
        return self.open_cycle(device)

    def read_only_session_completed(self, device, owner):
        self.lookup.append((device, owner))
        return False

    def open_cycle(self, device):
        session = super().open_cycle(device)
        session.version, session.sequence = 5, 1
        pending = []
        count = 0

        def stage(ip):
            nonlocal count
            count += 1
            seq = session.sequence
            session.sequence += 1
            if count == self.defer_stage:
                self.trace.append(('defer', device, ip))
                return None
            if any(entry.ip == ip for entry in self.entries[device]):
                self.trace.append(('noop', device, ip))
                return AdditionResult(False)
            self.entries[device].append(ObservedShun(ip, 'management'))
            self.writes.append((device, ip))
            self.trace.append(('stage', device, ip))
            if self.on_stage: self.on_stage(device, ip, count)
            if count == self.fail_stage: raise AgentUnavailable('Synthetic lost stage response after write')
            pending.append(ip)
            return PendingAddition(ip, seq)

        def verify():
            assert pending
            if self.fail_group: raise AgentUnavailable('Synthetic lost complete group read')
            self.trace.append(('verify', device, tuple(pending)))
            self.verifications.append(tuple(pending))
            result = VerifiedAdditionBatch(tuple((ip, AdditionResult(True, 'management')) for ip in pending),
                                           tuple(self.entries[device]))
            pending.clear()
            session.sequence += 1
            return result

        def guarded(original):
            def call(*args):
                assert not pending, 'A read/remove/END cannot overtake pending verification'
                session.sequence += 1
                return original(*args)
            return call

        session.stage_addition, session.verify_additions = stage, verify
        session.snapshot = guarded(session.snapshot)
        session.remove_shun = guarded(session.remove_shun)
        session.finish = guarded(session.finish)
        def finish_additions():
            result = verify()
            if self.fail_settlement == 'missing':
                raise AgentUnavailable('Synthetic lost final settlement after complete group read')
            if self.fail_settlement == 'false':
                return result
            session.finish()
            return result
        session.finish_additions = finish_additions
        return session


@pytest.fixture
def runtime(bulk, leases):
    grant(bulk, (1,), count=12)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 12
    queue.finish_cycle(token.owner, 0)
    agent = Agent()
    runner = ParallelSynchronizer(leases.store, agent, enabled=True, agent_concurrency=2,
                                  addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True,
                                  settled_cycles_required=True, batch_additions_enabled=True)
    runner._priority_removals = True
    return runner, agent


async def visit(runner):
    await runner._visit(next(device for device in runner.store.list_devices() if device.id == 1))


def states(runner):
    with runner.store._connection() as db:
        return dict(db.execute('SELECT state,COUNT(*) FROM operation_jobs GROUP BY state'))


def test_twelve_writes_share_one_terminal_group_read_and_publish_after_provenance(runtime):
    runner, agent = runtime
    asyncio.run(visit(runner))
    assert [len(group) for group in agent.verifications] == [12]
    assert states(runner) == {'VERIFIED': 12}
    assert runner._workers[1]._device_cycle['completed'] == 12
    assert runner._results['1']['state'] == 'success'
    with runner.store._connection() as db:
        assert db.execute("SELECT state FROM managed_bulk_device_executors WHERE device_id=1").fetchone()[0] == 'IDLE'
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='VERIFIED' AND occurrence_id IS NOT NULL").fetchone()[0] == 12
    assert sum(step[0] == 'open' for step in agent.trace) == 1
    assert not agent.lookup


@pytest.mark.parametrize('interrupt', ['stop', 'refresh', 'remove', 'pause', 'protect', 'cancel'])
def test_boundary_flush_precedes_stop_priority_refresh_or_unblock(runtime, bulk, cancellation_controls, interrupt):
    runner, agent = runtime

    def event(device, ip, count):
        if count != 2: return
        worker = runner._workers[1]
        if interrupt == 'stop': worker._stop_mutations = True
        elif interrupt == 'refresh': worker._priority_pending = True
        elif interrupt == 'remove': admitted_removal(bulk, IPv4Address('203.0.113.17'))
        elif interrupt == 'protect':
            from ftd_shun_manager.protected_policy import ProtectedPolicy

            ProtectedPolicy(runner.store).change('add', IPv4Address('198.51.100.1'), 0, 'synthetic:policy',
                                                 'Synthetic policy editor', ('Viewer',), managed_revision=1)
        elif interrupt == 'cancel':
            from test_bulk_cancellations import cancel

            with runner.store._connection() as db:
                key = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts LIMIT 1').fetchone()[0]
            cancel(cancellation_controls, key)
        else:
            with runner.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')

    agent.on_stage = event
    asyncio.run(visit(runner))
    assert len(agent.verifications[0]) == 2
    first_verify = next(i for i, step in enumerate(agent.trace) if step[0] == 'verify')
    assert sum(step[0] == 'stage' for step in agent.trace[:first_verify]) == 2
    if interrupt in {'stop', 'pause'}:
        assert states(runner) == {'QUEUED': 10, 'VERIFIED': 2}
    elif interrupt == 'cancel':
        assert states(runner) == {'CANCELLED': 10, 'VERIFIED': 2}
    elif interrupt == 'protect':
        assert agent.trace[first_verify + 1][0] == 'remove'
        assert all(entry.ip != IPv4Address('198.51.100.1') for entry in agent.entries[1])
    elif interrupt == 'remove':
        assert agent.trace[first_verify + 1][0] == 'remove'
        assert states(runner) == {'NOOP': 1, 'VERIFIED': 12}
    else:
        assert agent.trace[first_verify + 1][0] == 'stage'
        assert states(runner) == {'VERIFIED': 12}
    assert runner._workers[1].session_settled


def test_exact_prewrite_deferral_flushes_older_adds_without_replaying_deferred_job(runtime):
    runner, agent = runtime
    agent.defer_stage = 3
    asyncio.run(visit(runner))
    assert [len(group) for group in agent.verifications] == [2]
    assert states(runner) == {'QUEUED': 10, 'VERIFIED': 2}
    assert runner._workers[1].session_settled and runner._workers[1]._device_cycle['budget_deferred']
    assert len(agent.writes) == 2


def test_pending_stage_updates_status_without_forcing_data_reload_until_verification(runtime):
    runner, agent = runtime
    data_revisions = []

    def observe(device, ip, count):
        worker = runner._workers[device]
        data_revisions.append(worker._data_revision)
        if count == 2: worker._stop_mutations = True

    agent.on_stage = observe
    asyncio.run(visit(runner))
    assert len(data_revisions) == 2 and data_revisions[0] == data_revisions[1]
    assert runner._workers[1]._data_revision > data_revisions[-1]


@pytest.mark.parametrize('failure', ['stage', 'group', 'local', 'settlement', 'unsettled'])
def test_failure_retains_every_unconfirmed_member_and_earlier_verified_results(runtime, monkeypatch, failure):
    from ftd_shun_manager.device_leases import DeviceOperationQueue

    runner, agent = runtime
    if failure == 'stage': agent.fail_stage = 3
    elif failure == 'group': agent.fail_group = True
    elif failure in ('settlement', 'unsettled'):
        agent.fail_settlement = 'missing' if failure == 'settlement' else 'false'
    else:
        original = DeviceOperationQueue.finish_addition
        seen = [0]

        def fail_once(self, job, owner, result, **kwargs):
            if isinstance(result, AdditionResult):
                seen[0] += 1
                if seen[0] == 2: raise ValueError('Synthetic second settlement failure')
            return original(self, job, owner, result, **kwargs)
        monkeypatch.setattr(DeviceOperationQueue, 'finish_addition', fail_once)
    asyncio.run(visit(runner))
    counts = states(runner)
    expected = {'stage': {'QUEUED': 9, 'UNVERIFIED': 3},
                'group': {'UNVERIFIED': 12},
                'local': {'UNVERIFIED': 11, 'VERIFIED': 1},
                'settlement': {'UNVERIFIED': 12}, 'unsettled': {'UNVERIFIED': 12}}
    assert counts == expected[failure]
    assert runner._workers[1].rpc_failed
    assert runner._workers[1].session_settled is (failure == 'local')
    with runner.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] != 'IDLE'
    assert len(agent.writes) == (3 if failure == 'stage' else 12)
    assert not agent.active
