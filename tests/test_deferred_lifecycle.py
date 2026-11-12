"""Deferred restoration/ready cleanup using real guards and synthetic SSH only."""

import asyncio
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_batch_session import states, visit
from test_bulk_cancellations import cancel
from test_bulk_policy import dump, retire
from test_bulk_protection import protect
from test_deferred_worker import Agent, runner
from test_deferred_worker import bulk as bulk_fixture
from test_deferred_worker import cancellation_controls as cancellation_fixture
from test_deferred_worker import dispatch as dispatch_fixture
from test_deferred_worker import execution as execution_fixture
from test_deferred_worker import journal as journal_fixture
from test_deferred_worker import leases as leases_fixture
from test_deferred_worker import ledger as ledger_fixture
from test_deferred_worker import waits as waits_fixture
from test_device_leases import acquire, grant

from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.bulk_dispatch import BulkCandidate, BulkDispatch
from ftd_shun_manager.bulk_ordered_removals import BulkOrderedRemovalScopes
from ftd_shun_manager.bulk_ordered_review import inspect_ordered
from ftd_shun_manager.bulk_removals import BulkRemovals, BulkRemovalScopes, canonical_removal
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy

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
def runtime(bulk, execution):
    grant(bulk, (1, 2), count=1)
    with execution.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    agent = Agent()
    service = runner(execution.store, agent)
    return service, agent


def advance(bulk, service, seconds=1):
    bulk[1][0] += timedelta(seconds=seconds)
    asyncio.run(visit(service))


def observed(runtime, bulk, *, absent=False):
    service, agent = runtime
    asyncio.run(visit(service))
    if absent: agent.entries[1] = []
    advance(bulk, service)
    assert states(service) == {'CONFIRMED_ABSENT' if absent else 'OBSERVED_PRESENT': 1}
    return service, agent


def removal(service, *, fleet=False):
    value = BulkRemovalScopes(service.store).snapshot(IP, device_id=None if fleet else 1)
    scope = {key: value[key] for key in ('version', 'scope', 'ip', 'managed_revision', 'protected_revision', 'protected', 'targets')}
    return BulkRemovals(service.store, service.queue), scope


def admit(ready, scope, *, key=None):
    return ready.admit(key or str(uuid4()), scope, canonical_removal(scope)[1],
        'synthetic:lifecycle', 'Lifecycle operator', ('Operator',), enabled=True)


def test_observed_presence_restores_after_new_absence_without_creation_attribution(runtime, bulk):
    service, agent = observed(runtime, bulk)
    before = dump(service.store)
    advance(bulk, service, 301)
    assert len(agent.writes) == 1 and states(service) == {'OBSERVED_PRESENT': 1}
    assert before != dump(service.store)  # Real reads, not invented ADD success.
    agent.entries[1] = []
    advance(bulk, service)
    assert len(agent.writes) == 2 and states(service) == {'OBSERVED_PRESENT': 1, 'AWAITING_CONFIRMATION': 1}
    advance(bulk, service)
    assert states(service) == {'OBSERVED_PRESENT': 2}
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(DISTINCT id) FROM managed_bulk_attempts').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_attempts WHERE occurrence_id IS NOT NULL').fetchone()[0] == 0


def test_normal_backoff_and_hourly_churn_limit_are_not_replaced_by_fast_retry(runtime, bulk):
    service, agent = observed(runtime, bulk)
    agent.entries[1] = []
    advance(bulk, service, 2)
    assert len(agent.writes) == 1
    for _ in range(2):
        advance(bulk, service, 301)
        advance(bulk, service)
        agent.entries[1] = []
    assert len(agent.writes) == 3
    advance(bulk, service, 301)
    assert len(agent.writes) == 3
    advance(bulk, service, 3601)
    assert len(agent.writes) == 4


