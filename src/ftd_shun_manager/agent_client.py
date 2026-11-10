"""Typed interface to the privileged agent; raw command execution does not exist."""

from ipaddress import IPv4Address
from socket import AF_UNIX, MSG_TRUNC, SOCK_SEQPACKET, socket
from time import monotonic
from uuid import UUID

from .agent_protocol import (
    MAX_AGENT_RESPONSE_BYTES,
    SESSION_LOOKUP,
    AdditionResult,
    CycleOperation,
    ObservedShun,
    Operation,
    PendingAddition,
    SettledPendingAdditions,
    VerifiedAdditionBatch,
    decode_addition_batch,
    decode_cycle_open_failure,
    decode_cycle_read_failure,
    decode_cycle_response,
    decode_cycle_settlement,
    decode_list_shuns_response,
    decode_pending_end,
    decode_session_lookup,
    encode_cycle_request,
    encode_request,
    encode_session_request,
    max_pending_additions,
)
from .snapshot_protocol import SNAPSHOT_TRANSFER_SECONDS, SnapshotDecoder


class AgentUnavailable(RuntimeError):
    pass


class AgentCycleNotStarted(AgentUnavailable):
    """Local connect failed before BEGIN send; never a decoded agent response."""


class AgentCycleOpenFailed(AgentUnavailable):
    """Bound terminal agent proof: opening ended before any Cisco command."""


class AgentCycleReadFailed(AgentUnavailable):
    """Exact terminal read failure: no mutation steps and successful cleanup."""


def _connect_cycle(path, timeout_seconds):
    connection = None
    try:
        connection = socket(AF_UNIX, SOCK_SEQPACKET)
        connection.settimeout(timeout_seconds)
        connection.connect(path)
        return connection
    except BaseException as error:
        if connection is not None:
            connection.close()
        if isinstance(error, OSError):
            raise AgentCycleNotStarted('Agent socket connection unavailable; no cycle request submitted.') from error
        raise


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
    def __init__(self, socket_path: str, timeout_seconds: int = 125, *, large_snapshots: bool = False,
                 additions_enabled: bool = False, addition_device_ids: frozenset[int] | None = None,
                 settled_cycles: bool = False, recoverable_cycles: bool = False, tracked_cycles: bool = False,
                 batch_additions: bool = False, batch_session_version: int = 5) -> None:
        if type(settled_cycles) is not bool:
            raise ValueError('Settled cycle capability must be boolean.')
        if type(recoverable_cycles) is not bool or (recoverable_cycles and not settled_cycles):
            raise ValueError('Recoverable opening requires explicit strict settlement.')
        if type(tracked_cycles) is not bool or (tracked_cycles and not recoverable_cycles):
            raise ValueError('Tracked cycles require explicit recoverable strict cycles.')
        if additions_enabled and not large_snapshots:
            raise ValueError("addition cycles require large snapshots")
        if type(batch_additions) is not bool or (batch_additions and not (additions_enabled and tracked_cycles)):
            raise ValueError('Batch additions require explicit tracked addition cycles.')
        if (type(batch_session_version) is not int or batch_session_version not in (5, 6)
                or (batch_session_version == 6 and not batch_additions)):
            raise ValueError('Extended sessions require the explicit matching grouped capability.')
        self.batch_session_version = batch_session_version
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds
        self.large_snapshots = large_snapshots
        self.additions_enabled = additions_enabled
        # None preserves explicit low-level v3 callers. The API always supplies
        # an exact validated set, including empty: no implicit fleet capability.
        self.addition_device_ids = addition_device_ids
        self.settled_cycles = settled_cycles
        self.recoverable_cycles = recoverable_cycles
        self.tracked_cycles = tracked_cycles
        self.batch_additions = batch_additions

    def remove_shun(self, device_id: int, ip: IPv4Address) -> None:
        request = encode_request(Operation.REMOVE_SHUN, device_id, ip)
        response = self._request(request)
        # The agent response is deliberately tiny: 0x00 is verified success.
        if response != b"\x00":
            raise AgentUnavailable("agent did not return verified removal success")

    def list_shuns(self, device_id: int) -> list[ObservedShun]:
        if self.large_snapshots:
            request = encode_request(Operation.LIST_SHUNS_LARGE, device_id)
            try:
                with socket(AF_UNIX, SOCK_SEQPACKET) as connection:
                    deadline = monotonic() + self.timeout_seconds
                    connection.settimeout(self.timeout_seconds)
                    connection.connect(self.socket_path)
                    if connection.send(request) != len(request):
                        raise AgentUnavailable("large snapshot send was incomplete")
                    return _receive_snapshot(connection, Operation.LIST_SHUNS_LARGE, 0, deadline)
            except (OSError, ValueError) as error:
                raise AgentUnavailable("complete large snapshot unavailable; no fallback attempted") from error
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
        if self.tracked_cycles:
            raise AgentUnavailable('Tracked client requires explicit lease-bound session identity.')
        return self._open_cycle(device_id)

    def _open_cycle(self, device_id, session_id=None):
        addition_cycle = self.additions_enabled and (
            self.addition_device_ids is None or device_id in self.addition_device_ids
        )
        return UnixAgentCycle(self.socket_path, self.timeout_seconds, device_id,
                              version=self.batch_session_version if addition_cycle and self.batch_additions else 3 if addition_cycle else 2 if self.large_snapshots else 1,
                              settled_cycles=self.settled_cycles, recoverable_cycles=self.recoverable_cycles,
                              session_id=session_id)

    def open_tracked_cycle(self, device_id: int, lease_owner: str):
        if not self.tracked_cycles:
            raise AgentUnavailable('Tracked session capability is disabled.')
        return self._open_cycle(device_id, _session_id(lease_owner))

    def read_only_session_completed(self, device_id: int, lease_owner: str) -> bool:
        if not self.tracked_cycles:
            raise AgentUnavailable('Tracked session capability is disabled.')
        addition_cycle = self.additions_enabled and (self.addition_device_ids is None or device_id in self.addition_device_ids)
        version = self.batch_session_version if addition_cycle and self.batch_additions else 3 if addition_cycle else 2 if self.large_snapshots else 1
        session_id = _session_id(lease_owner)
        request = encode_session_request(SESSION_LOOKUP, version, device_id, session_id)
        try:
            with socket(AF_UNIX, SOCK_SEQPACKET) as connection:
                deadline = monotonic() + min(5, self.timeout_seconds)
                connection.settimeout(max(0.001, deadline - monotonic()))
                connection.connect(self.socket_path)
                connection.settimeout(max(0.001, deadline - monotonic()))
                if connection.send(request) != len(request):
                    raise AgentUnavailable('Session lookup send was incomplete.')
                return decode_session_lookup(_receive_before(connection, deadline), version, device_id, session_id)
        except (OSError, ValueError) as error:
            raise AgentUnavailable('Session completion proof unavailable; original hold retained.') from error


