"""Private ordered API on disposable profiles and semantic fakes, never lab SSH."""

import asyncio
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_ordered_promotion import finish
from test_bulk_ordered_removals import running
from test_bulk_policy import dump
from test_continuous_api import bulk as bulk_fixture
from test_continuous_api import cancellation_controls as cancellation_fixture
from test_continuous_api import composition as composition_fixture
from test_continuous_api import dispatch as dispatch_fixture
from test_continuous_api import journal as journal_fixture
from test_continuous_api import leases as leases_fixture
from test_continuous_api import waits as waits_fixture
from test_continuous_dispatch import until
from test_device_leases import acquire, grant

from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_ordered_waits import (
    BulkOrderedWaits,
    canonical_ordered_removal,
    captured,
)
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
IP = '198.51.100.1'
BASE = '/api/v2/managed-ordered-removals'
ACTOR = {'subject': 'synthetic:operator', 'display_name': 'Actual fixture operator', 'roles': ['Operator']}


@pytest.fixture
def ordered(composition):
    _, store, _, service = composition
    controls = BulkOrderedWaits(store, service.runner.queue)
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    controls.initialize(enabled=True)
    service.ordered_promoter.initialize(enabled=True)
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    service.ordered_promotion_enabled = True
    return controls


def application(composition, *, enabled=True, settings=None, ready=False):
    original, store, agent, service = composition
    return create_app(settings or original, store, agent, continuous_dispatcher=service,
                      ordered_removal_admission_enabled=enabled, ready_removal_admission_enabled=ready)


def request_for(inspection, *, ttl=900):
    predecessors = captured(inspection)
    scope = inspection['scope']
    return {'actor': deepcopy(ACTOR), 'reviewed': scope, 'predecessors': predecessors,
            'confirmation_digest': canonical_ordered_removal(scope, predecessors, ttl)[1], 'ttl_seconds': ttl}


async def inspection(client, *, device=None):
    response = await client.get(f'/api/v2/managed-ordered-removal-scope/{IP}',
                                params={} if device is None else {'device_id': device})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    return response.json()


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://private')


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('device', [None, 1])
def test_readonly_inspection_default_off_and_explicit_whole_scope_admission(composition, ordered, bulk, leases, enabled, device):
    _, store, agent, service = composition
    grant(bulk)
    original = running(bulk, leases)
    app = application(composition, enabled=enabled)
    before = dump(store)
    key = str(uuid4())

    async def scenario():
        async with client_for(app) as client:
            value = await inspection(client, device=device)
            assert value['disposition'] == 'WAITING_ADD' and value['device_work_admitted'] is False
            state = (await client.get('/api/v1/status')).json()
            assert state['ordered_removal_review_available'] is True
            assert state['ordered_removal_admission_enabled'] is enabled
            assert state['ordered_removal_promotion_enabled'] is True
            assert state['ready_removal_admission_enabled'] is False and dump(store) == before
            path = BASE + ('/fleet' if device is None else '/device')
            body = request_for(value)
            response = await client.post(path, json=body, headers={'Idempotency-Key': key})
            assert response.headers['cache-control'] == 'no-store'
            if not enabled:
                assert response.status_code == 503 and dump(store) == before
                return
            assert response.status_code == 202, response.text
            receipt = response.json()
            assert receipt['state'] == 'WAITING_ADD' and receipt['verified_removal'] is False
            assert receipt['target_count'] == (2 if device is None else 1)
            assert receipt['predecessor_count'] == 1 and receipt['device_work_admitted'] is False
            after = dump(store)
            service._wake.clear()
            replay = await client.post(path, json=body, headers={'Idempotency-Key': key})
            assert replay.json() == receipt | {'replayed': True}
            assert dump(store) == after and not service._wake.is_set()
            status = (await client.get(BASE + '/' + key)).json()
            assert status['scope'] == body['reviewed'] and status['state'] == 'WAITING_ADD'
            assert status['requested_at'] == receipt['requested_at'] and status['expires_at'] == receipt['expires_at']
            assert status['cleanup_jobs'] == [] and status['verified_removal'] is False
            assert status['predecessors'][0]['state'] == 'RUNNING' and dump(store) == after
    asyncio.run(scenario())
    assert not agent.seen
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (original[2]['id'],)).fetchone()[0] == 'RUNNING'
        if enabled:
            event = db.execute("SELECT actor_subject FROM shun_events WHERE event_type='MANAGED_ORDERED_REMOVAL_RESERVED'").fetchone()
            assert event[0] == ACTOR['subject']


