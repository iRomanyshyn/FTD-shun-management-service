# Agent Cycle Protocol v1

Current integration: the clean managed lab uses v3 with strict settlement; the
new configured client selects [recoverable opening BEGIN `17`](opening-recovery.md).
This legacy v1/BEGIN `10` specification and its default-safe gates remain unchanged.
Older no-live-selection notes below describe the initial isolated increment.

This document remains the exact legacy v1 contract. The independently gated
[large-snapshot extension](large-snapshots.md) defines cycle v2 with unchanged
mutation semantics and bounded multi-frame full observations. Neither version
supports ADD/import. Keep both feature flags false unless explicitly lab-approved.

The separate opt-in [local settlement extension](cycle-settlement.md) adds strict
BEGIN `16` and a post-cleanup/guard-release/worker-idle receipt across versions
1/2/3. Legacy BEGIN `10` and the v1 packets/default behavior below are unchanged.
No deployed client, feature gate or lab configuration selects the new mode.

The separate [addition contract](addition-contract.md) implements cycle v3
behind another default-off agent gate and explicit per-device creation profile.
It does not change v1/v2 packets or default API scheduling. Its 16-step budget
combines ADD/REMOVE attempts. Private admission/provenance and independently
gated [worker integration](import-execution.md) are now implemented; all ADD
gates remain off in the lab and there is no executable browser import.

## Release gate

This document defines the implementation contract for experimental removal cycles,
not authorization for production writes. `FTD_SHUN_AGENT_CYCLES_ENABLED=false`
is the default in both API and agent. Enable both only for the documented
non-production laboratory procedure. There is no addition/import opcode.
Legacy RPC remains available while the cycle mode is disabled; a failed cycle
never falls back to a legacy write or reconnects within that cycle.

## Wire format

Transport remains peer-UID-checked AF_UNIX/SOCK_SEQPACKET. Integers are unsigned
big-endian. Every packet has an exact opcode-dependent size. Reject truncation,
oversize, unknown versions/opcodes, reordered/duplicate sequence numbers, and
trailing bytes. Maximum response size, including the envelope, is 65536 bytes.

| Request | Exact bytes | Meaning |
| --- | --- | --- |
| BEGIN | `10 01 device:u16` | Open one pinned/authenticated PTY session; return initial complete snapshot. Sequence is implicitly zero. |
| SNAPSHOT | `11 01 seq:u8` | One optional priority full snapshot at a verified command checkpoint. |
| REMOVE | `12 01 seq:u8 ip:4` | Observe target, remove only observed allowlisted interfaces, verify absence. |
| END | `13 01 seq:u8` | Obtain final full snapshot and close the session. |

After BEGIN, sequence starts at 1 and increases by one for each request.
The connection binds the device; no device/route/interface/CLI field occurs
in subsequent requests. Send one request and await its response before the
next. The agent never reads another request while a command or verification
is outstanding. Unsolicited/pipelined API frames are not a supported workflow.

Response envelope is `status:u8 01 opcode:u8 seq:u8`. Status values:

- `00`: success. BEGIN/SNAPSHOT/END append the existing LIST_SHUNS payload
  (`00 count:u16 entries...`); REMOVE appends one byte, `00` for already absent
  or `01` for verified removal. No response contains Cisco output.
- `02`: REMOVE deferred **before any write**, with no payload. It may follow
  a target read that established insufficient remaining command budget.
  Return the claimed job to QUEUED, then END; this is not an uncertain write.
  SNAPSHOT may also return this exact envelope without a payload when there
  is insufficient budget for both it and END. No snapshot is implied; join
  the reserved final snapshot and defer further mutations to the next cycle.
- `01` or any malformed/missing response: abort, close, and fail closed.
  An outstanding removal is UNVERIFIED. Generic legacy rejection `01` is also
  a failure, never successful feature negotiation or permission to retry.

## Independent agent limits

