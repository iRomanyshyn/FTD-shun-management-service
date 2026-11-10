"""Fresh-profile deferred queue transitions; not a configured worker or retry loop.

Only exact settled-v7 ACKs may leave RUNNING. Later complete observation settles
as presence/known absence without inventing creation, adoption or replay rights.
"""

import sqlite3
from contextlib import closing
from functools import lru_cache

from .bulk_attempts import DDL as BASE_ATTEMPTS
from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable, _atomic, _quiescent, _state
from .bulk_waits import DDL as BASE_WAITS
from .device_leases import DeviceLeases, _token, device_uncertain
from .import_preparations import _stamp
from .managed_restoration import CompleteSnapshot, validate_binding
from .operation_queue import OperationQueue, QueueConflict
from .pending_confirmation import PendingConfirmations, _enabled
from .pending_retries import DDL as RETRIES_DDL
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

AWAITING = 'AWAITING_CONFIRMATION'
OUTCOMES = ('OBSERVED_PRESENT', 'CONFIRMED_ABSENT')
TABLE = 'managed_bulk_pending_execution'

# Trusted fresh-profile DDL only. No copying/converting/deleting retained jobs.
JOBS_DDL = """
CREATE TABLE operation_jobs (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 device_id INTEGER NOT NULL REFERENCES devices(id), ip BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','VERIFIED','NOOP','FAILED','UNVERIFIED',
    'RECONCILED_ABSENT','CANCELLED','AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')),
 requested_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, reason TEXT,
 action TEXT NOT NULL DEFAULT 'REMOVE' CHECK(action IN ('REMOVE','ADD')),
 dispatch_kind TEXT CHECK(dispatch_kind IN ('REMOVE','ADD')),
 CHECK(state NOT IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')
    OR (action='ADD' AND dispatch_kind='ADD' AND started_at IS NOT NULL
        AND ((state='AWAITING_CONFIRMATION' AND completed_at IS NULL)
            OR (state!='AWAITING_CONFIRMATION' AND completed_at IS NOT NULL))))
);
CREATE UNIQUE INDEX idx_operation_active_target ON operation_jobs(device_id,ip)
 WHERE state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION');
CREATE INDEX idx_operation_jobs_state ON operation_jobs(state,device_id,seq);
CREATE TRIGGER guard_add_claim BEFORE UPDATE OF state ON operation_jobs
WHEN NEW.action='ADD' AND NEW.state='RUNNING' AND OLD.state!='RUNNING' AND NEW.dispatch_kind IS NOT 'ADD'
BEGIN SELECT RAISE(ABORT,'ADD requires an explicit addition claimant'); END;
CREATE TRIGGER guard_add_requeue BEFORE UPDATE ON operation_jobs
WHEN NEW.action='ADD' AND NEW.state='QUEUED' AND NEW.dispatch_kind IS NOT NULL
BEGIN SELECT RAISE(ABORT,'ADD requeue must clear dispatch kind'); END;
CREATE TRIGGER immutable_operation_action BEFORE UPDATE OF action ON operation_jobs
WHEN NEW.action!=OLD.action BEGIN SELECT RAISE(ABORT,'operation action is immutable'); END;
"""

ATTEMPTS_DDL = BASE_ATTEMPTS.replace(
    "'UNVERIFIED','CANCELLED'", "'UNVERIFIED','CANCELLED','AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT'", 1,
).replace("state IN ('QUEUED','RUNNING')", "state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION')").replace(
    "NEW.state!='RUNNING'", "NEW.state!='QUEUED'",
).replace("'VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED')", "'VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED','OBSERVED_PRESENT','CONFIRMED_ABSENT')").replace(
    "('QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED')", "('QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED','AWAITING_CONFIRMATION')",
).replace("('CANCELLED','FAILED')))", "('RUNNING','CANCELLED','FAILED'))\n    OR (OLD.state='AWAITING_CONFIRMATION' AND NEW.state IN ('OBSERVED_PRESENT','CONFIRMED_ABSENT')))").replace(
    'only current pre-send RUNNING evidence may be captured', 'bulk admission requires original QUEUED evidence',
)

WAITS_DDL = BASE_WAITS.replace(
    "'UNVERIFIED','QUEUED','CANCELLED'", "'UNVERIFIED','QUEUED','CANCELLED','OBSERVED_PRESENT','CONFIRMED_ABSENT'",
)


