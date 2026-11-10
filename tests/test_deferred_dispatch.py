"""Continuous deferred scheduling on disposable state and synthetic SSH only."""

import asyncio
from datetime import datetime, timedelta
from threading import Event
from time import monotonic

import pytest
from test_batch_session import states
from test_bulk_policy import dump
from test_continuous_dispatch import until
from test_deferred_worker import Agent
from test_deferred_worker import bulk as bulk_fixture
from test_deferred_worker import cancellation_controls as cancellation_fixture
from test_deferred_worker import dispatch as dispatch_fixture
from test_deferred_worker import execution as execution_fixture
from test_deferred_worker import journal as journal_fixture
from test_deferred_worker import leases as leases_fixture
from test_deferred_worker import ledger as ledger_fixture
from test_deferred_worker import waits as waits_fixture
from test_device_leases import grant
from test_parallel_synchronizer import wait

from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
from ftd_shun_manager.deferred_dispatch import DeferredContinuousDispatcher
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture


@pytest.fixture
def runtime(bulk, execution, monkeypatch):
    grant(bulk, (1,), count=12)
    with execution.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>1')
    started, offset = monotonic(), [0]
    monkeypatch.setattr(OperationQueue, '_now', staticmethod(
        lambda: bulk[1][0] + timedelta(seconds=monotonic() - started)))
    monkeypatch.setattr('ftd_shun_manager.continuous_dispatch.RECHECK_SECONDS', 0.01)
    agent = Agent()
    service = DeferredContinuousDispatcher(execution.store, agent, enabled=True,
        addition_device_ids=frozenset({1}), agent_concurrency=2,
        clock=lambda: 1000 + offset[0] + monotonic() - started)

    def tick(seconds):
        bulk[1][0] += timedelta(seconds=seconds)
        offset[0] += seconds
        service.signal_work()
    return service, agent, tick


def test_disabled_never_opens_storage(tmp_path):
    service = DeferredContinuousDispatcher(Store(tmp_path / 'absent.db'), object())
    asyncio.run(service.start())
    assert not service.runner.store.path.exists()
    assert service.status()['deferred_confirmation'] == {}


def test_ordered_promotion_refuses_before_storage(tmp_path):
    with pytest.raises(ValueError, match='ordered'):
        DeferredContinuousDispatcher(Store(tmp_path / 'absent.db'), Agent(), ordered_promotion_enabled=True)
    assert not (tmp_path / 'absent.db').exists()


def test_current_coordinator_still_refuses_v7(runtime):
    service, agent, _ = runtime
    current = ContinuousDispatcher(service.runner.store, agent, enabled=True, addition_device_ids=frozenset({1}))
    with pytest.raises(QueueConflict, match='explicit deferred worker'):
        asyncio.run(current.start())
    assert not agent.seen


