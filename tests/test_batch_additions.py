"""Gated staged-ADD transport: acknowledgements never establish creation."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from pathlib import Path
from socket import AF_UNIX, SOCK_SEQPACKET, socket
from struct import pack
from uuid import UUID

import pytest

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient, UnixAgentCycle
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    CycleOperation,
    ObservedShun,
    PendingAddition,
    VerifiedAdditionBatch,
    decode_addition_batch,
    decode_cycle_response,
    decode_cycle_settlement,
    encode_cycle_request,
    encode_session_request,
    max_pending_additions,
)

VECTORS = json.loads((Path(__file__).parent / 'fixtures/batch-addition-v4.json').read_text())
IP = IPv4Address(VECTORS['target'])
ID = UUID(int=1).bytes
OWNER = 'e92ad135-07a0-43d9-ac93-f685674069b4'


def frames(opcode, seq, entries=(), *, version=4):
    prefix = bytes([0, version, opcode, seq])
    data = b''.join(ip.packed + bytes([len(name)]) + name.encode('ascii') for ip, name in entries)
    chunks = [data[index:index + 32768] for index in range(0, len(data), 32768)]
    return [prefix + b'\0' + pack('>IIH', len(entries), len(data), len(chunks)),
            *(prefix + b'\1' + index.to_bytes(2, 'big') + chunk for index, chunk in enumerate(chunks)),
            prefix + b'\2' + hashlib.sha256(data).digest()]


def serve(tmp_path, handler, *, version=4):
    path = str(tmp_path / 'batch.sock')
    listener = socket(AF_UNIX, SOCK_SEQPACKET)
    listener.bind(path)
    listener.listen(1)
    listener.settimeout(4)
    pool = ThreadPoolExecutor()

    def run():
        with listener:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(4)
                expected = bytes.fromhex(VECTORS['begin'])
                assert connection.recv(100) == expected[:1] + bytes([version]) + expected[2:]
                for frame in frames(0x18, 0, version=version): connection.send(frame)
                handler(connection)

    return path, pool, pool.submit(run)


def cycle(path):
    return UnixAgentCycle(path, 4, 7, version=4, settled_cycles=True, recoverable_cycles=True, session_id=ID)


def test_shared_vectors_and_version_specific_request_shape():
    assert encode_session_request(0x18, 4, 7, ID).hex() == VECTORS['begin']
    assert encode_cycle_request(CycleOperation.STAGE_ADD, 1, ip=IP, version=4).hex() == VECTORS['stage']
    assert encode_cycle_request(CycleOperation.VERIFY_ADDS, 2, version=4).hex() == VECTORS['verify']
    pending = decode_cycle_response(bytes.fromhex(VECTORS['pending']), CycleOperation.STAGE_ADD, 1, version=4, target=IP)
    assert pending == PendingAddition(IP, 1)
    assert not isinstance(pending, AdditionResult)
    assert decode_cycle_response(bytes.fromhex(VECTORS['noop']), CycleOperation.STAGE_ADD, 1, version=4) == AdditionResult(False)
    assert decode_cycle_response(bytes.fromhex(VECTORS['deferred']), CycleOperation.STAGE_ADD, 1, version=4) is None
    assert decode_addition_batch(bytes.fromhex(VECTORS['receipt']), 2, (IP,)) == ((IP, AdditionResult(True, 'management')),)
    decode_cycle_settlement(bytes.fromhex(VECTORS['settled']), 3, version=4, begin=CycleOperation.BEGIN_TRACKED)
    assert encode_cycle_request(CycleOperation.END, 34, version=4) == b'\x13\x04\x22'
    for version in (1, 2, 3):
        for operation in (CycleOperation.STAGE_ADD, CycleOperation.VERIFY_ADDS):
            with pytest.raises(ValueError):
                encode_cycle_request(operation, 1, version=version, **({'ip': IP} if operation == CycleOperation.STAGE_ADD else {}))
    for operation, seq, fields in [(CycleOperation.ADD, 1, {'ip': IP}), (CycleOperation.BEGIN, 0, {'device_id': 7}),
                                  (CycleOperation.VERIFY_ADDS, 35, {}), (CycleOperation.VERIFY_ADDS, 0, {}),
                                  (CycleOperation.VERIFY_ADDS, 1, {'ip': IP}), (CycleOperation.STAGE_ADD, 1, {})]:
        with pytest.raises(ValueError): encode_cycle_request(operation, seq, version=4, **fields)


@pytest.mark.parametrize('packet', [b'', b'\1', b'\0\4\x1a\1\1\x0amanagement', b'\5\4\x1a\1\0',
                                  b'\5\3\x1a\1', b'\5\4\x1a\2', b'\0\4\x1a\1\0\0'])
def test_stage_rejects_success_shaped_or_misbound_acknowledgements(packet):
    with pytest.raises(ValueError):
        decode_cycle_response(packet, CycleOperation.STAGE_ADD, 1, version=4, target=IP)


@pytest.mark.parametrize('fault', ['empty', 'truncated', 'trailing', 'count', 'sequence', 'version', 'ip', 'scope', 'duplicate'])
def test_receipt_requires_exact_nonempty_ordered_pending_scope(fault):
    packet = bytearray.fromhex(VECTORS['receipt'])
    pending = (IP,)
    if fault == 'empty': pending = ()
    elif fault == 'truncated': packet = packet[:-1]
    elif fault == 'trailing': packet.extend(b'x')
    elif fault == 'count': packet[4] = 2
    elif fault == 'sequence': packet[3] = 3
    elif fault == 'version': packet[1] = 3
    elif fault == 'ip': packet[8] ^= 1
    elif fault == 'scope': packet[-1] = ord(';')
    else: pending = (IP, IP)
    with pytest.raises(ValueError): decode_addition_batch(bytes(packet), 2, pending)


def test_gate_is_explicit_default_off_and_eligible_devices_only(monkeypatch):
    monkeypatch.setattr(agent_client, 'UnixAgentCycle', lambda *args, **kwargs: kwargs['version'])
    args = {'large_snapshots': True, 'additions_enabled': True, 'settled_cycles': True,
            'recoverable_cycles': True, 'tracked_cycles': True, 'addition_device_ids': frozenset({7})}
    client = UnixAgentClient('/unused', **args)
    assert not client.batch_additions
    assert client.open_tracked_cycle(7, OWNER) == 3
    client = UnixAgentClient('/unused', batch_additions=True, **args)
    assert client.open_tracked_cycle(7, OWNER) == 5
    assert client.open_tracked_cycle(8, OWNER) == 2
    for fields in ({'batch_additions': True}, {'batch_additions': 'true'},
                   args | {'tracked_cycles': False, 'batch_additions': True}):
        with pytest.raises(ValueError): UnixAgentClient('/unused', **fields)
    with pytest.raises(ValueError): UnixAgentCycle('/unused', 4, 7, version=4)


def test_ack_then_group_read_then_strict_finish_use_one_connection(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage']
        connection.send(bytes.fromhex(VECTORS['pending']))
        assert connection.recv(100).hex() == VECTORS['verify']
        connection.send(bytes.fromhex(VECTORS['receipt']))
        for frame in frames(0x1b, 2, ((IP, 'management'),)): connection.send(frame)
        assert connection.recv(100).hex() == VECTORS['end']
        for frame in frames(0x13, 3, ((IP, 'management'),)): connection.send(frame)
        connection.send(bytes.fromhex(VECTORS['settled']))
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(ValueError):  # local empty-group rejection, no socket needed
            dummy = object.__new__(UnixAgentCycle)
            dummy.version, dummy.pending_additions = 4, []
            dummy.verify_additions()
        current = cycle(path)
        assert current.stage_addition(IP) == PendingAddition(IP, 1)
        for action in [current.snapshot, lambda: current.remove_shun(IP)]:
            with pytest.raises(AgentUnavailable, match='Pending additions'): action()
        with pytest.raises(ValueError): current.stage_addition(IP)
        result = current.verify_additions()
        assert result == VerifiedAdditionBatch(((IP, AdditionResult(True, 'management')),), (ObservedShun(IP, 'management'),))
        assert current.pending_additions == []
        assert current.finish() == [ObservedShun(IP, 'management')]
        assert current.closed and current.settled
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


@pytest.mark.parametrize('fault', ['receipt_only', 'digest', 'missing', 'scope', 'extra_scope', 'bad_receipt', 'lost_stage'])
def test_incomplete_or_conflicting_group_closes_without_success_or_replay(tmp_path, fault):
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage']
        if fault == 'lost_stage': return
        connection.send(bytes.fromhex(VECTORS['pending']))
        assert connection.recv(100).hex() == VECTORS['verify']
        if fault == 'bad_receipt': connection.send(b'\0\4\x1b\2\0')
        else:
            connection.send(bytes.fromhex(VECTORS['receipt']))
            if fault == 'receipt_only': return
            entries = ((IP, 'outside'),) if fault == 'scope' else () if fault == 'missing' else (
                (IP, 'management'), (IP, 'outside')) if fault == 'extra_scope' else ((IP, 'management'),)
            response = frames(0x1b, 2, entries)
            if fault == 'digest': response[-1] = response[-1][:-1] + bytes([response[-1][-1] ^ 1])
            for frame in response: connection.send(frame)
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        current = cycle(path)
        with pytest.raises(AgentUnavailable):
            current.stage_addition(IP)
            current.verify_additions()
        assert current.closed and current.mutation_attempted and not current.settled
        if fault != 'lost_stage': assert current.pending_additions == [PendingAddition(IP, 1)]
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_eight_pending_requests_share_one_verification_and_capacity_is_local(tmp_path):
    targets = tuple(IPv4Address(f'198.51.100.{n}') for n in range(1, 9))

    def handler(connection):
        for seq, ip in enumerate(targets, 1):
            assert connection.recv(100) == bytes([0x1a, 4, seq]) + ip.packed
            connection.send(bytes([5, 4, 0x1a, seq]))
        assert connection.recv(100) == b'\x1b\4\11'
        connection.send(bytes([0, 4, 0x1b, 9, 8]) + b''.join(ip.packed + b'\x0amanagement' for ip in targets))
        for frame in frames(0x1b, 9, tuple((ip, 'management') for ip in targets)): connection.send(frame)
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        current = cycle(path)
        for ip in targets: assert isinstance(current.stage_addition(ip), PendingAddition)
        assert len(current.pending_additions) == max_pending_additions(4)
        with pytest.raises(ValueError): current.stage_addition(IP)
        assert len(current.verify_additions().additions) == 8
        current.abort()
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_noop_and_deferral_do_not_discard_previously_pending_scope(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage']
        connection.send(bytes.fromhex(VECTORS['pending']))
        assert connection.recv(100) == bytes([0x1a, 4, 2]) + IPv4Address('198.51.100.252').packed
        connection.send(bytes([0, 4, 0x1a, 2, 0]))
        assert connection.recv(100) == bytes([0x1a, 4, 3]) + IPv4Address('198.51.100.253').packed
        connection.send(bytes([2, 4, 0x1a, 3]))
        assert connection.recv(100) == bytes([0x1b, 4, 4])
        receipt = bytearray.fromhex(VECTORS['receipt'])
        receipt[3] = 4
        connection.send(receipt)
        for frame in frames(0x1b, 4, ((IP, 'management'),)): connection.send(frame)
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        current = cycle(path)
        current.stage_addition(IP)
        assert current.stage_addition(IPv4Address('198.51.100.252')) == AdditionResult(False)
        assert current.stage_addition(IPv4Address('198.51.100.253')) is None
        assert current.pending_additions == [PendingAddition(IP, 1)]
        assert len(current.verify_additions().additions) == 1
        current.abort()
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_pending_finish_closes_without_sending_end_or_claiming_settlement(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage']
        connection.send(bytes.fromhex(VECTORS['pending']))
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        current = cycle(path)
        current.stage_addition(IP)
        with pytest.raises(AgentUnavailable): current.finish()
        assert current.closed and not current.settled
        assert current.pending_additions == [PendingAddition(IP, 1)]
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_large_group_observation_remains_chunked_and_complete(tmp_path):
    entries = ((IP, 'management'),) + tuple((IPv4Address(0xc6120000 + n), 'management') for n in range(7307))

    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage']
        connection.send(bytes.fromhex(VECTORS['pending']))
        assert connection.recv(100).hex() == VECTORS['verify']
        connection.send(bytes.fromhex(VECTORS['receipt']))
        for frame in frames(0x1b, 2, entries): connection.send(frame)
        assert connection.recv(100) == b''

    path, pool, worker = serve(tmp_path, handler)
    try:
        current = cycle(path)
        current.stage_addition(IP)
        result = current.verify_additions()
        assert len(result.snapshot) == 7308
        assert result.additions == ((IP, AdditionResult(True, 'management')),)
        current.abort()
        worker.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_receipt_order_is_not_a_set_and_pending_is_not_proof_without_request_binding():
    second = IPv4Address('198.51.100.252')
    packet = bytes([0, 4, 0x1b, 2, 2]) + b''.join(ip.packed + b'\x0amanagement' for ip in (IP, second))
    assert len(decode_addition_batch(packet, 2, (IP, second))) == 2
    with pytest.raises(ValueError): decode_addition_batch(packet, 2, (second, IP))
    with pytest.raises(ValueError):
        decode_cycle_response(bytes.fromhex(VECTORS['pending']), CycleOperation.STAGE_ADD, 1, version=4)


@pytest.mark.parametrize('fault', [None, 'receipt', 'digest', 'missing', 'scope', 'terminal', 'terminal_sequence'])
def test_v5_final_observation_requires_group_stream_and_actual_settlement(tmp_path, fault):
    vectors = json.loads((Path(__file__).parent / 'fixtures/batch-addition-v5.json').read_text())
    assert encode_session_request(0x18, 5, 7, ID).hex() == vectors['begin']
    assert encode_cycle_request(CycleOperation.VERIFY_END, 2, version=5).hex() == vectors['final']
    for version in (1, 2, 3, 4):
        with pytest.raises(ValueError): encode_cycle_request(CycleOperation.VERIFY_END, 2, version=version)

    def handler(connection):
        assert connection.recv(100).hex() == vectors['stage']
        connection.send(bytes.fromhex(vectors['pending']))
        assert connection.recv(100).hex() == vectors['final']
        connection.send(bytes.fromhex(vectors['receipt']))
        if fault == 'receipt': return
        entries = () if fault == 'missing' else ((IP, 'outside' if fault == 'scope' else 'management'),)
        response = frames(0x1c, 2, entries, version=5)
        if fault == 'digest': response[-1] = response[-1][:-1] + bytes([response[-1][-1] ^ 1])
        for frame in response: connection.send(frame)
        if fault == 'terminal': return
        if fault not in ('digest', 'missing', 'scope'):
            connection.send(bytes.fromhex(vectors['settled']) if fault != 'terminal_sequence' else b'\0\5\x18\3')
        assert connection.recv(100) == b''  # Never an additional END or mutation retry.

    path, pool, server = serve(tmp_path, handler, version=5)
    try:
        current = UnixAgentCycle(path, 4, 7, version=5, settled_cycles=True, recoverable_cycles=True, session_id=ID)
        assert current.stage_addition(IP) == PendingAddition(IP, 1)
        if fault:
            with pytest.raises(AgentUnavailable): current.finish_additions()
            assert not current.settled and current.pending_additions == [PendingAddition(IP, 1)]
        else:
            result = current.finish_additions()
            assert result == VerifiedAdditionBatch(((IP, AdditionResult(True, 'management')),),
                                                   (ObservedShun(IP, 'management'),))
            assert current.settled and not current.pending_additions
        assert current.closed
        server.result(timeout=4)
    finally: pool.shutdown(wait=True)


def test_v5_sixteen_pending_writes_share_one_final_observation(tmp_path):
    targets = tuple(IPv4Address(f'198.51.100.{n}') for n in range(1, 17))

    def handler(connection):
        for seq, ip in enumerate(targets, 1):
            assert connection.recv(100) == bytes([0x1a, 5, seq]) + ip.packed
            connection.send(bytes([5, 5, 0x1a, seq]))
        assert connection.recv(100) == bytes([0x1c, 5, 17])
        connection.send(bytes([0, 5, 0x1c, 17, 16]) + b''.join(ip.packed + b'\x0amanagement' for ip in targets))
        for frame in frames(0x1c, 17, tuple((ip, 'management') for ip in targets), version=5): connection.send(frame)
        connection.send(bytes([0, 5, 0x18, 17]))
        assert connection.recv(100) == b''

    path, pool, server = serve(tmp_path, handler, version=5)
    try:
        current = UnixAgentCycle(path, 4, 7, version=5, settled_cycles=True, recoverable_cycles=True, session_id=ID)
        for ip in targets: assert isinstance(current.stage_addition(ip), PendingAddition)
        with pytest.raises(ValueError): current.stage_addition(IP)
        assert len(current.finish_additions().additions) == 16
        assert current.settled and current.closed
        server.result(timeout=4)
    finally: pool.shutdown(wait=True)
