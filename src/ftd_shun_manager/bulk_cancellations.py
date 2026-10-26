"""Large-import revocation before version-aware dispatch; no device executor.

The initial suspended profile has no attempt ledger. Unattributable ADD evidence
therefore conflicts instead of being mistaken for completed or unsent work.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from itertools import islice

from .bulk_intent import _digest, _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _actor, _atomic, _quiescent, _state
from .import_preparations import _feed, _stamp
from .managed_shuns import ManagedConflict
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

DDL = """
CREATE TABLE managed_bulk_cancellations (
    import_id TEXT PRIMARY KEY REFERENCES managed_bulk_manifests(id),
    actor_subject TEXT NOT NULL, actor_display_name TEXT NOT NULL,
    actor_roles_json TEXT NOT NULL CHECK(json_valid(actor_roles_json)),
    reviewed_at TEXT NOT NULL, review_digest TEXT NOT NULL CHECK(length(review_digest)=64),
    requested_at TEXT NOT NULL, scope_digest TEXT NOT NULL CHECK(length(scope_digest)=64),
    accepted_count INTEGER NOT NULL CHECK(accepted_count BETWEEN 1 AND 100000),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TABLE managed_bulk_cancellation_members (
    import_id TEXT NOT NULL REFERENCES managed_bulk_cancellations(import_id) DEFERRABLE INITIALLY DEFERRED,
    device_id INTEGER NOT NULL, ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    classification TEXT NOT NULL CHECK(classification IN ('PROPOSE_ADD','PROPOSE_ADOPT','ALREADY_MANAGED')),
    intent_id TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=1),
    authorization_request_id TEXT NOT NULL,
    current_revision INTEGER NOT NULL CHECK(current_revision>=0),
    state TEXT NOT NULL CHECK(state IN ('STOPPED_UNSENT','RETAINED_ADOPTED','RETAINED_EXISTING','ALREADY_STOPPED','SUPERSEDED')),
    PRIMARY KEY(import_id,device_id,ip),
    FOREIGN KEY(import_id,device_id,ip) REFERENCES managed_bulk_members(request_id,device_id,ip)
);
CREATE TRIGGER managed_bulk_cancellation_complete BEFORE INSERT ON managed_bulk_cancellations
WHEN NEW.accepted_count!=(SELECT accepted_count FROM managed_bulk_manifests WHERE id=NEW.import_id)
 OR NEW.accepted_count!=(SELECT COUNT(*) FROM managed_bulk_cancellation_members WHERE import_id=NEW.import_id)
