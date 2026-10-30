"""Read-only nonempty transition inspection on disposable legacy SQLite only."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_managed_maintenance import IP, NOW, fingerprint, standing
from test_managed_maintenance import store as store_fixture
from test_managed_restoration import admit, advance_clock, change, claim
from test_managed_restoration import lab as restoration_fixture

from ftd_shun_manager import migration_inspection as inspection
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.import_preparations import ImportPreparations
from ftd_shun_manager.inventory import load_public_inventory
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import stamp
from ftd_shun_manager.store import Device, Store

store = store_fixture
lab = restoration_fixture


@pytest.fixture
def source(store, tmp_path):
    standing(store)
    registry = ManagedShuns(store)
    registry.change(str(uuid4()), 'RETIRE', [(1, IP)], 1, 0,
                    canonical_managed_change('RETIRE', [(1, IP)], 1, 0)[2],
                    'fixture-author', 'Fixture author', ('Operator',))
    store.record_observed_shun(1, IPv4Address('198.51.100.7'), 'management')
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1,next_eligible_at=?', (stamp(NOW - timedelta(seconds=1)),))
        db.execute('UPDATE protected_policy SET legacy_imported=1')
    path = tmp_path / 'public.json'
    path.write_text(json.dumps([{'id': 1, 'hostname': 'synthetic', 'management_ip': '192.0.2.1',
                                'ssh_host_key': 'ssh-ed25519 AAAA', 'allowed_interfaces': ['management']}]))
    return store, path


def inspect(source, **options):
    store, inventory = source
    return inspection.inspect_database(store.path, inventory, **({'now': NOW} | options))


def test_nonempty_retired_source_is_fingerprinted_not_converted_or_adopted(source):
    store, _path = source
    before = fingerprint(store)
    report = inspect(source)
    assert report['read_only'] and report['operational_preconditions_satisfied']
    assert not report['migration_available'] and not report['migration_ready']
    assert report['semantic_conversion_validated'] is False and report['blockers'] == []
    assert report['tables']['managed_shun_targets']['rows'] == 1
    assert report['tables']['managed_shun_requests']['rows'] == 2
    assert report['tables']['shun_state']['rows'] == 1
    assert report['summary']['policy'] == {0: 1}
    assert report['target'] == {'runtime': 'continuous-observation', 'policy_format': 2, 'device_ids': [1],
                                'concurrency': 1, 'desired_execution_suspended': True,
                                'ordinary_mutations_paused': True, 'addition_device_ids': []}
    assert fingerprint(store) == before


def test_source_connection_is_readonly_query_only_and_never_calls_file_initialization(source, monkeypatch):
    store, _path = source
    inspection._expected(False)  # Trusted in-memory contract, never selected-source startup.
    before = fingerprint(store)
    monkeypatch.setattr(Store, 'initialize', lambda *_a, **_k: pytest.fail('No selected Store startup'))
    original = inspection.inspect_snapshot

    def checked(db, *args, **kwargs):
        assert db.in_transaction and db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError): db.execute('UPDATE operation_executor SET revision=revision+1')
        return original(db, *args, **kwargs)
    monkeypatch.setattr(inspection, 'inspect_snapshot', checked)
    assert inspect(source)['read_only']
    assert fingerprint(store) == before


@pytest.mark.parametrize('damage,code', [
    ('unpause', 'ORDINARY_MUTATIONS_NOT_PAUSED'), ('desired', 'DESIRED_EXECUTION_NOT_SUSPENDED'),
    ('lease', 'GLOBAL_LEASE_RETAINED'), ('cooldown', 'COOLDOWN_NOT_ELAPSED'),
    ('protection', 'PROTECTION_IMPORT_INCOMPLETE'), ('enabled', 'ENABLED_LEGACY_POLICY_UNSUPPORTED'),
    ('QUEUED', 'PENDING_QUEUE_WORK'), ('RUNNING', 'PENDING_QUEUE_WORK'),
    ('UNVERIFIED', 'UNCERTAIN_QUEUE_EVIDENCE'), ('RECONCILED_ABSENT', 'UNCERTAIN_QUEUE_EVIDENCE'),
])
def test_operational_blockers_never_repair_pause_or_relabel_results(source, damage, code):
    store, _path = source
    with store._connection() as db:
        if damage == 'unpause': db.execute('UPDATE operation_executor SET mutations_suspended=0')
        elif damage == 'desired': db.execute('UPDATE managed_shun_registry SET restoration_suspended=0')
        elif damage == 'lease': db.execute("UPDATE operation_executor SET owner='expired-owner',lease_until=?", (stamp(NOW - timedelta(days=1)),))
        elif damage == 'cooldown': db.execute('UPDATE operation_executor SET next_eligible_at=?', (stamp(NOW + timedelta(seconds=60)),))
        elif damage == 'protection': db.execute('UPDATE protected_policy SET legacy_imported=0')
        elif damage == 'enabled': db.execute('UPDATE managed_shun_targets SET enabled=1,retired_at=NULL')
        else:
            db.execute('INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,?,?,?)',
                       (str(uuid4()), IP.packed, damage, stamp(NOW), 'ADD'))
    before = fingerprint(store)
    report = inspect(source)
    assert code in report['blockers'] and not report['operational_preconditions_satisfied']
    assert not report['migration_ready'] and fingerprint(store) == before


@pytest.mark.parametrize('damage', ['extra', 'missing_index', 'partial', 'closure', 'v2_name', 'base_trigger'])
def test_unknown_changed_or_incident_schema_is_not_treated_as_empty(source, damage):
    store, _path = source
    with store._connection() as db:
        if damage == 'extra': db.execute('CREATE TABLE unknown_evidence(value TEXT)')
        elif damage == 'missing_index': db.execute('DROP INDEX idx_managed_restoration_pair')
        elif damage == 'partial': db.execute('DROP TABLE managed_fleet_waits')
        elif damage == 'closure':
            from ftd_shun_manager.managed_closures import initialize
            db.execute('BEGIN')
            initialize(db)
        elif damage == 'v2_name': db.execute('ALTER TABLE managed_shun_registry RENAME TO managed_bulk_registry')
        else: db.execute('CREATE TRIGGER unexpected AFTER INSERT ON shun_events BEGIN SELECT 1; END')
    before = fingerprint(store)
    with pytest.raises(ValueError, match='Unsupported source schema'): inspect(source)
    assert fingerprint(store) == before


def test_exact_optional_drafts_are_retained_and_never_gain_authority(source):
    store, _path = source
    drafts = ImportPreparations(store, clock=lambda: NOW)
    drafts.initialize()
    drafts.create('198.51.100.55', [1], 'draft-owner', 'Draft owner', ('Viewer',))
    before = fingerprint(store)
    report = inspect(source)
    assert report['source_profile'] == 'legacy-seven-tables-with-drafts'
    assert report['tables']['import_preparation_plans']['rows'] == 1
    assert report['tables']['import_preparation_targets']['rows'] == 1
    assert report['tables']['managed_shun_targets']['rows'] == 1
    assert fingerprint(store) == before


@pytest.mark.parametrize('change', ['history', 'observation', 'sequence', 'authority', 'retired', 'protection', 'queue', 'inventory', 'concurrency'])
def test_same_count_and_configuration_changes_invalidate_original_inspection_without_rebase(source, change):
    store, path = source
    frozen = inspect(source)
    concurrency = 1
    if change == 'inventory':
        entries = json.loads(path.read_text())
        entries[0]['allowed_interfaces'].append('outside')
        path.write_text(json.dumps(entries))
    elif change == 'concurrency': concurrency = 2
    else:
        with store._connection() as db:
            if change == 'history': db.execute("UPDATE shun_events SET actor_display_name='different' WHERE id=(SELECT id FROM shun_events LIMIT 1)")
            elif change == 'observation': db.execute("UPDATE shun_state SET last_seen_at='2026-10-17T00:00:00Z'")
            elif change == 'sequence': db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES ('operation_jobs',42)")
            elif change == 'authority':
                # Explicit damaged-fixture edit, not a supported migration or repair.
                db.execute('DROP TRIGGER managed_request_immutable_update')
                db.execute("UPDATE managed_shun_requests SET actor_display_name='different'")
                trigger = next(row[3] for row in inspection._expected(False) if row[1] == 'managed_request_immutable_update')
                db.execute(trigger)
            elif change == 'retired': db.execute('UPDATE managed_shun_targets SET generation=generation+1')
            elif change == 'protection': db.execute('UPDATE protected_policy SET revision=revision+1')
            else: db.execute('UPDATE operation_executor SET revision=revision+1')
    before = fingerprint(store)
    with pytest.raises(ValueError, match='changed'):
        inspect(source, reviewed_at=NOW, expected_digest=frozen['inspection_digest'], concurrency=concurrency)
    assert fingerprint(store) == before


@pytest.mark.parametrize('age', [-1, 300, 301])
def test_future_and_expired_inspections_refuse_without_mutation(source, age):
    before = fingerprint(source[0])
    with pytest.raises(ValueError, match='expired|future'):
        inspect(source, reviewed_at=NOW - timedelta(seconds=age))
    assert fingerprint(source[0]) == before


def test_original_snapshot_reinspection_and_semantic_inventory_order_are_stable(source):
    store, path = source
    frozen = inspect(source)
    path.write_text(json.dumps(list(reversed(json.loads(path.read_text()))), indent=2))
    before = fingerprint(store)
    same = inspect(source, reviewed_at=NOW, expected_digest=frozen['inspection_digest'], now=NOW + timedelta(seconds=1))
    assert same['inspection_digest'] == frozen['inspection_digest'] and same['source_digest'] == frozen['source_digest']
    assert fingerprint(store) == before


def test_full_manifest_reads_committed_wal_and_bounds_row_batches(source, monkeypatch):
    store, _path = source
    with store._connection() as db:
        db.executemany('INSERT INTO shun_events VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       [(str(uuid4()), stamp(NOW), 'FIXTURE', None, None, None, None, None, None, None, '{}') for _ in range(501)])
    before = inspect(source)
    original, sizes = inspection._manifest, []

    def manifest(db, *args):
        class Cursor:
            def __init__(self, cursor):
                self.cursor, self.description = cursor, cursor.description
            def fetchone(self):
                return self.cursor.fetchone()
            def fetchmany(self, size):
                assert size <= 100
                rows = self.cursor.fetchmany(size)
                sizes.append(len(rows))
                return rows
        class Reader:
            def execute(self, *args):
                return Cursor(db.execute(*args))
        return original(Reader(), *args)
    monkeypatch.setattr(inspection, '_manifest', manifest)
    # Hold a connection with autocheckpoint disabled so the reader must see WAL.
    with closing(sqlite3.connect(store.path)) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE operation_executor SET revision=revision+1')
        writer.commit()
        report = inspect(source)
        assert report['tables']['shun_events']['rows'] > 500
        assert report['source_digest'] != before['source_digest']
    assert sizes and max(sizes) == 100


def test_missing_file_is_never_created_and_relative_paths_are_refused(source, tmp_path):
    _store, inventory = source
    absent = tmp_path / 'missing' / 'state.db'
    with pytest.raises(ValueError): inspection.inspect_database(absent, inventory, now=NOW)
    assert not absent.parent.exists()
    with pytest.raises(ValueError, match='absolute'): inspection.inspect_database(type(absent)('relative.db'), inventory, now=NOW)


def test_cli_is_explicit_readonly_and_does_not_print_source_payloads(source, monkeypatch, capsys):
    store, inventory = source
    original = inspection.inspect_database
    monkeypatch.setattr(inspection, 'inspect_database', lambda *args, **kwargs: original(*args, **kwargs, now=NOW))
    before = fingerprint(store)
    assert inspection.main(['--database', str(store.path), '--inventory', str(inventory), '--confirm-offline']) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['event'] == 'maintenance.migration.inspected' and not result['migration_ready']
    assert 'ssh-ed25519' not in output and '198.51.100' not in output and 'fixture-author' not in output
    assert fingerprint(store) == before


@pytest.mark.parametrize('arguments', [[], ['--apply'], ['--confirm-offline', '--reviewed-at', stamp(NOW)]])
def test_cli_missing_confirmation_or_apply_never_opens_storage(source, monkeypatch, arguments):
    store, inventory = source
    monkeypatch.setattr(inspection, 'inspect_database', lambda *_a, **_k: pytest.fail('No storage access'))
    with pytest.raises(SystemExit) as error:
        inspection.main(['--database', str(store.path), '--inventory', str(inventory), *arguments])
    assert error.value.code == 2


def test_cli_failure_is_sanitized_and_no_report_or_backup_is_created(source, capsys):
    store, inventory = source
    inventory.write_text('[{"password":"sensitive-test-value"}]')
    before = fingerprint(store)
    with pytest.raises(SystemExit) as error:
        inspection.main(['--database', str(store.path), '--inventory', str(inventory), '--confirm-offline'])
    output = capsys.readouterr()
    assert error.value.code == 2 and not output.out and 'sensitive-test-value' not in output.err
    assert 'No migration was performed' in output.err and fingerprint(store) == before


def test_snapshot_api_requires_a_transaction(source):
    store, inventory = source
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        with pytest.raises(ValueError, match='transaction'):
            inspection.inspect_snapshot(db, load_public_inventory(inventory), now=NOW)


def test_empty_managed_namespace_is_not_silently_initialized(store, tmp_path):
    inventory = tmp_path / 'public.json'
    inventory.write_text(json.dumps([{'id': 1, 'hostname': 'synthetic', 'management_ip': '192.0.2.1',
                                    'ssh_host_key': 'ssh-ed25519 AAAA', 'allowed_interfaces': ['management']}]))
    before = fingerprint(store)
    with pytest.raises(ValueError, match='Unsupported source schema'):
        inspection.inspect_database(store.path, inventory, now=NOW)
    assert fingerprint(store) == before


@pytest.mark.parametrize('outcome', ['VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED'])
@pytest.mark.parametrize('prune', [False, True])
def test_retained_real_attempts_and_missing_old_queue_evidence_remain_honest(lab, tmp_path, outcome, prune):
    restoration, registry, clock = lab
    store = restoration.store
    # Complete the seven-table schema only on this disposable fixture.
    with store._connection() as db:
        db.execute('BEGIN')
        inspection._initialize(db, store)
    admit(lab)
    job = claim(lab)
    result = AdditionResult(True, 'management') if outcome == 'VERIFIED' else AdditionResult(False, None) if outcome == 'NOOP' else outcome
    assert restoration.queue.finish_addition(job['id'], 'synthetic-worker', result) == outcome
    change(registry, 'RETIRE')
    if prune:
        advance_clock(lab, 400 * 86400)
        restoration.queue.prune_completed(366)
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET owner=NULL,lease_until=NULL,mutations_suspended=1,next_eligible_at=?',
                   (stamp(clock[0] - timedelta(seconds=1)),))
        db.execute('UPDATE managed_shun_registry SET restoration_suspended=1')
        db.execute('UPDATE protected_policy SET legacy_imported=1')
    path = tmp_path / 'public.json'
    path.write_text(json.dumps([{'id': 1, 'hostname': 'synthetic', 'management_ip': '192.0.2.1',
                                'ssh_host_key': 'ssh-ed25519 AAAA', 'allowed_interfaces': ['management']}]))
    before = fingerprint(store)
    report = inspection.inspect_database(store.path, path, now=clock[0])
    assert report['summary']['attempts'] == {outcome: 1}
    assert report['summary']['terminal_attempts_without_queue_evidence'] == int(prune and outcome != 'UNVERIFIED')
    assert ('MANAGED_ATTEMPT_ATTENTION' in report['blockers']) == (outcome in {'FAILED', 'UNVERIFIED'})
    assert report['tables']['managed_shun_targets']['rows'] == 1 and report['summary']['policy'] == {0: 1}
    assert not report['migration_ready'] and fingerprint(store) == before


def test_disabled_device_ids_are_retained_even_when_not_in_planned_executor_scope(source):
    store, path = source
    store.upsert_device(Device(2, 'disabled-fixture', IPv4Address('192.0.2.2'), False), 'ssh-ed25519 OTHER')
    assert 'PUBLIC_INVENTORY_DIFFERS' in inspect(source)['blockers']
    entries = json.loads(path.read_text())
    entries.append({'id': 2, 'hostname': 'disabled-fixture', 'management_ip': '192.0.2.2', 'enabled': False,
                    'ssh_host_key': 'ssh-ed25519 OTHER', 'allowed_interfaces': ['management']})
    path.write_text(json.dumps(entries))
    report = inspect(source)
    assert report['operational_preconditions_satisfied'] and report['target']['device_ids'] == [1]
    assert report['tables']['devices']['rows'] == 2


@pytest.mark.parametrize('value', [0, 11, True, '2', 2.0])
def test_requested_concurrency_is_literal_bounded_and_not_authority(source, value):
    before = fingerprint(source[0])
    with pytest.raises(ValueError, match='concurrency'): inspect(source, concurrency=value)
    assert fingerprint(source[0]) == before


def test_inventory_change_during_inspection_refuses_the_entire_report(source, monkeypatch):
    store, path = source
    original = inspection.inspect_snapshot
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        entries = json.loads(path.read_text())
        entries[0]['allowed_interfaces'].append('outside')
        path.write_text(json.dumps(entries))
        return report
    monkeypatch.setattr(inspection, 'inspect_snapshot', changed)
    before = fingerprint(store)
    with pytest.raises(ValueError, match='during inspection'): inspect(source)
    assert fingerprint(store) == before


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink'])
def test_database_nonregular_paths_are_refused_without_opening(source, tmp_path, kind):
    store, inventory = source
    path = tmp_path / 'not-regular.db'
    if kind == 'fifo': os.mkfifo(path)
    elif kind == 'directory': path.mkdir()
    else: path.symlink_to(store.path)
    with pytest.raises(ValueError, match='regular'): inspection.inspect_database(path, inventory, now=NOW)


@pytest.mark.parametrize('pragma', ['user_version', 'application_id'])
def test_source_header_metadata_is_bound_to_inspection(source, pragma):
    store, _path = source
    frozen = inspect(source)
    with store._connection() as db: db.execute(f'PRAGMA {pragma}=7')
    with pytest.raises(ValueError, match='changed'):
        inspect(source, reviewed_at=NOW, expected_digest=frozen['inspection_digest'])


@pytest.mark.parametrize('first,second', [(None, ''), (0, '0'), (1, 1.0), ('00', b'00'), (b'', '')])
def test_digest_values_are_typed_not_stringified_ambiguously(first, second):
    assert inspection._typed(first) != inspection._typed(second)


@pytest.mark.parametrize('state', ['WAITING_ADD', 'ADMITTING', 'ATTENTION'])
@pytest.mark.parametrize('kind', ['device', 'fleet'])
def test_retained_cleanup_barriers_block_even_when_no_job_is_pending(source, kind, state):
    store, _path = source
    with store._connection() as db:
        authority = db.execute('SELECT authorization_request_id FROM managed_shun_targets').fetchone()[0]
        key = str(uuid4())
        if kind == 'device':
            db.execute('INSERT INTO managed_removal_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (key, 1, IP.packed, str(uuid4()), 1, authority, str(uuid4()), 'fixture', 'Fixture', '[]',
                        '{}', '{}', stamp(NOW), stamp(NOW + timedelta(seconds=60)), state, None))
        else:
            db.execute('INSERT INTO managed_fleet_removals VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (key, authority, 'fixture', 'Fixture', '[]', '{}', '{}', stamp(NOW),
                        stamp(NOW + timedelta(seconds=60)), 'ADMITTED'))
            db.execute('INSERT INTO managed_fleet_waits VALUES (?,?,?,?,?)', (key, 1, '[]', state, None))
    before = fingerprint(store)
    report = inspect(source)
    assert 'UNFINISHED_' + kind.upper() + '_CLEANUP' in report['blockers']
    assert not report['migration_ready'] and fingerprint(store) == before


def test_broken_foreign_key_evidence_is_unavailable_not_empty(source):
    store, _path = source
    with store._connection() as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('UPDATE managed_shun_targets SET authorization_request_id=?', (str(uuid4()),))
    before = fingerprint(store)
    with pytest.raises(ValueError, match='integrity'): inspect(source)
    assert fingerprint(store) == before


def test_cli_reinspection_requires_both_original_fields_before_opening(source, monkeypatch):
    store, path = source
    monkeypatch.setattr(inspection, 'inspect_database', lambda *_a, **_k: pytest.fail('No storage read'))
    with pytest.raises(SystemExit) as error:
        inspection.main(['--database', str(store.path), '--inventory', str(path), '--confirm-offline',
                         '--inspection-digest', '0' * 64])
    assert error.value.code == 2
