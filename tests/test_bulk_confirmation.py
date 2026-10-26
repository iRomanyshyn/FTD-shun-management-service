"""Suspended standing consent on synthetic BFF/API/SQLite; never lab activation."""

import asyncio
import json
import re
from dataclasses import FrozenInstanceError
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import dump, no_work, retire
from test_bulk_preparation_api import client_for, proposal
from test_bulk_preparation_api import stage as api_stage
from test_bulk_preparation_web import bulk as bulk_fixture
from test_bulk_preparation_web import cancellation_controls as cancellation_fixture
from test_bulk_preparation_web import composition as composition_fixture
from test_bulk_preparation_web import dispatch as dispatch_fixture
from test_bulk_preparation_web import journal as journal_fixture
from test_bulk_preparation_web import leases as leases_fixture
from test_bulk_preparation_web import stage, surface_for
from test_bulk_preparation_web import ten_device_composition as ten_fixture
from test_bulk_preparation_web import waits as waits_fixture
from test_device_leases import acquire

from ftd_shun_manager import managed_review, web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_confirmation_view import BulkConfirmationReviews
from ftd_shun_manager.bulk_policy import BulkPolicies
from ftd_shun_manager.bulk_preparation_view import operation_key
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
ten_device_composition = ten_fixture
WEB, API = '/managed-imports/v2', '/api/v2/managed-imports/'


@pytest.fixture
def surface(composition, monkeypatch):
    return surface_for(composition, monkeypatch)


async def prepare_review(client, *, text='198.51.100.1', devices=('1',)):
    response = await stage(client, text=text, devices=devices)
    assert response.status_code == 303, response.text[:500]
    location = response.headers['location']
    page = await client.post(location + '/confirmation-review', data={'csrf': client.cookies.get('ftd_shun_csrf')})
    assert page.status_code == 200, page.text[:500]
    token = re.search('name="review" value="([^"]+)"', page.text)[1]
    return location, page, {'csrf': client.cookies.get('ftd_shun_csrf'), 'review': token,
                            'accepted_count': str(len(set(text.splitlines())) * len(devices)), 'maintain_present': 'true'}


@pytest.mark.parametrize('api_enabled,web_enabled', [(False, False), (True, False), (False, True)])
def test_separate_default_off_gates_never_submit_or_grant(composition, surface, api_enabled, web_enabled):
    async def scenario():
        async with surface(policy_api=api_enabled, policy_web=web_enabled,
                           profile_ids=frozenset({1}) if api_enabled else frozenset()) as (client, calls, _):
            _, page, fields = await prepare_review(client)
            assert 'type="submit" disabled' in page.text
            before = dump(composition[1])
            result = await client.post(WEB + '/confirm', data=fields)
            assert result.status_code == 503 and dump(composition[1]) == before
            assert not any(path == API + 'confirm' for _, path, _ in calls)
    asyncio.run(scenario())


