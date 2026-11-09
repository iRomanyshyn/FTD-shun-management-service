"""Live-epoch pending ADD evidence, not a second queue or replay mechanism."""

import json
from ipaddress import IPv4Address
from uuid import uuid4

from .agent_protocol import (
    MAX_PENDING_ADDITIONS,
    AdditionResult,
    PendingAddition,
    VerifiedAdditionBatch,
    max_cycle_sequence,
)
from .device_leases import DeviceOperationQueue
from .operation_queue import OperationQueue, QueueConflict


class PendingBatchMustFlush(QueueConflict):
    """No claim committed: settle the acknowledged group before priority work."""


class BatchDeviceOperationQueue(DeviceOperationQueue):
    """One fresh in-memory group over durable original RUNNING jobs and audit.

    Construction cannot adopt a previous group's work, even in the same epoch.
    Every additional claim validates exact retained acknowledgements. No schema,
    new authority, terminal state, generic concurrency or automatic recovery.
    """

    def __init__(self, store, token, *, priority_removals=False, version=5):
        if type(version) is not int or version not in (5, 6):
            raise ValueError('Grouped queue requires its literal matching session version.')
        self.version = version
        super().__init__(store, token, priority_removals=priority_removals)
        self.group = str(uuid4())
        self.pending = []
        self.settled = 0
        self.verification_sequence = None

    def _binding(self):
        return {'group': self.group, 'owner': self.token.owner, 'epoch': self.token.epoch,
                **({'version': 6} if self.version == 6 else {})}

    def _events(self, db, job_id, event):
        # Existing request-ID index avoids scanning the whole import history.
        return db.execute('''SELECT e.* FROM operation_links l JOIN shun_events e ON e.request_id=l.request_id
            WHERE l.job_id=? AND e.event_type=? AND json_extract(e.details_json,'$.operation_id')=?''',
                          (job_id, event, job_id)).fetchall()

    def _claim_evidence(self, db, job):
        # Exact pre-write deferrals may retain older RUNNING claims for this
        # same job. Those remain history, never this live epoch's permission.
        events = [event for event in self._events(db, job['id'], 'SHUN_OPERATION_RUNNING')
                  if json.loads(event['details_json']).get('device_executor') ==
                  {'owner': self.token.owner, 'epoch': self.token.epoch}]
        if len(events) != 1:
            raise QueueConflict('Pending ADD requires its single original claim audit.')
        details = json.loads(events[0]['details_json'])
        if (details.get('addition_group') != self.group
                or details.get('device_executor') != {'owner': self.token.owner, 'epoch': self.token.epoch}
                or events[0]['device_id'] != self.token.device_id or events[0]['ip'] != job['ip']
                or job['state'] != 'RUNNING' or job['action'] != 'ADD' or job['dispatch_kind'] != 'ADD'):
            raise QueueConflict('Pending ADD claim does not belong to this exact live group.')

    def _pending_evidence(self, db, verification_sequence=None):
        jobs = db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND state='RUNNING' ORDER BY seq",
                          (self.token.device_id,)).fetchall()
        if (len(self.pending) > MAX_PENDING_ADDITIONS or len(self.pending) != len(set(self.pending))
                or {row['id'] for row in jobs} != set(self.pending)):
            raise QueueConflict('RUNNING device work differs from the acknowledged pending group.')
        by_id = {job['id']: job for job in jobs}
        previous_sequence = 0
        for job_id in self.pending:
            job = by_id[job_id]
            self._claim_evidence(db, job)
            events = self._events(db, job_id, 'SHUN_ADDITION_ACKNOWLEDGED')
            if len(events) != 1:
                raise QueueConflict('Pending ADD acknowledgement is missing or duplicated.')
            details = json.loads(events[0]['details_json'])
            sequence = details.get('sequence')
            if (details.get('batch_session') != self._binding() or type(sequence) is not int
                    or not previous_sequence < sequence <= max_cycle_sequence(self.version) or details.get('verified') is not False
                    or events[0]['device_id'] != job['device_id'] or events[0]['ip'] != job['ip']):
                raise QueueConflict('Pending acknowledgement has a foreign binding or sequence.')
            previous_sequence = sequence
        if verification_sequence is not None and verification_sequence <= previous_sequence:
            raise QueueConflict('Group verification must follow every staged command.')
        return [by_id[job_id] for job_id in self.pending]

    def _claim_running_scope(self, db, device_id, owner, action):
        # The owning claim transaction checked the exact executor immediately
        # before this hook and checks it again before commit. Do not repeat a
        # complete profile scan between those adjacent read-only steps.
        if not self.pending:
            return super()._claim_running_scope(db, device_id, owner, action)
        self._pending_evidence(db)
        protected_pending = db.execute('''SELECT 1 FROM operation_jobs j JOIN protected_ips p ON p.ip=j.ip
            WHERE j.device_id=? AND j.state='RUNNING' AND p.enabled=1''', (device_id,)).fetchone()
        if protected_pending or len(self.pending) >= MAX_PENDING_ADDITIONS or action == 'REMOVE' or (
                self.priority_removals and db.execute(
                    "SELECT 1 FROM operation_jobs WHERE device_id=? AND state='QUEUED' AND action='REMOVE'",
                    (device_id,)).fetchone()):
            raise PendingBatchMustFlush('Verify pending additions before priority removal or another group.')
        return True, 'ADD'  # Never claim REMOVE while any ADD is awaiting observation.

    def _event(self, db, event, request, job, details=None):
        if self.version == 6 and job['action'] == 'ADD':
            details = {**(details or {}), 'batch_session_version': 6}
        if event == 'SHUN_OPERATION_RUNNING' and job['action'] == 'ADD':
            # Membership is an additional grouped-claim requirement, not a
            # replacement profile validator. The base event below still calls
            # attempt_for_job, including its complete exact-profile validation,
            # before inserting audit in this same transaction.
            if not db.execute('SELECT 1 FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone():
                raise QueueConflict('Grouped ADD requires an original managed bulk attempt.')
            details = {**(details or {}), 'addition_group': self.group}
        elif job['action'] == 'ADD' and event in {'SHUN_OPERATION_VERIFIED', 'SHUN_OPERATION_UNVERIFIED', 'SHUN_OPERATION_NOOP'}:
            details = {**(details or {}), 'addition_group': self.group}
            if self.verification_sequence is not None:
                details['verification_sequence'] = self.verification_sequence
        super()._event(db, event, request, job, details)

    def acknowledge_addition(self, job_id, owner, acknowledgement):
        if (type(acknowledgement) is not PendingAddition or type(acknowledgement.sequence) is not int
                or not 1 <= acknowledgement.sequence <= max_cycle_sequence(self.version) or type(acknowledgement.ip) is not IPv4Address):
            raise ValueError('An exact pending ADD acknowledgement is required.')
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._executor(db, owner, self.token.device_id)
            if job_id in self.pending or len(self.pending) >= MAX_PENDING_ADDITIONS:
                raise QueueConflict('Duplicate or full pending addition group.')
            job = db.execute('SELECT * FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
            if job is None or job['device_id'] != self.token.device_id or job['ip'] != acknowledgement.ip.packed:
                raise QueueConflict('Pending acknowledgement target differs from its original job.')
            self._claim_evidence(db, job)
            if self._events(db, job_id, 'SHUN_ADDITION_ACKNOWLEDGED'):
                raise QueueConflict('Pending acknowledgement is already retained.')
            # Managed bulk jobs have one immutable original requester. ACK is a
            # distinct nonterminal diagnostic, not a second claim/terminal proof.
            requests = db.execute('''SELECT r.* FROM operation_requests r JOIN operation_links l
                ON l.request_id=r.id WHERE l.job_id=?''', (job_id,)).fetchall()
            if len(requests) != 1:
                raise QueueConflict('Pending managed ADD requires exactly one original requester.')
            OperationQueue._event(self, db, 'SHUN_ADDITION_ACKNOWLEDGED', requests[0], job,
                                  {'batch_session': self._binding(), 'sequence': acknowledgement.sequence, 'verified': False})
            db.execute("UPDATE operation_jobs SET reason='Awaiting batch verification' WHERE id=?", (job_id,))
            self._bump(db)
            self._executor(db, owner, self.token.device_id)
        self.pending.append(job_id)  # Only after the acknowledgement transaction commits.

    def finish_verified_group(self, owner, result, sequence):
        if type(result) is not VerifiedAdditionBatch or type(sequence) is not int or not 1 <= sequence <= max_cycle_sequence(self.version):
            raise ValueError('A complete typed group result and exact verification sequence are required.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            self._executor(db, owner, self.token.device_id)
            jobs = self._pending_evidence(db, sequence)
            expected = tuple(IPv4Address(job['ip']) for job in jobs)
            if not expected or tuple(ip for ip, _ in result.additions) != expected:
                raise QueueConflict('Verified group differs from the complete ordered pending scope.')
            observed = {ip: [] for ip in expected}
            for entry in result.snapshot:
                if entry.ip in observed:
                    observed[entry.ip].append(entry.interface)
            for ip, addition in result.additions:
                if (type(addition) is not AdditionResult or addition.created is not True
                        or observed[ip] != [addition.interface]):
                    raise QueueConflict('Group verification lacks exact per-target creation scope.')
        self.verification_sequence = sequence
        try:
            for job, (_, addition) in zip(jobs, result.additions, strict=True):
                # Intentionally separate transactions: retain earlier verified
                # results if a later local settlement fails. Publish no snapshot here.
                state = super().finish_addition(job['id'], owner, addition)
                if state != 'VERIFIED':
                    raise QueueConflict('Group creation attribution was refused; uncertainty retained.')
                self.pending.remove(job['id'])
                self.settled += 1
        finally:
            self.verification_sequence = None
        self.group = str(uuid4())

    def fail_pending_group(self, owner, reason):
        # Do not overwrite an already committed terminal result if a local
        # failure happened after commit but before its caller saw the result.
        for job_id in tuple(self.pending):
            with self.store._connection() as db:
                self._executor(db, owner, self.token.device_id)
                row = db.execute('SELECT state FROM operation_jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise QueueConflict('Pending job evidence is missing; device fence retained.')
            if row['state'] == 'RUNNING':
                super().finish_addition(job_id, owner, 'UNVERIFIED', reason=reason)
            elif row['state'] not in {'VERIFIED', 'UNVERIFIED'}:
                raise QueueConflict('Unexpected pending terminal state; device fence retained.')
            self.pending.remove(job_id)
