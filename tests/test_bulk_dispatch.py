"""Synthetic real queue admissions/claims; no lab, sockets, controller or FTD."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_attempts import OWNER, attempt
from test_bulk_attempts import journal as journal_fixture
from test_bulk_cancellations import cancel
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Disposable shared fixture.
from test_bulk_policy import confirm, dump, prepare
from test_bulk_waits import waits as waits_fixture

from ftd_shun_manager import bulk_dispatch
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_cancellations import BulkCancellations
from ftd_shun_manager.bulk_dispatch import BulkCandidate, BulkDispatch
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.bulk_work import BulkWorkPlans
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.operation_queue import QueueConflict, QueueFull, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy

journal = journal_fixture
cancellation_controls = cancellation_fixture
waits = waits_fixture


@pytest.fixture
def dispatch(bulk, journal, waits):
    policy, _ = bulk
    service = BulkDispatch(policy.store, journal[1])
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize()
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def setup(bulk, dispatch, *, count=1, activate=True):
    policy, clock = bulk
    _, proposal = prepare(bulk, '\n'.join(f'198.51.100.{i}' for i in range(1, count + 1)))
    root = confirm(bulk, proposal)['operation_id']
    with policy.store._connection() as db:
        candidates = tuple(BulkCandidate(row['device_id'], IPv4Address(row['ip']), row['intent_id'], row['generation'],
                                        row['authorization_request_id'], row['revision'])
                           for row in db.execute('SELECT * FROM managed_shun_targets ORDER BY ip'))
        if activate:
            # Explicit disposable activation, NOT an operator/lab procedure.
            db.execute('UPDATE operation_executor SET mutations_suspended=1')
            db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0,dispatch_resume_after=?', (stamp(clock[0]),))
            db.execute('UPDATE operation_executor SET mutations_suspended=0')
    clock[0] += timedelta(seconds=2)
    assert dispatch.queue.claim_cycle(OWNER, 135)
    snapshot = CompleteSnapshot(str(uuid4()), 1, clock[0] - timedelta(seconds=1), clock[0], frozenset())
    return root, snapshot, candidates


def admit(dispatch, snapshot, candidates, **changes):
    args = {'owner': OWNER, 'managed_revision': 1, 'protected_revision': 0,
            'enabled': True, 'addition_device_ids': frozenset({1})}
    return dispatch.admit(snapshot, candidates, **(args | changes))


def claim(dispatch, **changes):
    return dispatch.queue.claim_addition(1, OWNER, dispatch.queue.cutoff(), execution_enabled=True,
                                        **({'bulk_dispatch_enabled': True} | changes))


def test_schema_upgrade_preserves_rows_and_is_suspended_without_admission(bulk, journal, waits):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    controls = BulkCancellations(policy.store, clock=policy.clock)
    receipt, _ = cancel(controls, proposal['operation_id'])
    with policy.store._connection() as db:
        tables = ('managed_shun_targets', 'managed_shun_requests', 'managed_bulk_members', 'managed_bulk_cancellations')
        before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service = BulkDispatch(policy.store, journal[1])
    service.initialize()
    with policy.store._connection() as db:
        assert before == {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        assert _state(db)['restoration_suspended'] is True
        assert not db.execute('SELECT 1 FROM operation_jobs').fetchone()
    assert controls.page(proposal['operation_id'], 'alice', ('Operator',))['result'] == receipt
    before = dump(policy.store)
    service.initialize()
    assert dump(policy.store) == before


def test_upgrade_failure_is_atomic_under_caught_outer_transaction(bulk, journal, waits, monkeypatch):
    policy, _ = bulk
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(policy.store)
    original = bulk_dispatch._state

    def fail(db):
        result = original(db)
        if bulk_dispatch.present(db): raise ValueError('Synthetic upgrade failure')
        return result

    monkeypatch.setattr(bulk_dispatch, '_state', fail)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): BulkDispatch(policy.store, journal[1]).initialize(connection=db)
    assert dump(policy.store) == before


def test_schema_resume_requires_pause_and_quiescence(bulk, dispatch):
    policy, _ = bulk
    with policy.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0')
    setup(bulk, dispatch)
    with policy.store._connection() as db:
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
        with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0')


def test_default_capabilities_and_suspension_never_admit_or_claim(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, activate=False)
    before = dump(dispatch.store)
    assert dispatch.admit(snapshot, candidates, OWNER, 1, 0) is None
    with pytest.raises(QueueConflict, match='suspended'): admit(dispatch, snapshot, candidates)
    assert dump(dispatch.store) == before


def test_atomic_portion_uses_system_identity_original_authority_and_no_import_provenance(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=16)
    result = admit(dispatch, snapshot, candidates)
    assert len(result['attempts']) == 16 and not result['device_work_sent']
    with dispatch.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 16
        assert db.execute('SELECT COUNT(*) FROM operation_links').fetchone()[0] == 16
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] == 16
        assert not db.execute('SELECT 1 FROM manual_import_batches').fetchone()
        assert not db.execute('SELECT 1 FROM shun_import_origins').fetchone()
        assert db.execute("SELECT COUNT(*) FROM operation_requests WHERE actor_roles_json='[]' AND source='trusted_policy'").fetchone()[0] == 16
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='MANAGED_BULK_ATTEMPT_QUEUED'").fetchone()[0] == 16
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert not dispatch.store.list_active_shuns()


def test_claim_requires_new_capability_and_enforces_cutoff_and_serial_device_stream(bulk, dispatch, journal):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    cutoff = dispatch.queue.cutoff()
    result = admit(dispatch, snapshot, candidates)
    assert dispatch.queue.claim_addition(1, OWNER, dispatch.queue.cutoff(), execution_enabled=True,
                                        managed_restoration_enabled=True) is None
    assert dispatch.queue.claim_addition(1, OWNER, cutoff, execution_enabled=True, bulk_dispatch_enabled=True) is None
    first = claim(dispatch)
    assert first['state'] == 'RUNNING' and first['id'] == result['attempts'][0]['operation_id']
    assert claim(dispatch) is None
    dispatch.queue.finish_addition(first['id'], OWNER, AdditionResult(False, None))
    assert claim(dispatch)['id'] == result['attempts'][1]['operation_id']


@pytest.mark.parametrize('outcome,expected', [(AdditionResult(True, 'management'), 'VERIFIED'),
    (AdditionResult(False, None), 'NOOP'), ('FAILED', 'FAILED'), ('UNVERIFIED', 'UNVERIFIED')])
def test_actual_admitted_claimed_job_uses_shared_typed_completion(bulk, dispatch, journal, outcome, expected):
    _, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    assert dispatch.queue.finish_addition(job['id'], OWNER, outcome) == expected
    assert attempt(journal, job['id'])['state'] == expected
    assert bool(dispatch.store.list_active_shuns()) == (expected == 'VERIFIED')


def test_queued_import_cancel_stops_only_original_owned_work(bulk, dispatch, journal, cancellation_controls):
    root, snapshot, candidates = setup(bulk, dispatch, count=2)
    result = admit(dispatch, snapshot, candidates)
    cancel(cancellation_controls, root)
    assert all(attempt(journal, row['operation_id'])['state'] == 'CANCELLED' for row in result['attempts'])
    assert claim(dispatch) is None
    assert all(not row['enabled'] for row in bulk[0].policy_page()['entries'])
    before = dump(dispatch.store)
    assert admit(dispatch, snapshot, candidates)['replayed']
    assert dump(dispatch.store) == before


def test_running_import_cancel_settles_success_then_keeps_maintenance(bulk, dispatch, journal, cancellation_controls):
    root, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    result, _ = cancel(cancellation_controls, root)
    assert result['counts']['WAITING_OUTCOME'] == 1
    dispatch.queue.finish_addition(job['id'], OWNER, AdditionResult(True, 'management'))
    page = cancellation_controls.page(root, 'alice', ('Operator',))
    assert page['settled'] and page['current_counts']['RETAINED_APPLIED'] == 1
    assert bulk[0].policy_page()['entries'][0]['enabled']


def test_protection_cancels_unsent_and_permanently_retires_authority(bulk, dispatch, journal):
    _, snapshot, candidates = setup(bulk, dispatch)
    result = admit(dispatch, snapshot, candidates)
    ProtectedPolicy(dispatch.store).change('add', candidates[0].ip, 0, 'viewer', 'Viewer', ('Viewer',), managed_revision=1)
    assert attempt(journal, result['attempts'][0]['operation_id'])['state'] == 'CANCELLED'
    assert not bulk[0].policy_page()['entries'][0]['enabled']
    assert claim(dispatch) is None


def test_exact_prewrite_deferral_reuses_original_job_only_with_fresh_evidence(bulk, dispatch, journal):
    _, snapshot, candidates = setup(bulk, dispatch)
    result = admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    dispatch.queue.defer_addition(job['id'], OWNER)
    assert claim(dispatch)['id'] == job['id']
    assert len(result['attempts']) == 1
    dispatch.queue.defer_addition(job['id'], OWNER)
    bulk[1][0] += timedelta(seconds=121)
    assert claim(dispatch) is None
    assert attempt(journal, job['id'])['state'] == 'CANCELLED'


def test_expired_worker_records_unknown_and_never_readmits_pair(bulk, dispatch, journal):
    _, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    bulk[1][0] += timedelta(seconds=136)
    assert dispatch.queue.claim_cycle('replacement', 135)
    assert attempt(journal, job['id'])['state'] == 'UNVERIFIED'
    fresh = replace(snapshot, id=str(uuid4()), started_at=bulk[1][0], completed_at=bulk[1][0])
    with pytest.raises(QueueConflict): admit(dispatch, fresh, candidates, owner='replacement')
    assert attempt(journal, job['id'])['state'] == 'UNVERIFIED'


@pytest.mark.parametrize('change', ['revision', 'protected_revision', 'profile', 'owner', 'stale', 'future', 'present',
    'generation', 'intent', 'target_revision', 'device_disabled', 'protected', 'paused', 'capacity', 'last_conflict'])
def test_portion_guards_are_all_or_nothing(bulk, dispatch, monkeypatch, change):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    kwargs = {}
    if change == 'revision': kwargs['managed_revision'] = 0
    if change == 'protected_revision': kwargs['protected_revision'] = 1
    if change == 'profile': kwargs['addition_device_ids'] = frozenset()
    if change == 'owner': kwargs['owner'] = 'other-worker'
    if change == 'stale': snapshot = replace(snapshot, started_at=snapshot.started_at - timedelta(seconds=121))
    if change == 'future': snapshot = replace(snapshot, completed_at=snapshot.completed_at + timedelta(seconds=1))
    if change == 'present': snapshot = replace(snapshot, present_ips=frozenset({candidates[-1].ip}))
    if change == 'generation': candidates = candidates[:-1] + (replace(candidates[-1], generation=2),)
    if change == 'intent': candidates = candidates[:-1] + (replace(candidates[-1], intent_id=str(uuid4())),)
    if change == 'target_revision': candidates = candidates[:-1] + (replace(candidates[-1], target_revision=2),)
    with dispatch.store._connection() as db:
        if change == 'device_disabled': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
        if change == 'paused': db.execute('UPDATE operation_executor SET mutations_suspended=1')
        if change == 'protected': db.execute("INSERT INTO protected_ips VALUES (?,'Synthetic','',1,'2026-10-21T12:00:00Z')", (candidates[-1].ip.packed,))
        if change == 'last_conflict':
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'UNVERIFIED',?,'REMOVE')",
                       (str(uuid4()), candidates[-1].ip.packed, '2026-10-21T12:00:00Z'))
    if change == 'capacity': monkeypatch.setattr(dispatch.queue, '_pending_count', lambda db: 999)
    before = dump(dispatch.store)
    with pytest.raises((QueueConflict, QueueFull)): admit(dispatch, snapshot, candidates, **kwargs)
    assert dump(dispatch.store) == before


def test_late_audit_failure_rolls_back_portion_even_when_caller_catches(bulk, dispatch, monkeypatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    original = dispatch.store._insert_event
    count = 0

    def fail(*args):
        nonlocal count
        count += 1
        if count == 2: raise ValueError('Synthetic last-member audit failure')
        return original(*args)

    monkeypatch.setattr(dispatch.store, '_insert_event', fail)
    before = dump(dispatch.store)
    with dispatch.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): admit(dispatch, snapshot, candidates, connection=db)
    assert dump(dispatch.store) == before


def test_simultaneous_same_snapshot_admission_is_idempotent_not_double_queued(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: admit(dispatch, snapshot, candidates), range(2)))
    assert sorted(row['replayed'] for row in results) == [False, True]
    with dispatch.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 2


def test_partial_schema_is_not_repaired_or_interpreted_as_legacy(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    with dispatch.store._connection() as db: db.execute('DROP TRIGGER managed_bulk_attempt_identity')
    before = dump(dispatch.store)
    with pytest.raises(BulkUnavailable): admit(dispatch, snapshot, candidates)
    with pytest.raises(BulkUnavailable): dispatch.initialize()
    assert dump(dispatch.store) == before


def test_literal_input_bounds_and_snapshot_keys(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=17)
    before = dump(dispatch.store)
    for invalid in (candidates, list(candidates[:1]), (), (candidates[0], candidates[0])):
        with pytest.raises(ValueError): admit(dispatch, snapshot, invalid)
    with pytest.raises(ValueError): admit(dispatch, snapshot, candidates[:1], enabled=1)
    with pytest.raises(ValueError): admit(dispatch, replace(snapshot, complete=False), candidates[:1])
    assert dump(dispatch.store) == before
    admit(dispatch, snapshot, candidates[:1])
    with pytest.raises(QueueConflict): admit(dispatch, replace(snapshot, completed_at=snapshot.completed_at - timedelta(seconds=1)), candidates[:1])


@pytest.mark.parametrize('change', ['device_bool', 'ipv4_string', 'generation_bool', 'revision_bool', 'bad_uuid',
    'mixed_device', 'snapshot_naive', 'snapshot_set', 'snapshot_bool', 'profile_bool', 'revision_float'])
def test_strict_literal_boundaries_never_write(bulk, dispatch, change):
    _, snapshot, candidates = setup(bulk, dispatch)
    kwargs = {}
    if change == 'device_bool': candidates = (replace(candidates[0], device_id=True),)
    if change == 'ipv4_string': candidates = (replace(candidates[0], ip='198.51.100.1'),)
    if change == 'generation_bool': candidates = (replace(candidates[0], generation=True),)
    if change == 'revision_bool': candidates = (replace(candidates[0], target_revision=True),)
    if change == 'bad_uuid': candidates = (replace(candidates[0], intent_id='not-an-identity'),)
    if change == 'mixed_device': candidates = (replace(candidates[0], device_id=2),)
    if change == 'snapshot_naive': snapshot = replace(snapshot, started_at=snapshot.started_at.replace(tzinfo=None))
    if change == 'snapshot_set': snapshot = replace(snapshot, present_ips=set())
    if change == 'snapshot_bool': snapshot = replace(snapshot, device_id=True)
    if change == 'profile_bool': kwargs['addition_device_ids'] = frozenset({True})
    if change == 'revision_float': kwargs['managed_revision'] = 1.0
    before = dump(dispatch.store)
    with pytest.raises(ValueError): admit(dispatch, snapshot, candidates, **kwargs)
    assert dump(dispatch.store) == before


@pytest.mark.parametrize('failure', ['clock', 'lease'])
def test_late_admission_expiry_rolls_back_every_member(bulk, dispatch, monkeypatch, failure):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    original = dispatch.store._insert_event

    def slow(*args):
        result = original(*args)
        bulk[1][0] += timedelta(seconds=121 if failure == 'clock' else 136)
        return result

    monkeypatch.setattr(dispatch.store, '_insert_event', slow)
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict): admit(dispatch, snapshot, candidates)
    assert dump(dispatch.store) == before


def test_late_claim_expiry_rolls_back_running_transition(bulk, dispatch, journal, monkeypatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    result = admit(dispatch, snapshot, candidates)
    original = dispatch.queue._event

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        bulk[1][0] += timedelta(seconds=121)
        return result

    monkeypatch.setattr(dispatch.queue, '_event', slow)
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict): claim(dispatch)
    assert dump(dispatch.store) == before
    assert attempt(journal, result['attempts'][0]['operation_id'])['state'] == 'QUEUED'


def test_captured_running_deferral_cancels_instead_of_reclaiming(bulk, dispatch, journal, cancellation_controls):
    root, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    cancel(cancellation_controls, root)
    dispatch.queue.defer_addition(job['id'], OWNER)
    assert attempt(journal, job['id'])['state'] == 'CANCELLED'
    assert not bulk[0].policy_page()['entries'][0]['enabled']
    assert claim(dispatch) is None


def test_historical_retry_after_restart_and_pruning_never_recreates_work(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    result = admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    dispatch.queue.finish_addition(job['id'], OWNER, AdditionResult(False, None))
    bulk[1][0] += timedelta(days=400)
    dispatch.queue.prune_completed(366)
    restarted = BulkDispatch(dispatch.store, dispatch.queue)
    before = dump(dispatch.store)
    replay = admit(restarted, snapshot, candidates, owner='not-an-executor', addition_device_ids=frozenset())
    assert replay['replayed'] and replay['attempts'][0]['state'] == 'NOOP'
    assert replay['attempts'][0]['operation_id'] == result['attempts'][0]['operation_id']
    assert dump(dispatch.store) == before
    with dispatch.store._connection() as db:
        assert not db.execute('SELECT 1 FROM operation_jobs').fetchone()


def test_pair_backoff_and_retained_capacity_are_not_bypassed(bulk, dispatch, monkeypatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    job = claim(dispatch)
    dispatch.queue.finish_addition(job['id'], OWNER, AdditionResult(False, None))
    bulk[1][0] += timedelta(seconds=2)
    fresh = replace(snapshot, id=str(uuid4()), started_at=bulk[1][0], completed_at=bulk[1][0])
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict, match='backoff'): admit(dispatch, fresh, candidates)
    monkeypatch.setattr(bulk_dispatch, 'MAX_ATTEMPTS', 1)
    with pytest.raises(QueueFull): admit(dispatch, fresh, candidates)
    assert dump(dispatch.store) == before


def test_progress_reports_actual_profile_suspension_without_execution_authority(bulk, dispatch):
    root, _, _ = setup(bulk, dispatch)
    before = dump(dispatch.store)
    progress = BulkWorkPlans(dispatch.store).progress(root, 'alice', ('Operator',))
    assert progress['restoration_suspended'] is False and progress['can_execute'] is False
    assert progress['execution_available'] is False
    assert dump(dispatch.store) == before


def test_resume_barrier_is_preserved_and_not_rewritten_by_initialization(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    with dispatch.store._connection() as db:
        original = db.execute('SELECT dispatch_resume_after FROM managed_bulk_registry').fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE managed_bulk_registry SET dispatch_resume_after=?', (stamp(bulk[1][0]),))
    before = dump(dispatch.store)
    dispatch.initialize()
    assert dump(dispatch.store) == before
    with pytest.raises(QueueConflict):
        admit(dispatch, replace(snapshot, started_at=bulk[1][0] - timedelta(seconds=3)), candidates)
    with dispatch.store._connection() as db:
        assert db.execute('SELECT dispatch_resume_after FROM managed_bulk_registry').fetchone()[0] == original


def test_unknown_on_other_ip_blocks_device_without_clearing_evidence(bulk, dispatch, journal):
    _, snapshot, candidates = setup(bulk, dispatch, count=2)
    result = admit(dispatch, snapshot, candidates[:1])
    job = claim(dispatch)
    dispatch.queue.finish_addition(job['id'], OWNER, 'UNVERIFIED')
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict): admit(dispatch, snapshot, candidates[1:])
    assert dump(dispatch.store) == before
    assert attempt(journal, result['attempts'][0]['operation_id'])['state'] == 'UNVERIFIED'


def test_tampered_job_creation_time_refuses_claim_and_retention(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch)
    admit(dispatch, snapshot, candidates)
    with dispatch.store._connection() as db:
        db.execute("UPDATE operation_jobs SET requested_at='2026-10-21T11:59:00.000Z'")
    before = dump(dispatch.store)
    with pytest.raises(ManagedStateUnavailable): claim(dispatch)
    with pytest.raises(ManagedStateUnavailable): dispatch.queue.prune_completed(366)
    assert dump(dispatch.store) == before
