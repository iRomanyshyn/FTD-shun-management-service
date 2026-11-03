# Recover a Fully Verified Held Session

## When to use it

Use `ftd-shun-device-recovery` only when a device is held in ATTENTION after local
processing/session completion failed, but every mutation claimed in that exact
epoch has its original VERIFIED/NOOP job, terminal audit and system-ADD attempt.
It recovers execution ownership, not an unknown command or a missing outcome.
The original import and standing rules remain intact; there is no reimport.

The tool refuses pending/unknown jobs, failed/unknown system attempts, unsettled
cleanup, missing evidence, other owned devices and changed/expired reviews. Its
current narrow scope requires 1–16 verified claims and all other device fences
IDLE. An old read-only hold or pruned/missing original job is not covered.

This is a trusted-host offline procedure, not a Web button or automatic startup
action. Stop API/Web, then gracefully stop the privileged agent and verify its
actual exit. Prevent their orchestrator from restarting them. The offline flag
attests that no old API task/agent RPC can still execute; the SQLite tool cannot
verify process state or remote TCP termination itself. Process exit is **not**
proof of a write outcome: the retained job/attempt/audit evidence is also required.

## Procedure

Use the currently installed package and existing working database. Choose an
operator-owned mode-0700 private backup directory and a fresh UUID/key/label.
Example paths below must be replaced with the actual reviewed private paths:

```bash
ftd-shun-device-recovery inspect \
  --database /private/lab/managed-v2.db --device 1
```

Inspection is read-only. It validates exact storage and original import roots,
lists the original fence and verified claim bindings and returns `reviewed_at`
and a whole-database `review_digest`. It does not initialize the optional ledger,
clear a hold, contact FTD or infer provenance from an observed IP.

Within five minutes, with API/Web/agent still stopped:

```bash
ftd-shun-device-recovery recover \
  --database /private/lab/managed-v2.db --device 1 \
  --key NEW-UUID --actor operator-label \
  --reviewed-at EXACT-REVIEWED-AT --review-digest EXACT-REVIEW-DIGEST \
  --backup /private/lab/recovery-backups/before-verified-recovery.db \
  --confirm-api-web-agent-stopped
```

The tool creates and checks an exclusive mode-0600 SQLite backup, refuses a
concurrent commit and applies one rollback-safe transaction. On first use it
explicitly installs the compatible optional recovery ledger/guards; this is
never a startup migration. It records the original ATTENTION fence, verified
claim bindings/digests, real `maintenance:<label>` actor and offline assertion,
then permits only that receipt-bound ATTENTION-to-IDLE transition. The epoch
is retained; the next lease increments it. Audit failure rolls back the schema,
receipt and fence change together. Inspect any retained backup before retrying;
never overwrite it or clear rows/triggers manually.

No job, request, attempt, import member, desired policy or protection changes.
No original job is retried or relabelled. Original-key repetition is read-only
and cannot release a later epoch or grant work. Recovery keys cannot become ADD,
REMOVE or standing-policy authority. Receipts are immutable and bounded to 4096;
capacity refuses rather than evicting evidence.

Start the matching agent **before** API/Web. Use all three current managed-lab
Compose overlays. Verify a new lease epoch, a complete initial read newer than
the recovery, unchanged protection/standing authority, actual later verified
progress and no new ATTENTION. Pre-send bulk eligibility refuses evidence at or
before the recovery timestamp. Existing policy may now add still-required missing
addresses; announce that device-write scope before restarting the lab runtime.

## Compatibility and limits

The optional table is `managed_bulk_device_recovery`; two lease transition
guards gain the exact receipt-bound exception. Existing old profiles remain
supported without conversion; startup/GET never create this table. Older code
does not recognize the new exact profile and must refuse it. Retain the checked
old backup and matching images, but do not roll back by removing recovery guards,
restoring stale authority over later work or bypassing schema validation.

The retained receipt is an administrative quiescence/evidence decision, not new
FTD verification or automatic resolution of uncertainty. Unknown ADD/REMOVE,
missing terminal evidence, failed cleanup and broader recovery remain separate.
This procedure does not establish production, multi-device or 100,000-IP load
acceptance. See [fenced leases](device-leases.md) and
[continuous dispatch](continuous-dispatch.md).
