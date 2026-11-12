"""Fixed binary protocol for the privileged agent boundary.

No Cisco CLI text belongs in this module or crosses this boundary.
"""

from dataclasses import dataclass
from enum import IntEnum
from ipaddress import IPv4Address

MAX_AGENT_RESPONSE_BYTES = 64 * 1024
CYCLE_VERSION = 1
MAX_CYCLE_REMOVALS = 16
MAX_PENDING_ADDITIONS = 16
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


@dataclass(frozen=True)
class PendingAddition:
    """Strict write acknowledgement only. Never creation or success evidence."""

    ip: IPv4Address
    sequence: int


@dataclass(frozen=True)
class VerifiedAdditionBatch:
    """Exact ordered pending scope plus its completely received observation."""

    additions: tuple[tuple[IPv4Address, AdditionResult], ...]
    snapshot: tuple[ObservedShun, ...]


@dataclass(frozen=True)
class SettledPendingAdditions:
    """Transport-only ACK/closed-session evidence, NOT presence or creation.

    Only the explicit deferred queue can atomically retain it with original
    claim/ACK proof and release its live lease. Ordinary queues refuse it.
    """

    device_id: int
    session_id: bytes
    sequence: int
    acknowledgements: tuple[PendingAddition, ...]


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
    BEGIN_TRACKED = 0x18
    STAGE_ADD = 0x1a
    VERIFY_ADDS = 0x1b
    VERIFY_END = 0x1c
    END_PENDING = 0x1d


SESSION_LOOKUP = 0x19
PENDING_SESSION_LOOKUP = 0x1e


def max_cycle_sequence(version: int) -> int:
    return 130 if version in (6, 7) else 34 if version in (4, 5) else MAX_CYCLE_REMOVALS + 2


def max_cycle_mutations(version: int) -> int:
    return 64 if version in (6, 7) else MAX_CYCLE_REMOVALS


def max_pending_additions(version: int) -> int:
    if type(version) is not int or version not in (4, 5, 6, 7):
        raise ValueError('Pending additions require a grouped cycle version.')
    return 8 if version == 4 else MAX_PENDING_ADDITIONS


def encode_session_request(operation: int, version: int, device_id: int, session_id: bytes):
    if (type(operation) is not int or operation not in (0x18, SESSION_LOOKUP, PENDING_SESSION_LOOKUP)
            or type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7)
            or (operation == PENDING_SESSION_LOOKUP and version != 7)
            or type(device_id) is not int or not 1 <= device_id <= 65535
            or type(session_id) is not bytes or len(session_id) != 16 or not any(session_id)):
        raise ValueError('Invalid exact session binding.')
    return bytes([operation, version]) + device_id.to_bytes(2, 'big') + session_id


def decode_session_lookup(packet: bytes, version: int, device_id: int, session_id: bytes):
    request = encode_session_request(SESSION_LOOKUP, version, device_id, session_id)
    if len(packet) != 21 or packet[0] not in (0, 1, 2) or packet[1:] != request[1:2] + bytes([SESSION_LOOKUP]) + request[2:]:
        raise ValueError('Missing or invalid exact session lookup receipt.')
    return packet[0] == 0


def encode_cycle_request(operation: CycleOperation, sequence: int, *,
                         device_id: int | None = None, ip: IPv4Address | None = None,
                         version: int = CYCLE_VERSION) -> bytes:
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7):
        raise ValueError("invalid cycle version")
    operation = CycleOperation(operation)
    if operation == CycleOperation.END_PENDING and version != 7:
        raise ValueError('Pending-only end requires tracked cycle version 7')
    if operation == CycleOperation.ADD and version != 3:
        raise ValueError("ADD requires cycle version 3")
    if operation in {CycleOperation.STAGE_ADD, CycleOperation.VERIFY_ADDS} and version not in (4, 5, 6, 7):
        raise ValueError("Batch additions require a tracked grouped cycle version")
    if operation == CycleOperation.VERIFY_END and version not in (5, 6, 7):
        raise ValueError('Combined verification/end requires a shared-end cycle version')
    if operation in {CycleOperation.BEGIN, CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE}:
        if version in (4, 5, 6, 7):
            raise ValueError("Batch cycles require tracked BEGIN")
        if sequence != 0 or device_id is None or not 1 <= device_id <= 65535 or ip is not None:
            raise ValueError("invalid cycle begin fields")
        return bytes([operation, version]) + device_id.to_bytes(2, "big")
    if operation == CycleOperation.BEGIN_TRACKED:
        raise ValueError("Tracked BEGIN requires an exact session identity")
    if type(sequence) is not int or not 1 <= sequence <= max_cycle_sequence(version) or device_id is not None:
        raise ValueError("invalid cycle sequence or device")
    if (operation in {CycleOperation.REMOVE, CycleOperation.ADD, CycleOperation.STAGE_ADD}) != (ip is not None):
        raise ValueError("invalid cycle target")
    if ip is not None and not isinstance(ip, IPv4Address):
        raise ValueError("cycle target must be an IPv4 address")
    return bytes([operation, version, sequence]) + (ip.packed if ip else b"")


