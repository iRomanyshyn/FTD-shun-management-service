"""Deployable managed composition on disposable profiles and semantic fake RPCs."""

import asyncio
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from test_bulk_confirmation import prepare_review
from test_bulk_policy import dump
from test_bulk_preparation_api import ACTOR, PREFIX, proposal, stage
from test_continuous_dispatch import TracedAgent, until
from test_dev_init import fresh as fresh_fixture
from test_dev_init import inventory as inventory_fixture

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import UnixAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Store

inventory = inventory_fixture
fresh = fresh_fixture


@pytest.fixture
def configured(fresh):
    store, inventory = fresh
    settings = Settings(store.path, inventory, '/synthetic/agent.sock', '/synthetic/web.sock', '/synthetic/api.sock',
                        'socket', 120, 300, 60, 366, 300, False,
                        agent_cycles_enabled=True, large_snapshots_enabled=True, api_runtime='continuous-managed')
    return settings, store


def test_constructed_capabilities_are_exact_noncreating_and_do_not_connect(configured, monkeypatch):
    settings, store = configured
    before = dump(store)
    def forbidden(*_args, **_kwargs): pytest.fail('Construction must not initialize or connect')
    for component in (Store, OperationQueue): monkeypatch.setattr(component, 'initialize', forbidden)
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', forbidden)
    app = create_app(settings)
    runtime = app.state.synchronizer
    agent = runtime.dispatcher.runner.agent
    assert type(agent) is UnixAgentClient and agent.settled_cycles and agent.large_snapshots
    assert agent.additions_enabled and agent.addition_device_ids == frozenset({1})
    status = runtime.status()
    assert status['runtime_mode'] == 'continuous-managed' and status['bulk_execution_enabled']
    assert all(status[field] for field in ('bulk_policy_admission_enabled', 'bulk_policy_concurrent_enabled',
        'ready_removal_admission_enabled', 'ordered_removal_admission_enabled', 'ordered_removal_promotion_enabled'))
    assert status['manual_mutations_available'] is False  # No legacy admission fallback.
    assert dump(store) == before and runtime.dispatcher._task is None


@pytest.mark.parametrize('change', [
    {'agent_mode': 'mock'}, {'development_auth': True}, {'agent_cycles_enabled': False},
    {'large_snapshots_enabled': False}, {'device_inventory_path': None},
    {'import_execution_enabled': True}, {'managed_policy_admission_enabled': True},
    {'import_admission_enabled': True},
])
def test_incompatible_configuration_never_initializes_or_starts(configured, change):
    settings, store = configured
    before = dump(store)
    with pytest.raises((ValueError, QueueConflict)): create_app(replace(settings, **change))
    assert dump(store) == before


def test_explicit_profile_is_required_and_scope_drift_refuses_start(configured):
    settings, store = configured
    entries = json.loads(settings.device_inventory_path.read_text())
    entries[0].pop('addition_profile')
    settings.device_inventory_path.write_text(json.dumps(entries))
    before = dump(store)
    with pytest.raises(ValueError, match='profile'): create_app(settings)
    assert dump(store) == before


