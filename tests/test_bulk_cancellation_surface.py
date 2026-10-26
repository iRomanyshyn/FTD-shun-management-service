"""Actual private v2 revocation on disposable ASGI/SQLite; never lab or FTD."""

import asyncio
import re
from dataclasses import FrozenInstanceError
from datetime import timedelta
from ipaddress import IPv4Address

import httpx
import pytest
from test_bulk_confirmation import bulk as bulk_fixture
from test_bulk_confirmation import cancellation_controls as cancellation_fixture
from test_bulk_confirmation import composition as composition_fixture
from test_bulk_confirmation import dispatch as dispatch_fixture
from test_bulk_confirmation import journal as journal_fixture
from test_bulk_confirmation import leases as leases_fixture
from test_bulk_confirmation import ten_device_composition as ten_fixture
from test_bulk_confirmation import waits as waits_fixture
from test_bulk_policy import confirm, dump, prepare
from test_bulk_preparation_web import surface_for
from test_device_leases import acquire, claim, discover, grant

from ftd_shun_manager import managed_review, web
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_cancellation_view import BulkCancellationReviews
from ftd_shun_manager.bulk_cancellations import BulkCancellations
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
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
def surface(composition, monkeypatch): return surface_for(composition, monkeypatch)


def root(bulk, text='198.51.100.1', devices=(1,)):
    return confirm(bulk, prepare(bulk, text, devices=devices)[1])['operation_id']


async def review(client, key):
    assert (await client.get(WEB)).status_code == 200
    response = await client.post(f'{WEB}/{key}/cancellation-review', data={'csrf': client.cookies.get('ftd_shun_csrf')})
    assert response.status_code == 200, response.text[:500]
    token = re.search('name="review" value="([^"]+)"', response.text)[1]
    count = re.search('id="cancel-accepted-count"[^>]+pattern="([0-9]+)"', response.text)[1]
    return response, {'csrf': client.cookies.get('ftd_shun_csrf'), 'review': token, 'accepted_count': count}


def test_whole_scope_revocation_retains_adoption_existing_exclusions_during_pause_without_gates(composition, bulk, surface):
    root(bulk, '198.51.100.4')
    store = composition[1]
    store.record_observed_shun(1, IPv4Address('198.51.100.2'), 'management')
    ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address('198.51.100.3'), 0, 'protector', 'Fixture', ())
    key = root(bulk, '\n'.join(f'198.51.100.{i}' for i in range(1, 5)))
    with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')

    def forbidden(*_args, **_kwargs): raise AssertionError('No startup/request initialization')

    async def scenario():
        async with surface() as (client, calls, _):
            before = dump(store)
            page, fields = await review(client, key)
            assert fields['accepted_count'] == '3' and 'RETAINED_ADOPTED' in page.text and 'RETAINED_EXISTING' in page.text
            assert dump(store) == before
            result = await client.post(WEB + '/cancel', data=fields)
            assert result.status_code == 200 and 'Uncompleted work cancelled' in result.text
            event = next(row for row in store.list_events() if row['event_type'] == 'MANAGED_BULK_IMPORT_CANCELLED')
            assert event['actor_subject'] == 'alice' and event['actor_roles'] == ['Operator']
            assert (await client.get(f'{WEB}/cancellations/{key}')).status_code == 200
            assert not composition[3]._wake.is_set()
            assert not any(path.endswith('/refresh-hint') for _, path, _ in calls)
    # Constructors and requests must not call these even when revoking queued work.
    from unittest.mock import patch
    with patch.object(Store, 'initialize', forbidden), patch.object(OperationQueue, 'initialize', forbidden):
        asyncio.run(scenario())
    entries = bulk[0].policy_page()['entries']
    assert {row['ip']: row['enabled'] for row in entries} == {'198.51.100.1': False, '198.51.100.2': True, '198.51.100.4': True}
    assert not composition[2].seen


@pytest.mark.parametrize('bad', ['csrf', 'count', 'alias', 'actor', 'scope', 'other', 'viewer', 'cookie'])
def test_frozen_form_refuses_forged_role_session_count_fields_without_writes(composition, bulk, surface, bad):
    key = root(bulk)
    async def scenario():
        async with surface() as (client, calls, _):
            _, fields = await review(client, key)
            code = 422
            if bad == 'csrf': fields['csrf'], code = 'bad', 403
            if bad == 'count': fields['accepted_count'] = '2'
            if bad == 'alias': fields['accepted_count'] = '01'
            if bad == 'actor': fields['actor'] = 'forged'
            if bad == 'scope': fields['operation_id'] = key
            if bad == 'other': client.headers['Remote-User'], code = 'other', 409
            if bad == 'viewer': client.headers['Remote-Groups'], code = 'ftd-shun-viewers', 403
            if bad == 'cookie':
                client.cookies.clear(); client.cookies.set('ftd_shun_csrf', 'changed'); fields['csrf'], code = 'changed', 409
            before = dump(composition[1])
            response = await client.post(WEB + '/cancel', data=fields)
            assert response.status_code == code and dump(composition[1]) == before
            assert not any(path == API + 'cancel' for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'flag', 'count', 'counts', 'changed', 'key', 'extra'])
