# Confirmed Import Cancellation

## Delivery boundary

This backend cancels the uncompleted part of a
[confirmed managed import](managed-import-confirmation.md). The separate
[Web workflow](managed-import-web.md) now exposes review, confirmation and current
status. This is not an executable 10,000-IP import release; live gates remain
unchanged. No lab migration, policy fixture or device mutation is included.

Cancellation never sends `no shun`. Already applied/adopted policy remains managed.
To actually unblock those targets, use the separately reviewed removal workflow.
Cancelling an unconfirmed preparation remains a different, draft-only operation.

## Whole-scope review and authority

Only the original import owner with current Operator/Administrator permission,
or another current Administrator, may review/cancel/read cancellation status.
Trusted identity comes from the authenticated BFF, not public input. No standing-
admission/ADD capability is required for revocation; disabling new admission must
not remove the ability to cancel existing work.

A read-only review binds the original immutable import receipt, every accepted
device/IP and assigned intent/generation/authorization, current policy/protection
revisions and exact retained ADD outcomes. Confirm its digest, exact UTC review
timestamp and accepted **pair** count within five minutes. Any relevant change
rejects the whole decision, without silently shrinking or rebasing scope. Independent
unfinished work conflicts; it is not taken over or cancelled. No additional
canonical managed-request slot is needed to revoke an import.

| Current original member | Cancellation effect |
| --- | --- |
| Adopted at confirmation | `RETAINED_ADOPTED`: adoption is already complete; no creation claim. |
| Already managed before import | `RETAINED_EXISTING`: leave original authority unchanged. |
| Owned ADD has VERIFIED or NOOP evidence | `RETAINED_APPLIED`: keep maintenance, even if subsequently absent. NOOP is not service-created provenance. |
| No completed application / owned QUEUED ADD | `STOPPED_UNSENT`: retire the exact original generation and cancel only its unstarted job. Cached observation alone is not proof of application. |
| Owned first ADD is RUNNING | `WAITING_OUTCOME`: capture it, block further dispatch for this generation and let the existing command settle. |
| Failed/unknown initial ADD | `STOPPED_FAILED` / `STOPPED_UNVERIFIED`: retire future maintenance but retain original failure/uncertainty and attention. |
| Original authority already retired | `ALREADY_STOPPED`: never re-enable it. |
| Newer/different authority | `SUPERSEDED`: leave the newer grant untouched. |
| Protected exclusion / invalid input | No imported authority to cancel; original report retains the exclusion/diagnostic. |

The decision, exact accepted scope, immediate retirements, queued cancellations
and real-actor audit commit together or none. Historical confirmation reports are
unchanged. Cancellation is permanent for this import's remaining work, not a
pause/resume switch. A new explicit grant is a distinct later action.

## In-flight settlement and recovery

The existing queue result transaction also settles each captured predecessor:

- VERIFIED/NOOP retains the already enabled original policy.
- FAILED/UNVERIFIED retires that original policy and marks attention. Outcomes,
  occurrence evidence and uncertainty latches are never rewritten as success.
- An exact typed pre-write deferral retires/cancels the unexecuted job; it does
  not send the ADD again or renew authority.
- Protection/independent retirement/new generations win in every case. Settlement
  never re-enables policy, removes device state or touches a newer grant.

Lease-expiry recovery records UNVERIFIED and settles cancellation in the same
transaction. There is no second executor, startup/GET settlement or blind replay.
If a command really succeeded but its reply was lost, the original uncertainty
remains visible; cancellation does not invent verified application or removal.
Pending captured jobs and linked requests survive queue retention. Missing,
malformed or mismatched predecessors refuse pruning rather than fabricate evidence.

## Private API and receipts

All three are fixed private POSTs under `/api/v1/managed-imports/` with strict
bodies, trusted actor identity and `no-store` responses:

| Suffix | Body / result |
| --- | --- |
| `cancellation-review` | Actor and original `operation_id`; five-minute review/counts, or `already_requested` without new authority. |
| `cancel-confirmed` | Actor, original `operation_id`, `reviewed_at`, `review_digest`, strict integer `accepted_count`; one root-scoped cancellation. No target/action/CLI fields. |
| `cancellation` | Actor, original `operation_id`, optional `page`; current counts, attention, settled flag and at most 100 member rows. |

The original import UUID identifies the cancellation; no new key namespace can
gain ADD/removal/cleanup authority. Retry the exact original review and identity
after an uncertain response. Matching retries return the **immutable initial
receipt**, even after expiry, settlement, retirement or restart; they never issue
another revocation. Different review/actor payloads conflict after a decision exists.
Use status for **current** settlement, not the receipt's original WAITING counts.
An Administrator can inspect another owner's case, but cannot reinterpret that
owner's saved decision as a new Administrator-authored action.

The [Web integration](managed-import-web.md) enforces session/CSRF/sensitive-action
age, retains the review through uncertain replies, shows retained/stopped/attention
counts and explains that applied targets remain blocked. Rolling-import execution/
progress remains separate pending work.

## Migration, backup and rollback

No live migration was performed. Before separately approved activation, quiesce
mutations, take and validate a SQLite-safe backup with matching images/configuration,
review the exact current schema and explicitly initialize prerequisites in order:
policy/attempts, preparations, confirmed reports, then cancellation controls.
`ImportCancellations.initialize(connection=...)` creates only two empty tables,
one partial pending-pair index and five immutability/retention/transition triggers.
It participates in a caller-owned transaction and never creates prerequisites or
effective authority. Startup/requests/reads never call it or repair partial state.

The tables are `import_cancellation_decisions` (one immutable decision per confirmed
root) and `import_cancellation_targets` (exact assigned identities, initial/settled
disposition and captured predecessor). Terminal rows cannot change; only a pending
row can settle once. Existing confirmation limits imply at most 128 decisions and
128,000 accepted rows; current registry limits remain 1000 keys/accepted pairs,
with unchanged request/attempt bounds. Nothing is automatically evicted.

New confirmations now require these explicitly existing controls. Historical
confirmation reads and original-key recovery remain independent of this new
prerequisite. Current gates and lab optional schemas remain unchanged.

Do not roll back to writers lacking cancellation hooks while any member is
WAITING_OUTCOME. Quiesce, inspect/settle through compatible code first, and retain
all journals and evidence. If an unsupported older writer already committed a
result without settlement, status honestly remains pending and pruning preserves
its evidence; GET does not repair it or authorize replay. No automatic repair tool
is provided. Do not restore old enabled policy or erase journals as code rollback.
The agent/protocol/Compose are unchanged by this backend increment.

## Validation

Run `python3 -m pytest -q tests/test_import_cancellations.py tests/test_managed_imports.py tests/test_managed_restoration.py`.
Fixtures are temporary SQLite/ASGI, not the laboratory. They exercise queued and
RUNNING outcomes, exact deferral, lease recovery, protection precedence, retained
success after queue pruning, full current 1000-pair cancellation/pagination,
original-key concurrency/replay, current roles, atomic rollback and strict API.
This is not throughput, hardware, production or 100,000-pair execution acceptance.
