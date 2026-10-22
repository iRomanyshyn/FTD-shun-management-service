"""Bounded local work preparation/progress, never queue admission or execution."""

from ipaddress import IPv4Address

from .bulk_cancellations import authorized_root
from .bulk_intent import decode_bulk_descriptor
from .bulk_policy import BulkPolicies, BulkUnavailable, _state
from .managed_shuns import ManagedConflict
from .safety import mutations_suspended

_VIEW = '''WITH scope AS (
    SELECT m.device_id,m.ip,m.classification,m.intent_id,m.generation,m.authorization_request_id,
        t.revision AS target_revision,d.hostname,
        CASE WHEN t.intent_id IS NULL THEN 'MISSING_POLICY'
             WHEN t.intent_id!=m.intent_id OR t.generation!=m.generation
                 OR t.authorization_request_id!=m.authorization_request_id THEN 'SUPERSEDED'
             WHEN t.enabled=0 THEN 'STOPPED'
             WHEN EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=m.ip AND p.enabled=1) THEN 'PROTECTED'
             WHEN d.enabled=0 THEN 'DEVICE_DISABLED'
             WHEN EXISTS(SELECT 1 FROM operation_jobs j WHERE j.device_id=m.device_id AND j.ip=m.ip
                 AND (j.action='ADD' OR j.state='UNVERIFIED')) THEN 'EVIDENCE_REVIEW'
             WHEN EXISTS(SELECT 1 FROM operation_jobs j WHERE j.device_id=m.device_id AND j.ip=m.ip
                 AND j.state IN ('QUEUED','RUNNING')) THEN 'WORK_PENDING'
             WHEN EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=m.device_id AND s.ip=m.ip AND s.active=1)
                 THEN 'OBSERVED_PRESENT'
             ELSE 'MISSING_CANDIDATE' END AS disposition
    FROM managed_bulk_members m LEFT JOIN managed_shun_targets t ON t.device_id=m.device_id AND t.ip=m.ip
    LEFT JOIN devices d ON d.id=m.device_id WHERE m.request_id=? AND m.classification!='EXCLUDED_PROTECTED') '''


class BulkWorkPlans:
    def __init__(self, store):
        self.store = store
        self.policies = BulkPolicies(store)

    @staticmethod
    def _counts(db, key):
        counts = dict(db.execute(_VIEW + 'SELECT disposition,COUNT(*) FROM scope GROUP BY disposition', (key,)))
        if counts.get('MISSING_POLICY'):
            raise BulkUnavailable('Original effective policy is missing; progress cannot infer completion.')
        return counts

    def progress(self, key, subject, roles):
        with self.store._connection() as db:
            db.execute('BEGIN')
            root = authorized_root(db, self.policies, key, subject, roles)
            counts = self._counts(db, key)
            return {'operation_id': key, 'intent_format': 2, 'accepted_count': root['accepted_count'],
                'classification_counts': decode_bulk_descriptor(root['payload_json'], root['payload_digest'])['manifest']['classification_counts'],
                'counts': counts, **self._metadata(db), 'read_only': True, 'can_execute': False,
                'observations_are_execution_receipts': False}

    @staticmethod
    def _metadata(db):
        return {'managed_revision': _state(db)['revision'],
                'protected_revision': db.execute('SELECT revision FROM protected_policy WHERE id=1').fetchone()[0],
                'mutations_suspended': mutations_suspended(db), 'restoration_suspended': True,
                'execution_available': False}

    def portion(self, key, subject, roles, *, limit=16, after=None, revision=None, protected_revision=None):
        """A candidate page only; no reservation, durable cursor or fresh-read proof."""
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError('Prepare at most 16 candidate pairs per portion.')
        for value in (revision, protected_revision):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Use literal nonnegative review revisions.')
        if after is not None and (type(after) is not tuple or len(after) != 2 or type(after[0]) is not int
                or not 1 <= after[0] <= 65535 or type(after[1]) is not IPv4Address
                or revision is None or protected_revision is None):
            raise ValueError('A keyset cursor requires literal device/IPv4 and both reviewed revisions.')
        with self.store._connection() as db:
            db.execute('BEGIN')
            authorized_root(db, self.policies, key, subject, roles)
            metadata = self._metadata(db)
            if ((revision is not None and revision != metadata['managed_revision'])
                    or (protected_revision is not None and protected_revision != metadata['protected_revision'])):
                raise ManagedConflict('Policy changed; restart work preparation from the beginning.')
            counts = self._counts(db, key)
            cursor = (after[0], after[1].packed) if after else (0, b'\0\0\0\0')
            rows = db.execute(_VIEW + '''SELECT * FROM scope WHERE disposition='MISSING_CANDIDATE'
                AND (device_id,ip)>(?,?) ORDER BY device_id,ip LIMIT ?''', (key, *cursor, limit + 1)).fetchall()
            page = rows[:limit]
            next_after = (page[-1]['device_id'], IPv4Address(page[-1]['ip'])) if len(rows) > limit else None
            return {'operation_id': key, **metadata, 'counts': counts, 'limit': limit,
                'read_only': True, 'can_execute': False, 'device_work_admitted': False,
                'next_after': next_after,
                'candidates': [{**dict(row), 'ip': str(IPv4Address(row['ip']))} for row in page]}
