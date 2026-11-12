"""Confirmed-absence fresh admission on disposable deferred profiles only."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4

import pytest
from test_bulk_policy import dump
from test_device_leases import acquire, claim
from test_pending_confirmation import SyntheticV7Queue, read, stage
from test_pending_execution import awaiting
from test_pending_execution import bulk as bulk_fixture
from test_pending_execution import cancellation_controls as cancellation_fixture
from test_pending_execution import dispatch as dispatch_fixture
from test_pending_execution import execution as execution_fixture
from test_pending_execution import journal as journal_fixture
from test_pending_execution import leases as leases_fixture
from test_pending_execution import ledger as ledger_fixture
from test_pending_execution import waits as waits_fixture

from ftd_shun_manager.agent_protocol import PendingAddition, SettledPendingAdditions
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.pending_retries import PendingRetries, RetryDeferred

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture


def absent(bulk, leases, execution, *, count=1, present=()):
    staged = stage(bulk, leases, count=count)
    session = awaiting(execution, staged)
    bulk[1][0] += timedelta(seconds=1)
    token, queue = acquire(leases)
    snapshot = read(bulk, present=present)
    execution.confirm(token, session, snapshot, enabled=True)
    with execution.store._connection() as db:
        parents = tuple(row[0] for row in db.execute('SELECT id FROM managed_bulk_attempts ORDER BY ip'))
    return token, queue, snapshot, parents


def admit(execution, visit, **changes):
    token, queue, snapshot, parents = visit
    with execution.store._connection() as db:
        revision = db.execute('SELECT revision FROM managed_bulk_registry').fetchone()[0]
        protected = db.execute('SELECT revision FROM protected_policy').fetchone()[0]
    options = {'enabled': True, 'addition_device_ids': frozenset({1}), **changes}
    return PendingRetries(execution.store, queue).admit(token, snapshot, parents, revision, protected, **options)


def complete_absent(bulk, leases, execution, visit, *, snapshot_changes=None):
    token, _, _, _ = visit
    queue = SyntheticV7Queue(execution.store, token)
    job = claim(queue)
    assert job is not None
    acknowledgement = PendingAddition(IPv4Address(job['ip']), 1)
    queue.acknowledge_addition(job['id'], token.owner, acknowledgement)
    receipt = SettledPendingAdditions(token.device_id, UUID(token.owner).bytes, 2, (acknowledgement,))
    session = execution.await_confirmation(token, receipt, (job['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    new_token, new_queue = acquire(leases)
    snapshot = read(bulk, **(snapshot_changes or {}))
    execution.confirm(new_token, session, snapshot, enabled=True)
    with execution.store._connection() as db:
        parent = db.execute('SELECT id FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()[0]
    return new_token, new_queue, snapshot, (parent,)


def test_new_attempt_uses_same_confirming_read_after_backoff_and_preserves_parent(bulk, leases, execution):
    visit = absent(bulk, leases, execution)
    before = dump(execution.store)
    with pytest.raises(RetryDeferred) as delayed:
        admit(execution, visit)
    assert delayed.value.retry_at.endswith('08.000Z')
    assert dump(execution.store) == before
    with execution.store._connection() as db:
        parent = tuple(db.execute('SELECT * FROM managed_bulk_attempts').fetchone())
    bulk[1][0] += timedelta(seconds=5)
    accepted = admit(execution, visit)
    assert accepted['device_work_sent'] is False and not accepted['replayed']
    child = accepted['attempts'][0]
    assert child['attempt_id'] != visit[3][0]
    with execution.store._connection() as db:
        assert tuple(db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (visit[3][0],)).fetchone()) == parent
        link = db.execute('SELECT * FROM managed_bulk_pending_retries').fetchone()
        assert link['predecessor_id'] == visit[3][0] == link['origin_id'] and link['ordinal'] == 1
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (child['operation_id'],)).fetchone()[0] == 'QUEUED'
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0
    assert claim(visit[1])['id'] == child['operation_id']


def test_operator_resume_requires_new_read_for_a_deferred_retry(bulk, leases, execution):
    from ftd_shun_manager.managed_addition_controls import ManagedAdditionControls

    controls = ManagedAdditionControls(execution.store, clock=lambda: bulk[1][0])
    controls.initialize()
    visit = absent(bulk, leases, execution)
    controls.change(str(uuid4()), 'imports', 'PAUSE', 0, 'fixture', 'Fixture operator', ('Operator',))
    bulk[1][0] += timedelta(seconds=6)
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='paused'):
        admit(execution, visit)
    assert dump(execution.store) == before
    controls.change(str(uuid4()), 'imports', 'RESUME', 1, 'fixture', 'Fixture operator', ('Operator',))
    before = dump(execution.store)
    with pytest.raises(QueueConflict):
        admit(execution, visit)  # Original absence predates Resume; no cached-read reuse.
    assert dump(execution.store) == before
    bulk[1][0] += timedelta(seconds=1)
    token, queue, _, parents = visit
    result = admit(execution, (token, queue, read(bulk), parents))
    assert not result['replayed'] and not result['device_work_sent']
    assert result['attempts'][0]['attempt_id'] != parents[0]


def test_exponential_delays_and_rolling_hour_limit_are_typed_waits(bulk, leases, execution):
    from ftd_shun_manager.pending_retries import HOURLY_LIMIT

    assert HOURLY_LIMIT == 12
    visit = absent(bulk, leases, execution)
    for ordinal in range(1, 13):
        expected = min(60, 5 * 2 ** min(ordinal-1, 4))
        before = bulk[1][0]
        with pytest.raises(RetryDeferred) as delayed:
            admit(execution, visit)
        assert delayed.value.retry_at == (before+timedelta(seconds=expected)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        bulk[1][0] += timedelta(seconds=expected)
        admit(execution, visit)
        visit = complete_absent(bulk, leases, execution, visit)
    bulk[1][0] += timedelta(seconds=60)
    before = dump(execution.store)
    with pytest.raises(RetryDeferred, match='hourly') as delayed:
        admit(execution, visit)
    assert dump(execution.store) == before
    leases.release(visit[0])
    bulk[1][0] = datetime.fromisoformat(delayed.value.retry_at)
    token, queue = acquire(leases)
    accepted = admit(execution, (token, queue, read(bulk), visit[3]))
    assert accepted['attempts'][0]['state'] == 'QUEUED'
    with execution.store._connection() as db:
        assert db.execute('SELECT MAX(ordinal) FROM managed_bulk_pending_retries').fetchone()[0] == 13


@pytest.mark.parametrize('fault', ['present', 'partial', 'stale', 'future', 'same_id_changed_contents',
                                  'other_device', 'other_owner', 'expired', 'unknown_parent', 'duplicate_parent'])
def test_bad_scope_read_or_lease_does_not_admit_any_job(bulk, leases, execution, fault):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    token, queue, snapshot, parents = visit
    if fault == 'present': snapshot = replace(snapshot, present_ips=frozenset({IPv4Address('198.51.100.1')}))
    if fault == 'partial': snapshot = replace(snapshot, complete=False)
    if fault == 'stale': bulk[1][0] += timedelta(seconds=121)
    if fault == 'future': snapshot = replace(snapshot, completed_at=bulk[1][0]+timedelta(seconds=1))
    if fault == 'same_id_changed_contents': snapshot = replace(snapshot, present_ips=frozenset({IPv4Address('192.0.2.9')}))
    if fault == 'other_device': token = replace(token, device_id=2)
    if fault == 'other_owner': token = replace(token, owner=str(uuid4()))
    if fault == 'expired': bulk[1][0] += timedelta(seconds=136)
    if fault == 'unknown_parent': parents = (str(uuid4()),)
    if fault == 'duplicate_parent': parents = parents*2
    before = dump(execution.store)
    with pytest.raises((ValueError, QueueConflict)):
        admit(execution, (token, queue, snapshot, parents))
    assert dump(execution.store) == before


def test_confirmed_presence_is_not_first_confirmation_retry_authority(bulk, leases, execution):
    visit = absent(bulk, leases, execution, present=('198.51.100.1',))
    bulk[1][0] += timedelta(seconds=5)
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='confirmed-absent'):
        admit(execution, visit)
    assert dump(execution.store) == before


@pytest.mark.parametrize('revoke', ['cancel', 'protect', 'pause', 'disable_device', 'suspend', 'retire'])
def test_current_policy_revocation_stops_fresh_admission(bulk, leases, execution, cancellation_controls, revoke):
    from test_bulk_cancellations import cancel
    from test_bulk_policy import retire
    from test_bulk_protection import protect

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    with execution.store._connection() as db:
        root = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts').fetchone()[0]
        if revoke == 'pause': db.execute('UPDATE operation_executor SET mutations_suspended=1')
        if revoke == 'disable_device': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
        if revoke == 'suspend': db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
    if revoke == 'cancel': cancel(cancellation_controls, root)
    if revoke == 'protect': protect(ProtectedPolicy(execution.store))
    if revoke == 'retire': retire(bulk)
    before = dump(execution.store)
    with pytest.raises(QueueConflict):
        admit(execution, visit)
    assert dump(execution.store) == before


def test_exact_replay_is_historical_after_revocation_and_does_not_renew_consent(bulk, leases, execution):
    from test_bulk_protection import protect

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    accepted = admit(execution, visit)
    protect(ProtectedPolicy(execution.store))
    leases.release(visit[0])
    bulk[1][0] += timedelta(hours=1)
    before = dump(execution.store)
    replayed = admit(execution, visit)
    assert replayed['replayed'] and replayed['attempts'][0]['attempt_id'] == accepted['attempts'][0]['attempt_id']
    assert dump(execution.store) == before


def test_portion_rolls_back_first_new_member_if_second_is_ineligible(bulk, leases, execution):
    from test_bulk_protection import protect

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    visit = absent(bulk, leases, execution, count=2)
    bulk[1][0] += timedelta(seconds=5)
    protect(ProtectedPolicy(execution.store), ip=IPv4Address('198.51.100.2'))
    before = dump(execution.store)
    with pytest.raises(QueueConflict):
        admit(execution, visit)
    assert dump(execution.store) == before


def test_sixteen_member_portion_preserves_all_original_absent_attempts(bulk, leases, execution):
    visit = absent(bulk, leases, execution, count=16)
    bulk[1][0] += timedelta(seconds=5)
    accepted = admit(execution, visit)
    assert len(accepted['attempts']) == 16
    assert not set(visit[3]) & {row['attempt_id'] for row in accepted['attempts']}
    with execution.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='CONFIRMED_ABSENT'").fetchone()[0] == 16
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='QUEUED'").fetchone()[0] == 16
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 16


def test_shared_later_read_identity_cannot_change_between_admissions(bulk, leases, execution):
    token, queue, _, parents = absent(bulk, leases, execution, count=2)
    bulk[1][0] += timedelta(seconds=5)
    snapshot = read(bulk)
    admit(execution, (token, queue, snapshot, parents[:1]))
    changed = replace(snapshot, present_ips=frozenset({IPv4Address('192.0.2.9')}))
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='Shared retry read identity'):
        admit(execution, (token, queue, changed, parents[1:]))
    assert dump(execution.store) == before


def test_later_confirmation_cannot_rebind_a_retained_retry_read_identity(bulk, leases, execution):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    retry_read = read(bulk)
    admit(execution, (visit[0], visit[1], retry_read, visit[3]))
    # A complete causal confirmation is still invalid if its UUID was already
    # bound to another read's time/content by retry admission. No verdict commits.
    with pytest.raises(BulkUnavailable):
        complete_absent(bulk, leases, execution, visit, snapshot_changes={'id': retry_read.id})
    with execution.store._connection() as db:
        _state(db)
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_reads').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='AWAITING_CONFIRMATION'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='CONFIRMED_ABSENT'").fetchone()[0] == 1


def test_revocation_after_admission_cancels_child_before_claim(bulk, leases, execution):
    from test_bulk_protection import protect

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    child = admit(execution, visit)['attempts'][0]
    protect(ProtectedPolicy(execution.store))
    assert claim(visit[1]) is None
    with execution.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE id=?', (child['attempt_id'],)).fetchone()[0] == 'CANCELLED'
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_RUNNING'",
                          (child['attempt_id'],)).fetchone()[0] == 0


def test_late_lease_expiry_rolls_back_jobs_provenance_and_audit(bulk, leases, execution, monkeypatch):
    from ftd_shun_manager import pending_retries

    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    original = pending_retries.retain

    def expire(*args, **kwargs):
        original(*args, **kwargs)
        bulk[1][0] += timedelta(seconds=136)

    monkeypatch.setattr(pending_retries, 'retain', expire)
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='deadline'):
        admit(execution, visit)
    assert dump(execution.store) == before


def test_expired_original_delegation_is_not_renewed_by_fresh_job(bulk, leases, execution):
    staged = stage(bulk, leases, count=1)
    session = awaiting(execution, staged)
    bulk[1][0] += timedelta(hours=1)
    from ftd_shun_manager.operation_queue import OperationQueue

    OperationQueue(execution.store).expire_requests()
    token, queue = acquire(leases)
    snapshot = read(bulk)
    execution.confirm(token, session, snapshot, enabled=True)
    with execution.store._connection() as db:
        parent = db.execute('SELECT id FROM managed_bulk_attempts').fetchone()[0]
        original = tuple(db.execute('SELECT * FROM operation_requests WHERE id=?', (parent,)).fetchone())
    bulk[1][0] += timedelta(seconds=5)
    child = admit(execution, (token, queue, snapshot, (parent,)))['attempts'][0]
    with execution.store._connection() as db:
        assert tuple(db.execute('SELECT * FROM operation_requests WHERE id=?', (parent,)).fetchone()) == original
        fresh = db.execute('SELECT * FROM operation_requests WHERE id=?', (child['attempt_id'],)).fetchone()
        assert fresh['state'] == 'ACTIVE' and fresh['id'] != parent
        assert datetime.fromisoformat(fresh['expires_at'])-datetime.fromisoformat(fresh['requested_at']) == timedelta(seconds=900)


def test_never_claimed_stale_child_can_be_replaced_from_new_read(bulk, leases, execution):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    first = admit(execution, visit)['attempts'][0]
    leases.release(visit[0])
    bulk[1][0] += timedelta(seconds=121)
    token, queue = acquire(leases)
    queue.cancel_obsolete_policy()
    bulk[1][0] += timedelta(seconds=1)
    replacement = admit(execution, (token, queue, read(bulk), visit[3]))['attempts'][0]
    assert replacement['attempt_id'] != first['attempt_id']
    with execution.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE id=?', (first['attempt_id'],)).fetchone()[0] == 'CANCELLED'
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 2


def test_lost_child_result_is_held_and_not_replaced(bulk, leases, execution):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    admit(execution, visit)
    job = claim(visit[1])
    visit[1].finish_addition(job['id'], visit[0].owner, 'UNVERIFIED', reason='Synthetic unknown child')
    bulk[1][0] += timedelta(seconds=60)
    before = dump(execution.store)
    with pytest.raises(QueueConflict):
        admit(execution, (visit[0], visit[1], read(bulk), visit[3]))
    assert dump(execution.store) == before


@pytest.mark.parametrize('claimed', [False, True])
def test_retention_keeps_cancelled_child_and_claim_history_before_replacement(bulk, leases, execution, claimed):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    child = admit(execution, visit)['attempts'][0]
    if claimed:
        job = claim(visit[1])
        visit[1].defer_addition(job['id'], visit[0].owner)
    bulk[1][0] += timedelta(seconds=121)
    visit[1].cancel_obsolete_policy()
    leases.release(visit[0])
    with execution.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE id=?', (child['attempt_id'],)).fetchone()[0] == 'CANCELLED'
        retained = [tuple(row) for row in db.execute('''SELECT * FROM shun_events WHERE request_id IN (
            SELECT attempt_id FROM managed_bulk_pending_members UNION SELECT attempt_id FROM managed_bulk_pending_retries)
            OR event_type='DEVICE_LEASE_CLAIMED' ORDER BY id''')]
        execution.store._insert_event(db, 'UNRELATED_OLD_EVENT', None, None, None,
            'system:test', 'Retention test', (), None, {}, '2026-01-01T00:00:00.000Z')
    bulk[1][0] += timedelta(days=400)
    visit[1].prune_completed(366)
    purged = execution.store.prune_expired_history(366, bulk[1][0])
    assert purged['events_deleted'] >= 1
    with execution.store._connection() as db:
        _state(db)
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM operation_requests').fetchone()[0] == 2
        assert [tuple(row) for row in db.execute('''SELECT * FROM shun_events WHERE request_id IN (
            SELECT attempt_id FROM managed_bulk_pending_members UNION SELECT attempt_id FROM managed_bulk_pending_retries)
            OR event_type='DEVICE_LEASE_CLAIMED' ORDER BY id''')] == retained
    token, queue = acquire(leases)
    replacement = (token, queue, read(bulk), visit[3])
    if claimed:
        before = dump(execution.store)
        with pytest.raises(QueueConflict, match='another child'):
            admit(execution, replacement)
        assert dump(execution.store) == before
    else:
        assert admit(execution, replacement)['attempts'][0]['attempt_id'] != child['attempt_id']


def test_pending_ledger_only_audit_retention_keeps_claim_and_ack(bulk, leases, execution):
    staged = stage(bulk, leases, count=1)
    awaiting(execution, staged)
    bulk[1][0] += timedelta(days=400)
    execution.store.prune_expired_history(366, bulk[1][0])
    with execution.store._connection() as db:
        _state(db)
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'").fetchone()[0] == 1


@pytest.mark.parametrize('damage', ['audit', 'link'])
def test_corrupt_retry_evidence_refuses_both_pruners_without_deletion(bulk, leases, execution, damage):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    child = admit(execution, visit)['attempts'][0]
    leases.release(visit[0])
    bulk[1][0] += timedelta(seconds=121)
    token, queue = acquire(leases)
    queue.cancel_obsolete_policy()
    leases.release(token)
    with execution.store._connection() as db:
        if damage == 'audit': db.execute("DELETE FROM shun_events WHERE event_type='MANAGED_BULK_RETRY_ADMITTED'")
        else: db.execute('DELETE FROM operation_links WHERE job_id=?', (child['operation_id'],))
    bulk[1][0] += timedelta(days=400)
    before = dump(execution.store)
    with pytest.raises(ValueError): visit[1].prune_completed(366)
    assert dump(execution.store) == before
    with pytest.raises(ValueError): execution.store.prune_expired_history(366, bulk[1][0])
    assert dump(execution.store) == before


def test_provenance_is_immutable_and_missing_or_changed_audit_refuses(bulk, leases, execution):
    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    admit(execution, visit)
    for sql in ('DELETE FROM managed_bulk_pending_retries', 'UPDATE managed_bulk_pending_retries SET ordinal=2'):
        with execution.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    with execution.store._connection() as db:
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='shun_events'").fetchall():
            db.execute(f'DROP TRIGGER {row[0]}')
        db.execute("DELETE FROM shun_events WHERE event_type='MANAGED_BULK_RETRY_ADMITTED'")
    with execution.store._connection() as db, pytest.raises(BulkUnavailable, match='retry proof'):
        _state(db)


def test_default_disabled_does_not_touch_storage(execution):
    before = dump(execution.store)
    with pytest.raises(PermissionError):
        PendingRetries(execution.store, execution.queue).admit(None, None, None, None, None)
    assert dump(execution.store) == before


def cancelled_prewrite_child(bulk, leases, execution, *, later_visit=False, expired=False):
    from ftd_shun_manager.deferred_worker import DeferredDeviceOperationQueue
    from ftd_shun_manager.operation_queue import OperationQueue

    visit = absent(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=5)
    child = admit(execution, visit)['attempts'][0]
    token = visit[0]
    if later_visit:
        leases.release(token)
        bulk[1][0] += timedelta(seconds=1)
        token, _ = acquire(leases)
    queue = DeferredDeviceOperationQueue(execution.store, token)
    job = claim(queue)
    assert job['id'] == child['operation_id']
    queue.defer_addition(job['id'], token.owner)
    leases.release(token)
    bulk[1][0] += timedelta(seconds=901 if expired else 121)
    if expired:
        OperationQueue(execution.store).expire_requests()
    new_token, new_queue = acquire(leases)
    new_queue.cancel_obsolete_policy()
    bulk[1][0] += timedelta(seconds=1)
    return (new_token, new_queue, read(bulk), visit[3]), child


@pytest.mark.parametrize('later_visit,expired', [(False, False), (True, False), (False, True), (True, True)])
def test_exact_prewrite_cancelled_child_gets_new_ids_after_fresh_absence(bulk, leases, execution, later_visit, expired):
    from ftd_shun_manager.pending_retries import retry_candidates

    visit, child = cancelled_prewrite_child(bulk, leases, execution, later_visit=later_visit, expired=expired)
    with execution.store._connection() as db:
        old = tuple(db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (child['attempt_id'],)).fetchone())
        request = tuple(db.execute('SELECT * FROM operation_requests WHERE id=?', (child['attempt_id'],)).fetchone())
        assert [row['id'] for row in retry_candidates(db, 1)] == list(visit[3])
    result = admit(execution, visit)
    replacement = result['attempts'][0]
    assert replacement['attempt_id'] != child['attempt_id'] and replacement['operation_id'] != child['operation_id']
    with execution.store._connection() as db:
        _state(db)
        assert tuple(db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (child['attempt_id'],)).fetchone()) == old
        assert tuple(db.execute('SELECT * FROM operation_requests WHERE id=?', (child['attempt_id'],)).fetchone()) == request
        assert db.execute('SELECT MAX(ordinal) FROM managed_bulk_pending_retries').fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='VERIFIED'").fetchone()[0] == 0
    assert admit(execution, visit)['replayed']
    assert claim(visit[1])['id'] == replacement['operation_id']


@pytest.mark.parametrize('fault', ['missing_claim', 'missing_defer', 'duplicate_claim', 'duplicate_defer', 'ack',
    'write_sent', 'numeric_false', 'version', 'version_bool', 'owner', 'epoch', 'epoch_bool', 'source', 'group',
    'actor', 'requeue', 'cancel', 'opening'])
def test_missing_or_ambiguous_prewrite_proof_cannot_replace_child(bulk, leases, execution, fault):
    visit, child = cancelled_prewrite_child(bulk, leases, execution)
    with execution.store._connection() as db:
        event = db.execute("SELECT * FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_DEFERRED'",
                           (child['attempt_id'],)).fetchone()
        if fault.startswith('missing_'):
            kind = 'SHUN_OPERATION_RUNNING' if fault == 'missing_claim' else 'SHUN_OPERATION_DEFERRED'
            db.execute('DELETE FROM shun_events WHERE request_id=? AND event_type=?', (child['attempt_id'], kind))
        elif fault.startswith('duplicate_') or fault == 'ack':
            kind = 'SHUN_OPERATION_RUNNING' if fault == 'duplicate_claim' else 'SHUN_OPERATION_DEFERRED'
            original = db.execute('SELECT * FROM shun_events WHERE request_id=? AND event_type=?', (child['attempt_id'], kind)).fetchone()
            values = list(original)
            values[0] = str(uuid4())
            if fault == 'ack': values[2] = 'SHUN_ADDITION_ACKNOWLEDGED'
            db.execute('INSERT INTO shun_events VALUES (' + ','.join('?' for _ in values) + ')', values)
        elif fault == 'opening':
            scope = json.loads(event['details_json'])['device_executor']
            db.execute("DELETE FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED' AND json_extract(details_json,'$.owner')=?",
                       (scope['owner'],))
        else:
            data = json.loads(event['details_json'])
            if fault == 'write_sent': data['write_sent'] = True
            if fault == 'numeric_false': data['write_sent'] = 0
            if fault == 'version': data['batch_session_version'] = 6
            if fault == 'version_bool': data['batch_session_version'] = True
            if fault == 'owner': data['device_executor']['owner'] = str(uuid4())
            if fault == 'epoch': data['device_executor']['epoch'] += 1
            if fault == 'epoch_bool': data['device_executor']['epoch'] = True
            if fault == 'source': data['source'] = 'manual_import'
            if fault == 'actor':
                db.execute('UPDATE shun_events SET actor_subject=? WHERE id=?', ('spoofed', event['id']))
            if fault in {'group', 'requeue', 'cancel'}:
                kind = {'group': 'SHUN_OPERATION_RUNNING', 'requeue': 'MANAGED_BULK_ATTEMPT_QUEUED', 'cancel': 'SHUN_OPERATION_CANCELLED'}[fault]
                original = db.execute('SELECT * FROM shun_events WHERE request_id=? AND event_type=? ORDER BY timestamp,id DESC LIMIT 1',
                                      (child['attempt_id'], kind)).fetchone()
                changed = json.loads(original['details_json'])
                changed['addition_group' if fault == 'group' else 'reason'] = 'changed'
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(changed), original['id']))
            else:
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(data), event['id']))
    before = dump(execution.store)
    with pytest.raises((QueueConflict, BulkUnavailable)):
        admit(execution, visit)
    assert dump(execution.store) == before


def test_replacement_requires_new_read_and_preserves_limits_and_old_receipt(bulk, leases, execution):
    visit, child = cancelled_prewrite_child(bulk, leases, execution)
    with execution.store._connection() as db:
        cancelled_at = datetime.fromisoformat(db.execute('SELECT completed_at FROM managed_bulk_attempts WHERE id=?',
                                                       (child['attempt_id'],)).fetchone()[0])
    snapshot = replace(visit[2], started_at=cancelled_at, completed_at=cancelled_at)
    before = dump(execution.store)
    with pytest.raises(QueueConflict):
        admit(execution, (visit[0], visit[1], snapshot, visit[3]))
    assert dump(execution.store) == before


def test_replaced_child_proof_survives_retention_across_separate_claim_visit(bulk, leases, execution):
    visit, child = cancelled_prewrite_child(bulk, leases, execution, later_visit=True)
    replacement = admit(execution, visit)['attempts'][0]
    leases.release(visit[0])
    bulk[1][0] += timedelta(days=400)
    visit[1].cancel_obsolete_policy()
    visit[1].prune_completed(366)
    execution.store.prune_expired_history(366, bulk[1][0])
    with execution.store._connection() as db:
        _state(db)
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (child['operation_id'],)).fetchone()[0] == 'CANCELLED'
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (replacement['operation_id'],)).fetchone()[0] == 'CANCELLED'


def test_changed_replaced_child_proof_blocks_retention_without_deletion(bulk, leases, execution):
    visit, child = cancelled_prewrite_child(bulk, leases, execution)
    admit(execution, visit)
    leases.release(visit[0])
    with execution.store._connection() as db:
        db.execute("DELETE FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_DEFERRED'", (child['attempt_id'],))
    bulk[1][0] += timedelta(days=400)
    before = dump(execution.store)
    with pytest.raises(BulkUnavailable):
        execution.store.prune_expired_history(366, bulk[1][0])
    assert dump(execution.store) == before
    with pytest.raises(BulkUnavailable):
        visit[1].prune_completed(366)
    assert dump(execution.store) == before


def test_expired_prewrite_replacement_is_automatically_discovered_and_confirmed(bulk, leases, execution):
    import asyncio

    from test_batch_session import states
    from test_batch_session import visit as run_visit
    from test_deferred_worker import Agent, runner

    visit, child = cancelled_prewrite_child(bulk, leases, execution, later_visit=True, expired=True)
    leases.release(visit[0])
    agent = Agent()
    service = runner(execution.store, agent)
    asyncio.run(run_visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 1, 'CANCELLED': 1, 'AWAITING_CONFIRMATION': 1}
    assert len(agent.writes) == 1
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(run_visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 1, 'CANCELLED': 1, 'OBSERVED_PRESENT': 1}
    assert len(agent.writes) == 1
    with execution.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE id=?', (child['attempt_id'],)).fetchone()[0] == 'CANCELLED'
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='VERIFIED'").fetchone()[0] == 0
