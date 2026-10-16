# Addition Contract — Offline Review Draft

## Status and boundaries

This is a proposed narrow ADD contract, not a supported agent protocol or an
operator command to enable imports. The deployed agent/API still reject ADD
and cycle version 3. No new setting, inventory field, queue admission, schema,
CLI operation or worker dispatch is implemented by this document.

`agent/src/addition_contract.rs` is an executable evidence model compiled only
under `cfg(test)`. It validates the recorded one-address fixture and adversarial
variants without SSH, a socket, a command sender or a database. It is excluded
from release builds. Its successful assessment is not production write support.

Before implementation in the live agent, review this draft against the
[addition lab gates](addition-lab-validation.md). Before enablement, complete
the Basic-account, duplicate, creation-scope, real traffic and bounded-read
checks. Large-population imports require their separate complete-read evidence.
The lab deployment authorization does not waive those gates.

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

Future agent-owned inventory must explicitly opt a device into a reviewed
creation profile; missing/unknown/disabled profile means no addition. The
existing removal-interface allowlist is not a creation profile. Never select
the first allowlisted interface or silently assume `management` for the fleet.
The initial profile would bind the recorded context and expected interface,
which must also be allowed for observation/removal. Configuration is not proof
of compatibility: the laboratory evidence must establish the actual profile.

The API supplies only a typed IPv4 target on the device-bound cycle. Neither
interface/context, CLI, a route, a destination/port selector nor raw source text
may occur in an ADD request. The future SSH sender would construct only the
fixed source-only command form; it must not offer a generic execution method.

## Per-target evidence and outcomes

1. Validate profile, live authorization/policy, cycle limits and reserve before
   the target read. Read and strictly parse `show shun <target>` in the existing
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

## Proposed wire extension (not accepted by current code)

Use cycle version `03`, retaining the peer-checked UDS, one pinned SSH session
and device-bound ordering. Require the separately validated large-read mode.
BEGIN/SNAPSHOT/REMOVE/END retain their request layouts with version `03`;
snapshot streams retain manifest/chunks/end but bind every envelope to version
`03`. This requires paired implementation and new shared vectors; current
v2 decoders deliberately reject it. No auto-negotiation or downgrade.

| Proposed ADD frame | Exact bytes |
| --- | --- |
| Request, 7 bytes | `14 03 seq:u8 IPv4:4` |
| Already present, 5 bytes | `00 03 14 seq 00` |
| Verified creation, 6 + name length | `00 03 14 seq 01 length:u8 interface:ASCII` |
| Deferred before any write, 4 bytes | `02 03 14 seq` |

The returned interface is agent-observed/profile-validated, not API-selected;
length is 1–64 and the existing strict name grammar applies. Reject unknown
outcomes, wrong binding, extra/truncated bytes or invalid names. Rejection/loss
is never a no-op or a signal to retry. No standalone legacy ADD opcode is
proposed: additions must share the serialized cycle with reads/removals.

## Shared budgets and queue/provenance follow-up

The existing 16-step limit must become a **combined ADD/REMOVE attempt limit**,
including no-ops and deferred attempts, not 16 of each. Keep 64 CLI commands,
120 seconds, one optional priority snapshot, the 45-second/configured step
bound, 15-second prompt waits, absolute IPC deadlines and persisted cooldown.
Reserve target read + possible write + target verification + final full read
(four commands), and a full step plus final-read time, before starting ADD.
Only explicit pre-write deferral can return a claimed job to QUEUED; verification
and END cannot be sacrificed to start another target. A priority refresh waits
for the current operation/verification and uses the same session and reserve.

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

Offline tests cover exact acknowledgement, target/context binding, unexpected
fields/interfaces, duplicate/pre-existing records, missing verification, bounds,
control characters and malformed evidence. Production protocol regressions
assert no ADD enum and rejection of draft frames/version. A captured direct-CLI
duplicate fixture checks identical acknowledgements, unchanged visible target
rows, no creation attribution for an already-present target, and scoped cleanup.
These local regressions do not independently reproduce real duplicate behavior
or validate timers/SSH dispatch, queue provenance, hidden state or traffic.

No rollout, backup, migration or runtime rollback is needed for this test-only
increment. Existing lab services remain untouched. A later live implementation
needs a separate disabled-by-default gate, paired rollout, backup/rollback and
an explicitly scoped one-target validation before wider admission. Reverting
this draft/tests cannot clean up an operator-created device fixture.
