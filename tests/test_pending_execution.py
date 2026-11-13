"""Fresh disposable deferred queue profile; no configured worker or lab write."""

import sqlite3
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address

import pytest
from test_pending_confirmation import bulk as bulk_fixture
from test_pending_confirmation import cancellation_controls as cancellation_fixture
from test_pending_confirmation import dispatch as dispatch_fixture
from test_pending_confirmation import journal as journal_fixture
from test_pending_confirmation import leases as leases_fixture
from test_pending_confirmation import ledger as ledger_fixture
from test_pending_confirmation import read, stage
from test_pending_confirmation import waits as waits_fixture

from ftd_shun_manager import bulk_policy, pending_execution
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.device_leases import DeviceLeases
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.pending_execution import PendingExecution

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture


def test_deferred_profile_retains_read_claim_even_without_mutations(execution, leases):
    from uuid import uuid4

    token = leases.claim(1, str(uuid4()), 135, enabled=True)
    leases.release(token, quiet_read=True)
    with leases.store._connection() as db:
        assert [row[0] for row in db.execute('SELECT event_type FROM shun_events ORDER BY rowid DESC LIMIT 2')] == ['DEVICE_LEASE_RELEASED', 'DEVICE_LEASE_CLAIMED']


@pytest.fixture
def execution(ledger, leases):
    service = PendingExecution(ledger.store, leases.queue)
    with service.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize_empty()
    with service.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def awaiting(execution, staged):
    queue, jobs, receipt = staged
    return execution.await_confirmation(queue.token, receipt, tuple(job['id'] for job in jobs), enabled=True)


def test_settled_queue_can_release_then_confirm_without_inventing_creation(bulk, leases, execution):
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    with execution.store._connection() as db:
        assert [row[0] for row in db.execute('SELECT state FROM operation_jobs ORDER BY seq')] == ['AWAITING_CONFIRMATION'] * 2
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts WHERE completed_at IS NOT NULL').fetchone()[0] == 0
    assert leases.status()['devices'][0]['state'] == 'IDLE'
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    result = execution.confirm(token, session, read(bulk, present=('198.51.100.1',)), enabled=True)
    assert [state for _, state in result] == ['OBSERVED_PRESENT', 'CONFIRMED_ABSENT']
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts WHERE occurrence_id IS NOT NULL').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='VERIFIED'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM operation_requests WHERE state=\'ACTIVE\'').fetchone()[0] == 0
        assert db.execute('SELECT ip FROM operation_jobs ORDER BY seq LIMIT 1').fetchone()[0] == IPv4Address('198.51.100.1').packed
        events = db.execute("SELECT * FROM shun_events WHERE event_type IN ('SHUN_OPERATION_OBSERVED_PRESENT', 'MANAGED_BULK_ATTEMPT_OBSERVED_PRESENT')").fetchall()
        assert len(events) == 2 and all(row['actor_subject'] == 'system:managed-shun-policy' for row in events)
        assert all(row['interface'] is None for row in events)
    leases.release(token)


def test_init_is_explicit_atomic_and_idempotent(ledger, leases, monkeypatch):
    from test_bulk_policy import dump

    service = PendingExecution(ledger.store, leases.queue)
    before = dump(service.store)
    with pytest.raises(QueueConflict, match='Pause'):
        service.initialize_empty()
    assert dump(service.store) == before
    with service.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    paused = dump(service.store)
    original = pending_execution.execute_schema

    def fail(db, ddl):
        original(db, ddl)
        raise ValueError('Synthetic profile failure')

    with monkeypatch.context() as context:
        context.setattr(pending_execution, 'execute_schema', fail)
        with pytest.raises(ValueError, match='Synthetic'):
            service.initialize_empty()
    assert dump(service.store) == paused
    service.initialize_empty()
    after = dump(service.store)
    service.initialize_empty()
    assert dump(service.store) == after


