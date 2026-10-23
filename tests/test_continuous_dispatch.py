"""Independent timers/continuous semantic dispatch on disposable state, not FTD."""

import asyncio
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_cancellations import cancel as cancel_bulk
from test_bulk_policy import dump
from test_device_leases import acquire, claim, discover, grant
from test_parallel_synchronizer import BlockingAgent, wait
from test_parallel_synchronizer import bulk as bulk_fixture
from test_parallel_synchronizer import cancellation_controls as cancellation_fixture
from test_parallel_synchronizer import dispatch as dispatch_fixture
from test_parallel_synchronizer import journal as journal_fixture
from test_parallel_synchronizer import leases as leases_fixture
from test_parallel_synchronizer import waits as waits_fixture

from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher, ReadDemand
from ftd_shun_manager.device_leases import DeviceOperationQueue
from ftd_shun_manager.operation_queue import QueueConflict, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


class TracedAgent(BlockingAgent):
    settled_cycles = True  # Synthetic semantic transport models successful local settlement.
    def __init__(self):
        super().__init__()
        self.trace = []

    def open_cycle(self, device):
        session = super().open_cycle(device)
        self.trace.append(('open', device, None))
        add, remove, snapshot, finish = session.add_shun, session.remove_shun, session.snapshot, session.finish

        def addition(ip):
            result = add(ip)
            self.trace.append(('add', device, ip))
            return result

        def removal(ip):
            result = remove(ip)
            self.trace.append(('remove', device, ip))
            return result

        def refresh():
            result = snapshot()
            self.trace.append(('refresh', device, None))
            return result

        def settled_finish():
            result = finish()
            session.settled = True
            return result

        session.add_shun, session.remove_shun, session.snapshot = addition, removal, refresh
        session.finish = settled_finish
        return session


@pytest.fixture
def continuous(bulk, leases):
    with leases.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    clock, agent = [1000.0], TracedAgent()
    service = ContinuousDispatcher(leases.store, agent, enabled=True, agent_concurrency=2,
                                   addition_device_ids=frozenset({1, 2}), bulk_dispatch_enabled=True,
                                   clock=lambda: clock[0])
    return service, agent, clock


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.005)


async def idle(service, agent):
    await until(lambda: len(agent.seen) == 4 and not service._active)


def admitted_removal(bulk, ip, *, device=1, ttl=900):
    """An existing synthetic ordinary request, not a new v2 Web admission path."""
    key, job = str(uuid4()), str(uuid4())
    with bulk[0].store._connection() as db:
        db.execute("INSERT INTO operation_requests VALUES (?,'synthetic:interactive','Synthetic interactive',"
                   "'[\"Operator\"]','manual','{}',?,?,'ACTIVE')",
                   (key, stamp(bulk[1][0]), stamp(bulk[1][0] + timedelta(seconds=ttl))))
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,?,?,'QUEUED',?,'REMOVE')",
                   (job, device, ip.packed, stamp(bulk[1][0])))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job))
    return key, job


def test_default_off_start_status_refresh_stop_do_not_create_database(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = ContinuousDispatcher(store, BlockingAgent())

    async def scenario():
        await service.start()
        assert not service.request_refresh()['running']
        assert service.status()['maintenance']['running'] is False
        await service.stop()
    asyncio.run(scenario())
    assert not store.path.exists()


def test_slow_maintenance_does_not_block_device_reads_or_let_stop_escape(continuous, monkeypatch):
    from threading import Event

    service, agent, _clock = continuous
    entered, release = Event(), Event()
    original = service.runner.queue.prune_completed

    def blocked(days):
        entered.set()
        assert release.wait(5), 'Synthetic maintenance release missing.'
        return original(days)
    monkeypatch.setattr(service.runner.queue, 'prune_completed', blocked)

    async def scenario():
        await service.start()
        assert await asyncio.to_thread(entered.wait, 3)
        stopping = None
        try:
            await idle(service, agent)
            assert service.refresh_status()['maintenance']['phase'] == 'pruning_queue'
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0.03)
            assert not stopping.done() and service._task is not None
            await service.start()  # Cannot create replacement while draining.
            assert service.runner._service_active
        finally:
            release.set()
            if stopping is not None:
                await stopping
            else:
                await service.stop()
        assert not service.maintenance.status()['running']
        assert not service.runner._service_active
        assert service.refresh_status()['last_retention_purge'] is None
    asyncio.run(scenario())


