# Reconcile a Quiescent Managed-ADD Session

This is an explicit trusted-host desired-state decision, not retrospective
verification of an unknown ADD. Use it only for an expired ATTENTION epoch with
1–16 original system managed ADD claims, at least one UNVERIFIED and the others
VERIFIED/NOOP. Manual commands, uncertain REMOVE, FAILED attempts, other owned
devices, foreign uncertainty and unsettled cleanup refuse. Do not use the
separate verified-epoch tool to force this case through.

For 17–64 original tracked-v6 system ADD claims use the separately selected
[extended offline profile](extended-session-recovery.md). Do not raise the default
limit, truncate a review or reuse another epoch's receipt.

## What changes

The original unknown job, system attempt, delegation, terminal audit and policy
remain unchanged. An immutable receipt records the exact original device epoch
and original unknown job/attempt hashes. This permits a single same-epoch IDLE
transition and exempts only those reviewed records from the operational unknown
barrier. New or changed unknown work still blocks. Receipt replay is read-only;
it cannot release a later epoch or grant policy. Old keys/requests never restart.

The next worker must obtain a complete snapshot started strictly after the
receipt. Presence is an observation, not proof of original service creation.
Absence can produce a **new** managed attempt only under current standing intent,
protection, retirement, cancellation, freshness and backoff. No original outcome
becomes VERIFIED/NOOP, and an expired delegation is never extended. Protection
or stopped policy cannot be re-enabled by reconciliation.

Managed policy shows **Unknown outcome reviewed** separately from an unresolved
hold. The original attempt remains in history as unknown. Import progress uses
current pending/presence or later independently verified results rather than
counting a reviewed historical unknown as successful creation.

Queue warnings and its attention badge count only unresolved failures/unknowns.
An exactly validated reconciliation receipt moves its original unknown into the
collapsed **Reviewed history** section, with review time, original outcome/reason
and the IP detail link. No action is required for that historical record; a later
verified addition remains a separate operation. Raw outcome totals and original
evidence stay unchanged. New unknowns, unrelated failures and missing/invalid
review evidence never inherit this presentation exemption. Real **Needs attention**
appears above import progress/active rows so it is not buried in a long queue.

## Offline procedure

1. Stop API and Web; prevent automatic restarts. Gracefully stop the actual agent
   and verify all three exits. An elapsed timeout or lease is not quiescence.
2. Retain the existing DB/WAL, images and failure evidence. Use the matching new
   package, explicit existing DB path, fresh UUID and a real maintenance label.
3. Inspect the whole original scope without writing:

```bash
ftd-shun-device-reconciliation inspect \
  --database /private/lab/managed-v2.db --device 1
```

4. Within five minutes, with every old executor still stopped, apply the exact
   returned review. Select a new private backup path; examples are placeholders:

```bash
ftd-shun-device-reconciliation reconcile \
  --database /private/lab/managed-v2.db --device 1 \
  --key NEW-UUID --actor operator-label \
  --reviewed-at EXACT-REVIEWED-AT --review-digest EXACT-REVIEW-DIGEST \
  --backup /private/lab/private-backups/before-reconciliation.db \
  --confirm-api-web-agent-stopped
```

The offline assertion is trusted-host administrative authority: the tool cannot
prove OS/container shutdown itself. It creates a checked exclusive 0600 SQLite
backup in an operator-owned 0700 directory and refuses concurrent commits. Schema,
receipt, epoch transition and real-actor audit are one rollback-safe transaction.
An expired/changed review refuses rather than rebasing. Keep any backup after a
failure; never overwrite, remove triggers or change original outcomes manually.

5. Start the matching agent, then API/Web with all three managed-lab overlays.
   Announce that current standing rules may create new device work after fresh
   observation. Check a successor epoch, a post-receipt complete read, original
   outcome preservation, unchanged policy/protection and actual new results.

## Compatibility and limits

The optional `managed_bulk_reconciled_jobs` table binds unknown jobs/attempts to
the existing `managed_bulk_device_recovery` receipt. Its guards and the exact
recovery-bound insert guard form a new recognized profile. Startup, GET, queue
and ordinary initialization never create it. Retained capacity is 1024 unknown
jobs and the existing 4096 recovery receipts; no evidence eviction is allowed.

Older DB writers refuse this profile. Retain the pre-change archive but do not
restore old authority over later writes just to roll back code. Use matching
profile-aware API code; agent/Web have no SQLite write authority. This is not an
automatic crash-recovery service, generalized unknown-command replay, production
certification or proof that any original unknown command did/did not execute.
