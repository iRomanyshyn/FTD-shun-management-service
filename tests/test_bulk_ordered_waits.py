"""Durable ordered reservations on disposable SQLite; no lab or device work."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_ordered_removals import bulk as bulk_fixture
from test_bulk_ordered_removals import cancellation_controls as cancellation_fixture
from test_bulk_ordered_removals import dispatch as dispatch_fixture
from test_bulk_ordered_removals import journal as journal_fixture
from test_bulk_ordered_removals import leases as leases_fixture
from test_bulk_ordered_removals import running
from test_bulk_ordered_removals import waits as waits_fixture
from test_bulk_policy import confirm, dump, prepare
from test_device_leases import grant

from ftd_shun_manager import bulk_ordered_waits
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_ordered_removals import BulkOrderedRemovalScopes
from ftd_shun_manager.bulk_ordered_waits import (
    BulkOrderedWaits,
    canonical_ordered_removal,
    captured,
)
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.bulk_removals import BulkRemovals, canonical_removal
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


@pytest.fixture
def ordered(bulk, leases):
    service = BulkOrderedWaits(bulk[0].store, OperationQueue(bulk[0].store))
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize(enabled=True)
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def review(ordered, bulk, *, device=None):
    value = ordered.scopes.snapshot(IP, device_id=device, now=bulk[1][0])
    assert value['disposition'] == 'WAITING_ADD'
    return value['scope'], captured(value)


def reserve(ordered, value, **changes):
    scope, predecessors = value
    args = {'key': str(uuid4()), 'reviewed': scope, 'predecessors': predecessors,
            'digest': canonical_ordered_removal(scope, predecessors)[1],
            'subject': 'synthetic:operator', 'display_name': 'Actual synthetic operator',
            'roles': ('Operator',), 'enabled': True}
    return ordered.reserve(**(args | changes))


def test_missing_default_disabled_and_exact_queue_boundary(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = BulkOrderedWaits(store, OperationQueue(store))
    with pytest.raises(PermissionError): service.initialize()
    with pytest.raises(PermissionError): service.initialize(enabled=1)
    with pytest.raises(BulkUnavailable): service.initialize(enabled=True)
    with pytest.raises(PermissionError): service.reserve(None, None, None, None, None, None, None)
    with pytest.raises(sqlite3.OperationalError): service.status(str(uuid4()))
    assert not store.path.exists()


def test_explicit_migration_requires_both_pauses_and_quiescence(bulk, leases):
    service = BulkOrderedWaits(bulk[0].store, OperationQueue(bulk[0].store))
    before = dump(service.store)
    with pytest.raises(QueueConflict): service.initialize(enabled=True)
    assert dump(service.store) == before
    grant(bulk)
    running(bulk, leases)
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(service.store)
    with pytest.raises(ManagedConflict): service.initialize(enabled=True)
    assert dump(service.store) == before


def test_migration_is_atomic_idempotent_and_does_not_change_original_receipts(ordered, bulk, monkeypatch):
    confirm(bulk, prepare(bulk)[1])
    before = dump(ordered.store)
    ordered.initialize(enabled=True)
    assert dump(ordered.store) == before
    assert not hasattr(ordered, 'advance')
    def forbidden(*_args, **_kwargs): raise AssertionError('No startup or read initialization.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    with pytest.raises(KeyError): ordered.status(str(uuid4()))
    assert dump(ordered.store) == before


def test_late_migration_failure_rolls_back_even_if_caller_commits(bulk, leases, monkeypatch):
    service = BulkOrderedWaits(bulk[0].store, OperationQueue(bulk[0].store))
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(service.store)
    original = bulk_ordered_waits._state
    def fail(db):
        if bulk_ordered_waits.present(db): raise BulkUnavailable('Synthetic late migration failure.')
        return original(db)
    monkeypatch.setattr(bulk_ordered_waits, '_state', fail)
    with service.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(BulkUnavailable): service.initialize(enabled=True, connection=db)
    assert dump(service.store) == before


def test_atomic_whole_scope_retirement_reservation_and_actual_actor_audit(ordered, bulk, leases):
    grant(bulk, devices=(1, 2))
    token, queue, job = running(bulk, leases)
    ordered.store.record_observed_shun(3, IP, 'management')
    result = reserve(ordered, review(ordered, bulk))
    assert result['state'] == 'WAITING_ADD' and result['target_count'] == 3 and result['predecessor_count'] == 1
    assert result['retired_targets'] == 2 and result['managed_revision'] == 2
    assert result['cleanup_reserved'] and not result['device_work_admitted'] and not result['verified_removal']
    with ordered.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0] == 2  # No adoption.
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job['id'],)).fetchone()[0] == 'RUNNING'
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
        assert ordered.queue._pending_count(db) == 4  # One running ADD + whole three-target cleanup.
        assert ordered.queue._active_request_count(db) == 2
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    event = next(row for row in ordered.store.list_events() if row['event_type'] == 'MANAGED_ORDERED_REMOVAL_RESERVED')
    assert event['actor_subject'] == 'synthetic:operator' and event['actor_roles'] == ['Operator']
    queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    assert ordered.status(result['operation_id'])['predecessors'][0]['state'] == 'NOOP'
    assert ordered.status(result['operation_id'])['state'] == 'WAITING_ADD'  # No promotion exists.


@pytest.mark.parametrize('change', ['scope', 'settled', 'protection', 'reason', 'digest', 'roles', 'paused', 'deadline'])
def test_stale_scope_predecessor_or_wrong_action_never_partially_writes(ordered, bulk, leases, change):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    value, options = review(ordered, bulk), {}
    if change == 'scope': ordered.store.record_observed_shun(3, IP, 'management')
    elif change == 'settled': queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    elif change == 'protection': ProtectedPolicy(ordered.store, initialize_queue=False).change(
        'add', IP, 0, 'synthetic:policy', 'Policy author', ('Viewer',), managed_revision=1)
    elif change == 'reason': options['reason'] = 'Not the frozen reason.'
    elif change == 'digest': options['digest'] = canonical_removal(value[0])[1]
    elif change == 'roles': options['roles'] = ('Viewer',)
    elif change == 'deadline': bulk[1][0] += timedelta(seconds=136)
    else:
        with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(ordered.store)
    with pytest.raises((ValueError, PermissionError)): reserve(ordered, value, **options)
    assert dump(ordered.store) == before


@pytest.mark.parametrize('damage', ['extra', 'bool', 'duplicate', 'uuid', 'time', 'authority', 'empty', 'scope_digest'])
def test_separate_literal_ordered_descriptor(ordered, bulk, leases, damage):
    grant(bulk)
    running(bulk, leases)
    scope, predecessors = review(ordered, bulk)
    if damage == 'extra': predecessors[0]['evidence']['command'] = 'no shun'
    elif damage == 'bool': predecessors[0]['evidence']['executor_epoch'] = True
    elif damage == 'duplicate': predecessors.append(predecessors[0])
    elif damage == 'uuid': predecessors[0]['evidence']['job_id'] = 'not a UUID'
    elif damage == 'time': predecessors[0]['evidence']['requested_at'] = '2026-10-21T15:00:02+03:00'
    elif damage == 'authority': predecessors[0]['evidence']['generation'] += 1
    elif damage == 'empty': predecessors.clear()
    else: scope['scope_digest'] = '0' * 64
    before = dump(ordered.store)
    with pytest.raises(ValueError): canonical_ordered_removal(scope, predecessors)
    assert dump(ordered.store) == before


@pytest.mark.parametrize('failure', ['audit', 'clock', 'expiry', 'lease', 'capacity', 'active', 'rate', 'ledger', 'roots'])
def test_late_failure_and_all_capacity_checks_roll_back_even_outer_commit(ordered, bulk, leases, monkeypatch, failure):
    grant(bulk)
    running(bulk, leases)
    scope, predecessors = review(ordered, bulk)
    before = dump(ordered.store)
    original = ordered.store._insert_event
    def fail(*args, **kwargs):
        if failure == 'audit': raise RuntimeError('Synthetic audit failure.')
        if failure == 'clock': bulk[1][0] -= timedelta(seconds=1)
        if failure == 'expiry': bulk[1][0] += timedelta(seconds=901)
        if failure == 'lease': bulk[1][0] += timedelta(seconds=136)
        return original(*args, **kwargs)
    if failure in {'audit', 'clock', 'expiry', 'lease'}: monkeypatch.setattr(ordered.store, '_insert_event', fail)
    elif failure == 'capacity': monkeypatch.setattr(ordered.queue, '_pending_count', lambda db: 999)
    elif failure == 'active': monkeypatch.setattr(ordered.queue, '_active_request_count', lambda db: 2000)
    elif failure == 'rate': monkeypatch.setattr(ordered.queue, '_recent_request_count', lambda *args: 10)
    elif failure == 'ledger': monkeypatch.setattr(bulk_ordered_waits, 'MAX_REQUESTS', 1)
    else: monkeypatch.setattr(bulk_ordered_waits, 'MAX_ROOTS', 0)
    with ordered.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises((RuntimeError, ValueError)):
            ordered.apply_reserve(db, str(uuid4()), scope, predecessors, canonical_ordered_removal(scope, predecessors)[1],
                                  'synthetic:operator', 'Operator', ('Operator',), enabled=True)
    assert dump(ordered.store) == before


def test_same_key_concurrency_replay_after_restart_cancel_and_pruning_never_reenables(ordered, bulk, leases):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    value, key = review(ordered, bulk), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(ordered, value, key=key), range(2)))
    assert sum(not result['replayed'] for result in results) == 1
    original = next(result for result in results if not result['replayed'])
    queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    ordered.cancel(key, 'synthetic:operator', 'Operator', ('Operator',))
    bulk[1][0] += timedelta(days=367)
    ordered.queue.prune_completed(366)
    restart = BulkOrderedWaits(ordered.store, OperationQueue(ordered.store))
    before = dump(ordered.store)
    assert reserve(restart, value, key=key) == {**original, 'replayed': True}
    assert dump(ordered.store) == before
    with ordered.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 0


@pytest.mark.parametrize('outcome', ['VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'DEFERRED'])
def test_queue_and_audit_retention_hold_original_evidence_after_all_outcomes(ordered, bulk, leases, outcome):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    value = review(ordered, bulk)
    result = reserve(ordered, value)
    if outcome == 'DEFERRED':
        queue.defer_addition(job['id'], token.owner)
        ordered.queue.cancel_obsolete_policy()
    else:
        result_value = AdditionResult(True, 'management') if outcome == 'VERIFIED' else AdditionResult(False, None) if outcome == 'NOOP' else outcome
        queue.finish_addition(job['id'], token.owner, result_value)
    bulk[1][0] += timedelta(days=367)
    ordered.queue.expire_requests()
    assert ordered.status(result['operation_id'])['state'] == 'EXPIRED'
    ordered.queue.prune_completed(366)
    ordered.store.prune_expired_history(366, bulk[1][0])
    with ordered.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM operation_requests WHERE id=?', (value[1][0]['evidence']['request_id'],)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM shun_events WHERE id=?', (value[1][0]['evidence']['claim_event_id'],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0


@pytest.mark.parametrize('damage', ['job', 'link', 'claim', 'deadline'])
def test_corrupt_held_evidence_refuses_both_pruners_before_any_deletion(ordered, bulk, leases, damage):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    value = review(ordered, bulk)
    reserve(ordered, value)
    queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    with ordered.store._connection() as db:
        if damage == 'job': db.execute('DELETE FROM operation_jobs WHERE id=?', (job['id'],))
        elif damage == 'link': db.execute('DELETE FROM operation_links WHERE job_id=?', (job['id'],))
        elif damage == 'claim': db.execute('DELETE FROM shun_events WHERE id=?', (value[1][0]['evidence']['claim_event_id'],))
        else: db.execute('UPDATE operation_requests SET expires_at=? WHERE id=?', (stamp(bulk[1][0]), value[1][0]['evidence']['request_id']))
    bulk[1][0] += timedelta(days=367)
    before = dump(ordered.store)
    with pytest.raises(ValueError): ordered.queue.prune_completed(366)
    assert dump(ordered.store) == before
    with pytest.raises(ValueError): ordered.store.prune_expired_history(366, bulk[1][0])
    assert dump(ordered.store) == before


def test_owner_or_admin_cancel_expiry_keeps_policy_stopped_and_claim_unchanged(ordered, bulk, leases):
    grant(bulk)
    _, _, job = running(bulk, leases)
    result = reserve(ordered, review(ordered, bulk))
    key = result['operation_id']
    before = dump(ordered.store)
    with pytest.raises(PermissionError): ordered.cancel(key, 'other:operator', 'Other', ('Operator',))
    assert dump(ordered.store) == before
    with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    assert ordered.cancel(key, 'other:admin', 'Admin', ('Administrator',))['state'] == 'CANCELLED'
    before = dump(ordered.store)
    assert ordered.cancel(key, 'other:admin', 'Admin', ('Administrator',))['replayed']
    assert dump(ordered.store) == before
    with ordered.store._connection() as db:
        assert ordered.queue._pending_count(db) == 1 and ordered.queue._active_request_count(db) == 1
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()


def test_held_pairs_block_independent_manual_ready_grants_but_not_protected_policy(ordered, bulk, leases):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    reserve(ordered, review(ordered, bulk))
    queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    before = dump(ordered.store)
    with pytest.raises(QueueConflict):
        ordered.queue.enqueue(str(uuid4()), [(2, IP)], 'synthetic:operator', 'Operator', ('Operator',))
    scope = BulkOrderedRemovalScopes(ordered.store).snapshot(IP, device_id=2, now=bulk[1][0])['scope']
    with pytest.raises(QueueConflict):
        BulkRemovals(ordered.store, ordered.queue).admit(str(uuid4()), scope, canonical_removal(scope)[1],
            'synthetic:operator', 'Operator', ('Operator',), enabled=True)
    assert dump(ordered.store) == before
    # Independent protected removal remains a semantic system request, not a manual bypass.
    ordered.queue.enqueue(str(uuid4()), [(2, IP)], 'system:trusted-ip-policy', 'Protected policy', (), source='trusted_policy')


def test_schema_identity_deadline_membership_and_phase_cannot_be_rearmed(ordered, bulk, leases):
    grant(bulk)
    running(bulk, leases)
    key = reserve(ordered, review(ordered, bulk))['operation_id']
    with ordered.store._connection() as db:
        for sql in ("UPDATE managed_bulk_ordered_roots SET expires_at='2099'", 'DELETE FROM managed_bulk_ordered_roots',
                    'UPDATE managed_bulk_ordered_members SET device_id=4', 'DELETE FROM managed_bulk_ordered_members',
                    "UPDATE managed_bulk_ordered_roots SET state='ADMITTING'"):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
    ordered.cancel(key, 'synthetic:operator', 'Operator', ('Operator',))
    with ordered.store._connection() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE managed_bulk_ordered_roots SET state='WAITING_ADD'")
        assert _state(db)['revision'] == 2


def test_captures_two_parallel_adds_as_one_root_not_a_single_target_loop(ordered, bulk, leases):
    grant(bulk, devices=(1, 2, 3))
    first, second = running(bulk, leases), running(bulk, leases, device=2)
    value = review(ordered, bulk)
    result = reserve(ordered, value)
    assert result['predecessor_count'] == 2 and result['target_count'] == 3
    first[1].finish_addition(first[2]['id'], first[0].owner, AdditionResult(False, None))
    status = ordered.status(result['operation_id'])
    assert [row['state'] for row in status['predecessors']] == ['NOOP', 'RUNNING']
    assert status['state'] == 'WAITING_ADD' and not status['device_work_admitted']
    second[1].finish_addition(second[2]['id'], second[0].owner, 'UNVERIFIED')
    assert [row['state'] for row in ordered.status(result['operation_id'])['predecessors']] == ['NOOP', 'UNVERIFIED']
    with ordered.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_roots').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_members').fetchone()[0] == 3
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()


def test_original_request_key_actor_and_expiry_never_gain_new_authority(ordered, bulk, leases):
    grant(bulk)
    _, _, job = running(bulk, leases)
    value = review(ordered, bulk)
    result = reserve(ordered, value)
    key = result['operation_id']
    before = dump(ordered.store)
    with pytest.raises(ManagedConflict): reserve(ordered, value, key=key, subject='other:operator')
    assert dump(ordered.store) == before
    with pytest.raises(QueueConflict): ordered.queue.enqueue(key, [(2, IP)], 'synthetic:operator', 'Operator', ('Operator',))
    assert dump(ordered.store) == before
    bulk[1][0] += timedelta(seconds=901)
    ordered.queue.expire_requests()
    assert ordered.status(key)['expires_at'] == result['expires_at']
    before = dump(ordered.store)
    assert reserve(ordered, value, key=key)['expires_at'] == result['expires_at']
    assert dump(ordered.store) == before
    with ordered.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert ordered.queue._pending_count(db) == 1
        assert ordered.queue._recent_request_count(db, 'synthetic:operator', bulk[1][0] - timedelta(seconds=900)) == 1


def test_missing_optional_schema_never_initialized_by_admission_or_reads(bulk, leases):
    grant(bulk)
    running(bulk, leases)
    service = BulkOrderedWaits(bulk[0].store, OperationQueue(bulk[0].store))
    value = review(service, bulk)
    before = dump(service.store)
    with pytest.raises(BulkUnavailable): reserve(service, value)
    with pytest.raises(BulkUnavailable): service.status(str(uuid4()))
    assert dump(service.store) == before


def test_partial_or_unknown_profile_and_malformed_retained_scope_fail_closed(ordered, bulk, leases):
    with ordered.store._connection() as db:
        db.execute('DROP TRIGGER managed_bulk_ordered_member_retained')
    before = dump(ordered.store)
    with ordered.store._connection() as db, pytest.raises(BulkUnavailable): _state(db)
    assert dump(ordered.store) == before


def test_pending_root_excludes_new_grants_even_after_all_adds_and_leases_settle(ordered, bulk, leases):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    reserve(ordered, review(ordered, bulk))
    queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
    leases.release(token)
    _, proposal = prepare(bulk, '198.51.100.2')
    before = dump(ordered.store)
    with pytest.raises(ManagedConflict, match='Ordered cleanup reservations'): confirm(bulk, proposal)
    assert dump(ordered.store) == before


def test_startup_and_read_methods_do_not_create_ordered_storage(bulk, leases):
    before = dump(bulk[0].store)
    queue = OperationQueue(bulk[0].store)
    queue.status()
    queue.expire_requests()
    queue.prune_completed(366)
    bulk[0].store.prune_expired_history(366, bulk[1][0])
    assert dump(bulk[0].store) == before
