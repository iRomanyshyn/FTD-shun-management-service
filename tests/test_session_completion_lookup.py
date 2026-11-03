"""Bound proof-loss recovery on local sockets/disposable state, never FTD."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from socket import AF_UNIX, SOCK_SEQPACKET, socket
from uuid import UUID, uuid4

import pytest
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
from test_read_failure_recovery import frames

from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient, UnixAgentCycle
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    encode_session_request,
)
from ftd_shun_manager.operation_queue import QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
continuous = continuous_fixture
OWNER = '10000000-0000-4000-8000-000000000001'
IDENTITY = UUID(OWNER).bytes
VECTORS = json.loads((Path(__file__).parent / 'fixtures/agent-sessions.json').read_text())


def client(path, version=3, timeout=5):
    return UnixAgentClient(path, timeout, large_snapshots=version >= 2,
                           additions_enabled=version == 3, addition_device_ids=frozenset({1, 7}),
                           settled_cycles=True, recoverable_cycles=True, tracked_cycles=True)


def serve_many(tmp_path, handler, count=2):
    path = str(tmp_path / 'sessions.sock')
    listener = socket(AF_UNIX, SOCK_SEQPACKET)
    listener.bind(path)
    listener.listen(4)
    listener.settimeout(5)
    pool = ThreadPoolExecutor(max_workers=1)
    def run():
        with listener:
            for index in range(count):
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    handler(connection, index)
    return path, pool, pool.submit(run)


@pytest.mark.parametrize('vector', VECTORS, ids=['v1', 'v2', 'v3'])
@pytest.mark.parametrize('state', ['safe', 'unknown', 'active'])
def test_exact_vectors_and_lookup_over_real_seqpacket(tmp_path, vector, state):
    version = vector['version']
    assert encode_session_request(0x18, version, 7, IDENTITY).hex() == vector['begin']
    assert encode_session_request(0x19, version, 7, IDENTITY).hex() == vector['lookup']
    def handler(connection):
        assert connection.recv(100).hex() == vector['lookup']
        connection.send(bytes.fromhex(vector[state]))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        assert client(path, version).read_only_session_completed(7, OWNER) is (state == 'safe')
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('outcome', ['success', 'opening_failed', 'read_failed'])
def test_tracked_begin_preserves_strict_snapshot_and_failure_bindings(tmp_path, version, outcome):
    def handler(connection):
        assert connection.recv(100) == bytes.fromhex(VECTORS[version - 1]['begin'])
        if outcome != 'success': connection.send(bytes([3 if outcome == 'opening_failed' else 4, version, 0x18, 0]))
        else:
            for packet in frames(version, 0x18, 0): connection.send(packet)
            assert connection.recv(100) == bytes([0x13, version, 1])
            for packet in frames(version, 0x13, 1): connection.send(packet)
            connection.send(bytes([0, version, 0x18, 1]))
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, handler)
    try:
        if outcome == 'success':
            cycle = client(path, version).open_tracked_cycle(7, OWNER)
            assert cycle.initial_snapshot == [] and cycle.session_id == IDENTITY
            assert cycle.finish() == [] and cycle.settled
        else:
            from ftd_shun_manager.agent_client import AgentCycleOpenFailed, AgentCycleReadFailed
            with pytest.raises(AgentCycleOpenFailed if outcome == 'opening_failed' else AgentCycleReadFailed):
                client(path, version).open_tracked_cycle(7, OWNER)
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


@pytest.mark.parametrize('fault', ['missing', 'short', 'long', 'truncated', 'version', 'opcode', 'device', 'identity', 'status'])
def test_missing_or_wrong_lookup_cannot_become_proof(tmp_path, fault):
    packet = bytearray(bytes.fromhex(VECTORS[2]['safe']))
    if fault == 'missing': packet = b''
    elif fault == 'short': packet = packet[:-1]
    elif fault == 'long': packet += b'x'
    elif fault == 'truncated': packet += b'x' * 65537
    else: packet[{'version': 1, 'opcode': 2, 'device': 4, 'identity': 20, 'status': 0}[fault]] ^= 4
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS[2]['lookup']
        if packet: connection.send(packet)
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable): client(path).read_only_session_completed(7, OWNER)
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


@pytest.mark.parametrize('owner', [None, '', str(uuid4()).upper(), 'not-a-uuid', str(UUID(int=0)), str(uuid4()).replace('-', '')])
def test_invalid_session_identity_never_connects(tmp_path, owner):
    with pytest.raises(ValueError): client(str(tmp_path / 'absent.sock')).open_tracked_cycle(7, owner)
    with pytest.raises(ValueError): client(str(tmp_path / 'absent.sock')).read_only_session_completed(7, owner)


@pytest.mark.parametrize('fields', [{'operation': 0x17}, {'version': True}, {'version': 5}, {'device_id': 0},
    {'device_id': True}, {'session_id': b''}, {'session_id': bytes(16)}, {'session_id': IDENTITY + b'x'}])
def test_session_packet_validation_is_literal_exact_and_bounded(fields):
    with pytest.raises(ValueError):
        encode_session_request(**({'operation': 0x18, 'version': 3, 'device_id': 7, 'session_id': IDENTITY} | fields))


def test_tracking_requires_explicit_recoverable_mode_and_bound_open(tmp_path):
    path = str(tmp_path / 'absent.sock')
    with pytest.raises(ValueError): UnixAgentClient(path, tracked_cycles=True)
    with pytest.raises(ValueError): UnixAgentClient(path, settled_cycles=True, recoverable_cycles=True, tracked_cycles=1)
    with pytest.raises(ValueError): UnixAgentCycle(path, 5, 7, session_id=IDENTITY)
    with pytest.raises(AgentUnavailable): client(path).open_cycle(7)
    with pytest.raises(AgentUnavailable): UnixAgentClient(path).open_tracked_cycle(7, OWNER)
    with pytest.raises(AgentUnavailable): UnixAgentClient(path).read_only_session_completed(7, OWNER)


@pytest.mark.parametrize('fault', ['wrong_owner', 'wrong_epoch', 'expired', 'attention', 'RUNNING', 'UNVERIFIED', 'VERIFIED'])
def test_lookup_release_preserves_old_fences_and_all_claimed_work(bulk, leases, fault):
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
        if fault != 'RUNNING': queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management') if fault == 'VERIFIED' else fault)
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.release_read_receipt_recovered(token)
    assert dump(leases.store) == before


@pytest.mark.parametrize('phase', ['initial', 'final', 'processing'])
@pytest.mark.parametrize('status', [0, 1, 2])
def test_lost_proof_releases_only_exact_completed_read_only_session(continuous, tmp_path, monkeypatch, phase, status):
    service, agent, clock = continuous
    # One affected and one healthy device: a deliberately retained lease still
    # occupies its sealed capacity, without unrelated artificial-clock contention.
    with service.runner.store._connection() as db:
        db.execute('UPDATE devices SET enabled=0 WHERE id>2')
    original, calls, identity = agent.open_cycle, [], []
    def handler(connection, index):
        packet = connection.recv(100)
        if index == 0:
            assert len(packet) == 20 and packet[:4] == bytes([0x18, 3, 0, 1])
            identity.append(packet[4:])
            if phase != 'initial':
                for frame in frames(3, 0x18, 0): connection.send(frame)
                if phase == 'final':
                    assert connection.recv(100) == bytes([0x13, 3, 1])
                    for frame in frames(3, 0x13, 1): connection.send(frame)
                else: assert connection.recv(100) == b''  # Local processing aborted its own socket.
            # Lost initial/final terminal response; no synthetic success here.
        else:
            assert packet == bytes([0x19, 3, 0, 1]) + identity[0]
            connection.send(bytes([status, 3, 0x19, 0, 1]) + identity[0])
    path, pool, server = serve_many(tmp_path, handler)
    actual = client(path)
    def bound_open(device, owner):
        if device == 1:
            calls.append(owner)
            if len(calls) == 1: return actual.open_tracked_cycle(device, owner)
        return original(device)
    monkeypatch.setattr(agent, 'tracked_cycles', True, raising=False)
    monkeypatch.setattr(agent, 'open_tracked_cycle', bound_open, raising=False)
    monkeypatch.setattr(agent, 'read_only_session_completed', actual.read_only_session_completed, raising=False)
    if phase == 'processing':
        from ftd_shun_manager.parallel_synchronizer import _DeviceWorker
        publish = _DeviceWorker._publish_snapshot
        def fail_once(worker, device, snapshot):
            if device == 1 and len(calls) == 1: raise ValueError('Synthetic local publication error')
            return publish(worker, device, snapshot)
        monkeypatch.setattr(_DeviceWorker, '_publish_snapshot', fail_once)

    async def scenario():
        await service.start()
        try:
            expected = 'retrying' if status == 0 else 'held'
            await until(lambda: service.runner._results.get('1', {}).get('state') == expected
                        and 2 in agent.seen and not service._active)
            server.result(timeout=4)
            assert 2 in agent.seen and not agent.writes
            with service.runner.store._connection() as db:
                row = db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='DEVICE_LEASE_READ_RECEIPT_RECOVERED'").fetchone()
                assert row[0] == (1 if status == 0 else 0)
            assert service.runner.leases.status()['devices'][0]['state'] == ('IDLE' if status == 0 else 'LEASED')
            service.request_refresh(frozenset({1}))
            service.request_policy_scan(frozenset({1}))
            await until(lambda: 1 in service._policy_scans)
            if status == 0:
                assert service.refresh_status()['devices']['1']['retry_in_seconds'] == 5
                clock[0] += 5
                service.signal_work()
                await until(lambda: len(calls) == 2 and not service._active)
                assert calls[0] != calls[1]  # New lease UUID, never resend old BEGIN.
                row = service.refresh_status()['devices']['1']
                assert row['state'] == 'ready' and not row['refresh_pending'] and not row['policy_scan_pending']
        finally: await service.stop()
    try: asyncio.run(scenario())
    finally: pool.shutdown(wait=True)


def test_lookup_release_audit_failure_rolls_back(leases, monkeypatch):
    token, _ = acquire(leases)
    before = dump(leases.store)
    original = leases._event
    def event(db, kind, token, timestamp):
        if kind == 'RELEASED': raise ValueError('Synthetic audit unavailable')
        original(db, kind, token, timestamp)
    monkeypatch.setattr(leases, '_event', event)
    with pytest.raises(ValueError): leases.release_read_receipt_recovered(token)
    assert dump(leases.store) == before


def test_even_false_safe_lookup_cannot_release_completed_mutation_epoch(bulk, continuous, monkeypatch):
    service, agent, _clock = continuous
    grant(bulk, (1,))
    token, queue = acquire(service.runner.leases)
    discover(bulk, queue)
    service.runner.leases.release(token)
    original, queries = agent.open_cycle, []
    def bound_open(device, _owner):
        cycle = original(device)
        if device == 1:
            def failed(): raise AgentUnavailable('Synthetic lost final confirmation after ADD')
            cycle.finish = failed
        return cycle
    def lookup(device, owner):
        queries.append((device, owner))
        return True  # Deliberately false evidence; independent DB guard must refuse.
    monkeypatch.setattr(agent, 'tracked_cycles', True, raising=False)
    monkeypatch.setattr(agent, 'open_tracked_cycle', bound_open, raising=False)
    monkeypatch.setattr(agent, 'read_only_session_completed', lookup, raising=False)
    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner._results.get('1', {}).get('state') == 'held' and not service._active)
            assert len(queries) == 1 and len(agent.writes) == 1
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
            with service.runner.store._connection() as db:
                assert db.execute('SELECT state FROM operation_jobs WHERE device_id=1').fetchone()[0] == 'VERIFIED'
                assert not db.execute("SELECT 1 FROM shun_events WHERE event_type='DEVICE_LEASE_READ_RECEIPT_RECOVERED'").fetchone()
        finally: await service.stop()
    asyncio.run(scenario())