def test_maintenance_error_visible_without_hiding_device_success_or_resuming_policy(continuous, monkeypatch):
    service, agent, clock = continuous
    prune = service.runner.queue.prune_completed
    def failure(_days):
        raise ValueError('Synthetic retained evidence error')
    monkeypatch.setattr(service.runner.queue, 'prune_completed', failure)

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            await until(lambda: service.maintenance.status()['retention_error'] is not None)
            status = service.refresh_status()
            assert 'retained evidence error' in status['last_error']
            assert status['last_successful_refresh'] is not None
            assert status['history_retention_days'] == 366
            assert status['last_retention_purge'] is None
            assert not status['maintenance']['broken']
            assert service._control_state()[2] == 1  # No resume authority from housekeeping.
            monkeypatch.setattr(service.runner.queue, 'prune_completed', prune)
            clock[0] += 60
            service.maintenance._wake.set()
            await until(lambda: service.maintenance.status()['last_retention_purge'] is not None)
            assert service.refresh_status()['history_retention_error'] is None
            assert service.refresh_status()['last_error'] is None
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome', ['UNVERIFIED', 'WAITING_OUTCOME'])
def test_actual_bulk_uncertainty_and_captured_predecessors_survive_maintenance(
        bulk, leases, continuous, cancellation_controls, monkeypatch, outcome):
    from ftd_shun_manager import bulk_waits

    service, agent, _clock = continuous
    root = grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    receipt, _args = cancel_bulk(cancellation_controls, root)
    if outcome == 'WAITING_OUTCOME':
        with monkeypatch.context() as historical_writer:
            historical_writer.setattr(bulk_waits, 'settle_result', lambda *_args: None)
            queue.finish_addition(job['id'], token.owner, 'FAILED')
    else:
        queue.finish_addition(job['id'], token.owner, 'UNVERIFIED')
    queue.finish_cycle(token.owner, 0)
    bulk[1][0] += timedelta(days=400)

    async def scenario():
        # Isolated service-owned maintenance, not scheduler/FTD activation.
        await service.maintenance.start()
        try:
            await until(lambda: service.maintenance.status()['last_retention_purge'] is not None)
        finally:
            await service.maintenance.stop()
    asyncio.run(scenario())
    with service.runner.store._connection() as db:
        row = db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()
        assert row is not None and row[0] == ('FAILED' if outcome == 'WAITING_OUTCOME' else 'UNVERIFIED')
        assert db.execute('SELECT COUNT(*) FROM operation_links WHERE job_id=?', (job['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE job_id=?', (job['id'],)).fetchone()[0] == row[0]
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_cancellations WHERE import_id=?', (root,)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_cancellation_members WHERE job_id=?', (job['id'],)).fetchone()[0] == 1
    assert receipt['counts'] == {'WAITING_OUTCOME': 1}
    assert not agent.seen and not agent.writes  # Retention is not recovery/replay.


def test_malformed_captured_bulk_evidence_refuses_queue_and_history_pruning(
        bulk, leases, continuous, cancellation_controls, monkeypatch):
    service, agent, _clock = continuous
    root = grant(bulk, devices=(1,))
    _token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    cancel_bulk(cancellation_controls, root)
    with queue.store._connection() as db:
        # Corrupt retained authority, not a new admission shortcut.
        db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]'")
    bulk[1][0] += timedelta(days=400)
    history_calls = []
    monkeypatch.setattr(service.runner.store, 'prune_expired_history', lambda *_a, **_kw: history_calls.append(True))

    async def scenario():
        await service.maintenance.start()
        try:
            await until(lambda: service.maintenance.status()['retention_error'] is not None)
            assert service.maintenance.status()['last_retention_purge'] is None
        finally:
            await service.maintenance.stop()
    asyncio.run(scenario())
    assert history_calls == [] and not agent.seen
    with queue.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert db.execute('SELECT COUNT(*) FROM operation_links WHERE job_id=?', (job['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'LEASED'


def test_unexpected_maintenance_failure_stops_controller_without_replacement(continuous, monkeypatch):
    service, agent, _clock = continuous

    def failure(_days):
        raise RuntimeError('Synthetic unexpected maintenance failure')
    monkeypatch.setattr(service.runner.queue, 'prune_completed', failure)

    async def scenario():
        await service.start()
        await until(lambda: service._task.done())
        with pytest.raises(RuntimeError, match='unexpected maintenance failure'):
            await service.stop()
        assert service.runner._broken and not service.runner._service_active
        assert service.maintenance._inflight is None
        with pytest.raises(QueueConflict, match='broken'):
            await service.start()
        assert not agent.writes
    asyncio.run(scenario())


def test_disabled_browser_projection_and_demand_do_not_open_database(tmp_path):
    service = ContinuousDispatcher(Store(tmp_path / 'absent.db'), BlockingAgent())
    first = service.refresh_status()
    assert first['refresh_schedule_mode'] == 'per_device'
    assert first['refresh_enabled'] is False and first['devices'] == {}
    assert first['last_successful_refresh'] is None
    assert service.request_activity()['interactive_refresh_state'] == 'disabled'
    assert not service.runner.store.path.exists()


def test_enabled_projection_missing_storage_refuses_without_creating_file(tmp_path):
    service = ContinuousDispatcher(Store(tmp_path / 'absent.db'), TracedAgent(), enabled=True)
    with pytest.raises(QueueConflict, match='existing storage'):
        service.refresh_status()
    assert not service.runner.store.path.exists()


def test_browser_request_refuses_stopped_coordinator_without_demand(continuous):
    service, agent, _clock = continuous
    with pytest.raises(QueueConflict, match='not accepting'):
        service.request_activity()
    assert service._demands == {} and not agent.seen


def test_committed_state_notification_changes_data_version_without_device_work(continuous):
    service, agent, _clock = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            reads = list(agent.reads)
            first = service.refresh_status()
            from ftd_shun_manager.web import refresh_metadata
            browser = refresh_metadata(first)
            assert browser['refresh_schedule_mode'] == 'per_device'
            assert browser['device_cycles'] == first['device_cycles']
            assert 'execution' not in browser and 'owner' not in browser
            service.note_state_change()
            second = service.refresh_status()
            assert second['data_revision'] == first['data_revision'] + 1
            assert second['status_revision'] > first['status_revision']
            await asyncio.to_thread(service.note_state_change)
            await until(lambda: service.refresh_status()['data_revision'] == second['data_revision'] + 1)
            assert agent.reads == reads
            assert service.refresh_status()['pending_refresh_device_count'] == 0
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_browser_projection_read_only_detached_and_revisions_follow_real_reads(bulk, continuous):
    service, agent, clock = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            before = dump(bulk[0].store)
            first = service.refresh_status()
            assert dump(bulk[0].store) == before
            assert first['cycle_id'] is None and first['device_cycle'] == {}
            assert first['last_successful_refresh'] == min(
                row['last_successful_refresh'] for row in first['devices'].values() if row['state'] != 'disabled')
            assert len(first['devices']) == 10  # Disabled inventory stays visible.
            first['devices']['1']['hostname'] = 'changed detached copy'
            assert service.refresh_status()['devices']['1']['hostname'] != 'changed detached copy'
            pending = service.request_activity()
            assert pending['pending_refresh_device_count'] == 4
            assert pending['interactive_refresh_state'] == 'rate_limited'
            assert pending['data_revision'] == first['data_revision']
            due = service._demands[1].manual_due(60)
            clock[0] += 20
            repeated = service.request_activity()
            assert service._demands[1].manual_due(60) == due
            assert repeated['devices']['1']['manual_refresh_in_seconds'] == 40
            clock[0] += 40
            # Eligibility alone does not confirm anything or reload content.
            eligible = service.refresh_status()
            assert eligible['data_revision'] == first['data_revision']
            assert eligible['pending_refresh_device_count'] == 4
            service.signal_work()
            await until(lambda: service.refresh_status()['pending_refresh_device_count'] == 0)
            fresh = service.refresh_status()
            assert fresh['data_revision'] > first['data_revision']
            assert fresh['status_revision'] > repeated['status_revision']
        finally:
            await service.stop()
        assert not service.refresh_status()['refresh_enabled']
    asyncio.run(scenario())


def test_browser_projection_never_uses_healthy_device_as_fleet_confirmation(continuous):
    service, agent, _clock = continuous
    agent.block_open.add(1)

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            await until(lambda: service._demands[2].last_complete is not None)
            status = service.request_activity()
            assert status['last_successful_refresh'] is None
            assert status['devices']['1']['last_successful_refresh'] is None
            assert status['devices']['2']['last_successful_refresh'] is not None
            assert status['devices']['1']['active'] is True
            assert status['devices']['1']['stale'] is True
            assert status['active_device_count'] >= 1
            assert status['pending_refresh_device_count'] >= 1
            assert status['device_cycle'] == {}  # Never select a random parallel phase.
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_browser_projection_keeps_held_failure_and_unfulfilled_demand(continuous):
    service, agent, clock = continuous
    agent.fail_open.add(1)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'held')
            status = service.request_activity()
            assert status['devices']['1']['state'] == 'error'
            assert status['devices']['1']['refresh_pending'] is True
            assert status['devices']['1']['last_error']
            assert status['last_successful_refresh'] is None
            clock[0] += 301
            later = service.refresh_status()
            assert later['devices']['1']['refresh_pending'] is True
            assert later['devices']['2']['stale'] is True or later['devices']['2']['state'] == 'pending'
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_start_missing_profile_refuses_without_migration_or_rpc(bulk):
    service = ContinuousDispatcher(bulk[0].store, BlockingAgent(), enabled=True)
    before = dump(bulk[0].store)
    with pytest.raises(BulkUnavailable): asyncio.run(service.start())
    assert dump(bulk[0].store) == before and not service.runner.agent.seen


def test_demand_preserves_original_deadline_and_only_complete_read_satisfies():
    demand = ReadDemand(0)
    demand.confirmed(0, 1, 300)
    demand.request(10)
    assert demand.manual_due(60) == 61
    demand.request(30)
    assert demand.pending_since == 10 and demand.manual_due(60) == 61
    demand.confirmed(0, 1, 300)
    assert demand.pending_since == 10
    demand.confirmed(50, 62, 300)
    assert demand.pending_since is None and demand.baseline_due == 362
    demand.request(64)
    assert demand.manual_due(60) == 122


@pytest.mark.parametrize('started,completed', [(3, 2), (0, 0)])
def test_backwards_complete_read_does_not_fabricate_freshness(started, completed):
    demand = ReadDemand(0)
    demand.confirmed(0, 1, 300)
    demand.request(2)
    with pytest.raises(ValueError): demand.confirmed(started, completed, 300)
    assert demand.pending_since == 2 and demand.last_complete == 1


def test_bulk_continues_without_minute_or_baseline_wait_and_does_not_poll_idle_devices(bulk, continuous):
    service, agent, clock = continuous
    grant(bulk, devices=(1,), count=36)

    async def scenario():
        await service.start()
        try:
            await until(lambda: len(agent.writes) == 36 and not service._active)
            assert clock[0] == 1000  # No scheduler/read/queue clock advance to drain the import.
            assert agent.maximum <= 2
            assert all(agent.reads.count(('initial', device)) == 1 for device in (2, 3, 4))
            before = list(agent.reads)
            await asyncio.sleep(0.04)
            assert agent.reads == before
        finally:
            await service.stop()
    asyncio.run(scenario())
    with service.runner.store._connection() as db:
        assert {row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')} == {'VERIFIED'}
    assert all(row['state'] == 'IDLE' for row in service.runner.leases.status()['devices'])


def test_slow_device_does_not_block_next_sessions_on_healthy_device(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(2,), count=20)
    agent.block_open = {1}

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            await until(lambda: len(agent.writes) == 20)
            assert 1 in agent.active and all(device == 2 for device, _ in agent.writes)
            assert agent.maximum == 2
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_manual_refresh_coalesces_and_respects_device_spacing(continuous):
    service, agent, clock = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            service.request_refresh(frozenset({2}))
            clock[0] += 10
            status = service.request_refresh(frozenset({2}))
            assert status['devices']['2']['manual_refresh_in_seconds'] == 50
            assert not status['devices']['1']['refresh_pending']
            clock[0] += 49
            service._wake.set()
            await asyncio.sleep(0.04)
            assert agent.reads.count(('initial', 2)) == 1
            clock[0] += 1
            service._wake.set()
            await until(lambda: agent.reads.count(('initial', 2)) == 2 and not service._active)
            assert not service.status()['devices']['2']['refresh_pending']
            assert service.status()['devices']['2']['baseline_refresh_in_seconds'] == 300
            assert service.status()['devices']['3']['baseline_refresh_in_seconds'] == 240
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_demand_during_initial_read_joins_that_complete_read(continuous):
    service, agent, clock = continuous
    agent.block_open = {1}

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            clock[0] += 5
            assert service.request_refresh(frozenset({1}))['devices']['1']['refresh_pending']
            agent.releases[1].set()
            await idle(service, agent)
            assert not service.status()['devices']['1']['refresh_pending']
            assert agent.reads.count(('initial', 1)) == 1
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_due_refresh_joins_next_checkpoint_after_current_add_verification(bulk, continuous):
    service, agent, clock = continuous
    grant(bulk, devices=(1,), count=3)
    agent.block_add = {1}

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            clock[0] += 60
            service.request_refresh(frozenset({1}))
            await until(lambda: service.runner._workers[1]._priority_pending)
            assert not agent.writes
            agent.releases[1].set()
            await until(lambda: len(agent.writes) == 3 and not service._active)
            ordered = [action for action, device, _ in agent.trace if device == 1 and action != 'open']
            assert ordered == ['add', 'refresh', 'add', 'add']
            assert not service.status()['devices']['1']['refresh_pending']
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_late_manual_remove_preempts_add_backlog_and_checks_current_absence(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(1,), count=3)
    target = IPv4Address('203.0.113.250')
    agent.block_add = {1}

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            # External appearance after the session's initial empty snapshot.
            agent.entries[1].append(ObservedShun(target, 'management'))
            _, job = admitted_removal(bulk, target)
            service.signal_work()
            agent.releases[1].set()
            await until(lambda: len(agent.writes) == 3 and bool(agent.removals) and not service._active)
            ordered = [(action, ip) for action, device, ip in agent.trace if device == 1 and action != 'open']
            assert [action for action, _ in ordered] == ['add', 'remove', 'add', 'add']
            assert ordered[1][1] == target and all(entry.ip != target for entry in agent.entries[1])
            with service.runner.store._connection() as db:
                assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'VERIFIED'
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_protection_enabled_during_add_retires_authority_and_removes_next(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(1,), count=3)
    agent.block_add = {1}
    target = IPv4Address('198.51.100.1')

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            ProtectedPolicy(service.runner.store).change('add', target, 0, 'synthetic:policy', 'Synthetic policy',
                                                         ('Viewer',), managed_revision=1)
            service.signal_work()
            agent.releases[1].set()
            await until(lambda: len(agent.writes) == 3 and bool(agent.removals) and not service._active)
            assert [action for action, device, _ in agent.trace if device == 1 and action != 'open'] == ['add', 'remove', 'add', 'add']
            with service.runner.store._connection() as db:
                assert db.execute('SELECT enabled FROM managed_shun_targets WHERE device_id=1 AND ip=?',
                                  (target.packed,)).fetchone()[0] == 0
            assert all(entry.ip != target for entry in agent.entries[1])
        finally:
            agent.releases[1].set()
            await service.stop()
    asyncio.run(scenario())


def test_stop_drains_current_add_without_executing_rest_of_queue(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(1,), count=3)
    agent.block_add = {1}

    async def scenario():
        await service.start()
        await wait(agent.entered[1])
        stop = asyncio.create_task(service.stop())
        try:
            await asyncio.sleep(0)
            stop.cancel()
            await asyncio.sleep(0)
            stop.cancel()
            await asyncio.sleep(0)
            assert not stop.done() and 1 in agent.active
            with pytest.raises(QueueConflict): service.request_refresh()
        finally:
            agent.releases[1].set()
            with pytest.raises(asyncio.CancelledError): await stop
        assert len(agent.writes) == 1 and not agent.active and not service.status()['running']
    asyncio.run(scenario())
    assert all(row['state'] == 'IDLE' for row in service.runner.leases.status()['devices'])
    with service.runner.store._connection() as db:
        assert sorted(row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')) == ['QUEUED', 'QUEUED', 'VERIFIED']


def test_lost_add_does_not_spin_or_replay_and_healthy_device_continues(bulk, continuous):
    service, agent, clock = continuous
    grant(bulk, count=2)
    agent.fail_add = {1}

    async def scenario():
        await service.start()
        try:
            await until(lambda: len(agent.writes) == 3 and not service._active)
            before = list(agent.reads)
            service.request_refresh(frozenset({1}))
            service._wake.set()
            await asyncio.sleep(0.04)
            assert agent.reads == before and service.status()['devices']['1']['refresh_pending']
            clock[0] += 60  # Now the pending manual read is due despite the held lease.
            service._wake.set()
            await until(lambda: service.runner.status()['devices']['1']['state'] == 'lease_held')
            assert agent.reads == before and len(agent.writes) == 3
        finally:
            await service.stop()
    asyncio.run(scenario())
    with service.runner.store._connection() as db:
        assert dict(db.execute('SELECT device_id,COUNT(*) FROM managed_bulk_attempts WHERE state=\'VERIFIED\' GROUP BY device_id')) == {2: 2}
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='UNVERIFIED'").fetchone()[0] == 1


def test_status_is_detached_and_never_wakes_or_initializes(continuous):
    service, agent, _ = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            before, reads = dump(service.runner.store), list(agent.reads)
            status = service.status()
            assert status['execution']['running'] and status['execution']['execution_mode'] == 'continuous'
            status['devices']['1']['refresh_pending'] = True
            status['execution']['cycles']['1']['action'] = 'invented'
            assert not service.status()['devices']['1']['refresh_pending']
            assert service.status()['execution']['cycles']['1']['action'] == 'completed'
            assert dump(service.runner.store) == before and agent.reads == reads
            with pytest.raises(QueueConflict): await service.runner.sweep()
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('devices', [frozenset({True}), {1}, frozenset({5})])
def test_invalid_refresh_scope_does_not_create_demand(continuous, devices):
    service, agent, _ = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            with pytest.raises(ValueError): service.request_refresh(devices)
            assert all(not row['refresh_pending'] for row in service.status()['devices'].values())
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_nonliteral_priority_configuration_never_creates_state(bulk, leases):
    token = leases.claim(1, str(uuid4()), 135, enabled=True)
    before = dump(leases.store)
    with pytest.raises(ValueError): DeviceOperationQueue(leases.store, token, priority_removals=1)
    assert dump(leases.store) == before


def test_work_signal_without_committed_work_does_not_poll_idle_devices(continuous):
    service, agent, _ = continuous

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            before = list(agent.reads)
            service.signal_work()
            await asyncio.sleep(0.04)
            assert agent.reads == before and not service._active
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('priority', [False, True])
def test_removal_cutoff_bypass_is_scoped_opt_in_and_preserves_remove_fifo(bulk, leases, priority):
    grant(bulk, devices=(1,), count=2)
    token, old_queue = acquire(leases)
    assert discover(bulk, old_queue) == 2
    queue = DeviceOperationQueue(leases.store, token, priority_removals=priority)
    cutoff = queue.cutoff()
    _, first = admitted_removal(bulk, IPv4Address('203.0.113.249'))
    _, second = admitted_removal(bulk, IPv4Address('203.0.113.250'))
    job = queue.claim_next_mutation(1, token.owner, cutoff, additions_enabled=True, bulk_dispatch_enabled=True)
    if priority:
        assert job['id'] == first
        queue.finish_removal(first, token.owner, 'NOOP')
        assert queue.claim_next_mutation(1, token.owner, cutoff, additions_enabled=True,
                                         bulk_dispatch_enabled=True)['id'] == second
    else:
        assert job['action'] == 'ADD' and job['seq'] <= cutoff


@pytest.mark.parametrize('invalid', ['expired', 'cancelled', 'no_role'])
def test_removal_priority_does_not_bypass_request_authorization(bulk, leases, invalid):
    grant(bulk, devices=(1,))
    token, old_queue = acquire(leases)
    assert discover(bulk, old_queue) == 1
    queue = DeviceOperationQueue(leases.store, token, priority_removals=True)
    cutoff = queue.cutoff()
    key, removed = admitted_removal(bulk, IPv4Address('203.0.113.250'))
    with leases.store._connection() as db:
        if invalid == 'expired':
            db.execute('UPDATE operation_requests SET expires_at=? WHERE id=?', (stamp(bulk[1][0]), key))
        elif invalid == 'cancelled':
            db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (key,))
        else:
            db.execute("UPDATE operation_requests SET actor_roles_json='[]' WHERE id=?", (key,))
    job = queue.claim_next_mutation(1, token.owner, cutoff, additions_enabled=True, bulk_dispatch_enabled=True)
    assert job['action'] == 'ADD'
    with leases.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (removed,)).fetchone()[0] != 'RUNNING'


def test_exact_deferral_has_short_backoff_without_a_busy_loop(bulk, continuous):
    service, agent, clock = continuous
    grant(bulk, devices=(1,), count=2)
    agent.defer = True

    async def scenario():
        await service.start()
        try:
            await until(lambda: len(agent.writes) == 1 and not service._active)
            before = list(agent.reads)
            service._wake.set()
            await asyncio.sleep(0.04)
            assert agent.reads == before
            agent.defer = False
            clock[0] += 5
            service._wake.set()
            await until(lambda: len(agent.writes) == 3 and not service._active)
        finally:
            await service.stop()
    asyncio.run(scenario())
    with service.runner.store._connection() as db:
        assert {row[0] for row in db.execute('SELECT state FROM managed_bulk_attempts')} == {'VERIFIED'}


def test_pause_allows_reads_but_not_add_then_work_hint_gets_fresh_evidence(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(1,))
    with service.runner.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')

    async def scenario():
        await service.start()
        try:
            await idle(service, agent)
            assert not agent.writes
            with service.runner.store._connection() as db:
                db.execute('UPDATE operation_executor SET mutations_suspended=0')  # Synthetic fixture only.
            service.signal_work()
            await until(lambda: len(agent.writes) == 1 and not service._active)
            assert agent.reads.count(('initial', 1)) >= 3  # Pause read, fresh admission, execution.
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_restart_same_controller_requires_fresh_reads_without_replaying_work(bulk, continuous):
    service, agent, _ = continuous
    grant(bulk, devices=(1,))

    async def scenario():
        await service.start()
        await until(lambda: len(agent.writes) == 1 and not service._active)
        await service.stop()
        reads = {device: agent.reads.count(('initial', device)) for device in range(1, 5)}
        await service.start()
        try:
            await until(lambda: all(agent.reads.count(('initial', device)) > reads[device] for device in reads)
                        and not service._active)
            assert len(agent.writes) == 1
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_forced_dispatcher_cancellation_drains_and_refuses_restart(continuous):
    service, agent, _ = continuous
    agent.block_open = {1}

    async def scenario():
        await service.start()
        try:
            await wait(agent.entered[1])
            service._task.cancel()
            await asyncio.sleep(0)
            assert not service._task.done() and service.runner._broken
        finally:
            agent.releases[1].set()
            with pytest.raises(asyncio.CancelledError): await service.stop()
        assert not agent.active
        with pytest.raises(QueueConflict): await service.start()
    asyncio.run(scenario())
