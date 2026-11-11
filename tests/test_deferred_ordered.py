"""Captured RUNNING cleanup survives settled-v7 handoff; disposable stores only."""

import asyncio
import json
from datetime import timedelta
from ipaddress import IPv4Address
from time import monotonic
from uuid import UUID

import pytest
from test_batch_queue import acknowledge
from test_bulk_ordered_waits import reserve, review
from test_bulk_policy import dump
from test_continuous_dispatch import until
from test_deferred_worker import Agent
from test_device_leases import acquire, discover, grant
from test_pending_confirmation import SyntheticV7Queue, read
from test_pending_execution import bulk as bulk_fixture
from test_pending_execution import cancellation_controls as cancellation_fixture
from test_pending_execution import dispatch as dispatch_fixture
from test_pending_execution import execution as execution_fixture
from test_pending_execution import journal as journal_fixture
from test_pending_execution import leases as leases_fixture
from test_pending_execution import ledger as ledger_fixture
from test_pending_execution import waits as waits_fixture

from ftd_shun_manager.agent_protocol import PendingAddition, SettledPendingAdditions
from ftd_shun_manager.bulk_ordered_promotion import BulkOrderedPromoter
from ftd_shun_manager.bulk_ordered_review import validate_ordered_status
from ftd_shun_manager.bulk_ordered_waits import BulkOrderedWaits
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.deferred_dispatch import DeferredContinuousDispatcher
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


@pytest.fixture
def ordered(execution):
    service = BulkOrderedWaits(execution.store, execution.queue)
    promoter = BulkOrderedPromoter(execution.store, execution.queue)
    with execution.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize(enabled=True)
    promoter.initialize(enabled=True)
    with execution.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service, promoter


def captured(bulk, leases, ordered, *, fleet=False):
    grant(bulk, (1, 2) if fleet else (1,))
    token, ordinary = acquire(leases)
    assert discover(bulk, ordinary) == 1
    queue = SyntheticV7Queue(leases.store, token)
    job = acknowledge(queue, 1)
    frozen = review(ordered[0], bulk, device=None if fleet else 1)
    receipt = reserve(ordered[0], frozen)
    terminal = SettledPendingAdditions(1, UUID(token.owner).bytes, 2, (PendingAddition(IP, 1),))
    return queue, job, terminal, receipt, frozen


@pytest.mark.parametrize('present', [True, False])
@pytest.mark.parametrize('fleet', [False, True])
def test_waits_for_original_handoff_and_observation_then_delegates_exact_cleanup(bulk, leases, execution, ordered, present, fleet):
    queue, job, terminal, receipt, frozen = captured(bulk, leases, ordered, fleet=fleet)
    key = receipt['operation_id']
    assert ordered[1].advance(enabled=True) == 0
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    assert leases.status()['devices'][0]['state'] == 'IDLE'
    before = dump(execution.store)
    assert ordered[1].advance(enabled=True) == 0
    assert dump(execution.store) == before
    pending = validate_ordered_status(key, ordered[0].status(key))
    assert pending['state'] == 'WAITING_ADD' and not pending['attention']
    assert pending['predecessors'][0]['state'] == 'AWAITING_CONFIRMATION'
    assert not pending['cleanup_jobs']
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),) if present else ()), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 1
    value = validate_ordered_status(key, ordered[0].status(key))
    assert value['state'] == 'ADMITTED' and not value['verified_removal']
    assert [row['device_id'] for row in value['cleanup_jobs']] == ([1, 2] if fleet else [1])
    assert value['expires_at'] == receipt['expires_at']
    assert value['predecessors'][0]['state'] == ('OBSERVED_PRESENT' if present else 'CONFIRMED_ABSENT')
    with execution.store._connection() as db:
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='ADD'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == (2 if fleet else 1)
    after = dump(execution.store)
    assert ordered[1].advance(enabled=True) == 0 and dump(execution.store) == after
    assert reserve(ordered[0], frozen, key=key)['replayed'] and dump(execution.store) == after


@pytest.mark.parametrize('cancel', [False, True])
def test_expiry_and_revocation_never_restore_policy_or_admit_cleanup(bulk, leases, execution, ordered, cancel):
    queue, job, terminal, receipt, _ = captured(bulk, leases, ordered)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    if cancel:
        ordered[0].cancel(receipt['operation_id'], 'synthetic:operator', 'Actual synthetic operator', ('Operator',))
    bulk[1][0] += timedelta(seconds=1 if cancel else 901)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 0
    with execution.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()


