"""Provider, lifecycle and presentation checks; all DNS answers are synthetic."""

import asyncio
import json
from ipaddress import IPv4Address
from types import SimpleNamespace

import dns.resolver
import pytest
from test_location_context import DAY, IP, value
from test_location_context import context as location_fixture

from ftd_shun_manager.cymru import PROFILE, SOURCE, CymruDNS, checked_context, origin
from ftd_shun_manager.cymru_context import CymruSupplement, combine
from ftd_shun_manager.ip_context import read_contexts
from ftd_shun_manager.web import templates

context = location_fixture


def route(ip=IP):
    return {'provider': PROFILE, 'source': SOURCE, 'network': str(ip) + '/32',
            'asns': [15169], 'organization': '<Cymru network>',
            'registration_country': 'DE', 'registry': 'arin', 'allocated_at': '1992-12-01'}


class Resolver:
    def __init__(self, answers):
        self.answers, self.calls, self.active, self.maximum = answers, [], 0, 0

    async def resolve(self, name, kind, **kwargs):
        assert kind == 'TXT' and kwargs == {'search': False, 'lifetime': 4}
        self.calls.append(name)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0)
            value = self.answers[name]
            if isinstance(value, BaseException): raise value
            return [SimpleNamespace(strings=(row.encode(),)) for row in value]
        finally:
            self.active -= 1


def test_dns_batches_deduplicate_as_names_select_specific_prefix_and_bound_parallelism():
    ips = [IPv4Address('8.8.8.' + str(n)) for n in range(1, 21)]
    responses = {f'{ip}.8.8.8.origin.asn.cymru.com.': ['15169 | 8.8.8.0/24 | US | arin | 1992-12-01',
                 '123 | 8.0.0.0/8 | US | arin | 1992-12-01'] for ip in range(1, 21)}
    responses['AS15169.asn.cymru.com.'] = ['15169 | US | arin | 2000-03-30 | <Network name>']
    resolver = Resolver(responses)
    result = CymruDNS(resolver).lookup_many(ips)
    assert set(result) == set(map(str, ips)) and len(resolver.calls) == 21
    assert resolver.maximum == 8 and resolver.active == 0
    assert all(info['asns'] == [15169] and info['organization'] == '<Network name>' and reason is None
               for info, reason in result.values())


def test_multiple_origin_asns_remain_explicit_and_wrong_name_binding_is_discarded():
    resolver = Resolver({'8.8.8.8.origin.asn.cymru.com.': ['123 456 | 8.8.8.0/24 | DE | arin | NA'],
        'AS123.asn.cymru.com.': ['123 | DE | arin | NA | First'],
        'AS456.asn.cymru.com.': ['999 | DE | arin | NA | Foreign']})
    info, reason = CymruDNS(resolver).lookup_many([IP])[str(IP)]
    assert info['asns'] == [123, 456] and info['organization'] == 'First' and reason == 'name_unavailable'
    result = combine({'state': 'unavailable'}, info | {'fetched_at': '2026-11-12T00:00:00Z', 'stale': False})
    assert result['asn'] is None and result['asns'] == [123, 456] and result['country'] is None


@pytest.mark.parametrize('answer,reason', [
    (dns.resolver.NXDOMAIN(), 'not_mapped'), (dns.resolver.NoAnswer(), 'not_mapped'),
    (dns.resolver.NoNameservers(), 'lookup_failed'), (['15169 | 1.1.1.0/24 | US | arin | NA'], 'lookup_failed'),
    (['bad'], 'lookup_failed'), (['15169 | 8.8.8.0/24 | US | arin | NA'] * 9, 'lookup_failed'),
])
def test_dns_failures_and_foreign_prefixes_never_become_ready(answer, reason):
    resolver = Resolver({'8.8.8.8.origin.asn.cymru.com.': answer})
    assert CymruDNS(resolver).lookup_many([IP]) == {str(IP): (None, reason)}
    assert len(resolver.calls) == 1


@pytest.mark.parametrize('ip', ['10.0.0.1', '127.0.0.1', '198.51.100.1', '169.254.1.1'])
def test_no_dns_for_special_use_or_invalid_batches(ip):
    resolver = Resolver({})
    with pytest.raises(ValueError): CymruDNS(resolver).lookup_many([IPv4Address(ip)])
    assert not resolver.calls


