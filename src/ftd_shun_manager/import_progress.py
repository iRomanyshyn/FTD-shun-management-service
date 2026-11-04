"""Whole-import initial application, not standing authority or creation proof."""

from .bulk_intent import decode_bulk_descriptor
from .bulk_policy import BulkUnavailable

_COUNTS = '''WITH attempts AS (
    SELECT authorization_request_id,device_id,ip,intent_id,generation,
        MAX(state='VERIFIED') AS verified,MAX(state='NOOP') AS noop,
        MAX(state='UNVERIFIED' AND {unresolved}) AS uncertain,MAX(state='FAILED') AS failed,
        MAX(state='RUNNING') AS running,MAX(state='QUEUED') AS queued
    FROM managed_bulk_attempts GROUP BY authorization_request_id,device_id,ip,intent_id,generation
), scope AS (
    SELECT m.request_id,
        CASE WHEN m.classification='PROPOSE_ADOPT' THEN 'adopted'
             WHEN m.classification='ALREADY_MANAGED' THEN 'unchanged'
             WHEN a.verified=1 THEN 'verified'
             WHEN a.noop=1 THEN 'noop'
             WHEN t.intent_id IS NULL THEN 'unknown'
             WHEN t.intent_id!=m.intent_id OR t.generation!=m.generation
                 OR t.authorization_request_id!=m.authorization_request_id THEN 'superseded'
             WHEN a.uncertain=1 THEN 'unverified'
             WHEN a.failed=1 THEN 'failed'
             WHEN t.enabled=0 THEN 'stopped'
             WHEN a.running=1 THEN 'running'
             WHEN a.queued=1 THEN 'queued'
             WHEN EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=m.device_id AND s.ip=m.ip AND s.active=1)
                 THEN 'present'
             ELSE 'pending' END AS outcome
    FROM managed_bulk_members m
    LEFT JOIN managed_shun_targets t ON t.device_id=m.device_id AND t.ip=m.ip
    LEFT JOIN attempts a ON a.authorization_request_id=m.authorization_request_id
        AND a.device_id=m.device_id AND a.ip=m.ip AND a.intent_id=m.intent_id AND a.generation=m.generation
    WHERE m.classification!='EXCLUDED_PROTECTED'
) SELECT request_id,outcome,COUNT(*) FROM scope GROUP BY request_id,outcome'''


def import_progress(db):
    """Read within the caller's already validated transaction, never initialize.

    Retained attempt results survive job pruning. Current observation is labelled
    separately; only the existing cancellation review can revoke an import.
    """
    if not db.in_transaction:
        raise ValueError('Import progress requires a consistent validated snapshot.')
    from .device_reconciliation import unresolved

    counts = {}
    for key, outcome, count in db.execute(_COUNTS.format(unresolved=unresolved(db, 'job_id'))):
        counts.setdefault(key, {})[outcome] = count
    tasks = []
    for row in db.execute('''SELECT m.id,m.payload_digest,m.accepted_count,m.pair_count,
            r.payload_json,r.actor_subject,r.actor_display_name,r.requested_at,c.import_id AS cancelled
        FROM managed_bulk_manifests m JOIN managed_shun_requests r ON r.id=m.id
        LEFT JOIN managed_bulk_cancellations c ON c.import_id=m.id
        ORDER BY r.requested_at DESC,m.id'''):
        descriptor = decode_bulk_descriptor(row['payload_json'], row['payload_digest'])
        states = counts.get(row['id'], {})
        if (sum(states.values()) != row['accepted_count']
                or descriptor['operation_id'] != row['id']
                or descriptor['manifest']['accepted_count'] != row['accepted_count']
                or descriptor['manifest']['pair_count'] != row['pair_count']):
            raise BulkUnavailable('Complete original import progress is unavailable.')
        outstanding = sum(states.get(state, 0) for state in ('pending', 'queued', 'running'))
        attention = sum(states.get(state, 0) for state in ('failed', 'unverified', 'unknown'))
        tasks.append({'id': row['id'], 'label': descriptor['label'],
            'actor_subject': row['actor_subject'], 'actor_display_name': row['actor_display_name'],
            'requested_at': row['requested_at'], 'total': row['accepted_count'],
            'processed': row['accepted_count'] - outstanding, 'counts': states,
            'outstanding': outstanding, 'attention': attention,
            'active': bool(outstanding or attention), 'cancelled': row['cancelled'] is not None,
            'cancellation_available': bool(outstanding and row['cancelled'] is None),
            'excluded_protected': row['pair_count'] - row['accepted_count']})
    active = [task for task in tasks if task['active']]
    recent = [task for task in tasks if not task['active']][:3]
    return {'tasks': (active + recent)[:20], 'active_tasks': len(active),
            'total_tasks': len(tasks), 'limit': 20, 'read_only': True}