def test_reopen_preserves_wait_and_requires_causal_complete_confirmation(bulk, leases, execution, ordered):
    queue, job, terminal, receipt, _ = captured(bulk, leases, ordered)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    restarted = BulkOrderedPromoter(execution.store, execution.queue)
    assert restarted.advance(enabled=True) == 0
    token, _ = acquire(leases)
    before = dump(execution.store)
    with pytest.raises(QueueConflict, match='strictly after'):
        execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    assert dump(execution.store) == before and restarted.advance(enabled=True) == 0
    assert ordered[0].status(receipt['operation_id'])['state'] == 'WAITING_ADD'


def test_missing_original_pending_evidence_fails_closed(bulk, leases, execution, ordered):
    queue, job, terminal, _, _ = captured(bulk, leases, ordered)
    execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    with execution.store._connection() as db:
        name = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='managed_bulk_pending_members' LIMIT 1").fetchone()[0]
        db.execute('DROP TRIGGER ' + name)
    before = dump(execution.store)
    with pytest.raises(BulkUnavailable): ordered[1].advance(enabled=True)
    assert dump(execution.store) == before


def test_no_profile_initialization_at_dispatcher_start(tmp_path):
    from ftd_shun_manager.store import Store

    store = Store(tmp_path / 'absent.db')
    service = DeferredContinuousDispatcher(store, Agent(), enabled=True, ordered_promotion_enabled=True)
    with pytest.raises((BulkUnavailable, QueueConflict)):
        asyncio.run(service.start())
    assert not store.path.exists()


def test_status_does_not_accept_deferred_remove_outcomes(bulk, leases, execution, ordered):
    queue, job, terminal, receipt, _ = captured(bulk, leases, ordered)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    ordered[1].advance(enabled=True)
    value = json.loads(json.dumps(ordered[0].status(receipt['operation_id'])))
    value['cleanup_jobs'][0]['state'] = 'OBSERVED_PRESENT'
    with pytest.raises(ValueError, match='REMOVE outcome'):
        validate_ordered_status(receipt['operation_id'], value)
    with execution.store._connection() as db:
        assert _state(db) is not None


@pytest.mark.parametrize('change', ['device', 'protection', 'pause'])
def test_current_guards_still_apply_after_deferred_confirmation(bulk, leases, execution, ordered, change):
    queue, job, terminal, receipt, _ = captured(bulk, leases, ordered, fleet=True)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    with execution.store._connection() as db:
        if change == 'device': db.execute('UPDATE devices SET enabled=0 WHERE id=2')
        if change == 'protection': db.execute('UPDATE protected_policy SET revision=revision+1')
        if change == 'pause': db.execute('UPDATE operation_executor SET mutations_suspended=1')
    assert ordered[1].advance(enabled=True) == (0 if change == 'pause' else 1)
    assert ordered[0].status(receipt['operation_id'])['state'] == ('WAITING_ADD' if change == 'pause' else 'ATTENTION')
    with execution.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()


def test_late_fleet_failure_rolls_back_all_cleanup_not_original_retirement(bulk, leases, execution, ordered, monkeypatch):
    queue, job, terminal, receipt, _ = captured(bulk, leases, ordered, fleet=True)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    original = ordered[1]._event

    def fail(db, root, event, details, timestamp):
        if event == 'MANAGED_ORDERED_REMOVAL_ADMITTED':
            raise ValueError('Synthetic late cleanup persistence failure')
        return original(db, root, event, details, timestamp)
    monkeypatch.setattr(ordered[1], '_event', fail)
    assert ordered[1].advance(enabled=True) == 1
    assert ordered[0].status(receipt['operation_id'])['state'] == 'ATTENTION'
    with execution.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert not db.execute('SELECT 1 FROM operation_requests WHERE id=?', (receipt['operation_id'],)).fetchone()
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'OBSERVED_PRESENT'


