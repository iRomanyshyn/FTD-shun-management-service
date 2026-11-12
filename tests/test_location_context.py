"""Local bulk enrichment, refresh scheduling and signed-update failure handling."""

import json
import lzma
import subprocess
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager.ip_context import ContextCache, read_contexts
from ftd_shun_manager.location_context import (
    DAY,
    DOWNLOAD,
    PROFILE,
    SOURCE,
    LocationCache,
    LocationDataset,
    checked_context,
)
from ftd_shun_manager.observation_feed import snapshot
from ftd_shun_manager.store import Device, Store

IP = IPv4Address('8.8.8.8')


class Feed:
    def __init__(self, store): self.store = store

    def read(self, cursor, source):
        return snapshot(self.store.path, *(cursor or [0, None]), source)


def value(ip=IP, generation='a' * 64):
    return {'country': 'US', 'network': str(ip) + '/32', 'organization': '<Example AS>',
            'asn': 15169, 'source': SOURCE, 'registry': 'IPFire Location', 'provider': PROFILE,
            'dataset': generation, 'database_at': '2026-11-11T00:00:00Z',
            'range_start': str(ip), 'range_end': str(ip)}


class Provider:
    generation, database_at = 'a' * 64, '2026-11-11T00:00:00Z'

    def __init__(self): self.batches, self.failure, self.missing = [], False, False

    def lookup_many(self, ips):
        self.batches.append(ips)
        if self.failure: raise ValueError('Native lookup failed')
        return {str(ip): None if self.missing else value(ip, self.generation) for ip in ips}


@pytest.fixture
def context(tmp_path):
    store = Store(tmp_path / 'source.db'); store.initialize()
    store.upsert_device(Device(1, 'local-fixture', IPv4Address('192.0.2.1'), True), 'ssh-ed25519 AAAA')
    clock = [1760000000.0]
    cache = LocationCache(tmp_path / 'location-cache.db', lambda: clock[0]); cache.initialize()
    yield store, cache, Feed(store), Provider(), clock
    cache.close()


def test_baseline_backfills_all_existing_in_bounded_local_batches_without_source_changes(context):
    store, cache, feed, provider, _ = context
    ips = [IPv4Address(f'8.8.8.{i}') for i in range(1, 24)]
    for ip in ips: store.record_observed_shun(1, ip, 'outside')
    with store._connection() as db: before = tuple(db.iterdump())
    cache.scan(feed)
    assert cache.refresh_batch(provider, limit=10) == 10
    assert cache.refresh_batch(provider, limit=10) == 10
    assert cache.refresh_batch(provider, limit=10) == 3
    assert cache.refresh_batch(provider, limit=10) == 0
    assert len(read_contexts(cache.path, ips)) == len(ips)
    assert [len(batch) for batch in provider.batches] == [10, 10, 3]
    with store._connection() as db: assert tuple(db.iterdump()) == before


def test_new_detection_restart_views_ttl_and_new_dataset(context):
    store, cache, feed, provider, clock = context
    cache.scan(feed)
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    assert cache.refresh_batch(provider) == 1
    cache.initialize()
    for _ in range(4):
        cache.scan(feed); read_contexts(cache.path, [IP])
        assert cache.refresh_batch(provider) == 0
    clock[0] += 7 * DAY - 1
    assert cache.refresh_batch(provider) == 0
    clock[0] += 1
    assert cache.refresh_batch(provider) == 1
    provider.generation = 'b' * 64
    assert cache.refresh_batch(provider) == 1
    assert read_contexts(cache.path, [IP])[str(IP)]['dataset'] == provider.generation
    assert cache.refresh_batch(provider) == 0


def test_new_occurrence_refreshes_but_inactive_addresses_do_not(context):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.refresh_batch(provider)
    store.reconcile_snapshot(1, []); cache.scan(feed)
    provider.generation = 'b' * 64
    assert cache.refresh_batch(provider) == 0
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    assert cache.refresh_batch(provider) == 1


def test_missing_context_retries_on_dataset_or_interval_not_every_scan(context):
    store, cache, feed, provider, clock = context
    provider.missing = True
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    assert cache.refresh_batch(provider) == 1
    assert read_contexts(cache.path, [IP])[str(IP)]['state'] == 'unavailable'
    for _ in range(5): assert cache.refresh_batch(provider) == 0
    provider.missing = False; provider.generation = 'b' * 64
    assert cache.refresh_batch(provider) == 1
    clock[0] += DAY
    assert cache.refresh_batch(provider, refresh_seconds=DAY) == 0  # existing deadline is not shortened
    clock[0] += 6 * DAY
    assert cache.refresh_batch(provider, refresh_seconds=DAY) == 1


def test_local_failure_preserves_last_good_and_retries_with_backoff(context):
    store, cache, feed, provider, clock = context
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.refresh_batch(provider)
    before = read_contexts(cache.path, [IP])
    provider.generation = 'b' * 64; provider.failure = True
    assert cache.refresh_batch(provider) == 0
    assert read_contexts(cache.path, [IP]) == before
    assert cache.refresh_batch(provider) == 0 and len(provider.batches) == 2
    clock[0] += 900; provider.failure = False
    assert cache.refresh_batch(provider) == 1


