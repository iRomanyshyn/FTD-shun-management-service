"""Explicit configured-v7 API/client with fresh storage and local fake peers."""

import asyncio
import json
from dataclasses import replace
from ipaddress import IPv4Address
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest
from test_batch_additions import frames
from test_bulk_policy import dump
from test_bulk_preparation_api import ACTOR, PREFIX, proposal, stage
from test_continuous_dispatch import until
from test_dev_init import inventory as inventory_fixture
from test_session_completion_lookup import serve_many

from ftd_shun_manager import dev_init, web
from ftd_shun_manager.agent_client import UnixAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.deferred_dispatch import DeferredContinuousDispatcher
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.pending_execution import PendingExecution
from ftd_shun_manager.store import Store

inventory = inventory_fixture


@pytest.fixture
def configured(tmp_path, inventory):
    target = tmp_path / 'deferred.db'
    dev_init.initialize(target, inventory, profile='deferred-confirmation')
    settings = Settings(target, inventory, str(tmp_path / 'unused.sock'), '/synthetic/web.sock', '/synthetic/api.sock',
        'socket', 120, 300, 60, 366, 300, False, agent_cycles_enabled=True, large_snapshots_enabled=True,
        api_runtime='continuous-managed', batch_additions_enabled=True, batch_session_version=7,
        deferred_confirmation_enabled=True)
    return settings, Store(target)


@pytest.mark.parametrize('changes', [
    {'deferred_confirmation_enabled': False}, {'deferred_confirmation_enabled': 1},
    {'deferred_confirmation_enabled': 'true'}, {'batch_session_version': 6}, {'batch_session_version': True},
    {'batch_additions_enabled': False}, {'api_runtime': 'legacy'}, {'api_runtime': 'continuous-observation'},
    {'agent_mode': 'mock'}, {'development_auth': True}, {'agent_cycles_enabled': False},
    {'large_snapshots_enabled': False},
])
def test_deferred_requires_separate_exact_capability_and_matching_settings(configured, changes):
    settings, store = configured
    before = dump(store)
    with pytest.raises(ValueError): replace(settings, **changes)
    assert dump(store) == before


def test_environment_selection_is_explicit_and_canonical(monkeypatch):
    fields = {'FTD_SHUN_API_RUNTIME': 'continuous-managed', 'FTD_SHUN_AGENT_MODE': 'socket',
        'FTD_SHUN_AGENT_CYCLES_ENABLED': 'true', 'FTD_SHUN_LARGE_SNAPSHOTS_ENABLED': 'true',
        'FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED': 'true', 'FTD_SHUN_AGENT_BATCH_SESSION_VERSION': '7',
        'FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED': 'true', 'FTD_SHUN_DEVELOPMENT_AUTH': 'false'}
    for key, value in fields.items(): monkeypatch.setenv(key, value)
    assert Settings.from_environment().deferred_confirmation_enabled is True
    for value in ('True', '1', '', ' true', 'false'):
        monkeypatch.setenv('FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED', value)
        with pytest.raises(ValueError): Settings.from_environment()
    monkeypatch.delenv('FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED')
    with pytest.raises(ValueError): Settings.from_environment()


def test_exact_composition_does_not_initialize_connect_or_grant_work(configured, monkeypatch):
    settings, store = configured
    before = dump(store)

    def forbidden(*_args, **_kwargs): pytest.fail('Construction/GET may not initialize or contact an agent')
    for cls, method in ((Store, 'initialize'), (Store, 'upsert_device'), (OperationQueue, 'initialize'),
                        (PendingExecution, 'initialize_empty'), (UnixAgentClient, 'open_tracked_cycle'),
                        (UnixAgentClient, 'read_only_session_completed')):
        monkeypatch.setattr(cls, method, forbidden)
    app = create_app(settings)
    runtime = app.state.synchronizer
    assert type(runtime.dispatcher) is DeferredContinuousDispatcher
    agent = runtime.dispatcher.runner.agent
    assert type(agent) is UnixAgentClient and agent.deferred_confirmation and agent.batch_session_version == 7
    assert agent.addition_device_ids == frozenset({1})
    state = runtime.status()
    assert state['runtime_mode'] == 'continuous-managed' and state['deferred_confirmation_enabled'] is True
    assert not state['manual_mutations_available'] and state['bulk_execution_enabled']
    assert web.refresh_metadata(state)['deferred_confirmation_enabled'] is True
    assert dump(store) == before and runtime.dispatcher._task is None


def test_cli_preflight_reports_matching_deferred_choice_without_starting(configured, monkeypatch, capsys):
    from ftd_shun_manager import api

    settings, store = configured
    before = dump(store)
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    monkeypatch.setattr(api.uvicorn, 'run', lambda *_a, **_kw: pytest.fail('No serving in preflight'))
    monkeypatch.setattr(UnixAgentClient, 'open_tracked_cycle', lambda *_a: pytest.fail('No agent RPC in preflight'))
    api.main(['--check'])
    report = json.loads(capsys.readouterr().out)
    assert report['deferred_confirmation_enabled'] is True and report['batch_session_version'] == 7
    assert report['execution_started'] is False and report['migration_performed'] is False
    assert dump(store) == before


