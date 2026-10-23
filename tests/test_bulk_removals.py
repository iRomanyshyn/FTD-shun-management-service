"""Atomic v2 removal on disposable fenced storage; never lab/SSH admission."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import confirm, dump, prepare
from test_continuous_api import bulk as bulk_fixture
from test_continuous_api import cancellation_controls as cancellation_fixture
from test_continuous_api import composition as composition_fixture
from test_continuous_api import dispatch as dispatch_fixture
from test_continuous_api import journal as journal_fixture
from test_continuous_api import leases as leases_fixture
from test_continuous_api import waits as waits_fixture
from test_continuous_dispatch import idle, until
from test_device_leases import acquire, claim, discover, grant

from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_removals import (
    SCOPE,
    BulkRemovals,
    BulkRemovalScopes,
    canonical_removal,
    canonical_scope,
)
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')


@pytest.fixture
def ready(composition):
    _, store, _, service = composition
    return BulkRemovals(store, service.runner.queue)


def reviewed(ready, *, device=None):
    value = BulkRemovalScopes(ready.store).snapshot(IP, device_id=device)
    return {key: value[key] for key in ('version', 'scope', 'ip', 'managed_revision', 'protected_revision', 'protected', 'targets')}


def admit(ready, scope, *, key=None, **changes):
    args = {'key': key or str(uuid4()), 'reviewed': scope, 'digest': canonical_removal(scope)[1],
            'subject': 'synthetic:operator', 'display_name': 'Synthetic operator', 'roles': ('Operator',), 'enabled': True}
    return ready.admit(**(args | changes))


def test_default_off_missing_storage_and_reads_never_initialize(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = BulkRemovals(store, OperationQueue(store))
    with pytest.raises(PermissionError): service.admit(None, None, None, None, None, None)
    with pytest.raises(PermissionError): service.admit(None, None, None, None, None, None, enabled=1)
    with pytest.raises(BulkUnavailable): service.admit(None, None, None, None, None, None, enabled=True)
    with pytest.raises(sqlite3.OperationalError): BulkRemovalScopes(store).snapshot(IP)
    assert not store.path.exists()


def test_read_scope_is_complete_union_with_missing_disabled_and_unmanaged_not_adopted(ready, bulk, monkeypatch):
    confirm(bulk, prepare(bulk, devices=(1, 2, 3))[1])
    ready.store.record_observed_shun(1, IP, 'management')
    ready.store.record_observed_shun(1, IP, 'outside')
    ready.store.record_observed_shun(4, IP, 'management')
    with ready.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id=3')
    before = dump(ready.store)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Readonly scope/admission never initialize storage.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    scope = reviewed(ready)
    assert [row['device_id'] for row in scope['targets']] == [1, 2, 3, 4]
    assert scope['targets'][1]['maintenance_enabled'] and not scope['targets'][1]['observed_present']
    assert not scope['targets'][2]['device_enabled']
    assert scope['targets'][3]['observed_present'] and scope['targets'][3]['intent_id'] is None
    assert reviewed(ready, device=2)['targets'] == [scope['targets'][1]]
    with pytest.raises(QueueConflict): admit(ready, scope)
    assert dump(ready.store) == before


@pytest.mark.parametrize('damage', ['version', 'scope', 'extra', 'boolean', 'duplicate', 'authority', 'revision', 'hostname'])
def test_literal_canonical_scope_and_action_are_not_interchangeable(ready, bulk, damage):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    scope = reviewed(ready)
    if damage == 'version': scope['version'] = 2.0
    elif damage == 'scope': scope['scope'] = 'device'
    elif damage == 'extra': scope['action'] = 'CLI'
    elif damage == 'boolean': scope['targets'][0]['observed_present'] = 0
    elif damage == 'duplicate': scope['targets'][1] = scope['targets'][0].copy()
    elif damage == 'authority': scope['targets'][0]['authorization_request_id'] = None
    elif damage == 'revision': scope['managed_revision'] = True
    elif damage == 'hostname': scope['targets'][0]['hostname'] = 'host\ncommand'
    before = dump(ready.store)
    with pytest.raises(ValueError): canonical_scope(scope)
    assert dump(ready.store) == before


def test_atomic_whole_scope_has_one_retained_receipt_and_no_fabricated_success(ready, bulk):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    ready.store.record_observed_shun(3, IP, 'management')
    original = bulk[0].policy_page()['entries']
    scope = reviewed(ready)
    result = admit(ready, scope)
    assert result['target_count'] == 3 and result['retired_targets'] == 2 and result['managed_revision'] == 2
    assert result['device_work_admitted'] and not result['verified_removal'] and not result['policy_only']
    assert len(result['jobs']) == 3
    for old, current in zip(original, bulk[0].policy_page()['entries'], strict=True):
        assert not current['enabled']
        assert all(old[field] == current[field] for field in ('intent_id', 'generation', 'authorization_request_id'))
    with ready.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM operation_requests').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='QUEUED'").fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE device_id=3').fetchone()[0] == 0
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    event = next(row for row in ready.store.list_events() if row['event_type'] == 'MANAGED_READY_REMOVAL_ADMITTED')
    assert event['actor_subject'] == 'synthetic:operator' and event['actor_roles'] == ['Operator']


@pytest.mark.parametrize('change', ['membership', 'protection', 'revision', 'scope_digest', 'actor', 'paused'])
def test_stale_or_unauthorized_scope_cannot_partially_retire_or_admit(ready, bulk, change):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    scope = reviewed(ready)
    changes = {}
    if change == 'membership': ready.store.record_observed_shun(3, IP, 'management')
    elif change == 'protection': ProtectedPolicy(ready.store, initialize_queue=False).change(
        'add', IP, 0, 'synthetic:policy', 'Policy author', ('Viewer',), managed_revision=1)
    elif change == 'revision': confirm(bulk, prepare(bulk, '198.51.100.2')[1])
    elif change == 'scope_digest': changes['digest'] = canonical_scope(scope)[1]
    elif change == 'actor': changes['roles'] = ('Viewer',)
    elif change == 'paused':
        with ready.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(ready.store)
    with pytest.raises((ValueError, PermissionError)): admit(ready, scope, **changes)
    assert dump(ready.store) == before


@pytest.mark.parametrize('failure', ['audit', 'capacity', 'expiry', 'clock_backwards', 'lease_expiry'])
def test_late_failure_rolls_back_entire_scope_even_when_outer_caller_commits(ready, bulk, leases, monkeypatch, failure):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    scope, key = reviewed(ready), str(uuid4())
    if failure == 'lease_expiry': acquire(leases, seconds=5)
    original = ready.store._insert_event

    def event(db, event_type, *args, **kwargs):
        original(db, event_type, *args, **kwargs)
        if event_type == 'MANAGED_READY_REMOVAL_ADMITTED':
            if failure == 'audit': raise sqlite3.OperationalError('Synthetic late audit failure')
            if failure == 'expiry': bulk[1][0] += timedelta(seconds=901)
            if failure == 'clock_backwards': bulk[1][0] -= timedelta(seconds=1)
            if failure == 'lease_expiry': bulk[1][0] += timedelta(seconds=6)
    monkeypatch.setattr(ready.store, '_insert_event', event)
    if failure == 'capacity': monkeypatch.setattr(ready.queue, '_pending_count', lambda db: 1000)
    before = dump(ready.store)
    with ready.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises((sqlite3.DatabaseError, QueueConflict, QueueFull)):
            ready.apply_admit(db, key, scope, canonical_removal(scope)[1], 'synthetic:operator', 'Synthetic operator',
                              ('Operator',), enabled=True)
    assert dump(ready.store) == before


@pytest.mark.parametrize('state', ['QUEUED', 'RUNNING', 'FAILED', 'UNVERIFIED'])
def test_actual_bulk_add_predecessor_is_never_replayed_cancelled_or_silently_waited(ready, bulk, leases, state):
    grant(bulk, devices=(1, 2))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue) if state != 'QUEUED' else None
    if state in {'FAILED', 'UNVERIFIED'}:
        queue.finish_addition(job['id'], token.owner, state)
    scope, before = reviewed(ready), dump(ready.store)
    with pytest.raises(QueueConflict): admit(ready, scope)
    assert dump(ready.store) == before


def test_exact_key_replay_survives_pruning_and_never_retires_newer_generation_or_requeues(ready, bulk, leases):
    confirm(bulk, prepare(bulk)[1])
    scope, key = reviewed(ready), str(uuid4())
    result = admit(ready, scope, key=key)
    token, queue = acquire(leases)
    job = queue.claim_removal(1, token.owner, queue.cutoff())
    assert job['id'] == result['jobs'][0]['job_id']
    queue.finish_removal(job['id'], token.owner, 'NOOP')
    leases.release(token)
    bulk[1][0] += timedelta(days=367)
    ready.queue.prune_completed(366)
    confirm(bulk, prepare(bulk)[1])
    before = dump(ready.store)
    assert admit(ready, scope, key=key) == {**result, 'replayed': True}
    assert bulk[0].policy_page()['entries'][0]['generation'] == 2
    assert bulk[0].policy_page()['entries'][0]['enabled']
    assert dump(ready.store) == before
    with pytest.raises((QueueConflict, ManagedStateUnavailable)):
        ready.queue.enqueue(key, [(1, IP)], 'synthetic:operator', 'Synthetic operator', ('Operator',), scope=SCOPE)
    assert dump(ready.store) == before


def test_concurrent_same_and_conflicting_confirmations_have_one_atomic_result(ready, bulk):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    scope, key = reviewed(ready), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: admit(ready, scope, key=key), range(2)))
    assert sorted(result['replayed'] for result in results) == [False, True]
    before = dump(ready.store)
    with pytest.raises(ManagedConflict): admit(ready, scope)
    assert dump(ready.store) == before


def test_general_queue_scope_label_and_capability_cannot_bypass_managed_policy(ready, bulk):
    confirm(bulk, prepare(bulk)[1])
    before = dump(ready.store)
    with pytest.raises(ManagedStateUnavailable):
        ready.queue.enqueue(str(uuid4()), [(1, IP)], 'actor', 'Actor', ('Operator',), scope=SCOPE)
    with ready.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(QueueConflict):
            ready.queue.apply_enqueue(db, str(uuid4()), [(1, IP)], 'actor', 'Actor', ('Operator',),
                                      scope=SCOPE, bulk_removal_enabled=True)
        with pytest.raises(ValueError):
            ready.queue.apply_enqueue(db, str(uuid4()), [(1, IP)], 'actor', 'Actor', ('Operator',),
                                      bulk_removal_enabled=True)
    assert dump(ready.store) == before


def test_real_continuous_worker_dispatches_new_admission_without_waiting_for_baseline(ready, bulk, composition):
    _, store, agent, service = composition
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    for device in (1, 2): agent.entries[device] = [ObservedShun(IP, 'management')]

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            opens = sum(step[0] == 'open' for step in agent.trace)
            result = admit(ready, reviewed(ready))
            await until(lambda: len(agent.removals) == 2 and not service._active)
            assert sum(step[0] == 'open' for step in agent.trace) > opens and not agent.writes
            with store._connection() as db:
                states = [row[0] for row in db.execute('''SELECT j.state FROM operation_jobs j
                    JOIN operation_links l ON l.job_id=j.id WHERE l.request_id=?''', (result['operation_id'],))]
            assert states == ['VERIFIED', 'VERIFIED']
            assert not any(row['enabled'] for row in bulk[0].policy_page()['entries'])
        finally:
            await service.stop()
        assert not agent.active
    asyncio.run(scenario())


def test_ready_scope_digest_is_distinct_from_action_and_freezes_ttl_reason_and_mode(ready, bulk):
    confirm(bulk, prepare(bulk)[1])
    scope = reviewed(ready)
    assert canonical_scope(scope)[1] != canonical_removal(scope)[1]
    assert canonical_removal(scope, 899)[1] != canonical_removal(scope)[1]
    assert canonical_removal(scope, reason='Reason')[1] != canonical_removal(scope)[1]
    assert canonical_removal(reviewed(ready, device=1))[1] != canonical_removal(scope)[1]
    assert json.loads(canonical_removal(scope)[0])['action'] == 'STOP_AND_REMOVE_READY'


@pytest.mark.parametrize('ttl,reason', [(True, ''), (1.0, ''), (0, ''), (901, ''), (900, 'line\nbreak'), (900, 'x'*501)])
def test_action_lifetime_and_reason_are_literal_bounded_and_nonexecuting(ready, bulk, ttl, reason):
    confirm(bulk, prepare(bulk)[1])
    scope, before = reviewed(ready), dump(ready.store)
    with pytest.raises(ValueError): canonical_removal(scope, ttl, reason)
    assert dump(ready.store) == before


def test_missing_executor_scope_is_not_silently_dropped_from_fleet(ready, bulk):
    confirm(bulk, prepare(bulk)[1])
    with ready.store._connection() as db: db.execute('UPDATE devices SET enabled=1 WHERE id=5')
    ready.store.record_observed_shun(5, IP, 'management')
    scope, before = reviewed(ready), dump(ready.store)
    assert [row['device_id'] for row in scope['targets']] == [1, 5]
    with pytest.raises(QueueConflict): admit(ready, scope)
    assert dump(ready.store) == before


def test_original_admission_receipt_never_retries_unknown_removal(ready, bulk, leases):
    confirm(bulk, prepare(bulk)[1])
    scope, key = reviewed(ready), str(uuid4())
    result = admit(ready, scope, key=key)
    token, queue = acquire(leases)
    job = queue.claim_removal(1, token.owner, queue.cutoff())
    queue.finish_removal(job['id'], token.owner, 'UNVERIFIED')
    before = dump(ready.store)
    assert admit(ready, scope, key=key) == {**result, 'replayed': True}
    assert dump(ready.store) == before
    with pytest.raises(QueueConflict): admit(ready, reviewed(ready, device=1))
    assert dump(ready.store) == before


def test_private_scope_api_is_readonly_and_does_not_expose_removal_admission(composition, bulk):
    settings, store, agent, service = composition
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    before = dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            fleet = await client.get(f'/api/v2/managed-removal-scope/{IP}')
            assert fleet.status_code == 200 and fleet.headers['cache-control'] == 'no-store'
            assert fleet.json()['version'] == 2 and fleet.json()['scope'] == 'fleet'
            assert len(fleet.json()['targets']) == 2 and not fleet.json()['execution_available']
            device = await client.get(f'/api/v2/managed-removal-scope/{IP}?device_id=2')
            assert device.status_code == 200 and device.json()['scope'] == 'device'
            assert [row['device_id'] for row in device.json()['targets']] == [2]
            assert (await client.get(f'/api/v2/managed-removal-scope/{IP}?device_id=0')).status_code == 422
            assert (await client.get('/api/v2/managed-removal-scope/invalid')).status_code == 422
            assert (await client.get('/api/v2/managed-removal-scope/198.51.100.99')).status_code == 409
            for path in ('/api/v2/managed-removals/device', '/api/v2/managed-removals/fleet',
                         '/api/v1/managed-removals/device', '/api/v1/managed-removals/fleet'):
                assert (await client.post(path, json=fleet.json())).status_code == 503
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


def test_scope_api_corrupt_optional_state_is_unavailable_not_empty(composition, bulk):
    settings, store, agent, service = composition
    confirm(bulk, prepare(bulk)[1])
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    with store._connection() as db: db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    before = dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            response = await client.get(f'/api/v2/managed-removal-scope/{IP}')
            assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
            assert 'no successful device operation' in response.json()['detail']
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen
