"""Bounded fresh ADD admission after proved absence, never RPC replay.

Internal default-disabled composition on the fresh deferred execution profile.
No schema initialization, agent call, configuration selector or worker loop.
"""

import hashlib
import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid5

from .bulk_dispatch import BulkCandidate, BulkDispatch, _snapshot
from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable, _atomic, _state
from .device_leases import DeviceLeases, _token
from .import_preparations import _stamp
from .managed_restoration import validate_binding
from .operation_queue import QueueConflict
from .pending_confirmation import _enabled
from .schema import schema_connection

TABLE = 'managed_bulk_pending_retries'
MAX_RETRIES = 1000000
HOURLY_LIMIT = 12
DDL = """
CREATE TABLE managed_bulk_pending_retries (
 attempt_id TEXT PRIMARY KEY REFERENCES managed_bulk_attempts(id),
 predecessor_id TEXT NOT NULL REFERENCES managed_bulk_attempts(id),
 origin_id TEXT NOT NULL REFERENCES managed_bulk_attempts(id),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 1000000),
 eligible_at TEXT NOT NULL, admitted_at TEXT NOT NULL,
 snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
 owner TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>=1),
 UNIQUE(origin_id,ordinal), CHECK(attempt_id!=predecessor_id)
);
CREATE INDEX idx_managed_bulk_pending_retry_parent ON managed_bulk_pending_retries(predecessor_id);
CREATE INDEX idx_managed_bulk_pending_retry_read ON managed_bulk_attempts(snapshot_id);
CREATE TRIGGER managed_bulk_pending_retry_immutable BEFORE UPDATE ON managed_bulk_pending_retries
BEGIN SELECT RAISE(ABORT,'fresh retry admission evidence is immutable'); END;
CREATE TRIGGER managed_bulk_pending_retry_retained BEFORE DELETE ON managed_bulk_pending_retries
BEGIN SELECT RAISE(ABORT,'fresh retry admission evidence is retained'); END;
"""


class RetryDeferred(QueueConflict):
    """Scheduling delay, not a failed write, uncertainty or new authority."""

    def __init__(self, retry_at, reason):
        super().__init__(reason)
        self.retry_at = retry_at


def present(db):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is not None


def validate_retained_jobs(db):
    """Retention boundary only, outside intermediate job/result transitions."""
    _state(db)
    for attempt in db.execute('''SELECT a.* FROM managed_bulk_attempts a
            JOIN managed_bulk_pending_retries r ON r.attempt_id=a.id'''):
        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (attempt['job_id'],)).fetchone()
        validate_binding(db, attempt, job)


def _delay(ordinal):
    return min(60, 5 * 2 ** min(ordinal - 1, 4))


def retry_candidates(db, device_id, after=b''):
    """Bounded advisory selection only; never admission or permission evidence."""
    return db.execute('''SELECT a.* FROM managed_bulk_attempts a
        JOIN managed_shun_targets t ON t.device_id=a.device_id AND t.ip=a.ip
        JOIN devices d ON d.id=a.device_id
        WHERE a.device_id=? AND a.state='CONFIRMED_ABSENT' AND a.ip>? AND d.enabled=1
          AND t.enabled=1 AND t.intent_id=a.intent_id AND t.generation=a.generation
          AND t.authorization_request_id=a.authorization_request_id AND t.revision=a.target_revision
          AND NOT EXISTS(SELECT 1 FROM managed_bulk_cancellations c WHERE c.import_id=a.authorization_request_id)
          AND NOT EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=a.ip AND p.enabled=1)
          AND NOT EXISTS(SELECT 1 FROM managed_bulk_attempts newer WHERE newer.intent_id=a.intent_id
            AND newer.state='CONFIRMED_ABSENT' AND newer.requested_at>a.requested_at)
          AND NOT EXISTS(SELECT 1 FROM managed_bulk_pending_retries r
            JOIN managed_bulk_attempts child ON child.id=r.attempt_id
            WHERE r.predecessor_id=a.id AND child.state!='CANCELLED')
        ORDER BY a.ip LIMIT 65''', (device_id, after)).fetchall()