def decode_cycle_response(packet: bytes, operation: CycleOperation, sequence: int, *,
                          version: int = CYCLE_VERSION, target: IPv4Address | None = None):
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7):
        raise ValueError("invalid cycle version")
    operation = CycleOperation(operation)
    if operation == CycleOperation.END_PENDING:
        raise ValueError('Pending-only end requires its separate non-success decoder')
    if operation == CycleOperation.ADD and version != 3:
        raise ValueError("ADD requires cycle version 3")
    if operation in {CycleOperation.STAGE_ADD, CycleOperation.VERIFY_ADDS} and version not in (4, 5, 6, 7):
        raise ValueError("Batch additions require a tracked grouped cycle version")
    if operation == CycleOperation.VERIFY_END and version not in (5, 6, 7):
        raise ValueError('Combined verification/end requires a shared-end cycle version')
    begin = operation in {CycleOperation.BEGIN, CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE, CycleOperation.BEGIN_TRACKED}
    if (begin and sequence != 0) or (
        not begin and not 1 <= sequence <= max_cycle_sequence(version)
    ):
        raise ValueError("invalid cycle response sequence")
    if len(packet) > MAX_AGENT_RESPONSE_BYTES or len(packet) < 4:
        raise ValueError("invalid cycle response size")
    if packet[1:4] != bytes([version, operation, sequence]):
        raise ValueError("cycle response version, operation, or sequence mismatch")
    if operation in {CycleOperation.REMOVE, CycleOperation.ADD, CycleOperation.STAGE_ADD, CycleOperation.SNAPSHOT} and packet == bytes(
        [2, version, operation, sequence]
    ):
        return None  # Explicit deferral, never an observed snapshot or successful write.
    if operation == CycleOperation.STAGE_ADD:
        if packet == bytes([0, version, operation, sequence, 0]):
            return AdditionResult(False)
        # The client binds status 05 to its own request IP; a success-shaped
        # packet or interface field is forbidden at the staging boundary.
        if packet == bytes([5, version, operation, sequence]) and type(target) is IPv4Address:
            return PendingAddition(target, sequence)
        raise ValueError("invalid pending addition acknowledgement")
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
    if (type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7)
            or (version in (4, 5, 6, 7) and begin != CycleOperation.BEGIN_TRACKED)
            or begin not in (CycleOperation.BEGIN_SETTLED, CycleOperation.BEGIN_RECOVERABLE, CycleOperation.BEGIN_TRACKED)
            or type(sequence) is not int or not 1 <= sequence <= max_cycle_sequence(version)
            or packet != bytes([0, version, begin, sequence])):
        raise ValueError('Missing or invalid exact cycle settlement receipt.')


def decode_cycle_open_failure(packet: bytes, *, version: int, begin=CycleOperation.BEGIN_RECOVERABLE):
    """Exact terminal proof that opening ended before any Cisco command."""
    if (type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7)
            or (version in (4, 5, 6, 7) and begin != CycleOperation.BEGIN_TRACKED)
            or begin not in (CycleOperation.BEGIN_RECOVERABLE, CycleOperation.BEGIN_TRACKED)
            or packet != bytes([3, version, begin, 0])):
        raise ValueError('Missing or invalid exact cycle opening-failure receipt.')


