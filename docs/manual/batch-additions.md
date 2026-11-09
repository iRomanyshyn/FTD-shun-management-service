# Grouped addition verification

Status: default-off agent/client and fenced queue/worker integration. Configured
`continuous-managed` may explicitly select it; other runtime modes cannot.
Consult project status/log for live rollout and acceptance. Code support alone
does not establish a measured speedup or large-list acceptance.

The desk lab selected this mode on 2026-11-03 after matched preflight and exit-0
API/agent drain. The original import continued; first three settled epochs
verified 25 addresses in 207.066s. This is only 7.24/minute, not large-list
acceptance. Examples remain false. See current status for image IDs, rollback
tags, integrity checks and remaining local claim overhead.

## Current execution contract (v5)

An explicitly selected [multi-group v6 profile](multi-group-sessions.md) adds
bounded fresh refill and larger session budgets. Version 5 remains the default;
the exact v5 contract below is unchanged. Consult current status for deployment.

The lab selected this contract after a separate reviewed
[quiescent reconciliation](quiescent-managed-reconciliation.md) of the old held
epoch 2060 at 18:20:30.926Z on 2026-11-03. That unknown outcome remains retained,
not replayed or relabelled. Matching API/Web/agent are now running; consult
current status for actual bounded execution/throughput acceptance. No reset or
reimport was used. Other held epochs still need their own valid contract.

The matching configured grouped API/agent now selects tracked cycle v5. Up to
**16** acknowledged addresses share a complete verification read. The final group
uses `VERIFY_END` (`1c 05 seq`): the exact ordered group receipt, complete typed
snapshot and real post-handler terminal settlement replace a separate VERIFY
and END read. The receipt has the same layout as v4, with version `05` and opcode
`1c`; every snapshot frame binds that version/opcode/sequence too. Success requires
all three components. Missing settlement retains pending evidence and the fence;
there is no fallback, inferred success or replay.

The one final observation both confirms additions and updates the visible list.
Commit proven per-target results before publishing that observation. Interactive
refresh/removal still verifies a partial group between semantic commands. Stop,
pause, cancellation and pre-write deferral also finish the actual pending scope.
No queued address beyond the original frozen cutoff gains permission.

The 16-mutation, 64-command and 120-second whole-session limits are unchanged.
V5 caps an individual stage to 30 seconds (two bounded prompt interactions),
reserving that step plus the final 15-second prompt interaction before writing.
V5 allows a 30-second receive-only local-processing wait, capped by the remaining
session deadline; v4 stays at ten. Send/transfer and other operation/cleanup
limits remain unchanged. This recovers
some unused session time; 16 is a maximum, not a promised actual group size.
Per-target preflight and current root/lease/protection checks remain. One session
is already shared across its addresses; there is not a new SSH login per address.

A previously verified managed block that disappears on a later complete refresh
is restored by existing desired-state reconciliation. First confirmation deferred
across sessions, or automatic retry of an ACKed but missing first verification,
is still pending a durable known-absence/settlement contract. Missing/invalid
first verification currently retains uncertainty. Never reinterpret a lost write
reply or generic later presence as original creation proof.

## Historical v4 transport contract (still supported by the low-level agent/client)

The grouped worker stages at most eight ADDs on one device's existing SSH
session. Each stage reads that exact target immediately before writing, branches
to NOOP if already present, and otherwise checks the strict Cisco acknowledgement.
It does not run a target-specific post-read. One explicit VERIFY_ADDS reads the
complete shun table, validates every pending target's exact source-only scope,
and returns the ordered verified scope plus the complete typed snapshot.

The acknowledgement is not success. No creation provenance or successful job
may be recorded before receiving and validating the entire group evidence.
Other unrelated valid shuns may appear in the table; malformed unrelated rows,
unknown interfaces, duplicate/missing targets or non-source-only pending rows
refuse the group. Missing/partial/digest-mismatched IPC also refuses success.
Previously verified groups are not invalidated by a later failure.

## Fixed binary extension

Cycle v4 requires tracked BEGIN `18 04 device:u16 nonce:16`. The separate agent
environment gate `FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED` defaults to `false`
and requires existing additions/cycles/large-read gates and the validated device
profile. The low-level Python client additionally requires explicit
`batch_additions=True` with tracked/recoverable/settled addition cycles. The same
environment flag selects the configured API's matching managed worker. It must
be false for legacy/observation modes. Existing Compose `env_file` propagation
supplies both API and agent; no new public port/HTTP endpoint is introduced.
Defaults are false. Old clients retain their exact old version; no fallback.

