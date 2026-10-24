"""Whole-scope ordered promotion to the existing queue; never a device executor."""

import json
from datetime import datetime
from ipaddress import IPv4Address
from math import ceil

from .bulk_intent import _integer, _uuid
from .bulk_ordered_removals import _time
from .bulk_ordered_waits import (
    BulkOrderedWaits,
    _json,
    validate_held_predecessors,
)
from .bulk_ordered_waits import (
    present as waits_present,
)
from .bulk_policy import BulkUnavailable, _atomic, _quiescent, _state
from .bulk_policy_views import BulkPolicyViews
from .managed_restoration import ACTOR, SOURCE
from .operation_queue import QueueConflict, stamp
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

SCOPE = 'managed_v2_ordered_removal'
DDL = """
CREATE TABLE managed_bulk_ordered_promotions (
    root_id TEXT PRIMARY KEY REFERENCES managed_bulk_ordered_roots(id),
    state TEXT NOT NULL CHECK(state IN ('ADMITTING','ADMITTED','ATTENTION')),
    decided_at TEXT NOT NULL,result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TRIGGER managed_bulk_ordered_promotion_identity BEFORE UPDATE OF root_id,decided_at ON managed_bulk_ordered_promotions
BEGIN SELECT RAISE(ABORT,'ordered decision identity is immutable'); END;
CREATE TRIGGER managed_bulk_ordered_promotion_transition BEFORE UPDATE ON managed_bulk_ordered_promotions
WHEN NOT (OLD.state='ADMITTING' AND NEW.state='ADMITTED')
BEGIN SELECT RAISE(ABORT,'ordered decision cannot rearm'); END;
CREATE TRIGGER managed_bulk_ordered_promotion_retained BEFORE DELETE ON managed_bulk_ordered_promotions
BEGIN SELECT RAISE(ABORT,'ordered decisions are retained'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_ordered_promotion*' LIMIT 1").fetchone() is not None


def decision(db, key):
    return db.execute('SELECT * FROM managed_bulk_ordered_promotions WHERE root_id=?', (key,)).fetchone() if present(db) else None


def released_filter(db, alias='r'):
    # alias is internal constant SQL, never a form/protocol identifier.
    return (f" AND NOT EXISTS (SELECT 1 FROM managed_bulk_ordered_promotions p WHERE p.root_id={alias}.id AND p.state='ADMITTED')"
            if present(db) else '')


def validate(db):
    rows = db.execute('''SELECT p.*,r.requested_at,r.expires_at,r.state AS root_state,a.payload_json,a.actor_subject,
        a.actor_display_name,a.actor_roles_json FROM managed_bulk_ordered_promotions p
        LEFT JOIN managed_bulk_ordered_roots r ON r.id=p.root_id
        LEFT JOIN managed_shun_requests a ON a.id=p.root_id''')
    try:
        while chunk := rows.fetchmany(100):
            for row in chunk:
                _uuid(row['root_id'])
                if (row['requested_at'] is None or _time(row['decided_at']) < row['requested_at']
                        or len(row['result_json']) > 8192):
                    raise ValueError('Invalid ordered decision.')
                result = json.loads(row['result_json'])
                if row['state'] == 'ADMITTING':
                    if row['root_state'] != 'WAITING_ADD' or result != {}:
                        raise ValueError('Invalid internal admission ticket.')
                elif row['state'] == 'ATTENTION':
                    if (type(result) is not dict or set(result) != {'reason'} or result['reason'] not in {
                            'EVIDENCE_UNAVAILABLE', 'ADD_FAILED_OR_UNKNOWN', 'FENCE_UNSAFE', 'SCOPE_CHANGED', 'ADMISSION_CONFLICT'}):
                        raise ValueError('Invalid retained attention reason.')
                else:
                    if row['root_state'] != 'WAITING_ADD' or row['decided_at'] >= row['expires_at']:
                        raise ValueError('An admitted root cannot be revoked as waiting.')
                    _validate_admitted(db, row, result)
    except (ValueError, TypeError, KeyError) as error:
        raise BulkUnavailable('Ordered promotion authority/receipt is unavailable.') from error


def _validate_admitted(db, row, result):
    scope = json.loads(row['payload_json'])['reviewed']
    expected_devices = [target['device_id'] for target in scope['targets']]
    if (type(result) is not dict or set(result) != {'jobs', 'requested_at', 'expires_at'}
            or result['requested_at'] != row['requested_at'] or result['expires_at'] != row['expires_at']
            or type(result['jobs']) is not list or len(result['jobs']) != len(expected_devices)):
        raise ValueError('Invalid complete ordered delegation receipt.')
    for entry in result['jobs']:
        if type(entry) is not dict or set(entry) != {'device_id', 'job_id'}:
            raise ValueError('Exact delegated job identities are required.')
        _integer(entry['device_id'], 1, 65535, 'delegated device')
        _uuid(entry['job_id'])
    if ([entry['device_id'] for entry in result['jobs']] != expected_devices
            or len({entry['job_id'] for entry in result['jobs']}) != len(expected_devices)):
        raise ValueError('Partial or repeated ordered delegation.')
    request = db.execute('SELECT * FROM operation_requests WHERE id=?', (row['root_id'],)).fetchone()
    expected_payload = {'scope': SCOPE, 'targets': [[device, scope['ip']] for device in expected_devices]}
    if (request is None or request['source'] != 'manual' or request['actor_subject'] != row['actor_subject']
            or request['actor_display_name'] != row['actor_display_name']
            or request['actor_roles_json'] != row['actor_roles_json']
            or json.loads(request['payload_json']) != expected_payload
            or request['requested_at'] != row['requested_at'] or request['expires_at'] != row['expires_at']):
        raise ValueError('Original ordered delegation changed or is missing.')
    jobs = db.execute('''SELECT j.* FROM operation_jobs j JOIN operation_links l ON l.job_id=j.id
        WHERE l.request_id=? ORDER BY j.device_id LIMIT 11''', (row['root_id'],)).fetchall()
    if ([{'device_id': job['device_id'], 'job_id': job['id']} for job in jobs] != result['jobs']
            or any(job['action'] != 'REMOVE' or job['ip'] != IPv4Address(scope['ip']).packed for job in jobs)):
        raise ValueError('Original ordered cleanup jobs changed or are missing.')


def queue_scope(db, key, targets, subject, source, scope, now):
    """Only a current private whole-scope ticket may transfer reserved capacity."""
    state = _state(db)
    ticket = decision(db, key)
    if state is None or ticket is None or ticket['state'] != 'ADMITTING' or source != 'manual' or scope != SCOPE:
        raise QueueConflict('Ordered queue transfer requires its exact internal admission ticket.')
    root = db.execute('''SELECT r.*,a.actor_subject,a.payload_json FROM managed_bulk_ordered_roots r
        JOIN managed_shun_requests a ON a.id=r.id WHERE r.id=?''', (key,)).fetchone()
    frozen = json.loads(root['payload_json'])['reviewed']
    expected = [(target['device_id'], IPv4Address(frozen['ip'])) for target in frozen['targets']]
    if (root['state'] != 'WAITING_ADD' or subject != root['actor_subject'] or targets != expected
            or any(type(device) is not int or type(ip) is not IPv4Address for device, ip in targets)
            or not root['requested_at'] <= stamp(now) < root['expires_at']
            or db.execute('SELECT 1 FROM operation_requests WHERE id=?', (key,)).fetchone()):
        raise QueueConflict('Ordered transfer cannot change actor, scope, original deadline or queue identity.')
    return root


def require_claim(db, request, job):
    """An incomplete/persisted ticket cannot send even a single device command."""
    if not waits_present(db):
        return
    root = db.execute('SELECT 1 FROM managed_bulk_ordered_roots WHERE id=?', (request['id'],)).fetchone()
    if root is None:
        return
    _state(db)
    receipt = decision(db, request['id'])
    if (receipt is None or receipt['state'] != 'ADMITTED' or job['action'] != 'REMOVE'
            or job['id'] not in {entry['job_id'] for entry in json.loads(receipt['result_json'])['jobs']}):
        raise QueueConflict('Only a complete ADMITTED ordered delegation may claim device work.')


def _deferral(db, evidence, member, now):
    rows = db.execute("""SELECT * FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_DEFERRED'
        ORDER BY id LIMIT 2""", (evidence['request_id'],)).fetchall()
    if len(rows) != 1 or len(rows[0]['details_json']) > 16384:
        raise QueueConflict('Exact original pre-write deferral evidence is required.')
    event, details = rows[0], json.loads(rows[0]['details_json'])
    if (type(details) is not dict or details.get('write_sent') is not False or details.get('action') != 'ADD'
            or details.get('operation_id') != evidence['job_id'] or event['device_id'] != member['device_id']
            or event['ip'] != member['ip'] or not evidence['started_at'] <= _time(event['timestamp']) <= stamp(now)
            or event['actor_subject'] != ACTOR or json.loads(event['actor_roles_json']) != []
            or details.get('source') != SOURCE or type(details.get('device_executor')) is not dict
            or type(details['device_executor'].get('epoch')) is not int
            or details.get('device_executor') != {'owner': evidence['executor_owner'], 'epoch': evidence['executor_epoch']}):
        raise QueueConflict('Pre-write deferral is not bound to the captured original command.')


class BulkOrderedPromoter:
    def __init__(self, store, queue):
        self.waits = BulkOrderedWaits(store, queue)
        self.store, self.queue = store, queue

    def require_storage(self):
        with BulkPolicyViews(self.store)._snapshot() as db:
            _state(db)
            if not present(db) or db.execute("SELECT 1 FROM managed_bulk_ordered_promotions WHERE state='ADMITTING' LIMIT 1").fetchone():
                raise BulkUnavailable('Existing complete ordered promotion storage is required.')

    def initialize(self, *, enabled=False, connection=None):
        if type(enabled) is not bool or not enabled:
            raise PermissionError('Explicit ordered promotion migration is disabled.')
        self.waits._existing()
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None or not waits_present(db):
                raise BulkUnavailable('Existing exact ordered reservation storage is required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db) or not state['restoration_suspended']:
                raise QueueConflict('Pause and suspend desired policy before explicit promotion migration.')
            execute_schema(db, DDL)
            _state(db)

    def advance(self, *, enabled=False, limit=8):
        if type(enabled) is not bool:
            raise ValueError('Ordered promotion capability must be a literal boolean.')
        if not enabled:
            return 0
        _integer(limit, 1, 8, 'ordered promotion sweep limit')
        self.waits._existing()
        logs, changed = [], 0
        with schema_connection(self.store) as db, _atomic(db):
            _state(db)
            if not present(db):
                raise BulkUnavailable('Existing promotion storage is required; nothing was initialized.')
            if db.execute("SELECT 1 FROM managed_bulk_ordered_promotions WHERE state='ADMITTING' LIMIT 1").fetchone():
                raise BulkUnavailable('An incomplete admission ticket cannot be resumed automatically.')
            if mutations_suspended(db):
                return 0
            roots = db.execute('''SELECT r.*,a.payload_json,a.actor_subject,a.actor_display_name,a.actor_roles_json
                FROM managed_bulk_ordered_roots r JOIN managed_shun_requests a ON a.id=r.id
                WHERE r.state='WAITING_ADD' AND NOT EXISTS (
                    SELECT 1 FROM managed_bulk_ordered_promotions p WHERE p.root_id=r.id)
                AND r.expires_at>? ORDER BY r.requested_at,r.id LIMIT ?''', (stamp(self.queue._now()), limit + 10)).fetchall()
            for root in roots:
                if changed >= limit:
                    break
                now = self.queue._now()
                if stamp(now) < root['updated_at']:
                    raise QueueConflict('Ordered coordination clock moved backwards.')
                if root['expires_at'] <= stamp(now):
                    # Existing shared maintenance owns expiry; never promote or renew here.
                    continue
                db.execute('SAVEPOINT ordered_promotion')
                try:
                    pending = self._barrier(db, root, now)
                    if pending is None:
                        continue
                    for job in pending:
                        self.queue._finish(db, job, 'CANCELLED', 'Captured exact pre-write deferral superseded by ordered cleanup')
                    db.execute("INSERT INTO managed_bulk_ordered_promotions VALUES (?,'ADMITTING',?,'{}')", (root['id'], stamp(now)))
                    scope = json.loads(root['payload_json'])['reviewed']
                    targets = [(row['device_id'], IPv4Address(scope['ip'])) for row in scope['targets']]
                    remaining = ceil((datetime.fromisoformat(root['expires_at']) - now).total_seconds())
                    result, entries = self.queue.apply_enqueue(db, root['id'], targets, root['actor_subject'],
                        root['actor_display_name'], tuple(json.loads(root['actor_roles_json'])), remaining, 'manual', SCOPE,
                        bulk_ordered_removal_enabled=True)
                    if result['replayed']:
                        raise QueueConflict('An ordered transfer cannot adopt an earlier queue receipt.')
                    db.execute('UPDATE operation_requests SET requested_at=?,expires_at=? WHERE id=?',
                               (root['requested_at'], root['expires_at'], root['id']))
                    jobs = db.execute('''SELECT j.id,j.device_id FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                        WHERE l.request_id=? ORDER BY j.device_id''', (root['id'],)).fetchall()
                    receipt = {'requested_at': root['requested_at'], 'expires_at': root['expires_at'],
                               'jobs': [{'device_id': job['device_id'], 'job_id': job['id']} for job in jobs]}
                    db.execute("UPDATE managed_bulk_ordered_promotions SET state='ADMITTED',result_json=? WHERE root_id=?",
                               (_json(receipt), root['id']))
                    self._event(db, root, 'MANAGED_ORDERED_REMOVAL_ADMITTED', {'target_count': len(targets), 'verified_removal': False}, stamp(now))
                    _state(db)
                    final = self.queue._now()
                    if not now <= final or stamp(final) >= root['expires_at']:
                        raise QueueConflict('Original cleanup deadline expired or clock reversed during promotion.')
                    for target in scope['targets']:
                        fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (target['device_id'],)).fetchone()
                        if (fence['updated_at'] > stamp(final) or fence['state'] == 'ATTENTION'
                                or (fence['state'] == 'LEASED' and fence['lease_until'] <= stamp(final))):
                            raise QueueConflict('Device fence expired during promotion.')
                except (ValueError, TypeError, KeyError, PermissionError):
                    db.execute('ROLLBACK TO ordered_promotion')
                    timestamp = stamp(self.queue._now())
                    if timestamp < root['updated_at']:
                        raise QueueConflict('Ordered coordination clock moved backwards.')
                    self._attention(db, root, 'ADMISSION_CONFLICT', timestamp)
                else:
                    logs.extend(entries)
                finally:
                    db.execute('RELEASE ordered_promotion')
                changed += 1
            if changed:
                self.queue._bump(db)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return changed

    def _event(self, db, root, event, details, timestamp):
        self.store._insert_event(db, event, None, IPv4Address(root['ip']), None, root['actor_subject'],
            root['actor_display_name'], tuple(json.loads(root['actor_roles_json'])), root['id'], details, timestamp)

    def _attention(self, db, root, reason, timestamp):
        db.execute("INSERT INTO managed_bulk_ordered_promotions VALUES (?,'ATTENTION',?,?)",
                   (root['id'], timestamp, _json({'reason': reason})))
        self._event(db, root, 'MANAGED_ORDERED_REMOVAL_ATTENTION', {'reason': reason, 'device_work_admitted': False}, timestamp)

    def _barrier(self, db, root, now):
        """None waits; returned unsent jobs may be cancelled inside this transaction."""
        validate_held_predecessors(db)
        scope = json.loads(root['payload_json'])['reviewed']
        protected = db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0]
        if protected != scope['protected_revision']:
            raise QueueConflict('Frozen protection changed.')
        # New observations must not silently expand a frozen fleet.
        if scope['scope'] == 'fleet':
            observed = {row[0] for row in db.execute('''SELECT DISTINCT device_id FROM shun_state WHERE ip=? AND active=1
                UNION SELECT device_id FROM managed_shun_targets WHERE ip=? AND enabled=1 LIMIT 11''', (root['ip'], root['ip']))}
            if not observed <= {row['device_id'] for row in scope['targets']}:
                raise QueueConflict('Frozen fleet membership expanded.')
        pending, waiting = [], False
        retired_revision = scope['managed_revision'] + bool(any(row['maintenance_enabled'] for row in scope['targets']))
        members = {row['device_id']: row for row in db.execute('SELECT * FROM managed_bulk_ordered_members WHERE root_id=?', (root['id'],))}
        for target in scope['targets']:
            device, member = target['device_id'], members[target['device_id']]
            current = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?', (device, root['ip'])).fetchone()
            inventory = db.execute('SELECT enabled,hostname FROM devices WHERE id=?', (device,)).fetchone()
            fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device,)).fetchone()
            if (inventory is None or not inventory['enabled'] or inventory['hostname'] != target['hostname']
                    or fence is None or fence['state'] == 'ATTENTION' or fence['updated_at'] > stamp(now)
                    or (fence['state'] == 'LEASED' and fence['lease_until'] <= stamp(now))
                    or (current is not None and current['enabled'])
                    or (target['intent_id'] is not None and (current is None or any(current[field] != target[field]
                        for field in ('intent_id', 'generation', 'authorization_request_id'))
                        or current['revision'] != (retired_revision if target['maintenance_enabled'] else target['target_revision'])))):
                raise QueueConflict('Device fence, inventory or retired authority changed.')
            if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT') LIMIT 1", (device,)).fetchone()
                    or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED' LIMIT 1", (device,)).fetchone()):
                raise QueueConflict('Device outcome remains unknown.')
            if member['job_id'] is not None:
                evidence = json.loads(member['predecessor_json'])
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (member['job_id'],)).fetchone()
                if job['state'] in {'FAILED', 'UNVERIFIED', 'RECONCILED_ABSENT'}:
                    raise QueueConflict('Captured ADD failed or remains unknown.')
                if job['state'] == 'RUNNING':
                    waiting = True
                elif job['state'] in {'QUEUED', 'CANCELLED'}:
                    _deferral(db, evidence, member, now)
                    if job['dispatch_kind'] is not None or job['started_at'] is not None:
                        raise QueueConflict('Deferred job still has sent-command metadata.')
                    if job['state'] == 'QUEUED':
                        pending.append(job)
                elif job['state'] not in {'VERIFIED', 'NOOP'}:
                    raise QueueConflict('Captured ADD has no qualifying original result.')
                if fence['epoch'] < evidence['executor_epoch']:
                    raise QueueConflict('Captured executor epoch regressed.')
                if fence['epoch'] == evidence['executor_epoch'] and fence['state'] != 'IDLE':
                    waiting = True
            if db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING')
                    AND (? IS NULL OR id!=?) LIMIT 1""", (device, root['ip'], member['job_id'], member['job_id'])).fetchone():
                raise QueueConflict('Independent pending work changed the frozen scope.')
            if (db.execute("""SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=?
                    AND state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED') AND (? IS NULL OR job_id!=?) LIMIT 1""",
                    (device, root['ip'], member['job_id'], member['job_id'])).fetchone()
                    or db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND action='ADD'
                        AND state='FAILED' AND (? IS NULL OR id!=?) LIMIT 1""",
                        (device, root['ip'], member['job_id'], member['job_id'])).fetchone()):
                raise QueueConflict('Independent ADD evidence conflicts with the frozen scope.')
        return None if waiting else pending
