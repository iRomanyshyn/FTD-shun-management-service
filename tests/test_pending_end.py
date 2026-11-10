"""Synthetic tracked transport only; current runtime cannot select version 7."""

import json
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from test_batch_additions import ID, serve

from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient, UnixAgentCycle
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    CycleOperation,
    PendingAddition,
    SettledPendingAdditions,
    VerifiedAdditionBatch,
    decode_cycle_response,
    decode_cycle_settlement,
    decode_pending_end,
    encode_cycle_request,
    encode_session_request,
    max_cycle_mutations,
    max_pending_additions,
)
from ftd_shun_manager.batch_queue import BatchDeviceOperationQueue

VECTORS = json.loads((Path(__file__).parent / 'fixtures/pending-end-v7.json').read_text())
TARGETS = tuple(map(IPv4Address, VECTORS['targets']))
PENDING = tuple(PendingAddition(ip, seq) for ip, seq in zip(TARGETS, (1, 3), strict=True))


def current(path):
    return UnixAgentCycle(path, 4, 7, version=7, settled_cycles=True, recoverable_cycles=True, session_id=ID)


def stages(connection):
    assert connection.recv(100).hex() == VECTORS['stage_first']
    connection.send(bytes.fromhex(VECTORS['ack_first']))
    assert connection.recv(100) == bytes([0x1a, 7, 2, 198, 51, 100, 253])
    connection.send(bytes([0, 7, 0x1a, 2, 0]))  # Existing-address NOOP is not a pending ACK.
    assert connection.recv(100).hex() == VECTORS['stage_second']
    connection.send(bytes.fromhex(VECTORS['ack_second']))
    assert connection.recv(100).hex() == VECTORS['end_pending']


def send_stages(cycle):
    assert cycle.stage_addition(TARGETS[0]) == PENDING[0]
    assert cycle.stage_addition(IPv4Address('198.51.100.253')) == AdditionResult(False)
    assert cycle.stage_addition(TARGETS[1]) == PENDING[1]


def test_shared_vectors_require_original_scope_and_separate_post_cleanup_settlement():
    assert encode_session_request(0x18, 7, 7, ID).hex() == VECTORS['begin']
    assert encode_cycle_request(CycleOperation.END_PENDING, 4, version=7).hex() == VECTORS['end_pending']
    assert encode_cycle_request(CycleOperation.END_PENDING, 130, version=7).hex() == VECTORS['last_end_pending']
    assert decode_pending_end(bytes.fromhex(VECTORS['receipt']), 4, PENDING, version=7) == PENDING
    decode_cycle_settlement(bytes.fromhex(VECTORS['settled']), 4, version=7, begin=CycleOperation.BEGIN_TRACKED)
    with pytest.raises(ValueError):
        decode_cycle_response(bytes.fromhex(VECTORS['receipt']), CycleOperation.END_PENDING, 4, version=7)
    assert max_pending_additions(7) == 16 and max_cycle_mutations(7) == 64
    with pytest.raises(ValueError): encode_cycle_request(CycleOperation.END_PENDING, 131, version=7)


def test_receipt_accepts_full_bounded_scope_but_never_truncates_an_excess_target():
    pending = tuple(PendingAddition(IPv4Address(0xc6336400 + n), n) for n in range(1, 17))
    packet = bytes([6, 7, 0x1d, 17, 16]) + b''.join(item.ip.packed for item in pending)
    assert decode_pending_end(packet, 17, pending, version=7) == pending
    extra = pending + (PendingAddition(IPv4Address('198.51.100.17'), 17),)
    with pytest.raises(ValueError): decode_pending_end(packet, 18, extra, version=7)


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5, 6, 8, True, '7', 7.0])
def test_old_versions_and_untyped_versions_cannot_request_pending_only_end(version):
    with pytest.raises(ValueError): encode_cycle_request(CycleOperation.END_PENDING, 4, version=version)


@pytest.mark.parametrize('fault', ['empty', 'truncated', 'trailing', 'success', 'version', 'operation', 'sequence',
    'count', 'target', 'reversed', 'duplicate', 'ack_order', 'ack_after_end', 'boolean_ack', 'wrong_ack', 'list', 'scope'])
