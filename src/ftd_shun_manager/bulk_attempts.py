"""Bulk evidence capture/shared results only; no admission or dispatch authority."""

import json
from datetime import timedelta
from ipaddress import IPv4Address

from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _atomic, _quiescent, _state
from .import_preparations import _stamp
from .operation_queue import QueueConflict
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

MAX_ATTEMPTS = 1000000
DDL = """
CREATE TABLE managed_bulk_attempts (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id), ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    intent_id TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=1),
    authorization_request_id TEXT NOT NULL REFERENCES managed_shun_requests(id),
    target_revision INTEGER NOT NULL CHECK(target_revision>=0),
    snapshot_id TEXT NOT NULL, snapshot_started_at TEXT NOT NULL, snapshot_at TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED')),
    completed_at TEXT, occurrence_id TEXT, interface TEXT,
    UNIQUE(intent_id,snapshot_id),
    CHECK((state IN ('QUEUED','RUNNING'))=(completed_at IS NULL)),
    CHECK((state='VERIFIED' AND occurrence_id IS NOT NULL AND interface IS NOT NULL)
       OR (state!='VERIFIED' AND occurrence_id IS NULL AND interface IS NULL))
);
CREATE INDEX idx_managed_bulk_attempt_pair ON managed_bulk_attempts(device_id,ip,requested_at);
CREATE TRIGGER managed_bulk_attempt_capture BEFORE INSERT ON managed_bulk_attempts
WHEN NEW.state!='RUNNING' OR NEW.completed_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'only current pre-send RUNNING evidence may be captured'); END;
CREATE TRIGGER managed_bulk_attempt_identity BEFORE UPDATE OF
    id,job_id,device_id,ip,intent_id,generation,authorization_request_id,target_revision,
    snapshot_id,snapshot_started_at,snapshot_at,requested_at ON managed_bulk_attempts
BEGIN SELECT RAISE(ABORT,'bulk attempt authority is immutable'); END;
CREATE TRIGGER managed_bulk_attempt_retained BEFORE DELETE ON managed_bulk_attempts
BEGIN SELECT RAISE(ABORT,'bulk attempt evidence is retained'); END;
CREATE TRIGGER managed_bulk_attempt_terminal BEFORE UPDATE ON managed_bulk_attempts
WHEN OLD.state IN ('VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED')
BEGIN SELECT RAISE(ABORT,'settled bulk attempt is immutable'); END;
CREATE TRIGGER managed_bulk_attempt_monotonic BEFORE UPDATE OF state ON managed_bulk_attempts
WHEN NOT ((OLD.state='RUNNING' AND NEW.state IN ('QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED'))
    OR (OLD.state='QUEUED' AND NEW.state IN ('CANCELLED','FAILED')))
BEGIN SELECT RAISE(ABORT,'bulk retry/dispatch is unavailable'); END;
"""


def present(db):
    """Presence probe only; callers must recognize the complete profile before use."""
    return db.execute("""SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_attempt*'
        OR name GLOB 'idx_managed_bulk_attempt*' OR tbl_name='managed_bulk_attempts' LIMIT 1""").fetchone() is not None


def validate(db):
    """Profile invariants, not transient job/result state equality inside a write."""
    if (db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] > MAX_ATTEMPTS
            or db.execute('''SELECT 1 FROM managed_bulk_attempts a LEFT JOIN managed_bulk_members m
                ON m.request_id=a.authorization_request_id AND m.device_id=a.device_id AND m.ip=a.ip
                LEFT JOIN operation_jobs j ON j.id=a.job_id
                WHERE m.request_id IS NULL OR m.classification='EXCLUDED_PROTECTED'
                    OR m.intent_id!=a.intent_id OR m.generation!=a.generation
                    OR m.authorization_request_id!=a.authorization_request_id
                    OR (a.state IN ('QUEUED','RUNNING') AND j.id IS NULL) LIMIT 1''').fetchone()):
        raise BulkUnavailable('Bulk attempt evidence is missing, inconsistent or exceeds retained capacity.')


def for_job(db, job_id):
    _state(db)
    return db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()


def reserved(db, key):
    _state(db)
    return db.execute('SELECT 1 FROM managed_bulk_attempts WHERE id=? OR job_id=?', (key, key)).fetchone() is not None


