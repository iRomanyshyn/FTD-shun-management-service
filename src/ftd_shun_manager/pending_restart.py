"""Exact completed-END crash recovery; never a lease renewal or ADD retry.

The append-only pre-END checkpoint is intent, not settlement proof. Only the
agent's matching completed-session journal can finish its original handoff.
Historical unknowns and ATTENTION fences are outside this contract.
"""

import hashlib
import json
from dataclasses import dataclass
from ipaddress import IPv4Address
from uuid import UUID

from .agent_protocol import PendingAddition, SettledPendingAdditions, decode_pending_end
from .bulk_intent import _uuid
from .bulk_policy import _atomic
from .device_leases import DeviceLease, DeviceLeases, device_uncertain
from .import_preparations import _stamp
from .managed_restoration import validate_binding
from .operation_queue import OperationQueue, QueueConflict
from .pending_execution import PendingExecution
from .result_storage import persist_result
from .schema import schema_connection

EVENT = 'SHUN_PENDING_END_PREPARED'

# Only original claims behind an unreleased checkpoint. Retention must not
# remove a settled prefix while its final group still needs crash recovery.
RETAINED_CLAIMS = '''SELECT c.request_id,json_extract(c.details_json,'$.operation_id') AS job_id,
    d.device_id,d.owner,d.epoch FROM managed_bulk_device_executors d JOIN shun_events c
    ON c.device_id=d.device_id AND c.event_type='SHUN_OPERATION_RUNNING'
    AND json_extract(c.details_json,'$.device_executor.owner')=d.owner
    AND json_extract(c.details_json,'$.device_executor.epoch')=d.epoch
    WHERE d.state='LEASED' AND EXISTS(SELECT 1 FROM shun_events p
        WHERE p.device_id=d.device_id AND p.event_type='SHUN_PENDING_END_PREPARED'
        AND json_extract(p.details_json,'$.owner')=d.owner
        AND json_extract(p.details_json,'$.epoch')=d.epoch)'''


def _row(row):
    return {key: value.hex() if type(value) is bytes else value for key, value in dict(row).items()}


def _same_scope(value, expected):
    # JSON booleans/floats must not compare equal to integer protocol fields.
    return json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True)


