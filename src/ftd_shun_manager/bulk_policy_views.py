"""Bounded version-2 policy projections; no initialization, admission or RPC."""

import json
import sqlite3
from contextlib import contextmanager
from ipaddress import IPv4Address

from .bulk_policy import MAX_KEYS, BulkUnavailable, _state
from .managed_selection import selected_pairs
from .managed_shuns import ManagedPageChanged, ManagedPageInvalid


class BulkPolicyViews:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _snapshot(self):
        # mode=ro also refuses an absent/deleted database without creating it.
        db = sqlite3.connect(self.store.path.resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN')
            yield db
        finally:
            db.close()

    @staticmethod
    def _metadata(db, revision):
        state = _state(db)
        if state is None:
            raise BulkUnavailable('Existing version-2 policy is required; no storage was initialized.')
        if revision is not None and revision != state['revision']:
            raise ManagedPageChanged('Managed policy changed; reopen the current version-2 view.')
        if db.execute('''SELECT 1 FROM managed_shun_targets t LEFT JOIN devices d ON d.id=t.device_id
                LEFT JOIN managed_shun_requests r ON r.id=t.authorization_request_id
                WHERE d.id IS NULL OR r.id IS NULL LIMIT 1''').fetchone():
            raise BulkUnavailable('Managed target is missing its device or retained authority.')
        total = db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0]
        return {'intent_format': 2, 'initialized': True, 'revision': state['revision'],
                'restoration_suspended': bool(state['restoration_suspended']), 'total': total,
                'limit': MAX_KEYS, 'read_only': True, 'controller_enabled': False,
                'attempt_ledger_initialized': db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_attempts'").fetchone() is not None,
                'controller_available': False, 'device_work_admitted': False}

    @staticmethod
    def _revision(value):
        if value is not None and (type(value) is not int or value < 0):
            raise ManagedPageInvalid('A literal non-negative policy revision is required.')

    def page(self, page=1, *, revision=None):
        self._revision(revision)
        if type(page) is not int or not 1 <= page <= 2**31 - 1:
            raise ManagedPageInvalid('Select a positive version-2 policy page.')
        with self._snapshot() as db:
            metadata = self._metadata(db, revision)
            pages = max(1, (metadata['total'] + 99) // 100)
            if page > pages:
                raise ManagedPageInvalid('Select a page within retained policy.')
            rows = self._rows(db, 'ORDER BY t.device_id,t.ip LIMIT 100 OFFSET ?', ((page - 1) * 100,))
            return {**metadata, 'page': page, 'pages': pages, 'page_size': 100, 'entries': self._entries(db, rows)}

    def selection(self, pairs, *, revision=None):
        self._revision(revision)
        pairs = selected_pairs(pairs)  # At most 100, never a batch/full-registry fallback.
        with self._snapshot() as db:
            metadata = self._metadata(db, revision)
            conditions = ' OR '.join('(t.device_id=? AND t.ip=?)' for _ in pairs)
            parameters = [value for device, ip in pairs for value in (device, ip.packed)]
            rows = self._rows(db, 'WHERE ' + conditions + ' ORDER BY t.device_id,t.ip LIMIT 100', parameters)
            entries = self._entries(db, rows)
            return {**metadata, 'read_scope': 'selected_pairs', 'selected_count': len(entries),
                    'selection': [{'device_id': device, 'ip': str(ip)} for device, ip in pairs], 'entries': entries}

    @staticmethod
    def _rows(db, suffix, parameters):
        return db.execute('''SELECT t.*,d.hostname,d.enabled AS device_enabled,r.actor_subject,
            r.actor_display_name,r.actor_roles_json,
            EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=t.device_id AND s.ip=t.ip AND s.active=1) AS observed_present,
            EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=t.ip AND p.enabled=1) AS protected
            FROM managed_shun_targets t JOIN devices d ON d.id=t.device_id
            JOIN managed_shun_requests r ON r.id=t.authorization_request_id ''' + suffix, parameters).fetchall()

    @staticmethod
    def _entries(db, rows):
        entries, metadata = [], {}
        attempts = db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_attempts'").fetchone() is not None
        for row in rows:
            entry = dict(row)
            key = entry['authorization_request_id']
            if key not in metadata:
                # A bulk authority may contain thousands of pairs. Read it once
                # per distinct request, not once per returned target row.
                authority = db.execute('SELECT payload_json FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
                payload, roles = json.loads(authority['payload_json']), json.loads(entry['actor_roles_json'])
                if (not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 2
                        or any(type(payload.get(field)) is not str for field in ('label', 'reason'))
                        or not isinstance(roles, list) or any(type(role) is not str for role in roles)):
                    raise BulkUnavailable('Version-2 author metadata is unavailable; no legacy interpretation was used.')
                metadata[key] = {'label': payload['label'], 'reason': payload['reason'], 'actor_roles': roles}
            entry.pop('actor_roles_json')
            entry.update(metadata[key])
            pair = (row['device_id'], row['ip'])
            latest = db.execute('''SELECT a.state,a.generation,a.completed_at,a.job_id,
                EXISTS(SELECT 1 FROM operation_jobs j WHERE j.id=a.job_id) AS job_present
                FROM managed_bulk_attempts a WHERE a.device_id=? AND a.ip=?
                ORDER BY a.requested_at DESC,a.id DESC LIMIT 1''', pair).fetchone() if attempts else None
            attention = attempts and db.execute("SELECT 1 FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND state IN ('FAILED','UNVERIFIED') LIMIT 1", pair).fetchone() is not None
            verified = db.execute("SELECT MAX(completed_at) FROM managed_bulk_attempts WHERE device_id=? AND ip=? AND state='VERIFIED'", pair).fetchone()[0] if attempts else None
            pending = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING')", pair).fetchone()[0]
            entry.update(last_attempt_state=latest['state'] if latest else None,
                         last_attempt_generation=latest['generation'] if latest else None,
                         last_verified_application_at=verified, attention=bool(attention), pending_jobs=pending,
                         missing_unknown_job=bool(latest and latest['state'] == 'UNVERIFIED' and not latest['job_present']))
            entry['ip'] = str(IPv4Address(row['ip']))
            for field in ('enabled', 'device_enabled', 'observed_present', 'protected'):
                entry[field] = bool(entry[field])
            entries.append(entry)
        return entries