def decode_cycle_read_failure(packet: bytes, operation: CycleOperation, sequence: int, *, version: int):
    """Terminal failed-read proof, never a snapshot or mutation success."""
    if (type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7)
            or (version in (4, 5, 6, 7) and operation == CycleOperation.BEGIN_RECOVERABLE)
            or type(sequence) is not int
            or not ((operation in (CycleOperation.BEGIN_RECOVERABLE, CycleOperation.BEGIN_TRACKED) and sequence == 0)
                    or (operation in (CycleOperation.SNAPSHOT, CycleOperation.END)
                        and 1 <= sequence <= max_cycle_sequence(version)))
            or packet != bytes([4, version, operation, sequence])):
        raise ValueError('Missing or invalid exact cycle read-failure receipt.')


def decode_pending_end(packet: bytes, sequence: int, pending: tuple[PendingAddition, ...], *, version: int):
    """Exact status-06 scope only; caller still must receive terminal settlement."""
    if (type(version) is not int or version != 7 or type(sequence) is not int
            or not 1 <= sequence <= max_cycle_sequence(version)
            or type(pending) is not tuple or not 1 <= len(pending) <= max_pending_additions(version)):
        raise ValueError('Invalid pending-only end binding or capacity.')
    seen, previous = set(), 0
    for item in pending:
        if (type(item) is not PendingAddition or type(item.ip) is not IPv4Address
                or type(item.sequence) is not int or not previous < item.sequence < sequence
                or item.ip in seen):
            raise ValueError('Pending-only end requires exact ordered original acknowledgements.')
        previous = item.sequence
        seen.add(item.ip)
    expected = bytes([6, version, CycleOperation.END_PENDING, sequence, len(pending)]) + b''.join(
        item.ip.packed for item in pending)
    if type(packet) is not bytes or packet != expected:
        raise ValueError('Pending-only end receipt differs from the original pending scope.')
    return pending


def decode_pending_lookup(packet: bytes, device_id: int, session_id: bytes, sequence: int,
                          pending: tuple[PendingAddition, ...]) -> SettledPendingAdditions:
    """Exact completed journal scope, never read-only proof or verified creation."""
    request = encode_session_request(PENDING_SESSION_LOOKUP, 7, device_id, session_id)
    if type(packet) is not bytes or packet[:21] != b'\x00\x07' + bytes([PENDING_SESSION_LOOKUP]) + request[2:]:
        raise ValueError('Pending completion is unavailable or has a foreign session binding.')
    acknowledgements = decode_pending_end(packet[21:], sequence, pending, version=7)
    return SettledPendingAdditions(device_id, session_id, sequence, acknowledgements)


def decode_addition_batch(packet: bytes, sequence: int, pending: tuple[IPv4Address, ...], *,
                          version: int = 4, operation: CycleOperation = CycleOperation.VERIFY_ADDS):
    """Decode only the proof header; a complete matching snapshot is also required."""
    if (operation not in (CycleOperation.VERIFY_ADDS, CycleOperation.VERIFY_END)
            or (operation == CycleOperation.VERIFY_END and version not in (5, 6, 7))
            or type(sequence) is not int or not 1 <= sequence <= max_cycle_sequence(version)
            or not 1 <= len(pending) <= max_pending_additions(version) or len(set(pending)) != len(pending)
            or any(type(ip) is not IPv4Address for ip in pending)
            or packet[:5] != bytes([0, version, operation, sequence, len(pending)])):
        raise ValueError("invalid pending addition receipt binding")
    offset = 5
    results = []
    for ip in pending:
        if len(packet) < offset + 5 or packet[offset:offset + 4] != ip.packed:
            raise ValueError("addition receipt target/order mismatch")
        size = packet[offset + 4]
        offset += 5
        try:
            interface = packet[offset:offset + size].decode('ascii')
        except UnicodeDecodeError as error:
            raise ValueError("addition receipt interface must be ASCII") from error
        if size != len(interface) or not _valid_interface(interface):
            raise ValueError("invalid addition receipt scope")
        results.append((ip, AdditionResult(True, interface)))
        offset += size
    if offset != len(packet):
        raise ValueError("trailing or truncated addition receipt")
    return tuple(results)


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