@pytest.mark.parametrize('change', [{'asns': [True]}, {'asns': [0]}, {'asns': [2, 1]},
    {'source': 'https://localhost/'}, {'network': '1.1.1.0/24'}, {'registration_country': 'de'},
    {'registry': 'unknown'}, {'allocated_at': '20260101'}, {'organization': 'x' * 97}, {'email': 'discard'}])
def test_cached_routing_payload_is_strict(change):
    with pytest.raises((ValueError, TypeError)): checked_context(route() | change, IP)
    assert origin('15169 | 8.8.8.0/24 | NA | NA | NA', IP)['registration_country'] is None


class Provider:
    def __init__(self): self.calls, self.failure, self.missing = [], False, False

    def lookup_many(self, ips):
        self.calls.append(ips)
        return {str(ip): (None, 'lookup_failed' if self.failure else 'not_mapped')
                if self.failure or self.missing else (route(ip), None) for ip in ips}


def setup(context, *, partial=False):
    store, cache, feed, local, clock = context
    local.missing = not partial
    if partial: local.lookup_many = lambda ips: {str(ip): value(ip) | {'asn': None, 'organization': None} for ip in ips}
    store.record_observed_shun(1, IP, 'outside')
    cache.scan(feed); cache.refresh_batch(local)
    supplement, provider = CymruSupplement(cache), Provider()
    supplement.initialize()
    return store, cache, feed, local, clock, supplement, provider


def test_backfill_restart_cooldown_ttl_and_views_do_not_mutate_or_query(context):
    store, cache, feed, _local, clock, supplement, provider = setup(context)
    with store._connection() as db: before = tuple(db.iterdump())
    assert supplement.refresh_batch(provider) == 1
    info = read_contexts(cache.path, [IP])[str(IP)]
    assert info['asn'] == 15169 and info['country'] is None and info['routing']['registration_country'] == 'DE'
    with cache.write() as db: saved = tuple(db.iterdump())
    for _ in range(3):
        read_contexts(cache.path, [IP]); cache.scan(feed)
        CymruSupplement(cache).initialize()
        assert supplement.refresh_batch(provider) == 0
    assert len(provider.calls) == 1
    with cache.write() as db: assert tuple(db.iterdump()) == saved
    clock[0] += 7 * DAY
    assert supplement.refresh_batch(provider) == 1
    with store._connection() as db: assert tuple(db.iterdump()) == before


def test_ipfire_fields_country_and_payload_are_preserved_and_conflicting_names_not_merged(context):
    _, cache, _, _local, _, supplement, provider = setup(context, partial=True)
    with cache.write() as db: before = db.execute('SELECT payload FROM contexts').fetchone()[0]
    assert supplement.refresh_batch(provider) == 1
    info = read_contexts(cache.path, [IP])[str(IP)]
    assert info['country'] == 'US' and info['provider'] == 'ipfire-location-v1'
    assert info['asn'] == 15169 and info['routing_fields'] == ['ASN', 'network name']
    with cache.write() as db: assert db.execute('SELECT payload FROM contexts').fetchone()[0] == before
    full = value() | {'state': 'ready'}
    combined = combine(full, route() | {'fetched_at': '2026-11-12T00:00:00Z'})
    assert all(combined[key] == full[key] for key in full) and combined['routing_fields'] == []
    conflicting = combine(full | {'asn': 123, 'organization': None}, route())
    assert conflicting['organization'] is None and conflicting['asn'] == 123


def test_failures_preserve_last_useful_context_and_persist_retry_schedule(context):
    _, cache, _, _, clock, supplement, provider = setup(context)
    supplement.refresh_batch(provider)
    before = read_contexts(cache.path, [IP])[str(IP)]
    clock[0] += 7 * DAY; provider.failure = True
    assert supplement.refresh_batch(provider) == 1
    after = read_contexts(cache.path, [IP])[str(IP)]
    assert after['asn'] == before['asn'] and after['fetched_at'] == before['fetched_at']
    assert after['routing']['stale'] is True
    clock[0] += 899; assert CymruSupplement(cache).refresh_batch(provider) == 0
    clock[0] += 1; provider.failure = False
    assert supplement.refresh_batch(provider) == 1


def test_no_queries_for_inactive_or_complete_ipfire_context_new_occurrence_gets_fresh_data(context):
    store, cache, feed, local, clock, supplement, provider = setup(context)
    supplement.refresh_batch(provider)
    store.reconcile_snapshot(1, []); cache.scan(feed); clock[0] += 60
    assert supplement.refresh_batch(provider) == 0
    store.record_observed_shun(1, IP, 'outside'); cache.scan(feed); cache.refresh_batch(local)
    assert 'routing' not in read_contexts(cache.path, [IP])[str(IP)]
    assert supplement.refresh_batch(provider) == 1
    local.missing = False; local.generation = 'b' * 64; cache.refresh_batch(local)
    clock[0] += 7 * DAY
    assert supplement.refresh_batch(provider) == 0


