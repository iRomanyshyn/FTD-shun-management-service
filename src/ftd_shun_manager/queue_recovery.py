"""Read-only recovery guidance; never release a fence or claim offline quiescence."""

from datetime import UTC, datetime

from .bulk_policy import _state
from .device_reconciliation import _review
from .import_unblocks import ActiveImportCleanup


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
                    item['import_cleanup_blocked']=isinstance(error,ActiveImportCleanup)
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
                        if isinstance(error,ActiveImportCleanup):item['import_cleanup_blocked']=True
                        continue
                    item.update(eligible=True, extended_v6=extended, claims=len(reviewed['claims']),
                                unknown=sum(c['state'] == 'UNVERIFIED' for c in reviewed['claims']), reason=None)
                    break
            else:
                item['reason'] = 'No expired held session needs reconciliation.'
            item['lab_assistance'] = item['eligible'] and len(rows) == 1 and row['hostname'] == 'fpr1010-lab'
            devices.append(item)
        cleanup_tasks=[]
        from .import_unblocks import present as cleanup_present
        if any(item.get('import_cleanup_blocked') for item in devices) and cleanup_present(db):
            from .import_ownership import import_labels

            roots=db.execute("SELECT id,import_id FROM managed_import_unblocks WHERE state='ACTIVE' ORDER BY requested_at,id LIMIT 20").fetchall()
            labels=import_labels(db,[root['import_id'] for root in roots])
            cleanup_tasks=[{'id':root['id'],'label':labels[root['import_id']]['label']} for root in roots]
        return {'supported': True, 'devices': devices, 'read_only': True, 'import_cleanup_tasks':cleanup_tasks,
                'execution_available': False, 'host_assistance_required': True}
