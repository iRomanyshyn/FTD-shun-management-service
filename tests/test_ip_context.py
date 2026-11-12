"""Advisory occurrence/cache isolation; synthetic SQLite and HTTP only."""

import json
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager.ip_context import ContextCache, cache_revision, read_contexts
from ftd_shun_manager.observation_feed import create_app, snapshot
from ftd_shun_manager.rdap import BOOTSTRAP, LookupUnavailable, RdapClient, registration, services
from ftd_shun_manager.store import Device, Store

IP = IPv4Address('8.8.8.8')
BOOT = {'services': [[['8.0.0.0/8'], ['https://rdap.arin.net/registry/']]]}


def result(ip=IP):
    return {'objectClassName': 'ip network', 'ipVersion': 'v4', 'startAddress': str(ip), 'endAddress': str(ip),
            'country': 'US', 'name': '<network>', 'entities': [{'roles': ['registrant'], 'vcardArray': ['vcard', [
                ['kind', {}, 'text', 'org'], ['fn', {}, 'text', '<Registry Company>'],
                ['email', {}, 'text', 'private-contact@example.invalid']]]}]}


class Feed:
    def __init__(self, store): self.store = store

    def read(self, cursor, source):
        return snapshot(self.store.path, *(cursor or [0, None]), source)


class Provider:
    def __init__(self): self.seen, self.failure = [], None

    def lookup(self, ip, bootstrap):
        self.seen.append(ip)
        if self.failure: raise self.failure
        return registration(result(ip), ip, 'https://rdap.arin.net/registry/ip/' + str(ip)), BOOT


@pytest.fixture
def context(tmp_path):
    store = Store(tmp_path / 'source.db')
    store.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f'fixture-{device}', IPv4Address(f'192.0.2.{device}'), True), 'ssh-ed25519 AAAA')
    clock = [1760000000.0]
    cache = ContextCache(tmp_path / 'cache.db', lambda: clock[0])
    cache.initialize()
    yield store, cache, Feed(store), Provider(), clock
    cache.close()


def state(cache, ip=IP):
    with cache.write() as db:
        row = db.execute('SELECT * FROM contexts WHERE ip=?', (ip.packed,)).fetchone()
        return dict(row) if row else None


def test_no_backfill_or_lookup_on_first_baseline_and_readers_never_create_files(context, tmp_path):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed)
    assert state(cache)['state'] == 'not_requested'
    assert cache.lookup_one(provider) is False and not provider.seen
    assert read_contexts(tmp_path / 'absent.db', [str(IP)]) == {}
    assert not (tmp_path / 'absent.db').exists()


def test_one_attempt_per_global_occurrence_reused_across_devices_views_and_restart(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed)
    original = state(cache)['occurrence']
    assert cache.lookup_one(provider) is True
    for _ in range(3):
        cache.scan(feed)
        assert cache.lookup_one(provider) is False
        assert read_contexts(cache.path, [str(IP)])[str(IP)]['organization'] == '<Registry Company>'
    # The entire overlap transition occurs between scans. There is no fresh
    # attempt merely because the old device/interface is gone by the next scan.
    store.record_observed_shun(2, IP, 'dmz')
    store.reconcile_snapshot(1, [])
    cache.scan(feed)
    assert state(cache)['occurrence'] == original and state(cache)['active'] == 1
    cache.close()
    cache.initialize()
    clock[0] += 100
    cache.scan(feed)
    assert cache.lookup_one(provider) is False and provider.seen == [IP]
    store.reconcile_snapshot(2, [])
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed)
    assert state(cache)['occurrence'] != original
    assert cache.lookup_one(provider) is True and provider.seen == [IP, IP]


def test_verified_removal_then_redetection_allows_new_attempt(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed); cache.lookup_one(provider)
    store.complete_removal(1, IP, 'fixture', 'Fixture', (), 'fixture-request')
    cache.scan(feed)
    assert state(cache)['active'] == 0
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed)
    clock[0] += 2
    assert cache.lookup_one(provider) and len(provider.seen) == 2


