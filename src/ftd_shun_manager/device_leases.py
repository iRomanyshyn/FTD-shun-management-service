"""Explicit fenced bulk-device leases; shared queue, no scheduler or auto recovery."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable, _atomic, _quiescent, _state
from .import_preparations import _stamp
from .operation_queue import OperationQueue, QueueConflict
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

DDL = """
CREATE TABLE managed_bulk_device_profile (
    id INTEGER PRIMARY KEY CHECK(id=1),format_version INTEGER NOT NULL CHECK(format_version=1),
    concurrency INTEGER NOT NULL CHECK(concurrency BETWEEN 1 AND 10),
    device_ids_json TEXT NOT NULL CHECK(json_valid(device_ids_json))
);
CREATE TABLE managed_bulk_device_executors (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id),epoch INTEGER NOT NULL CHECK(epoch>=0),
    owner TEXT,lease_until TEXT,state TEXT NOT NULL CHECK(state IN ('IDLE','LEASED','ATTENTION')),
    updated_at TEXT NOT NULL,
    CHECK((state='IDLE' AND owner IS NULL AND lease_until IS NULL)
       OR (state!='IDLE' AND epoch>=1 AND owner IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE TRIGGER managed_bulk_device_profile_complete BEFORE INSERT ON managed_bulk_device_profile
WHEN json_type(NEW.device_ids_json)!='array' OR json_array_length(NEW.device_ids_json) NOT BETWEEN 1 AND 10
    OR json_array_length(NEW.device_ids_json)!=(SELECT COUNT(*) FROM managed_bulk_device_executors)
    OR json_array_length(NEW.device_ids_json)!=(SELECT COUNT(DISTINCT value) FROM json_each(NEW.device_ids_json))
    OR EXISTS(SELECT 1 FROM json_each(NEW.device_ids_json) j WHERE j.type!='integer'
        OR NOT EXISTS(SELECT 1 FROM managed_bulk_device_executors d WHERE d.device_id=j.value))
BEGIN SELECT RAISE(ABORT,'complete fixed device lease scope is required'); END;
CREATE TRIGGER managed_bulk_device_profile_immutable BEFORE UPDATE ON managed_bulk_device_profile
BEGIN SELECT RAISE(ABORT,'device lease profile is immutable'); END;
CREATE TRIGGER managed_bulk_device_profile_retained BEFORE DELETE ON managed_bulk_device_profile
BEGIN SELECT RAISE(ABORT,'device lease profile is retained'); END;
CREATE TRIGGER managed_bulk_device_sealed BEFORE INSERT ON managed_bulk_device_executors
WHEN EXISTS(SELECT 1 FROM managed_bulk_device_profile)
BEGIN SELECT RAISE(ABORT,'device lease scope is sealed'); END;
CREATE TRIGGER managed_bulk_device_retained BEFORE DELETE ON managed_bulk_device_executors
BEGIN SELECT RAISE(ABORT,'device lease evidence is retained'); END;
CREATE TRIGGER managed_bulk_device_identity BEFORE UPDATE OF device_id ON managed_bulk_device_executors
BEGIN SELECT RAISE(ABORT,'device lease identity is immutable'); END;
CREATE TRIGGER managed_bulk_device_attention BEFORE UPDATE ON managed_bulk_device_executors
WHEN OLD.state='ATTENTION'
BEGIN SELECT RAISE(ABORT,'device lease attention cannot be released'); END;
CREATE TRIGGER managed_bulk_device_epoch BEFORE UPDATE ON managed_bulk_device_executors
WHEN NOT ((OLD.state='IDLE' AND NEW.state='LEASED' AND NEW.epoch=OLD.epoch+1)
    OR (OLD.state='LEASED' AND NEW.epoch=OLD.epoch AND
        ((NEW.state IN ('LEASED','ATTENTION') AND NEW.owner=OLD.owner) OR NEW.state='IDLE')))
BEGIN SELECT RAISE(ABORT,'invalid device lease transition'); END;
CREATE TRIGGER managed_bulk_device_no_global BEFORE UPDATE OF owner,lease_until ON operation_executor
WHEN NEW.owner IS NOT NULL OR NEW.lease_until IS NOT NULL
BEGIN SELECT RAISE(ABORT,'global executor is disabled on device lease storage'); END;
CREATE TRIGGER managed_bulk_device_no_resume BEFORE UPDATE OF restoration_suspended ON managed_bulk_registry
WHEN NEW.restoration_suspended=0 AND EXISTS(SELECT 1 FROM managed_bulk_device_executors WHERE state!='IDLE')
BEGIN SELECT RAISE(ABORT,'settle all device leases before desired-policy resume'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_device*' LIMIT 1").fetchone() is not None


def validate(db):
    profile = db.execute('SELECT * FROM managed_bulk_device_profile').fetchall()
    rows = db.execute('SELECT * FROM managed_bulk_device_executors ORDER BY device_id').fetchall()
    try:
        if len(profile) != 1 or not 1 <= len(rows) <= 10:
            raise ValueError('Missing device lease scope')
        devices = json.loads(profile[0]['device_ids_json'])
        if (type(profile[0]['concurrency']) is not int or not 1 <= profile[0]['concurrency'] <= 10
                or type(devices) is not list or any(type(device) is not int or not 1 <= device <= 65535 for device in devices)
                or devices != sorted(set(devices)) or devices != [row['device_id'] for row in rows]):
            raise ValueError('Invalid device lease scope')
        executor = db.execute('SELECT owner,lease_until FROM operation_executor WHERE id=1').fetchone()
        if executor is None or executor['owner'] is not None or executor['lease_until'] is not None:
            raise ValueError('Concurrent legacy executor')
        for row in rows:
            if type(row['epoch']) is not int or row['epoch'] < 0:
                raise ValueError('Invalid device epoch')
            if _stamp(datetime.fromisoformat(row['updated_at'])) != row['updated_at']:
                raise ValueError('Invalid device lease time')
            if row['owner'] is not None:
                _uuid(row['owner'])
                if _stamp(datetime.fromisoformat(row['lease_until'])) != row['lease_until']:
                    raise ValueError('Invalid device deadline')
    except (ValueError, TypeError) as error:
        raise BulkUnavailable('Device lease profile/evidence is incomplete or malformed.') from error


@dataclass(frozen=True)
class DeviceLease:
    device_id: int
    owner: str
    epoch: int


def _token(token):
    if (type(token) is not DeviceLease or type(token.device_id) is not int or not 1 <= token.device_id <= 65535
            or type(token.epoch) is not int or token.epoch < 1):
        raise ValueError('Exact literal device lease token is required.')
    _uuid(token.owner)


class DeviceLeases:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError('Device leases must use the shared queue database.')
        self.store, self.queue = store, queue

    def initialize(self, device_ids, *, concurrency=4, connection=None):
        if (type(device_ids) is not frozenset or not 1 <= len(device_ids) <= 10
                or any(type(device) is not int or not 1 <= device <= 65535 for device in device_ids)
                or type(concurrency) is not int or not 1 <= concurrency <= 10):
            raise ValueError('Select 1..10 literal devices and a 1..10 concurrency limit.')
        devices = sorted(device_ids)
        with schema_connection(self.store, connection) as db, _atomic(db):
            state = _state(db)
            if state is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_dispatch_registry'").fetchone():
                raise BulkUnavailable('Existing exact bulk dispatch storage is required.')
            if present(db):
                row = db.execute('SELECT * FROM managed_bulk_device_profile').fetchone()
                if json.loads(row['device_ids_json']) != devices or row['concurrency'] != concurrency:
                    raise QueueConflict('Existing immutable device lease scope/limit differs.')
                return
            _quiescent(db)
            if not mutations_suspended(db) or not state['restoration_suspended']:
                raise QueueConflict('Pause ordinary mutations and suspend desired policy before initializing device leases.')
            if any(not db.execute('SELECT 1 FROM devices WHERE id=? AND enabled=1', (device,)).fetchone() for device in devices):
                raise QueueConflict('Every selected device must already exist and be enabled.')
            for root in db.execute('SELECT id,actor_subject FROM managed_shun_requests WHERE id IN (SELECT id FROM managed_bulk_manifests)'):
                BulkPolicies(self.store)._root(db, root['id'], root['actor_subject'])
            execute_schema(db, DDL)
            timestamp = _stamp(self.queue._now())
            db.executemany("INSERT INTO managed_bulk_device_executors VALUES (?,0,NULL,NULL,'IDLE',?)",
                           [(device, timestamp) for device in devices])
            db.execute('INSERT INTO managed_bulk_device_profile VALUES (1,1,?,?)', (concurrency, json.dumps(devices)))
            _state(db)

    def claim(self, device_id, owner, seconds, *, enabled=False):
        if type(enabled) is not bool:
            raise ValueError('Device lease capability must be boolean.')
        if not enabled:
            return None
        if type(device_id) is not int or not 1 <= device_id <= 65535:
            raise ValueError('A literal device ID is required.')
        _uuid(owner)
        self._duration(seconds)
        with schema_connection(self.store) as db, _atomic(db):
            self._profile(db)
            row = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()
            if row is None:
                raise QueueConflict('Device is outside the sealed executor scope.')
            timestamp = _stamp(self.queue._now())
            if row['updated_at'] > timestamp:
                raise QueueConflict('Device lease time moved backwards.')
            if row['state'] == 'LEASED' and row['lease_until'] <= timestamp:
                # Never grant a successor while the original RPC may still execute.
                for job in db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND state='RUNNING'", (device_id,)).fetchall():
                    self.queue._finish(db, job, 'UNVERIFIED', 'device lease expired; original RPC outcome remains unknown')
                db.execute("UPDATE managed_bulk_device_executors SET state='ATTENTION',updated_at=? WHERE device_id=?",
                           (timestamp, device_id))
                self._event(db, 'ATTENTION', DeviceLease(device_id, row['owner'], row['epoch']), timestamp)
                self.queue._bump(db)
                return None
            if row['state'] != 'IDLE':
                return None
            if (not db.execute('SELECT 1 FROM devices WHERE id=? AND enabled=1', (device_id,)).fetchone()
                    or db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('RUNNING','UNVERIFIED','RECONCILED_ABSENT')", (device_id,)).fetchone()
                    or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED'", (device_id,)).fetchone()):
                return None
            limit = db.execute('SELECT concurrency FROM managed_bulk_device_profile').fetchone()[0]
            if db.execute("SELECT COUNT(*) FROM managed_bulk_device_executors WHERE state='LEASED'").fetchone()[0] >= limit:
                return None
            token = DeviceLease(device_id, owner, row['epoch'] + 1)
            db.execute("UPDATE managed_bulk_device_executors SET state='LEASED',epoch=?,owner=?,lease_until=?,updated_at=? WHERE device_id=?",
                       (token.epoch, owner, _stamp(self.queue._now() + timedelta(seconds=seconds)), timestamp, device_id))
            self._event(db, 'CLAIMED', token, timestamp)
            self.queue._bump(db)
            self.check(db, token)
            return token

    @staticmethod
    def _duration(seconds):
        if type(seconds) is not int or not 5 <= seconds <= 300:
            raise ValueError('Device lease duration must be a literal 5..300 seconds.')

    @staticmethod
    def _profile(db):
        if _state(db) is None or not present(db):
            raise BulkUnavailable('Exact device lease storage is not initialized.')

    def check(self, db, token):
        _token(token)
        self._profile(db)
        row = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (token.device_id,)).fetchone()
        if (row is None or row['state'] != 'LEASED' or row['owner'] != token.owner or row['epoch'] != token.epoch
                or row['updated_at'] > _stamp(self.queue._now()) or row['lease_until'] <= _stamp(self.queue._now())):
            raise QueueConflict('Device lease fence, owner or deadline was lost.')
        return row

    def renew(self, token, seconds):
        self._duration(seconds)
        with schema_connection(self.store) as db, _atomic(db):
            previous = self.check(db, token)
            db.execute('UPDATE managed_bulk_device_executors SET lease_until=?,updated_at=? WHERE device_id=?',
                       (_stamp(self.queue._now() + timedelta(seconds=seconds)), _stamp(self.queue._now()), token.device_id))
            self.check(db, token)
            if previous['lease_until'] <= _stamp(self.queue._now()):
                raise QueueConflict('Original device lease expired during renewal.')

    def release(self, token):
        self._release(token, opening_event=None)

    def release_unsubmitted(self, token):
        """Only a first-open local pre-send failure may use this audited release."""
        self._release(token, opening_event='NOT_SUBMITTED')

    def release_unopened(self, token):
        """Exact terminal agent proof of opening failure, not an unknown command."""
        self._release(token, opening_event='OPEN_FAILED')

    def _release(self, token, *, opening_event):
        with schema_connection(self.store) as db, _atomic(db):
            previous = self.check(db, token)
            if db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state='RUNNING'", (token.device_id,)).fetchone():
                raise QueueConflict('Settle RUNNING work before releasing a device lease.')
            if opening_event is not None and (
                    db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT')",
                               (token.device_id,)).fetchone()
                    or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED'",
                                  (token.device_id,)).fetchone()
                    or db.execute("SELECT 1 FROM shun_events WHERE device_id=? AND event_type='SHUN_OPERATION_RUNNING' "
                                  "AND json_extract(details_json,'$.device_executor.owner')=? "
                                  "AND json_extract(details_json,'$.device_executor.epoch')=?",
                                  (token.device_id, token.owner, token.epoch)).fetchone()):
                raise QueueConflict('Opening-failure release cannot cover claimed work or device uncertainty.')
            timestamp = _stamp(self.queue._now())
            db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL,updated_at=? WHERE device_id=?",
                       (timestamp, token.device_id))
            if opening_event is not None:
                self._event(db, opening_event, token, timestamp)
            self._event(db, 'RELEASED', token, timestamp)
            self.queue._bump(db)
            if previous['lease_until'] <= _stamp(self.queue._now()) or _stamp(self.queue._now()) < timestamp:
                raise QueueConflict('Device lease expired during release.')

    def _event(self, db, event, token, timestamp):
        self.store._insert_event(db, 'DEVICE_LEASE_' + event, token.device_id, None, None,
                                 'system:device-executor', 'Device executor', (), None,
                                 {'owner': token.owner, 'epoch': token.epoch}, timestamp)

    def status(self):
        with self.store._connection() as db:
            db.execute('BEGIN')
            self._profile(db)
            profile = db.execute('SELECT * FROM managed_bulk_device_profile').fetchone()
            timestamp = _stamp(self.queue._now())
            return {'concurrency': profile['concurrency'], 'read_only': True,
                    'devices': [{**dict(row), 'expired': row['state'] == 'LEASED' and row['lease_until'] <= timestamp,
                                 'needs_attention': row['state'] == 'ATTENTION' or (row['state'] == 'LEASED' and row['lease_until'] <= timestamp)}
                                for row in db.execute('SELECT * FROM managed_bulk_device_executors ORDER BY device_id')]}