| Operation | Exact request | Response |
| --- | --- | --- |
| STAGE_ADD | `1a 04 seq ip:4` | `05 04 1a seq` pending; `00 04 1a seq 00` existing/NOOP; `02 04 1a seq` before-write deferral |
| VERIFY_ADDS | `1b 04 seq` | `00 04 1b seq count:u8 (ip:4 name_len:u8 interface:ASCII)*`, then the normal complete v4 snapshot stream bound to `1b/seq` |

The receipt contains exactly the pending IPs in original order, at most eight,
without omissions, extras or duplicates. Interfaces use the existing bounded
grammar. A receipt without the whole matching snapshot is never returned as
verified to the caller. Pending status is a distinct `PendingAddition`, not an
`AdditionResult(created=True)`; successful VERIFY yields `VerifiedAdditionBatch`.

No more than 16 combined stage/REMOVE attempts or 64 commands per session; the
original 120-second session, 45-second maximum step, 15-second prompt and
10-second IPC/transfer limits remain. Stage reserves preflight/ADD/group-read/END
capacity before writing. Sequence numbers extend to 34 only in v4: up to 16
mutations, 16 nonempty group reads, one priority read and END. The full snapshot
still has the existing 200,000-entry / 16 MiB typed / 32 MiB CLI limits.

Ordinary ADD opcode `14` is v3-only. Stage/verify are v4-only. While any additions
are pending, the agent rejects SNAPSHOT, REMOVE and END. The grouped scheduler
explicitly verifies a partial group before those operations, allowing
interactive requests to interrupt staging between semantic commands rather than
waiting for an entire import. There is no second connection/writer.

## Queue integration

Keep staged jobs RUNNING with owner/epoch/group-bound append-only acknowledgement
evidence. Permit multiple RUNNING claims only for that exact validated pending
group; ordinary same-device serialization remains. Recheck current protection,
original root/consent, lease, cutoff and expiry before every stage. Flush on
interactive demand, capacity, stop/defer and END. Finish each verified job before
publishing the group snapshot so observation publication cannot preempt creation
provenance. Retain unknown jobs/fences after transport or local settlement failure.

The status panel should distinguish staging from group verification and show the
pending-verification count. Whole-import processed/success counts advance only
after verified per-target settlement, not after ACKs. Keep task-level progress
and cancellation review; do not recreate one-address progress cards for group
members. The status panel now labels these phases and pending counts separately.

Diagnostic `device.session.timing` separates local `acknowledge_addition`,
`finish_verified_group` and `fail_pending_group` durations from `other`. These
are aggregate method wall times, including failed calls, not device execution,
successful task progress or isolated SQLite/CLI timings. Group claims retain
both executor boundaries and full base audit profile validation without
repeating adjacent equivalent scans. No profile or authority cache is used.

Waiting for the five-minute baseline across sessions is not implemented: it
outlives the current executor lease and loses the live pending evidence. A
generic later observation must never turn an unknown ADD into success.

## Deployment and rollback

V5 requires a matching API/agent pair; older agents reject it before any device
write. Do not fall back to v4 after an uncertain operation. Drain API, check
IDLE/no RUNNING or unknown work, then drain agent before replacing both. Compatible
pre-v5 images may be restored together at that same clean boundary with the
existing grouped flag unchanged. No schema or retained authority changes occur.

No database/schema/data/credentials/trust/network changes are needed. Validate
the queue integration, drain API before agent replacement, retain compatible
images and use all three managed-lab overlays. Enable the shared flag only in
the matching managed API/agent configuration after preflight checks. Never downgrade
in-flight pending groups or requeue unknown writes; terminal settlement or the
existing uncertainty hold is required before replacement. For the retained
pre-batch v3 images, drain first, check IDLE/no RUNNING/unknown work and set the
shared batch flag false before starting the matching old API/agent/Web. Never
release unknown work to obtain a convenient rollback boundary.

Fresh-fixture tests must measure writes/grouped observations and verify cleanup.
Alternatively, observe the original already-consented running import without
granting/reimporting anything; retain its intended blocks rather than deleting
them as test cleanup. Synthetic console/protocol checks alone do not establish
throughput or live failure/priority acceptance.