def retry_window(db, parent, now, retained=None):
    """Shared timing arithmetic, not authority or an invented complete read."""
    previous = db.execute('SELECT * FROM managed_bulk_pending_retries WHERE attempt_id=?', (parent['id'],)).fetchone()
    origin = previous['origin_id'] if previous else parent['id']
    ordinal = retained['ordinal'] if retained else 1 + db.execute(
        'SELECT COALESCE(MAX(ordinal),0) FROM managed_bulk_pending_retries WHERE origin_id=?', (origin,)).fetchone()[0]
    if ordinal > MAX_RETRIES:
        raise QueueConflict('Fresh retry retained capacity is exhausted.')
    due = _stamp(datetime.fromisoformat(parent['completed_at']) + timedelta(seconds=_delay(ordinal)))
    hourly_due = due
    if retained is None:
        recent = db.execute('''SELECT COUNT(*),MIN(r.admitted_at) FROM managed_bulk_pending_retries r JOIN managed_bulk_attempts a ON a.id=r.attempt_id
            WHERE a.device_id=? AND a.ip=? AND r.admitted_at>?''',
            (parent['device_id'], parent['ip'], _stamp(now - timedelta(hours=1)))).fetchone()
        if recent[0] >= HOURLY_LIMIT:
            hourly_due = max(due, _stamp(datetime.fromisoformat(recent[1]) + timedelta(hours=1)))
    return origin, ordinal, due, hourly_due


def _digest(snapshot):
    return hashlib.sha256(b''.join(ip.packed for ip in sorted(snapshot.present_ips))).hexdigest()


def _read_identity(db, snapshot):
    expected = (snapshot.device_id, _stamp(snapshot.started_at), _stamp(snapshot.completed_at), _digest(snapshot))
    rows = db.execute('''SELECT s.device_id,r.started_at,r.completed_at,r.snapshot_digest
        FROM managed_bulk_pending_reads r JOIN managed_bulk_pending_sessions s ON s.id=r.session_id WHERE r.snapshot_id=?
        UNION ALL SELECT a.device_id,a.snapshot_started_at,a.snapshot_at,r.snapshot_digest
        FROM managed_bulk_pending_retries r JOIN managed_bulk_attempts a ON a.id=r.attempt_id WHERE a.snapshot_id=?''',
        (snapshot.id, snapshot.id)).fetchall()
    if any(tuple(row) != expected for row in rows):
        raise QueueConflict('Shared retry read identity must describe identical device/time/content evidence.')


def _absent(db, predecessor_id):
    row = db.execute('''SELECT a.*,m.ordinal AS member_ordinal,r.snapshot_id AS confirmation_id,
        r.started_at AS confirmation_started,r.completed_at AS confirmation_completed,
        r.recorded_at,r.snapshot_digest AS confirmation_digest,r.present_ordinals_json
        FROM managed_bulk_attempts a JOIN operation_jobs j ON j.id=a.job_id
        JOIN managed_bulk_pending_members m ON m.attempt_id=a.id
        JOIN managed_bulk_pending_reads r ON r.session_id=m.session_id
        WHERE a.id=? AND a.state='CONFIRMED_ABSENT' AND j.state=a.state
          AND a.completed_at=j.completed_at AND a.completed_at>=r.recorded_at
          AND NOT EXISTS(SELECT 1 FROM json_each(r.present_ordinals_json) WHERE value=m.ordinal)''',
                     (predecessor_id,)).fetchone()
    if row is None:
        raise QueueConflict('Fresh retry requires the exact settled, confirmed-absent predecessor.')
    job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (row['job_id'],)).fetchone()
    validate_binding(db, row, job)
    return row


def _same_scope(first, second):
    return all(first[field] == second[field] for field in (
        'device_id', 'ip', 'intent_id', 'generation', 'authorization_request_id', 'target_revision'))


