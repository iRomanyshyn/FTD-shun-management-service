"""Explicit API/BFF composition with disposable v2 storage and semantic fakes."""

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import confirm, dump, no_work, prepare
from test_continuous_dispatch import TracedAgent, idle, until
from test_continuous_dispatch import bulk as bulk_fixture
from test_continuous_dispatch import cancellation_controls as cancellation_fixture
from test_continuous_dispatch import dispatch as dispatch_fixture
from test_continuous_dispatch import journal as journal_fixture
from test_continuous_dispatch import leases as leases_fixture
from test_continuous_dispatch import waits as waits_fixture
from test_device_leases import grant

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import UnixAgentClient
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.config import Settings
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def composition(bulk, leases):
    store, agent = leases.store, TracedAgent()
    with store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>4')
        db.execute('UPDATE protected_policy SET legacy_imported=1')
    settings = Settings(store.path, None, '/unused/agent.sock', '/unused/web.sock', '/unused/api.sock',
                        'socket', 120, 300, 60, 366, 86400, False,
                        agent_cycles_enabled=True, large_snapshots_enabled=True)
    service = ContinuousDispatcher(store, agent, enabled=True, agent_concurrency=2)
    return settings, store, agent, service


def test_existing_policy_read_constructor_never_initializes_queue(tmp_path):
    store = Store(tmp_path / 'absent.db')
    ProtectedPolicy(store, initialize_queue=False)
    assert not store.path.exists()
    with pytest.raises(ValueError): ProtectedPolicy(store, initialize_queue=0)
    assert not store.path.exists()


