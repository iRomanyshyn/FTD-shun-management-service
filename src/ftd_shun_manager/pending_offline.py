"""Explicit offline classification of interrupted v7 ADDs; never settlement proof."""

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
from .device_leases import DeviceLease, DeviceOperationQueue
from .device_recovery import _digest
from .maintenance import _actor, checked_offline
from .operation_queue import stamp
from .schema import execute_schema

TABLE = 'managed_bulk_pending_classifications'
MARKERS = 'managed_bulk_pending_offline_recovery'
PROFILE = 'tracked-v7-interrupted'
FORMAT = 'compact-v7-interrupted'
LIMIT = 4096
DDL = """
CREATE TABLE managed_bulk_pending_classifications (
 id TEXT PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id),
 epoch INTEGER NOT NULL CHECK(epoch>=1), owner TEXT NOT NULL,
 held_at TEXT NOT NULL, receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json) AND length(receipt_json)<=65536),
 UNIQUE(device_id,epoch)
);
CREATE TRIGGER managed_bulk_pending_classifications_immutable BEFORE UPDATE ON managed_bulk_pending_classifications
BEGIN SELECT RAISE(ABORT,'offline classification is immutable'); END;
CREATE TRIGGER managed_bulk_pending_classifications_retained BEFORE DELETE ON managed_bulk_pending_classifications
BEGIN SELECT RAISE(ABORT,'offline classification evidence is retained'); END;
CREATE TRIGGER managed_bulk_pending_classifications_bound BEFORE INSERT ON managed_bulk_pending_classifications
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_executors d WHERE d.device_id=NEW.device_id
 AND d.epoch=NEW.epoch AND d.owner=NEW.owner AND d.state='ATTENTION' AND d.updated_at=NEW.held_at)
BEGIN SELECT RAISE(ABORT,'classification requires its exact held original epoch'); END;
CREATE TABLE managed_bulk_pending_offline_recovery (
 recovery_id TEXT PRIMARY KEY REFERENCES managed_bulk_device_recovery(id),
 classification_id TEXT NOT NULL UNIQUE REFERENCES managed_bulk_pending_classifications(id),
 claim_count INTEGER NOT NULL CHECK(claim_count BETWEEN 1 AND 64),
 claims_digest TEXT NOT NULL CHECK(length(claims_digest)=64)
);
CREATE TRIGGER managed_bulk_pending_offline_recovery_immutable BEFORE UPDATE ON managed_bulk_pending_offline_recovery
BEGIN SELECT RAISE(ABORT,'pending recovery evidence is immutable'); END;
CREATE TRIGGER managed_bulk_pending_offline_recovery_retained BEFORE DELETE ON managed_bulk_pending_offline_recovery
BEGIN SELECT RAISE(ABORT,'pending recovery evidence is retained'); END;
"""
RELEASE_DDL = """
CREATE TRIGGER managed_bulk_pending_offline_recovery_bound BEFORE INSERT ON managed_bulk_pending_offline_recovery
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_device_executors d
 ON d.device_id=r.device_id JOIN managed_bulk_pending_classifications c ON c.id=NEW.classification_id
 WHERE r.id=NEW.recovery_id AND d.state='ATTENTION' AND d.epoch=r.epoch AND d.owner=r.owner
 AND d.updated_at=r.held_at AND c.device_id=r.device_id AND c.epoch=r.epoch AND c.owner=r.owner
 AND c.held_at=r.held_at AND json_extract(r.receipt_json,'$.classification_id')=c.id
 AND json_extract(r.receipt_json,'$.recovery_profile')='tracked-v7-interrupted'
 AND json_array_length(r.receipt_json,'$.compact_claims')=NEW.claim_count)
BEGIN SELECT RAISE(ABORT,'pending recovery requires its original offline classification'); END;
CREATE TRIGGER managed_bulk_pending_offline_release BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION' AND NEW.state='IDLE' AND NOT EXISTS(
 SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_pending_offline_recovery m
 ON m.recovery_id=r.id JOIN managed_bulk_pending_classifications c ON c.id=m.classification_id
 WHERE r.device_id=OLD.device_id AND r.epoch=OLD.epoch AND r.owner=OLD.owner
 AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
 AND c.device_id=r.device_id AND c.epoch=r.epoch AND c.owner=r.owner AND c.held_at=r.held_at)
BEGIN SELECT RAISE(ABORT,'pending fence release requires its complete classified receipt'); END;
"""


