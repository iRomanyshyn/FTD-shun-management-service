"""All rendered collections share bounded, canonical, deduplicated cache keys."""

from ipaddress import IPv4Address
from types import SimpleNamespace

from ftd_shun_manager.ip_presentation import displayed_ips


def test_collects_all_displayed_surfaces_without_duplicates_or_invalid_tokens():
    context = {'shuns': [{'ip': '8.8.8.8'}, {'ip': 'bad'}],
        'search_results': [{'ip': IPv4Address('1.1.1.1')}],
        'policy': {'entries': [{'ip': '9.9.9.9'}]},
        'recent_events': [{'ip': None}, {'ip': '8.8.4.4'}],
        'managed': {'entries': [{'ip': '8.8.8.8'}]},
        'draft': {'targets': [{'ip': '2.2.2.2'}], 'report_rows': [{'ip': '3.3.3.3'}]},
        'receipt': {'targets': [{'ip': '4.4.4.4'}]},
        'refresh': {'queue': {'items': [{'ip': '5.5.5.5'}], 'attention_items': [{'ip': '6.6.6.6'}]}}}
    assert displayed_ips(context, '7.7.7.7') == [
        '7.7.7.7', '8.8.8.8', '1.1.1.1', '8.8.4.4', '9.9.9.9',
        '2.2.2.2', '3.3.3.3', '4.4.4.4', '5.5.5.5', '6.6.6.6']


def test_preview_only_reads_displayed_page_not_large_source():
    class Preview:
        page_rows = (SimpleNamespace(ip=IPv4Address('8.8.8.8')),)

        @property
        def rows(self): raise AssertionError('Full parsed source must not be traversed')

        @property
        def ips(self): raise AssertionError('Full address set must not be traversed')

    assert displayed_ips({'preview': Preview()}) == ['8.8.8.8']


def test_whole_protected_list_is_bounded_but_not_limited_to_first_hundred():
    entries = [{'ip': str(IPv4Address(0x08000000 + i))} for i in range(1200)]
    assert len(displayed_ips({'policy': {'entries': entries}})) == 1000


def test_paginated_review_never_reads_hidden_authority_targets():
    class Review:
        @property
        def targets(self): raise AssertionError('Use displayed page_targets only')

    assert displayed_ips({'review': Review(), 'page_targets': [{'ip': '8.8.8.8'}]}) == ['8.8.8.8']


def test_protected_and_history_pages_read_the_same_existing_cache(tmp_path, monkeypatch):
    import json
    from contextlib import contextmanager
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from ftd_shun_manager import web
    from ftd_shun_manager.api import create_app
    from ftd_shun_manager.config import Settings
    from ftd_shun_manager.ip_context import ContextCache
    from ftd_shun_manager.rdap import registration
    from ftd_shun_manager.store import Device, Store

    store = Store(tmp_path / 'source.db')
    cache = ContextCache(tmp_path / 'context.db'); cache.initialize()
    settings = replace(Settings.from_environment(), database_path=store.path,
                       device_inventory_path=None, development_auth=True, agent_mode='disabled',
                       ip_context_cache_path=cache.path)
    app = create_app(settings, store)
    ip = IPv4Address('8.8.8.8')
    store.upsert_device(Device(1, 'synthetic', IPv4Address('192.0.2.1'), True), 'ssh-ed25519 AAAA')
    store.record_observed_shun(1, ip, 'outside')
    with store._connection() as db:
        db.execute('INSERT INTO protected_ips(ip,name,comment,enabled,updated_at) VALUES (?,?,?,?,?)',
                   (ip.packed, 'Synthetic office', '', 0, '2026-11-12T00:00:00Z'))
        before = tuple(db.iterdump())
    payload = registration({'objectClassName': 'ip network', 'ipVersion': 'v4',
        'startAddress': str(ip), 'endAddress': str(ip), 'country': 'UA', 'name': 'SYNTHETIC-CONTEXT'},
        ip, f'https://rdap.arin.net/registry/ip/{ip}')
    with cache.write() as db:
        db.execute('INSERT INTO contexts VALUES (?,?,1,?,?,?,?,?,NULL)',
                   (ip.packed, 'synthetic-occurrence', 'ready', '2026-11-12T00:00:00Z',
                    '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z', json.dumps(payload)))
    with TestClient(app) as api:
        @contextmanager
        def client(_settings): yield api

        monkeypatch.setattr(web, 'api_client', client)
        with TestClient(web.create_app(settings), base_url='https://test') as browser:
            for path in ('/protected-ips', '/history'):
                response = browser.get(path, headers={'X-Dev-User': 'synthetic', 'X-Dev-Groups': 'Administrator'})
                assert response.status_code == 200
                assert 'SYNTHETIC-CONTEXT' in response.text
                assert 'data-ip-link' in response.text
    with store._connection() as db:
        assert tuple(db.iterdump()) == before
