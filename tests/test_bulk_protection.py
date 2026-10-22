"""Existing protection editor against disposable version-2 policy storage only."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, no_work, prepare

from ftd_shun_manager import bulk_policy
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_policy import BulkPolicies
from ftd_shun_manager.config import Settings
from ftd_shun_manager.managed_safety import ManagedStateUnavailable, managed_state
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy

IP = IPv4Address('198.51.100.1')
OTHER = IPv4Address('198.51.100.2')


def protect(editor, *, action='add', ip=IP, roles=('Viewer',), **changes):
    options = {'managed_revision': editor.snapshot()['managed_revision'], **changes}
    return editor.change(action, ip, editor.revision(), 'policy-editor', 'Actual editor', roles, **options)


def grant(bulk, *, devices=(1, 2, 3)):
    policy, _ = bulk
    _, proposal = prepare(bulk, f'{IP}\n{OTHER}', devices)
    confirm(bulk, proposal)
    return policy, ProtectedPolicy(policy.store), proposal


@pytest.mark.parametrize('roles', [(), ('Viewer',), ('Operator',), ('Administrator',)])
def test_actual_editor_retires_all_matching_devices_without_promoting_roles(bulk, roles):
    policy, editor, proposal = grant(bulk, devices=tuple(range(1, 11)))
    before = policy.policy_page()['entries']
    with policy.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id=10')
    # No target has an observed shun, including the disabled tenth device.
    protect(editor, roles=roles)
    current = policy.policy_page()
    assert current['revision'] == 2
    for old, new in zip(before, current['entries'], strict=True):
        for field in ('intent_id', 'generation', 'authorization_request_id', 'authorized_at'):
            assert new[field] == old[field]
        assert bool(new['enabled']) == (new['ip'] != str(IP))
        assert new['revision'] == (2 if new['ip'] == str(IP) else 1)
    snapshot = editor.snapshot()
    assert snapshot['managed_policy_available'] and snapshot['managed_revision'] == 2
    assert snapshot['entries'][0]['maintained_devices'] == 0
    assert snapshot['entries'][0]['active_devices'] == 0
    events = policy.store.list_events(limit=100)
    saved = next(row for row in events if row['event_type'] == 'PROTECTED_IP_ADDED')
    retired = [row for row in events if row['event_type'] == 'MANAGED_SHUN_RETIRED']
    assert len(retired) == 10 and {row['device_id'] for row in retired} == set(range(1, 11))
    for row in [saved, *retired]:
        assert row['actor_subject'] == 'policy-editor' and row['actor_display_name'] == 'Actual editor'
        assert row['actor_roles'] == list(roles) and row['request_id'] == saved['request_id']
    assert all(row['details']['authorization_request_id'] == proposal['operation_id'] for row in retired)
    assert all(row['details']['protected_revision'] == 1 for row in retired)
    assert saved['details']['managed_context']['retired_targets'] == 10
    assert not saved['details']['managed_context']['retirement_deferred']
    assert len(policy.page(proposal['operation_id'], 'alice')['targets']) == 20
    with policy.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 1
        with pytest.raises(ManagedStateUnavailable): managed_state(db)
    no_work(policy)


@pytest.mark.parametrize('action', ['edit', 'delete'])
def test_weakening_restart_and_old_confirmation_never_reenable_retired_generation(bulk, action):
    policy, editor, proposal = grant(bulk)
    protect(editor)
    original = policy.policy_page()['entries']
    before = dump(policy.store)
    assert confirm(bulk, proposal)['replayed']
    assert dump(policy.store) == before
    protect(editor, action=action, enabled=False, confirm_maintenance_resume=True)
    restarted = BulkPolicies(policy.store, clock=policy.clock)
    editor = ProtectedPolicy(policy.store)
    assert not editor.enabled_ips()
    assert restarted.policy_page()['entries'] == original
    assert confirm((restarted, bulk[1]), proposal)['replayed']
    assert restarted.policy_page()['entries'] == original
    # New explicit consent after weakening may create a new generation, not a retry.
    _, newer = prepare(bulk)
    confirm(bulk, newer)
    row = next(row for row in policy.policy_page()['entries'] if row['device_id'] == 1 and row['ip'] == str(IP))
    assert row['enabled'] and row['generation'] == 2
    assert row['authorization_request_id'] == newer['operation_id']
    assert confirm(bulk, proposal)['replayed']
    assert policy.policy_page()['entries'][0] == row
    no_work(policy)


def test_disabled_protection_metadata_does_not_stop_new_explicit_maintenance(bulk):
    policy, editor, _ = grant(bulk)
    protect(editor, enabled=False)
    protect(editor, action='edit', enabled=False, name='Still disabled')
    assert all(row['enabled'] for row in policy.policy_page()['entries'])
    protect(editor, action='delete')
    assert all(row['enabled'] for row in policy.policy_page()['entries'])
    assert policy.policy_page()['revision'] == 1
    no_work(policy)


@pytest.mark.parametrize('revision', [None, 0, 2])
def test_nonempty_retirement_requires_exact_reviewed_revision(bulk, revision):
    policy, editor, _ = grant(bulk)
    before = dump(policy.store)
    with pytest.raises(QueueConflict): protect(editor, managed_revision=revision)
    assert dump(policy.store) == before


def test_stale_protection_revision_and_duplicate_save_do_not_repeat_retirement(bulk):
    policy, editor, _ = grant(bulk)
    protect(editor)
    before = dump(policy.store)
    with pytest.raises(QueueConflict):
        editor.change('edit', IP, 0, 'policy-editor', 'Actual editor', (), managed_revision=2)
    with pytest.raises(QueueConflict): protect(editor)
    assert dump(policy.store) == before
    protect(editor, action='edit', name='Metadata only')
    assert policy.policy_page()['revision'] == 2
    assert len([row for row in policy.store.list_events(limit=100) if row['event_type'] == 'MANAGED_SHUN_RETIRED']) == 3


def test_retirement_works_with_full_request_ledger_and_ordinary_mutation_pause(bulk, monkeypatch):
    policy, editor, _ = grant(bulk)
    monkeypatch.setattr(bulk_policy, 'MAX_REQUESTS', 1)
    with policy.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    protect(editor)
    assert sum(row['enabled'] for row in policy.policy_page()['entries']) == 3
    with policy.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 1
        assert db.execute('SELECT mutations_suspended FROM operation_executor').fetchone()[0] == 1
    no_work(policy)


@pytest.mark.parametrize('failure', ['retirement_audit', 'policy_audit', 'queue_hook'])
def test_any_late_failure_rolls_back_policy_retirement_revisions_and_audit(bulk, monkeypatch, failure):
    policy, editor, _ = grant(bulk)
    before = dump(policy.store)
    original = policy.store._insert_event

    def fail_event(db, event, *args, **kwargs):
        result = original(db, event, *args, **kwargs)
        if event == {'retirement_audit': 'MANAGED_SHUN_RETIRED', 'policy_audit': 'PROTECTED_IP_ADDED'}[failure]:
            raise sqlite3.OperationalError('Synthetic late audit failure')
        return result

    def fail_queue(db):
        raise sqlite3.OperationalError('Synthetic queue hook failure')

    if failure == 'queue_hook':
        monkeypatch.setattr(editor.queue, '_cancel_obsolete_policy', fail_queue)
    else:
        monkeypatch.setattr(policy.store, '_insert_event', fail_event)
    with pytest.raises(sqlite3.OperationalError): protect(editor)
    assert dump(policy.store) == before


@pytest.mark.parametrize('corruption', ['registry_row', 'member_column', 'optional_attempts', 'legacy_registry', 'identity'])
def test_unknown_bulk_state_allows_barrier_but_refuses_weakening_or_legacy_fallback(bulk, corruption):
    policy, editor, _ = grant(bulk)
    with policy.store._connection() as db:
        if corruption == 'registry_row':
            db.execute('DELETE FROM managed_bulk_registry')
        elif corruption == 'member_column':
            db.execute('ALTER TABLE managed_bulk_members RENAME COLUMN classification TO broken')
        elif corruption == 'optional_attempts':
            db.execute('CREATE TABLE managed_restoration_attempts(id TEXT PRIMARY KEY)')
        elif corruption == 'legacy_registry':
            db.execute('CREATE TABLE managed_shun_registry(id INTEGER PRIMARY KEY,revision INTEGER,restoration_suspended INTEGER)')
        else:
            db.execute("UPDATE managed_shun_targets SET intent_id='not-a-uuid' WHERE device_id=1 AND ip=?", (IP.packed,))
    protect(editor)
    snapshot = editor.snapshot()
    assert not snapshot['managed_policy_available'] and snapshot['managed_revision'] is None
    assert snapshot['entries'][0]['maintained_devices'] is None
    assert editor.enabled_ips() == {IP}
    saved = next(row for row in policy.store.list_events() if row['event_type'] == 'PROTECTED_IP_ADDED')
    assert saved['details']['managed_context']['retirement_deferred']
    before = dump(policy.store)
    for action in ('edit', 'delete'):
        with pytest.raises(ManagedStateUnavailable): protect(editor, action=action, enabled=False)
    assert dump(policy.store) == before
    assert editor.snapshot() == snapshot
    assert dump(policy.store) == before  # GET does not repair or retire.


@pytest.mark.parametrize('action', ['edit', 'delete'])
def test_repaired_barrier_completes_retirement_before_release_not_on_read_or_restart(bulk, action):
    policy, editor, proposal = grant(bulk)
    with policy.store._connection() as db:
        db.execute('DELETE FROM managed_bulk_registry')
    protect(editor)
    with policy.store._connection() as db:
        db.execute('INSERT INTO managed_bulk_registry(id,revision,restoration_suspended,format_version) VALUES (1,1,1,2)')
    editor = ProtectedPolicy(policy.store)
    before = dump(policy.store)
    assert editor.snapshot()['entries'][0]['maintained_devices'] == 3
    assert dump(policy.store) == before
    protect(editor, action=action, enabled=False)
    assert not editor.enabled_ips()
    assert not any(row['enabled'] for row in policy.policy_page()['entries'] if row['ip'] == str(IP))
    assert confirm(bulk, proposal)['replayed']
    no_work(policy)


def seed_job(store, device, ip, action, state, *, source='manual'):
    """Synthetic retained jobs only; bypasses no runtime admission in this test."""
    key, job = str(uuid4()), str(uuid4())
    with store._connection() as db:
        db.execute("""INSERT INTO operation_requests VALUES
            (?,'synthetic-requester','Fixture','[]',?,?,'2026-10-21T12:00:00Z','2099-01-01T00:00:00Z','ACTIVE')""",
            (key, source, json.dumps({'scope': 'device', 'targets': [[device, str(ip)]]})))
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action,dispatch_kind)
            VALUES (?,?,?,?,'2026-10-21T12:00:00Z',?,?)""",
            (job, device, ip.packed, state, action, action if state == 'RUNNING' else None))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job))
    return job


