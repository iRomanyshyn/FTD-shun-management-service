"""Exact cancelled pre-write proof for explicit offline v6 recovery only."""

import hashlib
import json

from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable
from .schema import execute_schema

TABLE = 'managed_bulk_prewrite_recovery'
PROFILE = 'tracked-v6-prewrite'
FORMAT = 'compact-v6-prewrite'
DDL = """
CREATE TABLE managed_bulk_prewrite_recovery (
 recovery_id TEXT PRIMARY KEY REFERENCES managed_bulk_device_recovery(id),
 job_id TEXT NOT NULL REFERENCES operation_jobs(id),
 claim_count INTEGER NOT NULL CHECK(claim_count BETWEEN 17 AND 64),
 claims_digest TEXT NOT NULL CHECK(length(claims_digest)=64),
 proof_json TEXT NOT NULL CHECK(json_valid(proof_json) AND length(proof_json)<=4096)
);
CREATE TRIGGER managed_bulk_prewrite_recovery_immutable BEFORE UPDATE ON managed_bulk_prewrite_recovery
BEGIN SELECT RAISE(ABORT,'pre-write recovery evidence is immutable'); END;
CREATE TRIGGER managed_bulk_prewrite_recovery_retained BEFORE DELETE ON managed_bulk_prewrite_recovery
BEGIN SELECT RAISE(ABORT,'pre-write recovery evidence is retained'); END;
CREATE TRIGGER managed_bulk_prewrite_recovery_bound BEFORE INSERT ON managed_bulk_prewrite_recovery
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_device_executors d
 ON d.device_id=r.device_id JOIN operation_jobs j ON j.id=NEW.job_id
 WHERE r.id=NEW.recovery_id AND d.state='ATTENTION' AND d.epoch=r.epoch AND d.owner=r.owner
 AND d.updated_at=r.held_at AND d.lease_until=r.lease_until AND j.state='CANCELLED' AND j.action='ADD'
 AND json_extract(r.receipt_json,'$.recovery_profile')='tracked-v6-prewrite'
 AND json_extract(r.receipt_json,'$.prewrite_proof.job_id')=NEW.job_id
 AND json_extract(r.receipt_json,'$.prewrite_proof')=json(NEW.proof_json))
BEGIN SELECT RAISE(ABORT,'pre-write receipt requires its exact original held scope'); END;
CREATE TRIGGER managed_bulk_prewrite_recovery_release BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION' AND NEW.state='IDLE'
 AND EXISTS(SELECT 1 FROM managed_bulk_device_recovery r WHERE r.device_id=OLD.device_id
 AND r.epoch=OLD.epoch AND r.owner=OLD.owner AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
 AND json_extract(r.receipt_json,'$.recovery_profile')='tracked-v6-prewrite')
 AND NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_prewrite_recovery p
 ON p.recovery_id=r.id WHERE r.device_id=OLD.device_id AND r.epoch=OLD.epoch AND r.owner=OLD.owner
 AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at)
BEGIN SELECT RAISE(ABORT,'pre-write release requires its exact retained marker'); END;
DROP TRIGGER managed_bulk_extended_recovery_release;
CREATE TRIGGER managed_bulk_extended_recovery_release BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION' AND NEW.state='IDLE'
 AND EXISTS(SELECT 1 FROM managed_bulk_device_recovery r WHERE r.device_id=OLD.device_id
 AND r.epoch=OLD.epoch AND r.owner=OLD.owner AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
 AND json_type(r.receipt_json,'$.claims_format') IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_extended_recovery x
 ON x.recovery_id=r.id WHERE r.device_id=OLD.device_id AND r.epoch=OLD.epoch AND r.owner=OLD.owner
 AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
 AND json_extract(r.receipt_json,'$.claims_format')='compact-v6'
 AND json_array_length(r.receipt_json,'$.compact_claims')=x.claim_count)
 AND NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_prewrite_recovery p
 ON p.recovery_id=r.id WHERE r.device_id=OLD.device_id AND r.epoch=OLD.epoch AND r.owner=OLD.owner
 AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
 AND json_extract(r.receipt_json,'$.claims_format')='compact-v6-prewrite'
 AND json_array_length(r.receipt_json,'$.compact_claims')=p.claim_count)
BEGIN SELECT RAISE(ABORT,'extended release requires its exact retained marker'); END;
"""


