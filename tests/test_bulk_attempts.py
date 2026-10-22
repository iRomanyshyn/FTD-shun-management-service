"""Synthetic pre-send evidence/shared completion only; no live dispatcher/FTD."""

import json
import sqlite3
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, prepare, retire

from ftd_shun_manager import bulk_attempts
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_attempts import BulkAttempts
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.managed_restoration import (
    ACTOR,
    CompleteSnapshot,
    attempt_for_job,
    key_reserved,
)
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

IP = IPv4Address('198.51.100.1')
OWNER = 'synthetic-bulk-result-worker'
cancellation_controls = cancellation_fixture


@pytest.fixture
def journal(bulk, cancellation_controls, monkeypatch):
    policy, clock = bulk
    queue = OperationQueue(policy.store)
    monkeypatch.setattr(OperationQueue, '_now', lambda self: clock[0])
    journal = BulkAttempts(policy.store, queue)
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    journal.initialize()
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return journal, queue


def running(bulk, journal, *, capture=True):
    """Simulate future pre-send composition, not current claim/admission support."""
    policy, clock = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    source, queue = journal
    clock[0] += timedelta(seconds=2)
    assert queue.claim_cycle(OWNER, 135)
    key, job = str(uuid4()), str(uuid4())
    snapshot = CompleteSnapshot(str(uuid4()), 1, clock[0] - timedelta(seconds=1), clock[0], frozenset())
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        target = db.execute('SELECT * FROM managed_shun_targets').fetchone()
        payload = json.dumps({'scope': 'managed_restoration', 'intent_id': target['intent_id'],
                              'generation': target['generation'], 'targets': [[1, str(IP)]]})
        db.execute("INSERT INTO operation_requests VALUES (?,?,?,'[]','trusted_policy',?,?,?,'ACTIVE')",
            (key, ACTOR, 'Managed shun policy', payload, stamp(clock[0]), stamp(clock[0] + timedelta(seconds=900))))
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,started_at,action,dispatch_kind)
            VALUES (?,1,?,'RUNNING',?,?,'ADD','ADD')""", (job, IP.packed, stamp(clock[0]), stamp(clock[0])))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job))
        if capture:
            result = source.capture_running(key, job, snapshot, OWNER, enabled=True, connection=db)
            assert result['evidence_captured'] and result['dispatch_authorized'] is False
    return key, job, snapshot


def attempt(journal, job):
    with journal[0].store._connection() as db:
        return dict(attempt_for_job(db, job))


def test_optional_constructor_init_boundaries_and_original_profile_unchanged(bulk, cancellation_controls, tmp_path):
    absent = Store(tmp_path / 'absent.db')
    BulkAttempts(absent, OperationQueue(absent))
    assert not absent.path.exists()
    policy, _ = bulk
    source = BulkAttempts(policy.store, OperationQueue(policy.store))
    before = dump(policy.store)
    with pytest.raises(QueueConflict, match='Pause'): source.initialize()
    assert dump(policy.store) == before
    assert not any('managed_bulk_attempts' in row for row in before)
    with pytest.raises(ValueError): BulkAttempts(policy.store, OperationQueue(Store(tmp_path / 'other.db')))


def test_initialization_caught_failure_rolls_back_all_ddl(bulk, cancellation_controls, monkeypatch):
    policy, _ = bulk
    source = BulkAttempts(policy.store, OperationQueue(policy.store))
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(policy.store)
    original = bulk_attempts._state

    def fail(db):
        result = original(db)
        if bulk_attempts.present(db): raise ValueError('Synthetic final schema check failure')
        return result

    monkeypatch.setattr(bulk_attempts, '_state', fail)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): source.initialize(connection=db)
    assert dump(policy.store) == before


@pytest.mark.parametrize('result,expected', [(AdditionResult(True, 'management'), 'VERIFIED'),
    (AdditionResult(False, None), 'NOOP'), ('FAILED', 'FAILED'), ('UNVERIFIED', 'UNVERIFIED')])
def test_shared_queue_results_retain_original_authority_and_honest_occurrence(bulk, journal, result, expected):
    _, job, _ = running(bulk, journal)
    original = attempt(journal, job)
    assert journal[1].finish_addition(job, OWNER, result) == expected
    current = attempt(journal, job)
    assert current['state'] == expected and current['completed_at'] is not None
    for field in ('id', 'job_id', 'intent_id', 'generation', 'authorization_request_id', 'target_revision',
                  'snapshot_id', 'snapshot_started_at', 'snapshot_at', 'requested_at'):
        assert current[field] == original[field]
    assert bool(current['occurrence_id']) == (expected == 'VERIFIED')
    assert (current['interface'] == 'management') == (expected == 'VERIFIED')
    with journal[0].store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
        assert db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0] == 1
        event = db.execute('SELECT actor_subject,actor_roles_json,details_json FROM shun_events WHERE event_type=?',
                          ('MANAGED_BULK_ATTEMPT_' + expected,)).fetchone()
        assert event['actor_subject'] == ACTOR and json.loads(event['actor_roles_json']) == []
        assert json.loads(event['details_json'])['authorization_request_id'] == original['authorization_request_id']
    assert journal[1].status()['items'][0]['requests'][0]['source'] == 'managed_shun_policy'


@pytest.mark.parametrize('protection', [False, True])
def test_inflight_success_after_retirement_or_protection_never_reenables_policy(bulk, journal, protection):
    _, job, _ = running(bulk, journal)
    policy, _ = bulk
    if protection:
        ProtectedPolicy(policy.store).change('add', IP, 0, 'viewer', 'Actual viewer', ('Viewer',), managed_revision=1)
    else:
        retire(bulk)
    assert journal[1].finish_addition(job, OWNER, AdditionResult(True, 'management')) == 'VERIFIED'
    assert not policy.policy_page()['entries'][0]['enabled']
    assert attempt(journal, job)['state'] == 'VERIFIED'


def test_exact_deferral_is_not_replayed_even_with_legacy_execution_capability(bulk, journal):
    _, job, _ = running(bulk, journal)
    queue = journal[1]
    queue.defer_addition(job, OWNER)
    assert attempt(journal, job)['state'] == 'QUEUED'
    assert queue.claim_addition(1, OWNER, queue.cutoff(), execution_enabled=True, managed_restoration_enabled=True) is None
    assert attempt(journal, job)['state'] == 'CANCELLED'
    assert not bulk[0].store.list_active_shuns()


def test_expired_lease_recovers_original_unknown_result_without_add_replay(bulk, journal):
    _, job, _ = running(bulk, journal)
    bulk[1][0] += timedelta(seconds=136)
    assert journal[1].claim_cycle('replacement-result-worker', 135)
    assert attempt(journal, job)['state'] == 'UNVERIFIED'
    assert journal[1].status()['counts'] == {'UNVERIFIED': 1}
    assert journal[1].claim_addition(1, 'replacement-result-worker', journal[1].cutoff(), execution_enabled=True,
                                  managed_restoration_enabled=True) is None
    assert attempt(journal, job)['state'] == 'UNVERIFIED'


def test_pending_unknown_retention_and_pruned_terminal_independent_evidence(bulk, journal):
    _, job, _ = running(bulk, journal)
    journal[1].finish_addition(job, OWNER, AdditionResult(True, 'management'))
    bulk[1][0] += timedelta(days=400)
    journal[1].prune_completed(366)
    with journal[0].store._connection() as db:
        assert not db.execute('SELECT 1 FROM operation_jobs').fetchone()
        assert not db.execute('SELECT 1 FROM operation_requests').fetchone()
        assert key_reserved(db, job)
    assert attempt(journal, job)['state'] == 'VERIFIED'
    restarted = BulkAttempts(Store(journal[0].store.path), OperationQueue(Store(journal[0].store.path)))
    before = dump(restarted.store)
    restarted.initialize()
    assert dump(restarted.store) == before


def test_unknown_job_and_request_survive_retention(bulk, journal):
    key, job, _ = running(bulk, journal)
    journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    bulk[1][0] += timedelta(days=400)
    journal[1].prune_completed(366)
    with journal[0].store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT id FROM operation_requests WHERE id=?', (key,)).fetchone()[0] == key
    assert attempt(journal, job)['state'] == 'UNVERIFIED'


@pytest.mark.parametrize('damage', ['missing_job', 'missing_request', 'wrong_roles', 'wrong_state'])
def test_missing_or_malformed_held_evidence_refuses_pruning_and_is_not_repaired(bulk, journal, damage):
    key, job, _ = running(bulk, journal)
    with journal[0].store._connection() as db:
        if damage == 'missing_job': db.execute('DELETE FROM operation_jobs WHERE id=?', (job,))
        elif damage == 'missing_request': db.execute('DELETE FROM operation_requests WHERE id=?', (key,))
        elif damage == 'wrong_roles': db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]' WHERE id=?", (key,))
        else: db.execute("UPDATE operation_jobs SET state='UNVERIFIED' WHERE id=?", (job,))
    before = dump(journal[0].store)
    with pytest.raises(ManagedStateUnavailable): journal[1].prune_completed(1)
    assert dump(journal[0].store) == before


@pytest.mark.parametrize('change', ['gate', 'subject', 'roles', 'source', 'link', 'device', 'stale', 'present', 'lease', 'expired', 'capacity'])
def test_capture_guards_do_not_mutate_or_admit_work(bulk, journal, monkeypatch, change):
    key, job, snapshot = running(bulk, journal, capture=False)
    source, _queue = journal
    with source.store._connection() as db:
        if change == 'subject': db.execute("UPDATE operation_requests SET actor_subject='manual-user'")
        if change == 'roles': db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]'")
        if change == 'source': db.execute("UPDATE operation_requests SET source='manual'")
        if change == 'link': db.execute('DELETE FROM operation_links')
        if change == 'device': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
        if change == 'lease': db.execute("UPDATE operation_executor SET owner='different-worker'")
        if change == 'expired': db.execute("UPDATE operation_requests SET expires_at='2026-10-21T11:00:00Z'")
    if change == 'stale': bulk[1][0] += timedelta(seconds=121)
    if change == 'present': snapshot = CompleteSnapshot(snapshot.id, 1, snapshot.started_at, snapshot.completed_at, frozenset({IP}))
    if change == 'capacity': monkeypatch.setattr(bulk_attempts, 'MAX_ATTEMPTS', 0)
    before = dump(source.store)
    with source.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises((ValueError, PermissionError)):
            source.capture_running(key, job, snapshot, OWNER, enabled=change != 'gate', connection=db)
    assert dump(source.store) == before


def test_terminal_and_identity_are_immutable_and_recapture_cannot_rearm(bulk, journal):
    key, job, snapshot = running(bulk, journal)
    source = journal[0]
    with source.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(QueueConflict): source.capture_running(key, job, snapshot, OWNER, enabled=True, connection=db)
    journal[1].finish_addition(job, OWNER, 'UNVERIFIED')
    before = dump(source.store)
    with source.store._connection() as db:
        for sql in ('DELETE FROM managed_bulk_attempts', "UPDATE managed_bulk_attempts SET state='RUNNING',completed_at=NULL",
                    'UPDATE managed_bulk_attempts SET target_revision=99'):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
    assert dump(source.store) == before


@pytest.mark.parametrize('boundary', ['capture', 'result'])
def test_late_audit_failure_rolls_back_journal_and_shared_result_transaction(bulk, journal, monkeypatch, boundary):
    key, job, snapshot = running(bulk, journal, capture=boundary != 'capture')
    source = journal[0]
    before = dump(source.store)
    original = source.store._insert_event

    def fail(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == ('MANAGED_BULK_ATTEMPT_RUNNING' if boundary == 'capture' else 'MANAGED_BULK_ATTEMPT_VERIFIED'):
            raise ValueError('Synthetic late bulk evidence audit failure')

    monkeypatch.setattr(source.store, '_insert_event', fail)
    if boundary == 'capture':
        with source.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with pytest.raises(ValueError): source.capture_running(key, job, snapshot, OWNER, enabled=True, connection=db)
    else:
        with pytest.raises(ValueError): journal[1].finish_addition(job, OWNER, AdditionResult(True, 'management'))
    assert dump(source.store) == before


def test_initialization_requires_existing_cancellation_controls_and_never_creates_them(bulk):
    policy, _ = bulk
    source = BulkAttempts(policy.store, OperationQueue(policy.store))
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(policy.store)
    with pytest.raises(BulkUnavailable): source.initialize()
    assert dump(policy.store) == before


def test_partial_journal_is_unknown_and_cannot_be_repaired_by_init_or_policy_read(bulk, journal):
    source = journal[0]
    with source.store._connection() as db:
        db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    before = dump(source.store)
    with pytest.raises(BulkUnavailable): source.initialize()
    with pytest.raises(BulkUnavailable): bulk[0].policy_page()
    assert not ProtectedPolicy(source.store).snapshot()['managed_policy_available']
    assert dump(source.store) == before


@pytest.mark.parametrize('damage', ['other_uncertain_job', 'earlier_success', 'forged_scope', 'terminal_history', 'nonboolean'])
def test_capture_cannot_adopt_uncertain_or_terminal_history_or_coerce_authority(bulk, journal, damage):
    key, job, snapshot = running(bulk, journal, capture=False)
    source = journal[0]
    with source.store._connection() as db:
        if damage in {'other_uncertain_job', 'earlier_success'}:
            db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,completed_at,action)
                VALUES (?,1,?,?,'2026-10-21T12:00:00Z','2026-10-21T12:00:02.000Z','ADD')""",
                (str(uuid4()), IP.packed, 'UNVERIFIED' if damage == 'other_uncertain_job' else 'VERIFIED'))
        elif damage == 'forged_scope': db.execute("UPDATE operation_requests SET payload_json='{}'")
        elif damage == 'terminal_history': db.execute("UPDATE operation_jobs SET state='VERIFIED' WHERE id=?", (job,))
    before = dump(source.store)
    with source.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError):
            source.capture_running(key, job, snapshot, OWNER, enabled=1 if damage == 'nonboolean' else True, connection=db)
    assert dump(source.store) == before


