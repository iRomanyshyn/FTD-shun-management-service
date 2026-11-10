# Recover a Held Multi-group Session

This explicit **offline** profile covers **17–64 system ADD claims** from one
tracked-v6 session. It is not automatic retry, a Web action or proof that an
unknown ADD succeeded. Ordinary recovery commands still refuse more than 16
claims unless `--extended-v6` is supplied on both inspection and apply.

## Choose the right decision

- All original claims have VERIFIED/NOOP outcomes: use `ftd-shun-device-recovery`.
- At least one original managed ADD is UNVERIFIED and the others VERIFIED/NOOP:
  use `ftd-shun-device-reconciliation`. Every unknown stays UNVERIFIED forever;
  the reviewed hold is released, not the original job retried or relabelled.

Both require exact original claim/result/job/attempt/request bindings, matching
v6/group metadata on each claim and terminal result, valid original standing
roots and the whole held scope. Missing/pruned evidence, manual ADD, REMOVE,
FAILED work, deferred/nonterminal claims, other owned devices, foreign uncertainty
and unsettled cleanup still refuse. This is deliberately not every possible
crash/recovery case. Do not split a held epoch into smaller reviews or change
old rows to make one of these decisions fit.

### Separate pre-write-DEFER profile — 2026-11-10

Read-only inspection found the desk lab held at epoch 2921 after 32 VERIFIED
claims plus one exact same-owner/epoch v6 pre-write DEFER, later CANCELLED when
its execution delegation expired. Final full-read/settlement failed. There are
no new unknown jobs, but this is **not** an all-VERIFIED/NOOP scope accepted by
these tools. Do not omit that claim, label it NOOP, reuse an earlier recovery key
or clear the fence based on logs/current presence. The original task, outcomes
and retained claim/defer audit remain intact. The separate
[pre-write-DEFER contract](prewrite-epoch-recovery.md) now supports this narrower
case behind both `--extended-v6 --prewrite-defer`. The modes above still refuse
it; the new selection never substitutes for actual quiescence/review/backup.

## Procedure

1. Preserve current status, failure diagnostics and the original dataset.
2. Stop API/Web, then gracefully stop agent and verify actual exits; prevent
   automatic restarts. A timeout or expired lease is not executor quiescence.
3. Use matching profile-aware code. Inspect the existing DB read-only:

```bash
ftd-shun-device-reconciliation inspect --extended-v6 \
  --database /private/lab/managed-v2.db --device 1
```

4. Review all claims and unknown outcomes. Within five minutes, with executors
   still stopped, use a fresh UUID and real trusted-host maintenance label:

```bash
ftd-shun-device-reconciliation reconcile --extended-v6 \
  --database /private/lab/managed-v2.db --device 1 \
  --key NEW-UUID --actor operator-label \
  --reviewed-at EXACT-REVIEWED-AT --review-digest EXACT-REVIEW-DIGEST \
  --backup /private/lab/private-backups/before-extended-recovery.db \
  --confirm-api-web-agent-stopped
```

For a fully verified epoch substitute `ftd-shun-device-recovery inspect` and
`recover`, retaining `--extended-v6` and the other controls. Do not use it for
unknown outcomes. Examples are placeholders, not reusable authority.

The backup directory must already be private (0700) and owned by the operator.
The tool creates an exclusive checked 0600 SQLite backup and refuses overwrite
or concurrent commits. An expired/changed review refuses instead of rebasing.
The review digest is bound to the extended profile as well as the whole DB.
Rehearse on a separate checked copy first; its keys/reviews/receipts are never
copied back as permission for the live dataset.

5. Start matching agent, then API/Web using **all three** managed-lab overlays.
   Existing authorized policy may create new work after a complete read started
   strictly after the receipt. Verify that read, current authority/protection,
   original unknown preservation, new epoch and actual subsequent results.

Reconciliation never assigns original creation provenance from current presence.
Fresh absence can produce a new attempt only under current standing intent and
normal protection/cancellation/backoff; no expired request is renewed.

## Storage and compatibility

Only explicit successful offline apply creates the optional immutable
`managed_bulk_extended_recovery` marker. Startup, GET, ordinary queue use and
inspection never create it. Existing recovery/reconciliation receipts remain
byte-for-byte unchanged. The original epoch transition guards remain in place.
An additional SQL guard refuses an extended ATTENTION-to-IDLE transition without
its matching marker; failure rolls the complete decision back, including any new
schema/receipt.

The new receipt uses `claims_format=compact-v6` and ordered six-field tuples
bound by the marker's exact count and SHA-256 digest. It stays within the existing
**16-KiB** receipt limit without truncating evidence. Operator review and replay
output expand the same named fields. Missing, duplicated, reordered, malformed
or misbound claims/markers refuse; receipt replay cannot release another epoch.
The 4096-receipt and 1024-reviewed-unknown capacity limits remain; nothing is
evicted to fit a recovery.

Old DB writers refuse the new optional profile. Retain original archives/images,
but do not force an old API against the upgraded DB, remove guards/markers or
restore stale standing authority to roll back. Use compatible code after this
decision; no reverse converter or destructive reset is required.

See [verified recovery](verified-epoch-recovery.md),
[unknown ADD reconciliation](quiescent-managed-reconciliation.md) and
[multi-group sessions](multi-group-sessions.md). Consult current project status
for actual laboratory rehearsal/application and remaining limitations.