def test_prior_absence_then_presence_then_disappearance_can_restore_and_retry_again(runtime, bulk):
    service, agent = observed(runtime, bulk, absent=True)
    advance(bulk, service, 5)
    advance(bulk, service)
    assert states(service) == {'CONFIRMED_ABSENT': 1, 'OBSERVED_PRESENT': 1}
    agent.entries[1] = []
    advance(bulk, service, 301)
    assert states(service) == {'CONFIRMED_ABSENT': 1, 'OBSERVED_PRESENT': 1, 'AWAITING_CONFIRMATION': 1}
    agent.entries[1] = []
    advance(bulk, service)
    assert states(service) == {'CONFIRMED_ABSENT': 2, 'OBSERVED_PRESENT': 1}
    advance(bulk, service, 5)
    advance(bulk, service)
    assert states(service) == {'CONFIRMED_ABSENT': 2, 'OBSERVED_PRESENT': 2}
    assert len(agent.writes) == 4


@pytest.mark.parametrize('terminal', ['VERIFIED', 'NOOP'])
def test_strict_known_presence_also_supersedes_only_earlier_known_absence(runtime, bulk, terminal):
    service, agent = observed(runtime, bulk, absent=True)
    original = agent.open_tracked_cycle
    if terminal == 'VERIFIED':
        agent.on_stage = lambda *_: setattr(service._workers[1], '_priority_pending', True)
    else:
        def opening(device, owner):
            session = original(device, owner)
            stage = session.stage_addition

            def preflight_race(ip):
                # Another source added it after the initial read, before
                # preflight. The real semantic result is NOOP, not creation.
                agent.entries[device].append(ObservedShun(ip, 'management'))
                return stage(ip)
            session.stage_addition = preflight_race
            return session
        agent.open_tracked_cycle = opening
    advance(bulk, service, 5)
    assert states(service) == {'CONFIRMED_ABSENT': 1, terminal: 1}
    assert len(agent.writes) == (2 if terminal == 'VERIFIED' else 1)
    agent.on_stage = None
    agent.open_tracked_cycle = original
    agent.entries[1] = []
    advance(bulk, service, 301)
    assert len(agent.writes) == (3 if terminal == 'VERIFIED' else 2) and states(service)['AWAITING_CONFIRMATION'] == 1


def test_newer_absence_is_not_superseded_by_older_presence_or_generic_observation(runtime, bulk, leases):
    service, agent = observed(runtime, bulk)
    agent.entries[1] = []
    advance(bulk, service, 301)
    agent.entries[1] = []
    advance(bulk, service)
    bulk[1][0] += timedelta(seconds=301)
    service.store.record_observed_shun(1, IP, 'management')
    service.store.reconcile_snapshot(1, [])
    token, queue = acquire(leases)
    snapshot = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    with service.store._connection() as db:
        target = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=1').fetchone()
        revision = db.execute('SELECT revision FROM managed_bulk_registry').fetchone()[0]
        protected = db.execute('SELECT revision FROM protected_policy').fetchone()[0]
    candidate = BulkCandidate(1, IP, target['intent_id'], target['generation'], target['authorization_request_id'], target['revision'])
    before = dump(service.store)
    with pytest.raises(QueueConflict):
        BulkDispatch(service.store, queue).admit(snapshot, (candidate,), token.owner, revision, protected,
            enabled=True, addition_device_ids=frozenset({1}))
    assert dump(service.store) == before
    leases.release(token)


@pytest.mark.parametrize('revoke', ['protect', 'retire', 'pause', 'suspend', 'device'])
def test_current_policy_still_blocks_disappearance_restoration(runtime, bulk, revoke):
    service, agent = observed(runtime, bulk)
    if revoke == 'protect': protect(ProtectedPolicy(service.store))
    if revoke == 'retire': retire(bulk, [(1, IP)])
    with service.store._connection() as db:
        if revoke == 'pause': db.execute('UPDATE operation_executor SET mutations_suspended=1')
        if revoke == 'suspend': db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
        if revoke == 'device': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
    agent.entries[1] = []
    advance(bulk, service, 301)
    assert len(agent.writes) == 1 and states(service) == {'OBSERVED_PRESENT': 1}
    if revoke == 'protect':
        protect(ProtectedPolicy(service.store), action='edit', enabled=False)
        advance(bulk, service, 301)
        assert len(agent.writes) == 1  # Protection permanently retired this policy.