def _session_id(owner):
    if type(owner) is not str:
        raise ValueError('Canonical lease-owner UUIDv4 is required.')
    parsed = UUID(owner)
    if str(parsed) != owner or parsed.version != 4:
        raise ValueError('Canonical lease-owner UUIDv4 is required.')
    return parsed.bytes


def _receive_packet(connection: socket) -> bytes:
    packet, _, flags, _ = connection.recvmsg(MAX_AGENT_RESPONSE_BYTES)
    if flags & MSG_TRUNC or not packet:
        raise AgentUnavailable("agent response was truncated or the connection closed")
    return packet


def _receive_before(connection: socket, deadline: float) -> bytes:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise AgentUnavailable("agent response deadline expired")
    connection.settimeout(remaining)
    return _receive_packet(connection)


def _receive_snapshot(connection: socket, operation: int, sequence: int, deadline: float, *, version: int = 2,
                      read_failure: bool = False):
    manifest = _receive_before(connection, deadline)
    _check_open_failure(manifest, operation, sequence, version)
    _check_read_failure(manifest, operation, sequence, version, read_failure)
    if operation == CycleOperation.SNAPSHOT and manifest == bytes([2, version, operation, sequence]):
        return None
    decoder = SnapshotDecoder(manifest, operation, sequence, version=version)
    deadline = min(deadline, monotonic() + SNAPSHOT_TRANSFER_SECONDS)
    for _ in range(decoder.chunks + 1):
        packet = _receive_before(connection, deadline)
        _check_read_failure(packet, operation, sequence, version, read_failure)
        result = decoder.accept(packet)
        if result is not None:
            return result
    raise AgentUnavailable("snapshot did not complete")


def _check_open_failure(packet, operation, sequence, version):
    if operation in (CycleOperation.BEGIN_RECOVERABLE, CycleOperation.BEGIN_TRACKED) and sequence == 0 and packet[:1] == b'\x03':
        decode_cycle_open_failure(packet, version=version, begin=operation)
        raise AgentCycleOpenFailed('FTD SSH session opening failed; agent confirmed no Cisco commands submitted.')


def _check_read_failure(packet, operation, sequence, version, enabled):
    if enabled and packet[:1] == b'\x04':
        decode_cycle_read_failure(packet, operation, sequence, version=version)
        raise AgentCycleReadFailed('FTD read failed; agent confirmed read-only session cleanup and completion.')


