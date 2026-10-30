"""Explicit no-command terminal proof on local sockets/disposable state only."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from test_bulk_cancellations import cancel
from test_bulk_policy import dump
from test_continuous_dispatch import continuous as continuous_fixture
from test_continuous_dispatch import until
from test_device_leases import acquire, claim, discover, grant
from test_large_snapshots import serve
from test_parallel_synchronizer import bulk as bulk_fixture
from test_parallel_synchronizer import cancellation_controls as cancellation_fixture
from test_parallel_synchronizer import dispatch as dispatch_fixture
from test_parallel_synchronizer import journal as journal_fixture
from test_parallel_synchronizer import leases as leases_fixture
from test_parallel_synchronizer import waits as waits_fixture

from ftd_shun_manager.agent_client import (
    AgentCycleOpenFailed,
    AgentUnavailable,
    UnixAgentClient,
    UnixAgentCycle,
)
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    CycleOperation,
    decode_cycle_open_failure,
    decode_cycle_settlement,
    encode_cycle_request,
)
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.parallel_synchronizer import _DeviceWorker
from ftd_shun_manager.protected_policy import ProtectedPolicy

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
continuous = continuous_fixture
VECTORS = json.loads((Path(__file__).parent / 'fixtures/agent-opening.json').read_text())


@pytest.mark.parametrize('vector', VECTORS, ids=['v1', 'v2', 'v3'])
@pytest.mark.parametrize('failed', [False, True])
def test_exact_shared_vectors_over_real_seqpacket(tmp_path, vector, failed):
    def handler(connection):
        assert connection.recv(100).hex() == vector['begin']
        if failed:
            connection.send(bytes.fromhex(vector['open_failed']))
        else:
            for frame in vector['initial']: connection.send(bytes.fromhex(frame))
            assert connection.recv(100).hex() == vector['end']
            for frame in vector['final']: connection.send(bytes.fromhex(frame))
            connection.send(bytes.fromhex(vector['settled']))
        assert connection.recv(100) == b''
    version = vector['version']
    assert encode_cycle_request(CycleOperation.BEGIN_RECOVERABLE, 0, device_id=7, version=version).hex() == vector['begin']
    decode_cycle_open_failure(bytes.fromhex(vector['open_failed']), version=version)
    decode_cycle_settlement(bytes.fromhex(vector['settled']), 1, version=version, begin=CycleOperation.BEGIN_RECOVERABLE)
    path, pool, worker = serve(tmp_path, handler)
    try:
        if failed:
            with pytest.raises(AgentCycleOpenFailed):
                UnixAgentCycle(path, 5, 7, version=version, settled_cycles=True, recoverable_cycles=True)
        else:
            cycle = UnixAgentCycle(path, 5, 7, version=version, settled_cycles=True, recoverable_cycles=True)
            assert cycle.initial_snapshot == [] and not cycle.settled
            assert cycle.finish() == [] and cycle.settled
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('phase', ['initial', 'priority', 'final'])
def test_local_processing_error_cannot_release_a_submitted_unsettled_session(continuous, monkeypatch, phase):
    service, agent, _clock = continuous
    original, calls = _DeviceWorker._publish_snapshot, []
    def publish(worker, device, snapshot):
        if device == 1:
            calls.append(device)
            if phase == 'initial' or len(calls) == 2:
                raise ValueError('Synthetic local snapshot processing failure')
        original(worker, device, snapshot)
    monkeypatch.setattr(_DeviceWorker, '_publish_snapshot', publish)
    if phase == 'priority':
        monkeypatch.setattr(_DeviceWorker, '_priority_read_due', lambda *_args: True)
        # Make the first legal checkpoint use the same publication pipeline.
        original_open = agent.open_cycle
        def open_cycle(device):
            cycle = original_open(device)
            if device == 1:
                service.runner._workers[1]._priority_pending = True
            return cycle
        monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            expected = 'partial' if phase == 'final' else 'held'
            await until(lambda: service.runner._results.get('1', {}).get('state') == expected and not service._active)
            assert service.runner.leases.status()['devices'][0]['state'] == ('IDLE' if phase == 'final' else 'LEASED')
            assert not agent.writes
            assert service.runner._workers[1].session_settled is (phase == 'final')
        finally:
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('packet', [b'', b'\x01', b'\x03', bytes.fromhex('03011700'),
    bytes.fromhex('03031701'), bytes.fromhex('03031600'), bytes.fromhex('03031300'),
    bytes.fromhex('00031700'), bytes.fromhex('0303170000'), bytes.fromhex('03031700') + b'x' * 65537])
def test_missing_malformed_or_truncated_receipt_never_permits_retry(tmp_path, packet):
    def handler(connection):
        assert connection.recv(100).hex() == '17030007'
        if packet: connection.send(packet)
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentCycle(path, 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
        assert not isinstance(error.value, AgentCycleOpenFailed)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_slow_opening_waits_for_proof_without_reconnect(tmp_path):
    entered, release = Event(), Event()
    def handler(connection):
        assert connection.recv(100).hex() == '17010007'
        entered.set()
        assert release.wait(4)
        connection.send(bytes.fromhex('03011700'))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with ThreadPoolExecutor(max_workers=1) as caller:
            result = caller.submit(UnixAgentCycle, path, 5, 7, settled_cycles=True, recoverable_cycles=True)
            try:
                assert entered.wait(4) and not result.done()
            finally:
                release.set()
            with pytest.raises(AgentCycleOpenFailed): result.result(timeout=4)
        worker.result(timeout=4)
    finally:
        release.set()
        pool.shutdown(wait=True)


def test_timeout_before_terminal_proof_is_not_recovery(tmp_path):
    release = Event()
    def handler(connection):
        assert connection.recv(100).hex() == '17010007'
        assert release.wait(4)
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentCycle(path, 0.05, 7, settled_cycles=True, recoverable_cycles=True)
        assert not isinstance(error.value, AgentCycleOpenFailed)
    finally:
        release.set()
        worker.result(timeout=4)
        pool.shutdown(wait=True)


@pytest.mark.parametrize('phase', ['initial_chunk', 'snapshot', 'add', 'end', 'settlement'])
def test_valid_failure_receipt_at_later_stage_is_not_recovery_proof(tmp_path, phase):
    vector = VECTORS[2]
    def handler(connection):
        assert connection.recv(100).hex() == vector['begin']
        initial = vector['initial'][:1] if phase == 'initial_chunk' else vector['initial']
        for frame in initial: connection.send(bytes.fromhex(frame))
        if phase != 'initial_chunk':
            expected = {'snapshot': '110301', 'add': '140301c63364fe', 'end': '130301', 'settlement': '130301'}[phase]
            assert connection.recv(100).hex() == expected
        if phase == 'settlement':
            for frame in vector['final']: connection.send(bytes.fromhex(frame))
        connection.send(bytes.fromhex(vector['open_failed']))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            cycle = UnixAgentCycle(path, 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
            if phase == 'snapshot': cycle.snapshot()
            elif phase == 'add':
                from ipaddress import IPv4Address

                cycle.add_shun(IPv4Address('198.51.100.254'))
            else: cycle.finish()
        assert not isinstance(error.value, AgentCycleOpenFailed)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('settled,recoverable', [(False, True), (True, 1), (1, True), (True, 'true')])
def test_opt_in_is_literal_and_requires_strict_settlement(settled, recoverable):
    with pytest.raises(ValueError):
        UnixAgentClient('/absent.sock', settled_cycles=settled, recoverable_cycles=recoverable)
    with pytest.raises(ValueError):
        UnixAgentCycle('/absent.sock', 5, 1, settled_cycles=settled, recoverable_cycles=recoverable)


def test_old_strict_begin_cannot_accept_new_open_failure(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == '16010007'
        connection.send(bytes.fromhex('03011700'))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentClient(path, 5, settled_cycles=True).open_cycle(7)
        assert not isinstance(error.value, AgentCycleOpenFailed)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('version', [True, 0, 4, '3'])
def test_failure_decoder_requires_exact_version(version):
    with pytest.raises(ValueError): decode_cycle_open_failure(bytes.fromhex('03031700'), version=version)


def test_opening_release_has_distinct_audit_and_refuses_claimed_work(bulk, leases):
    token, _ = acquire(leases)
    leases.release_unopened(token)
    with leases.store._connection() as db:
        assert [row[0] for row in db.execute("SELECT event_type FROM shun_events WHERE event_type LIKE 'DEVICE_LEASE_%' ORDER BY rowid")] == [
            'DEVICE_LEASE_CLAIMED', 'DEVICE_LEASE_OPEN_FAILED', 'DEVICE_LEASE_RELEASED']
    grant(bulk, (1,))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.release_unopened(token)
    assert dump(leases.store) == before


@pytest.mark.parametrize('change', ['none', 'cancel', 'protect'])
def test_real_failure_proof_retries_and_rechecks_current_authority(bulk, continuous, cancellation_controls, tmp_path, monkeypatch, change):
    service, agent, clock = continuous
    root = grant(bulk, (1,))
    original, calls = agent.open_cycle, []
    def handler(connection):
        assert connection.recv(100).hex() == '17030001'
        connection.send(bytes.fromhex('03031700'))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    client = UnixAgentClient(path, 5, large_snapshots=True, additions_enabled=True,
                             addition_device_ids=frozenset({1}), settled_cycles=True, recoverable_cycles=True)
    def open_cycle(device):
        if device == 1:
            calls.append(clock[0])
            if len(calls) == 1: return client.open_cycle(device)
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'retrying' and not service._active)
            worker.result(timeout=4)
            assert service.runner.leases.status()['devices'][0]['state'] == 'IDLE'
            result = service.runner._results['1']
            assert result['details']['error_category'] == 'agent_open_failed'
            service.request_refresh(frozenset({1}))
            service.request_policy_scan(frozenset({1}))
            await asyncio.sleep(0)
            with service.runner.store._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
                assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='DEVICE_LEASE_OPEN_FAILED'").fetchone()[0] == 1
            if change == 'cancel': cancel(cancellation_controls, root)
            elif change == 'protect':
                from ipaddress import IPv4Address

                ProtectedPolicy(service.runner.store).change('add', IPv4Address('198.51.100.1'), 0,
                    'synthetic:protect', 'Synthetic protection', ('Operator',), managed_revision=1)
            clock[0] += 5
            service.signal_work()
            await until(lambda: len(calls) >= 2 and not service._active)
            if change == 'none':
                await until(lambda: len(agent.writes) == 1 and not service._active)
                with service.runner.store._connection() as db:
                    assert db.execute('SELECT state FROM operation_jobs').fetchone()[0] == 'VERIFIED'
            else: assert not agent.writes
            row = service.refresh_status()['devices']['1']
            assert row['state'] == 'ready' and not row['refresh_pending'] and not row['policy_scan_pending']
            assert row['connection_retry_attempts'] == 0
        finally:
            await service.stop()
    try:
        asyncio.run(scenario())
    finally:
        pool.shutdown(wait=True)
