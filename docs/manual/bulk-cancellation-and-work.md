# Bulk Cancellation and Work Preparation

## Delivery boundary

This is the developer backend for the suspended
[version-2 bulk profile](bulk-policy-storage.md), not a live import runbook.
`BulkCancellations` permanently revokes the uncompleted part of an original
100000-pair import. `BulkWorkPlans` reports local state and prepares at most 16
candidate pairs at a time. Neither opens SSH, calls an agent, queues commands,
resumes restoration or exposes a new HTTP/Web route. The legacy lab is unchanged.
The separate [legacy cancellation](import-cancellation.md) still describes the
current gated Web workflow and its attempt settlement.
The separate [v2 API/Web surface](bulk-cancellation-surface.md) connects this
coordinator to compatible continuous storage without initialization/live activation.

## Whole-scope cancellation

Only the original import owner with current Operator/Administrator permission,
or another current Administrator, may inspect/cancel. Real current identity/roles
are checked, not copied from the grant or promoted. New admission/execution
capability is not required to revoke existing policy.

`review(key, subject, roles)` verifies the whole original root/source and accepted
scope in a read transaction. It binds original grant references, each current
disposition, managed/protection revisions and the reviewer. Confirm its exact
digest, UTC timestamp and accepted **pair count** within five minutes using
`cancel(...)`. Changed scope conflicts atomically, never silently shrinks/rebases.

| Original member/current authority | Cancellation disposition |
| --- | --- |
| Adopted at confirmation | `RETAINED_ADOPTED`: adoption was complete; maintenance remains. |
| Previously managed | `RETAINED_EXISTING`: keep original grant/generation. |
| Enabled original proposed ADD, no retained ADD or unfinished work | `STOPPED_UNSENT`: permanently stop that exact generation. |
| Already stopped | `ALREADY_STOPPED`: leave stopped without revision churn. |
| Newer/different generation | `SUPERSEDED`: leave newer authority untouched. |
| Protected exclusion/invalid input | No imported authority to revoke; keep original report. |

Observation after a proposed ADD does not prove service application. Cancellation
can stop its unapplied desired policy without removing an observed shun. It never
sends REMOVE or invents verified addition/removal/provenance.

### Initial limit: execution evidence

The original profiles retain the limitation below. A separately explicit
[captured-cancellation upgrade](bulk-captured-cancellation.md) now supports owned
completed/RUNNING/QUEUED outcomes and shared settlement without enabling dispatch.
It preserves old receipts/hashes; startup/GET never upgrades automatically.

An optional [version-2 result journal](bulk-attempt-journal.md) now captures
pre-send evidence and shared outcomes, but has no deployed admission/dispatch or
captured-wait cancellation integration. If an enabled
original proposed-ADD member has **any retained ADD job**, or independent
QUEUED/RUNNING work, cancellation refuses the whole decision. Even VERIFIED/NOOP
history cannot be attributed to this grant without a proper attempt binding.
Unknown outcomes are never treated as unsent or successful. Adopted/existing
members are retained, not classified as newly applied ADDs.

This is a pre-dispatch implementation. RUNNING capture, completed-application
retention and in-flight settlement must be integrated before bulk execution.
Do not bypass checks by pruning evidence, dropping tables, seeding receipts or
replaying commands. Ordinary outcomes and legacy incident/cleanup controls remain.

## Atomic records, replay and pages

The decision, exact accepted membership/dispositions, retirements, one managed
revision increment when anything stops, and actual-actor audit share one
transaction. Final audit/checksum/deadline failures roll back everything, even
inside a caller-owned transaction that catches the error and commits. No managed
request slot is consumed; full ledger/ordinary pause does not block revocation.

`managed_bulk_cancellations` retains one immutable decision per import.
`managed_bulk_cancellation_members` retains accepted pairs, original classification/
authority, reviewed revision and disposition. Members precede a final count-checked
seal through a deferred FK; the seal forbids later insertion. Both tables forbid
update/delete. Original-member/count checks and full streamed scope verification
refuse partial/inconsistent evidence. Bounds follow the existing 128 roots /
1000000 members; no automatic expiry or evidence eviction.