def test_pending_receipt_is_never_success_or_ambiguous_scope(fault):
    packet, pending = bytearray.fromhex(VECTORS['receipt']), PENDING
    if fault == 'empty': pending = ()
    elif fault == 'truncated': packet.pop()
    elif fault == 'trailing': packet.append(0)
    elif fault == 'success': packet[0] = 0
    elif fault == 'version': packet[1] = 6
    elif fault == 'operation': packet[2] = 0x1c
    elif fault == 'sequence': packet[3] += 1
    elif fault == 'count': packet[4] += 1
    elif fault == 'target': packet[-1] ^= 1
    elif fault == 'reversed': pending = tuple(reversed(pending))
    elif fault == 'duplicate': pending = (pending[0], pending[0])
    elif fault == 'ack_order': pending = (PendingAddition(TARGETS[0], 3), PendingAddition(TARGETS[1], 1))
    elif fault == 'ack_after_end': pending = (pending[0], PendingAddition(TARGETS[1], 4))
    elif fault == 'boolean_ack': pending = (PendingAddition(TARGETS[0], True), pending[1])
    elif fault == 'wrong_ack': pending = (AdditionResult(True, 'management'), pending[1])
    elif fault == 'list': pending = list(pending)
    else: packet.extend(b'\x0amanagement')
    with pytest.raises(ValueError): decode_pending_end(bytes(packet), 4, pending, version=7)


def test_nonempty_end_returns_only_acknowledgements_after_actual_settlement(tmp_path):
    def handler(connection):
        stages(connection)
        connection.send(bytes.fromhex(VECTORS['receipt']))
        connection.send(bytes.fromhex(VECTORS['settled']))
        assert connection.recv(100) == b''  # No read, retry, fallback or second END.
    path, pool, server = serve(tmp_path, handler, version=7)
    try:
        cycle = current(path)
        send_stages(cycle)
        value = cycle.finish_pending_additions()
        assert value == SettledPendingAdditions(7, ID, 4, PENDING)
        assert not isinstance(value, (AdditionResult, VerifiedAdditionBatch))
        assert not hasattr(value, 'snapshot') and not hasattr(value, 'created')
        assert cycle.closed and cycle.settled and not cycle.pending_additions
        server.result(4)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('fault', ['lost_header', 'wrong_header', 'terminal_first', 'lost_terminal',
                                 'wrong_terminal', 'foreign_scope', 'legacy_terminal'])
def test_missing_or_foreign_completion_keeps_uncertainty_without_fallback(tmp_path, fault):
    def handler(connection):
        stages(connection)
        if fault == 'lost_header': return
        receipt = bytes.fromhex(VECTORS['receipt'])
        if fault == 'wrong_header': receipt = bytes([0]) + receipt[1:]
        elif fault == 'foreign_scope': receipt = receipt[:-1] + bytes([receipt[-1] ^ 1])
        elif fault == 'terminal_first': receipt = bytes.fromhex(VECTORS['settled'])
        connection.send(receipt)
        if fault in {'wrong_header', 'foreign_scope', 'terminal_first'}:
            assert connection.recv(100) == b''
            return
        if fault == 'lost_terminal': return
        terminal = bytes([0, 7, 0x18, 5]) if fault == 'wrong_terminal' else bytes([0, 6, 0x18, 4])
        connection.send(terminal)
        assert connection.recv(100) == b''
    path, pool, server = serve(tmp_path, handler, version=7)
    try:
        cycle = current(path)
        send_stages(cycle)
        with pytest.raises(AgentUnavailable): cycle.finish_pending_additions()
        assert cycle.closed and not cycle.settled and tuple(cycle.pending_additions) == PENDING
        server.result(4)
    finally:
        pool.shutdown(wait=True)


def test_lost_stage_ack_cannot_be_laundered_by_pending_only_end(tmp_path):
    def handler(connection):
        assert connection.recv(100).hex() == VECTORS['stage_first']
        connection.send(bytes([0, 7, 0x1a, 1, 1]))  # Not an exact pending ACK or NOOP.
        assert connection.recv(100) == b''
    path, pool, server = serve(tmp_path, handler, version=7)
    try:
        cycle = current(path)
        with pytest.raises(AgentUnavailable): cycle.stage_addition(TARGETS[0])
        with pytest.raises(ValueError): cycle.finish_pending_additions()
        assert cycle.closed and not cycle.settled
        server.result(4)
    finally:
        pool.shutdown(wait=True)


def test_current_composition_refuses_v7_and_pending_end_is_not_a_snapshot():
    from ftd_shun_manager.snapshot_protocol import SnapshotDecoder

    with pytest.raises(ValueError):
        UnixAgentClient('/unused', large_snapshots=True, additions_enabled=True, settled_cycles=True,
                        recoverable_cycles=True, tracked_cycles=True, batch_additions=True, batch_session_version=7)
    with pytest.raises(ValueError): BatchDeviceOperationQueue(None, None, version=7)
    with pytest.raises(ValueError): SnapshotDecoder(b'', CycleOperation.END_PENDING, 4, version=7)
    for version in (5, 6):
        cycle = object.__new__(UnixAgentCycle)
        cycle.version, cycle.pending_additions = version, list(PENDING)
        with pytest.raises(ValueError): cycle.finish_pending_additions()