def test_api_construction_gets_and_refused_workflows_do_not_initialize_or_mutate(composition, monkeypatch):
    settings, store, agent, service = composition
    before = dump(store)

    def forbidden(*_args, **_kwargs):
        raise AssertionError('No initialization or legacy environment import is permitted.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    monkeypatch.setattr(ProtectedPolicy, 'migrate_legacy_environment', forbidden)
    monkeypatch.setenv('FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS', 'must-not-be-read')
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    assert app.state.synchronizer.dispatcher is service

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            result = await client.get('/api/v1/status')
            assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
            status = result.json()
            assert status['managed_policy_initialized'] is True and status['managed_policy_format'] == 2
            assert status['runtime_mode'] == 'continuous-observation'
            assert not status['manual_mutations_available'] and not status['refresh_enabled']
            assert (await client.post('/api/v1/refresh-hint')).status_code == 503
            for method, path in [('POST', '/api/v1/imports'), ('POST', '/api/v1/managed-shuns/maintain'),
                                 ('GET', '/api/v1/managed-shuns/page'), ('POST', '/api/v1/managed-removals/device'),
                                 ('DELETE', '/api/v1/devices/1/shuns/198.51.100.1'),
                                 ('POST', '/api/v1/shuns/198.51.100.1/remove-all'),
                                 ('POST', '/api/v1/operations/11111111-1111-4111-8111-111111111111/cancel')]:
                response = await client.request(method, path, json={})
                assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
                assert 'no request was admitted' in response.json()['detail']
            for path in ['/api/v1/shuns', '/api/v1/history', '/api/v1/history-page', '/api/v1/protected-ips']:
                assert (await client.get(path)).status_code == 200
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('change', [
    {'agent_mode': 'disabled'}, {'agent_mode': 'mock'}, {'agent_cycles_enabled': False},
    {'large_snapshots_enabled': False}, {'import_admission_enabled': True},
    {'managed_policy_admission_enabled': True}, {'managed_removal_worker_enabled': True},
    {'managed_removal_worker_enabled': True, 'managed_removal_admission_enabled': True},
    {'poll_interval_seconds': 600}, {'interactive_refresh_min_interval_seconds': 120},
    {'agent_timeout_seconds': 45}, {'history_retention_days': 367},
    {'development_auth': True},
])
def test_mixed_runtime_configuration_refused_before_any_change(composition, change):
    settings, store, agent, service = composition
    before = dump(store)
    with pytest.raises(ValueError): create_app(replace(settings, **change), store, agent, continuous_dispatcher=service)
    assert dump(store) == before and not agent.seen and service._task is None


@pytest.mark.parametrize('damage', ['marker', 'capacity', 'settlement', 'settlement_optout', 'add', 'inventory', 'other_agent', 'other_store'])
def test_composition_scope_and_capability_mismatch_never_falls_back(composition, tmp_path, damage):
    settings, store, agent, service = composition
    if damage == 'marker':
        with store._connection() as db: db.execute('UPDATE protected_policy SET legacy_imported=0')
    elif damage == 'capacity': service.runner.agent_concurrency = 1
    elif damage == 'settlement': agent.settled_cycles = False
    elif damage == 'settlement_optout': service.runner.settled_cycles_required = False
    elif damage == 'add': service.runner.configuration['bulk_dispatch_enabled'] = True
    elif damage == 'inventory': settings = replace(settings, device_inventory_path=tmp_path / 'not-read.json')
    elif damage == 'other_agent': agent = TracedAgent()
    elif damage == 'other_store': store = Store(tmp_path / 'not-created.db')
    before = dump(service.runner.store)
    with pytest.raises((ValueError, QueueConflict)):
        create_app(settings, store, agent, continuous_dispatcher=service)
    assert dump(service.runner.store) == before and not agent.seen
    if damage == 'other_store': assert not store.path.exists()


def test_application_binding_and_startup_drift_do_not_migrate_or_start_work(composition):
    settings, store, agent, service = composition
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    with pytest.raises(QueueConflict, match='bound'):
        create_app(settings, store, agent, continuous_dispatcher=service)
    with store._connection() as db: db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    before = dump(store)

    async def scenario():
        with pytest.raises(BulkUnavailable):
            async with app.router.lifespan_context(app):
                raise AssertionError('Invalid profile must not enter lifespan.')
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen
    assert service._task is None and not service.maintenance.status()['running']


def test_real_api_lifecycle_reads_refresh_and_atomic_protection_without_add(composition, bulk, monkeypatch):
    settings, store, agent, service = composition
    grant(bulk, devices=(1,))  # Synthetic standing authority, not live activation.
    ip = IPv4Address('198.51.100.1')
    agent.entries[1] = [ObservedShun(ip, 'management')]
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Neither app construction nor first device visit may initialize schemas.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    app = create_app(settings, store, agent, continuous_dispatcher=service)

    async def scenario():
        async with app.router.lifespan_context(app):
            await idle(service, agent)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
                assert (await client.get('/api/v1/shuns')).json()[0]['ip'] == str(ip)
                assert (await client.get('/api/v1/search', params={'ip': str(ip)})).json()[0]['active']
                preview = await client.post('/api/v1/import-preview', json={'ips': [str(ip)], 'device_ids': [1]})
                assert preview.status_code == 200 and preview.json()['can_execute'] is False
                hint = (await client.post('/api/v1/refresh-hint')).json()
                assert hint['refresh']['pending_refresh_device_count'] == 4
                assert hint['refresh']['refresh_schedule_mode'] == 'per_device'
                policy = (await client.get('/api/v1/protected-ips')).json()
                protected = await client.post(f'/api/v1/protected-ips/{ip}/add', json={
                    'actor': {'subject': 'synthetic:viewer', 'display_name': 'Synthetic viewer', 'roles': ['Viewer']},
                    'revision': policy['revision'], 'managed_revision': 1, 'name': 'Fixture office'})
                assert protected.status_code == 200
                await until(lambda: bool(agent.removals))
                with store._connection() as db:
                    assert db.execute('SELECT enabled FROM managed_shun_targets WHERE device_id=1 AND ip=?', (ip.packed,)).fetchone()[0] == 0
                assert not agent.writes
        assert not service.status()['running'] and not service.maintenance.status()['running']
        assert not service.runner._service_active and not agent.active
    asyncio.run(scenario())


def test_started_controller_cannot_be_adopted_by_api(composition):
    settings, store, agent, service = composition

    async def scenario():
        await service.start()
        try:
            with pytest.raises(QueueConflict, match='exclusively'):
                create_app(settings, store, agent, continuous_dispatcher=service)
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_actual_bff_to_api_status_policy_auth_csrf_and_unavailable_controls(composition, monkeypatch):
    settings, store, agent, service = composition
    ip = IPv4Address('198.51.100.44')
    agent.entries[1] = [ObservedShun(ip, 'management')]
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    calls = []

    async def scenario():
        loop = asyncio.get_running_loop()

        def internal(request):
            calls.append((request.method, request.url.path))

            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
                    return await client.request(request.method, str(request.url), content=request.content, headers=request.headers)
            # BFF sync routes run in worker threads; the real API stays on its
            # owning loop, including demand/callbacks and lifespan drain.
            response = asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=10)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(
            transport=httpx.MockTransport(internal), base_url='http://internal'))
        async with app.router.lifespan_context(app):
            await idle(service, agent)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(settings)), base_url='https://fixture.test') as bff:
                assert (await bff.get('/refresh-status')).status_code == 401
                assert not calls
                bff.headers.update({'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'})
                detail = await bff.get(f'/shuns/{ip}')
                assert detail.status_code == 200
                assert 'data-queue-form' not in detail.text
                assert 'href="/managed-shuns"' in detail.text
                assert 'href="/imports"' in detail.text
                assert 'Continuous observation profile' in detail.text
                preview = await bff.get('/imports')
                assert preview.status_code == 200 and 'formaction="/imports/review"' not in preview.text
                status = await bff.get('/refresh-status')
                assert status.status_code == 200 and status.headers['cache-control'] == 'no-store'
                assert status.json()['runtime_mode'] == 'continuous-observation'
                assert status.json()['managed_policy_format'] == 2
                assert status.json()['manual_mutations_available'] is False
                before = len(calls)
                assert (await bff.post('/refresh', data={'csrf': 'wrong'})).status_code == 403
                assert len(calls) == before
                csrf = bff.cookies.get('ftd_shun_csrf')
                refresh = await bff.post('/refresh', data={'csrf': csrf}, headers={'Accept': 'application/json'})
                assert refresh.status_code == 200 and refresh.json()['pending_refresh_device_count'] == 4
                protected = await bff.post('/protected-ips/add', data={
                    'csrf': csrf, 'ip': '198.51.100.45', 'revision': '0', 'managed_revision': '0',
                    'enabled': 'true', 'name': 'Synthetic office'}, headers={'Accept': 'application/json'})
                assert protected.status_code == 200
                event = next(row for row in store.list_events() if row['event_type'] == 'PROTECTED_IP_ADDED')
                assert event['actor_subject'] == 'alice' and event['actor_roles'] == ['Operator']
                assert not agent.writes and not agent.removals
        assert not service.status()['running'] and not service.maintenance.status()['running']
    asyncio.run(scenario())


