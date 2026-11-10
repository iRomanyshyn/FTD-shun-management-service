"""Explicit fresh-profile v7 worker; no configured startup, DDL or activation.

Keeps v5/v6 on their original path. Only the separate coordinator below may
compose durable pending handoff, causal confirmation and bounded fresh retries.
"""

import sqlite3
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

from .agent_client import AgentUnavailable
from .agent_protocol import SettledPendingAdditions
from .batch_queue import BatchDeviceOperationQueue
from .batch_session import BatchSession
from .bulk_discovery import BulkDiscovery
from .bulk_dispatch import _snapshot
from .bulk_policy import BulkUnavailable, _atomic
from .device_leases import DeviceOperationQueue, device_uncertain
from .managed_restoration import CompleteSnapshot
from .operation_queue import QueueConflict, QueueFull
from .parallel_synchronizer import ParallelSynchronizer, _DeviceWorker
from .pending_execution import PendingExecution
from .pending_retries import PendingRetries, RetryDeferred, retry_candidates
from .safety import mutations_suspended
from .schema import schema_connection


class DeferredDeviceOperationQueue(BatchDeviceOperationQueue):
    """Exact fresh-profile v7 claimant, not a widened ordinary queue selector."""

    _session_versions = (7,)

    def __init__(self, store, token, *, priority_removals=True, version=7):
        with store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)
        super().__init__(store, token, priority_removals=priority_removals, version=version)
        self.handed_off_session = None

    def handoff(self, owner, receipt):
        if owner != self.token.owner or type(receipt) is not SettledPendingAdditions:
            raise QueueConflict('Deferred handoff requires its actual typed terminal receipt and owner.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            self._executor(db, owner, self.token.device_id)
            self._pending_evidence(db, receipt.sequence)
        session = PendingExecution(self.store, self).await_confirmation(
            self.token, receipt, tuple(self.pending), enabled=True)
        # Do not clear memory or claim completion before the whole DB handoff
        # and original lease release have actually committed.
        self.handed_off_session = session
        self.pending.clear()
        return session


class DeferredBatchSession(BatchSession):
    _session_versions = (7,)

    def __init__(self, *args):
        super().__init__(*args)
        if not isinstance(self.queue, DeferredDeviceOperationQueue):
            raise TypeError('Deferred session requires its explicit fresh-profile queue.')

    async def flush(self, *, final=False):
        if not final or not self.queue.pending:
            return await super().flush(final=final)
        w = self.worker
        count = len(self.queue.pending)
        w._device_cycle.update(action='settling_pending_additions', ip=None, pending_verification=count)
        w._status_revision += 1
        receipt = await w._agent_call(self.cycle.finish_pending_additions)
        if getattr(self.cycle, 'settled', False) is not True:
            raise AgentUnavailable('Deferred terminal response lacks actual session settlement.')
        w.session_settled = True
        await w._local_call(self.queue.handoff, w.instance_id, receipt)
        w._device_cycle.update(pending_verification=0, awaiting_confirmation=count)
        w.note_state_change()
        # No complete read occurred here: no publication, refresh callback,
        # creation attribution or verified-progress increment is permitted.


class _RetryDiscovery:
    """Bounded advisory selector; PendingRetries rechecks every real permission."""

    def __init__(self, store, queue):
        self.store, self.queue = store, queue
        self.cursor = b''
        self.status = {'checked': 0, 'admitted': 0, 'counts': {}, 'retry_at': None}

    def discover(self, snapshot, addition_device_ids):
        counts, admitted, checked, retry_at = Counter(), 0, 0, None
        with self.store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)
            self.queue.leases.check(db, self.queue.token)
            if (mutations_suspended(db) or device_uncertain(db, snapshot.device_id)
                    or db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0]):
                self.status = {'checked': 0, 'admitted': 0, 'counts': {'paused_or_held': 1}, 'retry_at': None}
                return 0
            room = max(0, 16 - db.execute('''SELECT COUNT(*) FROM operation_jobs WHERE device_id=?
                AND state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION')''', (snapshot.device_id,)).fetchone()[0])
            rows = retry_candidates(db, snapshot.device_id, self.cursor)
        service = PendingRetries(self.store, self.queue)
        for row in rows[:64]:
            if admitted >= room:
                break
            checked += 1
            self.cursor = row['ip']
            if IPv4Address(row['ip']) in snapshot.present_ips:
                counts['present'] += 1
                continue
            with self.store._connection() as db:
                db.execute('BEGIN')
                PendingExecution._profile(db)
                revision = db.execute('SELECT revision FROM managed_bulk_registry').fetchone()[0]
                protected = db.execute('SELECT revision FROM protected_policy').fetchone()[0]
            try:
                result = service.admit(self.queue.token, snapshot, (row['id'],), revision, protected,
                    enabled=True, addition_device_ids=addition_device_ids)
            except RetryDeferred as wait:
                retry_at = min(retry_at, wait.retry_at) if retry_at else wait.retry_at
                counts['waiting'] += 1
            except QueueFull:
                counts['capacity'] += 1
                break
            except QueueConflict:
                counts['ineligible'] += 1  # Revocation/stale evidence, never unknown replay.
            else:
                admitted += not result['replayed']
                counts['admitted' if not result['replayed'] else 'historical'] += 1
        if checked == len(rows):
            self.cursor = b''
        self.status = {'checked': checked, 'admitted': admitted, 'counts': dict(counts), 'retry_at': retry_at}
        return admitted


