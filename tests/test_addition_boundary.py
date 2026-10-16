"""Explicit v3 transport only: no legacy ADD, admission or fallback."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from socket import AF_UNIX, SOCK_SEQPACKET, socket
from struct import pack

import pytest

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient
from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    CycleOperation,
    Operation,
    decode_cycle_response,
    decode_request,
    encode_cycle_request,
)
from ftd_shun_manager.api import _agent
from ftd_shun_manager.config import Settings
from ftd_shun_manager.snapshot_protocol import SnapshotDecoder

IP = IPv4Address("198.51.100.251")


def empty_snapshot(opcode, sequence):
    prefix = bytes([0, 3, opcode, sequence])
    return [prefix + b"\0" + pack(">IIH", 0, 0, 0), prefix + b"\2" + hashlib.sha256(b"").digest()]


def test_no_standalone_addition_exists_and_agent_flag_alone_cannot_select_v3(monkeypatch):
    assert all("ADD" not in operation.name for operation in Operation)
    assert CycleOperation.ADD == 0x14
    monkeypatch.setenv("FTD_SHUN_AGENT_ADDITIONS_ENABLED", "true")
    client = _agent(replace(Settings.from_environment(), agent_mode="socket", large_snapshots_enabled=True))
    assert not client.additions_enabled, "The agent flag alone cannot enable the API execution gate"
    with pytest.raises(ValueError, match="require large snapshots"):
        UnixAgentClient("/never-connect", additions_enabled=True)
    monkeypatch.setattr(agent_client, "UnixAgentCycle", lambda *args, **kwargs: kwargs["version"])
    assert UnixAgentClient("/unused").open_cycle(1) == 1
    assert UnixAgentClient("/unused", large_snapshots=True).open_cycle(1) == 2
    assert UnixAgentClient("/unused", large_snapshots=True, additions_enabled=True).open_cycle(1) == 3


@pytest.mark.parametrize("version", [1, 2, 3])
def test_addition_frames_cannot_enter_legacy_agent_protocol(version):
    for packet in [bytes([0x14, version, 1, 198, 51, 100, 251]),
                   bytes([0x08, 0, 1, 198, 51, 100, 251])]:
        with pytest.raises(ValueError, match="unknown operation"):
            decode_request(packet)


def test_unknown_version_is_rejected_not_negotiated_or_downgraded():
    with pytest.raises(ValueError, match="invalid cycle version"):
        encode_cycle_request(CycleOperation.BEGIN, 0, device_id=1, version=4)
    with pytest.raises(ValueError, match="invalid cycle version"):
        decode_cycle_response(bytes.fromhex("0004140100"), CycleOperation.ADD, 1, version=4)


def test_shared_v3_addition_and_snapshot_wire_vectors():
    vectors = json.loads((Path(__file__).parent / "fixtures/agent-addition-v3.json").read_text())
    assert encode_cycle_request(CycleOperation.BEGIN, 0, device_id=7, version=3).hex() == vectors["snapshot"]["request"]
    frames = [bytes.fromhex(frame) for frame in vectors["snapshot"]["frames"]]
    decoder = SnapshotDecoder(frames[0], 16, 0, version=3)
    assert decoder.accept(frames[1]) is None
    assert decoder.accept(frames[2])[0].ip == IP
    with pytest.raises(ValueError):
        SnapshotDecoder(frames[0], 16, 0)  # v3 is never silently accepted as v2.
    for vector in vectors["add"]:
        assert encode_cycle_request(CycleOperation.ADD, vector["sequence"], ip=IP, version=3).hex() == vector["request"]
        result = decode_cycle_response(bytes.fromhex(vector["response"]), CycleOperation.ADD, vector["sequence"], version=3)
        assert result == {"created": AdditionResult(True, "management"), "noop": AdditionResult(False), "deferred": None}[vector["result"]]


@pytest.mark.parametrize("version", [1, 2])
def test_add_is_refused_in_older_versions(version):
    with pytest.raises(ValueError, match="requires cycle version 3"):
        encode_cycle_request(CycleOperation.ADD, 1, ip=IP, version=version)
    with pytest.raises(ValueError, match="requires cycle version 3"):
        decode_cycle_response(bytes([0, version, 20, 1, 0]), CycleOperation.ADD, 1, version=version)


@pytest.mark.parametrize("sequence,fields", [(0, {"ip": IP}), (19, {"ip": IP}), (1, {}),
    (1, {"ip": IP, "device_id": 1}), (1, {"ip": IPv6Address("::1")})])
def test_add_request_exact_target_sequence_and_device_binding(sequence, fields):
    with pytest.raises(ValueError):
        encode_cycle_request(CycleOperation.ADD, sequence, version=3, **fields)


@pytest.mark.parametrize("packet", [b"", b"\1", bytes.fromhex("0002140100"),
    bytes.fromhex("0003140200"), bytes.fromhex("0003120100"), bytes.fromhex("000314010000"),
    bytes.fromhex("0003140102"), bytes.fromhex("0203140100"), bytes.fromhex("000314010100"),
    bytes.fromhex("000314010101ff"), bytes.fromhex("0003140101026162") + b"extra",
    bytes.fromhex("00031401010124"), bytes([0,3,20,1,1,65]) + b"a" * 65])
def test_add_result_is_exact_and_never_guessed(packet):
    with pytest.raises(ValueError):
        decode_cycle_response(packet, CycleOperation.ADD, 1, version=3)


def test_one_v3_connection_add_noop_priority_remove_and_final_snapshot(tmp_path):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                exchanges = [
                    (bytes.fromhex("10030007"), empty_snapshot(16,0)),
                    (bytes.fromhex("140301c63364fb"), [bytes.fromhex("00031401010a6d616e6167656d656e74")]),
                    (bytes.fromhex("140302c63364fb"), [bytes.fromhex("0003140200")]),
                    (bytes.fromhex("110303"), empty_snapshot(17,3)),
                    (bytes.fromhex("120304c63364fb"), [bytes.fromhex("0003120401")]),
                    (bytes.fromhex("130305"), empty_snapshot(19,5)),
                ]
                for request, replies in exchanges:
                    assert connection.recv(100) == request
                    for reply in replies:
                        connection.send(reply)
                assert connection.recv(100) == b""

        worker = pool.submit(server)
        cycle = UnixAgentClient(path, 2, large_snapshots=True, additions_enabled=True).open_cycle(7)
        assert cycle.initial_snapshot == []
        assert cycle.add_shun(IP) == AdditionResult(True, "management")
        assert cycle.add_shun(IP) == AdditionResult(False)
        assert cycle.snapshot() == []
        assert cycle.remove_shun(IP) is True
        assert cycle.finish() == [] and cycle.closed
        worker.result(timeout=3)


@pytest.mark.parametrize("reply", [b"\1", bytes.fromhex("0003140200"), bytes.fromhex("000314010100")])
def test_bad_add_reply_closes_connection_without_retry(tmp_path, reply):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                assert connection.recv(100) == bytes.fromhex("10030007")
                for frame in empty_snapshot(16,0):
                    connection.send(frame)
                assert connection.recv(100) == bytes.fromhex("140301c63364fb")
                connection.send(reply)
                assert connection.recv(100) == b"", "No replay, END or replacement mutation after failure"

        worker = pool.submit(server)
        cycle = UnixAgentClient(path, 2, large_snapshots=True, additions_enabled=True).open_cycle(7)
        with pytest.raises(AgentUnavailable, match="no retry"):
            cycle.add_shun(IP)
        assert cycle.closed
        worker.result(timeout=3)


def test_v3_mismatch_aborts_before_add_without_v2_or_legacy_fallback(tmp_path):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                assert connection.recv(100) == bytes.fromhex("10030007")
                connection.send(b"\1")
                assert connection.recv(100) == b""
            listener.settimeout(0.03)
            with pytest.raises(TimeoutError):
                listener.accept()

        worker = pool.submit(server)
        with pytest.raises(AgentUnavailable):
            UnixAgentClient(path, 2, large_snapshots=True, additions_enabled=True).open_cycle(7)
        worker.result(timeout=3)


def test_add_response_timeout_closes_without_replay(tmp_path):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                assert connection.recv(100) == bytes.fromhex("10030007")
                for frame in empty_snapshot(16,0):
                    connection.send(frame)
                assert connection.recv(100) == bytes.fromhex("140301c63364fb")
                # The peer may have written; withhold acknowledgement, observe
                # client close and no second ADD/END rather than replaying it.
                assert connection.recv(100) == b""

        worker = pool.submit(server)
        cycle = UnixAgentClient(path, 2, large_snapshots=True, additions_enabled=True).open_cycle(7)
        cycle.timeout_seconds = 0.03
        with pytest.raises(AgentUnavailable, match="no retry"):
            cycle.add_shun(IP)
        assert cycle.closed
        worker.result(timeout=3)


def test_v3_full_population_chunks_keep_version_binding_and_complete_only():
    count = 20000
    name = b"a" * 64
    data = b"".join(IPv4Address(0xc6120000 + index).packed + bytes([len(name)]) + name for index in range(count))
    chunks = [data[offset:offset + 32768] for offset in range(0,len(data),32768)]
    prefix = bytes([0,3,17,1])
    decoder = SnapshotDecoder(prefix + b"\0" + pack(">IIH", count,len(data),len(chunks)),17,1,version=3)
    for index, chunk in enumerate(chunks):
        assert decoder.accept(prefix + b"\1" + index.to_bytes(2,"big") + chunk) is None
    end = prefix + b"\2" + hashlib.sha256(data).digest()
    rows = decoder.accept(end)
    assert len(rows) == count and rows[-1].interface == name.decode()
    wrong_version = SnapshotDecoder(prefix + b"\0" + pack(">IIH", count,len(data),len(chunks)),17,1,version=3)
    with pytest.raises(ValueError):
        wrong_version.accept(bytes([0,2,17,1,1,0,0]) + chunks[0])
