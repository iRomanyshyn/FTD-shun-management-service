"""Source-only settled-ACK evidence ledger, never queue/lease/retry authority.

Explicit initialization and internal composition only. Existing jobs/attempts stay
RUNNING and fenced: the worker/state transition contract is a separate increment.
"""

import hashlib
import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID

from .agent_protocol import PendingAddition, SettledPendingAdditions, decode_pending_end
from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _atomic, _quiescent, _state
from .device_leases import DeviceLeases, _token
from .import_preparations import _stamp
from .managed_restoration import CompleteSnapshot, validate_binding
from .operation_queue import QueueConflict
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection
from .snapshot_protocol import MAX_SNAPSHOT_ENTRIES

TABLE = 'managed_bulk_pending_sessions'
MAX_MEMBERS = 1000000
DDL = """
CREATE TABLE managed_bulk_pending_sessions (
 id TEXT PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id),
 owner TEXT NOT NULL UNIQUE, epoch INTEGER NOT NULL CHECK(epoch>=1),
 end_sequence INTEGER NOT NULL CHECK(end_sequence BETWEEN 2 AND 130),
 member_count INTEGER NOT NULL CHECK(member_count BETWEEN 1 AND 16),
 settled_at TEXT NOT NULL
);
CREATE TABLE managed_bulk_pending_members (
 session_id TEXT NOT NULL REFERENCES managed_bulk_pending_sessions(id) DEFERRABLE INITIALLY DEFERRED,
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 15),
 attempt_id TEXT NOT NULL UNIQUE REFERENCES managed_bulk_attempts(id),
 job_id TEXT NOT NULL UNIQUE REFERENCES operation_jobs(id),
 ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
 sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 129),
 claim_event_id TEXT NOT NULL UNIQUE REFERENCES shun_events(id),
 ack_event_id TEXT NOT NULL UNIQUE REFERENCES shun_events(id),
 PRIMARY KEY(session_id,ordinal), UNIQUE(session_id,ip), UNIQUE(session_id,sequence)
);
CREATE TABLE managed_bulk_pending_reads (
 session_id TEXT PRIMARY KEY REFERENCES managed_bulk_pending_sessions(id),
 snapshot_id TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL, snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
 present_ordinals_json TEXT NOT NULL CHECK(json_valid(present_ordinals_json))
);
CREATE INDEX idx_managed_bulk_pending_snapshot ON managed_bulk_pending_reads(snapshot_id);
CREATE TRIGGER managed_bulk_pending_complete BEFORE INSERT ON managed_bulk_pending_sessions
WHEN NEW.member_count!=(SELECT COUNT(*) FROM managed_bulk_pending_members WHERE session_id=NEW.id)
 OR NEW.member_count!=(SELECT MAX(ordinal)+1 FROM managed_bulk_pending_members WHERE session_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'complete ordered pending scope is required'); END;
CREATE TRIGGER managed_bulk_pending_sealed BEFORE INSERT ON managed_bulk_pending_members
WHEN EXISTS(SELECT 1 FROM managed_bulk_pending_sessions WHERE id=NEW.session_id)
BEGIN SELECT RAISE(ABORT,'pending scope is sealed'); END;
CREATE TRIGGER managed_bulk_pending_session_immutable BEFORE UPDATE ON managed_bulk_pending_sessions
BEGIN SELECT RAISE(ABORT,'pending session evidence is immutable'); END;
CREATE TRIGGER managed_bulk_pending_session_retained BEFORE DELETE ON managed_bulk_pending_sessions
BEGIN SELECT RAISE(ABORT,'pending session evidence is retained'); END;
CREATE TRIGGER managed_bulk_pending_member_immutable BEFORE UPDATE ON managed_bulk_pending_members
BEGIN SELECT RAISE(ABORT,'pending member evidence is immutable'); END;
CREATE TRIGGER managed_bulk_pending_member_retained BEFORE DELETE ON managed_bulk_pending_members
BEGIN SELECT RAISE(ABORT,'pending member evidence is retained'); END;
CREATE TRIGGER managed_bulk_pending_read_immutable BEFORE UPDATE ON managed_bulk_pending_reads
BEGIN SELECT RAISE(ABORT,'pending observation evidence is immutable'); END;
CREATE TRIGGER managed_bulk_pending_read_retained BEFORE DELETE ON managed_bulk_pending_reads
BEGIN SELECT RAISE(ABORT,'pending observation evidence is retained'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is not None


def validate(db):
    """Retained scope integrity only; no current eligibility or outcome inference."""
    if (db.execute('SELECT COUNT(*) FROM managed_bulk_pending_members').fetchone()[0] > MAX_MEMBERS
            or db.execute('''SELECT 1 FROM managed_bulk_pending_sessions s WHERE s.member_count!=(
                SELECT COUNT(*) FROM managed_bulk_pending_members m WHERE m.session_id=s.id)
                OR s.member_count!=(SELECT MAX(ordinal)+1 FROM managed_bulk_pending_members m WHERE m.session_id=s.id)
                LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_pending_members m
                LEFT JOIN managed_bulk_pending_sessions s ON s.id=m.session_id
                LEFT JOIN managed_bulk_attempts a ON a.id=m.attempt_id
                LEFT JOIN operation_jobs j ON j.id=m.job_id
                LEFT JOIN shun_events c ON c.id=m.claim_event_id LEFT JOIN shun_events k ON k.id=m.ack_event_id
                WHERE s.id IS NULL OR a.id IS NULL OR j.id IS NULL OR c.id IS NULL OR k.id IS NULL
                OR a.job_id!=m.job_id OR a.device_id!=s.device_id OR a.ip!=m.ip
                OR j.device_id!=s.device_id OR j.ip!=m.ip OR j.action!='ADD'
                OR c.event_type!='SHUN_OPERATION_RUNNING' OR k.event_type!='SHUN_ADDITION_ACKNOWLEDGED'
                OR c.device_id!=s.device_id OR k.device_id!=s.device_id OR c.ip!=m.ip OR k.ip!=m.ip
                OR c.request_id IS NOT a.id OR k.request_id IS NOT a.id
                OR json_extract(c.details_json,'$.operation_id') IS NOT m.job_id
                OR json_extract(k.details_json,'$.operation_id') IS NOT m.job_id
                OR json_extract(c.details_json,'$.addition_group') IS NOT s.id
                OR json_extract(c.details_json,'$.batch_session_version') IS NOT 7
                OR json_extract(c.details_json,'$.device_executor.owner') IS NOT s.owner
                OR json_extract(c.details_json,'$.device_executor.epoch') IS NOT s.epoch
                OR json_extract(k.details_json,'$.batch_session.group') IS NOT s.id
                OR json_extract(k.details_json,'$.batch_session.owner') IS NOT s.owner
                OR json_extract(k.details_json,'$.batch_session.epoch') IS NOT s.epoch
                OR json_extract(k.details_json,'$.batch_session.version') IS NOT 7
                OR json_extract(k.details_json,'$.sequence') IS NOT m.sequence
                OR json_type(k.details_json,'$.verified') IS NOT 'false'
                OR m.sequence>=s.end_sequence OR a.requested_at>c.timestamp
                OR c.timestamp>k.timestamp OR k.timestamp>s.settled_at
                OR EXISTS(SELECT 1 FROM managed_bulk_pending_members earlier WHERE earlier.session_id=m.session_id
                    AND earlier.ordinal<m.ordinal AND earlier.sequence>=m.sequence)
                LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_bulk_pending_reads r
                LEFT JOIN managed_bulk_pending_sessions s ON s.id=r.session_id
                WHERE s.id IS NULL OR r.started_at<=s.settled_at OR r.completed_at<r.started_at
                    OR r.recorded_at<r.completed_at LIMIT 1''').fetchone()):
        raise BulkUnavailable('Settled pending evidence is missing, inconsistent or exceeds capacity.')
    try:
        for row in db.execute('''SELECT r.*,s.member_count FROM managed_bulk_pending_reads r
                JOIN managed_bulk_pending_sessions s ON s.id=r.session_id'''):
            ordinals = json.loads(row['present_ordinals_json'])
            _uuid(row['snapshot_id'])
            if (type(ordinals) is not list or any(type(n) is not int or not 0 <= n < row['member_count'] for n in ordinals)
                    or ordinals != sorted(set(ordinals))
                    or any(c not in '0123456789abcdef' for c in row['snapshot_digest'])
                    or any(_stamp(datetime.fromisoformat(row[field])) != row[field]
                           for field in ('started_at', 'completed_at', 'recorded_at'))):
                raise ValueError('Invalid pending observation')
        for row in db.execute('SELECT * FROM managed_bulk_pending_sessions'):
            _uuid(row['id'])
            _uuid(row['owner'])
            if _stamp(datetime.fromisoformat(row['settled_at'])) != row['settled_at']:
                raise ValueError('Invalid settlement time')
    except (ValueError, TypeError) as error:
        raise BulkUnavailable('Retained pending observation or identity is invalid.') from error


def _enabled(value):
    if type(value) is not bool:
        raise ValueError('Pending evidence capability must be a literal boolean.')
    if not value:
        raise PermissionError('Pending evidence composition is disabled.')


class PendingConfirmations:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError('Pending evidence must use its original queue database.')
        self.store, self.queue = store, queue

    def initialize(self, *, connection=None):
        """Explicit quiescent schema composition; never startup, GET or recovery."""
        with schema_connection(self.store, connection) as db, _atomic(db):
            self._profile(db, required=False)
            if present(db):
                return
            _quiescent(db)
            if not mutations_suspended(db):
                raise QueueConflict('Pause ordinary mutations before pending evidence initialization.')
            execute_schema(db, DDL)
            self._profile(db)

    @staticmethod
    def _profile(db, *, required=True):
        if (_state(db) is None or not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='managed_bulk_device_executors'").fetchone()
                or (required and not present(db))):
            raise BulkUnavailable('Exact device-scoped pending evidence profile is required.')

    @staticmethod
    def _members(db, session_id):
        return db.execute('SELECT * FROM managed_bulk_pending_members WHERE session_id=? ORDER BY ordinal',
                          (session_id,)).fetchall()

    def record(self, token, receipt, job_ids, *, enabled=False, connection=None):
        """Retain original settled transport evidence; NO job/attempt/lease change.

        Caller supplies the actual low-level client's terminal value, not a raw
        ACK or generic agent log. Ordinary handoff requires the live lease.
        """
        return self._record(token, receipt, job_ids, DeviceLeases(self.store, self.queue).check,
                            enabled=enabled, connection=connection)

    def _record(self, token, receipt, job_ids, check_fence, *, enabled=False, connection=None):
        # Also used inside the exact expired-END recovery transaction. Its
        # checker proves an unchanged checkpoint/fence and actual journal receipt;
        # it does not renew a lease or authorize another device command.
        _enabled(enabled)
        _token(token)
        if (type(receipt) is not SettledPendingAdditions or type(receipt.device_id) is not int
                or receipt.device_id != token.device_id or type(receipt.session_id) is not bytes
                or receipt.session_id != UUID(token.owner).bytes or type(job_ids) is not tuple
                or not 1 <= len(job_ids) <= 16 or len(set(job_ids)) != len(job_ids)):
            raise ValueError('Exact original pending receipt, lease and ordered jobs are required.')
        for job_id in job_ids:
            _uuid(job_id)
        if (type(receipt.sequence) is not int or not 2 <= receipt.sequence <= 130
                or type(receipt.acknowledgements) is not tuple or not 1 <= len(receipt.acknowledgements) <= 16
                or any(type(ack) is not PendingAddition or type(ack.ip) is not IPv4Address
                       for ack in receipt.acknowledgements)):
            raise ValueError('A bounded ordered original acknowledgement tuple is required.')
        # Reuse the strict transport scope validator, including literal types,
        # increasing sequences, uniqueness and terminal ordering. Not proof of I/O.
        packet = bytes([6, 7, 0x1d, receipt.sequence, len(receipt.acknowledgements)]) + b''.join(
            ack.ip.packed for ack in receipt.acknowledgements)
        decode_pending_end(packet, receipt.sequence, receipt.acknowledgements, version=7)
        if len(job_ids) != len(receipt.acknowledgements):
            raise ValueError('Every pending acknowledgement needs its original job.')
        with schema_connection(self.store, connection) as db, _atomic(db):
            self._profile(db)
            check_fence(db, token)
            if db.execute('SELECT 1 FROM managed_bulk_pending_sessions WHERE owner=?', (token.owner,)).fetchone():
                raise QueueConflict('This terminal session is already retained; no replacement evidence.')
            running = db.execute("SELECT id FROM operation_jobs WHERE device_id=? AND state='RUNNING'",
                                 (token.device_id,)).fetchall()
            if {row['id'] for row in running} != set(job_ids):
                raise QueueConflict('Pending scope differs from the complete original RUNNING device scope.')
            settled_at = _stamp(self.queue._now())  # Conservative causal barrier AFTER actual receipt.
            members, roots, group = [], set(), None
            for ordinal, (job_id, ack) in enumerate(zip(job_ids, receipt.acknowledgements, strict=True)):
                job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
                attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()
                if (job is None or attempt is None or job['state'] != 'RUNNING' or job['dispatch_kind'] != 'ADD'
                        or job['ip'] != ack.ip.packed):
                    raise QueueConflict('Pending member is not its original running managed ADD.')
                validate_binding(db, attempt, job)
                if attempt['authorization_request_id'] not in roots:
                    root = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?',
                                      (attempt['authorization_request_id'],)).fetchone()
                    BulkPolicies(self.store)._root(db, attempt['authorization_request_id'], root['actor_subject'])
                    roots.add(attempt['authorization_request_id'])
                claims = db.execute('''SELECT * FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_RUNNING'
                    AND json_extract(details_json,'$.operation_id')=?
                    AND json_extract(details_json,'$.device_executor.owner')=?
                    AND json_extract(details_json,'$.device_executor.epoch')=?''',
                                    (attempt['id'], job_id, token.owner, token.epoch)).fetchall()
                acks = db.execute('''SELECT * FROM shun_events WHERE request_id=?
                    AND event_type='SHUN_ADDITION_ACKNOWLEDGED' AND json_extract(details_json,'$.operation_id')=?''',
                                  (attempt['id'], job_id)).fetchall()
                if len(claims) != 1 or len(acks) != 1:
                    raise QueueConflict('Pending member requires its single original claim and ACK audit.')
                claim, acknowledgement = claims[0], acks[0]
                c, k = json.loads(claim['details_json']), json.loads(acknowledgement['details_json'])
                if (type(c) is not dict or type(k) is not dict or type(c.get('device_executor')) is not dict
                        or type(k.get('batch_session')) is not dict):
                    raise QueueConflict('Pending claim and ACK require exact structured bindings.')
                candidate_group = c.get('addition_group')
                _uuid(candidate_group)
                if group is None:
                    group = candidate_group
                if (candidate_group != group or type(c.get('batch_session_version')) is not int
                        or c['batch_session_version'] != 7
                        or type(c.get('device_executor', {}).get('epoch')) is not int
                        or type(k.get('batch_session', {}).get('epoch')) is not int
                        or k.get('batch_session') != {'group': group, 'owner': token.owner, 'epoch': token.epoch, 'version': 7}
                        or type(k.get('sequence')) is not int or k['sequence'] != ack.sequence or k.get('verified') is not False
                        or claim['device_id'] != token.device_id or acknowledgement['device_id'] != token.device_id
                        or claim['ip'] != ack.ip.packed or acknowledgement['ip'] != ack.ip.packed
                        or not attempt['requested_at'] <= claim['timestamp'] <= acknowledgement['timestamp'] <= settled_at):
                    raise QueueConflict('Original claim/ACK audit differs from this exact v7 terminal scope.')
                members.append((group, ordinal, attempt['id'], job_id, ack.ip.packed, ack.sequence,
                                claim['id'], acknowledgement['id']))
            if db.execute('SELECT COUNT(*) FROM managed_bulk_pending_members').fetchone()[0] + len(members) > MAX_MEMBERS:
                raise BulkUnavailable('Retained pending evidence capacity is exhausted.')
            db.executemany('INSERT INTO managed_bulk_pending_members VALUES (?,?,?,?,?,?,?,?)', members)
            db.execute('INSERT INTO managed_bulk_pending_sessions VALUES (?,?,?,?,?,?,?)',
                       (group, token.device_id, token.owner, token.epoch, receipt.sequence, len(members), settled_at))
            check_fence(db, token)
            self._profile(db)
        return group

    def classify(self, session_id, snapshot, *, enabled=False, connection=None):
        """First causal complete observation only; neither success nor retry permit."""
        _enabled(enabled)
        _uuid(session_id)
        now = self.queue._now()
        if (type(snapshot) is not CompleteSnapshot or snapshot.complete is not True
                or type(snapshot.device_id) is not int or not 1 <= snapshot.device_id <= 65535
                or type(snapshot.present_ips) is not frozenset or len(snapshot.present_ips) > MAX_SNAPSHOT_ENTRIES
                or any(type(ip) is not IPv4Address for ip in snapshot.present_ips)):
            raise ValueError('A typed complete bounded same-device snapshot is required.')
        _uuid(snapshot.id)
        started, completed, recorded = _stamp(snapshot.started_at), _stamp(snapshot.completed_at), _stamp(now)
        if not now - timedelta(seconds=120) <= snapshot.started_at <= snapshot.completed_at <= now:
            raise ValueError('Pending classification requires a fresh, completed UTC read.')
        digest = hashlib.sha256(b''.join(ip.packed for ip in sorted(snapshot.present_ips))).hexdigest()
        with schema_connection(self.store, connection) as db, _atomic(db):
            self._profile(db)
            session = db.execute('SELECT * FROM managed_bulk_pending_sessions WHERE id=?', (session_id,)).fetchone()
            if session is None or session['device_id'] != snapshot.device_id or started <= session['settled_at']:
                raise QueueConflict('Read must start strictly after this exact same-device settlement.')
            shared = db.execute('''SELECT s.device_id,r.started_at,r.completed_at,r.snapshot_digest FROM managed_bulk_pending_reads r
                JOIN managed_bulk_pending_sessions s ON s.id=r.session_id
                WHERE r.snapshot_id=?''', (snapshot.id,)).fetchall()
            if any(tuple(row) != (snapshot.device_id, started, completed, digest) for row in shared):
                raise QueueConflict('A shared snapshot identity cannot describe different complete evidence.')
            members = self._members(db, session_id)
            present_ordinals = [row['ordinal'] for row in members if IPv4Address(row['ip']) in snapshot.present_ips]
            values = (session_id, snapshot.id, started, completed, recorded, digest, json.dumps(present_ordinals))
            old = db.execute('SELECT * FROM managed_bulk_pending_reads WHERE session_id=?', (session_id,)).fetchone()
            if old is not None:
                if tuple(old)[:4] + tuple(old)[5:] != values[:4] + values[5:]:
                    raise QueueConflict('First pending observation is immutable; a later read cannot replace it.')
            else:
                db.execute('INSERT INTO managed_bulk_pending_reads VALUES (?,?,?,?,?,?,?)', values)
            self._profile(db)
            return tuple((row['job_id'], 'OBSERVED_PRESENT' if row['ordinal'] in present_ordinals else 'CONFIRMED_ABSENT')
                         for row in members)

    def inspect(self, session_id):
        """Bounded restart-readable evidence; no DDL, queue mutation or fallback."""
        _uuid(session_id)
        with self.store._connection() as db:
            db.execute('BEGIN')
            self._profile(db)
            session = db.execute('SELECT * FROM managed_bulk_pending_sessions WHERE id=?', (session_id,)).fetchone()
            if session is None:
                raise QueueConflict('Pending session evidence is unavailable.')
            read = db.execute('SELECT * FROM managed_bulk_pending_reads WHERE session_id=?', (session_id,)).fetchone()
            present_ordinals = json.loads(read['present_ordinals_json']) if read else []
            return {'session': dict(session), 'read': dict(read) if read else None,
                    'members': [{**dict(row), 'observation': ('AWAITING_CONFIRMATION' if read is None else
                        'OBSERVED_PRESENT' if row['ordinal'] in present_ordinals else 'CONFIRMED_ABSENT')}
                        for row in self._members(db, session_id)],
                    'can_release': False, 'can_retry': False, 'proves_creation': False}
