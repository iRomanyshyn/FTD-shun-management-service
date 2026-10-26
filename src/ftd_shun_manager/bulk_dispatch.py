"""Bounded atomic bulk admission/shared claim; no runtime caller or activation."""

import json
from dataclasses import dataclass
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid5

from .bulk_attempts import MAX_ATTEMPTS, validate_held_jobs
from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _atomic, _key_free, _quiescent, _state
from .import_preparations import _stamp
from .managed_restoration import ACTOR, CompleteSnapshot, validate_binding
from .operation_queue import QueueConflict, QueueFull
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

MAX_PORTION = 16
DDL = """
DROP TRIGGER managed_bulk_no_resume;
DROP TRIGGER managed_bulk_attempt_capture;
DROP TRIGGER managed_bulk_attempt_monotonic;
ALTER TABLE managed_bulk_registry ADD COLUMN dispatch_resume_after TEXT;
CREATE TRIGGER managed_bulk_dispatch_registry BEFORE UPDATE OF restoration_suspended ON managed_bulk_registry
WHEN NEW.restoration_suspended=0 AND OLD.restoration_suspended=1 AND (
    NEW.dispatch_resume_after IS NULL
    OR (OLD.dispatch_resume_after IS NOT NULL AND NEW.dispatch_resume_after<=OLD.dispatch_resume_after)
    OR NOT EXISTS(SELECT 1 FROM operation_executor WHERE id=1 AND mutations_suspended=1
        AND owner IS NULL AND lease_until IS NULL)
    OR EXISTS(SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING','UNVERIFIED')))
BEGIN SELECT RAISE(ABORT,'bulk resume requires offline pause and quiescence'); END;
CREATE TRIGGER managed_bulk_dispatch_barrier BEFORE UPDATE OF dispatch_resume_after ON managed_bulk_registry
WHEN NEW.dispatch_resume_after IS NOT OLD.dispatch_resume_after
    AND NOT (OLD.restoration_suspended=1 AND NEW.restoration_suspended=0)
BEGIN SELECT RAISE(ABORT,'bulk fresh-read barrier changes only with explicit resume'); END;
CREATE TRIGGER managed_bulk_attempt_capture BEFORE INSERT ON managed_bulk_attempts
WHEN NEW.state!='QUEUED' OR NEW.completed_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'bulk admission requires original QUEUED evidence'); END;
CREATE TRIGGER managed_bulk_attempt_monotonic BEFORE UPDATE OF state ON managed_bulk_attempts
WHEN NOT ((OLD.state='RUNNING' AND NEW.state IN ('QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED'))
    OR (OLD.state='QUEUED' AND NEW.state IN ('RUNNING','CANCELLED','FAILED')))
BEGIN SELECT RAISE(ABORT,'bulk attempt cannot be replayed'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_dispatch*' LIMIT 1").fetchone() is not None


@dataclass(frozen=True)
class BulkCandidate:
    """Literal discovery identity; never silently rebound to a newer generation."""

    device_id: int
    ip: IPv4Address
    intent_id: str
    generation: int
    authorization_request_id: str
    target_revision: int


def _snapshot(snapshot):
    if (type(snapshot) is not CompleteSnapshot or snapshot.complete is not True
            or type(snapshot.device_id) is not int or not 1 <= snapshot.device_id <= 65535
            or type(snapshot.present_ips) is not frozenset or len(snapshot.present_ips) > 65536
            or any(type(ip) is not IPv4Address for ip in snapshot.present_ips)):
        raise ValueError('A complete bounded typed snapshot is required.')
    _uuid(snapshot.id)
    return _stamp(snapshot.started_at), _stamp(snapshot.completed_at)


def _lease(db, queue, owner, device_id=None):
    row = queue._executor(db, owner, device_id)
    if (type(owner) is not str or not owner or row is None or row['owner'] != owner
            or not row['lease_until'] or row['lease_until'] <= _stamp(queue._now())):
        raise QueueConflict('Shared executor lease lost.')


def authority_valid(db, attempt, now):
    """Current pre-send eligibility; never settles or clears original evidence."""
    state = _state(db)
    if state is None or not present(db) or state['restoration_suspended'] or mutations_suspended(db):
        return False
    barrier = db.execute('SELECT dispatch_resume_after FROM managed_bulk_registry WHERE id=1').fetchone()[0]
    row = db.execute('''SELECT t.*,d.enabled AS device_enabled,
        json_extract(r.result_json,'$.admission_mode') AS admission_mode FROM managed_shun_targets t
        JOIN devices d ON d.id=t.device_id JOIN managed_shun_requests r ON r.id=t.authorization_request_id
        WHERE t.device_id=? AND t.ip=?''',
        (attempt['device_id'], attempt['ip'])).fetchone()
    if (row is None or not row['enabled'] or not row['device_enabled']
            or any(row[field] != attempt[field] for field in ('intent_id', 'generation', 'authorization_request_id'))
            or row['revision'] != attempt['target_revision'] or row['updated_at'] > attempt['snapshot_started_at']
            or (row['admission_mode'] == 'fenced' and row['updated_at'] == attempt['snapshot_started_at'])
            or attempt['snapshot_started_at'] < barrier
            or not attempt['snapshot_started_at'] <= attempt['snapshot_at'] <= attempt['requested_at'] <= _stamp(now)
            or attempt['snapshot_started_at'] < _stamp(now - timedelta(seconds=120))
            or db.execute('SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1', (attempt['ip'],)).fetchone()
            or db.execute('SELECT 1 FROM shun_state WHERE device_id=? AND ip=? AND active=1',
                          (attempt['device_id'], attempt['ip'])).fetchone()
            or db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT')",
                          (attempt['device_id'],)).fetchone()
            or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED'",
                          (attempt['device_id'],)).fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=?
                AND id!=? AND state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED')''',
                (attempt['device_id'], attempt['ip'], attempt['id'])).fetchone()
            or db.execute('''SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND id!=?
                AND state IN ('QUEUED','RUNNING','UNVERIFIED')''',
                (attempt['device_id'], attempt['ip'], attempt['job_id'])).fetchone()
            or db.execute('''SELECT 1 FROM operation_jobs j WHERE device_id=? AND ip=? AND id!=? AND action='ADD'
                AND NOT EXISTS(SELECT 1 FROM managed_bulk_attempts a WHERE a.job_id=j.id)''',
                (attempt['device_id'], attempt['ip'], attempt['job_id'])).fetchone()):
        return False
    latest = db.execute('''SELECT MAX(completed_at) FROM operation_jobs WHERE device_id=? AND ip=?
        AND id!=? AND state IN ('VERIFIED','NOOP')''',
        (attempt['device_id'], attempt['ip'], attempt['job_id'])).fetchone()[0]
    retained = db.execute('''SELECT MAX(completed_at) FROM managed_bulk_attempts
        WHERE device_id=? AND ip=? AND id!=?''', (attempt['device_id'], attempt['ip'], attempt['id'])).fetchone()[0]
    return all(value is None or value < attempt['snapshot_started_at'] for value in (latest, retained))


def cancel_obsolete(db, queue):
    rows = db.execute('''SELECT j.* FROM operation_jobs j JOIN managed_bulk_attempts a ON a.job_id=j.id
        WHERE j.state='QUEUED' ''').fetchall()  # Shared queue is bounded to 1000 pending jobs.
    for job in rows:
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
        validate_binding(db, attempt, job)
        request = db.execute('SELECT * FROM operation_requests WHERE id=?', (attempt['id'],)).fetchone()
        if (not authority_valid(db, attempt, queue._now()) or request['state'] != 'ACTIVE'
                or request['expires_at'] <= _stamp(queue._now())):
            queue._finish(db, job, 'CANCELLED', 'Bulk authority/evidence expired or was revoked before dispatch')


class BulkDispatch:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError('Bulk admission must use the shared queue database.')
        self.store, self.queue = store, queue

    def initialize(self, *, connection=None):
        """Explicit exact-profile upgrade only; keeps suspension and all data."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_wait_results'").fetchone():
                raise BulkUnavailable('Existing exact captured-cancellation profile is required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db) or not state['restoration_suspended']:
                raise QueueConflict('Pause ordinary mutations and suspend policy before upgrading bulk dispatch.')
            policies = BulkPolicies(self.store)
            for root in db.execute('SELECT id,actor_subject FROM managed_shun_requests WHERE id IN (SELECT id FROM managed_bulk_manifests)'):
                policies._root(db, root['id'], root['actor_subject'])
            execute_schema(db, DDL)
            _state(db)

    def admit(self, snapshot, candidates, owner, managed_revision, protected_revision, *,
              enabled=False, addition_device_ids=frozenset(), connection=None):
        """One all-or-nothing portion, no RPC. Original-key retries are historical."""
        if type(enabled) is not bool:
            raise ValueError('Bulk admission capability must be boolean.')
        if not enabled:
            return None
        started, completed = _snapshot(snapshot)
        if (type(candidates) is not tuple or not 1 <= len(candidates) <= MAX_PORTION
                or any(type(c) is not BulkCandidate or type(c.device_id) is not int
                       or c.device_id != snapshot.device_id or type(c.ip) is not IPv4Address
                       or type(c.generation) is not int or c.generation < 1
                       or type(c.target_revision) is not int or c.target_revision < 0 for c in candidates)
                or len({c.ip for c in candidates}) != len(candidates)
                or any(type(value) is not int or value < 0 for value in (managed_revision, protected_revision))
                or type(addition_device_ids) is not frozenset
                or any(type(device) is not int or not 1 <= device <= 65535 for device in addition_device_ids)):
            raise ValueError('Select 1..16 distinct literal same-device identities and exact revisions/profiles.')
        identities = []
        for candidate in candidates:
            _uuid(candidate.intent_id)
            _uuid(candidate.authorization_request_id)
            if candidate.ip in snapshot.present_ips:
                raise QueueConflict('The complete snapshot still contains a selected target.')
            key = str(uuid5(UUID(candidate.intent_id), snapshot.id))
            identities.append((candidate, key, str(uuid5(UUID(key), 'bulk-add-job'))))
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None or not present(db):
                raise BulkUnavailable('Explicit dispatch-capable profile is required.')
            validate_held_jobs(db)
            for root in {candidate.authorization_request_id for candidate in candidates}:
                actor = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?', (root,)).fetchone()
                if actor is None:
                    raise BulkUnavailable('Original author is missing.')
                BulkPolicies(self.store)._root(db, root, actor[0])
            attempts = []
            for candidate, key, job_id in identities:
                old = db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (key,)).fetchone()
                if old is not None:
                    expected = (job_id, candidate.device_id, candidate.ip.packed, candidate.intent_id,
                                candidate.generation, candidate.authorization_request_id, candidate.target_revision,
                                snapshot.id, started, completed)
                    fields = ('job_id', 'device_id', 'ip', 'intent_id', 'generation', 'authorization_request_id',
                              'target_revision', 'snapshot_id', 'snapshot_started_at', 'snapshot_at')
                    if tuple(old[field] for field in fields) != expected:
                        raise QueueConflict('Original snapshot/intent key belongs to different evidence.')
                    attempts.append({'attempt_id': key, 'operation_id': job_id, 'state': old['state'], 'replayed': True})
            if len(attempts) == len(identities):
                return {'attempts': attempts, 'replayed': True, 'device_work_sent': False}
            if attempts:
                raise QueueConflict('Recover existing admissions separately; do not mix old and new portion members.')
            _lease(db, self.queue, owner, snapshot.device_id)
            if (state['restoration_suspended'] or mutations_suspended(db) or state['revision'] != managed_revision
                    or db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0] != protected_revision
                    or snapshot.device_id not in addition_device_ids):
                raise QueueConflict('Policy is suspended/changed, mutations paused or device ADD capability is absent.')
            if (db.execute('SELECT COUNT(*) FROM managed_bulk_attempts').fetchone()[0] + len(candidates) > MAX_ATTEMPTS
                    or self.queue._pending_count(db) + len(candidates) > 1000
                    or self.queue._active_request_count(db) + len(candidates) > 2000):
                raise QueueFull('Bulk journal/shared queue capacity reached; portion was not admitted.')
            now = self.queue._now()
            timestamp = _stamp(now)
            for candidate, key, job_id in identities:
                attempt = {'id': key, 'job_id': job_id, 'device_id': candidate.device_id, 'ip': candidate.ip.packed,
                           'intent_id': candidate.intent_id, 'generation': candidate.generation,
                           'authorization_request_id': candidate.authorization_request_id,
                           'target_revision': candidate.target_revision, 'snapshot_id': snapshot.id,
                           'snapshot_started_at': started, 'snapshot_at': completed, 'requested_at': timestamp}
                if not authority_valid(db, attempt, now):
                    raise QueueConflict('Current authority, protection, device or fresh absence evidence changed.')
                history = db.execute('''SELECT MAX(requested_at),SUM(requested_at>?) FROM managed_bulk_attempts
                    WHERE device_id=? AND ip=?''', (_stamp(now - timedelta(hours=1)), candidate.device_id, candidate.ip.packed)).fetchone()
                if (history[0] is not None and history[0] > _stamp(now - timedelta(seconds=300))) or (history[1] or 0) >= 3:
                    raise QueueConflict('Bulk pair backoff/churn limit reached; original evidence retained.')
                for identity in (key, job_id):
                    _key_free(db, identity)
                    if db.execute('SELECT 1 FROM managed_bulk_attempts WHERE id=? OR job_id=?', (identity, identity)).fetchone():
                        raise QueueConflict('Retained attempt identities cannot acquire another authority.')
                payload = json.dumps({'scope': 'managed_restoration', 'intent_id': candidate.intent_id,
                                      'generation': candidate.generation, 'targets': [[candidate.device_id, str(candidate.ip)]]})
                db.execute("INSERT INTO operation_requests VALUES (?,?,?,'[]','trusted_policy',?,?,?,'ACTIVE')",
                           (key, ACTOR, 'Managed shun policy', payload, timestamp, _stamp(now + timedelta(seconds=900))))
                db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action)
                    VALUES (?,?,?,'QUEUED',?,'ADD')""", (job_id, candidate.device_id, candidate.ip.packed, timestamp))
                db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job_id))
                db.execute("""INSERT INTO managed_bulk_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'QUEUED',NULL,NULL,NULL)""",
                           tuple(attempt.values()))
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
                row = db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (key,)).fetchone()
                validate_binding(db, row, job)
                from .managed_restoration import _event

                _event(db, self.store, row, 'QUEUED', timestamp)
                attempts.append({'attempt_id': key, 'operation_id': job_id, 'state': 'QUEUED', 'replayed': False})
            _lease(db, self.queue, owner, snapshot.device_id)
            if any(not authority_valid(db, db.execute('SELECT * FROM managed_bulk_attempts WHERE id=?', (a['attempt_id'],)).fetchone(),
                                       self.queue._now()) for a in attempts):
                raise QueueConflict('Evidence expired during portion admission.')
            self.queue._bump(db)
            return {'attempts': attempts, 'replayed': False, 'device_work_sent': False}
