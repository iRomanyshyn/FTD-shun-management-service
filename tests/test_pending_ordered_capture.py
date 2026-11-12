"""New consent for already-settled pending ADDs; synthetic profiles/transports only."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from time import monotonic
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_batch_queue import acknowledge
from test_batch_session import visit
from test_bulk_ordered_waits import reserve
from test_bulk_policy import dump
from test_continuous_dispatch import until
from test_deferred_ordered import bulk as bulk_fixture
from test_deferred_ordered import cancellation_controls as cancellation_fixture
from test_deferred_ordered import dispatch as dispatch_fixture
from test_deferred_ordered import execution as execution_fixture
from test_deferred_ordered import journal as journal_fixture
from test_deferred_ordered import leases as leases_fixture
from test_deferred_ordered import ledger as ledger_fixture
from test_deferred_ordered import ordered as ordered_fixture
from test_deferred_ordered import waits as waits_fixture
from test_deferred_worker import Agent, runner
from test_device_leases import acquire, discover, grant
from test_pending_confirmation import SyntheticV7Queue, read

from ftd_shun_manager.agent_protocol import PendingAddition, SettledPendingAdditions
from ftd_shun_manager.api import OrderedRemovalRequest
from ftd_shun_manager.bulk_ordered_review import (
    OrderedRemovalReviews,
    inspect_ordered,
    validate_ordered_status,
)
from ftd_shun_manager.bulk_ordered_waits import captured
from ftd_shun_manager.bulk_policy import _state
from ftd_shun_manager.deferred_dispatch import DeferredContinuousDispatcher
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
ordered = ordered_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


def stage_device(leases, bulk, device=1, *, count=1):
    token, ordinary = acquire(leases, device)
    assert discover(bulk, ordinary) == count
    queue = SyntheticV7Queue(leases.store, token)
    jobs = [acknowledge(queue, n * 2 + 1) for n in range(count)]
    terminal = SettledPendingAdditions(device, UUID(token.owner).bytes, count * 2,
        tuple(PendingAddition(IPv4Address(job['ip']), n * 2 + 1) for n, job in enumerate(jobs)))
    return queue, jobs, terminal


def awaiting(bulk, leases, execution, *, fleet=False, count=1):
    grant(bulk, (1, 2) if fleet else (1,), count=count)
    queue, jobs, terminal = stage_device(leases, bulk, count=count)
    session = execution.await_confirmation(queue.token, terminal, tuple(job['id'] for job in jobs), enabled=True)
    return queue, jobs, session


def inspection(ordered, bulk, *, fleet=False):
    value = ordered[0].scopes.snapshot(IP, device_id=None if fleet else 1, now=bulk[1][0])
    return inspect_ordered(value, IP, device_id=None if fleet else 1)


@pytest.mark.parametrize('present', [False, True])
@pytest.mark.parametrize('fleet', [False, True])
def test_initial_pending_capture_never_invents_a_live_lease_then_promotes_after_read(bulk, leases, execution, ordered, present, fleet):
    queue, jobs, session = awaiting(bulk, leases, execution, fleet=fleet)
    before = dump(execution.store)
    value = inspection(ordered, bulk, fleet=fleet)
    assert dump(execution.store) == before and value['disposition'] == 'WAITING_ADD'
    predecessor = value['targets'][0]['predecessor']
    assert predecessor['kind'] == 'AWAITING_CONFIRMATION' and 'lease_until' not in predecessor
    assert predecessor['pending_session_id'] == session and predecessor['executor_owner'] == queue.token.owner
    assert value['read_only'] and not value['device_work_admitted']
    frozen = (value['scope'], captured(value))
    review = OrderedRemovalReviews().prepare('synthetic:operator', 'synthetic-cookie', value, IP,
        device_id=None if fleet else 1)
    body = OrderedRemovalRequest.model_validate({**review.payload(), 'actor': {
        'subject': 'synthetic:operator', 'display_name': 'Actual synthetic operator', 'roles': ['Operator']}}).model_dump()
    assert body['predecessors'] == captured(value)
    receipt = ordered[0].reserve(review.request_id, body['reviewed'], body['predecessors'], body['confirmation_digest'],
        body['actor']['subject'], body['actor']['display_name'], tuple(body['actor']['roles']),
        ttl_seconds=body['ttl_seconds'], reason=body['reason'], enabled=True)
    original = dump(execution.store)
    assert ordered[1].advance(enabled=True) == 0 and dump(execution.store) == original
    assert reserve(ordered[0], frozen, key=receipt['operation_id'])['replayed']
    assert dump(execution.store) == original
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),) if present else ()), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 1
    status = validate_ordered_status(receipt['operation_id'], ordered[0].status(receipt['operation_id']))
    assert status['state'] == 'ADMITTED' and not status['verified_removal']
    assert len(status['cleanup_jobs']) == (2 if fleet else 1)
    assert status['expires_at'] == receipt['expires_at']
    assert jobs[0]['id'] == status['predecessors'][0]['job_id']
    with execution.store._connection() as db:
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='ADD'").fetchone()[0] == 1


def test_expired_original_add_authorization_is_not_renewed_by_new_cleanup(bulk, leases, execution, ordered):
    _, jobs, session = awaiting(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=901)
    execution.queue.expire_requests()
    value = inspection(ordered, bulk)
    assert value['targets'][0]['predecessor']['expires_at'] < value['inspected_at']
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    with execution.store._connection() as db:
        old = db.execute('SELECT r.* FROM operation_requests r JOIN operation_links l ON l.request_id=r.id WHERE l.job_id=?', (jobs[0]['id'],)).fetchone()
        assert old['state'] == 'EXPIRED' and old['expires_at'] < receipt['requested_at']
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='ADD'").fetchone()[0] == 1
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 1


def test_confirmation_race_rejects_stale_review_without_silent_ready_conversion(bulk, leases, execution, ordered):
    _, _, session = awaiting(bulk, leases, execution)
    value = inspection(ordered, bulk)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    before = dump(execution.store)
    with pytest.raises(ManagedConflict, match='changed'):
        reserve(ordered[0], (value['scope'], captured(value)))
    assert dump(execution.store) == before
    assert inspection(ordered, bulk)['disposition'] == 'READY'


def test_fleet_mixes_live_and_settled_predecessors_without_changing_either_contract(bulk, leases, execution, ordered):
    _, _, first = awaiting(bulk, leases, execution, fleet=True)
    queue, jobs, terminal = stage_device(leases, bulk, device=2)
    value = inspection(ordered, bulk, fleet=True)
    assert [row['predecessor'].get('kind', 'RUNNING') for row in value['targets']] == ['AWAITING_CONFIRMATION', 'RUNNING']
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    assert ordered[1].advance(enabled=True) == 0
    second = execution.await_confirmation(queue.token, terminal, (jobs[0]['id'],), enabled=True)
    bulk[1][0] += timedelta(seconds=1)
    for device, session in ((1, first), (2, second)):
        token, _ = acquire(leases, device)
        execution.confirm(token, session, replace(read(bulk, present=(str(IP),)), device_id=device), enabled=True)
        leases.release(token)
        if device == 1:
            assert ordered[1].advance(enabled=True) == 0
    assert ordered[1].advance(enabled=True) == 1
    assert len(ordered[0].status(receipt['operation_id'])['cleanup_jobs']) == 2


@pytest.mark.parametrize('damage', ['kind', 'extra_lease', 'session', 'settled', 'digest', 'missing_kind'])
def test_malformed_or_substituted_pending_consent_never_retires_policy(bulk, leases, execution, ordered, damage):
    awaiting(bulk, leases, execution)
    value = inspection(ordered, bulk)
    predecessors = deepcopy(captured(value))
    target = predecessors[0]['evidence']
    if damage == 'kind': target['kind'] = 'RUNNING'
    if damage == 'extra_lease': target['lease_until'] = target['expires_at']
    if damage == 'session': target['pending_session_id'] = str(uuid4())
    if damage == 'settled': target['settled_at'] = '2099-01-01T00:00:00.000Z'
    if damage == 'digest': target['evidence_digest'] = '0' * 64
    if damage == 'missing_kind': del target['kind']
    before = dump(execution.store)
    with pytest.raises((ValueError, ManagedConflict)):
        reserve(ordered[0], (value['scope'], predecessors))
    assert dump(execution.store) == before
    if damage in {'kind', 'extra_lease', 'missing_kind'}:
        with pytest.raises(ValidationError):
            OrderedRemovalRequest.model_validate({'actor': {'subject': 'alice', 'display_name': '', 'roles': ['Operator']},
                'reviewed': value['scope'], 'predecessors': predecessors, 'confirmation_digest': '0' * 64, 'ttl_seconds': 900})


def test_pending_group_of_twelve_can_capture_one_ip_without_dropping_group_proof(bulk, leases, execution, ordered):
    _, jobs, session = awaiting(bulk, leases, execution, count=12)
    value = inspection(ordered, bulk)
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=tuple(str(IPv4Address(job['ip'])) for job in jobs)), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 1
    assert len(ordered[0].status(receipt['operation_id'])['cleanup_jobs']) == 1
    with execution.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 11
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='OBSERVED_PRESENT'").fetchone()[0] == 12


def test_revoked_pending_capture_survives_history_retention_without_rearming(bulk, leases, execution, ordered):
    _, _, session = awaiting(bulk, leases, execution)
    value = inspection(ordered, bulk)
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    ordered[0].cancel(receipt['operation_id'], 'synthetic:operator', 'Actual synthetic operator', ('Operator',))
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    bulk[1][0] += timedelta(days=400)
    execution.queue.prune_completed(366)
    assert ordered[1].advance(enabled=True) == 0
    with execution.store._connection() as db:
        assert _state(db) is not None
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()


def test_pending_capture_keeps_original_identity_without_touching_successor_lease(bulk, leases, execution, ordered):
    old, _, session = awaiting(bulk, leases, execution)
    bulk[1][0] += timedelta(seconds=1)
    token, _ = acquire(leases)
    fence = leases.status()['devices'][0]
    value = inspection(ordered, bulk)
    evidence = value['targets'][0]['predecessor']
    assert evidence['executor_owner'] == old.token.owner != token.owner
    assert evidence['executor_epoch'] == old.token.epoch < token.epoch
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    assert leases.status()['devices'][0] == fence
    assert ordered[1].advance(enabled=True) == 0
    execution.confirm(token, session, read(bulk, present=(str(IP),)), enabled=True)
    leases.release(token)
    assert ordered[1].advance(enabled=True) == 1
    assert ordered[0].status(receipt['operation_id'])['state'] == 'ADMITTED'


def test_fresh_coordinator_confirms_existing_pending_group_then_unblocks_without_new_add(bulk, execution, ordered, monkeypatch):
    grant(bulk, (1,), count=12)
    with execution.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>1')
    agent = Agent()
    asyncio.run(visit(runner(execution.store, agent)))
    assert len(agent.writes) == 12
    value = inspection(ordered, bulk)
    receipt = reserve(ordered[0], (value['scope'], captured(value)))
    started = monotonic()
    monkeypatch.setattr(OperationQueue, '_now', staticmethod(
        lambda: bulk[1][0] + timedelta(seconds=monotonic() - started)))
    monkeypatch.setattr('ftd_shun_manager.continuous_dispatch.RECHECK_SECONDS', 0.01)
    service = DeferredContinuousDispatcher(execution.store, agent, enabled=True,
        addition_device_ids=frozenset({1}), agent_concurrency=2, ordered_promotion_enabled=True)

    async def scenario():
        await service.start()
        try:
            await until(lambda: ordered[0].status(receipt['operation_id'])['verified_removal'] and not service._active)
            assert len(agent.writes) == 12 and all(entry.ip != IP for entry in agent.entries[1])
            assert service.status()['error'] is None
            with execution.store._connection() as db:
                assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='OBSERVED_PRESENT'").fetchone()[0] == 12
                assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='VERIFIED'").fetchone()[0] == 1
                assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 11
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('state', ['RUNNING', 'NOOP', 'VERIFIED', 'CANCELLED', 'FAILED', 'UNVERIFIED'])
def test_settled_capture_cannot_skip_first_observation_by_substituting_old_outcome(bulk, leases, execution, ordered, state):
    from ftd_shun_manager.pending_ordered import descriptor

    _, jobs, _ = awaiting(bulk, leases, execution)
    before = dump(execution.store)
    with execution.store._connection() as db:
        job = dict(db.execute('SELECT * FROM operation_jobs WHERE id=?', (jobs[0]['id'],)).fetchone())
        with pytest.raises(ValueError, match='substitute another ADD outcome'):
            descriptor(db, job | {'state': state})
    assert dump(execution.store) == before
