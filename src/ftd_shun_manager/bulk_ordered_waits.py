"""Explicit v2 ordered reservations/revocation only; never promotes device work."""

import hmac
import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .bulk_intent import _digest as require_digest
from .bulk_intent import _integer, _uuid
from .bulk_ordered_removals import BulkOrderedRemovalScopes, _digest, _record, _time
from .bulk_policy import (
    MAX_REQUESTS,
    BulkUnavailable,
    _actor,
    _atomic,
    _key_free,
    _quiescent,
    _state,
)
from .bulk_policy_views import BulkPolicyViews
from .bulk_removals import canonical_scope
from .device_leases import present as device_profile_present
from .managed_restoration import validate_binding
from .managed_shuns import ManagedCapacity, ManagedConflict
from .operation_queue import OperationQueue, QueueConflict, QueueFull, stamp
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

MAX_ROOTS = 10000
DOMAIN = b'ftd-shun-manager:ordered-removal:v2\n'
_PREDECESSOR_FIELDS = {'request_id', 'job_id', 'intent_id', 'generation', 'authorization_request_id',
    'target_revision', 'snapshot_id', 'snapshot_started_at', 'snapshot_at', 'requested_at', 'expires_at',
    'started_at', 'executor_owner', 'executor_epoch', 'lease_until', 'claim_event_id', 'evidence_digest'}


class OrderedReservationNotFound(KeyError):
    """An absent root, distinct from malformed retained evidence."""


DDL = """
CREATE TABLE managed_bulk_ordered_roots (
    id TEXT PRIMARY KEY REFERENCES managed_shun_requests(id),
    ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 10),
    predecessor_count INTEGER NOT NULL CHECK(predecessor_count BETWEEN 1 AND target_count),
    requested_at TEXT NOT NULL,expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('WAITING_ADD','CANCELLED','EXPIRED')),
    updated_at TEXT NOT NULL
);
CREATE TABLE managed_bulk_ordered_members (
    root_id TEXT NOT NULL REFERENCES managed_bulk_ordered_roots(id),
    device_id INTEGER NOT NULL REFERENCES devices(id),
    ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    predecessor_json TEXT,claim_json TEXT,
    job_id TEXT,claim_event_id TEXT,
    PRIMARY KEY(root_id,device_id),
    CHECK((predecessor_json IS NULL AND claim_json IS NULL AND job_id IS NULL AND claim_event_id IS NULL)
       OR (json_valid(predecessor_json) AND json_valid(claim_json) AND job_id IS NOT NULL AND claim_event_id IS NOT NULL))
);
CREATE INDEX idx_managed_bulk_ordered_pair ON managed_bulk_ordered_members(device_id,ip,root_id);
CREATE TRIGGER managed_bulk_ordered_root_identity BEFORE UPDATE OF
    id,ip,target_count,predecessor_count,requested_at,expires_at ON managed_bulk_ordered_roots
BEGIN SELECT RAISE(ABORT,'ordered authority and deadline are immutable'); END;
CREATE TRIGGER managed_bulk_ordered_root_retained BEFORE DELETE ON managed_bulk_ordered_roots
BEGIN SELECT RAISE(ABORT,'ordered receipts are retained'); END;
CREATE TRIGGER managed_bulk_ordered_root_transition BEFORE UPDATE ON managed_bulk_ordered_roots
WHEN NOT (OLD.state='WAITING_ADD' AND NEW.state IN ('CANCELLED','EXPIRED') AND NEW.updated_at>=OLD.updated_at)
BEGIN SELECT RAISE(ABORT,'ordered reservation cannot rearm or promote'); END;
CREATE TRIGGER managed_bulk_ordered_member_identity BEFORE UPDATE ON managed_bulk_ordered_members
BEGIN SELECT RAISE(ABORT,'ordered scope and captured evidence are immutable'); END;
CREATE TRIGGER managed_bulk_ordered_member_retained BEFORE DELETE ON managed_bulk_ordered_members
BEGIN SELECT RAISE(ABORT,'ordered evidence is retained'); END;
"""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def present(db):
    return db.execute("""SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_ordered_*'
        OR name GLOB 'idx_managed_bulk_ordered_*' OR tbl_name GLOB 'managed_bulk_ordered_*' LIMIT 1""").fetchone() is not None


