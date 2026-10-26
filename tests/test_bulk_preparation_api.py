"""Real private preparation API on disposable exact profiles; no lab/FTD work."""

import asyncio
import json
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import confirm, dump, prepare
from test_bulk_preparation_intent import trace_read_only_chunks
from test_continuous_api import bulk as bulk_fixture
from test_continuous_api import cancellation_controls as cancellation_fixture
from test_continuous_api import composition as composition_fixture
from test_continuous_api import dispatch as dispatch_fixture
from test_continuous_api import journal as journal_fixture
from test_continuous_api import leases as leases_fixture
from test_continuous_api import waits as waits_fixture
from test_continuous_dispatch import TracedAgent
from test_import_preparations import outside

from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_intent import verify_bulk_intent
from ftd_shun_manager.config import Settings
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
from ftd_shun_manager.device_leases import DeviceLeases
from ftd_shun_manager.import_preparations import ImportPreparations
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
PREFIX = '/api/v2/managed-imports/'
ACTOR = {'subject': 'alice', 'display_name': 'Actual fixture author', 'roles': ['Operator']}


def application(composition):
    settings, store, agent, service = composition
    return create_app(settings, store, agent, continuous_dispatcher=service)


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal')


async def stage(client, *, text='198.51.100.1', devices=None, actor=None, **metadata):
    return await client.post(PREFIX + 'prepare', json={'actor': actor or ACTOR, 'text': text,
        'device_ids': [1] if devices is None else devices, **metadata})


async def report(client, saved, *, actor=None, page=1):
    return await client.post(PREFIX + 'preparation', json={'actor': actor or ACTOR,
        'preparation_id': saved['plan_id'], 'page': page})


async def proposal(client, saved, *, actor=None, key=None):
    return await client.post(PREFIX + 'proposal', json={'actor': actor or ACTOR,
        'preparation_id': saved['plan_id'], 'preparation_digest': saved['digest'], 'operation_id': key or str(uuid4())})


def assert_no_authority(value):
    assert value['intent_format'] == 2 and value['can_execute'] is False
    assert value['policy_saved'] is False and value['device_work_admitted'] is False


def test_mixed_scope_diagnostics_provenance_and_pure_proposal(composition, bulk):
    _, store, agent, service = composition
    # Distinct synthetic current states: managed, unmanaged observation and protection.
    confirm(bulk, prepare(bulk, devices=(1,))[1])
    store.record_observed_shun(2, IPv4Address('198.51.100.1'), 'management')
    ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address('198.51.100.2'), 0, 'protector', 'Protector', ())
    before = outside(store)
    app = application(composition)

    async def scenario():
        async with client_for(app) as client:
            response = await stage(client, text='source-marker 198.51.100.1 # comment-marker\n198.51.100.2\n198.51.100.3\n198.51.100.1\n555.555.555.666',
                                   devices=[2, 1], label='<b>Intentional label</b>', reason='Intentional reason')
            assert response.status_code == 201, response.text
            assert response.headers['cache-control'] == 'no-store'
            saved = response.json()
            assert_no_authority(saved)
            value = (await report(client, saved)).json()
            assert_no_authority(value)
            assert value['target_count'] == 6 and value['address_count'] == 3
            assert value['classification_counts'] == {'PROPOSE_ADD': 2, 'PROPOSE_ADOPT': 1, 'ALREADY_MANAGED': 1, 'EXCLUDED_PROTECTED': 2}
            assert value['source_counts']['Duplicate'] == value['source_counts']['Invalid'] == 1
            assert value['actor_subject'] == ACTOR['subject'] and value['actor_display_name'] == ACTOR['display_name']
            assert value['actor_roles'] == ['Operator'] and value['label'] == '<b>Intentional label</b>'
            assert not any(marker in json.dumps(value) for marker in ('source-marker', 'comment-marker'))
            key = str(uuid4())
            frozen = dump(store)
            result = await proposal(client, saved, key=key)
            assert result.status_code == 200, result.text
            proposed = result.json()
            assert_no_authority(proposed)
            cells = ((row['device_id'], IPv4Address(row['ip']), row['classification']) for row in value['targets'])
            assert verify_bulk_intent(proposed['canonical'], cells, proposed['digest']).as_dict() == proposed['manifest']
            assert (await proposal(client, saved, key=key)).json() == proposed and dump(store) == frozen
            source = (await client.post(PREFIX + 'preparations', json={'actor': ACTOR})).json()
            assert any(plan['plan_id'] == saved['plan_id'] for plan in source['plans'])
            status = (await client.get('/api/v1/status')).json()
            assert status['bulk_import_preparation_available'] is True
            assert status['managed_workflows_available'] is False and status['manual_mutations_available'] is False
            for path in ['confirm', 'cancel-confirmed', 'arbitrary-command']:
                assert (await client.post(PREFIX + path, json={})).status_code == 503
    asyncio.run(scenario())
    assert outside(store) == before and not agent.seen and not service._wake.is_set()
    with store._connection() as db:
        assert not any('source-marker' in row['header_json'] or 'comment-marker' in row['header_json']
                       for row in db.execute('SELECT header_json FROM import_preparation_plans'))


