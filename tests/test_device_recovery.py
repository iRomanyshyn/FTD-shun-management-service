"""Offline recovery on disposable verified-epoch evidence, never FTD."""

import json
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bulk_policy import dump
from test_device_leases import acquire, claim, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_attempts import reserved
from ftd_shun_manager.bulk_policy import _key_free, _state
from ftd_shun_manager.device_recovery import fresh_after_recovery, inspect, present, recover
from ftd_shun_manager.maintenance import checked_offline
from ftd_shun_manager.operation_queue import QueueConflict, stamp

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

    def later_audit(*args, **kwargs):
        bulk[1][0] += timedelta(milliseconds=1)
        return original(*args, **kwargs)

    # Real event emission happens after its job timestamp, not at the same tick.
    monkeypatch.setattr(queue, '_event', later_audit)
    for _ in range(2):
        job = claim(queue)
        queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    bulk[1][0] += timedelta(seconds=1)
    return token, queue


def apply(bulk, review, *, key=None, **changes):
    options = {'device_id': 1, 'key': key or str(uuid4()), 'actor': 'synthetic-recovery',
               'reviewed_at': review['reviewed_at'], 'review_digest': review['review_digest'],
               'offline': True, 'now': bulk[1][0]}
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return recover(db, bulk[0].store, **(options | changes))


def review(bulk):
    return inspect(bulk[0].store.path, 1, now=bulk[1][0])


def test_inspection_is_readonly_and_original_schema_stays_uninitialized(bulk, leases, held):
    before = dump(bulk[0].store)
    inspected = review(bulk)
    assert inspected['read_only'] and len(inspected['claims']) == 2
    assert inspected['original_fence']['state'] == 'ATTENTION'
    assert dump(bulk[0].store) == before
    with bulk[0].store._connection() as db:
        assert not present(db)


def test_recovery_retains_jobs_policy_original_epoch_and_requires_fresh_next_evidence(bulk, leases, held):
    store = bulk[0].store
    with store._connection() as db:
        before = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in
                  ('operation_jobs', 'operation_requests', 'managed_bulk_attempts', 'managed_shun_targets', 'protected_ips')}
    inspected = review(bulk)
    receipt = apply(bulk, inspected)
    assert receipt['original_fence']['state'] == 'ATTENTION' and not receipt['replayed']
    assert receipt['jobs_retried'] == 0 and receipt['policy_changed'] is False
    with store._connection() as db:
        assert _state(db)
        assert before == {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in before}
        fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=1').fetchone()
        assert fence['state'] == 'IDLE' and fence['epoch'] == held[0].epoch
        assert not fresh_after_recovery(db, 1, receipt['recovered_at'])
        assert fresh_after_recovery(db, 1, stamp(bulk[1][0] + timedelta(milliseconds=1)))
        assert fresh_after_recovery(db, 2, inspected['original_fence']['updated_at'])
        assert db.execute("SELECT actor_subject FROM shun_events WHERE event_type='DEVICE_LEASE_OFFLINE_VERIFIED_RECOVERY'").fetchone()[0] == 'maintenance:synthetic-recovery'
    successor = leases.claim(1, str(uuid4()), 135, enabled=True)
    assert successor.epoch == held[0].epoch + 1
    with pytest.raises(QueueConflict): leases.renew(held[0], 135)
    before = dump(store)
    assert apply(bulk, inspected, key=receipt['operation_id'])['replayed']
    assert dump(store) == before, 'Replay never releases the successor or grants work'


@pytest.mark.parametrize('change', ['offline', 'digest', 'expiry', 'changed_db', 'device'])
def test_recovery_requires_explicit_offline_fresh_exact_whole_db_review(bulk, leases, held, change):
    inspected = review(bulk)
    args = {}
    if change == 'offline': args['offline'] = False
    if change == 'digest': args['review_digest'] = '0' * 64
    if change == 'device': args['device_id'] = True
    if change == 'expiry': bulk[1][0] += timedelta(minutes=6)
    if change == 'changed_db':
        with bulk[0].store._connection() as db: db.execute('UPDATE operation_executor SET revision=revision+1')
    before = dump(bulk[0].store)
    with pytest.raises(ValueError): apply(bulk, inspected, **args)
    assert dump(bulk[0].store) == before


