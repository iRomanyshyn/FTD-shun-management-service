"""Settled read-only failure proof; local sockets/disposable state, never FTD."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from pathlib import Path
from threading import Event
from uuid import uuid4

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
    AgentCycleReadFailed,
    AgentUnavailable,
    UnixAgentClient,
    UnixAgentCycle,
)
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    CycleOperation,
    decode_cycle_read_failure,
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
VECTORS = json.loads((Path(__file__).parent / 'fixtures/agent-read-failure.json').read_text())
OPENING = json.loads((Path(__file__).parent / 'fixtures/agent-opening.json').read_text())


def frames(version, operation, sequence):
    # Rebind complete empty reference frames, never invent a partial observation.
    return [bytes.fromhex(frame)[:2] + bytes([operation, sequence]) + bytes.fromhex(frame)[4:]
            for frame in OPENING[version - 1]['initial']]


@pytest.mark.parametrize('version,phase', [(version, phase) for version in (1, 2, 3)
    for phase in ('initial', 'snapshot', 'end', 'initial_chunk', 'final_chunk')
    if version != 1 or 'chunk' not in phase])
def test_exact_terminal_failure_at_current_read_and_partial_stream(tmp_path, version, phase):
    vector = VECTORS[version - 1]
    opcode = 0x17 if phase.startswith('initial') else 0x11 if phase == 'snapshot' else 0x13
    sequence = 0 if opcode == 0x17 else 1 if opcode == 0x11 else 2
    field = 'initial_failed' if opcode == 0x17 else 'snapshot_failed' if opcode == 0x11 else 'end_failed'
    proof = bytes.fromhex(vector[field])
    decode_cycle_read_failure(proof, CycleOperation(opcode), sequence, version=version)

    def handler(connection):
        assert connection.recv(100).hex() == vector['begin']
        if not phase.startswith('initial'):
            for frame in frames(version, 0x17, 0): connection.send(frame)
            assert connection.recv(100) == bytes([0x11, version, 1])
            if phase != 'snapshot':
                for frame in frames(version, 0x11, 1): connection.send(frame)
                assert connection.recv(100) == bytes([0x13, version, 2])
        if 'chunk' in phase:
            connection.send(frames(version, opcode, sequence)[0])
        connection.send(proof)
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    cycle = None
    try:
        with pytest.raises(AgentCycleReadFailed):
            cycle = UnixAgentCycle(path, 5, 7, version=version, settled_cycles=True, recoverable_cycles=True)
            cycle.snapshot()
            cycle.finish()
        if cycle is not None:
            assert cycle.closed and not cycle.settled and not cycle.mutation_attempted
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('packet', [b'', b'\x01', b'\x04', bytes.fromhex('04021700'),
    bytes.fromhex('04031600'), bytes.fromhex('04031701'), bytes.fromhex('04031300'),
    bytes.fromhex('0403170000'), bytes.fromhex('04031700') + b'x' * 65537])
def test_missing_truncated_or_misbound_failure_is_never_retryable(tmp_path, packet):
    def handler(connection):
        assert connection.recv(100).hex() == '17030007'
        if packet: connection.send(packet)
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentCycle(path, 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
        assert not isinstance(error.value, AgentCycleReadFailed)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('action,outcome', [('add', 'noop'), ('add', 'defer'), ('remove', 'noop'), ('remove', 'defer')])
@pytest.mark.parametrize('phase', ['mutation', 'end'])
def test_any_mutation_attempt_disqualifies_failure_proof_even_noop_or_deferral(tmp_path, action, outcome, phase):
    opcode = 0x14 if action == 'add' else 0x12
    def handler(connection):
        assert connection.recv(100).hex() == '17030007'
        for frame in frames(3, 0x17, 0): connection.send(frame)
        assert connection.recv(100) == bytes([opcode, 3, 1]) + IPv4Address('198.51.100.250').packed
        if phase == 'mutation':
            connection.send(bytes([4, 3, opcode, 1]))
        else:
            connection.send(bytes([2, 3, opcode, 1]) if outcome == 'defer' else bytes([0, 3, opcode, 1, 0]))
            assert connection.recv(100) == bytes([0x13, 3, 2])
            connection.send(bytes([4, 3, 0x13, 2]))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        cycle = UnixAgentCycle(path, 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
        with pytest.raises(AgentUnavailable) as error:
            getattr(cycle, action + '_shun')(IPv4Address('198.51.100.250'))
            cycle.finish()
        assert not isinstance(error.value, AgentCycleReadFailed)
        assert cycle.mutation_attempted and cycle.closed
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('begin', [0x10, 0x16])
def test_old_modes_do_not_accept_read_failure_proof(tmp_path, begin):
    def handler(connection):
        assert connection.recv(100) == bytes([begin, 1, 0, 7])
        connection.send(bytes([4, 1, begin, 0]))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentCycle(path, 5, 7, settled_cycles=begin == 0x16)
        assert not isinstance(error.value, AgentCycleReadFailed)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_failure_after_complete_final_snapshot_is_not_settlement(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == '17030007'
        for frame in frames(3, 0x17, 0): connection.send(frame)
        assert connection.recv(100).hex() == '130301'
        for frame in frames(3, 0x13, 1): connection.send(frame)
        connection.send(bytes.fromhex('04031301'))
    path, pool, worker = serve(tmp_path, handler)
    try:
        cycle = UnixAgentCycle(path, 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
        with pytest.raises(AgentUnavailable) as error: cycle.finish()
        assert not isinstance(error.value, AgentCycleReadFailed)
        assert cycle.closed and not cycle.settled
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_timeout_without_terminal_receipt_cannot_release_read_only_work(tmp_path):
    release = Event()
    def handler(connection):
        assert connection.recv(100).hex() == '17030007'
        assert release.wait(4)
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable) as error:
            UnixAgentCycle(path, 0.05, 7, version=3, settled_cycles=True, recoverable_cycles=True)
        assert not isinstance(error.value, AgentCycleReadFailed)
    finally:
        release.set()
        worker.result(timeout=4)
        pool.shutdown(wait=True)


@pytest.mark.parametrize('action', ['add', 'remove'])
@pytest.mark.parametrize('failure', ['error', 'short'])
def test_mutation_attempt_is_marked_before_failed_send(monkeypatch, action, failure):
    from ftd_shun_manager import agent_client

    class Connection:
        def __init__(self): self.incoming = iter(frames(3, 0x17, 0))
        def settimeout(self, _timeout): pass
        def connect(self, _path): pass
        def close(self): pass
        def send(self, packet):
            if packet[0] == 0x17: return len(packet)
            if failure == 'error': raise OSError('Synthetic send failure')
            return len(packet) - 1
        def recvmsg(self, _limit):
            return next(self.incoming), [], 0, None
    monkeypatch.setattr(agent_client, 'socket', lambda *_args: Connection())
    cycle = UnixAgentCycle('/synthetic.sock', 5, 7, version=3, settled_cycles=True, recoverable_cycles=True)
    with pytest.raises(AgentUnavailable) as error:
        getattr(cycle, action + '_shun')(IPv4Address('198.51.100.250'))
    assert not isinstance(error.value, AgentCycleReadFailed)
    assert cycle.mutation_attempted and cycle.closed


@pytest.mark.parametrize('version,op,seq', [(True, 0x17, 0), (0, 0x17, 0), (4, 0x17, 0),
    (3, 0x16, 0), (3, 0x14, 1), (3, 0x12, 1), (3, 0x11, 0), (3, 0x13, 19), (3, 0x13, True)])
def test_decoder_refuses_other_bindings(version, op, seq):
    with pytest.raises(ValueError): decode_cycle_read_failure(b'\x04\x03\x17\x00', op, seq, version=version)


@pytest.mark.parametrize('fault', ['wrong_owner', 'wrong_epoch', 'expired', 'attention', 'RUNNING', 'UNVERIFIED', 'VERIFIED'])
def test_release_refuses_old_fences_and_any_claimed_epoch(bulk, leases, fault):
    if fault in ('RUNNING', 'UNVERIFIED', 'VERIFIED'): grant(bulk, (1,))
    token, queue = acquire(leases, seconds=5)
    if fault == 'wrong_owner': token = replace(token, owner=str(uuid4()))
    elif fault == 'wrong_epoch': token = replace(token, epoch=token.epoch + 1)
    elif fault in ('expired', 'attention'):
        bulk[1][0] += timedelta(seconds=6)
        if fault == 'attention': assert leases.claim(1, str(uuid4()), 5, enabled=True) is None
    else:
        discover(bulk, queue)
        job = claim(queue)
        if fault != 'RUNNING':
            queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management') if fault == 'VERIFIED' else fault)
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.release_read_failed(token)
    assert dump(leases.store) == before


def test_release_and_audit_are_atomic_and_preserve_authority(leases, monkeypatch):
    token, _ = acquire(leases)
    original = leases._event
    def event(db, kind, token, timestamp):
        if kind == 'RELEASED': raise ValueError('Synthetic failed audit')
        original(db, kind, token, timestamp)
    monkeypatch.setattr(leases, '_event', event)
    before = dump(leases.store)
    with pytest.raises(ValueError): leases.release_read_failed(token)
    assert dump(leases.store) == before
    monkeypatch.setattr(leases, '_event', original)
    leases.release_read_failed(token)
    with leases.store._connection() as db:
        events = db.execute("SELECT event_type,details_json FROM shun_events WHERE event_type LIKE 'DEVICE_LEASE_%' ORDER BY rowid").fetchall()
        assert [row[0] for row in events] == ['DEVICE_LEASE_CLAIMED', 'DEVICE_LEASE_READ_FAILED', 'DEVICE_LEASE_RELEASED']
        assert all(json.loads(row[1]) == {'owner': token.owner, 'epoch': token.epoch} for row in events)


@pytest.mark.parametrize('phase', ['initial', 'priority', 'final'])
def test_real_proof_retries_with_new_read_and_preserves_healthy_devices(continuous, tmp_path, monkeypatch, phase):
    service, agent, clock = continuous
    original, calls = agent.open_cycle, []
    def handler(connection):
        assert connection.recv(100).hex() == '17030001'
        if phase != 'initial':
            for frame in frames(3, 0x17, 0): connection.send(frame)
            expected = 0x11 if phase == 'priority' else 0x13
            assert connection.recv(100) == bytes([expected, 3, 1])
        else: expected = 0x17
        connection.send(bytes([4, 3, expected, 0 if phase == 'initial' else 1]))
        assert connection.recv(100) == b''
    path, pool, server = serve(tmp_path, handler)
    client = UnixAgentClient(path, 5, large_snapshots=True, additions_enabled=True,
                             addition_device_ids=frozenset({1}), settled_cycles=True, recoverable_cycles=True)
    def open_cycle(device):
        if device == 1:
            calls.append(clock[0])
            if len(calls) == 1:
                cycle = client.open_cycle(device)
                if phase == 'priority': service.runner._workers[1]._priority_pending = True
                return cycle
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)
    if phase == 'priority': monkeypatch.setattr(_DeviceWorker, '_priority_read_due', lambda *_args: True)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'retrying' and not service._active)
            server.result(timeout=4)
            assert service.runner.leases.status()['devices'][0]['state'] == 'IDLE'
            assert service.runner._results['1']['details']['error_category'] == 'agent_read_failed'
            assert {2, 3, 4} <= agent.seen and not agent.writes
            row = service.refresh_status()['devices']['1']
            assert row['stale'] and row['retry_in_seconds'] == 5
            service.request_refresh(frozenset({1}))
            service.request_policy_scan(frozenset({1}))
            await asyncio.sleep(0.02)
            assert len(calls) == 1  # Clicks cannot bypass retry backoff.
            clock[0] += 5
            service.signal_work()
            await until(lambda: len(calls) >= 2 and not service._active)
            row = service.refresh_status()['devices']['1']
            assert row['state'] == 'ready' and not row['refresh_pending'] and not row['policy_scan_pending']
            assert row['connection_retry_attempts'] == 0 and not agent.writes
        finally: await service.stop()
    try: asyncio.run(scenario())
    finally: pool.shutdown(wait=True)


@pytest.mark.parametrize('change', ['none', 'cancel', 'protect'])
def test_retry_rechecks_changed_standing_authority(bulk, continuous, cancellation_controls, tmp_path, monkeypatch, change):
    service, agent, clock = continuous
    root = grant(bulk, (1,))
    original, calls = agent.open_cycle, []
    def handler(connection):
        assert connection.recv(100).hex() == '17030001'
        connection.send(bytes.fromhex('04031700'))
    path, pool, server = serve(tmp_path, handler)
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
            server.result(timeout=4)
            assert not agent.writes
            if change == 'cancel': cancel(cancellation_controls, root)
            elif change == 'protect':
                ProtectedPolicy(service.runner.store).change('add', IPv4Address('198.51.100.1'), 0,
                    'synthetic:protect', 'Synthetic protection', ('Operator',), managed_revision=1)
            clock[0] += 5
            service.signal_work()
            await until(lambda: len(calls) >= 2 and not service._active)
            if change == 'none': await until(lambda: len(agent.writes) == 1 and not service._active)
            else: assert not agent.writes
        finally: await service.stop()
    try: asyncio.run(scenario())
    finally: pool.shutdown(wait=True)


def test_cancelled_caller_does_not_gain_read_failure_release(continuous, monkeypatch):
    service, agent, _clock = continuous
    entered, release = Event(), Event()
    original = agent.open_cycle
    def open_cycle(device):
        if device == 1:
            entered.set()
            assert release.wait(4)
            raise AgentCycleReadFailed('Synthetic terminal result after cancellation')
        return original(device)
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)
    async def scenario():
        await service.start()
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            service._active[1].cancel()
            release.set()
            await until(lambda: not service._active)
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
            with service.runner.store._connection() as db:
                assert not db.execute("SELECT 1 FROM shun_events WHERE event_type='DEVICE_LEASE_READ_FAILED'").fetchone()
        finally:
            release.set()
            await service.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['mutation', 'final'])
def test_misclassified_late_proof_never_releases_claimed_epoch(bulk, continuous, monkeypatch, phase):
    service, agent, _clock = continuous
    grant(bulk, (1,))
    # Queue before the frozen cutoff; newly discovered work is not claimed in
    # its discovery cycle. Preserve the normal product scheduling contract.
    token, queue = acquire(service.runner.leases)
    discover(bulk, queue)
    service.runner.leases.release(token)
    original = agent.open_cycle

    class BoundSession:
        def __init__(self, cycle): self.cycle = cycle
        def __getattr__(self, name): return getattr(self.cycle, name)
        def snapshot(self): return self.cycle.snapshot()
        def finish(self): raise AgentCycleReadFailed('Synthetic falsely classified final read')
        def add_shun(self, target):
            if phase == 'mutation': raise AgentCycleReadFailed('Synthetic falsely classified mutation')
            return self.cycle.add_shun(target)
    def open_cycle(device):
        cycle = original(device)
        return BoundSession(cycle) if device == 1 else cycle
    monkeypatch.setattr(agent, 'open_cycle', open_cycle)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'held' and not service._active)
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
            assert 1 not in service._connection_failures
            with service.runner.store._connection() as db:
                assert db.execute('SELECT state FROM operation_jobs WHERE device_id=1').fetchone()[0] == (
                    'VERIFIED' if phase == 'final' else 'UNVERIFIED')
                assert not db.execute("SELECT 1 FROM shun_events WHERE event_type='DEVICE_LEASE_READ_FAILED'").fetchone()
        finally: await service.stop()
    asyncio.run(scenario())