BEGIN SELECT RAISE(ABORT,'bulk cancellation scope is incomplete'); END;
CREATE TRIGGER managed_bulk_cancellation_immutable BEFORE UPDATE ON managed_bulk_cancellations
BEGIN SELECT RAISE(ABORT,'bulk cancellation is immutable'); END;
CREATE TRIGGER managed_bulk_cancellation_retained BEFORE DELETE ON managed_bulk_cancellations
BEGIN SELECT RAISE(ABORT,'bulk cancellation is retained'); END;
CREATE TRIGGER managed_bulk_cancellation_member_sealed BEFORE INSERT ON managed_bulk_cancellation_members
WHEN EXISTS(SELECT 1 FROM managed_bulk_cancellations WHERE import_id=NEW.import_id)
BEGIN SELECT RAISE(ABORT,'bulk cancellation membership is sealed'); END;
CREATE TRIGGER managed_bulk_cancellation_member_immutable BEFORE UPDATE ON managed_bulk_cancellation_members
BEGIN SELECT RAISE(ABORT,'bulk cancellation scope is immutable'); END;
CREATE TRIGGER managed_bulk_cancellation_member_retained BEFORE DELETE ON managed_bulk_cancellation_members
BEGIN SELECT RAISE(ABORT,'bulk cancellation scope is retained'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_cancellation*' LIMIT 1").fetchone() is not None


def validate(db):
    """Called only after exact schema recognition; no migration or repair."""
    if (db.execute('''SELECT 1 FROM managed_bulk_cancellations c LEFT JOIN managed_bulk_manifests m ON m.id=c.import_id
            WHERE m.id IS NULL OR c.accepted_count!=m.accepted_count OR c.accepted_count!=(SELECT COUNT(*)
                FROM managed_bulk_cancellation_members b WHERE b.import_id=c.import_id) LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_cancellation_members c
                LEFT JOIN managed_bulk_cancellations r ON r.import_id=c.import_id
                LEFT JOIN managed_bulk_members m ON m.request_id=c.import_id AND m.device_id=c.device_id AND m.ip=c.ip
                WHERE r.import_id IS NULL OR m.request_id IS NULL OR m.classification!=c.classification
                    OR m.intent_id!=c.intent_id OR m.generation!=c.generation
                    OR m.authorization_request_id!=c.authorization_request_id LIMIT 1''').fetchone()):
        raise BulkUnavailable('Retained cancellation membership is incomplete or inconsistent.')


def authorized_root(db, policies, key, subject, roles):
    """Current permission plus the whole original immutable root, never observations."""
    _uuid(key)
    _actor(subject, '', roles)
    if _state(db) is None:
        raise BulkUnavailable('Bulk policy is not initialized.')
    owner = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
    if owner is None or (owner[0] != subject and 'Administrator' not in roles):
        raise PermissionError('Original import owner or Administrator required.')
    return policies._root(db, key, owner[0])[0]


def _scope(db, key):
    from .bulk_waits import classify
    from .bulk_waits import present as waits_present

    waits = waits_present(db)
    cursor = db.execute('''SELECT m.*,t.intent_id AS current_intent,t.generation AS current_generation,
        t.authorization_request_id AS current_authority,t.enabled AS target_enabled,t.revision AS current_revision,
        EXISTS(SELECT 1 FROM operation_jobs j WHERE j.device_id=m.device_id AND j.ip=m.ip AND j.action='ADD') AS add_evidence,
        EXISTS(SELECT 1 FROM operation_jobs j WHERE j.device_id=m.device_id AND j.ip=m.ip
            AND j.state IN ('QUEUED','RUNNING')) AS unfinished
        FROM managed_bulk_members m LEFT JOIN managed_shun_targets t ON t.device_id=m.device_id AND t.ip=m.ip
        WHERE m.request_id=? AND m.classification!='EXCLUDED_PROTECTED' ORDER BY m.device_id,m.ip''', (key,))
    while chunk := cursor.fetchmany(100):
        for row in chunk:
            extra = {}
            if row['current_intent'] is None:
                raise BulkUnavailable('Original effective policy is missing; no empty scope was inferred.')
            if (type(row['current_revision']) is not int or row['current_revision'] < 0
                    or type(row['target_enabled']) is not int or row['target_enabled'] not in (0, 1)):
                raise BulkUnavailable('Current policy revision or enabled state is invalid.')
            if (row['current_intent'], row['current_generation'], row['current_authority']) != (
                    row['intent_id'], row['generation'], row['authorization_request_id']):
                state = 'SUPERSEDED'
            elif not row['target_enabled']:
                state = 'ALREADY_STOPPED'
            elif row['classification'] == 'ALREADY_MANAGED':
                state = 'RETAINED_EXISTING'
            elif row['classification'] == 'PROPOSE_ADOPT':
                state = 'RETAINED_ADOPTED'
            elif waits:
                extra = classify(db, row)
                state = extra.pop('state')
            elif row['add_evidence'] or row['unfinished']:
                raise ManagedConflict('ADD evidence or unfinished work needs version-aware settlement before bulk cancellation.')
            else:
                state = 'STOPPED_UNSENT'
            yield {'device_id': row['device_id'], 'ip': str(IPv4Address(row['ip'])),
                   **{name: row[name] for name in ('classification', 'intent_id', 'generation',
                                                 'authorization_request_id', 'current_revision')}, 'state': state, **extra}


def _summary(rows):
    checksum, counts, total = hashlib.sha256(b'ftd-shun-manager:bulk-cancellation-scope:v2\n'), {}, 0
    for row in rows:
        _feed(checksum, row)
        counts[row['state']] = counts.get(row['state'], 0) + 1
        total += 1
    return checksum.hexdigest(), counts, total


class BulkCancellations:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.policies = BulkPolicies(store, clock=self.clock)

    def initialize(self, *, connection=None):
        """Explicit additive extension of exact bulk state; never a startup hook."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            if _state(db) is None:
                raise BulkUnavailable('Existing exact bulk policy storage is required.')
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db):
                raise ManagedConflict('Pause ordinary mutations before initializing cancellation controls.')
            execute_schema(db, DDL)
            _state(db)

    def _root(self, db, key, subject, roles):
        root = authorized_root(db, self.policies, key, subject, roles)
        if not present(db):
            raise BulkUnavailable('Initialize bulk cancellation controls explicitly before use.')
        return root

    def _review(self, db, root, subject, reviewed_at):
        scope_digest, counts, count = _summary(_scope(db, root['id']))
        if count != root['accepted_count']:
            raise BulkUnavailable('Whole accepted import scope is required.')
        payload = {'version': 2, 'scope': 'bulk_import_cancellation', 'operation_id': root['id'],
            'receipt_digest': root['payload_digest'], 'actor_subject': subject, 'reviewed_at': reviewed_at,
            'managed_revision': _state(db)['revision'],
            'protected_revision': db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0],
            'scope_digest': scope_digest, 'accepted_count': count, 'counts': counts}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'operation_id': root['id'], 'reviewed_at': reviewed_at, 'review_digest': digest,
            'expires_at': _stamp(datetime.fromisoformat(reviewed_at) + timedelta(minutes=5)),
            'accepted_count': count, 'counts': counts, 'scope_digest': scope_digest,
            'can_cancel': True, 'device_work_admitted': False}

    def review(self, key, subject, roles):
        with self.store._connection() as db:
            db.execute('BEGIN')
            root = self._root(db, key, subject, roles)
            old = db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone()
            if old:
                self._receipt(db, old)
                return {'operation_id': key, 'can_cancel': False, 'already_requested': True}
            return self._review(db, root, subject, _stamp(self.clock()))

    def cancel(self, key, reviewed_at, review_digest, accepted_count, subject, display_name, roles, *, connection=None):
        _actor(subject, display_name, roles)
        _uuid(key)
        _digest(review_digest)
        if type(accepted_count) is not int or not 1 <= accepted_count <= 100000 or type(reviewed_at) is not str:
            raise ValueError('An exact accepted pair count and review timestamp are required.')
        if len(reviewed_at) > 40:
            raise ValueError('Invalid UTC review timestamp.')
        reviewed = datetime.fromisoformat(reviewed_at)
        if _stamp(reviewed) != reviewed_at:
            raise ValueError('Use the exact UTC review timestamp.')
        with schema_connection(self.store, connection) as db, _atomic(db):
            root = self._root(db, key, subject, roles)
            old = db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone()
            if old:
                if (old['actor_subject'] != subject or old['actor_display_name'] != display_name
                        or json.loads(old['actor_roles_json']) != list(roles) or old['reviewed_at'] != reviewed_at
                        or old['review_digest'] != review_digest or old['accepted_count'] != accepted_count):
                    raise ManagedConflict('The root already has a different immutable cancellation decision.')
                return {**self._receipt(db, old), 'replayed': True}
            self._fresh(reviewed)
            review = self._review(db, root, subject, reviewed_at)
            if accepted_count != review['accepted_count'] or not hmac.compare_digest(review_digest, review['review_digest']):
                raise ManagedConflict('Cancellation scope changed; review the whole import again.')
            revision = _state(db)['revision']
            changed = sum(count for state, count in review['counts'].items() if state.startswith('STOPPED_'))
            timestamp = _stamp(self.clock())
            result = {'operation_id': key, 'intent_format': 2, 'status': 'cancelled_uncompleted',
                'accepted_count': accepted_count, 'counts': review['counts'], 'changed_targets': changed,
                'managed_revision': revision + bool(changed), 'device_work_admitted': False,
                'device_removal_requested': False, 'replayed': False}
            from .bulk_waits import present as waits_present

            waits = waits_present(db)
            insert_sql = 'INSERT INTO managed_bulk_cancellation_members VALUES (' + ','.join('?' for _ in range(11 if waits else 9)) + ')'
            members = []
            for row in _scope(db, key):
                ip = IPv4Address(row['ip'])
                if row['state'].startswith('STOPPED_'):
                    updated = db.execute('''UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=?
                        WHERE device_id=? AND ip=? AND intent_id=? AND generation=? AND authorization_request_id=? AND enabled=1''',
                        (revision + 1, timestamp, timestamp, row['device_id'], ip.packed, row['intent_id'], row['generation'], row['authorization_request_id'])).rowcount
                    if updated != 1:
                        raise BulkUnavailable('The exact original cancellation generation could not be retired.')
                    self.store._insert_event(db, 'MANAGED_SHUN_RETIRED', row['device_id'], ip, None, subject, display_name, roles, key,
                        {'source': 'managed_bulk_cancellation_v2', 'intent_id': row['intent_id'], 'generation': row['generation'],
                         'authorization_request_id': row['authorization_request_id'], 'managed_revision': revision + 1}, timestamp)
                member = (key, row['device_id'], ip.packed, *(row[name] for name in (
                    'classification', 'intent_id', 'generation', 'authorization_request_id', 'current_revision', 'state')))
                members.append((*member, row.get('job_id'), row.get('attempt_digest')) if waits else member)
                if len(members) == 100:
                    db.executemany(insert_sql, members)
                    members.clear()
            db.executemany(insert_sql, members)
            db.execute('''INSERT INTO managed_bulk_cancellations VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (key, subject, display_name, json.dumps(roles), reviewed_at, review_digest, timestamp,
                 review['scope_digest'], accepted_count, json.dumps(result)))
            if changed:
                db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1', (revision + 1,))
            if waits:
                from .operation_queue import OperationQueue

                queue = OperationQueue(self.store)
                jobs = db.execute("""SELECT job_id FROM managed_bulk_cancellation_members WHERE import_id=?
                    AND state IN ('STOPPED_UNSENT','STOPPED_FAILED','STOPPED_UNVERIFIED') AND job_id IS NOT NULL
                    ORDER BY device_id,ip""", (key,))
                while chunk := jobs.fetchmany(100):
                    for row in chunk:
                        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (row['job_id'],)).fetchone()
                        if job is None or job['state'] != 'QUEUED':
                            raise BulkUnavailable('Owned unsent cancellation predecessor changed before commit.')
                        queue._finish(db, job, 'CANCELLED', 'Original bulk import cancelled before dispatch')
            self.store._insert_event(db, 'MANAGED_BULK_IMPORT_CANCELLED', None, None, None, subject, display_name, roles, key,
                {'counts': review['counts'], 'accepted_count': accepted_count, 'device_work_admitted': False,
                 'device_removal_requested': False}, timestamp)
            self._fresh(reviewed)
            self._receipt(db, db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone())
            return result

    def review_page(self, key, reviewed_at, review_digest, accepted_count, subject, roles, *, page=1):
        """Read exact still-current accepted members; no rebase, migration or writes."""
        _digest(review_digest)
        if type(accepted_count) is not int or not 1 <= accepted_count <= 100000 or type(page) is not int:
            raise ValueError('Exact accepted count and canonical page required.')
        reviewed = datetime.fromisoformat(reviewed_at)
        if reviewed.utcoffset() != timedelta(0) or _stamp(reviewed) != reviewed_at:
            raise ValueError('Original canonical UTC review time required.')
        pages = (accepted_count + 99) // 100
        if not 1 <= page <= pages:
            raise ValueError('Select a page within the exact accepted scope.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            root = self._root(db, key, subject, roles)
            if db.execute('SELECT 1 FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone():
                raise ManagedConflict('Cancellation already requested; inspect its retained status.')
            self._fresh(reviewed)
            review = self._review(db, root, subject, reviewed_at)
            if review['accepted_count'] != accepted_count or not hmac.compare_digest(review['review_digest'], review_digest):
                raise ManagedConflict('Original cancellation review changed; no page was rebased.')
            targets = list(islice(_scope(db, key), (page - 1) * 100, page * 100))
            self._fresh(reviewed)
            return {'review': review, 'page': page, 'pages': pages, 'targets': targets}

    def _fresh(self, reviewed):
        if not reviewed <= self.clock() < reviewed + timedelta(minutes=5):
            raise ManagedConflict('Cancellation review expired or clock moved backwards; review again.')

    @staticmethod
    def _receipt(db, decision):
        def members():
            cursor = db.execute('SELECT * FROM managed_bulk_cancellation_members WHERE import_id=? ORDER BY device_id,ip', (decision['import_id'],))
            while chunk := cursor.fetchmany(100):
                for row in chunk:
                    member = {name: str(IPv4Address(row[name])) if name == 'ip' else row[name] for name in (
                        'device_id', 'ip', 'classification', 'intent_id', 'generation', 'authorization_request_id', 'current_revision', 'state')}
                    fields = row.keys()  # sqlite3.Row membership tests values, not column names.
                    for name in ('job_id', 'attempt_digest'):
                        if name in fields and row[name] is not None:
                            member[name] = row[name]
                    yield member
        checksum, counts, count = _summary(members())
        result = json.loads(decision['result_json'])
        expected = {'operation_id', 'intent_format', 'status', 'accepted_count', 'counts', 'changed_targets',
                    'managed_revision', 'device_work_admitted', 'device_removal_requested', 'replayed'}
        if (type(result) is not dict or set(result) != expected or result['operation_id'] != decision['import_id']
                or type(result['intent_format']) is not int or result['intent_format'] != 2
                or result['status'] != 'cancelled_uncompleted' or type(result['accepted_count']) is not int
                or result['accepted_count'] != count or count != decision['accepted_count']
                or result['counts'] != counts or type(result['changed_targets']) is not int
                or result['changed_targets'] != sum(count for state, count in counts.items() if state.startswith('STOPPED_'))
                or type(result['managed_revision']) is not int or result['managed_revision'] < 0
                or result['device_work_admitted'] is not False or result['device_removal_requested'] is not False
                or result['replayed'] is not False or not hmac.compare_digest(checksum, decision['scope_digest'])):
            raise BulkUnavailable('Retained cancellation receipt or scope is inconsistent.')
        return result

    def page(self, key, subject, roles, *, page=1):
        if type(page) is not int or page < 1:
            raise ValueError('Select a positive cancellation page.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            self._root(db, key, subject, roles)
            decision = db.execute('SELECT * FROM managed_bulk_cancellations WHERE import_id=?', (key,)).fetchone()
            if decision is None:
                return {'operation_id': key, 'requested': False, 'read_only': True, 'can_execute': False}
            result = self._receipt(db, decision)
            pages = (decision['accepted_count'] + 99) // 100
            if page > pages:
                raise ValueError('Select a page within the retained cancellation.')
            rows = db.execute('''SELECT * FROM managed_bulk_cancellation_members WHERE import_id=?
                ORDER BY device_id,ip LIMIT 100 OFFSET ?''', (key, (page - 1) * 100)).fetchall()
            from .bulk_waits import present as waits_present
            from .bulk_waits import validate_pending

            if waits_present(db):
                validate_pending(db)
                counts = dict(db.execute('''SELECT COALESCE(r.state,m.state),COUNT(*) FROM managed_bulk_cancellation_members m
                    LEFT JOIN managed_bulk_wait_results r ON r.import_id=m.import_id AND r.device_id=m.device_id AND r.ip=m.ip
                    WHERE m.import_id=? GROUP BY COALESCE(r.state,m.state)''', (key,)))
                targets = []
                for row in rows:
                    settled = db.execute('''SELECT state,attention,outcome,settled_at FROM managed_bulk_wait_results
                        WHERE import_id=? AND device_id=? AND ip=?''', (key, row['device_id'], row['ip'])).fetchone()
                    current = dict(settled) if settled else {'state': row['state'], 'attention': row['state'] in {'STOPPED_FAILED','STOPPED_UNVERIFIED'}}
                    targets.append({**dict(row), 'ip': str(IPv4Address(row['ip'])), 'initial_state': row['state'], **current})
                return {'operation_id': key, 'requested': True, 'read_only': True, 'can_execute': False,
                    'historical_cancellation': True, 'settled': not counts.get('WAITING_OUTCOME', 0),
                    'page': page, 'pages': pages, 'result': result, 'current_counts': counts,
                    'attention_count': sum(counts.get(state, 0) for state in ('STOPPED_FAILED', 'STOPPED_UNVERIFIED'))
                        + db.execute("SELECT COUNT(*) FROM managed_bulk_wait_results WHERE import_id=? AND attention=1 AND state NOT IN ('STOPPED_FAILED','STOPPED_UNVERIFIED')", (key,)).fetchone()[0],
                    'targets': targets}
            return {'operation_id': key, 'requested': True, 'read_only': True, 'can_execute': False,
                'historical_cancellation': True, 'settled': True, 'page': page, 'pages': pages, 'result': result,
                'targets': [{**dict(row), 'ip': str(IPv4Address(row['ip']))} for row in rows]}
