"""Ordered queue promotion on disposable SQLite/fake sessions; no SSH or lab."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_ordered_waits import bulk as bulk_fixture
from test_bulk_ordered_waits import cancellation_controls as cancellation_fixture
from test_bulk_ordered_waits import dispatch as dispatch_fixture
from test_bulk_ordered_waits import journal as journal_fixture
from test_bulk_ordered_waits import leases as leases_fixture
from test_bulk_ordered_waits import ordered as ordered_fixture
from test_bulk_ordered_waits import reserve, review, running
from test_bulk_ordered_waits import waits as waits_fixture
from test_bulk_policy import dump
from test_continuous_dispatch import TracedAgent, until
from test_device_leases import grant

from ftd_shun_manager.agent_protocol import AdditionResult, ObservedShun
from ftd_shun_manager.bulk_ordered_promotion import SCOPE, BulkOrderedPromoter
from ftd_shun_manager.bulk_ordered_waits import captured
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.parallel_synchronizer import ParallelSynchronizer
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
ordered = ordered_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


@pytest.fixture
def promoter(ordered):
    service = BulkOrderedPromoter(ordered.store, ordered.queue)
    with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize(enabled=True)
    with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def setup(ordered, bulk, leases, *, devices=(1, 2), second=False):
    grant(bulk, devices=devices)
    first = running(bulk, leases)
    other = running(bulk, leases, device=2) if second else None
    frozen = review(ordered, bulk)
    result = reserve(ordered, frozen)
    return result, first, other, frozen


def finish(leases, worker, result=None, *, release=True):
    token, queue, job = worker
    queue.finish_addition(job['id'], token.owner, result or AdditionResult(False, None))
    if release: leases.release(token)  # Synthetic model of completed session settlement.


def test_disabled_missing_and_wrong_boolean_never_initialize(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = BulkOrderedPromoter(store, OperationQueue(store))
    assert service.advance() == 0 and not store.path.exists()
    with pytest.raises(ValueError): service.advance(enabled=1)
    with pytest.raises(PermissionError): service.initialize()
    with pytest.raises(BulkUnavailable): service.advance(enabled=True)
    assert not store.path.exists()


def test_actual_transfer_keeps_one_original_scope_deadline_and_actor(promoter, ordered, bulk, leases):
    result, first, _, frozen = setup(ordered, bulk, leases)
    finish(leases, first)
    original = reserve(ordered, frozen, key=result['operation_id'])
    bulk[1][0] += timedelta(seconds=11, milliseconds=750)
    assert promoter.advance(enabled=True) == 1
    status = ordered.status(result['operation_id'])
    assert status['state'] == 'ADMITTED' and status['device_work_admitted'] and not status['cleanup_reserved']
    assert [row['device_id'] for row in status['decision']['jobs']] == [1, 2]
    assert reserve(ordered, frozen, key=result['operation_id']) == original
    with ordered.store._connection() as db:
        request = db.execute('SELECT * FROM operation_requests WHERE id=?', (result['operation_id'],)).fetchone()
        assert request['requested_at'] == result['requested_at'] and request['expires_at'] == result['expires_at']
        assert request['actor_subject'] == 'synthetic:operator'
        assert json.loads(request['payload_json']) == {'scope': SCOPE, 'targets': [[1, str(IP)], [2, str(IP)]]}
        assert ordered.queue._pending_count(db) == 2 and ordered.queue._active_request_count(db) == 1
        assert ordered.queue._recent_request_count(db, 'synthetic:operator', bulk[1][0]) == 1
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    before = dump(ordered.store)
    assert promoter.advance(enabled=True) == 0 and dump(ordered.store) == before
    with pytest.raises(QueueConflict): ordered.cancel(result['operation_id'], 'synthetic:operator', 'Operator', ('Operator',))


def test_running_or_unreleased_completed_session_never_promotes_partial_fleet(promoter, ordered, bulk, leases):
    result, first, other, _ = setup(ordered, bulk, leases, devices=(1, 2, 3), second=True)
    before = dump(ordered.store)
    assert promoter.advance(enabled=True) == 0 and dump(ordered.store) == before
    finish(leases, first)
    assert promoter.advance(enabled=True) == 0
    finish(leases, other, release=False)
    assert promoter.advance(enabled=True) == 0
    assert ordered.status(result['operation_id'])['state'] == 'WAITING_ADD'
    leases.release(other[0])
    assert promoter.advance(enabled=True) == 1
    assert len(ordered.status(result['operation_id'])['decision']['jobs']) == 3


@pytest.mark.parametrize('outcome', ['FAILED', 'UNVERIFIED'])
def test_failed_unknown_whole_scope_attention_preserves_original_outcome(promoter, ordered, bulk, leases, outcome):
    result, first, _, frozen = setup(ordered, bulk, leases)
    finish(leases, first, outcome)
    ordered.store.record_observed_shun(1, IP, 'management')  # A later observation is not resolution.
    assert promoter.advance(enabled=True) == 1
    status = ordered.status(result['operation_id'])
    assert status['state'] == 'ATTENTION' and not status['device_work_admitted']
    with ordered.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (first[2]['id'],)).fetchone()[0] == outcome
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
    before = dump(ordered.store)
    assert promoter.advance(enabled=True) == 0 and dump(ordered.store) == before
    assert reserve(ordered, frozen, key=result['operation_id'])['state'] == 'WAITING_ADD'  # Original receipt.


@pytest.mark.parametrize('already_cancelled', [False, True])
def test_exact_prewrite_deferral_can_cancel_unsent_only_after_session_release(promoter, ordered, bulk, leases, already_cancelled):
    result, first, _, _ = setup(ordered, bulk, leases)
    token, queue, job = first
    queue.defer_addition(job['id'], token.owner)
    if already_cancelled: ordered.queue.cancel_obsolete_policy()
    assert promoter.advance(enabled=True) == 0
    leases.release(token)
    assert promoter.advance(enabled=True) == 1
    assert ordered.status(result['operation_id'])['state'] == 'ADMITTED'
    with ordered.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'CANCELLED'


@pytest.mark.parametrize('damage', ['disabled', 'scope', 'protection', 'claim', 'pending', 'fence', 'retirement'])
def test_changed_full_scope_or_evidence_is_attention_without_any_remove(promoter, ordered, bulk, leases, damage):
    result, first, _, frozen = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db:
        if damage == 'disabled': db.execute('UPDATE devices SET enabled=0 WHERE id=2')
        elif damage == 'claim': db.execute('DELETE FROM shun_events WHERE id=?', (frozen[1][0]['evidence']['claim_event_id'],))
        elif damage == 'pending':
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,2,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), IP.packed, stamp(bulk[1][0])))
        elif damage == 'retirement': db.execute('UPDATE managed_shun_targets SET revision=revision+1 WHERE device_id=2')
    if damage == 'scope': ordered.store.record_observed_shun(3, IP, 'management')
    elif damage == 'protection': ProtectedPolicy(ordered.store, initialize_queue=False).change(
        'add', IP, 0, 'synthetic:policy', 'Policy author', ('Viewer',), managed_revision=2)
    elif damage == 'fence':
        from test_device_leases import acquire
        acquire(leases, seconds=5)
        bulk[1][0] += timedelta(seconds=6)
    assert promoter.advance(enabled=True) == 1
    assert ordered.status(result['operation_id'])['state'] == 'ATTENTION'
    with ordered.store._connection() as db:
        assert not db.execute('SELECT 1 FROM operation_requests WHERE id=?', (result['operation_id'],)).fetchone()


def test_expiry_pause_cancellation_and_admitted_expiry_never_renew_authority(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(ordered.store)
    assert promoter.advance(enabled=True) == 0 and dump(ordered.store) == before
    with ordered.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    bulk[1][0] += timedelta(seconds=901)
    before = dump(ordered.store)
    assert promoter.advance(enabled=True) == 0 and dump(ordered.store) == before
    ordered.queue.expire_requests()
    assert ordered.status(result['operation_id'])['state'] == 'EXPIRED'
    assert promoter.advance(enabled=True) == 0


def test_continuous_owner_promotes_and_executes_actual_shared_fake_removals(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    agent = TracedAgent()
    agent.entries = {1: [ObservedShun(IP, 'management')], 2: [ObservedShun(IP, 'management')]}
    service = ContinuousDispatcher(ordered.store, agent, enabled=True, agent_concurrency=2, ordered_promotion_enabled=True)
    async def run():
        await service.start()
        try:
            def verified():
                with ordered.store._connection() as db:
                    return db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='VERIFIED'").fetchone()[0] == 2
            await until(verified)
            assert ordered.status(result['operation_id'])['state'] == 'ADMITTED'
            assert not any(kind == 'add' for kind, _, _ in agent.trace)
        finally:
            await service.stop()
    asyncio.run(run())


def test_migration_requires_pause_and_settled_reservations_preserving_receipts(ordered, bulk, leases, monkeypatch):
    from ftd_shun_manager import bulk_ordered_promotion
    service = BulkOrderedPromoter(ordered.store, ordered.queue)
    before = dump(ordered.store)
    with pytest.raises(QueueConflict): service.initialize(enabled=True)
    assert dump(ordered.store) == before
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
    with pytest.raises(ManagedConflict): service.initialize(enabled=True)
    ordered.cancel(result['operation_id'], 'synthetic:operator', 'Operator', ('Operator',))
    before = dump(ordered.store)
    original = bulk_ordered_promotion._state
    def fail(db):
        if bulk_ordered_promotion.present(db): raise BulkUnavailable('Synthetic final DDL failure.')
        return original(db)
    monkeypatch.setattr(bulk_ordered_promotion, '_state', fail)
    with ordered.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(BulkUnavailable): service.initialize(enabled=True, connection=db)
    assert dump(ordered.store) == before
    monkeypatch.setattr(bulk_ordered_promotion, '_state', original)
    service.initialize(enabled=True)
    after = dump(ordered.store)
    service.initialize(enabled=True)
    assert dump(ordered.store) == after


@pytest.mark.parametrize('failure', ['expiry', 'clock', 'audit', 'capacity'])
def test_late_failure_has_no_partial_queue_or_ticket(promoter, ordered, bulk, leases, monkeypatch, failure):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    original = ordered.store._insert_event
    def fail(db, event, *args, **kwargs):
        if event == 'MANAGED_ORDERED_REMOVAL_ADMITTED':
            if failure == 'expiry': bulk[1][0] += timedelta(seconds=901)
            elif failure == 'clock': bulk[1][0] -= timedelta(seconds=1)
            elif failure == 'audit': raise RuntimeError('Synthetic late audit failure.')
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(ordered.store, '_insert_event', fail)
    if failure == 'capacity': monkeypatch.setattr(ordered.queue, '_pending_count', lambda db: 1002)
    before = dump(ordered.store)
    if failure in {'clock', 'audit'}:
        with pytest.raises((QueueConflict, RuntimeError)): promoter.advance(enabled=True)
        assert dump(ordered.store) == before
    else:
        assert promoter.advance(enabled=True) == 1
        assert ordered.status(result['operation_id'])['state'] == 'ATTENTION'
    with ordered.store._connection() as db:
        assert not db.execute('SELECT 1 FROM operation_requests WHERE id=?', (result['operation_id'],)).fetchone()
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert not db.execute("SELECT 1 FROM managed_bulk_ordered_promotions WHERE state='ADMITTING'").fetchone()


def test_concurrent_promotion_is_once_and_reserved_budgets_are_not_charged_twice(promoter, ordered, bulk, leases, monkeypatch):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    original = ordered.queue._pending_count
    monkeypatch.setattr(ordered.queue, '_pending_count', lambda db: original(db) + 998)
    monkeypatch.setattr(ordered.queue, '_active_request_count', lambda db: 2000)
    monkeypatch.setattr(ordered.queue, '_recent_request_count', lambda *args: 10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: promoter.advance(enabled=True), range(2)))
    assert sum(outcomes) == 1
    assert ordered.status(result['operation_id'])['state'] == 'ADMITTED'
    with ordered.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 2


@pytest.mark.parametrize('damage', ['missing', 'bool_epoch', 'write_sent', 'duplicate', 'future', 'started'])
def test_deferral_requires_exact_original_proof(promoter, ordered, bulk, leases, damage):
    result, first, _, frozen = setup(ordered, bulk, leases)
    token, queue, job = first
    queue.defer_addition(job['id'], token.owner)
    leases.release(token)
    with ordered.store._connection() as db:
        event = db.execute("SELECT * FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_DEFERRED'",
                           (frozen[1][0]['evidence']['request_id'],)).fetchone()
        details = json.loads(event['details_json'])
        if damage == 'missing': db.execute('DELETE FROM shun_events WHERE id=?', (event['id'],))
        elif damage == 'duplicate':
            values = list(event)
            values[0] = str(uuid4())
            db.execute('INSERT INTO shun_events VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
        elif damage == 'future': db.execute('UPDATE shun_events SET timestamp=? WHERE id=?', (stamp(bulk[1][0] + timedelta(seconds=1)), event['id']))
        elif damage == 'started': db.execute('UPDATE operation_jobs SET started_at=? WHERE id=?', (stamp(bulk[1][0]), job['id']))
        else:
            if damage == 'bool_epoch': details['device_executor']['epoch'] = True
            else: details['write_sent'] = True
            db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(details), event['id']))
    assert promoter.advance(enabled=True) == 1
    assert ordered.status(result['operation_id'])['state'] == 'ATTENTION'
    with ordered.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'QUEUED'
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()


def test_scope_or_flag_without_ticket_cannot_delegate(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    before = dump(ordered.store)
    for enabled in (False, True, 1):
        with ordered.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with pytest.raises(ValueError):
                ordered.queue.apply_enqueue(db, result['operation_id'], [(1, IP), (2, IP)],
                    'synthetic:operator', 'Operator', ('Operator',), source='manual', scope=SCOPE,
                    bulk_ordered_removal_enabled=enabled)
    assert dump(ordered.store) == before


def test_incomplete_ticket_cannot_resume_expire_or_claim(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db:
        db.execute("INSERT INTO managed_bulk_ordered_promotions VALUES (?,'ADMITTING',?,'{}')",
                   (result['operation_id'], stamp(bulk[1][0])))
    bulk[1][0] += timedelta(seconds=901)
    before = dump(ordered.store)
    with pytest.raises(BulkUnavailable): promoter.advance(enabled=True)
    with pytest.raises(BulkUnavailable): promoter.require_storage()
    with pytest.raises(BulkUnavailable): ordered.queue.expire_requests()
    with pytest.raises(BulkUnavailable): ordered.status(result['operation_id'])
    assert dump(ordered.store) == before


def test_cleanup_jobs_original_delegation_and_deferral_survive_retention(promoter, ordered, bulk, leases):
    result, first, _, frozen = setup(ordered, bulk, leases)
    token, queue, _ = first
    queue.defer_addition(first[2]['id'], token.owner)
    leases.release(token)
    assert promoter.advance(enabled=True) == 1
    before = ordered.status(result['operation_id'])
    bulk[1][0] += timedelta(days=367)
    ordered.queue.expire_requests()
    ordered.queue.prune_completed(366)
    ordered.store.prune_expired_history(366, bulk[1][0])
    status = ordered.status(result['operation_id'])
    assert status['state'] == 'ADMITTED' and status['decision'] == before['decision']
    with ordered.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_DEFERRED'").fetchone()[0] == 1
        assert _state(db)['revision'] == 2
    assert reserve(ordered, frozen, key=result['operation_id'])['expires_at'] == result['expires_at']


def test_default_continuous_mode_never_promotes(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    with ordered.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    service = ContinuousDispatcher(ordered.store, TracedAgent(), enabled=True, agent_concurrency=2)
    async def run():
        await service.start()
        try:
            await until(lambda: service._completed_sessions >= 4)
            assert ordered.status(result['operation_id'])['state'] == 'WAITING_ADD'
        finally:
            await service.stop()
    asyncio.run(run())


def test_incomplete_ticket_partial_job_is_never_claimable(promoter, ordered, bulk, leases):
    from test_device_leases import acquire
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first)
    key, job_id = result['operation_id'], str(uuid4())
    with ordered.store._connection() as db:
        db.execute("INSERT INTO managed_bulk_ordered_promotions VALUES (?,'ADMITTING',?,'{}')", (key, stamp(bulk[1][0])))
        db.execute("INSERT INTO operation_requests VALUES (?,?,?,'[\"Operator\"]','manual',?,?,?,'ACTIVE')",
            (key, 'synthetic:operator', 'Actual synthetic operator', json.dumps({'scope': SCOPE, 'targets': [[1, str(IP)], [2, str(IP)]]}),
             result['requested_at'], result['expires_at']))
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,2,?,'QUEUED',?,'REMOVE')",
                   (job_id, IP.packed, stamp(bulk[1][0])))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job_id))
    token, queue = acquire(leases, device=2)
    before = dump(ordered.store)
    with pytest.raises(QueueConflict): queue.claim_removal(2, token.owner, queue.cutoff())
    assert dump(ordered.store) == before


def test_waiting_slow_root_does_not_starve_later_healthy_scope(promoter, ordered, bulk, leases):
    from ftd_shun_manager.bulk_ordered_waits import canonical_ordered_removal
    grant(bulk, count=2)
    first = running(bulk, leases)
    first_result = reserve(ordered, review(ordered, bulk))
    bulk[1][0] += timedelta(seconds=1)
    second = running(bulk, leases, device=2)
    second_ip = IPv4Address('198.51.100.2')
    value = ordered.scopes.snapshot(second_ip, device_id=2, now=bulk[1][0])
    predecessors = captured(value)
    second_result = ordered.reserve(str(uuid4()), value['scope'], predecessors,
        canonical_ordered_removal(value['scope'], predecessors)[1], 'synthetic:operator', 'Operator', ('Operator',), enabled=True)
    finish(leases, second)
    assert promoter.advance(enabled=True, limit=1) == 1
    assert ordered.status(first_result['operation_id'])['state'] == 'WAITING_ADD'
    assert ordered.status(second_result['operation_id'])['state'] == 'ADMITTED'
    with ordered.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (first[2]['id'],)).fetchone()[0] == 'RUNNING'


def test_attention_survives_waiting_revocation_and_age(promoter, ordered, bulk, leases):
    result, first, _, _ = setup(ordered, bulk, leases)
    finish(leases, first, 'UNVERIFIED')
    promoter.advance(enabled=True)
    ordered.cancel(result['operation_id'], 'synthetic:operator', 'Operator', ('Operator',))
    bulk[1][0] += timedelta(days=367)
    ordered.queue.prune_completed(366)
    status = ordered.status(result['operation_id'])
    assert status['state'] == 'CANCELLED' and status['attention'] and not status['cleanup_reserved']
    assert status['predecessors'][0]['state'] == 'UNVERIFIED'


def test_nonsettled_round_and_missing_profile_activation_refuse_before_work(promoter, ordered, leases):
    with ordered.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    runner = ParallelSynchronizer(ordered.store, TracedAgent(), enabled=True, agent_concurrency=2)
    before = dump(ordered.store)
    with pytest.raises(QueueConflict, match='strict local cycle settlement'): runner._configured_devices()
    assert dump(ordered.store) == before
