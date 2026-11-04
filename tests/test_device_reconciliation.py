"""Offline desired-state decisions retain unknown jobs; no device access."""

import json
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bulk_policy import dump
from test_bulk_policy import retire as retire_policy
from test_device_leases import acquire, claim, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_attempts import reserved
from ftd_shun_manager.bulk_policy import BulkUnavailable, _key_free, _state
from ftd_shun_manager.device_reconciliation import inspect, present, reconcile, unresolved
from ftd_shun_manager.device_recovery import inspect as verified_inspect
from ftd_shun_manager.maintenance import checked_offline
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def held(bulk, leases, monkeypatch):
    grant(bulk, devices=(1,), count=2)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 2
    original = queue._event

    def event(*args, **kwargs):
        bulk[1][0] += timedelta(milliseconds=1)
        return original(*args, **kwargs)

    monkeypatch.setattr(queue, '_event', event)
    first = claim(queue)
    queue.finish_addition(first['id'], token.owner, AdditionResult(True, 'management'))
    unknown = claim(queue)
    queue.finish_addition(unknown['id'], token.owner, 'UNVERIFIED', reason='Synthetic lost response')
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    bulk[1][0] += timedelta(seconds=1)
    return token, unknown


def review(bulk):
    return inspect(bulk[0].store.path, 1, now=bulk[1][0])


def apply(bulk, reviewed, **changes):
    args = {'device_id': 1, 'key': str(uuid4()), 'actor': 'synthetic-quiescent-reconciliation',
            'reviewed_at': reviewed['reviewed_at'], 'review_digest': reviewed['review_digest'],
            'offline': True, 'now': bulk[1][0]}
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return reconcile(db, bulk[0].store, **(args | changes))


def test_review_is_readonly_and_strict_verified_recovery_still_refuses_unknown(bulk, held):
    before = dump(bulk[0].store)
    result = review(bulk)
    assert result['read_only'] and result['original_outcomes_unchanged']
    assert [row['state'] for row in result['claims']].count('UNVERIFIED') == 1
    assert dump(bulk[0].store) == before
    with bulk[0].store._connection() as db:
        assert not present(db)
    with pytest.raises(ValueError): verified_inspect(bulk[0].store.path, 1, now=bulk[1][0])


def test_reconciliation_preserves_every_original_outcome_policy_and_replay_is_historical(bulk, leases, held):
    store = bulk[0].store
    tables = ('operation_jobs', 'operation_requests', 'managed_bulk_attempts', 'managed_shun_targets',
              'managed_shun_requests', 'protected_ips', 'managed_bulk_members')
    with store._connection() as db:
        before = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in tables}
    reviewed = review(bulk)
    receipt = apply(bulk, reviewed)
    assert receipt['original_outcomes_unchanged'] and receipt['jobs_retried'] == 0
    with store._connection() as db:
        assert _state(db)
        assert before == {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in tables}
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (held[1]['id'],)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'IDLE'
        assert reserved(db, receipt['operation_id'])
        with pytest.raises(ValueError): _key_free(db, receipt['operation_id'])
    next_token, _ = acquire(leases)
    assert next_token.epoch == held[0].epoch + 1
    with pytest.raises(QueueConflict): leases.renew(held[0], 135)
    snapshot = dump(store)
    assert apply(bulk, reviewed, key=receipt['operation_id'])['replayed']
    assert dump(store) == snapshot


