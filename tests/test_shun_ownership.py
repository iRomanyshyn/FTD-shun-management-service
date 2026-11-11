"""Current maintenance is not historical creation or automatic detection."""

import asyncio
import json
from dataclasses import replace
from ipaddress import IPv4Address

import httpx
import pytest
from test_bulk_policy import bulk as bulk_fixture
from test_bulk_policy import confirm, dump, prepare, retire
from test_managed_shuns import change
from test_shun_pagination import populate
from test_shun_pagination import store as store_fixture

from ftd_shun_manager import web
from ftd_shun_manager.api import _serialize, create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.store import Device

bulk = bulk_fixture
store = store_fixture
IP = IPv4Address('198.18.0.0')


def test_absent_policy_is_unmanaged_without_initialization_or_creation_claim(store):
    populate(store, 3)
    with store._connection() as db:
        db.execute('INSERT INTO manual_import_batches VALUES (?,?,?,?,?,?,?)',
                   ('old-batch', 'manual_import', 'alice', 'Alice', '["Operator"]',
                    json.dumps({'label': 'Historical creation only', 'reason': 'Fixture'}), 'requested'))
        db.execute('INSERT INTO shun_import_origins VALUES (?,?,?,?,?,?,?)',
                   ('old-batch', 'old-job', 1, IP.packed, 'outside', 'occurrence-0', 'verified'))
    before = dump(store)
    page = store.active_shuns_page(ownership='unmanaged')
    assert page['ownership'] == 'unmanaged' and page['total'] == 3
    assert all(row.maintained is False for row in page['items'])
    assert page['items'][0].manual_imports and page['items'][0].maintained is False
    assert all(row.maintained is None for row in store.list_active_shuns())
    assert dump(store) == before
    for value in ('managed', '', None, True, ['all']):
        with pytest.raises(ValueError): store.active_shuns_page(ownership=value)


def test_legacy_maintenance_is_device_scoped_and_retirement_is_not_protection(store):
    policy = ManagedShuns(store)
    policy.initialize()
    change(policy, targets=[(1, IP)])
    populate(store, 2)
    store.upsert_device(Device(2, 'second', IPv4Address('192.0.2.2'), True), 'ssh-ed25519 AAAA')
    with store._connection() as db:
        db.execute('INSERT INTO shun_state SELECT 2,ip,interface,active,first_seen_at,last_seen_at,last_changed_at,NULL '
                   'FROM shun_state WHERE ip=?', (IP.packed,))
    rows = store.active_shuns_page()['items']
    assert {(row.device_id, row.ip) for row in rows if row.maintained} == {(1, IP)}
    assert store.active_shuns_page(ownership='unmanaged')['total'] == 2
    change(policy, action='RETIRE', targets=[(1, IP)])
    assert store.active_shuns_page(ownership='unmanaged')['total'] == 3
    with store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM protected_ips').fetchone()[0] == 0


def test_large_unmanaged_page_filters_in_sql_and_stays_readable_during_writer(store, monkeypatch):
    policy = ManagedShuns(store)
    policy.initialize()
    change(policy, targets=[(1, IP)])
    populate(store, 100000)
    statements, sizes = [], []
    original = store._active_shuns
    def traced(db, *args, **kwargs):
        db.set_trace_callback(statements.append)
        result = original(db, *args, **kwargs)
        sizes.append(len(result))
        return result
    monkeypatch.setattr(store, '_active_shuns', traced)
    with store._connection() as writer:
        writer.execute('BEGIN IMMEDIATE')
        page = store.active_shuns_page(777, ownership='unmanaged')
        assert writer.in_transaction
        writer.rollback()
    assert page['total'] == 99999 and page['pages'] == 1000 and sizes == [100]
    assert all(row.maintained is False for row in page['items'])
    assert any('NOT EXISTS' in sql and 'LIMIT 100 OFFSET 77600' in sql for sql in statements)


def test_v2_filter_precedes_limit_handles_interfaces_and_retained_import_origin(bulk, monkeypatch):
    policy, _ = bulk
    store = policy.store
    populate(store, 251)
    with store._connection() as db:
        db.execute("INSERT INTO shun_state SELECT 1,ip,'inside',active,first_seen_at,last_seen_at,last_changed_at,NULL "
                   'FROM shun_state WHERE ip=?', (IP.packed,))
        db.execute('INSERT INTO shun_state SELECT 2,ip,interface,active,first_seen_at,last_seen_at,last_changed_at,NULL '
                   "FROM shun_state WHERE ip=? AND interface='outside'", (IP.packed,))
    _, proposal = prepare(bulk, str(IP))
    confirm(bulk, proposal)  # Already-present adoption is maintenance, not creation.
    before = dump(store)
    full = store.active_shuns_page()
    assert full['total'] == 253 and sum(row.maintained for row in full['items']) == 2
    assert len(store.list_active_shuns(IP, classify_maintenance=True)) == 3
    statements = []
    original = store._active_shuns
    def traced(db, *args, **kwargs):
        db.set_trace_callback(statements.append)
        return original(db, *args, **kwargs)
    monkeypatch.setattr(store, '_active_shuns', traced)
    pages = [store.active_shuns_page(n, ownership='unmanaged') for n in (1, 2, 3)]
    assert [len(page['items']) for page in pages] == [100, 100, 51]
    assert all(page['total'] == 251 for page in pages)
    assert all(row.maintained is False for page in pages for row in page['items'])
    assert any('NOT EXISTS' in sql and 'LIMIT 100 OFFSET 200' in sql for sql in statements)
    assert dump(store) == before
    retire(bulk, [(1, IP)])
    assert store.active_shuns_page(ownership='unmanaged')['total'] == 253


