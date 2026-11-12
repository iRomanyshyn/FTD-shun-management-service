"""Clean profiles published into disposable paths only, never the lab store."""

import json
import os
import stat
from pathlib import Path

import pytest

from ftd_shun_manager import dev_init
from ftd_shun_manager.bulk_policy import _state
from ftd_shun_manager.inventory import load_public_inventory
from ftd_shun_manager.store import Store


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / 'public.json'
    path.write_text(json.dumps([{'id': 1, 'hostname': 'synthetic', 'management_ip': '192.0.2.1',
        'ssh_host_key': 'ssh-ed25519 AAAA', 'allowed_interfaces': ['management'],
        'addition_profile': 'fpr1010-766-single-vf-management-v1'}]))
    return path


@pytest.fixture
def fresh(tmp_path, inventory):
    destination = tmp_path / 'fresh.db'
    dev_init.initialize(destination, inventory)
    return Store(destination), inventory


def test_clean_profile_is_complete_active_empty_and_private(fresh, tmp_path):
    store, _path = fresh
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    with store._connection() as db:
        assert _state(db) == {'revision': 0, 'restoration_suspended': False}
        assert db.execute('SELECT mutations_suspended FROM operation_executor').fetchone()[0] == 0
        assert db.execute('SELECT legacy_imported FROM protected_policy').fetchone()[0] == 1
        for table in ('managed_shun_targets', 'managed_shun_requests', 'operation_jobs', 'operation_requests',
                      'managed_bulk_attempts', 'shun_state', 'import_preparation_plans'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_promotions').fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    events = store.list_events()
    assert len(events) == 1 and events[0]['event_type'] == 'DEV_PROFILE_INITIALIZED'
    assert events[0]['actor_subject'] == 'maintenance:development-setup'
    assert not list(tmp_path.glob('.ftd-fresh-*'))


@pytest.mark.parametrize('profile', dev_init.PROFILES)
@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'dangling'])
def test_existing_destinations_are_never_overwritten(tmp_path, inventory, kind, profile):
    target = tmp_path / 'existing.db'
    if kind == 'file': target.write_bytes(b'existing bytes')
    elif kind == 'directory': target.mkdir()
    elif kind == 'symlink': target.symlink_to(inventory)
    else: target.symlink_to(tmp_path / 'absent')
    before = inventory.read_bytes()
    with pytest.raises(FileExistsError): dev_init.initialize(target, inventory, profile=profile)
    assert inventory.read_bytes() == before
    if kind == 'file': assert target.read_bytes() == b'existing bytes'
    assert not list(tmp_path.glob('.ftd-fresh-*'))


@pytest.mark.parametrize('profile', dev_init.PROFILES)
@pytest.mark.parametrize('phase', ['schema', 'audit', 'publication_race', 'inventory_drift'])
def test_failed_build_or_racing_target_never_publishes_partial_state(tmp_path, inventory, monkeypatch, phase, profile):
    target = tmp_path / 'fresh.db'
    if phase == 'schema':
        monkeypatch.setattr(dev_init.BulkDispatch, 'initialize', lambda *_a, **_k: (_ for _ in ()).throw(ValueError('fixture failure')))
    elif phase == 'audit':
        monkeypatch.setattr(Store, '_insert_event', lambda *_a, **_k: (_ for _ in ()).throw(ValueError('fixture failure')))
    else:
        build = dev_init._build
        def raced(*args):
            result = build(*args)
            if phase == 'publication_race': target.write_bytes(b'concurrent owner')
            else:
                data = json.loads(inventory.read_text())
                data[0]['allowed_interfaces'].append('outside')
                inventory.write_text(json.dumps(data))
            return result
        monkeypatch.setattr(dev_init, '_build', raced)
    with pytest.raises((ValueError, FileExistsError)): dev_init.initialize(target, inventory, profile=profile)
    if phase == 'publication_race': assert target.read_bytes() == b'concurrent owner'
    else: assert not target.exists()
    assert not list(tmp_path.glob('.ftd-fresh-*'))


def test_only_current_protected_settings_are_copied_with_new_audit(tmp_path, inventory):
    source = Store(tmp_path / 'old.db')
    source.initialize()
    with source._connection() as db:
        db.executemany('INSERT INTO protected_ips VALUES (?,?,?,?,?)',
                       [(bytes([198, 51, 100, 1]), 'Office', 'Note', 1, 'old'),
                        (bytes([198, 51, 100, 2]), 'Disabled', '', 0, 'old')])
        before = tuple(db.iterdump())
    target = tmp_path / 'fresh.db'
    result = dev_init.initialize(target, inventory, protection_from=source.path, actor='fixture-setup')
    assert result['protected_ips_copied'] == 2
    with source._connection() as db: assert tuple(db.iterdump()) == before
    with Store(target)._connection() as db:
        assert db.execute('SELECT name,enabled FROM protected_ips ORDER BY ip').fetchall()[0]['name'] == 'Office'
        assert db.execute('SELECT revision FROM protected_policy').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
    assert {row['actor_subject'] for row in Store(target).list_events()} == {'maintenance:fixture-setup'}


