"""Optional advisory cache worker. Source SQLite is read-only; no device RPC."""

import argparse
import fcntl
import json
import os
import re
import signal
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4

import httpx

from .rdap import LookupUnavailable, RdapClient, public_ip, registration

APPLICATION_ID = 0x46544358
MAX_IPS = 100000
MAX_PAIRS = 200000
ADDED = {'SHUN_DETECTED', 'SHUN_REAPPEARED', 'SHUN_ADDED_BY_IMPORT',
         'MANAGED_BULK_ATTEMPT_VERIFIED', 'MANAGED_SHUN_RESTORATION_VERIFIED'}
REMOVED = {'SHUN_DISAPPEARED', 'SHUN_REMOVED_BY_UI', 'SHUN_TRUSTED_AUTO_REMOVED'}
DDL = '''
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE contexts(ip BLOB PRIMARY KEY CHECK(length(ip)=4),occurrence TEXT NOT NULL,
 active INTEGER NOT NULL CHECK(active IN (0,1)),
 state TEXT NOT NULL CHECK(state IN ('not_requested','pending','looking_up','ready','unavailable','skipped')),
 detected_at TEXT NOT NULL, attempted_at TEXT, fetched_at TEXT,
 payload TEXT CHECK(payload IS NULL OR length(payload)<=2048), reason TEXT);
CREATE TABLE observations(device_id INTEGER NOT NULL,ip BLOB NOT NULL REFERENCES contexts(ip),
 interface TEXT NOT NULL,PRIMARY KEY(device_id,ip,interface));
CREATE INDEX observations_ip ON observations(ip);
CREATE INDEX contexts_pending ON contexts(state,active,detected_at);
'''


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')


@contextmanager
def readonly(path, timeout=0.25):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Existing read-only source is required.')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=timeout)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


class ObservationFeed:
    def __init__(self, socket):
        self.client = httpx.Client(transport=httpx.HTTPTransport(uds=socket),
                                   base_url='http://observation-feed', timeout=10, trust_env=False)

    def close(self):
        self.client.close()

    def read(self, cursor, source):
        params = {'source': source} if source else {}
        if cursor:
            params['rowid'] = cursor[0]
            if cursor[1]:
                params['event_id'] = cursor[1]
        with self.client.stream('GET', '/observations', params=params) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes(16384):
                if len(raw) + len(chunk) > 32 * 1024 * 1024:
                    raise ValueError('Observation feed response exceeds capacity.')
                raw.extend(chunk)
            return json.loads(raw)


