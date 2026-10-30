"""Automatic pre-BEGIN recovery on disposable state and local sockets, never FTD."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bulk_policy import dump
from test_continuous_dispatch import continuous as continuous_fixture
from test_continuous_dispatch import until
from test_device_leases import acquire, claim, discover, grant
from test_large_snapshots import serve
from test_parallel_synchronizer import bulk as bulk_fixture
from test_parallel_synchronizer import cancellation_controls as cancellation_fixture
from test_parallel_synchronizer import dispatch as dispatch_fixture
from test_parallel_synchronizer import journal as journal_fixture
from test_parallel_synchronizer import leases as leases_fixture
from test_parallel_synchronizer import waits as waits_fixture

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import (
    AgentCycleNotStarted,
    AgentCycleOpenFailed,
    AgentUnavailable,
    UnixAgentClient,
    UnixAgentCycle,
)
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.operation_queue import QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
continuous = continuous_fixture


@pytest.mark.parametrize('stage', ['socket', 'setup', 'connect'])
def test_only_local_pre_send_oserror_is_typed_and_closes_socket(monkeypatch, stage):
    calls = []

    class Connection:
        def settimeout(self, _timeout):
            calls.append('setup')
            if stage == 'setup': raise OSError('Synthetic resource failure')

        def connect(self, _path):
            calls.append('connect')
            raise OSError('Synthetic unavailable socket')

        def send(self, _packet):
            pytest.fail('No packet may be submitted after a failed connection.')

        def close(self): calls.append('closed')

    def socket(*_args):
        calls.append('socket')
        if stage == 'socket': raise OSError('Synthetic descriptor exhaustion')
        return Connection()

    monkeypatch.setattr(agent_client, 'socket', socket)
    with pytest.raises(AgentCycleNotStarted) as error:
        UnixAgentCycle('/synthetic.sock', 5, 1, settled_cycles=True)
    assert isinstance(error.value.__cause__, OSError)
    assert calls == {'socket': ['socket'], 'setup': ['socket', 'setup', 'closed'],
                     'connect': ['socket', 'setup', 'connect', 'closed']}[stage]


@pytest.mark.parametrize('fault', ['send_error', 'short_send', 'lost_reply', 'rejection', 'malformed'])
def test_any_attempted_begin_send_remains_unknown_not_retryable(monkeypatch, fault):
    calls = []

    class Connection:
        def settimeout(self, _timeout): pass
        def connect(self, _path): pass
        def close(self): calls.append('closed')

        def send(self, packet):
            calls.append('send')
            if fault == 'send_error': raise OSError('Synthetic send failure')
            return len(packet) - 1 if fault == 'short_send' else len(packet)

        def recvmsg(self, _maximum):
            if fault == 'lost_reply': raise TimeoutError('Synthetic lost reply')
            return (b'\x01' if fault == 'rejection' else b'not a receipt'), [], 0, None

    monkeypatch.setattr(agent_client, 'socket', lambda *_args: Connection())
    with pytest.raises(AgentUnavailable) as error:
        UnixAgentCycle('/synthetic.sock', 5, 1, settled_cycles=True)
    assert not isinstance(error.value, AgentCycleNotStarted)
    assert calls == ['send', 'closed']


@pytest.mark.parametrize('fields', [{'device_id': 0}, {'device_id': 65536}, {'version': 4}])
def test_invalid_begin_never_becomes_a_retryable_connection_error(monkeypatch, fields):
    def socket(*_args): pytest.fail('Invalid request must be rejected before connecting.')
    monkeypatch.setattr(agent_client, 'socket', socket)
    with pytest.raises(ValueError):
        UnixAgentCycle('/absent.sock', 5, **({'device_id': 1} | fields))


def test_real_missing_socket_is_typed_but_real_agent_rejection_is_not(tmp_path):
    with pytest.raises(AgentCycleNotStarted):
        UnixAgentClient(str(tmp_path / 'absent.sock'), 5, settled_cycles=True).open_cycle(1)

    def reject(connection):
        assert connection.recv(100) == bytes.fromhex('16010001')
        connection.send(b'\x01')
        assert connection.recv(100) == b''  # No retry/fallback on the connected peer.

    path, pool, worker = serve(tmp_path, reject)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentClient(path, 5, settled_cycles=True).open_cycle(1)
        assert not isinstance(error.value, AgentCycleNotStarted)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_unsubmitted_release_is_atomic_audited_and_does_not_touch_policy(bulk, leases):
    grant(bulk, (1,))
    token, _ = acquire(leases)
    with leases.store._connection() as db:
        policy = [tuple(row) for row in db.execute('SELECT * FROM managed_shun_targets')]
    leases.release_unsubmitted(token)
    with leases.store._connection() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM managed_shun_targets')] == policy
        events = db.execute("SELECT event_type,details_json FROM shun_events WHERE event_type LIKE 'DEVICE_LEASE_%' ORDER BY rowid").fetchall()
        assert [row[0] for row in events] == ['DEVICE_LEASE_CLAIMED', 'DEVICE_LEASE_NOT_SUBMITTED', 'DEVICE_LEASE_RELEASED']
        assert all(json.loads(row[1]) == {'owner': token.owner, 'epoch': token.epoch} for row in events)
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
    assert leases.status()['devices'][0]['state'] == 'IDLE'
    next_token, _ = acquire(leases)
    assert next_token.epoch == token.epoch + 1


@pytest.mark.parametrize('fault', ['wrong_owner', 'wrong_epoch', 'expired', 'attention'])
def test_old_or_lost_fence_cannot_use_pre_submission_recovery(bulk, leases, fault):
    token, _ = acquire(leases, seconds=5)
    if fault == 'wrong_owner': token = replace(token, owner=str(uuid4()))
    if fault == 'wrong_epoch': token = replace(token, epoch=token.epoch + 1)
    if fault in {'expired', 'attention'}: bulk[1][0] += timedelta(seconds=6)
    if fault == 'attention': assert leases.claim(1, str(uuid4()), 5, enabled=True) is None
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.release_unsubmitted(token)
    assert dump(leases.store) == before


@pytest.mark.parametrize('outcome', ['RUNNING', 'UNVERIFIED', 'VERIFIED'])
def test_claimed_epoch_cannot_be_relabelled_unsubmitted_even_after_success(bulk, leases, outcome):
    grant(bulk, (1,))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    assert job
    if outcome != 'RUNNING':
        queue.finish_addition(job['id'], token.owner,
                              AdditionResult(True, 'management') if outcome == 'VERIFIED' else outcome)
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.release_unsubmitted(token)
    assert dump(leases.store) == before


def test_audit_failure_rolls_back_release_and_both_events(leases, monkeypatch):
    token, _ = acquire(leases)
    original = leases._event
    def event(db, kind, token, timestamp):
        if kind == 'RELEASED': raise ValueError('Synthetic audit failure')
        original(db, kind, token, timestamp)
    monkeypatch.setattr(leases, '_event', event)
    before = dump(leases.store)
    with pytest.raises(ValueError): leases.release_unsubmitted(token)
    assert dump(leases.store) == before


def test_continuous_retries_connect_with_capped_backoff_and_retains_demand(continuous, tmp_path, monkeypatch):
    service, agent, clock = continuous
    original, failures, calls = agent.open_cycle, [True], []
    def open_cycle(device):
        if device == 1:
            calls.append(clock[0])
            if failures[0]:
                return UnixAgentClient(str(tmp_path / 'absent.sock'), 5, settled_cycles=True).open_cycle(device)
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            for index, delay in enumerate((5, 10, 20, 40, 60, 60), start=1):
                await until(lambda index=index: len(calls) == index and 1 not in service._active)
                status = service.refresh_status()
                row = status['devices']['1']
                assert row['state'] == 'error' and row['stale']
                assert row['retry_in_seconds'] == delay
                assert row['last_successful_refresh'] is None
                assert row['connection_retry_attempts'] == index
                assert service.runner._results['1']['state'] == 'retrying'
                assert service.runner.leases.status()['devices'][0]['state'] == 'IDLE'
                service.request_refresh(frozenset({1}))
                await until(lambda: {2, 3, 4} <= agent.seen and not service._active)
                clock[0] += delay - 1
                service.signal_work()
                await asyncio.sleep(0.03)
                assert len(calls) == index  # Clicks/wakes cannot bypass retry floor.
                assert service.status()['devices']['1']['refresh_pending']
                clock[0] += 1
                if index == 6: failures[0] = False
                service.signal_work()
            await until(lambda: len(calls) == 7 and not service._active)
            row = service.refresh_status()['devices']['1']
            assert row['state'] == 'ready' and row['last_successful_refresh']
            assert not row['refresh_pending'] and row['connection_retry_attempts'] == 0
            assert not row['last_error'] and not agent.writes
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_failed_reconnect_preserves_previous_freshness_and_policy_scan(continuous, tmp_path, monkeypatch):
    service, agent, clock = continuous
    original, failed = agent.open_cycle, [False]
    def open_cycle(device):
        if device == 1 and failed[0]:
            return UnixAgentClient(str(tmp_path / 'absent.sock'), 5, settled_cycles=True).open_cycle(device)
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            await until(lambda: len(agent.seen) == 4 and not service._active)
            previous = service.refresh_status()['devices']['1']['last_successful_refresh']
            revision = service.runner._workers[1]._data_revision
            failed[0], clock[0] = True, clock[0] + 61
            service.request_policy_scan(frozenset({1}))
            service.request_refresh(frozenset({1}))
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'retrying' and not service._active)
            row = service.refresh_status()['devices']['1']
            assert row['last_successful_refresh'] == previous
            assert row['refresh_pending'] and row['policy_scan_pending'] and row['stale']
            assert service.runner._workers[1]._data_revision == revision
            failed[0], clock[0] = False, clock[0] + 5
            service.signal_work()
            await until(lambda: service.runner._results['1']['state'] == 'success' and not service._active)
            row = service.refresh_status()['devices']['1']
            assert row['state'] == 'ready' and not row['refresh_pending'] and not row['policy_scan_pending']
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['add', 'final'])
@pytest.mark.parametrize('error_type', [AgentCycleNotStarted, AgentCycleOpenFailed])
def test_late_typed_error_cannot_release_submitted_session(bulk, continuous, monkeypatch, phase, error_type):
    service, agent, _clock = continuous
    grant(bulk, (1,))
    original = agent.open_cycle
    def open_cycle(device):
        cycle = original(device)
        if device == 1:
            def fail(*_args): raise error_type('Misclassified late error')
            if phase == 'add': cycle.add_shun = fail
            else: cycle.finish = fail
        return cycle
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'held' and not service._active)
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
            assert 1 not in service._connection_failures
            with service.runner.store._connection() as db:
                assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type IN ('DEVICE_LEASE_NOT_SUBMITTED','DEVICE_LEASE_OPEN_FAILED')").fetchone()[0] == 0
                if phase == 'add':
                    assert db.execute('SELECT state FROM operation_jobs WHERE device_id=1').fetchone()[0] == 'UNVERIFIED'
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_managed_authority_waits_for_new_complete_read_then_progresses(bulk, continuous, tmp_path, monkeypatch):
    service, agent, clock = continuous
    grant(bulk, (1,))
    original, failed = agent.open_cycle, [True]
    def open_cycle(device):
        if device == 1 and failed[0]:
            return UnixAgentClient(str(tmp_path / 'absent.sock'), 5, settled_cycles=True).open_cycle(device)
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'retrying' and not service._active)
            assert not agent.writes
            with service.runner.store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
                assert db.execute('SELECT enabled FROM managed_shun_targets').fetchone()[0] == 1
            failed[0], clock[0] = False, clock[0] + 5
            service.signal_work()
            await until(lambda: len(agent.writes) == 1 and not service._active)
            assert agent.trace[0][0] == 'open'  # A new initial read, never replayed ADD.
            with service.runner.store._connection() as db:
                assert db.execute('SELECT action,state FROM operation_jobs').fetchone()[:] == ('ADD', 'VERIFIED')
                assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'VERIFIED'
        finally:
            await service.stop()
    asyncio.run(scenario())
