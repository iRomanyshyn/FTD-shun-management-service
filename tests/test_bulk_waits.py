"""Bulk cancellation/result settlement using disposable state and typed outcomes."""

import sqlite3
from datetime import timedelta
from ipaddress import IPv4Address

import pytest
from test_bulk_attempts import OWNER, attempt, running
from test_bulk_attempts import journal as attempt_fixture
from test_bulk_cancellations import cancel, seed_job
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, prepare, retire

from ftd_shun_manager import bulk_policy, bulk_waits
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_waits import BulkWaits
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy

journal = attempt_fixture
cancellation_controls = cancellation_fixture


@pytest.fixture
def waits(bulk, journal):
    policy, _ = bulk
    controls = BulkWaits(policy.store)
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    controls.initialize()
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return controls


def root_id(store):
    with store._connection() as db:
        return db.execute('SELECT id FROM managed_bulk_manifests ORDER BY rowid DESC LIMIT 1').fetchone()[0]


def status(controls, key):
    return controls.page(key, 'alice', ('Operator',))


def test_upgrade_preserves_existing_immutable_receipts_scope_hashes_and_original_replay(bulk, journal, cancellation_controls):
    policy, _ = bulk
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2')
    confirm(bulk, proposal)
    original, args = cancel(cancellation_controls, proposal['operation_id'])
    with policy.store._connection() as db:
        receipt = tuple(db.execute('SELECT * FROM managed_bulk_cancellations').fetchone())
        members = [tuple(row) for row in db.execute('SELECT * FROM managed_bulk_cancellation_members ORDER BY device_id,ip')]
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    controls = BulkWaits(policy.store)
    controls.initialize()
    with policy.store._connection() as db:
        assert tuple(db.execute('SELECT * FROM managed_bulk_cancellations').fetchone()) == receipt
        assert [tuple(row)[:9] for row in db.execute('SELECT * FROM managed_bulk_cancellation_members ORDER BY device_id,ip')] == members
    assert cancellation_controls.cancel(**args) == {**original, 'replayed': True}
    assert status(cancellation_controls, proposal['operation_id'])['result'] == original
    assert status(cancellation_controls, proposal['operation_id'])['current_counts'] == original['counts']
    before = dump(policy.store)
    controls.initialize()
    assert dump(policy.store) == before


@pytest.mark.parametrize('result,state,enabled,attention', [(AdditionResult(True, 'management'), 'RETAINED_APPLIED', True, 0),
    (AdditionResult(False, None), 'RETAINED_APPLIED', True, 0), ('FAILED', 'STOPPED_FAILED', False, 1),
    ('UNVERIFIED', 'STOPPED_UNVERIFIED', False, 1)])
def test_running_capture_settles_in_shared_result_transaction_without_interrupt_or_replay(
        bulk, journal, waits, cancellation_controls, result, state, enabled, attention):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    original, args = cancel(cancellation_controls, root)
    assert original['counts'] == {'WAITING_OUTCOME': 1} and original['changed_targets'] == 0
    assert attempt(journal, job)['state'] == 'RUNNING'
    assert not status(cancellation_controls, root)['settled']
    assert bulk[0].policy_page()['entries'][0]['enabled']
    journal[1].finish_addition(job, OWNER, result)
    current = status(cancellation_controls, root)
    assert current['settled'] and current['current_counts'] == {state: 1}
    assert current['attention_count'] == attention
    assert current['targets'][0]['initial_state'] == 'WAITING_OUTCOME' and current['targets'][0]['state'] == state
    assert current['result'] == original
    assert bool(bulk[0].policy_page()['entries'][0]['enabled']) is enabled
    before = dump(waits.store)
    bulk[1][0] += timedelta(days=1)
    assert cancellation_controls.cancel(**args) == {**original, 'replayed': True}
    assert dump(waits.store) == before
    with waits.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_wait_results').fetchone()[0] == 1
        assert db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0] == 1
    event = next(row for row in waits.store.list_events() if row['event_type'] == 'MANAGED_BULK_CANCELLATION_SETTLED')
    assert event['actor_subject'] == 'alice' and event['actor_display_name'] == 'Actual canceller'
    assert event['actor_roles'] == ['Operator'] and event['request_id'] == root


