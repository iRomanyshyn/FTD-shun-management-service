"""Read-only legacy transition inventory; no converter, authority or startup hook."""

import argparse
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .import_preparations import ImportPreparations, _feed
from .inventory import load_public_inventory
from .managed_maintenance import TABLES, _initialize, _time
from .managed_safety import fleet_waits_present, managed_state
from .operation_queue import OperationQueue, stamp
from .store import Store

BATCH_SIZE = 100
BASE_TABLES = ('devices', 'protected_ips', 'protected_policy', 'shun_state', 'shun_events',
               'manual_import_batches', 'shun_import_origins', 'operation_jobs', 'operation_requests',
               'operation_links', 'operation_executor', 'sqlite_sequence')
DRAFT_TABLES = ('import_preparation_plans', 'import_preparation_targets')
DOMAIN = 'ftd-shun/legacy-to-fenced-inspection/v1'


def _schema(db):
    return [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]


class _MemoryStore(Store):
    """Trusted contract generation only; it cannot open the selected source."""

    def __init__(self, db):
        self.db = db
        self.path = Path('/unused-in-memory-migration-contract')

    @contextmanager
    def _connection(self):
        yield self.db
        self.db.commit()


@lru_cache(maxsize=2)
def _expected(with_drafts):
    with closing(sqlite3.connect(':memory:')) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        store = _MemoryStore(db)
        store.initialize()
        OperationQueue(store).initialize()
        db.execute('BEGIN')
        _initialize(db, store)
        if with_drafts:
            ImportPreparations(store).initialize(connection=db)
        return _schema(db)


def _typed(value):
    if value is None:
        return ['null']
    if type(value) is bytes:
        return ['blob', value.hex()]
    if type(value) is int:
        return ['integer', str(value)]
    if type(value) is float:
        return ['real', value.hex()]
    if type(value) is str:
        return ['text', value]
    raise ValueError('Unsupported SQLite value; no partial source manifest was returned.')


def _manifest(db, schema, with_drafts):
    digest = hashlib.sha256()
    metadata = {name: db.execute(f'PRAGMA {name}').fetchone()[0]
                for name in ('user_version', 'application_id', 'encoding', 'journal_mode')}
    _feed(digest, [DOMAIN, 'source', metadata, schema])
    tables = {}
    # Identifiers are fixed trusted constants, never names supplied by the CLI/DB.
    for table in sorted((*BASE_TABLES, *TABLES, *(DRAFT_TABLES if with_drafts else ()))):
        rows, count = db.execute(f'SELECT rowid,* FROM {table} ORDER BY rowid'), 0
        table_hash = hashlib.sha256()
        _feed(table_hash, [DOMAIN, 'table', table, [column[0] for column in rows.description]])
        while batch := rows.fetchmany(BATCH_SIZE):
            for row in batch:
                _feed(table_hash, [_typed(value) for value in row])
            count += len(batch)
        tables[table] = {'rows': count, 'digest': table_hash.hexdigest()}
        _feed(digest, [table, tables[table]])
    return digest.hexdigest(), tables, metadata


def _inventory(entries):
    return [{'id': entry.device.id, 'hostname': entry.device.hostname,
             'management_ip': str(entry.device.management_ip), 'enabled': entry.device.enabled,
             'ssh_host_key': entry.ssh_host_key, 'allowed_interfaces': list(entry.allowed_interfaces),
             'addition_profile': entry.device.addition_profile} for entry in entries]


def _hash(value):
    digest = hashlib.sha256()
    _feed(digest, value)
    return digest.hexdigest()


def _counts(db, table, column):
    # Only this module's fixed calls supply SQL identifiers.
    return {row[0]: row[1] for row in db.execute(f'SELECT {column},COUNT(*) FROM {table} GROUP BY {column} ORDER BY {column}')}


