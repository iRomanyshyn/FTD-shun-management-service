"""Fixed binary protocol for the privileged agent boundary.

No Cisco CLI text belongs in this module or crosses this boundary.
"""

from dataclasses import dataclass
from enum import IntEnum
from ipaddress import IPv4Address

MAX_AGENT_RESPONSE_BYTES = 64 * 1024
_SUCCESS = 0x00


@dataclass(frozen=True, order=True)
class ObservedShun:
    ip: IPv4Address
    interface: str


class Operation(IntEnum):
    LIST_SHUNS = 0x01
    GET_SHUN = 0x02
    REMOVE_SHUN = 0x03
    GET_RA_AUTH_STATUS = 0x04
    GET_RA_INIT_STATUS = 0x05
    HEALTH = 0x06


_IP_OPERATIONS = {Operation.GET_SHUN, Operation.REMOVE_SHUN}


def encode_request(operation: Operation, device_id: int, ip: IPv4Address | None = None) -> bytes:
    """Encode one complete SOCK_SEQPACKET request and validate its exact shape."""
    if not 1 <= device_id <= 65535:
        raise ValueError("device_id must be between 1 and 65535")
    if operation in _IP_OPERATIONS and ip is None:
        raise ValueError(f"{operation.name} requires an IPv4 address")
    if operation not in _IP_OPERATIONS and ip is not None:
        raise ValueError(f"{operation.name} does not accept an IPv4 address")
    payload = bytes([operation]) + device_id.to_bytes(2, "big")
    return payload + (ip.packed if ip else b"")


def decode_request(packet: bytes) -> tuple[Operation, int, IPv4Address | None]:
    """Strictly decode a single request; unknown operations and lengths fail closed."""
    if len(packet) not in {3, 7}:
        raise ValueError("invalid packet length")
    try:
        operation = Operation(packet[0])
    except ValueError as error:
        raise ValueError("unknown operation") from error
    requires_ip = operation in _IP_OPERATIONS
    if requires_ip != (len(packet) == 7):
        raise ValueError("invalid packet length for operation")
    device_id = int.from_bytes(packet[1:3], "big")
    if device_id == 0:
        raise ValueError("device_id must not be zero")
    return operation, device_id, IPv4Address(packet[3:]) if requires_ip else None


def decode_list_shuns_response(packet: bytes) -> list[ObservedShun]:
    """Decode the agent's fixed binary complete-snapshot response."""
    if len(packet) > MAX_AGENT_RESPONSE_BYTES:
        raise ValueError("agent list-shuns response exceeds the maximum size")
    if len(packet) < 3 or packet[0] != _SUCCESS:
        raise ValueError("agent did not return a list-shuns success response")
    expected_count = int.from_bytes(packet[1:3], "big")
    offset = 3
    entries: list[ObservedShun] = []
    for _ in range(expected_count):
        if offset + 5 > len(packet):
            raise ValueError("agent list-shuns response is truncated")
        ip = IPv4Address(packet[offset : offset + 4])
        interface_length = packet[offset + 4]
        offset += 5
        if not 1 <= interface_length <= 64 or offset + interface_length > len(packet):
            raise ValueError("agent list-shuns interface field is invalid")
        try:
            interface = packet[offset : offset + interface_length].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("agent list-shuns interface is not ASCII") from error
        offset += interface_length
        if not _valid_interface(interface):
            raise ValueError("agent list-shuns interface is invalid")
        entries.append(ObservedShun(ip, interface))
    if offset != len(packet) or len(set(entries)) != len(entries):
        raise ValueError("agent list-shuns response is malformed")
    return entries


def _valid_interface(value: str) -> bool:
    return (
        1 <= len(value) <= 64
        and value[0].isalpha()
        and value.isascii()
        and all(character.isalnum() or character in "/._-" for character in value)
    )