def test_source_gap_keeps_active_context_and_never_authorizes_backfill(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed); cache.lookup_one(provider)
    original = state(cache)['occurrence']
    with store._connection() as db: db.execute('DELETE FROM shun_events')
    cache.scan(feed)
    clock[0] += 100
    assert cache.lookup_one(provider) is False
    assert state(cache)['occurrence'] == original and provider.seen == [IP]
    with pytest.raises(ValueError): cache.scan(feed, prime_count=1)


def test_explicit_bounded_first_sample_and_source_data_unchanged(context):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IP, 'outside')
    with store._connection() as db: before = tuple(db.iterdump())
    cache.scan(feed, prime_count=1)
    assert cache.lookup_one(provider) is True
    with store._connection() as db: assert tuple(db.iterdump()) == before
    with pytest.raises(ValueError): cache.scan(feed, prime_count=1)


def test_failure_is_consumed_and_throttling_delays_other_ips(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed)
    provider.failure = LookupUnavailable('throttled', 300)
    cache.lookup_one(provider)
    assert state(cache)['state'] == 'unavailable'
    other = IPv4Address('8.8.4.4')
    store.record_observed_shun(1, other, 'outside'); cache.scan(feed)
    assert cache.lookup_one(provider) is False
    clock[0] += 301
    provider.failure = None
    assert cache.lookup_one(provider) is True and provider.seen == [IP, other]
    clock[0] += 1000
    assert cache.lookup_one(provider) is False


def test_interrupted_attempt_stays_consumed_on_restart(context):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    with cache.write() as db: db.execute("UPDATE contexts SET state='looking_up'")
    cache.close(); cache.initialize()
    assert state(cache)['state'] == 'unavailable' and state(cache)['reason'] == 'interrupted'
    assert cache.lookup_one(provider) is False and not provider.seen


@pytest.mark.parametrize('ip', ['192.0.2.1', '198.51.100.1', '203.0.113.1', '10.0.0.1', '127.0.0.1', '224.0.0.1'])
def test_private_documentation_and_special_use_addresses_never_lookup(context, ip):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IPv4Address(ip), 'outside'); cache.scan(feed)
    assert cache.lookup_one(provider) is False and not provider.seen


def test_cache_corruption_is_unavailable_not_a_web_failure(context):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.lookup_one(provider)
    revision = cache_revision(cache.path)
    assert revision > 0
    with cache.write() as db: db.execute("UPDATE contexts SET payload='[]'")
    assert read_contexts(cache.path, [str(IP)]) == {}
    assert read_contexts(cache.path, [str(IP)], with_revision=True) == ({}, revision)
    assert read_contexts(cache.path, [], with_revision=True) == ({}, revision)
    assert cache_revision(store.path) == 0


def test_actual_rdap_bootstrap_longest_prefix_registration_and_no_contacts():
    requests = []

    def http(request):
        requests.append(str(request.url))
        if str(request.url) == BOOTSTRAP:
            return httpx.Response(200, json={'services': BOOT['services'] + [[['8.8.8.0/24'], ['https://rdap.db.ripe.net/']]]})
        assert str(request.url) == 'https://rdap.db.ripe.net/ip/8.8.8.8'
        return httpx.Response(200, json=result())

    provider = RdapClient(client=httpx.Client(transport=httpx.MockTransport(http)))
    value, bootstrap = provider.lookup(IP)
    assert len(requests) == 2 and value['country'] == 'US' and value['registry'] == 'RIPE NCC'
    assert value['organization'] == '<Registry Company>' and 'contact' not in json.dumps(value)
    provider.lookup(IP, bootstrap)
    assert len(requests) == 3  # Reused registry bootstrap, not a second discovery request.


@pytest.mark.parametrize('url', ['http://rdap.arin.net/registry/', 'https://127.0.0.1/',
    'https://rdap.arin.net@127.0.0.1/', 'https://rdap.arin.net:8443/registry/',
    'https://rdap.arin.net/private/', 'https://rdap.arin.net/registry/?key=secret'])
def test_bootstrap_never_grants_arbitrary_network_destinations(url):
    with pytest.raises(LookupUnavailable): services({'services': [[['8.0.0.0/8'], [url]]]})


