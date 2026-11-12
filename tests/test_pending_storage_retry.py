"""Deferred SQL contention recovery; never retry an SSH mutation or terminal END."""

import asyncio
import sqlite3
from datetime import timedelta

import pytest
from test_batch_session import states, visit
from test_deferred_worker import bulk as bulk_fixture
from test_deferred_worker import cancellation_controls as cancellation_fixture
from test_deferred_worker import dispatch as dispatch_fixture
from test_deferred_worker import execution as execution_fixture
from test_deferred_worker import journal as journal_fixture
from test_deferred_worker import leases as leases_fixture
from test_deferred_worker import ledger as ledger_fixture
from test_deferred_worker import runner
from test_deferred_worker import runtime as runtime_fixture
from test_deferred_worker import waits as waits_fixture
from test_result_storage import busy

from ftd_shun_manager import deferred_worker, result_storage
from ftd_shun_manager.deferred_worker import DeferredDeviceOperationQueue
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
runtime = runtime_fixture
waits = waits_fixture


def interrupt_write(monkeypatch, phase, fail):
    if phase == 'pending_checkpoint':
        original = Store._insert_event

        def event(db, name, *args, **kwargs):
            result = original(db, name, *args, **kwargs)
            if name == 'SHUN_PENDING_END_PREPARED': fail(db)
            return result

        monkeypatch.setattr(Store, '_insert_event', staticmethod(event))
    else:
        original = OperationQueue._event

        def event(self, db, name, *args, **kwargs):
            result = original(self, db, name, *args, **kwargs)
            if name == 'SHUN_OPERATION_AWAITING_CONFIRMATION': fail(db)
            return result

        monkeypatch.setattr(OperationQueue, '_event', event)


def assert_single_handoff(service, agent):
    assert states(service) == {'AWAITING_CONFIRMATION': 12}
    assert len(agent.writes) == len(set(agent.writes)) == 12
    assert sum(step[0] == 'open' for step in agent.trace) == 1
    assert sum(step[0] == 'end_pending' for step in agent.trace) == 1
    assert not agent.verifications
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_members').fetchone()[0] == 12
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_PENDING_END_PREPARED'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_AWAITING_CONFIRMATION'").fetchone()[0] == 12


@pytest.mark.parametrize('phase', ['pending_checkpoint', 'pending_handoff'])
def test_real_sqlite_writer_lock_retries_only_local_transaction(runtime, bulk, monkeypatch, capsys, phase):
    service, agent = runtime
    locks = []
    connect = sqlite3.connect

    def short_ordinary_connection(*args, **kwargs):
        kwargs.setdefault('timeout', 0.01)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', short_ordinary_connection)

    def locked(call, *args):
        if not locks:
            writer = connect(service.store.path, check_same_thread=False)
            writer.execute('BEGIN IMMEDIATE')
            locks.append(writer)
        return call(*args)

    if phase == 'pending_checkpoint':
        original = deferred_worker.prepare
        monkeypatch.setattr(deferred_worker, 'prepare', lambda *args: locked(original, *args))
    else:
        original = DeferredDeviceOperationQueue.handoff
        monkeypatch.setattr(DeferredDeviceOperationQueue, 'handoff', lambda *args: locked(original, *args))
    monkeypatch.setattr(result_storage, 'sleep', lambda _: locks[0].rollback())
    try:
        asyncio.run(visit(service))
    finally:
        for writer in locks: writer.close()
    assert_single_handoff(service, agent)
    assert f'"phase": "{phase}"' in capsys.readouterr().out
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(runner(service.store, agent)))
    assert states(service) == {'OBSERVED_PRESENT': 12}
    assert len(agent.writes) == 12


@pytest.mark.parametrize('phase', ['pending_checkpoint', 'pending_handoff'])
def test_busy_after_partial_audit_rolls_back_before_retry(runtime, monkeypatch, phase):
    service, agent = runtime
    calls = []

    def fail(db):
        calls.append(db.in_transaction)
        if len(calls) < 3: raise busy()

    interrupt_write(monkeypatch, phase, fail)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    asyncio.run(visit(service))
    assert_single_handoff(service, agent)
    assert len(calls) == (3 if phase == 'pending_checkpoint' else 14) and all(calls)


@pytest.mark.parametrize('phase', ['pending_checkpoint', 'pending_handoff'])
@pytest.mark.parametrize('fault', ['untyped_busy', 'locked', 'io', 'integrity', 'validation', 'exhausted'])
def test_failure_retains_original_pending_and_never_replays_remote_work(runtime, monkeypatch, phase, fault):
    service, agent = runtime
    calls = []

    def fail(db):
        calls.append(True)
        raise {'untyped_busy': sqlite3.OperationalError('database is locked'),
               'locked': busy(sqlite3.SQLITE_LOCKED), 'io': busy(sqlite3.SQLITE_IOERR),
               'integrity': sqlite3.IntegrityError('Synthetic invalid storage'),
               'validation': ValueError('Synthetic invalid evidence'), 'exhausted': busy()}[fault]

    interrupt_write(monkeypatch, phase, fail)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: None)
    asyncio.run(visit(service))
    assert len(calls) == (3 if fault == 'exhausted' else 1)
    assert states(service) == {'UNVERIFIED': 12}
    assert len(agent.writes) == len(set(agent.writes)) == 12
    assert sum(step[0] == 'open' for step in agent.trace) == 1
    assert sum(step[0] == 'end_pending' for step in agent.trace) == (phase == 'pending_handoff')
    assert service._workers[1].queue.handed_off_session is None
    assert service.leases.status()['devices'][0]['state'] != 'IDLE'
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_AWAITING_CONFIRMATION'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'").fetchone()[0] == 12


@pytest.mark.parametrize('phase', ['pending_checkpoint', 'pending_handoff'])
def test_retry_rechecks_lease_deadline_and_keeps_uncommitted_scope(runtime, bulk, monkeypatch, phase):
    service, agent = runtime
    calls = []

    def fail(db):
        calls.append(True)
        raise busy()

    interrupt_write(monkeypatch, phase, fail)
    monkeypatch.setattr(result_storage, 'sleep', lambda _: bulk[1].__setitem__(0, bulk[1][0] + timedelta(seconds=301)))
    asyncio.run(visit(service))
    assert calls == [True]  # Second transaction refuses before the audit callback.
    assert not {'AWAITING_CONFIRMATION', 'OBSERVED_PRESENT'} & states(service).keys()
    assert len(service._workers[1].queue.pending) == 12
    assert len(agent.writes) == len(set(agent.writes)) == 12
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] != 'IDLE'


@pytest.mark.parametrize('phase', ['pending_checkpoint', 'pending_handoff'])
def test_retry_revalidates_original_ack_scope(runtime, monkeypatch, phase):
    service, agent = runtime

    def fail(db): raise busy()

    def changed(_):
        with service.store._connection() as db:
            db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.sequence',999) "
                       "WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'")

    interrupt_write(monkeypatch, phase, fail)
    monkeypatch.setattr(result_storage, 'sleep', changed)
    asyncio.run(visit(service))
    assert not {'AWAITING_CONFIRMATION', 'OBSERVED_PRESENT'} & states(service).keys()
    assert service._workers[1].queue.handed_off_session is None
    assert len(agent.writes) == len(set(agent.writes)) == 12
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