class _DeferredDeviceWorker(_DeviceWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bulk_discovery = BulkDiscovery(self.store, self.queue, enabled=self.bulk_dispatch_enabled,
            addition_device_ids=self.addition_device_ids, admission_limit=64, check_limit=256)
        self._retry_cursor = b''
        self.retry_discovery = None

    def _bound_queue(self, token, priority_removals):
        if self.device_id in self.addition_device_ids:
            return DeferredDeviceOperationQueue(self.store, token, priority_removals=priority_removals)
        return DeviceOperationQueue(self.store, token, priority_removals=priority_removals)

    def bind(self, *args, **kwargs):
        super().bind(*args, **kwargs)
        self.retry_discovery = _RetryDiscovery(self.store, self.queue)
        self.retry_discovery.cursor = self._retry_cursor

    def _confirm_read(self, evidence):
        with schema_connection(self.store) as db, _atomic(db):
            PendingExecution._profile(db)
            self.queue.leases.check(db, self.queue.token)
            sessions = db.execute('''SELECT s.id FROM managed_bulk_pending_sessions s
                WHERE s.device_id=? AND NOT EXISTS(SELECT 1 FROM managed_bulk_pending_reads r WHERE r.session_id=s.id)
                ORDER BY s.settled_at,s.id LIMIT 17''', (self.device_id,)).fetchall()
            if len(sessions) > 16:
                raise BulkUnavailable('Deferred read exceeds its bounded outstanding session scope.')
            execution = PendingExecution(self.store, self.queue)
            outcomes = [outcome for session in sessions for outcome in execution.confirm(
                self.queue.token, session['id'], evidence, enabled=True, connection=db)]
            self.queue.leases.check(db, self.queue.token)
        return dict(Counter(state for _, state in outcomes))

    async def _process_complete_snapshot(self, device_id, snapshot, started, completed):
        evidence = CompleteSnapshot(str(uuid4()), device_id, started, completed,
                                    frozenset(entry.ip for entry in snapshot))
        _snapshot(evidence)
        if (device_id != self.device_id or not started <= completed <= self.queue._now()
                or started < self.queue._now() - timedelta(seconds=120)):
            raise QueueConflict('Deferred processing requires a current complete same-device read.')
        confirmed = await self._local_call(self._confirm_read, evidence)
        self._device_cycle['confirmation'] = dict(Counter(self._device_cycle.get('confirmation', {})) + Counter(confirmed))
        # Results before observations: generic presence never turns into an
        # original creation receipt or permits replay of an unknown command.
        await self._publish_complete_snapshot(device_id, snapshot)
        if not self._stop_mutations and not self._mutations_blocked and device_id in self.addition_device_ids:
            try:
                await self._local_call(self.retry_discovery.discover, evidence, self.addition_device_ids)
                self._retry_cursor = self.retry_discovery.cursor
                await self._local_call(self.bulk_discovery.discover, evidence, self.instance_id)
                self._device_cycle['retry'] = deepcopy(self.retry_discovery.status)
                self.note_state_change()
            except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
                self._restoration_failed()

    async def _session_mutations(self, device_id, cycle, snapshot):
        if isinstance(self.queue, DeferredDeviceOperationQueue):
            result = await DeferredBatchSession(self, device_id, cycle, snapshot).run()
            if self.queue.handed_off_session is not None:
                self._device_cycle['action'] = 'awaiting_confirmation'
            return result
        return await super()._session_mutations(device_id, cycle, snapshot)

    def _release_completed_visit(self):
        session_id = getattr(self.queue, 'handed_off_session', None)
        if session_id is None:
            return super()._release_completed_visit()
        with self.store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)
            row = db.execute('SELECT * FROM managed_bulk_pending_sessions WHERE id=?', (session_id,)).fetchone()
            if (not self.session_settled or self.rpc_failed or row is None
                    or row['owner'] != self.instance_id or row['epoch'] != self.queue.token.epoch
                    or row['device_id'] != self.device_id):
                raise QueueConflict('Deferred visit lacks its exact committed original handoff.')
        # The atomic original handoff already released this lease. Never release
        # again, renew it or touch a possible successor's current lease.


class DeferredParallelSynchronizer(ParallelSynchronizer):
    """Internal opt-in only; current service/client/agent configuration stays v5/v6."""

    _worker_type = _DeferredDeviceWorker

    def __init__(self, store, agent, *, enabled=False, **configuration):
        if type(enabled) is not bool:
            raise ValueError('Deferred execution requires a literal explicit capability.')
        for name in ('bulk_dispatch_enabled', 'batch_additions_enabled'):
            if name in configuration and configuration[name] is not enabled:
                raise ValueError('Deferred execution requires exact matching bulk/grouped capabilities.')
            configuration[name] = enabled
        if configuration.get('settled_cycles_required', True) is not True:
            raise ValueError('Deferred execution cannot disable actual terminal settlement.')
        configuration['settled_cycles_required'] = True
        if enabled:
            self._validate_transport(agent)
        super().__init__(store, agent, enabled=enabled, **configuration)
        self._priority_removals = True

    def _validate_execution_storage(self):
        self._validate_transport(self.agent)
        with self.store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)

    @staticmethod
    def _validate_transport(agent):
        if (type(getattr(agent, 'batch_session_version', None)) is not int
                or agent.batch_session_version != 7 or any(getattr(agent, name, None) is not True
                    for name in ('settled_cycles', 'tracked_cycles', 'batch_additions'))):
            raise ValueError('Deferred execution requires an explicitly matching strict tracked-v7 client.')

    def status(self):
        return {**super().status(), 'deferred_confirmation': {
            str(device): deepcopy(worker.retry_discovery.status) if worker.retry_discovery else {}
            for device, worker in self._workers.items()}}
