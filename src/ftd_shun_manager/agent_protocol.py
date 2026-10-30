"""Fixed binary protocol for the privileged agent boundary.

No Cisco CLI text belongs in this module or crosses this boundary.
"""

from dataclasses import dataclass
from enum import IntEnum
from ipaddress import IPv4Address

MAX_AGENT_RESPONSE_BYTES = 64 * 1024
CYCLE_VERSION = 1
MAX_CYCLE_REMOVALS = 16
_SUCCESS = 0x00


@dataclass(frozen=True, order=True)
class ObservedShun:
    ip: IPv4Address
    interface: str


@dataclass(frozen=True)
class AdditionResult:
    """No-op has no creation scope/provenance; only a verified add has one."""

    created: bool
    interface: str | None = None


class Operation(IntEnum):
    LIST_SHUNS = 0x01
    GET_SHUN = 0x02
    REMOVE_SHUN = 0x03
    GET_RA_AUTH_STATUS = 0x04
    GET_RA_INIT_STATUS = 0x05
    HEALTH = 0x06
    LIST_SHUNS_LARGE = 0x07


class CycleOperation(IntEnum):
    BEGIN = 0x10
    SNAPSHOT = 0x11
    REMOVE = 0x12
    END = 0x13
    ADD = 0x14
    BEGIN_SETTLED = 0x16
    BEGIN_RECOVERABLE = 0x17


def encode_cycle_request(operation: CycleOperation, sequence: int, *,
                         device_id: int | None = None, ip: IPv4Address | None = None,
                         version: int = CYCLE_VERSION) -> bytes:
    if version not in (1, 2, 3):
        raise ValueError("invalid cycle version")
    operation = CycleOperation(operation)
    if operation == CycleOperation.ADD and version != 3:
        raise ValueError("ADD requires cycle version 3")
    if operation in {CycleOperation.BEGIN, CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE}:
        if sequence != 0 or device_id is None or not 1 <= device_id <= 65535 or ip is not None:
            raise ValueError("invalid cycle begin fields")
        return bytes([operation, version]) + device_id.to_bytes(2, "big")
    if not 1 <= sequence <= MAX_CYCLE_REMOVALS + 2 or device_id is not None:
        raise ValueError("invalid cycle sequence or device")
    if (operation in {CycleOperation.REMOVE, CycleOperation.ADD}) != (ip is not None):
        raise ValueError("invalid cycle target")
    if ip is not None and not isinstance(ip, IPv4Address):
        raise ValueError("cycle target must be an IPv4 address")
    return bytes([operation, version, sequence]) + (ip.packed if ip else b"")


def decode_cycle_response(packet: bytes, operation: CycleOperation, sequence: int, *, version: int = CYCLE_VERSION):
    if version not in (1, 2, 3):
        raise ValueError("invalid cycle version")
    operation = CycleOperation(operation)
    if operation == CycleOperation.ADD and version != 3:
        raise ValueError("ADD requires cycle version 3")
    begin = operation in {CycleOperation.BEGIN, CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE}
    if (begin and sequence != 0) or (
        not begin and not 1 <= sequence <= MAX_CYCLE_REMOVALS + 2
    ):
        raise ValueError("invalid cycle response sequence")
    if len(packet) > MAX_AGENT_RESPONSE_BYTES or len(packet) < 4:
        raise ValueError("invalid cycle response size")
    if packet[1:4] != bytes([version, operation, sequence]):
        raise ValueError("cycle response version, operation, or sequence mismatch")
    if operation in {CycleOperation.REMOVE, CycleOperation.ADD, CycleOperation.SNAPSHOT} and packet == bytes(
        [2, version, operation, sequence]
    ):
        return None  # Explicit deferral, never an observed snapshot or successful write.
    if operation == CycleOperation.ADD:
        if packet == bytes([0, version, operation, sequence, 0]):
            return AdditionResult(False)
        if len(packet) < 7 or packet[0] != 0 or packet[4] != 1 or len(packet) != 6 + packet[5]:
            raise ValueError("invalid cycle addition result")
        try:
            interface = packet[6:].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("addition interface must be ASCII") from error
        if not _valid_interface(interface):
            raise ValueError("invalid addition interface")
        return AdditionResult(True, interface)
    if operation == CycleOperation.REMOVE:
        if len(packet) != 5 or packet[0] != 0 or packet[4] not in (0, 1):
            raise ValueError("invalid cycle removal result")
        return bool(packet[4])
    if packet[0] != 0:
        raise ValueError("cycle request rejected")
    if version >= 2:
        raise ValueError("versioned snapshots require the complete stream decoder")
    return decode_list_shuns_response(packet[4:])


def decode_cycle_settlement(packet: bytes, sequence: int, *, version: int, begin=CycleOperation.BEGIN_SETTLED):
    """Local completed-handler receipt, never mutation/recovery authority."""
    if (type(version) is not int or version not in (1, 2, 3)
            or begin not in (CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE)
            or type(sequence) is not int or not 1 <= sequence <= MAX_CYCLE_REMOVALS + 2
            or packet != bytes([0, version, begin, sequence])):
        raise ValueError('Missing or invalid exact cycle settlement receipt.')


def decode_cycle_open_failure(packet: bytes, *, version: int):
    """Exact terminal proof that opening ended before any Cisco command."""
    if (type(version) is not int or version not in (1, 2, 3)
            or packet != bytes([3, version, CycleOperation.BEGIN_RECOVERABLE, 0])):
        raise ValueError('Missing or invalid exact cycle opening-failure receipt.')


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
    return _decode_shun_entries(packet[3:], int.from_bytes(packet[1:3], "big"))


def _decode_shun_entries(packet: bytes, expected_count: int) -> list[ObservedShun]:
    """Shared strict entry decoder; outer legacy/stream layers enforce budgets."""
    offset = 0
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