@pytest.mark.parametrize('missing', ['running_audit', 'terminal_audit', 'job', 'attempt', 'claim_audit', 'attention_audit'])
def test_missing_original_evidence_never_becomes_verification(bulk, leases, held, missing):
    # Corrupt only this disposable fixture, restoring the exact expected schema.
    with bulk[0].store._connection() as db:
        if missing in {'job', 'attempt'}:
            if missing == 'attempt':
                trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_attempt_retained'").fetchone()[0]
                db.execute('DROP TRIGGER managed_bulk_attempt_retained')
                db.execute('DELETE FROM managed_bulk_attempts WHERE job_id=(SELECT id FROM operation_jobs LIMIT 1)')
                db.execute(trigger)
            else:
                db.execute('PRAGMA foreign_keys=OFF')
                db.execute('DELETE FROM operation_jobs WHERE id=(SELECT id FROM operation_jobs LIMIT 1)')
        else:
            event = {'running_audit': 'SHUN_OPERATION_RUNNING', 'terminal_audit': 'SHUN_OPERATION_VERIFIED',
                     'claim_audit': 'DEVICE_LEASE_CLAIMED', 'attention_audit': 'DEVICE_LEASE_ATTENTION'}[missing]
            db.execute('DELETE FROM shun_events WHERE id=(SELECT id FROM shun_events WHERE event_type=? LIMIT 1)', (event,))
    before = dump(bulk[0].store)
    with pytest.raises((ValueError, sqlite3.Error)): review(bulk)
    assert dump(bulk[0].store) == before


def test_upgrade_audit_failure_rolls_back_ledger_and_guard_changes(bulk, leases, held, monkeypatch):
    inspected, before = review(bulk), dump(bulk[0].store)

    def fail(*_args, **_kwargs): raise ValueError('Synthetic audit failure')
    monkeypatch.setattr(bulk[0].store, '_insert_event', fail)
    with pytest.raises(ValueError, match='audit failure'): apply(bulk, inspected)
    assert dump(bulk[0].store) == before


def test_sql_guards_and_recovery_key_cannot_release_other_epochs_or_gain_authority(bulk, leases, held):
    receipt = apply(bulk, review(bulk))
    store = bulk[0].store
    with store._connection() as db:
        with pytest.raises(ValueError): _key_free(db, receipt['operation_id'])
        assert reserved(db, receipt['operation_id'])
        with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM managed_bulk_device_recovery')
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE managed_bulk_device_recovery SET actor_subject='other'")
    token = leases.claim(1, str(uuid4()), 135, enabled=True)
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    with store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")
    assert token.epoch == held[0].epoch + 1


def test_checked_offline_creates_private_backup_without_overwrite(bulk, leases, held, tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    target = directory / 'before.db'
    inspected, key = review(bulk), str(uuid4())
    args = (1, key, 'synthetic-recovery', inspected['reviewed_at'], inspected['review_digest'])
    result = checked_offline(bulk[0].store.path, target, lambda db, store: recover(db, store, *args, offline=True, now=bulk[1][0]))
    assert result['operation_id'] == key and target.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(target) as db:
        assert not present(db) and db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'ATTENTION'
    with pytest.raises(FileExistsError): checked_offline(bulk[0].store.path, target, lambda *_: None)
    with bulk[0].store._connection() as db:
        stored = json.loads(db.execute('SELECT receipt_json FROM managed_bulk_device_recovery').fetchone()[0])
        assert stored['original_fence']['owner'] == held[0].owner


@pytest.mark.parametrize('outcome', ['FAILED', 'UNVERIFIED'])
def test_failed_or_unknown_original_claim_is_not_recoverable(bulk, leases, outcome):
    grant(bulk, devices=(1,), count=1)
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, outcome, reason='Synthetic retained failure')
    bulk[1][0] += timedelta(seconds=136)
    leases.claim(1, str(uuid4()), 135, enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    before = dump(bulk[0].store)
    with pytest.raises(ValueError): review(bulk)
    assert dump(bulk[0].store) == before


@pytest.mark.parametrize('unsafe', ['pending', 'other_lease', 'wrong_action', 'wrong_time'])
def test_incomplete_scope_or_inconsistent_terminal_metadata_refuses(bulk, leases, held, unsafe):
    with bulk[0].store._connection() as db:
        if unsafe in {'wrong_action', 'wrong_time'}:
            row = db.execute("SELECT id,details_json FROM shun_events WHERE event_type='SHUN_OPERATION_VERIFIED' LIMIT 1").fetchone()
            if unsafe == 'wrong_action':
                details = json.loads(row['details_json'])
                details['action'] = 'REMOVE'
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(details), row['id']))
            else:
                db.execute("UPDATE shun_events SET timestamp='2020-01-01T00:00:00.000Z' WHERE id=?", (row['id'],))
        elif unsafe == 'pending':
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), bytes.fromhex('c6336463'), stamp(bulk[1][0])))
    if unsafe == 'other_lease':
        assert leases.claim(2, str(uuid4()), 135, enabled=True)
    before = dump(bulk[0].store)
    with pytest.raises(ValueError): review(bulk)
    assert dump(bulk[0].store) == before


def test_no_receipt_means_no_raw_sql_attention_release_and_no_new_ledger(bulk, leases, held):
    with bulk[0].store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")
    with bulk[0].store._connection() as db:
        assert not present(db)