def test_queue_separates_reviewed_history_without_changing_original_outcomes(bulk, held):
    queue = OperationQueue(bulk[0].store)
    original = queue.status()
    assert original['counts']['UNVERIFIED'] == 1
    assert original['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 1}
    assert original['reviewed_history'] == {'total': 0, 'items': [], 'limit': 20}
    receipt = apply(bulk, review(bulk))
    before = dump(queue.store)
    status = queue.status()
    assert status['counts'] == original['counts']
    assert status['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 0}
    assert held[1]['id'] not in {item['id'] for item in status['items']}
    history = status['reviewed_history']
    assert history['total'] == 1 and history['limit'] == 20
    assert len(history['items']) == 1
    item = history['items'][0]
    assert item['id'] == held[1]['id'] and item['state'] == 'UNVERIFIED'
    assert item['reason'] == 'Synthetic lost response'
    assert item['review_id'] == receipt['operation_id'] and item['reviewed_at'] == receipt['recovered_at']
    assert dump(queue.store) == before  # GET never acknowledges or repairs.


def test_absence_after_receipt_admits_new_current_attempt_never_replays_old_job(bulk, leases, held):
    from ftd_shun_manager.bulk_discovery import BulkDiscovery
    from ftd_shun_manager.managed_restoration import CompleteSnapshot

    receipt = apply(bulk, review(bulk))
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    source = BulkDiscovery(queue.store, queue, enabled=True, addition_device_ids=frozenset({1}))
    old_time = type(bulk[1][0]).fromisoformat(receipt['recovered_at'])
    old = CompleteSnapshot(str(uuid4()), 1, old_time, old_time, frozenset())
    # Too old is never a fresh-read barrier shortcut, even if absent.
    with pytest.raises(ValueError): source.discover(old, token.owner)
    fresh = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    assert source.discover(fresh, token.owner) == 1
    new_job = claim(queue)
    assert new_job['id'] != held[1]['id'] and new_job['ip'] == held[1]['ip']
    queue.finish_addition(new_job['id'], token.owner, AdditionResult(True, 'management'))
    queue.finish_cycle(token.owner, 0)
    with queue.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (held[1]['id'],)).fetchone()[0] == 'UNVERIFIED'


@pytest.mark.parametrize('change', ['offline', 'digest', 'expiry', 'changed', 'literal'])
def test_reconciliation_refuses_missing_quiescence_stale_review_or_nonliteral_scope(bulk, held, change):
    reviewed = review(bulk)
    args = {}
    if change == 'offline': args['offline'] = False
    elif change == 'digest': args['review_digest'] = '0' * 64
    elif change == 'expiry': bulk[1][0] += timedelta(minutes=6)
    elif change == 'literal': args['device_id'] = True
    else:
        with bulk[0].store._connection() as db:
            db.execute('UPDATE operation_executor SET revision=revision+1')
    before = dump(bulk[0].store)
    with pytest.raises(ValueError): apply(bulk, reviewed, **args)
    assert dump(bulk[0].store) == before


def test_audit_failure_rolls_back_new_schema_decision_and_release(bulk, held, monkeypatch):
    reviewed, before = review(bulk), dump(bulk[0].store)
    def fail(*args, **kwargs): raise ValueError('Synthetic audit failure')
    monkeypatch.setattr(bulk[0].store, '_insert_event', fail)
    with pytest.raises(ValueError, match='audit failure'): apply(bulk, reviewed)
    assert dump(bulk[0].store) == before


@pytest.mark.parametrize('corruption', ['job', 'attempt', 'ledger', 'receipt'])
def test_original_unknown_evidence_is_immutable_and_drift_refuses_dispatch(bulk, held, corruption):
    receipt = apply(bulk, review(bulk))
    with bulk[0].store._connection() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM managed_bulk_reconciled_jobs')
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE managed_bulk_reconciled_jobs SET job_digest='bad'")
        if corruption == 'job':
            db.execute("UPDATE operation_jobs SET reason='tampered' WHERE id=?", (held[1]['id'],))
        elif corruption == 'attempt':
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_attempt_terminal'").fetchone()[0]
            db.execute('DROP TRIGGER managed_bulk_attempt_terminal')
            db.execute("UPDATE managed_bulk_attempts SET completed_at='2026-10-21T12:00:09.000Z' WHERE job_id=?", (held[1]['id'],))
            db.execute(trigger)  # Exact schema restored: value drift must fail too.
        elif corruption == 'ledger':
            db.execute('DROP TRIGGER managed_bulk_reconciled_retained')
            db.execute('DELETE FROM managed_bulk_reconciled_jobs')
        else:
            db.execute('DROP TRIGGER managed_bulk_device_recovery_immutable')
            db.execute("UPDATE managed_bulk_device_recovery SET receipt_json=? WHERE id=?", (json.dumps({'mode': 'fake'}), receipt['operation_id']))
    with bulk[0].store._connection() as db, pytest.raises(BulkUnavailable): _state(db)
    with pytest.raises(BulkUnavailable): OperationQueue(bulk[0].store).status()


def test_checked_offline_keeps_private_nonoverwriting_original_archive(bulk, held, tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    backup = private / 'before.db'
    reviewed = review(bulk)
    args = (1, str(uuid4()), 'synthetic-quiescent-reconciliation', reviewed['reviewed_at'], reviewed['review_digest'])
    result = checked_offline(bulk[0].store.path, backup,
                             lambda db, store: reconcile(db, store, *args, offline=True, now=bulk[1][0]))
    assert result['original_outcomes_unchanged'] and backup.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): checked_offline(bulk[0].store.path, backup, lambda *_: None)


def test_sql_fragments_never_accept_free_form_columns(bulk):
    with bulk[0].store._connection() as db, pytest.raises(ValueError): unresolved(db, 'id OR 1=1')


def test_reviewed_unknown_is_not_service_creation_and_current_presence_is_separate(bulk, held):
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    from ftd_shun_manager.bulk_policy_views import BulkPolicyViews
    from ftd_shun_manager.import_progress import import_progress

    receipt = apply(bulk, review(bulk))
    views = BulkPolicyViews(bulk[0].store)
    entry = next(row for row in views.page()['entries'] if row['ip'] == '198.51.100.2')
    assert entry['last_attempt_state'] == 'UNVERIFIED' and entry['attention'] is False
    assert entry['unknown_reconciled_at'] == receipt['recovered_at']
    assert entry['last_verified_application_at'] is None and entry['observed_present'] is False
    templates = Path(__file__).resolve().parents[1] / 'templates'
    environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
    html = str(environment.get_template('managed-policy-ui.html').module.policy_table([entry]))
    assert 'Unknown outcome reviewed' in html and 'Addition outcome unknown' in html
    assert 'needs attention' not in html and 'Addition verified' not in html
    with bulk[0].store._connection() as db:
        db.execute('BEGIN')
        _state(db)
        task = import_progress(db)['tasks'][0]
        assert task['counts'] == {'verified': 1, 'pending': 1}
        assert task['attention'] == 0 and task['outstanding'] == 1


@pytest.mark.parametrize('revocation', ['protection', 'retirement'])
def test_current_protection_and_retirement_still_prevent_new_add(bulk, leases, held, revocation):
    from ipaddress import IPv4Address

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    apply(bulk, review(bulk))
    if revocation == 'protection':
        ProtectedPolicy(bulk[0].store).change('add', IPv4Address('198.51.100.2'), 0,
                                            'synthetic:operator', 'Synthetic operator', ('Viewer',), managed_revision=1)
    else:
        retire_policy(bulk, pairs=[(1, IPv4Address('198.51.100.2'))])
    bulk[1][0] += timedelta(seconds=301)
    _, queue = acquire(leases)
    assert discover(bulk, queue) == 0


@pytest.mark.parametrize('damage', ['pending', 'other_owner', 'missing_claim', 'missing_terminal',
                                  'missing_diagnostic', 'wrong_actor', 'remove', 'failed'])
def test_incomplete_or_broader_original_scope_is_never_reconciled(bulk, leases, held, damage):
    with bulk[0].store._connection() as db:
        if damage == 'pending':
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), bytes.fromhex('c6336463'), bulk[1][0].isoformat()))
        elif damage.startswith('missing_'):
            name = {'missing_claim': 'SHUN_OPERATION_RUNNING', 'missing_terminal': 'SHUN_OPERATION_UNVERIFIED',
                    'missing_diagnostic': 'SHUN_ADD_FAILED'}[damage]
            db.execute("DELETE FROM shun_events WHERE event_type=? AND json_extract(details_json,'$.operation_id')=?",
                       (name, held[1]['id']))
        elif damage == 'wrong_actor':
            db.execute("UPDATE operation_requests SET actor_subject='spoofed:web' WHERE id=(SELECT id FROM managed_bulk_attempts WHERE job_id=?)", (held[1]['id'],))
        elif damage == 'remove':
            trigger = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql LIKE '%operation action is immutable%'").fetchone()
            db.execute('DROP TRIGGER ' + trigger['name'])  # Corrupt only this disposable fixture.
            db.execute("UPDATE operation_jobs SET action='REMOVE' WHERE id=?", (held[1]['id'],))
            db.execute(trigger['sql'])
        elif damage == 'failed':
            db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (held[1]['id'],))
    if damage == 'other_owner': assert leases.claim(2, str(uuid4()), 135, enabled=True)
    before = dump(bulk[0].store)
    with pytest.raises((ValueError, BulkUnavailable)): review(bulk)
    assert dump(bulk[0].store) == before


