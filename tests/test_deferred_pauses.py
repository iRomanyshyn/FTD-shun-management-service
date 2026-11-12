"""Real pause ledgers and deferred scheduling with synthetic device sessions."""

import asyncio
from uuid import uuid4

import pytest
from test_batch_session import states
from test_bulk_protection import protect
from test_continuous_dispatch import until
from test_deferred_dispatch import bulk as bulk_fixture
from test_deferred_dispatch import cancellation_controls as cancellation_fixture
from test_deferred_dispatch import dispatch as dispatch_fixture
from test_deferred_dispatch import execution as execution_fixture
from test_deferred_dispatch import journal as journal_fixture
from test_deferred_dispatch import leases as leases_fixture
from test_deferred_dispatch import ledger as ledger_fixture
from test_deferred_dispatch import runtime as runtime_fixture
from test_deferred_dispatch import waits as waits_fixture

from ftd_shun_manager.managed_addition_controls import ManagedAdditionControls, read
from ftd_shun_manager.protected_policy import ProtectedPolicy

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
runtime = runtime_fixture
waits = waits_fixture


@pytest.fixture
def controls(runtime):
    service, _, _ = runtime
    result = ManagedAdditionControls(service.runner.store, clock=service.runner.queue._now)
    result.initialize()
    return result


def change(controls, kind, action):
    with controls.store._connection() as db:
        revision = read(db)[kind]['revision']
    return controls.change(str(uuid4()), kind, action, revision, 'pause-fixture', 'Synthetic operator', ('Operator',))


def drop_group(agent, ordinal=1):
    original, count = agent.open_tracked_cycle, [0]

    def opening(device, owner):
        session = original(device, owner)
        finish = session.finish_pending_additions

        def pending():
            receipt = finish()
            count[0] += 1
            if count[0] == ordinal:
                agent.entries[device] = []
            return receipt
        session.finish_pending_additions = pending
        return session
    agent.open_tracked_cycle = opening


def test_paused_import_retry_does_not_spin_reads_but_manual_refresh_and_resume_work(runtime, controls):
    service, agent, tick = runtime
    drop_group(agent)

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12} and not service._active)
            change(controls, 'imports', 'PAUSE')
            before = list(agent.reads)
            tick(6)
            await until(lambda: service.status()['deferred_confirmation'].get('1', {}).get('operator_paused_candidates') == 12)
            await asyncio.sleep(0.1)  # Multiple scheduler checks; no retry-only SSH visit.
            assert agent.reads == before and len(agent.writes) == 12
            assert service.status()['deferred_confirmation']['1']['retry_at'] is None

            tick(61)
            service.request_refresh(frozenset({1}))
            await until(lambda: len(agent.reads) > len(before) and not service._active)
            assert len(agent.writes) == 12
            retry = service.runner._workers[1].retry_discovery.status
            assert retry['counts']['operator_paused'] == 12 and retry['admitted'] == 0

            tick(1)
            change(controls, 'imports', 'RESUME')
            service.signal_work()
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12, 'OBSERVED_PRESENT': 12}
                        and not service._active)
            assert len(agent.writes) == 24
            with service.runner.store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 12
                assert not read(db)['imports']['paused']
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_restoration_pause_does_not_prevent_initial_import_retries(runtime, controls):
    service, agent, tick = runtime
    drop_group(agent)

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12} and not service._active)
            change(controls, 'restoration', 'PAUSE')
            tick(6)
            await until(lambda: states(service.runner) == {'CONFIRMED_ABSENT': 12, 'OBSERVED_PRESENT': 12}
                        and not service._active)
            assert len(agent.writes) == 24
            with service.runner.store._connection() as db:
                assert read(db)['restoration']['paused'] and not read(db)['imports']['paused']
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('paused_kind', ['imports', 'restoration'])
def test_restore_retry_uses_restoration_pause_after_previous_confirmed_presence(runtime, controls, paused_kind):
    service, agent, tick = runtime
    drop_group(agent, ordinal=2)

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            agent.entries[1] = []
            tick(301)
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12, 'CONFIRMED_ABSENT': 12}
                        and not service._active)
            assert len(agent.writes) == 24
            change(controls, paused_kind, 'PAUSE')
            reads = list(agent.reads)
            tick(6)
            if paused_kind == 'restoration':
                await until(lambda: service.status()['deferred_confirmation'].get('1', {}).get('operator_paused_candidates') == 12)
                await asyncio.sleep(0.1)
                assert agent.reads == reads and len(agent.writes) == 24
                tick(1)
                change(controls, 'restoration', 'RESUME')
                service.signal_work()
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 24, 'CONFIRMED_ABSENT': 12}
                        and not service._active)
            assert len(agent.writes) == 36
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_both_pauses_settle_already_claimed_group_and_still_confirm_it(runtime, controls):
    service, agent, _ = runtime
    original, paused = agent.open_tracked_cycle, []

    def opening(device, owner):
        session = original(device, owner)
        finish = session.finish_pending_additions

        def pending():
            receipt = finish()
            if not paused:
                change(controls, 'imports', 'PAUSE')
                change(controls, 'restoration', 'PAUSE')
                paused.append(True)
            return receipt
        session.finish_pending_additions = pending
        return session
    agent.open_tracked_cycle = opening

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            assert len(agent.writes) == 12 and sum(step[0] == 'open' for step in agent.trace) == 2
            with service.runner.store._connection() as db:
                assert read(db)['imports']['paused'] and read(db)['restoration']['paused']
            assert service.runner.leases.status()['devices'][0]['state'] == 'IDLE'
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_both_pauses_keep_protected_ip_unblocking_available(runtime, controls):
    service, agent, tick = runtime

    async def scenario():
        await service.start()
        try:
            await until(lambda: states(service.runner) == {'OBSERVED_PRESENT': 12} and not service._active)
            change(controls, 'imports', 'PAUSE')
            change(controls, 'restoration', 'PAUSE')
            protect(ProtectedPolicy(service.runner.store))
            tick(61)
            service.request_refresh(frozenset({1}))
            await until(lambda: states(service.runner).get('VERIFIED') == 1 and not service._active)
            assert len(agent.writes) == 12
            with service.runner.store._connection() as db:
                assert read(db)['imports']['paused'] and read(db)['restoration']['paused']
                removed = db.execute("SELECT action,state FROM operation_jobs WHERE action='REMOVE'").fetchall()
                assert [tuple(row) for row in removed] == [('REMOVE', 'VERIFIED')]
        finally:
            await service.stop()
    asyncio.run(scenario())