def test_owner_recovery_role_loss_cancel_pause_and_deterministic_restart(composition, bulk):
    app = application(composition)
    store = composition[1]
    before = outside(store)

    async def scenario():
        async with client_for(app) as client:
            first = (await stage(client, label='First retained draft')).json()  # Discarded response can be recovered by owner list.
            second = (await stage(client, actor=ACTOR | {'subject': 'bob'}, label='Other owner private')).json()
            listing = await client.post(PREFIX + 'preparations', json={'actor': ACTOR | {'roles': ['Viewer']}})
            assert listing.status_code == 200
            assert [row['plan_id'] for row in listing.json()['plans']] == [first['plan_id']]
            assert_no_authority(listing.json())
            for name, body in [('preparation', {'preparation_id': second['plan_id']}),
                               ('cancel-preparation', {'preparation_id': second['plan_id']}),
                               ('proposal', {'preparation_id': second['plan_id'], 'preparation_digest': second['digest'], 'operation_id': str(uuid4())})]:
                response = await client.post(PREFIX + name, json={'actor': ACTOR, **body})
                assert response.status_code == 409 and 'Other owner private' not in response.text
            body = {'actor': ACTOR | {'roles': []}, 'preparation_id': first['plan_id']}
            with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
            assert (await client.post(PREFIX + 'cancel-preparation', json=body)).json()['cancelled'] is True
            frozen = dump(store)
            response = await client.post(PREFIX + 'cancel-preparation', json=body)
            assert response.status_code == 200 and response.json()['cancelled'] is False and dump(store) == frozen
            assert (await report(client, first)).json()['state'] == 'CANCELLED'
            assert (await proposal(client, first)).status_code == 409
            # A fresh API instance over the same existing, inactive composition recovers the same private draft.
            clone = ContinuousDispatcher(store, composition[2], enabled=True, agent_concurrency=2)
            fresh = create_app(composition[0], store, composition[2], continuous_dispatcher=clone)
            async with client_for(fresh) as restarted:
                assert (await report(restarted, first)).json()['state'] == 'CANCELLED'
                assert (await report(restarted, second, actor=ACTOR | {'subject': 'bob'})).status_code == 200
    asyncio.run(scenario())
    # Only the explicit synthetic pause changed outside the draft journal.
    with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    assert outside(store) == before and not composition[2].seen