def canonical_ordered_removal(reviewed, predecessors, ttl_seconds=900, reason=''):
    scope, scope_digest = canonical_scope(reviewed)
    _integer(ttl_seconds, 1, 900, 'ordered cleanup lifetime')
    if type(reason) is not str or len(reason) > 500 or any(ord(char) < 32 for char in reason):
        raise ValueError('Use at most 500 plain-text reason characters.')
    if type(predecessors) is not list or not 1 <= len(predecessors) <= len(reviewed['targets']):
        raise ValueError('Explicit ordered cleanup requires at least one captured RUNNING ADD.')
    targets, previous, identities = {row['device_id']: row for row in reviewed['targets']}, 0, set()
    for entry in predecessors:
        if type(entry) is not dict or set(entry) != {'device_id', 'evidence'}:
            raise ValueError('Exact ordered predecessor metadata is required.')
        _integer(entry['device_id'], previous + 1, 65535, 'ordered predecessor device')
        previous, evidence = entry['device_id'], entry['evidence']
        target = targets.get(previous)
        if (target is None or not target['maintenance_enabled'] or type(evidence) is not dict
                or set(evidence) != _PREDECESSOR_FIELDS):
            raise ValueError('Captured ADD must belong to the frozen maintained scope.')
        for field in ('request_id', 'job_id', 'intent_id', 'authorization_request_id', 'snapshot_id', 'executor_owner', 'claim_event_id'):
            _uuid(evidence[field])
        _integer(evidence['executor_epoch'], 1, 2**63 - 1, 'executor epoch')
        _integer(evidence['generation'], 1, 2**63 - 1, 'generation')
        _integer(evidence['target_revision'], 0, reviewed['managed_revision'], 'target revision')
        require_digest(evidence['evidence_digest'])
        if (any(evidence[field] != target[field] for field in ('intent_id', 'generation', 'authorization_request_id', 'target_revision'))
                or evidence['job_id'] == evidence['request_id']
                or identities.intersection((evidence['request_id'], evidence['job_id']))):
            raise ValueError('Captured identities cannot alias another predecessor or authority.')
        identities.update((evidence['request_id'], evidence['job_id']))
        for field in ('snapshot_started_at', 'snapshot_at', 'requested_at', 'expires_at', 'started_at', 'lease_until'):
            _time(evidence[field])
        if not (evidence['snapshot_started_at'] <= evidence['snapshot_at'] <= evidence['requested_at']
                <= evidence['started_at'] < min(evidence['expires_at'], evidence['lease_until'])):
            raise ValueError('Original predecessor times and deadlines are inconsistent.')
    payload = {'version': 2, 'action': 'STOP_AND_REMOVE_ORDERED', 'scope_digest': scope_digest,
               'reviewed': json.loads(scope), 'predecessors': predecessors, 'ttl_seconds': ttl_seconds, 'reason': reason.strip()}
    return _json(payload), _digest(payload, DOMAIN)


def captured(preflight):
    return [{'device_id': row['device_id'], 'evidence': row['predecessor']}
            for row in preflight['targets'] if row['predecessor'] is not None]


def _receipt(key, scope, predecessors, requested, expires):
    retired = sum(row['maintenance_enabled'] for row in scope['targets'])
    return {'operation_id': key, 'status': 'accepted', 'replayed': False, 'intent_format': 2,
            'action': 'STOP_AND_REMOVE_ORDERED', 'scope': scope['scope'], 'state': 'WAITING_ADD',
            'target_count': len(scope['targets']), 'predecessor_count': len(predecessors), 'retired_targets': retired,
            'managed_revision': scope['managed_revision'] + bool(retired), 'requested_at': requested, 'expires_at': expires,
            'cleanup_reserved': True, 'policy_only': False, 'device_work_admitted': False, 'verified_removal': False}