def _guards(table, job_column, prefix):
    # Fixed table/column literals chosen below, never request input.
    return f"""
CREATE TRIGGER {prefix}_insert BEFORE INSERT ON {table}
WHEN NEW.state IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')
BEGIN SELECT RAISE(ABORT,'deferred state requires its original RUNNING claim'); END;
CREATE TRIGGER {prefix}_transition BEFORE UPDATE OF state ON {table}
WHEN (NEW.state IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')
 OR OLD.state IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')) AND NOT (
 EXISTS(SELECT 1 FROM managed_bulk_pending_members m JOIN managed_bulk_pending_sessions s ON s.id=m.session_id
    WHERE m.job_id=NEW.{job_column} AND s.device_id=NEW.device_id AND m.ip=NEW.ip
    AND ((OLD.state='RUNNING' AND NEW.state='AWAITING_CONFIRMATION')
      OR (OLD.state='AWAITING_CONFIRMATION' AND EXISTS(
        SELECT 1 FROM managed_bulk_pending_reads r WHERE r.session_id=m.session_id AND (
            (NEW.state='OBSERVED_PRESENT' AND EXISTS(SELECT 1 FROM json_each(r.present_ordinals_json) WHERE value=m.ordinal))
         OR (NEW.state='CONFIRMED_ABSENT' AND NOT EXISTS(SELECT 1 FROM json_each(r.present_ordinals_json) WHERE value=m.ordinal))))))))
BEGIN SELECT RAISE(ABORT,'deferred transition requires exact original settlement/observation'); END;
"""


JOBS_DDL += _guards('operation_jobs', 'id', 'managed_bulk_pending_job')
DDL = ("DROP TABLE IF EXISTS operation_jobs;\nDROP TABLE managed_bulk_attempts;\nDROP TABLE managed_bulk_wait_results;\n"
       + JOBS_DDL + ATTEMPTS_DDL + WAITS_DDL
       + _guards('managed_bulk_attempts', 'job_id', 'managed_bulk_pending_attempt') + """
CREATE TABLE managed_bulk_pending_execution (
 id INTEGER PRIMARY KEY CHECK(id=1), format_version INTEGER NOT NULL CHECK(format_version=1)
);
INSERT INTO managed_bulk_pending_execution VALUES (1,1);
CREATE TRIGGER managed_bulk_pending_execution_immutable BEFORE UPDATE ON managed_bulk_pending_execution
BEGIN SELECT RAISE(ABORT,'pending execution profile is immutable'); END;
CREATE TRIGGER managed_bulk_pending_execution_retained BEFORE DELETE ON managed_bulk_pending_execution
BEGIN SELECT RAISE(ABORT,'pending execution profile is retained'); END;
""" + RETRIES_DDL)


def present(db):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is not None


def _job_objects(db):
    return [tuple(row) for row in db.execute("""SELECT type,name,sql FROM sqlite_master
        WHERE tbl_name='operation_jobs' AND sql IS NOT NULL ORDER BY type,name""")]


@lru_cache(maxsize=1)
def _expected_jobs():
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('BEGIN')
        execute_schema(db, JOBS_DDL)
        return _job_objects(db)


def validate(db):
    from .pending_retries import validate as validate_retries

    if [tuple(row) for row in db.execute('SELECT id,format_version FROM managed_bulk_pending_execution')] != [(1, 1)]:
        raise BulkUnavailable('Exact pending execution profile marker is required.')
    if _job_objects(db) != _expected_jobs():
        raise BulkUnavailable('Exact deferred queue schema and guards are required.')
    if db.execute('''SELECT 1 FROM operation_jobs j LEFT JOIN managed_bulk_pending_members m ON m.job_id=j.id
        LEFT JOIN managed_bulk_attempts a ON a.id=m.attempt_id
        LEFT JOIN managed_bulk_pending_reads r ON r.session_id=m.session_id
        WHERE j.state IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')
        AND (m.job_id IS NULL OR a.id IS NULL OR a.state!=j.state OR a.completed_at IS NOT j.completed_at
            OR (j.state!='AWAITING_CONFIRMATION' AND r.session_id IS NULL)) LIMIT 1''').fetchone():
        raise BulkUnavailable('Deferred queue state lacks its original matching attempt and evidence.')
    if db.execute('''SELECT 1 FROM managed_bulk_attempts a LEFT JOIN operation_jobs j ON j.id=a.job_id
        WHERE a.state IN ('AWAITING_CONFIRMATION','OBSERVED_PRESENT','CONFIRMED_ABSENT')
        AND (j.id IS NULL OR j.state!=a.state) LIMIT 1''').fetchone():
        raise BulkUnavailable('Deferred attempt is missing its exact retained queue state.')
    validate_retries(db)


