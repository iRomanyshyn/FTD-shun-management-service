"""Explicit clean development setup; no overwrite, conversion, SSH or authority."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .bulk_attempts import BulkAttempts
from .bulk_cancellations import BulkCancellations
from .bulk_dispatch import BulkDispatch
from .bulk_ordered_promotion import BulkOrderedPromoter
from .bulk_ordered_waits import BulkOrderedWaits
from .bulk_policy import BulkPolicies, _state
from .bulk_waits import BulkWaits
from .device_leases import DeviceLeases
from .inventory import load_public_inventory
from .maintenance import _actor
from .operation_queue import OperationQueue, stamp
from .store import Store


def _protection(path):
    if path is None:
        return []
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError('Select an existing regular absolute protection-source database.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        rows = db.execute('SELECT ip,name,comment,enabled FROM protected_ips ORDER BY ip LIMIT 1001').fetchall()
    if len(rows) > 1000:
        raise ValueError('Protected-IP settings exceed the 1000-address limit.')
    seen = set()
    for ip, name, comment, enabled in rows:
        if (type(ip) is not bytes or len(ip) != 4 or ip in seen or type(enabled) is not int or enabled not in (0, 1)
                or type(name) is not str or type(comment) is not str or len(name) > 100 or len(comment) > 500
                or any(ord(char) < 32 and char not in '\n\t' for char in name + comment)):
            raise ValueError('Protected-IP settings are invalid; no partial settings copy.')
        seen.add(ip)
    return rows


def _build(store, entries, concurrency, protection, subject):
    store.initialize()
    queue = OperationQueue(store)
    queue.initialize()
    for entry in entries:
        store.upsert_device(entry.device, entry.ssh_host_key)
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    policy = BulkPolicies(store)
    policy.initialize_empty()
    policy.preparations.initialize()
    BulkCancellations(store).initialize()
    BulkAttempts(store, queue).initialize()
    BulkWaits(store).initialize()
    BulkDispatch(store, queue).initialize()
    scope = frozenset(entry.device.id for entry in entries if entry.device.enabled)
    DeviceLeases(store, queue).initialize(scope, concurrency=concurrency)
    BulkOrderedWaits(store, queue).initialize(enabled=True)
    BulkOrderedPromoter(store, queue).initialize(enabled=True)
    timestamp, key = stamp(datetime.now(UTC)), str(uuid4())
    with store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for ip, name, comment, enabled in protection:
            db.execute('INSERT INTO protected_ips VALUES (?,?,?,?,?)', (ip, name, comment, enabled, timestamp))
            store._insert_event(db, 'PROTECTED_IP_IMPORTED_FROM_DEV_SETTINGS', None, IPv4Address(ip), None,
                                subject, 'Development setup', (), key, {'enabled': bool(enabled)}, timestamp)
        db.execute('UPDATE protected_policy SET legacy_imported=1,revision=?', (int(bool(protection)),))
        # This is a new empty profile, not resume/rearm of any old policy.
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0,dispatch_resume_after=?', (timestamp,))
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
        store._insert_event(db, 'DEV_PROFILE_INITIALIZED', None, None, None, subject, 'Development setup', (), key,
                            {'device_ids': sorted(scope), 'concurrency': concurrency,
                             'protected_ips_copied': len(protection), 'managed_targets': 0}, timestamp)
        _state(db)
        if db.execute('PRAGMA foreign_key_check').fetchone() or db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Fresh profile failed integrity validation.')
    with store._connection() as db:
        result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result[0] != 0 or result[1] != 0:
            raise ValueError('Fresh profile could not checkpoint before publication.')
    return {'device_ids': sorted(scope), 'device_count': len(entries), 'concurrency': concurrency,
            'protected_ips_copied': len(protection), 'managed_targets': 0, 'jobs': 0}


def initialize(database, inventory, *, concurrency=1, protection_from=None, actor='development-setup'):
    """Build privately and hard-link the completed file exclusively on Linux."""
    subject = _actor(actor)
    if not database.is_absolute() or not inventory.is_absolute() or type(concurrency) is not int or not 1 <= concurrency <= 10:
        raise ValueError('Absolute destination/inventory paths and literal concurrency 1..10 are required.')
    parent = database.parent.resolve(strict=True)
    destination = parent / database.name
    if os.path.lexists(destination):
        raise FileExistsError('Destination already exists; no reset, repair or overwrite is supported.')
    entries = load_public_inventory(inventory)
    if not 1 <= len(entries) <= 10 or not any(entry.device.enabled for entry in entries):
        raise ValueError('Select 1..10 public devices with at least one enabled device.')
    protection = _protection(protection_from)
    with TemporaryDirectory(prefix='.ftd-fresh-', dir=parent) as temporary:
        staging = Path(temporary) / 'state.db'
        # Restrict the file before any data is written, independently of umask.
        fd = os.open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        result = _build(Store(staging), entries, concurrency, protection, subject)
        if load_public_inventory(inventory) != entries:
            raise ValueError('Public inventory changed during setup; nothing was published.')
        with staging.open('rb') as source:
            os.fsync(source.fileno())
        # EEXIST is deliberate, including a concurrently created/dangling symlink.
        os.link(staging, destination, follow_symlinks=False)
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return {'event': 'development.profile.initialized', 'database': str(destination), **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a clean separate development DB; never replace or migrate an existing file.')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--protection-from', type=Path, help='Explicit readonly settings copy; no old managed policy, queues or history')
    parser.add_argument('--actor', default='development-setup', help='Trusted maintenance label, not a Web identity')
    args = parser.parse_args(argv)
    try:
        result = initialize(args.database, args.inventory, concurrency=args.concurrency,
                            protection_from=args.protection_from, actor=args.actor)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        parser.exit(2, 'Fresh setup refused. No existing database was overwritten. If a destination was published, it was retained; inspect it before retrying.\n')
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