def present(db):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is not None


def row_digest(row):
    return hashlib.sha256(repr(tuple(row)).encode()).hexdigest()


def _time(now):
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Offline review time must be explicit UTC.')
    return current


def _scope(db, device_id, current):
    from .bulk_ordered_waits import held_count
    from .bulk_waits import validate_pending
    from .device_reconciliation import unresolved
    from .managed_restoration import validate_binding
    from .pending_execution import PendingExecution

    if type(device_id) is not int or not 1 <= device_id <= 65535:
        raise ValueError('Select one literal device ID.')
    PendingExecution._profile(db)
    fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()
    timestamp = stamp(current)
    if (fence is None or fence['state'] not in ('LEASED', 'ATTENTION')
            or not fence['lease_until'] < timestamp or fence['updated_at'] >= timestamp
            or (fence['state'] == 'ATTENTION' and fence['lease_until'] >= fence['updated_at'])):
        raise ValueError('An expired original v7 visit is required.')
    if (db.execute("SELECT 1 FROM managed_bulk_device_executors WHERE device_id!=? AND state!='IDLE'", (device_id,)).fetchone()
            or db.execute("SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','AWAITING_CONFIRMATION','RECONCILED_ABSENT')").fetchone()
            or db.execute("SELECT 1 FROM operation_jobs WHERE device_id!=? AND state IN ('RUNNING','UNVERIFIED') AND "
                          + unresolved(db, 'id'), (device_id,)).fetchone()
            or validate_pending(db) or held_count(db)):
        raise ValueError('Other pending, unknown or captured cleanup work prevents classification.')
    opening = db.execute("""SELECT * FROM shun_events WHERE device_id=? AND event_type='DEVICE_LEASE_CLAIMED'
        AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?""",
                         (device_id, fence['owner'], fence['epoch'])).fetchall()
    claims = db.execute("""SELECT * FROM shun_events WHERE device_id=? AND event_type='SHUN_OPERATION_RUNNING'
        AND json_extract(details_json,'$.device_executor.owner')=?
        AND json_extract(details_json,'$.device_executor.epoch')=? ORDER BY timestamp,id LIMIT 65""",
                       (device_id, fence['owner'], fence['epoch'])).fetchall()
    if len(opening) != 1 or not 1 <= len(claims) <= 64:
        raise ValueError('The complete original bounded claim audit is required.')
    jobs, seen = [], set()
    for claim in claims:
        details = json.loads(claim['details_json'])
        key = details.get('operation_id')
        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (key,)).fetchone()
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (key,)).fetchone()
        if (key in seen or job is None or attempt is None or job['device_id'] != device_id
                or claim['ip'] != job['ip'] or job['action'] != 'ADD' or job['dispatch_kind'] != 'ADD'
                or job['state'] not in ('RUNNING', 'VERIFIED', 'NOOP', 'UNVERIFIED')
                or attempt['state'] != job['state'] or attempt['completed_at'] != job['completed_at']
                or type(details.get('batch_session_version')) is not int or details['batch_session_version'] != 7
                or details.get('source') != 'managed_shun_policy'
                or not opening[0]['timestamp'] <= job['started_at'] <= claim['timestamp'] <= timestamp):
            raise ValueError('Only the complete original managed v7 ADD scope can be classified.')
        _uuid(details.get('addition_group'))
        validate_binding(db, attempt, job)
        terminal = db.execute("""SELECT * FROM shun_events WHERE device_id=?
            AND event_type=? AND json_extract(details_json,'$.operation_id')=?
            AND json_extract(details_json,'$.device_executor.owner')=?
            AND json_extract(details_json,'$.device_executor.epoch')=?""",
            (device_id, 'SHUN_OPERATION_'+job['state'], key, fence['owner'], fence['epoch'])).fetchall()
        if job['state'] == 'RUNNING':
            request = db.execute('SELECT state FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
            if request is None or request['state'] not in ('ACTIVE', 'EXPIRED', 'CANCELLED'):
                raise ValueError('An interrupted ADD requires its original retained request.')
        elif (len(terminal) != 1 or job['completed_at'] is None
                or not claim['timestamp'] <= job['completed_at'] <= terminal[0]['timestamp'] <=
                    (fence['updated_at'] if fence['state'] == 'ATTENTION' else timestamp)):
            raise ValueError('Known outcomes require their original complete terminal audit.')
        seen.add(key)
        jobs.append(job)
    window = {r[0] for r in db.execute('SELECT id FROM operation_jobs WHERE device_id=? AND started_at>=?',
                                      (device_id, opening[0]['timestamp']))}
    unknown = {r[0] for r in db.execute("SELECT id FROM operation_jobs WHERE device_id=? AND state IN ('RUNNING','UNVERIFIED') AND "
                                       + unresolved(db, 'id'), (device_id,))}
    if (window != seen or not unknown or not unknown <= seen
            or sum(job['state'] == 'RUNNING' for job in jobs) > 16):
        raise ValueError('The complete unfinished visit must match the original claims.')
    if present(db) and db.execute(f'SELECT 1 FROM {TABLE} WHERE device_id=? AND epoch=?', (device_id, fence['epoch'])).fetchone():
        raise ValueError('This visit is already classified; inspect reconciliation instead.')
    return dict(fence), jobs


def inspect(database, device_id, *, now=None):
    path, current = database.resolve(strict=True), _time(now)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        fence, jobs = _scope(db, device_id, current)
        return {'profile': PROFILE, 'device_id': device_id, 'original_fence': fence,
                'job_ids': [job['id'] for job in jobs], 'running_to_unknown': sum(j['state'] == 'RUNNING' for j in jobs),
                'existing_unknown': sum(j['state'] == 'UNVERIFIED' for j in jobs),
                'reviewed_at': stamp(current), 'review_digest': _digest(db), 'read_only': True,
                'device_work_admitted': False, 'releases_fence': False}


def classify(db, store, device_id, key, actor, reviewed_at, review_digest, *, offline=False, now=None):
    if offline is not True or not db.in_transaction:
        raise ValueError('Stop API/Web/agent and supply a caller-owned offline transaction.')
    if type(device_id) is not int or not 1 <= device_id <= 65535:
        raise ValueError('Select one literal device ID.')
    _uuid(key)
    subject, current = _actor(actor), _time(now)
    with _atomic(db):
        _state(db)
        if present(db):
            old = db.execute(f'SELECT * FROM {TABLE} WHERE id=?', (key,)).fetchone()
            if old:
                receipt = json.loads(old['receipt_json'])
                if (old['device_id'], receipt['actor_subject'], receipt['source_review_digest']) != (device_id, subject, review_digest):
                    raise ValueError('Classification key belongs to another decision.')
                return {**receipt, 'replayed': True}
        reviewed = datetime.fromisoformat(reviewed_at)
        if (stamp(reviewed) != reviewed_at or reviewed.tzinfo is None or reviewed.utcoffset() != timedelta(0)
                or not reviewed <= current <= reviewed + timedelta(minutes=5)
                or type(review_digest) is not str or not hmac.compare_digest(_digest(db), review_digest)):
            raise ValueError('Review expired or database changed; inspect again.')
        fence, jobs = _scope(db, device_id, current)
        _key_free(db, key)
        if not present(db):
            execute_schema(db, DDL)
        if db.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0] >= LIMIT:
            raise ValueError('Offline classification capacity reached; no evidence evicted.')
        token = DeviceLease(device_id, fence['owner'], fence['epoch'])
        queue = DeviceOperationQueue(store, token)
        queue._now = lambda: current
        interrupted = [job for job in jobs if job['state'] == 'RUNNING']
        for job in interrupted:
            reason = 'Offline interrupted v7 visit; original ADD outcome remains unknown'
            request = db.execute('''SELECT r.* FROM operation_requests r JOIN managed_bulk_attempts a ON a.id=r.id
                WHERE a.job_id=?''', (job['id'],)).fetchone()
            queue._finish(db, job, 'UNVERIFIED', reason)
            if request['state'] == 'CANCELLED':
                # Terminal audit for the original revoked request, not renewed
                # execution authority. Ordinary finishing omits cancelled links.
                queue._event(db, 'SHUN_OPERATION_UNVERIFIED', request, job, {'reason': reason, 'offline_classification': key})
                queue._event(db, 'SHUN_ADD_FAILED', request, job,
                             {'reason': reason, 'outcome': 'UNVERIFIED', 'offline_classification': key})
        if fence['state'] == 'LEASED':
            db.execute("UPDATE managed_bulk_device_executors SET state='ATTENTION',updated_at=? WHERE device_id=?",
                       (stamp(current), device_id))
            queue.leases._event(db, 'ATTENTION', token, stamp(current))
        held = db.execute('SELECT updated_at FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()[0]
        bindings = []
        for job in jobs:
            after = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
            bindings.append([job['id'], row_digest(after), row_digest(attempt)])
        receipt = {'profile': PROFILE, 'operation_id': key, 'actor_subject': subject, 'device_id': device_id,
                   'epoch': token.epoch, 'original_fence': fence, 'held_at': held, 'classified_at': stamp(current),
                   'source_review_digest': review_digest, 'claims': bindings, 'classified_unknown': len(interrupted),
                   'terminal_outcomes_unchanged': True, 'releases_fence': False, 'jobs_retried': 0, 'replayed': False}
        db.execute(f'INSERT INTO {TABLE} VALUES (?,?,?,?,?,?)',
                   (key, device_id, token.epoch, token.owner, held, json.dumps(receipt, sort_keys=True)))
        store._insert_event(db, 'DEVICE_LEASE_OFFLINE_PENDING_CLASSIFIED', device_id, None, None, subject,
                            'Offline interrupted ADD classification; outcome remains unknown', (), key, receipt, stamp(current))
        queue._bump(db)
        _state(db)
        return receipt


def classification(db, fence):
    if not present(db):
        raise ValueError('Explicit offline v7 classification is required first.')
    row = db.execute(f'SELECT * FROM {TABLE} WHERE device_id=? AND epoch=? AND owner=? AND held_at=?',
                     (fence['device_id'], fence['epoch'], fence['owner'], fence['updated_at'])).fetchone()
    if row is None:
        raise ValueError('The exact original epoch has no offline classification.')
    return row


def validate(db):
    if db.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0] > LIMIT:
        raise BulkUnavailable('Offline v7 classification bound exceeded.')
    for row in db.execute(f'SELECT * FROM {TABLE}'):
        receipt = json.loads(row['receipt_json'])
        if type(receipt) is not dict:
            raise BulkUnavailable('Invalid offline v7 classification record.')
        bindings, fence = receipt.get('claims'), receipt.get('original_fence')
        if (receipt.get('profile') != PROFILE or receipt.get('operation_id') != row['id']
                or receipt.get('device_id') != row['device_id'] or receipt.get('epoch') != row['epoch']
                or type(receipt.get('device_id')) is not int or type(receipt.get('epoch')) is not int
                or receipt.get('held_at') != row['held_at'] or type(bindings) is not list or not 1 <= len(bindings) <= 64
                or any(type(b) is not list or len(b) != 3 or any(type(v) is not str for v in b) for b in bindings)
                or len({b[0] for b in bindings}) != len(bindings)
                or type(fence) is not dict or fence.get('device_id') != row['device_id']
                or fence.get('epoch') != row['epoch'] or fence.get('owner') != row['owner']
                or fence.get('state') not in ('LEASED', 'ATTENTION')
                or receipt.get('terminal_outcomes_unchanged') is not True or receipt.get('releases_fence') is not False
                or type(receipt.get('classified_unknown')) is not int or not 0 <= receipt['classified_unknown'] <= 16
                or type(receipt.get('actor_subject')) is not str or not receipt['actor_subject'].startswith('maintenance:')
                or receipt.get('jobs_retried') != 0 or receipt.get('replayed') is not False):
            raise BulkUnavailable('Invalid offline v7 classification binding.')
        try:
            _uuid(row['id']); _uuid(row['owner'])
            for key in ('held_at', 'classified_at'):
                if stamp(_time(datetime.fromisoformat(receipt[key]))) != receipt[key]:
                    raise ValueError('Noncanonical time')
            if not fence['lease_until'] < row['held_at'] <= receipt['classified_at']:
                raise ValueError('Invalid classification order')
            digest = receipt['source_review_digest']
            if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid original review digest')
        except (ValueError, TypeError, KeyError) as error:
            raise BulkUnavailable('Invalid offline v7 identity/time/review evidence.') from error
        audit = db.execute("SELECT * FROM shun_events WHERE request_id=? AND event_type='DEVICE_LEASE_OFFLINE_PENDING_CLASSIFIED'", (row['id'],)).fetchall()
        if (len(audit) != 1 or audit[0]['actor_subject'] != receipt['actor_subject']
                or audit[0]['device_id'] != row['device_id'] or audit[0]['timestamp'] != receipt['classified_at']
                or json.loads(audit[0]['details_json']) != receipt):
            raise BulkUnavailable('Original offline classification audit is missing or changed.')
        for key, job_hash, attempt_hash in bindings:
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (key,)).fetchone()
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (key,)).fetchone()
            if (job is None or attempt is None or job['device_id'] != row['device_id']
                    or job['state'] not in ('VERIFIED', 'NOOP', 'UNVERIFIED')
                    or row_digest(job) != job_hash or row_digest(attempt) != attempt_hash):
                raise BulkUnavailable('Retained classified v7 outcome changed or disappeared.')


