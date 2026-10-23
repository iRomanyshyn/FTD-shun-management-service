"""Read-only ordered-cleanup preflight; no admission, barrier or executor."""

import hashlib
import json
from datetime import UTC, datetime

from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable
from .bulk_policy_views import BulkPolicyViews
from .bulk_removals import BulkRemovalScopes, canonical_scope
from .device_leases import present as device_profile_present
from .managed_restoration import ACTOR, SOURCE, validate_binding
from .managed_safety import ManagedStateUnavailable
from .operation_queue import stamp
from .safety import mutations_suspended

_DOMAIN = b'ftd-shun-manager:ordered-removal-preflight:v2\n'


def _digest(value, domain):
    return hashlib.sha256(domain + json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _record(row):
    return {key: value.hex() if type(value) is bytes else value for key, value in dict(row).items()}


def _time(value):
    if type(value) is not str:
        raise ValueError('Original canonical UTC evidence time is required.')
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != UTC.utcoffset(parsed) or stamp(parsed) != value:
        raise ValueError('Original canonical UTC evidence time is required.')
    return value


class BulkOrderedRemovalScopes:
    """A local inspection API, deliberately without an admission method."""

    def __init__(self, store):
        self.store = store
        self.views = BulkPolicyViews(store)

    def snapshot(self, ip, *, device_id=None, now=None):
        current = datetime.now(UTC) if now is None else now
        if type(current) is not datetime or current.tzinfo is None or current.utcoffset() != UTC.utcoffset(current):
            raise ValueError('Use an explicit UTC inspection time.')
        timestamp = stamp(current)
        with self.views._snapshot() as db:
            scope = BulkRemovalScopes.read(db, ip, device_id=device_id)
            if not device_profile_present(db):
                raise BulkUnavailable('Ordered inspection requires existing exact fenced v2 storage.')
            targets = [self._target(db, row, ip, timestamp) for row in scope['targets']]
            global_blockers = ['MUTATIONS_PAUSED'] if mutations_suspended(db) else []
            blocked = sum(row['disposition'] == 'BLOCKED' for row in targets)
            waiting = sum(row['disposition'] == 'WAITING_ADD' for row in targets)
            value = {'intent_format': 2, 'mode': 'ordered-removal-preflight', 'inspected_at': timestamp,
                     'scope': scope, 'scope_digest': canonical_scope(scope)[1], 'targets': targets,
                     'global_blockers': global_blockers, 'blocked_target_count': blocked,
                     'waiting_target_count': waiting,
                     'disposition': 'BLOCKED' if blocked or global_blockers else 'WAITING_ADD' if waiting else 'READY',
                     'read_only': True, 'execution_available': False, 'device_work_admitted': False}
            return {**value, 'preflight_digest': _digest(value, _DOMAIN)}

    @staticmethod
    def _target(db, target, ip, now):
        device, blockers, predecessor = target['device_id'], [], None
        pair = (device, ip.packed)
        if not target['device_enabled']:
            blockers.append('DEVICE_DISABLED')
        fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device,)).fetchone()
        if fence is None:
            blockers.append('DEVICE_OUTSIDE_EXECUTOR_SCOPE')
        elif fence['state'] == 'ATTENTION':
            blockers.append('DEVICE_FENCE_ATTENTION')
        elif fence['updated_at'] > now:
            blockers.append('DEVICE_CLOCK_REVERSED')
        elif fence['state'] == 'LEASED' and fence['lease_until'] <= now:
            blockers.append('DEVICE_FENCE_EXPIRED')
        if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT') LIMIT 1", (device,)).fetchone()
                or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED' LIMIT 1", (device,)).fetchone()):
            blockers.append('DEVICE_OUTCOME_UNKNOWN')
        if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND action='ADD' AND state='FAILED' LIMIT 1", pair).fetchone()
                or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND state IN ('FAILED','UNVERIFIED') LIMIT 1", pair).fetchone()):
            blockers.append('PAIR_ADD_ATTENTION')
        job = db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING')", pair).fetchone()
        if job is None:
            if db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING') LIMIT 1", pair).fetchone():
                blockers.append('ADD_BINDING_UNAVAILABLE')
        elif job['action'] != 'ADD':
            blockers.append('PENDING_REMOVE')
        elif job['state'] != 'RUNNING':
            blockers.append('ADD_NOT_RUNNING')
        elif not blockers:
            try:
                predecessor = BulkOrderedRemovalScopes._predecessor(db, target, job, fence, now)
            except (ValueError, TypeError, KeyError, ManagedStateUnavailable):
                blockers.append('ADD_BINDING_UNAVAILABLE')
        return {'device_id': device, 'disposition': 'BLOCKED' if blockers else 'WAITING_ADD' if predecessor else 'READY',
                'blockers': blockers, 'predecessor': predecessor}

    @staticmethod
    def _predecessor(db, target, job, fence, now):
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
        if (attempt is None or attempt['state'] != 'RUNNING' or job['dispatch_kind'] != 'ADD'
                or attempt['completed_at'] is not None or job['completed_at'] is not None
                or not target['maintenance_enabled'] or fence is None or fence['state'] != 'LEASED'
                or any(attempt[field] != target[field] for field in ('intent_id', 'generation', 'authorization_request_id', 'target_revision'))):
            raise ValueError('The exact current owned RUNNING ADD is required.')
        if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND id!=? AND state='RUNNING' LIMIT 1",
                       (job['device_id'], job['id'])).fetchone()
                or db.execute("""SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND id!=?
                    AND state IN ('QUEUED','RUNNING') LIMIT 1""", (job['device_id'], job['ip'], attempt['id'])).fetchone()):
            raise ValueError('Conflicting running or retained pending evidence cannot be omitted.')
        validate_binding(db, attempt, job)
        for identity in (attempt['id'], job['id'], attempt['snapshot_id']):
            _uuid(identity)
        request = db.execute('SELECT * FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
        if (request['state'] != 'ACTIVE' or not _time(request['requested_at']) <= _time(job['started_at']) <= now < _time(request['expires_at'])
                or not _time(attempt['snapshot_started_at']) <= _time(attempt['snapshot_at']) <= request['requested_at']
                or fence['lease_until'] <= now):
            raise ValueError('Original request, snapshot and live executor evidence must agree.')
        # One linked system request owns one ADD. The indexed bounded lookup
        # refuses missing/duplicate claims instead of picking a convenient row.
        claims = db.execute("""SELECT * FROM shun_events WHERE request_id=?
            AND event_type='SHUN_OPERATION_RUNNING' ORDER BY id LIMIT 2""", (attempt['id'],)).fetchall()
        if len(claims) != 1 or len(claims[0]['details_json']) > 16384:
            raise ValueError('Exactly one bounded original claim receipt is required.')
        claim = claims[0]
        _uuid(claim['id'])
        details = json.loads(claim['details_json'])
        executor = {'owner': fence['owner'], 'epoch': fence['epoch']}
        if (claim['device_id'] != job['device_id'] or claim['ip'] != job['ip']
                or claim['actor_subject'] != ACTOR or json.loads(claim['actor_roles_json']) != []
                or not job['started_at'] <= _time(claim['timestamp']) <= now
                or type(details) is not dict or details.get('operation_id') != job['id']
                or details.get('action') != 'ADD' or details.get('source') != SOURCE
                or type(details.get('device_executor')) is not dict
                or type(details['device_executor'].get('epoch')) is not int
                or details['device_executor'] != executor):
            raise ValueError('The original claim does not bind the current device epoch.')
        evidence = {'attempt': _record(attempt), 'job': _record(job), 'request': _record(request),
                    'fence': _record(fence), 'claim': _record(claim)}
        return {'request_id': attempt['id'], 'job_id': job['id'], 'intent_id': attempt['intent_id'],
                'generation': attempt['generation'], 'authorization_request_id': attempt['authorization_request_id'],
                'target_revision': attempt['target_revision'], 'snapshot_id': attempt['snapshot_id'],
                'snapshot_started_at': attempt['snapshot_started_at'], 'snapshot_at': attempt['snapshot_at'],
                'requested_at': request['requested_at'], 'expires_at': request['expires_at'], 'started_at': job['started_at'],
                'executor_owner': fence['owner'], 'executor_epoch': fence['epoch'], 'lease_until': fence['lease_until'],
                'claim_event_id': claim['id'], 'evidence_digest': _digest(evidence, _DOMAIN + b'evidence\n')}
