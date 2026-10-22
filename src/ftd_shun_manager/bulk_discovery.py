"""Bounded version-2 refill under the existing lease; no migration or executor."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta
from ipaddress import IPv4Address
from threading import RLock

from .bulk_dispatch import BulkCandidate, BulkDispatch, _lease, _snapshot, authority_valid, present
from .bulk_policy import BulkUnavailable, _state
from .import_preparations import _stamp
from .operation_queue import QueueConflict, QueueFull
from .safety import mutations_suspended
from .schema import schema_connection

ADMISSION_LIMIT = 16
CHECK_LIMIT = 64
DEVICE_WINDOW = 16


class BulkDiscovery:
    def __init__(self, store, queue, *, enabled=False, addition_device_ids=frozenset()):
        if (type(enabled) is not bool or type(addition_device_ids) is not frozenset
                or len(addition_device_ids) > 10
                or any(type(device) is not int or not 1 <= device <= 65535 for device in addition_device_ids)):
            raise ValueError('Bulk refill requires a boolean capability and at most ten literal device profiles.')
        self.store, self.queue = store, queue
        self.enabled, self.addition_device_ids = enabled, addition_device_ids
        self.source = BulkDispatch(store, queue)
        self._lock = RLock()
        self._cursors = {}
        self.begin_cycle()

    def begin_cycle(self):
        with self._lock:
            self.remaining, self.checked = ADMISSION_LIMIT, 0
            self.devices = {}

    def status(self):
        with self._lock:
            counts = Counter()
            for device in self.devices.values():
                counts.update(device['counts'])
            return deepcopy({'enabled': self.enabled, 'admitted_this_cycle': ADMISSION_LIMIT - self.remaining,
                             'admission_limit': ADMISSION_LIMIT, 'checked_this_cycle': self.checked,
                             'check_limit': CHECK_LIMIT, 'device_window': DEVICE_WINDOW,
                             'counts_are_sampled_checks': True, 'counts': dict(counts), 'devices': self.devices})

    def ordered_devices(self, devices):
        if not self.enabled or not self.addition_device_ids:
            return devices
        with self.store._connection() as db:
            db.execute('BEGIN')
            if _state(db) is None or not present(db):
                raise BulkUnavailable('Bulk refill requires the exact existing dispatch profile.')
            last = dict(db.execute('SELECT device_id,MAX(requested_at) FROM managed_bulk_attempts WHERE device_id IN ('
                                   + ','.join('?' for _ in self.addition_device_ids) + ') GROUP BY device_id',
                                   tuple(sorted(self.addition_device_ids))))
        return sorted(devices, key=lambda device: (device.id not in self.addition_device_ids,
                                                   last.get(device.id, ''), device.id))

    def _report(self, device, snapshot, counts, state):
        self.devices[str(device)] = {'snapshot_at': _stamp(snapshot.completed_at), 'state': state,
                                     'counts': dict(counts)}

    def discover(self, snapshot, owner):
        if not self.enabled:
            return 0
        started, completed = _snapshot(snapshot)
        current = self.queue._now()
        if not started <= completed <= _stamp(current) or current - snapshot.started_at > timedelta(seconds=120):
            raise ValueError('Bulk discovery requires fresh complete read evidence.')
        if snapshot.device_id not in self.addition_device_ids:
            return 0
        with self._lock:
            counts, admitted, checked = Counter(), 0, 0
            with schema_connection(self.store) as db:
                state = _state(db)
                if state is None or not present(db):
                    raise BulkUnavailable('Bulk refill requires the exact existing dispatch profile.')
                _lease(db, self.queue, owner, snapshot.device_id)
                hold = 'suspended' if state['restoration_suspended'] else 'recovery_pause' if mutations_suspended(db) else None
                if hold is None and (db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND state IN ('UNVERIFIED','RECONCILED_ABSENT')",
                                               (snapshot.device_id,)).fetchone()
                                     or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND state='UNVERIFIED'",
                                                   (snapshot.device_id,)).fetchone()):
                    hold = 'device_uncertain'
                if hold is None and (not self.remaining or self.checked >= CHECK_LIMIT):
                    hold = 'cycle_budget'
                pending = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE device_id=? AND state IN ('QUEUED','RUNNING')",
                                     (snapshot.device_id,)).fetchone()[0]
                room = min(self.remaining, DEVICE_WINDOW - pending)
                if hold is None and room <= 0:
                    hold = 'window_full'
                if hold:
                    self._report(snapshot.device_id, snapshot, counts, hold)
                    return 0
                protected_revision = db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0]
                barrier = db.execute('SELECT dispatch_resume_after FROM managed_bulk_registry WHERE id=1').fetchone()[0]
                epoch = (state['revision'], protected_revision, barrier)
                old_epoch, cursor = self._cursors.get(snapshot.device_id, (None, b''))
                if epoch != old_epoch:
                    cursor = b''
                rows = db.execute('''SELECT * FROM managed_shun_targets WHERE device_id=? AND enabled=1
                    AND ip>? ORDER BY ip LIMIT ?''', (snapshot.device_id, cursor, CHECK_LIMIT - self.checked + 1)).fetchall()
                candidates = []
                for row in rows[:CHECK_LIMIT - self.checked]:
                    if len(candidates) >= room:
                        break
                    checked += 1
                    cursor = row['ip']
                    ip = IPv4Address(row['ip'])
                    # Placeholder identities only for eligibility exclusions, never written or used as authority.
                    attempt = {**dict(row), 'id': '', 'job_id': '', 'target_revision': row['revision'],
                               'snapshot_started_at': started, 'snapshot_at': completed, 'requested_at': _stamp(current)}
                    if ip in snapshot.present_ips:
                        reason = 'present'
                    elif db.execute('SELECT 1 FROM managed_bulk_attempts WHERE intent_id=? AND snapshot_id=?',
                                    (row['intent_id'], snapshot.id)).fetchone():
                        reason = 'snapshot_used'
                    elif not authority_valid(db, attempt, self.queue._now()):
                        reason = 'held'
                    else:
                        history = db.execute('''SELECT MAX(requested_at),SUM(requested_at>?) FROM managed_bulk_attempts
                            WHERE device_id=? AND ip=?''', (_stamp(current - timedelta(hours=1)), snapshot.device_id, row['ip'])).fetchone()
                        reason = ('backoff' if history[0] is not None and history[0] > _stamp(current - timedelta(seconds=300))
                                  else 'churn_limit' if (history[1] or 0) >= 3 else 'eligible')
                    counts[reason] += 1
                    if reason == 'eligible':
                        candidates.append(BulkCandidate(snapshot.device_id, ip, row['intent_id'], row['generation'],
                                                        row['authorization_request_id'], row['revision']))
                # Wrap only after exhausting the selected page, not after breaking at the admission window.
                if checked == len(rows):
                    cursor = b''
                report_state = 'scanned'
                if candidates:
                    try:
                        result = self.source.admit(snapshot, tuple(candidates), owner, state['revision'], protected_revision,
                                                   enabled=True, addition_device_ids=self.addition_device_ids, connection=db)
                    except QueueFull:
                        report_state = 'capacity'
                    else:
                        admitted = sum(not item['replayed'] for item in result['attempts'])
                        report_state = 'admitted'
                _lease(db, self.queue, owner, snapshot.device_id)
                if self.queue._now() - snapshot.started_at > timedelta(seconds=120):
                    raise QueueConflict('Bulk evidence expired during discovery.')
            # Scan positions/budgets are hints only, published after the write commits.
            self._cursors[snapshot.device_id] = (epoch, cursor)
            self.remaining -= admitted
            self.checked += checked
            self._report(snapshot.device_id, snapshot, counts, report_state)
            return admitted
