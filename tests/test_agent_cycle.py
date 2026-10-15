import json
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from pathlib import Path
from socket import AF_UNIX, SOCK_SEQPACKET, socket

import pytest

from ftd_shun_manager.agent_client import AgentUnavailable, UnixAgentClient
from ftd_shun_manager.agent_protocol import (
    CycleOperation,
    decode_cycle_response,
    encode_cycle_request,
)
from ftd_shun_manager.config import Settings


def test_shared_cycle_wire_vectors():
    vectors = json.loads((Path(__file__).parent / "fixtures/agent-cycle-v1.json").read_text())
    for vector in vectors:
        operation = CycleOperation(vector["operation"])
        fields = {}
        if "device_id" in vector:
            fields["device_id"] = vector["device_id"]
        if "ip" in vector:
            fields["ip"] = IPv4Address(vector["ip"])
        assert encode_cycle_request(operation, vector["sequence"], **fields).hex() == vector["request"]
        result = decode_cycle_response(bytes.fromhex(vector["response"]), operation, vector["sequence"])
        assert result == (None if vector["response"].startswith("02") else
                          True if operation == CycleOperation.REMOVE else [])


@pytest.mark.parametrize("packet", [b"", b"\x01", bytes.fromhex("0001120200"),
    bytes.fromhex("0002120101"), bytes.fromhex("0001120102"),
    bytes.fromhex("0201120100"), bytes.fromhex("000112010100")])
def test_bad_cycle_responses_fail_closed(packet):
    with pytest.raises(ValueError):
        decode_cycle_response(packet, CycleOperation.REMOVE, 1)


@pytest.mark.parametrize("fields", [
    (CycleOperation.BEGIN, 1, {"device_id": 7}),
    (CycleOperation.BEGIN, 0, {"device_id": 0}),
    (CycleOperation.REMOVE, 1, {}),
    (CycleOperation.END, 0, {}),
    (CycleOperation.END, 1, {"ip": IPv4Address("203.0.113.1")}),
    (CycleOperation.SNAPSHOT, 19, {}),
])
def test_bad_cycle_requests_fail_closed(fields):
    with pytest.raises(ValueError):
        encode_cycle_request(fields[0], fields[1], **fields[2])


def test_cycle_uses_one_seqpacket_connection_and_ordered_steps(tmp_path):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(5)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                frames = [
                    ("10010007", "00011000000000"),
                    ("120101cb007111", "0001120101"),
                    ("110102", "00011102000000"),
                    ("130103", "00011303000000"),
                ]
                for request, response in frames:
                    assert connection.recv(100).hex() == request
                    connection.send(bytes.fromhex(response))
                assert connection.recv(100) == b""

        worker = pool.submit(server)
        cycle = UnixAgentClient(path, 5).open_cycle(7)
        assert cycle.initial_snapshot == []
        assert cycle.remove_shun(IPv4Address("203.0.113.17")) is True
        assert cycle.snapshot() == []
        assert cycle.finish() == []
        assert cycle.closed
        worker.result(timeout=5)


@pytest.mark.parametrize("response", [b"\x01", bytes.fromhex("0001120201"), b"x" * 65537])
def test_transport_rejection_or_truncation_closes_without_retry(tmp_path, response):
    path = str(tmp_path / "agent.sock")
    with socket(AF_UNIX, SOCK_SEQPACKET) as listener, ThreadPoolExecutor() as pool:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(5)

        def server():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                assert connection.recv(100).hex() == "10010007"
                connection.send(bytes.fromhex("00011000000000"))
                assert connection.recv(100).hex() == "120101cb007111"
                connection.send(response)
                assert connection.recv(100) == b""

        worker = pool.submit(server)
        cycle = UnixAgentClient(path, 5).open_cycle(7)
        with pytest.raises(AgentUnavailable):
            cycle.remove_shun(IPv4Address("203.0.113.17"))
        assert cycle.closed
        with pytest.raises(AgentUnavailable):
            cycle.finish()
        worker.result(timeout=5)


def test_cycle_flag_is_opt_in_and_strict(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_AGENT_CYCLES_ENABLED", raising=False)
    assert not Settings.from_environment().agent_cycles_enabled
    monkeypatch.setenv("FTD_SHUN_AGENT_CYCLES_ENABLED", "true")
    assert Settings.from_environment().agent_cycles_enabled
    monkeypatch.setenv("FTD_SHUN_AGENT_CYCLES_ENABLED", "maybe")
    with pytest.raises(ValueError, match="CYCLES_ENABLED"):
        Settings.from_environment()