def test_atomic_real_actor_policy_receipt_restart_pruning_retirement_and_original_key(composition, bulk, surface):
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1, 2})) as (client, calls, app):
            location, _, fields = await prepare_review(client, devices=('1', '2'))
            key = operation_key(location.split('/')[-1])
            result = await client.post(WEB + '/confirm', data=fields)
            assert result.status_code == 200 and 'Policy saved — restoration suspended' in result.text
            event = next(row for row in composition[1].list_events() if row['event_type'] == 'MANAGED_BULK_IMPORT_CONFIRMED')
            assert event['actor_subject'] == 'alice' and event['actor_roles'] == ['Operator']
            assert not composition[3]._wake.is_set()
            assert 'Saved policy receipts' in (await client.get(WEB)).text
            assert (await client.get(WEB + '/receipts/' + key)).status_code == 200
            retire(bulk, [(1, IPv4Address('198.51.100.1')), (2, IPv4Address('198.51.100.1'))])
            before = dump(composition[1])
            client.headers['Remote-Groups'] = 'ftd-shun-administrators'
            replay = await client.post(WEB + '/confirm', data=fields)
            assert replay.status_code == 200 and 'Original-key replay' in replay.text and dump(composition[1]) == before
            # Independent immutable policy evidence survives draft expiry/pruning.
            bulk[1][0] += timedelta(minutes=11)
            app.state.synchronizer.policy_revocation.preparations.prune_expired()
            receipt = await client.get(WEB + '/receipts/' + key)
            assert receipt.status_code == 200 and 'Historical managed-policy receipt' in receipt.text
            fresh = web.create_app(composition[0])  # No admission capability or ephemeral review.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fresh), base_url='https://fixture.test', headers=client.headers) as restarted:
                assert (await restarted.get(WEB + '/receipts/' + key)).status_code == 200
            posts = [(path, json.loads(body)) for method, path, body in calls if method == 'POST' and path == API + 'confirm']
            assert len(posts) == 2 and all(body['actor']['subject'] == 'alice' for _, body in posts)
    asyncio.run(scenario())
    no_work(bulk[0])
    assert not composition[2].seen


@pytest.mark.parametrize('change', [
    {'bulk_policy_admission_enabled': 1}, {'bulk_policy_admission_enabled': 'true'},
    {'bulk_policy_admission_enabled': True}, {'bulk_policy_device_ids': frozenset({1})},
    {'bulk_policy_admission_enabled': True, 'bulk_policy_device_ids': {1}},
    {'bulk_policy_admission_enabled': True, 'bulk_policy_device_ids': frozenset({True})},
    {'bulk_policy_admission_enabled': True, 'bulk_policy_device_ids': frozenset({65536})},
])
def test_factory_strict_capability_scope_never_initializes(tmp_path, change):
    store = Store(tmp_path / 'absent.db')
    with pytest.raises(ValueError): create_app(store=store, **change)
    assert not store.path.exists()


def test_factory_refuses_undeclared_device_before_binding(composition):
    settings, store, agent, service = composition
    before = dump(store)
    with pytest.raises(ValueError):
        create_app(settings, store, agent, continuous_dispatcher=service,
                   bulk_policy_admission_enabled=True, bulk_policy_device_ids=frozenset({5}))
    assert dump(store) == before and not getattr(service, '_api_application_bound', False)


@pytest.mark.parametrize('bad', ['csrf', 'count', 'count_alias', 'consent', 'actor', 'scope', 'other_subject', 'viewer', 'cookie'])
def test_web_consent_role_session_fields_are_not_authority(composition, surface, bad):
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1})) as (client, calls, _):
            _, _, fields = await prepare_review(client)
            expected = 422
            if bad == 'csrf': fields['csrf'], expected = 'bad', 403
            if bad == 'count': fields['accepted_count'] = '2'
            if bad == 'count_alias': fields['accepted_count'] = '01'
            if bad == 'consent': fields.pop('maintain_present')
            if bad == 'actor': fields['actor'] = 'forged'
            if bad == 'scope': fields['canonical'] = '{}'
            if bad == 'other_subject': client.headers['Remote-User'], expected = 'bob', 409
            if bad == 'viewer': client.headers['Remote-Groups'], expected = 'ftd-shun-viewers', 403
            if bad == 'cookie':
                client.cookies.clear(); client.cookies.set('ftd_shun_csrf', 'another-cookie')
                fields['csrf'], expected = 'another-cookie', 409
            before = dump(composition[1])
            response = await client.post(WEB + '/confirm', data=fields)
            assert response.status_code == expected and dump(composition[1]) == before
            assert not any(path == API + 'confirm' for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['lease', 'scope', 'expiry', 'pause', 'profile'])