@pytest.mark.parametrize('missing', ['absent', 'partial', 'corrupt_profile'])
def test_missing_or_partial_storage_never_initialized_or_repaired(composition, missing, monkeypatch):
    app = application(composition)
    store = composition[1]
    with store._connection() as db:
        if missing == 'absent':
            db.execute('DROP TABLE import_preparation_targets')
            db.execute('DROP TABLE import_preparation_plans')
        elif missing == 'partial':
            db.execute('DROP TRIGGER import_preparation_header_immutable')
        else:
            db.execute('DROP TRIGGER managed_bulk_manifest_retained')
    before = dump(store)

    def forbidden(*_args, **_kwargs): raise AssertionError('No migration, pruning or initialization.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    monkeypatch.setattr(ImportPreparations, 'initialize', forbidden)
    monkeypatch.setattr(ImportPreparations, 'prune_expired', forbidden)

    async def scenario():
        async with client_for(app) as client:
            response = await client.post(PREFIX + 'preparations', json={'actor': ACTOR})
            if missing == 'absent':
                assert response.status_code == 200 and response.json()['initialized'] is False
            else:
                assert response.status_code == 503
            assert (await stage(client)).status_code == 503
            assert (await client.post(PREFIX + 'cancel-preparation', json={'actor': ACTOR, 'preparation_id': str(uuid4())})).status_code == 503
    asyncio.run(scenario())
    assert dump(store) == before


@pytest.mark.parametrize('damage', ['devices_bool', 'devices_string', 'devices_duplicate', 'devices_empty', 'devices_large',
    'devices_disabled', 'actor_extra', 'actor_blank', 'actor_control', 'roles_duplicate', 'roles_unknown', 'viewer',
    'text_bytes', 'text_type', 'label_control', 'label_size', 'reason_size', 'action', 'source_lines', 'source_rows'])
def test_creation_strict_input_and_limits_never_change_state(composition, damage):
    app = application(composition)
    store = composition[1]
    body = {'actor': dict(ACTOR), 'text': '198.51.100.1', 'device_ids': [1]}
    code = 422
    if damage == 'devices_bool': body['device_ids'] = [True]
    if damage == 'devices_string': body['device_ids'] = ['1']
    if damage == 'devices_duplicate': body['device_ids'] = [1, 1]
    if damage == 'devices_empty': body['device_ids'] = []
    if damage == 'devices_large': body['device_ids'] = list(range(1, 12))
    if damage == 'devices_disabled': body['device_ids'], code = [5], 409
    if damage == 'actor_extra': body['actor']['command'] = 'shun'
    if damage == 'actor_blank': body['actor']['subject'] = ' '
    if damage == 'actor_control': body['actor']['subject'] = 'user\n'
    if damage == 'roles_duplicate': body['actor']['roles'] = ['Operator', 'Operator']
    if damage == 'roles_unknown': body['actor']['roles'] = ['Root']
    if damage == 'viewer': body['actor']['roles'], code = ['Viewer'], 403
    if damage == 'text_bytes': body['text'] = 'я' * 524289
    if damage == 'text_type': body['text'] = True
    if damage == 'label_control': body['label'] = 'bad\x00'
    if damage == 'label_size': body['label'] = 'a' * 101
    if damage == 'reason_size': body['reason'] = 'a' * 501
    if damage == 'action': body['action'] = 'MAINTAIN'
    if damage == 'source_lines': body['text'] = '\n' * 20001
    if damage == 'source_rows': body['text'] = '\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(10001))
    before = dump(store)

    async def scenario():
        async with client_for(app) as client:
            response = await client.post(PREFIX + 'prepare', json=body)
            assert response.status_code == code, response.text[:500]
            assert response.headers['cache-control'] == 'no-store'
    asyncio.run(scenario())
    assert dump(store) == before and not composition[2].seen


@pytest.mark.parametrize('damage', ['page_bool', 'page_string', 'page_zero', 'page_overflow', 'uuid_alias',
    'uuid_unknown', 'digest', 'operation_alias', 'operation_same', 'extra', 'viewer'])
def test_strict_report_and_proposal_binding(composition, damage):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client)).json()
            path = 'preparation' if damage.startswith(('page_', 'uuid_')) else 'proposal'
            body = {'actor': ACTOR, 'preparation_id': saved['plan_id']}
            code = 422
            if path == 'proposal': body |= {'preparation_digest': saved['digest'], 'operation_id': str(uuid4())}
            if damage == 'page_bool': body['page'] = True
            if damage == 'page_string': body['page'] = '1'
            if damage == 'page_zero': body['page'] = 0
            if damage == 'page_overflow': body['page'] = 1001
            if damage == 'uuid_alias': body['preparation_id'] = saved['plan_id'].upper()
            if damage == 'uuid_unknown': body['preparation_id'], code = str(uuid4()), 409
            if damage == 'digest': body['preparation_digest'], code = '0' * 64, 409
            if damage == 'operation_alias': body['operation_id'] = body['operation_id'].upper()
            if damage == 'operation_same': body['operation_id'] = saved['plan_id']
            if damage == 'extra': body['maintain_present'] = True
            if damage == 'viewer': body['actor'], code = ACTOR | {'roles': ['Viewer']}, 403
            before = dump(store)
            response = await client.post(PREFIX + path, json=body)
            assert response.status_code == code, response.text
            assert dump(store) == before
    asyncio.run(scenario())


