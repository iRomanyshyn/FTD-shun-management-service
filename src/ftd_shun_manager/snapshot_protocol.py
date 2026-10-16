"""Bounded v2 snapshot assembly. No partial observation escapes this decoder."""

import hashlib
import hmac
from struct import unpack

from .agent_protocol import ObservedShun, _decode_shun_entries

SNAPSHOT_CHUNK_BYTES = 32768
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_ENTRIES = 20000
SNAPSHOT_TRANSFER_SECONDS = 10


class SnapshotDecoder:
    def __init__(self, manifest: bytes, opcode: int, sequence: int, *, version: int = 2):
        if (version not in (2, 3) or (opcode == 7 and version != 2)
                or opcode not in (7, 0x10, 0x11, 0x13)
                or (opcode in (7, 0x10) and sequence != 0)
                or (opcode in (0x11, 0x13) and not 1 <= sequence <= 18)):
            raise ValueError("invalid snapshot request binding")
        if len(manifest) != 15 or manifest[:5] != bytes([0, version, opcode, sequence, 0]):
            raise ValueError("invalid snapshot manifest")
        self.count, self.size, self.chunks = unpack(">IIH", manifest[5:])
        if (self.count > MAX_SNAPSHOT_ENTRIES or self.size > MAX_SNAPSHOT_BYTES
                or self.chunks != (self.size + SNAPSHOT_CHUNK_BYTES - 1) // SNAPSHOT_CHUNK_BYTES
                or not 6 * self.count <= self.size <= 69 * self.count):
            raise ValueError("invalid snapshot manifest bounds")
        self.binding = bytes([0, version, opcode, sequence])
        self.data = bytearray()
        self.index = 0
        self.finished = False

    def accept(self, packet: bytes) -> list[ObservedShun] | None:
        if self.finished or packet[:4] != self.binding:
            raise ValueError("invalid snapshot frame binding or trailing frame")
        if self.index < self.chunks:
            size = min(SNAPSHOT_CHUNK_BYTES, self.size - len(self.data))
            if (len(packet) != 7 + size or packet[4] != 1
                    or int.from_bytes(packet[5:7], "big") != self.index):
                raise ValueError("invalid snapshot chunk length, kind or index")
            self.data.extend(packet[7:])
            self.index += 1
            return None
        if len(packet) != 37 or packet[4] != 2 or not hmac.compare_digest(
            packet[5:], hashlib.sha256(self.data).digest()
        ):
            raise ValueError("invalid snapshot completion digest or length")
        result = _decode_shun_entries(bytes(self.data), self.count)
        self.finished = True
        self.data.clear()
        return result