def test_whole_scope_preconditions_conflict_without_partial_policy(composition, bulk, leases, surface, case):
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1})) as (client, _, _):
            location, _, fields = await prepare_review(client, devices=('1', '2') if case == 'profile' else ('1',))
            if case == 'lease': acquire(leases)
            if case == 'scope': composition[1].record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')
            if case == 'expiry': bulk[1][0] += timedelta(minutes=11)
            if case == 'pause':
                with composition[1]._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
            before = dump(composition[1])
            response = await client.post(WEB + '/confirm', data=fields)
            assert response.status_code == (503 if case == 'profile' else 409), (location, response.text[:500])
            assert dump(composition[1]) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'flag', 'count', 'revision', 'actor', 'classification', 'extra'])
def test_unknown_reply_keeps_same_frozen_key_and_never_duplicates(composition, surface, damage):
    changed = [False]

    def transform(request, response):
        if request.url.path != API + 'confirm' or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic reply lost after commit', request=request)
        value = response.json()
        if damage == 'flag': value['device_work_admitted'] = True
        if damage == 'count': value['accepted_pairs'] = True
        if damage == 'revision': value['managed_revision'] += 1
        if damage == 'actor': value['confirmation_actor']['subject'] = 'other'
        if damage == 'classification': value['classification_counts']['PROPOSE_ADD'] = True
        if damage == 'extra': value['jobs'] = []
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), transform=transform) as (client, _, _):
            _, _, fields = await prepare_review(client)
            response = await client.post(WEB + '/confirm', data=fields)
            assert response.status_code == 503 and 'outcome is unknown' in response.text
            assert fields['review'] in response.text
            before = dump(composition[1])
            replay = await client.post(WEB + '/confirm', data=fields)
            assert replay.status_code == 200 and 'Original-key replay' in replay.text and dump(composition[1]) == before
    asyncio.run(scenario())


def test_paged_review_preserves_original_scope_count_consent_and_no_submit(composition, surface):
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1})) as (client, calls, _):
            _, _, fields = await prepare_review(client, text='\n'.join(f'198.18.0.{i}' for i in range(1, 103)))
            before = dump(composition[1])
            response = await client.post(WEB + '/confirmation-review/page', data=fields | {'page': '2'})
            assert response.status_code == 200, response.text[:500]
            assert fields['review'] in response.text and 'value="102"' in response.text and 'value="true" checked' in response.text
            assert response.text.count('PROPOSE_ADD</td>') == 2
            assert dump(composition[1]) == before and not any(path == API + 'confirm' for _, path, _ in calls)
    asyncio.run(scenario())


def test_review_expiry_rechecked_after_status_io(composition, surface, monkeypatch):
    expire = [False]
    original = managed_review.time.monotonic

    def transform(request, response):
        if expire[0] and request.url.path == '/api/v1/status':
            monkeypatch.setattr(managed_review.time, 'monotonic', lambda: original() + 1000)
        return response

    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), transform=transform) as (client, calls, _):
            _, _, fields = await prepare_review(client)
            expire[0] = True
            before = dump(composition[1])
            response = await client.post(WEB + '/confirm', data=fields)
            assert response.status_code == 503 and 'expired' in response.text and dump(composition[1]) == before
            assert not any(path == API + 'confirm' for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['manifest', 'members', 'actor', 'generation', 'canonical', 'flag'])
def test_malformed_historical_receipt_is_unavailable_not_success(composition, surface, damage):
    def transform(request, response):
        if request.url.path != API + 'receipt': return response
        value = response.json()
        if damage == 'manifest': value['manifest']['accepted_count'] = True
        if damage == 'members': value['targets'].clear()
        if damage == 'actor': value['result']['confirmation_actor']['subject'] = 'other'
        if damage == 'generation': value['targets'][0]['generation'] = True
        if damage == 'canonical': value['canonical'] += ' '
        if damage == 'flag': value['historical_confirmation'] = 1
        return httpx.Response(200, json=value)

    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), transform=transform) as (client, _, _):
            location, _, fields = await prepare_review(client)
            assert (await client.post(WEB + '/confirm', data=fields)).status_code == 200
            before = dump(composition[1])
            page = await client.get(WEB + '/receipts/' + operation_key(location.split('/')[-1]))
            assert page.status_code == 503 and 'unavailable' in page.text and dump(composition[1]) == before
    asyncio.run(scenario())


