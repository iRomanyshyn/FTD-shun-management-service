"""Fixed binary protocol for the privileged agent boundary.

No Cisco CLI text belongs in this module or crosses this boundary.
"""

from enum import IntEnum
from ipaddress import IPv4Address


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