def test_queued_add_cancelled_running_and_unknown_preserved_and_removal_stays_independent(bulk):
    policy, editor, _ = grant(bulk)
    queued = seed_job(policy.store, 1, IP, 'ADD', 'QUEUED')
    running = seed_job(policy.store, 2, IP, 'ADD', 'RUNNING')
    unknown = seed_job(policy.store, 3, IP, 'ADD', 'UNVERIFIED')
    unrelated = seed_job(policy.store, 1, OTHER, 'ADD', 'QUEUED')
    removal = seed_job(policy.store, 4, IP, 'REMOVE', 'QUEUED', source='trusted_policy')
    protect(editor)
    with policy.store._connection() as db:
        states = dict(db.execute('SELECT id,state FROM operation_jobs'))
        assert states == {queued: 'FAILED', running: 'RUNNING', unknown: 'UNVERIFIED', unrelated: 'QUEUED', removal: 'QUEUED'}
    protect(editor, action='edit', enabled=False)
    with policy.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (removal,)).fetchone()[0] == 'CANCELLED'
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (running,)).fetchone()[0] == 'RUNNING'
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (unknown,)).fetchone()[0] == 'UNVERIFIED'
    _, newer = prepare(bulk)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict): confirm(bulk, newer)
    assert dump(policy.store) == before