def _cancelled_child(db, child):
    """Exact known nonexecution, not generic cancellation or RPC replay proof."""
    job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (child['job_id'],)).fetchone()
    if job is None:
        raise QueueConflict('Cancelled child is missing its original job.')
    validate_binding(db, child, job)
    if (child['state'] != 'CANCELLED' or job['started_at'] is not None or job['dispatch_kind'] is not None
            or child['completed_at'] != job['completed_at']):
        raise QueueConflict('Use only the latest absence; another child is pending, sent or uncertain.')
    events = db.execute('SELECT * FROM shun_events WHERE request_id=? ORDER BY timestamp,id', (child['id'],)).fetchall()
    claims = [event for event in events if event['event_type'] == 'SHUN_OPERATION_RUNNING']
    if not claims:
        # Preserve the existing never-claimed replacement contract.
        if any(event['event_type'] in {'SHUN_OPERATION_DEFERRED', 'SHUN_ADDITION_ACKNOWLEDGED',
                                      'MANAGED_BULK_ATTEMPT_RUNNING'} for event in events):
            raise QueueConflict('Unclaimed child has inconsistent command evidence.')
        return child['completed_at']
    try:
        grouped = {}
        for event in events:
            if (len(event['details_json']) > 16384 or event['device_id'] != child['device_id']
                    or event['ip'] != child['ip'] or event['actor_subject'] != 'system:managed-shun-policy'
                    or event['actor_roles_json'] != '[]'):
                raise ValueError('Changed child identity')
            grouped.setdefault(event['event_type'], []).append(event)
        expected = {'MANAGED_BULK_RETRY_ADMITTED': 1, 'MANAGED_BULK_ATTEMPT_QUEUED': 2,
            'MANAGED_BULK_ATTEMPT_RUNNING': 1, 'SHUN_OPERATION_RUNNING': 1,
            'SHUN_OPERATION_DEFERRED': 1, 'MANAGED_BULK_ATTEMPT_CANCELLED': 1, 'SHUN_OPERATION_CANCELLED': 1}
        if {kind: len(rows) for kind, rows in grouped.items()} != expected:
            raise ValueError('Missing, duplicate or acknowledged command evidence')
        claim, deferred = claims[0], grouped['SHUN_OPERATION_DEFERRED'][0]
        cd, dd = json.loads(claim['details_json']), json.loads(deferred['details_json'])
        executor = cd['device_executor']
        _uuid(cd['addition_group'])
        _uuid(executor['owner'])
        if type(executor['epoch']) is not int or executor['epoch'] < 1 or set(executor) != {'owner', 'epoch'}:
            raise ValueError('Invalid original visit')
        base = {'operation_id': job['id'], 'action': 'ADD', 'source': 'managed_shun_policy',
                'batch_session_version': 7, 'device_executor': executor}
        if (cd != {**base, 'addition_group': cd['addition_group']} or type(cd['batch_session_version']) is not int
                or dd != {**base, 'write_sent': False} or dd.get('write_sent') is not False
                or type(dd['batch_session_version']) is not int or type(dd['device_executor']['epoch']) is not int):
            raise ValueError('Not an exact tracked-v7 pre-write deferral')
        request = db.execute('SELECT * FROM operation_requests WHERE id=?', (child['id'],)).fetchone()
        opening = db.execute('''SELECT timestamp FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED'
            AND device_id=? AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?''',
            (child['device_id'], executor['owner'], executor['epoch'])).fetchall()
        requeues = [event for event in grouped['MANAGED_BULK_ATTEMPT_QUEUED']
                    if json.loads(event['details_json']).get('reason') == 'Exact pre-write deferral']
        cancelled = grouped['SHUN_OPERATION_CANCELLED'][0]
        cancellation = json.loads(cancelled['details_json'])
        if 'batch_session_version' in cancellation:
            version = cancellation.pop('batch_session_version')
            if type(version) is not int or version != 7:
                raise ValueError('Foreign cancellation version')
        if (len(opening) != 1 or len(requeues) != 1
                or not opening[0][0] <= claim['timestamp'] <= requeues[0]['timestamp'] <= deferred['timestamp'] <= child['completed_at']
                or not request['requested_at'] <= claim['timestamp'] <= deferred['timestamp'] < request['expires_at']
                or request['state'] not in {'EXPIRED', 'CANCELLED'} or cancelled['timestamp'] != child['completed_at']
                or grouped['MANAGED_BULK_ATTEMPT_CANCELLED'][0]['timestamp'] != child['completed_at']
                or cancellation != {'operation_id': job['id'], 'action': 'ADD', 'source': 'managed_shun_policy', 'reason': job['reason']}
                or db.execute('SELECT 1 FROM managed_bulk_pending_members WHERE attempt_id=?', (child['id'],)).fetchone()):
            raise ValueError('Inconsistent original deferral/cancellation scope')
        for kind in ('MANAGED_BULK_ATTEMPT_QUEUED', 'MANAGED_BULK_ATTEMPT_RUNNING', 'MANAGED_BULK_ATTEMPT_CANCELLED'):
            for event in grouped[kind]:
                details = json.loads(event['details_json'])
                expected = {'source': 'managed_shun_policy', 'operation_id': job['id'], 'intent_format': 2,
                    'intent_id': child['intent_id'], 'generation': child['generation'],
                    'authorization_request_id': child['authorization_request_id'], 'snapshot_id': child['snapshot_id'],
                    'reason': job['reason'] if kind.endswith('CANCELLED') else 'Exact pre-write deferral' if event['id'] == requeues[0]['id'] else None,
                    'managed_revision': details.get('managed_revision'), 'protected_revision': details.get('protected_revision'),
                    'occurrence_id': None}
                if details != expected or any(type(details.get(field)) is not int or not 0 <= details[field] < 2**63
                        for field in ('managed_revision', 'protected_revision')):
                    raise ValueError('Changed original transition audit')
    except (ValueError, TypeError, KeyError) as error:
        raise QueueConflict('Use only the latest absence; another child lacks exact pre-write cancellation proof.') from error
    return child['completed_at']


