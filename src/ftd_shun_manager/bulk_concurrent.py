"""Read-only admission fences inside the caller's whole-policy transaction."""

from .bulk_attempts import validate_held_jobs
from .bulk_policy import BulkUnavailable, _state
from .bulk_waits import validate_pending
from .device_leases import present
from .import_preparations import _stamp
from .managed_shuns import ManagedConflict


def check_admission(db, plan_id, device_ids, expected_suspended, now):
    state = _state(db)
    if state is None or not present(db):
        raise BulkUnavailable('Concurrent standing admission requires exact existing fenced-device storage.')
    if bool(state['restoration_suspended']) is not expected_suspended:
        raise ManagedConflict('Reviewed desired-execution suspension changed; no new policy was admitted.')
    validate_held_jobs(db)
    validate_pending(db)  # Preserve missing/incompatible-writer evidence, even outside this scope.
    timestamp = _stamp(now)
    for device in device_ids:
        fence = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=?', (device,)).fetchone()
        if (fence is None or fence['state'] not in {'IDLE', 'LEASED'} or fence['updated_at'] > timestamp
                or (fence['state'] == 'LEASED' and fence['lease_until'] <= timestamp)):
            raise ManagedConflict('Selected device fence is absent, expired, ahead of the clock or needs attention.')
    marks = ','.join('?' for _ in device_ids)
    if (db.execute("SELECT 1 FROM operation_jobs WHERE device_id IN (" + marks + ") AND state IN ('UNVERIFIED','RECONCILED_ABSENT') LIMIT 1", device_ids).fetchone()
            or db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id IN (" + marks + ") AND state='UNVERIFIED' LIMIT 1", device_ids).fetchone()):
        raise ManagedConflict('Selected device has retained uncertainty; admission cannot resolve or bypass it.')
    queries = (
        """SELECT 1 FROM import_preparation_targets p JOIN operation_jobs j
            ON j.device_id=p.device_id AND j.ip=p.ip WHERE p.plan_id=? AND p.classification!='EXCLUDED_PROTECTED'
            AND (j.state IN ('QUEUED','RUNNING','UNVERIFIED','RECONCILED_ABSENT') OR
                (j.action='ADD' AND NOT EXISTS(SELECT 1 FROM managed_bulk_attempts a WHERE a.job_id=j.id))) LIMIT 1""",
        """SELECT 1 FROM import_preparation_targets p JOIN managed_bulk_attempts a
            ON a.device_id=p.device_id AND a.ip=p.ip WHERE p.plan_id=? AND p.classification!='EXCLUDED_PROTECTED'
            AND a.state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED') LIMIT 1""",
        """SELECT 1 FROM import_preparation_targets p JOIN managed_bulk_cancellation_members m
            ON m.device_id=p.device_id AND m.ip=p.ip WHERE p.plan_id=? AND p.classification!='EXCLUDED_PROTECTED'
            AND m.state='WAITING_OUTCOME' AND NOT EXISTS(SELECT 1 FROM managed_bulk_wait_results r
                WHERE r.import_id=m.import_id AND r.device_id=m.device_id AND r.ip=m.ip) LIMIT 1""",
    )
    if any(db.execute(query, (plan_id,)).fetchone() for query in queries):
        raise ManagedConflict('An accepted pair has pending, failed, uncertain or unattributed work; whole scope refused.')
    from .bulk_ordered_promotion import released_filter
    from .bulk_ordered_waits import present as ordered_present
    from .bulk_ordered_waits import validate_held_predecessors

    if ordered_present(db):
        validate_held_predecessors(db)
        if db.execute('''SELECT 1 FROM import_preparation_targets p JOIN managed_bulk_ordered_members m
            ON m.device_id=p.device_id AND m.ip=p.ip JOIN managed_bulk_ordered_roots r ON r.id=m.root_id
            WHERE p.plan_id=? AND p.classification!='EXCLUDED_PROTECTED' AND r.state='WAITING_ADD' '''
                + released_filter(db) + ' LIMIT 1', (plan_id,)).fetchone():
            raise ManagedConflict('An accepted pair is held by original ordered cleanup; no new authority.')
