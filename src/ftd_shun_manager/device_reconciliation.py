"""Explicit offline quiescence decisions, never retroactive write verification."""

import argparse
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable, _atomic, _key_free, _state
from .device_recovery import DDL as RECOVERY_DDL
from .device_recovery import _digest, _review
from .device_recovery import present as recovery_present
from .extended_recovery import claims as receipt_claims
from .extended_recovery import encode, expanded, record
from .maintenance import _actor, checked_offline
from .operation_queue import stamp
from .schema import execute_schema
from .store import Store

TABLE = 'managed_bulk_reconciled_jobs'
MODE = 'offline_quiescent_managed_add'
LIMIT = 1024
DDL = """
CREATE TABLE managed_bulk_reconciled_jobs (
 job_id TEXT PRIMARY KEY REFERENCES operation_jobs(id),
 attempt_id TEXT NOT NULL UNIQUE REFERENCES managed_bulk_attempts(id),
 recovery_id TEXT NOT NULL REFERENCES managed_bulk_device_recovery(id) DEFERRABLE INITIALLY DEFERRED,
 job_digest TEXT NOT NULL CHECK(length(job_digest)=64),
 attempt_digest TEXT NOT NULL CHECK(length(attempt_digest)=64)
);
CREATE TRIGGER managed_bulk_reconciled_immutable BEFORE UPDATE ON managed_bulk_reconciled_jobs
BEGIN SELECT RAISE(ABORT,'reconciled unknown evidence is immutable'); END;
CREATE TRIGGER managed_bulk_reconciled_retained BEFORE DELETE ON managed_bulk_reconciled_jobs
BEGIN SELECT RAISE(ABORT,'reconciled unknown evidence is retained'); END;
CREATE TRIGGER managed_bulk_reconciled_bound BEFORE INSERT ON managed_bulk_reconciled_jobs
WHEN NOT EXISTS(SELECT 1 FROM operation_jobs j JOIN managed_bulk_attempts a ON a.job_id=j.id
 JOIN managed_bulk_device_executors d ON d.device_id=j.device_id
 WHERE j.id=NEW.job_id AND a.id=NEW.attempt_id AND j.action='ADD'
 AND j.state='UNVERIFIED' AND a.state='UNVERIFIED' AND d.state='ATTENTION'
 AND j.device_id=a.device_id AND j.ip=a.ip AND j.completed_at=a.completed_at)
BEGIN SELECT RAISE(ABORT,'only original held unknown managed ADDs may be reconciled'); END;
DROP TRIGGER managed_bulk_device_recovery_bound;
CREATE TRIGGER managed_bulk_device_recovery_bound BEFORE INSERT ON managed_bulk_device_recovery
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_executors d WHERE d.device_id=NEW.device_id
 AND d.state='ATTENTION' AND d.epoch=NEW.epoch AND d.owner=NEW.owner
 AND d.lease_until=NEW.lease_until AND d.updated_at=NEW.held_at)
 OR NEW.recovered_at<=NEW.held_at OR NEW.recovered_at<=NEW.lease_until
 OR NEW.actor_subject NOT LIKE 'maintenance:%'
 OR EXISTS(SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING','RECONCILED_ABSENT'))
 OR EXISTS(SELECT 1 FROM operation_jobs j WHERE j.state='UNVERIFIED'
   AND NOT EXISTS(SELECT 1 FROM managed_bulk_reconciled_jobs m
     JOIN managed_bulk_device_recovery old ON old.id=m.recovery_id WHERE m.job_id=j.id)
   AND NOT EXISTS(SELECT 1 FROM managed_bulk_reconciled_jobs m WHERE m.job_id=j.id
     AND m.recovery_id=NEW.id AND j.device_id=NEW.device_id
     AND json_extract(NEW.receipt_json,'$.mode')='offline_quiescent_managed_add'))
 OR EXISTS(SELECT 1 FROM managed_bulk_reconciled_jobs m JOIN operation_jobs j ON j.id=m.job_id
   WHERE m.recovery_id=NEW.id AND j.device_id!=NEW.device_id)
BEGIN SELECT RAISE(ABORT,'device recovery requires exact held quiescent evidence'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is not None


def unresolved(db, column):
    """Internal SQL fragment, only after the caller validates its whole profile."""
    if column not in {'id', 'job_id', 'j.id', 'a.job_id', 'operation_jobs.id', 'managed_bulk_attempts.job_id'}:
        raise ValueError('An exact internal job column is required.')
    # Qualify bare outer columns: an unqualified job_id would bind to the inner
    # table and accidentally exclude every unknown, not just this receipt's job.
    outer = {'id': 'operation_jobs.id', 'job_id': 'managed_bulk_attempts.job_id'}.get(column, column)
    return (f'NOT EXISTS(SELECT 1 FROM {TABLE} reconciled WHERE reconciled.job_id={outer})'
            if present(db) else '1')


def _row_digest(row):
    return hashlib.sha256(repr(tuple(row)).encode()).hexdigest()


def validate(db):
    if db.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0] > LIMIT:
        raise BulkUnavailable('Retained reconciliation capacity exceeded.')
    for row in db.execute(f'SELECT * FROM {TABLE}'):
        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (row['job_id'],)).fetchone()
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (row['attempt_id'],)).fetchone()
        recovery = db.execute('SELECT * FROM managed_bulk_device_recovery WHERE id=?', (row['recovery_id'],)).fetchone()
        if (job is None or attempt is None or recovery is None or job['action'] != 'ADD'
                or job['state'] != 'UNVERIFIED' or attempt['state'] != 'UNVERIFIED'
                or attempt['job_id'] != job['id'] or recovery['device_id'] != job['device_id']
                or not hmac.compare_digest(row['job_digest'], _row_digest(job))
                or not hmac.compare_digest(row['attempt_digest'], _row_digest(attempt))):
            raise BulkUnavailable('Original reconciled unknown evidence changed or is missing.')
        from .managed_restoration import validate_binding

        validate_binding(db, attempt, job)
        receipt = json.loads(recovery['receipt_json'])
        claims = [claim for claim in receipt_claims(receipt) if claim.get('job_id') == job['id']]
        if (receipt.get('mode') != MODE or len(claims) != 1 or claims[0].get('state') != 'UNVERIFIED'
                or receipt.get('operation_id') != recovery['id'] or receipt.get('epoch') != recovery['epoch']
                or receipt.get('recovered_at') != recovery['recovered_at']
                or receipt.get('actor_subject') != recovery['actor_subject']
                or receipt.get('offline_assertion') != 'api_web_agent_stopped'
                or receipt.get('original_outcomes_unchanged') is not True
                or receipt.get('policy_changed') is not False or receipt.get('jobs_retried') != 0
                or claims[0].get('action') != 'ADD'
                or claims[0].get('evidence_digest') != hashlib.sha256(repr((tuple(job), tuple(attempt))).encode()).hexdigest()
                or receipt.get('original_fence') != {
                    'device_id': recovery['device_id'], 'epoch': recovery['epoch'], 'owner': recovery['owner'],
                    'lease_until': recovery['lease_until'], 'state': 'ATTENTION', 'updated_at': recovery['held_at']}):
            raise BulkUnavailable('Reconciliation receipt does not bind the original unknown claim.')
    for recovery in db.execute("SELECT id,receipt_json FROM managed_bulk_device_recovery WHERE json_extract(receipt_json,'$.mode')=?", (MODE,)):
        receipt = json.loads(recovery['receipt_json'])
        expected = {claim['job_id'] for claim in receipt_claims(receipt) if claim.get('state') == 'UNVERIFIED'}
        actual = {row[0] for row in db.execute(f'SELECT job_id FROM {TABLE} WHERE recovery_id=?', (recovery['id'],))}
        if not expected or expected != actual:
            raise BulkUnavailable('The complete reconciled unknown scope is missing or inconsistent.')


def inspect(database, device_id, *, now=None, extended_v6=False, pending_v7=False):
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Reconciliation time must be explicit UTC.')
    path = database.resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        review = _review(db, Store(path), device_id, current, reconcile=True, extended_v6=extended_v6, pending_v7=pending_v7)
        return {**review, 'mode': MODE, 'reviewed_at': stamp(current), 'review_digest': _digest(db, extended_v6=extended_v6, pending_v7=pending_v7),
                'read_only': True, 'original_outcomes_unchanged': True}


def reconcile(db, store, device_id, key, actor, reviewed_at, review_digest, *, offline=False, now=None, extended_v6=False, pending_v7=False):
    if type(extended_v6) is not bool:
        raise ValueError('Extended v6 recovery requires a literal explicit selection.')
    if type(pending_v7) is not bool or (pending_v7 and extended_v6):
        raise ValueError('Select one literal offline recovery profile.')
    if offline is not True or not db.in_transaction:
        raise ValueError('Stop API/Web/agent and explicitly attest offline quiescence.')
    if type(device_id) is not int or not 1 <= device_id <= 65535:
        raise ValueError('Select a literal device ID.')
    _uuid(key)
    subject, current = _actor(actor), now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Reconciliation time must be explicit UTC.')
    with _atomic(db):
        if present(db):
            _state(db)
            old = db.execute('SELECT * FROM managed_bulk_device_recovery WHERE id=?', (key,)).fetchone()
            if old:
                receipt = json.loads(old['receipt_json'])
                if (old['device_id'], old['actor_subject'], old['review_digest'], receipt.get('mode')) != (device_id, subject, review_digest, MODE):
                    raise ValueError('Reconciliation key is bound to another decision.')
                if ((receipt.get('recovery_profile') == 'tracked-v6') is not extended_v6
                        or (receipt.get('recovery_profile') == 'tracked-v7-interrupted') is not pending_v7):
                    raise ValueError('Reconciliation key belongs to another profile selection.')
                return {**expanded(receipt), 'replayed': True}
        reviewed = datetime.fromisoformat(reviewed_at)
        if (reviewed.tzinfo is None or reviewed.utcoffset() != timedelta(0) or stamp(reviewed) != reviewed_at
                or not reviewed <= current <= reviewed + timedelta(minutes=5)
                or type(review_digest) is not str or len(review_digest) != 64
                or not hmac.compare_digest(_digest(db, extended_v6=extended_v6, pending_v7=pending_v7), review_digest)):
            raise ValueError('The review is expired or the database changed; inspect again.')
        review = _review(db, store, device_id, current, reconcile=True, extended_v6=extended_v6, pending_v7=pending_v7)
        _key_free(db, key)
        if not recovery_present(db):
            execute_schema(db, RECOVERY_DDL)
        if not present(db):
            execute_schema(db, DDL)
        if pending_v7 and not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_pending_offline_release'").fetchone():
            from .pending_offline import RELEASE_DDL
            execute_schema(db, RELEASE_DDL)
        unknown = [claim for claim in review['claims'] if claim['state'] == 'UNVERIFIED']
        if (db.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0] + len(unknown) > LIMIT
                or db.execute('SELECT COUNT(*) FROM managed_bulk_device_recovery').fetchone()[0] >= 4096):
            raise ValueError('Retained reconciliation capacity reached; no evidence was evicted.')
        for claim in unknown:
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (claim['job_id'],)).fetchone()
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
            db.execute(f'INSERT INTO {TABLE} VALUES (?,?,?,?,?)',
                       (job['id'], attempt['id'], key, _row_digest(job), _row_digest(attempt)))
        timestamp = stamp(current)
        receipt = {**review, 'operation_id': key, 'mode': MODE, 'actor_subject': subject, 'recovered_at': timestamp,
                   'offline_assertion': 'api_web_agent_stopped', 'replayed': False,
                   'jobs_retried': 0, 'policy_changed': False, 'original_outcomes_unchanged': True}
        stored, serialized = encode(receipt, extended_v6)
        fence = review['original_fence']
        db.execute('INSERT INTO managed_bulk_device_recovery VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (key, device_id, fence['epoch'], fence['owner'], fence['lease_until'], fence['updated_at'],
                    timestamp, subject, review_digest, serialized))
        record(db, stored)
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL,updated_at=? WHERE device_id=?",
                   (timestamp, device_id))
        store._insert_event(db, 'DEVICE_LEASE_OFFLINE_MANAGED_RECONCILIATION', device_id, None, None, subject,
                            'Offline desired-state reconciliation; old ADD outcome remains unknown', (), key, stored, timestamp)
        db.execute('UPDATE operation_executor SET revision=revision+1 WHERE id=1')
        _state(db)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline managed ADD reconciliation; original unknown outcomes are retained.')
    parser.add_argument('action', choices=('inspect', 'reconcile'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--device', type=int, required=True)
    parser.add_argument('--extended-v6', action='store_true', help='Explicit 17-64-claim tracked-v6 system ADD profile')
    parser.add_argument('--key')
    parser.add_argument('--actor')
    parser.add_argument('--reviewed-at')
    parser.add_argument('--review-digest')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--confirm-api-web-agent-stopped', action='store_true')
    args = parser.parse_args(argv)
    if not args.database.is_absolute() or (args.backup and not args.backup.is_absolute()):
        parser.error('Use explicit absolute database and backup paths.')
    try:
        if args.action == 'inspect':
            result = inspect(args.database, args.device, extended_v6=args.extended_v6)
        else:
            if not all((args.key, args.actor, args.reviewed_at, args.review_digest, args.backup,
                        args.confirm_api_web_agent_stopped)):
                parser.error('Reconciliation requires a fresh review, backup, actor/key and stopped-executor assertion.')
            result = checked_offline(args.database, args.backup, lambda db, store: reconcile(
                db, store, args.device, args.key, args.actor, args.reviewed_at, args.review_digest, offline=True, extended_v6=args.extended_v6))
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f'Reconciliation refused: {error}\n')


if __name__ == '__main__':
    main()
