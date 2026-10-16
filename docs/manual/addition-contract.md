# Addition Contract — Experimental Agent Cycle v3

## Status and boundaries

The narrow ADD contract is implemented in the Rust agent and explicit Python
transport, disabled by default. This is not production write support or
permission to enable imports. API routes/scheduler still select v1/v2 and cannot
enqueue/dispatch ADD; no schema, admission or provenance migration is part of
this increment. Mock mode does not implement addition.

`agent/src/addition_contract.rs` is an executable evidence model compiled only
under `cfg(test)`. It now exercises the strict production helpers in
`agent/src/addition.rs`, alongside fake-console cycle tests. The assessment
model is excluded from release builds; gated typed sender/parsers are included.
Local tests do not establish live ADD readiness.

Before enablement, complete the remaining
[addition lab gates](addition-lab-validation.md), including
the Basic-account, duplicate, creation-scope, real traffic and bounded-read
checks. Large-population imports require their separate complete-read evidence.
The lab deployment authorization does not waive those gates.

The agent accepts v3 BEGIN only with all three explicit true flags:
`FTD_SHUN_AGENT_CYCLES_ENABLED`, `FTD_SHUN_LARGE_SNAPSHOTS_ENABLED`, and the new
`FTD_SHUN_AGENT_ADDITIONS_ENABLED` (default false). The bound enabled device must
have `addition_profile: "fpr1010-766-single-vf-management-v1"` and an allowlist
containing `management`. Missing/null profile disables v3 for that device;
unknown profiles/invalid types or a profile outside the allowlist fail startup.
Gate/profile failures precede secret access/SSH. Additions enabled without the
other two flags fail startup. Existing inventory needs no change; tracked
examples use null and the new flag remains false.

Python `UnixAgentClient(..., large_snapshots=True, additions_enabled=True)`
explicitly selects v3. It is a low-level transport, not an application write
route: normal API construction does not pass this option, even if the new
agent flag is set in the environment. Do not run an independent writer beside
the leased worker. Future scoped validation must coordinate exclusive execution
and authorization; this manual does not authorize an ad-hoc RPC/device write.

## Creation profile, not an API-selected interface

Current evidence is operator-observed FPR1010 / FTD 7.6.6 Basic-user
creation of an initially absent `198.51.100.251`, followed by scoped cleanup.
It returned context `single_vf` and the source-only row on `management`.
The separately approved repeated-add transcript returned the identical success
text twice, with one identical target row after each and absence after cleanup.
That visible behavior does not reveal hidden counter/age changes. Both are
operator-provided observations under the previously reported profile, not
independently re-read model/version/role or service-executed additions.
That does not prove data-plane blocking or support on another device/version.

Agent-owned inventory must explicitly opt a device into a reviewed
creation profile; missing/unknown/disabled profile means no addition. The
existing removal-interface allowlist is not a creation profile. Never select
the first allowlisted interface or silently assume `management` for the fleet.
The implemented profile binds the recorded context and expected interface,
which must also be allowed for observation/removal. Configuration is not proof
of compatibility: the laboratory evidence must establish the actual profile.

The API supplies only a typed IPv4 target on the device-bound cycle. Neither
interface/context, CLI, a route, a destination/port selector nor raw source text
may occur in an ADD request. The SSH sender constructs only the
fixed source-only command form; it must not offer a generic execution method.

## Per-target evidence and outcomes

1. The agent independently validates profile, cycle limits and reserve before
   the target read. Future admission/worker integration must revalidate live
   authorization/policy before dispatch; that path is not implemented yet.
   Read and strictly parse `show shun <target>` in the existing
   session. Unknown text/interface, a different target or duplicate row is an
   error, never an empty preflight.
2. Any valid already-present target on an allowlisted interface is **Already
   present**: do not write, replace fields, relabel origin or claim import
   ownership. A duplicate import is not a request to repair or broaden a shun.
   Recorded repeat-add success text is identical to initial creation, so do
   not infer creation/no-op from acknowledgement or replace the preflight.
3. Only an observed absent target is eligible for one write. Bind the response
   to the same target and reviewed profile; the recorded acknowledgement is
   exactly these ordered nonempty lines after shell echo/prompt removal:

   ```text
   Shun 198.51.100.251 added in context: single_vf
   Shun 198.51.100.251 successful
   ```

   LF/CRLF, surrounding ASCII whitespace and empty lines are allowed. Different
   target/context/wording, partial/duplicate/reversed success, warnings/errors,
   control sequences, non-ASCII or extra lines fail closed. Acknowledgement is
   not verification. Target/write evidence retains the 64 KiB limit.
4. Require a subsequent fresh target read with exactly one expected interface
   and the exact source-only fields `0.0.0.0 0 0 0`. The general observation DTO
   omits these fields; comparing target/interface alone is insufficient. Absent,
   extra, more-specific or unexpected state is not verified creation.
5. Only valid acknowledgement plus valid post-read yields **Verified creation**
   for this operation/current occurrence. It does not prove exclusive ownership
   against another administrator racing outside the service or actual traffic
   blocking. Later external reappearance must not inherit import provenance.

Timeout/loss/unknown output after possible dispatch is **UNVERIFIED**: retain
the attempt/audit and last observations; never resend or automatically undo it.
A later complete snapshot can update observed presence, but must not promote
an uncertain import to verified creation or requeue it. Unknown acknowledgement
is a terminal error, not permission for a second write or a guessed parser.