def test_cancel_retains_already_confirmed_present_policy_and_its_restoration(runtime, bulk, cancellation_controls):
    service, agent = observed(runtime, bulk)
    with service.store._connection() as db:
        root = db.execute('SELECT authorization_request_id FROM managed_shun_targets WHERE device_id=1').fetchone()[0]
    cancel(cancellation_controls, root)
    agent.entries[1] = []
    advance(bulk, service, 301)
    assert len(agent.writes) == 2 and states(service)['AWAITING_CONFIRMATION'] == 1


def test_unknown_restoration_is_not_replayed_or_excused_by_old_known_presence(runtime, bulk):
    service, agent = observed(runtime, bulk)
    agent.entries[1] = []
    agent.fail_stage = 1
    advance(bulk, service, 301)
    assert states(service) == {'OBSERVED_PRESENT': 1, 'UNVERIFIED': 1}
    with service.store._connection() as db:
        unknown = tuple(db.execute("SELECT * FROM operation_jobs WHERE state='UNVERIFIED'").fetchone())
    advance(bulk, service, 301)
    assert len(agent.writes) == 2
    with service.store._connection() as db:
        assert tuple(db.execute("SELECT * FROM operation_jobs WHERE state='UNVERIFIED'").fetchone()) == unknown


@pytest.mark.parametrize('fleet', [False, True])
def test_pending_confirmation_refuses_ready_cleanup_atomically_and_inspection_is_not_ready(runtime, bulk, fleet):
    service, _ = runtime
    asyncio.run(visit(service))
    ready, scope = removal(service, fleet=fleet)
    before = dump(service.store)
    with pytest.raises(QueueConflict, match='pending or unresolved'):
        admit(ready, scope)
    inspection = BulkOrderedRemovalScopes(service.store).snapshot(IP, device_id=None if fleet else 1, now=bulk[1][0])
    assert inspection['disposition'] == 'WAITING_ADD'
    assert inspection['targets'][0]['blockers'] == []
    assert inspection['targets'][0]['predecessor']['kind'] == 'AWAITING_CONFIRMATION'
    assert inspect_ordered(inspection, IP, device_id=None if fleet else 1)['disposition'] == 'WAITING_ADD'
    from ftd_shun_manager.web import Identity, templates

    html = templates.get_template('bulk-ordered-review.html').render(
        identity=Identity('synthetic:lifecycle', 'Lifecycle operator', ('Operator',)),
        inspection=inspection, refresh=None, review=None, message=None)
    assert 'SSH session has finished' in html and 'Wait for confirmation' in html
    assert 'No confirmation token was created' in html and 'name="review"' not in html
    assert dump(service.store) == before


@pytest.mark.parametrize('absent', [False, True])
def test_ready_cleanup_of_known_outcome_retires_then_verifies_without_later_readd(runtime, bulk, absent):
    service, agent = observed(runtime, bulk, absent=absent)
    ready, scope = removal(service)
    key = str(uuid4())
    result = admit(ready, scope, key=key)
    assert result['retired_targets'] == 1 and not result['verified_removal']
    advance(bulk, service)
    expected = 'NOOP' if absent else 'VERIFIED'
    assert states(service) == {'CONFIRMED_ABSENT' if absent else 'OBSERVED_PRESENT': 1, expected: 1}
    advance(bulk, service, 301)
    assert len(agent.writes) == 1 and not agent.entries[1]
    assert admit(ready, scope, key=key)['replayed']


def test_review_prepared_while_pending_cannot_silently_gain_postconfirmation_scope(runtime, bulk):
    service, _ = runtime
    asyncio.run(visit(service))
    ready, scope = removal(service)
    advance(bulk, service)
    before = dump(service.store)
    with pytest.raises(ValueError, match='scope changed'):
        admit(ready, scope)
    assert dump(service.store) == before


