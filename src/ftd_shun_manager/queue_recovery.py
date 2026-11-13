"""Read-only recovery guidance; never release a fence or claim offline quiescence."""

from datetime import UTC, datetime

from .bulk_policy import _state
from .device_reconciliation import _review


def report(store, *, now=None):
    with store._connection() as db:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_device_executors'").fetchone():
            return {'supported': False, 'devices': [], 'reason': 'This runtime has no fenced recovery profile.'}
        _state(db)
        rows = db.execute('''SELECT d.id,d.hostname,e.state,e.epoch FROM devices d
            JOIN managed_bulk_device_executors e ON e.device_id=d.id ORDER BY d.id LIMIT 11''').fetchall()
        if len(rows) > 10:
            raise ValueError('Recovery guidance requires a bounded known inventory.')
        devices = []
        for row in rows:
            item = dict(row)
            item.update(eligible=False, extended_v6=False, claims=0, unknown=0, reason=None)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_pending_execution'").fetchone() and row['state'] != 'IDLE':
                try:
                    from .pending_offline import _scope, present
                    classified = present(db) and db.execute(
                        'SELECT 1 FROM managed_bulk_pending_classifications WHERE device_id=? AND epoch=?',
                        (row['id'], row['epoch'])).fetchone() is not None
                    if row['state'] == 'ATTENTION' and classified:
                        reviewed = _review(db, store, row['id'], now or datetime.now(UTC), reconcile=True, pending_v7=True)
                        count = len(reviewed['claims'])
                        unknown = sum(c['state'] == 'UNVERIFIED' for c in reviewed['claims'])
                        phase = 'reconcile'
                    else:
                        _, jobs = _scope(db, row['id'], now or datetime.now(UTC))
                        count, unknown = len(jobs), sum(j['state'] in ('RUNNING', 'UNVERIFIED') for j in jobs)
                        phase = 'classify'
                    item.update(pending_v7_phase=phase, claims=count, unknown=unknown,
                                reason='A separate stopped-executor v7 recovery review is available. Original outcomes stay unknown.')
                except ValueError as error:
                    item['reason'] = str(error)
                item['lab_assistance'] = False  # Never advertise the verified-v6 host helper for this profile.
                devices.append(item)
                continue
            if row['state'] == 'ATTENTION':
                # Inspect both literal existing contracts; this does not select an
                # execution profile, initialize storage or authorize any recovery.
                for extended in (False, True):
                    try:
                        reviewed = _review(db, store, row['id'], now or datetime.now(UTC), reconcile=True, extended_v6=extended)
                    except ValueError as error:
                        if not extended:
                            item['reason'] = str(error)
                        continue
                    item.update(eligible=True, extended_v6=extended, claims=len(reviewed['claims']),
                                unknown=sum(c['state'] == 'UNVERIFIED' for c in reviewed['claims']), reason=None)
                    break
            else:
                item['reason'] = 'No expired held session needs reconciliation.'
            item['lab_assistance'] = item['eligible'] and len(rows) == 1 and row['hostname'] == 'fpr1010-lab'
            devices.append(item)
        return {'supported': True, 'devices': devices, 'read_only': True,
                'execution_available': False, 'host_assistance_required': True}
