"""Real SQLite offline classification/reconciliation, never Cisco or authority replay."""

import json
import sqlite3
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_policy import dump
from test_pending_restart import bulk as bulk_fixture
from test_pending_restart import cancellation_controls as cancellation_fixture
from test_pending_restart import crash as crash_fixture
from test_pending_restart import dispatch as dispatch_fixture
from test_pending_restart import journal as journal_fixture
from test_pending_restart import leases as leases_fixture
from test_pending_restart import ledger as ledger_fixture
from test_pending_restart import waits as waits_fixture

from ftd_shun_manager import device_reconciliation, pending_offline
from ftd_shun_manager.bulk_policy import _state
from ftd_shun_manager.maintenance import checked_offline
from ftd_shun_manager.managed_addition_controls import ManagedAdditionControls
from ftd_shun_manager.pending_execution import PendingExecution

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
crash = crash_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture


@pytest.fixture
def execution(ledger, leases):
    service = PendingExecution(ledger.store, leases.queue)
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize_empty()
    with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    ManagedAdditionControls(service.store, clock=leases.queue._now).initialize()
    return service


def apply(bulk, reviewed, **changes):
    options = {'device_id': 1, 'key': str(uuid4()), 'actor': 'synthetic-pending-offline',
               'reviewed_at': reviewed['reviewed_at'], 'review_digest': reviewed['review_digest'],
               'offline': True, 'now': bulk[1][0]}
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return pending_offline.classify(db, bulk[0].store, **(options | changes))


def reconcile(bulk, reviewed, **changes):
    options = {'device_id': 1, 'key': str(uuid4()), 'actor': 'synthetic-pending-offline',
               'reviewed_at': reviewed['reviewed_at'], 'review_digest': reviewed['review_digest'],
               'offline': True, 'pending_v7': True, 'now': bulk[1][0]}
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return device_reconciliation.reconcile(db, bulk[0].store, **(options | changes))


def test_classification_is_explicit_retains_unknowns_and_does_not_release(bulk, crash):
    store = bulk[0].store
    before = dump(store)
    reviewed = pending_offline.inspect(store.path, 1, now=bulk[1][0])
    assert reviewed['running_to_unknown'] == 2 and not reviewed['releases_fence']
    assert dump(store) == before
    result = apply(bulk, reviewed)
    assert result['classified_unknown'] == 2 and result['jobs_retried'] == 0 and not result['releases_fence']
    with store._connection() as db:
        assert _state(db)
        assert [r[0] for r in db.execute('SELECT state FROM operation_jobs')] == ['UNVERIFIED'] * 2
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'ATTENTION'
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
    unchanged = dump(store)
    assert apply(bulk, reviewed, key=result['operation_id'])['replayed']
    assert dump(store) == unchanged


def test_separate_fresh_reconciliation_preserves_original_unknowns_and_policy(bulk, crash):
    store = bulk[0].store
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    bulk[1][0] += timedelta(seconds=1)
    with store._connection() as db:
        tables = ('operation_jobs', 'operation_requests', 'managed_bulk_attempts', 'managed_shun_targets', 'managed_shun_requests')
        before = {t: list(map(tuple, db.execute('SELECT * FROM '+t))) for t in tables}
    reviewed = device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True)
    assert reviewed['recovery_profile'] == pending_offline.PROFILE
    result = reconcile(bulk, reviewed)
    assert result['jobs_retried'] == 0 and result['original_outcomes_unchanged']
    with store._connection() as db:
        assert _state(db)
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'IDLE'
        assert before == {t: list(map(tuple, db.execute('SELECT * FROM '+t))) for t in tables}
        stored = json.loads(db.execute('SELECT receipt_json FROM managed_bulk_device_recovery').fetchone()[0])
        assert stored['claims_format'] == pending_offline.FORMAT and len(stored['compact_claims']) == 2
    after = dump(store)
    assert reconcile(bulk, reviewed, key=result['operation_id'])['replayed']
    assert dump(store) == after


@pytest.mark.parametrize('change', ['offline', 'expiry', 'digest', 'changed', 'literal'])
def test_classification_refuses_missing_quiescence_or_changed_review(bulk, crash, change):
    store = bulk[0].store
    reviewed = pending_offline.inspect(store.path, 1, now=bulk[1][0])
    options = {}
    if change == 'offline': options['offline'] = False
    elif change == 'expiry': bulk[1][0] += timedelta(minutes=6)
    elif change == 'digest': options['review_digest'] = '0'*64
    elif change == 'literal': options['device_id'] = True
    else:
        with store._connection() as db: db.execute('UPDATE protected_policy SET revision=revision+1')
    before = dump(store)
    with pytest.raises(ValueError): apply(bulk, reviewed, **options)
    assert dump(store) == before


