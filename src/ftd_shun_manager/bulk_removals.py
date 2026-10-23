"""V2 local scope reads and default-disabled atomic ready-only queue admission."""

import hashlib
import hmac
import json
from datetime import timedelta
from ipaddress import IPv4Address

from .bulk_intent import _integer, _uuid
from .bulk_policy import MAX_KEYS, MAX_REQUESTS, BulkUnavailable, _actor, _key_free, _state
from .bulk_policy_views import BulkPolicyViews
from .device_leases import present as device_profile_present
from .managed_shuns import ManagedCapacity, ManagedConflict
from .operation_queue import OperationQueue, QueueConflict, stamp
from .safety import mutations_suspended
from .schema import schema_connection

SCOPE = 'managed_v2_ready_removal'
_FIELDS = {'version', 'scope', 'ip', 'managed_revision', 'protected_revision', 'protected', 'targets'}
_TARGET_FIELDS = {'device_id', 'hostname', 'device_enabled', 'observed_present', 'maintenance_enabled',
                  'intent_id', 'generation', 'authorization_request_id', 'target_revision'}


def canonical_scope(reviewed):
    """Validate literal bounded metadata; neither observation freshness nor consent."""
    if (type(reviewed) is not dict or set(reviewed) != _FIELDS or type(reviewed['version']) is not int
            or reviewed['version'] != 2 or type(reviewed['scope']) is not str or reviewed['scope'] not in {'device', 'fleet'}
            or type(reviewed['ip']) is not str or str(IPv4Address(reviewed['ip'])) != reviewed['ip']
            or type(reviewed['protected']) is not bool):
        raise ValueError('An exact version-2 removal scope is required.')
    for field in ('managed_revision', 'protected_revision'):
        _integer(reviewed[field], 0, 2**63 - 1, field)
    targets = reviewed['targets']
    if type(targets) is not list or not 1 <= len(targets) <= (1 if reviewed['scope'] == 'device' else 10):
        raise ValueError('Select one device or the complete bounded fleet for one IP.')
    previous = 0
    for row in targets:
        if type(row) is not dict or set(row) != _TARGET_FIELDS:
            raise ValueError('Complete exact target metadata is required.')
        _integer(row['device_id'], previous + 1, 65535, 'ordered device ID')
        previous = row['device_id']
        if (type(row['hostname']) is not str or not 1 <= len(row['hostname']) <= 255
                or any(ord(char) < 32 for char in row['hostname'])
                or any(type(row[field]) is not bool for field in ('device_enabled', 'observed_present', 'maintenance_enabled'))):
            raise ValueError('Literal device metadata and policy/observation flags are required.')
        if row['intent_id'] is None:
            if (row['maintenance_enabled'] or any(row[field] is not None for field in
                    ('generation', 'authorization_request_id', 'target_revision'))):
                raise ValueError('Missing authority cannot be interpreted as managed policy.')
        else:
            _uuid(row['intent_id'])
            _uuid(row['authorization_request_id'])
            _integer(row['generation'], 1, 2**63 - 1, 'generation')
            _integer(row['target_revision'], 0, reviewed['managed_revision'], 'target revision')
    canonical = json.dumps(reviewed, sort_keys=True, separators=(',', ':'))
    return canonical, hashlib.sha256(b'ftd-shun-manager:removal-scope:v2\n' + canonical.encode()).hexdigest()


def canonical_removal(reviewed, ttl_seconds=900, reason=''):
    canonical, scope_digest = canonical_scope(reviewed)
    _integer(ttl_seconds, 1, 900, 'removal lifetime')
    if type(reason) is not str or len(reason) > 500 or any(ord(char) < 32 for char in reason):
        raise ValueError('Use at most 500 plain-text reason characters.')
    payload = json.dumps({'version': 2, 'action': 'STOP_AND_REMOVE_READY', 'scope_digest': scope_digest,
                          'reviewed': json.loads(canonical), 'ttl_seconds': ttl_seconds, 'reason': reason.strip()},
                         sort_keys=True, separators=(',', ':'))
    return payload, hashlib.sha256(b'ftd-shun-manager:ready-removal:v2\n' + payload.encode()).hexdigest()