@pytest.mark.parametrize('absent', [False, True])
def test_late_cleanup_failure_preserves_known_outcome_and_complete_policy(runtime, bulk, monkeypatch, absent):
    service, _ = observed(runtime, bulk, absent=absent)
    ready, scope = removal(service, fleet=True)
    original = service.store._insert_event

    def failing(db, event, *args, **kwargs):
        original(db, event, *args, **kwargs)
        if event == 'MANAGED_READY_REMOVAL_ADMITTED':
            raise ValueError('Synthetic late cleanup audit failure')
    monkeypatch.setattr(service.store, '_insert_event', failing)
    before = dump(service.store)
    with pytest.raises(ValueError, match='late cleanup audit'):
        admit(ready, scope)
    assert dump(service.store) == before


def test_read_not_strictly_after_presence_cannot_restore_even_after_pair_backoff(runtime, bulk, leases):
    service, _ = runtime
    asyncio.run(visit(service))
    advance(bulk, service, 301)  # The first observation is recent, original ADD old.
    service.store.reconcile_snapshot(1, [])
    token, queue = acquire(leases)
    snapshot = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    with service.store._connection() as db:
        target = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=1').fetchone()
        revision = db.execute('SELECT revision FROM managed_bulk_registry').fetchone()[0]
        protected = db.execute('SELECT revision FROM protected_policy').fetchone()[0]
    candidate = BulkCandidate(1, IP, target['intent_id'], target['generation'], target['authorization_request_id'], target['revision'])
    before = dump(service.store)
    with pytest.raises(QueueConflict):
        BulkDispatch(service.store, queue).admit(snapshot, (candidate,), token.owner, revision, protected,
            enabled=True, addition_device_ids=frozenset({1}))
    assert dump(service.store) == before
    leases.release(token)


def test_old_generation_presence_cannot_supersede_new_generation_known_absence(runtime, bulk, leases):
    service, agent = observed(runtime, bulk)
    retire(bulk, [(1, IP)])
    agent.entries[1] = []
    advance(bulk, service)
    with service.store._connection() as db:
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
    grant(bulk, (1,), count=1)
    advance(bulk, service, 301)
    agent.entries[1] = []
    advance(bulk, service)
    assert states(service) == {'OBSERVED_PRESENT': 1, 'CONFIRMED_ABSENT': 1}
    bulk[1][0] += timedelta(seconds=301)
    token, queue = acquire(leases)
    snapshot = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    with service.store._connection() as db:
        target = db.execute('SELECT * FROM managed_shun_targets WHERE device_id=1').fetchone()
        revision = db.execute('SELECT revision FROM managed_bulk_registry').fetchone()[0]
        protected = db.execute('SELECT revision FROM protected_policy').fetchone()[0]
    assert target['generation'] == 2
    candidate = BulkCandidate(1, IP, target['intent_id'], target['generation'], target['authorization_request_id'], target['revision'])
    before = dump(service.store)
    with pytest.raises(QueueConflict):
        BulkDispatch(service.store, queue).admit(snapshot, (candidate,), token.owner, revision, protected,
            enabled=True, addition_device_ids=frozenset({1}))
    assert dump(service.store) == before
    leases.release(token)


def test_fleet_cleanup_after_all_confirmations_is_one_atomic_retirement_and_shared_queue(runtime, bulk):
    service, agent = observed(runtime, bulk)
    second = runner(service.store, agent)
    second.configuration['addition_device_ids'] = frozenset({1, 2})
    device = next(device for device in service.store.list_devices() if device.id == 2)
    asyncio.run(second._visit(device))
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(second._visit(device))
    ready, scope = removal(service, fleet=True)
    result = admit(ready, scope)
    assert result['retired_targets'] == 2 and len(result['jobs']) == 2
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(service))
    asyncio.run(second._visit(device))
    assert not agent.entries[1] and not agent.entries[2]
    assert states(service) == {'OBSERVED_PRESENT': 2, 'VERIFIED': 2}
