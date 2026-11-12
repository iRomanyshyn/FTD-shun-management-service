"""Signed IPFire dataset updates and bounded local enrichment; no device RPC."""

import argparse
import fcntl
import hashlib
import json
import lzma
import os
import signal
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import httpx

from .ip_context import ContextCache, ObservationFeed, readonly, stamp
from .rdap import clean, public_ip

SOURCE = 'https://www.ipfire.org/location/'
DOWNLOAD = 'https://location.ipfire.org/databases/1/location.db.xz'
PROFILE = 'ipfire-location-v1'
READER = Path(__file__).with_name('location_reader.py')
DAY = 86400


def checked_context(value, ip):
    fields = {'country', 'network', 'organization', 'range_start', 'range_end',
              'source', 'registry', 'provider', 'asn', 'dataset', 'database_at'}
    if type(value) is not dict or set(value) != fields:
        raise ValueError('Invalid local IP context fields.')
    if value['provider'] != PROFILE or value['source'] != SOURCE or value['registry'] != 'IPFire Location':
        raise ValueError('Invalid local source.')
    network = IPv4Network(value['network'], strict=True)
    if (ip not in network or value['range_start'] != str(network.network_address)
            or value['range_end'] != str(network.broadcast_address)):
        raise ValueError('Foreign local prefix.')
    if value['asn'] is not None and (type(value['asn']) is not int or not 1 <= value['asn'] <= 2**32 - 1):
        raise ValueError('Invalid ASN.')
    country = value['country']
    if country is not None and (type(country) is not str or len(country) != 2
            or not country.isascii() or not country.isalpha() or country != country.upper()):
        raise ValueError('Invalid country.')
    if value['organization'] is not None and (type(value['organization']) is not str
            or len(value['organization']) > 96 or any(not c.isprintable() for c in value['organization'])):
        raise ValueError('Invalid network name.')
    if (type(value['dataset']) is not str or len(value['dataset']) != 64
            or any(c not in '0123456789abcdef' for c in value['dataset'])):
        raise ValueError('Invalid dataset identity.')
    if (type(value['database_at']) is not str or len(value['database_at']) > 40
            or not value['database_at'].endswith('Z')):
        raise ValueError('Invalid database time.')
    datetime.fromisoformat(value['database_at'])
    return value


def native_read(path, ips):
    result = subprocess.run(['/usr/bin/python3', str(READER)],
        input=json.dumps({'database': str(path), 'ips': [str(ip) for ip in ips]}),
        capture_output=True, text=True, timeout=15, check=True)
    if len(result.stdout) > 512 * 1024:
        raise ValueError('Oversized local batch.')
    value = json.loads(result.stdout)
    if (type(value) is not dict or set(value) != {'created_at', 'rows'}
            or type(value['created_at']) is not int or not 0 < value['created_at'] < 2**40
            or type(value['rows']) is not dict or set(value['rows']) != {str(ip) for ip in ips}):
        raise ValueError('Incomplete local batch.')
    return value


def verify(path):
    subprocess.run(['/usr/bin/location', '--database', str(path), 'verify'],
                   capture_output=True, timeout=15, check=True)


