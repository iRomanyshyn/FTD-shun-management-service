"""Operator ADD pause, separate from recovery fences and standing authority."""

import json
from datetime import UTC, datetime

from .bulk_policy import BulkUnavailable, _actor, _atomic, _key_free, _quiescent, _state
from .import_preparations import _stamp
from .managed_shuns import ManagedCapacity, ManagedConflict
from .schema import execute_schema, schema_connection

MAX_CHANGES = 10000
DDL = """
CREATE TABLE managed_bulk_controls (
    kind TEXT PRIMARY KEY CHECK(kind IN ('imports','restoration')),
    revision INTEGER NOT NULL CHECK(revision>=0),
    additions_paused INTEGER NOT NULL CHECK(additions_paused IN (0,1)),
    resume_after TEXT,
    last_request_id TEXT REFERENCES managed_bulk_control_requests(id)
);
CREATE TABLE managed_bulk_control_requests (
    id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK(revision>=1),
    expected_revision INTEGER NOT NULL CHECK(expected_revision=revision-1),
    kind TEXT NOT NULL CHECK(kind IN ('imports','restoration')),
    action TEXT NOT NULL CHECK(action IN ('PAUSE','RESUME')),
    actor_subject TEXT NOT NULL,
    actor_display_name TEXT NOT NULL,
    actor_roles TEXT NOT NULL CHECK(json_valid(actor_roles)),
    timestamp TEXT NOT NULL,
    UNIQUE(kind,revision)
);
CREATE TRIGGER managed_bulk_control_request_immutable BEFORE UPDATE ON managed_bulk_control_requests
BEGIN SELECT RAISE(ABORT,'operator control history is immutable'); END;
CREATE TRIGGER managed_bulk_control_request_retained BEFORE DELETE ON managed_bulk_control_requests
BEGIN SELECT RAISE(ABORT,'operator control history is retained'); END;
CREATE TRIGGER managed_bulk_controls_retained BEFORE DELETE ON managed_bulk_controls
BEGIN SELECT RAISE(ABORT,'operator controls are retained'); END;
CREATE TRIGGER managed_bulk_controls_transition BEFORE UPDATE ON managed_bulk_controls
WHEN NEW.kind!=OLD.kind OR NEW.revision!=OLD.revision+1
 OR NEW.additions_paused=OLD.additions_paused
 OR (NEW.additions_paused=1 AND NEW.resume_after IS NOT OLD.resume_after)
 OR (NEW.additions_paused=0 AND (NEW.resume_after IS NULL
     OR (OLD.resume_after IS NOT NULL AND NEW.resume_after<=OLD.resume_after)))
 OR NOT EXISTS(SELECT 1 FROM managed_bulk_control_requests r WHERE r.id=NEW.last_request_id
     AND r.kind=NEW.kind AND r.revision=NEW.revision AND r.expected_revision=OLD.revision
     AND r.action=CASE WHEN NEW.additions_paused=1 THEN 'PAUSE' ELSE 'RESUME' END
     AND (NEW.additions_paused=1 OR r.timestamp=NEW.resume_after))
BEGIN SELECT RAISE(ABORT,'operator controls require an attributed monotonic transition'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_controls'").fetchone() is not None


def read(db):
    """Caller validates the exact profile in its own transaction before use."""
    if not present(db):
        return {'available': False}
    result = {'available': True}
    for kind in ('imports', 'restoration'):
        row = db.execute('SELECT * FROM managed_bulk_controls WHERE kind=?', (kind,)).fetchone()
        if row is None:
            raise BulkUnavailable('Operator ADD controls are incomplete.')
        result[kind] = {'paused': bool(row['additions_paused']), 'revision': row['revision'], 'resume_after': row['resume_after']}
    return result


def validate(db):
    if db.execute('SELECT COUNT(*) FROM managed_bulk_controls').fetchone()[0] != 2:
        raise BulkUnavailable('Exactly two operator controls are required.')
    for kind in ('imports', 'restoration'):
        row = db.execute('SELECT * FROM managed_bulk_controls WHERE kind=?', (kind,)).fetchone()
        requests = db.execute('SELECT * FROM managed_bulk_control_requests WHERE kind=? ORDER BY revision', (kind,)).fetchall()
        if row is None or len(requests) > MAX_CHANGES or row['revision'] != len(requests):
            raise BulkUnavailable('Operator ADD control history is incomplete.')
        paused, barrier, last, previous_time = False, None, None, None
        try:
            for revision, item in enumerate(requests, 1):
                from .bulk_intent import _uuid

                _uuid(item['id'])
                roles = json.loads(item['actor_roles'])
                if type(roles) is not list:
                    raise ValueError('Original actor roles must be an array.')
                _actor(item['actor_subject'], item['actor_display_name'], tuple(roles))
                if (item['revision'] != revision or item['expected_revision'] != revision - 1
                        or item['action'] != ('RESUME' if paused else 'PAUSE')
                        or _stamp(datetime.fromisoformat(item['timestamp'])) != item['timestamp']
                        or (previous_time is not None and item['timestamp'] <= previous_time)):
                    raise ValueError('Invalid operator control transition.')
                paused = item['action'] == 'PAUSE'
                if not paused:
                    barrier = item['timestamp']
                last, previous_time = item['id'], item['timestamp']
        except (ValueError, TypeError, PermissionError) as error:
            raise BulkUnavailable('Operator ADD controls contain invalid actor/transition evidence.') from error
        if (bool(row['additions_paused']), row['resume_after'], row['last_request_id']) != (paused, barrier, last):
            raise BulkUnavailable('Operator ADD controls do not match retained history.')


def restoration_sql(alias='t'):
    """Trusted internal predicate; exact current intent, never creation proof."""
    if alias not in {'t', 'target'}:
        raise ValueError('Fixed target aliases only.')
    return f'''(EXISTS(SELECT 1 FROM managed_bulk_members m WHERE m.request_id={alias}.authorization_request_id
        AND m.device_id={alias}.device_id AND m.ip={alias}.ip
        AND m.intent_id={alias}.intent_id AND m.generation={alias}.generation
        AND m.authorization_request_id={alias}.authorization_request_id
        AND m.classification IN ('PROPOSE_ADOPT','ALREADY_MANAGED'))
      OR EXISTS(SELECT 1 FROM managed_bulk_attempts a WHERE a.device_id={alias}.device_id AND a.ip={alias}.ip
        AND a.intent_id={alias}.intent_id AND a.generation={alias}.generation
        AND a.authorization_request_id={alias}.authorization_request_id AND a.state IN ('VERIFIED','NOOP','OBSERVED_PRESENT'))
      OR EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id={alias}.device_id AND s.ip={alias}.ip
        AND s.last_seen_at>={alias}.updated_at))'''


def kind_for(db, target):
    row = db.execute('SELECT ' + restoration_sql() + ' FROM managed_shun_targets t WHERE t.device_id=? AND t.ip=?',
                     (target['device_id'], target['ip'])).fetchone()
    if row is None:
        raise BulkUnavailable('An ADD control needs an exact current managed target.')
    return 'restoration' if row[0] else 'imports'


def paused_for(db, target):
    control = read(db)
    if not control['available'] or not any(control[kind]['paused'] for kind in ('imports', 'restoration')):
        return False
    return control[kind_for(db, target)]['paused']


def effective_barrier(db, barrier, target=None):
    control = read(db)
    # A pause is scheduling state, not authority revocation. During pause old
    # attempts retain their ordinary evidence/expiry rules. Resume requires a
    # new causal complete read, never replay of an earlier uncertain command.
    if not control['available']:
        return barrier
    if all(control[kind]['resume_after'] is None for kind in ('imports', 'restoration')):
        return barrier
    kinds = (kind_for(db, target),) if target is not None else ('imports', 'restoration')
    return max(filter(None, (barrier, *(control[kind]['resume_after'] for kind in kinds))), default=None)


class ManagedAdditionControls:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def initialize(self, *, connection=None):
        """Explicit stopped/quiescent profile extension; never startup or GET."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            if _state(db) is None or not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='managed_bulk_device_executors'").fetchone():
                raise BulkUnavailable('Existing device-scoped bulk execution profile is required.')
            if present(db):
                return
            _quiescent(db)
            execute_schema(db, DDL)
            db.executemany('INSERT INTO managed_bulk_controls VALUES (?,0,0,NULL,NULL)', [('imports',), ('restoration',)])
            _state(db)

    def change(self, key, kind, action, revision, subject, display_name, roles):
        from .bulk_intent import _uuid

        _uuid(key)
        _actor(subject, display_name, roles)
        if kind not in {'imports', 'restoration'} or action not in {'PAUSE', 'RESUME'} or type(revision) is not int or revision < 0:
            raise ValueError('An exact PAUSE/RESUME action and current control revision are required.')
        with schema_connection(self.store) as db:
            _state(db)
            control = read(db)
            if not control['available']:
                raise BulkUnavailable('Operator ADD controls require explicit profile initialization.')
            old = db.execute('SELECT * FROM managed_bulk_control_requests WHERE id=?', (key,)).fetchone()
            if old:
                if (old['kind'], old['action'], old['expected_revision'], old['actor_subject']) != (kind, action, revision, subject):
                    raise ManagedConflict('The control key belongs to another request.')
                return {**control, 'replayed': True, 'device_work_admitted': False}
            _key_free(db, key)
            selected = control[kind]
            if revision != selected['revision'] or selected['paused'] == (action == 'PAUSE'):
                raise ManagedConflict('Pause state changed. Read the current control before submitting a new request.')
            if revision >= MAX_CHANGES:
                raise ManagedCapacity('Retained operator control history is full.')
            timestamp = _stamp(self.clock())
            previous = db.execute('SELECT timestamp FROM managed_bulk_control_requests WHERE kind=? ORDER BY revision DESC LIMIT 1', (kind,)).fetchone()
            if previous and timestamp <= previous[0]:
                raise ManagedConflict('Control time must advance beyond the previous resume barrier.')
            db.execute('INSERT INTO managed_bulk_control_requests VALUES (?,?,?,?,?,?,?,?,?)',
                       (key, revision + 1, revision, kind, action, subject, display_name, json.dumps(roles), timestamp))
            db.execute('UPDATE managed_bulk_controls SET revision=?,additions_paused=?,resume_after=?,last_request_id=? WHERE kind=?',
                       (revision + 1, int(action == 'PAUSE'), timestamp if action == 'RESUME' else selected['resume_after'], key, kind))
            self.store._insert_event(db, 'MANAGED_ADDITIONS_PAUSED' if action == 'PAUSE' else 'MANAGED_ADDITIONS_RESUMED',
                                     None, None, None, subject, display_name, roles, key,
                                     {'kind': kind, 'control_revision': revision + 1, 'existing_blocks_unchanged': True}, timestamp)
            _state(db)
            return {**read(db), 'replayed': False, 'device_work_admitted': False}
