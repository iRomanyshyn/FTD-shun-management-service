"""Explicit continuous deferred reads/retry scheduling, never startup or authority."""

from datetime import datetime, timedelta

from .bulk_policy import BulkUnavailable
from .continuous_dispatch import ContinuousDispatcher
from .deferred_worker import DeferredParallelSynchronizer
from .device_leases import device_uncertain
from .import_preparations import _stamp
from .managed_addition_controls import paused_for
from .operation_queue import QueueConflict
from .pending_execution import PendingExecution
from .pending_retries import retry_candidates, retry_window
from .safety import mutations_suspended


class DeferredContinuousDispatcher(ContinuousDispatcher):
    """Default-disabled composition on the exact prepared deferred profile.

    Scheduling samples are advisory. Timer expiry requests a new complete read;
    the worker, never this selector, validates permission and creates fresh jobs.
    """

    _runner_type = DeferredParallelSynchronizer

    def __init__(self, *args, ordered_promotion_enabled=False, **kwargs):
        super().__init__(*args, ordered_promotion_enabled=ordered_promotion_enabled, **kwargs)
        self._deferred_samples = {}
        self._deferred_cursors = {}

    async def start(self):
        if self.runner.enabled and not self.runner.store.path.is_file():
            raise BulkUnavailable('Existing explicit deferred storage is required; nothing was initialized.')
        await super().start()

    def _read_ready(self, device, current):
        now = self.runner.queue._now()
        with self.runner.store._connection() as db:
            db.execute('BEGIN')
            PendingExecution._profile(db)
            pending = db.execute('''SELECT COUNT(*),MAX(s.settled_at) FROM managed_bulk_pending_members m
                JOIN managed_bulk_pending_sessions s ON s.id=m.session_id
                WHERE s.device_id=? AND NOT EXISTS(SELECT 1 FROM managed_bulk_pending_reads r WHERE r.session_id=s.id)''',
                (device,)).fetchone()
            held = device_uncertain(db, device)
            paused = mutations_suspended(db) or bool(db.execute(
                'SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0])
            due, checked, operator_paused = None, 0, 0
            cursor = self._deferred_cursors.get(device, b'')
            if device in self.runner.configuration['addition_device_ids'] and not held and not paused:
                rows = retry_candidates(db, device, cursor)
                for row in rows[:64]:
                    checked += 1
                    cursor = row['ip']
                    if paused_for(db, row):
                        operator_paused += 1
                        continue  # Paused retry timers must not create extra SSH visits.
                    try:
                        eligible = retry_window(db, row, now)[3]
                    except QueueConflict:
                        continue  # Exhausted retained capacity never grants another write.
                    due = min(due, eligible) if due else eligible
                if checked == len(rows):
                    cursor = b''
            not_before = (datetime.fromisoformat(pending[1]) + timedelta(milliseconds=1)) if pending[1] else None
            self._deferred_cursors[device] = cursor
            self._deferred_samples[str(device)] = {
                'awaiting_confirmation': pending[0], 'retry_at': due,
                'retry_in_seconds': max(0, (datetime.fromisoformat(due) - now).total_seconds()) if due else None,
                'confirmation_in_seconds': max(0, (not_before - now).total_seconds()) if not_before else None,
                'confirmation_not_before': _stamp(not_before) if not_before else None,
                'checked_retry_candidates': checked, 'counts_are_sampled': True,
                'operator_paused_candidates': operator_paused,
                'held': held, 'mutations_paused': paused,
                'sampled_at': _stamp(now), 'sampled_monotonic': current,
            }
        # Read-only confirmation remains available while mutations are paused.
        # Ensure the new read starts strictly after the original ms-precision
        # settlement barrier; never sleep inside an SSH session for this margin.
        return not not_before or held or now >= not_before

    def _scheduled_read_due(self, device, current):
        sample = self._deferred_samples.get(str(device), {})
        return not sample.get('held', True) and (sample.get('awaiting_confirmation', 0) > 0
            or sample.get('retry_in_seconds') == 0)

    def refresh_status(self, **kwargs):
        result = super().refresh_status(**kwargs)
        result['deferred_confirmation'] = self._presentation()
        return result

    def _presentation(self):
        current = self.clock()
        return {key: {**{field: value for field, value in row.items() if field != 'sampled_monotonic'},
            'retry_in_seconds': max(0, row['retry_in_seconds'] - max(0, current - row['sampled_monotonic']))
                if row['retry_in_seconds'] is not None else None,
            'confirmation_in_seconds': max(0, row['confirmation_in_seconds'] - max(0, current - row['sampled_monotonic']))
                if row['confirmation_in_seconds'] is not None else None}
            for key, row in self._deferred_samples.items() if int(key) in self._enabled}

    def status(self):
        return {**super().status(), 'deferred_confirmation': self._presentation()}