def test_existing_policy_key_cannot_gain_attempt_identity(bulk, journal):
    key, job, snapshot = running(bulk, journal, capture=False)
    source = journal[0]
    with source.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        root = db.execute('SELECT id FROM managed_bulk_manifests').fetchone()[0]
        db.execute('DELETE FROM operation_links WHERE request_id=?', (key,))
        db.execute('UPDATE operation_requests SET id=? WHERE id=?', (root, key))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (root, job))
    before = dump(source.store)
    with source.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(QueueConflict, match='earlier authority'):
            source.capture_running(root, job, snapshot, OWNER, enabled=True, connection=db)
    assert dump(source.store) == before


def test_running_cancellation_remains_explicitly_unavailable_and_never_interrupts_job(bulk, journal, cancellation_controls):
    _, job, _ = running(bulk, journal)
    source = journal[0]
    with source.store._connection() as db:
        root = db.execute('SELECT id FROM managed_bulk_manifests').fetchone()[0]
    before = dump(source.store)
    with pytest.raises(ValueError, match='settlement'):
        cancellation_controls.review(root, 'alice', ('Operator',))
    assert attempt(journal, job)['state'] == 'RUNNING'
    assert dump(source.store) == before


def test_root_bound_pages_have_current_permission_and_survive_terminal_queue_pruning(bulk, journal):
    _, job, _ = running(bulk, journal)
    source, queue = journal
    with source.store._connection() as db:
        root = db.execute('SELECT id FROM managed_bulk_manifests').fetchone()[0]
    before = dump(source.store)
    page = source.page(root, 'alice', ('Operator',))
    assert page['counts'] == {'RUNNING': 1} and page['total'] == 1
    assert page['evidence_only'] and not page['can_execute'] and not page['execution_available']
    assert source.page(root, 'admin', ('Administrator',)) == page
    with pytest.raises(PermissionError): source.page(root, 'someone-else', ('Operator',))
    with pytest.raises(PermissionError): source.page(root, 'alice', ('Viewer',))
    for value in (0, True, 2):
        with pytest.raises(ValueError): source.page(root, 'alice', ('Operator',), page=value)
    assert dump(source.store) == before
    queue.finish_addition(job, OWNER, AdditionResult(True, 'management'))
    bulk[1][0] += timedelta(days=400)
    queue.prune_completed(366)
    before = dump(source.store)
    page = source.page(root, 'alice', ('Operator',))
    assert page['counts'] == {'VERIFIED': 1} and page['attempts'][0]['occurrence_id']
    assert dump(source.store) == before