def test_helper_cannot_accept_a_foreign_capture_or_disagreeing_verdict(bulk, leases, execution, ordered):
    from ftd_shun_manager.pending_execution import ordered_predecessor_confirmed

    queue, job, terminal, receipt, frozen = captured(bulk, leases, ordered)
    session = execution.await_confirmation(queue.token, terminal, (job['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    before = dump(execution.store)
    with execution.store._connection() as db:
        member = db.execute('SELECT * FROM managed_bulk_ordered_members WHERE root_id=?', (receipt['operation_id'],)).fetchone()
        current = dict(db.execute('SELECT * FROM operation_jobs WHERE id=?', (job['id'],)).fetchone())
        evidence = frozen[1][0]['evidence']
        for change in ({'executor_owner': str(UUID(int=1))}, {'executor_epoch': evidence['executor_epoch'] + 1},
                       {'claim_event_id': str(UUID(int=2))}):
            with pytest.raises(QueueConflict, match='original command'):
                ordered_predecessor_confirmed(db, member, evidence | change, current, current['completed_at'])
        with pytest.raises(QueueConflict, match='immutable first observation'):
            ordered_predecessor_confirmed(db, member, evidence, current | {'state': 'CONFIRMED_ABSENT'}, current['completed_at'])
    assert dump(execution.store) == before


@pytest.mark.parametrize('unknown', [False, True])
def test_continuous_batch_captured_before_ack_waits_for_observation_or_preserves_unknown(bulk, execution, ordered, monkeypatch, unknown):
    grant(bulk, (1,), count=12)
    with execution.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>1')
    started = monotonic()
    monkeypatch.setattr(OperationQueue, '_now', staticmethod(
        lambda: bulk[1][0] + timedelta(seconds=monotonic() - started)))
    monkeypatch.setattr('ftd_shun_manager.continuous_dispatch.RECHECK_SECONDS', 0.01)
    agent, receipts = Agent(), []
    if unknown:
        agent.pending_failure = 'lost'

    def requesting(device, ip, count):
        if count == 1:
            value = ordered[0].scopes.snapshot(ip, device_id=device, now=OperationQueue._now())
            from ftd_shun_manager.bulk_ordered_waits import captured as predecessors

            receipts.append(reserve(ordered[0], (value['scope'], predecessors(value))))
    agent.on_stage = requesting
    service = DeferredContinuousDispatcher(execution.store, agent, enabled=True,
        addition_device_ids=frozenset({1}), agent_concurrency=2, ordered_promotion_enabled=True)

    async def scenario():
        await service.start()
        try:
            await until(lambda: receipts)
            key = receipts[0]['operation_id']
            await until(lambda: ordered[0].status(key)['state'] == ('ATTENTION' if unknown else 'ADMITTED')
                        and not service._active)
            if not unknown:
                await until(lambda: ordered[0].status(key)['verified_removal'] and not service._active)
            value = validate_ordered_status(key, ordered[0].status(key))
            assert value['attention'] is unknown and value['verified_removal'] is not unknown
            assert len(agent.writes) == 12
            assert sum(step[0] == 'stage' and step[2] == IP for step in agent.trace) == 1
            assert not service.status()['error']
            with execution.store._connection() as db:
                target = db.execute('SELECT enabled FROM managed_shun_targets WHERE device_id=1 AND ip=?', (IP.packed,)).fetchone()
                assert not target[0]
                assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='UNVERIFIED'").fetchone()[0] == (12 if unknown else 0)
                assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == (0 if unknown else 1)
            if not unknown:
                end = next(i for i, step in enumerate(agent.trace) if step[0] == 'end_pending')
                removal = next(i for i, step in enumerate(agent.trace) if step[0] == 'remove')
                # Opening returns the complete initial snapshot in this fake;
                # no separate snapshot() RPC is required before priority REMOVE.
                assert end < removal and any(step[0] == 'open' for step in agent.trace[end + 1:removal])
                with execution.store._connection() as db:
                    first = db.execute('''SELECT r.started_at,s.settled_at,r.recorded_at FROM managed_bulk_pending_reads r
                        JOIN managed_bulk_pending_sessions s ON s.id=r.session_id''').fetchone()
                    cleanup = db.execute("SELECT requested_at FROM operation_jobs WHERE action='REMOVE'").fetchone()[0]
                    assert first['settled_at'] < first['started_at'] <= first['recorded_at'] <= cleanup
        finally:
            await service.stop()
    asyncio.run(scenario())
