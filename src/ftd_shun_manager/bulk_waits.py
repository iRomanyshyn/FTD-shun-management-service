"""Captured bulk cancellation outcomes; shared result transaction, no executor."""

import hashlib
import json
from ipaddress import IPv4Address

# Trusted schema composition, not user-provided SQL or an implicit live upgrade.
from .bulk_cancellations import DDL as CANCELLATION_DDL
from .bulk_policy import BulkUnavailable, _atomic, _quiescent, _state
from .import_preparations import _feed
from .managed_shuns import ManagedConflict
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

EXPANDED_DDL = CANCELLATION_DDL.replace(
    "'ALREADY_STOPPED','SUPERSEDED'))",
    "'ALREADY_STOPPED','SUPERSEDED','WAITING_OUTCOME','RETAINED_APPLIED','STOPPED_FAILED','STOPPED_UNVERIFIED'))",
).replace(
    '    PRIMARY KEY(import_id,device_id,ip),',
    "    job_id TEXT, attempt_digest TEXT CHECK(attempt_digest IS NULL OR length(attempt_digest)=64),\n"
    "    CHECK(state!='WAITING_OUTCOME' OR (job_id IS NOT NULL AND attempt_digest IS NOT NULL)),\n"
    '    PRIMARY KEY(import_id,device_id,ip),',
)
DDL = """
CREATE TABLE managed_bulk_wait_results (
    import_id TEXT NOT NULL,device_id INTEGER NOT NULL,ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    job_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('RETAINED_APPLIED','STOPPED_UNSENT','STOPPED_FAILED','STOPPED_UNVERIFIED','ALREADY_STOPPED','SUPERSEDED')),
    attention INTEGER NOT NULL CHECK(attention IN (0,1)),
    outcome TEXT NOT NULL CHECK(outcome IN ('VERIFIED','NOOP','FAILED','UNVERIFIED','QUEUED','CANCELLED')),
    settled_at TEXT NOT NULL,
    CHECK(attention=(outcome IN ('FAILED','UNVERIFIED'))),
    PRIMARY KEY(import_id,device_id,ip),
    FOREIGN KEY(import_id,device_id,ip) REFERENCES managed_bulk_cancellation_members(import_id,device_id,ip)
);
CREATE TRIGGER managed_bulk_wait_capture BEFORE INSERT ON managed_bulk_wait_results
WHEN NOT EXISTS(SELECT 1 FROM managed_bulk_cancellation_members m
    WHERE m.import_id=NEW.import_id AND m.device_id=NEW.device_id AND m.ip=NEW.ip
      AND m.state='WAITING_OUTCOME' AND m.job_id=NEW.job_id)
BEGIN SELECT RAISE(ABORT,'settlement requires its original captured wait'); END;
CREATE TRIGGER managed_bulk_wait_immutable BEFORE UPDATE ON managed_bulk_wait_results
BEGIN SELECT RAISE(ABORT,'bulk settlement is immutable'); END;
CREATE TRIGGER managed_bulk_wait_retained BEFORE DELETE ON managed_bulk_wait_results
BEGIN SELECT RAISE(ABORT,'bulk settlement is retained'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_wait*' LIMIT 1").fetchone() is not None


def validate(db):
    if (db.execute('''SELECT 1 FROM managed_bulk_wait_results r LEFT JOIN managed_bulk_cancellation_members m
            ON m.import_id=r.import_id AND m.device_id=r.device_id AND m.ip=r.ip
            WHERE m.import_id IS NULL OR m.state!='WAITING_OUTCOME' OR m.job_id!=r.job_id LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_cancellation_members m LEFT JOIN managed_bulk_attempts a ON a.job_id=m.job_id
                WHERE m.state='WAITING_OUTCOME' AND (a.id IS NULL OR a.device_id!=m.device_id OR a.ip!=m.ip
                    OR a.intent_id!=m.intent_id OR a.generation!=m.generation
                    OR a.authorization_request_id!=m.authorization_request_id) LIMIT 1''').fetchone()):
        raise BulkUnavailable('Captured bulk cancellation evidence is incomplete or inconsistent.')


def classify(db, member):
    """Own exact history only. Observation cannot establish completed application."""
    from .managed_restoration import validate_binding

    checksum = hashlib.sha256(b'ftd-shun-manager:bulk-cancel-attempts:v2\n')
    states, count, pending = set(), 0, None
    rows = db.execute('''SELECT * FROM managed_bulk_attempts WHERE device_id=? AND ip=?
        AND intent_id=? AND generation=? AND authorization_request_id=? ORDER BY id''',
        tuple(member[name] for name in ('device_id', 'ip', 'intent_id', 'generation', 'authorization_request_id')))
    while chunk := rows.fetchmany(100):
        for attempt in chunk:
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (attempt['job_id'],)).fetchone()
            if job is not None:
                validate_binding(db, attempt, job)
            elif attempt['state'] in {'QUEUED', 'RUNNING', 'UNVERIFIED'}:
                raise BulkUnavailable('Owned pending/unknown attempt is missing its queue evidence.')
            if attempt['state'] in {'QUEUED', 'RUNNING'}:
                if pending is not None:
                    raise BulkUnavailable('Multiple unfinished attempts cannot be captured as one predecessor.')
                pending = attempt
            _feed(checksum, dict(attempt) | {'ip': str(IPv4Address(attempt['ip']))})
            states.add(attempt['state'])
            count += 1
    if db.execute('''SELECT 1 FROM operation_jobs j WHERE j.device_id=? AND j.ip=?
        AND (j.action='ADD' OR j.state IN ('QUEUED','RUNNING')) AND NOT EXISTS (
            SELECT 1 FROM managed_bulk_attempts a WHERE a.job_id=j.id AND a.intent_id=?
                AND a.generation=? AND a.authorization_request_id=?) LIMIT 1''',
        tuple(member[name] for name in ('device_id', 'ip', 'intent_id', 'generation', 'authorization_request_id'))).fetchone():
        raise ManagedConflict('Independent ADD evidence/unfinished work cannot be taken over by bulk cancellation.')
    if states.intersection({'VERIFIED', 'NOOP'}):
        state, job_id = 'RETAINED_APPLIED', None
    elif pending is not None and pending['state'] == 'RUNNING':
        state, job_id = 'WAITING_OUTCOME', pending['job_id']
    else:
        state = 'STOPPED_UNVERIFIED' if 'UNVERIFIED' in states else 'STOPPED_FAILED' if 'FAILED' in states else 'STOPPED_UNSENT'
        job_id = pending['job_id'] if pending is not None else None
    return {'state': state, **({'job_id': job_id} if job_id is not None else {}),
            **({'attempt_digest': checksum.hexdigest()} if count else {})}


def validate_pending(db):
    """All captured references survive pruning, including incompatible-writer gaps."""
    from .managed_restoration import validate_binding

    _state(db)
    cursor = db.execute('''SELECT m.* FROM managed_bulk_cancellation_members m
        WHERE m.state='WAITING_OUTCOME' AND NOT EXISTS(SELECT 1 FROM managed_bulk_wait_results r
            WHERE r.import_id=m.import_id AND r.device_id=m.device_id AND r.ip=m.ip)''')
    count = 0
    while chunk := cursor.fetchmany(100):
        for member in chunk:
            attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (member['job_id'],)).fetchone()
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (member['job_id'],)).fetchone()
            if attempt is None or job is None:
                raise BulkUnavailable('Captured pending bulk cancellation is missing its original ADD.')
            validate_binding(db, attempt, job)
            count += 1
    return count


def settle_result(db, store, attempt, outcome, timestamp):
    if outcome == 'RUNNING' or not present(db):
        return
    _state(db)
    rows = db.execute('''SELECT m.* FROM managed_bulk_cancellation_members m
        WHERE m.job_id=? AND m.state='WAITING_OUTCOME' AND NOT EXISTS (
            SELECT 1 FROM managed_bulk_wait_results r WHERE r.import_id=m.import_id AND r.device_id=m.device_id AND r.ip=m.ip)''',
        (attempt['job_id'],)).fetchall()
    for member in rows:  # At most one decision per root; at most 128 retained roots.
        if any(member[name] != attempt[name] for name in ('device_id', 'ip', 'intent_id', 'generation', 'authorization_request_id')):
            raise BulkUnavailable('Settled ADD does not match its original captured cancellation.')
        target = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?',
                            (member['device_id'], member['ip'])).fetchone()
        if target is None:
            raise BulkUnavailable('Captured original effective policy is missing.')
        if any(target[name] != member[name] for name in ('intent_id', 'generation', 'authorization_request_id')):
            state = 'SUPERSEDED'
        elif not target['enabled']:
            state = 'ALREADY_STOPPED'
        elif outcome in {'VERIFIED', 'NOOP'}:
            state = 'RETAINED_APPLIED'
        else:
            state = {'FAILED': 'STOPPED_FAILED', 'UNVERIFIED': 'STOPPED_UNVERIFIED',
                     'QUEUED': 'STOPPED_UNSENT', 'CANCELLED': 'STOPPED_UNSENT'}[outcome]
        db.execute('INSERT INTO managed_bulk_wait_results VALUES (?,?,?,?,?,?,?,?)',
            (member['import_id'], member['device_id'], member['ip'], member['job_id'], state,
             int(outcome in {'FAILED', 'UNVERIFIED'}), outcome, timestamp))
        actor = db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (member['import_id'],)).fetchone()
        roles, ip = tuple(json.loads(actor['actor_roles_json'])), IPv4Address(member['ip'])
        if state.startswith('STOPPED_'):
            revision = _state(db)['revision'] + 1
            changed = db.execute('''UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=?
                WHERE device_id=? AND ip=? AND intent_id=? AND generation=? AND authorization_request_id=? AND enabled=1''',
                (revision, timestamp, timestamp, member['device_id'], member['ip'], member['intent_id'],
                 member['generation'], member['authorization_request_id'])).rowcount
            if changed != 1:
                raise BulkUnavailable('Exact captured policy could not be retired.')
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (revision,))
            store._insert_event(db, 'MANAGED_SHUN_RETIRED', member['device_id'], ip, None,
                actor['actor_subject'], actor['actor_display_name'], roles, member['import_id'],
                {'source': 'bulk_cancellation_settlement', 'intent_id': member['intent_id'], 'generation': member['generation'],
                 'authorization_request_id': member['authorization_request_id'], 'managed_revision': revision}, timestamp)
        store._insert_event(db, 'MANAGED_BULK_CANCELLATION_SETTLED', member['device_id'], ip, None,
            actor['actor_subject'], actor['actor_display_name'], roles, member['import_id'],
            {'state': state, 'attention': outcome in {'FAILED', 'UNVERIFIED'}, 'job_id': member['job_id'],
             'outcome': outcome, 'intent_id': member['intent_id'], 'generation': member['generation']}, timestamp)
    if rows and outcome == 'QUEUED':
        from .operation_queue import OperationQueue

        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (attempt['job_id'],)).fetchone()
        OperationQueue(store)._finish(db, job, 'CANCELLED', 'Bulk import cancelled after exact pre-write deferral')


class BulkWaits:
    def __init__(self, store):
        self.store = store

    def initialize(self, *, connection=None):
        """Explicit preservation-checked developer upgrade, never a startup hook."""
        from .bulk_cancellations import BulkCancellations

        with schema_connection(self.store, connection) as db, _atomic(db):
            if _state(db) is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_attempts'").fetchone():
                raise BulkUnavailable('Existing exact bulk cancellation/journal profile is required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db):
                raise ManagedConflict('Pause ordinary mutations before upgrading captured cancellation controls.')
            controls = BulkCancellations(self.store)
            receipts = []
            for row in db.execute('SELECT * FROM managed_bulk_cancellations'):
                owner = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?', (row['import_id'],)).fetchone()[0]
                controls.policies._root(db, row['import_id'], owner)
                receipts.append((row['import_id'], owner, controls._receipt(db, row)))
            upgrade_schema(db)
            _state(db)
            for key, owner, expected in receipts:
                controls.policies._root(db, key, owner)
                row = db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone()
                if BulkCancellations._receipt(db, row) != expected:
                    raise BulkUnavailable('Upgrade changed an immutable historical cancellation receipt.')


def upgrade_schema(db):
    """Trusted exact DDL, also used to construct expected schema in memory."""
    triggers = ('complete', 'immutable', 'retained', 'member_sealed', 'member_immutable', 'member_retained')
    for name in triggers:
        db.execute(f'DROP TRIGGER managed_bulk_cancellation_{name}')
    db.execute('ALTER TABLE managed_bulk_cancellation_members RENAME TO managed_bulk_old_cancellation_members')
    member_sql = EXPANDED_DDL.split('CREATE TABLE managed_bulk_cancellation_members', 1)[1].split('CREATE TRIGGER', 1)[0]
    execute_schema(db, 'CREATE TABLE managed_bulk_cancellation_members' + member_sql)
    db.execute('''INSERT INTO managed_bulk_cancellation_members
        SELECT *,NULL,NULL FROM managed_bulk_old_cancellation_members''')
    db.execute('DROP TABLE managed_bulk_old_cancellation_members')
    execute_schema(db, 'CREATE TRIGGER' + EXPANDED_DDL.split('CREATE TRIGGER', 1)[1])
    execute_schema(db, DDL)
