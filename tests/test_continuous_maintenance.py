"""Owning-service maintenance on disposable SQLite, without device authority."""

import asyncio
from datetime import timedelta
from threading import Event

import pytest
from test_operation_queue import enqueue
from test_operation_queue import queue as queue_fixture

from ftd_shun_manager.continuous_maintenance import ContinuousMaintenance
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Store

queue = queue_fixture


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
def maintenance(queue):
    clock, changes = [1000.0], []
    service = ContinuousMaintenance(queue, enabled=True, clock=lambda: clock[0],
                                    on_change=lambda: changes.append(True))
    return service, clock, changes


def test_default_disabled_and_missing_storage_do_not_initialize(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = ContinuousMaintenance(OperationQueue(store))

    async def scenario():
        await service.start()
        assert service.status()['running'] is False
        await service.stop()
        enabled = ContinuousMaintenance(OperationQueue(store), enabled=True)
        with pytest.raises(QueueConflict, match='existing storage'):
            await enabled.start()
    asyncio.run(scenario())
    assert not store.path.exists()


@pytest.mark.parametrize('configuration', [{'enabled': 1}, {'history_retention_days': True},
    {'history_retention_days': 0}, {'history_retention_days': 3654}, {'history_retention_days': '366'}])
def test_literal_configuration_refuses_before_storage(tmp_path, configuration):
    store = Store(tmp_path / 'absent.db')
    with pytest.raises(ValueError): ContinuousMaintenance(OperationQueue(store), **configuration)
    assert not store.path.exists()


def test_single_lifecycle_expiry_daily_retention_and_detached_status(queue, maintenance, monkeypatch):
    service, clock, changes = maintenance
    calls = []
    for name, owner in [('expire_requests', queue), ('prune_completed', queue), ('prune_expired_history', queue.store)]:
        original = getattr(owner, name)

        def record(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(owner, name, record)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.status()['last_retention_purge'] is not None)
            await service.start()  # No competing owner/task or extra pass.
            assert calls == ['expire_requests', 'prune_completed', 'prune_expired_history']
            status = service.status()
            status['phase'] = 'fake'
            assert service.status()['phase'] != 'fake'
            assert changes == []  # Idle housekeeping does not reload Web content.
            clock[0] += 4
            service._wake.set()
            await asyncio.sleep(0.03)
            assert len(calls) == 3
            clock[0] += 1
            service._wake.set()
            await until(lambda: calls.count('expire_requests') == 2)
            # The trace records thread entry, not completion. Keep the fake
            # clock stable until _expire has published its next deadline;
            # otherwise its +5s schedule may be based on the following day.
            await until(lambda: service.status()['phase'] == 'idle'
                        and service.status()['next_expiry_in_seconds'] == 5)
            assert calls.count('prune_completed') == 1
            clock[0] += 86400
            service._wake.set()
            await until(lambda: calls.count('prune_expired_history') == 2)
            await until(lambda: service.status()['phase'] == 'idle')
        finally:
            await service.stop()
        await service.start()  # Same owner retains its daily retention deadline.
        await until(lambda: calls.count('expire_requests') == 4)
        assert calls.count('prune_completed') == 2
        await service.stop()
    asyncio.run(scenario())


def test_expired_unsent_request_settles_without_claim_or_device_read(queue, maintenance):
    key = enqueue(queue)['operation_id']
    queue.test_clock[0] += timedelta(hours=1)
    service, _, changes = maintenance

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.status()['last_retention_purge'] is not None)
        finally:
            await service.stop()
    asyncio.run(scenario())
    assert queue.status()['counts'] == {'FAILED': 1}  # Original ordinary contract.
    assert changes
    with queue.store._connection() as db:
        assert db.execute('SELECT state FROM operation_requests WHERE id=?', (key,)).fetchone()[0] == 'EXPIRED'
        assert db.execute('SELECT started_at FROM operation_jobs').fetchone()[0] is None