def _receive_cycle_response(connection, deadline, operation, sequence, version, *, read_failure=False, target=None):
    packet = _receive_before(connection, deadline)
    _check_open_failure(packet, operation, sequence, version)
    _check_read_failure(packet, operation, sequence, version, read_failure)
    return decode_cycle_response(packet, operation, sequence, version=version, target=target)


def _receive_addition_batch(connection, deadline, sequence, pending, *, version, operation):
    additions = decode_addition_batch(_receive_before(connection, deadline), sequence, pending,
                                      version=version, operation=operation)
    snapshot = _receive_snapshot(connection, operation, sequence, deadline, version=version)
    # A proof header alone, truncated stream, or scope-conflicting complete
    # observation must never become a successful creation result.
    wanted = {ip for ip, _ in additions}
    observed = {}
    for entry in snapshot:
        if entry.ip in wanted:
            observed.setdefault(entry.ip, []).append(entry.interface)
    if any(observed.get(ip) != [result.interface] for ip, result in additions):
        raise ValueError('Batch receipt and complete snapshot scopes disagree.')
    return VerifiedAdditionBatch(additions, tuple(snapshot))


class UnixAgentCycle:
    """One sequential, device-bound binary conversation; never retries a step."""

    def __init__(self, path: str, timeout_seconds: int, device_id: int, *, version: int = 1,
                 settled_cycles: bool = False, recoverable_cycles: bool = False, session_id: bytes | None = None) -> None:
        if type(settled_cycles) is not bool:
            raise ValueError('Settled cycle capability must be boolean.')
        if type(recoverable_cycles) is not bool or (recoverable_cycles and not settled_cycles):
            raise ValueError('Recoverable opening requires explicit strict settlement.')
        if session_id is not None and not recoverable_cycles:
            raise ValueError('Bound session identity requires recoverable strict cycles.')
        if version in (4, 5, 6, 7) and session_id is None:
            raise ValueError('Batch cycles require a tracked session identity.')
        operation = (CycleOperation.BEGIN_TRACKED if session_id is not None else
                     CycleOperation.BEGIN_RECOVERABLE if recoverable_cycles else
                     CycleOperation.BEGIN_SETTLED if settled_cycles else CycleOperation.BEGIN)
        # Invalid requests must fail validation even when the socket is absent.
        if session_id is None:
            encode_cycle_request(operation, 0, device_id=device_id, version=version)
        else:
            encode_session_request(int(operation), version, device_id, session_id)
        self.connection = _connect_cycle(path, timeout_seconds)
        self.sequence = 0
        self.closed = False
        self.version = version
        self.device_id = device_id
        self.timeout_seconds = timeout_seconds
        self.settled_cycles = settled_cycles
        self.begin_operation = operation
        self.settled = False
        self.recoverable_cycles = recoverable_cycles
        self.mutation_attempted = False
        self.session_id = session_id
        self.pending_additions: list[PendingAddition] = []
        try:
            self.initial_snapshot = self._exchange(operation, device_id=device_id)
        except BaseException:
            self.abort()
            raise

    def _exchange(self, operation: CycleOperation, *, _deadline=None, **fields):
        if self.closed:
            raise AgentUnavailable("agent cycle is closed")
        try:
            deadline = monotonic() + self.timeout_seconds if _deadline is None else _deadline
            self.connection.settimeout(self.timeout_seconds)
            request = (encode_session_request(int(operation), self.version, fields['device_id'], self.session_id)
                       if operation == CycleOperation.BEGIN_TRACKED else
                       encode_cycle_request(operation, self.sequence, version=self.version, **fields))
            if operation in (CycleOperation.ADD, CycleOperation.REMOVE, CycleOperation.STAGE_ADD):
                self.mutation_attempted = True  # Before even a short/failed send.
            read_failure = self.recoverable_cycles and not self.mutation_attempted
            if self.connection.send(request) != len(request):
                raise AgentUnavailable("agent cycle send was incomplete")
            result = (
                decode_pending_end(_receive_before(self.connection, deadline), self.sequence,
                                   tuple(self.pending_additions), version=self.version)
                if operation == CycleOperation.END_PENDING else
                _receive_addition_batch(self.connection, deadline, self.sequence,
                                       tuple(item.ip for item in self.pending_additions),
                                       version=self.version, operation=operation)
                if operation in (CycleOperation.VERIFY_ADDS, CycleOperation.VERIFY_END) else
                _receive_snapshot(self.connection, operation, self.sequence, deadline, version=self.version,
                                  read_failure=read_failure)
                if self.version >= 2 and operation not in {CycleOperation.REMOVE, CycleOperation.ADD, CycleOperation.STAGE_ADD} else
                _receive_cycle_response(self.connection, deadline, operation, self.sequence, self.version,
                                        read_failure=read_failure, target=fields.get('ip'))
            )
            self.sequence += 1
            return result
        except (AgentCycleOpenFailed, AgentCycleReadFailed):
            self.abort()
            raise
        except (OSError, ValueError, AgentUnavailable) as error:
            self.abort()
            raise AgentUnavailable("agent cycle step failed; no retry was attempted") from error

    def snapshot(self) -> list[ObservedShun] | None:
        self._require_verified_additions()
        return self._exchange(CycleOperation.SNAPSHOT)

    def remove_shun(self, ip: IPv4Address) -> bool | None:
        self._require_verified_additions()
        return self._exchange(CycleOperation.REMOVE, ip=ip)

    def add_shun(self, ip: IPv4Address) -> AdditionResult | None:
        return self._exchange(CycleOperation.ADD, ip=ip)

    def stage_addition(self, ip: IPv4Address) -> PendingAddition | AdditionResult | None:
        if (self.version not in (4, 5, 6, 7) or len(self.pending_additions) >= max_pending_additions(self.version)
                or any(item.ip == ip for item in self.pending_additions)):
            raise ValueError('Invalid batch version, capacity or duplicate pending target.')
        result = self._exchange(CycleOperation.STAGE_ADD, ip=ip)
        if isinstance(result, PendingAddition):
            self.pending_additions.append(result)
        return result

    def verify_additions(self) -> VerifiedAdditionBatch:
        if self.version not in (4, 5, 6, 7) or not self.pending_additions:
            raise ValueError('A nonempty grouped cycle is required.')
        result = self._exchange(CycleOperation.VERIFY_ADDS)
        self.pending_additions.clear()  # Only after proof AND the complete observation.
        return result

    def finish_additions(self) -> VerifiedAdditionBatch:
        """One final full read proves pending ADDs and settles this session."""
        if self.version not in (5, 6, 7) or not self.pending_additions:
            raise ValueError('Combined verification/end requires a nonempty v5 group.')
        try:
            deadline = monotonic() + self.timeout_seconds
            result = self._exchange(CycleOperation.VERIFY_END, _deadline=deadline)
            decode_cycle_settlement(
                _receive_before(self.connection, min(deadline, monotonic() + 5)),
                self.sequence - 1, version=self.version, begin=self.begin_operation)
            self.settled = True
            self.pending_additions.clear()
            return result
        except (OSError, ValueError, AgentUnavailable) as error:
            raise AgentUnavailable('Final addition verification/settlement unavailable; no retry attempted.') from error
        finally:
            self.abort()

    def finish_pending_additions(self) -> SettledPendingAdditions:
        """Transport foundation only: no current worker releases jobs from this.

        End the exact acknowledged group without a verification read. Never
        substitute this for successful creation or retry a lost response.
        """
        if self.version != 7 or not self.pending_additions:
            raise ValueError('Pending-only end requires a nonempty tracked-v7 group.')
        try:
            deadline = monotonic() + self.timeout_seconds
            pending = self._exchange(CycleOperation.END_PENDING, _deadline=deadline)
            sequence = self.sequence - 1
            decode_cycle_settlement(
                _receive_before(self.connection, min(deadline, monotonic() + 5)),
                sequence, version=self.version, begin=self.begin_operation)
            self.settled = True
            self.pending_additions.clear()
            return SettledPendingAdditions(self.device_id, self.session_id, sequence, pending)
        except (OSError, ValueError, AgentUnavailable) as error:
            raise AgentUnavailable('Pending-only end/settlement unavailable; no retry attempted.') from error
        finally:
            self.abort()

    def _require_verified_additions(self):
        if self.pending_additions:
            raise AgentUnavailable('Pending additions require explicit batch verification first.')

    def finish(self) -> list[ObservedShun]:
        try:
            self._require_verified_additions()
            deadline = monotonic() + self.timeout_seconds
            snapshot = self._exchange(CycleOperation.END, _deadline=deadline)
            if self.settled_cycles:
                decode_cycle_settlement(
                    _receive_before(self.connection, min(deadline, monotonic() + 5)),
                    self.sequence - 1, version=self.version, begin=self.begin_operation)
                self.settled = True
            return snapshot
        except AgentCycleReadFailed:
            raise
        except (OSError, ValueError, AgentUnavailable) as error:
            raise AgentUnavailable('Final cycle snapshot/settlement unavailable; no retry attempted.') from error
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