@pytest.mark.parametrize('concurrency', [True, 0, 11, '2'])
def test_invalid_inputs_create_no_destination(tmp_path, inventory, concurrency):
    target = tmp_path / 'fresh.db'
    with pytest.raises(ValueError): dev_init.initialize(target, inventory, concurrency=concurrency)
    assert not os.path.lexists(target)


def test_cli_does_not_read_environment_or_contact_devices(tmp_path, inventory, monkeypatch, capsys):
    monkeypatch.setenv('FTD_SHUN_DATABASE', 'must-not-be-read')
    monkeypatch.setenv('FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS', 'invalid legacy input')
    target = tmp_path / 'fresh.db'
    assert dev_init.main(['--database', str(target), '--inventory', str(inventory)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['managed_targets'] == 0 and result['jobs'] == 0
    assert result['event'] == 'development.profile.initialized'
    assert load_public_inventory(inventory)[0].device.id == 1


def test_relative_or_missing_parent_destination_is_not_created(tmp_path, inventory):
    with pytest.raises(ValueError): dev_init.initialize(Path('relative.db'), inventory)
    with pytest.raises(FileNotFoundError): dev_init.initialize(tmp_path / 'absent' / 'state.db', inventory)
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('profile', [None, True, 7, 'v7', 'deferred', ' deferred-confirmation', ''])
def test_profile_selection_is_explicit_and_literal_without_any_published_file(tmp_path, inventory, profile):
    target = tmp_path / 'fresh.db'
    with pytest.raises(ValueError): dev_init.initialize(target, inventory, profile=profile)
    assert not os.path.lexists(target) and not list(tmp_path.glob('.ftd-fresh-*'))


def test_deferred_profile_includes_complete_ordered_and_independent_control_storage(tmp_path, inventory, fresh):
    from ftd_shun_manager.managed_addition_controls import read
    from ftd_shun_manager.pending_execution import PendingExecution

    previous, _ = fresh
    with previous._connection() as db: before = tuple(db.iterdump())
    target = tmp_path / 'deferred.db'
    result = dev_init.initialize(target, inventory, profile='deferred-confirmation', actor='deferred-fixture')
    store = Store(target)
    assert result['profile'] == 'deferred-confirmation' and result['jobs'] == result['managed_targets'] == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with store._connection() as db:
        PendingExecution._profile(db)
        assert _state(db) == {'revision': 0, 'restoration_suspended': False}
        control = read(db)
        assert control['available'] and not control['imports']['paused'] and not control['restoration']['paused']
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_ordered_promotions').fetchone()[0] == 0
        for table in ('managed_bulk_pending_sessions', 'managed_bulk_pending_retries', 'managed_bulk_pending_reads',
                      'operation_jobs', 'operation_requests', 'managed_shun_targets', 'shun_state'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    event = store.list_events()[0]
    assert event['actor_subject'] == 'maintenance:deferred-fixture'
    assert event['details']['profile'] == 'deferred-confirmation'
    with previous._connection() as db: assert tuple(db.iterdump()) == before


def test_failed_deferred_extension_never_publishes_or_overwrites(tmp_path, inventory, monkeypatch):
    original = dev_init.PendingExecution.initialize_empty

    def fail(service, **kwargs):
        original(service, **kwargs)
        raise ValueError('Synthetic deferred extension failure')
    monkeypatch.setattr(dev_init.PendingExecution, 'initialize_empty', fail)
    target = tmp_path / 'deferred.db'
    with pytest.raises(ValueError, match='Synthetic deferred'):
        dev_init.initialize(target, inventory, profile='deferred-confirmation')
    assert not target.exists() and not list(tmp_path.glob('.ftd-fresh-*'))


def test_deferred_cli_selects_storage_without_enabling_current_runtime(tmp_path, inventory, capsys):
    import asyncio

    from test_deferred_worker import Agent

    from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
    from ftd_shun_manager.deferred_dispatch import DeferredContinuousDispatcher
    from ftd_shun_manager.operation_queue import QueueConflict

    target = tmp_path / 'deferred.db'
    assert dev_init.main(['--database', str(target), '--inventory', str(inventory),
                          '--profile', 'deferred-confirmation']) == 0
    assert json.loads(capsys.readouterr().out)['profile'] == 'deferred-confirmation'
    store, agent = Store(target), Agent()
    current = ContinuousDispatcher(store, agent, enabled=True, addition_device_ids=frozenset({1}))
    with pytest.raises(QueueConflict, match='explicit deferred'):
        asyncio.run(current.start())
    assert not agent.seen
    future = DeferredContinuousDispatcher(store, agent, enabled=True, addition_device_ids=frozenset({1}),
        ordered_promotion_enabled=True)
    future.runner._validate_execution_storage()
    assert not agent.seen  # Validation does not acquire a lease or contact a device.
