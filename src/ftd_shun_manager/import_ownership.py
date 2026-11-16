"""Bounded current import ownership views; membership alone grants no authority."""

import hashlib
import json
from datetime import UTC, datetime
from ipaddress import IPv4Address

from .bulk_intent import _uuid
from .bulk_policy import BulkPolicies, BulkUnavailable
from .bulk_policy_views import BulkPolicyViews
from .managed_shuns import ManagedPageInvalid

CATEGORIES = ('OWNED_ADDED', 'OWNED_ADOPTED', 'RETIRED', 'SUPERSEDED', 'ALREADY_MANAGED', 'EXCLUDED_PROTECTED')
OWNED = ('OWNED_ADDED', 'OWNED_ADOPTED')
# Literal internal SQL; no user-supplied identifier or expression is interpolated.
CATEGORY = """CASE WHEN b.classification='EXCLUDED_PROTECTED' THEN 'EXCLUDED_PROTECTED'
 WHEN b.classification='ALREADY_MANAGED' THEN 'ALREADY_MANAGED'
 WHEN t.device_id IS NULL OR t.authorization_request_id!=b.request_id
   OR t.intent_id!=b.intent_id OR t.generation!=b.generation THEN 'SUPERSEDED'
 WHEN t.enabled=0 THEN 'RETIRED'
 WHEN b.classification='PROPOSE_ADOPT' THEN 'OWNED_ADOPTED' ELSE 'OWNED_ADDED' END"""
MEMBERS = f"""SELECT b.*,d.hostname,d.enabled AS device_enabled,t.enabled AS maintenance_enabled,
 t.authorization_request_id AS current_import_id,t.intent_id AS current_intent_id,
 t.generation AS current_generation,t.revision AS target_revision,{CATEGORY} AS ownership,
 EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=b.device_id AND s.ip=b.ip AND s.active=1) AS observed_present,
 (env_protected_ip(b.ip) OR EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=b.ip AND p.enabled=1)) AS protected,
 (SELECT COUNT(*) FROM operation_jobs j WHERE j.device_id=b.device_id AND j.ip=b.ip
   AND j.state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION')) AS pending_jobs,
 EXISTS(SELECT 1 FROM operation_jobs j WHERE j.device_id=b.device_id AND j.ip=b.ip
   AND j.state IN ('FAILED','UNVERIFIED') AND __UNRESOLVED_JOB__) AS attention
 FROM managed_bulk_members b JOIN devices d ON d.id=b.device_id
 LEFT JOIN managed_shun_targets t ON t.device_id=b.device_id AND t.ip=b.ip
 WHERE b.request_id=?"""


def import_labels(db, keys):
    """Display metadata for presented targets only, never a whole-list authority read."""
    keys = sorted(set(keys))
    if len(keys) > 100:
        raise ValueError('At most 100 presented import references are supported.')
    for key in keys:
        _uuid(key)
    if not keys:
        return {}
    rows = db.execute('''SELECT m.id,m.header_json,r.actor_display_name,r.requested_at
        FROM managed_bulk_manifests m JOIN managed_shun_requests r ON r.id=m.id
        WHERE m.id IN (''' + ','.join('?' for _ in keys) + ')', keys).fetchall()
    result = {}
    for row in rows:
        header = json.loads(row['header_json'])
        if type(header) is not dict:
            raise BulkUnavailable('Import display metadata is unavailable.')
        label = header.get('label')
        if type(label) is not str or len(label) > 100:
            raise BulkUnavailable('Import display metadata is unavailable.')
        result[row['id']] = {'id': row['id'], 'label': label or 'Unlabelled import',
            'actor_display_name': row['actor_display_name'], 'requested_at': row['requested_at']}
    if len(result) != len(keys):
        raise BulkUnavailable('Current maintenance is missing its original import.')
    return result