class BulkRemovalScopes:
    def __init__(self, store):
        self.store = store
        self.views = BulkPolicyViews(store)

    def snapshot(self, ip, *, device_id=None):
        with self.views._snapshot() as db:
            scope = self.read(db, ip, device_id=device_id)
            return {**scope, 'scope_digest': canonical_scope(scope)[1], 'read_only': True,
                    'execution_available': False, 'device_work_admitted': False}

    @staticmethod
    def read(db, ip, *, device_id=None):
        if not db.in_transaction or type(ip) is not IPv4Address:
            raise ValueError('An exact IPv4 and caller-owned snapshot are required.')
        if device_id is not None:
            _integer(device_id, 1, 65535, 'device ID')
        state = _state(db)
        if state is None:
            raise BulkUnavailable('Existing version-2 policy is required; no storage was initialized.')
        # LIMIT detects overflow before materializing an unbounded fleet. Several
        # interfaces on a device remain a single target; timestamps are not scope.
        rows = db.execute('''SELECT d.id AS device_id,d.hostname,d.enabled AS device_enabled,
                t.intent_id,t.generation,t.authorization_request_id,t.revision AS target_revision,
                COALESCE(t.enabled,0) AS maintenance_enabled,
                EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=d.id AND s.ip=? AND s.active=1) AS observed_present
            FROM devices d LEFT JOIN managed_shun_targets t ON t.device_id=d.id AND t.ip=?
            WHERE (? IS NOT NULL AND d.id=? AND (t.device_id IS NOT NULL OR EXISTS(
                SELECT 1 FROM shun_state s WHERE s.device_id=d.id AND s.ip=? AND s.active=1)))
              OR (? IS NULL AND (t.enabled=1 OR EXISTS(
                SELECT 1 FROM shun_state s WHERE s.device_id=d.id AND s.ip=? AND s.active=1)))
            ORDER BY d.id LIMIT 11''', (ip.packed, ip.packed, device_id, device_id, ip.packed, device_id, ip.packed)).fetchall()
        # A missing inventory row must not silently shrink an observed scope.
        if db.execute('''SELECT 1 FROM shun_state s LEFT JOIN devices d ON d.id=s.device_id
                WHERE s.ip=? AND s.active=1 AND d.id IS NULL AND (? IS NULL OR s.device_id=?) LIMIT 1''',
                (ip.packed, device_id, device_id)).fetchone():
            raise BulkUnavailable('Observed removal scope is missing its device metadata.')
        if not rows or len(rows) > 10:
            raise ManagedConflict('Removal scope is empty or exceeds ten devices; nothing was truncated.')
        protection = db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()
        if protection is None:
            raise BulkUnavailable('Protection revision is unavailable.')
        entries = []
        for row in rows:
            entry = dict(row)
            for field in ('device_enabled', 'maintenance_enabled', 'observed_present'):
                if type(entry[field]) is not int or entry[field] not in (0, 1):
                    raise BulkUnavailable('Invalid device/target metadata; no false state was inferred.')
                entry[field] = bool(entry[field])
            entries.append(entry)
        scope = {'version': 2, 'scope': 'fleet' if device_id is None else 'device', 'ip': str(ip),
                 'managed_revision': state['revision'], 'protected_revision': protection[0],
                 'protected': db.execute('SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1', (ip.packed,)).fetchone() is not None,
                 'targets': entries}
        canonical_scope(scope)
        return scope