def test_existing_job_history_is_not_converted_or_deleted(bulk, leases, ledger):
    from test_bulk_policy import dump

    staged = stage(bulk, leases)
    staged[0].fail_pending_group(staged[0].token.owner, 'Synthetic retained unknown')
    leases.release(staged[0].token)
    with ledger.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(ledger.store)
    with pytest.raises((ManagedConflict, QueueConflict, BulkUnavailable), match='uncertain|fresh empty'):
        PendingExecution(ledger.store, leases.queue).initialize_empty()
    assert dump(ledger.store) == before


def test_even_verified_history_is_not_rebuilt_by_fresh_initializer(bulk, leases, ledger):
    from test_batch_queue import result
    from test_bulk_policy import dump

    queue, jobs, _ = stage(bulk, leases)
    queue.finish_verified_group(queue.token.owner, result(jobs), 4)
    leases.release(queue.token)
    with ledger.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(ledger.store)
    with pytest.raises(QueueConflict, match='fresh empty'):
        PendingExecution(ledger.store, leases.queue).initialize_empty()
    assert dump(ledger.store) == before


def test_current_coordinator_refuses_new_profile_before_any_agent_call(execution):
    from ftd_shun_manager.parallel_synchronizer import ParallelSynchronizer

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError('No agent request is allowed')

    # Literal capability values only; no socket/transport method is called.
    runner = ParallelSynchronizer(execution.store, object(), enabled=True, operation_timeout_seconds=125)
    runner.agent = NoCalls()
    with pytest.raises(QueueConflict, match='explicit deferred worker'):
        runner._configured_devices()


@pytest.mark.parametrize('phase', ['audit', 'release', 'expiry'])
def test_failed_handoff_rolls_back_scope_states_audit_and_lease(bulk, leases, execution, phase, monkeypatch):
    from test_bulk_policy import dump

    staged = stage(bulk, leases)
    before = dump(execution.store)
    if phase == 'audit':
        def fail(*args, **kwargs):
            raise ValueError('Synthetic audit failure')
        monkeypatch.setattr(execution, '_audit', fail)
    elif phase == 'release':
        original = DeviceLeases._event

        def fail(self, db, event, token, timestamp):
            original(self, db, event, token, timestamp)
            if event == 'RELEASED':
                raise ValueError('Synthetic release audit failure')
        monkeypatch.setattr(DeviceLeases, '_event', fail)
    else:
        original = execution._audit

        def expire(*args, **kwargs):
            original(*args, **kwargs)
            bulk[1][0] += timedelta(seconds=136)
        monkeypatch.setattr(execution, '_audit', expire)
    with pytest.raises((ValueError, QueueConflict)):
        awaiting(execution, staged)
    assert dump(execution.store) == before
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_members').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='RUNNING'").fetchone()[0] == 2


def test_old_token_is_fenced_and_exact_first_read_replay_writes_nothing(bulk, leases, execution):
    from test_bulk_policy import dump
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    with pytest.raises(QueueConflict):
        leases.renew(staged[0].token, 135)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    snapshot = read(bulk, present=('198.51.100.1',))
    result = execution.confirm(token, session, snapshot, enabled=True)
    before = dump(execution.store)
    assert execution.confirm(token, session, snapshot, enabled=True) == result
    assert dump(execution.store) == before
    with pytest.raises(QueueConflict):
        execution.confirm(staged[0].token, session, snapshot, enabled=True)
    assert dump(execution.store) == before


@pytest.mark.parametrize('outcome', ['QUEUED', 'NOOP', 'VERIFIED', 'FAILED', 'UNVERIFIED', 'CANCELLED'])
def test_awaiting_state_cannot_be_requeued_or_laundered_as_old_result(bulk, leases, execution, outcome):
    from test_bulk_policy import dump

    staged = stage(bulk, leases)
    awaiting(execution, staged)
    before = dump(execution.store)
    for table in ('operation_jobs', 'managed_bulk_attempts'):
        with execution.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(f'UPDATE {table} SET state=?', (outcome,))
    assert dump(execution.store) == before


