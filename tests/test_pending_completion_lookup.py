"""Lost v7 terminal receipt recovery over local seqpacket, never Cisco."""

import json
from pathlib import Path

import pytest
from test_batch_additions import frames
from test_pending_end import ID, PENDING, TARGETS, current, send_stages, stages
from test_session_completion_lookup import serve_many

from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient
from ftd_shun_manager.agent_protocol import (
    PENDING_SESSION_LOOKUP,
    SettledPendingAdditions,
    decode_pending_lookup,
    decode_session_lookup,
    encode_session_request,
)

VECTORS = json.loads((Path(__file__).parent / 'fixtures/pending-lookup-v7.json').read_text())
END = json.loads((Path(__file__).parent / 'fixtures/pending-end-v7.json').read_text())


def configured_client(path):
    return UnixAgentClient(path, 1, large_snapshots=True, additions_enabled=True,
                           addition_device_ids=frozenset({7}), settled_cycles=True, recoverable_cycles=True,
                           tracked_cycles=True, batch_additions=True, batch_session_version=7,
                           deferred_confirmation=True)


@pytest.mark.parametrize('state', ['complete', 'unknown', 'active', 'foreign', 'closed'])
def test_restart_client_only_reads_exact_local_journal_once(tmp_path, state):
    from uuid import UUID

    identity = UUID('00000000-0000-4000-8000-000000000001')

    def handler(connection, index):
        assert index == 0
        assert connection.recv(100) == encode_session_request(PENDING_SESSION_LOOKUP, 7, 7, identity.bytes)
        if state == 'closed': return
        packet = bytes.fromhex(VECTORS['complete' if state == 'foreign' else state])
        packet = packet[:5] + identity.bytes + packet[21:]
        if state == 'foreign': packet = packet[:-1] + bytes([packet[-1] ^ 1])
        connection.send(packet)
        assert connection.recv(100) == b''

    path, pool, server = serve_many(tmp_path, handler, count=1)
    try:
        client = configured_client(path)
        if state == 'complete':
            assert client.pending_session_completed(7, str(identity), 4, PENDING) == SettledPendingAdditions(7, identity.bytes, 4, PENDING)
        else:
            with pytest.raises(AgentUnavailable): client.pending_session_completed(7, str(identity), 4, PENDING)
        server.result(5)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('fault', ['disabled', 'version', 'device', 'bool_device', 'owner', 'sequence', 'bool_sequence',
                                  'empty', 'list', 'order', 'untyped', 'bool_ack'])
def test_restart_lookup_invalid_configuration_or_original_scope_never_connects(fault):
    from dataclasses import replace
    from uuid import uuid4

    client = configured_client('/missing/agent.sock')
    device, owner, sequence, pending = 7, str(uuid4()), 4, PENDING
    if fault == 'disabled': client.deferred_confirmation = False
    elif fault == 'version': client.batch_session_version = 6
    elif fault == 'device': device = 8
    elif fault == 'bool_device': device = True
    elif fault == 'owner': owner = 'invalid'
    elif fault == 'sequence': sequence = 1
    elif fault == 'bool_sequence': sequence = True
    elif fault == 'empty': pending = ()
    elif fault == 'list': pending = list(PENDING)
    elif fault == 'order': pending = PENDING[::-1]
    elif fault == 'untyped': pending = (True,)
    elif fault == 'bool_ack': pending = (replace(PENDING[0], sequence=True),)
    with pytest.raises((ValueError, AgentUnavailable)) as error:
        client.pending_session_completed(device, owner, sequence, pending)
    assert not isinstance(error.value.__cause__, OSError)  # All refused before socket I/O.


def test_shared_vectors_bind_pending_scope_and_are_never_read_only_completion():
    assert encode_session_request(PENDING_SESSION_LOOKUP, 7, 7, ID).hex() == VECTORS['lookup']
    receipt = decode_pending_lookup(bytes.fromhex(VECTORS['complete']), 7, ID, 4, PENDING)
    assert receipt == SettledPendingAdditions(7, ID, 4, PENDING)
    for state in ('complete', 'unknown', 'active'):
        with pytest.raises(ValueError):
            decode_session_lookup(bytes.fromhex(VECTORS[state]), 7, 7, ID)


@pytest.mark.parametrize('version', [True, 1, 2, 3, 4, 5, 6, 8, 7.0, '7'])
def test_lookup_refuses_other_versions_before_connecting(version):
    with pytest.raises(ValueError):
        encode_session_request(PENDING_SESSION_LOOKUP, version, 7, ID)


@pytest.mark.parametrize('fault', ['unknown', 'active', 'empty', 'truncated', 'trailing', 'version', 'device',
    'session', 'operation', 'sequence', 'count', 'ip', 'order', 'duplicate', 'verified', 'read_only', 'bytearray'])
