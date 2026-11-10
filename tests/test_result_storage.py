"""Local rollback proof, real competing writer and grouped RPC non-repetition."""

import asyncio
import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_batch_queue import acknowledge, result
from test_batch_queue import group as group_fixture
from test_batch_session import bulk as bulk_fixture
from test_batch_session import cancellation_controls as cancellation_fixture
from test_batch_session import dispatch as dispatch_fixture
from test_batch_session import journal as journal_fixture
from test_batch_session import leases as leases_fixture
from test_batch_session import runtime as runtime_fixture
from test_batch_session import states, visit
from test_batch_session import waits as waits_fixture
from test_device_leases import claim

from ftd_shun_manager import result_storage
from ftd_shun_manager.agent_protocol import PendingAddition
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict

group = group_fixture
bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
runtime = runtime_fixture
waits = waits_fixture


def busy(code=sqlite3.SQLITE_BUSY):
    error = sqlite3.OperationalError('Synthetic numeric SQLite error')
    error.sqlite_errorcode = code
    return error


@pytest.fixture
def storage(tmp_path):
    path = tmp_path / 'results.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE result (value INTEGER)')
    return SimpleNamespace(path=path)


def test_real_competing_writer_retries_failed_begin_without_running_callback(storage, monkeypatch):
    writer = sqlite3.connect(storage.path)
    writer.execute('BEGIN IMMEDIATE')
    calls, delays = [], []
    def release(delay):
        delays.append(delay)
        writer.rollback()
    monkeypatch.setattr(result_storage, 'sleep', release)
    try:
        def write(db):
            calls.append(True)
            db.execute('INSERT INTO result VALUES (1)')
            return 'persisted'
        assert result_storage.persist_result(storage, write, phase='acknowledgement') == 'persisted'
    finally:
        writer.close()
    assert calls == [True] and delays == [0.05]
    with sqlite3.connect(storage.path) as db:
        assert db.execute('SELECT * FROM result').fetchall() == [(1,)]


@pytest.mark.parametrize('code', [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_SNAPSHOT])
def test_partial_local_write_is_rolled_back_before_same_result_retry(storage, monkeypatch, code):
    calls = []
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    def write(db):
        calls.append(True)
        assert not db.execute('SELECT * FROM result').fetchall()
        db.execute('INSERT INTO result VALUES (1)')
        if len(calls) == 1: raise busy(code)
    result_storage.persist_result(storage, write, phase='addition_result')
    assert len(calls) == 2
    with sqlite3.connect(storage.path) as db:
        assert db.execute('SELECT * FROM result').fetchall() == [(1,)]


@pytest.mark.parametrize('fault', ['generic', 'locked', 'io', 'integrity', 'validation', 'cancel', 'rollback'])
def test_non_busy_or_failed_rollback_never_retries(storage, monkeypatch, fault):
    calls = []
    def unexpected(_): raise AssertionError('Must not retry')
    monkeypatch.setattr(result_storage, 'sleep', unexpected)
    def write(db):
        calls.append(True)
        db.execute('INSERT INTO result VALUES (1)')
        if fault == 'rollback':
            db.close()
            raise busy()
        raise {'generic': sqlite3.OperationalError('database is locked'), 'locked': busy(sqlite3.SQLITE_LOCKED),
               'io': busy(sqlite3.SQLITE_IOERR), 'integrity': sqlite3.IntegrityError('Synthetic'),
               'validation': ValueError('Synthetic'), 'cancel': asyncio.CancelledError()}[fault]
    expected = {'generic': sqlite3.OperationalError, 'locked': sqlite3.OperationalError,
                'io': sqlite3.OperationalError, 'integrity': sqlite3.IntegrityError,
                'validation': ValueError, 'cancel': asyncio.CancelledError, 'rollback': sqlite3.ProgrammingError}[fault]
    with pytest.raises(expected): result_storage.persist_result(storage, write, phase='addition_result')
    assert len(calls) == 1
    with sqlite3.connect(storage.path) as db:
        assert not db.execute('SELECT * FROM result').fetchall()