@pytest.mark.parametrize('count', [1, 16, 17, 64])
def test_whole_visit_with_verified_prefix_retains_proof_and_fresh_read_barrier(bulk, leases, execution, count):
    from test_batch_queue import acknowledge, result
    from test_device_leases import acquire, grant
    from test_pending_confirmation import read

    from ftd_shun_manager.bulk_discovery import BulkDiscovery
    from ftd_shun_manager.deferred_worker import DeferredDeviceOperationQueue
    from ftd_shun_manager.device_recovery import fresh_after_recovery

    grant(bulk, (1,), count=count)
    token, ordinary = acquire(leases)
    source = BulkDiscovery(execution.store, ordinary, enabled=True, addition_device_ids=frozenset({1}), admission_limit=64, check_limit=256)
    assert source.discover(read(bulk), token.owner) == min(16, count)
    queue = DeferredDeviceOperationQueue(execution.store, token)
    remaining, sequence = count, 1
    while remaining > 16:
        prefix = [acknowledge(queue, n) for n in range(sequence, sequence+16)]
        sequence += 16
        queue.finish_verified_group(token.owner, result(prefix), sequence)
        sequence += 1
        remaining -= 16
        assert source.discover(read(bulk), token.owner) == min(16, remaining)
    # No END or even a final checkpoint: the session may have been interrupted.
    for n in range(sequence, sequence+remaining): acknowledge(queue, n)
    bulk[1][0] += timedelta(seconds=136)
    path = execution.store.path
    classified = apply(bulk, pending_offline.inspect(path, 1, now=bulk[1][0]))
    assert classified['classified_unknown'] == remaining
    bulk[1][0] += timedelta(seconds=1)
    reviewed = device_reconciliation.inspect(path, 1, now=bulk[1][0], pending_v7=True)
    assert len(reviewed['claims']) == count
    recovered = reconcile(bulk, reviewed)
    with execution.store._connection() as db:
        assert _state(db)
        assert not fresh_after_recovery(db, 1, recovered['recovered_at'])
        assert fresh_after_recovery(db, 1, (bulk[1][0]+timedelta(seconds=1)).isoformat(timespec='milliseconds').replace('+00:00','Z'))
        events = [tuple(r) for r in db.execute("SELECT * FROM shun_events WHERE event_type NOT IN ('DEV_PROFILE_INITIALIZED')")]
        jobs = [tuple(r) for r in db.execute('SELECT * FROM operation_jobs')]
    bulk[1][0] += timedelta(days=367)
    queue.prune_completed(366)
    execution.store.prune_expired_history(366, reference_time=bulk[1][0])
    with execution.store._connection() as db:
        assert _state(db)
        assert jobs == [tuple(r) for r in db.execute('SELECT * FROM operation_jobs')]
        retained = {r['id'] for r in db.execute('SELECT * FROM shun_events')}
        assert all(row[0] in retained for row in events if row[2] in ('SHUN_OPERATION_RUNNING','SHUN_OPERATION_UNVERIFIED'))


def test_checked_offline_backups_and_fk_integrity_cover_both_phases(bulk, crash, tmp_path):
    private = tmp_path/'private';private.mkdir(mode=0o700)
    store = bulk[0].store
    reviewed = pending_offline.inspect(store.path, 1, now=bulk[1][0])
    key = str(uuid4())
    result = checked_offline(store.path, private/'before-classification.db', lambda db, current: pending_offline.classify(
        db, current, 1, key, 'synthetic-pending-offline', reviewed['reviewed_at'], reviewed['review_digest'], offline=True, now=bulk[1][0]))
    assert result['classified_unknown'] == 2
    bulk[1][0] += timedelta(seconds=1)
    reviewed = device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True)
    result = checked_offline(store.path, private/'before-reconciliation.db', lambda db, current: device_reconciliation.reconcile(
        db, current, 1, str(uuid4()), 'synthetic-pending-offline', reviewed['reviewed_at'], reviewed['review_digest'],
        offline=True, now=bulk[1][0], pending_v7=True))
    assert result['original_outcomes_unchanged']
    with store._connection() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_current_policy_continues_only_after_new_complete_read(bulk, leases, crash):
    from test_device_leases import acquire, claim
    from test_pending_confirmation import read

    from ftd_shun_manager.bulk_discovery import BulkDiscovery
    from ftd_shun_manager.operation_queue import OperationQueue

    store = bulk[0].store
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    bulk[1][0] += timedelta(seconds=1)
    receipt = reconcile(bulk, device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True))
    status = OperationQueue(store).status()
    assert status['counts']['UNVERIFIED'] == 2 and status['attention_counts']['UNVERIFIED'] == 0
    assert status['reviewed_history']['total'] == 2
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    source = BulkDiscovery(store, queue, enabled=True, addition_device_ids=frozenset({1}))
    old = read(bulk, started_at=type(bulk[1][0]).fromisoformat(receipt['recovered_at']))
    with pytest.raises(ValueError): source.discover(old, token.owner)
    assert source.discover(read(bulk), token.owner) == 2
    new = claim(queue)
    assert new['id'] not in {job['id'] for job in crash[1]}