def validate_held_jobs(db):
    """Validate every held binding before ordinary retention can delete anything."""
    from .managed_restoration import validate_binding

    _state(db)
    rows = db.execute("SELECT * FROM managed_bulk_attempts WHERE state IN ('QUEUED','RUNNING','UNVERIFIED')")
    held = 0
    while chunk := rows.fetchmany(100):
        for attempt in chunk:
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (attempt['job_id'],)).fetchone()
            if job is None:
                raise BulkUnavailable('Held bulk ADD is missing its original queue evidence.')
            validate_binding(db, attempt, job)
            held += 1
    return held


class BulkAttempts:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError('Bulk results must use the shared queue database.')
        self.store, self.queue = store, queue

    def initialize(self, *, connection=None):
        with schema_connection(self.store, connection) as db, _atomic(db):
            if _state(db) is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_cancellations'").fetchone():
                raise BulkUnavailable('Existing bulk policy and cancellation controls are required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db):
                raise QueueConflict('Pause ordinary mutations before initializing bulk attempt evidence.')
            execute_schema(db, DDL)
            _state(db)

    def capture_running(self, key, job_id, snapshot, owner, *, enabled=False, connection):
        """Future pre-send composition hook. Does not create/claim/authorize a job."""
        from .managed_restoration import ACTOR, CompleteSnapshot, validate_binding

        if type(enabled) is not bool:
            raise ValueError('Capture capability must be a literal boolean.')
        if not enabled:
            raise PermissionError('Bulk evidence capture is disabled.')
        if not connection.in_transaction:
            raise ValueError('Capture requires the caller-owned pre-send transaction.')
        _uuid(key)
        _uuid(job_id)
        if key == job_id:
            raise ValueError('Request and job identities must stay distinct.')
        if (type(snapshot) is not CompleteSnapshot or snapshot.complete is not True
                or type(snapshot.device_id) is not int or not 1 <= snapshot.device_id <= 65535
                or type(snapshot.present_ips) is not frozenset or len(snapshot.present_ips) > 65536
                or any(type(ip) is not IPv4Address for ip in snapshot.present_ips)):
            raise ValueError('Complete bounded typed absence evidence is required.')
        _uuid(snapshot.id)
        started, completed = _stamp(snapshot.started_at), _stamp(snapshot.completed_at)
        db = connection
        with _atomic(db):
            if _state(db) is None or not present(db):
                raise BulkUnavailable('Bulk attempt journal is not initialized.')
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
            request = db.execute('SELECT * FROM operation_requests WHERE id=?', (key,)).fetchone()
            target = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?',
                                (job['device_id'], job['ip'])).fetchone() if job else None
            if (job is None or target is None or request is None or job['action'] != 'ADD'
                    or job['state'] != 'RUNNING' or job['dispatch_kind'] != 'ADD'
                    or request['state'] != 'ACTIVE' or request['actor_subject'] != ACTOR
                    or job['requested_at'] != request['requested_at']
                    or request['source'] != 'trusted_policy' or json.loads(request['actor_roles_json']) != []):
                raise QueueConflict('Only the exact original RUNNING system ADD may be captured.')
            candidate = {**dict(target), 'id': key, 'job_id': job_id, 'target_revision': target['revision'],
                         'requested_at': request['requested_at'], 'state': 'RUNNING'}
            validate_binding(db, candidate, job)
            for table in ('managed_shun_requests', 'manual_import_batches', 'import_preparation_plans'):
                if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                        and db.execute(f'SELECT 1 FROM {table} WHERE id IN (?,?)', (key, job_id)).fetchone()):
                    raise QueueConflict('An earlier authority/preparation key cannot become an attempt.')
            if (db.execute('SELECT 1 FROM operation_requests WHERE id=?', (job_id,)).fetchone()
                    or db.execute('SELECT 1 FROM operation_jobs WHERE id=?', (key,)).fetchone()):
                raise QueueConflict('Attempt namespaces overlap another request/job.')
            now = self.queue._now()
            lease = db.execute('SELECT * FROM operation_executor WHERE id=1').fetchone()
            if (not owner or lease['owner'] != owner or not lease['lease_until'] or lease['lease_until'] <= _stamp(now)
                    or snapshot.device_id != job['device_id'] or IPv4Address(job['ip']) in snapshot.present_ips
                    or not started <= completed <= request['requested_at'] <= _stamp(now)
                    or now - snapshot.started_at > timedelta(seconds=120)
                    or request['expires_at'] <= _stamp(now) or target['updated_at'] > started
                    or not target['enabled'] or mutations_suspended(db)
                    or not db.execute('SELECT 1 FROM devices WHERE id=? AND enabled=1', (job['device_id'],)).fetchone()
                    or db.execute('SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1', (job['ip'],)).fetchone()
                    or db.execute('SELECT 1 FROM shun_state WHERE device_id=? AND ip=? AND active=1', (job['device_id'], job['ip'])).fetchone()):
                raise QueueConflict('Lease, request, current policy or complete absence evidence is no longer valid.')
            if (db.execute("""SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=?
                    AND state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED')""", (job['device_id'], job['ip'])).fetchone()
                    or db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND id!=?
                        AND state IN ('QUEUED','RUNNING','UNVERIFIED')""", (job['device_id'], job['ip'], job_id)).fetchone()):
                raise QueueConflict('Earlier pending/uncertain pair evidence cannot be bypassed by capture.')
            latest = db.execute("""SELECT MAX(completed_at) FROM operation_jobs WHERE device_id=? AND ip=?
                AND state IN ('VERIFIED','NOOP')""", (job['device_id'], job['ip'])).fetchone()[0]
            if latest is not None and started <= latest:
                raise QueueConflict('Complete absence evidence must follow the earlier successful operation.')
            old = db.execute('SELECT * FROM managed_bulk_attempts WHERE id=? OR job_id=?', (key, job_id)).fetchone()
            if old:
                raise QueueConflict('Attempt identity is already captured; never recapture or rearm it.')
            if db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] >= MAX_ATTEMPTS:
                raise QueueConflict('Retained attempt capacity reached; nothing was evicted.')
            root = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?', (target['authorization_request_id'],)).fetchone()
            BulkPolicies(self.store)._root(db, target['authorization_request_id'], root[0])
            db.execute("""INSERT INTO managed_bulk_attempts VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',NULL,NULL,NULL)""",
                (key, job_id, job['device_id'], job['ip'], target['intent_id'], target['generation'],
                 target['authorization_request_id'], target['revision'], snapshot.id, started, completed, request['requested_at']))
            self.store._insert_event(db, 'MANAGED_BULK_ATTEMPT_RUNNING', job['device_id'], IPv4Address(job['ip']), None,
                ACTOR, 'Managed shun policy', (), key,
                {'intent_id': target['intent_id'], 'generation': target['generation'],
                 'authorization_request_id': target['authorization_request_id'], 'operation_id': job_id,
                 'snapshot_id': snapshot.id, 'evidence_only': True}, _stamp(now))
            if self.queue._now() - snapshot.started_at > timedelta(seconds=120) or lease['lease_until'] <= _stamp(self.queue._now()):
                raise QueueConflict('Lease or evidence freshness expired during capture.')
            return {'attempt_id': key, 'operation_id': job_id, 'evidence_captured': True, 'dispatch_authorized': False}

    def page(self, key, subject, roles, *, page=1):
        """Original-root-bound evidence, not current desired state or retry authority."""
        from .bulk_cancellations import authorized_root
        from .managed_restoration import validate_binding

        if type(page) is not int or page < 1:
            raise ValueError('Select a positive attempt page.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            authorized_root(db, BulkPolicies(self.store), key, subject, roles)
            if not present(db):
                raise BulkUnavailable('Bulk attempt journal is not initialized.')
            scope = '''FROM managed_bulk_attempts a JOIN managed_bulk_members m
                ON m.request_id=? AND m.device_id=a.device_id AND m.ip=a.ip
                AND m.intent_id=a.intent_id AND m.generation=a.generation
                AND m.authorization_request_id=a.authorization_request_id '''
            counts = dict(db.execute('SELECT a.state,COUNT(*) ' + scope + ' GROUP BY a.state', (key,)))
            total = sum(counts.values())
            pages = max(1, (total + 99) // 100)
            if page > pages:
                raise ValueError('Select a page within retained attempts.')
            rows = db.execute('SELECT a.* ' + scope + ' ORDER BY a.requested_at,a.id LIMIT 100 OFFSET ?',
                              (key, (page - 1) * 100)).fetchall()
            for row in rows:
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (row['job_id'],)).fetchone()
                if job is not None:
                    validate_binding(db, row, job)
                elif row['state'] in {'QUEUED', 'RUNNING', 'UNVERIFIED'}:
                    raise BulkUnavailable('Held attempt is missing its original queue evidence.')
            return {'operation_id': key, 'intent_format': 2, 'read_only': True, 'can_execute': False,
                'execution_available': False, 'evidence_only': True, 'total': total, 'counts': counts,
                'page': page, 'pages': pages,
                'attempts': [{**dict(row), 'ip': str(IPv4Address(row['ip']))} for row in rows]}