@pytest.mark.parametrize('fault', ['verified_storage', 'missing_file', 'missing_controls', 'disabled_flag', 'changed_transport'])
def test_mismatched_or_incomplete_profile_never_connects_or_repairs(configured, tmp_path, monkeypatch, fault):
    settings, store = configured
    monkeypatch.setattr(UnixAgentClient, 'open_tracked_cycle', lambda *_a: pytest.fail('No agent call'))
    if fault == 'verified_storage':
        target = tmp_path / 'verified.db'
        dev_init.initialize(target, settings.device_inventory_path)
        settings, store = replace(settings, database_path=target), Store(target)
    elif fault == 'missing_file':
        settings = replace(settings, database_path=tmp_path / 'absent.db')
    elif fault == 'missing_controls':
        with store._connection() as db:
            objects = db.execute("SELECT type,name FROM sqlite_master WHERE name GLOB 'managed_bulk_control*' ORDER BY type DESC").fetchall()
            for kind, name in objects:
                db.execute(f'DROP {kind} {name}')
    elif fault == 'disabled_flag':
        settings = replace(settings, deferred_confirmation_enabled=False, batch_session_version=6)
    before = dump(store)
    if fault == 'changed_transport':
        app = create_app(settings)
        app.state.synchronizer.dispatcher.runner.agent.deferred_confirmation = False

        async def scenario():
            with pytest.raises(ValueError, match='matching strict'):
                async with app.router.lifespan_context(app): pytest.fail('Changed transport started')
        asyncio.run(scenario())
    else:
        with pytest.raises((ValueError, QueueConflict)): create_app(settings)
    assert dump(store) == before
    if fault == 'missing_file': assert not settings.database_path.exists()


@pytest.mark.parametrize('changes', [{'deferred_confirmation': False}, {'deferred_confirmation': 1},
    {'batch_session_version': 6}, {'addition_device_ids': None}, {'addition_device_ids': frozenset()},
    {'addition_device_ids': frozenset({True})}, {'batch_additions': False}, {'recoverable_cycles': False}])
def test_high_level_client_refuses_implicit_or_unbounded_v7_selection(changes):
    fields = {'large_snapshots': True, 'additions_enabled': True, 'addition_device_ids': frozenset({1}),
        'settled_cycles': True, 'recoverable_cycles': True, 'tracked_cycles': True, 'batch_additions': True,
        'batch_session_version': 7, 'deferred_confirmation': True}
    with pytest.raises(ValueError): UnixAgentClient('/must-not-connect', **(fields | changes))


def test_real_api_import_over_local_binary_client_waits_then_confirms_without_creation(configured, tmp_path):
    settings, store = configured
    release, second, transcript = Event(), Event(), []
    ips = tuple(map(IPv4Address, ('198.51.100.251', '198.51.100.252')))

    def handler(connection, index):
        begin = connection.recv(100)
        assert begin[:4] == bytes([0x18, 7, 0, 1]) and len(begin) == 20
        assert UUID(bytes=begin[4:]).version == 4
        transcript.append(begin)
        if index == 1:
            second.set()
            assert release.wait(6)
        for frame in frames(0x18, 0, tuple((ip, 'management') for ip in ips) if index else (), version=7):
            connection.send(frame)
        if index == 0:
            for sequence, ip in enumerate(ips, 1):
                packet = connection.recv(100)
                assert packet == bytes([0x1a, 7, sequence]) + ip.packed
                transcript.append(packet)
                connection.send(bytes([5, 7, 0x1a, sequence]))
            assert connection.recv(100) == bytes([0x1d, 7, 3])
            connection.send(bytes([6, 7, 0x1d, 3, 2]) + b''.join(ip.packed for ip in ips))
            connection.send(bytes([0, 7, 0x18, 3]))
        else:
            assert connection.recv(100) == bytes([0x13, 7, 1])
            for frame in frames(0x13, 1, tuple((ip, 'management') for ip in ips), version=7): connection.send(frame)
            connection.send(bytes([0, 7, 0x18, 1]))
        assert connection.recv(100) == b''

    path, pool, server = serve_many(tmp_path, handler)
    app = create_app(replace(settings, agent_socket=path))
    runtime = app.state.synchronizer

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://internal') as client:
            saved = await stage(client, text='\n'.join(map(str, ips)))
            assert saved.status_code == 201, saved.text
            key = str(uuid4())
            proposed = (await proposal(client, saved.json(), key=key)).json()
            payload = {'actor': ACTOR, 'canonical': proposed['canonical'], 'digest': proposed['digest'],
                'accepted_count': 2, 'maintain_present': True, 'expected_suspended': False}
            response = await client.post(PREFIX + 'confirm-concurrent', json=payload, headers={'Idempotency-Key': key})
            assert response.status_code == 200, response.text
            async with app.router.lifespan_context(app):
                await until(second.is_set)
                state = (await client.get('/api/v1/status')).json()
                assert state['deferred_confirmation_enabled'] is True
                with store._connection() as db:
                    assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['AWAITING_CONFIRMATION'] * 2
                    assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
                release.set()
                await until(lambda: not runtime.dispatcher._active)
                with store._connection() as db:
                    assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['OBSERVED_PRESENT'] * 2
                    assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
                replay = await client.post(PREFIX + 'confirm-concurrent', json=payload, headers={'Idempotency-Key': key})
                assert replay.status_code == 200 and replay.json()['replayed']
                assert len(transcript) == 4  # Two bound BEGINs and two ADDs total.
    try:
        asyncio.run(scenario())
        server.result(6)
    finally:
        release.set()
        pool.shutdown(wait=True)