@pytest.mark.parametrize('after_commit', [False, True])
def test_commit_failure_retries_only_when_original_transaction_is_still_rollbackable(storage, monkeypatch, after_commit):
    connect = result_storage._connect
    connections, calls = [], []
    class CommitFault(sqlite3.Connection):
        def commit(self):
            if after_commit: super().commit()
            raise busy()
    def open_connection(path):
        connections.append(True)
        if len(connections) > 1: return connect(path)
        return sqlite3.connect(path, factory=CommitFault)
    monkeypatch.setattr(result_storage, '_connect', open_connection)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    def write(db):
        calls.append(True)
        db.execute('INSERT INTO result VALUES (1)')
    if after_commit:
        with pytest.raises(sqlite3.OperationalError): result_storage.persist_result(storage, write, phase='addition_result')
        assert len(calls) == len(connections) == 1
    else:
        result_storage.persist_result(storage, write, phase='addition_result')
        assert len(calls) == len(connections) == 2
    with sqlite3.connect(storage.path) as db:
        assert db.execute('SELECT * FROM result').fetchall() == [(1,)]


def test_failed_explicit_rollback_never_retries(storage, monkeypatch):
    calls, rollbacks = [], []
    class RollbackFault(sqlite3.Connection):
        def rollback(self):
            rollbacks.append(True)
            raise sqlite3.OperationalError('Synthetic rollback failure')
    monkeypatch.setattr(result_storage, '_connect', lambda path: sqlite3.connect(path, factory=RollbackFault))
    monkeypatch.setattr(result_storage, 'sleep', lambda _: pytest.fail('Must not retry a failed rollback'))
    def write(db):
        calls.append(True)
        db.execute('INSERT INTO result VALUES (1)')
        raise busy()
    with pytest.raises(sqlite3.OperationalError, match='rollback failure'):
        result_storage.persist_result(storage, write, phase='addition_result')
    assert calls == rollbacks == [True]
    with sqlite3.connect(storage.path) as db:
        assert not db.execute('SELECT * FROM result').fetchall()


@pytest.mark.parametrize('time_exhausted', [False, True])
def test_retry_count_and_start_deadline_are_bounded(storage, monkeypatch, time_exhausted):
    ticks, calls, delays = [0], [], []
    monkeypatch.setattr(result_storage, 'monotonic', lambda: ticks[0])
    monkeypatch.setattr(result_storage, 'sleep', delays.append)
    def write(db):
        calls.append(True)
        db.execute('INSERT INTO result VALUES (1)')
        if time_exhausted: ticks[0] = result_storage.RETRY_START_SECONDS
        raise busy()
    with pytest.raises(sqlite3.OperationalError): result_storage.persist_result(storage, write, phase='addition_result')
    assert len(calls) == (1 if time_exhausted else 3)
    assert delays == ([] if time_exhausted else [0.05, 0.15])
    with sqlite3.connect(storage.path) as db:
        assert not db.execute('SELECT * FROM result').fetchall()


@pytest.mark.parametrize('phase', ['ack', 'result'])
def test_group_audit_retries_locally_without_duplicate_events_or_memory_members(group, monkeypatch, phase):
    from ipaddress import IPv4Address

    queue, _ = group
    job = claim(queue)
    target_event = 'SHUN_ADDITION_ACKNOWLEDGED' if phase == 'ack' else 'SHUN_OPERATION_VERIFIED'
    original = OperationQueue._event
    faults = []
    def event(self, db, name, *args, **kwargs):
        original(self, db, name, *args, **kwargs)
        if name == target_event and not faults:
            faults.append(True)
            raise busy()
    monkeypatch.setattr(OperationQueue, '_event', event)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    queue.acknowledge_addition(job['id'], queue.token.owner, PendingAddition(IPv4Address(job['ip']), 1))
    assert queue.pending == [job['id']]
    queue.finish_verified_group(queue.token.owner, result([job]), 2)
    assert queue.pending == [] and queue.settled == 1 and faults == [True]
    with queue.store._connection() as db:
        for name in ('SHUN_ADDITION_ACKNOWLEDGED', 'SHUN_OPERATION_VERIFIED'):
            assert db.execute('SELECT COUNT(*) FROM shun_events WHERE event_type=?', (name,)).fetchone()[0] == 1