class LocationDataset:
    def __init__(self, path):
        self.path = Path(path)
        self.generation = None
        self.database_at = None

    def load(self):
        verify(self.path)
        value = native_read(self.path, [])
        digest = hashlib.sha256()
        with self.path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        self.generation = digest.hexdigest()
        self.database_at = stamp(value['created_at'])

    def update(self, *, client=None):
        """Fixed HTTPS source; signature verification precedes atomic replacement."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        own_client = client is None
        client = client or httpx.Client(trust_env=False, follow_redirects=False)
        descriptor, temporary = tempfile.mkstemp(prefix='.location-', dir=self.path.parent)
        candidate = Path(temporary)
        deadline, compressed, expanded = time.monotonic() + 120, 0, 0
        try:
            with os.fdopen(descriptor, 'wb') as target:
                decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
                with client.stream('GET', DOWNLOAD, timeout=10,
                        headers={'Accept-Encoding': 'identity'}) as response:
                    response.raise_for_status()
                    if response.headers.get('content-encoding', 'identity') != 'identity':
                        raise ValueError('Unexpected database encoding.')
                    for chunk in response.iter_bytes(65536):
                        compressed += len(chunk)
                        if compressed > 64 * 1024 * 1024 or time.monotonic() > deadline:
                            raise ValueError('Database download exceeds bounds.')
                        while True:
                            output = decoder.decompress(chunk, max_length=1024 * 1024)
                            chunk = b''
                            expanded += len(output)
                            if expanded > 256 * 1024 * 1024 or time.monotonic() > deadline:
                                raise ValueError('Expanded database exceeds bounds.')
                            target.write(output)
                            if decoder.needs_input or decoder.eof:
                                break
                    if not decoder.eof or decoder.unused_data:
                        raise ValueError('Truncated or trailing database data.')
                target.flush()
                os.fsync(target.fileno())
            # Validate both signature and native readability before replacing.
            verified = LocationDataset(candidate)
            verified.load()
            os.replace(candidate, self.path)
            self.generation, self.database_at = verified.generation, verified.database_at
        finally:
            candidate.unlink(missing_ok=True)
            if own_client:
                client.close()

    def lookup_many(self, ips):
        if not self.generation:
            raise ValueError('No verified location database.')
        rows = native_read(self.path, ips)['rows']
        result = {}
        for ip in ips:
            row = rows[str(ip)]
            if row is None:
                result[str(ip)] = None
                continue
            if type(row) is not dict or set(row) != {'prefix', 'country', 'asn', 'organization'}:
                raise ValueError('Invalid native context.')
            network = IPv4Network(row['prefix'], strict=True)
            value = {'country': row['country'], 'network': str(network),
                'organization': clean(row['organization']), 'asn': row['asn'], 'provider': PROFILE,
                'range_start': str(network.network_address), 'range_end': str(network.broadcast_address),
                'source': SOURCE, 'registry': 'IPFire Location', 'dataset': self.generation,
                'database_at': self.database_at}
            result[str(ip)] = checked_context(value, ip)
        return result


class LocationCache(ContextCache):
    def initialize(self):
        if self.path.exists():
            with readonly(self.path) as db:
                if self.meta(db, 'location_profile') != PROFILE:
                    raise ValueError('Use a separate location cache; the RDAP cache is retained.')
        super().initialize()
        with self.write() as db:
            db.execute('CREATE TABLE IF NOT EXISTS location_attempts('
                       'ip BLOB PRIMARY KEY REFERENCES contexts(ip) ON DELETE CASCADE,'
                       'dataset TEXT NOT NULL,retry_at REAL NOT NULL)')
            self.save_meta(db, 'location_profile', PROFILE)

    def refresh_batch(self, provider, *, refresh_seconds=7 * DAY, limit=500):
        if not 1 <= limit <= 1000 or not DAY <= refresh_seconds <= 30 * DAY:
            raise ValueError('Invalid local refresh bounds.')
        with self.write() as db:
            rows = db.execute('''SELECT c.* FROM contexts c LEFT JOIN location_attempts a ON a.ip=c.ip
                WHERE c.active=1 AND c.state!='skipped' AND (a.ip IS NULL OR a.dataset!=?
                    OR a.retry_at<=? OR c.state IN ('pending','looking_up','not_requested'))
                ORDER BY c.detected_at DESC,c.ip LIMIT ?''',
                (provider.generation, self.clock(), limit)).fetchall()
        if not rows:
            return 0
        ips = [IPv4Address(row['ip']) for row in rows]
        if not all(public_ip(ip) for ip in ips):
            raise ValueError('Local work must use public observed IPs.')
        failure = False
        try:
            values = provider.lookup_many(ips)
            if type(values) is not dict or set(values) != {str(ip) for ip in ips}:
                raise ValueError('Incomplete local result.')
            for ip in ips:
                if values[str(ip)] is not None:
                    checked_context(values[str(ip)], ip)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            values, failure = {}, True
        changed = 0
        with self.write() as db:
            for row, ip in zip(rows, ips, strict=True):
                current = db.execute('SELECT * FROM contexts WHERE ip=? AND occurrence=? AND active=1',
                                     (row['ip'], row['occurrence'])).fetchone()
                if current is None:
                    continue
                value = values.get(str(ip))
                # A transient native failure retains previously useful context.
                if not failure or current['payload'] is None:
                    db.execute('UPDATE contexts SET state=?,payload=?,reason=?,attempted_at=?,fetched_at=? WHERE ip=?',
                        ('ready' if value else 'unavailable', json.dumps(value) if value else None,
                         None if value else 'local_lookup_failed' if failure else 'not_in_dataset',
                         stamp(self.clock()), stamp(self.clock()), row['ip']))
                db.execute('INSERT INTO location_attempts VALUES (?,?,?) ON CONFLICT(ip) DO UPDATE '
                           'SET dataset=excluded.dataset,retry_at=excluded.retry_at',
                           (row['ip'], provider.generation, self.clock() + (900 if failure else refresh_seconds)))
                changed += 1
            if changed:
                self.save_meta(db, 'revision', self.meta(db, 'revision', 0) + 1)
        print(json.dumps({'event': 'ip_context.local_batch', 'processed': changed,
                          'failed': failure, 'dataset_at': provider.database_at}), flush=True)
        return 0 if failure else changed


def interval(name, default, maximum):
    value = int(os.environ.get(name, default))
    if not DAY <= value <= maximum:
        raise ValueError(f'{name} must be between {DAY} and {maximum} seconds.')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed-socket', required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    update_seconds = interval('FTD_SHUN_LOCATION_UPDATE_INTERVAL_SECONDS', DAY, 7 * DAY)
    refresh_seconds = interval('FTD_SHUN_IP_CONTEXT_REFRESH_INTERVAL_SECONDS', 7 * DAY, 30 * DAY)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (args.cache.parent / 'location-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cache, dataset = LocationCache(args.cache), LocationDataset(args.database)
        cache.initialize()
        feed = ObservationFeed(args.feed_socket)
        try:
            if args.database.exists():
                dataset.load()
            with cache.write() as db:
                saved_update = cache.meta(db, 'location_next_update', 0)
            next_update = saved_update if dataset.generation and type(saved_update) in (int, float) else 0
            next_update = min(next_update, time.time() + update_seconds)
            feed_failed = False
            while not stopping:
                if time.time() >= next_update:
                    try:
                        dataset.update()
                        next_update = time.time() + update_seconds
                        print(json.dumps({'event': 'ip_context.dataset.ready',
                                          'database_at': dataset.database_at}), flush=True)
                    except (OSError, ValueError, lzma.LZMAError, EOFError, httpx.HTTPError, subprocess.SubprocessError):
                        next_update = time.time() + 3600
                        print(json.dumps({'event': 'ip_context.dataset.unavailable',
                                          'last_good_retained': dataset.generation is not None}), flush=True)
                    with cache.write() as db:
                        cache.save_meta(db, 'location_next_update', next_update)
                try:
                    cache.scan(feed)
                    if feed_failed:
                        print(json.dumps({'event': 'ip_context.feed.recovered'}), flush=True)
                    feed_failed = False
                except (httpx.HTTPError, OSError, ValueError, sqlite3.Error):
                    if args.once:
                        raise
                    if not feed_failed:
                        print(json.dumps({'event': 'ip_context.feed.unavailable'}), flush=True)
                    feed_failed = True
                    time.sleep(5)
                    continue
                processed = 0
                if dataset.generation:
                    for _ in range(200 if args.once else 4):
                        if stopping:
                            break
                        count = cache.refresh_batch(dataset, refresh_seconds=refresh_seconds)
                        processed += count
                        if not count:
                            break
                if args.once:
                    if not dataset.generation:
                        raise RuntimeError('No verified location dataset; no context was invented.')
                    return
                for _ in range(2 if processed else 10):
                    if stopping:
                        break
                    time.sleep(0.5)
        finally:
            feed.close()
            cache.close()


if __name__ == '__main__':
    main()
