"""Immutable settled-session predecessors for ordered cleanup; no ADD authority."""

import json

from .bulk_ordered_removals import _DOMAIN, _digest, _record, _time
from .managed_restoration import ACTOR, SOURCE, validate_binding
from .operation_queue import QueueConflict
from .pending_execution import present

KIND = 'AWAITING_CONFIRMATION'


def descriptor(db, job):
    """Caller validates the complete profile; this evidence survives observation."""
    if not present(db):
        raise ValueError('Exact deferred execution storage is required.')
    member = db.execute('SELECT * FROM managed_bulk_pending_members WHERE job_id=?', (job['id'],)).fetchone()
    attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
    if member is None or attempt is None:
        raise ValueError('Original settled pending membership is missing.')
    if (job['state'] not in {'AWAITING_CONFIRMATION', 'OBSERVED_PRESENT', 'CONFIRMED_ABSENT'}
            or attempt['state'] != job['state'] or attempt['completed_at'] != job['completed_at']):
        raise ValueError('Settled pending cleanup cannot substitute another ADD outcome.')
    session = db.execute('SELECT * FROM managed_bulk_pending_sessions WHERE id=?', (member['session_id'],)).fetchone()
    claim = db.execute('SELECT * FROM shun_events WHERE id=?', (member['claim_event_id'],)).fetchone()
    ack = db.execute('SELECT * FROM shun_events WHERE id=?', (member['ack_event_id'],)).fetchone()
    request = db.execute('SELECT * FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
    validate_binding(db, attempt, job)
    if (session is None or claim is None or ack is None or request is None
            or len(claim['details_json']) > 16384 or len(ack['details_json']) > 16384
            or len(claim['actor_roles_json']) > 1024 or len(ack['actor_roles_json']) > 1024
            or member['attempt_id'] != attempt['id'] or session['device_id'] != job['device_id']
            or member['ip'] != job['ip'] or job['dispatch_kind'] != 'ADD'
            or job['started_at'] is None or not _time(request['requested_at']) <= _time(job['started_at']) < _time(request['expires_at'])
            or not job['started_at'] <= _time(claim['timestamp']) <= _time(ack['timestamp']) <= _time(session['settled_at'])
            or claim['actor_subject'] != ACTOR or json.loads(claim['actor_roles_json']) != []
            or ack['actor_subject'] != ACTOR or json.loads(ack['actor_roles_json']) != []):
        raise ValueError('Original pending claim, acknowledgement and settlement must agree.')
    details = json.loads(claim['details_json'])
    if (type(details) is not dict or details.get('action') != 'ADD' or details.get('source') != SOURCE
            or details.get('operation_id') != job['id']
            or details.get('device_executor') != {'owner': session['owner'], 'epoch': session['epoch']}
            or type(details.get('batch_session_version')) is not int or details['batch_session_version'] != 7):
        raise ValueError('Pending cleanup cannot substitute another original claim.')
    stable = {'session': _record(session), 'member': _record(member), 'claim': _record(claim), 'ack': _record(ack)}
    return {'kind': KIND, 'pending_session_id': session['id'], 'settled_at': session['settled_at'],
            'request_id': attempt['id'], 'job_id': job['id'], 'intent_id': attempt['intent_id'],
            'generation': attempt['generation'], 'authorization_request_id': attempt['authorization_request_id'],
            'target_revision': attempt['target_revision'], 'snapshot_id': attempt['snapshot_id'],
            'snapshot_started_at': attempt['snapshot_started_at'], 'snapshot_at': attempt['snapshot_at'],
            'requested_at': request['requested_at'], 'expires_at': request['expires_at'], 'started_at': job['started_at'],
            'executor_owner': session['owner'], 'executor_epoch': session['epoch'],
            'claim_event_id': claim['id'], 'evidence_digest': _digest(stable, _DOMAIN + b'pending-evidence\n')}


def capture(db, target, job, fence, now):
    """A fresh read of an exact still-awaiting maintained target, not live ADD."""
    value = descriptor(db, job)
    attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
    if (job['state'] != KIND or attempt['state'] != KIND or job['completed_at'] is not None
            or attempt['completed_at'] is not None or not target['maintenance_enabled']
            or any(attempt[field] != target[field] for field in
                   ('intent_id', 'generation', 'authorization_request_id', 'target_revision'))
            or value['settled_at'] > now or fence is None or fence['epoch'] < value['executor_epoch']
            or (fence['epoch'] == value['executor_epoch'] and fence['state'] != 'IDLE')
            or db.execute('SELECT 1 FROM managed_bulk_pending_reads WHERE session_id=?', (value['pending_session_id'],)).fetchone()
            or db.execute("""SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND job_id!=?
                AND state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION') LIMIT 1""",
                (job['device_id'], job['ip'], job['id'])).fetchone()):
        raise ValueError('Only the exact current awaiting target can be captured.')
    return value


def require_captured(db, evidence, job):
    """Check immutable evidence after capture, including after first observation."""
    if descriptor(db, job) != evidence:
        raise QueueConflict('Captured settled predecessor changed or lost its original evidence.')
