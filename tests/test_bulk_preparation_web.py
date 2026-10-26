"""Actual v2 draft BFF/API integration, synthetic state only; never SSH or lab."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import dump
from test_bulk_preparation_api import bulk as bulk_fixture
from test_bulk_preparation_api import cancellation_controls as cancellation_fixture
from test_bulk_preparation_api import composition as composition_fixture
from test_bulk_preparation_api import dispatch as dispatch_fixture
from test_bulk_preparation_api import journal as journal_fixture
from test_bulk_preparation_api import leases as leases_fixture
from test_bulk_preparation_api import ten_device_composition as ten_fixture
from test_bulk_preparation_api import waits as waits_fixture
from test_import_preparations import outside

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_preparation_view import operation_key
from ftd_shun_manager.protected_policy import ProtectedPolicy

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
ten_device_composition = ten_fixture
WEB, API = '/managed-imports/v2', '/api/v2/managed-imports/'


def surface_for(composition, monkeypatch):
    settings, store, agent, service = composition

    @asynccontextmanager
    async def browser(*, transform=None, policy_api=False, policy_web=False, profile_ids=frozenset(), concurrent_api=False, concurrent_web=False):
        app = create_app(settings, store, agent, continuous_dispatcher=service,
                         bulk_policy_admission_enabled=policy_api, bulk_policy_device_ids=profile_ids,
                         bulk_policy_concurrent_enabled=concurrent_api)
        loop, calls = asyncio.get_running_loop(), []

        def internal(request):
            calls.append((request.method, request.url.path, request.content))

            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
                    return await client.request(request.method, str(request.url), content=request.content, headers=request.headers)
            response = asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=20)
            if transform: response = transform(request, response)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url='http://internal'))
        bff = web.create_app(settings, bulk_policy_admission_enabled=policy_web, bulk_policy_concurrent_enabled=concurrent_web)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bff), base_url='https://fixture.test',
                headers={'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'}) as client:
            yield client, calls, app
    return browser


@pytest.fixture
def surface(composition, monkeypatch):
    return surface_for(composition, monkeypatch)


async def stage(client, *, text='198.51.100.1', devices=('1',), **extra):
    response = await client.get(WEB)
    assert response.status_code == 200, response.text[:500]
    return await client.post(WEB + '/prepare', data={'csrf': client.cookies.get('ftd_shun_csrf'), 'text': text,
        'device_ids': list(devices), 'label': '<b>Intentional label</b>', 'reason': 'Explicit metadata only', **extra})


def writes(calls):
    return [(path, json.loads(body)) for method, path, body in calls if method == 'POST' and path in {API + 'prepare', API + 'cancel-preparation'}]


def test_navigation_creation_private_actor_frozen_report_proposal_and_cancel(composition, surface):
    store, agent = composition[1:3]
    before = outside(store)

    async def scenario():
        async with surface() as (client, calls, _):
            index = await client.get('/')
            assert 'href="/managed-imports/v2"' in index.text
            response = await stage(client, text='source-marker 198.51.100.1 # comment-marker\n198.51.100.2\n198.51.100.1\n555.555.555.666', devices=('2', '1'))
            assert response.status_code == 303 and response.headers['cache-control'] == 'no-store'
            location = response.headers['location']
            key = location.split('/')[-1]
            report = await client.get(location)
            assert report.status_code == 200, report.text[:500]
            assert '4 proposed pairs' in report.text and 'Duplicate' in report.text and 'Invalid' in report.text
            assert 'source-marker' not in report.text and 'comment-marker' not in report.text
            assert '&lt;b&gt;Intentional label&lt;/b&gt;' in report.text and '<b>Intentional label</b>' not in report.text
            frozen = dump(store)
            proposal = await client.get(location + '/review')
            assert proposal.status_code == 200 and operation_key(key) in proposal.text
            assert 'This proposal does not save policy.' in proposal.text and 'Prepare separate recurring-policy consent' in proposal.text
            assert dump(store) == frozen
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await client.get(location + '/review')).status_code == 403
            assert (await client.get(location)).status_code == 200
            cancelled = await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})
            assert cancelled.status_code == 200 and 'Draft cancellation confirmed' in cancelled.text
            after = dump(store)
            assert (await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})).status_code == 200
            assert dump(store) == after
            assert all(body['actor']['subject'] == 'alice' for _, body in writes(calls))
            assert len([path for path, _ in writes(calls) if path == API + 'prepare']) == 1
    asyncio.run(scenario())
    assert outside(store) == before and not agent.seen and not composition[3]._wake.is_set()


def test_protected_exclusions_and_adoption_are_visible_not_authority(composition, surface):
    store = composition[1]
    store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')
    ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address('198.51.100.2'), 0, 'protector', 'Protector', ())
    before = outside(store)

    async def scenario():
        async with surface() as (client, _, _):
            response = await stage(client, text='198.51.100.1\n198.51.100.2\n198.51.100.3')
            page = await client.get(response.headers['location'] + '/review')
            assert page.status_code == 200, page.text[:500]
            assert 'PROPOSE_ADOPT' in page.text and 'EXCLUDED_PROTECTED' in page.text and 'protected-shun' in page.text
            assert '1 protected pairs excluded' in page.text and 'no admission' in page.text
    asyncio.run(scenario())
    assert outside(store) == before


@pytest.mark.parametrize('damage', ['csrf', 'actor', 'scope', 'devices_duplicate', 'devices_alias', 'devices_missing', 'bytes', 'lines'])
def test_invalid_forms_do_not_call_creation_and_preserve_transient_input(composition, surface, damage):
    before = dump(composition[1])

    async def scenario():
        async with surface() as (client, calls, _):
            extra, code = {}, 422
            if damage == 'csrf': extra, code = {'csrf': 'wrong'}, 403
            if damage == 'actor': extra = {'actor': 'forged'}
            if damage == 'scope': extra = {'maintain_present': 'true'}
            if damage == 'devices_duplicate': extra = {'devices': ('1', '1')}
            if damage == 'devices_alias': extra = {'devices': ('01',)}
            if damage == 'devices_missing': extra = {'devices': ()}
            if damage == 'bytes': extra = {'text': 'я' * 524289}
            if damage == 'lines': extra = {'text': '\n' * 20001}
            response = await stage(client, **extra)
            assert response.status_code in ({422, 413} if damage == 'bytes' else {code}), response.text[:500]
            assert not writes(calls)
            if damage == 'devices_duplicate': assert '198.51.100.1' in response.text and 'value="1" checked' in response.text
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_role_identity_owner_boundaries_and_cacheless_restart(composition, surface, monkeypatch):
    async def scenario():
        async with surface() as (client, calls, _):
            response = await stage(client)
            location = response.headers['location']
            client.headers['Remote-User'] = 'bob'
            client.headers['Remote-Groups'] = 'ftd-shun-administrators'
            assert (await client.get(location)).status_code == 409
            assert (await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})).status_code == 409
            listing = await client.get(WEB)
            assert location not in listing.text
            client.headers['Remote-User'] = 'alice'
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await stage(client)).status_code == 403
            assert (await client.get(location + '/review')).status_code == 403
            fresh = web.create_app(composition[0])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fresh), base_url='https://fixture.test', headers=client.headers) as restarted:
                assert (await restarted.get(location)).status_code == 200
                assert (await restarted.get(WEB)).status_code == 200
            client.headers.pop('Remote-User')
            assert (await client.get(WEB)).status_code == 401
            assert (await client.get(location)).status_code == 401
            assert not any(path.endswith('/confirm') or '/api/v1/managed-imports/' in path for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'uuid', 'count', 'flag', 'extra', 'format'])
def test_unknown_creation_reply_recovers_owner_list_without_resubmitting(composition, surface, damage):
    changed = [False]

    def transform(request, response):
        if request.url.path != API + 'prepare' or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic reply lost after draft commit', request=request)
        value = response.json()
        if damage == 'uuid': value['plan_id'] = value['plan_id'].upper()
        if damage == 'count': value['target_count'] = 2
        if damage == 'flag': value['policy_saved'] = True
        if damage == 'extra': value['jobs'] = []
        if damage == 'format': value['intent_format'] = True
        return httpx.Response(201, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, calls, _):
            response = await stage(client)
            assert response.status_code == 503 and 'outcome is unknown' in response.text
            assert 'id="bulk-source"' in response.text and '>198.51.100.1</textarea>' in response.text
            assert 'Save draft only</button>' in response.text and 'type="submit" disabled' in response.text
            with composition[1]._connection() as db: key = db.execute('SELECT id FROM import_preparation_plans').fetchone()[0]
            assert WEB + '/' + key in response.text
            before = dump(composition[1])
            assert (await client.get(WEB + '/' + key)).status_code == 200
            assert dump(composition[1]) == before
            assert [path for path, _ in writes(calls)] == [API + 'prepare']
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['list_flag', 'list_duplicate', 'report_owner', 'report_count', 'report_page', 'report_partial', 'diagnostic', 'target', 'time', 'confirmed'])
def test_malformed_private_reports_fail_closed(composition, surface, damage):
    armed = [False]

    def transform(request, response):
        if not armed[0] or request.url.path not in {API + 'preparations', API + 'preparation'}: return response
        value = response.json()
        if request.url.path.endswith('/preparations'):
            if damage == 'list_flag': value['can_execute'] = True
            if damage == 'list_duplicate': value['plans'] *= 2
        elif damage.startswith('list_'): return response
        elif damage == 'report_owner': value['actor_subject'] = 'someone-else'
        elif damage == 'report_count': value['classification_counts']['PROPOSE_ADD'] = True
        elif damage == 'report_page': value['page_size'] = 1000
        elif damage == 'report_partial': value['targets'].clear()
        elif damage == 'diagnostic': value['report_rows'][0]['excerpt'] = 'raw-source-forbidden'
        elif damage == 'target': value['targets'][0]['classification'] = 'ARBITRARY_CLI'
        elif damage == 'time': value['expires_at'] = value['created_at']
        elif damage == 'confirmed': value['confirmed_operation_id'] = str(uuid4())
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            response = await stage(client)
            armed[0] = True
            before = dump(composition[1])
            page = await client.get(WEB if damage.startswith('list_') else response.headers['location'])
            assert page.status_code == 503, page.text[:500]
            assert dump(composition[1]) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['canonical', 'digest', 'manifest_bool', 'key', 'preparation', 'policy'])
def test_malformed_proposal_never_shows_success_or_creates_authority(composition, surface, damage):
    def transform(request, response):
        if request.url.path != API + 'proposal': return response
        value = response.json()
        if damage == 'canonical': value['canonical'] += ' '
        if damage == 'digest': value['digest'] = '0' * 64
        if damage == 'manifest_bool': value['manifest']['accepted_count'] = True
        if damage == 'key': value['operation_id'] = str(uuid4())
        if damage == 'preparation': value['preparation_id'] = str(uuid4())
        if damage == 'policy': value['policy_saved'] = True
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            location = (await stage(client)).headers['location']
            before = dump(composition[1])
            page = await client.get(location + '/review')
            assert page.status_code == 503 and 'Prepare separate recurring-policy consent' not in page.text
            assert dump(composition[1]) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('closed', ['EXPIRED', 'CONFIRMED', 'CANCELLED'])
def test_closed_drafts_remain_reports_but_never_reopen_proposal(composition, bulk, surface, closed):
    async def scenario():
        async with surface() as (client, _, app):
            response = await stage(client)
            location = response.headers['location']
            key = location.split('/')[-1]
            if closed == 'EXPIRED': bulk[1][0] += timedelta(minutes=11)
            if closed == 'CANCELLED':
                await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})
            if closed == 'CONFIRMED':
                source = app.state.synchronizer.policy_revocation.preparations
                saved = source.list_for_owner('alice')['plans'][0]
                value = source.propose_bulk_intent(key, 'alice', saved['digest'], operation_key(key))
                bulk[0].confirm(value['canonical'], value['digest'], 1, 'alice', 'Actual fixture operator', ('Operator',),
                    maintain_present=True, enabled=True, addition_device_ids=frozenset({1}))
            before = dump(composition[1])
            page = await client.get(location)
            assert page.status_code == 200 and closed in page.text
            assert 'Inspect exact future managed-policy proposal</a>' not in page.text
            assert (await client.get(location + '/review')).status_code == 409
            if closed == 'CONFIRMED':
                assert (await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})).status_code == 409
            assert dump(composition[1]) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['lost', 'malformed', 'followup'])
def test_draft_cancellation_receipt_and_unknown_recovery(composition, surface, failure):
    cancelled = [False]

    def transform(request, response):
        if request.url.path == API + 'cancel-preparation':
            cancelled[0] = True
            if failure == 'lost': raise httpx.ReadTimeout('Synthetic cancelled reply lost', request=request)
            if failure == 'malformed': return httpx.Response(200, json={'cancelled': True})
        if cancelled[0] and failure == 'followup' and request.url.path == API + 'preparation': return httpx.Response(503, json={})
        return response

    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            location = (await stage(client)).headers['location']
            result = await client.post(location + '/cancel', data={'csrf': client.cookies.get('ftd_shun_csrf')})
            assert result.status_code == 503
            assert ('Draft cancellation confirmed' if failure == 'followup' else 'outcome is unknown') in result.text
            with composition[1]._connection() as db:
                assert db.execute('SELECT cancelled_at FROM import_preparation_plans').fetchone()[0] is not None
    asyncio.run(scenario())


def test_missing_journal_is_explicit_and_disables_creation(composition, surface):
    with composition[1]._connection() as db:
        db.execute('DROP TABLE import_preparation_targets')
        db.execute('DROP TABLE import_preparation_plans')
    before = dump(composition[1])

    async def scenario():
        async with surface() as (client, _, _):
            page = await client.get(WEB)
            assert page.status_code == 200 and 'journal is not initialized' in page.text
            assert 'type="submit" disabled' in page.text
    asyncio.run(scenario())
    assert dump(composition[1]) == before


def test_maximum_bff_scope_pagination_and_proposal_without_any_jobs(ten_device_composition, monkeypatch):
    composition = ten_device_composition
    before = outside(composition[1])

    async def scenario():
        async with surface_for(composition, monkeypatch)() as (client, _, _):
            response = await stage(client, text='\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(10000)), devices=tuple(str(i) for i in range(1, 11)))
            assert response.status_code == 303
            location = response.headers['location']
            first = await client.get(location)
            last = await client.get(location + '?page=1000')
            assert first.status_code == last.status_code == 200
            assert 'Page 1 of 1000' in first.text and 'Page 1000 of 1000' in last.text
            assert first.text.count('PROPOSE_ADD</span>') == last.text.count('PROPOSE_ADD</span>') == 100
            proposed = await client.get(location + '/review?page=1000')
            assert proposed.status_code == 200 and '100000 accepted pairs' in proposed.text
            assert 'This proposal does not save policy.' in proposed.text
    asyncio.run(scenario())
    assert outside(composition[1]) == before and not composition[2].seen