def test_interrupted_attempt_is_consumed_before_dns_and_backoff_survives_restart(context):
    _, cache, _, _, clock, supplement, provider = setup(context)
    def interrupted(ips): raise KeyboardInterrupt
    provider.lookup_many = interrupted
    with pytest.raises(KeyboardInterrupt): supplement.refresh_batch(provider)
    clock[0] += 60
    assert CymruSupplement(cache).refresh_batch(Provider()) == 0
    clock[0] += 840
    assert supplement.refresh_batch(Provider()) == 1


def test_foreign_occurrence_result_discarded_and_bad_supplement_does_not_hide_ipfire(context):
    store, cache, feed, _, _, supplement, provider = setup(context, partial=True)
    def disappeared(ips):
        store.reconcile_snapshot(1, []); cache.scan(feed)
        return {str(ip): (route(ip), None) for ip in ips}
    provider.lookup_many = disappeared
    assert supplement.refresh_batch(provider) == 0
    with cache.write() as db:
        db.execute('UPDATE cymru_entries SET payload=?,fetched_at=?', (json.dumps(route() | {'source': 'javascript:bad'}), '2026-11-12T00:00:00Z'))
    assert read_contexts(cache.path, [IP])[str(IP)]['provider'] == 'ipfire-location-v1'


def test_batches_are_bounded_and_duplicate_sightings_do_not_repeat_queries(context):
    store, cache, feed, local, clock, supplement, provider = setup(context)
    store.record_observed_shun(1, IP, 'inside')
    store.record_observed_shun(1, IPv4Address('1.1.1.1'), 'outside')
    cache.scan(feed); local.generation = 'c' * 64; cache.refresh_batch(local)
    assert supplement.refresh_batch(provider, limit=1) == 1
    assert supplement.refresh_batch(provider, limit=1) == 0
    clock[0] += 60
    assert supplement.refresh_batch(provider, limit=1) == 1
    assert {ip for batch in provider.calls for ip in batch} == {IP, IPv4Address('1.1.1.1')}
    assert sum(map(len, provider.calls)) == 2


def test_corrupt_recursive_supplement_keeps_valid_primary_metadata(context):
    _, cache, _, _, _, supplement, provider = setup(context, partial=True)
    supplement.refresh_batch(provider)
    with cache.write() as db:
        db.execute('UPDATE cymru_entries SET payload=?', ('[' * 1000 + '0' + ']' * 1000,))
    info = read_contexts(cache.path, [IP])[str(IP)]
    assert info['country'] == 'US' and info['provider'] == 'ipfire-location-v1' and 'routing' not in info


def test_invalid_batch_result_never_publishes_foreign_data(context):
    _, cache, _, _, _, supplement, provider = setup(context)
    provider.lookup_many = lambda ips: {str(IP): (route(IPv4Address('1.1.1.1')), None)}
    assert supplement.refresh_batch(provider) == 1
    assert read_contexts(cache.path, [IP])[str(IP)]['state'] == 'unavailable'
    with cache.write() as db:
        assert db.execute('SELECT reason FROM cymru_entries').fetchone()[0] == 'lookup_failed'


def test_templates_show_distinct_routing_attribution_country_and_escaped_name(context):
    _, cache, _, _, _, supplement, provider = setup(context, partial=True)
    supplement.refresh_batch(provider)
    contexts = read_contexts(cache.path, [IP])
    module = templates.env.get_template('ip-context.html').module
    card, inline = str(module.card(str(IP), contexts)), str(module.inline(str(IP), contexts))
    assert 'Team Cymru DNS' in card and 'DE (registry data, not geolocation)' in card
    assert 'Country:' in card and '>US</span>' in card and 'https://www.ipfire.org/location/lookup/8.8.8.8' in card
    assert '<Cymru network>' not in card and '&lt;Cymru network&gt;' in card
    assert 'AS15169' in inline and '· Cymru' in inline
    footer = templates.env.get_template('base.html').render(identity=None, ip_context_location=True, ip_context_cymru=True)
    assert SOURCE in footer and 'CC BY-SA' in footer
