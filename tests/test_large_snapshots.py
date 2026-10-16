import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from pathlib import Path
from socket import AF_UNIX, SOCK_SEQPACKET, socket
from struct import pack
from time import monotonic, sleep

import pytest

from ftd_shun_manager import agent_client
from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient
from ftd_shun_manager.agent_protocol import (
    CycleOperation,
    Operation,
    encode_cycle_request,
    encode_request,
)
from ftd_shun_manager.config import Settings
from ftd_shun_manager.snapshot_protocol import (
    MAX_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_ENTRIES,
    SNAPSHOT_CHUNK_BYTES,
    SnapshotDecoder,
)
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer


def wire(count=0, *, opcode=7, sequence=0, interface="management", data=None):
    if data is None:
        name = interface.encode("ascii")
        data = b"".join(IPv4Address(0xC6120000 + index).packed + bytes([len(name)]) + name for index in range(count))
    prefix = bytes([0, 2, opcode, sequence])
    chunks = [data[offset:offset + SNAPSHOT_CHUNK_BYTES] for offset in range(0, len(data), SNAPSHOT_CHUNK_BYTES)]
    return [prefix + b"\x00" + pack(">IIH", count, len(data), len(chunks)),
            *(prefix + b"\x01" + index.to_bytes(2, "big") + chunk for index, chunk in enumerate(chunks)),
            prefix + b"\x02" + hashlib.sha256(data).digest()]


def assemble(frames, opcode=7, sequence=0):
    decoder = SnapshotDecoder(frames[0], opcode, sequence)
    result = None
    for frame in frames[1:]:
        result = decoder.accept(frame)
    return result


def test_shared_rust_python_snapshot_vectors():
    vectors = json.loads((Path(__file__).parent / "fixtures/snapshot-v2.json").read_text())
    for vector in vectors:
        op, seq = vector["opcode"], vector["sequence"]
        request = encode_request(Operation.LIST_SHUNS_LARGE, 7) if op == 7 else encode_cycle_request(
            CycleOperation(op), seq, version=2, **({"device_id": 7} if op == 16 else {}))
        assert request.hex() == vector["request"]
        result = assemble([bytes.fromhex(frame) for frame in vector["frames"]], op, seq)
        assert len(result) == {7: 0, 16: 1, 17: 2, 19: 0}[op]


@pytest.mark.parametrize("count,interface", [(0, "management"), (7307, "management"),
    (MAX_SNAPSHOT_ENTRIES, "management"), (MAX_SNAPSHOT_ENTRIES, "a" * 64)])
def test_complete_large_streams_split_entries_and_preserve_every_pair(count, interface):
    frames = wire(count, interface=interface)
    decoder = SnapshotDecoder(frames[0], 7, 0)
    for frame in frames[1:-1]:
        assert decoder.accept(frame) is None, "No partial snapshot may escape"
        assert len(frame) <= 32775
    result = decoder.accept(frames[-1])
    assert len(result) == count
    assert all(entry.interface == interface for entry in result)
    if count:
        assert result[-1].ip == IPv4Address(0xC6120000 + count - 1)
    with pytest.raises(ValueError):
        decoder.accept(frames[-1])


@pytest.mark.parametrize("manifest", [b"", b"\x01", wire()[0] + b"\x00",
    bytes([0, 3, 7, 0, 0]) + pack(">IIH", 0, 0, 0),
    bytes([0, 2, 7, 0, 0]) + pack(">IIH", MAX_SNAPSHOT_ENTRIES + 1, 0, 0),
    bytes([0, 2, 7, 0, 0]) + pack(">IIH", 1, MAX_SNAPSHOT_BYTES + 1, 65),
    bytes([0, 2, 7, 0, 0]) + pack(">IIH", 1, 0, 0),
    bytes([0, 2, 7, 0, 0]) + pack(">IIH", 0, 1, 1),
    bytes([0, 2, 7, 0, 0]) + pack(">IIH", 1, 15, 0)])
def test_manifest_is_exact_and_bounded_before_allocation(manifest):
    with pytest.raises(ValueError):
        SnapshotDecoder(manifest, 7, 0)


@pytest.mark.parametrize("fault", ["reorder", "duplicate", "missing", "wrong_binding", "short", "long", "bad_hash", "trailing_end"])
def test_bad_streams_fail_closed(fault):
    frames = wire(7307)
    if fault == "reorder":
        frames[1], frames[2] = frames[2], frames[1]
    elif fault == "duplicate":
        frames.insert(2, frames[1])
    elif fault == "missing":
        del frames[2]
    elif fault == "wrong_binding":
        frames[2] = frames[2][:3] + b"\x01" + frames[2][4:]
    elif fault == "short":
        frames[1] = frames[1][:-1]
    elif fault == "long":
        frames[1] += b"x"
    elif fault == "bad_hash":
        frames[-1] = frames[-1][:-1] + bytes([frames[-1][-1] ^ 1])
    else:
        frames[-1] += b"x"
    with pytest.raises(ValueError):
        assemble(frames)


@pytest.mark.parametrize("data,count", [(b"\xc6\x12\x00\x01\x00", 1),
    (b"\xc6\x12\x00\x01\x01$", 1), (b"\xc6\x12\x00\x01\x01\xff", 1),
    (b"\xc6\x12\x00\x01\x01a" * 2, 2), (b"\xc6\x12\x00\x01\x01ab", 1)])
