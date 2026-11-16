"""Actual BFF/API current-import browsing and existing per-IP actions; no device work."""

import asyncio
from ipaddress import IPv4Address

from test_bulk_policy import confirm, dump, prepare, retire
from test_ready_removal_web import bulk as bulk_fixture
from test_ready_removal_web import cancellation_controls as cancellation_fixture
from test_ready_removal_web import composition as composition_fixture
from test_ready_removal_web import dispatch as dispatch_fixture
from test_ready_removal_web import journal as journal_fixture
from test_ready_removal_web import leases as leases_fixture
from test_ready_removal_web import surface as surface_fixture
from test_ready_removal_web import waits as waits_fixture

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
surface = surface_fixture
waits = waits_fixture


def test_authenticated_import_page_uses_current_scope_and_existing_unblock_review(surface, bulk, composition):
    first = confirm(bulk, prepare(bulk)[1])['operation_id']
    second = confirm(bulk, prepare(bulk, '198.51.100.1\n198.51.100.2')[1])['operation_id']
    before = dump(bulk[0].store)

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _app, calls):
            root = f'/managed-imports/v2/imports/{second}'
            response = await client.get(root)
            assert response.status_code == 200
            assert '1 managed pairs' in response.text
            assert '/ip-actions/unblock' in response.text and 'name="target" value="1:198.51.100.2"' in response.text
            assert 'name="target" value="1:198.51.100.1"' not in response.text
            excluded = await client.get(root+'?scope=excluded')
            assert excluded.status_code == 200 and 'Already managed elsewhere' in excluded.text
            assert f'/managed-imports/v2/imports/{first}' in excluded.text
            assert '/ip-actions/unblock' not in excluded.text
            assert all(method == 'GET' for method, _path, _body in calls)
    asyncio.run(scenario())
    assert dump(bulk[0].store) == before and not composition[2].seen


def test_ip_and_managed_page_link_the_actual_owner(surface, bulk):
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    bulk[0].store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')

    async def scenario():
        async with surface(api_enabled=True, web_enabled=True) as (client, _app, calls):
            for path in ['/managed-shuns','/shuns/198.51.100.1']:
                result = await client.get(path)
                assert result.status_code == 200
                assert f'/managed-imports/v2/imports/{key}' in result.text
                assert '>Fixture</a>' in result.text
            assert all(method == 'GET' for method, _path, _body in calls)
    asyncio.run(scenario())


def test_stale_page_returns_html_conflict_and_never_rebases_a_scope(surface, bulk):
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    revision = bulk[0].policy_page()['revision']
    retire(bulk)

    async def scenario():
        async with surface() as (client, _app, calls):
            result = await client.get(f'/managed-imports/v2/imports/{key}?revision={revision}')
            assert result.status_code == 409 and 'text/html' in result.headers['content-type']
            assert 'Import ownership changed' in result.text
            assert f'href="/managed-imports/v2/imports/{key}"' in result.text
            assert all(method == 'GET' for method, _path, _body in calls)
    asyncio.run(scenario())