def test_policy_change_after_count_does_not_mix_page_and_classification(bulk, monkeypatch):
    policy, _ = bulk
    store = policy.store
    populate(store, 3)
    _, proposal = prepare(bulk, str(IP))
    confirm(bulk, proposal)
    original = store._active_shuns
    def retire_after_count(db, *args, **kwargs):
        retire(bulk, [(1, IP)])
        return original(db, *args, **kwargs)
    monkeypatch.setattr(store, '_active_shuns', retire_after_count)
    page = store.active_shuns_page(ownership='unmanaged')
    assert page['total'] == 2 and len(page['items']) == 2
    assert all(row.ip != IP and row.maintained is False for row in page['items'])
    monkeypatch.setattr(store, '_active_shuns', original)
    assert store.active_shuns_page(ownership='unmanaged')['total'] == 3


@pytest.mark.parametrize('damage', ['partial', 'metadata', 'enabled'])
def test_partial_or_invalid_policy_never_means_unmanaged(store, damage):
    populate(store, 1)
    if damage != 'partial': ManagedShuns(store).initialize()
    with store._connection() as db:
        if damage == 'partial': db.execute('CREATE TABLE managed_shun_targets (ip BLOB)')
        elif damage == 'metadata': db.execute('DELETE FROM managed_shun_registry')
        else: db.execute('ALTER TABLE managed_shun_targets RENAME COLUMN enabled TO broken')
    before = dump(store)
    with pytest.raises(ManagedStateUnavailable): store.active_shuns_page(ownership='unmanaged')
    assert dump(store) == before


def test_invalid_policy_returns_unavailable_instead_of_unmanaged_api_data(store):
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode='disabled', development_auth=False)
    app = create_app(config, store)
    populate(store, 1)
    with store._connection() as db: db.execute('CREATE TABLE managed_shun_targets (ip BLOB)')
    before = dump(store)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            for path in ('/api/v1/shuns-page', '/api/v1/shuns-page?ownership=unmanaged', f'/api/v1/shuns/{IP}'):
                response = await client.get(path)
                assert response.status_code == 503
                assert 'no unmanaged state was inferred' in response.json()['detail']
    asyncio.run(scenario())
    assert dump(store) == before


def test_api_and_unmanaged_bff_are_readonly_bounded_and_keep_route(store, monkeypatch):
    populate(store, 251)
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode='disabled', development_auth=False)
    app = create_app(config, store)
    calls = []
    def internal(request):
        calls.append(request)
        if request.url.path == '/api/v1/shuns-page':
            page = store.active_shuns_page(int(request.url.params['page']), ownership=request.url.params.get('ownership', 'all'))
            return httpx.Response(200, json={**page, 'items': [_serialize(row) for row in page['items']]})
        if request.url.path == '/api/v1/search':
            return httpx.Response(200, json=store.search_ip_history(request.url.params['ip']))
        return httpx.Response(200, json={})
    monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url='http://internal'))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            response = await client.get('/api/v1/shuns-page?ownership=unmanaged&page=3')
            assert response.status_code == 200 and len(response.json()['items']) == 51
            assert all(row['maintained'] is False for row in response.json()['items'])
            assert (await client.get('/api/v1/shuns-page?ownership=managed')).status_code == 422
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url='https://lab.test') as client:
            assert (await client.get('/unmanaged')).status_code == 401 and not calls
            client.headers['Remote-User'] = 'viewer'
            response = await client.get('/unmanaged?page=2&q=198.18.0.250')
            assert response.status_code == 200 and '100 per page' in response.text
            assert 'href="/unmanaged" aria-current="page"' in response.text
            assert 'href="/unmanaged?page=3&amp;q=198.18.0.250"' in response.text
            assert 'action="/unmanaged"' in response.text
            assert 'They are not automatically restored after disappearance.' in response.text
            assert 'Queue removal' not in response.text
            assert response.headers['cache-control'] == 'no-store'
            assert (await client.get('/unmanaged?page=0')).status_code == 422
    before = dump(store)
    asyncio.run(scenario())
    assert dump(store) == before
    assert all(request.method == 'GET' for request in calls)


@pytest.mark.parametrize('old_page', [{'items': [], 'page': 1}, {'items': [{'maintained': True}], 'ownership': 'unmanaged'}])
def test_unmanaged_view_refuses_old_or_unfiltered_api(store, monkeypatch, old_page):
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode='disabled', development_auth=False)
    monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=old_page if request.url.path == '/api/v1/shuns-page' else {})), base_url='http://internal'))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url='https://lab.test',
                                     headers={'Remote-User': 'viewer'}) as client:
            response = await client.get('/unmanaged')
            assert response.status_code == 503 and 'no unfiltered list was substituted' in response.text
    asyncio.run(scenario())
