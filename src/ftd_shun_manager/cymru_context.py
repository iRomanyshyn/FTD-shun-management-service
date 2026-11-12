"""Optional supplement in the isolated metadata cache; never source-DB writes."""

import json
import sqlite3
from collections import Counter
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network
from uuid import uuid4

from .cymru import PROFILE, SOURCE, checked_context
from .ip_context import stamp
from .location_context import DAY
from .location_context import PROFILE as LOCATION_PROFILE
from .location_context import checked_context as checked_location
from .rdap import public_ip


class CymruSupplement:
    def __init__(self, cache):
        self.cache = cache

    def initialize(self):
        with self.cache.write() as db:
            if self.cache.meta(db, 'location_profile') != LOCATION_PROFILE:
                raise ValueError('Cymru requires the existing separate location cache.')
            db.execute('''CREATE TABLE IF NOT EXISTS cymru_entries(
                ip BLOB PRIMARY KEY REFERENCES contexts(ip) ON DELETE CASCADE,
                occurrence TEXT NOT NULL,attempt_id TEXT NOT NULL,attempted_at TEXT NOT NULL,
                fetched_at TEXT,retry_at REAL NOT NULL,
                payload TEXT CHECK(payload IS NULL OR length(payload)<=2048),reason TEXT)''')

    def refresh_batch(self, provider, *, refresh_seconds=7 * DAY, limit=500):
        if type(limit) is not int or not 1 <= limit <= 500 or not DAY <= refresh_seconds <= 30 * DAY:
            raise ValueError('Invalid routing refresh bounds.')
        cache, now, attempt = self.cache, self.cache.clock(), str(uuid4())
        with cache.write() as db:
            if cache.meta(db, 'cymru_next_batch', 0) > now:
                return 0
            rows = db.execute('''SELECT c.* FROM contexts c LEFT JOIN cymru_entries e ON e.ip=c.ip
                WHERE c.active=1 AND c.state NOT IN ('skipped','pending','looking_up','not_requested')
                AND (c.payload IS NULL OR json_extract(c.payload,'$.asn') IS NULL
                    OR json_extract(c.payload,'$.organization') IS NULL OR json_extract(c.payload,'$.network') IS NULL)
                AND (e.ip IS NULL OR e.retry_at<=?
                    OR (e.occurrence!=c.occurrence AND e.attempted_at<=?))
                ORDER BY c.detected_at DESC,c.ip LIMIT ?''', (now, stamp(now - 60), limit)).fetchall()
            # A new occurrence is eligible again after the ordinary cooldown.
            for row in rows:
                ip = IPv4Address(row['ip'])
                if not public_ip(ip):
                    raise ValueError('Routing queries require public observed IPs.')
                if row['payload'] is not None:
                    checked_location(json.loads(row['payload']), ip)
            if not rows:
                return 0
            for row in rows:
                db.execute('''INSERT INTO cymru_entries VALUES (?,?,?,?,NULL,?,NULL,'in_progress')
                    ON CONFLICT(ip) DO UPDATE SET occurrence=excluded.occurrence,attempt_id=excluded.attempt_id,
                    attempted_at=excluded.attempted_at,retry_at=excluded.retry_at,reason='in_progress',
                    payload=CASE WHEN cymru_entries.occurrence=excluded.occurrence THEN cymru_entries.payload END,
                    fetched_at=CASE WHEN cymru_entries.occurrence=excluded.occurrence THEN cymru_entries.fetched_at END''',
                    (row['ip'], row['occurrence'], attempt, stamp(now), now + 900))
            cache.save_meta(db, 'cymru_next_batch', now + 60)
        ips = [IPv4Address(row['ip']) for row in rows]
        try:
            values = provider.lookup_many(ips)
            if type(values) is not dict or set(values) != {str(ip) for ip in ips}:
                raise ValueError('Incomplete routing batch.')
            for ip in ips:
                value, reason = values[str(ip)]
                if reason not in (None, 'not_mapped', 'lookup_failed', 'name_unavailable'):
                    raise ValueError('Invalid routing result.')
                if value is not None:
                    checked_context(value, ip)
                    if reason not in (None, 'name_unavailable'):
                        raise ValueError('Invalid successful routing result.')
                elif reason not in ('not_mapped', 'lookup_failed'):
                    raise ValueError('Missing routing result.')
        except (OSError, ValueError, TypeError, KeyError):
            values = {str(ip): (None, 'lookup_failed') for ip in ips}
        counts = Counter()
        with cache.write() as db:
            for row, ip in zip(rows, ips, strict=True):
                current = db.execute('''SELECT e.* FROM cymru_entries e JOIN contexts c ON c.ip=e.ip
                    AND c.occurrence=e.occurrence WHERE e.ip=? AND e.occurrence=? AND e.attempt_id=? AND c.active=1''',
                    (row['ip'], row['occurrence'], attempt)).fetchone()
                if current is None:
                    continue
                value, reason = values[str(ip)]
                # Preserve last useful data on failure/negative refresh. Never
                # borrow names from a different route or observed occurrence.
                if value and reason == 'name_unavailable' and current['payload']:
                    previous = checked_context(json.loads(current['payload']), ip)
                    if previous['network'] == value['network'] and previous['asns'] == value['asns']:
                        value['organization'] = value['organization'] or previous['organization']
                payload = json.dumps(value) if value else current['payload']
                db.execute('UPDATE cymru_entries SET payload=?,reason=?,fetched_at=?,retry_at=? WHERE ip=?',
                    (payload, reason, stamp(cache.clock()) if value else current['fetched_at'],
                     cache.clock() + (900 if reason in ('lookup_failed', 'name_unavailable') else refresh_seconds), row['ip']))
                counts[reason or 'ready'] += 1
            if counts:
                cache.save_meta(db, 'revision', cache.meta(db, 'revision', 0) + 1)
            if counts.get('lookup_failed') == len(rows):
                cache.save_meta(db, 'cymru_next_batch', cache.clock() + 900)
        print(json.dumps({'event': 'ip_context.cymru_batch', 'processed': sum(counts.values()),
                          'counts': dict(counts)}), flush=True)
        return sum(counts.values())


