# Captured Bulk Cancellation

## Delivery boundary

This extends [bulk cancellation](bulk-cancellation-and-work.md) after the
[attempt result journal](bulk-attempt-journal.md). It implements cancellation
while an original ADD is RUNNING and settlement through the existing queue result
transaction. It does not add a dispatcher, queue admission, HTTP route, runtime
flag or permission to send FTD commands. The registry remains suspended and the
current legacy lab is unchanged.

An explicit optional profile upgrade is required; startup/GET never performs it.
Earlier bulk profiles keep their original refusal of in-flight cancellation.
The new path retains existing owner/Administrator, exact accepted-pair count,
five-minute review, actual actor, whole-scope revision and same-key retry rules.

## What cancellation does

Reviews stream exact owned attempt history into a frozen digest, including its
state, original authority and captured predecessor. A later result/protection/
generation change conflicts with that review rather than silently changing scope.
Unattributable ADD history or independent unfinished work is never taken over.
Cached observation alone is not proof that a service ADD was applied.

| Original accepted member | Initial cancellation disposition |
| --- | --- |
| Adopted/already managed | Retain the original policy, as before. |
| Owned VERIFIED/NOOP application | `RETAINED_APPLIED`; maintenance remains even if subsequently absent. NOOP does not invent creation provenance. |
| First owned ADD is RUNNING | `WAITING_OUTCOME`; capture exact job/authority, do not interrupt or guess its result. |
| Owned unsent QUEUED work / no application | `STOPPED_UNSENT`; retire exact authority and cancel only its own unsent job after sealing the whole decision. |
| Owned failed/unknown first ADD | `STOPPED_FAILED` / `STOPPED_UNVERIFIED`; retire future maintenance, retain original outcomes/attention. |
| Original already retired/newer generation | `ALREADY_STOPPED` / `SUPERSEDED`; never re-enable or touch replacement authority. |

The decision, frozen accepted membership/history bindings, immediate retirements,
owned unsent cancellations and audit commit together. No new managed-request slot,
REMOVE, immediate agent call or user-role promotion follows. Bulk cancellation
does not undo applied additions. Use a separately reviewed removal flow to unblock.

## Waiting for a command

The existing shared queue completion transaction also appends one settlement for
each captured wait. It preserves the original job/attempt outcome and decides:

- VERIFIED/NOOP: retain still-enabled exact original authority.
- FAILED/UNVERIFIED: retire future maintenance, keep original failure/uncertainty
  and mark attention. This is not verified removal or permission to retry ADD.
- Exact typed pre-write deferral: retire unsent policy, append settlement, then
  cancel the now-QUEUED job in the same transaction. No resend or renewed request.
- Protection/prior retirement/new generation: leave it stopped or superseded,
  regardless of the original command's later success. Never re-enable policy.

Settlement is stored before recursive cancellation of a deferred job, preventing
double settlement/retirement. Lease-expiry recovery records UNVERIFIED and settles
through the same result hook. Late audit/settlement failure rolls back job,
journal, occurrence, policy and all events together. Real cancelling actor/roles
are retained in settlement audit; the attempt keeps its fixed system identity.

## Historical receipt versus current status

The original cancellation receipt and member dispositions stay immutable,
including initial `WAITING_OUTCOME` counts. The separate
`managed_bulk_wait_results` ledger holds immutable final disposition, original
job, outcome, attention and timestamp. One accepted member has at most one result.

`BulkCancellations.page(...)` on this profile returns:

- `result`: immutable initial receipt, also returned by an exact retry.
- `current_counts`, `settled`, `attention_count`: current settlement summary.
- At most 100 targets, with `initial_state` distinct from current `state` and
  optional settlement outcome/time. Terminal unknown attention remains visible.

The same original key/review/actor can recover history after expiry, restart,
pruning or later explicit grants without applying revocation again. GET/restart
never settles or repairs a command. Original import confirmation receipts are
unchanged. Cancellation settlement does not resolve an uncertainty latch.

## Retention and incompatible writers

Validate and retain every pending captured job/request/link, including when an
incompatible writer recorded a terminal attempt but omitted settlement. Such a
case stays visibly pending: GET does not infer the missing decision. New authority
and migration remain blocked even if the ordinary queue looks terminal/quiescent.
Missing/mismatched jobs, requests, roles, authority or state refuse pruning.

After settlement, independent unknown attempt evidence and its original queue
records still survive retention. Completed independent evidence can outlive normal
queue pruning and still prove earlier application; cached presence is not used as
a substitute. No repair/replay/resolution tool or automatic reconciliation is
provided by this increment.

## Explicit preservation upgrade

`BulkWaits.initialize(connection=...)` requires an exact existing cancellation/
attempt profile, ordinary mutation pause and quiescence. It never creates its
prerequisites. Repeated exact initialization is observational; partial/unsupported
state refuses use. The upgrade:

1. Verifies every existing original root and cancellation scope/receipt.
2. Transactionally rebuilds only `managed_bulk_cancellation_members`, preserving
   its original nine fields/data and adding nullable `job_id`/`attempt_digest`
   plus the expanded disposition checks. Original rows remain immutable.
3. Recreates the six original cancellation guards and adds the immutable
   settlement table with three capture/update/delete guards.
4. Verifies exact schema, whole-source integrity and unchanged historical receipts
   before commit. Empty new fields are omitted from old scope hashes, not filled
   with reconstructed execution evidence.

All DDL/copy/checks roll back together, including inside a caller-owned transaction
that catches an error. The temporary old member table is removed only after its
rows are copied inside that transaction; it is not an operator cleanup action.
No old decision, checksum, original attempt outcome or source authority is rewritten.

No live migration was performed. Before non-disposable use, stop writers/settle
RPCs, retain a private checked SQLite-safe backup and matching code/configuration,
review the exact schema and obtain environment-specific approval. Do not copy an
active WAL file as a backup. Old code refuses the expanded profile: retain
compatible code or keep data offline. Never drop settlements/receipts, restore
enabled policy or release barriers with an older writer to force a downgrade.
The unchanged legacy lab needs no database restore.

## Validation

```bash
python3 -m pytest -q tests/test_bulk_waits.py tests/test_bulk_cancellations.py tests/test_bulk_attempts.py
```

Disposable tests cover running/completed outcomes, exact deferral, lease recovery,
protection/retirement/newer-generation precedence, original-key history, current
status, audit/migration rollback, immutable records, old-writer pending evidence,
retention/no-replay, owned versus independent work and quiescence. The existing
100000-member scenario additionally verifies preservation upgrade and late-page/
original-receipt stability with zero executable backlog. No FTD/worker/lab access
or executable bulk-load acceptance is involved.
