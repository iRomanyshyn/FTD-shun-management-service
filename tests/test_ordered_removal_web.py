"""Actual ordered BFF/API on disposable exact profiles; never lab/FTD writes."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address

import httpx
import pytest
from test_bulk_ordered_promotion import finish
from test_bulk_ordered_removals import running
from test_bulk_policy import dump
from test_device_leases import grant
from test_ordered_removal_api import bulk as bulk_fixture
from test_ordered_removal_api import cancellation_controls as cancellation_fixture
from test_ordered_removal_api import composition as composition_fixture
from test_ordered_removal_api import dispatch as dispatch_fixture
from test_ordered_removal_api import journal as journal_fixture
from test_ordered_removal_api import leases as leases_fixture
from test_ordered_removal_api import ordered as ordered_fixture
from test_ordered_removal_api import waits as waits_fixture

from ftd_shun_manager import managed_review, web
from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_ordered_removals import _DOMAIN, _digest
from ftd_shun_manager.bulk_ordered_review import OrderedRemovalReviews, inspect_ordered
from ftd_shun_manager.import_review import ReviewUnavailable

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
ordered = ordered_fixture
waits = waits_fixture
IP = IPv4Address('198.51.100.1')
CONFIRM = '/managed-shuns/v2/ordered-removal-confirm'
API = '/api/v2/managed-ordered-removals/'
WEB = '/managed-shuns/v2/ordered-removals/'


@pytest.fixture
def surface(composition, ordered, monkeypatch):
    settings, store, agent, service = composition

    @asynccontextmanager
    async def browser(*, api_enabled=True, web_enabled=True, transform=None):
        app = create_app(settings, store, agent, continuous_dispatcher=service,
                         ordered_removal_admission_enabled=api_enabled)
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
        bff = web.create_app(settings, ordered_removal_admission_enabled=web_enabled)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bff), base_url='https://fixture.test',
                headers={'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'}) as client:
            yield client, app, calls
    return browser


async def review(client, *, fleet=False):
    page = await client.get('/managed-shuns')
    assert page.status_code == 200 and 'ordered-removal-preparation' in page.text
    response = await client.post('/managed-shuns/v2/' + ('ordered-fleet-removal-review' if fleet else 'ordered-removal-review'),
        data={'csrf': client.cookies.get('ftd_shun_csrf'), 'reason': 'Synthetic ordered removal',
              **({'ip': str(IP)} if fleet else {'target': f'1:{IP}'})})
    assert response.status_code == 200, response.text
    token = re.search('name="review" value="([^"]+)"', response.text)
    fields = {'csrf': client.cookies.get('ftd_shun_csrf'), 'review': token[1] if token else '', 'confirm_ip': str(IP)}
    return response, fields


def key_from(page):
    return re.search('/managed-shuns/v2/ordered-removals/([a-f0-9-]{36})', page.text)[1]


def posts(calls):
    return [(path, json.loads(body)) for method, path, body in calls if method == 'POST' and path.startswith(API)]


@pytest.mark.parametrize('api_gate,web_gate', [(False, False), (False, True), (True, False)])
def test_independent_gates_allow_inspection_but_never_submit(composition, bulk, leases, surface, api_gate, web_gate):
    grant(bulk)
    running(bulk, leases)
    before = dump(composition[1])

    async def scenario():
        async with surface(api_enabled=api_gate, web_enabled=web_gate) as (client, _, calls):
            page, fields = await review(client)
            assert 'Inspection only' in page.text and 'button type="submit" disabled' in page.text
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 503 and not posts(calls)
    asyncio.run(scenario())
    assert dump(composition[1]) == before and not composition[2].seen


@pytest.mark.parametrize('fleet', [False, True])
def test_frozen_whole_scope_real_actor_receipt_replay_and_status(composition, bulk, leases, surface, fleet):
    grant(bulk)
    running(bulk, leases)
    store = composition[1]

    async def scenario():
        async with surface() as (client, _, calls):
            before = dump(store)
            page, fields = await review(client, fleet=fleet)
            assert 'Ordered reservation — not verified removal' in page.text and dump(store) == before
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 200 and 'Waiting reserved — not verified removal' in response.text
            key = key_from(response)
            after = dump(store)
            replay = await client.post(CONFIRM, data=fields)
            assert 'Original-key replay' in replay.text and dump(store) == after
            status = await client.get(WEB + key)
            assert status.status_code == 200 and status.headers['cache-control'] == 'no-store'
            assert 'RUNNING' in status.text and 'Not delegated' in status.text and 'Cancel waiting only' in status.text
            assert dump(store) == after
            submissions = posts(calls)
            assert [path for path, _ in submissions] == [API + ('fleet' if fleet else 'device')] * 2
            assert all(body['actor']['subject'] == 'alice' and body['actor']['roles'] == ['Operator'] for _, body in submissions)
    asyncio.run(scenario())
    assert not composition[2].seen


@pytest.mark.parametrize('blocked', [False, True])
def test_ready_or_blocked_inspection_has_no_confirmation_token_or_fallback(composition, bulk, leases, surface, blocked):
    grant(bulk)
    if blocked:
        running(bulk, leases)
        with composition[1]._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id=2')

    async def scenario():
        async with surface() as (client, _, calls):
            page, fields = await review(client, fleet=True)
            assert not fields['review'] and 'No confirmation token was created' in page.text
            assert ('DEVICE_DISABLED' if blocked else 'No captured RUNNING ADD remains') in page.text
            assert (await client.post(CONFIRM, data=fields)).status_code == 409
            assert not posts(calls)
    before = dump(composition[1])
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_csrf_role_actor_cookie_extra_fields_and_cross_purpose_refuse(composition, bulk, leases, surface):
    grant(bulk)
    running(bulk, leases)
    before = dump(composition[1])

    async def scenario():
        async with surface() as (client, _, calls):
            _, fields = await review(client)
            for extra in ({'actor': 'forged'}, {'scope': 'fleet'}, {'predecessors': '[]'}, {'ordered_wait': 'true'}):
                assert (await client.post(CONFIRM, data=fields | extra)).status_code == 422
            assert (await client.post(CONFIRM, data=fields | {'csrf': 'wrong'})).status_code == 403
            assert (await client.post(CONFIRM, data=fields | {'confirm_ip': '198.51.100.2'})).status_code == 422
            client.headers['Remote-User'] = 'bob'
            assert (await client.post(CONFIRM, data=fields)).status_code == 409
            client.headers['Remote-User'] = 'alice'
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await client.post(CONFIRM, data=fields)).status_code == 403
            client.headers['Remote-Groups'] = 'ftd-shun-operators'
            ready = await client.post('/managed-shuns/v2/removal-review', data={'csrf': fields['csrf'], 'target': f'1:{IP}'})
            other = re.search('name="review" value="([^"]+)"', ready.text)[1]
            assert (await client.post(CONFIRM, data=fields | {'review': other})).status_code == 409
            assert (await client.post('/managed-shuns/v2/removal-confirm', data=fields)).status_code == 409
            cookie = client.cookies.get('ftd_shun_csrf')
            client.cookies.clear()
            client.cookies.set('ftd_shun_csrf', 'another-session')
            assert (await client.post(CONFIRM, data=fields | {'csrf': 'another-session'})).status_code == 409
            client.cookies.clear()
            client.cookies.set('ftd_shun_csrf', cookie)
            client.headers.pop('Remote-User')
            assert (await client.post(CONFIRM, data=fields)).status_code == 401
            assert not posts(calls)
    asyncio.run(scenario())
    assert dump(composition[1]) == before


@pytest.mark.parametrize('damage', ['lost', 'version', 'verified', 'scope', 'count', 'expiry', 'requested', 'extra'])
def test_unknown_reply_keeps_original_key_and_no_duplicate_authority(composition, bulk, leases, surface, damage):
    grant(bulk)
    running(bulk, leases)
    changed = [False]

    def transform(request, response):
        if request.method != 'POST' or request.url.path != API + 'device' or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic reply loss after commit', request=request)
        value = response.json()
        if damage == 'version': value['intent_format'] = True
        if damage == 'verified': value['verified_removal'] = True
        if damage == 'scope': value['scope'] = 'fleet'
        if damage == 'count': value['predecessor_count'] = True
        if damage == 'expiry': value['expires_at'] = value['requested_at']
        if damage == 'requested': value['requested_at'] = value['expires_at']
        if damage == 'extra': value['jobs'] = []
        return httpx.Response(202, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, calls):
            page, fields = await review(client)
            key = key_from(page)
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 503 and 'outcome is unknown' in response.text
            assert key_from(response) == key
            after = dump(composition[1])
            replay = await client.post(CONFIRM, data=fields)
            assert replay.status_code == 200 and 'Original-key replay' in replay.text and dump(composition[1]) == after
            assert len(posts(calls)) == 2
    asyncio.run(scenario())


def test_stale_whole_scope_rejects_without_partial_changes(composition, bulk, leases, surface):
    grant(bulk)
    running(bulk, leases)

    async def scenario():
        async with surface() as (client, _, _):
            _, fields = await review(client, fleet=True)
            composition[1].record_observed_shun(3, IP, 'management')
            before = dump(composition[1])
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 409 and dump(composition[1]) == before
    asyncio.run(scenario())


def test_expiry_rechecked_after_status_io(composition, bulk, leases, surface, monkeypatch):
    grant(bulk)
    running(bulk, leases)
    original, expire = managed_review.time.monotonic, [False]

    def transform(request, response):
        if expire[0] and request.url.path == '/api/v1/status':
            monkeypatch.setattr(managed_review.time, 'monotonic', lambda: original() + 1000)
        return response

    async def scenario():
        async with surface(transform=transform) as (client, _, calls):
            _, fields = await review(client)
            expire[0] = True
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 503 and 'expired' in response.text and not posts(calls)
    before = dump(composition[1])
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_checked_receipt_survives_optional_metadata_failure(composition, bulk, leases, surface):
    grant(bulk)
    running(bulk, leases)
    submitted = [False]

    def transform(request, response):
        if request.method == 'POST' and request.url.path.startswith(API): submitted[0] = True
        if submitted[0] and request.url.path == '/api/v1/status': return httpx.Response(503, json={})
        return response

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client)
            response = await client.post(CONFIRM, data=fields)
            assert response.status_code == 200 and 'Waiting reserved — not verified removal' in response.text
    asyncio.run(scenario())


def test_frozen_cache_detachment_cookie_expiry_capacity_and_web_restart(ordered, bulk, leases, monkeypatch):
    grant(bulk)
    running(bulk, leases)
    value = ordered.scopes.snapshot(IP, now=bulk[1][0])
    cache = OrderedRemovalReviews(60)
    frozen = cache.prepare('alice', 'cookie', value, IP)
    with pytest.raises(FrozenInstanceError): frozen.digest = '0' * 64
    original = frozen.payload()
    frozen.payload()['predecessors'].clear()
    frozen.inspection['scope']['targets'].clear()
    value['targets'].clear()
    assert frozen.payload() == original and frozen.inspection['targets']
    for subject, cookie in [('other', 'cookie'), ('alice', 'other-cookie')]:
        with pytest.raises(ReviewUnavailable): cache.get(frozen.token, subject, cookie)
    with pytest.raises(ReviewUnavailable): OrderedRemovalReviews().get(frozen.token, 'alice', 'cookie')
    value = frozen.inspection
    for _ in range(4): cache.prepare('alice', 'cookie', value, IP)
    with pytest.raises(ReviewUnavailable): cache.prepare('alice', 'cookie', value, IP)
    for index in range(251): cache.prepare(str(index), 'cookie', value, IP)
    with pytest.raises(ReviewUnavailable): cache.prepare('global-limit', 'cookie', value, IP)
    clock = managed_review.time.monotonic
    monkeypatch.setattr(managed_review.time, 'monotonic', lambda: clock() + 61)
    with pytest.raises(ReviewUnavailable): cache.get(frozen.token, 'alice', 'cookie')


@pytest.mark.parametrize('damage', ['digest', 'mode', 'target', 'count', 'blockers', 'disposition', 'literal'])
def test_complete_preflight_validation_refuses_even_redigested_inconsistency(ordered, bulk, leases, damage):
    grant(bulk)
    running(bulk, leases)
    value = ordered.scopes.snapshot(IP, now=bulk[1][0])
    if damage == 'mode': value['scope']['scope'] = 'device'
    if damage == 'target': value['targets'][0]['device_id'] = 3
    if damage == 'count': value['waiting_target_count'] = 0
    if damage == 'blockers': value['targets'][0]['blockers'] = ['CLI_COMMAND']
    if damage == 'disposition': value['disposition'] = 'READY'
    if damage == 'literal': value['intent_format'] = True
    value['preflight_digest'] = _digest({key: item for key, item in value.items() if key != 'preflight_digest'}, _DOMAIN)
    if damage == 'digest': value['preflight_digest'] = '0' * 64
    with pytest.raises(ValueError): inspect_ordered(value, IP)


@pytest.mark.parametrize('change', [{'ordered_removal_admission_enabled': 1}, {'ordered_removal_admission_enabled': 'true'}])
def test_literal_web_capability_required(composition, change):
    with pytest.raises(ValueError): web.create_app(composition[0], **change)


@pytest.mark.parametrize('change', [{'development_auth': True}, {'agent_mode': 'mock'}, {'large_snapshots_enabled': False}, {'agent_cycles_enabled': False}])
def test_incompatible_web_enablement_refused(composition, change):
    with pytest.raises(ValueError): web.create_app(replace(composition[0], **change), ordered_removal_admission_enabled=True)


@pytest.mark.parametrize('outcome', ['NOOP', 'FAILED', 'UNVERIFIED'])
def test_current_status_attention_and_cancel_do_not_reinterpret_add(composition, bulk, leases, surface, outcome):
    grant(bulk)
    predecessor = running(bulk, leases)

    async def scenario():
        async with surface() as (client, _, _):
            _, fields = await review(client, fleet=True)
            accepted = await client.post(CONFIRM, data=fields)
            key = key_from(accepted)
            finish(leases, predecessor, None if outcome == 'NOOP' else outcome)
            assert composition[3].ordered_promoter.advance(enabled=True) == 1
            before = dump(composition[1])
            page = await client.get(WEB + key)
            assert page.status_code == 200 and outcome in page.text and dump(composition[1]) == before
            response = await client.post(WEB + key + '/cancel', data={'csrf': fields['csrf'], 'confirm_ip': str(IP)})
            if outcome == 'NOOP':
                assert response.status_code == 409 and 'QUEUED' in page.text
            else:
                assert response.status_code == 200 and 'Waiting authority revoked' in response.text
                assert 'Retained attention' in response.text and outcome in response.text
    asyncio.run(scenario())


def test_status_restart_revocation_without_gates_csrf_owner_admin_pause(composition, bulk, leases, surface, monkeypatch):
    grant(bulk)
    predecessor = running(bulk, leases)

    async def scenario():
        async with surface() as (client, app, calls):
            _, fields = await review(client)
            key = key_from(await client.post(CONFIRM, data=fields))
            # A new BFF cache loses consent but the durable status permalink survives.
            fresh = web.create_app(composition[0])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fresh), base_url='https://fixture.test',
                    headers=client.headers) as restarted:
                page = await restarted.get(WEB + key)
                assert page.status_code == 200 and 'Cancel waiting only' in page.text
                assert (await restarted.post(CONFIRM, data=fields)).status_code in {403, 409}
            app.state.synchronizer.ordered_removal_admission_enabled = False
            composition[3].ordered_promotion_enabled = False
            with composition[1]._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
            before = dump(composition[1])
            data = {'csrf': fields['csrf'], 'confirm_ip': str(IP)}
            path = WEB + key + '/cancel'
            assert (await client.post(path, data=data | {'resume': 'true'})).status_code == 422
            assert (await client.post(path, data=data | {'csrf': 'bad'})).status_code == 403
            assert (await client.post(path, data=data | {'confirm_ip': '198.51.100.2'})).status_code == 422
            client.headers['Remote-User'] = 'bob'
            assert (await client.post(path, data=data)).status_code == 403
            assert dump(composition[1]) == before
            client.headers['Remote-Groups'] = 'ftd-shun-administrators'
            response = await client.post(path, data=data)
            assert response.status_code == 200 and 'Waiting authority revoked' in response.text
            after = dump(composition[1])
            assert (await client.post(path, data=data)).status_code == 200 and dump(composition[1]) == after
            assert all(body['actor']['subject'] == 'bob' for path, body in posts(calls) if path.endswith('/cancel'))
    asyncio.run(scenario())
    with composition[1]._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (predecessor[2]['id'],)).fetchone()[0] == 'RUNNING'
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE device_id=1 AND enabled=1').fetchone()
        assert db.execute('SELECT 1 FROM managed_shun_targets WHERE device_id=2 AND enabled=1').fetchone()


@pytest.mark.parametrize('damage', ['verified', 'scope', 'missing', 'count', 'alias', 'owner', 'phase', 'decision'])
def test_malformed_status_unavailable_never_success(composition, bulk, leases, surface, damage):
    grant(bulk)
    running(bulk, leases)

    def transform(request, response):
        if request.method != 'GET' or not request.url.path.startswith(API): return response
        value = response.json()
        if damage == 'verified': value['verified_removal'] = True
        if damage == 'scope': value['scope']['targets'].clear()
        if damage == 'missing': value['predecessors'][0]['missing_evidence'] = True
        if damage == 'count': value['predecessor_count'] = True
        if damage == 'alias': value['predecessors'][0]['job_id'] = value['operation_id']
        if damage == 'owner': value['owner_subject'] = ''
        if damage == 'phase': value['state'] = 'ADMITTING'
        if damage == 'decision': value['decision'] = {'reason': 'ADMISSION_CONFLICT'}
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, calls):
            _, fields = await review(client)
            key = key_from(await client.post(CONFIRM, data=fields))
            before = dump(composition[1])
            page = await client.get(WEB + key)
            assert page.status_code == 503 and 'Current ordered evidence is unavailable' in page.text
            assert 'Cancel waiting only' not in page.text and dump(composition[1]) == before
            assert len(posts(calls)) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('followup', [404, 503])
def test_checked_cancel_receipt_survives_failed_followup(composition, bulk, leases, surface, followup):
    grant(bulk)
    running(bulk, leases)
    cancelled = [False]

    def transform(request, response):
        if request.method == 'POST' and request.url.path.endswith('/cancel'): cancelled[0] = True
        if cancelled[0] and request.method == 'GET' and request.url.path.startswith(API):
            return httpx.Response(followup, json={'detail': 'Synthetic unavailable'})
        return response

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client)
            key = key_from(await client.post(CONFIRM, data=fields))
            response = await client.post(WEB + key + '/cancel', data={'csrf': fields['csrf'], 'confirm_ip': str(IP)})
            assert response.status_code == 503 and 'Waiting authority revoked' in response.text
            assert 'revocation confirmed' in response.text and 'Current ordered evidence is unavailable' in response.text
    asyncio.run(scenario())


def test_actual_bff_api_continuous_worker_and_readonly_final_status(composition, bulk, leases, surface):
    from test_continuous_dispatch import until
    grant(bulk)
    predecessor = running(bulk, leases)
    _, store, agent, _ = composition
    agent.entries = {1: [ObservedShun(IP, 'management')], 2: [ObservedShun(IP, 'management')]}

    async def scenario():
        async with surface() as (client, app, calls):
            _, fields = await review(client, fleet=True)
            key = key_from(await client.post(CONFIRM, data=fields))
            finish(leases, predecessor)
            async with app.router.lifespan_context(app):
                def verified():
                    with store._connection() as db:
                        return db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='VERIFIED'").fetchone()[0] == 2
                await until(verified)
                page = await client.get(WEB + key)
                assert page.status_code == 200 and 'All original REMOVE jobs verified' in page.text
                assert 'Cancel waiting only' not in page.text
                assert not any(kind == 'add' for kind, _, _ in agent.trace)
            calls.clear()
            before = dump(store)
            assert (await client.get(WEB + key)).status_code == 200 and dump(store) == before
            assert all(method == 'GET' for method, _, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'malformed', 'wrong_key', 'http_error'])
def test_unknown_revocation_reply_retries_only_original_request(composition, bulk, leases, surface, damage):
    grant(bulk)
    running(bulk, leases)
    changed = [False]

    def transform(request, response):
        if request.method != 'POST' or not request.url.path.endswith('/cancel') or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic revocation reply lost', request=request)
        if damage == 'http_error': return httpx.Response(503, json={})
        value = response.json()
        if damage == 'malformed': value['maintenance_resumed'] = True
        if damage == 'wrong_key': value['operation_id'] = '11111111-1111-4111-8111-111111111111'
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, calls):
            _, fields = await review(client)
            key = key_from(await client.post(CONFIRM, data=fields))
            path, data = WEB + key + '/cancel', {'csrf': fields['csrf'], 'confirm_ip': str(IP)}
            response = await client.post(path, data=data)
            assert response.status_code == 503 and 'revocation outcome is unknown' in response.text
            after = dump(composition[1])
            retry = await client.post(path, data=data)
            assert retry.status_code == 200 and 'original revocation replay' in retry.text
            assert dump(composition[1]) == after
            assert [path for path, _ in posts(calls) if path.endswith('/cancel')] == [API + key + '/cancel'] * 2
    asyncio.run(scenario())


def test_revocation_race_to_admitted_is_conflict_without_cancelling_jobs(composition, bulk, leases, surface):
    grant(bulk)
    predecessor = running(bulk, leases)
    race = [False]

    def transform(request, response):
        if race[0] and request.method == 'GET' and request.url.path.startswith(API):
            race[0] = False
            finish(leases, predecessor)
            assert composition[3].ordered_promoter.advance(enabled=True) == 1
        return response

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client, fleet=True)
            key = key_from(await client.post(CONFIRM, data=fields))
            race[0] = True
            response = await client.post(WEB + key + '/cancel', data={'csrf': fields['csrf'], 'confirm_ip': str(IP)})
            assert response.status_code == 409
            status = await client.get(WEB + key)
            assert 'ADMITTED' in status.text and 'QUEUED' in status.text and 'Cancel waiting only' not in status.text
    asyncio.run(scenario())
    with composition[1]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE' AND state='QUEUED'").fetchone()[0] == 2


@pytest.mark.parametrize('damage', ['partial', 'job_alias', 'job_device', 'decision_device', 'decision_expiry', 'verified', 'all_verified'])
def test_admitted_projection_requires_complete_typed_job_scope(composition, bulk, leases, surface, damage):
    grant(bulk)
    predecessor = running(bulk, leases)

    def transform(request, response):
        if request.method != 'GET' or not request.url.path.startswith(API): return response
        value = response.json()
        if damage == 'partial': value['cleanup_jobs'].pop()
        if damage == 'job_alias': value['cleanup_jobs'][0]['job_id'] = value['predecessors'][0]['job_id']
        if damage == 'job_device': value['cleanup_jobs'][0]['device_id'] = True
        if damage == 'decision_device': value['decision']['jobs'][0]['device_id'] = True
        if damage == 'decision_expiry': value['decision']['expires_at'] = value['requested_at']
        if damage == 'verified': value['verified_removal'] = True
        if damage == 'all_verified':
            for row in value['cleanup_jobs']: row['state'] = 'VERIFIED'
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client, fleet=True)
            key = key_from(await client.post(CONFIRM, data=fields))
            finish(leases, predecessor)
            assert composition[3].ordered_promoter.advance(enabled=True) == 1
            before = dump(composition[1])
            page = await client.get(WEB + key)
            assert page.status_code == 503 and 'Current ordered evidence is unavailable' in page.text
            assert dump(composition[1]) == before
    asyncio.run(scenario())