def test_runtime_status_schema_drift_is_503_not_empty_legacy_state(composition):
    settings, store, agent, service = composition
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    with store._connection() as db: db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    before = dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            response = await client.get('/api/v1/status')
            assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
            assert 'no successful device operation' in response.json()['detail']
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


def test_legacy_default_refuses_fenced_profile_without_initialization(composition, monkeypatch):
    settings, store, agent, _service = composition
    before = dump(store)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Legacy profile must refuse before initialization.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    with pytest.raises(QueueConflict, match='legacy startup'):
        create_app(settings, store, agent)
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('field,value', [('socket_path', '/wrong/agent.sock'), ('timeout_seconds', 120),
    ('large_snapshots', False), ('settled_cycles', False), ('additions_enabled', True), ('addition_device_ids', None)])
def test_real_transport_configuration_cannot_disagree_with_api(composition, field, value):
    settings, store, agent, service = composition
    transport = UnixAgentClient(settings.agent_socket, 125, large_snapshots=True, settled_cycles=True,
                                addition_device_ids=frozenset())
    setattr(transport, field, value)
    service.runner.agent = transport
    before = dump(store)
    with pytest.raises((ValueError, QueueConflict)):
        create_app(settings, store, transport, continuous_dispatcher=service)
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('field,internal', [('poll_interval_seconds', 'poll_interval_seconds'),
    ('interactive_refresh_min_interval_seconds', 'interactive_min_interval_seconds')])
def test_matching_internal_test_timers_cannot_weaken_api_read_spacing(composition, field, internal):
    settings, store, agent, service = composition
    settings = replace(settings, **{field: 1})
    service.runner.configuration[internal] = 1
    before = dump(store)
    with pytest.raises(ValueError, match='floors'):
        create_app(settings, store, agent, continuous_dispatcher=service)
    assert dump(store) == before and not agent.seen


def retirement_body(revision=1):
    reason = 'Synthetic revocation only'
    return {'actor': {'subject': 'alice', 'display_name': 'Actual author', 'roles': ['Operator']},
            'device_id': 1, 'ip': '198.51.100.1', 'managed_revision': revision, 'reason': reason,
            'confirmation_digest': canonical_managed_change('RETIRE', [(1, IPv4Address('198.51.100.1'))],
                                                           revision, 0, reason=reason)[2]}