def test_unknown_reply_keeps_original_review_and_retry_is_historical(composition, bulk, surface, damage):
    key, changed = root(bulk), [False]
    def transform(request, response):
        if request.url.path != API + 'cancel' or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic post-commit lost reply', request=request)
        value = response.json()
        if damage == 'flag': value['device_removal_requested'] = True
        if damage == 'count': value['accepted_count'] = True
        if damage == 'counts': value['counts']['STOPPED_UNSENT'] = True
        if damage == 'changed': value['changed_targets'] = 0
        if damage == 'key': value['operation_id'] = '00000000-0000-4000-8000-000000000000'
        if damage == 'extra': value['jobs'] = []
        return httpx.Response(200, json=value)
    async def scenario():
        async with surface(transform=transform) as (client, _, app):
            _, fields = await review(client, key)
            response = await client.post(WEB + '/cancel', data=fields)
            assert response.status_code == 503 and 'outcome is unknown' in response.text and fields['review'] in response.text
            bulk[1][0] += timedelta(minutes=11)
            app.state.synchronizer.policy_revocation.preparations.prune_expired()
            before = dump(composition[1])
            replay = await client.post(WEB + '/cancel', data=fields)
            assert replay.status_code == 200 and 'Original-review replay' in replay.text and dump(composition[1]) == before
            fresh = web.create_app(composition[0])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fresh), base_url='https://fixture.test', headers=client.headers) as restarted:
                status = await restarted.get(f'{WEB}/cancellations/{key}')
                assert status.status_code == 200 and 'STOPPED_UNSENT' in status.text
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['expiry', 'protection', 'actor_roles', 'post_io_expiry'])
def test_review_changes_fail_closed_without_partial_revocation(composition, bulk, surface, monkeypatch, change):
    key, expire = root(bulk, '198.51.100.1\n198.51.100.2'), [False]
    original = managed_review.time.monotonic
    def transform(request, response):
        if expire[0] and request.url.path == '/api/v1/status':
            monkeypatch.setattr(managed_review.time, 'monotonic', lambda: original() + 400)
        return response
    async def scenario():
        async with surface(transform=transform) as (client, calls, _):
            _, fields = await review(client, key)
            if change == 'expiry': bulk[1][0] += timedelta(minutes=6)
            if change == 'protection': ProtectedPolicy(composition[1], initialize_queue=False).change('add', IPv4Address('198.51.100.1'), 0, 'protector', '', (), managed_revision=1)
            if change == 'actor_roles': client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            if change == 'post_io_expiry': expire[0] = True
            before = dump(composition[1])
            response = await client.post(WEB + '/cancel', data=fields)
            assert response.status_code == (403 if change == 'actor_roles' else 503 if change == 'post_io_expiry' else 409), response.text[:300]
            assert dump(composition[1]) == before
            if change == 'post_io_expiry': assert not any(path == API + 'cancel' for _, path, _ in calls)
    asyncio.run(scenario())


def test_admin_may_cancel_another_owner_without_private_policy_receipt_access(composition, bulk, surface):
    key = root(bulk)
    async def scenario():
        async with surface() as (client, _, _):
            client.headers['Remote-User'] = 'other'
            assert (await client.get(f'{WEB}/cancellations/{key}')).status_code == 403
            client.headers['Remote-Groups'] = 'ftd-shun-administrators'
            assert (await client.get(f'{WEB}/receipts/{key}')).status_code != 200
            _, fields = await review(client, key)
            assert (await client.post(WEB + '/cancel', data=fields)).status_code == 200
            assert (await client.get(f'{WEB}/cancellations/{key}')).status_code == 200
            client.headers['Remote-Groups'] = 'ftd-shun-viewers'
            assert (await client.get(f'{WEB}/cancellations/{key}')).status_code == 403
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome,state', [(AdditionResult(True, 'management'), 'RETAINED_APPLIED'),
    (AdditionResult(False, None), 'RETAINED_APPLIED'), ('FAILED', 'STOPPED_FAILED'), ('UNVERIFIED', 'STOPPED_UNVERIFIED')])