The separate [bounded connection dispatcher](agent-concurrency.md) defaults to
one inline worker. Opt-in workers never overlap the same device/address and hold
its guard across the complete cycle/verification/disconnect. This changes neither
wire status meanings nor the limits below, and does not enable parallel API leases.

Hard limits per connection: 16 REMOVE steps, 64 CLI commands, one optional
SNAPSHOT, and 120 seconds from before SSH connection establishment. Every
connect/step is additionally bounded by the smaller of 45 seconds and
`FTD_SHUN_AGENT_TIMEOUT_SECONDS` (connect plus initial snapshot share one bound);
individual prompt waits retain the existing 15-second bound. API inactivity
and blocked socket sends are bounded to 10 seconds (or the remaining session
deadline, if shorter). Wrong frames, EOF, timeout, parser failure, unknown
interface, or unexpected write output terminate the session without replay.

Reserve a final full-snapshot command before every optional read/mutation.
Before a REMOVE, reserve the configured operation timeout plus 15 seconds for
the final observation. After the fresh target read, reserve every observed
interface write and target verification before sending the first write.
Budget exhaustion never cuts off required verification to start another job.
The absolute deadline remains a last-resort fail-closed abort, not an ETA.

No session is reused after END, transport loss, or deadline. The 120-second
work window is followed by at most two seconds of bounded disconnect cleanup;
no further Cisco command is sent during cleanup. The server remains a
single serialized executor; it does not open another SSH session to handle
a priority request. A failed device does not suppress subsequent fleet devices.

## Scheduler and browser contract

Freeze manual admissions at the existing cycle cutoff. Claim and revalidate
each job only immediately before dispatch, retaining cancellation and short
authorization expiry. Trusted-IP discovery may join within the same budget.
Persist each verified result immediately, independently of final snapshot
success. A later session failure must not erase earlier verified results.

A UI hint during a session is coalesced. A recent complete snapshot satisfies
it; otherwise service one eligible priority read after the current verified
operation, before the next mutation. Optional interactive reads obey the
configured minimum interval measured from the most recent committed full
snapshot; mandatory initial/final reads do not wait for that interval.
Allow at most one extra priority read per
device cycle. Final snapshots satisfy remaining demand; they do not extend
the time/count budget. Publish snapshot/data revisions immediately so browser
state changes before the cycle completes. Show active device/action, completed
items, priority waiting/reading, and budget deferral separately from success.

The durable fleet cooldown remains at least 60 seconds after cycle completion.
The existing lease is renewed before each bounded step. On shutdown, retain
the lease until any in-flight step can no longer execute. On restart, abandoned
RUNNING work is UNVERIFIED and never replayed. No additional database tables
are needed; a deferred-before-write job records an append-only deferral event.

## Migration and laboratory validation

Back up SQLite using the [queue procedure](operation-queue.md), stop the old
API executor, and update agent/API/Web together with the flag still false.
Do not run independent legacy writers beside the scheduler. Enable the flag
only in a non-production lab after unit/transport checks pass.

Queue several dedicated test IP removals on one FTD. Independently verify the
result with `show shun` and observe a single SSH login/session for the device
cycle. Check progress before completion, duplicate actors, cancellation of a
later unstarted item, budget deferral, and a failing device followed by a
healthy device. With a sufficiently long test cycle, request refresh after
interactive cooldown: it must run after current verification, publish its
snapshot before the next removal, and not open a second session. Concurrent
hints must coalesce; recent snapshots must satisfy hints without extra CLI.

Exercise disconnect/timeout during a write and verify UNVERIFIED/no replay.
Test unsupported agent/flag mismatch: visible failure, no legacy fallback.
Record sanitized evidence and software versions before calling this mode
lab-validated. Addition/import validation remains separate.

To roll back cycle mode, stop the API and ensure the old session is closed;
disable the flag in API and agent, then restart together. Queue schema is
unchanged. Do not reset RUNNING jobs to QUEUED: follow lease recovery and the
backup/restore suspension procedure for any restored database.
