"""Explicit bounded parallel rounds on existing fenced storage; no activation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from .agent_client import (
    AgentCycleNotStarted,
    AgentCycleOpenFailed,
    AgentCycleReadFailed,
    AgentUnavailable,
)
from .bulk_discovery import BulkDiscovery
from .device_leases import DeviceLeases, DeviceOperationQueue
from .operation_queue import OperationQueue, QueueConflict
from .session_timing import SessionTiming
from .synchronizer import Synchronizer


class _DeviceWorker(Synchronizer):
    """One isolated context running the same semantic collector/result pipeline."""

    def __init__(self, store, agent, device_id, **configuration):
        super().__init__(store, agent, initialize_queue=False, **configuration)
        self.device_id = device_id
        self.rpc_failed = False
        self.snapshot_callback = None
        self.clock = monotonic
        self.require_settlement = False
        self._timing = SessionTiming()

    def bind(self, token, lease_seconds, *, priority_removals=False):
        self.queue = DeviceOperationQueue(self.store, token, priority_removals=priority_removals)
        self.instance_id = token.owner
        self._lease_seconds = lease_seconds
        # Preserve non-authoritative keyset hints across rounds, never authority.
        self.bulk_discovery.queue = self.queue
        self.bulk_discovery.source.queue = self.queue
        self.bulk_discovery.begin_cycle()
        self._stop_mutations = self.rpc_failed = False
        self.request_not_submitted = False
        self.opening_failed = False
        self.read_failed = False
        self.receipt_recovered = False
        self.session_bound = False
        self._read_session = None
        self.session_settled = False
        self._rpc_calls = 0
        self._managed_restoration_error = None
        self._cycle_cutoff = self.queue.cutoff()
        self._cycle_outcome = 'running'
        self._timing = SessionTiming()

    def _collection_devices(self):
        return [device for device in self.store.list_devices() if device.id == self.device_id]

    async def _prune_expired_history_if_due(self):
        # A parallel round never runs independent competing retention passes.
        # Retention stays with the owning service's maintenance lifecycle.
        return

    async def _agent_call(self, function, *args):
        opening = self._rpc_calls == 0 and function == self.agent.open_cycle and args == (self.device_id,)
        session = self._read_session
        reading = opening or (session is not None and not args
                              and getattr(function, '__self__', None) is session
                              and function in (session.snapshot, session.finish))
        phase = 'open' if opening else 'other'
        if session is not None and getattr(function, '__self__', None) is session:
            for name, label in (('snapshot', 'snapshot'), ('finish', 'finish'),
                                ('add_shun', 'add'), ('remove_shun', 'remove')):
                if function == getattr(session, name, None):
                    phase = label
                    break
        self._rpc_calls += 1
        started, local_before = monotonic(), self._timing.local_seconds
        try:
            self._rpc_started = self.clock()
            if opening and getattr(self.agent, 'tracked_cycles', False) is True:
                self.session_bound = True
                function, args = self.agent.open_tracked_cycle, (self.device_id, self.instance_id)
            result = await super()._agent_call(function, *args)
            if opening:
                self._read_session = result
            return result
        except AgentCycleNotStarted:
            self.rpc_failed = True
            self.request_not_submitted = opening
            raise
        except AgentCycleOpenFailed:
            self.rpc_failed = True
            self.opening_failed = opening
            raise
        except AgentCycleReadFailed:
            self.read_failed = reading and not self.rpc_failed
            self.rpc_failed = True
            raise
        except BaseException:
            # No replacement after an RPC/lease failure, even for read-only work.
            self.rpc_failed = True
            raise
        finally:
            # Base RPC first renews its lease via _local_call. Do not count
            # that database time twice or describe it as device/SSH latency.
            self._timing.rpc(monotonic() - started - (self._timing.local_seconds - local_before), phase)

    def _publish_snapshot(self, device_id, snapshot):
        super()._publish_snapshot(device_id, snapshot)
        self._last_complete_read = self.clock()
        if self.queue.priority_removals and not self._stop_mutations:
            allowed = self.policy.enabled_ips()
            self._admit_trusted(device_id, sorted({entry.ip for entry in snapshot if entry.ip in allowed}, key=int))

    async def _publish_complete_snapshot(self, device_id, snapshot):
        await super()._publish_complete_snapshot(device_id, snapshot)
        # Scheduling demand belongs to the owning event loop, never the SQL thread.
        if self.snapshot_callback is not None:
            self.snapshot_callback(device_id, self._rpc_started, self._last_complete_read)

    async def _local_call(self, function, *args, **kwargs):
        started = monotonic()
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        cancelled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    cancelled = self._stop_mutations = True
                    if task.cancelled():
                        raise
        finally:
            if timing := getattr(self, '_timing', None):
                timing.local(function, monotonic() - started)
        if cancelled:
            raise asyncio.CancelledError
        return result

    def _priority_read_due(self, device_id):
        last = getattr(self, '_last_complete_read', None)
        return last is None or self.clock() - last >= self.interactive_min_interval_seconds

    async def _finish_session(self, cycle):
        snapshot = await super()._finish_session(cycle)
        if self.require_settlement and getattr(cycle, 'settled', False) is not True:
            self.rpc_failed = True
            raise AgentUnavailable('Required cycle settlement was not confirmed; device fence retained.')
        self.session_settled = getattr(cycle, 'settled', False) is True
        return snapshot

    def _discover_snapshot(self, *args):
        if not self._stop_mutations:
            super()._discover_snapshot(*args)

    def _admit_trusted(self, *args):
        if not self._stop_mutations:
            super()._admit_trusted(*args)

    async def _session_addition(self, device_id, cycle, job, target):
        completed = await super()._session_addition(device_id, cycle, job, target)
        if completed and self.queue.priority_removals and target in self.policy.enabled_ips():
            self._admit_trusted(device_id, [target])
        return completed


class ParallelSynchronizer:
    """Internal round coordinator, disabled unless explicitly constructed enabled.

    No environment/API startup wiring or schema initialization. The separate
    service loop/read-demand timing/continuous dispatch remains an integration
    step. A round reuses Synchronizer's bounded sessions and shared job queue.
    """

    def __init__(self, store, agent, *, enabled=False, agent_concurrency=1,
                 operation_timeout_seconds=125, poll_interval_seconds=300,
                 interactive_min_interval_seconds=60, addition_device_ids=frozenset(),
                 bulk_dispatch_enabled=False, settled_cycles_required=False):
        if (type(enabled) is not bool or type(bulk_dispatch_enabled) is not bool or type(settled_cycles_required) is not bool
                or type(agent_concurrency) is not int or not 1 <= agent_concurrency <= 10
                or type(operation_timeout_seconds) is not int or not 5 <= operation_timeout_seconds <= 240
                or type(poll_interval_seconds) is not int or poll_interval_seconds < 1
                or type(interactive_min_interval_seconds) is not int or interactive_min_interval_seconds < 1
                or type(addition_device_ids) is not frozenset or len(addition_device_ids) > 10
                or any(type(device) is not int or not 1 <= device <= 65535 for device in addition_device_ids)):
            raise ValueError('Literal bounded parallel scheduler configuration is required.')
        rpc_timeout = getattr(agent, 'timeout_seconds', operation_timeout_seconds)
        if type(rpc_timeout) is not int or not 1 <= rpc_timeout <= operation_timeout_seconds:
            raise ValueError('Agent RPC deadline must fit the configured operation bound.')
        self.store, self.agent, self.enabled = store, agent, enabled
        self.agent_concurrency = agent_concurrency
        self.settled_cycles_required = settled_cycles_required
        self.queue = OperationQueue(store)
        self.leases = DeviceLeases(store, self.queue)
        self._lease_seconds = operation_timeout_seconds + 30
        self.configuration = {'poll_interval_seconds': poll_interval_seconds,
                              'interactive_min_interval_seconds': interactive_min_interval_seconds,
                              'operation_timeout_seconds': operation_timeout_seconds,
                              'session_cycles_enabled': True,
                              'import_execution_enabled': bulk_dispatch_enabled,
                              'addition_device_ids': addition_device_ids,
                              'bulk_dispatch_enabled': bulk_dispatch_enabled}
        self._workers = {}
        self._round = None
        self._stopping = False
        self._broken = False
        self._results = {}
        self._service_active = False
        self._priority_removals = False
        self._snapshot_callback = None
        self._clock = monotonic

    def status(self):
        """Local sampled round progress, not a replacement for Web freshness."""
        return deepcopy({'enabled': self.enabled, 'running': self._round is not None or self._service_active,
                         'execution_mode': 'continuous' if self._service_active else 'round' if self._round is not None else 'idle',
                         'stopping': self._stopping, 'broken': self._broken, 'devices': self._results,
                         'cycles': {str(device): worker._device_cycle for device, worker in self._workers.items()},
                         'bulk_discovery': {str(device): worker.bulk_discovery.status()
                                            for device, worker in self._workers.items()}})

    def _configured_devices(self):
        profile = self.leases.status()  # Exact profile validation, never initialize/repair.
        from .bulk_ordered_promotion import present as promotion_present

        if not self.settled_cycles_required:
            with self.store._connection() as db:
                if promotion_present(db):
                    raise QueueConflict('Ordered promotion storage requires strict local cycle settlement.')
        scope = {row['device_id'] for row in profile['devices']}
        inventory = {device.id: device for device in self.store.list_devices()}
        if (profile['concurrency'] > self.agent_concurrency
                or not self.configuration['addition_device_ids'] <= scope
                or not scope <= inventory.keys()
                or any(device.enabled and device.id not in scope for device in inventory.values())):
            raise QueueConflict('Existing fixed device scope/agent capacity does not match the coordinator.')
        if self.settled_cycles_required and getattr(self.agent, 'settled_cycles', False) is not True:
            raise QueueConflict('This coordinator requires explicit settled-cycle client capability.')
        devices = [device for device in inventory.values() if device.enabled]
        discovery = BulkDiscovery(self.store, self.queue, enabled=self.configuration['bulk_dispatch_enabled'],
                                  addition_device_ids=self.configuration['addition_device_ids'])
        return profile, discovery.ordered_devices(devices)

    async def sweep(self):
        if not self.enabled:
            return self.status()
        if self._round is not None or self._service_active:
            raise QueueConflict('A parallel round or continuous dispatcher is already active in this coordinator.')
        if self._broken:
            raise QueueConflict('Internal worker cancellation requires offline quiescence review.')
        profile, devices = self._configured_devices()
        self._stopping = False
        self._results = {}
        self._round = asyncio.create_task(self._collect(devices, profile['concurrency']))
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(self._round)
                    break
                except asyncio.CancelledError:
                    if self._round.cancelled():
                        # Forced event-loop/internal shutdown is not ordinary
                        # caller cancellation. Do not spin on a cancelled task
                        # or admit replacement RPCs in this process.
                        self._broken = self._stopping = True
                        raise
                    # to_thread cancellation is NOT RPC cancellation. Keep the
                    # tasks, device leases and pool slots until the current RPC
                    # and required session completion have actually returned.
                    cancelled = True
                    self._stopping = True
                    for worker in self._workers.values():
                        worker._stop_mutations = True
            if cancelled:
                raise asyncio.CancelledError
        finally:
            self._round = None
        return self.status()

    async def _collect(self, devices, concurrency):
        slots = asyncio.Semaphore(concurrency)

        async def visit(device):
            async with slots:
                await self._visit(device)

        # At most ten small waiting tasks, at most the sealed limit of sessions.
        # return_exceptions keeps siblings/slots alive even on an unexpected bug.
        results = await asyncio.gather(*(visit(device) for device in devices), return_exceptions=True)
        for device, result in zip(devices, results, strict=True):
            if isinstance(result, BaseException):
                self._results[str(device.id)] = {'state': 'held', 'error': 'Unexpected device worker failure.'}

    async def _visit(self, device):
        if self._stopping:
            self._results[str(device.id)] = {'state': 'not_started'}
            return
        worker = self._workers.get(device.id)
        if worker is None:
            worker = self._workers[device.id] = _DeviceWorker(
                self.store, self.agent, device.id, **self.configuration)
        timing_bound = False
        try:
            token = self.leases.claim(device.id, str(uuid4()), self._lease_seconds, enabled=True)
            if token is None:
                self._results[str(device.id)] = {'state': 'lease_held'}
                return
            worker.bind(token, self._lease_seconds, priority_removals=self._priority_removals)
            timing_bound = True
            worker.snapshot_callback, worker.clock = self._snapshot_callback, self._clock
            worker.require_settlement = self.settled_cycles_required
            self._results[str(device.id)] = {'state': 'running', 'epoch': token.epoch}
            await worker._collect()
            # Only exact bound terminal failure proof permits failed-session release.
            # A local processing error is not terminal agent settlement either.
            if worker.request_not_submitted:
                self.leases.release_unsubmitted(token)
                worker._devices[device.id]['error_category'] = 'agent_not_submitted'
            elif worker.opening_failed:
                self.leases.release_unopened(token)
                worker._devices[device.id]['error_category'] = 'agent_open_failed'
            elif worker.read_failed:
                self.leases.release_read_failed(token)
                worker._devices[device.id]['error_category'] = 'agent_read_failed'
            elif worker.session_bound and (worker.rpc_failed or not worker.session_settled):
                worker.rpc_failed = True
                try:
                    completed = await asyncio.to_thread(self.agent.read_only_session_completed, device.id, token.owner)
                except (AgentUnavailable, ValueError, OSError):
                    completed = False
                if completed is True:
                    self.leases.release_read_receipt_recovered(token)
                    worker.receipt_recovered = True
                    worker._devices[device.id]['error_category'] = 'agent_read_receipt_recovered'
            elif not worker.rpc_failed:
                if self.settled_cycles_required and not worker.session_settled:
                    worker.rpc_failed = True
                else:
                    worker.queue.finish_cycle(token.owner, 0)
            self._results[str(device.id)] = {
                'state': 'retrying' if worker.request_not_submitted or worker.opening_failed or worker.read_failed or worker.receipt_recovered else
                         'held' if worker.rpc_failed else worker._cycle_outcome,
                'epoch': token.epoch, 'details': deepcopy(worker._devices.get(device.id, {})),
            }
        except (ValueError, OSError, sqlite3.Error) as error:
            # Retain any acquired fence; never fabricate missing/late evidence.
            self._results[str(device.id)] = {'state': 'held', 'error': str(error)}
        finally:
            if timing_bound:
                print(json.dumps({'event': 'device.session.timing', 'device_id': device.id,
                                  'epoch': token.epoch, 'settled': worker.session_settled,
                                  **worker._timing.report()}, sort_keys=True), flush=True)