def test_audit_failure_also_rolls_back_unsent_job_cancellation(bulk, monkeypatch):
    policy, editor, _ = grant(bulk)
    queued = seed_job(policy.store, 1, IP, 'ADD', 'QUEUED')
    before = dump(policy.store)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('Synthetic policy audit failure after cancellation')

    monkeypatch.setattr(editor, '_audit', fail)
    with pytest.raises(sqlite3.OperationalError): protect(editor)
    assert dump(policy.store) == before
    with policy.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (queued,)).fetchone()[0] == 'QUEUED'


def test_weakening_keeps_manual_request_coalesced_with_protected_removal(bulk):
    policy, editor, _ = grant(bulk)
    protect(editor)
    job = seed_job(policy.store, 1, IP, 'REMOVE', 'QUEUED', source='trusted_policy')
    manual = str(uuid4())
    with policy.store._connection() as db:
        db.execute("""INSERT INTO operation_requests VALUES
            (?,'manual-requester','Fixture','["Operator"]','manual','{}',
             '2026-10-21T12:00:00Z','2099-01-01T00:00:00Z','ACTIVE')""", (manual,))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (manual, job))
    protect(editor, action='delete')
    with policy.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'QUEUED'
        assert db.execute('SELECT state FROM operation_requests WHERE id=?', (manual,)).fetchone()[0] == 'ACTIVE'
        assert db.execute("SELECT COUNT(*) FROM operation_requests WHERE source='trusted_policy' AND state='CANCELLED'").fetchone()[0] == 1