The original import UUID identifies cancellation, not a new grant/cleanup key.
After an interrupted reply, retry the exact original review and actual actor
payload. Matching retries return the saved result without retiring again, even
after review/draft expiry, pruning, restart, protection changes or new consent.
Changed actor/review/count payloads conflict. Original import replay also stays
historical and never re-enables cancelled policy.

`page(key, subject, roles, page=...)` reads at most 100 members, including page1000
of a full import. It returns `historical_cancellation=true`, not current execution
status. Later protection/retirement does not rewrite the old decision. Reads/
restart never settle attempts, initialize, retire or repair policy.

## Local progress and bounded portions

`BulkWorkPlans.progress(...)` separates original classifications from current
accepted-member dispositions:

- `MISSING_CANDIDATE`: enabled policy missing from cached observations.
- `OBSERVED_PRESENT`: locally observed presence, **not verified execution**.
- `STOPPED` / `SUPERSEDED`: original authority no longer requires this work.
- `PROTECTED` / `DEVICE_DISABLED`: policy/device holds.
- `WORK_PENDING`: an independent queued/running operation exists.
- `EVIDENCE_REVIEW`: ADD history or unknown outcome needs attempt-aware review.

Missing policy evidence is an error, not completed work. Reports explicitly say
`execution_available=false`, `observations_are_execution_receipts=false`.
There is no installation percentage inferred from cached presence.

`portion(..., limit=16, after=None, revision=None, protected_revision=None)`
returns at most 16 currently missing/eligible pairs in numerical device/IP order,
with exact intent/generation/original authority and current target revision.
It is **not an executable capability or reservation**. Continuation uses the
returned literal `(device_id, IPv4Address)` cursor and both saved revisions;
changed policy requires restarting preparation. No full target array or
100000-job backlog is built.

Each page reads one consistent local snapshot. Observations/device/work
eligibility can change between pages; newly eligible pairs before the cursor
appear on a new scan from the beginning. No durable execution cursor advances.
A later dispatcher must recheck fresh complete FTD evidence, settled prior RPCs,
current authority/protection/cancellation, device capabilities and shared queue/
attempt capacity under its own claim contract. Do not loop read portions directly
into admissions. Retained adoption/existing policy remains eligible for future
restoration after disappearance; stopped generations do not.

## Explicit extension, backup and rollback

No lab migration, migration CLI or profile activation was added. For disposable
development state, initialize the exact bulk profile first.
`BulkCancellations.initialize(connection=...)` explicitly adds two empty tables
and six triggers under ordinary pause/quiescence (no lease/pending/uncertain jobs).
It creates no prerequisites, grants, jobs or resume authority. Repeated exact
initialization is observational; failed DDL rolls back even inside an outer
transaction whose caller catches the error.

Current code recognizes the exact original profile or its exact extension.
The separately explicit attempt-journal extension is also recognized without
changing this cancellation decision/receipt format or enabling execution.
Partial/mixed/unsupported state refuses use; protection strengthening can still
persist an enabled deferred-retirement barrier. Startup/GET never migrates or
repairs. This initializer cannot convert retained legacy/lab state.

Before eventual non-disposable migration, stop writers/settle commands, retain a
private checked SQLite-safe backup and matching code/configuration, review exact
schema and obtain environment-specific authorization. An active WAL file copy
is not a backup. Older version-2 code refuses this extension; use compatible code
or keep data offline. Do not drop cancellation records, restore enabled policy
or release a barrier through an older writer to make a downgrade work. Today's
unchanged legacy lab needs no database restore.

## Validation

```bash
python3 -m pytest -q tests/test_bulk_cancellations.py tests/test_bulk_policy.py tests/test_bulk_protection.py tests/test_import_cancellations.py
```

Disposable tests cover actual 100000-pair cancellation/restart/pruning/late pages,
mixed scope, old/new generations, concurrent replay, real actor/current roles,
strict review fields/conflicts, full ledger/pause, atomic audit/DDL/deadline
rollback, immutable/partial/corrupt state, protection and bounded portions with
zero jobs. This is not RPC throughput, automatic reconciliation, hardware
capacity or live import acceptance.
