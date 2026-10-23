"""Read-only ordered inspection on disposable storage; no SSH or lab writes."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_policy import confirm, dump, prepare, retire
from test_device_leases import acquire, claim, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_ordered_removals import BulkOrderedRemovalScopes
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_removals import BulkRemovals, canonical_removal
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


@pytest.fixture
def inspector(bulk, leases):
    return BulkOrderedRemovalScopes(bulk[0].store)


def inspect(inspector, bulk, **kwargs):
    return inspector.snapshot(IP, now=bulk[1][0], **kwargs)


def running(bulk, leases, *, device=1):
    token, queue = acquire(leases, device)
    discover(bulk, queue)
    job = claim(queue)
    assert job is not None
    return token, queue, job


def test_no_creation_initialization_or_admission_method(tmp_path):
    store = Store(tmp_path / 'absent.db')
    inspector = BulkOrderedRemovalScopes(store)
    assert not hasattr(inspector, 'admit') and not hasattr(inspector, 'initialize')
    with pytest.raises(sqlite3.OperationalError): inspector.snapshot(IP)
    assert not store.path.exists()


@pytest.mark.parametrize('now', [True, '2026-10-23', datetime(2026, 10, 23),
                                 datetime(2026, 10, 23, tzinfo=timezone(timedelta(hours=3)))])
def test_literal_utc_inspection_time_required_before_storage(tmp_path, now):
    store = Store(tmp_path / 'absent.db')
    with pytest.raises(ValueError): BulkOrderedRemovalScopes(store).snapshot(IP, now=now)
    assert not store.path.exists()


def test_requires_existing_exact_fenced_profile(bulk):
    confirm(bulk, prepare(bulk)[1])
    before = dump(bulk[0].store)
    with pytest.raises(BulkUnavailable): inspect(BulkOrderedRemovalScopes(bulk[0].store), bulk)
    assert dump(bulk[0].store) == before


def test_ready_union_is_detached_read_only_and_digest_separate(inspector, bulk, monkeypatch):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    inspector.store.record_observed_shun(3, IP, 'management')
    inspector.store.record_observed_shun(3, IP, 'outside')
    before = dump(inspector.store)
    def forbidden(*_args, **_kwargs): raise AssertionError('No initialization or admission during inspection.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'apply_enqueue', forbidden)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'READY' and value['waiting_target_count'] == value['blocked_target_count'] == 0
    assert [row['device_id'] for row in value['targets']] == [1, 2, 3]
    assert value['scope']['targets'][2]['intent_id'] is None
    assert value['read_only'] and not value['execution_available'] and not value['device_work_admitted']
    assert len(value['preflight_digest']) == 64
    assert value['preflight_digest'] not in {value['scope_digest'], canonical_removal(value['scope'])[1]}
    assert inspect(inspector, bulk) == value
    value['scope']['targets'][0]['hostname'] = 'not retained'
    value['targets'][0]['blockers'].append('not retained')
    assert inspect(inspector, bulk)['targets'][0]['blockers'] == []
    assert dump(inspector.store) == before


def test_exact_running_predecessor_captures_original_authority_deadline_and_epoch(inspector, bulk, leases):
    root = grant(bulk)
    token, queue, job = running(bulk, leases)
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'WAITING_ADD' and value['waiting_target_count'] == 1
    assert [row['disposition'] for row in value['targets']] == ['WAITING_ADD', 'READY']
    predecessor = value['targets'][0]['predecessor']
    assert predecessor['job_id'] == job['id'] and predecessor['request_id'] != root
    assert predecessor['authorization_request_id'] == root and predecessor['generation'] == 1
    assert predecessor['executor_owner'] == token.owner and predecessor['executor_epoch'] == token.epoch
    assert predecessor['expires_at'] == stamp(bulk[1][0] + timedelta(seconds=900))
    assert predecessor['lease_until'] == stamp(bulk[1][0] + timedelta(seconds=135))
    assert len(predecessor['evidence_digest']) == 64 and predecessor['claim_event_id']
    assert dump(inspector.store) == before
    with pytest.raises(QueueConflict):
        BulkRemovals(inspector.store, OperationQueue(inspector.store)).admit(str(uuid4()), value['scope'],
            canonical_removal(value['scope'])[1], 'synthetic:operator', 'Operator', ('Operator',), enabled=True)
    assert dump(inspector.store) == before
    with queue.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0


def test_fleet_waits_for_both_actual_parallel_running_adds(inspector, bulk, leases):
    grant(bulk, devices=(1, 2, 3))
    first = running(bulk, leases)
    second = running(bulk, leases, device=2)
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['waiting_target_count'] == 2 and value['disposition'] == 'WAITING_ADD'
    assert [row['disposition'] for row in value['targets']] == ['WAITING_ADD', 'WAITING_ADD', 'READY']
    assert dump(inspector.store) == before
    first[1].finish_addition(first[2]['id'], first[0].owner, AdditionResult(False, None))
    value = inspect(inspector, bulk)
    assert value['waiting_target_count'] == 1 and value['disposition'] == 'WAITING_ADD'
    assert value['targets'][1]['predecessor']['job_id'] == second[2]['id']


@pytest.mark.parametrize('outcome', ['VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'DEFERRED'])
def test_reinspection_never_settles_retries_or_promotes_any_result(inspector, bulk, leases, outcome):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    original = inspect(inspector, bulk)
    if outcome == 'DEFERRED': queue.defer_addition(job['id'], token.owner)
    else:
        result = AdditionResult(True, 'management') if outcome == 'VERIFIED' else AdditionResult(False, None) if outcome == 'NOOP' else outcome
        queue.finish_addition(job['id'], token.owner, result)
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['preflight_digest'] != original['preflight_digest']
    assert value['disposition'] == ('READY' if outcome in {'VERIFIED', 'NOOP'} else 'BLOCKED')
    assert value['targets'][0]['predecessor'] is None
    if outcome == 'DEFERRED': assert 'ADD_NOT_RUNNING' in value['targets'][0]['blockers']
    if outcome == 'UNVERIFIED': assert 'DEVICE_OUTCOME_UNKNOWN' in value['targets'][0]['blockers']
    assert dump(inspector.store) == before
    with inspector.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 2


@pytest.mark.parametrize('damage', ['deadline', 'cancelled', 'link', 'dispatch', 'started', 'future',
                                     'claim_missing', 'claim_duplicate', 'claim_owner', 'claim_epoch',
                                     'claim_epoch_bool', 'claim_action', 'claim_json', 'claim_oversize'])
def test_damaged_running_binding_never_becomes_waitable(inspector, bulk, leases, damage):
    grant(bulk)
    _, _, job = running(bulk, leases)
    with inspector.store._connection() as db:
        request = db.execute('SELECT request_id FROM operation_links WHERE job_id=?', (job['id'],)).fetchone()[0]
        if damage == 'deadline': db.execute('UPDATE operation_requests SET expires_at=? WHERE id=?', (stamp(bulk[1][0]), request))
        elif damage == 'cancelled': db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (request,))
        elif damage == 'link': db.execute('DELETE FROM operation_links WHERE job_id=?', (job['id'],))
        elif damage == 'dispatch': db.execute("UPDATE operation_jobs SET dispatch_kind='REMOVE' WHERE id=?", (job['id'],))
        elif damage == 'started': db.execute('UPDATE operation_jobs SET started_at=NULL WHERE id=?', (job['id'],))
        elif damage == 'future': db.execute('UPDATE operation_jobs SET started_at=? WHERE id=?', (stamp(bulk[1][0] + timedelta(seconds=1)), job['id']))
        else:
            event = db.execute("SELECT * FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_RUNNING'", (request,)).fetchone()
            if damage == 'claim_missing': db.execute('DELETE FROM shun_events WHERE id=?', (event['id'],))
            elif damage == 'claim_duplicate':
                values = list(event)
                values[0] = str(uuid4())
                db.execute('INSERT INTO shun_events VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
            else:
                details = json.loads(event['details_json'])
                if damage == 'claim_owner': details['device_executor']['owner'] = str(uuid4())
                elif damage == 'claim_epoch': details['device_executor']['epoch'] += 1
                elif damage == 'claim_epoch_bool': details['device_executor']['epoch'] = True
                elif damage == 'claim_action': details['action'] = 'REMOVE'
                text = '{' if damage == 'claim_json' else ' ' * 16385 if damage == 'claim_oversize' else json.dumps(details)
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (text, event['id']))
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'BLOCKED' and value['waiting_target_count'] == 0
    assert value['targets'][0]['blockers'] == ['ADD_BINDING_UNAVAILABLE']
    assert value['targets'][1]['disposition'] == 'READY'
    assert dump(inspector.store) == before


@pytest.mark.parametrize('blocker', ['paused', 'disabled', 'outside', 'expired', 'attention', 'retired', 'queued', 'remove'])
def test_explicit_blockers_never_shrink_or_change_the_scope(inspector, bulk, leases, blocker):
    if blocker in {'queued', 'remove', 'outside'}:
        confirm(bulk, prepare(bulk, devices=(1, 2, 5) if blocker == 'outside' else (1, 2))[1])
        if blocker == 'remove':
            OperationQueue(inspector.store).enqueue(str(uuid4()), [(1, IP)], 'synthetic:operator', 'Operator', ('Operator',), source='trusted_policy')
        elif blocker == 'queued':
            with inspector.store._connection() as db:
                db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'ADD')", (str(uuid4()), IP.packed, stamp(bulk[1][0])))
    else:
        grant(bulk)
        running(bulk, leases)
        if blocker == 'retired': retire(bulk)
        elif blocker in {'expired', 'attention'}:
            bulk[1][0] += timedelta(seconds=136)
            if blocker == 'attention': leases.claim(1, str(uuid4()), 135, enabled=True)
        else:
            with inspector.store._connection() as db:
                if blocker == 'paused': db.execute('UPDATE operation_executor SET mutations_suspended=1')
                else: db.execute('UPDATE devices SET enabled=0 WHERE id=1')
    before = dump(inspector.store)
    value = inspect(inspector, bulk, device_id=1 if blocker == 'retired' else None)
    assert value['disposition'] == 'BLOCKED'
    codes = {'paused': 'MUTATIONS_PAUSED', 'disabled': 'DEVICE_DISABLED', 'outside': 'DEVICE_OUTSIDE_EXECUTOR_SCOPE',
             'expired': 'DEVICE_FENCE_EXPIRED', 'attention': 'DEVICE_FENCE_ATTENTION', 'retired': 'ADD_BINDING_UNAVAILABLE',
             'queued': 'ADD_NOT_RUNNING', 'remove': 'PENDING_REMOVE'}
    assert codes[blocker] in value['global_blockers'] + [code for row in value['targets'] for code in row['blockers']]
    assert dump(inspector.store) == before


def test_missing_pending_evidence_fails_closed_not_empty(inspector, bulk, leases):
    grant(bulk)
    _, _, job = running(bulk, leases)
    with inspector.store._connection() as db: db.execute('DELETE FROM operation_jobs WHERE id=?', (job['id'],))
    before = dump(inspector.store)
    with pytest.raises((BulkUnavailable, ManagedStateUnavailable)): inspect(inspector, bulk)
    assert dump(inspector.store) == before


def test_claim_from_old_epoch_cannot_bind_a_new_executor(inspector, bulk, leases):
    grant(bulk)
    token, _, _ = running(bulk, leases)
    with inspector.store._connection() as db:
        # Deliberately corrupt a disposable fixture, not a lease release API.
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")
        db.execute("UPDATE managed_bulk_device_executors SET state='LEASED',owner=?,epoch=epoch+1,lease_until=? WHERE device_id=1",
                   (token.owner, stamp(bulk[1][0] + timedelta(seconds=135))))
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['targets'][0]['blockers'] == ['ADD_BINDING_UNAVAILABLE']
    assert dump(inspector.store) == before


def test_snapshot_does_not_mix_concurrent_completion_and_original_running_claim(inspector, bulk, leases, monkeypatch):
    grant(bulk)
    token, queue, job = running(bulk, leases)
    original = inspector._target
    calls = []
    def complete(db, target, ip, now):
        if not calls:
            calls.append(True)
            queue.finish_addition(job['id'], token.owner, AdditionResult(False, None))
        return original(db, target, ip, now)
    monkeypatch.setattr(inspector, '_target', complete)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'WAITING_ADD'  # Original consistent snapshot.
    assert inspect(inspector, bulk)['disposition'] == 'READY'


def test_expired_inspection_keeps_running_job_and_original_deadline(inspector, bulk, leases):
    grant(bulk)
    _, _, job = running(bulk, leases)
    original = inspect(inspector, bulk)['targets'][0]['predecessor']
    bulk[1][0] += timedelta(seconds=901)
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'BLOCKED' and value['targets'][0]['predecessor'] is None
    assert dump(inspector.store) == before
    with inspector.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert db.execute('SELECT expires_at FROM operation_requests WHERE id=?', (original['request_id'],)).fetchone()[0] == original['expires_at']


def test_current_device_unknown_on_another_pair_blocks_the_whole_fleet(inspector, bulk):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    with inspector.store._connection() as db:
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action)
            VALUES (?,2,?,'RECONCILED_ABSENT',?,'ADD')""", (str(uuid4()), IPv4Address('198.51.100.99').packed, stamp(bulk[1][0])))
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'BLOCKED'
    assert value['targets'][0]['disposition'] == 'READY'
    assert value['targets'][1]['blockers'] == ['DEVICE_OUTCOME_UNKNOWN']
    assert dump(inspector.store) == before


def test_duplicate_device_stream_is_not_a_valid_single_predecessor(inspector, bulk, leases):
    grant(bulk)
    running(bulk, leases)
    with inspector.store._connection() as db:
        # Invalid stream state must not be hidden by selecting only this IP.
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action,dispatch_kind)
            VALUES (?,1,?,'RUNNING',?,'ADD','ADD')""", (str(uuid4()), IPv4Address('198.51.100.99').packed, stamp(bulk[1][0])))
    before = dump(inspector.store)
    value = inspect(inspector, bulk)
    assert value['disposition'] == 'BLOCKED'
    assert value['targets'][0]['blockers'] == ['ADD_BINDING_UNAVAILABLE']
    assert dump(inspector.store) == before
