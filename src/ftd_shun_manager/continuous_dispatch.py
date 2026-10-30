"""Internal continuous fenced dispatch/read demand; no service activation route."""

from __future__ import annotations

import asyncio
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from .continuous_maintenance import ContinuousMaintenance
from .operation_queue import QueueConflict
from .parallel_synchronizer import ParallelSynchronizer

RECHECK_SECONDS = 1
DEFER_SECONDS = 5
MAX_CONNECT_RETRY_SECONDS = 60
POLICY_READ_MARGIN_SECONDS = 0.001  # SQL authority timestamps have millisecond precision.


@dataclass
class ReadDemand:
    """Advisory monotonic timing, never standing authority or freshness evidence."""

    baseline_due: float
    last_complete: float | None = None
    pending_since: float | None = None

    def request(self, current):
        if self.pending_since is None:
            self.pending_since = current

    def manual_due(self, spacing):
        if self.pending_since is None:
            return None
        return max(self.pending_since, self.last_complete + spacing if self.last_complete is not None else self.pending_since)

    def confirmed(self, started, completed, interval):
        if started > completed or (self.last_complete is not None and completed < self.last_complete):
            raise ValueError('Complete read clock moved backwards.')
        self.last_complete, self.baseline_due = completed, completed + interval
        # A read already in flight may satisfy demand; a completed old read may not.
        if self.pending_since is not None and completed >= self.pending_since:
            self.pending_since = None