def test_running_real_fenced_claim_settles_once_without_interruption_or_remove(composition, bulk, leases, surface, outcome, state):
    key = grant(bulk, devices=(1, 2))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    async def scenario():
        async with surface() as (client, _, _):
            page, fields = await review(client, key)
            assert 'WAITING_OUTCOME' in page.text and 'STOPPED_UNSENT' in page.text
            assert (await client.post(WEB + '/cancel', data=fields)).status_code == 200
            current = await client.get(f'{WEB}/cancellations/{key}')
            assert current.status_code == 200 and 'WAITING_OUTCOME' in current.text
            queue.finish_addition(job['id'], token.owner, outcome)
            settled = await client.get(f'{WEB}/cancellations/{key}')
            assert settled.status_code == 200 and state in settled.text and 'SETTLED' in settled.text, settled.text[:400]
            before = dump(composition[1])
            assert (await client.post(WEB + '/cancel', data=fields)).status_code == 200 and dump(composition[1]) == before
            with composition[1]._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_bulk_wait_results').fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
    asyncio.run(scenario())
    leases.release(token)
    assert not composition[2].seen


def test_frozen_member_pages_preserve_count_and_refuse_rebase(composition, bulk, surface):
    key = root(bulk, '\n'.join(f'198.18.0.{i}' for i in range(1, 103)))
    async def scenario():
        async with surface() as (client, calls, _):
            _, fields = await review(client, key)
            before = dump(composition[1])
            result = await client.post(WEB + '/cancellation-review/page', data=fields | {'page': '2'})
            assert result.status_code == 200 and 'value="102"' in result.text and fields['review'] in result.text
            assert result.text.count('STOPPED_UNSENT</td>') == 2 and dump(composition[1]) == before
            assert not any(path == API + 'cancel' for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['counts', 'members', 'flag', 'settled', 'authority', 'attention', 'projection'])
def test_bad_current_status_never_implies_success(composition, bulk, surface, damage):
    key = root(bulk)
    def transform(request, response):
        if request.url.path != API + 'cancellation': return response
        value = response.json()
        if damage == 'counts': value['current_counts']['STOPPED_UNSENT'] = True
        if damage == 'members': value['targets'].clear()
        if damage == 'flag': value['can_execute'] = True
        if damage == 'settled': value['settled'] = 1
        if damage == 'authority': value['targets'][0]['generation'] = True
        if damage == 'attention': value['attention_count'] = 1
        if damage == 'projection':
            value.pop('current_counts'); value.pop('attention_count')
            for row in value['targets']:
                for field in ('initial_state', 'attention', 'job_id', 'attempt_digest'): row.pop(field, None)
        return httpx.Response(200, json=value)
    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client, key)
            assert (await client.post(WEB + '/cancel', data=fields)).status_code == 200
            before = dump(composition[1])
            result = await client.get(f'{WEB}/cancellations/{key}')
            assert result.status_code == 503 and 'unavailable' in result.text and dump(composition[1]) == before
    asyncio.run(scenario())


def test_no_implicit_optional_initialization_or_cache_authority(composition, bulk, surface):
    key = root(bulk)
    controls = BulkCancellations(composition[1], clock=bulk[0].clock)
    original = controls.review(key, 'alice', ('Operator',))
    cache = BulkCancellationReviews(900)
    frozen = cache.prepare('alice', 'cookie', original)
    assert cache.ttl == 300
    with pytest.raises(FrozenInstanceError): frozen.summary_json = '{}'
    frozen.summary['counts'].clear()
    assert frozen.summary['counts']
    for _ in range(4): cache.prepare('alice', 'cookie', original)
    with pytest.raises(ValueError): cache.prepare('alice', 'cookie', original)