def present(db):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is not None


def proof(db, job_id, fence, opened):
    """Retained original audit proves pre-write deferral, never success."""
    from .managed_restoration import validate_binding

    job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
    attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()
    if job is None or attempt is None:
        raise ValueError('Original pre-write job/attempt is missing.')
    validate_binding(db, attempt, job)
    request = db.execute('SELECT * FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
    events = db.execute('SELECT * FROM shun_events WHERE request_id=? ORDER BY timestamp,id', (attempt['id'],)).fetchall()
    groups = {}
    for event in events:
        groups.setdefault(event['event_type'], []).append(event)
        if (event['device_id'] != fence['device_id'] or event['ip'] != job['ip']
                or event['actor_subject'] != 'system:managed-shun-policy' or event['actor_roles_json'] != '[]'):
            raise ValueError('Pre-write audit identity or target changed.')
    expected = {'MANAGED_BULK_ATTEMPT_QUEUED': 2, 'MANAGED_BULK_ATTEMPT_RUNNING': 1,
        'SHUN_OPERATION_RUNNING': 1, 'SHUN_OPERATION_DEFERRED': 1,
        'MANAGED_BULK_ATTEMPT_CANCELLED': 1, 'SHUN_OPERATION_CANCELLED': 1}
    if ({kind: len(rows) for kind, rows in groups.items()} != expected or request is None
            or request['state'] != 'EXPIRED' or job['state'] != 'CANCELLED' or attempt['state'] != 'CANCELLED'
            or job['action'] != 'ADD' or job['started_at'] is not None or job['dispatch_kind'] is not None
            or job['device_id'] != fence['device_id'] or job['completed_at'] != attempt['completed_at']
            or not request['requested_at'] <= request['expires_at'] <= job['completed_at']):
        raise ValueError('Exact expired, cancelled, never-acknowledged pre-write scope is required.')
    claim = groups['SHUN_OPERATION_RUNNING'][0]
    deferred = groups['SHUN_OPERATION_DEFERRED'][0]
    cancelled = groups['SHUN_OPERATION_CANCELLED'][0]
    requeues = [event for event in groups['MANAGED_BULK_ATTEMPT_QUEUED']
                if json.loads(event['details_json']).get('reason') == 'Exact pre-write deferral']
    if len(requeues) != 1:
        raise ValueError('Exactly one original pre-write requeue is required.')
    requeue = requeues[0]
    cd, dd = json.loads(claim['details_json']), json.loads(deferred['details_json'])
    for kind in ('MANAGED_BULK_ATTEMPT_QUEUED', 'MANAGED_BULK_ATTEMPT_RUNNING', 'MANAGED_BULK_ATTEMPT_CANCELLED'):
        for event in groups[kind]:
            details = json.loads(event['details_json'])
            expected = {'authorization_request_id': attempt['authorization_request_id'], 'generation': attempt['generation'],
                'intent_format': 2, 'intent_id': attempt['intent_id'], 'managed_revision': details.get('managed_revision'),
                'occurrence_id': None, 'operation_id': job_id, 'protected_revision': details.get('protected_revision'),
                'reason': job['reason'] if kind.endswith('CANCELLED') else 'Exact pre-write deferral' if event['id'] == requeue['id'] else None,
                'snapshot_id': attempt['snapshot_id'], 'source': 'managed_shun_policy'}
            if (details != expected or any(type(details.get(field)) is not int or not 0 <= details[field] < 2**63
                    for field in ('managed_revision', 'protected_revision'))):
                raise ValueError('Original bulk transition audit differs from its exact attempt.')
    owner = {'owner': fence['owner'], 'epoch': fence['epoch']}
    expected_defer = {'action': 'ADD', 'batch_session_version': 6, 'device_executor': owner,
        'operation_id': job_id, 'source': 'managed_shun_policy', 'write_sent': False}
    if (dd != expected_defer or dd.get('write_sent') is not False
            or type(dd.get('batch_session_version')) is not int
            or type(dd.get('device_executor', {}).get('epoch')) is not int
            or cd.get('device_executor') != owner or type(cd.get('device_executor', {}).get('epoch')) is not int
            or cd.get('action') != 'ADD' or cd.get('source') != 'managed_shun_policy'
            or cd.get('operation_id') != job_id or type(cd.get('batch_session_version')) is not int
            or cd['batch_session_version'] != 6
            or not opened <= claim['timestamp'] <= requeue['timestamp'] <= deferred['timestamp'] <= fence['updated_at']
            or not request['requested_at'] <= claim['timestamp'] <= deferred['timestamp'] < request['expires_at']
            or not deferred['timestamp'] <= job['completed_at'] <= cancelled['timestamp']
            or json.loads(requeue['details_json']).get('reason') != 'Exact pre-write deferral'
            or json.loads(cancelled['details_json']) != {'operation_id': job_id, 'action': 'ADD',
                'source': 'managed_shun_policy', 'reason': job['reason']}
            or groups['MANAGED_BULK_ATTEMPT_CANCELLED'][0]['timestamp'] != job['completed_at']):
        raise ValueError('Original typed pre-write deferral and cancellation evidence disagree.')
    _uuid(cd.get('addition_group'))
    for event in events:
        _uuid(event['id'])
    return {'job_id': job_id, 'attempt_id': attempt['id'], 'claim_event_id': claim['id'],
        'deferred_event_id': deferred['id'], 'cancellation_event_id': cancelled['id'],
        'evidence_digest': hashlib.sha256(repr((tuple(job), tuple(attempt), tuple(request),
                                               tuple(tuple(event) for event in events))).encode()).hexdigest()}


def record(db, receipt):
    from .extended_recovery import DDL as EXTENDED_DDL
    from .extended_recovery import _digest
    from .extended_recovery import present as extended_present

    if not extended_present(db):
        execute_schema(db, EXTENDED_DDL)
    if not present(db):
        execute_schema(db, DDL)
    value = receipt['prewrite_proof']
    db.execute('INSERT INTO managed_bulk_prewrite_recovery VALUES (?,?,?,?,?)',
        (receipt['operation_id'], value['job_id'], len(receipt['compact_claims']), _digest(receipt['compact_claims']),
         json.dumps(value, sort_keys=True, separators=(',', ':'))))


def validate(db, declared):
    rows = list(db.execute('SELECT * FROM managed_bulk_prewrite_recovery')) if present(db) else []
    if {row['recovery_id'] for row in rows} != set(declared):
        raise BulkUnavailable('Pre-write receipts and complete markers disagree.')
    try:
        for row in rows:
            receipt = json.loads(declared[row['recovery_id']]['receipt_json'])
            if receipt.get('original_outcomes_unchanged') is not True:
                raise ValueError('Original outcomes must remain unchanged')
            fence = receipt['original_fence']
            openings = db.execute('''SELECT timestamp FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED'
                AND device_id=? AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?''',
                (fence['device_id'], fence['owner'], fence['epoch'])).fetchall()
            if len(openings) != 1:
                raise ValueError('Missing pre-write visit')
            original = proof(db, row['job_id'], fence, openings[0][0])
            if original != json.loads(row['proof_json']) or original != receipt['prewrite_proof']:
                raise ValueError('Changed pre-write proof')
    except (ValueError, KeyError, TypeError) as error:
        raise BulkUnavailable('Retained pre-write proof is missing or changed.') from error
