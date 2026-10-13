"""Typed interface to the privileged agent; raw command execution does not exist."""

from ipaddress import IPv4Address
from socket import AF_UNIX, SOCK_SEQPACKET, socket

from .agent_protocol import Operation, encode_request


class AgentUnavailable(RuntimeError):
    pass


class AgentClient:
    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        raise NotImplementedError


class DisabledAgentClient(AgentClient):
    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        raise AgentUnavailable("FTD agent is disabled; no Cisco write was attempted")


class UnixAgentClient(AgentClient):
    def __init__(self, socket_path: str, timeout_seconds: int = 125) -> None:
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        request = encode_request(Operation.REMOVE_SHUN, device_id, ip)
        with socket(AF_UNIX, SOCK_SEQPACKET) as connection:
            connection.settimeout(self.timeout_seconds)
            connection.connect(self.socket_path)
            connection.sendall(request)
            response = connection.recv(16)
        # The agent response is deliberately tiny: 0x00 is verified success.
        if response != b"\x00":
            raise AgentUnavailable("agent did not return verified removal success")


class MockAgentClient(AgentClient):
    """Development-only stand-in. Production deployments must not use this."""

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        encode_request(Operation.REMOVE_SHUN, device_id, ip)