@pytest.mark.parametrize('bad', ['count_bool', 'time_alias', 'digest', 'extra', 'viewer', 'other', 'page_bool', 'scope_change'])
def test_private_api_fields_owner_and_exact_review_refuse_without_writes(composition, bulk, surface, bad):
    key = root(bulk)
    async def scenario():
        async with surface() as (_, _, app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            actor = {'subject': 'alice', 'display_name': 'Actual operator', 'roles': ['Operator']}
            value = (await client.post(API + 'cancellation-review', json={'actor': actor, 'operation_id': key})).json()
            body = {k: value[k] for k in ('operation_id', 'reviewed_at', 'review_digest', 'accepted_count')}
            body['actor'] = actor
            suffix, code = 'cancel', 422
            if bad == 'count_bool': body['accepted_count'] = True
            if bad == 'time_alias': body['reviewed_at'] = body['reviewed_at'].replace('Z', '+00:00')
            if bad == 'digest': body['review_digest'] = 'A'*64
            if bad == 'extra': body['device_ids'] = [1]
            if bad == 'viewer': actor['roles'], code = ['Viewer'], 403
            if bad == 'other': actor['subject'], code = 'other', 403
            if bad == 'page_bool': suffix, body['page'] = 'cancellation-targets', True
            if bad == 'scope_change':
                body['review_digest'], suffix, code = '0'*64, 'cancellation-targets', 409
            before = dump(composition[1])
            response = await client.post(API + suffix, json=body)
            assert response.status_code == code, response.text
            assert dump(composition[1]) == before and response.headers['cache-control'] == 'no-store'
    asyncio.run(scenario())


def test_receipt_survives_metadata_failure_and_changed_actor_recovers_status_only(composition, bulk, surface):
    key, committed = root(bulk), [False]
    def transform(request, response):
        if request.url.path == API + 'cancel': committed[0] = True
        if committed[0] and request.url.path == '/api/v1/status': return httpx.Response(503, json={'detail': 'Synthetic metadata unavailable'})
        return response
    async def scenario():
        async with surface(transform=transform) as (client, _, _):
            _, fields = await review(client, key)
            result = await client.post(WEB + '/cancel', data=fields)
            assert result.status_code == 200 and 'Uncompleted work cancelled' in result.text
            committed[0] = False
            client.headers['Remote-Groups'] = 'ftd-shun-administrators'
            before = dump(composition[1])
            assert (await client.post(WEB + '/cancel', data=fields)).status_code == 409
            committed[0] = False  # Restore metadata before preparing a new read-only review.
            assert (await client.get(f'{WEB}/cancellations/{key}')).status_code == 200
            assert dump(composition[1]) == before
            existing = await client.post(f'{WEB}/{key}/cancellation-review', data={'csrf': fields['csrf']})
            assert existing.status_code == 303 and existing.headers['location'] == f'{WEB}/cancellations/{key}'
    asyncio.run(scenario())


def test_late_expiry_during_review_page_stream_refuses_without_writes(composition, bulk, monkeypatch):
    key = root(bulk)
    controls = BulkCancellations(composition[1], clock=bulk[0].clock)
    value = controls.review(key, 'alice', ('Operator',))
    from ftd_shun_manager import bulk_cancellations
    original = bulk_cancellations._scope
    def expire(db, key):
        yield from original(db, key)
        bulk[1][0] += timedelta(minutes=6)
    monkeypatch.setattr(bulk_cancellations, '_scope', expire)
    before = dump(composition[1])
    with pytest.raises(ValueError, match='expired'):
        controls.review_page(key, value['reviewed_at'], value['review_digest'], 1, 'alice', ('Operator',))
    assert dump(composition[1]) == before


def test_maximum_private_cancellation_and_late_status_page(ten_device_composition, bulk, monkeypatch):
    composition = ten_device_composition
    key = root(bulk, '\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(10000)), tuple(range(1, 11)))
    async def scenario():
        async with surface_for(composition, monkeypatch)() as (client, _, _):
            _, fields = await review(client, key)
            assert fields['accepted_count'] == '100000'
            last = await client.post(WEB + '/cancellation-review/page', data=fields | {'page': '1000'})
            assert last.status_code == 200 and last.text.count('STOPPED_UNSENT</td>') == 100
            result = await client.post(WEB + '/cancel', data=fields)
            assert result.status_code == 200, result.text[:400]
            status = await client.get(f'{WEB}/cancellations/{key}?page=1000')
            assert status.status_code == 200 and 'Page 1000 / 1000' in status.text
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome,disposition', [(AdditionResult(True, 'management'), 'RETAINED_APPLIED'),
    (AdditionResult(False, None), 'RETAINED_APPLIED'), ('FAILED', 'STOPPED_FAILED'), ('UNVERIFIED', 'STOPPED_UNVERIFIED')])
def test_completed_owned_history_digest_without_pending_job_is_reviewable(composition, bulk, leases, surface, outcome, disposition):
    key = grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, outcome)
    async def scenario():
        async with surface() as (client, _, _):
            page, fields = await review(client, key)
            assert disposition in page.text
            response = await client.post(WEB+'/cancel', data=fields)
            assert response.status_code == 200, response.text[:400]
            status = await client.get(f'{WEB}/cancellations/{key}')
            assert status.status_code == 200 and disposition in status.text
    asyncio.run(scenario())
    leases.release(token)