def test_retention_removes_old_terminal_work_but_preserves_unknown_original_evidence(queue, maintenance):
    enqueue(queue)
    assert queue.claim_cycle('synthetic-maintenance', 135)
    first = queue.claim_removal(1, 'synthetic-maintenance', queue.cutoff())
    queue.finish_removal(first['id'], 'synthetic-maintenance', 'VERIFIED')
    key = enqueue(queue, ip='198.51.100.11')['operation_id']
    held = queue.claim_removal(1, 'synthetic-maintenance', queue.cutoff())
    queue.finish_removal(held['id'], 'synthetic-maintenance', 'UNVERIFIED')
    queue.finish_cycle('synthetic-maintenance', 60)
    queue.test_clock[0] += timedelta(days=367)
    service, _, changes = maintenance

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.status()['last_retention_purge'] is not None)
        finally:
            await service.stop()
    asyncio.run(scenario())
    assert queue.status()['counts'] == {'UNVERIFIED': 1}
    with queue.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_links WHERE request_id=? AND job_id=?', (key, held['id'])).fetchone()[0] == 1
    assert changes and enqueue(queue, request_id=key, ip='198.51.100.11')['replayed']


@pytest.mark.parametrize('stage', ['expiry', 'queue', 'history'])
def test_failure_backoff_skips_unsafe_history_and_recovers_without_rearm(queue, maintenance, monkeypatch, capsys, stage):
    service, clock, _changes = maintenance
    owner, name = (queue.store, 'prune_expired_history') if stage == 'history' else (
        queue, 'expire_requests' if stage == 'expiry' else 'prune_completed')
    original, calls, history = getattr(owner, name), [], []
    prune = queue.store.prune_expired_history
    monkeypatch.setattr(queue.store, 'prune_expired_history', lambda *a, **kw: (history.append(True), prune(*a, **kw))[1])

    def failure(*_args, **_kwargs):
        calls.append(True)
        raise ValueError('Synthetic evidence validation failure')
    monkeypatch.setattr(owner, name, failure)

    async def scenario():
        await service.start()
        try:
            field = 'expiry_error' if stage == 'expiry' else 'retention_error'
            await until(lambda: service.status()[field] is not None and service.status()['phase'] == 'idle')
            if stage == 'queue': assert history == []
            if stage != 'expiry': assert service.status()['last_retention_purge'] is None
            clock[0] += 59
            service._wake.set()
            await asyncio.sleep(0.03)
            assert len(calls) == 1
            monkeypatch.setattr(owner, name, original)
            clock[0] += 1
            service._wake.set()
            await until(lambda: service.status()[field] is None)
            assert not service.status()['broken']
        finally:
            await service.stop()
    asyncio.run(scenario())
    assert 'maintenance.' in capsys.readouterr().out


@pytest.mark.parametrize('forced', [False, True])
def test_stop_cancellation_drains_single_thread_without_another_stage_or_replacement(queue, maintenance, monkeypatch, forced):
    service, _, _changes = maintenance
    entered, release = Event(), Event()
    calls = []
    original = queue.prune_completed

    def blocked(days):
        calls.append('queue')
        entered.set()
        assert release.wait(5), 'Synthetic maintenance release missing.'
        return original(days)
    monkeypatch.setattr(queue, 'prune_completed', blocked)
    monkeypatch.setattr(queue.store, 'prune_expired_history', lambda *_a, **_kw: calls.append('history'))

    async def scenario():
        await service.start()
        assert await asyncio.to_thread(entered.wait, 3)
        if forced:
            task = service._task
            task.cancel()
        else:
            task = asyncio.create_task(service.stop())
        try:
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done() and service._inflight is not None
            await service.start()
            assert calls == ['queue']
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError): await task
        if forced:
            with pytest.raises(asyncio.CancelledError): await service.stop()
            with pytest.raises(QueueConflict, match='cancelled'): await service.start()
        assert service.status()['last_retention_purge'] is None
        assert service.status()['broken'] is forced
        assert calls == ['queue']  # Never launch history after shutdown began.
    asyncio.run(scenario())