def test_v2_private_policy_reads_retirement_and_original_key_replay_never_admit_device_work(composition, bulk):
    settings, store, agent, service = composition
    confirm(bulk, prepare(bulk)[1])
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    before = dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            page = await client.get('/api/v2/managed-shuns/page')
            assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
            assert page.json()['intent_format'] == 2 and page.json()['limit'] == 200000
            body = {'revision': 1, 'targets': [{'device_id': 1, 'ip': '198.51.100.1'}]}
            selection = await client.post('/api/v2/managed-shuns/selection', json=body)
            assert selection.status_code == 200 and selection.json()['selected_count'] == 1
            assert (await client.post('/api/v2/managed-shuns/selection', json={**body, 'revision': 0})).status_code == 409
            assert (await client.post('/api/v2/managed-shuns/selection', json={**body, 'targets': body['targets'] * 2})).status_code == 422
            assert (await client.get('/api/v2/managed-shuns/page?page=2')).status_code == 422
            assert dump(store) == before and not agent.seen
            headers = {'Idempotency-Key': str(uuid4())}
            response = await client.post('/api/v2/managed-shuns/retire', json=retirement_body(), headers=headers)
            assert response.status_code == 200
            receipt = response.json()
            assert receipt['changed_targets'] == 1 and receipt['managed_revision'] == 2
            assert receipt['intent_format'] == 2 and receipt['policy_only'] is True
            assert receipt['device_work_admitted'] is False and not receipt['replayed']
            # New consent may create a new generation in the synthetic policy
            # fixture. Replaying old consent must not retire that newer grant.
            confirm(bulk, prepare(bulk)[1])
            replay = await client.post('/api/v2/managed-shuns/retire', json=retirement_body(), headers=headers)
            assert replay.status_code == 200 and replay.json() == {**receipt, 'replayed': True}
            current = (await client.get('/api/v2/managed-shuns/page')).json()
            assert current['entries'][0]['enabled'] and current['entries'][0]['generation'] == 2
            assert (await client.get('/api/v2/managed-shuns/page?revision=1')).status_code == 409
            assert (await client.post('/api/v1/managed-shuns/retire', json=retirement_body(), headers=headers)).status_code == 503
            assert (await client.post('/api/v1/managed-removals/device', json={})).status_code == 503
    asyncio.run(scenario())
    no_work(bulk[0])
    assert not agent.seen and service._task is None
    event = next(row for row in store.list_events() if row['event_type'] == 'MANAGED_SHUN_RETIRED')
    assert event['actor_subject'] == 'alice' and event['actor_roles'] == ['Operator']


@pytest.mark.parametrize('override,expected', [
    ({'device_id': True}, 422), ({'managed_revision': True}, 422), ({'action': 'MAINTAIN'}, 422),
    ({'confirmation_digest': '0' * 64}, 422),
    ({'actor': {'subject': 'viewer', 'display_name': 'Viewer', 'roles': ['Viewer']}}, 403),
])
def test_v2_retirement_strict_roles_fields_and_digest_have_no_effect(composition, bulk, override, expected):
    settings, store, agent, service = composition
    confirm(bulk, prepare(bulk)[1])
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    before = dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            response = await client.post('/api/v2/managed-shuns/retire', json=retirement_body() | override,
                                         headers={'Idempotency-Key': str(uuid4())})
            assert response.status_code == expected
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


@pytest.fixture
def policy_browser(composition, monkeypatch):
    settings, store, agent, service = composition
    app = create_app(settings, store, agent, continuous_dispatcher=service)
    calls = []

    @asynccontextmanager
    async def browser():
        loop = asyncio.get_running_loop()

        def internal(request):
            calls.append((request.method, request.url.path))

            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
                    return await client.request(request.method, str(request.url), content=request.content, headers=request.headers)
            response = asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=10)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(
            transport=httpx.MockTransport(internal), base_url='http://internal'))
        # Deliberately no lifespan: policy views/revocation must work without
        # starting discovery, maintenance, an executor or any agent session.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(settings)),
                                     base_url='https://fixture.test', headers={
                                         'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'}) as client:
            yield client, calls
    return browser


