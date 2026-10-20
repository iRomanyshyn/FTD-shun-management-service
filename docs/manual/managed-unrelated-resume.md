# Resuming Unrelated Managed Policy

## Purpose and boundary

An abandoned restoration incident must never be replayed. It need not permanently
stop other healthy standing policy once its exact device/IP has been excluded.
Use the separate offline `review-resume-unrelated` / `resume-unrelated-policy`
workflow for that situation. Ordinary `review-resume` / `resume-policy` retains
its stricter refusal of all retained failed/uncertain restoration.

This is not incident resolution, rearm or device verification. FAILED/UNVERIFIED
outcomes, closure receipts and pair-wide latches remain. Abandoned pairs cannot
receive new MAINTAIN or restoration, including new generations. The command
never grants policy, queues work, calls FTD, wakes execution or changes gates.
Ordinary uncertain operations and single/fleet cleanup attention still block.
There is no HTTP route or automatic startup behavior.

Ordinary/single/fleet exclusions use the distinct
[Incident Isolation](incident-isolation.md) and `resume-isolated-policy` workflow.
This restoration-only command retains its stricter refusal of those cases.

## Prerequisites

Follow [Offline Managed Maintenance](managed-maintenance.md) and
[Offline Recovery](recovery.md): stop the sole API/Web pair, prevent automatic
restart and settle all prior RPCs (stop the agent if necessary). An expired lease
is not proof of settlement. `--confirm-offline` asserts these operator duties.
Use the database owner's UID and current matching source/package. The command
is packaged in the 2026-10-19 lab API/Web update, but was not invoked there;
packaging is not approval to initialize the closure ledger or resume policy.

The complete optional managed schema and separately initialized closure ledger
must already exist. Use [Incident Abandonment](managed-abandonment.md) to review
and record each restoration decision under both pauses; this command never
migrates or invents a closure. Restore ordinary mutations through the reviewed
recovery procedure while keeping services stopped and desired policy suspended.
Keep the existing execution gates and device profiles unchanged.

For a ready review:

- At least one retained abandonment and one enabled healthy standing target exist.
- Every FAILED/UNVERIFIED restoration attempt has its own matching closure.
  One closure does not cover another attempt on the same pair.
- Every closed pair remains retired with the recorded intent, generation and
  authority. Missing or changed targets refuse, not silently shrink the scope.
- Original attempt, closure request/receipt and retained job/delegation agree.
  Pruned terminal jobs/delegations are permitted as missing evidence, never
  recreated or treated as successful. Extra/contradictory request links refuse.
  New queue retention preserves UNVERIFIED jobs and cleanup-held predecessors;
  support for missing older evidence does not authorize deleting those records.
- No UNVERIFIED job remains outside those exact closed system attempts, even
  an ordinary job for the same IP. No lease, pending job/restoration, waiting or
  ATTENTION single/fleet cleanup, or incomplete fleet admission remains.
- Every enabled target retains valid standing authority, belongs to an enabled
  device, is not protected and has a timestamp before the resume time.

These are exact device/IP pairs: a closure for one device never isolates the same
IP on another device. Protection on a retired pair does not authorize anything.
Unknown/partial schema, over-capacity ledgers and inconsistent data refuse.

## Review and confirm

Paths are illustrative; choose approved absolute database/WAL and private backup
paths first. No invocation against the current lab is authorized by this manual.

```bash
ftd-shun-managed-maintenance review-resume-unrelated \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

Inspect `ready`, every `blocker`, all enabled `targets` and all
`isolated_incidents`. The latter names the unchanged outcome, original case/job,
closure decision and retired pair/generation. Keep this output private. A ready
report is not permission to enable execution gates or restore retired policy.

Within five minutes, confirm the exact review with a new exclusive backup file
inside an operator-owned 0700 directory:

```bash
ftd-shun-managed-maintenance resume-unrelated-policy \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-unrelated-resume.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

The confirmation binds this action, schema, managed authority/receipts, complete
retained attention context, delegation/link state, observations, devices and
protection. A normal resume or attention digest cannot authorize it. Changed,
future or expired reviews refuse without automatic rebasing. No list of
operator-supplied exception IDs can bypass these checks.

## Commit, audit and restart

The existing checked SQLite backup/integrity/concurrent-commit safeguards apply.
One transaction clears desired suspension, increments its revision and advances
only enabled targets' fresh-read barrier. It preserves all retired targets,
original grants, attempts, receipts, outcomes and queue contents. Audit failure
or expiry before commit rolls back the barrier/control changes, even if the
caller catches the exception. Created 0600 backups remain after refusal.

`MANAGED_UNRELATED_POLICY_RESUMED` records a trusted-host `maintenance:<label>`
actor with no directory roles, review/state digest, isolated-incident count and
isolation-summary digest. This audit event does not say Cisco executed anything.
Keep the review output alongside the backup to inspect the exact excluded cases.

After a successful reviewed restart, only a fresh complete snapshot started
after the new barrier may authorize restoration. All default-off controller/
ADD gates, explicit device profiles, shared lease, cooldown, cutoff, protection
and per-pair uncertainty checks still apply. Original grant/closure replay is
observational and cannot reactivate excluded policy. Old resume confirmations
cannot be replayed after a successful state change.

## Rollback and limitations

To stop work again, stop services/settle RPCs and use current checked offline
`suspend`. Never undo the resume by dropping closures or restoring an older DB
with enabled abandoned policy. Retain checked backups and matching images;
older maintenance code remains stricter, and older writers without closure/
pause support must not run against this state without a separate downgrade plan.
No schema migration is added by this feature.

`tests/test_managed_unrelated_resume.py` uses disposable SQLite and typed local
source/queue controls: successful isolation, retained/pruned evidence, fresh-read
and default-off gates, no-rearm/replay, extra attempts/delegations, ordinary and
fleet blockers, contradictory receipts, changed/expired reviews, atomic audit
rollback and checked CLI backups. The full suite remains required. Ordinary/
fleet incident closure, live recovery, bulk/load/reboot and production acceptance
are still outside this increment. New lab activation requires separate scope.
