"""Scoped advisory scans after real standing consent, with synthetic RPCs only."""

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from test_bulk_preparation_api import ACTOR, PREFIX, proposal, stage
from test_configured_managed import configured as configured_fixture
from test_continuous_dispatch import TracedAgent, until
from test_dev_init import fresh as fresh_fixture
from test_dev_init import inventory as inventory_fixture

from ftd_shun_manager.agent_client import UnixAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher, ReadDemand
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.store import Store

configured = configured_fixture
fresh = fresh_fixture
inventory = inventory_fixture


def scheduler(tmp_path, clock):
    return ContinuousDispatcher(Store(tmp_path / 'absent.db'), TracedAgent(), clock=lambda: clock[0],
                                bulk_dispatch_enabled=True, addition_device_ids=frozenset({1, 2}))


@pytest.mark.parametrize('scope', [None, {1}, frozenset(), frozenset({True}), frozenset({0}),
                                 frozenset({65536}), frozenset({3}), frozenset({'1'})])
def test_scope_is_literal_bounded_profiled_and_never_initializes(tmp_path, scope):
    service = scheduler(tmp_path, [1000.0])
    with pytest.raises(ValueError): service.request_policy_scan(scope)
    assert not service.runner.store.path.exists() and not service._policy_scans


def test_disabled_bulk_and_unstarted_or_stopping_lifecycle_do_not_schedule(tmp_path):
    disabled = ContinuousDispatcher(Store(tmp_path / 'disabled.db'), TracedAgent())
    with pytest.raises(ValueError): disabled.request_policy_scan(frozenset({1}))
    service = scheduler(tmp_path, [1000.0])
    service.request_policy_scan(frozenset({1}))
    assert not service._policy_scans and not service.runner.store.path.exists()

    async def scenario():
        service._loop, service._task = asyncio.get_running_loop(), asyncio.current_task()
        service._stopping = True
        service.request_policy_scan(frozenset({1}))
        await asyncio.sleep(0)
        assert not service._policy_scans
    asyncio.run(scenario())


def test_cross_thread_latest_notification_needs_a_strictly_new_read(tmp_path):
    clock = [1000.0]
    service = scheduler(tmp_path, clock)

    async def scenario():
        service._loop, service._task = asyncio.get_running_loop(), asyncio.current_task()
        service._enabled = {1, 2}
        service._demands = {device: ReadDemand(1300, last_complete=1000) for device in (1, 2)}
        await asyncio.to_thread(service.request_policy_scan, frozenset({1}))
        await until(lambda: 1 in service._policy_scans)
        first = service._policy_scans[1]
        assert service._policy_scan_due(1) == 1060 and service._policy_scan_due(2) is None
        clock[0] = 1010
        service.request_policy_scan(frozenset({1}))
        await asyncio.sleep(0)
        latest = service._policy_scans[1]
        assert latest > first and len(service._policy_scans) == 1
        # An in-flight read, or even an equal-precision start, is insufficient.
        service._confirmed(1, 1005, 1010)
        assert service._policy_scans[1] == latest and service._policy_scan_due(1) == 1070
        clock[0] = 1011
        service._confirmed(1, latest, 1011)
        assert 1 in service._policy_scans
        clock[0] = 1012
        service._confirmed(1, latest + 0.001, 1012)
        assert not service._policy_scans
        assert service._demands[2].baseline_due == 1300
    asyncio.run(scenario())
    assert not service.runner.store.path.exists()


