"""Explicit compact v6 offline receipts; never startup repair or job replay."""

import hashlib
import hmac
import json

from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable
from .schema import execute_schema

TABLE = 'managed_bulk_extended_recovery'
FORMAT = 'compact-v6'
FIELDS = ('job_id', 'action', 'state', 'running_event_id', 'terminal_event_id', 'evidence_digest')
DDL = """
CREATE TABLE managed_bulk_extended_recovery (
 recovery_id TEXT PRIMARY KEY REFERENCES managed_bulk_device_recovery(id),
 claim_count INTEGER NOT NULL CHECK(claim_count BETWEEN 17 AND 64),
 claims_digest TEXT NOT NULL CHECK(length(claims_digest)=64)
);
CREATE TRIGGER managed_bulk_extended_recovery_immutable BEFORE UPDATE ON managed_bulk_extended_recovery
BEGIN SELECT RAISE(ABORT,'extended recovery evidence is immutable'); END;
CREATE TRIGGER managed_bulk_extended_recovery_retained BEFORE DELETE ON managed_bulk_extended_recovery
BEGIN SELECT RAISE(ABORT,'extended recovery evidence is retained'); END;
CREATE TRIGGER managed_bulk_extended_recovery_bound BEFORE INSERT ON managed_bulk_extended_recovery
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_device_executors d
 ON d.device_id=r.device_id WHERE r.id=NEW.recovery_id AND d.state='ATTENTION'
 AND d.epoch=r.epoch AND d.owner=r.owner AND d.lease_until=r.lease_until AND d.updated_at=r.held_at
 AND json_extract(r.receipt_json,'$.claims_format')='compact-v6'
 AND json_extract(r.receipt_json,'$.recovery_profile')='tracked-v6'
 AND json_array_length(r.receipt_json,'$.compact_claims')=NEW.claim_count)
BEGIN SELECT RAISE(ABORT,'extended receipt requires its exact original held epoch'); END;
CREATE TRIGGER managed_bulk_extended_recovery_release BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION' AND NEW.state='IDLE'
 AND EXISTS(SELECT 1 FROM managed_bulk_device_recovery r WHERE r.device_id=OLD.device_id
  AND r.epoch=OLD.epoch AND r.owner=OLD.owner AND r.held_at=OLD.updated_at
  AND r.recovered_at=NEW.updated_at AND json_type(r.receipt_json,'$.claims_format') IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM managed_bulk_device_recovery r JOIN managed_bulk_extended_recovery x
  ON x.recovery_id=r.id WHERE r.device_id=OLD.device_id AND r.epoch=OLD.epoch AND r.owner=OLD.owner
  AND r.held_at=OLD.updated_at AND r.recovered_at=NEW.updated_at
  AND json_extract(r.receipt_json,'$.claims_format')='compact-v6'
  AND json_array_length(r.receipt_json,'$.compact_claims')=x.claim_count)
BEGIN SELECT RAISE(ABORT,'extended release requires its exact retained marker'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is not None


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def claims(receipt):
    from .pending_offline import FORMAT as PENDING_FORMAT
    from .pending_offline import PROFILE as PENDING_PROFILE
    from .prewrite_recovery import FORMAT as PREWRITE_FORMAT
    from .prewrite_recovery import PROFILE as PREWRITE_PROFILE

    prewrite = receipt.get('recovery_profile') == PREWRITE_PROFILE
    pending = receipt.get('recovery_profile') == PENDING_PROFILE
    if 'claims_format' not in receipt and 'compact_claims' not in receipt:
        if receipt.get('recovery_profile') in {'tracked-v6', PREWRITE_PROFILE, PENDING_PROFILE}:
            raise BulkUnavailable('Extended receipt is missing its exact compact format.')
        return receipt.get('claims', [])
    rows = receipt.get('compact_claims')
    if (receipt.get('claims_format') != (PENDING_FORMAT if pending else PREWRITE_FORMAT if prewrite else FORMAT)
            or receipt.get('recovery_profile') != (PENDING_PROFILE if pending else PREWRITE_PROFILE if prewrite else 'tracked-v6')
            or 'claims' in receipt or type(rows) is not list or not (1 if pending else 17) <= len(rows) <= 64):
        raise BulkUnavailable('Extended recovery receipt has an invalid format or scope.')
    result = []
    previous = ''
    try:
        for row in rows:
            if (type(row) is not list or len(row) != len(FIELDS) or any(type(value) is not str for value in row)
                    or row[1] != 'ADD' or row[2] not in ({'VERIFIED', 'NOOP', 'CANCELLED'} if prewrite else {'VERIFIED', 'NOOP', 'UNVERIFIED'})
                    or row[0] <= previous or len(row[5]) != 64
                    or any(c not in '0123456789abcdef' for c in row[5])):
                raise ValueError('Invalid compact claim')
            for index in (0, 3, 4):
                _uuid(row[index])
            previous = row[0]
            result.append(dict(zip(FIELDS, row, strict=True)))
    except (ValueError, TypeError) as error:
        raise BulkUnavailable('Extended recovery claim identities/order are invalid.') from error
    if prewrite and (type(receipt.get('prewrite_proof')) is not dict
            or sum(row['state'] == 'CANCELLED' for row in result) != 1
            or receipt.get('prewrite_proof', {}).get('job_id') != next(row['job_id'] for row in result if row['state'] == 'CANCELLED')):
        raise BulkUnavailable('Pre-write scope requires its one exact cancelled member.')
    return result


def encode(receipt, extended_v6):
    stored = dict(receipt)
    from .pending_offline import FORMAT as PENDING_FORMAT
    from .pending_offline import PROFILE as PENDING_PROFILE
    pending = stored.get('recovery_profile') == PENDING_PROFILE
    if extended_v6 or pending:
        stored['compact_claims'] = [[claim[field] for field in FIELDS] for claim in stored.pop('claims')]
        from .prewrite_recovery import FORMAT as PREWRITE_FORMAT
        from .prewrite_recovery import PROFILE as PREWRITE_PROFILE

        stored['claims_format'] = PENDING_FORMAT if pending else PREWRITE_FORMAT if stored.get('recovery_profile') == PREWRITE_PROFILE else FORMAT
        claims(stored)  # Validate literal bounds/identities before any schema write.
    text = json.dumps(stored, sort_keys=True, separators=(',', ':') if extended_v6 else None)
    if len(text.encode('utf-8')) > 16384:
        raise ValueError('Recovery receipt exceeds its retained 16-KiB bound; no evidence was truncated.')
    return stored, text


def expanded(receipt):
    result = {key: value for key, value in receipt.items() if key not in {'claims_format', 'compact_claims'}}
    result['claims'] = claims(receipt)
    return result


def record(db, receipt):
    """Only explicit offline apply, after parent INSERT and before fence release."""
    from . import pending_offline, prewrite_recovery

    if receipt.get('claims_format') == pending_offline.FORMAT:
        scope = claims(receipt)
        db.execute(f'INSERT INTO {pending_offline.MARKERS} VALUES (?,?,?,?)',
                   (receipt['operation_id'], receipt['classification_id'], len(scope), _digest(receipt['compact_claims'])))
        return

    if receipt.get('claims_format') == prewrite_recovery.FORMAT:
        claims(receipt)
        prewrite_recovery.record(db, receipt)
        return
    if receipt.get('claims_format') != FORMAT:
        return
    claims(receipt)
    if not present(db):
        execute_schema(db, DDL)
    db.execute(f'INSERT INTO {TABLE} VALUES (?,?,?)',
               (receipt['operation_id'], len(receipt['compact_claims']), _digest(receipt['compact_claims'])))


def validate(db):
    from . import prewrite_recovery

    declared = {row['id']: row for row in db.execute("""SELECT * FROM managed_bulk_device_recovery
        WHERE json_type(receipt_json,'$.claims_format') IS NOT NULL
           OR json_type(receipt_json,'$.compact_claims') IS NOT NULL
           OR json_extract(receipt_json,'$.recovery_profile')='tracked-v6'""")}
    deferred = {key: row for key, row in declared.items()
                if json.loads(row['receipt_json']).get('recovery_profile') == prewrite_recovery.PROFILE}
    from . import pending_offline
    pending = {key: row for key, row in declared.items()
               if json.loads(row['receipt_json']).get('recovery_profile') == pending_offline.PROFILE}
    pending_offline.validate_recoveries(db, pending)
    prewrite_recovery.validate(db, deferred)
    markers = list(db.execute(f'SELECT * FROM {TABLE}')) if present(db) else []
    if len(markers) + len(deferred) + len(pending) > 4096 or {row['recovery_id'] for row in markers} != set(declared) - set(deferred) - set(pending):
        raise BulkUnavailable('Extended recovery markers and complete receipt scope disagree.')
    prewrite_markers = list(db.execute('SELECT * FROM managed_bulk_prewrite_recovery')) if prewrite_recovery.present(db) else []
    for marker in [*markers, *prewrite_markers]:
        parent = declared[marker['recovery_id']]
        receipt = json.loads(parent['receipt_json'])
        scope = claims(receipt)
        if (marker['claim_count'] != len(scope)
                or not hmac.compare_digest(marker['claims_digest'], _digest(receipt['compact_claims']))
                or type(receipt.get('epoch')) is not int or type(receipt.get('device_id')) is not int
                or receipt.get('operation_id') != parent['id'] or receipt.get('epoch') != parent['epoch']
                or receipt.get('device_id') != parent['device_id']
                or receipt.get('recovered_at') != parent['recovered_at']
                or receipt.get('actor_subject') != parent['actor_subject']
                or receipt.get('offline_assertion') != 'api_web_agent_stopped'
                or type(receipt.get('jobs_retried')) is not int or receipt['jobs_retried'] != 0
                or receipt.get('policy_changed') is not False
                or receipt.get('original_fence') != {
                    'device_id': parent['device_id'], 'epoch': parent['epoch'], 'owner': parent['owner'],
                    'lease_until': parent['lease_until'], 'state': 'ATTENTION', 'updated_at': parent['held_at']}):
            raise BulkUnavailable('Extended recovery claim evidence differs from its immutable binding.')