def test_exact_prewrite_deferral_settles_before_owned_queued_cancellation(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    journal[1].defer_addition(job, OWNER)
    assert attempt(journal, job)['state'] == 'CANCELLED'
    assert status(cancellation_controls, root)['current_counts'] == {'STOPPED_UNSENT': 1}
    assert not bulk[0].policy_page()['entries'][0]['enabled']
    assert journal[1].claim_addition(1, OWNER, journal[1].cutoff(), execution_enabled=True, managed_restoration_enabled=True) is None
    with waits.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_wait_results').fetchone()[0] == 1


def test_queued_owned_first_application_can_be_cancelled_after_deferral(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    journal[1].defer_addition(job, OWNER)
    assert attempt(journal, job)['state'] == 'QUEUED'
    result, _ = cancel(cancellation_controls, root)
    assert result['counts'] == {'STOPPED_UNSENT': 1}
    assert attempt(journal, job)['state'] == 'CANCELLED'
    assert not bulk[0].policy_page()['entries'][0]['enabled']


@pytest.mark.parametrize('outcome,disposition', [(AdditionResult(True, 'management'), 'RETAINED_APPLIED'),
    (AdditionResult(False, None), 'RETAINED_APPLIED'), ('FAILED', 'STOPPED_FAILED'), ('UNVERIFIED', 'STOPPED_UNVERIFIED')])
def test_already_completed_application_is_classified_from_exact_owned_evidence(
        bulk, journal, waits, cancellation_controls, outcome, disposition):
    _, job, _ = running(bulk, journal)
    journal[1].finish_addition(job, OWNER, outcome)
    result, _ = cancel(cancellation_controls, root_id(waits.store))
    assert result['counts'] == {disposition: 1}
    assert bool(bulk[0].policy_page()['entries'][0]['enabled']) == (disposition == 'RETAINED_APPLIED')
    assert attempt(journal, job)['state'] in {'VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED'}


@pytest.mark.parametrize('protected', [False, True])
def test_protection_or_prior_retirement_wins_when_waited_add_later_succeeds(bulk, journal, waits, cancellation_controls, protected):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    if protected:
        ProtectedPolicy(waits.store).change('add', IPv4Address('198.51.100.1'), 0, 'viewer', 'Actual viewer', (), managed_revision=1)
    else:
        retire(bulk)
    journal[1].finish_addition(job, OWNER, AdditionResult(True, 'management'))
    assert status(cancellation_controls, root)['current_counts'] == {'ALREADY_STOPPED': 1}
    assert not bulk[0].policy_page()['entries'][0]['enabled']
    assert attempt(journal, job)['state'] == 'VERIFIED'


def test_expired_lease_records_original_uncertainty_and_settles_wait(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    bulk[1][0] += timedelta(seconds=136)
    assert journal[1].claim_cycle('replacement-synthetic-worker', 135)
    assert attempt(journal, job)['state'] == 'UNVERIFIED'
    assert status(cancellation_controls, root)['current_counts'] == {'STOPPED_UNVERIFIED': 1}
    assert not bulk[0].policy_page()['entries'][0]['enabled']


def test_outcome_change_after_review_conflicts_without_partial_cancellation(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    review = cancellation_controls.review(root, 'alice', ('Operator',))
    journal[1].finish_addition(job, OWNER, AdditionResult(False, None))
    before = dump(waits.store)
    with pytest.raises(ManagedConflict):
        cancellation_controls.cancel(root, review['reviewed_at'], review['review_digest'], 1, 'alice', 'Actual canceller', ('Operator',))
    assert dump(waits.store) == before


@pytest.mark.parametrize('boundary', ['retire_audit', 'settle_audit'])
def test_late_settlement_failure_rolls_back_job_attempt_policy_and_receipt(bulk, journal, waits, cancellation_controls, monkeypatch, boundary):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    before = dump(waits.store)
    original = waits.store._insert_event

    def fail(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == ('MANAGED_SHUN_RETIRED' if boundary == 'retire_audit' else 'MANAGED_BULK_CANCELLATION_SETTLED'):
            raise ValueError('Synthetic late settlement audit failure')

    monkeypatch.setattr(waits.store, '_insert_event', fail)
    with pytest.raises(ValueError): journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    assert dump(waits.store) == before


def test_preservation_upgrade_failure_rolls_back_schema_and_existing_receipts(bulk, journal, cancellation_controls, monkeypatch):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    cancel(cancellation_controls, proposal['operation_id'])
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(policy.store)
    original = bulk_waits._state

    def fail(db):
        result = original(db)
        if bulk_waits.present(db): raise ValueError('Synthetic final migration check failure')
        return result

    monkeypatch.setattr(bulk_waits, '_state', fail)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): BulkWaits(policy.store).initialize(connection=db)
    assert dump(policy.store) == before


def test_settlement_and_initial_wait_records_are_immutable(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    cancel(cancellation_controls, root_id(waits.store))
    journal[1].finish_addition(job, OWNER, AdditionResult(False, None))
    before = dump(waits.store)
    with waits.store._connection() as db:
        for sql in ('DELETE FROM managed_bulk_wait_results', "UPDATE managed_bulk_wait_results SET state='SUPERSEDED'",
                    "UPDATE managed_bulk_cancellation_members SET state='RETAINED_APPLIED'"):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
    assert dump(waits.store) == before


def test_upgrade_requires_pause_quiescence_and_exact_prior_profile(bulk, journal):
    policy, _ = bulk
    before = dump(policy.store)
    with pytest.raises(ManagedConflict): BulkWaits(policy.store).initialize()
    assert dump(policy.store) == before
    with policy.store._connection() as db: db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    before = dump(policy.store)
    with pytest.raises(BulkUnavailable): BulkWaits(policy.store).initialize()
    assert dump(policy.store) == before


def test_terminal_result_without_settlement_is_held_not_pruned_or_repaired(bulk, journal, waits, cancellation_controls, monkeypatch):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    with monkeypatch.context() as old_writer:
        old_writer.setattr(bulk_waits, 'settle_result', lambda *args: None)
        journal[1].finish_addition(job, OWNER, AdditionResult(False, None))
    bulk[1][0] += timedelta(days=400)
    journal[1].prune_completed(366)
    with waits.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'NOOP'
        assert db.execute('SELECT COUNT(*) FROM operation_requests').fetchone()[0] == 1
    before = dump(waits.store)
    current = status(cancellation_controls, root)
    assert not current['settled'] and current['current_counts'] == {'WAITING_OUTCOME': 1}
    assert attempt(journal, job)['state'] == 'NOOP'
    assert dump(waits.store) == before  # GET never manufactures missing settlement.
    journal[1].finish_cycle(OWNER, 60)
    _, proposal = prepare(bulk)
    before = dump(waits.store)
    with pytest.raises(ManagedConflict, match='unsettled'): confirm(bulk, proposal)
    assert dump(waits.store) == before


def test_settled_unknown_latch_and_original_request_survive_retention(bulk, journal, waits, cancellation_controls):
    key, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    bulk[1][0] += timedelta(days=400)
    journal[1].prune_completed(366)
    assert status(cancellation_controls, root)['settled']
    with waits.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT id FROM operation_requests WHERE id=?', (key,)).fetchone()[0] == key
    assert attempt(journal, job)['state'] == 'UNVERIFIED'
    _, newer = prepare(bulk)
    before = dump(waits.store)
    with pytest.raises(ManagedConflict): confirm(bulk, newer)
    assert dump(waits.store) == before


@pytest.mark.parametrize('damage', ['job', 'request', 'roles', 'state'])
def test_bad_captured_predecessor_refuses_pruning_and_preserves_all_state(bulk, journal, waits, cancellation_controls, damage):
    key, job, _ = running(bulk, journal)
    cancel(cancellation_controls, root_id(waits.store))
    with waits.store._connection() as db:
        if damage == 'job': db.execute('DELETE FROM operation_jobs WHERE id=?', (job,))
        elif damage == 'request': db.execute('DELETE FROM operation_requests WHERE id=?', (key,))
        elif damage == 'roles': db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]'")
        else: db.execute("UPDATE operation_jobs SET state='NOOP' WHERE id=?", (job,))
    before = dump(waits.store)
    with pytest.raises(ValueError): journal[1].prune_completed(1)
    assert dump(waits.store) == before


def test_owned_completed_evidence_can_be_used_after_ordinary_job_pruning(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    journal[1].finish_addition(job, OWNER, AdditionResult(False, None))
    bulk[1][0] += timedelta(days=400)
    journal[1].prune_completed(366)
    result, _ = cancel(cancellation_controls, root_id(waits.store))
    assert result['counts'] == {'RETAINED_APPLIED': 1}
    assert bulk[0].policy_page()['entries'][0]['enabled']


def test_unowned_add_evidence_still_conflicts_with_whole_cancel_scope(bulk, journal, waits, cancellation_controls):
    running(bulk, journal)
    seed_job(waits.store)
    before = dump(waits.store)
    with pytest.raises(ManagedConflict, match='Independent'):
        cancellation_controls.review(root_id(waits.store), 'alice', ('Operator',))
    assert dump(waits.store) == before


def test_inconsistent_replacement_refuses_completion_instead_of_guessing_new_authority(bulk, journal, waits, cancellation_controls):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    retire(bulk)
    # Simulate incompatible-writer replacement while retaining the original job:
    # normal admission correctly refuses RUNNING work. Only disposable evidence
    # is constructed; settlement must not retire the replacement generation.
    with waits.store._connection() as db:
        original = db.execute('SELECT * FROM managed_shun_targets').fetchone()
        db.execute('UPDATE managed_shun_targets SET generation=generation+1')
        # This intentionally inconsistent replacement cannot be assumed valid.
    before = dump(waits.store)
    with pytest.raises(BulkUnavailable): journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    assert dump(waits.store) == before
    with waits.store._connection() as db:
        assert db.execute('SELECT generation FROM managed_shun_targets').fetchone()[0] == original['generation'] + 1


def test_valid_newer_generation_survives_original_wait_outcome(bulk, journal, waits, cancellation_controls, monkeypatch):
    _, job, _ = running(bulk, journal)
    root = root_id(waits.store)
    cancel(cancellation_controls, root)
    retire(bulk)
    _, proposal = prepare(bulk)
    # Construct coherent newer authority to exercise settlement precedence. Normal
    # admission forbids this RUNNING overlap; this disposable fixture models a
    # future compatible writer, never an enabled runtime/lab admission path.
    with monkeypatch.context() as fixture_writer:
        fixture_writer.setattr(bulk_policy, '_quiescent', lambda db: None)
        confirm(bulk, proposal)
    before = bulk[0].policy_page()['entries'][0]
    assert before['generation'] == 2 and before['enabled']
    journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    assert status(cancellation_controls, root)['current_counts'] == {'SUPERSEDED': 1}
    assert status(cancellation_controls, root)['attention_count'] == 1
    assert bulk[0].policy_page()['entries'][0] == before


def test_quiescence_does_not_treat_inconsistent_terminal_job_as_settled_attempt(bulk, journal, waits):
    _, job, _ = running(bulk, journal)
    # Incompatible-writer damage: a terminal queue row, but RUNNING journal and
    # no lease. It must not authorize migration/grants by appearing quiescent.
    with waits.store._connection() as db:
        db.execute("UPDATE operation_jobs SET state='NOOP' WHERE id=?", (job,))
        db.execute('UPDATE operation_executor SET owner=NULL,lease_until=NULL,mutations_suspended=1')
    before = dump(waits.store)
    with waits.store._connection() as db, pytest.raises(ValueError): bulk_policy._quiescent(db)
    assert dump(waits.store) == before