class ImportOwnership:
    def __init__(self, store):
        self.store, self.views = store, BulkPolicyViews(store)

    def page(self, key, *, page=1, scope='owned', revision=None):
        _uuid(key)
        if type(page) is not int or page < 1 or scope not in {'owned', 'excluded', 'all'}:
            raise ManagedPageInvalid('Select a valid import ownership page and filter.')
        self.views._revision(revision)
        with self.views._snapshot() as db:
            return self.read(db, key, page=page, scope=scope, revision=revision)

    def read(self, db, key, *, page=1, scope='owned', revision=None):
        """Same projection inside a caller-owned snapshot/confirmation transaction."""
        metadata = self.views._metadata(db, revision)
        actor = db.execute('SELECT actor_subject FROM managed_shun_requests WHERE id=?', (key,)).fetchone()
        if actor is None:
            raise BulkUnavailable('The original import is unavailable.')
        # Verify the retained manifest against its stored author. This is a
        # readonly projection, not permission to submit on that author's behalf.
        root, _, manifest = BulkPolicies(self.store)._root(db, key, actor[0])
        summary = {name: 0 for name in CATEGORIES}
        from .device_reconciliation import unresolved

        members = MEMBERS.replace('__UNRESOLVED_JOB__', unresolved(db, 'j.id'))
        observed = pending = disabled = protected = attention = 0
        digest = hashlib.sha256(b'ftd-shun-manager:current-import-ownership:v1\n')
        digest.update(json.dumps([key, metadata['revision'], root['payload_digest']], separators=(',', ':')).encode())
        # Whole-scope counts/digest stream in bounded chunks; never send all
        # members to Python templates, metadata providers or the browser.
        cursor = db.execute(members + ' ORDER BY b.device_id,b.ip', (key,))
        total = 0
        while chunk := cursor.fetchmany(100):
            for row in chunk:
                if row['classification'] != 'EXCLUDED_PROTECTED' and row['current_import_id'] is None:
                    raise BulkUnavailable('An original import member is missing its retained policy key.')
                total += 1
                summary[row['ownership']] += 1
                if row['ownership'] in OWNED:
                    observed += bool(row['observed_present'])
                    pending += row['pending_jobs']
                    disabled += not row['device_enabled']
                    protected += bool(row['protected'])
                    attention += bool(row['attention'])
                    digest.update(json.dumps([row['device_id'], row['ip'].hex(), row['intent_id'], row['generation'],
                        row['authorization_request_id'], row['target_revision'], bool(row['device_enabled']),
                        bool(row['protected'])], separators=(',', ':')).encode() + b'\n')
        if total != manifest.pair_count:
            raise BulkUnavailable('Complete import ownership membership is unavailable.')
        owned = sum(summary[name] for name in OWNED)
        selected = owned if scope == 'owned' else total - owned if scope == 'excluded' else total
        pages = max(1, (selected + 99) // 100)
        if page > pages:
            raise ManagedPageInvalid('Select a page within the current import scope.')
        predicate = ('ownership IN' if scope == 'owned' else 'ownership NOT IN') + " ('OWNED_ADDED','OWNED_ADOPTED')"
        sql = 'SELECT * FROM (' + members + ')' + (' WHERE ' + predicate if scope != 'all' else '')
        rows = db.execute(sql + ' ORDER BY device_id,ip LIMIT 100 OFFSET ?', (key, (page-1)*100)).fetchall()
        targets = []
        for row in rows:
            target = {field: row[field] for field in ('device_id','hostname','ownership','classification','generation',
                'intent_id','authorization_request_id','current_import_id','current_generation','pending_jobs')}
            target.update(ip=str(IPv4Address(row['ip'])), device_enabled=bool(row['device_enabled']),
                observed_present=bool(row['observed_present']), protected=bool(row['protected']), attention=bool(row['attention']))
            targets.append(target)
        return {'import': import_labels(db, [key])[key], 'managed_revision': metadata['revision'],
            'as_of': datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            'counts': summary, 'member_count': total, 'owned_count': owned, 'observed_owned': observed,
            'absent_owned': owned-observed, 'pending_jobs': pending, 'disabled_owned': disabled,
            'attention_owned': attention,
            'protected_owned': protected, 'scope_digest': digest.hexdigest(), 'scope': scope,
            'page': page, 'pages': pages, 'page_size': 100, 'selected_count': selected, 'targets': targets,
            'read_only': True, 'device_work_admitted': False, 'can_execute': False}
