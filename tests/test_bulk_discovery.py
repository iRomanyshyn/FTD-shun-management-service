"""Bounded refill and existing scheduler integration; disposable state/fake FTD."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_attempts import OWNER
from test_bulk_attempts import journal as journal_fixture
from test_bulk_cancellations import cancel
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_dispatch import dispatch as dispatch_fixture
from test_bulk_dispatch import setup
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, prepare
from test_bulk_waits import waits as waits_fixture
from test_managed_discovery import Agent

from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_discovery import BulkDiscovery
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store
from ftd_shun_manager.synchronizer import Synchronizer

journal = journal_fixture
cancellation_controls = cancellation_fixture
waits = waits_fixture
dispatch = dispatch_fixture


def controller(dispatch, **changes):
    return BulkDiscovery(dispatch.store, dispatch.queue,
                         **({'enabled': True, 'addition_device_ids': frozenset({1})} | changes))


def fresh(bulk, snapshot, seconds=1):
    bulk[1][0] += timedelta(seconds=seconds)
    return replace(snapshot, id=str(uuid4()), started_at=bulk[1][0], completed_at=bulk[1][0])


def complete(dispatch):
    while job := dispatch.queue.claim_addition(1, OWNER, dispatch.queue.cutoff(), execution_enabled=True, bulk_dispatch_enabled=True):
        dispatch.queue.finish_addition(job['id'], OWNER, AdditionResult(False, None))


def test_disabled_constructor_and_reads_never_initialize_optional_state(tmp_path):
    store = Store(tmp_path / 'absent.db')
    discovery = BulkDiscovery(store, OperationQueue(store))
    assert not store.path.exists()
    assert discovery.discover(None, '') == 0
    assert discovery.status()['enabled'] is False
    assert discovery.ordered_devices([]) == []
    assert not store.path.exists()


def test_window_and_cycle_budget_bound_new_work_and_same_snapshot_reuse(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch, count=40)
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 16
    assert discovery.discover(snapshot, OWNER) == 0
    assert discovery.status()['admitted_this_cycle'] == 16
    complete(dispatch)
    discovery.begin_cycle()
    assert discovery.discover(snapshot, OWNER) == 16
    assert discovery.status()['checked_this_cycle'] == 16
    assert discovery.discover(snapshot, OWNER) == 0
    complete(dispatch)
    discovery.begin_cycle()
    assert discovery.discover(snapshot, OWNER) == 8
    complete(dispatch)
    discovery.begin_cycle()
    assert discovery.discover(snapshot, OWNER) == 0
    assert discovery.status()['counts']['snapshot_used'] == 40
    with dispatch.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 40
        assert not db.execute('SELECT 1 FROM manual_import_batches').fetchone()


def test_large_present_prefix_does_not_starve_later_missing_targets(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=100)
    snapshot = replace(snapshot, present_ips=frozenset(c.ip for c in candidates[:64]))
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 0
    assert discovery.status()['checked_this_cycle'] == 64
    discovery.begin_cycle()
    assert discovery.discover(fresh(bulk, snapshot), OWNER) == 16
    assert discovery.status()['checked_this_cycle'] == 16
    with dispatch.store._connection() as db:
        assert db.execute('SELECT MIN(ip) FROM operation_jobs').fetchone()[0] == candidates[64].ip.packed


def test_restart_rescans_without_duplicate_or_lost_standing_authority(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch, count=30)
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 16
    complete(dispatch)
    restarted = controller(dispatch)
    assert restarted.discover(snapshot, OWNER) == 14
    assert restarted.status()['checked_this_cycle'] == 30
    assert restarted.status()['counts']['snapshot_used'] == 16


def test_window_counts_independent_removals_and_survives_begin_cycle(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch, count=30)
    with dispatch.store._connection() as db:
        for i in range(15):
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), IPv4Address(0xCB007101 + i).packed, stamp(bulk[1][0])))
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 1
    discovery.begin_cycle()
    assert discovery.discover(snapshot, OWNER) == 0
    assert discovery.status()['devices']['1']['state'] == 'window_full'


@pytest.mark.parametrize('hold', ['suspended', 'paused', 'unknown', 'disabled', 'protected'])
def test_current_controls_skip_without_rearming_or_clearing_evidence(bulk, dispatch, hold):
    _, snapshot, candidates = setup(bulk, dispatch)
    if hold == 'protected':
        ProtectedPolicy(dispatch.store).change('add', candidates[0].ip, 0, 'viewer', 'Viewer', ('Viewer',), managed_revision=1)
    with dispatch.store._connection() as db:
        if hold == 'suspended': db.execute('UPDATE managed_bulk_registry SET restoration_suspended=1')
        if hold == 'paused': db.execute('UPDATE operation_executor SET mutations_suspended=1')
        if hold == 'disabled': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
        if hold == 'unknown':
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'UNVERIFIED',?,'REMOVE')",
                       (str(uuid4()), IPv4Address('203.0.113.250').packed, stamp(bulk[1][0])))
    before = dump(dispatch.store)
    assert controller(dispatch).discover(snapshot, OWNER) == 0
    assert dump(dispatch.store) == before


def test_queue_backpressure_reports_capacity_without_partial_members(bulk, dispatch, monkeypatch):
    _, snapshot, _ = setup(bulk, dispatch, count=16)
    discovery = controller(dispatch)
    monkeypatch.setattr(dispatch.queue, '_pending_count', lambda db: 999)
    before = dump(dispatch.store)
    assert discovery.discover(snapshot, OWNER) == 0
    assert discovery.status()['devices']['1']['state'] == 'capacity'
    assert discovery.status()['admitted_this_cycle'] == 0
    assert dump(dispatch.store) == before


def test_late_clock_failure_does_not_commit_jobs_or_advance_scan_hints(bulk, dispatch, monkeypatch):
    _, snapshot, _ = setup(bulk, dispatch, count=30)
    discovery = controller(dispatch)
    original = dispatch.store._insert_event

    def slow(*args):
        value = original(*args)
        bulk[1][0] += timedelta(seconds=121)
        return value

    monkeypatch.setattr(dispatch.store, '_insert_event', slow)
    before, status = dump(dispatch.store), discovery.status()
    with pytest.raises(QueueConflict): discovery.discover(snapshot, OWNER)
    assert dump(dispatch.store) == before and discovery.status() == status
    assert discovery._cursors == {}


def test_revision_change_resets_cursor_and_status_is_defensive_copy(bulk, dispatch):
    _, snapshot, candidates = setup(bulk, dispatch, count=80)
    discovery = controller(dispatch)
    present = replace(snapshot, present_ips=frozenset(c.ip for c in candidates[:64]))
    assert discovery.discover(present, OWNER) == 0
    with dispatch.store._connection() as db: db.execute('UPDATE protected_policy SET revision=1')
    discovery.begin_cycle()
    assert discovery.discover(fresh(bulk, present), OWNER) == 0
    assert discovery.status()['checked_this_cycle'] == 64
    view = discovery.status()
    view['devices']['1']['counts'].clear()
    assert discovery.status()['counts']['present'] == 64


def test_cancelled_root_and_used_snapshot_are_not_replayed(bulk, dispatch, cancellation_controls):
    root, snapshot, _ = setup(bulk, dispatch, count=30)
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 16
    cancel(cancellation_controls, root)
    discovery.begin_cycle()
    before = dump(dispatch.store)
    assert discovery.discover(fresh(bulk, snapshot), OWNER) == 0
    assert dump(dispatch.store) == before


@pytest.mark.parametrize('bad', ['partial', 'future', 'stale', 'lease', 'schema'])
def test_bad_evidence_lease_or_profile_never_migrates_or_admits(bulk, dispatch, bad):
    _, snapshot, _ = setup(bulk, dispatch)
    if bad == 'partial': snapshot = replace(snapshot, complete=False)
    if bad == 'future': snapshot = replace(snapshot, completed_at=snapshot.completed_at + timedelta(seconds=1))
    if bad == 'stale': snapshot = replace(snapshot, started_at=snapshot.started_at - timedelta(seconds=121))
    with dispatch.store._connection() as db:
        if bad == 'lease': db.execute("UPDATE operation_executor SET owner='other'")
        if bad == 'schema': db.execute('DROP TRIGGER managed_bulk_attempt_identity')
    before = dump(dispatch.store)
    with pytest.raises((ValueError, BulkUnavailable)): controller(dispatch).discover(snapshot, OWNER)
    assert dump(dispatch.store) == before


@pytest.fixture
def scheduler(bulk, dispatch):
    root, _, _ = setup(bulk, dispatch, count=36)
    dispatch.queue.finish_cycle(OWNER, 60)
    bulk[1][0] += timedelta(seconds=61)
    agent = Agent()
    agent.entries = {i: [] for i in range(1, 11)}
    sync = Synchronizer(dispatch.store, agent, 300, 60, session_cycles_enabled=True,
                        import_execution_enabled=True, addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True)
    return root, agent, sync


def sweep(bulk, sync, seconds=0):
    bulk[1][0] += timedelta(seconds=seconds)
    asyncio.run(sync._sweep())


def test_existing_scheduler_refills_dispatches_and_restores_missing_managed_target(bulk, scheduler):
    _, agent, sync = scheduler
    sweep(bulk, sync)
    assert not agent.writes and sync._has_pending()
    assert sync.status()['bulk_discovery']['admitted_this_cycle'] == 16
    assert all(item['execution_enabled'] for item in sync.status()['queue']['items'])
    sweep(bulk, sync, 59)
    assert not agent.writes
    sweep(bulk, sync, 2)
    assert len(agent.writes) == 16
    assert sync.status()['bulk_discovery']['admitted_this_cycle'] == 16
    sweep(bulk, sync, 61)
    assert len(agent.writes) == 32
    sweep(bulk, sync, 61)
    assert len(agent.writes) == 36 and not sync._has_pending()
    removed = agent.entries[1].pop(0)  # Synthetic disappearance, not live SSH.
    sweep(bulk, sync, 301)
    assert len(agent.writes) == 36 and sync._has_pending()
    sweep(bulk, sync, 61)
    assert len(agent.writes) == 37 and agent.writes[-1] == (1, removed.ip)


def test_old_flags_do_not_mark_bulk_jobs_pending_or_executable(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch)
    controller(dispatch).discover(snapshot, OWNER)
    assert not dispatch.queue.has_pending(addition_device_ids=frozenset({1}), managed_restoration_enabled=True)
    assert not dispatch.queue.status(addition_device_ids=frozenset({1}), managed_restoration_enabled=True)['items'][0]['execution_enabled']
    assert dispatch.queue.has_pending(addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True)


def test_expired_unsent_delegation_is_cancelled_not_a_permanent_cli_failure(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch)
    discovery = controller(dispatch)
    assert discovery.discover(snapshot, OWNER) == 1
    bulk[1][0] += timedelta(seconds=901)
    dispatch.queue.expire_requests()
    with dispatch.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'CANCELLED'
    assert dispatch.queue.claim_cycle('replacement', 135)
    discovery.begin_cycle()
    assert discovery.discover(fresh(bulk, snapshot), 'replacement') == 1


def test_lost_reply_retains_unknown_without_automatic_second_add(bulk, scheduler):
    _, agent, sync = scheduler
    sweep(bulk, sync)
    agent.lost = True
    sweep(bulk, sync, 61)
    assert len(agent.writes) == 1
    agent.lost = False
    sweep(bulk, sync, 301)
    assert len(agent.writes) == 1
    assert sync.status()['bulk_discovery']['devices']['1']['state'] == 'device_uncertain'
    assert sync.status()['queue']['counts']['UNVERIFIED'] == 1


@pytest.mark.parametrize('changes', [{'bulk_dispatch_enabled': 1}, {'bulk_dispatch_enabled': True},
    {'bulk_dispatch_enabled': True, 'import_execution_enabled': True, 'session_cycles_enabled': True, 'managed_restoration_enabled': True},
    {'bulk_dispatch_enabled': True, 'import_execution_enabled': True, 'session_cycles_enabled': True, 'managed_removal_worker_enabled': True}])
def test_incompatible_controller_modes_are_rejected_without_migration(bulk, changes):
    before = dump(bulk[0].store)
    with pytest.raises(ValueError): Synchronizer(bulk[0].store, Agent(), 300, 60, **changes)
    assert dump(bulk[0].store) == before


def test_device_order_uses_retained_admissions_across_restart(bulk, dispatch):
    policy, clock = bulk
    _, proposal = prepare(bulk, '\n'.join(f'198.51.100.{i}' for i in range(1, 31)), (1, 2))
    confirm(bulk, proposal)
    with dispatch.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0,dispatch_resume_after=?', (stamp(clock[0]),))
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    clock[0] += timedelta(seconds=2)
    assert dispatch.queue.claim_cycle(OWNER, 135)
    from ftd_shun_manager.managed_restoration import CompleteSnapshot

    evidence = CompleteSnapshot(str(uuid4()), 1, clock[0], clock[0], frozenset())
    discovery = controller(dispatch, addition_device_ids=frozenset({1, 2}))
    assert [d.id for d in discovery.ordered_devices(policy.store.list_devices())][:2] == [1, 2]
    assert discovery.discover(evidence, OWNER) == 16
    restarted = controller(dispatch, addition_device_ids=frozenset({1, 2}))
    assert [d.id for d in restarted.ordered_devices(policy.store.list_devices())][:2] == [2, 1]
    assert restarted.discover(replace(evidence, device_id=2, id=str(uuid4())), OWNER) == 16
    assert restarted.status()['admitted_this_cycle'] == 16


@pytest.mark.parametrize('kwargs', [{'enabled': 1}, {'addition_device_ids': [1]},
    {'addition_device_ids': frozenset({True})}, {'addition_device_ids': frozenset(range(1, 12))}])
def test_controller_rejects_nonliteral_or_unbounded_configuration(bulk, dispatch, kwargs):
    before = dump(dispatch.store)
    with pytest.raises(ValueError): controller(dispatch, **kwargs)
    assert dump(dispatch.store) == before


def test_missing_optional_profile_surfaces_error_but_keeps_reads_and_does_not_initialize(bulk):
    policy, _ = bulk
    agent = Agent()
    agent.entries = {i: [] for i in range(1, 11)}
    sync = Synchronizer(policy.store, agent, 300, 60, session_cycles_enabled=True,
                        import_execution_enabled=True, addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True)
    with policy.store._connection() as db:
        original = [tuple(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE name GLOB 'managed_*' ORDER BY name")]
    sweep(bulk, sync)
    assert not agent.writes and len(agent.reads) == 20
    status = sync.status()
    assert all(device['last_successful_refresh'] for device in status['devices'].values())
    assert status['managed_restoration_error'] and status['cycle_outcome'] == 'partial'
    with policy.store._connection() as db:
        assert [tuple(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE name GLOB 'managed_*' ORDER BY name")] == original


def test_read_reconciliation_and_retention_cannot_erase_device_unknown_barrier(bulk, dispatch):
    _, snapshot, _ = setup(bulk, dispatch)
    key, job = str(uuid4()), str(uuid4())
    with dispatch.store._connection() as db:
        db.execute("INSERT INTO operation_requests VALUES (?,'synthetic:original','Original','[]','trusted_policy','{}',?,?,'CANCELLED')",
                   (key, stamp(bulk[1][0]), stamp(bulk[1][0] + timedelta(seconds=900))))
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,completed_at,action) VALUES (?,1,?,'UNVERIFIED',?,?,'REMOVE')",
                   (job, IPv4Address('203.0.113.250').packed, stamp(bulk[1][0]), stamp(bulk[1][0])))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job))
    dispatch.queue.reconcile_unknown(1, set())
    with dispatch.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'RECONCILED_ABSENT'
    bulk[1][0] += timedelta(days=400)
    dispatch.queue.prune_completed(366)
    with dispatch.store._connection() as db:
        assert db.execute('SELECT id FROM operation_jobs WHERE id=?', (job,)).fetchone()
        assert db.execute('SELECT id FROM operation_requests WHERE id=?', (key,)).fetchone()
    assert dispatch.queue.claim_cycle('replacement', 135)
    discovery = controller(dispatch)
    assert discovery.discover(fresh(bulk, snapshot), 'replacement') == 0
    assert discovery.status()['devices']['1']['state'] == 'device_uncertain'