def test_late_failure_rolls_back_schema_outcomes_and_audit(bulk, crash, monkeypatch):
    store = bulk[0].store
    reviewed = pending_offline.inspect(store.path, 1, now=bulk[1][0])
    original = store._insert_event
    def fail(db, event, *args, **kwargs):
        if event == 'DEVICE_LEASE_OFFLINE_PENDING_CLASSIFIED': raise sqlite3.OperationalError('Synthetic storage failure')
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(store, '_insert_event', fail)
    before = dump(store)
    with pytest.raises(sqlite3.OperationalError): apply(bulk, reviewed)
    assert dump(store) == before


def test_reconciliation_late_failure_rolls_back_markers_and_release(bulk, crash, monkeypatch):
    store = bulk[0].store
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    bulk[1][0] += timedelta(seconds=1)
    reviewed = device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True)
    original = store._insert_event
    def fail(db, event, *args, **kwargs):
        if event == 'DEVICE_LEASE_OFFLINE_MANAGED_RECONCILIATION': raise sqlite3.OperationalError('Synthetic final audit failure')
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(store, '_insert_event', fail)
    before = dump(store)
    with pytest.raises(sqlite3.OperationalError): reconcile(bulk, reviewed)
    assert dump(store) == before


@pytest.mark.parametrize('fault', ['missing_claim', 'foreign_version', 'foreign_unknown', 'unexpired'])
def test_incomplete_foreign_or_live_scope_refuses_before_any_write(bulk, crash, fault):
    store = bulk[0].store
    with store._connection() as db:
        if fault == 'missing_claim':
            db.execute("DELETE FROM shun_events WHERE id=(SELECT id FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING' LIMIT 1)")
        elif fault == 'foreign_version':
            db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.batch_session_version',6) WHERE event_type='SHUN_OPERATION_RUNNING'")
        elif fault == 'unexpired':
            bulk[1][0] -= timedelta(seconds=100)
        else:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,started_at,completed_at,action,dispatch_kind) VALUES (?,1,x'C63364FA','UNVERIFIED',?,?,?,'REMOVE','REMOVE')",
                       (str(uuid4()), *([bulk[1][0].isoformat()]*3)))
    before = dump(store)
    with pytest.raises(ValueError): pending_offline.inspect(store.path, 1, now=bulk[1][0])
    assert dump(store) == before


@pytest.mark.parametrize('state', ['EXPIRED', 'CANCELLED'])
def test_classification_does_not_need_to_renew_expired_or_cancelled_requests(bulk, crash, state):
    store = bulk[0].store
    with store._connection() as db: db.execute('UPDATE operation_requests SET state=?', (state,))
    result = apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    assert result['classified_unknown'] == 2
    bulk[1][0] += timedelta(seconds=1)
    reconcile(bulk, device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True))
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_requests WHERE state='ACTIVE'").fetchone()[0] == 0


def test_default_legacy_reconciliation_and_old_profile_remain_refused(bulk, crash):
    from ftd_shun_manager.bulk_policy import _expected, _objects

    store = bulk[0].store
    with store._connection() as db: old_objects = _objects(db)
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    bulk[1][0] += timedelta(seconds=1)
    before = dump(store)
    with pytest.raises(ValueError): device_reconciliation.inspect(store.path, 1, now=bulk[1][0])
    with store._connection() as db:
        assert _objects(db) != old_objects
        assert _objects(db) != _expected(True, True, True, True, True, False, False, False, False, False, True, True)
    assert dump(store) == before


def test_previous_writer_with_controls_refuses_the_new_offline_profile(bulk, crash, monkeypatch):
    from ftd_shun_manager import bulk_policy
    from ftd_shun_manager.bulk_policy import BulkUnavailable

    store = bulk[0].store
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    original = bulk_policy._expected
    monkeypatch.setattr(bulk_policy, '_expected', lambda *args: original(*args[:-1]))
    with store._connection() as db, pytest.raises(BulkUnavailable): _state(db)


def test_recovery_guidance_is_readonly_and_never_advertises_the_old_host_helper(bulk, crash):
    from ftd_shun_manager.queue_recovery import report

    store = bulk[0].store
    before = dump(store)
    first = report(store, now=bulk[1][0])['devices'][0]
    assert first['pending_v7_phase'] == 'classify' and not first['lab_assistance'] and not first['eligible']
    assert dump(store) == before
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    bulk[1][0] += timedelta(seconds=1)
    before = dump(store)
    second = report(store, now=bulk[1][0])['devices'][0]
    assert second['pending_v7_phase'] == 'reconcile' and not second['lab_assistance']
    assert dump(store) == before


def test_recorded_failure_after_last_lease_renewal_remains_unknown(bulk, crash):
    queue, jobs, _, _ = crash
    bulk[1][0] -= timedelta(seconds=130)
    for job in jobs:
        queue.finish_addition(job['id'], queue.token.owner, 'UNVERIFIED', reason='Synthetic lost stage response')
    bulk[1][0] += timedelta(seconds=136)
    store = bulk[0].store
    with store._connection() as db: before = [tuple(r) for r in db.execute('SELECT * FROM operation_jobs')]
    classified = apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    assert classified['classified_unknown'] == 0
    bulk[1][0] += timedelta(seconds=1)
    reconcile(bulk, device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True))
    with store._connection() as db: assert before == [tuple(r) for r in db.execute('SELECT * FROM operation_jobs')]


def test_unknown_attention_without_classification_offers_the_first_offline_phase(bulk, leases, crash):
    from ftd_shun_manager.queue_recovery import report

    queue, jobs, _, _ = crash
    bulk[1][0] -= timedelta(seconds=130)
    for job in jobs: queue.finish_addition(job['id'], queue.token.owner, 'UNVERIFIED', reason='Synthetic lost reply')
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    bulk[1][0] += timedelta(seconds=1)
    before = dump(queue.store)
    device = report(queue.store, now=bulk[1][0])['devices'][0]
    assert device['state'] == 'ATTENTION' and device['pending_v7_phase'] == 'classify'
    assert not device['lab_assistance'] and dump(queue.store) == before
    classified = apply(bulk, pending_offline.inspect(queue.store.path, 1, now=bulk[1][0]))
    assert classified['classified_unknown'] == 0


def test_interruption_before_final_stage_ack_needs_no_invented_completion(bulk, leases, execution):
    from test_batch_queue import acknowledge
    from test_device_leases import acquire, claim, discover, grant

    from ftd_shun_manager.deferred_worker import DeferredDeviceOperationQueue

    grant(bulk, (1,), count=2)
    token, ordinary = acquire(leases)
    assert discover(bulk, ordinary) == 2
    queue = DeferredDeviceOperationQueue(execution.store, token)
    acknowledge(queue, 1)
    assert claim(queue) is not None  # No stage reply or ACK persisted for this claim.
    bulk[1][0] += timedelta(seconds=136)
    classified = apply(bulk, pending_offline.inspect(queue.store.path, 1, now=bulk[1][0]))
    assert classified['classified_unknown'] == 2
    bulk[1][0] += timedelta(seconds=1)
    reconcile(bulk, device_reconciliation.inspect(queue.store.path, 1, now=bulk[1][0], pending_v7=True))
    with queue.store._connection() as db:
        assert _state(db)
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'").fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0


@pytest.mark.parametrize('policy', ['pause_imports', 'pause_restoration', 'protect', 'retire'])
def test_recovery_preserves_current_pauses_protection_and_retirement(bulk, leases, crash, policy):
    from test_bulk_policy import retire
    from test_bulk_protection import protect
    from test_deferred_pauses import change
    from test_device_leases import acquire
    from test_pending_confirmation import read

    from ftd_shun_manager.bulk_discovery import BulkDiscovery
    from ftd_shun_manager.protected_policy import ProtectedPolicy

    store = bulk[0].store
    apply(bulk, pending_offline.inspect(store.path, 1, now=bulk[1][0]))
    if policy == 'retire':
        retire(bulk, [(1, IPv4Address('198.51.100.1')), (1, IPv4Address('198.51.100.2'))])
    elif policy == 'protect':
        editor = ProtectedPolicy(store, initialize_queue=False)
        for n in (1, 2): protect(editor, ip=IPv4Address(f'198.51.100.{n}'))
    else:
        if policy == 'pause_restoration':
            store.reconcile_snapshot(1, [(IPv4Address(f'198.51.100.{n}'), 'outside') for n in (1, 2)])
            store.reconcile_snapshot(1, [])
        controls = ManagedAdditionControls(store, clock=leases.queue._now)
        change(controls, 'imports' if policy == 'pause_imports' else 'restoration', 'PAUSE')
    bulk[1][0] += timedelta(seconds=1)
    receipt = reconcile(bulk, device_reconciliation.inspect(store.path, 1, now=bulk[1][0], pending_v7=True))
    assert not receipt['policy_changed']
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    assert BulkDiscovery(store, queue, enabled=True, addition_device_ids=frozenset({1})).discover(read(bulk), token.owner) == 0
