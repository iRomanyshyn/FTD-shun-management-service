"""Strict settlement vectors and real SeqPacket fixtures, never SSH/FTD."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from test_bulk_policy import dump
from test_continuous_dispatch import continuous as continuous_fixture
from test_continuous_dispatch import until
from test_device_leases import grant
from test_large_snapshots import serve
from test_parallel_synchronizer import bulk as bulk_fixture
from test_parallel_synchronizer import cancellation_controls as cancellation_fixture
from test_parallel_synchronizer import dispatch as dispatch_fixture
from test_parallel_synchronizer import journal as journal_fixture
from test_parallel_synchronizer import leases as leases_fixture
from test_parallel_synchronizer import waits as waits_fixture

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient, UnixAgentCycle
from ftd_shun_manager.agent_protocol import (
    CycleOperation,
    decode_cycle_response,
    decode_cycle_settlement,
    encode_cycle_request,
)
from ftd_shun_manager.continuous_dispatch import ContinuousDispatcher
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.snapshot_protocol import SnapshotDecoder
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
continuous = continuous_fixture
VECTORS = json.loads((Path(__file__).parent / 'fixtures/agent-settlement.json').read_text())


@pytest.mark.parametrize('vector', VECTORS, ids=['v1', 'v2', 'v3'])
def test_shared_fixed_settlement_vectors(vector):
    version = vector['version']
    assert encode_cycle_request(CycleOperation.BEGIN_SETTLED, 0, device_id=7, version=version).hex() == vector['begin']
    assert encode_cycle_request(CycleOperation.END, 1, version=version).hex() == vector['end']
    for operation, sequence, frames in [(CycleOperation.BEGIN_SETTLED, 0, vector['initial']), (CycleOperation.END, 1, vector['final'])]:
        packets = [bytes.fromhex(frame) for frame in frames]
        if version == 1:
            assert decode_cycle_response(packets[0], operation, sequence) == []
        else:
            decoder = SnapshotDecoder(packets[0], operation, sequence, version=version)
            assert decoder.accept(packets[1]) == []
    decode_cycle_settlement(bytes.fromhex(vector['settled']), 1, version=version)


@pytest.mark.parametrize('packet', [b'', b'\x01', b'\0', bytes.fromhex('00011600'),
    bytes.fromhex('00021601'), bytes.fromhex('00011301'), bytes.fromhex('00011602'),
    bytes.fromhex('02011601'), bytes.fromhex('0001160100'), b'x' * 65537])
def test_only_exact_bound_receipt_is_accepted(packet):
    with pytest.raises(ValueError): decode_cycle_settlement(packet, 1, version=1)


@pytest.mark.parametrize('version,sequence', [(True, 1), (1, True), (0, 1), (4, 1), (1, 0), (1, 19)])
def test_settlement_binding_has_literal_version_and_sequence(version, sequence):
    with pytest.raises(ValueError): decode_cycle_settlement(bytes.fromhex('00011601'), sequence, version=version)


@pytest.mark.parametrize('vector', VECTORS, ids=['v1', 'v2', 'v3'])
def test_final_snapshot_waits_for_delayed_receipt_without_new_connection(tmp_path, vector):
    final_sent, release = Event(), Event()

    def server(connection):
        assert connection.recv(100).hex() == vector['begin']
        for frame in vector['initial']: connection.send(bytes.fromhex(frame))
        assert connection.recv(100).hex() == vector['end']
        for frame in vector['final']: connection.send(bytes.fromhex(frame))
        final_sent.set()
        assert release.wait(4)
        connection.send(bytes.fromhex(vector['settled']))
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, server)
    try:
        cycle = UnixAgentCycle(path, 5, 7, version=vector['version'], settled_cycles=True)
        with ThreadPoolExecutor(max_workers=1) as caller:
            finished = caller.submit(cycle.finish)
            try:
                assert final_sent.wait(4)
                assert not finished.done() and not cycle.settled
            finally:
                release.set()
            assert finished.result(timeout=4) == []
        assert cycle.settled and cycle.closed
        worker.result(timeout=4)
    finally:
        release.set()
        pool.shutdown(wait=True)


@pytest.mark.parametrize('receipt', [b'', b'\x01', bytes.fromhex('00021601'), bytes.fromhex('00011602'), b'x' * 65537])
def test_complete_final_snapshot_without_valid_receipt_fails_closed(tmp_path, receipt):
    vector = VECTORS[0]

    def server(connection):
        assert connection.recv(100).hex() == vector['begin']
        connection.send(bytes.fromhex(vector['initial'][0]))
        assert connection.recv(100).hex() == vector['end']
        connection.send(bytes.fromhex(vector['final'][0]))
        if receipt: connection.send(receipt)

    path, pool, worker = serve(tmp_path, server)
    try:
        cycle = UnixAgentCycle(path, 5, 7, settled_cycles=True)
        with pytest.raises(AgentUnavailable): cycle.finish()
        assert not cycle.settled and cycle.closed
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_old_agent_rejection_never_falls_back_to_legacy_begin(tmp_path):
    def server(connection):
        assert connection.recv(100).hex() == '16010007'
        connection.send(b'\x01')
        assert connection.recv(100) == b''
    path, pool, worker = serve(tmp_path, server)
    try:
        with pytest.raises(AgentUnavailable): UnixAgentClient(path, 5, settled_cycles=True).open_cycle(7)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('vector', VECTORS, ids=['v1', 'v2', 'v3'])
def test_strict_begin_cannot_accept_legacy_bound_snapshot(tmp_path, vector):
    def server(connection):
        assert connection.recv(100).hex() == vector['begin']
        packet = bytes.fromhex(vector['initial'][0])
        connection.send(packet[:2] + b'\x10' + packet[3:])
    path, pool, worker = serve(tmp_path, server)
    try:
        with pytest.raises(AgentUnavailable):
            UnixAgentCycle(path, 5, 7, version=vector['version'], settled_cycles=True)
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_settlement_uses_remaining_end_deadline_not_a_fresh_timeout(tmp_path, monkeypatch):
    current, observed = [100.0], []
    original = agent_client._receive_before

    def receive(connection, deadline):
        observed.append(deadline)
        if len(observed) == 3:
            assert deadline == 101
        packet = original(connection, deadline)
        if len(observed) == 2: current[0] = 100.9
        return packet

    monkeypatch.setattr(agent_client, 'monotonic', lambda: current[0])
    monkeypatch.setattr(agent_client, '_receive_before', receive)

    def server(connection):
        assert connection.recv(100).hex() == '16010007'
        connection.send(bytes.fromhex('00011600000000'))
        assert connection.recv(100).hex() == '130101'
        connection.send(bytes.fromhex('00011301000000'))
        connection.send(bytes.fromhex('00011601'))
    path, pool, worker = serve(tmp_path, server)
    try:
        cycle = UnixAgentCycle(path, 1, 7, settled_cycles=True)
        assert cycle.finish() == [] and cycle.settled
        worker.result(timeout=4)
    finally:
        pool.shutdown(wait=True)


def test_missing_terminal_receipt_has_a_bounded_wait(tmp_path):
    release = Event()

    def server(connection):
        assert connection.recv(100).hex() == '16010007'
        connection.send(bytes.fromhex('00011600000000'))
        assert connection.recv(100).hex() == '130101'
        connection.send(bytes.fromhex('00011301000000'))
        assert release.wait(4)
    path, pool, worker = serve(tmp_path, server)
    try:
        cycle = UnixAgentCycle(path, 5, 7, settled_cycles=True)
        cycle.timeout_seconds = 0.05
        started = monotonic()
        with pytest.raises(AgentUnavailable): cycle.finish()
        assert monotonic() - started < 1 and not cycle.settled and cycle.closed
    finally:
        release.set()
        worker.result(timeout=4)
        pool.shutdown(wait=True)


def test_continuous_refuses_an_unsettled_client_without_claiming_or_writing(continuous):
    service, agent, _ = continuous
    agent.settled_cycles = False
    before = dump(service.runner.store)
    with pytest.raises(QueueConflict): asyncio.run(service.start())
    assert dump(service.runner.store) == before and not agent.seen


def test_continuous_cannot_disable_settlement_requirement(tmp_path):
    with pytest.raises(ValueError):
        ContinuousDispatcher(Store(tmp_path / 'absent'), object(), settled_cycles_required=False)
    with pytest.raises(ValueError): UnixAgentClient('unused', settled_cycles=1)


def test_final_read_without_cycle_proof_is_not_published_or_released(continuous, monkeypatch):
    service, agent, _ = continuous
    original, callbacks = agent.open_cycle, []
    publish = service.runner._snapshot_callback

    def recorded(device, *args):
        callbacks.append(device)
        return publish(device, *args)
    service.runner._snapshot_callback = recorded

    def unproved(device):
        cycle = original(device)
        if device == 1:
            finish = cycle.finish

            def missing_proof():
                result = finish()
                cycle.settled = False
                return result
            cycle.finish = missing_proof
        return cycle
    monkeypatch.setattr(agent, 'open_cycle', unproved)

    async def scenario():
        await service.start()
        try:
            await until(lambda: service.runner.status()['devices'].get('1', {}).get('state') == 'held'
                        and service.runner.status()['devices'].get('2', {}).get('state') == 'success'
                        and not service._active)
            assert service.runner.status()['devices']['1']['state'] == 'held'
            assert callbacks.count(1) == 1 and callbacks.count(2) == 2
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
        finally:
            await service.stop()
    asyncio.run(scenario())


def test_verified_add_survives_later_missing_settlement(bulk, continuous, monkeypatch):
    service, agent, _ = continuous
    grant(bulk, devices=(1,))
    original, opened = agent.open_cycle, {}

    def unproved_after_add(device):
        cycle = original(device)
        opened[device] = opened.get(device, 0) + 1
        if device == 1 and opened[device] == 2:
            finish = cycle.finish

            def missing_proof():
                result = finish()
                cycle.settled = False
                return result
            cycle.finish = missing_proof
        return cycle
    monkeypatch.setattr(agent, 'open_cycle', unproved_after_add)

    async def scenario():
        await service.start()
        try:
            await until(lambda: len(agent.writes) == 1 and not service._active
                        and service.runner.status()['devices']['1']['state'] == 'held')
            with service.runner.store._connection() as db:
                assert db.execute('SELECT state FROM managed_bulk_attempts').fetchone()[0] == 'VERIFIED'
            assert service.runner.leases.status()['devices'][0]['state'] == 'LEASED'
        finally:
            await service.stop()
    asyncio.run(scenario())
