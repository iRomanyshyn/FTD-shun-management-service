"""Disposable durable ACK/observation evidence, no runtime enablement or FTD."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4

import pytest
from test_batch_queue import acknowledge
from test_bulk_policy import dump
from test_device_leases import acquire, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager import pending_confirmation
from ftd_shun_manager.agent_protocol import PendingAddition, SettledPendingAdditions
from ftd_shun_manager.batch_queue import BatchDeviceOperationQueue
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.pending_confirmation import PendingConfirmations

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


class SyntheticV7Queue(BatchDeviceOperationQueue):
    """Test-only audit producer; real queue/config must continue refusing v7."""

    def __init__(self, store, token):
        super().__init__(store, token, version=6)
        self.version = 7

    def _binding(self):
        return {**super()._binding(), 'version': 7}

    def _event(self, db, event, request, job, details=None):
        return super()._event(db, event, request, job, {**(details or {}), 'batch_session_version': 7})


@pytest.fixture
def ledger(leases):
    service = PendingConfirmations(leases.store, leases.queue)
    with leases.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize()
    with leases.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def stage(bulk, leases, *, count=2, version=7):
    grant(bulk, (1,), count=count)
    token, ordinary = acquire(leases)
    assert discover(bulk, ordinary) == count
    queue = SyntheticV7Queue(leases.store, token) if version == 7 else BatchDeviceOperationQueue(leases.store, token, version=version)
    jobs = [acknowledge(queue, n * 2 + 1) for n in range(count)]
    receipt = SettledPendingAdditions(1, UUID(token.owner).bytes, count * 2,
        tuple(PendingAddition(IPv4Address(job['ip']), n * 2 + 1) for n, job in enumerate(jobs)))
    return queue, jobs, receipt


def record(ledger, staged):
    queue, jobs, receipt = staged
    return ledger.record(queue.token, receipt, tuple(job['id'] for job in jobs), enabled=True)


def read(bulk, *, present=(), **changes):
    return replace(CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset(map(IPv4Address, present))), **changes)


def originals(store):
    with store._connection() as db:
        return tuple((table, tuple(tuple(row) for row in db.execute(f'SELECT * FROM {table}')))
                     for table in ('operation_jobs', 'operation_requests', 'managed_bulk_attempts',
                                   'managed_shun_targets', 'managed_shun_requests', 'shun_events',
                                   'managed_bulk_device_executors', 'shun_state'))


def test_explicit_profile_is_idempotent_and_reads_never_initialize(leases):
    ledger = PendingConfirmations(leases.store, leases.queue)
    before = dump(leases.store)
    with pytest.raises(BulkUnavailable):
        ledger.inspect(str(uuid4()))
    with pytest.raises(QueueConflict, match='Pause'):
        ledger.initialize()
    assert dump(leases.store) == before
    with leases.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    ledger.initialize()
    initialized = dump(leases.store)
    ledger.initialize()
    assert dump(leases.store) == initialized


def test_profile_requires_quiescence(leases):
    service = PendingConfirmations(leases.store, leases.queue)
    acquire(leases)
    with leases.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(leases.store)
    with pytest.raises(ManagedConflict, match='Settle every device'):
        service.initialize()
    assert dump(leases.store) == before


def test_profile_initialization_rolls_back_partial_schema(leases, monkeypatch):
    ledger = PendingConfirmations(leases.store, leases.queue)
    with leases.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(leases.store)
    original = pending_confirmation.execute_schema

    def fail(db, ddl):
        original(db, ddl)
        raise ValueError('Synthetic DDL failure')

    monkeypatch.setattr(pending_confirmation, 'execute_schema', fail)
    with pytest.raises(ValueError, match='Synthetic'):
        ledger.initialize()
    assert dump(leases.store) == before


def test_record_survives_restart_without_terminal_result_provenance_or_release(bulk, leases, ledger):
    staged = stage(bulk, leases)
    before = originals(ledger.store)
    session = record(ledger, staged)
    reopened = PendingConfirmations(ledger.store, leases.queue).inspect(session)
    assert [m['observation'] for m in reopened['members']] == ['AWAITING_CONFIRMATION'] * 2
    assert reopened['read'] is None
    assert reopened['session']['owner'] == staged[0].token.owner
    assert not reopened['can_retry'] and not reopened['can_release'] and not reopened['proves_creation']
    assert originals(ledger.store) == before
    with pytest.raises(QueueConflict, match='RUNNING'):
        leases.release(staged[0].token)
    with pytest.raises(QueueConflict, match='already retained'):
        record(ledger, staged)
    assert originals(ledger.store) == before


def test_first_complete_later_read_classifies_mixed_scope_without_claiming_success(bulk, leases, ledger):
    staged = stage(bulk, leases)
    session = record(ledger, staged)
    before = originals(ledger.store)
    bulk[1][0] += timedelta(seconds=1)
    snapshot = read(bulk, present=('198.51.100.1', '192.0.2.99'))
    expected = ((staged[1][0]['id'], 'OBSERVED_PRESENT'), (staged[1][1]['id'], 'CONFIRMED_ABSENT'))
    assert ledger.classify(session, snapshot, enabled=True) == expected
    first = dump(ledger.store)
    bulk[1][0] += timedelta(seconds=1)
    assert ledger.classify(session, snapshot, enabled=True) == expected  # Exact first-read replay, not new authority.
    assert dump(ledger.store) == first
    assert [m['observation'] for m in PendingConfirmations(ledger.store, leases.queue).inspect(session)['members']] == [
        'OBSERVED_PRESENT', 'CONFIRMED_ABSENT']
    assert originals(ledger.store) == before
    with pytest.raises(QueueConflict, match='immutable'):
        ledger.classify(session, read(bulk, present=('198.51.100.2',)), enabled=True)
    with pytest.raises(QueueConflict, match='shared snapshot identity'):
        ledger.classify(session, replace(snapshot, present_ips=frozenset()), enabled=True)


@pytest.mark.parametrize('revoke', ['cancel', 'protect'])
def test_settlement_and_observation_never_reenable_cancelled_or_protected_authority(
        bulk, leases, ledger, cancellation_controls, revoke):
    from test_bulk_cancellations import cancel
    from test_bulk_protection import protect

    from ftd_shun_manager.protected_policy import ProtectedPolicy

    staged = stage(bulk, leases)
    with ledger.store._connection() as db:
        root = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts LIMIT 1').fetchone()[0]
    if revoke == 'cancel':
        cancel(cancellation_controls, root)
    else:
        protect(ProtectedPolicy(ledger.store))
    before = originals(ledger.store)
    session = record(ledger, staged)
    bulk[1][0] += timedelta(seconds=1)
    ledger.classify(session, read(bulk), enabled=True)
    assert originals(ledger.store) == before
    with ledger.store._connection() as db:
        if revoke == 'protect':
            assert db.execute('SELECT enabled FROM managed_shun_targets WHERE ip=?',
                              (IPv4Address('198.51.100.1').packed,)).fetchone()[0] == 0
        else:
            # RUNNING cancellation retains its existing ordered wait; this
            # evidence-only hook must not finish or discard that wait itself.
            assert db.execute('SELECT COUNT(*) FROM managed_bulk_cancellations WHERE import_id=?', (root,)).fetchone()[0] == 1


def test_optional_profile_coexists_with_retained_recovery_profiles(leases, ledger):
    from ftd_shun_manager.device_reconciliation import DDL as reconciliation
    from ftd_shun_manager.device_recovery import DDL as recovery
    from ftd_shun_manager.extended_recovery import DDL as extended
    from ftd_shun_manager.schema import execute_schema

    with leases.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for ddl in (recovery, reconciliation, extended):
            execute_schema(db, ddl)
        assert _state(db) is not None and pending_confirmation.present(db)


@pytest.mark.parametrize('fault', ['partial', 'not_literal_complete', 'other_device', 'same_time', 'before_settlement',
                                  'starts_before_ends_after', 'future', 'reversed_time', 'stale', 'naive', 'wrong_ip_type',
                                  'mutable_scope', 'bad_id', 'unknown_session', 'oversized'])
def test_bad_read_never_classifies_or_changes_old_work(bulk, leases, ledger, fault, monkeypatch):
    session = record(ledger, stage(bulk, leases))
    settled = bulk[1][0]
    bulk[1][0] += timedelta(seconds=2)
    snapshot = read(bulk)
    if fault == 'partial': snapshot = replace(snapshot, complete=False)
    if fault == 'not_literal_complete': snapshot = replace(snapshot, complete=1)
    if fault == 'other_device': snapshot = replace(snapshot, device_id=2)
    if fault == 'same_time': snapshot = replace(snapshot, started_at=settled)
    if fault == 'before_settlement': snapshot = replace(snapshot, started_at=settled-timedelta(seconds=1), completed_at=settled)
    if fault == 'starts_before_ends_after': snapshot = replace(snapshot, started_at=settled-timedelta(seconds=1))
    if fault == 'future': snapshot = replace(snapshot, completed_at=bulk[1][0]+timedelta(seconds=1))
    if fault == 'reversed_time': snapshot = replace(snapshot, completed_at=bulk[1][0]-timedelta(seconds=1))
    if fault == 'stale':
        bulk[1][0] += timedelta(seconds=121)
    if fault == 'naive': snapshot = replace(snapshot, started_at=snapshot.started_at.replace(tzinfo=None))
    if fault == 'wrong_ip_type': snapshot = replace(snapshot, present_ips=frozenset({'198.51.100.1'}))
    if fault == 'mutable_scope': snapshot = replace(snapshot, present_ips=set())
    if fault == 'bad_id': snapshot = replace(snapshot, id='not-an-id')
    if fault == 'unknown_session': session = str(uuid4())
    if fault == 'oversized':
        monkeypatch.setattr(pending_confirmation, 'MAX_SNAPSHOT_ENTRIES', 1)
        snapshot = replace(snapshot, present_ips=frozenset(map(IPv4Address, ('192.0.2.1', '192.0.2.2'))))
    before = dump(ledger.store)
    with pytest.raises((ValueError, QueueConflict)):
        ledger.classify(session, snapshot, enabled=True)
    assert dump(ledger.store) == before


@pytest.mark.parametrize('fault', ['old_version', 'wrong_owner', 'wrong_epoch', 'expired', 'wrong_device', 'missing_job',
                                  'reordered_jobs', 'reordered_ack', 'duplicate_ack', 'wrong_sequence', 'wrong_session',
                                  'empty', 'extra_running', 'missing_ack', 'foreign_group', 'missing_claim', 'root_damage'])
def test_bad_binding_cannot_become_durable_settlement(bulk, leases, ledger, fault):
    queue, jobs, receipt = stage(bulk, leases, version=6 if fault == 'old_version' else 7)
    token = queue.token
    job_ids = tuple(job['id'] for job in jobs)
    if fault == 'wrong_owner': token = replace(token, owner=str(uuid4()))
    if fault == 'wrong_epoch': token = replace(token, epoch=token.epoch+1)
    if fault == 'expired': bulk[1][0] += timedelta(seconds=136)
    if fault == 'wrong_device': receipt = replace(receipt, device_id=2)
    if fault == 'missing_job': job_ids = (job_ids[0], str(uuid4()))
    if fault == 'reordered_jobs': job_ids = job_ids[::-1]
    if fault == 'reordered_ack': receipt = replace(receipt, acknowledgements=receipt.acknowledgements[::-1])
    if fault == 'duplicate_ack': receipt = replace(receipt, acknowledgements=(receipt.acknowledgements[0],)*2)
    if fault == 'wrong_sequence': receipt = replace(receipt, sequence=1)
    if fault == 'wrong_session': receipt = replace(receipt, session_id=uuid4().bytes)
    if fault == 'empty': receipt = replace(receipt, acknowledgements=())
    if fault == 'extra_running': job_ids, receipt = (job_ids[0],), replace(receipt, acknowledgements=receipt.acknowledgements[:1])
    with ledger.store._connection() as db:
        if fault in ('missing_ack', 'foreign_group', 'missing_claim'):
            # Corruption tests deliberately remove immutable-event guards on a disposable DB only.
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='shun_events'").fetchall():
                db.execute(f'DROP TRIGGER {row[0]}')
            if fault == 'foreign_group':
                row = db.execute("SELECT id,details_json FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED' LIMIT 1").fetchone()
                detail = json.loads(row['details_json'])
                detail['batch_session']['group'] = str(uuid4())
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(detail), row['id']))
            else:
                kind = 'SHUN_ADDITION_ACKNOWLEDGED' if fault == 'missing_ack' else 'SHUN_OPERATION_RUNNING'
                db.execute('DELETE FROM shun_events WHERE id=(SELECT id FROM shun_events WHERE event_type=? LIMIT 1)', (kind,))
        if fault == 'root_damage':
            db.execute('DROP TRIGGER managed_bulk_manifest_immutable')
            db.execute("UPDATE managed_bulk_manifests SET payload_digest=?", ('0'*64,))
    before = dump(ledger.store)
    with pytest.raises((ValueError, QueueConflict, BulkUnavailable)):
        ledger.record(token, receipt, job_ids, enabled=True)
    assert dump(ledger.store) == before


def test_sixteen_member_scope_and_capacity_are_atomic(bulk, leases, ledger, monkeypatch):
    staged = stage(bulk, leases, count=16)
    monkeypatch.setattr(pending_confirmation, 'MAX_MEMBERS', 15)
    before = dump(ledger.store)
    with pytest.raises(BulkUnavailable, match='capacity'):
        record(ledger, staged)
    assert dump(ledger.store) == before
    monkeypatch.setattr(pending_confirmation, 'MAX_MEMBERS', 16)
    assert len(ledger.inspect(record(ledger, staged))['members']) == 16


@pytest.mark.parametrize('table', ['managed_bulk_pending_sessions', 'managed_bulk_pending_members', 'managed_bulk_pending_reads'])
@pytest.mark.parametrize('operation', ['UPDATE', 'DELETE'])
def test_all_ledger_evidence_is_immutable_and_retained(bulk, leases, ledger, table, operation):
    session = record(ledger, stage(bulk, leases))
    bulk[1][0] += timedelta(seconds=1)
    ledger.classify(session, read(bulk), enabled=True)
    before = dump(ledger.store)
    with ledger.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(f'{operation} {"FROM" if operation == "DELETE" else ""} {table}' +
                   (' SET rowid=rowid' if operation == 'UPDATE' else ''))
    assert dump(ledger.store) == before


def test_missing_optional_trigger_refuses_reads_without_repair(bulk, leases, ledger):
    session = record(ledger, stage(bulk, leases))
    with ledger.store._connection() as db:
        db.execute('DROP TRIGGER managed_bulk_pending_read_immutable')
    before = dump(ledger.store)
    with pytest.raises(BulkUnavailable, match='Exact version-2'):
        ledger.inspect(session)
    assert dump(ledger.store) == before


def test_last_lease_check_rolls_back_complete_ledger_and_preserves_original_jobs(bulk, leases, ledger, monkeypatch):
    staged = stage(bulk, leases)
    before = dump(ledger.store)
    original = pending_confirmation.DeviceLeases.check
    calls = []

    def expire_on_final_check(self, db, token):
        calls.append(token)
        if len(calls) == 2:
            bulk[1][0] += timedelta(seconds=136)
        return original(self, db, token)

    monkeypatch.setattr(pending_confirmation.DeviceLeases, 'check', expire_on_final_check)
    with pytest.raises(QueueConflict, match='deadline'):
        record(ledger, staged)
    assert len(calls) == 2 and dump(ledger.store) == before


@pytest.mark.parametrize('fault', ['invalid_ordinals', 'out_of_scope', 'boolean_ordinal', 'corrupt_ack', 'corrupt_sequence'])
def test_retained_corruption_refuses_inspection_not_synthetic_success(bulk, leases, ledger, fault):
    session = record(ledger, stage(bulk, leases))
    bulk[1][0] += timedelta(seconds=1)
    ledger.classify(session, read(bulk), enabled=True)
    with ledger.store._connection() as db:
        if fault.startswith('corrupt_'):
            # Exact ledger schema remains; original immutable audit is deliberately damaged.
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='shun_events'").fetchall():
                db.execute(f'DROP TRIGGER {row[0]}')
            field, value = ('$.batch_session.owner', 'foreign') if fault == 'corrupt_ack' else ('$.sequence', 120)
            db.execute('''UPDATE shun_events SET details_json=json_set(details_json,?,?)
                WHERE id=(SELECT ack_event_id FROM managed_bulk_pending_members LIMIT 1)''', (field, value))
        else:
            # Bypass only this disposable immutable trigger, then restore its exact DDL.
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_pending_read_immutable'").fetchone()[0]
            db.execute('DROP TRIGGER managed_bulk_pending_read_immutable')
            invalid = {'invalid_ordinals': '[1,0]', 'out_of_scope': '[2]', 'boolean_ordinal': '[true]'}[fault]
            db.execute('UPDATE managed_bulk_pending_reads SET present_ordinals_json=?', (invalid,))
            db.execute(sql)
    before = dump(ledger.store)
    with pytest.raises(BulkUnavailable, match='pending'):
        ledger.inspect(session)
    assert dump(ledger.store) == before


def test_disabled_composition_never_mutates_or_initializes(leases):
    ledger = PendingConfirmations(leases.store, leases.queue)
    before = dump(ledger.store)
    with pytest.raises(PermissionError):
        ledger.record(None, None, None)
    with pytest.raises(PermissionError):
        ledger.classify(None, None)
    with leases.store._connection() as db:
        assert _state(db) is not None and not pending_confirmation.present(db)
    assert dump(ledger.store) == before