@pytest.mark.parametrize('capability', [1, 'true', None])
def test_literal_capability_required_before_storage_creation(tmp_path, capability):
    store = Store(tmp_path / 'missing.db')
    with pytest.raises(ValueError): create_app(store=store, ordered_removal_admission_enabled=capability)
    assert not store.path.exists()


def test_enablement_without_runtime_refused_before_storage_creation(tmp_path):
    store = Store(tmp_path / 'missing.db')
    with pytest.raises(ValueError): create_app(store=store, ordered_removal_admission_enabled=True)
    assert not store.path.exists()


@pytest.mark.parametrize('missing', ['promotion', 'tables'])
def test_incompatible_enablement_never_binds_or_initializes(composition, ordered, missing):
    _, store, agent, service = composition
    if missing == 'promotion':
        service.ordered_promotion_enabled = False
    else:
        with store._connection() as db:
            db.execute('DROP TABLE managed_bulk_ordered_promotions')
    before = dump(store)
    with pytest.raises((ValueError, BulkUnavailable)): application(composition)
    assert dump(store) == before and not agent.seen and not getattr(service, '_api_application_bound', False)


def test_disabled_preflight_never_requires_or_creates_optional_profile(composition, bulk, leases):
    _, store, agent, _ = composition
    grant(bulk)
    running(bulk, leases)
    before = dump(store)
    app = application(composition, enabled=False)

    async def scenario():
        async with client_for(app) as client:
            value = await inspection(client)
            assert value['disposition'] == 'WAITING_ADD'
            response = await client.get(BASE + '/' + str(uuid4()))
            assert response.status_code == 503
            assert (await client.post(BASE + '/device', content='not-json')).status_code == 503
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('damage', [
    'actor_extra', 'unknown_role', 'viewer', 'mode', 'missing_key', 'alias_key', 'ttl_bool',
    'ttl_large', 'predecessor_extra', 'epoch_bool', 'epoch_string', 'missing_evidence',
    'scope_extra', 'digest_ready', 'digest_zero', 'stale', 'duplicate', 'action',
])
def test_strict_frozen_request_rejection_never_retires_or_admits(composition, ordered, bulk, leases, damage):
    _, store, agent, _ = composition
    grant(bulk)
    running(bulk, leases)
    app = application(composition)

    async def scenario():
        async with client_for(app) as client:
            body = request_for(await inspection(client))
            headers = {'Idempotency-Key': str(uuid4())}
            code = 422
            if damage == 'actor_extra': body['actor']['command'] = 'show shun'
            if damage == 'unknown_role': body['actor']['roles'] = ['Root']
            if damage == 'viewer': body['actor']['roles'], code = ['Viewer'], 403
            if damage == 'mode': body['reviewed']['scope'] = 'device'
            if damage == 'missing_key': headers = {}
            if damage == 'alias_key': headers['Idempotency-Key'] = headers['Idempotency-Key'].upper()
            if damage == 'ttl_bool': body['ttl_seconds'] = True
            if damage == 'ttl_large': body['ttl_seconds'] = 901
            if damage == 'predecessor_extra': body['predecessors'][0]['command'] = 'no shun'
            if damage == 'epoch_bool': body['predecessors'][0]['evidence']['executor_epoch'] = True
            if damage == 'epoch_string': body['predecessors'][0]['evidence']['executor_epoch'] = '1'
            if damage == 'missing_evidence': del body['predecessors'][0]['evidence']['claim_event_id']
            if damage == 'scope_extra': body['reviewed']['command'] = 'show shun'
            if damage == 'digest_ready':
                from ftd_shun_manager.bulk_removals import canonical_removal
                body['confirmation_digest'] = canonical_removal(body['reviewed'])[1]
            if damage == 'digest_zero': body['confirmation_digest'] = '0' * 64
            if damage == 'stale':
                store.record_observed_shun(3, IPv4Address(IP), 'management')
                code = 409
            if damage == 'duplicate': body['predecessors'] *= 2
            if damage == 'action': body['action'] = 'STOP_AND_REMOVE'
            before = dump(store)
            response = await client.post(BASE + '/fleet', json=body, headers=headers)
            assert response.status_code == code, response.text
            assert response.headers['cache-control'] == 'no-store' and dump(store) == before
    asyncio.run(scenario())
    assert not agent.seen


