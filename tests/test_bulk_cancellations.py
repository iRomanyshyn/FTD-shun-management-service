"""Version-2 revocation/rolling preparation on disposable state, no FTD calls."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, no_work, prepare, retire

from ftd_shun_manager import bulk_cancellations, bulk_policy
from ftd_shun_manager.bulk_cancellations import BulkCancellations
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_work import BulkWorkPlans
from ftd_shun_manager.managed_safety import ManagedStateUnavailable, managed_state
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

IP = IPv4Address('198.51.100.1')


@pytest.fixture
def controls(bulk):
    policy, clock = bulk
    service = BulkCancellations(policy.store, clock=lambda: clock[0])
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize()
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def cancel(controls, key, *, actor='alice', roles=('Operator',), **changes):
    review = controls.review(key, actor, roles)
    args = {'key': key, 'reviewed_at': review['reviewed_at'], 'review_digest': review['review_digest'],
            'accepted_count': review['accepted_count'], 'subject': actor, 'display_name': 'Actual canceller', 'roles': roles}
    args.update(changes)
    return controls.cancel(**args), args


def seed_job(store, *, state='UNVERIFIED', action='ADD', ip=IP):
    """Retained synthetic evidence, never a runtime admission/executor shortcut."""
    key = str(uuid4())
    with store._connection() as db:
        db.execute('''INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action,dispatch_kind)
            VALUES (?,1,?,?,'2026-10-21T12:00:00Z',?,?)''', (key, ip.packed, state, action, action if state == 'RUNNING' else None))
    return key


def test_constructor_reads_and_explicit_extension_never_initialize_prerequisites(bulk, tmp_path):
    absent = Store(tmp_path / 'absent.db')
    BulkCancellations(absent)
    BulkWorkPlans(absent)
    assert not absent.path.exists()
    absent.initialize()
    OperationQueue(absent).initialize()
    before = dump(absent)
    with pytest.raises(BulkUnavailable): BulkCancellations(absent).initialize()
    assert dump(absent) == before
    ManagedShuns(absent).initialize()
    before = dump(absent)
    with pytest.raises(BulkUnavailable): BulkCancellations(absent).initialize()
    assert dump(absent) == before
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    controls = BulkCancellations(policy.store, clock=policy.clock)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict, match='Pause'): controls.initialize()
    with pytest.raises(BulkUnavailable): controls.review(proposal['operation_id'], 'alice', ('Operator',))
    assert dump(policy.store) == before
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    controls.initialize()
    before = dump(policy.store)
    controls.initialize()
    assert dump(policy.store) == before
    with policy.store._connection() as db, pytest.raises(ManagedStateUnavailable): managed_state(db)
    assert controls.page(proposal['operation_id'], 'alice', ('Operator',))['requested'] is False


def test_explicit_extension_rolls_back_inside_caught_outer_transaction(bulk, monkeypatch):
    policy, _ = bulk
    controls = BulkCancellations(policy.store)
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(policy.store)
    original = bulk_cancellations._state

    def fail(db):
        result = original(db)
        if bulk_cancellations.present(db):
            raise ValueError('Synthetic final extension validation failure')
        return result

    monkeypatch.setattr(bulk_cancellations, '_state', fail)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): controls.initialize(connection=db)
    assert dump(policy.store) == before


def test_mixed_scope_retires_only_unsent_keeps_adoption_existing_and_exclusions(bulk, controls):
    policy, _ = bulk
    _, first = prepare(bulk, '198.51.100.2', (1, 2))
    confirm(bulk, first)
    policy.store.record_observed_shun(1, IPv4Address('198.51.100.3'), 'management')
    editor = ProtectedPolicy(policy.store)
    editor.change('add', IPv4Address('198.51.100.4'), 0, 'protector', 'Protector', (), managed_revision=1)
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2\n198.51.100.3\n198.51.100.4\ninvalid', (1, 2))
    result = confirm(bulk, proposal)
    historical = policy.page(result['operation_id'], 'alice')
    outcome, args = cancel(controls, result['operation_id'])
    assert outcome['counts'] == {'STOPPED_UNSENT': 3, 'RETAINED_ADOPTED': 1, 'RETAINED_EXISTING': 2}
    assert outcome['changed_targets'] == 3 and outcome['managed_revision'] == 3
    assert outcome['device_removal_requested'] is False and outcome['device_work_admitted'] is False
    assert policy.page(result['operation_id'], 'alice') == historical
    report = controls.page(result['operation_id'], 'alice', ('Operator',))
    assert report['historical_cancellation'] and report['settled'] and len(report['targets']) == 6
    assert not report['can_execute']
    current = {(row['device_id'], row['ip']): bool(row['enabled']) for row in policy.policy_page()['entries']}
    assert current == {(1, str(IP)): False, (2, str(IP)): False, (1, '198.51.100.2'): True,
                       (2, '198.51.100.2'): True, (1, '198.51.100.3'): True, (2, '198.51.100.3'): False}
    before = dump(policy.store)
    assert controls.cancel(**args) == {**outcome, 'replayed': True}
    assert dump(policy.store) == before
    event = next(row for row in policy.store.list_events(limit=100) if row['event_type'] == 'MANAGED_BULK_IMPORT_CANCELLED')
    assert event['actor_subject'] == 'alice' and event['actor_display_name'] == 'Actual canceller'
    assert event['actor_roles'] == ['Operator'] and event['request_id'] == result['operation_id']
    no_work(policy)


def test_observation_after_grant_is_not_application_and_is_not_removed(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    policy.store.record_observed_shun(1, IP, 'management')
    result, _ = cancel(controls, proposal['operation_id'])
    assert result['counts'] == {'STOPPED_UNSENT': 1}
    assert len(policy.store.list_active_shuns()) == 1
    no_work(policy)


def test_stopped_and_superseded_generations_are_not_changed(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2\n198.51.100.3')
    confirm(bulk, proposal)
    retire(bulk, [(1, IP), (1, IPv4Address('198.51.100.2'))])
    _, newer = prepare(bulk, '198.51.100.2')
    confirm(bulk, newer)
    before = policy.policy_page()['entries'][:2]
    result, _ = cancel(controls, proposal['operation_id'])
    assert result['counts'] == {'ALREADY_STOPPED': 1, 'SUPERSEDED': 1, 'STOPPED_UNSENT': 1}
    assert policy.policy_page()['entries'][:2] == before
    no_work(policy)


def test_retry_after_expiry_pruning_restart_and_new_grant_never_retires_new_generation(bulk, controls):
    policy, clock = bulk
    saved, proposal = prepare(bulk)
    confirm(bulk, proposal)
    result, args = cancel(controls, proposal['operation_id'])
    _, newer = prepare(bulk)
    confirm(bulk, newer)
    clock[0] += timedelta(days=1)
    assert policy.preparations.prune_expired() == 2
    restarted = BulkCancellations(Store(policy.store.path), clock=policy.clock)
    before = dump(policy.store)
    assert restarted.cancel(**args) == {**result, 'replayed': True}
    assert confirm(bulk, proposal)['replayed']
    assert restarted.page(proposal['operation_id'], 'alice', ('Operator',))['result'] == result
    assert restarted.review(proposal['operation_id'], 'alice', ('Operator',))['already_requested']
    assert dump(policy.store) == before
    assert policy.policy_page()['entries'][0]['generation'] == 2
    assert policy.policy_page()['entries'][0]['enabled']
    assert saved['plan_id'] != newer['preparation_id']
    no_work(policy)


@pytest.mark.parametrize('roles', [(), ('Viewer',), ('Operator',), ('Administrator',)])
def test_current_role_and_original_owner_or_administrator_required(bulk, controls, roles):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    before = dump(policy.store)
    if roles != ('Administrator',):
        with pytest.raises(PermissionError): controls.review(proposal['operation_id'], 'someone-else', roles)
        assert dump(policy.store) == before
    else:
        result, _ = cancel(controls, proposal['operation_id'], actor='actual-admin', roles=roles)
        assert result['changed_targets'] == 1
        row = next(row for row in policy.store.list_events() if row['event_type'] == 'MANAGED_BULK_IMPORT_CANCELLED')
        assert row['actor_subject'] == 'actual-admin' and row['actor_roles'] == ['Administrator']


@pytest.mark.parametrize('change', ['expired', 'backwards', 'revision', 'protection', 'job', 'digest', 'count'])
def test_changed_review_has_no_partial_effect(bulk, controls, change):
    policy, clock = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    review = controls.review(proposal['operation_id'], 'alice', ('Operator',))
    if change == 'expired': clock[0] += timedelta(minutes=5)
    if change == 'backwards': clock[0] -= timedelta(seconds=1)
    if change == 'revision':
        _, other = prepare(bulk, '198.51.100.2')
        confirm(bulk, other)
    if change == 'protection':
        ProtectedPolicy(policy.store).change('add', IPv4Address('198.51.100.2'), 0, 'p', 'P', (), managed_revision=1)
    if change == 'job': seed_job(policy.store)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict):
        controls.cancel(proposal['operation_id'], review['reviewed_at'], '0' * 64 if change == 'digest' else review['review_digest'],
            2 if change == 'count' else review['accepted_count'], 'alice', 'Actual canceller', ('Operator',))
    assert dump(policy.store) == before


@pytest.mark.parametrize('state', ['QUEUED', 'RUNNING', 'VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'CANCELLED'])
def test_unattributable_add_evidence_is_never_called_unsent_or_applied(bulk, controls, state):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    seed_job(policy.store, state=state)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict, match='settlement'): controls.review(proposal['operation_id'], 'alice', ('Operator',))
    assert dump(policy.store) == before
    assert BulkWorkPlans(policy.store).progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'EVIDENCE_REVIEW': 1}


@pytest.mark.parametrize('boundary', ['retirement', 'root_audit', 'late_clock'])
def test_late_failure_rolls_back_even_if_outer_caller_catches_and_commits(bulk, controls, monkeypatch, boundary):
    policy, clock = bulk
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2')
    confirm(bulk, proposal)
    review = controls.review(proposal['operation_id'], 'alice', ('Operator',))
    before = dump(policy.store)
    original = policy.store._insert_event

    def event(db, name, *args, **kwargs):
        original(db, name, *args, **kwargs)
        if boundary == 'retirement' and name == 'MANAGED_SHUN_RETIRED':
            raise ValueError('Synthetic retirement event failure')
        if name == 'MANAGED_BULK_IMPORT_CANCELLED':
            if boundary == 'late_clock': clock[0] += timedelta(minutes=5)
            else: raise ValueError('Synthetic final event failure')

    monkeypatch.setattr(controls.store, '_insert_event', event)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError):
            controls.cancel(proposal['operation_id'], review['reviewed_at'], review['review_digest'],
                review['accepted_count'], 'alice', 'Actual canceller', ('Operator',), connection=db)
    assert dump(policy.store) == before


def test_parallel_original_decision_commits_once_and_retries_are_historical(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    review = controls.review(proposal['operation_id'], 'alice', ('Operator',))

    def run(_):
        return controls.cancel(proposal['operation_id'], review['reviewed_at'], review['review_digest'],
            review['accepted_count'], 'alice', 'Actual canceller', ('Operator',))

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(run, range(3)))
    assert sum(not item['replayed'] for item in outcomes) == 1
    assert policy.policy_page()['revision'] == 2
    assert len([row for row in policy.store.list_events() if row['event_type'] == 'MANAGED_BULK_IMPORT_CANCELLED']) == 1
    no_work(policy)


def test_retirement_does_not_need_ledger_space_or_new_admission_capability(bulk, controls, monkeypatch):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    monkeypatch.setattr(bulk_policy, 'MAX_REQUESTS', 1)
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    assert cancel(controls, proposal['operation_id'])[0]['changed_targets'] == 1
    no_work(policy)


def test_immutable_sealed_cancel_scope_and_partial_extension_fail_closed(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    cancel(controls, proposal['operation_id'])
    with policy.store._connection() as db:
        for sql in ('DELETE FROM managed_bulk_cancellations', 'UPDATE managed_bulk_cancellations SET accepted_count=1',
                    'DELETE FROM managed_bulk_cancellation_members', "UPDATE managed_bulk_cancellation_members SET state='SUPERSEDED'",
                    'INSERT INTO managed_bulk_cancellation_members SELECT * FROM managed_bulk_cancellation_members'):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
        db.execute('DROP TRIGGER managed_bulk_cancellation_member_sealed')
    before = dump(policy.store)
    with pytest.raises(BulkUnavailable): policy.policy_page()
    with pytest.raises(BulkUnavailable): controls.initialize()
    editor = ProtectedPolicy(policy.store)
    assert not editor.snapshot()['managed_policy_available']
    editor.change('add', IP, 0, 'protector', 'Protector', ())
    with pytest.raises(ManagedStateUnavailable): editor.change('delete', IP, 1, 'protector', 'Protector', ())
    assert dump(policy.store) != before  # Only durable strengthening, never a repair.


def test_retained_disposition_corruption_fails_full_receipt_check(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    cancel(controls, proposal['operation_id'])
    with policy.store._connection() as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_cancellation_member_immutable'").fetchone()[0]
        db.execute('DROP TRIGGER managed_bulk_cancellation_member_immutable')
        db.execute("UPDATE managed_bulk_cancellation_members SET state='SUPERSEDED'")
        db.execute(sql)
    before = dump(policy.store)
    with pytest.raises(BulkUnavailable): controls.page(proposal['operation_id'], 'alice', ('Operator',))
    assert dump(policy.store) == before


def test_progress_and_keyset_portions_are_bounded_read_only_and_skip_cancelled_targets(bulk, controls):
    policy, _ = bulk
    text = '\n'.join(str(IPv4Address(0xC6120000 + index)) for index in range(251))
    _, proposal = prepare(bulk, text, (1, 2))
    confirm(bulk, proposal)
    plans = BulkWorkPlans(policy.store)
    before = dump(policy.store)
    progress = plans.progress(proposal['operation_id'], 'alice', ('Operator',))
    assert progress['counts'] == {'MISSING_CANDIDATE': 502}
    assert not progress['can_execute'] and not progress['execution_available']
    assert progress['observations_are_execution_receipts'] is False
    after, candidates = None, []
    while True:
        portion = plans.portion(proposal['operation_id'], 'alice', ('Operator',), after=after, revision=1, protected_revision=0)
        assert len(portion['candidates']) <= 16 and not portion['device_work_admitted']
        candidates.extend((row['device_id'], IPv4Address(row['ip'])) for row in portion['candidates'])
        after = portion['next_after']
        if after is None: break
    assert len(candidates) == len(set(candidates)) == 502 and candidates == sorted(candidates)
    assert dump(policy.store) == before
    result, _ = cancel(controls, proposal['operation_id'])
    assert result['changed_targets'] == 502
    assert plans.portion(proposal['operation_id'], 'alice', ('Operator',))['candidates'] == []
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'STOPPED': 502}
    assert len(controls.page(proposal['operation_id'], 'alice', ('Operator',), page=6)['targets']) == 2
    no_work(policy)


def test_retained_adoption_is_an_observation_not_execution_and_may_need_restoration(bulk, controls):
    policy, _ = bulk
    policy.store.record_observed_shun(1, IP, 'management')
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    plans = BulkWorkPlans(policy.store)
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'OBSERVED_PRESENT': 1}
    assert cancel(controls, proposal['operation_id'])[0]['counts'] == {'RETAINED_ADOPTED': 1}
    policy.store.reconcile_snapshot(1, [])
    portion = plans.portion(proposal['operation_id'], 'alice', ('Operator',))
    assert len(portion['candidates']) == 1 and portion['candidates'][0]['generation'] == 1
    no_work(policy)


@pytest.mark.parametrize('options', [{'limit': 17}, {'limit': True}, {'after': (True, IP)}, {'after': (1, str(IP))},
    {'after': [1, IP]}, {'after': (1, IP)}, {'revision': True}, {'protected_revision': False}])
def test_work_cursor_and_bounds_reject_coercion_without_writes(bulk, controls, options):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    before = dump(policy.store)
    with pytest.raises(ValueError): BulkWorkPlans(policy.store).portion(proposal['operation_id'], 'alice', ('Operator',), **options)
    assert dump(policy.store) == before


def test_work_revision_changes_and_independent_pending_jobs_hold_candidates(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    plans = BulkWorkPlans(policy.store)
    seed_job(policy.store, state='QUEUED', action='REMOVE')
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'WORK_PENDING': 1}
    assert plans.portion(proposal['operation_id'], 'alice', ('Operator',))['candidates'] == []
    with pytest.raises(ManagedConflict): controls.review(proposal['operation_id'], 'alice', ('Operator',))
    retire(bulk)
    with pytest.raises(ManagedConflict): plans.portion(proposal['operation_id'], 'alice', ('Operator',), revision=1)


@pytest.mark.parametrize('change', ['subject', 'display_name', 'roles', 'reviewed_at', 'review_digest', 'accepted_count'])
def test_old_decision_cannot_be_reinterpreted_with_changed_replay_payload(bulk, controls, change):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    _, args = cancel(controls, proposal['operation_id'])
    changed = {'subject': 'other-admin', 'display_name': 'Different display', 'roles': ('Administrator',),
        'reviewed_at': '2026-10-21T12:00:01.000Z', 'review_digest': '0' * 64, 'accepted_count': 2}
    args[change] = changed[change]
    if change == 'subject': args['roles'] = ('Administrator',)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict): controls.cancel(**args)
    assert dump(policy.store) == before


@pytest.mark.parametrize('changes', [{'accepted_count': True}, {'accepted_count': 100001}, {'reviewed_at': '2026-10-21T12:00:00'},
    {'reviewed_at': '2026-10-21T12:00:00+00:00'}, {'review_digest': 'A' * 64}, {'roles': ('Operator', {})},
    {'roles': ['Operator']}, {'display_name': 'bad\nactor'}])
def test_strict_cancellation_fields_and_current_actor_fail_without_writes(bulk, controls, changes):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    review = controls.review(proposal['operation_id'], 'alice', ('Operator',))
    args = {'key': proposal['operation_id'], 'reviewed_at': review['reviewed_at'], 'review_digest': review['review_digest'],
            'accepted_count': review['accepted_count'], 'subject': 'alice', 'display_name': 'Actual canceller', 'roles': ('Operator',)}
    before = dump(policy.store)
    with pytest.raises(ValueError): controls.cancel(**(args | changes))
    assert dump(policy.store) == before


def test_stopped_only_cancel_does_not_churn_managed_revision(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    retire(bulk)
    outcome, _ = cancel(controls, proposal['operation_id'])
    assert outcome['changed_targets'] == 0 and outcome['managed_revision'] == policy.policy_page()['revision'] == 2
    assert outcome['counts'] == {'ALREADY_STOPPED': 1}


def test_protection_after_cancel_retires_retained_adoption_and_never_resumes_it(bulk, controls):
    policy, _ = bulk
    policy.store.record_observed_shun(1, IP, 'management')
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    outcome, _ = cancel(controls, proposal['operation_id'])
    assert outcome['counts'] == {'RETAINED_ADOPTED': 1}
    editor = ProtectedPolicy(policy.store)
    editor.change('add', IP, 0, 'viewer', 'Actual viewer', ('Viewer',), managed_revision=1)
    editor.change('delete', IP, 1, 'viewer', 'Actual viewer', ('Viewer',), managed_revision=2)
    assert not policy.policy_page()['entries'][0]['enabled']
    assert controls.page(proposal['operation_id'], 'alice', ('Operator',))['result'] == outcome
    assert BulkWorkPlans(policy.store).progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'STOPPED': 1}
    no_work(policy)


def test_portion_holds_disabled_devices_protection_and_unknown_evidence(bulk, controls):
    policy, _ = bulk
    _, proposal = prepare(bulk, devices=(1, 2))
    confirm(bulk, proposal)
    with policy.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id=2')
    plans = BulkWorkPlans(policy.store)
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'MISSING_CANDIDATE': 1, 'DEVICE_DISABLED': 1}
    assert len(plans.portion(proposal['operation_id'], 'alice', ('Operator',))['candidates']) == 1
    # Synthetic enabled barrier without retirement, as during deferred repair;
    # planning must not bypass that barrier or mutate authority itself.
    with policy.store._connection() as db:
        db.execute("INSERT INTO protected_ips VALUES (?,'Synthetic barrier','',1,'2026-10-21T12:00:00Z')", (IP.packed,))
        db.execute('UPDATE protected_policy SET revision=revision+1')
    before = dump(policy.store)
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'PROTECTED': 2}
    assert plans.portion(proposal['operation_id'], 'alice', ('Operator',))['candidates'] == []
    with pytest.raises(ManagedConflict):
        plans.portion(proposal['operation_id'], 'alice', ('Operator',), revision=1, protected_revision=0)
    assert dump(policy.store) == before


def test_maximum_100000_pair_cancel_and_late_pages_keep_zero_executable_backlog(bulk, controls):
    from ftd_shun_manager.bulk_attempts import BulkAttempts
    from ftd_shun_manager.bulk_waits import BulkWaits

    policy, clock = bulk
    text = '\n'.join(str(IPv4Address(0xC6120000 + index)) for index in range(10000))
    _, proposal = prepare(bulk, text, tuple(range(1, 11)))
    confirm(bulk, proposal)
    plans = BulkWorkPlans(policy.store)
    portion = plans.portion(proposal['operation_id'], 'alice', ('Operator',))
    assert len(portion['candidates']) == 16 and portion['counts'] == {'MISSING_CANDIDATE': 100000}
    result, args = cancel(controls, proposal['operation_id'])
    assert result['changed_targets'] == 100000 and result['counts'] == {'STOPPED_UNSENT': 100000}
    clock[0] += timedelta(minutes=10)
    assert policy.preparations.prune_expired() == 1
    restarted = BulkCancellations(Store(policy.store.path), clock=policy.clock)
    assert len(restarted.page(proposal['operation_id'], 'alice', ('Operator',), page=1000)['targets']) == 100
    assert restarted.cancel(**args)['replayed']
    assert confirm(bulk, proposal)['replayed']
    assert plans.progress(proposal['operation_id'], 'alice', ('Operator',))['counts'] == {'STOPPED': 100000}
    with policy.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_cancellation_members').fetchone()[0] == 100000
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    BulkAttempts(policy.store, OperationQueue(policy.store)).initialize()
    BulkWaits(policy.store).initialize()
    assert restarted.cancel(**args) == {**result, 'replayed': True}
    upgraded = restarted.page(proposal['operation_id'], 'alice', ('Operator',), page=1000)
    assert len(upgraded['targets']) == 100 and upgraded['current_counts'] == result['counts']
    assert upgraded['result'] == result
    no_work(policy)
