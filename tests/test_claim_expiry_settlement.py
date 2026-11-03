"""Expired local claims must not strand already verified session work."""

import asyncio
from datetime import timedelta

import pytest
from test_continuous_dispatch import continuous as continuous_fixture
from test_device_leases import grant
from test_parallel_synchronizer import bulk as bulk_fixture
from test_parallel_synchronizer import cancellation_controls as cancellation_fixture
from test_parallel_synchronizer import dispatch as dispatch_fixture
from test_parallel_synchronizer import journal as journal_fixture
from test_parallel_synchronizer import leases as leases_fixture
from test_parallel_synchronizer import waits as waits_fixture

from ftd_shun_manager.device_leases import DeviceOperationQueue
from ftd_shun_manager.operation_queue import QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
continuous = continuous_fixture


@pytest.mark.parametrize('fault', ['evidence', 'lease', 'generic'])
def test_only_rolled_back_eligibility_expiry_finishes_prior_verified_work(continuous, bulk, monkeypatch, fault):
    service, agent, _ = continuous
    runner = service.runner
    runner._snapshot_callback = None  # Exercise explicit rounds, not an unstarted lifecycle's demand map.
    grant(bulk, devices=(1,), count=2)
    device = next(device for device in runner.store.list_devices() if device.id == 1)
    original = DeviceOperationQueue._event
    claimed = 0

    def late(self, db, event, request, job, details=None):
        nonlocal claimed
        original(self, db, event, request, job, details)
        if event == 'SHUN_OPERATION_RUNNING':
            claimed += 1
            if claimed == 2:
                if fault == 'generic':
                    raise QueueConflict('Synthetic untyped local claim failure')
                bulk[1][0] += timedelta(seconds=121 if fault == 'evidence' else 301)

    monkeypatch.setattr(DeviceOperationQueue, '_event', late)

    async def scenario():
        await runner._visit(device)  # Fresh evidence admits work after frozen cutoff.
        await runner._visit(device)  # One VERIFIED ADD, then a rolled-back claim.

    asyncio.run(scenario())
    assert len(agent.writes) == 1, 'The rejected claim must never reach the agent'
    with runner.store._connection() as db:
        assert dict(db.execute('SELECT state,COUNT(*) FROM operation_jobs GROUP BY state')) == {'QUEUED': 1, 'VERIFIED': 1}
        assert dict(db.execute('SELECT state,COUNT(*) FROM managed_bulk_attempts GROUP BY state')) == {'QUEUED': 1, 'VERIFIED': 1}
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING'").fetchone()[0] == 1
    worker = runner._workers[1]
    if fault != 'evidence':
        assert not worker.session_settled
        assert runner.leases.status()['devices'][0]['state'] != 'IDLE'
        return
    assert worker.session_settled and not worker.rpc_failed
    assert worker._device_cycle['budget_deferred']
    assert runner.leases.status()['devices'][0]['state'] == 'IDLE'
    # A later fresh session may cancel the obsolete unstarted delegation and
    # admit new work under standing consent; it never replays the rejected claim.
    bulk[1][0] += timedelta(seconds=301)

    async def resume():
        for _ in range(3):
            bulk[1][0] += timedelta(seconds=1)
            await runner._visit(device)

    asyncio.run(resume())
    assert len(agent.writes) == 2
    with runner.store._connection() as db:
        assert dict(db.execute('SELECT state,COUNT(*) FROM managed_bulk_attempts GROUP BY state')) == {'CANCELLED': 1, 'VERIFIED': 2}
    assert runner.leases.status()['devices'][0]['state'] == 'IDLE'
