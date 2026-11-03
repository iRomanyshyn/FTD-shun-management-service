# Grouped addition verification

Status: default-off agent/client foundation, not selected by the configured API
or queue. The current lab import still uses v3. Do not enable this gate to speed
up the lab until pending-group queue integration and bounded acceptance pass.

## Execution contract

The proposed worker stages at most eight ADDs on one device's existing SSH
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
`batch_additions=True` with tracked/recoverable/settled addition cycles. No
configured API environment selector, Compose activation or HTTP endpoint exists
yet. Old clients continue to select their exact old version; no fallback occurs.

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
are pending, the agent rejects SNAPSHOT, REMOVE and END. The future scheduler
must explicitly verify a partial group before those operations, allowing
interactive requests to interrupt staging between semantic commands rather than
waiting for an entire import. There is no second connection/writer.

## Queue integration still required

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
members. This UI integration is also pending, not part of the current foundation.

Waiting for the five-minute baseline across sessions is not implemented: it
outlives the current executor lease and loses the live pending evidence. A
generic later observation must never turn an unknown ADD into success.

## Deployment and rollback

No database/schema/data/credentials/trust/network changes in this increment.
Do not change the running lab merely to install this dormant foundation. A later
rollout must test the queue integration, drain API before agent replacement,
retain compatible images and use all three managed-lab overlays. Never downgrade
in-flight pending groups or requeue unknown writes; terminal settlement or the
existing uncertainty hold is required before replacement. The first bounded lab
test must measure real writes and grouped observations, then independently verify
cleanup; synthetic protocol/console tests are not throughput acceptance.