class ContinuousDispatcher:
    """Explicit developer lifecycle over one existing ParallelSynchronizer.

    The restricted API can own this component through explicit composition or
    configured observation startup on existing storage. Construction/GET never
    initializes schema, grants/resumes policy or activates the lab.
    """

    def __init__(self, store, agent, *, clock=monotonic, history_retention_days=366,
                 ordered_promotion_enabled=False, **configuration):
        if type(ordered_promotion_enabled) is not bool:
            raise ValueError('Ordered promotion capability must be a literal boolean.')
        if configuration.get('settled_cycles_required', True) is not True:
            raise ValueError('Continuous dispatch cannot disable required cycle settlement.')
        configuration['settled_cycles_required'] = True
        self.runner = ParallelSynchronizer(store, agent, **configuration)
        self.ordered_promotion_enabled = ordered_promotion_enabled
        from .bulk_ordered_promotion import BulkOrderedPromoter

        self.ordered_promoter = BulkOrderedPromoter(store, self.runner.queue)
        self.runner._priority_removals = True
        self.runner._snapshot_callback = self._confirmed
        self.runner._clock = clock
        self.clock = clock
        self._task = None
        self._loop = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._active = {}
        self._demands = {}
        self._enabled = set()
        self._retry_after = {}
        self._connection_failures = {}
        self._last_dispatch = {}
        self._dispatch_sequence = 0
        self._work_hints = set()
        self._policy_scans = {}
        self._error = None
        self._revision = 0
        self._controls = None
        self.instance_id = str(uuid4())
        self._completed_sessions = 0
        self._external_data_revision = 0
        self.maintenance = ContinuousMaintenance(self.runner.queue, enabled=self.runner.enabled,
                                                history_retention_days=history_retention_days,
                                                clock=clock, on_change=self.note_state_change)

    async def start(self):
        if type(self.ordered_promotion_enabled) is not bool:
            raise ValueError('Ordered promotion capability must stay a literal boolean.')
        if not self.runner.enabled or self._task is not None:
            return
        if self.runner._round is not None or self.runner._service_active or self.runner._broken:
            raise QueueConflict('A running/broken coordinator cannot start continuous dispatch.')
        profile, devices = self.runner._configured_devices()
        if self.ordered_promotion_enabled:
            self.ordered_promoter.require_storage()
        current = self.clock()
        for row in profile['devices']:
            self._demands.setdefault(row['device_id'], ReadDemand(current)).baseline_due = current
        self._enabled = {device.id for device in devices}
        self._controls = self._control_state()
        await self.maintenance.start()
        self._stopping = self.runner._stopping = False
        self._error = None
        self.runner._service_active = True
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._serve(), name='ftd-continuous-dispatch')
        self._revision += 1

    def _stop(self):
        if not self._stopping:
            self._revision += 1
        self._stopping = self.runner._stopping = True
        self.maintenance.request_stop()
        for worker in self.runner._workers.values():
            worker._stop_mutations = True
        self._wake.set()

    async def stop(self):
        if self._task is None:
            return
        self._stop()
        task, cancelled = self._task, False
        try:
            while True:
                try:
                    await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    if task.cancelled():
                        self.runner._broken = True
                        raise
                    cancelled = True  # Keep draining despite repeated caller cancellation.
            if cancelled:
                raise asyncio.CancelledError
        finally:
            if task.done():
                self._task = self._loop = None

    def signal_work(self):
        """Wake after an already committed admission/policy change, never admit it."""
        self._notify(self._wake.set)

    def request_policy_scan(self, device_ids):
        """Thread-safe advisory read after committed authority, never grant/claim."""
        eligible = self.runner.configuration['addition_device_ids']
        if (self.runner.configuration['bulk_dispatch_enabled'] is not True
                or type(device_ids) is not frozenset or not 1 <= len(device_ids) <= 10
                or any(type(device) is not int or not 1 <= device <= 65535 for device in device_ids)
                or not device_ids <= eligible):
            raise ValueError('Policy scan requires exact configured bulk-execution device scope.')

        def request():
            if self._task is None or self._task.done() or self._stopping:
                return  # Startup reads cover notifications before start/after shutdown.
            after = self.clock() + POLICY_READ_MARGIN_SECONDS
            for device in device_ids & self._enabled:
                self._policy_scans[device] = max(after, self._policy_scans.get(device, after))
            self._revision += 1
            self._wake.set()

        self._notify(request)

    def _policy_scan_due(self, device):
        after = self._policy_scans.get(device)
        if after is None:
            return None
        last = self._demands[device].last_complete
        spacing = self.runner.configuration['interactive_min_interval_seconds']
        return max(after, last + spacing if last is not None else after)

    def _notify(self, callback):
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(callback)
            except RuntimeError:
                if not loop.is_closed():
                    raise

    def note_activity(self):
        self._notify(self._activity)

    def note_state_change(self):
        """Publish committed API data only; do not admit or request device work."""
        def changed():
            self._external_data_revision += 1
            self._revision += 1

        try:
            owning_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            owning_loop = False
        if self._loop is None or owning_loop:
            changed()
        else:
            self._notify(changed)

    def _activity(self):
        if self._task is not None and not self._stopping:
            self.request_refresh()

    def _control_state(self):
        with self.runner.store._connection() as db:
            db.execute('BEGIN')
            policy = db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()
            executor = db.execute('SELECT mutations_suspended FROM operation_executor WHERE id=1').fetchone()
            desired = db.execute('SELECT restoration_suspended,dispatch_resume_after FROM managed_bulk_registry WHERE id=1').fetchone()
            if policy is None or executor is None or desired is None:
                raise QueueConflict('Existing policy/executor controls are incomplete.')
            return policy[0], executor[0], desired[0], desired[1]

    def request_refresh(self, device_ids=None):
        """Owning-loop coalesced demand; repeated clicks preserve the first deadline."""
        if not self.runner.enabled:
            return self.status()
        if self._task is None or self._task.done() or self._stopping:
            raise QueueConflict('Continuous dispatch is not accepting refresh demand.')
        selected = frozenset(self._enabled) if device_ids is None else device_ids
        if (type(selected) is not frozenset or len(selected) > 10 or any(type(device) is not int for device in selected)
                or not selected <= self._enabled):
            raise ValueError('Refresh demand requires exact enabled configured devices.')
        for device in selected:
            self._demands[device].request(self.clock())
        self._revision += 1
        self._wake.set()
        return self.status()

    def request_activity(self):
        """Owning-loop browser contract; demand acceptance is not read success."""
        self.request_refresh()
        return self.refresh_status()

    def refresh_status(self):
        """Read-only browser projection, without selecting this runtime in the API.

        Deadlines are wall-clock projections of monotonic scheduling, not evidence.
        There is deliberately no invented fleet cycle or arbitrary active device.
        """
        sampled = self.status()
        current, now = self.clock(), datetime.now(UTC)

        def deadline(seconds):
            return None if seconds is None else (now + timedelta(seconds=seconds)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        devices, workers = {}, self.runner._workers
        # Disabled construction/status must not even create a base database.
        if self.runner.enabled and not self.runner.store.path.is_file():
            raise QueueConflict('Refresh status requires existing storage; no database was initialized.')
        inventory = self.runner.store.list_devices() if self.runner.enabled else []
        for device in inventory:
            key, worker = str(device.id), workers.get(device.id)
            timing = sampled['devices'].get(key, {})
            details = deepcopy(worker._devices.get(device.id, {})) if worker else {}
            result = sampled['execution']['devices'].get(key, {})
            last = self._demands.get(device.id)
            stale = last is None or last.last_complete is None or last.baseline_due <= current
            error = details.get('last_error')
            held = result.get('state') in {'held', 'lease_held'}
            if held:
                error = result.get('error') or error or 'Device execution is held; inspect retained lease/operation evidence.'
            state = ('disabled' if not device.enabled else 'error' if error else
                     'refreshing' if timing.get('active') else 'pending' if last is None or last.last_complete is None else
                     'stale' if stale else 'ready')
            devices[key] = {
                'hostname': device.hostname, 'state': state, 'stale': stale or bool(error),
                'last_attempt': details.get('last_attempt'),
                'last_successful_refresh': details.get('last_successful_refresh'),
                'last_error': error, **timing,
                'next_baseline_refresh': deadline(timing.get('baseline_refresh_in_seconds')),
                'next_interactive_refresh': deadline(timing.get('manual_refresh_in_seconds')),
            }
        enabled = [row for row in devices.values() if row['state'] != 'disabled']
        pending = [row for row in enabled if row.get('refresh_pending')]
        active = [row for row in enabled if row.get('active')]
        successes = [row['last_successful_refresh'] for row in enabled if row['last_successful_refresh']]
        failures = [row for row in enabled if row['last_error']]
        due = [row['manual_refresh_in_seconds'] for row in pending]
        state = ('disabled' if not self.runner.enabled else 'checkpoint_pending' if pending and active else
                 'rate_limited' if due and min(due) > 0 else 'queued' if pending else 'idle')
        return {
            'instance_id': self.instance_id, 'refresh_schedule_mode': 'per_device',
            'status_revision': self._revision + sampled['maintenance']['revision'] + sum(worker._status_revision for worker in workers.values()),
            'data_revision': self._external_data_revision + sum(worker._data_revision for worker in workers.values()),
            'cycle_revision': self._completed_sessions, 'cycle_id': None,
            'cycle_started_at': None, 'cycle_completed_at': None,
            'cycle_outcome': 'partial' if failures and successes else 'failed' if failures else
                             'success' if enabled and len(successes) == len(enabled) else 'not_started',
            'server_time': now.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'refresh_enabled': self.runner.enabled and sampled['running'] and not sampled['stopping'] and not sampled['broken'],
            'refresh_in_progress': bool(active), 'active_device_count': len(active),
            'pending_refresh_device_count': len(pending),
            # The oldest confirmed device is conservative; never substitute the
            # newest device or a countdown for a successful fleet observation.
            'last_successful_refresh': min(successes) if enabled and len(successes) == len(enabled) else None,
            'last_attempt': max((row['last_attempt'] for row in enabled if row['last_attempt']), default=None),
            'last_error': sampled['error'] or ('Some device information needs attention.' if failures else None),
            'next_baseline_refresh': min((row['next_baseline_refresh'] for row in enabled if row['next_baseline_refresh']), default=None),
            'next_interactive_refresh': deadline(min(due)) if due else None,
            'baseline_interval_seconds': self.runner.configuration['poll_interval_seconds'],
            'interactive_min_interval_seconds': self.runner.configuration['interactive_min_interval_seconds'],
            'interactive_refresh_state': state, 'priority_refresh_available': False,
            'session_cycles_enabled': True, 'device_cycle': {},
            'device_cycles': sampled['execution']['cycles'], 'devices': devices,
            'bulk_discovery': sampled['execution']['bulk_discovery'],
            'maintenance': sampled['maintenance'],
            'history_retention_days': sampled['maintenance']['history_retention_days'],
            'last_retention_purge': sampled['maintenance']['last_retention_purge'],
            'history_retention_error': sampled['maintenance']['retention_error'],
            'import_execution_enabled': self.runner.configuration['bulk_dispatch_enabled'],
            'queue': self.runner.queue.status(addition_device_ids=self.runner.configuration['addition_device_ids'],
                                            bulk_dispatch_enabled=self.runner.configuration['bulk_dispatch_enabled'])
                     if self.runner.enabled else {'revision': 0, 'counts': {}, 'items': []},
        }

    def _confirmed(self, device, started, completed):
        self._demands[device].confirmed(started, completed, self.runner.configuration['poll_interval_seconds'])
        after = self._policy_scans.get(device)
        if after is not None and started > after:
            del self._policy_scans[device]
        self._revision += 1
        self._wake.set()

    def status(self):
        current = self.clock()
        spacing = self.runner.configuration['interactive_min_interval_seconds']
        devices = {}
        for device, demand in self._demands.items():
            manual_due = demand.manual_due(spacing)
            devices[str(device)] = {
                'enabled': device in self._enabled, 'active': device in self._active,
                'refresh_pending': demand.pending_since is not None,
                'manual_refresh_in_seconds': None if manual_due is None else max(0, manual_due - current),
                'baseline_refresh_in_seconds': max(0, demand.baseline_due - current),
                'retry_in_seconds': max(0, self._retry_after.get(device, 0) - current),
                'connection_retry_attempts': self._connection_failures.get(device, 0),
                'policy_scan_pending': device in self._policy_scans,
            }
        maintenance = self.maintenance.status()
        maintenance_error = maintenance['expiry_error'] or maintenance['retention_error']
        if maintenance['broken']:
            maintenance_error = 'Maintenance stopped unexpectedly; inspect storage and lifecycle before restarting.'
        return deepcopy({'enabled': self.runner.enabled, 'running': self._task is not None and not self._task.done(),
                         'stopping': self._stopping, 'broken': self.runner._broken,
                         'error': self._error or maintenance_error, 'revision': self._revision,
                         'maintenance': maintenance,
                         'devices': devices, 'execution': self.runner.status()})

    def _pending(self, device, *, removals_only=False):
        return self.runner.queue.has_pending(
            device, addition_device_ids=frozenset() if removals_only else self.runner.configuration['addition_device_ids'],
            bulk_dispatch_enabled=self.runner.configuration['bulk_dispatch_enabled'])

    def _nudge(self, device, current):
        demand = self._demands[device]
        due = demand.manual_due(self.runner.configuration['interactive_min_interval_seconds'])
        worker = self.runner._workers.get(device)
        if (due is not None and due <= current and worker is not None and not worker._priority_used
                and worker._device_cycle.get('action') not in {'final_snapshot', 'completed', 'failed'}):
            worker._priority_pending = True
            worker._device_cycle['priority_state'] = 'waiting_for_checkpoint'

    def _completed(self):
        for device, task in tuple(self._active.items()):
            if not task.done():
                continue
            del self._active[device]
            self._completed_sessions += 1
            if task.cancelled():
                self.runner._broken = True
                self._stop()
                continue
            error = task.exception()
            if error is not None:
                self.runner._results[str(device)] = {'state': 'held', 'error': 'Unexpected device worker failure.'}
            result = self.runner._results.get(str(device), {})
            worker = self.runner._workers.get(device)
            phase = worker._device_cycle if worker is not None else {}
            deferred = phase.get('budget_deferred') and phase.get('completed', 0) < phase.get('limit', 16)
            delay = DEFER_SECONDS if result.get('state') != 'success' or deferred else 0
            if result.get('state') == 'retrying':
                # Bounded local retries; never reuse a submitted RPC or lease.
                count = self._connection_failures.get(device, 0) + 1
                self._connection_failures[device] = count
                delay = min(MAX_CONNECT_RETRY_SECONDS, DEFER_SECONDS * 2 ** min(count - 1, 4))
                self._work_hints.add(device)
            else:
                self._connection_failures.pop(device, None)
            self._retry_after[device] = self.clock() + delay
            self._revision += 1

    async def _serve(self):
        try:
            while not self._stopping:
                self._wake.clear()
                self._completed()
                if self._stopping:
                    break
                if self.maintenance.status()['broken']:
                    raise QueueConflict('Maintenance stopped unexpectedly; coordinator stopped without rearming work.')
                profile, devices = self.runner._configured_devices()
                if self.ordered_promotion_enabled is True and self.ordered_promoter.advance(enabled=True):
                    self.note_state_change()
                self._enabled = {device.id for device in devices}
                controls = self._control_state()
                if (controls[0] != self._controls[0] or (self._controls[1] and not controls[1])
                        or (self._controls[2] and not controls[2]) or controls[3] != self._controls[3]):
                    self._work_hints.update(self._enabled)
                self._controls = controls
                current, ready = self.clock(), []
                for device in devices:
                    if device.id in self._active:
                        self._nudge(device.id, current)
                        continue
                    if self._retry_after.get(device.id, 0) > current:
                        continue
                    demand = self._demands[device.id]
                    manual = demand.manual_due(self.runner.configuration['interactive_min_interval_seconds'])
                    manual_due = manual is not None and manual <= current
                    baseline_due = demand.baseline_due <= current
                    policy_due = self._policy_scan_due(device.id)
                    policy_due = policy_due is not None and policy_due < current
                    pending = self._pending(device.id)
                    if not (manual_due or baseline_due or pending or policy_due or device.id in self._work_hints):
                        continue
                    priority = 0 if manual_due else 1 if pending and self._pending(device.id, removals_only=True) else 2 if baseline_due else 3
                    ready.append((priority, self._last_dispatch.get(device.id, -1), device.id, device))
                for _, _, device_id, device in sorted(ready)[:max(0, profile['concurrency'] - len(self._active))]:
                    self._work_hints.discard(device_id)
                    self._dispatch_sequence += 1
                    self._last_dispatch[device_id] = self._dispatch_sequence
                    task = asyncio.create_task(self.runner._visit(device), name=f'ftd-device-{device_id}')
                    self._active[device_id] = task
                    task.add_done_callback(lambda _: self._wake.set())
                    self._revision += 1
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=RECHECK_SECONDS)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            self.runner._broken = True
            raise
        except (ValueError, OSError, sqlite3.Error) as error:
            self._error = str(error)
        finally:
            self._stop()
            # Ordinary stop never cancels these tasks or their to_thread RPCs.
            drain = asyncio.gather(*self._active.values(), return_exceptions=True)
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    self.runner._broken = True
                    if drain.cancelled():
                        break
            self._completed()
            try:
                await self.maintenance.stop()
            finally:
                if self.maintenance.status()['broken']:
                    self.runner._broken = True
                self.runner._service_active = False