def test_initial_failure_and_partial_results_do_not_loop_or_invent_success(context):
    store, cache, feed, provider, clock = context
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    provider.lookup_many = lambda ips: {}
    assert cache.refresh_batch(provider) == 0
    assert read_contexts(cache.path, [IP])[str(IP)]['state'] == 'unavailable'
    assert cache.refresh_batch(provider) == 0
    clock[0] += 900
    provider.lookup_many = lambda ips: {str(ip): value(ip) for ip in ips}
    assert cache.refresh_batch(provider) == 1


def test_native_result_cannot_overwrite_a_disappeared_or_replaced_occurrence(context):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed)
    def changed(ips):
        store.reconcile_snapshot(1, []); cache.scan(feed)
        return {str(ip): value(ip) for ip in ips}
    provider.lookup_many = changed
    assert cache.refresh_batch(provider) == 0
    assert read_contexts(cache.path, [IP])[str(IP)]['state'] != 'ready'


def test_special_use_skipped_and_old_rdap_cache_is_retained(context, tmp_path):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IPv4Address('198.51.100.250'), 'outside'); cache.scan(feed)
    assert cache.refresh_batch(provider) == 0 and not provider.batches
    old = ContextCache(tmp_path / 'rdap.db'); old.initialize()
    before = old.path.read_bytes()
    with pytest.raises(ValueError, match='separate location cache'):
        LocationCache(old.path).initialize()
    assert old.path.read_bytes() == before


@pytest.mark.parametrize('fault', ['country', 'asn', 'source', 'network', 'organization', 'dataset', 'database_at', 'extra'])
def test_display_revalidates_local_payload(context, fault):
    store, cache, feed, provider, _ = context
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.refresh_batch(provider)
    bad = value()
    bad.update({'country': {'country': '<>'}, 'asn': {'asn': True}, 'source': {'source': 'http://localhost/'},
        'network': {'network': '1.1.1.0/24'}, 'organization': {'organization': 'x' * 97},
        'dataset': {'dataset': 'wrong'}, 'database_at': {'database_at': 'badZ'},
        'extra': {'email': 'not retained'}}[fault])
    with pytest.raises((ValueError, TypeError)): checked_context(bad, IP)
    with cache.write() as db: db.execute('UPDATE contexts SET payload=?', (json.dumps(bad),))
    assert read_contexts(cache.path, [IP]) == {}


def compressed_client(content, status=200):
    def request(request):
        assert str(request.url) == DOWNLOAD
        return httpx.Response(status, content=content)
    return httpx.Client(transport=httpx.MockTransport(request))


def test_signed_update_is_atomic_and_verification_precedes_replacement(tmp_path, monkeypatch):
    import ftd_shun_manager.location_context as module
    path = tmp_path / 'location.db'; path.write_bytes(b'old verified')
    dataset = LocationDataset(path); dataset.generation = 'a' * 64
    seen = []
    def verify(candidate):
        assert path.read_bytes() == b'old verified'
        assert candidate.read_bytes() == b'new signed dataset'
        seen.append(candidate)
    monkeypatch.setattr(module, 'verify', verify)
    monkeypatch.setattr(module, 'native_read', lambda p, ips: {'created_at': 1760000000, 'rows': {}})
    with compressed_client(lzma.compress(b'new signed dataset')) as client: dataset.update(client=client)
    assert len(seen) == 1 and path.read_bytes() == b'new signed dataset'
    assert dataset.generation != 'a' * 64 and not list(tmp_path.glob('.location-*'))


@pytest.mark.parametrize('failure', ['signature', 'truncated', 'garbage', 'redirect', 'native'])
def test_bad_download_keeps_last_verified_dataset(tmp_path, monkeypatch, failure):
    import ftd_shun_manager.location_context as module
    path = tmp_path / 'location.db'; path.write_bytes(b'last verified')
    dataset = LocationDataset(path); dataset.generation = 'a' * 64
    def verify(candidate):
        if failure == 'signature': raise subprocess.CalledProcessError(1, 'location verify')
    monkeypatch.setattr(module, 'verify', verify)
    def native(*_): raise ValueError('Invalid native file')
    monkeypatch.setattr(module, 'native_read', native)
    content = lzma.compress(b'candidate')
    if failure == 'truncated': content = content[:-8]
    if failure == 'garbage': content += b'extra'
    with (compressed_client(content, 302 if failure == 'redirect' else 200) as client,
          pytest.raises((ValueError, lzma.LZMAError, EOFError, httpx.HTTPError, subprocess.SubprocessError))):
        dataset.update(client=client)
    assert path.read_bytes() == b'last verified' and dataset.generation == 'a' * 64
    assert not list(tmp_path.glob('.location-*'))


def test_native_bridge_checks_complete_result_and_no_per_ip_process(tmp_path, monkeypatch):
    import ftd_shun_manager.location_context as module
    calls = []
    def run(args, **kwargs):
        calls.append((args, json.loads(kwargs['input'])))
        return subprocess.CompletedProcess(args, 0, json.dumps({'created_at': 1760000000,
            'rows': {str(IP): {'country': 'US', 'prefix': '8.8.8.0/24', 'asn': 15169, 'organization': 'Google'}}}))
    monkeypatch.setattr(module.subprocess, 'run', run)
    dataset = LocationDataset(tmp_path / 'signed.db'); dataset.generation = 'a' * 64
    dataset.database_at = '2026-11-11T00:00:00Z'
    assert dataset.lookup_many([IP])[str(IP)]['asn'] == 15169
    assert len(calls) == 1 and calls[0][0][0] == '/usr/bin/python3'
    assert calls[0][1]['ips'] == [str(IP)]