def test_expiry_and_frozen_classifications_never_rebase_or_renew(composition, bulk):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client)).json()
            original = (await report(client, saved)).json()
            store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')
            ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address('198.51.100.1'), 0, 'protector', 'Protector', ())
            before = dump(store)
            assert (await report(client, saved)).json() == original
            assert (await proposal(client, saved)).status_code == 200  # Historical proposal, not admission.
            assert dump(store) == before
            bulk[1][0] += timedelta(minutes=11)
            expired = (await report(client, saved)).json()
            assert expired['state'] == 'EXPIRED' and expired['expires_at'] == original['expires_at']
            assert (await proposal(client, saved)).status_code == 409 and dump(store) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['invalid', 'protected'])
def test_diagnostic_or_exclusion_only_draft_never_fabricates_proposal(composition, kind):
    store = composition[1]
    if kind == 'protected':
        ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address('198.51.100.1'), 0, 'protector', 'Protector', ())
    app = application(composition)
    before = outside(store)

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client, text='555.555.555.666' if kind == 'invalid' else '198.51.100.1')).json()
            page = (await report(client, saved)).json()
            assert_no_authority(page)
            assert page['target_count'] == (0 if kind == 'invalid' else 1)
            assert (await proposal(client, saved)).status_code == 422
    asyncio.run(scenario())
    assert outside(store) == before


def test_owner_capacity_no_eviction_and_confirmed_draft_cannot_revoke_policy(composition, bulk):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client)).json()
            proposed = (await proposal(client, saved)).json()
            bulk[0].confirm(proposed['canonical'], proposed['digest'], 1, 'alice', 'Current operator', ('Operator',),
                            maintain_present=True, enabled=True, addition_device_ids=frozenset({1}))
            assert (await report(client, saved)).json()['state'] == 'CONFIRMED'
            before = dump(store)
            assert (await client.post(PREFIX + 'cancel-preparation', json={'actor': ACTOR, 'preparation_id': saved['plan_id']})).status_code == 409
            assert (await proposal(client, saved)).status_code == 409 and dump(store) == before
            for _ in range(3): assert (await stage(client)).status_code == 201
            before = dump(store)
            assert (await stage(client)).status_code == 429 and dump(store) == before
    asyncio.run(scenario())


def test_late_insert_failure_atomic_and_lost_create_reply_recovers_owner_scope(composition):
    app = application(composition)
    store = composition[1]
    with store._connection() as db:
        db.execute("""CREATE TRIGGER synthetic_preparation_insert_failure BEFORE INSERT ON import_preparation_targets
            WHEN NEW.device_id=2 BEGIN SELECT RAISE(ABORT,'Synthetic late draft failure'); END""")
    # The optional journal recognizer ignores unrelated test triggers, not changed production schema.
    before = dump(store)

    async def scenario():
        async with client_for(app) as client:
            response = await stage(client, devices=[1, 2])
            assert response.status_code == 503 and dump(store) == before
            with store._connection() as db: db.execute('DROP TRIGGER synthetic_preparation_insert_failure')
            assert (await stage(client)).status_code == 201  # Imagine that this reply was lost.
            after = dump(store)
            recovered = (await client.post(PREFIX + 'preparations', json={'actor': ACTOR})).json()
            assert len(recovered['plans']) == 1 and dump(store) == after
    asyncio.run(scenario())


@pytest.fixture
def ten_device_composition(bulk, dispatch):
    store, agent = bulk[0].store, TracedAgent()
    leases = DeviceLeases(store, dispatch.queue)
    with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    leases.initialize(frozenset(range(1, 11)), concurrency=2)
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
        db.execute('UPDATE protected_policy SET legacy_imported=1')
    settings = Settings(store.path, None, '/unused/agent.sock', '/unused/web.sock', '/unused/api.sock',
                        'socket', 120, 300, 60, 366, 86400, False,
                        agent_cycles_enabled=True, large_snapshots_enabled=True)
    return settings, store, agent, ContinuousDispatcher(store, agent, enabled=True, agent_concurrency=2)


