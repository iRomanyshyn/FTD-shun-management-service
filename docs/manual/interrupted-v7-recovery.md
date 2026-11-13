# Recover an Interrupted Deferred Import Without Completion Proof

Source0.14.0 adds an explicit offline recovery procedure for a bounded managed-v7
ADD visit when automatic completion recovery cannot obtain its original receipt.
The main lab still runs verified v6. This procedure does not select v7, convert
the original DB or publish a release. Use the separate deferred test DB only.

If the original agent completion receipt is available, prefer normal
[automatic pending recovery](pending-restart-recovery.md). This procedure never
creates an END receipt or treats a later device presence as proof of creation.

## Outcome

1. **Classify interrupted work.** Original RUNNING ADDs become UNVERIFIED; known
   terminal results remain unchanged. Their claim/ACK/checkpoint audit stays.
   The original device session remains on ATTENTION, with no successor allowed.
2. **Review and reconcile separately.** A new exact review binds the whole
   unknown scope. Applying it retains those unknown results, records the operator
   decision and releases only the original epoch. Old jobs are never replayed.
3. **Read before continuing.** On restart, the normal scheduler must obtain a
   complete FTD read that starts after the recovery decision. Currently present
   addresses need no ADD. Missing ones require new jobs under current saved
   policy, pauses, protection, backoff and quota checks. Recovery does not resume
   pauses, re-enable retired rules or override Protected IPs.

Expired/cancelled original requests stay revoked. Recording their unknown terminal
outcome does not renew execution permission. The separate policy-only authority
may still maintain the address, unless the operator has stopped it.

## Preconditions

- Actually stop API/Web/agent and ensure previous SSH/CLI work has settled. A stop
  request or elapsed local timeout alone does not establish this. Keep failure
  logs and agent-journal evidence. If quiescence cannot be established, keep the
  hold and investigate instead of asserting the flag below.
- Use the exact prepared deferred-v7 DB and compatible new image. Scope is one
  expired original device visit:1–64 managed ADD claims, at most16 unfinished.
  Known verified/no-op prefixes are retained. There must be no queued/awaiting
  work, other owned devices, unrelated unresolved outcomes, failed prefix or
  captured cancellation/ordered cleanup. Uncertain REMOVE is not supported.
  Original terminal audit must retain its device/epoch attribution. A restart
  that already reached ordinary expiry with unscoped terminal events still
  refuses; do not reconstruct or backdate those events to pass this procedure.
- Use a trusted maintenance label, fresh UUIDs and a new backup path in an
  operator-owned0700 directory. Each apply checks a complete SQLite backup and
  unchanged DB; reviews expire after five minutes. Backups are never overwritten.
- Do not point a legacy executable at this optional profile. Old writers refuse
  its exact marker/schema. There is no startup/GET initialization or online
  fence-release endpoint.

## Commands

Run from a trusted host with access to the stopped test DB, or a maintenance
container with only that experiment's DB mount. Replace paths/labels/UUIDs and
review values with the actual values; these commands do not stop services for you.

```sh
python -m ftd_shun_manager.pending_offline inspect \
  --database /absolute/path/to/deferred-test.db --device 1
```

Check the original epoch, complete job IDs and `running_to_unknown`. Then apply
the first decision using its exact `reviewed_at` and `review_digest`:

```sh
python -m ftd_shun_manager.pending_offline classify \
  --database /absolute/path/to/deferred-test.db --device 1 \
  --key NEW-CLASSIFICATION-UUID --actor operator-label \
  --reviewed-at REVIEW-TIME --review-digest REVIEW-DIGEST \
  --backup /private/backups/before-classification.db \
  --confirm-api-web-agent-stopped
```

Classification alone deliberately keeps ATTENTION. Obtain a **new** review after
that classification, without starting any writer:

```sh
python -m ftd_shun_manager.pending_offline inspect-reconciliation \
  --database /absolute/path/to/deferred-test.db --device 1

python -m ftd_shun_manager.pending_offline reconcile \
  --database /absolute/path/to/deferred-test.db --device 1 \
  --key NEW-RECONCILIATION-UUID --actor operator-label \
  --reviewed-at NEW-REVIEW-TIME --review-digest NEW-REVIEW-DIGEST \
  --backup /private/backups/before-reconciliation.db \
  --confirm-api-web-agent-stopped
```

The result preserves original unknowns and reports zero retried jobs and no
policy change. Start compatible agent/API/Web only after successful reconciliation.
Wait for the next complete read before interpreting import progress. Keep the
original reports, receipts, backups and separate test volumes.

If apply fails, its transaction rolls back. A successfully classified but not
reconciled device remains held; inspect the saved phase and obtain a fresh
reconciliation review. Do not rerun imports, alter job outcomes, drop guards or
restore an older DB to clear attention. Reusing the exact committed decision key
returns a historical receipt without changing policy or releasing a later epoch.

## Storage and validation

Explicit classification installs `managed_bulk_pending_classifications` and
`managed_bulk_pending_offline_recovery`. Each immutable classification binds the
original epoch, maintenance identity, review digest and exact resulting job/attempt
hashes. Shared reconciliation retains original unknown mappings and a separate
compact-v7 receipt marker. SQL and full-profile checks bind same-epoch release.
Classification capacity4096; existing reconciliation bounds also apply. No record
is evicted to make room. Retention preserves referenced jobs and original audit.

Tests use real disposable SQLite and checked backups for1/16/17/64-claim visits,
verified prefixes, rollback, exact keys, stale scope, current pauses/protection/
retirement and the mandatory post-decision read barrier. See project status and
development log for actual device acceptance and activation boundaries.

## Bounded laboratory acceptance — 2026-11-13

On a separate fresh DB, one198.51.100.179 ADD finished on the desk FPR, then the
API exited before pending handoff. Restarting an explicitly process-local agent
lost its completion proof. The API correctly kept the original RUNNING job and
expired lease; it sent no repeated ADD. Both writers were then actually stopped.
The real CLI created two checked backups, classified the one job UNVERIFIED and
separately reconciled it. On restart, the normal complete FPR read found the
address without another ADD. The original job remained unknown, while current
Queue attention became zero and reviewed history retained the decision.

A fresh reviewed REMOVE finished VERIFIED, policy retired/address absent, and
the isolated executor returned IDLE. Four SSH visits performed exactly one ADD
and one REMOVE. Original main v6/API/Web containers/images were restored; its
authority/audit prefix/all26 raw unknowns remained unchanged. Keep evidence and
separate volumes at `/tmp/ftd-fpr-offline-20261113`. This is one real missing-proof
case after completed END, not acceptance of every active interruption or an
activation of persistent v7 on the main stack.