def test_automatically_confirms_without_manual_hint_or_baseline_wait(runtime):
    service, agent, _ = runtime

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            assert len(agent.writes) == 12
            assert sum(step[0] == 'open' for step in agent.trace) == 2
            assert service.status()['devices']['1']['baseline_refresh_in_seconds'] > 290
            assert not service.status()['devices']['1']['refresh_pending']
            assert service.runner.leases.status()['devices'][0]['state'] == 'IDLE'
            assert service.refresh_status()['deferred_confirmation']['1']['awaiting_confirmation'] == 0
            from ftd_shun_manager.web import refresh_metadata
            before = dump(service.runner.store)
            metadata = refresh_metadata(service.refresh_status())
            assert metadata['deferred_confirmation']['1']['awaiting_confirmation'] == 0
            assert dump(service.runner.store) == before
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_known_absence_automatically_waits_then_uses_new_jobs(runtime):
    service, agent, tick = runtime
    original = agent.open_tracked_cycle
    dropped = []

    def opening(device, owner):
        session = original(device, owner)
        finish = session.finish_pending_additions

        def end():
            receipt = finish()
            if not dropped:
                agent.entries[device] = []
                dropped.append(True)
            return receipt
        session.finish_pending_additions = end
        return session
    agent.open_tracked_cycle = opening

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12} and not service._active
                        and service.status()['deferred_confirmation'].get('1', {}).get('retry_at'))
            sample = service.refresh_status()['deferred_confirmation']['1']
            assert 0 < sample['retry_in_seconds'] <= 5 and sample['counts_are_sampled']
            before = len(agent.reads)
            await asyncio.sleep(0.1)
            assert len(agent.reads) == before and len(agent.writes) == 12
            tick(6)
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12, 'OBSERVED_PRESENT': 12}
                        and not service._active)
            assert len(agent.writes) == 24
            assert service.runner.queue.status()['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 0}
            with service.runner.store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 12
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_unknown_terminal_is_not_a_confirmation_timer_or_retry_permission(runtime):
    service, agent, tick = runtime
    agent.pending_failure = 'lost'

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner).get('UNVERIFIED') == 12 and not service._active)
            before = len(agent.writes)
            tick(61)
            await asyncio.sleep(0.1)
            assert len(agent.writes) == before
            assert service.runner.leases.status()['devices'][0]['state'] != 'IDLE'
            with service.runner.store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
                assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 0
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_startup_confirms_retained_handoff_even_while_mutations_are_paused(runtime):
    service, agent, tick = runtime

    async def scenario():
        service.runner._snapshot_callback = None
        device = next(device for device in service.runner.store.list_devices() if device.id == 1)
        await service.runner._visit(device)
        service.runner._snapshot_callback = service._confirmed
        assert states(service.runner) == {'AWAITING_CONFIRMATION': 12}
        with service.runner.store._connection() as db:
            db.execute('UPDATE operation_executor SET mutations_suspended=1')
        tick(1)
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            assert len(agent.writes) == 12
            assert service.refresh_status()['deferred_confirmation']['1']['mutations_paused']
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_pending_settlement_does_not_satisfy_refresh_or_reset_its_baseline(runtime):
    service, agent, tick = runtime
    original = agent.open_tracked_cycle
    entered, release = Event(), Event()

    def opening(device, owner):
        session = original(device, owner)
        finish = session.finish_pending_additions

        def end():
            entered.set()
            assert release.wait(5), 'Synthetic pending terminal was not released'
            return finish()
        session.finish_pending_additions = end
        return session
    agent.open_tracked_cycle = opening

    async def scenario():
        await service.start()
        try:
            await wait(entered)
            demand = service._demands[1]
            before = (demand.last_complete, demand.baseline_due)
            tick(61)
            service.request_refresh(frozenset({1}))
            await until(lambda: demand.pending_since is not None)
            assert (demand.last_complete, demand.baseline_due) == before
            assert agent.reads == [('initial', 1)]
            release.set()
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            assert demand.pending_since is None
            assert demand.last_complete > before[0] and demand.baseline_due > before[1]
            assert len(agent.writes) == 12
        finally:
            release.set()
            await service.stop()
    asyncio.run(scenario())


def test_confirmation_read_must_start_after_ms_precision_settlement(runtime, monkeypatch):
    service, agent, _ = runtime
    service.runner._snapshot_callback = None
    asyncio.run(service.runner._visit(next(device for device in service.runner.store.list_devices() if device.id == 1)))
    with service.runner.store._connection() as db:
        settled = datetime.fromisoformat(db.execute('SELECT MAX(settled_at) FROM managed_bulk_pending_sessions').fetchone()[0])
    monkeypatch.setattr(OperationQueue, '_now', staticmethod(lambda: settled))
    assert not service._read_ready(1, service.clock())
    assert service._deferred_samples['1']['confirmation_in_seconds'] == 0.001
    monkeypatch.setattr(OperationQueue, '_now', staticmethod(lambda: settled + timedelta(milliseconds=1)))
    assert service._read_ready(1, service.clock())
    assert service._scheduled_read_due(1, service.clock())
    assert len(agent.writes) == 12 and states(service.runner) == {'AWAITING_CONFIRMATION': 12}


def test_bounded_advisory_scan_wraps_without_granting_work(runtime, monkeypatch):
    service, agent, _ = runtime
    before = dump(service.runner.store)
    now = service.runner.queue._now()
    future, due = (now + timedelta(seconds=60)).isoformat(), now.isoformat()
    # Synthetic selection/timing only; no fake permission or job is submitted.
    candidates = [{'ip': index.to_bytes(4, 'big')} for index in range(1, 66)]
    calls = []

    def sample(db, device, after):
        calls.append(after)
        return [row for row in candidates if row['ip'] > after][:65]
    monkeypatch.setattr('ftd_shun_manager.deferred_dispatch.retry_candidates', sample)
    monkeypatch.setattr('ftd_shun_manager.deferred_dispatch.retry_window',
        lambda db, row, stamp: (None, None, None, due if row['ip'] == candidates[-1]['ip'] else future))
    assert service._read_ready(1, service.clock())
    assert not service._scheduled_read_due(1, service.clock())
    assert service._deferred_samples['1']['checked_retry_candidates'] == 64
    assert service._read_ready(1, service.clock())
    assert service._scheduled_read_due(1, service.clock())
    assert service._deferred_samples['1']['checked_retry_candidates'] == 1
    assert service._deferred_cursors[1] == b'' and calls == [b'', candidates[63]['ip']]
    assert dump(service.runner.store) == before and not agent.seen
