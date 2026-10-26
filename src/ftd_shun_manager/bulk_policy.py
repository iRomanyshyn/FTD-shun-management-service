"""Isolated version-2 SQLite policy storage; no runtime executor or migration CLI.

Uses the existing effective target/request tables, with a distinct suspended
registry that deliberately makes legacy services refuse this database profile.
"""

import hashlib
import hmac
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from ipaddress import IPv4Address
from pathlib import Path
from uuid import UUID, uuid4

from .bulk_intent import decode_bulk_descriptor, verify_bulk_intent
from .import_preparations import ImportPreparations, _feed, _member, _stamp
from .managed_intent import canonical_managed_change
from .managed_safety import ManagedStateUnavailable
from .managed_shuns import ManagedCapacity, ManagedConflict, ManagedShuns, _require_operator
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection
from .store import Store

MAX_KEYS = 200000
MAX_REQUESTS = 400000
MAX_ROOTS = 128
MAX_MEMBERS = 1000000

_DDL = """
ALTER TABLE managed_shun_registry RENAME TO managed_bulk_registry;
ALTER TABLE managed_bulk_registry ADD COLUMN format_version INTEGER NOT NULL DEFAULT 2 CHECK(format_version=2);
CREATE TRIGGER managed_bulk_no_resume BEFORE UPDATE OF restoration_suspended ON managed_bulk_registry
WHEN NEW.restoration_suspended!=1 BEGIN SELECT RAISE(ABORT,'bulk execution is unavailable'); END;
CREATE TABLE managed_bulk_manifests (
    id TEXT PRIMARY KEY REFERENCES managed_shun_requests(id),
    preparation_id TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64),
    header_json TEXT NOT NULL CHECK(json_valid(header_json)),
    pair_count INTEGER NOT NULL CHECK(pair_count BETWEEN 1 AND 100000),
    accepted_count INTEGER NOT NULL CHECK(accepted_count BETWEEN 1 AND 100000)
);
CREATE TABLE managed_bulk_members (
    request_id TEXT NOT NULL REFERENCES managed_bulk_manifests(id) DEFERRABLE INITIALLY DEFERRED,
    device_id INTEGER NOT NULL REFERENCES devices(id),
    ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    classification TEXT NOT NULL CHECK(classification IN ('PROPOSE_ADD','PROPOSE_ADOPT','ALREADY_MANAGED','EXCLUDED_PROTECTED')),
    observed_at TEXT,
    managed_enabled INTEGER NOT NULL CHECK(managed_enabled IN (0,1)),
    previous_intent_id TEXT, previous_generation INTEGER, previous_authorization_request_id TEXT,
    intent_id TEXT, generation INTEGER, authorization_request_id TEXT REFERENCES managed_shun_requests(id),
    PRIMARY KEY(request_id,device_id,ip),
    CHECK((classification='EXCLUDED_PROTECTED' AND intent_id IS NULL AND generation IS NULL AND authorization_request_id IS NULL)
       OR (classification!='EXCLUDED_PROTECTED' AND intent_id IS NOT NULL AND generation>=1 AND authorization_request_id IS NOT NULL))
);
CREATE TRIGGER managed_bulk_manifest_complete BEFORE INSERT ON managed_bulk_manifests
WHEN NEW.pair_count!=(SELECT COUNT(*) FROM managed_bulk_members WHERE request_id=NEW.id)
 OR NEW.accepted_count!=(SELECT COUNT(*) FROM managed_bulk_members WHERE request_id=NEW.id AND classification!='EXCLUDED_PROTECTED')
BEGIN SELECT RAISE(ABORT,'bulk membership is incomplete'); END;
CREATE TRIGGER managed_bulk_manifest_immutable BEFORE UPDATE ON managed_bulk_manifests
BEGIN SELECT RAISE(ABORT,'bulk manifest is immutable'); END;
CREATE TRIGGER managed_bulk_manifest_retained BEFORE DELETE ON managed_bulk_manifests
BEGIN SELECT RAISE(ABORT,'bulk manifest is retained'); END;
CREATE TRIGGER managed_bulk_member_sealed BEFORE INSERT ON managed_bulk_members
WHEN EXISTS(SELECT 1 FROM managed_bulk_manifests WHERE id=NEW.request_id)
BEGIN SELECT RAISE(ABORT,'bulk membership is sealed'); END;
CREATE TRIGGER managed_bulk_member_immutable BEFORE UPDATE ON managed_bulk_members
BEGIN SELECT RAISE(ABORT,'bulk membership is immutable'); END;
CREATE TRIGGER managed_bulk_member_retained BEFORE DELETE ON managed_bulk_members
BEGIN SELECT RAISE(ABORT,'bulk membership is retained'); END;
"""


