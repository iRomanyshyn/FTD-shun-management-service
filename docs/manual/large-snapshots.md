# Large Snapshots — Experimental Read Extension

## Gate and compatibility

`FTD_SHUN_LARGE_SNAPSHOTS_ENABLED=false` is the default in API and agent.
Enable both only in an approved non-production lab after paired upgrade.
No addition opcode, automatic import, broker, extra service or network port
is introduced. Legacy requests and cycle v1 retain their exact wire format,
64 KiB console/response limits and fail-closed behavior. There is no automatic
negotiation, reconnect, downgrade or replay after a rejection.

The flag selects read-only `LIST_SHUNS_LARGE` (`07 device:u16`, exactly 3 bytes)
for independent reads. When session cycles are also enabled, it selects cycle
version `02` in every request/response; request opcodes/layouts and REMOVE
success/no-op/deferral meanings are otherwise unchanged. Disabled/unsupported
large reads/v2 BEGIN are rejected before SSH. An API requesting the extension
from a disabled/old agent fails closed. An explicitly legacy-configured API
still uses legacy/v1 with a newer agent; that is selection, not a fallback
after failure. v2 supports existing removals only, not ADD.

## Exact response frames

AF_UNIX/SOCK_SEQPACKET with the existing peer UID check; unsigned big-endian
integers. Snapshot envelope is `00 02 opcode:u8 request_seq:u8 kind:u8`.
Independent large reads bind opcode `07`, sequence `00`. Cycle snapshots bind
BEGIN/SNAPSHOT/END and their exact request sequence. Every frame must match.

| Kind | Exact payload after envelope | Total length |
| --- | --- | --- |
| `00` manifest | `entry_count:u32 data_bytes:u32 chunk_count:u16` | 15 bytes |
| `01` data | `chunk_index:u16 bytes...` | 7 + the exact expected chunk length |
| `02` end | SHA-256 of concatenated data bytes | 37 bytes |

Data is the existing typed entry encoding without legacy status/count:
`IPv4:4 interface_length:u8 interface:ASCII`. Names retain the exact validated
1–64-byte grammar/allowlist; no raw Cisco output crosses the socket. Data chunks
are exactly 32768 bytes except the final remainder; indices start at zero and
are consecutive. An entry may cross a chunk boundary. Every nonempty snapshot
has `ceil(data_bytes/32768)` chunks. Empty is manifest 0/0/0 plus mandatory
SHA-256-of-empty end; rejection/EOF is never an empty snapshot.

Hard bounds: 20,000 entries, 2 MiB aggregate data, at most 64 data chunks,
at most 66 frames and no response frame larger than the existing 64 KiB receive
buffer. Manifest count/byte/chunk consistency is validated before buffering;
each declared entry requires 6–69 bytes. The receiver accepts nothing for
reconciliation until terminal digest, full strict entry decoding, exact count,
absence of duplicates and absence of trailing bytes all pass. The digest is
a completeness/correlation check, not a replacement for peer authentication.

Bad version/opcode/sequence/kind/index/length, missing/reordered/duplicate frames,
bad digest, oversize, invalid fields, timeout or EOF abort the request/session.
Partial data stays local and is discarded; prior observations remain active
and stale/error state is reported. There is no partial commit or inferred
disappearance. Existing verified earlier mutations remain retained if a later
snapshot fails. A v2 SNAPSHOT may return exactly `02 02 11 seq` for pre-read
deferral; no stream follows and no observation is implied.

## Console and time budgets

Only full snapshot commands in the opted-in read/v2 session may collect up to
4 MiB before the validated FTD prompt. Login, target reads and writes keep the
64 KiB cap. Parsed full results are capped at 20,000 entries before encoding.
All output is parsed/validated before any snapshot frame is sent. Paging,
unknown output, absent prompt or exceeded cap still fail closed; there is no
automatic pager command or blind delay.

Existing 15-second prompt bounds, configured operation timeout, 45-second
cycle-step bound, 120-second cycle window, command/write counts, lease/cooldown
and no-replay rules remain. Sending all response frames shares one deadline:
at most ten seconds and no later than the original operation/step/session
deadline. The client similarly bounds whole request and stream completion,
not ten seconds reset for every chunk. Slow peers cannot hold the executor
indefinitely. No second SSH session is opened for a stream or refresh hint.

## Upgrade, validation and rollback

No schema migration or data reset is needed. Preserve paired images and a
SQLite-safe backup under the queue manual before operational upgrade. Gracefully
stop the API executor before agent replacement; upgrade API/agent together
with the new flag false first. Web needs no protocol change. Never run a second
writer alongside the scheduler. Then explicitly approve lab opt-in in both
services; do not apply a large real blocklist as a transport test.

Synthetic tests must cover 7,307 and 20,000 entries, boundary-split entries,
long interface names, empty streams, count/byte/chunk/digest rejection, packet
truncation, wrong bindings/order, incomplete streams, absolute time budgets,
flag mismatch and existing v1/removal behavior. Use shared Python/Rust vectors
and real temporary SOCK_SEQPACKET sockets. Failed streams must not reconcile.

Live lab checks must separately establish small read compatibility, representative
large read size/prompt timing/paging, complete independent counts, cycle initial/
priority/final streams and preserved failure behavior. Synthetic capacity is
not live FTD evidence or production readiness. Data-plane/addition gates remain.

On 2026-10-16, after the operator added lab shuns, read-only API inspection
reported 61 active records, successful freshness and no device error. Agent logs
showed a v2 cycle with two full reads, zero removal steps and 8072 ms elapsed.
No new service mutation/refresh hint or direct agent read was submitted for this
check. This is a small-population observation, not independent CLI count matching,
multi-chunk live evidence, paging validation or permission to apply the long list.

To roll back, gracefully stop API, close the agent session, disable the flag
in both services and restore the preceding paired images. Existing queue lease
recovery remains authoritative; never turn RUNNING/UNVERIFIED into replayable
work. Legacy limits return, so a device already beyond them cannot be monitored
by rollback until separately reviewed scoped maintenance reduces its state.
Do not automatically remove entries, reset state or clear shuns for rollback.

## Recorded laboratory evidence — 2026-10-16

After explicit operator approval, paired API/agent images were upgraded and
the flag enabled in the local non-production environment. A live startup cycle
logged `protocol_version:2`, `commands:2`, `removal_steps:0`, `elapsed_ms:8282`
and completed without error. API reported both cycle/large flags enabled, a
successful completed cycle and last_error=null; SQLite quick_check was ok and
six prior VERIFIED outcomes/three policy entries/revision 3 were preserved.
No new mutation or refresh hint was submitted to create this evidence.

This establishes small live BEGIN/END framed-read compatibility in one pinned
SSH session, not a 7,307/20,000-entry device population, paging/prompt timing
under load, live v2 removals or mid-batch priority. Those remain separate gates.
