"""Offline held-epoch recovery for retained, fully verified work; never RPC replay."""

import argparse
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _atomic, _key_free, _state
from .extended_recovery import encode, expanded, record
from .maintenance import _actor, checked_offline
from .operation_queue import stamp
from .schema import execute_schema
from .store import Store

# Explicit optional upgrade. The retained receipt authorizes one exact transition,
# not a general override, a successor epoch or any job/desired-policy mutation.
_MATCH = """OLD.state='ATTENTION' AND NEW.state='IDLE' AND NEW.epoch=OLD.epoch
 AND NEW.owner IS NULL AND NEW.lease_until IS NULL AND EXISTS (
 SELECT 1 FROM managed_bulk_device_recovery r WHERE r.device_id=OLD.device_id
 AND r.epoch=OLD.epoch AND r.owner=OLD.owner AND r.lease_until=OLD.lease_until
 AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at)"""
DDL = """
CREATE TABLE managed_bulk_device_recovery (
 id TEXT PRIMARY KEY,device_id INTEGER NOT NULL REFERENCES managed_bulk_device_executors(device_id),
 epoch INTEGER NOT NULL CHECK(epoch>=1),owner TEXT NOT NULL,lease_until TEXT NOT NULL,
 held_at TEXT NOT NULL,recovered_at TEXT NOT NULL,actor_subject TEXT NOT NULL,
 review_digest TEXT NOT NULL CHECK(length(review_digest)=64),
 receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json) AND length(receipt_json)<=16384),
 UNIQUE(device_id,epoch)
);
CREATE TRIGGER managed_bulk_device_recovery_immutable BEFORE UPDATE ON managed_bulk_device_recovery
BEGIN SELECT RAISE(ABORT,'device recovery evidence is immutable'); END;
CREATE TRIGGER managed_bulk_device_recovery_retained BEFORE DELETE ON managed_bulk_device_recovery
BEGIN SELECT RAISE(ABORT,'device recovery evidence is retained'); END;
CREATE TRIGGER managed_bulk_device_recovery_bound BEFORE INSERT ON managed_bulk_device_recovery
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_executors d WHERE d.device_id=NEW.device_id
 AND d.state='ATTENTION' AND d.epoch=NEW.epoch AND d.owner=NEW.owner
 AND d.lease_until=NEW.lease_until AND d.updated_at=NEW.held_at)
 OR NEW.recovered_at<=NEW.held_at OR NEW.recovered_at<=NEW.lease_until
 OR NEW.actor_subject NOT LIKE 'maintenance:%'
 OR EXISTS(SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING','UNVERIFIED','RECONCILED_ABSENT'))
BEGIN SELECT RAISE(ABORT,'device recovery requires exact held quiescent evidence'); END;
DROP TRIGGER managed_bulk_device_attention;
DROP TRIGGER managed_bulk_device_epoch;
CREATE TRIGGER managed_bulk_device_attention BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION' AND NOT (""" + _MATCH + """)
BEGIN SELECT RAISE(ABORT,'device lease attention needs exact offline recovery'); END;
CREATE TRIGGER managed_bulk_device_epoch BEFORE UPDATE ON managed_bulk_device_executors
WHEN NOT ((OLD.state='IDLE' AND NEW.state='LEASED' AND NEW.epoch=OLD.epoch+1)
 OR (OLD.state='LEASED' AND NEW.epoch=OLD.epoch AND
 ((NEW.state IN ('LEASED','ATTENTION') AND NEW.owner=OLD.owner) OR NEW.state='IDLE'))
 OR (""" + _MATCH + """))
BEGIN SELECT RAISE(ABORT,'invalid device lease transition'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_device_recovery'").fetchone() is not None


def validate(db):
    if (db.execute('SELECT COUNT(*) FROM managed_bulk_device_recovery').fetchone()[0] > 4096
            or db.execute('''SELECT 1 FROM managed_bulk_device_recovery r
                LEFT JOIN managed_bulk_device_executors d ON d.device_id=r.device_id
                WHERE d.device_id IS NULL OR r.epoch>d.epoch OR r.recovered_at<=r.held_at
                    OR r.recovered_at<=r.lease_until LIMIT 1''').fetchone()):
        raise BulkUnavailable('Invalid or excessive retained device recovery evidence.')
    from .extended_recovery import validate as validate_extended

    validate_extended(db)


def fresh_after_recovery(db, device_id, started):
    if not present(db):
        return True
    row = db.execute('SELECT recovered_at FROM managed_bulk_device_recovery WHERE device_id=? ORDER BY epoch DESC LIMIT 1',
                     (device_id,)).fetchone()
    return row is None or started > row[0]


def _digest(db, *, extended_v6=False, prewrite_defer=False, pending_v7=False):
    digest = hashlib.sha256(b'ftd-shun:offline-interrupted-v7-recovery:v1\n' if pending_v7 else
        b'ftd-shun:offline-prewrite-v6-recovery:v1\n' if prewrite_defer else
        b'ftd-shun:offline-extended-v6-recovery:v1\n' if extended_v6 else b'ftd-shun:offline-verified-device-recovery:v1\n')
    for statement in db.iterdump():
        digest.update(statement.encode())
        digest.update(b'\n')
    return digest.hexdigest()


def _review(db, store, device_id, current, *, reconcile=False, extended_v6=False, prewrite_defer=False, pending_v7=False):
    from .bulk_ordered_waits import held_count, validate_held_predecessors
    from .bulk_ordered_waits import present as ordered_present
    from .bulk_waits import present as waits_present
    from .bulk_waits import validate_pending
    from .device_reconciliation import unresolved
    from .managed_restoration import attempt_for_job, validate_binding

    if type(extended_v6) is not bool:
        raise ValueError('Extended v6 recovery requires a literal explicit selection.')
    if type(pending_v7) is not bool or (pending_v7 and (extended_v6 or prewrite_defer or not reconcile)):
        raise ValueError('Interrupted v7 recovery requires its separate explicit reconciliation mode.')
    if type(prewrite_defer) is not bool or (prewrite_defer and (not extended_v6 or reconcile)):
        raise ValueError('Pre-write recovery needs explicit extended v6 and cannot reconcile unknowns.')
    if type(device_id) is not int or not 1 <= device_id <= 65535:
        raise ValueError('Select a literal device ID.')
    if _state(db) is None:
        raise BulkUnavailable('An exact existing fenced profile is required.')
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'managed_bulk_device_executors' not in tables:
        raise BulkUnavailable('Fenced device storage is required.')
    if ('managed_bulk_pending_execution' in tables) is not pending_v7:
        raise ValueError('Select the exact verified or interrupted-v7 recovery contract.')
    fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()
    if (fence is None or fence['state'] != 'ATTENTION'
            or not fence['lease_until'] < fence['updated_at'] < stamp(current)):
        raise ValueError('An exact expired ATTENTION epoch is required.')
    classification_id = None
    if pending_v7:
        from .pending_offline import classification
        classification_id = classification(db, dict(fence))['id']
        if db.execute("SELECT 1 FROM operation_jobs WHERE state='AWAITING_CONFIRMATION'").fetchone():
            raise ValueError('Awaiting device work prevents offline reconciliation.')
    if (db.execute("SELECT 1 FROM managed_bulk_device_executors WHERE device_id!=? AND state!='IDLE'", (device_id,)).fetchone()
            or db.execute("SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING','RECONCILED_ABSENT')").fetchone()
            or (not reconcile and db.execute("SELECT 1 FROM operation_jobs WHERE state='UNVERIFIED' AND " + unresolved(db, 'id')).fetchone())
            or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='FAILED'", (device_id,)).fetchone()
            or (not reconcile and db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED' AND "
                                             + unresolved(db, 'job_id'), (device_id,)).fetchone())):
        raise ValueError('Pending, uncertain, failed or other owned device work prevents recovery.')
    if waits_present(db) and validate_pending(db):
        raise ValueError('Captured cancellation remains unsettled.')
    if ordered_present(db):
        validate_held_predecessors(db)
        if held_count(db):
            raise ValueError('Ordered cleanup remains unsettled.')
    for root in db.execute('SELECT id,actor_subject FROM managed_shun_requests WHERE id IN (SELECT id FROM managed_bulk_manifests)'):
        BulkPolicies(store)._root(db, root['id'], root['actor_subject'])
    scope = (device_id, fence['owner'], fence['epoch'])
    openings = db.execute("""SELECT timestamp FROM shun_events WHERE device_id=? AND event_type='DEVICE_LEASE_CLAIMED'
        AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?""", scope).fetchall()
    attention = db.execute("""SELECT timestamp FROM shun_events WHERE device_id=? AND event_type='DEVICE_LEASE_ATTENTION'
        AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?""", scope).fetchall()
    if len(openings) != 1 or len(attention) != 1 or attention[0][0] != fence['updated_at']:
        raise ValueError('Original claim/attention audit is missing or inconsistent.')
    events = db.execute("""SELECT id,event_type,timestamp,details_json FROM shun_events WHERE device_id=?
        AND json_extract(details_json,'$.device_executor.owner')=?
        AND json_extract(details_json,'$.device_executor.epoch')=? ORDER BY timestamp,id""", scope).fetchall()
    claims, terminal, diagnostics = {}, {}, {}
    for event in events:
        details = json.loads(event['details_json'])
        job_id = details['operation_id']
        if reconcile and event['event_type'] == 'SHUN_ADD_FAILED':
            if (job_id in diagnostics or details.get('action') != 'ADD' or details.get('outcome') != 'UNVERIFIED'
                    or not openings[0][0] <= event['timestamp'] <= fence['updated_at']):
                raise ValueError('Unknown ADD diagnostic audit is duplicated or inconsistent.')
            diagnostics[job_id] = dict(event)
            continue
        target = claims if event['event_type'] == 'SHUN_OPERATION_RUNNING' else terminal
        permitted = {'SHUN_OPERATION_RUNNING', 'SHUN_OPERATION_VERIFIED', 'SHUN_OPERATION_NOOP'}
        if prewrite_defer:
            permitted.add('SHUN_OPERATION_DEFERRED')
        if reconcile:
            permitted.add('SHUN_OPERATION_UNVERIFIED')
        if (event['event_type'] not in permitted
                or job_id in target or not openings[0][0] <= event['timestamp'] <= fence['updated_at']):
            raise ValueError('Original epoch has unknown, duplicated or inconsistent claim results.')
        target[job_id] = dict(event)
    if not (1 <= len(claims) <= 64 if pending_v7 else 17 <= len(claims) <= 64 if extended_v6 else 1 <= len(claims) <= 16) or claims.keys() != terminal.keys():
        raise ValueError('Every original mutation claim needs its retained terminal verification.')
    window = {row[0] for row in db.execute('SELECT id FROM operation_jobs WHERE device_id=? AND started_at>=? AND started_at<=?',
                                          (device_id, openings[0][0], fence['updated_at']))}
    deferred = {key for key, event in terminal.items() if event['event_type'] == 'SHUN_OPERATION_DEFERRED'}
    if prewrite_defer and (len(deferred) != 1 or max(claims, key=lambda k: (claims[k]['timestamp'],
            db.execute('SELECT seq FROM operation_jobs WHERE id=?', (k,)).fetchone()[0])) not in deferred):
        raise ValueError('Exactly one final pre-write claim is required.')
    if window | deferred != claims.keys():
        raise ValueError('Retained started jobs do not match the whole original epoch.')
    evidence = []
    deferred_proof = None
    for key, claim in sorted(claims.items()):
        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (key,)).fetchone()
        result = terminal[key]
        if prewrite_defer and key in deferred:
            from .prewrite_recovery import proof

            deferred_proof = proof(db, key, dict(fence), openings[0][0])
            attempt = attempt_for_job(db, key)
            evidence.append({'job_id': key, 'action': 'ADD', 'state': 'CANCELLED',
                'running_event_id': claim['id'], 'terminal_event_id': result['id'],
                'evidence_digest': hashlib.sha256(repr((tuple(job), tuple(attempt))).encode()).hexdigest()})
            continue
        if (job is None or job['state'] not in ({'VERIFIED', 'NOOP', 'UNVERIFIED'} if reconcile else {'VERIFIED', 'NOOP'})
                or job['device_id'] != device_id or (reconcile and job['action'] != 'ADD')
                or result['event_type'] != 'SHUN_OPERATION_' + job['state']
                or not openings[0][0] <= job['started_at'] <= claim['timestamp'] <= job['completed_at'] <= result['timestamp']
                or any(json.loads(event['details_json']).get('action') != job['action'] for event in (claim, result))):
            raise ValueError('Original job and terminal audit disagree; no outcome is inferred.')
        if extended_v6 or pending_v7:
            claim_details = json.loads(claim['details_json'])
            result_details = json.loads(result['details_json'])
            if (job['action'] != 'ADD'
                    or type(claim_details.get('batch_session_version')) is not int
                    or claim_details['batch_session_version'] != (7 if pending_v7 else 6)
                    or (not pending_v7 and (type(result_details.get('batch_session_version')) is not int
                                            or result_details['batch_session_version'] != 6))
                    or claim_details.get('source') != 'managed_shun_policy'
                    or (not pending_v7 and result_details.get('addition_group') != claim_details.get('addition_group'))):
                raise ValueError('Extended recovery requires exact matching v6 system ADD audit.')
            _uuid(claim_details.get('addition_group'))
        attempt = attempt_for_job(db, key)
        if attempt is not None:
            validate_binding(db, attempt, job)
            if attempt['completed_at'] != job['completed_at']:
                raise ValueError('Original attempt and verified job disagree.')
            if reconcile:
                request_state = db.execute('SELECT state FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()[0]
                if request_state not in (('CANCELLED', 'EXPIRED') if pending_v7 else ('CANCELLED',)):
                    raise ValueError('Original terminal system request must remain revoked, never renewed.')
        elif job['action'] == 'ADD':
            raise ValueError('A held ADD requires its retained system attempt evidence.')
        evidence.append({'job_id': key, 'action': job['action'], 'state': job['state'],
                         'running_event_id': claim['id'], 'terminal_event_id': result['id'],
                         'evidence_digest': hashlib.sha256(repr((tuple(job), tuple(attempt) if attempt else None)).encode()).hexdigest()})
    if reconcile:
        unknown = {entry['job_id'] for entry in evidence if entry['state'] == 'UNVERIFIED'}
        retained = {row[0] for row in db.execute("SELECT id FROM operation_jobs WHERE state='UNVERIFIED' AND " + unresolved(db, 'id'))}
        attempts = {row[0] for row in db.execute("SELECT job_id FROM managed_bulk_attempts WHERE state='UNVERIFIED' AND " + unresolved(db, 'job_id'))}
        if not unknown or unknown != retained or unknown != attempts:
            raise ValueError('Reconcile the exact whole held ADD scope; foreign or missing uncertainty is not covered.')
        if set(diagnostics) != unknown or any(diagnostics[key]['timestamp'] < terminal[key]['timestamp'] for key in unknown):
            raise ValueError('Original unknown ADD diagnostic audit is missing or inconsistent.')
    return {'device_id': device_id, 'epoch': fence['epoch'], 'claims': evidence, 'original_fence': dict(fence),
            **({'recovery_profile': 'tracked-v7-interrupted', 'classification_id': classification_id} if pending_v7 else
               {'recovery_profile': 'tracked-v6-prewrite', 'prewrite_proof': deferred_proof,
                'original_outcomes_unchanged': True} if prewrite_defer
               else {'recovery_profile': 'tracked-v6'} if extended_v6 else {})}


def inspect(database, device_id, *, now=None, extended_v6=False, prewrite_defer=False):
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Recovery time must be explicit UTC.')
    path = database.resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        review = _review(db, Store(path), device_id, current, extended_v6=extended_v6, prewrite_defer=prewrite_defer)
        return {**review, 'reviewed_at': stamp(current), 'review_digest': _digest(db, extended_v6=extended_v6, prewrite_defer=prewrite_defer), 'read_only': True}


def recover(db, store, device_id, key, actor, reviewed_at, review_digest, *, offline=False, now=None, extended_v6=False, prewrite_defer=False):
    if offline is not True or not db.in_transaction:
        raise ValueError('Stop API/Web/agent and explicitly attest offline quiescence.')
    if type(extended_v6) is not bool:
        raise ValueError('Extended v6 recovery requires a literal explicit selection.')
    if type(prewrite_defer) is not bool or (prewrite_defer and not extended_v6):
        raise ValueError('Pre-write recovery needs explicit extended v6 selection.')
    if type(device_id) is not int or not 1 <= device_id <= 65535:
        raise ValueError('Select a literal device ID.')
    _uuid(key)
    subject, current = _actor(actor), now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Recovery time must be explicit UTC.')
    if (type(review_digest) is not str or len(review_digest) != 64
            or any(c not in '0123456789abcdef' for c in review_digest)):
        raise ValueError('Supply the exact reviewed digest.')
    with _atomic(db):
        if present(db):
            _state(db)
            old = db.execute('SELECT * FROM managed_bulk_device_recovery WHERE id=?', (key,)).fetchone()
            if old:
                if (old['device_id'], old['actor_subject'], old['review_digest']) != (device_id, subject, review_digest):
                    raise ValueError('Recovery key is bound to another decision.')
                stored = json.loads(old['receipt_json'])
                if stored.get('recovery_profile') != ('tracked-v6-prewrite' if prewrite_defer else 'tracked-v6' if extended_v6 else None):
                    raise ValueError('Recovery key belongs to another profile selection.')
                return {**expanded(stored), 'replayed': True}
        reviewed = datetime.fromisoformat(reviewed_at)
        if (reviewed.tzinfo is None or reviewed.utcoffset() != timedelta(0) or stamp(reviewed) != reviewed_at
                or not reviewed <= current <= reviewed + timedelta(minutes=5)
                or not hmac.compare_digest(_digest(db, extended_v6=extended_v6, prewrite_defer=prewrite_defer), review_digest)):
            raise ValueError('The review is expired or the database changed; inspect again.')
        review = _review(db, store, device_id, current, extended_v6=extended_v6, prewrite_defer=prewrite_defer)
        _key_free(db, key)
        if not present(db):
            execute_schema(db, DDL)
        if db.execute('SELECT COUNT(*) FROM managed_bulk_device_recovery').fetchone()[0] >= 4096:
            raise ValueError('Retained recovery capacity reached; no evidence was evicted.')
        timestamp = stamp(current)
        receipt = {**review, 'operation_id': key, 'actor_subject': subject, 'recovered_at': timestamp,
                   'offline_assertion': 'api_web_agent_stopped', 'replayed': False,
                   'jobs_retried': 0, 'policy_changed': False}
        stored, serialized = encode(receipt, extended_v6)
        fence = review['original_fence']
        db.execute('INSERT INTO managed_bulk_device_recovery VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (key, device_id, fence['epoch'], fence['owner'], fence['lease_until'], fence['updated_at'],
                    timestamp, subject, review_digest, serialized))
        record(db, stored)
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL,updated_at=? WHERE device_id=?",
                   (timestamp, device_id))
        store._insert_event(db, 'DEVICE_LEASE_OFFLINE_PREWRITE_RECOVERY' if prewrite_defer else 'DEVICE_LEASE_OFFLINE_VERIFIED_RECOVERY',
                            device_id, None, None, subject,
                            'Offline pre-write-deferral recovery' if prewrite_defer else 'Offline verified-epoch recovery', (), key, stored, timestamp)
        db.execute('UPDATE operation_executor SET revision=revision+1 WHERE id=1')
        _state(db)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline recovery of a fully verified held device epoch, never unknown work.')
    parser.add_argument('action', choices=('inspect', 'recover'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--device', type=int, required=True)
    parser.add_argument('--extended-v6', action='store_true', help='Explicit 17-64-claim tracked-v6 system ADD profile')
    parser.add_argument('--prewrite-defer', action='store_true', help='Separate v6 profile with one exact final expired/cancelled pre-write DEFER')
    parser.add_argument('--key')
    parser.add_argument('--actor')
    parser.add_argument('--reviewed-at')
    parser.add_argument('--review-digest')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--confirm-api-web-agent-stopped', action='store_true')
    args = parser.parse_args(argv)
    if not args.database.is_absolute() or (args.backup and not args.backup.is_absolute()):
        parser.error('Select absolute existing database and new backup paths.')
    if args.action == 'recover' and (not args.confirm_api_web_agent_stopped or not all(
            (args.key, args.actor, args.reviewed_at, args.review_digest, args.backup))):
        parser.error('Recovery requires a key, actor, fresh review, checked backup and offline quiescence confirmation.')
    try:
        if args.action == 'inspect':
            result = inspect(args.database, args.device, extended_v6=args.extended_v6, prewrite_defer=args.prewrite_defer)
        else:
            result = checked_offline(args.database, args.backup, lambda db, store: recover(
                db, store, args.device, args.key, args.actor, args.reviewed_at, args.review_digest, offline=True,
                extended_v6=args.extended_v6, prewrite_defer=args.prewrite_defer))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f'Recovery refused: {error}. Any created backup/evidence was retained.\n')
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