def _previous_children(db, parent_id, attempt_id, admitted_at=None):
    rows = db.execute('''SELECT a.* FROM managed_bulk_pending_retries r JOIN managed_bulk_attempts a ON a.id=r.attempt_id
        WHERE r.predecessor_id=? AND r.attempt_id!=? AND (? IS NULL OR r.admitted_at<=?)''',
        (parent_id, attempt_id, admitted_at, admitted_at)).fetchall()
    return max((_cancelled_child(db, row) for row in rows), default=None)


def validate(db):
    """Retained links only. Current permission/due checks are never cached."""
    if db.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone()[0] > MAX_RETRIES:
        raise BulkUnavailable('Retained fresh retry evidence exceeds capacity.')
    if db.execute('''SELECT 1 FROM managed_bulk_pending_retries r
        LEFT JOIN managed_bulk_attempts a ON a.id=r.attempt_id
        LEFT JOIN managed_bulk_attempts p ON p.id=r.predecessor_id
        LEFT JOIN managed_bulk_attempts o ON o.id=r.origin_id
        LEFT JOIN operation_jobs j ON j.id=a.job_id
        LEFT JOIN operation_requests q ON q.id=a.id
        LEFT JOIN managed_bulk_pending_retries previous ON previous.attempt_id=p.id
        WHERE a.id IS NULL OR p.id IS NULL OR o.id IS NULL OR j.id IS NULL OR q.id IS NULL OR p.state!='CONFIRMED_ABSENT'
          OR o.state!='CONFIRMED_ABSENT' OR a.device_id!=p.device_id OR a.ip!=p.ip
          OR a.intent_id!=p.intent_id OR a.generation!=p.generation
          OR a.authorization_request_id!=p.authorization_request_id OR a.target_revision!=p.target_revision
          OR o.device_id!=p.device_id OR o.ip!=p.ip OR o.intent_id!=p.intent_id
          OR o.generation!=p.generation OR o.authorization_request_id!=p.authorization_request_id OR o.target_revision!=p.target_revision
          OR r.admitted_at!=a.requested_at OR r.admitted_at<r.eligible_at
          OR (previous.attempt_id IS NULL AND r.origin_id!=p.id)
          OR (previous.attempt_id IS NOT NULL AND (previous.origin_id!=r.origin_id OR previous.ordinal>=r.ordinal))
          OR EXISTS(SELECT 1 FROM managed_bulk_pending_retries original WHERE original.attempt_id=o.id)
          OR EXISTS(SELECT 1 FROM managed_bulk_pending_reads read
            JOIN managed_bulk_pending_sessions session ON session.id=read.session_id
            WHERE read.snapshot_id=a.snapshot_id AND (session.device_id!=a.device_id
              OR read.started_at!=a.snapshot_started_at OR read.completed_at!=a.snapshot_at
              OR read.snapshot_digest!=r.snapshot_digest))
          OR EXISTS(SELECT 1 FROM managed_bulk_attempts other
            JOIN managed_bulk_pending_retries evidence ON evidence.attempt_id=other.id
            WHERE other.snapshot_id=a.snapshot_id AND (other.device_id!=a.device_id
              OR other.snapshot_started_at!=a.snapshot_started_at OR other.snapshot_at!=a.snapshot_at
              OR evidence.snapshot_digest!=r.snapshot_digest))
        LIMIT 1''').fetchone():
        raise BulkUnavailable('Fresh retry links are missing, cyclic or outside original managed scope.')
    try:
        for row in db.execute('SELECT * FROM managed_bulk_pending_retries'):
            for field in ('attempt_id', 'predecessor_id', 'origin_id', 'owner'):
                _uuid(row[field])
            parent = _absent(db, row['predecessor_id'])
            _absent(db, row['origin_id'])
            due = _stamp(datetime.fromisoformat(parent['completed_at']) + timedelta(seconds=_delay(row['ordinal'])))
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (row['attempt_id'],)).fetchone()
            if (row['eligible_at'] != due or _stamp(datetime.fromisoformat(row['admitted_at'])) != row['admitted_at']
                    or any(c not in '0123456789abcdef' for c in row['snapshot_digest'])):
                raise ValueError('Invalid retry time or digest')
            if attempt['snapshot_id'] == parent['confirmation_id']:
                if (attempt['snapshot_started_at'], attempt['snapshot_at'], row['snapshot_digest']) != (
                        parent['confirmation_started'], parent['confirmation_completed'], parent['confirmation_digest']):
                    raise ValueError('Mismatched original confirmation read')
            elif attempt['snapshot_started_at'] <= parent['completed_at']:
                raise ValueError('Noncausal replacement read')
            replaced_at = _previous_children(db, parent['id'], attempt['id'], row['admitted_at'])
            if replaced_at is not None and attempt['snapshot_started_at'] <= replaced_at:
                raise ValueError('Replacement read predates cancelled child')
            claims = db.execute('''SELECT timestamp FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED'
                AND device_id=? AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?''',
                (attempt['device_id'], row['owner'], row['epoch'])).fetchall()
            events = db.execute('''SELECT * FROM shun_events WHERE request_id=? AND event_type='MANAGED_BULK_RETRY_ADMITTED' ''',
                                (attempt['id'],)).fetchall()
            if len(claims) != 1 or claims[0]['timestamp'] > attempt['snapshot_started_at'] or len(events) != 1:
                raise ValueError('Missing retry visit/admission audit')
            event = events[0]
            details = json.loads(event['details_json'])
            if (event['actor_subject'] != 'system:managed-shun-policy' or event['actor_roles_json'] != '[]'
                    or event['device_id'] != attempt['device_id'] or event['ip'] != attempt['ip']
                    or event['timestamp'] != row['admitted_at'] or event['interface'] is not None
                    or details != {'operation_id': attempt['job_id'], 'predecessor_id': row['predecessor_id'],
                        'origin_id': row['origin_id'], 'ordinal': row['ordinal'], 'eligible_at': row['eligible_at'],
                        'snapshot_id': attempt['snapshot_id'], 'device_executor': {'owner': row['owner'], 'epoch': row['epoch']},
                        'proves_creation': False}):
                raise ValueError('Changed retry admission audit')
    except (ValueError, TypeError, QueueConflict) as error:
        raise BulkUnavailable('Retained fresh retry proof is invalid.') from error