## Exact versioned wire extension

Use cycle version `03`, retaining the peer-checked UDS, one pinned SSH session
and device-bound ordering. Require the separately validated large-read mode.
BEGIN/SNAPSHOT/REMOVE/END retain their request layouts with version `03`;
snapshot streams retain manifest/chunks/end but bind every envelope to version
`03`. Shared Python/Rust vectors cover requests, addition results and framed
snapshots. Default v2 decoders reject v3 unless selected explicitly. No auto-
negotiation or downgrade; old/disabled agent rejection aborts before ADD.

| ADD frame | Exact bytes |
| --- | --- |
| Request, 7 bytes | `14 03 seq:u8 IPv4:4` |
| Already present, 5 bytes | `00 03 14 seq 00` |
| Verified creation, 6 + name length | `00 03 14 seq 01 length:u8 interface:ASCII` |
| Deferred before any write, 4 bytes | `02 03 14 seq` |

The returned interface is agent-observed/profile-validated, not API-selected;
length is 1–64 and the existing strict name grammar applies. Reject unknown
outcomes, wrong binding, extra/truncated bytes or invalid names. Rejection/loss
is never a no-op or a signal to retry. No standalone legacy ADD opcode is
implemented: additions share the serialized cycle with reads/removals.

## Shared budgets and queue/provenance follow-up

The 16-step limit is a **combined ADD/REMOVE attempt limit**,
including no-ops and deferred attempts, not 16 of each. Keep 64 CLI commands,
120 seconds, one optional priority snapshot, the 45-second/configured step
bound, 15-second prompt waits, absolute IPC deadlines and persisted cooldown.
Reserve target read + possible write + target verification + final full read
(four commands), and a full step plus final-read time, before starting ADD.
Only explicit pre-write deferral can return a claimed job to QUEUED; verification
and END cannot be sacrificed to start another target. A priority refresh waits
for the current operation/verification and uses the same session and reserve.

The cycle tracks entry count from each complete full read and its own verified
changes. After an absent preflight, ADD fails before writing when that count
already reaches 20,000; an existing target can still return no-op. This cannot
exclude external administrators racing new entries. An oversized/failed final
snapshot still fails closed without replaying/undoing an earlier verified add.
At most one ADD command is issued for a step. Any step failure aborts the session;
only exact pre-write deferral returns a reusable non-success result.

Future admission must be atomic, idempotent and role/CSRF protected; bind explicit
canonical targets, selected devices, actor, label/reason and policy revision to
confirmation. A local preview is never write authority. Recheck enabled Protected
IPs at admission and claim, current snapshot capacity, cancellation and short
authorization expiry. Respect existing pending-work limits without silently
accepting a truncated batch. Opposite add/remove intentions require explicit
serialization/conflict semantics; do not coalesce them as the same operation.

Schema/provenance and that conflict policy require a separate reviewed increment
before admission: operation kind, immutable batch/request linkage, per-occurrence
verified-add attribution, Already-present/no-op distinction and bounded progress.
Never recreate completed imports after removal, disappearance or restart.
SQLite events and sanitized structured logs must distinguish accepted, no-op,
verified, refused and uncertain outcomes without logging pasted source.

## Validation and operational impact

Tests cover exact acknowledgement, target/context binding, unexpected
fields/interfaces, duplicate/pre-existing records, missing verification, bounds,
control characters and malformed evidence. Production protocol regressions
assert no standalone ADD, refusal in v1/v2, explicit selector and gate rejection.
A captured direct-CLI
duplicate fixture checks identical acknowledgements, unchanged visible target
rows, no creation attribution for an already-present target, and scoped cleanup.
These local regressions do not independently reproduce real duplicate behavior
or validate timers/SSH dispatch, queue provenance, hidden state or traffic.

Real local SeqPacket tests cover one v3 connection, mixed add/no-op/remove/read,
wrong/malformed response, timeout, no fallback/replay, large complete framed
reads and version binding. Fake consoles test combined attempt/command/time
reserves, no writes for pre-existing targets, profile/capacity rejection and
verification uncertainty. They are not live SSH/timing/traffic evidence.

Agent cycle JSON logs include addition/combined attempt counts. Per-ADD events
are `agent.add_shun.verified`, `.noop`, `.deferred`, or `.failed` with device,
sequence, target and a sanitized reason, never raw Cisco output. Agent-verified
logging precedes response transfer: a lost response can still be UNVERIFIED at
the client, and must not cause replay or inferred database provenance.

## Deployment and rollback

Preserve paired API/agent images and a SQLite-safe backup. No schema/data reset
is needed. Stop the API executor before agent replacement, upgrade the pair
with ADD disabled and actual inventory unchanged, then restart without another
writer. Web needs no rebuild. v1/v2 traffic remains compatible; normal API
selection cannot activate v3. Keep all existing lab/production release gates.

Rollback stops API before agent replacement and restores the paired images;
keep the new flag false/absent and profiles absent for older agents. An old
strict inventory decoder rejects an unknown field even if null, so remove it
from an older agent's configuration if one was added. Actual existing inventory
is not changed by this increment. Never turn uncertain jobs into replayable work
or restore a database without the queue manual's suspension/review procedure.
A later scoped validation/import needs explicit device-change authorization;
upgrading this code alone performs no new test write or cleanup.