@pytest.mark.parametrize('outcome', ['NOOP', 'FAILED', 'UNVERIFIED'])
def test_current_status_distinct_from_original_receipt_and_cancel_preserves_evidence(composition, ordered, bulk, leases, outcome):
    _, store, agent, service = composition
    grant(bulk)
    predecessor = running(bulk, leases)
    app = application(composition)
    key = str(uuid4())

    async def scenario():
        async with client_for(app) as client:
            body = request_for(await inspection(client))
            receipt = (await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})).json()
            finish(leases, predecessor, None if outcome == 'NOOP' else outcome)
            assert service.ordered_promoter.advance(enabled=True) == 1
            before = dump(store)
            status = await client.get(BASE + '/' + key)
            assert status.status_code == 200 and dump(store) == before
            value = status.json()
            assert value['state'] == ('ADMITTED' if outcome == 'NOOP' else 'ATTENTION')
            assert value['device_work_admitted'] is (outcome == 'NOOP') and value['verified_removal'] is False
            assert value['predecessors'][0]['state'] == outcome
            assert (await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})).json() == receipt | {'replayed': True}
            cancelled = await client.post(BASE + '/' + key + '/cancel', json={'actor': ACTOR})
            if outcome == 'NOOP':
                assert cancelled.status_code == 409
                assert {job['state'] for job in value['cleanup_jobs']} == {'QUEUED'}
            else:
                assert cancelled.status_code == 200 and cancelled.json()['state'] == 'CANCELLED'
                status = (await client.get(BASE + '/' + key)).json()
                assert status['state'] == 'CANCELLED' and status['attention'] is True
                assert status['predecessors'][0]['state'] == outcome and status['verified_removal'] is False
    asyncio.run(scenario())
    assert not agent.seen


def test_cancellation_owner_admin_pause_and_new_admission_disabled(composition, ordered, bulk, leases):
    _, store, agent, service = composition
    grant(bulk)
    predecessor = running(bulk, leases)
    value = ordered.scopes.snapshot(IPv4Address(IP), now=bulk[1][0])
    body = request_for(value)
    key = str(uuid4())
    ordered.reserve(key, body['reviewed'], body['predecessors'], body['confirmation_digest'],
                    ACTOR['subject'], ACTOR['display_name'], tuple(ACTOR['roles']), enabled=True)
    service.ordered_promotion_enabled = False
    with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    app = application(composition, enabled=False)
    before = dump(store)

    async def scenario():
        async with client_for(app) as client:
            path = BASE + '/' + key + '/cancel'
            for actor in [ACTOR | {'subject': 'other'}, ACTOR | {'roles': ['Viewer']}]:
                assert (await client.post(path, json={'actor': actor})).status_code == 403
            assert (await client.post(path, json={'actor': ACTOR, 'resume': True})).status_code == 422
            assert dump(store) == before
            actor = ACTOR | {'subject': 'actual:administrator', 'roles': ['Administrator']}
            assert (await client.post(path, json={'actor': actor})).json()['state'] == 'CANCELLED'
            after = dump(store)
            assert (await client.post(path, json={'actor': actor})).json()['replayed'] is True
            assert dump(store) == after
            assert (await client.get(BASE + '/' + key)).json()['state'] == 'CANCELLED'
    asyncio.run(scenario())
    assert not agent.seen
    with store._connection() as db:
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (predecessor[2]['id'],)).fetchone()[0] == 'RUNNING'
        event = db.execute("SELECT actor_subject FROM shun_events WHERE event_type='MANAGED_ORDERED_REMOVAL_CANCELLED'").fetchone()
        assert event[0] == 'actual:administrator'


def test_status_verified_only_after_all_original_remove_outcomes(composition, ordered, bulk, leases):
    _, store, _, service = composition
    grant(bulk)
    predecessor = running(bulk, leases)
    app = application(composition)

    async def scenario():
        async with client_for(app) as client:
            body, key = request_for(await inspection(client)), str(uuid4())
            response = await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})
            assert response.status_code == 202
            finish(leases, predecessor)
            assert service.ordered_promoter.advance(enabled=True) == 1
            for device in (1, 2):
                token, queue = acquire(leases, device)
                job = queue.claim_removal(device, token.owner, queue.cutoff())
                assert job is not None
                queue.finish_removal(job['id'], token.owner, 'VERIFIED')
                leases.release(token)
                value = (await client.get(BASE + '/' + key)).json()
                assert value['verified_removal'] is (device == 2)
                assert len(value['cleanup_jobs']) == 2
            before = dump(store)
            assert (await client.get(BASE + '/' + key)).json()['verified_removal'] is True
            assert dump(store) == before
    asyncio.run(scenario())