def test_configured_confirmation_scans_after_floor_without_manual_refresh(configured, monkeypatch):
    settings, store = configured
    fake, offset = TracedAgent(), [0.0]
    monkeypatch.setattr(OperationQueue, '_now', lambda _self: datetime.now(UTC) + timedelta(seconds=offset[0]))
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', lambda _self, device: fake.open_cycle(device))
    app = create_app(settings)
    service = app.state.synchronizer.dispatcher
    service.clock = service.runner._clock = lambda: monotonic() + offset[0]

    async def scenario():
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url='http://internal') as client:
            await until(lambda: fake.seen == {1} and not service._active)
            before = list(fake.trace)
            saved = await stage(client, text='198.51.100.254')
            assert saved.status_code == 201
            key = str(uuid4())
            proposed = (await proposal(client, saved.json(), key=key)).json()
            payload = {'actor': ACTOR, 'canonical': proposed['canonical'], 'digest': proposed['digest'],
                       'accepted_count': 1, 'maintain_present': True, 'expected_suspended': False}
            endpoint, headers = PREFIX + 'confirm-concurrent', {'Idempotency-Key': key}
            result = await client.post(endpoint, json=payload, headers=headers)
            assert result.status_code == 200, result.text
            await until(lambda: 1 in service._policy_scans)
            first = service._policy_scans[1]
            replay = await client.post(endpoint, json=payload, headers=headers)
            assert replay.json()['replayed'] and service._policy_scans[1] == first
            invalid = await client.post(endpoint, json=payload | {'maintain_present': False},
                                        headers={'Idempotency-Key': str(uuid4())})
            assert invalid.status_code == 422 and service._policy_scans[1] == first
            unchanged = (await stage(client, text='198.51.100.254')).json()
            other_key = str(uuid4())
            other = (await proposal(client, unchanged, key=other_key)).json()
            same = await client.post(endpoint, headers={'Idempotency-Key': other_key}, json={**payload,
                'canonical': other['canonical'], 'digest': other['digest']})
            assert same.status_code == 200 and same.json()['changed_targets'] == 0
            assert service._policy_scans[1] == first  # A new receipt with unchanged policy is not new demand.
            await asyncio.sleep(0.03)
            assert fake.trace == before and not fake.writes  # No 60s floor bypass.
            offset[0] += 61
            # No refresh POST or signal_work: the ordinary dispatcher loop sees demand.
            await until(lambda: 1 not in service._policy_scans and not service._active)
            assert sum(row[0] == 'open' for row in fake.trace) >= 2
            assert service._demands[1].baseline_due - service.clock() > 250
            if not fake.writes:
                offset[0] += 61
            await until(lambda: len(fake.writes) == 1 and not service._active)
            assert not service._policy_scans and len(fake.entries[1]) == 1
            with store._connection() as db:
                assert db.execute('SELECT action,state FROM operation_jobs').fetchone()[:] == ('ADD', 'VERIFIED')
    asyncio.run(scenario())


@pytest.mark.parametrize('problem', ['held_lease', 'failed_read'])
def test_advisory_scan_retains_demand_without_stealing_or_replaying(configured, monkeypatch, problem):
    settings, _store = configured
    fake, offset, calls = TracedAgent(), [0.0], []
    monkeypatch.setattr(OperationQueue, '_now', lambda _self: datetime.now(UTC) + timedelta(seconds=offset[0]))
    def open_cycle(_self, device):
        calls.append(device)
        return fake.open_cycle(device)
    monkeypatch.setattr(UnixAgentClient, 'open_cycle', open_cycle)
    app = create_app(settings)
    service = app.state.synchronizer.dispatcher
    service.clock = service.runner._clock = lambda: monotonic() + offset[0]

    async def scenario():
        async with app.router.lifespan_context(app):
            await until(lambda: fake.seen == {1} and not service._active)
            offset[0] += 61
            if problem == 'held_lease':
                token = service.runner.leases.claim(1, str(uuid4()), 135, enabled=True)
                assert token is not None
            else:
                fake.fail_open.add(1)
            service.request_policy_scan(frozenset({1}))
            await until(lambda: service.runner._results.get('1', {}).get('state') in {'held', 'lease_held'}
                        and not service._active)
            assert 1 in service._policy_scans and not fake.writes
            if problem == 'held_lease':
                assert calls == [1]  # No SSH/RPC while somebody else's fence is held.
                service.runner.leases.release(token)
                offset[0] += 61
                await until(lambda: 1 not in service._policy_scans and not service._active)
                assert calls == [1, 1]
            else:
                assert calls == [1, 1]
                offset[0] += 10
                await asyncio.sleep(1.1)
                assert calls == [1, 1] and 1 in service._policy_scans  # Failed read retains the fence.
    asyncio.run(scenario())
