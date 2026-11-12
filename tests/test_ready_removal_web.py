"""Actual v2 BFF/API admission on disposable state, never lab/FTD writes."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
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

from ftd_shun_manager import managed_review, web
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_removal_review import ReadyRemovalReviews
from ftd_shun_manager.bulk_removals import BulkRemovalScopes
from ftd_shun_manager.import_review import ReviewUnavailable
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
def surface(composition, monkeypatch):
    settings, store, agent, service = composition

    @asynccontextmanager
    async def browser(*, api_enabled=False, web_enabled=False, transform=None, start=False):
        app = create_app(settings, store, agent, continuous_dispatcher=service,
                         ready_removal_admission_enabled=api_enabled)
        loop, calls = asyncio.get_running_loop(), []

        def internal(request):
            calls.append((request.method, request.url.path, request.content))

            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as api:
                    return await api.request(request.method, str(request.url), content=request.content, headers=request.headers)
            response = asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=10)
            if transform:
                response = transform(request, response)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(
            transport=httpx.MockTransport(internal), base_url='http://internal'))
        bff = web.create_app(settings, ready_removal_admission_enabled=web_enabled)
        # Explicit lifespan only for the actual worker scenario, not policy tests.
        @asynccontextmanager
        async def lifecycle():
            if start:
                async with app.router.lifespan_context(app):
                    yield
            else:
                yield
        async with lifecycle(), httpx.AsyncClient(transport=httpx.ASGITransport(app=bff), base_url='https://fixture.test',
                headers={'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'}) as client:
            yield client, app, calls
    return browser


def test_dialog_button_consent_keeps_original_scope_actor_and_replay(surface, bulk, composition):
    confirm(bulk, prepare(bulk)[1])

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _, calls):
            page, fields = await review(client)
            assert 'name="confirm_ip"' not in page.text
            fields.pop('confirm_ip')
            before = len([call for call in calls if call[0] == 'POST'])
            for action in ('', 'stop-restoring', 'yes'):
                response = await client.post('/managed-shuns/v2/removal-confirm',
                    data=fields | {'confirm_action': action}, headers={'Accept': 'text/html'})
                assert response.status_code == 422
                assert 'text/html' in response.headers['content-type'] and 'Request unavailable' in response.text
            assert len([call for call in calls if call[0] == 'POST']) == before
            consent = fields | {'confirm_action': 'unblock'}
            first = await client.post('/managed-shuns/v2/removal-confirm', data=consent,
                                      headers={'Accept': 'text/html', 'X-Action-Dialog': '1'})
            assert first.status_code == 200 and 'Removal queued' in first.text
            second = await client.post('/managed-shuns/v2/removal-confirm', data=consent)
            assert second.status_code == 200 and 'Original-key replay' in second.text
            assert not composition[2].seen  # Admission is not a device operation.
    asyncio.run(scenario())


def test_browser_form_errors_are_html_but_json_clients_keep_structured_errors(surface):
    async def scenario():
        async with surface() as (client, _, calls):
            await client.get('/managed-shuns')
            fields = {'csrf': client.cookies.get('ftd_shun_csrf'), 'request_id': str(uuid4()), 'confirm_ip': 'wrong'}
            response = await client.post(f'/shuns/{IP}/remove-all', data=fields, headers={'Accept': 'text/html'})
            assert response.status_code == 400 and 'text/html' in response.headers['content-type']
            assert 'Confirm unblocking' in response.text and not response.text.startswith('{')
            response = await client.post(f'/shuns/{IP}/remove-all', data=fields, headers={'Accept': 'application/json'})
            assert response.status_code == 400 and type(response.json()['detail']) is str
            invalid = await client.post('/devices/1/shuns/not-an-ip/remove', data=fields,
                                        headers={'Accept': 'text/html'})
            assert invalid.status_code == 422 and 'text/html' in invalid.headers['content-type']
            assert not any(method == 'DELETE' or (method == 'POST' and 'remove-all' in path) for method, path, _ in calls)
    asyncio.run(scenario())


def test_ordinary_browser_unblock_prepares_then_queues_same_operation_key(surface, composition):
    store = composition[1]
    store.reconcile_snapshot(1, [(IP, 'management')])

    def legacy_ack(request, response):
        # This fixture's real API is continuous-only. Model only the distinct
        # legacy API acknowledgement to exercise the BFF dialog presentation.
        return httpx.Response(202, json={'fixture': 'legacy admission'}) if request.method == 'DELETE' else response

    async def scenario():
        async with surface(transform=legacy_ack) as (client, _, calls):
            await client.get('/managed-shuns')
            fields = {'csrf': client.cookies.get('ftd_shun_csrf'), 'request_id': str(uuid4())}
            path = f'/devices/1/shuns/{IP}/remove'
            page = await client.post(path, data=fields, headers={'Accept': 'text/html', 'X-Action-Dialog': '1'})
            assert page.status_code == 200 and f'Unblock {IP}?' in page.text
            assert 'name="confirm_ip"' not in page.text and fields['request_id'] in page.text
            assert not any(method == 'DELETE' for method, _, _ in calls)
            result = await client.post(path, data=fields | {'confirm_action': 'unblock'},
                                       headers={'Accept': 'text/html', 'X-Action-Dialog': '1'})
            assert result.status_code == 200 and 'Unblock request queued' in result.text
            assert len([call for call in calls if call[0] == 'DELETE']) == 1
    asyncio.run(scenario())


async def review(client, *, fleet=False):
    page = await client.get('/managed-shuns')
    assert page.status_code == 200 and 'ready-removal-preparation' in page.text
    response = await client.post('/managed-shuns/v2/' + ('fleet-removal-review' if fleet else 'removal-review'),
        data={'csrf': client.cookies.get('ftd_shun_csrf'), **({'ip': str(IP)} if fleet else {'target': f'1:{IP}'}),
              'reason': 'Synthetic removal'})
    assert response.status_code == 200
    return response, {'csrf': client.cookies.get('ftd_shun_csrf'),
                      'review': re.search('name="review" value="([^"]+)"', response.text)[1], 'confirm_ip': str(IP)}


def queued_count(store):
    with store._connection() as db:
        return db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0]


@pytest.mark.parametrize('api_gate,web_gate', [(False, False), (False, True), (True, False)])
def test_independent_default_off_gates_allow_review_but_never_submit(composition, bulk, surface, api_gate, web_gate):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk)[1])
    before = dump(store)

    async def scenario():
        async with surface(api_enabled=api_gate, web_enabled=web_gate) as (client, _, calls):
            page, fields = await review(client)
            assert re.search(r'<button[^>]*name="confirm_action"[^>]* disabled', page.text)
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 503 and 'not submitted' in response.text
            assert not any(method == 'POST' and path.startswith('/api/v2/managed-removals/') for method, path, _ in calls)
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


def test_ip_workspace_includes_absent_maintained_devices_and_only_prepares_existing_reviews(composition, bulk, surface):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    before = dump(store)

    async def scenario():
        async with surface() as (client, _, calls):
            page = await client.get(f'/shuns/{IP}')
            assert page.status_code == 200
            assert page.text.count('class="ip-device-card"') == 2
            assert 'No block observed' in page.text and 'Stop restoring…' in page.text
            assert 'action="/ip-actions/unblock"' in page.text
            assert 'action="/managed-shuns/retirement-review"' in page.text
            assert f'name="target" value="1:{IP}"' in page.text
            assert f'href="/protected-ips?ip={IP}#add-protected-ip"' in page.text
            assert all(method == 'GET' for method, _, _ in calls)
            response = await client.post('/managed-shuns/retirement-review', data={
                'csrf': client.cookies.get('ftd_shun_csrf'), 'target': f'1:{IP}'})
            assert response.status_code == 200 and 'value="stop-restoring"' in response.text
            response = await client.post('/managed-shuns/v2/removal-review', data={
                'csrf': client.cookies.get('ftd_shun_csrf'), 'target': f'1:{IP}'})
            assert response.status_code == 200 and 'value="unblock"' in response.text
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            viewer = await client.get(f'/shuns/{IP}')
            assert viewer.status_code == 200 and 'Read-only.' in viewer.text
            assert 'action="/ip-actions/unblock"' not in viewer.text
            assert 'action="/managed-shuns/retirement-review"' not in viewer.text
            assert 'Protect IP…' in viewer.text  # Shared authenticated policy access.
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('damage', ['wrong_ip', 'wrong_digest', 'mutable', 'wrong_scope', 'truncated', 'unavailable'])
def test_ip_workspace_rejects_substituted_or_unavailable_local_scope(composition, bulk, surface, damage):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk)[1])
    before = dump(store)

    def transform(request, response):
        if request.url.path != f'/api/v2/managed-removal-scope/{IP}': return response
        if damage == 'unavailable': return httpx.Response(503, json={})
        value = response.json()
        if damage == 'wrong_ip': value['ip'] = '198.51.100.2'
        elif damage == 'wrong_digest': value['scope_digest'] = 'f' * 64
        elif damage == 'mutable': value['read_only'] = False
        elif damage == 'wrong_scope': value['scope'] = 'device'
        elif damage == 'truncated': value['targets'] = []
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, calls):
            page = await client.get(f'/shuns/{IP}')
            assert page.status_code == 200 and 'Device actions could not be loaded.' in page.text
            assert 'class="ip-device-card"' not in page.text
            assert all(method == 'GET' for method, _, _ in calls)
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


@pytest.mark.parametrize('fleet', [False, True])
def test_actual_confirm_queues_exact_scope_with_real_actor_and_replays_only_original_receipt(composition, bulk, surface, fleet):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _, calls):
            page, fields = await review(client, fleet=fleet)
            before = dump(store)
            assert 'Preparatory review — execution is unavailable' not in page.text
            assert 'Ready-only local admission' in page.text and dump(store) == before
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 200 and 'Removal queued — not verified removal' in response.text
            after = dump(store)
            replay = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert replay.status_code == 200 and 'Original-key replay' in replay.text and dump(store) == after
            posts = [(path, json.loads(body)) for method, path, body in calls if method == 'POST' and '/managed-removals/' in path]
            assert [path for path, _ in posts] == ['/api/v2/managed-removals/' + ('fleet' if fleet else 'device')] * 2
            assert all(body['actor']['subject'] == 'alice' and body['actor']['roles'] == ['Operator'] for _, body in posts)
    asyncio.run(scenario())
    assert queued_count(store) == (2 if fleet else 1) and not agent.seen
    event = next(row for row in store.list_events() if row['event_type'] == 'MANAGED_READY_REMOVAL_ADMITTED')
    assert event['actor_subject'] == 'alice'


def test_forged_fields_wrong_ip_csrf_identity_roles_and_cross_purpose_tokens_do_not_admit(composition, bulk, surface):
    _, store, agent, _ = composition
    confirm(bulk, prepare(bulk)[1])
    before = dump(store)

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _, calls):
            _, fields = await review(client)
            for extra in ({'actor': 'forged'}, {'device_id': '2'}, {'scope': 'fleet'}, {'reviewed': '{}'}, {'ordered_wait': 'yes'}):
                assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields | extra)).status_code == 422
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields | {'csrf': 'wrong'})).status_code == 403
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields | {'confirm_ip': '198.51.100.2'})).status_code == 422
            client.headers['Remote-User'] = 'bob'
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields)).status_code == 409
            client.headers['Remote-User'] = 'alice'
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields)).status_code == 403
            client.headers['Remote-Groups'] = 'ftd-shun-operators'
            retired = await client.post('/managed-shuns/retirement-review', data={
                'csrf': fields['csrf'], 'target': f'1:{IP}'})
            other = re.search('name="review" value="([^"]+)"', retired.text)[1]
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields | {'review': other})).status_code == 409
            client.headers.pop('Remote-User')
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields)).status_code == 401
            assert not any(method == 'POST' and '/managed-removals/' in path for method, path, _ in calls)
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen


def test_changed_fleet_membership_conflicts_without_partial_retirement(composition, bulk, surface):
    _, store, _, _ = composition
    confirm(bulk, prepare(bulk)[1])

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _, _calls):
            _, fields = await review(client, fleet=True)
            store.record_observed_shun(2, IP, 'management')
            before = dump(store)
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 409 and dump(store) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'version', 'verified', 'scope', 'count', 'job_device', 'job_key', 'expiry'])
def test_lost_or_malformed_receipt_is_unknown_and_same_key_retry_never_duplicates(composition, bulk, surface, damage):
    _, store, _, _ = composition
    confirm(bulk, prepare(bulk)[1])
    altered = [False]

    def transform(request, response):
        if request.method != 'POST' or not request.url.path.startswith('/api/v2/managed-removals/') or altered[0]:
            return response
        altered[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic reply lost after commit', request=request)
        value = response.json()
        if damage == 'version': value['intent_format'] = 2.0
        elif damage == 'verified': value['verified_removal'] = True
        elif damage == 'scope': value['scope'] = 'fleet'
        elif damage == 'count': value['target_count'] = True
        elif damage == 'job_device': value['jobs'][0]['device_id'] = 2
        elif damage == 'job_key': value['jobs'][0]['job_id'] = value['operation_id']
        elif damage == 'expiry': value['expires_at'] = 'not a timestamp'
        return httpx.Response(response.status_code, json=value)

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True, transform=transform) as (client, _, _calls):
            _, fields = await review(client)
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 503 and 'outcome is unknown' in response.text
            assert queued_count(store) == 1
            before = dump(store)
            retry = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert retry.status_code == 200 and 'Original-key replay' in retry.text
            assert dump(store) == before
    asyncio.run(scenario())


def test_valid_receipt_survives_optional_status_failure(composition, bulk, surface):
    confirm(bulk, prepare(bulk)[1])
    submitted = [False]
    def transform(request, response):
        if request.url.path.startswith('/api/v2/managed-removals/'): submitted[0] = True
        if submitted[0] and request.url.path == '/api/v1/status': return httpx.Response(503, json={'detail': 'Synthetic unavailable'})
        return response

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True, transform=transform) as (client, _, _):
            _, fields = await review(client)
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 200 and 'Removal queued — not verified removal' in response.text
    asyncio.run(scenario())


def test_review_expiry_is_rechecked_after_preflight_io(composition, bulk, surface, monkeypatch):
    _, store, _, _ = composition
    confirm(bulk, prepare(bulk)[1])
    original = managed_review.time.monotonic
    advance = [False]
    def transform(request, response):
        if advance[0] and request.url.path == '/api/v1/status':
            monkeypatch.setattr(managed_review.time, 'monotonic', lambda: original() + 1000)
        return response

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True, transform=transform) as (client, _, calls):
            _, fields = await review(client)
            advance[0] = True
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 503 and 'expired' in response.text
            assert not any(method == 'POST' and '/managed-removals/' in path for method, path, _ in calls)
    asyncio.run(scenario())
    assert queued_count(store) == 0


def test_immutable_cache_scope_cookie_capacity_and_expiry(composition, bulk, monkeypatch):
    _, store, _, _ = composition
    confirm(bulk, prepare(bulk)[1])
    inspection = BulkRemovalScopes(store).snapshot(IP, device_id=1)
    reviews = ReadyRemovalReviews(60)
    frozen = reviews.prepare('alice', 'cookie', inspection, IP, device_id=1)
    with pytest.raises(FrozenInstanceError): frozen.digest = '0' * 64
    original = frozen.scope
    frozen.scope['targets'].clear()
    inspection['targets'].clear()
    assert frozen.scope == original
    with pytest.raises(ReviewUnavailable): reviews.get(frozen.token, 'alice', 'other-cookie')
    with pytest.raises(ReviewUnavailable): ReadyRemovalReviews().get(frozen.token, 'alice', 'cookie')
    fresh = BulkRemovalScopes(store).snapshot(IP, device_id=1)
    for _ in range(4): reviews.prepare('alice', 'cookie', fresh, IP, device_id=1)
    with pytest.raises(ReviewUnavailable): reviews.prepare('alice', 'cookie', fresh, IP, device_id=1)
    original_time = managed_review.time.monotonic
    monkeypatch.setattr(managed_review.time, 'monotonic', lambda: original_time() + 61)
    with pytest.raises(ReviewUnavailable): reviews.get(frozen.token, 'alice', 'cookie')


@pytest.mark.parametrize('value', [True, 1, 'true'])
def test_legacy_api_factory_cannot_activate_ready_removal_or_initialize_storage(composition, tmp_path, value):
    settings, _, _, _ = composition
    store = Store(tmp_path / 'not-created.db')
    with pytest.raises(ValueError): create_app(settings, store, ready_removal_admission_enabled=value)
    assert not store.path.exists()


def test_actual_bff_api_worker_lifecycle_verifies_removal_after_admission(composition, bulk, surface):
    _, store, agent, service = composition
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    for device in (1, 2): agent.entries[device] = [ObservedShun(IP, 'management')]

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True, start=True) as (client, _, _calls):
            await idle(service, agent)
            _, fields = await review(client, fleet=True)
            response = await client.post('/managed-shuns/v2/removal-confirm', data=fields)
            assert response.status_code == 200
            await until(lambda: len(agent.removals) == 2 and not service._active)
            with store._connection() as db:
                assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['VERIFIED', 'VERIFIED']
            assert not agent.writes
        assert not agent.active and not service.status()['running']
    asyncio.run(scenario())


def test_private_api_strict_fields_modes_and_roles_are_not_scope_authority(composition, bulk):
    settings, store, agent, service = composition
    confirm(bulk, prepare(bulk)[1])
    app = create_app(settings, store, agent, continuous_dispatcher=service, ready_removal_admission_enabled=True)
    inspected = BulkRemovalScopes(store).snapshot(IP, device_id=1)
    frozen = ReadyRemovalReviews().prepare('alice', 'cookie', inspected, IP, device_id=1)
    actor = {'subject': 'alice', 'display_name': 'Alice', 'roles': ['Operator']}
    body, before = {**frozen.payload(), 'actor': actor}, dump(store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            endpoint = '/api/v2/managed-removals/device'
            for extra in ({'ordered_wait': True}, {'enabled': True}, {'ttl_seconds': True}, {'action': 'CLI'}):
                assert (await client.post(endpoint, json=body | extra)).status_code == 422
            assert (await client.post('/api/v2/managed-removals/fleet', json=body)).status_code == 422
            assert (await client.post(endpoint, json=body | {'actor': actor | {'roles': ['Viewer']}})).status_code == 403
            assert (await client.post(endpoint, json=body)).status_code == 422
            bad = json.loads(json.dumps(body))
            bad['reviewed']['version'] = 2.0
            assert (await client.post(endpoint, json=bad)).status_code == 422
    asyncio.run(scenario())
    assert dump(store) == before and not agent.seen