def test_missing_canonical_keys_and_configured_ttl(composition, ordered, bulk, leases):
    grant(bulk)
    running(bulk, leases)
    settings = replace(composition[0], sensitive_action_max_age_seconds=60)
    app = application(composition, settings=settings)
    before = dump(composition[1])

    async def scenario():
        async with client_for(app) as client:
            key = str(uuid4())
            assert (await client.get(BASE + '/' + key)).status_code == 404
            assert (await client.post(BASE + '/' + key + '/cancel', json={'actor': ACTOR})).status_code == 404
            assert (await client.get(BASE + '/' + key.upper())).status_code != 200
            body = request_for(await inspection(client), ttl=61)
            assert (await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})).status_code == 422
            bulk[1][0] += timedelta(seconds=136)
            value = await inspection(client)
            assert value['disposition'] == 'BLOCKED'
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_concurrent_same_key_and_lost_response_do_not_duplicate_or_renew(composition, ordered, bulk, leases):
    _, store, agent, _ = composition
    grant(bulk)
    running(bulk, leases)
    app = application(composition)

    async def scenario():
        async with client_for(app) as client:
            body, key = request_for(await inspection(client)), str(uuid4())
            responses = await asyncio.gather(*[
                client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key}) for _ in range(3)])
            assert all(response.status_code == 202 for response in responses)
            receipts = [response.json() for response in responses]
            assert sum(not row['replayed'] for row in receipts) == 1
            assert all(row | {'replayed': False} == receipts[0] | {'replayed': False} for row in receipts)
            before = dump(store)
            # Discard the accepted reply; retry only the retained original key.
            bulk[1][0] += timedelta(seconds=30)
            replay = await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})
            assert replay.json() == receipts[0] | {'replayed': True} and dump(store) == before
            status = (await client.get(BASE + '/' + key)).json()
            assert status['expires_at'] == receipts[0]['expires_at']
            bulk[1][0] += timedelta(seconds=901)
            assert (await client.get(BASE + '/' + key)).json()['state'] == 'WAITING_ADD'
            assert dump(store) == before  # GET never expires, renews or promotes.
    asyncio.run(scenario())
    assert not agent.seen


def test_late_audit_failure_503_rolls_back_and_original_key_can_retry(composition, ordered, bulk, leases, monkeypatch):
    _, store, agent, _ = composition
    grant(bulk)
    running(bulk, leases)
    app = application(composition)
    insert = store._insert_event

    def fail(db, event, *args, **kwargs):
        if event == 'MANAGED_ORDERED_REMOVAL_RESERVED':
            raise sqlite3.OperationalError('Synthetic late audit failure')
        return insert(db, event, *args, **kwargs)

    async def scenario():
        async with client_for(app) as client:
            body, key = request_for(await inspection(client)), str(uuid4())
            before = dump(store)
            monkeypatch.setattr(store, '_insert_event', fail)
            response = await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})
            assert response.status_code == 503 and dump(store) == before
            monkeypatch.setattr(store, '_insert_event', insert)
            assert (await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})).status_code == 202
    asyncio.run(scenario())
    assert not agent.seen


def test_malformed_status_is_unavailable_not_not_found(composition, ordered, monkeypatch):
    app = application(composition, enabled=False)
    before = dump(composition[1])

    def fail(_key): raise KeyError('Missing retained evidence field')
    monkeypatch.setattr(app.state.synchronizer.ordered_removals, 'status', fail)

    async def scenario():
        async with client_for(app) as client:
            response = await client.get(BASE + '/' + str(uuid4()))
            assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_startup_rechecks_promotion_capability_without_initializing(composition, ordered):
    app = application(composition)
    service, store = composition[3], composition[1]
    service.ordered_promotion_enabled = False
    before = dump(store)

    async def scenario():
        with pytest.raises(ValueError):
            async with app.router.lifespan_context(app):
                pytest.fail('Invalid runtime must never start.')
    asyncio.run(scenario())
    assert dump(store) == before and service._task is None


def test_private_api_to_existing_continuous_fake_worker_end_to_end(composition, ordered, bulk, leases):
    _, store, agent, service = composition
    grant(bulk)
    predecessor = running(bulk, leases)
    agent.entries = {1: [ObservedShun(IPv4Address(IP), 'management')],
                     2: [ObservedShun(IPv4Address(IP), 'management')]}
    app = application(composition)

    async def scenario():
        async with client_for(app) as client:
            body, key = request_for(await inspection(client)), str(uuid4())
            response = await client.post(BASE + '/fleet', json=body, headers={'Idempotency-Key': key})
            assert response.status_code == 202
            finish(leases, predecessor)  # Synthetic predecessor/session release, no live ADD.
            async with app.router.lifespan_context(app):
                def verified():
                    with store._connection() as db:
                        return db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='VERIFIED'").fetchone()[0] == 2
                await until(verified)
                status = (await client.get(BASE + '/' + key)).json()
                assert status['state'] == 'ADMITTED' and status['verified_removal'] is True
                assert [job['device_id'] for job in status['cleanup_jobs']] == [1, 2]
                assert not any(kind == 'add' for kind, _, _ in agent.trace)
    asyncio.run(scenario())
    assert service._task is None
