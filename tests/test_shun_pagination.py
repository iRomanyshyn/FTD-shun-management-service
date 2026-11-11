"""Bounded local Shuns pages, never full browser datasets or device operations."""

import asyncio
import json
from dataclasses import replace
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import _serialize, create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / 'pages.db')
    value.initialize()
    value.upsert_device(Device(1, 'lab', IPv4Address('192.0.2.1'), True), 'ssh-ed25519 AAAA')
    return value


def populate(store, count):
    # Synthetic observations only; no policy, queue, SSH or per-row audit workload.
    with store._connection() as db:
        db.executemany('INSERT INTO shun_state VALUES (?,?,?,?,?,?,?,?)',
            ((1, IPv4Address(0xC6120000 + n).packed, 'outside', 1, '2026-10-14T00:00:00Z',
              '2026-10-15T00:00:00Z', '2026-10-14T00:00:00Z', f'occurrence-{n}',)
             for n in range(count)))


def test_empty_invalid_and_clamped_pages(store):
    assert store.active_shuns_page() == {'items': [], 'ownership': 'all', 'page': 1, 'pages': 1, 'total': 0, 'page_size': 100}
    for page in (True, False, 0, -1, 2**31, '1', 1.0):
        with pytest.raises(ValueError): store.active_shuns_page(page)
    populate(store, 251)
    assert store.active_shuns_page(2**31 - 1)['page'] == 3
    with store._connection() as db:
        db.execute('UPDATE shun_state SET active=0')
    assert store.active_shuns_page(3)['page'] == 1


def test_tied_rows_are_distinct_and_pages_match_original_protected_newest_order(store):
    populate(store, 251)
    with store._connection() as db:
        db.execute('INSERT INTO protected_ips VALUES (?,?,?,?,?)',
                   (IPv4Address(0xC6120000 + 250).packed, 'Synthetic', '', 0, '2026-10-14T00:00:00Z'))
    pages = [store.active_shuns_page(n) for n in (1, 2, 3)]
    assert [len(page['items']) for page in pages] == [100, 100, 51]
    rows = [row for page in pages for row in page['items']]
    assert rows == store.list_active_shuns(classify_maintenance=True)
    assert rows[0].ip == IPv4Address(0xC6120000 + 250)
    assert len({(row.device_id, row.ip, row.interface) for row in rows}) == 251


def test_100000_rows_are_limited_in_sql_before_hydration(store, monkeypatch):
    populate(store, 100000)
    statements, sizes = [], []
    original = store._active_shuns

    def inspect(db, *args, **kwargs):
        db.set_trace_callback(statements.append)
        result = original(db, *args, **kwargs)
        sizes.append(len(result))
        return result

    monkeypatch.setattr(store, '_active_shuns', inspect)
    monkeypatch.setattr(store, 'list_active_shuns', lambda *_: pytest.fail('Must not materialize the full list'))
    page = store.active_shuns_page(777)
    assert page['total'] == 100000 and page['pages'] == 1000 and sizes == [100]
    assert any('LIMIT 100 OFFSET 77600' in statement for statement in statements)
    origin_reads = [statement for statement in statements if 'MIN(o.rowid)' in statement]
    assert len(origin_reads) == 1 and 'occurrence-77600' in origin_reads[0] and 'occurrence-0\'' not in origin_reads[0]


def test_page_loads_only_selected_provenance_and_keeps_coalesced_count(store):
    populate(store, 201)
    with store._connection() as db:
        for batch, payload in (('selected', json.dumps({'label': 'Example', 'reason': 'Fixture'})),
                               ('off-page', 'deliberately invalid off-page payload')):
            db.execute('INSERT INTO manual_import_batches VALUES (?,?,?,?,?,?,?)',
                       (batch, 'manual_import', 'alice', 'Alice', '["Operator"]', payload, 'requested'))
        for batch, index, job in (('selected', 0, 'one'), ('selected', 0, 'two'), ('off-page', 200, 'three')):
            db.execute('INSERT INTO shun_import_origins VALUES (?,?,?,?,?,?,?)',
                       (batch, job, 1, IPv4Address(0xC6120000 + index).packed, 'outside', f'occurrence-{index}', 'verified'))
    page = store.active_shuns_page()
    assert len(page['items']) == 100
    row = page['items'][0]
    assert row.manual_import_count == 2 and len(row.manual_imports) == 1
    assert row.manual_imports[0]['label'] == 'Example'
    assert row.manual_imports[0]['actor_subject'] == 'alice'
    assert all(not row.manual_imports for row in page['items'][1:])


def test_count_and_rows_share_read_snapshot_during_concurrent_removal(store, monkeypatch):
    populate(store, 201)
    original = store._active_shuns

    def remove_after_count(db, *args, **kwargs):
        with store._connection() as writer:
            writer.execute('UPDATE shun_state SET active=0')
        return original(db, *args, **kwargs)

    monkeypatch.setattr(store, '_active_shuns', remove_after_count)
    page = store.active_shuns_page(3)
    assert page['total'] == 201 and page['page'] == 3 and len(page['items']) == 1
    monkeypatch.setattr(store, '_active_shuns', original)
    assert store.active_shuns_page(3)['total'] == 0


def test_api_and_bff_use_bounded_pages_preserve_query_and_remain_readonly(store, monkeypatch):
    populate(store, 251)
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode='disabled', development_auth=False)
    app = create_app(config, store)
    requests = []

    def internal(request):
        requests.append(request)
        if request.url.path == '/api/v1/shuns-page':
            page = store.active_shuns_page(int(request.url.params['page']))
            return httpx.Response(200, json={**page, 'items': [_serialize(row) for row in page['items']]})
        if request.url.path == '/api/v1/search':
            return httpx.Response(200, json=store.search_ip_history(request.url.params['ip']))
        assert request.url.path == '/api/v1/status'
        return httpx.Response(200, json={})

    monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url='http://internal'))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as api:
            page = (await api.get('/api/v1/shuns-page?page=2')).json()
            assert page['page'] == 2 and len(page['items']) == 100 and page['total'] == 251
            for value in ('0', '-1', '2147483648', 'true', '1.5'):
                assert (await api.get('/api/v1/shuns-page', params={'page': value})).status_code == 422
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url='https://lab.test') as client:
            assert (await client.get('/')).status_code == 401 and not requests
            client.headers['Remote-User'] = 'viewer'
            result = await client.get('/?page=2&q=198.18.0.250')
            assert result.status_code == 200 and 'Page 2 of 3' in result.text
            assert result.text.count('<tr') <= 103
            assert '198.18.0.250' in result.text.split('id="search-results"')[1].split('</section>')[0]
            assert 'href="/?page=3&amp;q=198.18.0.250"' in result.text
            assert 'name="q" value="198.18.0.250"' in result.text
            assert (await client.get('/?page=0')).status_code == 422
            assert (await client.get('/?page=999999')).status_code == 200
            assert result.headers['cache-control'] == 'no-store'
        assert all(request.method == 'GET' for request in requests)
        assert not any(request.url.path == '/api/v1/shuns' for request in requests)
        with store._connection() as db:
            assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
    asyncio.run(scenario())