def test_delayed_scheduler_wakeup_cannot_start_an_expired_retry(storage, monkeypatch):
    ticks, calls = [0], []
    monkeypatch.setattr(result_storage, 'monotonic', lambda: ticks[0])
    monkeypatch.setattr(result_storage, 'sleep', lambda _: ticks.__setitem__(0, result_storage.RETRY_START_SECONDS))
    def write(db):
        calls.append(True)
        db.execute('INSERT INTO result VALUES (1)')
        raise busy()
    with pytest.raises(sqlite3.OperationalError): result_storage.persist_result(storage, write, phase='addition_result')
    assert calls == [True]


def test_retry_rechecks_current_lease_instead_of_reusing_eligibility(group, bulk, monkeypatch):
    queue, _ = group
    job = acknowledge(queue, 1)
    original = OperationQueue._event
    def fail(self, db, event, *args, **kwargs):
        original(self, db, event, *args, **kwargs)
        if event == 'SHUN_OPERATION_VERIFIED': raise busy()
    monkeypatch.setattr(OperationQueue, '_event', fail)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: bulk[1].__setitem__(0, bulk[1][0] + timedelta(seconds=301)))
    with pytest.raises(QueueConflict): queue.finish_verified_group(queue.token.owner, result([job]), 2)
    assert queue.pending == [job['id']] and queue.settled == 0
    with queue.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert not db.execute("SELECT 1 FROM shun_events WHERE event_type='SHUN_OPERATION_VERIFIED'").fetchone()


@pytest.mark.parametrize('phase', ['acknowledgement', 'addition_result'])
def test_worker_real_lock_uses_one_session_and_never_resends_stage(runtime, monkeypatch, phase):
    from ftd_shun_manager import batch_queue

    runner, agent = runtime
    locks = []
    persist = batch_queue.persist_result
    def lock(store, write, *, phase: str):
        if phase == locked_phase and not locks:
            writer = sqlite3.connect(runner.store.path, check_same_thread=False)
            writer.execute('BEGIN IMMEDIATE')
            locks.append(writer)
        return persist(store, write, phase=phase)
    locked_phase = phase
    monkeypatch.setattr(batch_queue, 'persist_result', lock)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: locks[0].rollback())
    try:
        asyncio.run(visit(runner))
    finally:
        for writer in locks: writer.close()
    assert states(runner) == {'VERIFIED': 12}
    assert len(agent.writes) == len(set(agent.writes)) == 12
    assert sum(step[0] == 'open' for step in agent.trace) == 1
    assert len(agent.verifications) == 1 and not agent.lookup


def test_exhausted_later_result_keeps_earlier_verified_and_never_repeats_rpcs(runtime, monkeypatch):
    runner, agent = runtime
    verified, blocked = [], []
    original = OperationQueue._event
    def event(self, db, name, request, job, *args, **kwargs):
        original(self, db, name, request, job, *args, **kwargs)
        if name == 'SHUN_OPERATION_VERIFIED':
            if not verified: verified.append(job['id'])
            elif job['id'] != verified[0]:
                blocked.append(job['id'])
                raise busy()
    monkeypatch.setattr(OperationQueue, '_event', event)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    asyncio.run(visit(runner))
    assert states(runner) == {'VERIFIED': 1, 'UNVERIFIED': 11}
    assert len(blocked) == 3 and len(set(blocked)) == 1
    assert len(agent.writes) == len(set(agent.writes)) == 12
    assert sum(step[0] == 'open' for step in agent.trace) == 1
    assert len(agent.verifications) == 1
    with runner.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] != 'IDLE'