def validate(db):
    """Pure profile validation; no _state recursion, repair or outcome inference."""
    if db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_roots').fetchone()[0] > MAX_ROOTS:
        raise BulkUnavailable('Retained ordered reservation capacity exceeded.')
    if db.execute('''SELECT 1 FROM managed_bulk_ordered_members m LEFT JOIN managed_bulk_ordered_roots r ON r.id=m.root_id
                     WHERE r.id IS NULL OR r.ip!=m.ip LIMIT 1''').fetchone():
        raise BulkUnavailable('Ordered membership is incomplete.')
    if (db.execute('''SELECT 1 FROM managed_bulk_ordered_roots r JOIN managed_shun_requests a ON a.id=r.id
            WHERE length(a.payload_json)>65536 OR length(a.result_json)>4096 LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_ordered_members
                WHERE length(predecessor_json)>8192 OR length(claim_json)>65536 LIMIT 1''').fetchone()):
        raise BulkUnavailable('Ordered metadata exceeds its bounded descriptor capacity.')
    rows = db.execute('''SELECT r.*,a.actor_subject,a.actor_display_name,a.actor_roles_json,a.payload_json,a.result_json,
                        a.requested_at AS authority_at FROM managed_bulk_ordered_roots r
                        LEFT JOIN managed_shun_requests a ON a.id=r.id''')
    try:
        while chunk := rows.fetchmany(100):
            for root in chunk:
                _uuid(root['id'])
                payload = json.loads(root['payload_json'])
                scope, predecessors = payload['reviewed'], payload['predecessors']
                canonical, _ = canonical_ordered_removal(scope, predecessors, payload['ttl_seconds'], payload['reason'])
                _actor(root['actor_subject'], root['actor_display_name'], tuple(json.loads(root['actor_roles_json'])))
                if (canonical != root['payload_json'] or root['ip'] != IPv4Address(scope['ip']).packed
                        or root['target_count'] != len(scope['targets']) or root['predecessor_count'] != len(predecessors)
                        or _time(root['requested_at']) != root['authority_at']
                        or _time(root['updated_at']) < root['requested_at']
                        or datetime.fromisoformat(_time(root['expires_at'])) - datetime.fromisoformat(root['requested_at']) != timedelta(seconds=payload['ttl_seconds'])
                        or _json(json.loads(root['result_json'])) != _json(_receipt(root['id'], scope, predecessors, root['requested_at'], root['expires_at']))):
                    raise ValueError('Ordered root differs from its original authority.')
                members = db.execute('SELECT * FROM managed_bulk_ordered_members WHERE root_id=? ORDER BY device_id LIMIT 11', (root['id'],)).fetchall()
                expected = {entry['device_id']: entry['evidence'] for entry in predecessors}
                if [row['device_id'] for row in members] != [row['device_id'] for row in scope['targets']]:
                    raise ValueError('Ordered fleet membership changed.')
                for member in members:
                    evidence = expected.get(member['device_id'])
                    if evidence is None:
                        if any(member[field] is not None for field in ('predecessor_json', 'claim_json', 'job_id', 'claim_event_id')):
                            raise ValueError('Ready member acquired a predecessor.')
                    elif (member['predecessor_json'] != _json(evidence) or member['job_id'] != evidence['job_id']
                            or member['claim_event_id'] != evidence['claim_event_id']
                            or json.loads(member['claim_json'])['id'] != evidence['claim_event_id']):
                        raise ValueError('Captured predecessor changed.')
    except (ValueError, TypeError, KeyError, PermissionError) as error:
        raise BulkUnavailable('Ordered authority/evidence is incomplete or malformed.') from error


def held_count(db, *, subject=None, cutoff=None, exclude=None):
    from .bulk_ordered_promotion import released_filter

    if not present(db):
        return 0
    _state(db)
    if subject is not None:
        return db.execute('''SELECT COUNT(*) FROM managed_bulk_ordered_roots r JOIN managed_shun_requests a ON a.id=r.id
            WHERE a.actor_subject=? AND r.requested_at>=? AND (? IS NULL OR r.id!=?)
            AND NOT EXISTS (SELECT 1 FROM operation_requests q WHERE q.id=r.id)''', (subject, cutoff, exclude, exclude)).fetchone()[0]
    return db.execute("SELECT COUNT(*) FROM managed_bulk_ordered_roots r WHERE r.state='WAITING_ADD'" + released_filter(db)).fetchone()[0]


def held_targets(db):
    from .bulk_ordered_promotion import released_filter

    if not present(db):
        return 0
    _state(db)
    return db.execute("SELECT COALESCE(SUM(target_count),0) FROM managed_bulk_ordered_roots r WHERE r.state='WAITING_ADD'" + released_filter(db)).fetchone()[0]


def pair_held(db, device, ip):
    from .bulk_ordered_promotion import released_filter

    if not present(db):
        return False
    _state(db)
    return db.execute('''SELECT 1 FROM managed_bulk_ordered_members m JOIN managed_bulk_ordered_roots r ON r.id=m.root_id
        WHERE m.device_id=? AND m.ip=? AND r.state='WAITING_ADD' ''' + released_filter(db) + ' LIMIT 1', (device, ip.packed)).fetchone() is not None