def test_actual_api_maximum_10000_addresses_ten_devices_and_100_row_pages(ten_device_composition):
    app = application(ten_device_composition)
    store = ten_device_composition[1]
    before = outside(store)

    async def scenario():
        async with client_for(app) as client:
            text = '\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(10000))
            response = await stage(client, text=text, devices=list(range(10, 0, -1)))
            assert response.status_code == 201, response.text[:500]
            saved = response.json()
            assert saved['target_count'] == 100000
            first, last = (await report(client, saved)).json(), (await report(client, saved, page=1000)).json()
            assert first['address_count'] == 10000 and first['pages'] == 1000 and first['page_size'] == 100
            assert len(first['targets']) == len(last['targets']) == 100
            assert len(first['report_rows']) == 100 and not last['report_rows']
            assert first['targets'][0]['device_id'] == 1 and last['targets'][-1]['device_id'] == 10
            frozen = dump(store)
            proposed = await proposal(client, saved)
            assert proposed.status_code == 200, proposed.text[:500]
            assert proposed.json()['manifest']['pair_count'] == proposed.json()['manifest']['accepted_count'] == 100000
            assert len(proposed.json()['canonical'].encode()) <= 8192 and dump(store) == frozen
    asyncio.run(scenario())
    assert outside(store) == before and not ten_device_composition[2].seen


def test_legacy_profile_routes_refuse_without_creating_optional_storage(tmp_path, monkeypatch):
    monkeypatch.delenv('FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS', raising=False)
    store = Store(tmp_path / 'legacy.db')
    settings = Settings(store.path, None, '/unused/agent.sock', '/unused/web.sock', '/unused/api.sock',
                        'disabled', 120, 300, 60, 366, 86400, False)
    app = create_app(settings, store)
    before = dump(store)

    async def scenario():
        async with client_for(app) as client:
            assert (await stage(client)).status_code == 503
            assert (await client.post(PREFIX + 'preparations', json={'actor': ACTOR})).status_code == 503
    asyncio.run(scenario())
    assert dump(store) == before


@pytest.mark.parametrize('route', ['preparations', 'preparation', 'proposal', 'cancel-preparation'])
def test_same_count_substitution_is_unavailable_before_reporting_or_cancel(composition, route):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client)).json()
            with store._connection() as db:
                original = dict(db.execute('SELECT * FROM import_preparation_targets WHERE plan_id=?', (saved['plan_id'],)).fetchone())
                db.execute('DELETE FROM import_preparation_targets WHERE plan_id=?', (saved['plan_id'],))
                original['ip'] = IPv4Address('198.51.100.2').packed
                db.execute('INSERT INTO import_preparation_targets VALUES (?,?,?,?,?,?,?,?,?)', tuple(original.values()))
            body = {'actor': ACTOR}
            if route != 'preparations': body['preparation_id'] = saved['plan_id']
            if route == 'proposal': body |= {'preparation_digest': saved['digest'], 'operation_id': str(uuid4())}
            before = dump(store)
            response = await client.post(PREFIX + route, json=body)
            assert response.status_code == 503 and dump(store) == before
            assert 'targets' not in response.json() and 'plans' not in response.json()
    asyncio.run(scenario())


def test_global_capacity_and_concurrent_owner_limit_never_evict_or_partially_stage(composition):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            results = await asyncio.gather(*[stage(client) for _ in range(5)])
            assert sorted(response.status_code for response in results) == [201, 201, 201, 201, 429]
            for owner in range(3):
                for _ in range(4):
                    assert (await stage(client, actor=ACTOR | {'subject': f'owner-{owner}'})).status_code == 201
            before = dump(store)
            assert (await stage(client, actor=ACTOR | {'subject': 'new-owner'})).status_code == 429
            assert dump(store) == before
            listing = (await client.post(PREFIX + 'preparations', json={'actor': ACTOR})).json()
            assert len(listing['plans']) == 4
            assert len({row['plan_id'] for row in listing['plans']}) == 4
    asyncio.run(scenario())


def test_actual_proposal_uses_readonly_bounded_streams(composition, monkeypatch):
    app = application(composition)
    store = composition[1]

    async def scenario():
        async with client_for(app) as client:
            saved = (await stage(client, text='\n'.join(f'198.18.{i // 256}.{i % 256}' for i in range(250)))).json()
            before = dump(store)
            with monkeypatch.context() as patch:
                sizes, _queries = trace_read_only_chunks(patch, store)
                response = await proposal(client, saved)
                assert response.status_code == 200, response.text
                assert sizes and max(sizes) == 100 and sum(sizes) == 500  # Original journal hash and distinct manifest hash.
            assert dump(store) == before
    asyncio.run(scenario())