def validate_recoveries(db, declared):
    from .extended_recovery import _digest as claims_digest
    from .extended_recovery import claims

    markers = list(db.execute(f'SELECT * FROM {MARKERS}')) if present(db) else []
    if {row['recovery_id'] for row in markers} != set(declared):
        raise BulkUnavailable('Interrupted-v7 recovery markers differ from their complete receipts.')
    for marker in markers:
        parent = declared[marker['recovery_id']]
        receipt = json.loads(parent['receipt_json'])
        classified = db.execute(f'SELECT * FROM {TABLE} WHERE id=?', (marker['classification_id'],)).fetchone()
        if (classified is None or len(claims(receipt)) != marker['claim_count']
                or claims_digest(receipt['compact_claims']) != marker['claims_digest']
                or receipt.get('classification_id') != classified['id']
                or receipt.get('operation_id') != parent['id'] or receipt.get('epoch') != parent['epoch']
                or receipt.get('device_id') != parent['device_id']
                or receipt.get('recovered_at') != parent['recovered_at']
                or receipt.get('actor_subject') != parent['actor_subject']
                or receipt.get('offline_assertion') != 'api_web_agent_stopped'
                or receipt.get('jobs_retried') != 0 or receipt.get('policy_changed') is not False
                or receipt.get('original_outcomes_unchanged') is not True
                or (classified['device_id'], classified['epoch'], classified['owner'], classified['held_at']) !=
                    (parent['device_id'], parent['epoch'], parent['owner'], parent['held_at'])
                or {c['job_id'] for c in claims(receipt)} != {c[0] for c in json.loads(classified['receipt_json'])['claims']}):
            raise BulkUnavailable('Interrupted-v7 receipt does not bind its exact offline classification.')