def require_ready_queue_scope(db, targets, scope):
    """Narrow guard for an explicit trusted composition capability, not a label."""
    state = _state(db)
    if state is None or not device_profile_present(db) or scope != SCOPE:
        raise QueueConflict('Ready removal requires existing exact fenced v2 storage and its fixed scope.')
    if (not 1 <= len(targets) <= 10 or len({ip for _, ip in targets}) != 1
            or len({device for device, _ in targets}) != len(targets)):
        raise ValueError('Ready removal requires distinct devices and one exact IP.')
    for device, ip in targets:
        if db.execute('SELECT 1 FROM managed_shun_targets WHERE device_id=? AND ip=? AND enabled=1',
                      (device, ip.packed)).fetchone():
            raise QueueConflict('Retire the exact managed scope atomically before ready removal admission.')


def _require_ready_fence(db, device_id, current):
    fence = db.execute('SELECT state,lease_until FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()
    if (fence is None or fence['state'] == 'ATTENTION'
            or (fence['state'] == 'LEASED' and fence['lease_until'] <= stamp(current))):
        raise QueueConflict('Every target must be inside the sealed scope and free of unresolved device fences.')


class BulkRemovals:
    def __init__(self, store, queue):
        if store.path != queue.store.path or type(queue) is not OperationQueue:
            raise ValueError('Ready admission requires the same ordinary shared queue, not a device executor.')
        self.store, self.queue = store, queue

    def admit(self, key, reviewed, digest, subject, display_name, roles, *, ttl_seconds=900, reason='', enabled=False):
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Version-2 ready removal admission is disabled.')
        if not self.store.path.is_file():
            raise BulkUnavailable('Existing fenced storage is required; no database was created.')
        with schema_connection(self.store) as db:
            result, logs = self.apply_admit(db, key, reviewed, digest, subject, display_name, roles,
                                          ttl_seconds=ttl_seconds, reason=reason, enabled=enabled)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return result

    def apply_admit(self, db, key, reviewed, digest, subject, display_name, roles, *, ttl_seconds=900, reason='', enabled=False):
        """One savepoint-protected scope; caller owns commit and accepted logs."""
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Version-2 ready removal admission is disabled.')
        if not db.in_transaction:
            raise ValueError('Ready admission requires a caller-owned write transaction.')
        _actor(subject, display_name, roles)
        _uuid(key)
        payload, expected = canonical_removal(reviewed, ttl_seconds, reason)
        if type(digest) is not str or not digest.isascii() or not hmac.compare_digest(digest, expected):
            raise ValueError('Confirmation must match the exact version-2 ready-removal action.')
        # Freeze caller-owned containers before any durable changes.
        frozen = json.loads(payload)['reviewed']
        db.execute('SAVEPOINT bulk_ready_removal')
        try:
            result, logs = self._apply(db, key, frozen, payload, subject, display_name, roles, ttl_seconds, reason.strip())
        except Exception:
            db.execute('ROLLBACK TO bulk_ready_removal')
            db.execute('RELEASE bulk_ready_removal')
            raise
        db.execute('RELEASE bulk_ready_removal')
        return result, logs

    def _apply(self, db, key, scope, payload, subject, display_name, roles, ttl, reason):
        state = _state(db)
        if state is None or not device_profile_present(db):
            raise BulkUnavailable('Existing exact fenced v2 storage is required.')
        old = db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
        if old:
            if old['actor_subject'] != subject or old['payload_json'] != payload:
                raise ManagedConflict('Original key belongs to another actor or action/scope.')
            return {**json.loads(old['result_json']), 'replayed': True}, []
        _key_free(db, key)
        if mutations_suspended(db):
            raise QueueConflict('Device mutations are suspended; no removal was admitted.')
        ip = IPv4Address(scope['ip'])
        device = scope['targets'][0]['device_id'] if scope['scope'] == 'device' else None
        current = BulkRemovalScopes.read(db, ip, device_id=device)
        if canonical_scope(current)[0] != canonical_scope(scope)[0]:
            raise ManagedConflict('Removal scope changed; inspect and review the complete current scope.')
        now = self.queue._now()
        pairs = [(row['device_id'], ip) for row in current['targets']]
        for row in current['targets']:
            _require_ready_fence(db, row['device_id'], now)
            if not row['device_enabled']:
                raise QueueConflict('Every target must be enabled; use policy-only retirement separately.')
            if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING') LIMIT 1",
                           (row['device_id'], ip.packed)).fetchone()
                    or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED') LIMIT 1",
                                  (row['device_id'], ip.packed)).fetchone()
                    or db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND action='ADD' AND state='FAILED' LIMIT 1",
                                  (row['device_id'], ip.packed)).fetchone()
                    or db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT') LIMIT 1", (row['device_id'],)).fetchone()
                    or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED' LIMIT 1", (row['device_id'],)).fetchone()):
                raise QueueConflict('Ready-only scope has pending or unresolved work; no waiting, replay or partial removal was admitted.')
        retiring = [row for row in current['targets'] if row['maintenance_enabled']]
        count = db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0]
        if count >= MAX_REQUESTS or (not retiring and count >= MAX_REQUESTS - MAX_KEYS):
            raise ManagedCapacity('Retained ledger is full or reserved for actual policy revocation.')
        revision, timestamp = state['revision'] + bool(retiring), stamp(now)
        for row in retiring:
            db.execute('''UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=?
                WHERE device_id=? AND ip=?''', (revision, timestamp, timestamp, row['device_id'], ip.packed))
        if retiring:
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (revision,))
        result, logs = self.queue.apply_enqueue(db, key, pairs, subject, display_name, roles,
            ttl, 'manual', SCOPE, bulk_removal_enabled=True)
        # Queue admission may take time; never slide the original delegation
        # forward because a later internal clock sample created the request.
        db.execute('UPDATE operation_requests SET expires_at=? WHERE id=?',
                   (stamp(now + timedelta(seconds=ttl)), key))
        if result['replayed']:
            raise ManagedConflict('Queue key was already used without its immutable ready-removal receipt.')
        jobs = db.execute('''SELECT j.id,j.device_id FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                             WHERE l.request_id=? ORDER BY j.device_id''', (key,)).fetchall()
        if len(jobs) != len(pairs) or any(row['id'] == key for row in jobs):
            raise BulkUnavailable('Exact queue delegation was not retained; no partial receipt was saved.')
        result = {**result, 'intent_format': 2, 'action': 'STOP_AND_REMOVE_READY', 'scope': scope['scope'],
                  'target_count': len(pairs), 'retired_targets': len(retiring), 'managed_revision': revision,
                  'policy_only': False, 'device_work_admitted': True, 'verified_removal': False,
                  'expires_at': stamp(now + timedelta(seconds=ttl)),
                  'jobs': [{'device_id': row['device_id'], 'job_id': row['id']} for row in jobs]}
        db.execute('INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)',
                   (key, subject, display_name, json.dumps(roles), payload, json.dumps(result), timestamp))
        for row in retiring:
            self.store._insert_event(db, 'MANAGED_SHUN_RETIRED', row['device_id'], ip, None, subject, display_name,
                roles, key, {'source': SCOPE, 'intent_id': row['intent_id'], 'generation': row['generation'],
                             'authorization_request_id': row['authorization_request_id'], 'managed_revision': revision}, timestamp)
        self.store._insert_event(db, 'MANAGED_READY_REMOVAL_ADMITTED', None, ip, None, subject, display_name, roles,
            key, {'source': SCOPE, 'target_count': len(pairs), 'retired_targets': len(retiring),
                  'managed_revision': revision, 'verified_removal': False}, timestamp)
        _state(db)
        for device_id, _ in pairs:
            _require_ready_fence(db, device_id, self.queue._now())
        request = db.execute('SELECT requested_at,expires_at FROM operation_requests WHERE id=?', (key,)).fetchone()
        completed = self.queue._now()
        if (not now <= completed < now + timedelta(seconds=ttl)
                or not timestamp <= request['requested_at'] <= stamp(completed) < request['expires_at']):
            raise QueueConflict('Delegation expired or clock moved backwards during admission; nothing was committed.')
        return result, logs