def test_missing_stale_foreign_or_success_shaped_journal_evidence_never_recovers(fault):
    packet = bytearray.fromhex(VECTORS['complete'])
    if fault in {'unknown', 'active'}: packet = bytearray.fromhex(VECTORS[fault])
    elif fault == 'empty': packet.clear()
    elif fault == 'truncated': packet.pop()
    elif fault == 'trailing': packet.append(0)
    elif fault == 'version': packet[1] = 6
    elif fault == 'device': packet[4] ^= 1
    elif fault == 'session': packet[20] ^= 1
    elif fault == 'operation': packet[2] = 0x19
    elif fault == 'sequence': packet[24] += 1
    elif fault == 'count': packet[25] += 1
    elif fault == 'ip': packet[-1] ^= 1
    elif fault == 'order': packet[-8:] = packet[-4:] + packet[-8:-4]
    elif fault == 'duplicate': packet[-4:] = packet[-8:-4]
    elif fault == 'verified': packet[21] = 0
    elif fault == 'read_only': packet = bytearray([0, 7, 0x19, 0, 7]) + ID
    with pytest.raises(ValueError):
        decode_pending_lookup(packet if fault == 'bytearray' else bytes(packet), 7, ID, 4, PENDING)


@pytest.mark.parametrize('lost', ['header', 'terminal', 'timeout'])
@pytest.mark.parametrize('state', ['complete', 'unknown', 'active', 'foreign', 'closed'])
def test_lost_response_queries_once_and_never_resends_terminal_or_add(tmp_path, lost, state):
    def handler(connection, index):
        if index == 0:
            assert connection.recv(100).hex() == END['begin']
            for frame in frames(0x18, 0, version=7): connection.send(frame)
            stages(connection)
            if lost != 'header': connection.send(bytes.fromhex(END['receipt']))
            if lost == 'timeout': assert connection.recv(100) == b''
            return
        assert index == 1 and connection.recv(100).hex() == VECTORS['lookup']
        if state == 'closed': return
        packet = bytes.fromhex(VECTORS['complete' if state == 'foreign' else state])
        if state == 'foreign': packet = packet[:20] + bytes([packet[20] ^ 1]) + packet[21:]
        connection.send(packet)
        assert connection.recv(100) == b''

    path, pool, server = serve_many(tmp_path, handler)
    try:
        cycle = current(path)
        send_stages(cycle)
        if lost == 'timeout': cycle.timeout_seconds = 0.05
        if state == 'complete':
            receipt = cycle.finish_pending_additions()
            assert receipt == SettledPendingAdditions(7, ID, 4, PENDING)
            assert cycle.settled and cycle.pending_settlement_recovered and cycle.sequence == 5
            assert not cycle.pending_additions
        else:
            with pytest.raises(AgentUnavailable): cycle.finish_pending_additions()
            assert not cycle.settled and not cycle.pending_settlement_recovered
            assert tuple(cycle.pending_additions) == PENDING
        assert cycle.closed
        with pytest.raises(ValueError): cycle.finish_pending_additions()
        server.result(5)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('fault', ['header', 'terminal', 'truncated'])
def test_malformed_evidence_does_not_select_journal_recovery(tmp_path, fault):
    def handler(connection, index):
        assert index == 0
        assert connection.recv(100).hex() == END['begin']
        for frame in frames(0x18, 0, version=7): connection.send(frame)
        stages(connection)
        header = bytes.fromhex(END['receipt'])
        if fault == 'header': header = bytes([0]) + header[1:]
        elif fault == 'truncated': header = b'x' * 65537
        connection.send(header)
        if fault == 'terminal': connection.send(bytes([0, 7, 0x18, 5]))
        assert connection.recv(100) == b''

    path, pool, server = serve_many(tmp_path, handler, count=1)
    try:
        cycle = current(path)
        send_stages(cycle)
        with pytest.raises(AgentUnavailable): cycle.finish_pending_additions()
        assert cycle.closed and not cycle.settled and not cycle.pending_settlement_recovered
        server.result(5)
    finally: pool.shutdown(wait=True)


def test_lost_stage_ack_does_not_open_a_pending_lookup_connection(tmp_path):
    def handler(connection, index):
        assert index == 0 and connection.recv(100).hex() == END['begin']
        for frame in frames(0x18, 0, version=7): connection.send(frame)
        assert connection.recv(100).hex() == END['stage_first']
    path, pool, server = serve_many(tmp_path, handler, count=1)
    try:
        cycle = current(path)
        with pytest.raises(AgentUnavailable): cycle.stage_addition(TARGETS[0])
        with pytest.raises(ValueError): cycle.finish_pending_additions()
        assert not cycle.settled and not cycle.pending_additions
        server.result(5)
    finally: pool.shutdown(wait=True)