def test_previous_decision_never_excludes_or_releases_later_unknown_work(bulk, leases, held):
    apply(bulk, review(bulk))
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    new_job = claim(queue)
    queue.finish_addition(new_job['id'], token.owner, 'UNVERIFIED', reason='Synthetic distinct later unknown')
    status = queue.status()
    assert status['counts']['UNVERIFIED'] == 2
    assert status['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 1}
    assert status['reviewed_history']['total'] == 1
    assert new_job['id'] in {item['id'] for item in status['items']}
    assert held[1]['id'] not in {item['id'] for item in status['items']}
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    bulk[1][0] += timedelta(seconds=1)
    with bulk[0].store._connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='UNVERIFIED' AND " + unresolved(db, 'id')).fetchone()[0] == 1
    reviewed = review(bulk)
    assert {entry['job_id'] for entry in reviewed['claims']} == {new_job['id']}
    apply(bulk, reviewed)
    with bulk[0].store._connection() as db:
        assert _state(db) and db.execute('SELECT COUNT(*) FROM managed_bulk_reconciled_jobs').fetchone()[0] == 2


def test_future_verified_recovery_can_retain_previously_reviewed_unknown_history(bulk, leases, held):
    from ftd_shun_manager.device_recovery import recover

    apply(bulk, review(bulk))
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    bulk[1][0] += timedelta(seconds=1)
    inspected = verified_inspect(bulk[0].store.path, 1, now=bulk[1][0])
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        receipt = recover(db, bulk[0].store, 1, str(uuid4()), 'synthetic-verified-successor',
                          inspected['reviewed_at'], inspected['review_digest'], offline=True, now=bulk[1][0])
        assert receipt['jobs_retried'] == 0 and _state(db)
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (held[1]['id'],)).fetchone()[0] == 'UNVERIFIED'


def test_queue_retention_keeps_original_reviewed_unknown_job_attempt_and_request(bulk, held):
    from ftd_shun_manager.operation_queue import OperationQueue

    apply(bulk, review(bulk))
    queue = OperationQueue(bulk[0].store)
    queue._now = lambda: bulk[1][0] + timedelta(days=400)
    queue.prune_completed(366)
    with bulk[0].store._connection() as db:
        assert _state(db)
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (held[1]['id'],)).fetchone()
        assert attempt['state'] == 'UNVERIFIED'
        assert db.execute('SELECT 1 FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
        assert db.execute('SELECT 1 FROM operation_jobs WHERE id=?', (held[1]['id'],)).fetchone()