def context(db, attempt, now, *, predecessor_id=None):
    """Exact narrow exception to old deferred-outcome barriers, in one transaction.

    A prospective parent is accepted only by explicit new admission. Later
    claim/cancellation checks resolve the immutable retained link instead.
    """
    if not db.in_transaction:
        raise ValueError('Fresh retry eligibility needs its owning transaction.')
    if not present(db):
        if predecessor_id is not None:
            raise BulkUnavailable('Fresh retry execution profile is unavailable.')
        return None
    retained = db.execute('SELECT * FROM managed_bulk_pending_retries WHERE attempt_id=?', (attempt['id'],)).fetchone()
    if predecessor_id is None and retained is None:
        return None
    if retained is not None:
        if predecessor_id is not None and retained['predecessor_id'] != predecessor_id:
            raise QueueConflict('Retained retry belongs to a different predecessor.')
        predecessor_id = retained['predecessor_id']
    parent = _absent(db, predecessor_id)
    if not _same_scope(attempt, parent) or attempt['id'] == parent['id'] or attempt['job_id'] == parent['job_id']:
        raise QueueConflict('Fresh retry must keep exact original intent and use new attempt/job identities.')
    origin, ordinal, due, hourly_due = retry_window(db, parent, now, retained)
    _absent(db, origin)
    if _stamp(now) < due:
        raise RetryDeferred(due, 'Confirmed-absent retry backoff has not elapsed.')
    if db.execute('SELECT 1 FROM managed_bulk_cancellations WHERE import_id=?', (parent['authorization_request_id'],)).fetchone():
        raise QueueConflict('Cancelled import cannot authorize another first-confirmation attempt.')
    # Known pre-write cancellation permits NEW IDs after a NEW causal read,
    # never replay of a sent/unknown child. Historical validation excludes later siblings.
    replaced_at = _previous_children(db, parent['id'], attempt['id'], retained['admitted_at'] if retained else None)
    if replaced_at is not None and attempt['snapshot_started_at'] <= replaced_at:
        raise QueueConflict('Replacement retry read must start after cancelled child completion.')
    same_read = attempt['snapshot_id'] == parent['confirmation_id']
    if same_read:
        if (attempt['snapshot_started_at'], attempt['snapshot_at']) != (
                parent['confirmation_started'], parent['confirmation_completed']):
            raise QueueConflict('Retry confirmation snapshot identity/times differ.')
    elif attempt['snapshot_started_at'] <= parent['completed_at']:
        raise QueueConflict('A replacement retry read must start after the predecessor result.')
    if retained is None and _stamp(now) < hourly_due:
        raise RetryDeferred(hourly_due, 'Fresh retry hourly limit reached; wait for the rolling window.')
    return {'predecessor_id': parent['id'], 'origin_id': origin, 'ordinal': ordinal, 'eligible_at': due,
            'same_read': same_read, 'confirmation_digest': parent['confirmation_digest']}