def test_real_configured_lifecycle_confirms_adds_restores_and_stops_without_replay(configured, monkeypatch):
    settings, store = configured
    fake = TracedAgent()
    offset = [0.0]
    monkeypatch.setattr(OperationQueue, '_now', lambda _self: datetime.now(UTC) + timedelta(seconds=offset[0]))
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', lambda _self, device: fake.open_cycle(device))
    app = create_app(settings)
    service = app.state.synchronizer.dispatcher
    service.clock = service.runner._clock = lambda: monotonic() + offset[0]

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://internal') as client:
            saved = await stage(client, text='198.51.100.253')
            assert saved.status_code == 201, saved.text
            key = str(uuid4())
            proposed = (await proposal(client, saved.json(), key=key)).json()
            payload = {'actor': ACTOR, 'canonical': proposed['canonical'], 'digest': proposed['digest'],
                       'accepted_count': 1, 'maintain_present': True, 'expected_suspended': False}
            headers = {'Idempotency-Key': key}
            confirmed = await client.post(PREFIX + 'confirm-concurrent', json=payload, headers=headers)
            assert confirmed.status_code == 200, confirmed.text
            assert not fake.writes
            async with app.router.lifespan_context(app):
                await until(lambda: len(fake.writes) == 1 and not service._active)
                assert service.status()['running'] and not fake.active
                fake.entries[1].clear()  # Simulated disappearance, not device I/O.
                offset[0] += 301
                service.signal_work()
                await until(lambda: len(fake.writes) == 2 and not service._active)
                assert len(fake.entries[1]) == 1
                replay = await client.post(PREFIX + 'confirm-concurrent', json=payload, headers=headers)
                assert replay.status_code == 200 and replay.json()['replayed']
                assert len(fake.writes) == 2
                with store._connection() as db:
                    assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['VERIFIED', 'VERIFIED']
                state = (await client.get('/api/v1/status')).json()
                protected = await client.post('/api/v1/protected-ips/198.51.100.253/add', json={
                    'actor': ACTOR, 'revision': 0, 'managed_revision': state['managed_policy_revision'], 'enabled': True})
                assert protected.status_code == 200, protected.text
                offset[0] += 61
                service.signal_work()
                await until(lambda: len(fake.removals) == 1 and not service._active)
                assert fake.entries[1] == []
                state = (await client.get('/api/v1/status')).json()
                unprotected = await client.post('/api/v1/protected-ips/198.51.100.253/delete', json={
                    'actor': ACTOR, 'revision': 1, 'managed_revision': state['managed_policy_revision'],
                    'confirm_ip': '198.51.100.253'})
                assert unprotected.status_code == 200, unprotected.text
                prior = len(fake.reads)
                offset[0] += 301
                service.signal_work()
                await until(lambda: len(fake.reads) > prior and not service._active)
                assert fake.entries[1] == [] and len(fake.writes) == 2
            assert not service.runner._service_active and not fake.active
            assert service._task is None and not service.maintenance.status()['running']
    asyncio.run(scenario())


def test_configured_bff_requires_its_own_mode_and_retains_csrf_and_consent(configured, monkeypatch):
    settings, store = configured
    app = create_app(settings)

    async def scenario():
        loop = asyncio.get_running_loop()
        def internal(request):
            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://internal') as client:
                    return await client.request(request.method, str(request.url), content=request.content, headers=request.headers)
            response = asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=20)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url='http://internal'))
        bff = web.create_app(settings)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(bff), base_url='https://fixture.test',
                headers={'Remote-User': 'alice', 'Remote-Groups': 'ftd-shun-operators'}) as client:
            _, page, fields = await prepare_review(client, text='198.51.100.253')
            assert 'type="submit" disabled' not in page.text
            before = dump(store)
            assert (await client.post('/managed-imports/v2/confirm', data=fields | {'csrf': 'bad'})).status_code == 403
            assert dump(store) == before
            response = await client.post('/managed-imports/v2/confirm', data=fields)
            assert response.status_code == 200, response.text[:500]
            with store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0] == 1
                assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
            page = await client.get('/managed-shuns')
            assert page.status_code == 200 and 'ready-removal-preparation' in page.text
            review = await client.post('/managed-shuns/v2/removal-review', data={
                'csrf': client.cookies.get('ftd_shun_csrf'), 'target': '1:198.51.100.253', 'reason': 'Synthetic cleanup'})
            assert review.status_code == 200, review.text[:500]
            token = re.search('name="review" value="([^"]+)"', review.text)[1]
            response = await client.post('/managed-shuns/v2/removal-confirm', data={
                'csrf': client.cookies.get('ftd_shun_csrf'), 'review': token, 'confirm_ip': '198.51.100.253'})
            assert response.status_code == 200, response.text[:500]
            with store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 0
                assert db.execute('SELECT action FROM operation_jobs').fetchone()[0] == 'REMOVE'
    asyncio.run(scenario())
