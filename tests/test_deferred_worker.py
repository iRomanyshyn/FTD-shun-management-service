"""Real fresh-profile worker with synthetic tracked-v7 transport, never Cisco."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4

import pytest
from test_batch_session import Agent as GroupedAgent
from test_batch_session import states, visit
from test_bulk_policy import dump
from test_continuous_dispatch import admitted_removal, until
from test_device_leases import grant
from test_pending_execution import bulk as bulk_fixture
from test_pending_execution import cancellation_controls as cancellation_fixture
from test_pending_execution import dispatch as dispatch_fixture
from test_pending_execution import execution as execution_fixture
from test_pending_execution import journal as journal_fixture
from test_pending_execution import leases as leases_fixture
from test_pending_execution import ledger as ledger_fixture
from test_pending_execution import waits as waits_fixture

from ftd_shun_manager.agent_client import AgentUnavailable
from ftd_shun_manager.agent_protocol import ObservedShun, PendingAddition, SettledPendingAdditions
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.deferred_worker import (
    DeferredDeviceOperationQueue,
    DeferredParallelSynchronizer,
)
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture


class Agent(GroupedAgent):
    batch_session_version = 7

    def __init__(self):
        super().__init__()
        self.pending_failure = None

    def open_tracked_cycle(self, device, owner):
        session = super().open_tracked_cycle(device, owner)
        stage, verify = session.stage_addition, session.verify_additions
        acknowledgements = []

        def staged(ip):
            result = stage(ip)
            if type(result) is PendingAddition:
                acknowledgements.append(result)
            return result

        def verified():
            result = verify()
            acknowledgements.clear()
            return result

        def pending_end():
            assert acknowledgements
            self.trace.append(('end_pending', device, tuple(ack.ip for ack in acknowledgements)))
            if self.pending_failure == 'lost':
                raise AgentUnavailable('Synthetic lost pending terminal settlement')
            result = SettledPendingAdditions(device, UUID(owner).bytes, session.sequence, tuple(acknowledgements))
            session.sequence += 1
            if self.pending_failure == 'owner': result = replace(result, session_id=uuid4().bytes)
            if self.pending_failure == 'order': result = replace(result, acknowledgements=tuple(reversed(acknowledgements)))
            session.settled = self.pending_failure != 'unsettled'
            session.abort()  # Model cleanup/guard/worker completion, no extra read.
            return result

        session.stage_addition = staged
        session.verify_additions = verified
        session.finish_pending_additions = pending_end
        return session


def runner(store, agent):
    return DeferredParallelSynchronizer(store, agent, enabled=True, agent_concurrency=2,
        addition_device_ids=frozenset({1}), operation_timeout_seconds=240)


@pytest.fixture
def runtime(bulk, execution):
    grant(bulk, (1,), count=12)
    with execution.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>4')
    agent = Agent()
    return runner(execution.store, agent), agent


def test_disabled_mode_never_opens_or_initializes_storage(tmp_path):
    store = Store(tmp_path / 'absent.db')
    service = DeferredParallelSynchronizer(store, object())
    assert asyncio.run(service.sweep())['enabled'] is False
    assert not store.path.exists()


@pytest.mark.parametrize('fault', ['version', 'tracked', 'settled', 'grouped', 'disable_settlement'])
def test_mismatched_client_refuses_before_storage_or_rpc(tmp_path, fault):
    agent = Agent()
    options = {}
    if fault == 'version': agent.batch_session_version = 6
    if fault == 'tracked': agent.tracked_cycles = False
    if fault == 'settled': agent.settled_cycles = False
    if fault == 'grouped': agent.batch_additions = False
    if fault == 'disable_settlement': options['settled_cycles_required'] = False
    store = Store(tmp_path / 'absent.db')
    with pytest.raises(ValueError): DeferredParallelSynchronizer(store, agent, enabled=True, **options)
    assert not store.path.exists() and not agent.seen


def test_old_profile_cannot_be_used_as_a_deferred_execution_shortcut(leases):
    service = runner(leases.store, Agent())
    before = dump(leases.store)
    with pytest.raises(BulkUnavailable): asyncio.run(service.sweep())
    assert dump(leases.store) == before and not service.agent.seen


def test_twelve_writes_end_pending_without_final_read_then_confirm_before_publication(runtime, bulk):
    service, agent = runtime
    asyncio.run(visit(service))
    assert states(service) == {'AWAITING_CONFIRMATION': 12}
    assert agent.reads == [('initial', 1)] and not agent.verifications
    worker = service._workers[1]
    assert worker.session_settled and worker._device_cycle['completed'] == 0
    assert worker._device_cycle['awaiting_confirmation'] == 12
    assert worker._device_cycle['action'] == 'awaiting_confirmation'
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
    published = []

    def callback(*_args):
        published.append(states(service))
    bulk[1][0] += timedelta(seconds=1)
    restarted = runner(service.store, agent)
    restarted._snapshot_callback = callback
    asyncio.run(visit(restarted))
    assert published and all(state == {'OBSERVED_PRESENT': 12} for state in published)
    assert len(agent.writes) == 12 and sum(step[0] == 'open' for step in agent.trace) == 2
    assert not agent.lookup and service.leases.status()['devices'][0]['state'] == 'IDLE'
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM shun_state WHERE active=1').fetchone()[0] == 12
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_VERIFIED'").fetchone()[0] == 0


def test_absent_confirmation_waits_then_automatically_creates_only_fresh_jobs(runtime, bulk):
    service, agent = runtime
    asyncio.run(visit(service))
    agent.entries[1] = []
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 12}
    status = service.status()['deferred_confirmation']['1']
    assert status['counts']['waiting'] == 12 and status['retry_at'] is not None
    assert len(agent.writes) == 12
    bulk[1][0] += timedelta(seconds=5)
    asyncio.run(visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 12, 'AWAITING_CONFIRMATION': 12}
    assert len(agent.writes) == 24
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 12
        assert db.execute('SELECT COUNT(DISTINCT job_id) FROM managed_bulk_attempts').fetchone()[0] == 24
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 12, 'OBSERVED_PRESENT': 12}
    assert service.queue.status()['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 0}


@pytest.mark.parametrize('fault', ['lost', 'owner', 'order', 'unsettled'])
def test_missing_or_mismatched_terminal_scope_keeps_unknowns_and_original_fence(runtime, fault):
    service, agent = runtime
    agent.pending_failure = fault
    asyncio.run(visit(service))
    assert states(service) == {'UNVERIFIED': 12}
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute("SELECT state FROM managed_bulk_device_executors WHERE device_id=1").fetchone()[0] == 'LEASED'
    assert not service._workers[1].queue.handed_off_session
    assert len(agent.writes) == 12


@pytest.mark.parametrize('interrupt', ['refresh', 'remove', 'protect'])
def test_priority_flushes_after_current_command_before_the_next_mutation(runtime, bulk, interrupt):
    service, agent = runtime

    def boundary(device, ip, count):
        if count != 2: return
        if interrupt == 'refresh': service._workers[1]._priority_pending = True
        if interrupt == 'remove': admitted_removal(bulk, IPv4Address('203.0.113.17'))
        if interrupt == 'protect':
            ProtectedPolicy(service.store).change('add', IPv4Address('198.51.100.1'), 0,
                'synthetic:policy', 'Synthetic editor', ('Viewer',), managed_revision=1)

    agent.on_stage = boundary
    asyncio.run(visit(service))
    verify = next(i for i, step in enumerate(agent.trace) if step[0] == 'verify')
    assert len(agent.trace[verify][2]) == 2
    assert agent.trace[verify + 1][0] == ('stage' if interrupt == 'refresh' else 'remove')
    assert service._workers[1].session_settled
    assert sum(step[0] == 'open' for step in agent.trace) == 1


@pytest.mark.parametrize('interrupt', ['stop', 'pause', 'cancel'])
def test_stop_pause_or_cancellation_settles_pending_without_an_extra_complete_read(
        runtime, bulk, cancellation_controls, interrupt):
    service, agent = runtime

    def boundary(device, ip, count):
        if count != 2: return
        if interrupt == 'stop': service._workers[1]._stop_mutations = True
        elif interrupt == 'pause':
            with service.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
        else:
            from test_bulk_cancellations import cancel
            with service.store._connection() as db:
                root = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts LIMIT 1').fetchone()[0]
            cancel(cancellation_controls, root)

    agent.on_stage = boundary
    asyncio.run(visit(service))
    assert len(agent.writes) == 2
    assert states(service)['AWAITING_CONFIRMATION'] == 2
    assert agent.reads == [('initial', 1)] and not agent.verifications
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'


def test_deferred_queue_rejects_ordinary_session_versions(execution, leases):
    from test_device_leases import acquire

    token, _ = acquire(leases)
    for version in (True, 5, 6, 8):
        with pytest.raises(ValueError): DeferredDeviceOperationQueue(execution.store, token, version=version)


def test_original_coordinator_does_not_release_a_successors_lease(runtime, leases, monkeypatch):
    from test_device_leases import acquire

    service, _agent = runtime
    original = DeferredDeviceOperationQueue.handoff
    successors = []

    def successor(queue, owner, receipt):
        result = original(queue, owner, receipt)
        successors.append(acquire(leases)[0])
        return result

    monkeypatch.setattr(DeferredDeviceOperationQueue, 'handoff', successor)
    asyncio.run(visit(service))
    assert states(service) == {'AWAITING_CONFIRMATION': 12}
    with service.store._connection() as db:
        row = db.execute('SELECT * FROM managed_bulk_device_executors WHERE device_id=1').fetchone()
        assert row['state'] == 'LEASED' and row['owner'] == successors[0].owner and row['epoch'] == successors[0].epoch


def test_failed_local_terminal_handoff_rolls_back_before_retaining_unknowns(runtime, monkeypatch):
    from ftd_shun_manager.pending_execution import PendingExecution

    service, agent = runtime

    def fail(*_args, **_kwargs):
        raise ValueError('Synthetic result-audit transaction failure')

    monkeypatch.setattr(PendingExecution, '_audit', fail)
    asyncio.run(visit(service))
    assert states(service) == {'UNVERIFIED': 12}
    assert service._workers[1].session_settled and service._workers[1].rpc_failed
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_sessions').fetchone()[0] == 0
        assert db.execute("SELECT state FROM managed_bulk_device_executors WHERE device_id=1").fetchone()[0] == 'LEASED'
    assert len(agent.writes) == 12


def test_sixty_four_attempt_visit_verifies_intermediate_groups_and_defers_only_last(bulk, execution):
    grant(bulk, (1,), count=80)
    agent = Agent()
    service = runner(execution.store, agent)
    asyncio.run(visit(service))
    assert [len(group) for group in agent.verifications] == [16, 16, 16]
    assert states(service) == {'VERIFIED': 48, 'AWAITING_CONFIRMATION': 16}
    assert len(agent.writes) == 64 and sum(step[0] == 'open' for step in agent.trace) == 1
    assert agent.reads == [('initial', 1)]  # Intermediate group reads are traced separately.
    assert service._workers[1]._device_cycle['completed'] == 48
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'


def test_cancelled_absence_retires_targets_without_new_jobs(runtime, bulk, cancellation_controls):
    from test_bulk_cancellations import cancel

    service, agent = runtime
    asyncio.run(visit(service))
    agent.entries[1] = []
    with service.store._connection() as db:
        key = db.execute('SELECT authorization_request_id FROM managed_bulk_attempts LIMIT 1').fetchone()[0]
    cancel(cancellation_controls, key)
    bulk[1][0] += timedelta(seconds=10)
    asyncio.run(visit(service))
    assert states(service) == {'CONFIRMED_ABSENT': 12} and len(agent.writes) == 12
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_retries').fetchone()[0] == 0
    assert service.queue.status()['attention_counts'] == {'FAILED': 0, 'UNVERIFIED': 0}


def test_enabled_protection_during_awaiting_is_confirmed_then_unblocked(runtime, bulk):
    service, agent = runtime
    asyncio.run(visit(service))
    target = IPv4Address('198.51.100.1')
    ProtectedPolicy(service.store).change('add', target, 0,
        'synthetic:policy', 'Synthetic editor', ('Viewer',), managed_revision=1)
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(service))
    assert target not in {entry.ip for entry in agent.entries[1]}
    assert states(service) == {'OBSERVED_PRESENT': 12, 'VERIFIED': 1}
    assert len(agent.writes) == 12


def test_caller_cancellation_drains_current_rpc_and_commits_real_pending_settlement(runtime):
    from test_parallel_synchronizer import wait

    service, agent = runtime
    with service.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id!=1')

    def block(device, ip, count):
        if count == 2:
            agent.entered[device].set()
            assert agent.releases[device].wait(5)

    agent.on_stage = block

    async def scenario():
        task = asyncio.create_task(service.sweep())
        await wait(agent.entered[1])
        task.cancel()
        await asyncio.sleep(0)
        agent.releases[1].set()
        with pytest.raises(asyncio.CancelledError): await task

    asyncio.run(scenario())
    assert states(service) == {'AWAITING_CONFIRMATION': 2, 'QUEUED': 10}
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'
    assert agent.reads == [('initial', 1)] and len(agent.writes) == 2


def test_lost_stage_ack_never_becomes_pending_or_automatic_replay(runtime):
    service, agent = runtime
    agent.fail_stage = 3
    asyncio.run(visit(service))
    assert states(service) == {'UNVERIFIED': 3, 'QUEUED': 9}
    assert not any(step[0] == 'end_pending' for step in agent.trace)
    before = len(agent.writes)
    asyncio.run(visit(service))
    assert len(agent.writes) == before == 3
    assert service._results['1']['state'] == 'lease_held'


def test_actual_preflight_noop_does_not_enter_deferred_scope(runtime, monkeypatch):
    service, agent = runtime
    original = agent.open_tracked_cycle

    def external_add(device, owner):
        session = original(device, owner)
        staged = session.stage_addition
        first = True

        def stage(ip):
            nonlocal first
            if first:
                first = False
                agent.entries[device].append(ObservedShun(ip, 'management'))
            return staged(ip)

        session.stage_addition = stage
        return session

    monkeypatch.setattr(agent, 'open_tracked_cycle', external_add)
    asyncio.run(visit(service))
    assert states(service) == {'NOOP': 1, 'AWAITING_CONFIRMATION': 11}
    assert len(agent.writes) == 11
    with service.store._connection() as db:
        assert db.execute('SELECT member_count FROM managed_bulk_pending_sessions').fetchone()[0] == 11
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0


def test_one_complete_read_confirms_all_groups_atomically_before_any_publication(bulk, execution, leases, monkeypatch):
    from test_device_leases import acquire, claim, discover

    from ftd_shun_manager.pending_execution import PendingExecution

    grant(bulk, (1,), count=4)
    for group in range(2):
        token, ordinary = acquire(leases)
        if group == 0: assert discover(bulk, ordinary) == 4
        queue = DeferredDeviceOperationQueue(execution.store, token)
        for sequence in (1, 3):
            job = claim(queue)
            queue.acknowledge_addition(job['id'], token.owner, PendingAddition(IPv4Address(job['ip']), sequence))
        receipt = SettledPendingAdditions(1, UUID(token.owner).bytes, 4, tuple(
            PendingAddition(IPv4Address(f'198.51.100.{group * 2 + i}'), i * 2 - 1) for i in (1, 2)))
        queue.handoff(token.owner, receipt)
        bulk[1][0] += timedelta(seconds=1)
    agent = Agent()
    agent.entries[1] = [ObservedShun(IPv4Address(f'198.51.100.{i}'), 'management') for i in range(1, 5)]
    service = runner(execution.store, agent)
    published, confirmed = [], []
    service._snapshot_callback = lambda *_args: published.append(True)
    original = PendingExecution.confirm

    def fail_second(*args, **kwargs):
        result = original(*args, **kwargs)
        confirmed.append(True)
        if len(confirmed) == 2: raise ValueError('Synthetic second-group classification failure')
        return result

    monkeypatch.setattr(PendingExecution, 'confirm', fail_second)
    asyncio.run(visit(service))
    assert len(confirmed) == 2 and not published
    assert states(service) == {'AWAITING_CONFIRMATION': 4}
    with service.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_pending_reads').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0


def test_deferred_visits_remain_parallel_across_devices_and_serial_per_device(bulk, execution):
    from test_parallel_synchronizer import wait

    grant(bulk, (1, 2), count=2)
    with execution.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id>2')
    agent = Agent()
    service = DeferredParallelSynchronizer(execution.store, agent, enabled=True, agent_concurrency=2,
        addition_device_ids=frozenset({1, 2}), operation_timeout_seconds=240)

    def block(device, ip, count):
        if device == 1 and count == 1:
            agent.entered[1].set()
            assert agent.releases[1].wait(5)

    agent.on_stage = block

    async def scenario():
        task = asyncio.create_task(service.sweep())
        await wait(agent.entered[1])
        try:
            await wait(agent.finished[2])
            # Remote worker cleanup precedes local durable handoff. Wait for
            # that real transaction, never infer its commit from an RPC event.
            await until(lambda: states(service).get('AWAITING_CONFIRMATION') == 2)
            assert agent.maximum == 2
        finally:
            agent.releases[1].set()
        await task

    asyncio.run(scenario())
    assert states(service) == {'AWAITING_CONFIRMATION': 4}
    assert all(row['state'] == 'IDLE' for row in service.leases.status()['devices'])


def test_changed_transport_configuration_refuses_before_a_new_visit(runtime):
    service, agent = runtime
    before = dump(service.store)
    agent.batch_session_version = 6
    with pytest.raises(ValueError): service._configured_devices()
    assert dump(service.store) == before and not agent.seen
