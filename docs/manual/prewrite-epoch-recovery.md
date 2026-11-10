# Exact Pre-write-DEFER Recovery

This separate **offline** mode covers 17–64 original tracked-v6 system ADD
claims: exactly one final claim received a typed pre-write DEFER and became
CANCELLED after its original execution request expired; all others are
VERIFIED/NOOP. It is not all-verified recovery, unknown reconciliation, automatic
retry or permission to label the cancelled job successful.

## Evidence and limits

Require the exact expired ATTENTION epoch, original claim/attention audits and
all original standing roots. Other owned devices, pending work, failed/unknown
outcomes, manual ADD/REMOVE and unsettled cleanup refuse. The deferred member
needs one original same-owner/epoch/action/source/version claim and literal
`write_sent=false`, matching requeue/cancellation audits and unchanged expired
request/job/attempt. Missing, duplicate, foreign or acknowledged work refuses.
Equal millisecond timestamps use original queue sequence, not UUID ordering.

No old job/RPC is replayed, request renewed, policy changed or outcome relabelled.
Current presence and logs alone do not release the fence. Actual API/Web/agent
shutdown is required; a timeout or container restart is not evidence of quiescence.

## Procedure

1. Preserve current dataset/failure diagnostics. Rehearse matching tested code
   on a consistent private copy; never reuse its receipt/key on the original DB.
2. Stop API/Web, then agent, and verify actual exits and no automatic restart.
3. Inspect with **both** explicit flags:

```bash
ftd-shun-device-recovery inspect --extended-v6 --prewrite-defer \
  --database /private/lab/managed-v2.db --device 1
```

4. Review the whole scope. Within five minutes, still offline, select a new UUID,
   real maintenance label and new exclusive backup path:

```bash
ftd-shun-device-recovery recover --extended-v6 --prewrite-defer \
  --database /private/lab/managed-v2.db --device 1 \
  --key NEW-UUID --actor operator-label \
  --reviewed-at EXACT-REVIEWED-AT --review-digest EXACT-REVIEW-DIGEST \
  --backup /private/lab/private-backups/before-prewrite-recovery.db \
  --confirm-api-web-agent-stopped
```

The backup directory must be operator-owned mode 0700. The tool creates an
exclusive checked 0600 SQLite backup and refuses changed/expired reviews or
concurrent commits. Receipt, proof marker, real-identity audit and exact same-
epoch release commit atomically. Late failure rolls back everything; retain any
created backup. Never change original rows/triggers to make a case fit.

5. Start the same matching agent, then compatible API/Web with all three lab
   overlays. Announce that current standing rules may resume device writes.
   Require a complete read started strictly after the receipt before new work;
   verify successor epoch and actual new results. The original cancelled job and
   expired request remain unchanged; new admissions have fresh identities.

## Storage and compatibility

Only successful explicit offline apply creates `managed_bulk_prewrite_recovery`.
Its complete-scope count/digest and original job/attempt/request/audit proof bind
the distinct `tracked-v6-prewrite` / `compact-v6-prewrite` receipt within the
existing 16-KiB limit. Startup, GET and normal workers never initialize it.
Original recovery receipts and unknown outcomes are unchanged. SQL guards require
the exact marker; old keys cannot release later epochs. Retention preserves the
cancelled job/request, linked audits and original visit claim, refusing corruption.

**Older API images refuse the new exact schema.** Keep them as archives/pre-apply
fallback, not post-apply rollback. Use compatible code; never restore stale
authority over later writes. This mode does not implement deferred-v7 recovery,
new policy, v7 activation, generic unknown replay or production acceptance.

See [extended recovery](extended-session-recovery.md) and current project status.
