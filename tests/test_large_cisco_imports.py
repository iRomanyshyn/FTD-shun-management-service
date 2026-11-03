"""Large source-address exports through real private BFF/API, disposable SQLite."""

import asyncio
import re
from datetime import timedelta
from ipaddress import IPv4Address

from test_bulk_policy import no_work
from test_bulk_preparation_api import bulk as bulk_fixture
from test_bulk_preparation_api import cancellation_controls as cancellation_fixture
from test_bulk_preparation_api import composition as composition_fixture
from test_bulk_preparation_api import dispatch as dispatch_fixture
from test_bulk_preparation_api import journal as journal_fixture
from test_bulk_preparation_api import leases as leases_fixture
from test_bulk_preparation_api import waits as waits_fixture
from test_bulk_preparation_web import WEB, stage, surface_for
from test_import_preparations import outside

from ftd_shun_manager.bulk_policy import BulkPolicies
from ftd_shun_manager.protected_policy import ProtectedPolicy

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


def export(count):
    return '\r\n'.join(f'shun (outside_907) {IPv4Address(0xC6120000 + i)} 0.0.0.0 0 0 0' for i in range(count))


def test_95081_line_export_bff_review_confirmation_restart_and_protection(composition, bulk, monkeypatch):
    policy, clock = bulk
    store, agent = composition[1:3]
    count = 95081
    source = export(count)
    ProtectedPolicy(store, initialize_queue=False).change('add', IPv4Address(0xC6120000),
        0, 'protector', 'Synthetic protector', (), managed_revision=0)
    before = outside(store)

    async def scenario():
        async with surface_for(composition, monkeypatch)(policy_api=True, policy_web=True,
                profile_ids=frozenset({1})) as (client, calls, _):
            response = await stage(client, text=source)
            assert response.status_code == 303, response.text[:500]
            location = response.headers['location']
            first = await client.get(location)
            last = await client.get(location + '?page=951')
            assert first.status_code == last.status_code == 200
            assert 'Page 951 of 951' in last.text
            assert str(IPv4Address(0xC6120000 + count - 1)) in last.text
            assert last.text.count('data-classification="PROPOSE_ADD"') == 81
            assert 'not imported' in first.text
            assert outside(store) == before
            review = await client.post(location + '/confirmation-review', data={'csrf': client.cookies.get('ftd_shun_csrf')})
            assert review.status_code == 200, review.text[:500]
            token = re.search(r'name="review" value="([^"]+)"', review.text)[1]
            saved = await client.post(WEB + '/confirm', data={'csrf': client.cookies.get('ftd_shun_csrf'),
                'review': token, 'accepted_count': str(count - 1), 'maintain_present': 'true'})
            assert saved.status_code == 200, saved.text[:500]
            assert any(path.endswith('/confirm') for _, path, _ in calls)
            with store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == count - 1
                assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE ip=?',
                                  (IPv4Address('0.0.0.0').packed,)).fetchone()[0] == 0
                assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 1
                key = db.execute('SELECT id FROM managed_bulk_manifests').fetchone()[0]
            return key

    key = asyncio.run(scenario())
    clock[0] += timedelta(minutes=11)
    assert policy.preparations.prune_expired() == 1
    restarted = BulkPolicies(store, clock=lambda: clock[0])
    last = restarted.page(key, 'alice', page=951)
    assert len(last['targets']) == 81  # Includes the original protected exclusion.
    assert restarted.policy_page(page=951)['total'] == count - 1
    no_work(restarted)
    assert not agent.seen and not composition[3]._wake.is_set()


def test_large_export_multiple_devices_refused_before_draft_creation(composition, monkeypatch):
    async def scenario():
        async with surface_for(composition, monkeypatch)() as (client, calls, _):
            response = await stage(client, text=export(50001), devices=('1', '2'))
            assert response.status_code == 422
            assert '100,002 pairs' in response.text and '100,000 device/IP pairs' in response.text
            assert not any(path.endswith('/prepare') for _, path, _ in calls)
            assert '198.18.0.0' in response.text
    asyncio.run(scenario())
    with composition[1]._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM import_preparation_plans').fetchone()[0] == 0
    assert not composition[2].seen