class DeviceOperationQueue(OperationQueue):
    """A fixed lease scope over the existing executor; never a second job queue."""

    def __init__(self, store, token, *, priority_removals=False):
        _token(token)
        if type(priority_removals) is not bool:
            raise ValueError('Scoped removal priority must be boolean.')
        super().__init__(store)
        self.token = token
        self.priority_removals = priority_removals
        self.leases = DeviceLeases(store, self)

    def _executor(self, db, owner, device_id):
        if owner != self.token.owner or device_id != self.token.device_id:
            raise QueueConflict('Operation is outside this fixed device lease.')
        return self.leases.check(db, self.token)

    def _removal_priority(self):
        return self.priority_removals

    def _event(self, db, event, request, job, details=None):
        # Revocation may sweep other devices too; never attribute those jobs to this token.
        if job['device_id'] == self.token.device_id and (event == 'SHUN_OPERATION_RUNNING' or dict(job).get('state') == 'RUNNING'):
            row = db.execute('SELECT owner,epoch FROM managed_bulk_device_executors WHERE device_id=?', (self.token.device_id,)).fetchone()
            if row is not None and row['owner'] == self.token.owner and row['epoch'] == self.token.epoch:
                details = {**(details or {}), 'device_executor': {'owner': self.token.owner, 'epoch': self.token.epoch}}
        super()._event(db, event, request, job, details)

    def claim_cycle(self, owner, lease_seconds):
        raise QueueConflict('Acquire an explicit device token; global cycle admission is unavailable.')

    def renew(self, owner, lease_seconds):
        if owner != self.token.owner:
            raise QueueConflict('Device lease owner differs.')
        self.leases.renew(self.token, lease_seconds)

    def finish_cycle(self, owner, interval_seconds):
        if owner != self.token.owner:
            raise QueueConflict('Device lease owner differs.')
        self.leases.release(self.token)