def test_ack_without_actual_terminal_proof_does_not_release_or_transition(bulk, leases, execution):
    from test_bulk_policy import dump

    staged = stage(bulk, leases)
    before = dump(execution.store)
    for table in ('operation_jobs', 'managed_bulk_attempts'):
        with execution.store._connection() as db, pytest.raises(sqlite3.IntegrityError, match='exact original'):
            db.execute(f"UPDATE {table} SET state='AWAITING_CONFIRMATION'")
    with pytest.raises(QueueConflict, match='RUNNING'):
        leases.release(staged[0].token)
    assert dump(execution.store) == before


def test_other_unknown_work_never_leaves_lease_via_known_ack(bulk, leases, execution):
    from test_bulk_policy import dump

    queue, jobs, receipt = stage(bulk, leases)
    queue.finish_addition(jobs[1]['id'], queue.token.owner, 'UNVERIFIED', reason='Synthetic unknown')
    receipt = replace(receipt, acknowledgements=receipt.acknowledgements[:1])
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='Unknown device work'):
        execution.await_confirmation(queue.token, receipt, (jobs[0]['id'],), enabled=True)
    assert dump(execution.store) == before


@pytest.mark.parametrize('fault', ['partial', 'stale', 'wrong_device', 'wrong_epoch', 'old_visit', 'pre_settlement', 'future'])
def test_bad_confirmation_keeps_all_jobs_awaiting_and_no_verdict(bulk, leases, execution, fault):
    from test_bulk_policy import dump
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    settled = bulk[1][0]
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    snapshot = read(bulk)
    if fault == 'partial': snapshot = replace(snapshot, complete=False)
    if fault == 'stale': bulk[1][0] += timedelta(seconds=121)
    if fault == 'wrong_device': token, _ = acquire(leases, device=2)
    if fault == 'wrong_epoch': token = replace(token, epoch=token.epoch+1)
    if fault == 'old_visit': snapshot = replace(snapshot, started_at=settled+timedelta(milliseconds=1))
    if fault == 'pre_settlement': snapshot = replace(snapshot, started_at=settled)
    if fault == 'future': snapshot = replace(snapshot, completed_at=bulk[1][0]+timedelta(seconds=1))
    before = dump(execution.store)
    with pytest.raises((ValueError, QueueConflict)):
        execution.confirm(token, session, snapshot, enabled=True)
    assert dump(execution.store) == before


def test_read_commit_and_result_commit_are_atomic_on_audit_failure(bulk, leases, execution, monkeypatch):
    from test_bulk_policy import dump
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    before = dump(execution.store)
    original = execution._audit

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('Synthetic result audit failure')

    monkeypatch.setattr(execution, '_audit', fail)
    with pytest.raises(ValueError, match='Synthetic'):
        execution.confirm(token, session, read(bulk), enabled=True)
    assert dump(execution.store) == before


def test_confirmation_lease_expiry_rolls_back_read_and_both_results(bulk, leases, execution, monkeypatch):
    from test_bulk_policy import dump
    from test_device_leases import acquire

    session = awaiting(execution, stage(bulk, leases))
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    original = execution._audit

    def expire(*args, **kwargs):
        original(*args, **kwargs)
        bulk[1][0] += timedelta(seconds=136)

    monkeypatch.setattr(execution, '_audit', expire)
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='deadline'):
        execution.confirm(token, session, read(bulk), enabled=True)
    assert dump(execution.store) == before


def test_generic_discovery_cannot_retry_deferred_outcomes_without_new_contract(bulk, leases, execution):
    from test_device_leases import acquire, discover

    session = awaiting(execution, stage(bulk, leases))
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk), enabled=True)
    leases.release(token)
    bulk[1][0] += timedelta(seconds=2)
    _, queue = acquire(leases)
    assert discover(bulk, queue) == 0
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] == 2


def test_restart_after_delegation_expiry_can_confirm_but_never_replay(bulk, leases, execution):
    from test_device_leases import acquire

    session = awaiting(execution, stage(bulk, leases))
    bulk[1][0] += timedelta(hours=1)
    OperationQueue(execution.store).expire_requests()
    token, queue = acquire(leases)
    reopened = PendingExecution(execution.store, queue)
    result = reopened.confirm(token, session, read(bulk, present=('198.51.100.1',)), enabled=True)
    assert [state for _, state in result] == ['OBSERVED_PRESENT', 'CONFIRMED_ABSENT']
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM operation_requests WHERE state='EXPIRED'").fetchone()[0] == 2