def read_supplements(db, packed):
    """Same readonly snapshot/display limit as primary data; optional old-cache support."""
    result = {}
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cymru_entries'").fetchone():
            return result
        for offset in range(0, len(packed), 100):
            chunk = packed[offset:offset + 100]
            rows = db.execute('''SELECT e.ip,substr(e.payload,1,2049) AS payload,
                substr(e.fetched_at,1,40) AS fetched_at,substr(e.reason,1,40) AS reason
                FROM cymru_entries e JOIN contexts c ON c.ip=e.ip AND c.occurrence=e.occurrence
                WHERE e.ip IN (''' + ','.join('?' for _ in chunk) + ') AND e.payload IS NOT NULL', chunk)
            for row in rows:
                try:
                    if len(row['payload']) > 2048 or not row['fetched_at'].endswith('Z'):
                        raise ValueError('Invalid cached routing payload/time.')
                    datetime.fromisoformat(row['fetched_at'])
                    ip = IPv4Address(row['ip'])
                    value = dict(checked_context(json.loads(row['payload']), ip))
                    result[str(ip)] = {**value, 'fetched_at': row['fetched_at'],
                                       'stale': row['reason'] is not None}
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    continue  # Malformed supplement must not hide valid IPFire data.
    except sqlite3.Error:
        return {}  # Optional metadata schema is never repaired by Web.
    return result


def combine(primary, routing):
    if primary.get('state') != 'ready':
        network = IPv4Network(routing['network'])
        primary = {'state': 'ready', 'country': None, 'network': routing['network'],
                   'range_start': str(network.network_address), 'range_end': str(network.broadcast_address),
                   'organization': None, 'asn': None, 'provider': PROFILE,
                   'source': SOURCE, 'registry': 'Team Cymru', 'fetched_at': routing['fetched_at']}
    else:
        primary = dict(primary)
    # Geography and primary network stay intact. Mark every display field which
    # comes from Cymru, rather than presenting it as IPFire/RDAP information.
    supplied = []
    if not primary.get('asn'):
        primary['asns'] = routing['asns']
        primary['asn'] = routing['asns'][0] if len(routing['asns']) == 1 else None
        supplied.append('ASN')
    if (not primary.get('organization') and routing['organization']
            and (not primary.get('asn') or routing['asns'] == [primary['asn']])):
        primary['organization'] = routing['organization']
        supplied.append('network name')
    primary['routing'], primary['routing_fields'] = routing, supplied
    return primary