class PendingExecution:
    def __init__(self, store, queue):
        self.evidence = PendingConfirmations(store, queue)
        self.store, self.queue = store, queue
        self.leases = DeviceLeases(store, queue)

    def initialize_empty(self, *, connection=None):
        """Fresh empty queues only; no legacy converter or live upgrade."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            self.evidence._profile(db)
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db):
                raise QueueConflict('Pause mutations before fresh pending execution initialization.')
            for table in ('operation_jobs', 'operation_requests', 'operation_links', 'managed_bulk_attempts',
                          'managed_bulk_pending_sessions', 'managed_bulk_pending_members', 'managed_bulk_pending_reads',
                          'managed_bulk_wait_results', 'managed_bulk_cancellations'):
                if db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                    raise QueueConflict('Pending execution requires fresh empty execution tables; no data was converted.')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('managed_bulk_ordered_roots', 'managed_bulk_device_recovery')").fetchone():
                raise BulkUnavailable('Fresh pending execution does not support ordered/recovery profiles yet.')
            execute_schema(db, DDL)
            self._profile(db)

    @staticmethod
    def _profile(db):
        if _state(db) is None or not present(db):
            raise BulkUnavailable('Exact fresh pending execution profile is required.')

    def _audit(self, db, job, state, token, session_id, snapshot_id=None):
        from .managed_restoration import _event as attempt_event

        request = db.execute('''SELECT r.* FROM operation_requests r JOIN operation_links l
            ON l.request_id=r.id WHERE l.job_id=?''', (job['id'],)).fetchall()
        if len(request) != 1:
            raise QueueConflict('Deferred result requires its single original requester.')
        OperationQueue._event(self.queue, db, 'SHUN_OPERATION_' + state, request[0], job,
                             {'pending_session': session_id, 'snapshot_id': snapshot_id, 'proves_creation': False,
                              'device_executor': {'owner': token.owner, 'epoch': token.epoch}, 'batch_session_version': 7})
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()
        attempt_event(db, self.store, attempt, state, _stamp(self.queue._now()), job['reason'])

    def await_confirmation(self, token, receipt, job_ids, *, enabled=False):
        _enabled(enabled)
        _token(token)
        with schema_connection(self.store) as db, _atomic(db):
            self._profile(db)
            if device_uncertain(db, token.device_id):
                raise QueueConflict('Unknown device work cannot leave a lease through pending confirmation.')
            session_id = self.evidence.record(token, receipt, job_ids, enabled=True, connection=db)
            for job_id in job_ids:
                db.execute("UPDATE operation_jobs SET state=?,reason='Sent; awaiting complete observation' WHERE id=?", (AWAITING, job_id))
                db.execute('UPDATE managed_bulk_attempts SET state=? WHERE job_id=?', (AWAITING, job_id))
            self._profile(db)
            for job_id in job_ids:
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
                self._audit(db, job, AWAITING, token, session_id)
            self.queue._bump(db)
            self.leases.check(db, token)
            # The state handoff and original lease release commit together;
            # restart cannot observe an awaiting row with an unreleased owner.
            self.leases._release(token, opening_event=None, connection=db)
        return session_id

    def confirm(self, token, session_id, snapshot, *, enabled=False, connection=None):
        """Causal observation under a new live lease; no publication or new ADD."""
        _enabled(enabled)
        _token(token)
        _uuid(session_id)
        if type(snapshot) is not CompleteSnapshot:
            raise ValueError('A typed complete pending observation is required.')
        with schema_connection(self.store, connection) as db, _atomic(db):
            self._profile(db)
            self.leases.check(db, token)
            session = db.execute('SELECT * FROM managed_bulk_pending_sessions WHERE id=?', (session_id,)).fetchone()
            if session is None or session['device_id'] != token.device_id:
                raise QueueConflict('Pending confirmation is outside this original device scope.')
            # Confirmation may not use a read begun before its current lease.
            claims = db.execute('''SELECT timestamp FROM shun_events WHERE event_type='DEVICE_LEASE_CLAIMED'
                AND device_id=? AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=?''',
                                (token.device_id, token.owner, token.epoch)).fetchall()
            if len(claims) != 1 or _stamp(snapshot.started_at) < claims[0]['timestamp']:
                raise QueueConflict('Complete confirmation must belong to this current lease visit.')
            outcomes = self.evidence.classify(session_id, snapshot, enabled=True, connection=db)
            now = _stamp(self.queue._now())
            changed = []
            for job_id, state in outcomes:
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
                attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()
                validate_binding(db, attempt, job)
                if job['state'] == state:
                    continue  # Exact immutable first-read replay; no duplicate event/result.
                if job['state'] != AWAITING:
                    raise QueueConflict('Only original awaiting work can consume its first observation.')
                db.execute('UPDATE operation_jobs SET state=?,completed_at=?,reason=? WHERE id=?',
                           (state, now, 'Observed present; creation not attributed' if state == 'OBSERVED_PRESENT'
                            else 'Confirmed absent; original command will not be replayed', job_id))
                db.execute('UPDATE managed_bulk_attempts SET state=?,completed_at=? WHERE job_id=?', (state, now, job_id))
                changed.append((job_id, state))
            self._profile(db)
            for job_id, state in changed:
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
                attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()
                self._audit(db, job, state, token, session_id, snapshot.id)
                from .bulk_waits import settle_result

                settle_result(db, self.store, attempt, state, now)
                db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=? AND state='ACTIVE'", (attempt['id'],))
            if changed:
                self.queue._bump(db)
            self.leases.check(db, token)
        return outcomes