def test_actual_v2_bff_page_frozen_review_csrf_roles_revocation_and_replay(composition, bulk, policy_browser):
    _, store, agent, service = composition
    confirm(bulk, prepare(bulk)[1])
    before = dump(store)

    async def scenario():
        async with policy_browser() as (client, calls):
            page = await client.get('/managed-shuns')
            assert page.status_code == 200 and 'Version-2 standing policy' in page.text
            assert 'Review stop maintaining only' in page.text and 'combined device removal are unavailable' in page.text
            assert (await client.get('/managed-shuns?page=1&revision=0')).status_code == 200
            assert 'No scope was rebased' in (await client.get('/managed-shuns?revision=0')).text
            csrf = client.cookies.get('ftd_shun_csrf')
            review = await client.post('/managed-shuns/retirement-review', data={
                'csrf': csrf, 'target': '1:198.51.100.1', 'reason': 'Synthetic stop'})
            assert review.status_code == 200 and 'Version 2 · frozen with this review' in review.text
            assert dump(store) == before
            fields = {'csrf': csrf, 'review': re.search('name="review" value="([^"]+)"', review.text)[1],
                      'confirm_ip': '198.51.100.1'}
            count = len(calls)
            assert (await client.post('/managed-shuns/retirement-confirm', data={**fields, 'csrf': 'wrong'})).status_code == 403
            assert (await client.post('/managed-shuns/retirement-confirm', data={**fields, 'device_id': '2'})).status_code == 422
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await client.post('/managed-shuns/retirement-confirm', data=fields)).status_code == 403
            client.headers['Remote-Groups'] = 'ftd-shun-operators'
            assert len(calls) == count and dump(store) == before
            saved = await client.post('/managed-shuns/retirement-confirm', data=fields)
            assert saved.status_code == 200 and '1 target retired by the original request' in saved.text
            assert (await client.post('/managed-shuns/retirement-confirm', data=fields)).status_code == 200
            assert not bulk[0].policy_page()['entries'][0]['enabled']
            assert not any(path.startswith('/api/v1/managed-shuns') for _, path in calls)
            assert sum(path == '/api/v2/managed-shuns/retire' for _, path in calls) == 2
    asyncio.run(scenario())
    no_work(bulk[0])
    assert not agent.seen and service._task is None


def test_v2_frozen_review_conflict_never_rebases_target_or_revision(composition, bulk, policy_browser):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk)[1])

    async def scenario():
        async with policy_browser() as (client, calls):
            await client.get('/managed-shuns')
            csrf = client.cookies.get('ftd_shun_csrf')
            review = await client.post('/managed-shuns/retirement-review', data={'csrf': csrf, 'target': '1:198.51.100.1'})
            token = re.search('name="review" value="([^"]+)"', review.text)[1]
            confirm(bulk, prepare(bulk, '198.51.100.2')[1])
            before = dump(store)
            response = await client.post('/managed-shuns/retirement-confirm', data={
                'csrf': csrf, 'review': token, 'confirm_ip': '198.51.100.1'})
            assert response.status_code == 409 and dump(store) == before
            assert sum(path == '/api/v2/managed-shuns/retire' for _, path in calls) == 1
    asyncio.run(scenario())
    assert not agent.seen


@pytest.mark.parametrize('response_mode', ['status_drift', 'unavailable', 'malformed_receipt'])
def test_v2_confirmation_never_falls_back_or_reinterprets_its_frozen_format(
        composition, bulk, policy_browser, monkeypatch, response_mode):
    _, _, agent, _ = composition
    confirm(bulk, prepare(bulk)[1])

    async def scenario():
        async with policy_browser() as (client, _calls):
            await client.get('/managed-shuns')
            csrf = client.cookies.get('ftd_shun_csrf')
            review = await client.post('/managed-shuns/retirement-review', data={'csrf': csrf, 'target': '1:198.51.100.1'})
            token = re.search('name="review" value="([^"]+)"', review.text)[1]
            original, attempted = web.api_client, []

            def intercept(request):
                attempted.append(request.url.path)
                if response_mode == 'unavailable' and request.method == 'POST':
                    return httpx.Response(503, json={'detail': 'Synthetic endpoint unavailable.'})
                with original(None) as internal:
                    response = internal.request(request.method, str(request.url), content=request.content,
                                                headers=request.headers)
                value = response.json()
                if response_mode == 'status_drift' and request.url.path == '/api/v1/status':
                    value['managed_policy_format'] = 1
                elif response_mode == 'malformed_receipt' and request.method == 'POST':
                    value['intent_format'] = 2.0  # Numerically equal is not a literal version.
                return httpx.Response(response.status_code, json=value)

            monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(
                transport=httpx.MockTransport(intercept), base_url='http://internal'))
            response = await client.post('/managed-shuns/retirement-confirm', data={
                'csrf': csrf, 'review': token, 'confirm_ip': '198.51.100.1'})
            assert response.status_code == (200 if response_mode == 'status_drift' else 503)
            assert attempted.count('/api/v2/managed-shuns/retire') == 1
            assert '/api/v1/managed-shuns/retire' not in attempted
            assert bool(bulk[0].policy_page()['entries'][0]['enabled']) is (response_mode == 'unavailable')
            if response_mode == 'malformed_receipt':
                assert 'Retirement outcome is unknown' in response.text
    asyncio.run(scenario())
    no_work(bulk[0])
    assert not agent.seen