def retain(db, attempt, predecessor_id, snapshot, owner, queue):
    proof = context(db, attempt, queue._now(), predecessor_id=predecessor_id)
    digest = _digest(snapshot)
    if proof['same_read'] and digest != proof['confirmation_digest']:
        raise QueueConflict('Retry must use the exact complete first-confirmation snapshot.')
    lease = queue._executor(db, owner, snapshot.device_id)
    if db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] >= MAX_RETRIES:
        raise BulkUnavailable('Retained fresh retry evidence capacity is exhausted.')
    db.execute('INSERT INTO managed_bulk_pending_retries VALUES (?,?,?,?,?,?,?,?,?)',
               (attempt['id'], predecessor_id, proof['origin_id'], proof['ordinal'], proof['eligible_at'],
                attempt['requested_at'], digest, owner, lease['epoch']))
    queue.store._insert_event(db, 'MANAGED_BULK_RETRY_ADMITTED', attempt['device_id'], IPv4Address(attempt['ip']), None,
        'system:managed-shun-policy', 'Managed shun policy', (), attempt['id'],
        {'operation_id': attempt['job_id'], 'predecessor_id': predecessor_id, 'origin_id': proof['origin_id'],
         'ordinal': proof['ordinal'], 'eligible_at': proof['eligible_at'], 'snapshot_id': snapshot.id,
         'device_executor': {'owner': owner, 'epoch': lease['epoch']}, 'proves_creation': False}, attempt['requested_at'])


