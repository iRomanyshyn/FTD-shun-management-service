"""Typed interface to the privileged agent; raw command execution does not exist."""

from ipaddress import IPv4Address
from socket import AF_UNIX, MSG_TRUNC, SOCK_SEQPACKET, socket

from .agent_protocol import (
    MAX_AGENT_RESPONSE_BYTES,
    CycleOperation,
    ObservedShun,
    Operation,
    decode_cycle_response,
    decode_list_shuns_response,
    encode_cycle_request,
    encode_request,
)


class AgentUnavailable(RuntimeError):
    pass


class AgentClient:
    def open_cycle(self, device_id: int) -> "UnixAgentCycle":
        raise AgentUnavailable("agent client does not support session cycles")

    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        raise NotImplementedError

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        raise NotImplementedError


class DisabledAgentClient(AgentClient):
    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        raise AgentUnavailable("FTD agent is disabled; no Cisco read was attempted")

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        raise AgentUnavailable("FTD agent is disabled; no Cisco write was attempted")


class UnixAgentClient(AgentClient):
    def __init__(self, socket_path: str, timeout_seconds: int = 125) -> None:
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        request = encode_request(Operation.REMOVE_SHUN, device_id, ip)
        response = self._request(request)
        # The agent response is deliberately tiny: 0x00 is verified success.
        if response != b"\x00":
            raise AgentUnavailable("agent did not return verified removal success")

    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        response = self._request(encode_request(Operation.LIST_SHUNS, device_id))
        try:
            return decode_list_shuns_response(response)
        except ValueError as error:
            raise AgentUnavailable("agent did not return a valid shun snapshot") from error

    def _request(self, request: bytes) -> bytes:
        try:
            with socket(AF_UNIX, SOCK_SEQPACKET) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(self.socket_path)
                connection.sendall(request)
                return _receive_packet(connection)
        except OSError as error:
            raise AgentUnavailable("agent socket request failed") from error

    def open_cycle(self, device_id: int) -> "UnixAgentCycle":
        return UnixAgentCycle(self.socket_path, self.timeout_seconds, device_id)


def _receive_packet(connection: socket) -> bytes:
    packet, _, flags, _ = connection.recvmsg(MAX_AGENT_RESPONSE_BYTES)
    if flags & MSG_TRUNC or not packet:
        raise AgentUnavailable("agent response was truncated or the connection closed")
    return packet


class UnixAgentCycle:
    """One sequential, device-bound binary conversation; never retries a step."""

    def __init__(self, path: str, timeout_seconds: int, device_id: int) -> None:
        self.connection = socket(AF_UNIX, SOCK_SEQPACKET)
        self.sequence = 0
        self.closed = False
        try:
            self.connection.settimeout(timeout_seconds)
            self.connection.connect(path)
            self.initial_snapshot = self._exchange(CycleOperation.BEGIN, device_id=device_id)
        except BaseException:
            self.abort()
            raise

    def _exchange(self, operation: CycleOperation, **fields):
        if self.closed:
            raise AgentUnavailable("agent cycle is closed")
        try:
            request = encode_cycle_request(operation, self.sequence, **fields)
            if self.connection.send(request) != len(request):
                raise AgentUnavailable("agent cycle send was incomplete")
            result = decode_cycle_response(_receive_packet(self.connection), operation, self.sequence)
            self.sequence += 1
            return result
        except (OSError, ValueError, AgentUnavailable) as error:
            self.abort()
            raise AgentUnavailable("agent cycle step failed; no retry was attempted") from error

    def snapshot(self) -> list[ObservedShun] | None:
        return self._exchange(CycleOperation.SNAPSHOT)

    def remove_shun(self, ip: IPv4Address) -> bool | None:
        return self._exchange(CycleOperation.REMOVE, ip=ip)

    def finish(self) -> list[ObservedShun]:
        try:
            return self._exchange(CycleOperation.END)
        finally:
            self.abort()

    def abort(self) -> None:
        if not self.closed:
            self.closed = True
            self.connection.close()


class MockAgentClient(AgentClient):
    """Development-only stand-in. Production deployments must not use this."""

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        encode_request(Operation.REMOVE_SHUN, device_id, ip)

    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        encode_request(Operation.LIST_SHUNS, device_id)
        return []