@pytest.mark.parametrize('fault', ['foreign_ip', 'ipv6', 'non_json', 'oversized', 'gzip', 'throttled', 'external_referral', 'redirect_loop'])
def test_bad_or_throttled_registry_responses_are_bounded_unavailable(fault):
    seen = []

    def http(request):
        seen.append(str(request.url))
        if fault == 'non_json': return httpx.Response(200, text='not json', headers={'Content-Type': 'text/html'})
        if fault == 'oversized': return httpx.Response(200, content=b' ' * (512*1024+1), headers={'Content-Type': 'application/json'})
        if fault == 'gzip': return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=httpx.ByteStream(b''))
        if fault == 'throttled': return httpx.Response(429, headers={'Retry-After': '120'})
        if fault in ('external_referral', 'redirect_loop'):
            return httpx.Response(302, headers={'Location': 'https://127.0.0.1/private' if fault == 'external_referral' else str(request.url)})
        value = result()
        if fault == 'foreign_ip': value['startAddress'] = value['endAddress'] = '1.1.1.1'
        elif fault == 'ipv6': value['ipVersion'] = 'v6'
        return httpx.Response(200, json=value)

    provider = RdapClient(client=httpx.Client(transport=httpx.MockTransport(http)))
    with pytest.raises(LookupUnavailable): provider.lookup(IP, BOOT)
    assert len(seen) <= 3


def test_feed_has_no_mutation_or_arbitrary_sql_routes(context):
    import asyncio

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(context[0].path)), base_url='http://feed') as client:
            assert (await client.get('/observations')).status_code == 200
            assert (await client.post('/observations', json={'sql': 'DELETE FROM shun_state'})).status_code == 405
            assert (await client.get('/api/v1/status')).status_code == 404
            assert (await client.get('/observations?rowid=-1')).status_code == 422
            assert (await client.get('/docs')).status_code == 404
    asyncio.run(scenario())


def test_pending_removed_before_lookup_does_not_claim_to_be_waiting(context):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside')
    store.reconcile_snapshot(1, [])
    cache.scan(feed)
    assert state(cache)['active'] == 0 and state(cache)['state'] == 'not_requested'
    assert cache.lookup_one(provider) is False and not provider.seen


def test_worker_refuses_original_database_as_a_cache(context):
    store = context[0]
    with store._connection() as db: before = tuple(db.iterdump())
    with pytest.raises(ValueError): ContextCache(store.path).initialize()
    with store._connection() as db: assert tuple(db.iterdump()) == before


def test_cleanly_stopped_worker_leaves_a_plain_readable_cache(context):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.lookup_one(provider)
    cache.close()
    import sqlite3

    with sqlite3.connect(cache.path) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    assert read_contexts(cache.path, [str(IP)])[str(IP)]['state'] == 'ready'


def test_web_batch_is_bounded_and_cannot_trigger_provider_work(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    ips = [IPv4Address(f'8.8.8.{i}') for i in range(1, 106)]
    for ip in ips: store.record_observed_shun(1, ip, 'outside')
    cache.scan(feed)
    for _ in ips:
        cache.lookup_one(provider)
        clock[0] += 3
    before = len(provider.seen)
    values = read_contexts(cache.path, ips)
    assert len(values) == 100 and len(provider.seen) == before


@pytest.mark.parametrize('fault', ['country', 'source', 'registry', 'extra', 'oversized'])
def test_untrusted_cached_display_data_cannot_redirect_or_break_web(context, fault):
    store, cache, feed, provider, _ = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.lookup_one(provider)
    with cache.write() as db:
        raw = json.loads(db.execute('SELECT payload FROM contexts').fetchone()[0])
        if fault == 'country': raw['country'] = '<>'
        elif fault == 'source': raw['source'] = 'http://127.0.0.1/private'
        elif fault == 'registry': raw['registry'] = 'Wrong registry'
        elif fault == 'extra': raw['contacts'] = ['not retained']
        else:
            db.execute('PRAGMA ignore_check_constraints=ON')  # Simulated externally corrupted advisory file.
            raw['organization'] = 'x' * 4096
        db.execute('UPDATE contexts SET payload=?', (json.dumps(raw),))
    assert read_contexts(cache.path, [str(IP)], with_revision=True) == ({}, cache_revision(cache.path))