class ContextCache:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock

    @contextmanager
    def write(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('Not an IP-context cache.')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            with sqlite3.connect(self.path) as db:
                # Separate low-write cache: rollback journals keep clean closed
                # files readable through a strictly read-only Web mount.
                db.execute('PRAGMA journal_mode=DELETE')
                db.executescript(DDL)
                db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        with self.write() as db:
            # A process crash consumes the attempt; never replay its HTTP query.
            if db.execute("UPDATE contexts SET state='unavailable',reason='interrupted' WHERE state='looking_up'").rowcount:
                self.save_meta(db, 'revision', self.meta(db, 'revision', 0) + 1)
    def close(self):
        """All SQLite handles are already scoped to their short transactions."""

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def save_meta(db, key, value):
        db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps(value, separators=(',', ':'))))

    def _entry(self, db, packed, detected, *, request):
        previous = db.execute('SELECT * FROM contexts WHERE ip=?', (packed,)).fetchone()
        if previous and previous['active']:
            return
        if previous is None and db.execute('SELECT COUNT(*) FROM contexts').fetchone()[0] >= MAX_IPS:
            db.execute('DELETE FROM contexts WHERE ip IN (SELECT ip FROM contexts WHERE active=0 '
                       'AND NOT EXISTS(SELECT 1 FROM observations o WHERE o.ip=contexts.ip) ORDER BY detected_at LIMIT 1000)')
            if db.execute('SELECT COUNT(*) FROM contexts').fetchone()[0] >= MAX_IPS:
                raise ValueError('IP-context capacity is exhausted; source remains untouched.')
        state = ('pending' if request else 'not_requested') if public_ip(IPv4Address(packed)) else 'skipped'
        db.execute('''INSERT INTO contexts VALUES (?,?,1,?,?,NULL,NULL,NULL,NULL)
            ON CONFLICT(ip) DO UPDATE SET occurrence=excluded.occurrence,active=1,state=excluded.state,
            detected_at=excluded.detected_at,attempted_at=NULL,fetched_at=NULL,payload=NULL,reason=NULL''',
                   (packed, str(uuid4()), state, detected))

    def scan(self, feed, *, prime_count=0):
        """Consume committed events through the private query-only feed."""
        if type(prime_count) is not int or not 0 <= prime_count <= 10:
            raise ValueError('Initial explicit sample must be between zero and ten addresses.')
        with self.write() as db:
            cursor = self.meta(db, 'cursor')
            source = self.meta(db, 'source')
        batch = feed.read(cursor, source)
        if (type(batch) is not dict or type(batch.get('baseline')) is not bool
                or type(batch.get('cursor')) is not list or len(batch['cursor']) != 2
                or type(batch['cursor'][0]) is not int or not 0 <= batch['cursor'][0] <= 2**63-1
                or type(batch.get('source')) is not str or len(batch['source']) != 16):
            raise ValueError('Invalid observation feed boundary.')
        with self.write() as db:
            if self.meta(db, 'cursor') != cursor or self.meta(db, 'source') != source:
                raise ValueError('Concurrent context observation scan refused.')
            if prime_count and cursor is not None:
                raise ValueError('Explicit sampling is allowed only on the first cache baseline.')
            if batch['baseline']:
                rows = batch.get('observations')
                if type(rows) is not list or len(rows) > MAX_PAIRS:
                    raise ValueError('Observation baseline exceeds bounded context capacity.')
                normalized = []
                for row in rows:
                    if (type(row) is not list or len(row) != 3 or type(row[0]) is not int
                            or not 1 <= row[0] <= 65535 or type(row[2]) is not str or not 1 <= len(row[2]) <= 128):
                        raise ValueError('Invalid observation scope.')
                    normalized.append((row[0], IPv4Address(row[1]).packed, row[2]))
                old_active = {row[0] for row in db.execute('SELECT DISTINCT ip FROM observations')}
                present = {row[1] for row in normalized}
                if len(present) > MAX_IPS:
                    raise ValueError('Observation baseline exceeds cache capacity.')
                db.execute('DELETE FROM observations')
                for packed in old_active - present:
                    db.execute("UPDATE contexts SET active=0,state=CASE WHEN state='pending' THEN 'not_requested' ELSE state END WHERE ip=?", (packed,))
                selected = set(sorted(ip for ip in present if public_ip(IPv4Address(ip)))[:prime_count])
                for packed in present:
                    self._entry(db, packed, stamp(self.clock()), request=packed in selected)
                db.executemany('INSERT INTO observations VALUES (?,?,?)', normalized)
                self.save_meta(db, 'baseline_at', stamp(self.clock()))
                if cursor is not None:
                    self.save_meta(db, 'last_gap_at', stamp(self.clock()))
            else:
                events = batch.get('events')
                if type(events) is not list or len(events) > 1000 or batch['source'] != source:
                    raise ValueError('Invalid incremental observation feed.')
                for event in events:
                    if event['event_type'] not in ADDED | REMOVED or event['ip'] is None:
                        continue
                    packed, device, interface = IPv4Address(event['ip']).packed, event['device_id'], event['interface']
                    if type(device) is not int or not 1 <= device <= 65535:
                        raise ValueError('Invalid public observation event.')
                    if event['event_type'] in ADDED:
                        if type(interface) is not str or not 1 <= len(interface) <= 128:
                            raise ValueError('A new context requires an exact observed interface.')
                        self._entry(db, packed, event['timestamp'], request=True)
                        db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?)', (device, packed, interface))
                    else:
                        if interface is None:
                            db.execute('DELETE FROM observations WHERE device_id=? AND ip=?', (device, packed))
                        else:
                            db.execute('DELETE FROM observations WHERE device_id=? AND ip=? AND interface=?', (device, packed, interface))
                        if not db.execute('SELECT 1 FROM observations WHERE ip=?', (packed,)).fetchone():
                            db.execute("UPDATE contexts SET active=0,state=CASE WHEN state='pending' THEN 'not_requested' ELSE state END WHERE ip=?", (packed,))
                if db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] > MAX_PAIRS:
                    raise ValueError('Context observation capacity is exhausted.')
            self.save_meta(db, 'source', batch['source'])
            self.save_meta(db, 'cursor', batch['cursor'])
            if batch['baseline'] or batch.get('events'):
                self.save_meta(db, 'revision', self.meta(db, 'revision', 0) + 1)
        return len(batch.get('events', []))

    def lookup_one(self, provider):
        with self.write() as db:
            if self.meta(db, 'next_lookup', 0) > self.clock():
                return False
            row = db.execute("SELECT * FROM contexts WHERE active=1 AND state='pending' ORDER BY detected_at,ip LIMIT 1").fetchone()
            if row is None:
                return False
            db.execute("UPDATE contexts SET state='looking_up',attempted_at=? WHERE ip=? AND occurrence=? AND state='pending'",
                       (stamp(self.clock()), row['ip'], row['occurrence']))
            self.save_meta(db, 'next_lookup', self.clock() + 2)
            bootstrap = self.meta(db, 'bootstrap')
        payload, reason, cooldown = None, None, 2
        try:
            payload, bootstrap = provider.lookup(IPv4Address(row['ip']), bootstrap)
            state = 'ready'
        except LookupUnavailable as error:
            state, reason, cooldown = 'unavailable', error.reason, error.cooldown
            bootstrap = getattr(provider, 'bootstrap', None) or bootstrap
        with self.write() as db:
            db.execute('''UPDATE contexts SET state=?,payload=?,reason=?,fetched_at=?
                WHERE ip=? AND occurrence=? AND state='looking_up' ''',
                       (state, json.dumps(payload) if payload else None, reason, stamp(self.clock()), row['ip'], row['occurrence']))
            self.save_meta(db, 'next_lookup', self.clock() + cooldown)
            if bootstrap is not None:
                self.save_meta(db, 'bootstrap', bootstrap)
            self.save_meta(db, 'revision', self.meta(db, 'revision', 0) + 1)
        print(json.dumps({'event': 'ip_context.lookup.finished', 'ip': str(IPv4Address(row['ip'])),
                          'state': state, 'reason': reason}), flush=True)
        return True


