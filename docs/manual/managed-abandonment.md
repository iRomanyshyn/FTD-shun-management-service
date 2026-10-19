# Offline Restoration Incident Abandonment

## Meaning and limits

`ABANDON_MAINTENANCE` records a trusted-host operator's decision to stop maintaining
one managed device/IP following a retained FAILED/UNVERIFIED restoration attempt.
It retires the **current** target, which may be a later generation than the
attempt, and retains an immutable decision/receipt. It never calls FTD, repeats
ADD, submits REMOVE, changes an outcome to VERIFIED or clears a restoration latch.
Already retired target dates and original consent are preserved.

This closes the operational maintenance decision, **not the unknown device
outcome**. Policy resume still refuses retained FAILED/UNVERIFIED attempts and
uncertain jobs, including abandoned ones. Resuming unrelated healthy policy,
rearm/new authorization and ordinary/device/fleet cleanup incident resolution
remain separate unimplemented controls. Abandonment permanently blocks MAINTAIN
and restoration for this pair in the current implementation. It is not a retry.

There is no HTTP route, Web confirmation or automatic startup migration. No
actual lab migration/closure or new fixture is approved merely by building or
shipping these commands. The consumed one-address test authorization is not
reusable. Use disposable state for contributor tests.

## Prerequisites and deployment impact

Follow [Offline Recovery](recovery.md) and
[Offline Managed Maintenance](managed-maintenance.md): checked private backups,
current matched API/Web package/images, database owner's UID, sole services stopped
with automatic restart prevented, all old agent RPCs settled (or agent stopped).
An expired lease is not proof a remote command stopped. `--confirm-offline`
asserts these operator responsibilities; SQLite cannot recall a command.

Suspend ordinary mutations **and** desired restoration through reviewed offline
recovery first. Recovery may cancel queued/waiting work and retains RUNNING as
UNVERIFIED; review that impact. Abandonment requires no pending job, executor
lease, pending managed handoff/restoration or inconsistent fleet admission. An
overlapping single/fleet waiting or ATTENTION cleanup blocks the operation;
there is no per-member substitute for whole-fleet review. Protection and disabled
devices do not block this revocation-only action. They never authorize a write.

Commands below use illustrative absolute paths. Select approved real paths first.
Each write takes a new exclusive 0600 SQLite-API backup in an operator-owned 0700
directory, verifies integrity/foreign keys and refuses concurrent commits. A
failure retains the backup and rolls back control/audit changes. Use a new backup
filename for every retry. Keep the report/reason private.

## Explicit closure-ledger migration

The base managed initializer still creates only its original seven tables. On
the exact existing base schema, prepare an independent migration review:

```bash
ftd-shun-managed-maintenance review-enable-closures \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

Inspect `ready`/`blockers`, then use the returned timestamp/digest within five
minutes:

```bash
ftd-shun-managed-maintenance enable-closures \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-closure-ledger.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

The transaction adds only `managed_incident_closures`, its index/immutable-update/
retained-delete triggers and a migration audit event. Existing targets, attempts,
queue, protection, pauses and settings stay unchanged. No decisions are invented
for historical incidents. At most 10000 closure receipts are retained; no automatic
key recycling or archive exists. Partial/unknown schema refuses, not repair.
Both recognized seven-table and closure-extended versions remain readable.

## Review a specific restoration case

Find its exact `restoration:UUID` using [Attention Inspection](managed-attention.md).
The report's snapshot digest is **not** an abandonment confirmation.

```bash
ftd-shun-managed-maintenance review-abandon \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --case-id restoration:ORIGINAL_ATTEMPT_UUID \
  --reason "Stop maintaining this pair; retain the uncertain outcome"
```

Inspect the incident's original intent/generation/authorization and job evidence,
and the exact current target being retired. The five-minute review binds the
original canonical request UUID, operator, normalized nonblank printable reason
(at most 500 characters), evidence and retained state. Cached observations are
not proof of write success. Missing/pruned terminal jobs are explicit and may be
acknowledged from the immutable attempt; inconsistent retained jobs are refused.
No observed history is converted to standing authority.

Confirm with **all original review fields**, including its generated request UUID,
and type the target IPv4:

```bash
ftd-shun-managed-maintenance abandon \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-abandonment.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --case-id restoration:ORIGINAL_ATTEMPT_UUID \
  --reason "Stop maintaining this pair; retain the uncertain outcome" \
  --request-id REQUEST_UUID_FROM_REVIEW --confirm-ip EXACT_REVIEWED_IPV4 \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

Reason and operator must match preparation. Ordinary/fleet case IDs, stale or
future reviews, changed generation/protection/device/cache/state, mismatched
typed IP and keys reserved by another authority refuse instead of rebasing.
There is no automatic rekey/retry after an unknown response.

## Commit, receipts and investigation

One transaction stores minimal retained attempt/job/current-target evidence,
retires an enabled current target, increments registry revision, retains the
immutable decision/receipt and appends `MANAGED_RESTORATION_ABANDONED` with a
`maintenance:<label>` actor and empty directory roles. It never fabricates an
Operator/Administrator identity. An already retired target keeps its dates.
Original target intent/generation/authorization, attempt/job outcomes and every
queue entry remain unchanged. A late expiry or audit failure rolls everything
back, even if a caller catches the exception and commits the outer transaction.

Repeating **that exact original request** returns its historical receipt with
`replayed=true`, including after review expiry; it does not retire a later target
or renew authority. A different reason/operator/body under the same key refuses.
Use a new private backup filename for a deliberate CLI receipt retry. A second
request for the same incident cannot create another closure. Do not manufacture
a new review/key to guess whether an earlier submission committed.

The attention report keeps the original failure visible with a separate
`abandonment` decision, close time, decision UUID and `latch_retained=true`.
`abandoned_case_count` is not a count of verified device operations. Report
resolution availability remains false; no outcome/latch reset exists. Closure
keys remain reserved against policy/queue/restoration/cleanup authority, and
pair abandonment survives audit/queue-history retention. Original grant replay
cannot reactivate the retired target. No rearm route is present.

## Rollback and validation

Retain checked backups and paired matching images. Never drop a closure, its
triggers or original attempt to undo software changes, restore older enabled
policy or start an older writer that ignores retained abandonment. Downgrade
requires a separately reviewed offline plan. Ordinary recovery can suspend work
but does not remove decisions, reopen policy or prove device outcomes.

`tests/test_managed_abandonment.py` uses synthetic authority/disposable SQLite:
separate migration, no implicit init, atomic audit/DDL rollback, typed/frozen
scope, quiescence/protection/generation/cached-state conflicts, original-key
concurrency/replay, immutable retention, unchanged jobs/attempts/consent, pruned
evidence, late expiry and unchanged resume latches. Full recovery, source, queue,
grant/cleanup admission and attention suites remain required. No lab state,
new device command, production recovery or live acceptance is involved.