def test_immutable_cache_cookie_capacity_and_new_bff_cannot_recreate_consent(composition, bulk):
    source = bulk[0].preparations
    saved = source.create('198.51.100.1', [1], 'alice', 'Fixture', ('Operator',))
    proposed = source.propose_bulk_intent(saved['plan_id'], 'alice', saved['digest'], operation_key(saved['plan_id']))
    value = source.page(saved['plan_id'], 'alice') | {'intent_format': 2, 'policy_saved': False, 'device_work_admitted': False}
    cache = BulkConfirmationReviews()
    review = cache.prepare('alice', 'cookie', value, proposed)
    with pytest.raises(FrozenInstanceError): review.summary_json = '{}'
    review.summary['devices'].clear(); review.proposal['manifest']['device_ids'].clear()
    assert review.summary['devices'] and review.proposal['manifest']['device_ids']
    with pytest.raises(ReviewUnavailable): cache.get(review.token, 'alice', 'other')
    with pytest.raises(ReviewUnavailable): BulkConfirmationReviews().get(review.token, 'alice', 'cookie')
    for _ in range(4): cache.prepare('alice', 'cookie', value, proposed)
    with pytest.raises(ReviewUnavailable): cache.prepare('alice', 'cookie', value, proposed)


@pytest.mark.parametrize('bad', ['header', 'consent', 'count_bool', 'extra', 'digest', 'viewer'])
def test_private_api_strict_original_key_and_consent(composition, bad):
    settings, store, agent, service = composition
    app = create_app(settings, store, agent, continuous_dispatcher=service,
                     bulk_policy_admission_enabled=True, bulk_policy_device_ids=frozenset({1}))

    async def scenario():
        async with client_for(app) as client:
            saved = (await api_stage(client)).json()
            proposed = (await proposal(client, saved)).json()
            body = {'actor': {'subject': 'alice', 'display_name': 'Current operator', 'roles': ['Operator']},
                    'canonical': proposed['canonical'], 'digest': proposed['digest'], 'accepted_count': 1, 'maintain_present': True}
            headers, code = {'Idempotency-Key': proposed['operation_id']}, 422
            if bad == 'header': headers['Idempotency-Key'] = str(uuid4())
            if bad == 'consent': body['maintain_present'] = False
            if bad == 'count_bool': body['accepted_count'] = True
            if bad == 'extra': body['addition_device_ids'] = [1]
            if bad == 'digest': body['digest'] = '0' * 64
            if bad == 'viewer': body['actor']['roles'], code = ['Viewer'], 403
            before = dump(store)
            response = await client.post(API + 'confirm', json=body, headers=headers)
            assert response.status_code == code, response.text
            assert dump(store) == before
    asyncio.run(scenario())


def test_maximum_whole_scope_confirmation_receipt_after_journal_prune(ten_device_composition, monkeypatch):
    composition = ten_device_composition
    async def scenario():
        async with surface_for(composition, monkeypatch)(policy_api=True, policy_web=True,
                profile_ids=frozenset(range(1, 11))) as (client, _, _):
            location, _, fields = await prepare_review(client, text='\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(10000)),
                devices=tuple(str(i) for i in range(1, 11)))
            response = await client.post(WEB + '/confirm', data=fields)
            assert response.status_code == 200 and '100000 accepted pairs' in response.text
            key = operation_key(location.split('/')[-1])
            page = await client.get(WEB + '/receipts/' + key + '?page=1000')
            assert page.status_code == 200 and 'Page 1000 / 1000' in page.text
            assert page.text.count('Generation 1') == 100
    asyncio.run(scenario())
    no_work(BulkPolicies(composition[1]))