def _scope(db, token, jobs, sequence, timestamp):
    """Validate all original visit claims, including a settled prefix, then hash.

    Prefixes containing failed/cancelled/deferred claims deliberately refuse this
    narrow recovery. The existing explicit recovery contracts remain separate.
    """
    if (type(jobs) is not tuple or not 1 <= len(jobs) <= 16 or len(set(jobs)) != len(jobs)
            or type(sequence) is not int or not 2 <= sequence <= 130):
        raise QueueConflict('Pending END checkpoint requires a bounded exact ordered scope.')
    for job in jobs:
        _uuid(job)
    if device_uncertain(db, token.device_id):
        raise QueueConflict('Unknown device work cannot be recovered by pending END completion.')
    running = db.execute("SELECT id FROM operation_jobs WHERE device_id=? AND state='RUNNING'", (token.device_id,)).fetchall()
    if {row['id'] for row in running} != set(jobs):
        raise QueueConflict('Checkpoint differs from the complete original RUNNING device scope.')
    claims = db.execute('''SELECT * FROM shun_events WHERE device_id=? AND event_type='SHUN_OPERATION_RUNNING'
        AND json_extract(details_json,'$.device_executor.owner')=?
        AND json_extract(details_json,'$.device_executor.epoch')=? ORDER BY timestamp,id LIMIT 65''',
                        (token.device_id, token.owner, token.epoch)).fetchall()
    if not len(jobs) <= len(claims) <= 64:
        raise QueueConflict('Checkpoint requires the complete bounded original visit claims.')
    lease_claims = db.execute('''SELECT * FROM shun_events WHERE device_id=? AND event_type='DEVICE_LEASE_CLAIMED'
        AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=? LIMIT 2''',
                             (token.device_id, token.owner, token.epoch)).fetchall()
    if len(lease_claims) != 1:
        raise QueueConflict('Checkpoint requires its single original lease claim.')
    inventory = db.execute('SELECT * FROM devices WHERE id=?', (token.device_id,)).fetchone()
    if inventory is None or inventory['enabled'] != 1:
        raise QueueConflict('Pending END device must remain enabled with unchanged inventory.')
    evidence, pending, seen, group = [], {}, set(), None
    for claim in claims:
        details = json.loads(claim['details_json'])
        job_id = details.get('operation_id')
        if job_id in seen:
            raise QueueConflict('Duplicate claim in the original pending END visit.')
        seen.add(job_id)
        job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
        attempt = db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?', (job_id,)).fetchone()
        if (job is None or job['device_id'] != token.device_id or claim['ip'] != job['ip']
                or not lease_claims[0]['timestamp'] <= claim['timestamp'] <= timestamp
                or details.get('device_executor') != {'owner': token.owner, 'epoch': token.epoch}
                or type(details['device_executor'].get('epoch')) is not int):
            raise QueueConflict('Pending END contains a foreign or late original claim.')
        events = db.execute('''SELECT e.* FROM operation_links l JOIN shun_events e ON e.request_id=l.request_id
            WHERE l.job_id=? AND json_extract(e.details_json,'$.operation_id')=? ORDER BY e.timestamp,e.id''',
                            (job_id, job_id)).fetchall()
        if job_id in jobs:
            if (attempt is None or job['action'] != 'ADD' or job['dispatch_kind'] != 'ADD'
                    or type(details.get('batch_session_version')) is not int or details['batch_session_version'] != 7):
                raise QueueConflict('Pending END member is not its original managed v7 ADD.')
            validate_binding(db, attempt, job)
            candidate = details.get('addition_group')
            _uuid(candidate)
            if group is None:
                group = candidate
            acknowledgements = [event for event in events if event['event_type'] == 'SHUN_ADDITION_ACKNOWLEDGED']
            if candidate != group or len(acknowledgements) != 1:
                raise QueueConflict('Pending END requires its single original group and ACK per member.')
            ack = acknowledgements[0]
            value = json.loads(ack['details_json'])
            if (value.get('batch_session') != {'group': group, 'owner': token.owner, 'epoch': token.epoch, 'version': 7}
                    or type(value['batch_session'].get('epoch')) is not int
                    or type(value['batch_session'].get('version')) is not int
                    or value.get('verified') is not False or type(value.get('sequence')) is not int
                    or ack['device_id'] != token.device_id or ack['ip'] != job['ip']
                    or not claim['timestamp'] <= ack['timestamp'] <= timestamp):
                raise QueueConflict('Pending END acknowledgement differs from its original command.')
            pending[job_id] = PendingAddition(IPv4Address(job['ip']), value['sequence'])
        else:
            results = [event for event in events if event['event_type'] == 'SHUN_OPERATION_' + job['state']
                       and json.loads(event['details_json']).get('device_executor') ==
                       {'owner': token.owner, 'epoch': token.epoch}]
            if (job['state'] not in ('VERIFIED', 'NOOP') or len(results) != 1
                    or results[0]['device_id'] != token.device_id or results[0]['ip'] != job['ip']
                    or not claim['timestamp'] <= results[0]['timestamp'] <= timestamp):
                raise QueueConflict('Earlier visit claims must retain their exact settled result.')
        evidence.append([_row(claim), _row(job), _row(attempt) if attempt else None, [_row(event) for event in events]])
    if not set(jobs) <= seen:
        raise QueueConflict('Missing original pending END member claim.')
    acknowledgements = tuple(pending[job] for job in jobs)
    packet = bytes([6, 7, 0x1d, sequence, len(jobs)]) + b''.join(ack.ip.packed for ack in acknowledgements)
    decode_pending_end(packet, sequence, acknowledgements, version=7)  # Local scope validation, not I/O proof.
    digest = hashlib.sha256(json.dumps([_row(inventory), _row(lease_claims[0]), evidence],
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'format_version': 1, 'owner': token.owner, 'epoch': token.epoch, 'group': group,
            'jobs': list(jobs), 'sequence': sequence, 'digest': digest,
            'acknowledgements': [{'ip': str(ack.ip), 'sequence': ack.sequence} for ack in acknowledgements]}


def prepare(queue, sequence):
    """Commit the exact local recovery checkpoint BEFORE END_PENDING is sent."""
    token = queue.token
    def write(db):
        PendingExecution._profile(db)
        DeviceLeases(queue.store, queue).check(db, token)
        queue._pending_evidence(db, sequence)
        timestamp = _stamp(queue._now())
        details = _scope(db, token, tuple(queue.pending), sequence, timestamp)
        existing = _events(db, token)
        if existing:
            if len(existing) != 1 or not _same_scope(json.loads(existing[0]['details_json']), details):
                raise QueueConflict('Pending END checkpoint cannot change or replace original scope.')
            return
        request = db.execute('SELECT id FROM managed_bulk_attempts WHERE job_id=?', (queue.pending[0],)).fetchone()
        queue.store._insert_event(db, EVENT, token.device_id, None, None, 'system:pending-end-recovery',
                                  'Pending session recovery', (), request['id'], details, timestamp)
        DeviceLeases(queue.store, queue).check(db, token)

    return persist_result(queue.store, write, phase='pending_checkpoint')


def _events(db, token):
    return db.execute('''SELECT * FROM shun_events WHERE event_type=? AND device_id=?
        AND json_extract(details_json,'$.owner')=? AND json_extract(details_json,'$.epoch')=? LIMIT 2''',
                      (EVENT, token.device_id, token.owner, token.epoch)).fetchall()


@dataclass(frozen=True)
class _Checkpoint:
    token: DeviceLease
    fence: dict
    event: dict
    jobs: tuple
    sequence: int
    acknowledgements: tuple


class PendingRestart:
    def __init__(self, store, queue):
        self.store, self.queue = store, queue

    def inspect(self, device_id):
        """No writes; only the original expired LEASED state is eligible."""
        with self.store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)
            fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device_id,)).fetchone()
            timestamp = _stamp(self.queue._now())
            if fence is None or fence['state'] != 'LEASED' or fence['lease_until'] > timestamp:
                return None
            token = DeviceLease(device_id, fence['owner'], fence['epoch'])
            events = _events(db, token)
            if not events:
                return None
            if len(events) != 1 or not fence['updated_at'] <= timestamp or events[0]['timestamp'] > fence['lease_until']:
                raise QueueConflict('Pending END recovery requires its exact expired fence and single checkpoint.')
            event = events[0]
            value = json.loads(event['details_json'])
            if (type(value) is not dict or type(value.get('jobs')) is not list
                    or not 1 <= len(value['jobs']) <= 16):
                raise QueueConflict('Malformed pending END checkpoint; original fence retained.')
            jobs = tuple(value.get('jobs', []))
            expected = _scope(db, token, jobs, value.get('sequence'), event['timestamp'])
            if not _same_scope(value, expected):
                raise QueueConflict('Pending END checkpoint no longer matches original visit evidence.')
            attempt = db.execute('SELECT id FROM managed_bulk_attempts WHERE job_id=?', (jobs[0],)).fetchone()
            if (event['request_id'] != attempt['id'] or event['actor_subject'] != 'system:pending-end-recovery'
                    or event['ip'] is not None):
                raise QueueConflict('Pending END checkpoint has a substituted original requester.')
            return _Checkpoint(token, dict(fence), dict(event), jobs, expected['sequence'],
                               tuple(PendingAddition(IPv4Address(ack['ip']), ack['sequence'])
                                     for ack in expected['acknowledgements']))

    def complete(self, checkpoint, receipt):
        """Commit journal-proved original handoff + release, never renew/retry."""
        if (type(checkpoint) is not _Checkpoint or type(receipt) is not SettledPendingAdditions
                or receipt != SettledPendingAdditions(checkpoint.token.device_id, UUID(checkpoint.token.owner).bytes,
                                                     checkpoint.sequence, checkpoint.acknowledgements)):
            raise QueueConflict('Pending END recovery requires its exact completed agent journal receipt.')
        token = checkpoint.token
        execution = PendingExecution(self.store, self.queue)
        with schema_connection(self.store) as db, _atomic(db):
            execution._profile(db)

            def check_fence(db, candidate):
                current = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (token.device_id,)).fetchone()
                events = _events(db, token)
                timestamp = _stamp(self.queue._now())
                if (candidate != token or current is None or dict(current) != checkpoint.fence
                        or current['state'] != 'LEASED' or not current['updated_at'] <= timestamp
                        or current['lease_until'] > timestamp or len(events) != 1 or dict(events[0]) != checkpoint.event
                        or device_uncertain(db, token.device_id)):
                    raise QueueConflict('Original expired pending END fence or evidence changed during recovery.')

            check_fence(db, token)
            expected = _scope(db, token, checkpoint.jobs, checkpoint.sequence, checkpoint.event['timestamp'])
            if not _same_scope(json.loads(checkpoint.event['details_json']), expected):
                raise QueueConflict('Pending END visit or inventory changed during journal lookup.')
            session = execution.evidence._record(token, receipt, checkpoint.jobs, check_fence, enabled=True, connection=db)
            execution._transition_awaiting(db, token, checkpoint.jobs, session)
            check_fence(db, token)
            timestamp = _stamp(self.queue._now())
            settled = db.execute('SELECT settled_at FROM managed_bulk_pending_sessions WHERE id=?', (session,)).fetchone()[0]
            if timestamp < settled:
                raise QueueConflict('Clock moved backwards during pending END recovery.')
            db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL,updated_at=? WHERE device_id=?",
                       (timestamp, token.device_id))
            self.store._insert_event(db, 'SHUN_PENDING_END_RECOVERED', token.device_id, None, None,
                                     'system:pending-end-recovery', 'Pending session recovery', (),
                                     checkpoint.event['request_id'], {'checkpoint_id': checkpoint.event['id'],
                                     'owner': token.owner, 'epoch': token.epoch, 'pending_session': session,
                                     'proves_creation': False}, timestamp)
            DeviceLeases(self.store, self.queue)._event(db, 'PENDING_END_RECOVERED', token, timestamp)
            DeviceLeases(self.store, self.queue)._event(db, 'RELEASED', token, timestamp)
            execution._profile(db)
        return session


def recover(store, device_id, agent):
    """One local lookup; failures retain the original fence and RUNNING evidence."""
    service = PendingRestart(store, OperationQueue(store))
    checkpoint = service.inspect(device_id)
    if checkpoint is None:
        return False
    receipt = agent.pending_session_completed(device_id, checkpoint.token.owner, checkpoint.sequence,
                                             checkpoint.acknowledgements)
    session = service.complete(checkpoint, receipt)
    print(json.dumps({'event': 'queue.pending_end.restart_recovered', 'device_id': device_id,
                      'epoch': checkpoint.token.epoch, 'pending_session': session,
                      'awaiting_confirmation': len(checkpoint.jobs)}), flush=True)
    return True
