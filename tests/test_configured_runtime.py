"""Configured entrypoint on disposable retained profiles; no lab or socket I/O."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from test_bulk_policy import dump
from test_continuous_api import bulk as bulk_fixture
from test_continuous_api import cancellation_controls as cancellation_fixture
from test_continuous_api import composition as composition_fixture
from test_continuous_api import dispatch as dispatch_fixture
from test_continuous_api import journal as journal_fixture
from test_continuous_api import leases as leases_fixture
from test_continuous_api import waits as waits_fixture
from test_continuous_dispatch import idle

from ftd_shun_manager import api
from ftd_shun_manager.agent_client import UnixAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.config import Settings
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def configured(composition, tmp_path):
    settings, store, fake, _service = composition
    entries = [{'id': device.id, 'hostname': device.hostname, 'management_ip': str(device.management_ip),
                'ssh_host_key': 'ssh-ed25519 AAAA', 'enabled': device.enabled,
                'allowed_interfaces': ['management', 'outside']} for device in store.list_devices()]
    path = tmp_path / 'public.json'
    path.write_text(json.dumps(entries))
    return replace(settings, device_inventory_path=path, api_runtime='continuous-observation', agent_concurrency=2), store, fake, entries


def forbid_initialization(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Configured composition must not initialize, import environment policy or connect.')
    monkeypatch.setattr(Store, 'initialize', forbidden)
    monkeypatch.setattr(Store, 'upsert_device', forbidden)
    monkeypatch.setattr(OperationQueue, 'initialize', forbidden)
    monkeypatch.setattr(ProtectedPolicy, 'migrate_legacy_environment', forbidden)
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', forbidden)
    monkeypatch.setenv('FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS', 'must-not-be-read')


def test_configured_construction_and_status_do_not_initialize_connect_or_enable_capabilities(configured, monkeypatch):
    settings, store, fake, _entries = configured
    before = dump(store)
    forbid_initialization(monkeypatch)
    app = create_app(settings, store)
    runtime = app.state.synchronizer
    agent = runtime.dispatcher.runner.agent
    assert type(agent) is UnixAgentClient
    assert agent.large_snapshots and agent.settled_cycles and not agent.additions_enabled
    assert agent.recoverable_cycles is True
    assert agent.addition_device_ids == frozenset() and agent.timeout_seconds == 125
    assert runtime.dispatcher.runner.agent_concurrency == 2

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://internal') as client:
            status = (await client.get('/api/v1/status')).json()
            assert status['runtime_mode'] == 'continuous-observation'
            assert status['bulk_policy_admission_enabled'] is False
            assert status['ordered_removal_admission_enabled'] is False
            assert status['ready_removal_admission_enabled'] is False
            assert status['ordered_removal_promotion_enabled'] is False
            assert (await client.post('/api/v1/refresh-hint')).status_code == 503
    asyncio.run(scenario())
    assert dump(store) == before and not fake.seen


@pytest.mark.parametrize('change', [
    {'device_inventory_path': None}, {'agent_mode': 'mock'}, {'agent_mode': 'disabled'},
    {'agent_cycles_enabled': False}, {'large_snapshots_enabled': False}, {'development_auth': True},
    {'import_admission_enabled': True}, {'import_execution_enabled': True},
    {'managed_policy_admission_enabled': True}, {'managed_restoration_enabled': True, 'import_execution_enabled': True},
    {'managed_removal_worker_enabled': True}, {'agent_concurrency': 1},
])
def test_bad_configuration_fails_closed_without_change(configured, change, monkeypatch):
    settings, store, _fake, _entries = configured
    before = dump(store)
    forbid_initialization(monkeypatch)
    with pytest.raises((ValueError, QueueConflict)):
        create_app(replace(settings, **change), store)
    assert dump(store) == before


def test_configured_mode_cannot_adopt_an_injected_owner_or_client(configured, composition):
    settings, store, fake, _entries = configured
    for kwargs in [{'agent_client': fake}, {'continuous_dispatcher': composition[3]}]:
        before = dump(store)
        with pytest.raises(ValueError, match='mixed'):
            create_app(settings, store, **kwargs)
        assert dump(store) == before


@pytest.mark.parametrize('damage', ['absent', 'base_only', 'partial', 'legacy', 'marker'])
def test_missing_or_incompatible_profile_never_migrates(configured, tmp_path, damage, monkeypatch):
    settings, store, _fake, _entries = configured
    if damage in {'absent', 'base_only', 'legacy'}:
        store = Store(tmp_path / damage / 'state.db')
        if damage != 'absent':
            store.initialize()
            OperationQueue(store).initialize()
        if damage == 'legacy':
            from ftd_shun_manager.managed_shuns import ManagedShuns
            ManagedShuns(store).initialize()
        settings = replace(settings, database_path=store.path)
    elif damage == 'partial':
        with store._connection() as db:
            db.execute('DROP INDEX idx_managed_bulk_attempt_pair')
    else:
        with store._connection() as db:
            db.execute('UPDATE protected_policy SET legacy_imported=0')
    before = dump(store) if store.path.exists() else None
    forbid_initialization(monkeypatch)
    with pytest.raises((ValueError, BulkUnavailable)):
        create_app(settings, store)
    if before is None:
        assert not store.path.parent.exists()
    else:
        assert dump(store) == before


@pytest.mark.parametrize('change', ['id', 'hostname', 'address', 'key', 'enabled', 'missing_disabled', 'extra'])
def test_inventory_must_match_all_retained_devices_including_disabled(configured, change, monkeypatch):
    settings, store, _fake, entries = configured
    if change == 'missing_disabled': entries.pop()
    elif change == 'extra': entries.append(entries[0] | {'id': 11, 'hostname': 'extra', 'management_ip': '192.0.2.11'})
    else:
        field, value = {'id': ('id', 11), 'hostname': ('hostname', 'changed'), 'address': ('management_ip', '192.0.2.99'),
                        'key': ('ssh_host_key', 'ssh-ed25519 CHANGED'), 'enabled': ('enabled', True)}[change]
        entries[-1][field] = value
    settings.device_inventory_path.write_text(json.dumps(entries))
    before = dump(store)
    forbid_initialization(monkeypatch)
    with pytest.raises(QueueConflict, match='inventory|Inventory'):
        create_app(settings, store)
    assert dump(store) == before


@pytest.mark.parametrize('change', ['interfaces', 'profile', 'file_missing', 'database_key'])
def test_startup_rechecks_full_frozen_inventory_before_starting_tasks(configured, change, monkeypatch):
    settings, store, _fake, entries = configured
    forbid_initialization(monkeypatch)
    app = create_app(settings, store)
    service = app.state.synchronizer.dispatcher
    if change == 'interfaces': entries[0]['allowed_interfaces'] = ['management']
    elif change == 'profile': entries[0]['addition_profile'] = 'fpr1010-766-single-vf-management-v1'
    elif change == 'database_key':
        with store._connection() as db: db.execute("UPDATE devices SET ssh_host_key='changed' WHERE id=1")
    if change == 'file_missing': settings.device_inventory_path.unlink()
    else: settings.device_inventory_path.write_text(json.dumps(entries))
    before = dump(store)

    async def scenario():
        with pytest.raises(QueueConflict):
            async with app.router.lifespan_context(app):
                raise AssertionError('Changed inventory must not start a lifecycle.')
    asyncio.run(scenario())
    assert dump(store) == before and service._task is None and not service.maintenance.status()['running']


def test_semantic_inventory_order_is_stable_and_real_lifecycle_has_one_owner(configured, monkeypatch):
    settings, store, fake, entries = configured
    app = create_app(settings, store)
    service = app.state.synchronizer.dispatcher
    for entry in entries: entry['allowed_interfaces'].reverse()
    settings.device_inventory_path.write_text(json.dumps(list(reversed(entries)), indent=2))
    # Semantic fake only at the RPC boundary; not SSH/transport acceptance.
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', lambda _self, device: fake.open_cycle(device))

    async def scenario():
        async with app.router.lifespan_context(app):
            await idle(service, fake)
            assert service.status()['running'] and service.maintenance.status()['running']
            assert not fake.writes
        assert service._task is None and not service.maintenance.status()['running']
        assert not service.runner._service_active and not fake.active
    asyncio.run(scenario())


def test_cli_check_never_serves_starts_or_exposes_inventory(configured, monkeypatch, capsys):
    settings, store, _fake, _entries = configured
    before = dump(store)
    forbid_initialization(monkeypatch)
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    monkeypatch.setattr(api.uvicorn, 'run', lambda *_args, **_kwargs: pytest.fail('No HTTP in check mode'))
    api.main(['--check'])
    report = json.loads(capsys.readouterr().out)
    assert report == {'event': 'api.runtime.checked', 'runtime_mode': 'continuous-observation',
                      'execution_started': False, 'migration_performed': False}
    assert dump(store) == before


def test_cli_check_refuses_legacy_before_initialization(configured, monkeypatch, capsys):
    settings, store, _fake, _entries = configured
    forbid_initialization(monkeypatch)
    monkeypatch.setattr(Settings, 'from_environment', lambda: replace(settings, api_runtime='legacy'))
    before = dump(store)
    with pytest.raises(SystemExit) as error: api.main(['--check'])
    assert error.value.code == 2 and 'legacy initialization was not invoked' in capsys.readouterr().err
    assert dump(store) == before


def test_configured_connections_never_create_a_vanished_database(configured, monkeypatch):
    settings, store, _fake, _entries = configured
    store.path.unlink()  # Disposable synthetic DB only.
    is_file = Path.is_file
    # Model removal after successful existence tests but before SQLite opens it.
    monkeypatch.setattr(Path, 'is_file', lambda path: True if path == store.path else is_file(path))
    with pytest.raises(sqlite3.OperationalError): create_app(settings, store)
    assert not store.path.exists()


def test_cli_check_reports_invalid_inventory_without_source_or_mutation(configured, monkeypatch, capsys):
    settings, store, _fake, entries = configured
    entries[0]['password'] = 'sensitive-test-value'
    settings.device_inventory_path.write_text(json.dumps(entries))
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    before = dump(store)
    with pytest.raises(SystemExit) as error: api.main(['--check'])
    output = capsys.readouterr()
    assert error.value.code == 2 and 'No execution was started' in output.err
    assert not output.out and 'sensitive-test-value' not in output.err
    assert dump(store) == before


def test_normal_cli_passes_only_the_private_uds_application_to_uvicorn(configured, monkeypatch):
    settings, store, _fake, _entries = configured
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    calls = []
    monkeypatch.setattr(api.uvicorn, 'run', lambda app, **kwargs: calls.append((app, kwargs)))
    before = dump(store)
    api.main([])
    assert len(calls) == 1 and calls[0][1] == {'uds': settings.api_socket, 'log_level': 'info'}
    assert calls[0][0].state.synchronizer.dispatcher._task is None
    assert dump(store) == before