@pytest.mark.parametrize('roles', [[], ['Viewer'], ['Operator'], ['Administrator']])
def test_existing_private_policy_routes_read_and_revoke_bulk_without_enabling_runtime(bulk, roles):
    policy, _, proposal = grant(bulk)
    # Explicit synthetic first-import marker; no environment migration is exercised.
    with policy.store._connection() as db:
        db.execute('UPDATE protected_policy SET legacy_imported=1')
    config = Settings(database_path=policy.store.path, device_inventory_path=None,
        agent_socket='/unused-agent.sock', web_socket='/unused-web.sock', api_socket='/unused-api.sock',
        agent_mode='disabled', agent_timeout_seconds=45, poll_interval_seconds=300,
        interactive_refresh_min_interval_seconds=60, history_retention_days=366,
        sensitive_action_max_age_seconds=3600, development_auth=False)
    app = create_app(config, policy.store)  # No lifespan/worker/device connection.

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            snapshot = await client.get('/api/v1/protected-ips')
            assert snapshot.status_code == 200 and snapshot.json()['managed_revision'] == 1
            body = {'actor': {'subject': 'real-api-editor', 'display_name': 'API editor', 'roles': roles},
                    'revision': 0, 'managed_revision': 0, 'enabled': True}
            before = dump(policy.store)
            assert (await client.post(f'/api/v1/protected-ips/{IP}/add', json=body)).status_code == 409
            assert dump(policy.store) == before
            body['managed_revision'] = 1
            saved = await client.post(f'/api/v1/protected-ips/{IP}/add', json=body)
            assert saved.status_code == 200
            assert saved.json()['policy']['managed_revision'] == 2
            body.update(revision=1, managed_revision=2, enabled=False, confirm_ip=str(IP))
            assert (await client.post(f'/api/v1/protected-ips/{IP}/delete', json=body)).status_code == 200
    asyncio.run(scenario())
    assert not any(row['enabled'] for row in policy.policy_page()['entries'] if row['ip'] == str(IP))
    events = [row for row in policy.store.list_events(limit=100) if row['event_type'] == 'MANAGED_SHUN_RETIRED']
    assert len(events) == 3 and all(row['actor_roles'] == roles and row['actor_subject'] == 'real-api-editor' for row in events)
    assert confirm(bulk, proposal)['replayed']
    no_work(policy)


def test_simultaneous_new_grant_and_protection_cannot_leave_enabled_matching_authority(bulk):
    policy, _ = bulk
    editor = ProtectedPolicy(policy.store)
    _, proposal = prepare(bulk)

    def change(call):
        try:
            call()
            return 'saved'
        except (ManagedConflict, QueueConflict):
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        grant_result = pool.submit(change, lambda: confirm(bulk, proposal))
        protection_result = pool.submit(change, lambda: protect(editor, managed_revision=0))
        assert sorted([grant_result.result(), protection_result.result()]) == ['conflict', 'saved']
    protect(editor, action='edit' if editor.enabled_ips() else 'add')
    assert editor.enabled_ips() == {IP}
    assert not any(row['enabled'] for row in policy.policy_page()['entries'])
    no_work(policy)