def validate_held_predecessors(db):
    """Keep captured jobs, original requests and claims, even after revocation."""
    _state(db)
    rows = db.execute('SELECT * FROM managed_bulk_ordered_members WHERE job_id IS NOT NULL')
    while chunk := rows.fetchmany(100):
        for member in chunk:
            evidence = json.loads(member['predecessor_json'])
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (member['job_id'],)).fetchone()
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (member['job_id'],)).fetchone()
            claim = db.execute('SELECT * FROM shun_events WHERE id=?', (member['claim_event_id'],)).fetchone()
            if attempt is None or job is None or claim is None:
                raise BulkUnavailable('Captured ordered ADD evidence is missing; pruning was refused.')
            validate_binding(db, attempt, job)
            request = db.execute('SELECT expires_at FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
            if (attempt['id'] != evidence['request_id'] or request['expires_at'] != evidence['expires_at']
                    or any(attempt[field] != evidence[field] for field in ('intent_id', 'generation', 'authorization_request_id',
                        'target_revision', 'snapshot_id', 'snapshot_started_at', 'snapshot_at', 'requested_at'))
                    or _json(_record(claim)) != member['claim_json']):
                raise BulkUnavailable('Captured ordered ADD binding changed; pruning was refused.')


class BulkOrderedWaits:
    def __init__(self, store, queue):
        if store.path != queue.store.path or type(queue) is not OperationQueue:
            raise ValueError('Ordered reservations require the same base shared queue, not an executor.')
        self.store, self.queue = store, queue
        self.scopes = BulkOrderedRemovalScopes(store)

    def initialize(self, *, enabled=False, connection=None):
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Explicit ordered schema initialization is disabled.')
        self._existing()
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None or not device_profile_present(db):
                raise BulkUnavailable('Existing exact fenced v2 storage is required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db) or not state['restoration_suspended']:
                raise QueueConflict('Pause ordinary mutations and suspend desired policy before explicit migration.')
            execute_schema(db, DDL)
            _state(db)

    def _existing(self):
        if not self.store.path.is_file():
            raise BulkUnavailable('Existing ordered storage is required; no database was created.')

    def reserve(self, key, reviewed, predecessors, digest, subject, display_name, roles, *, ttl_seconds=900, reason='', enabled=False):
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Ordered reservation admission is disabled.')
        self._existing()
        with schema_connection(self.store) as db:
            return self.apply_reserve(db, key, reviewed, predecessors, digest, subject, display_name, roles,
                                      ttl_seconds=ttl_seconds, reason=reason, enabled=enabled)

    def apply_reserve(self, db, key, reviewed, predecessors, digest, subject, display_name, roles, *, ttl_seconds=900, reason='', enabled=False):
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Ordered reservation admission is disabled.')
        if not db.in_transaction:
            raise ValueError('Ordered admission requires a caller-owned write transaction.')
        _actor(subject, display_name, roles)
        _uuid(key)
        payload, expected = canonical_ordered_removal(reviewed, predecessors, ttl_seconds, reason)
        require_digest(digest)
        if not hmac.compare_digest(digest, expected):
            raise ValueError('Confirmation must match the separate exact ordered-removal action.')
        frozen = json.loads(payload)
        with _atomic(db):
            state = _state(db)
            if state is None or not present(db):
                raise BulkUnavailable('Existing ordered reservation storage is required.')
            old = db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
            if old:
                if old['actor_subject'] != subject or old['payload_json'] != payload:
                    raise ManagedConflict('Original key belongs to a different actor or exact action.')
                return {**json.loads(old['result_json']), 'replayed': True}
            _key_free(db, key)
            now, scope = self.queue._now(), frozen['reviewed']
            ip = IPv4Address(scope['ip'])
            device = scope['targets'][0]['device_id'] if scope['scope'] == 'device' else None
            current = self.scopes.read(db, ip, device_id=device, now=now)
            if (current['disposition'] != 'WAITING_ADD'
                    or canonical_ordered_removal(current['scope'], captured(current), ttl_seconds, reason)[0] != payload):
                raise ManagedConflict('Complete scope or RUNNING predecessors changed; review again, no fallback.')
            if any(pair_held(db, row['device_id'], ip) for row in scope['targets']):
                raise QueueConflict('The complete scope already has an ordered reservation.')
            if self.queue._pending_count(db) + len(scope['targets']) > 1000 or self.queue._active_request_count(db) >= 2000:
                raise QueueFull('The shared operation queue cannot reserve the entire ordered scope.')
            if self.queue._recent_request_count(db, subject, now, key) >= 10:
                raise QueueFull('At most 10 operation submissions per minute per user.')
            if (db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] >= MAX_REQUESTS
                    or db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_roots').fetchone()[0] >= MAX_ROOTS):
                raise ManagedCapacity('Retained ordered/authority capacity reached; nothing was evicted.')
            timestamp, expires = stamp(now), stamp(now + timedelta(seconds=ttl_seconds))
            result = _receipt(key, scope, frozen['predecessors'], timestamp, expires)
            for row in scope['targets']:
                if row['maintenance_enabled']:
                    db.execute('''UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=? WHERE device_id=? AND ip=?''',
                               (result['managed_revision'], timestamp, timestamp, row['device_id'], ip.packed))
                    self.store._insert_event(db, 'MANAGED_SHUN_RETIRED', row['device_id'], ip, None, subject, display_name,
                        roles, key, {'source': 'managed_v2_ordered_reservation', 'intent_id': row['intent_id'],
                                     'generation': row['generation'], 'authorization_request_id': row['authorization_request_id']}, timestamp)
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (result['managed_revision'],))
            db.execute('INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)',
                       (key, subject, display_name, json.dumps(roles), payload, _json(result), timestamp))
            db.execute("INSERT INTO managed_bulk_ordered_roots VALUES (?,?,?,?,?,?,'WAITING_ADD',?)",
                       (key, ip.packed, result['target_count'], result['predecessor_count'], timestamp, expires, timestamp))
            pending = {row['device_id']: row['evidence'] for row in frozen['predecessors']}
            for row in scope['targets']:
                evidence = pending.get(row['device_id'])
                claim = db.execute('SELECT * FROM shun_events WHERE id=?', (evidence['claim_event_id'],)).fetchone() if evidence else None
                db.execute('INSERT INTO managed_bulk_ordered_members VALUES (?,?,?,?,?,?,?)',
                    (key, row['device_id'], ip.packed, _json(evidence) if evidence else None,
                     _json(_record(claim)) if claim else None, evidence['job_id'] if evidence else None,
                     evidence['claim_event_id'] if evidence else None))
            self.store._insert_event(db, 'MANAGED_ORDERED_REMOVAL_RESERVED', None, ip, None, subject, display_name, roles, key,
                {'target_count': result['target_count'], 'predecessor_count': result['predecessor_count'],
                 'expires_at': expires, 'device_work_admitted': False}, timestamp)
            self.queue._bump(db)
            validate_held_predecessors(db)
            final = self.queue._now()
            if (not now <= final < now + timedelta(seconds=ttl_seconds)
                    or any(row['evidence']['lease_until'] <= stamp(final) or row['evidence']['expires_at'] <= stamp(final)
                           for row in frozen['predecessors'])):
                raise QueueConflict('Original delegation/lease expired or clock reversed during reservation.')
            return result

    def status(self, key):
        from .bulk_ordered_promotion import decision

        _uuid(key)
        with BulkPolicyViews(self.store)._snapshot() as db:
            _state(db)
            if not present(db):
                raise BulkUnavailable('Existing ordered storage is required.')
            row = db.execute('SELECT * FROM managed_bulk_ordered_roots WHERE id=?', (key,)).fetchone()
            if row is None:
                raise OrderedReservationNotFound('Ordered reservation not found.')
            outcomes = []
            for member in db.execute('SELECT * FROM managed_bulk_ordered_members WHERE root_id=? AND job_id IS NOT NULL ORDER BY device_id', (key,)):
                job = db.execute('SELECT state FROM operation_jobs WHERE id=?', (member['job_id'],)).fetchone()
                outcomes.append({'device_id': member['device_id'], 'job_id': member['job_id'], 'state': job['state'] if job else None,
                                 'missing_evidence': job is None})
            receipt = decision(db, key)
            if receipt is not None and receipt['state'] == 'ADMITTING':
                raise BulkUnavailable('Incomplete ordered promotion evidence is unavailable.')
            admitted = receipt is not None and receipt['state'] == 'ADMITTED'
            state = receipt['state'] if receipt is not None and row['state'] == 'WAITING_ADD' else row['state']
            original = db.execute('SELECT payload_json,actor_subject FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
            scope = json.loads(original['payload_json'])['reviewed']
            delegated = []
            result = json.loads(receipt['result_json']) if receipt else None
            if admitted:
                for reference in result['jobs']:
                    job = db.execute('SELECT state FROM operation_jobs WHERE id=?', (reference['job_id'],)).fetchone()
                    if job is None:
                        raise BulkUnavailable('Original delegated REMOVE evidence is unavailable.')
                    delegated.append({**reference, 'state': job['state']})
            return {'operation_id': key, 'intent_format': 2, 'action': 'STOP_AND_REMOVE_ORDERED',
                    'owner_subject': original['actor_subject'], 'predecessor_count': row['predecessor_count'],
                    'scope': scope, 'requested_at': row['requested_at'],
                    'state': state, 'expires_at': row['expires_at'], 'predecessors': outcomes,
                    'cleanup_jobs': delegated,
                    'verified_removal': admitted and bool(delegated) and all(job['state'] == 'VERIFIED' for job in delegated),
                    'cleanup_reserved': row['state'] == 'WAITING_ADD' and not admitted,
                    'read_only': True, 'device_work_admitted': admitted,
                    'attention': receipt is not None and receipt['state'] == 'ATTENTION',
                    'decision': result}

    def cancel(self, key, subject, display_name, roles):
        from .bulk_ordered_promotion import decision

        _uuid(key)
        _actor(subject, display_name, roles)
        self._existing()
        with schema_connection(self.store) as db, _atomic(db):
            _state(db)
            if not present(db):
                raise BulkUnavailable('Existing ordered storage is required.')
            row = db.execute('''SELECT r.*,a.actor_subject FROM managed_bulk_ordered_roots r
                                JOIN managed_shun_requests a ON a.id=r.id WHERE r.id=?''', (key,)).fetchone()
            if row is None:
                raise OrderedReservationNotFound('Ordered reservation not found.')
            if row['actor_subject'] != subject and 'Administrator' not in roles:
                raise PermissionError('Only the owner or Administrator may cancel ordered waiting.')
            receipt = decision(db, key)
            if receipt is not None and receipt['state'] in {'ADMITTING', 'ADMITTED'}:
                raise QueueConflict('Already admitted ordered work is governed by ordinary queue controls.')
            if row['state'] != 'WAITING_ADD':
                return {'operation_id': key, 'state': row['state'], 'replayed': True}
            timestamp = stamp(self.queue._now())
            if timestamp < row['updated_at']:
                raise QueueConflict('Reservation time moved backwards.')
            db.execute("UPDATE managed_bulk_ordered_roots SET state='CANCELLED',updated_at=? WHERE id=?", (timestamp, key))
            self.store._insert_event(db, 'MANAGED_ORDERED_REMOVAL_CANCELLED', None, IPv4Address(row['ip']), None,
                                     subject, display_name, roles, key, {'maintenance_resumed': False}, timestamp)
            self.queue._bump(db)
            return {'operation_id': key, 'state': 'CANCELLED', 'replayed': False}


def expire(db, store, current):
    from .bulk_ordered_promotion import present as promotion_present
    from .bulk_ordered_promotion import released_filter

    """Existing shared maintenance only; bounded local expiry, never promotion."""
    if not present(db):
        return 0
    _state(db)
    if promotion_present(db) and db.execute("SELECT 1 FROM managed_bulk_ordered_promotions WHERE state='ADMITTING' LIMIT 1").fetchone():
        raise BulkUnavailable('Incomplete ordered promotion cannot be expired or resumed automatically.')
    rows = db.execute("SELECT * FROM managed_bulk_ordered_roots r WHERE r.state='WAITING_ADD' AND r.expires_at<=?" + released_filter(db) + " ORDER BY r.expires_at,r.id LIMIT 100",
                      (stamp(current),)).fetchall()
    for row in rows:
        db.execute("UPDATE managed_bulk_ordered_roots SET state='EXPIRED',updated_at=? WHERE id=?", (stamp(current), row['id']))
        store._insert_event(db, 'MANAGED_ORDERED_REMOVAL_EXPIRED', None, IPv4Address(row['ip']), None,
            'system:operation-queue', 'Operation queue', (), row['id'], {'maintenance_resumed': False}, stamp(current))
    return len(rows)
