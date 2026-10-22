# Bulk Attempt Result Journal

## Delivery boundary

`BulkAttempts` adds retained version-2 attempt evidence and connects it to the
existing queue's completion, exact deferral, lease recovery, status and retention
transactions. It is **not** a new executor, job admission API, runtime controller,
retry mechanism or permission to send ADD. The bulk registry remains suspended.
No deployed caller invokes capture and no new HTTP route/configuration gate is
added. The current legacy lab is unchanged.

See [bulk storage](bulk-policy-storage.md) and
[cancellation/work preparation](bulk-cancellation-and-work.md) for prerequisites.
Captured-wait cancellation and completed-application retention are now supported
by a separately explicit [captured-cancellation profile](bulk-captured-cancellation.md).
This journal's original profile keeps its earlier refusal and never upgrades at
startup/GET. Atomic claim/admission and automatic reconciliation remain pending.

## Explicit optional schema

`initialize(connection=...)` adds `managed_bulk_attempts`, one pair/time index and
five capture/identity/retention/terminal/transition triggers to an exact existing
bulk-plus-cancellation profile. Ordinary mutation pause, a quiescent queue and no
executor lease/pending/uncertain work are required for first initialization.
Repeated exact initialization is observational; partial/mixed/legacy schemas
refuse use. DDL rolls back within a caught caller-owned transaction.

The table binds original request/job IDs, device/IP, intent/generation/authorizing
root, target revision, complete-read identity/times, original request time, state
and completion/occurrence evidence. Identity cannot change, rows cannot be deleted
and terminal outcomes cannot be rewritten. Only an initial RUNNING capture is
allowed. A typed pre-write deferral may transition RUNNING to QUEUED; the current
profile permits cancellation/failure from that state, **never redispatch**.

The retained limit is 1000000 attempts, including completed/failed/unknown records.
Capacity refuses capture without eviction. It does not increase queue capacity,
authorize a bulk backlog or establish hardware throughput. Startup/GET never
creates the optional table, retires authority, repairs evidence or resumes policy.

## Pre-send capture contract

`capture_running(key, job_id, snapshot, owner, enabled=False, connection=...)`
is a future trusted pre-send composition hook. A literal default-false capability
and caller-owned write transaction are required. The future dispatcher must
create/claim the job, bind evidence and commit before sending an external command;
it must never send after rollback. This component does not implement that claim.
The result explicitly says `dispatch_authorized=false`.

Capture checks:

1. Exact initialized profile and bounded complete typed snapshot, UTC times,
   absence of the target and freshness within 120 seconds.
2. A RUNNING ADD with explicit ADD dispatch kind; one original system request/
   job/link, fixed system identity and no invented user roles. Manual/import jobs
   and retroactive terminal-history adoption are refused.
3. Exact payload/intent/generation/original authorization, root integrity and
   current target revision. The device and desired policy must be enabled, with
   no active protection, ordinary pause or local observed presence.
4. Shared active executor lease/owner, original 900-second request and valid
   original deadline. Evidence must follow policy and earlier successful work;
   capture never renews consent or the request.
5. No earlier pending/failed/unknown attempt or independent pending/uncertain pair
   work. Earlier grants, preparations, imports, requests/jobs and captured keys
   cannot acquire new attempt meaning through namespace reuse.

The evidence insert and system audit are atomic with the caller's transaction;
late audit/freshness/lease failure rolls them back. Recapture conflicts, not rearm.
The hook has no live caller and does not itself create a request/job or make the
suspended registry executable. Synthetic tests construct the hypothetical pre-send
transaction directly; they are not end-to-end claim or FTD acceptance.

## Shared result handling

The existing queue result hook selects the bulk journal only when its exact
profile is recognized. Legacy restoration tables/readers keep their old meaning.
The same queue transaction commits job state, journal outcome and audit:

| Result | Retained meaning |
| --- | --- |
| VERIFIED | Exact worker success plus one actual locally recorded occurrence/interface. |
| NOOP | Already present; no invented service-created occurrence/provenance. |
| FAILED | Original failure remains; no automatic replay. |
| UNVERIFIED | Lost/uncertain result remains unknown, including expired-lease recovery. |
| Exact pre-write deferral | QUEUED evidence, followed by cancellation in this nonexecuting profile; no resend. |

Terminal events are `MANAGED_BULK_ATTEMPT_*`, retain original authority/snapshot/
job references and use the fixed system actor with no user roles. Human standing
consent remains in the original grant. A later verified in-flight result after
retirement/protection does not enable policy again or prove an unblock. Protected
removal remains a separate scheduler operation. A late audit failure rolls back
the job, journal, occurrence and all associated events together.

The legacy restoration-execution capability cannot make a deferred bulk job run.
No new source discovery, session, scheduler or network path is introduced.

## Retention and read-only evidence

Pending/unknown predecessors and linked requests survive ordinary queue retention.
Every held binding is checked before pruning; missing jobs/requests, contradictory
state or malformed identity/source refuses pruning rather than fabricating evidence.
Terminal independent journal evidence survives normal job/request pruning, so old
completion is not reconstructed from observations. Failed/unknown evidence is not
cleared by age, retirement or a newer generation.

`page(root_id, subject, roles, page=1)` verifies original root scope and current
Operator-owner/Administrator authority, returns whole-scope state counts and at
most 100 evidence rows, and labels the response read-only/evidence-only with
execution unavailable. It is not current desired-state status or retry authority.
Selected held rows require original queue evidence; selected terminal rows may
remain readable after normal pruning. GET/restart never repairs or settles them.

The original journal profile refuses in-flight/unattributable ADD evidence.
The separate captured-cancellation upgrade can wait on owned ADDs, while
unattributable evidence still conflicts. It preserves the original attempt and
cancellation receipts. No HTTP captured-wait admission route exists; journal
visibility alone does not authorize cancellation. Do not interrupt commands or
prune evidence to bypass the checks.

## Migration, backup and rollback

No lab migration or activation was performed. Explicit developer initialization
preserves the prior exact profile, roots, cancellation decisions and all source
evidence; it never converts legacy attempts. Before eventual non-disposable use,
stop writers/settle commands, retain a private checked SQLite-safe backup and
matching code/configuration, review schema and obtain scoped environment approval.
An active WAL file copy is not a backup.

Current code recognizes exact base, cancellation and cancellation-plus-journal
profiles. Older version-2 code refuses the journal extension. Use compatible code
or keep the database offline; never drop the journal/receipts, restore enabled
policy or release a barrier with an older writer to force a downgrade. A code-only
rollback on today's unchanged legacy lab needs no database restore. New live
fixtures, migrations or enabling dispatch are not authorized by this implementation.

## Validation

```bash
python3 -m pytest -q tests/test_bulk_attempts.py tests/test_managed_restoration.py tests/test_import_cancellations.py tests/test_queue_transactions.py
```

Disposable fixtures cover typed results, retired/protected policy, exact deferral,
lease recovery, original identities, pending/unknown retention, pruned terminal
evidence, malformed predecessors, late audit/DDL rollback, strict capture guards,
namespace protection, read permissions and continued running-cancellation refusal.
No worker/FTD connection, lab setting, real credential or live admission is used.