def read_contexts(path, ips, *, with_revision=False, limit=100):
    """Small read-only Web batch. Failure never blocks an operator action."""
    empty = ({}, 0) if with_revision else {}
    revision = 0
    if path is None:
        return empty
    try:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Invalid displayed-IP limit.')
        packed = list(dict.fromkeys(IPv4Address(ip).packed for ip in ips))[:limit]
        if not packed:
            return ({}, cache_revision(path)) if with_revision else {}
        with readonly(path, 0.05) as db:
            if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                return empty
            revision = _revision(db)
            rows = []
            for offset in range(0, len(packed), 100):
                batch = packed[offset:offset + 100]
                rows.extend(db.execute('SELECT ip,state,substr(fetched_at,1,40) AS fetched_at,substr(payload,1,2049) AS payload '
                                       'FROM contexts WHERE ip IN (' + ','.join('?' for _ in batch) + ')', batch).fetchall())
        result = {}
        for row in rows:
            ip = IPv4Address(row['ip'])
            value = {'state': row['state'], 'fetched_at': row['fetched_at']}
            if row['state'] == 'ready':
                if row['payload'] is None or len(row['payload']) > 2048:
                    raise ValueError('Oversized cached context')
                raw = json.loads(row['payload'])
                if type(raw) is dict and raw.get('provider') == 'ipfire-location-v1':
                    from .location_context import checked_context

                    value.update(checked_context(raw, ip))
                    result[str(ip)] = value
                    continue
                if type(raw) is not dict or set(raw) != {'country', 'network', 'organization', 'range_start', 'range_end', 'source', 'registry'}:
                    raise ValueError('Invalid cached context')
                # Revalidate even local advisory data; no raw external links or
                # contact objects are ever rendered from the cache.
                for key, field_limit in (('network', 96), ('organization', 96), ('country', 2), ('registry', 16)):
                    if raw.get(key) is not None and (type(raw[key]) is not str or len(raw[key]) > field_limit
                            or any(not char.isprintable() for char in raw[key])):
                        raise ValueError('Invalid cached display field')
                checked = registration({'objectClassName': 'ip network', 'ipVersion': 'v4',
                    'startAddress': raw['range_start'], 'endAddress': raw['range_end']}, ip, raw['source'])
                if raw['registry'] != checked['registry'] or (raw['country'] is not None and not re.fullmatch('[A-Z]{2}', raw['country'])):
                    raise ValueError('Invalid registration source or country')
                value.update(raw)
            result[str(ip)] = value
        return (result, revision) if with_revision else result
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RecursionError):
        return ({}, revision) if with_revision else {}


def _revision(db):
    row = db.execute("SELECT substr(value,1,128) FROM meta WHERE key='revision'").fetchone()
    value = json.loads(row[0]) if row else 0
    return value if type(value) is int and 0 <= value < 2**53 else 0


def cache_revision(path):
    if path is None:
        return 0
    try:
        with readonly(path, 0.05) as db:
            if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                return 0
            return _revision(db)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed-socket', required=True)
    parser.add_argument('--cache', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--prime-count', type=int, default=0)
    args = parser.parse_args()
    if args.check:
        feed = ObservationFeed(args.feed_socket)
        try:
            batch = feed.read(None, None)
            if type(batch) is not dict or batch.get('baseline') is not True or type(batch.get('observations')) is not list:
                raise ValueError('Invalid query-only observation feed.')
            print(json.dumps({'query_only_feed_checked': True, 'public_network_attempted': False,
                              'observations': len(batch['observations']), 'cache_exists': args.cache.is_file()}))
        finally:
            feed.close()
        return
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    with (args.cache.parent / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cache = ContextCache(args.cache)
        cache.initialize()
        provider = RdapClient()
        feed = ObservationFeed(args.feed_socket)
        stopping = False

        def stop(*_args):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            initial, failed = True, False
            while not stopping:
                try:
                    cache.scan(feed, prime_count=args.prime_count if initial else 0)
                except (httpx.HTTPError, OSError, ValueError, sqlite3.Error):
                    if args.once:
                        raise
                    if not failed:
                        print(json.dumps({'event': 'ip_context.feed.unavailable', 'retry_seconds': 5}), flush=True)
                    failed = True
                    time.sleep(5)
                    continue
                if failed:
                    print(json.dumps({'event': 'ip_context.feed.recovered'}), flush=True)
                initial, failed = False, False
                if args.once:
                    while cache.lookup_one(provider):
                        time.sleep(2)
                    return
                cache.lookup_one(provider)
                for _ in range(10):
                    if stopping:
                        break
                    time.sleep(0.5)
        finally:
            provider.close()
            feed.close()
            cache.close()


if __name__ == '__main__':
    main()