def main(argv=None):
    from . import device_reconciliation

    parser = argparse.ArgumentParser(description='Offline interrupted v7 ADDs: classify unknown, then separately review/reconcile.')
    parser.add_argument('action', choices=('inspect', 'classify', 'inspect-reconciliation', 'reconcile'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--device', type=int, required=True)
    for field in ('key', 'actor', 'reviewed-at', 'review-digest'):
        parser.add_argument('--' + field)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--confirm-api-web-agent-stopped', action='store_true')
    args = parser.parse_args(argv)
    if not args.database.is_absolute() or (args.backup and not args.backup.is_absolute()):
        parser.error('Use absolute database/backup paths.')
    try:
        if args.action == 'inspect':
            result = inspect(args.database, args.device)
        elif args.action == 'inspect-reconciliation':
            result = device_reconciliation.inspect(args.database, args.device, pending_v7=True)
        else:
            if not all((args.key, args.actor, args.reviewed_at, args.review_digest, args.backup, args.confirm_api_web_agent_stopped)):
                parser.error('Apply requires fresh review, key/actor, checked backup and stopped-executor assertion.')
            apply = classify if args.action == 'classify' else device_reconciliation.reconcile
            options = {} if args.action == 'classify' else {'pending_v7': True}
            result = checked_offline(args.database, args.backup, lambda db, store: apply(
                db, store, args.device, args.key, args.actor, args.reviewed_at, args.review_digest, offline=True, **options))
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f'Offline v7 recovery refused: {error}\n')


if __name__ == '__main__':
    main()