def _blockers(db, entries, current):
    executor = db.execute('SELECT * FROM operation_executor WHERE id=1').fetchone()
    protection = db.execute('SELECT * FROM protected_policy WHERE id=1').fetchone()
    state = managed_state(db)
    fleet_waits_present(db)
    if (executor is None or protection is None or state is None
            or executor['mutations_suspended'] not in (0, 1) or protection['legacy_imported'] not in (0, 1)):
        raise ValueError('Source control metadata is inconsistent; no migration readiness was inferred.')
    blockers = []
    def block(code, condition):
        if condition:
            blockers.append(code)
    block('ORDINARY_MUTATIONS_NOT_PAUSED', executor['mutations_suspended'] != 1)
    block('DESIRED_EXECUTION_NOT_SUSPENDED', not state['restoration_suspended'])
    block('GLOBAL_LEASE_RETAINED', executor['owner'] is not None or executor['lease_until'] is not None)
    if executor['next_eligible_at'] is not None:
        try:
            eligible = _time(datetime.fromisoformat(executor['next_eligible_at']))
            if stamp(eligible) != executor['next_eligible_at']:
                raise ValueError
        except (ValueError, TypeError) as error:
            raise ValueError('Source cooldown timestamp is inconsistent.') from error
        block('COOLDOWN_NOT_ELAPSED', eligible > current)
    block('PROTECTION_IMPORT_INCOMPLETE', protection['legacy_imported'] != 1)
    block('ENABLED_LEGACY_POLICY_UNSUPPORTED', db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1 LIMIT 1').fetchone())
    block('PENDING_QUEUE_WORK', db.execute("SELECT 1 FROM operation_jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone())
    block('UNCERTAIN_QUEUE_EVIDENCE', db.execute("SELECT 1 FROM operation_jobs WHERE state IN ('UNVERIFIED','RECONCILED_ABSENT') LIMIT 1").fetchone())
    block('MANAGED_ATTEMPT_ATTENTION', db.execute("SELECT 1 FROM managed_restoration_attempts WHERE state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED') LIMIT 1").fetchone())
    block('UNFINISHED_DEVICE_CLEANUP', db.execute("SELECT 1 FROM managed_removal_handoffs WHERE state IN ('WAITING_ADD','ADMITTING','ATTENTION') LIMIT 1").fetchone())
    block('UNFINISHED_FLEET_CLEANUP', db.execute("SELECT 1 FROM managed_fleet_waits WHERE state IN ('WAITING_ADD','ADMITTING','ATTENTION') LIMIT 1").fetchone()
          or db.execute("SELECT 1 FROM managed_fleet_removals WHERE phase!='ADMITTED' LIMIT 1").fetchone())
    wanted = [(entry.device.id, entry.device.hostname, entry.device.management_ip.packed,
               entry.ssh_host_key, int(entry.device.enabled)) for entry in entries]
    retained = [tuple(row) for row in db.execute('SELECT id,hostname,management_ip,ssh_host_key,enabled FROM devices ORDER BY id')]
    block('PUBLIC_INVENTORY_DIFFERS', retained != wanted)
    return blockers


def inspect_snapshot(db, entries, *, concurrency=1, reviewed_at=None, expected_digest=None, now=None):
    """Caller owns one read snapshot. A digest never authorizes a migration."""
    current = _time(now or datetime.now(UTC))
    issued = _time(reviewed_at or current)
    if issued > current or current - issued >= timedelta(minutes=5):
        raise ValueError('Inspection expired or is in the future; no automatic rebase.')
    if (not db.in_transaction or type(concurrency) is not int or not 1 <= concurrency <= 10
            or not 1 <= len(entries) <= 10 or not any(entry.device.enabled for entry in entries)):
        raise ValueError('One read transaction, 1..10 public devices/at least one enabled ID and literal concurrency 1..10 are required.')
    if expected_digest is not None and (reviewed_at is None or type(expected_digest) is not str
            or len(expected_digest) != 64 or any(char not in '0123456789abcdef' for char in expected_digest)):
        raise ValueError('Reinspection requires the original timestamp and lowercase SHA-256 inspection digest.')
    schema = _schema(db)
    with_drafts = any(row[1] in DRAFT_TABLES for row in schema)
    if schema != _expected(with_drafts):
        raise ValueError('Unsupported source schema: exact current base/queue plus seven legacy managed tables required; never drop retained evidence.')
    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Source integrity checks failed; no partial migration report was returned.')
    blockers = _blockers(db, entries, current)
    for table, limit in TABLES.items():
        if db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] > limit:
            raise ValueError('Source managed data exceeds the recognized legacy capacity.')
    source_digest, tables, metadata = _manifest(db, schema, with_drafts)
    inventory_digest = _hash([DOMAIN, 'inventory', _inventory(entries)])
    target = {'runtime': 'continuous-observation', 'policy_format': 2, 'concurrency': concurrency,
              'device_ids': [entry.device.id for entry in entries if entry.device.enabled],
              'desired_execution_suspended': True, 'ordinary_mutations_paused': True,
              'addition_device_ids': []}
    digest = _hash([DOMAIN, 'inspection', stamp(issued), source_digest, inventory_digest, target])
    if expected_digest is not None and not hmac.compare_digest(expected_digest, digest):
        raise ValueError('Inspection state/configuration changed; no automatic rebase or migration.')
    if now is None and datetime.now(UTC) - issued >= timedelta(minutes=5):
        raise ValueError('Inspection expired while reading the source; repeat inspection.')
    return {'inspection_format': 1, 'read_only': True, 'migration_available': False, 'migration_ready': False,
            'semantic_conversion_validated': False, 'operational_preconditions_satisfied': not blockers,
            'blockers': blockers, 'reviewed_at': stamp(issued), 'expires_at': stamp(issued + timedelta(minutes=5)),
            'source_profile': 'legacy-seven-tables-with-drafts' if with_drafts else 'legacy-seven-tables',
            'source_digest': source_digest, 'inventory_digest': inventory_digest, 'inspection_digest': digest,
            'target': target, 'tables': tables, 'source_metadata': metadata,
            'summary': {'policy': _counts(db, 'managed_shun_targets', 'enabled'),
                        'jobs': _counts(db, 'operation_jobs', 'state'),
                        'attempts': _counts(db, 'managed_restoration_attempts', 'state'),
                        'device_cleanup': _counts(db, 'managed_removal_handoffs', 'state'),
                        'fleet_cleanup': _counts(db, 'managed_fleet_waits', 'state'),
                        'terminal_attempts_without_queue_evidence': db.execute("""SELECT COUNT(*) FROM managed_restoration_attempts a
                            LEFT JOIN operation_jobs j ON j.id=a.job_id WHERE j.id IS NULL
                            AND a.state NOT IN ('QUEUED','RUNNING')""").fetchone()[0]},
            'preservation_required': ['original_keys_and_receipts', 'actors_and_authority', 'retired_generations',
                                      'attempts_and_uncertainty', 'original_ttls_and_links', 'observations_and_origins',
                                      'protection_and_audit', 'no_automatic_adoption_or_resume'],
            'warning': 'Observational snapshot only: no converter, backup, remote-quiescence proof or activation authority.'}


def inspect_database(database, inventory, **options):
    """Read existing files only, including WAL; never use Store's creating path."""
    if not database.is_absolute() or not inventory.is_absolute():
        raise ValueError('Supply reviewed absolute database and public-inventory paths.')
    if database.is_symlink() or not database.is_file():
        raise ValueError('Select an existing regular, non-symlink database file.')
    entries = load_public_inventory(inventory)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        report = inspect_snapshot(db, entries, **options)
        if load_public_inventory(inventory) != entries:
            raise ValueError('Public inventory changed during inspection; no report was returned.')
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only nonempty legacy-to-fenced transition inspection; no apply action.')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True, help='Credential-free public inventory only')
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--confirm-offline', action='store_true', help='Assert owning services are stopped and old RPCs settled; not proven by inspection')
    parser.add_argument('--reviewed-at', help='Original inspection timestamp, with --inspection-digest for reinspection')
    parser.add_argument('--inspection-digest')
    args = parser.parse_args(argv)
    if not args.confirm_offline or bool(args.reviewed_at) != bool(args.inspection_digest):
        parser.error('Offline confirmation is required; reinspection requires both original timestamp and inspection digest.')
    try:
        issued = datetime.fromisoformat(args.reviewed_at) if args.reviewed_at else None
        if issued is not None and stamp(_time(issued)) != args.reviewed_at:
            raise ValueError('Use the exact original canonical UTC inspection timestamp.')
        report = inspect_database(args.database, args.inventory, concurrency=args.concurrency,
                                  reviewed_at=issued, expected_digest=args.inspection_digest)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
        # Never echo raw SQLite/JSON, comments, inventory content or path arguments.
        parser.exit(2, 'Migration inspection refused: invalid/incompatible source, configuration or changed/expired snapshot. No migration was performed.\n')
    print(json.dumps({'event': 'maintenance.migration.inspected', **report}, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
