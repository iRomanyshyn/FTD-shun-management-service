"""Bounded staged ADD orchestration inside the existing device worker only."""

import json
import sqlite3
from ipaddress import IPv4Address

from .agent_client import AgentUnavailable
from .agent_protocol import (
    AdditionResult,
    PendingAddition,
    max_cycle_mutations,
    max_pending_additions,
)
from .batch_queue import BatchDeviceOperationQueue, PendingBatchMustFlush
from .operation_queue import ClaimNotSubmitted


class BatchSession:
    _session_versions = (5, 6)

    def __init__(self, worker, device_id, cycle, snapshot):
        if (not worker.batch_additions_enabled or cycle.version not in self._session_versions
                or not isinstance(worker.queue, BatchDeviceOperationQueue)):
            raise ValueError('Grouped execution requires the explicit matching fenced grouped worker.')
        self.worker, self.device, self.cycle = worker, device_id, cycle
        self.queue, self.snapshot = worker.queue, snapshot
        if self.queue.version != cycle.version:
            raise ValueError('Queue and agent session versions differ.')
        self.limit = max_cycle_mutations(cycle.version)
        worker._device_cycle['limit'] = self.limit

    async def publish(self, snapshot, started, completed):
        self.snapshot = snapshot
        w = self.worker
        await w._process_complete_snapshot(self.device, snapshot, started, completed)

    async def flush(self, *, final=False):
        if not self.queue.pending:
            return
        w = self.worker
        w._device_cycle.update(action='verify_addition_batch', ip=None,
                               pending_verification=len(self.queue.pending))
        w._status_revision += 1
        started = self.queue._now()
        result = (await w._finish_addition_session(self.cycle) if final else
                  await w._agent_call(self.cycle.verify_additions))
        completed = self.queue._now()
        before = self.queue.settled
        try:
            await w._local_call(self.queue.finish_verified_group, w.instance_id, result, self.cycle.sequence - 1)
        finally:
            w._device_cycle['completed'] += self.queue.settled - before
            w._device_cycle['pending_verification'] = len(self.queue.pending)
            w.note_state_change()
        # Result-before-publication is essential: otherwise reconciliation could
        # create an occurrence and cause the verified ADD's origin to be refused.
        await self.publish(list(result.snapshot), started, completed)
        if self.cycle.version >= 6 and not final:
            # No pending writes remain. New jobs require this fresh read and
            # current authority; old delegations/deadlines are never extended.
            w._cycle_cutoff = await w._local_call(self.queue.cutoff)

    async def priority(self):
        w = self.worker
        if not w._priority_pending or w._priority_used:
            return True
        w._priority_pending = False
        if self.queue.pending:
            await self.flush()  # This complete read can satisfy the coalesced hint.
        elif w._priority_read_due(self.device):
            w._priority_used = True
            w._device_cycle.update(action='priority_snapshot', priority_state='reading')
            w._status_revision += 1
            started = self.queue._now()
            snapshot = await w._agent_call(self.cycle.snapshot)
            completed = self.queue._now()
            if snapshot is None:
                w._device_cycle.update(priority_state='joining_final_snapshot', budget_deferred=True)
                return False
            await self.publish(snapshot, started, completed)
        w._device_cycle['priority_state'] = 'satisfied'
        w._set_interactive_state('running')
        return True

    async def full_group(self):
        """Verified versions always observe a full group before continuing."""
        await self.flush()
        return True

    async def stage(self, job, target):
        w = self.worker
        w._device_cycle.update(action='stage_addition', ip=str(target))
        w._status_revision += 1
        try:
            result = await w._agent_call(self.cycle.stage_addition, target)
            if result is None:
                await w._local_call(self.queue.defer_addition, job['id'], w.instance_id)
                w._device_cycle['budget_deferred'] = True
                return False
            if type(result) is PendingAddition:
                if result.ip != target:
                    raise AgentUnavailable('Pending ADD acknowledgement has the wrong target.')
                await w._local_call(self.queue.acknowledge_addition, job['id'], w.instance_id, result)
                w._device_cycle['pending_verification'] = len(self.queue.pending)
            elif type(result) is AdditionResult and result.created is False and result.interface is None:
                state = await w._local_call(self.queue.finish_addition, job['id'], w.instance_id, result)
                if state != 'NOOP':
                    raise AgentUnavailable('Existing ADD was not settled as NOOP.')
                w._device_cycle['completed'] += 1
                if self.queue.priority_removals and target in await w._local_call(w.policy.enabled_ips):
                    await w._local_call(w._admit_trusted, self.device, [target])
            else:
                raise AgentUnavailable('Stage returned success instead of an exact pending/NOOP result.')
        except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
            # This claimed job may not yet be in the acknowledged group. Retain
            # its uncertainty as well as all older pending members, never defer.
            try:
                await w._local_call(self.queue.finish_addition, job['id'], w.instance_id,
                                    'UNVERIFIED', reason=str(error))
            except (ValueError, sqlite3.Error) as local_error:
                print(json.dumps({'event': 'queue.addition_batch.evidence_write_failed', 'operation_id': job['id'],
                                  'reason': str(local_error), 'fence_retained': True}), flush=True)
            raise
        finally:
            w._status_revision += 1
        return True

    async def remove(self, job, target):
        w = self.worker
        if self.queue.pending:
            raise AgentUnavailable('Removal was claimed before pending additions were verified.')
        w._device_cycle.update(action='remove_and_verify', ip=str(target))
        w._status_revision += 1
        try:
            result = await w._agent_call(self.cycle.remove_shun, target)
        except (AgentUnavailable, OSError, ValueError) as error:
            await w._local_call(self.queue.finish_removal, job['id'], w.instance_id, 'UNVERIFIED', str(error))
            raise
        if result is None:
            await w._local_call(self.queue.defer_removal, job['id'], w.instance_id)
            w._device_cycle['budget_deferred'] = True
            return False
        if type(result) is not bool:
            await w._local_call(self.queue.finish_removal, job['id'], w.instance_id, 'UNVERIFIED', 'Invalid removal result')
            raise AgentUnavailable('Invalid typed removal result.')
        await w._local_call(self.queue.finish_removal, job['id'], w.instance_id, 'VERIFIED' if result else 'NOOP')
        w._device_cycle['completed'] += 1
        w.note_state_change()
        return True

    async def run(self):
        w = self.worker
        w._device_cycle['pending_verification'] = 0
        try:
            if self.cycle.version >= 6:
                # The caller published and discovered the complete initial read.
                # Freeze this segment only; each claim retains its evidence age.
                w._cycle_cutoff = await w._local_call(self.queue.cutoff)
            allowed = await w._local_call(w.policy.enabled_ips)
            await w._local_call(w._admit_trusted, self.device,
                                sorted({entry.ip for entry in self.snapshot if entry.ip in allowed}, key=int))
            attempts = 0
            while attempts < self.limit and not w._mutations_blocked and not w._stop_mutations:
                if not await self.priority():
                    break
                if w._mutations_blocked or w._stop_mutations:
                    break
                cutoff = w._cycle_cutoff if w._cycle_cutoff is not None else self.queue.cutoff()
                try:
                    job = await w._local_call(self.queue.claim_next_mutation, self.device, w.instance_id, cutoff,
                                             additions_enabled=True, bulk_dispatch_enabled=True)
                except PendingBatchMustFlush:
                    await self.flush()
                    continue  # No command/claim consumed; priority REMOVE goes next.
                except ClaimNotSubmitted:
                    w._device_cycle['budget_deferred'] = True
                    break
                if job is None:
                    break
                attempts += 1
                target = IPv4Address(job['ip'])
                if job['action'] == 'ADD':
                    if not await self.stage(job, target):
                        break
                    if (len(self.queue.pending) >= max_pending_additions(self.cycle.version)
                            and attempts < self.limit and not await self.full_group()):
                        break
                elif not await self.remove(job, target):
                    break
            # Stop/pause/defer/expiry all share one final verification observation
            # and actual terminal settlement, rather than VERIFY then another END.
            final_group = bool(self.queue.pending)
            if final_group:
                await self.flush(final=True)
            w._device_cycle.update(action='final_snapshot', ip=None)
            if attempts >= self.limit and w._has_pending(self.device):
                w._device_cycle['budget_deferred'] = True
            w._status_revision += 1
            if not final_group:
                started = self.queue._now()
                snapshot = await w._finish_session(self.cycle)
                completed = self.queue._now()
                await self.publish(snapshot, started, completed)
            w._priority_pending = False
            w._device_cycle.update(action='completed', priority_state='satisfied')
            return w._mutations_blocked
        except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
            w.rpc_failed = True  # Local failures after a possible write also retain the fence.
            try:
                await w._local_call(self.queue.fail_pending_group, w.instance_id, str(error))
            except (ValueError, sqlite3.Error) as local_error:
                print(json.dumps({'event': 'queue.addition_batch.evidence_write_failed', 'device_id': self.device,
                                  'reason': str(local_error), 'fence_retained': True}), flush=True)
            w._device_cycle.update(action='failed', pending_verification=len(self.queue.pending))
            w.note_state_change()
            print(json.dumps({'event': 'queue.addition_batch.failed', 'device_id': self.device,
                              'reason': str(error), 'pending_verification': len(self.queue.pending)}), flush=True)
            return f'device batch cycle failed: {error}'