def test_even_correct_digests_cannot_authorize_malformed_entries(data, count):
    with pytest.raises(ValueError):
        assemble(wire(count, data=data))


def serve(tmp_path, handler):
    listener = socket(AF_UNIX, SOCK_SEQPACKET)
    path = str(tmp_path / "agent.sock")
    listener.bind(path)
    listener.listen(1)
    listener.settimeout(5)
    pool = ThreadPoolExecutor(max_workers=1)

    def run():
        with listener:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                handler(connection)
    return path, pool, pool.submit(run)


def test_actual_seqpacket_transport_collects_a_large_snapshot(tmp_path):
    def handler(connection):
        assert connection.recv(100) == bytes.fromhex("070007")
        for frame in wire(7307):
            assert connection.send(frame) == len(frame)
        assert connection.recv(100) == b""
    path, pool, worker = serve(tmp_path, handler)
    try:
        assert len(UnixAgentClient(path, 5, large_snapshots=True).list_shuns(7)) == 7307
        worker.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize("failure", ["reject", "eof", "truncated", "corrupt"])
def test_stream_failure_closes_connection_without_retry_or_empty_success(tmp_path, failure):
    def handler(connection):
        assert connection.recv(100) == bytes.fromhex("070007")
        frames = wire(7307)
        if failure == "reject":
            frames = [b"\x01"]
        elif failure == "eof":
            frames = frames[:2]
        elif failure == "truncated":
            frames = [frames[0], b"x" * 65537]
        else:
            frames[-1] = frames[-1][:-1] + bytes([frames[-1][-1] ^ 1])
        for frame in frames:
            connection.send(frame)
    path, pool, worker = serve(tmp_path, handler)
    try:
        with pytest.raises(AgentUnavailable):
            UnixAgentClient(path, 5, large_snapshots=True).list_shuns(7)
        worker.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_v2_cycle_streams_and_existing_removal_results_share_one_socket(tmp_path):
    def handler(connection):
        for request, frames in [
            ("10020007", wire(7307, opcode=16)),
            ("120201cb007111", [bytes.fromhex("0002120101")]),
            ("110202", [bytes.fromhex("02021102")]),
            ("130203", wire(0, opcode=19, sequence=3)),
        ]:
            assert connection.recv(100).hex() == request
            for frame in frames:
                connection.send(frame)
        assert connection.recv(100) == b""
    path, pool, worker = serve(tmp_path, handler)
    try:
        cycle = UnixAgentClient(path, 5, large_snapshots=True).open_cycle(7)
        assert len(cycle.initial_snapshot) == 7307
        assert cycle.remove_shun(IPv4Address("203.0.113.17")) is True
        assert cycle.snapshot() is None
        assert cycle.finish() == [] and cycle.closed
        worker.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_stream_has_an_absolute_transfer_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_client, "SNAPSHOT_TRANSFER_SECONDS", 0.08)
    def handler(connection):
        assert connection.recv(100) == bytes.fromhex("070007")
        frames = wire(7307)
        connection.send(frames[0])
        for frame in frames[1:]:
            sleep(0.03)
            try:
                connection.send(frame)
            except BrokenPipeError:
                return
    path, pool, worker = serve(tmp_path, handler)
    try:
        started = monotonic()
        with pytest.raises(AgentUnavailable):
            UnixAgentClient(path, 5, large_snapshots=True).list_shuns(7)
        assert monotonic() - started < 1
        worker.result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_large_snapshot_flag_is_opt_in_and_strict(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", raising=False)
    assert not Settings.from_environment().large_snapshots_enabled
    monkeypatch.setenv("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", "true")
    assert Settings.from_environment().large_snapshots_enabled
    monkeypatch.setenv("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", "1")
    with pytest.raises(ValueError, match="LARGE_SNAPSHOTS"):
        Settings.from_environment()


@pytest.mark.parametrize("opcode,sequence", [(7, 1), (16, 1), (17, 0), (19, 19), (18, 1)])
def test_invalid_snapshot_operation_sequence_bindings_are_rejected(opcode, sequence):
    with pytest.raises(ValueError):
        SnapshotDecoder(wire(opcode=opcode, sequence=sequence)[0], opcode, sequence)


def test_incomplete_stream_never_reconciles_away_existing_state(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(7, "fixture-ftd", IPv4Address("192.0.2.7"), True), "ssh-ed25519 AAAA")
    target = IPv4Address("198.51.100.251")
    store.record_observed_shun(7, target, "management")
    before = store.list_events()

    def handler(connection):
        assert connection.recv(100) == bytes.fromhex("070007")
        # A valid empty manifest WITHOUT its mandatory digest is a failed read,
        # never an authoritative empty observation.
        connection.send(wire()[0])
    path, pool, worker = serve(tmp_path, handler)
    try:
        synchronizer = Synchronizer(store, UnixAgentClient(path, 5, large_snapshots=True), 300, 60)
        asyncio.run(synchronizer._sweep())
        assert [row.ip for row in store.list_active_shuns()] == [target]
        assert store.list_events() == before
        assert synchronizer.status()["last_error"] is not None
        assert synchronizer.status()["data_revision"] == 0
        assert synchronizer.queue.status()["counts"] == {}
        worker.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