class BulkUnavailable(ManagedStateUnavailable):
    """Missing, partial, legacy or unsupported storage; never automatically repaired."""


def _objects(db):
    return [tuple(row) for row in db.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL
        AND (name GLOB 'managed_*' OR name GLOB 'idx_managed_*' OR name GLOB 'incident_*'
            OR name GLOB 'confirmed_import_*' OR name GLOB 'import_cancellation_*' OR tbl_name GLOB 'managed_*')
        ORDER BY type,name""")]


def _initialize(db):
    ManagedShuns(Store(Path('/unused-bulk-schema'))).initialize(connection=db)
    execute_schema(db, _DDL)


@lru_cache(maxsize=9)
def _expected(cancellation=False, attempts=False, waits=False, dispatch=False, devices=False, ordered=False, promotions=False):
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('BEGIN')
        _initialize(db)
        if cancellation:
            from .bulk_cancellations import DDL

            execute_schema(db, DDL)
        if attempts:
            from .bulk_attempts import DDL as attempts_ddl

            execute_schema(db, attempts_ddl)
        if waits:
            from .bulk_waits import upgrade_schema

            upgrade_schema(db)
        if dispatch:
            from .bulk_dispatch import DDL

            execute_schema(db, DDL)
        if devices:
            from .device_leases import DDL

            # Expected-schema construction only: a trigger target, not live queue initialization.
            db.execute('CREATE TABLE operation_executor(id INTEGER PRIMARY KEY,owner TEXT,lease_until TEXT)')
            execute_schema(db, DDL)
        if ordered:
            from .bulk_ordered_waits import DDL

            execute_schema(db, DDL)
        if promotions:
            from .bulk_ordered_promotion import DDL

            execute_schema(db, DDL)
        return _objects(db)


def _state(db):
    objects = _objects(db)
    if not objects:
        return None
    cancellation = any(name.startswith('managed_bulk_cancellation') or table.startswith('managed_bulk_cancellation')
                       for _, name, table, _ in objects)
    attempts = any(name.startswith(('managed_bulk_attempt', 'idx_managed_bulk_attempt')) or table == 'managed_bulk_attempts'
                   for _, name, table, _ in objects)
    waits = any(name.startswith('managed_bulk_wait') or table == 'managed_bulk_wait_results'
                for _, name, table, _ in objects)
    dispatch = any(name.startswith('managed_bulk_dispatch') for _, name, _, _ in objects)
    devices = any(name.startswith('managed_bulk_device') for _, name, _, _ in objects)
    ordered = any(name.startswith(('managed_bulk_ordered_', 'idx_managed_bulk_ordered_'))
                  or table.startswith('managed_bulk_ordered_') for _, name, table, _ in objects)
    promotions = any(name.startswith('managed_bulk_ordered_promotion') for _, name, _, _ in objects)
    if ((attempts and not cancellation) or (waits and not attempts) or (dispatch and not waits)
            or (devices and not dispatch) or (ordered and not devices)
            or (promotions and not ordered)
            or objects != _expected(cancellation, attempts, waits, dispatch, devices, ordered, promotions)):
        raise BulkUnavailable('Exact version-2 storage is required; legacy/partial/optional state was not converted.')
    row = db.execute('SELECT revision,restoration_suspended,format_version FROM managed_bulk_registry WHERE id=1').fetchone()
    if (row is None or type(row[0]) is not int or row[0] < 0 or row[2] != 2
            or row[1] not in ((0, 1) if dispatch else (1,))):
        raise BulkUnavailable('Invalid or unsuspended bulk registry.')
    if dispatch:
        barrier = db.execute('SELECT dispatch_resume_after FROM managed_bulk_registry WHERE id=1').fetchone()[0]
        try:
            if (barrier is None and row[1] == 0) or (barrier is not None and _stamp(datetime.fromisoformat(barrier)) != barrier):
                raise ValueError('Invalid resume barrier')
        except (ValueError, TypeError) as error:
            raise BulkUnavailable('Bulk dispatch requires an exact UTC fresh-read barrier.') from error
    for table, limit in (('managed_shun_targets', MAX_KEYS), ('managed_shun_requests', MAX_REQUESTS),
                         ('managed_bulk_manifests', MAX_ROOTS), ('managed_bulk_members', MAX_MEMBERS)):
        if db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] > limit:
            raise BulkUnavailable('Retained bulk storage exceeds its fixed capacity.')
    if (db.execute("""SELECT 1 FROM managed_bulk_manifests m LEFT JOIN managed_shun_requests r ON r.id=m.id
            WHERE r.id IS NULL OR m.pair_count!=(SELECT COUNT(*) FROM managed_bulk_members b WHERE b.request_id=m.id)
            OR m.accepted_count!=(SELECT COUNT(*) FROM managed_bulk_members b
                WHERE b.request_id=m.id AND b.classification!='EXCLUDED_PROTECTED') LIMIT 1""").fetchone()
            or db.execute('SELECT 1 FROM managed_bulk_members b LEFT JOIN managed_bulk_manifests m ON m.id=b.request_id WHERE m.id IS NULL LIMIT 1').fetchone()
            or db.execute("""SELECT 1 FROM managed_shun_targets t LEFT JOIN devices d ON d.id=t.device_id
                LEFT JOIN managed_shun_requests r ON r.id=t.authorization_request_id
                LEFT JOIN managed_bulk_members b ON b.request_id=t.authorization_request_id AND b.device_id=t.device_id AND b.ip=t.ip
                WHERE d.id IS NULL OR r.id IS NULL OR b.request_id IS NULL OR b.intent_id!=t.intent_id OR b.generation!=t.generation
                    OR b.authorization_request_id!=t.authorization_request_id OR b.classification='EXCLUDED_PROTECTED' LIMIT 1""").fetchone()):
        raise BulkUnavailable('Bulk policy or retained membership is incomplete.')
    if cancellation:
        from .bulk_cancellations import validate

        validate(db)
    if attempts:
        from .bulk_attempts import validate as validate_attempts

        validate_attempts(db)
    if waits:
        from .bulk_waits import validate as validate_waits

        validate_waits(db)
    if devices:
        from .device_leases import validate as validate_devices

        validate_devices(db)
    if ordered:
        from .bulk_ordered_waits import validate as validate_ordered

        validate_ordered(db)
    if promotions:
        from .bulk_ordered_promotion import validate as validate_promotions

        validate_promotions(db)
    return {'revision': row[0], 'restoration_suspended': bool(row[1])}


def confirmed_operation(db, preparation):
    """Optional journal composition only; never adopt a legacy confirmation."""
    if _state(db) is None:
        return None
    row = db.execute("""SELECT m.id,r.actor_subject FROM managed_bulk_manifests m
        JOIN managed_shun_requests r ON r.id=m.id WHERE m.preparation_id=?""", (preparation['id'],)).fetchone()
    if row is not None and row['actor_subject'] != preparation['actor_subject']:
        raise BulkUnavailable('Preparation and bulk authority authors differ.')
    return row['id'] if row else None


def protection_state(db):
    """Recognize exact bulk storage for protection revocation only, never dispatch.

    Validate enabled identities in bounded chunks; the legacy retirement reader
    must not load a potentially 200000-key registry into one Python list.
    """
    try:
        state = _state(db)
        if state is None:
            raise BulkUnavailable('Bulk protection requires an existing exact profile.')
        rows = db.execute('SELECT intent_id,generation FROM managed_shun_targets WHERE enabled=1')
        while chunk := rows.fetchmany(100):
            for row in chunk:
                if (str(UUID(row['intent_id'])) != row['intent_id']
                        or type(row['generation']) is not int or row['generation'] < 1):
                    raise ValueError('Invalid managed identity')
        return {**state, 'format_version': 2}
    except (sqlite3.DatabaseError, ValueError, TypeError, AttributeError) as error:
        raise BulkUnavailable('Bulk retirement is unavailable; enabled protection must remain in place.') from error


class BulkPreparations(ImportPreparations):
    """Explicit bulk-profile classifier; no legacy runtime fallback."""

    @staticmethod
    def _managed_state(db):
        state = _state(db)
        if state is None:
            raise BulkUnavailable('Initialize empty bulk storage explicitly before preparing policy.')
        return state


@contextmanager
def _atomic(db):
    db.execute('SAVEPOINT bulk_policy_change')
    try:
        yield
    except Exception:
        db.execute('ROLLBACK TO bulk_policy_change')
        db.execute('RELEASE bulk_policy_change')
        raise
    db.execute('RELEASE bulk_policy_change')


def _actor(subject, display_name, roles):
    if (type(subject) is not str or not 1 <= len(subject) <= 255 or type(display_name) is not str
            or len(display_name) > 255 or any(ord(char) < 32 for char in subject + display_name)
            or type(roles) is not tuple
            or any(type(role) is not str or role not in {'Viewer', 'Operator', 'Administrator'} for role in roles)
            or len(set(roles)) != len(roles)):
        raise ValueError('A bounded real authenticated actor is required.')
    _require_operator(subject, roles)


def _key_free(db, key):
    for table in ('managed_shun_requests', 'manual_import_batches', 'operation_requests', 'operation_jobs', 'import_preparation_plans'):
        if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                and db.execute(f'SELECT 1 FROM {table} WHERE id=?', (key,)).fetchone()):
            raise ManagedConflict('The key is already reserved; it cannot acquire bulk authority.')


def _quiescent(db):
    row = db.execute('SELECT owner,lease_until FROM operation_executor WHERE id=1').fetchone()
    if row is None or row[0] is not None or row[1] is not None:
        raise ManagedConflict('Settle the executor lease before offline bulk storage changes.')
    from .device_leases import present as devices_present

    if devices_present(db) and db.execute("SELECT 1 FROM managed_bulk_device_executors WHERE state!='IDLE'").fetchone():
        raise ManagedConflict('Settle every device lease/attention before offline bulk storage changes.')
    if db.execute("SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING','UNVERIFIED') LIMIT 1").fetchone():
        raise ManagedConflict('Pending or uncertain work remains; bulk storage never resolves it.')
    from .bulk_attempts import present as attempts_present
    from .bulk_attempts import validate_held_jobs
    from .bulk_waits import present as waits_present
    from .bulk_waits import validate_pending

    if attempts_present(db):
        validate_held_jobs(db)
    if waits_present(db) and validate_pending(db):
        raise ManagedConflict('Captured bulk cancellation remains unsettled; no new authority or migration.')
    from .bulk_ordered_waits import held_count, validate_held_predecessors
    from .bulk_ordered_waits import present as ordered_present

    if ordered_present(db):
        validate_held_predecessors(db)
        if held_count(db):
            raise ManagedConflict('Ordered cleanup reservations remain; no new authority or migration.')


class BulkPolicies:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.preparations = BulkPreparations(store, clock=self.clock)

    def initialize_empty(self, *, connection=None):
        """Internal explicit empty-profile initialization, not a legacy migration."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            if _objects(db):
                raise BulkUnavailable('Existing managed state must be preserved; empty initialization cannot convert or repair it.')
            _quiescent(db)
            if not mutations_suspended(db):
                raise ManagedConflict('Pause ordinary mutations before empty schema initialization.')
            _initialize(db)
            _state(db)

    def confirm(self, canonical, digest, accepted_count, subject, display_name, roles, *, maintain_present=False,
                enabled=False, addition_device_ids=frozenset(), connection=None):
        """Atomic offline policy-only confirmation; no queue, RPC, hints or resume."""
        return self._confirm(canonical, digest, accepted_count, subject, display_name, roles,
            maintain_present=maintain_present, enabled=enabled, addition_device_ids=addition_device_ids,
            connection=connection, concurrent=False, expected_suspended=True)

    def confirm_concurrent(self, canonical, digest, accepted_count, subject, display_name, roles, *, expected_suspended,
                           maintain_present=False, enabled=False, addition_device_ids=frozenset(), connection=None):
        """Separate exact fenced policy admission; never queue, resume or interrupt."""
        return self._confirm(canonical, digest, accepted_count, subject, display_name, roles,
            maintain_present=maintain_present, enabled=enabled, addition_device_ids=addition_device_ids,
            connection=connection, concurrent=True, expected_suspended=expected_suspended)

    def _confirm(self, canonical, digest, accepted_count, subject, display_name, roles, *, maintain_present,
                 enabled, addition_device_ids, connection, concurrent, expected_suspended):
        _actor(subject, display_name, roles)
        if type(expected_suspended) is not bool:
            raise ValueError('An exact reviewed desired-suspension boolean is required.')
        if type(enabled) is not bool or type(maintain_present) is not bool or not maintain_present:
            raise ValueError('Explicit boolean capability and recurring consent are required.')
        if not enabled:
            raise PermissionError('Bulk policy admission is disabled.')
        descriptor = decode_bulk_descriptor(canonical, digest)
        manifest = descriptor['manifest']
        if type(accepted_count) is not int or accepted_count != manifest['accepted_count']:
            raise ValueError('Type the exact accepted pair count.')
        if (type(addition_device_ids) is not frozenset
                or any(type(device) is not int or not 1 <= device <= 65535 for device in addition_device_ids)):
            raise ValueError('Explicit trusted addition-capable devices are required.')
        key, plan_id = descriptor['operation_id'], descriptor['preparation_id']
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None:
                raise BulkUnavailable('Bulk policy storage is not initialized.')
            old = db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
            if old is not None:
                if old['actor_subject'] != subject or old['payload_json'] != canonical:
                    raise ManagedConflict('Original key belongs to a different actor or scope.')
                original = self._root(db, key, subject)[1]
                if (('admission_mode' in original) != concurrent or original['restoration_suspended'] is not expected_suspended):
                    raise ManagedConflict('Original key has a different admission mode or reviewed suspension.')
                return {**original, 'replayed': True}
            _key_free(db, key)
            if not concurrent:
                _quiescent(db)
                if not state['restoration_suspended']:
                    raise ManagedConflict('Policy-only bulk confirmation requires suspended execution; no concurrent admission yet.')
            if mutations_suspended(db):
                raise ManagedConflict('New authority is paused; policy retirement remains available.')
            if not set(manifest['device_ids']).issubset(addition_device_ids):
                raise ManagedConflict('Every selected accepted device needs its own eligible addition profile.')
            if db.execute('SELECT 1 FROM managed_bulk_manifests WHERE preparation_id=?', (plan_id,)).fetchone():
                raise ManagedConflict('Preparation already confirmed; recover its original key.')
            plan, header = self.preparations._verified_plan(db, plan_id, subject, descriptor['preparation_digest'])
            issued = _stamp(self.clock())
            if plan['cancelled_at'] is not None or not plan['created_at'] <= issued < plan['expires_at']:
                raise ManagedConflict('Preparation expired, cancelled or ahead of the clock.')
            if (header['managed_initialized'] is not True or state['revision'] != descriptor['managed_revision']
                    or state['revision'] != header['managed_revision'] or header['protected_revision'] != descriptor['protected_revision']
                    or db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0] != descriptor['protected_revision']
                    or header['label'] != descriptor['label'] or header['reason'] != descriptor['reason']):
                raise ManagedConflict('Reviewed policy or metadata changed; no scope was rebased.')
            devices = [dict(row) for row in db.execute('SELECT id,hostname FROM devices WHERE enabled=1 AND id IN ('
                + ','.join('?' for _ in manifest['device_ids']) + ') ORDER BY id', manifest['device_ids'])]
            if devices != header['devices']:
                raise ManagedConflict('Selected device identities/names/enabled state changed.')
            summary = verify_bulk_intent(canonical, self._classified(db, plan_id), digest)
            if (summary.pair_count != header['target_count'] or summary.address_count != header['address_count']
                    or summary.as_dict()['classification_counts'] != header['classification_counts']):
                raise ManagedConflict('Manifest does not match the complete preparation.')
            requests = db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0]
            new_keys = db.execute('''SELECT COUNT(*) FROM import_preparation_targets p LEFT JOIN managed_shun_targets t
                ON t.device_id=p.device_id AND t.ip=p.ip WHERE p.plan_id=? AND p.classification!='EXCLUDED_PROTECTED' AND t.device_id IS NULL''', (plan_id,)).fetchone()[0]
            if (requests >= MAX_REQUESTS - MAX_KEYS or db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0] + new_keys > MAX_KEYS
                    or db.execute('SELECT COUNT(*) FROM managed_bulk_manifests').fetchone()[0] >= MAX_ROOTS
                    or db.execute('SELECT COUNT(*) FROM managed_bulk_members').fetchone()[0] + summary.pair_count > MAX_MEMBERS):
                raise ManagedCapacity('Bulk storage capacity/reserved retirement budget reached; nothing was evicted.')
            self._validate_current(db, plan_id)
            if concurrent:
                from .bulk_concurrent import check_admission

                check_admission(db, plan_id, manifest['device_ids'], expected_suspended, self.clock())
            result = {'operation_id': key, 'status': 'policy_saved', 'intent_format': 2, 'managed_revision': state['revision'] + 1,
                'changed_targets': summary.classification_counts[0] + summary.classification_counts[1], 'replayed': False,
                'accepted_pairs': accepted_count, 'classification_counts': summary.as_dict()['classification_counts'],
                'policy_only': True, 'device_work_admitted': False, 'restoration_suspended': expected_suspended,
                'confirmation_actor': {'subject': subject, 'display_name': display_name, 'roles': list(roles)}}
            if concurrent: result['admission_mode'] = 'fenced'
            db.execute('INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)',
                (key, subject, display_name, json.dumps(roles), canonical, json.dumps(result), issued))
            self._apply_members(db, key, plan_id, state['revision'] + 1, issued, subject, display_name, roles)
            db.execute('INSERT INTO managed_bulk_manifests VALUES (?,?,?,?,?,?)',
                (key, plan_id, digest, plan['header_json'], summary.pair_count, accepted_count))
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (state['revision'] + 1,))
            self.store._insert_event(db, 'MANAGED_BULK_IMPORT_CONFIRMED', None, None, None, subject, display_name, roles, key,
                {'intent_format': 2, 'accepted_pairs': accepted_count, 'device_work_admitted': False}, issued)
            if not issued <= _stamp(self.clock()) < plan['expires_at']:
                raise ManagedConflict('Preparation expired or clock moved backwards during confirmation.')
            if concurrent:
                check_admission(db, plan_id, manifest['device_ids'], expected_suspended, self.clock())
            self._root(db, key, subject)
            return result

    @staticmethod
    def _classified(db, plan_id):
        cursor = db.execute('SELECT device_id,ip,classification FROM import_preparation_targets WHERE plan_id=? ORDER BY device_id,ip', (plan_id,))
        while chunk := cursor.fetchmany(100):
            for row in chunk:
                yield row['device_id'], IPv4Address(row['ip']), row['classification']

    @staticmethod
    def _validate_current(db, plan_id):
        cursor = db.execute('''SELECT p.*,t.enabled,t.intent_id,t.generation,t.authorization_request_id,
            EXISTS(SELECT 1 FROM protected_ips q WHERE q.ip=p.ip AND q.enabled=1) AS protected,
            EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=p.device_id AND s.ip=p.ip AND s.active=1) AS observed
            FROM import_preparation_targets p LEFT JOIN managed_shun_targets t ON t.device_id=p.device_id AND t.ip=p.ip
            WHERE p.plan_id=? ORDER BY p.device_id,p.ip''', (plan_id,))
        while chunk := cursor.fetchmany(100):
            for row in chunk:
                kind = ('EXCLUDED_PROTECTED' if row['protected'] else 'ALREADY_MANAGED' if row['enabled']
                        else 'PROPOSE_ADOPT' if row['observed'] else 'PROPOSE_ADD')
                if (kind != row['classification'] or bool(row['enabled']) != bool(row['managed_enabled'])
                        or any(row[current] != row[previous] for current, previous in (
                            ('intent_id', 'previous_intent_id'), ('generation', 'previous_generation'),
                            ('authorization_request_id', 'previous_authorization_request_id')))):
                    raise ManagedConflict('Current classification/generation differs; the whole import is unchanged.')

    def _apply_members(self, db, key, plan_id, revision, timestamp, subject, display_name, roles):
        cursor = db.execute('SELECT * FROM import_preparation_targets WHERE plan_id=? ORDER BY device_id,ip', (plan_id,))
        while chunk := cursor.fetchmany(100):
            members = []
            for row in chunk:
                assigned = (None, None, None)
                kind = row['classification']
                if kind != 'EXCLUDED_PROTECTED':
                    assigned = ((row['previous_intent_id'], row['previous_generation'], row['previous_authorization_request_id'])
                                if kind == 'ALREADY_MANAGED' else (str(uuid4()), (row['previous_generation'] or 0) + 1, key))
                    if kind != 'ALREADY_MANAGED':
                        db.execute('''INSERT INTO managed_shun_targets VALUES (?,?,?,?,1,?,?,?,?,NULL)
                            ON CONFLICT(device_id,ip) DO UPDATE SET intent_id=excluded.intent_id,generation=excluded.generation,
                            enabled=1,revision=excluded.revision,authorization_request_id=excluded.authorization_request_id,
                            authorized_at=excluded.authorized_at,updated_at=excluded.updated_at,retired_at=NULL''',
                            (row['device_id'], row['ip'], assigned[0], assigned[1], revision, key, timestamp, timestamp))
                    event = 'MANAGED_SHUN_ADOPTED' if kind == 'PROPOSE_ADOPT' else 'MANAGED_SHUN_POLICY_NOOP' if kind == 'ALREADY_MANAGED' else 'MANAGED_SHUN_AUTHORIZED'
                    self.store._insert_event(db, event, row['device_id'], IPv4Address(row['ip']), None, subject, display_name,
                        roles, key, {'source': 'managed_bulk_policy_v2', 'intent_id': assigned[0], 'generation': assigned[1],
                                     'managed_revision': revision}, timestamp)
                members.append((key, row['device_id'], row['ip'], kind, row['observed_at'], row['managed_enabled'],
                    row['previous_intent_id'], row['previous_generation'], row['previous_authorization_request_id'], *assigned))
            db.executemany('INSERT INTO managed_bulk_members VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', members)

    def _root(self, db, key, subject):
        row = db.execute('''SELECT m.*,r.actor_subject,r.actor_display_name,r.actor_roles_json,r.payload_json,r.result_json
            FROM managed_bulk_manifests m JOIN managed_shun_requests r ON r.id=m.id WHERE m.id=? AND r.actor_subject=?''', (key, subject)).fetchone()
        if row is None:
            raise BulkUnavailable('Bulk receipt is not available to this owner.')
        header = json.loads(row['header_json'])
        source = hashlib.sha256()
        _feed(source, header)

        def records():
            cursor = db.execute('SELECT * FROM managed_bulk_members WHERE request_id=? ORDER BY device_id,ip', (key,))
            while chunk := cursor.fetchmany(100):
                for member in chunk:
                    _feed(source, _member(member))
                    kind = member['classification']
                    if kind == 'ALREADY_MANAGED':
                        expected = tuple(member[name] for name in ('previous_intent_id','previous_generation','previous_authorization_request_id'))
                    elif kind == 'EXCLUDED_PROTECTED':
                        expected = (None, None, None)
                    else:
                        expected = (member['intent_id'], (member['previous_generation'] or 0) + 1, key)
                        if str(UUID(member['intent_id'])) != member['intent_id']:
                            raise BulkUnavailable('Invalid assigned intent identity.')
                    if tuple(member[name] for name in ('intent_id','generation','authorization_request_id')) != expected:
                        raise BulkUnavailable('Assigned bulk authority does not match its original classification.')
                    yield member['device_id'], IPv4Address(member['ip']), kind

        summary = verify_bulk_intent(row['payload_json'], records(), row['payload_digest'])
        descriptor = decode_bulk_descriptor(row['payload_json'], row['payload_digest'])
        result = json.loads(row['result_json'])
        concurrent = type(result) is dict and 'admission_mode' in result
        if (not hmac.compare_digest(source.hexdigest(), descriptor['preparation_digest'])
                or descriptor['operation_id'] != key or descriptor['preparation_id'] != row['preparation_id']
                or header['plan_id'] != row['preparation_id'] or header['actor_subject'] != subject
                or summary.pair_count != row['pair_count'] or summary.accepted_count != row['accepted_count']
                or type(result) is not dict or set(result) != {'operation_id','status','intent_format','managed_revision',
                    'changed_targets','replayed','accepted_pairs','classification_counts','policy_only','device_work_admitted',
                    'restoration_suspended','confirmation_actor'} | ({'admission_mode'} if concurrent else set())
                or result['status'] != 'policy_saved' or type(result['intent_format']) is not int or result['intent_format'] != 2
                or type(result['managed_revision']) is not int or result['managed_revision'] != descriptor['managed_revision'] + 1
                or type(result['changed_targets']) is not int or result['changed_targets'] != sum(summary.classification_counts[:2])
                or result['replayed'] is not False or type(result['restoration_suspended']) is not bool
                or (concurrent and result['admission_mode'] != 'fenced')
                or (not concurrent and result['restoration_suspended'] is not True)
                or result['operation_id'] != key or type(result['accepted_pairs']) is not int or result['accepted_pairs'] != summary.accepted_count
                or result['classification_counts'] != summary.as_dict()['classification_counts']
                or result['confirmation_actor'] != {'subject': row['actor_subject'], 'display_name': row['actor_display_name'],
                                                     'roles': json.loads(row['actor_roles_json'])}
                or result['policy_only'] is not True or result['device_work_admitted'] is not False):
            raise BulkUnavailable('Retained source, descriptor, actor or receipt is inconsistent.')
        return row, result, summary

    def list_for_owner(self, subject):
        """Bounded historical references for lost-reply/restart recovery."""
        with self.store._connection() as db:
            db.execute('BEGIN')
            if _state(db) is None:
                return {'initialized': False, 'read_only': True, 'can_execute': False, 'items': []}
            rows = db.execute('''SELECT m.id,m.preparation_id,m.payload_digest,m.pair_count,m.accepted_count,r.requested_at
                FROM managed_bulk_manifests m JOIN managed_shun_requests r ON r.id=m.id WHERE r.actor_subject=?
                ORDER BY r.requested_at DESC,m.id LIMIT ?''', (subject, MAX_ROOTS)).fetchall()
            return {'initialized': True, 'read_only': True, 'can_execute': False, 'items': [dict(row) for row in rows]}

    def page(self, key, subject, *, page=1):
        if type(page) is not int or page < 1:
            raise ValueError('Select a positive receipt page.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            if _state(db) is None:
                raise BulkUnavailable('Bulk storage is not initialized.')
            root, result, summary = self._root(db, key, subject)
            pages = (summary.pair_count + 99) // 100
            if page > pages:
                raise ValueError('Select a page within the whole retained import.')
            rows = db.execute('SELECT * FROM managed_bulk_members WHERE request_id=? ORDER BY device_id,ip LIMIT 100 OFFSET ?',
                              (key, (page - 1) * 100)).fetchall()
            return {'intent_format': 2, 'historical_confirmation': True, 'read_only': True, 'can_execute': False,
                'operation_id': key, 'preparation_id': root['preparation_id'], 'result': result, 'manifest': summary.as_dict(),
                'page': page, 'pages': pages, 'targets': [{**dict(row), 'ip': str(IPv4Address(row['ip']))} for row in rows]}

    def policy_page(self, page=1, *, revision=None):
        if type(page) is not int or page < 1 or (revision is not None and (type(revision) is not int or revision < 0)):
            raise ValueError('Invalid policy page/revision.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            state = _state(db)
            if state is None:
                raise BulkUnavailable('Bulk policy is not initialized.')
            if revision is not None and revision != state['revision']:
                raise ManagedConflict('Policy changed; open the current policy before paging.')
            total = db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0]
            pages = max(1, (total + 99) // 100)
            if page > pages:
                raise ValueError('Select a page within retained policy.')
            rows = db.execute('''SELECT t.*,d.hostname,r.actor_subject,r.actor_display_name,r.actor_roles_json
                FROM managed_shun_targets t JOIN devices d ON d.id=t.device_id JOIN managed_shun_requests r
                ON r.id=t.authorization_request_id ORDER BY t.device_id,t.ip LIMIT 100 OFFSET ?''', ((page - 1) * 100,)).fetchall()
            return {**state, 'intent_format': 2, 'total': total, 'limit': MAX_KEYS, 'page': page, 'pages': pages,
                    'read_only': True, 'can_execute': False,
                    'entries': [{**dict(row), 'ip': str(IPv4Address(row['ip']))} for row in rows]}

    def retire(self, key, pairs, revision, digest, subject, display_name, roles, *, reason='', connection=None):
        """Stop only policy; never REMOVE, interrupt jobs, resume or re-enable."""
        _actor(subject, display_name, roles)
        if type(key) is not str or str(UUID(key)) != key:
            raise ValueError('An exact original operation UUID is required.')
        pairs, payload, expected = canonical_managed_change('RETIRE', pairs, revision, 0, reason=reason)
        if type(digest) is not str or not hmac.compare_digest(expected, digest):
            raise ValueError('Exact reviewed retirement digest required.')
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None:
                raise BulkUnavailable('Bulk policy is not initialized.')
            old = db.execute('SELECT * FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
            if old:
                if old['actor_subject'] != subject or old['payload_json'] != payload:
                    raise ManagedConflict('Key is already used for another intention.')
                return {**json.loads(old['result_json']), 'replayed': True}
            _key_free(db, key)
            if state['revision'] != revision:
                raise ManagedConflict('Policy changed; review exact retirement again.')
            rows = [db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?', (device, ip.packed)).fetchone()
                    for device, ip in pairs]
            if any(row is None for row in rows):
                raise ManagedConflict('The entire retirement scope must be retained managed policy.')
            changed = sum(bool(row['enabled']) for row in rows)
            count = db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0]
            if count >= MAX_REQUESTS or (not changed and count >= MAX_REQUESTS - MAX_KEYS):
                raise ManagedCapacity('Retirement ledger is full or reserved for actual revocation.')
            timestamp = _stamp(self.clock())
            result = {'operation_id': key, 'status': 'policy_saved', 'managed_revision': revision + 1,
                      'changed_targets': changed, 'replayed': False}
            db.execute('INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)',
                (key, subject, display_name, json.dumps(roles), payload, json.dumps(result), timestamp))
            for row in rows:
                if row['enabled']:
                    db.execute('UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=? WHERE device_id=? AND ip=?',
                        (revision + 1, timestamp, timestamp, row['device_id'], row['ip']))
                self.store._insert_event(db, 'MANAGED_SHUN_RETIRED' if row['enabled'] else 'MANAGED_SHUN_POLICY_NOOP',
                    row['device_id'], IPv4Address(row['ip']), None, subject, display_name, roles, key,
                    {'source': 'managed_bulk_policy_v2', 'intent_id': row['intent_id'], 'generation': row['generation']}, timestamp)
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (revision + 1,))
            return result
