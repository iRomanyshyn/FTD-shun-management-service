"""Single owning-service maintenance loop; no migration or device authority."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from time import monotonic

from .operation_queue import QueueConflict, stamp

EXPIRY_SECONDS = 5
RETENTION_SECONDS = 24 * 3600
FAILURE_SECONDS = 60


class ContinuousMaintenance:
    """Serialize ordinary expiry and evidence-aware pruning, never device work.

    The application must have one lifecycle owner. SQLite transactions still
    protect against races with device workers; this is not a distributed leader.
    """

    def __init__(self, queue, *, enabled=False, history_retention_days=366,
                 clock=monotonic, on_change=None):
        if type(enabled) is not bool or type(history_retention_days) is not int or not 1 <= history_retention_days <= 3653:
            raise ValueError('Literal maintenance enablement and 1..3653 retention days are required.')
        self.queue, self.enabled = queue, enabled
        self.history_retention_days, self.clock = history_retention_days, clock
        self.on_change = on_change
        self._task = self._inflight = None
        self._wake = asyncio.Event()
        self._stopping = self._broken = False
        self._next_expiry = self._next_retention = None
        self._revision = 0
        self._details = {'phase': 'idle', 'last_expiry_attempt': None, 'last_expiry_success': None,
                         'last_retention_attempt': None, 'last_retention_purge': None,
                         'expiry_error': None, 'retention_error': None}

    async def start(self):
        if not self.enabled or self._task is not None:
            return
        if self._broken:
            raise QueueConflict('Forcibly cancelled maintenance must not be restarted in-process.')
        if not self.queue.store.path.is_file():
            raise QueueConflict('Maintenance requires existing storage; no database was initialized.')
        self._stopping = False
        self._next_expiry = self.clock()
        if self._next_retention is None:
            self._next_retention = self.clock()
        self._task = asyncio.create_task(self._run(), name='ftd-continuous-maintenance')
        self._revision += 1

    def request_stop(self):
        self._stopping = True
        self._wake.set()

    async def stop(self):
        if self._task is None:
            return
        self.request_stop()
        task, cancelled = self._task, False
        try:
            while True:
                try:
                    await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    if task.cancelled():
                        self._broken = True
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        finally:
            if task.done():
                self._task = None

    def status(self):
        current = self.clock()
        return deepcopy({**self._details, 'enabled': self.enabled,
                         'running': self._task is not None and not self._task.done(),
                         'stopping': self._stopping, 'broken': self._broken,
                         'revision': self._revision, 'history_retention_days': self.history_retention_days,
                         'next_expiry_in_seconds': None if self._next_expiry is None else max(0, self._next_expiry - current),
                         'next_retention_in_seconds': None if self._next_retention is None else max(0, self._next_retention - current)})

    def _phase(self, value):
        self._details['phase'] = value
        self._revision += 1

    def _queue_change(self, function, *args):
        def revision():
            with self.queue.store._connection() as db:
                return db.execute('SELECT revision FROM operation_executor WHERE id=1').fetchone()[0]

        before = revision()
        function(*args)
        return revision() != before

    async def _call(self, function, *args, **kwargs):
        # Cancelling an await never cancels the synchronous SQLite operation.
        task = self._inflight = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        cancelled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    cancelled = self._broken = True
                    self.request_stop()
                    if task.cancelled():
                        raise  # Forced shutdown cannot prove the thread stopped.
            if cancelled:
                raise asyncio.CancelledError
            return result
        finally:
            self._inflight = None

    def _changed(self, changed):
        if changed and self.on_change is not None:
            self.on_change()

    def _failure(self, kind, error):
        # No SQL payload, job contents, credentials or device output in logs.
        reason = f'{type(error).__name__}: {str(error)[:500]}'
        self._details[kind + '_error'] = reason
        self._revision += 1
        print(json.dumps({'event': 'maintenance.' + kind + '.failed', 'reason': reason}, sort_keys=True), flush=True)

    async def _expire(self):
        self._phase('expiring_requests')
        self._details['last_expiry_attempt'] = stamp(self.queue._now())
        try:
            changed = await self._call(self._queue_change, self.queue.expire_requests)
        except (ValueError, OSError, sqlite3.Error) as error:
            self._failure('expiry', error)
            self._next_expiry = self.clock() + FAILURE_SECONDS
        else:
            self._details['last_expiry_success'] = stamp(self.queue._now())
            self._details['expiry_error'] = None
            self._next_expiry = self.clock() + EXPIRY_SECONDS
            self._changed(changed)

    async def _retain(self):
        self._details['last_retention_attempt'] = stamp(self.queue._now())
        try:
            self._phase('pruning_queue')
            changed = await self._call(self._queue_change, self.queue.prune_completed, self.history_retention_days)
            self._changed(changed)
            if self._stopping:
                return  # Do not start another stage after stop; no false success.
            self._phase('pruning_history')
            result = await self._call(self.queue.store.prune_expired_history, self.history_retention_days,
                                      reference_time=self.queue._now())
            self._changed(any(result[field] for field in ('events_deleted', 'inactive_state_deleted', 'import_origins_deleted')))
        except (ValueError, OSError, sqlite3.Error) as error:
            self._failure('retention', error)
            self._next_retention = self.clock() + FAILURE_SECONDS
        else:
            self._details['last_retention_purge'] = stamp(self.queue._now())
            self._details['retention_error'] = None
            self._next_retention = self.clock() + RETENTION_SECONDS

    async def _run(self):
        try:
            while not self._stopping:
                self._wake.clear()
                if self.clock() >= self._next_expiry:
                    await self._expire()
                if not self._stopping and self.clock() >= self._next_retention:
                    await self._retain()
                self._phase('idle')
                if not self._stopping:
                    delay = max(0, min(self._next_expiry, self._next_retention) - self.clock())
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=min(EXPIRY_SECONDS, delay))
                    except TimeoutError:
                        pass
        except BaseException:
            self._broken = True
            self.request_stop()
            raise
        finally:
            self._phase('stopped')