def replay(db, attempt_id, predecessor_id, snapshot):
    row = db.execute('SELECT * FROM managed_bulk_pending_retries WHERE attempt_id=?', (attempt_id,)).fetchone()
    if row is None or row['predecessor_id'] != predecessor_id or row['snapshot_digest'] != _digest(snapshot):
        raise QueueConflict('Retry key belongs to different retained predecessor/read evidence.')


class PendingRetries:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError('Fresh retry admission must use its original queue database.')
        self.store, self.queue = store, queue

    def admit(self, token, snapshot, predecessors, managed_revision, protected_revision, *,
              enabled=False, addition_device_ids=frozenset()):
        """Atomic 1..16 fresh jobs. No command, old outcome change or consent renewal."""
        _enabled(enabled)
        _token(token)
        _snapshot(snapshot)
        if (snapshot.device_id != token.device_id or type(predecessors) is not tuple
                or not 1 <= len(predecessors) <= 16 or len(set(predecessors)) != len(predecessors)):
            raise ValueError('Select 1..16 exact same-device confirmed-absent predecessors.')
        for key in predecessors:
            _uuid(key)
        with schema_connection(self.store) as db, _atomic(db):
            from .pending_execution import PendingExecution

            PendingExecution._profile(db)
            _read_identity(db, snapshot)
            candidates, parents = [], {}
            for predecessor in predecessors:
                parent = _absent(db, predecessor)
                if parent['device_id'] != token.device_id:
                    raise QueueConflict('Retry predecessor is outside this device lease.')
                candidates.append(BulkCandidate(parent['device_id'], IPv4Address(parent['ip']), parent['intent_id'],
                    parent['generation'], parent['authorization_request_id'], parent['target_revision']))
                key = str(uuid5(UUID(parent['intent_id']), snapshot.id))
                parents[key] = predecessor
            if len(parents) != len(predecessors):
                raise QueueConflict('Retry portion contains duplicate device/IP scope.')
            # Historical replay is read-only. New admission always checks this
            # current live lease, never the original settled predecessor owner.
            existing = sum(db.execute('SELECT 1 FROM managed_bulk_attempts WHERE id=?', (key,)).fetchone() is not None for key in parents)
            if existing != len(parents):
                leases = DeviceLeases(self.store, self.queue)
                leases.check(db, token)
                claims = db.execute('''SELECT timestamp FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED'
                    AND device_id=? AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?''',
                    (token.device_id, token.owner, token.epoch)).fetchall()
                if len(claims) != 1 or _stamp(snapshot.started_at) < claims[0]['timestamp']:
                    raise QueueConflict('Fresh retry read must belong to the current lease visit.')
            result = BulkDispatch(self.store, self.queue)._admit(snapshot, tuple(candidates), token.owner,
                managed_revision, protected_revision, enabled=True, addition_device_ids=addition_device_ids,
                connection=db, retry_parents=parents)
            _state(db)
            return result