@pytest.mark.parametrize('when', ['before', 'after'])
@pytest.mark.parametrize('present', [False, True])
def test_import_cancellation_preserves_present_and_retires_only_confirmed_absent(
        bulk, leases, execution, cancellation_controls, when, present):
    from test_bulk_cancellations import cancel
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    with execution.store._connection() as db:
        root = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts LIMIT 1').fetchone()[0]
    if when == 'before': cancel(cancellation_controls, root)
    session = awaiting(execution, staged)
    if when == 'after': cancel(cancellation_controls, root)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=('198.51.100.1',) if present else ()), enabled=True)
    with execution.store._connection() as db:
        assert db.execute('SELECT enabled FROM managed_shun_targets WHERE ip=?',
                          (IPv4Address('198.51.100.1').packed,)).fetchone()[0] == int(present)
        results = db.execute('SELECT state,attention,outcome FROM managed_bulk_wait_results ORDER BY ip').fetchall()
        assert len(results) == 2 and all(row['attention'] == 0 for row in results)
        assert results[0]['state'] == ('RETAINED_APPLIED' if present else 'STOPPED_UNSENT')
        assert results[0]['outcome'] == ('OBSERVED_PRESENT' if present else 'CONFIRMED_ABSENT')
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0


def test_protection_retirement_survives_confirmation_and_disable(bulk, leases, execution):
    from test_bulk_protection import protect
    from test_device_leases import acquire

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    editor = ProtectedPolicy(execution.store)
    protect(editor)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=('198.51.100.1',)), enabled=True)
    protect(editor, action='edit', enabled=False, confirm_maintenance_resume=True)
    with execution.store._connection() as db:
        assert db.execute('SELECT enabled FROM managed_shun_targets WHERE ip=?',
                          (IPv4Address('198.51.100.1').packed,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2


def test_queue_progress_and_retention_keep_evidence_without_false_completion(bulk, leases, execution):
    from test_device_leases import acquire

    staged = stage(bulk, leases)
    session = awaiting(execution, staged)
    queue = OperationQueue(execution.store)
    status = queue.status(addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True)
    assert status['counts']['AWAITING_CONFIRMATION'] == 2
    assert all(row['state'] == 'AWAITING_CONFIRMATION' for row in status['items'])
    task = status['imports']['tasks'][0]
    assert task['processed'] == 0 and task['outstanding'] == 2
    assert task['counts'] == {'awaiting_confirmation': 2}
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=('198.51.100.1',)), enabled=True)
    leases.release(token)
    task = queue.status()['imports']['tasks'][0]
    assert task['processed'] == 1 and task['outstanding'] == 1
    assert task['counts'] == {'present': 1, 'awaiting_retry': 1}
    bulk[1][0] += timedelta(days=400)
    queue.prune_completed(366)
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM operation_requests').fetchone()[0] == 2


def test_old_profile_reader_and_damaged_job_guard_refuse_without_repair(bulk, leases, execution, monkeypatch):
    from test_bulk_policy import dump

    staged = stage(bulk, leases)
    awaiting(execution, staged)
    expected = bulk_policy._expected
    with monkeypatch.context() as context:
        context.setattr(bulk_policy, '_expected', lambda *args: expected(*args[:11]))
        with execution.store._connection() as db, pytest.raises(BulkUnavailable):
            bulk_policy._state(db)
    with execution.store._connection() as db:
        db.execute('DROP TRIGGER guard_add_claim')
    before = dump(execution.store)
    with execution.store._connection() as db, pytest.raises(BulkUnavailable, match='queue schema'):
        bulk_policy._state(db)
    assert dump(execution.store) == before


def test_disabled_hooks_do_not_create_state(execution):
    from test_bulk_policy import dump

    before = dump(execution.store)
    with pytest.raises(PermissionError): execution.await_confirmation(None, None, None)
    with pytest.raises(PermissionError): execution.confirm(None, None, None)
    assert dump(execution.store) == before
