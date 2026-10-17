# Managed Removal Handoffs — Offline Integration Contract

## Current boundary

Implemented on 2026-10-17 as an internal coordinator in `managed_removals.py`,
**not connected to admission HTTP/Web forms or the scheduler**. Optional GET
visibility and [preparatory Web reviews](managed-removal-review.md) are now
implemented; confirmation cannot execute or call this coordinator. Normal API/Store/queue
startup does not initialize it. Do not initialize or call it against the lab/
production database for testing. No live mutation is authorized; ADD/restoration
gates remain off. The initial contract handles **one reviewed device/IPv4 pair**
per request, not a silently split fleet/bulk operation.

## Atomic admission and durable authority

`canonical_managed_removal()` binds `RETIRE_AND_REMOVE`, fixed
`stop_maintenance_and_remove` mode, exact pair, managed revision, bounded reason
and a 1–900-second cleanup authorization. Its digest differs from policy-only
RETIRE or import; it is confirmation binding, not authentication.

`ManagedRemovals.admit()` requires current non-blank Operator/Administrator,
canonical UUID and matching digest. One `BEGIN IMMEDIATE` transaction checks
replay/namespaces/revisions/limits, retires the intent and either queues removal
or reserves `WAITING_ADD` against the exact already-RUNNING ADD. It never cancels
a running command or creates a second active device/IP job. Unstarted one-time
ADD conflicts: cancel it explicitly first. Disabled devices can be stopped via
policy-only retirement, but this coordinator does not admit their cleanup.
Failure rolls back root authority, retirement, queue/reservation and audit;
accepted logs are emitted only after commit.

Explicit initialization adds `managed_removal_handoffs`: immutable actor/roles,
canonical review/result, original dates/deadline, intent/generation, predecessor
and deterministic separate retirement key; mutable phase/reason. At most
**10000 total records**, retained without automatic key recycling. When full,
composite requests fail atomically; the registry's policy-only retirement is
independent. A replay returns the original reference, not current execution
status, and never requeues cleanup or retires a newer generation, even after
ordinary queue/history pruning.

Waiting reservations share the **1000 unfinished-slot** and **2000 active-request**
bounds with ordinary queue work. A running predecessor plus reserved cleanup
consume two slots. Waiting-only requests also share the ten submissions per
actor/minute limit, including after cancellation. Promotion is the same request,
not new delegation. New ADD cannot coalesce into a waiting-cleanup target.
Maintenance cannot be re-enabled while cleanup waits, is queued/running or
needs attention.

## Ordered settlement

`advance(owner, limit=16)` requires the current valid executor lease and processes
at most 16 eligible handoffs. It is explicit: **the scheduler does not call it**.
It opens no SSH/RPC and never sends device commands itself.

| Condition | Result |
| --- | --- |
| Predecessor still RUNNING | Keep waiting; no overlap or fake cancellation. |
| VERIFIED, NOOP, FAILED or UNVERIFIED | Queue separate REMOVE under the remaining original authorization; preserve the ADD outcome/uncertainty. |
| Exact predecessor returned to QUEUED after known pre-write deferral | Cancel that same unsent ADD, then queue REMOVE atomically; do not resubmit ADD. |
| Authorization expired | EXPIRED; no cleanup and no deadline extension. |
| Missing/inconsistent predecessor, changed intent, disabled device or admission failure | ATTENTION, not a device write or automatic retry. |

Ready selection excludes still-running predecessors to avoid head-of-line
starvation. Unexpected database/audit errors roll back the outer transaction.
`ADMITTING` exists only inside an uncommitted admission transaction; committed
phases are WAITING_ADD, ADMITTED, EXPIRED, CANCELLED and ATTENTION. This guard
also prevents direct queue-key reuse after a completed request was pruned.

ADMITTED means handed to the existing queue, not removed. `snapshot()` reports
phase separately from linked queue state, with full counts and at most 20 rows.
The optional GET/UI now exposes this read-only view. Fresh snapshots, verified agent response, FIFO/cutoff,
cooldown and command/time/mutation budgets remain the existing worker's job.
Cleanup does not bypass cutoff because ADD finished. Uncertain ADD is neither
upgraded to verified creation nor replayed.

Owner/Administrator may `cancel_waiting()` without cancelling ADD or enabling
maintenance. Once admitted, use ordinary queue cancellation. Cleanup failure,
expiry, uncertainty or cancellation never reverses retirement. Attention has
no automatic rearm path. Structured logs omit reason text and canonical payload;
SQLite audit retains actual actors and predecessor/intent/request correlation.

## Validation, migration and recovery

`tests/test_managed_removals.py` uses temporary SQLite and synthetic typed queue
results: atomic/audit rollback, parallel replay, running/deferred/verified/no-op/
uncertain settlement, lease recovery, deadlines/cancellation, shared limits,
namespaces, generations, pruning, immutable authority and SQLite backup. This
is not live Cisco, session, load or production evidence.

**No live migration, deployment or restart was performed.** Before runtime use,
complete executable confirmation/cancellation, shared-worker wake/advance/
expiry, all-device scope union, protection/system cancellation and reviewed
recovery tools. Take a checked SQLite-safe backup and retain paired images
before an approved schema rollout. Do not drop authority/tombstones to revert.

Retention preserves a predecessor while cleanup waits; handoff authority is
not ordinary expiring history. Backup recovery must suspend waiting cleanup,
queued jobs and desired restoration before starting any worker, followed by
fresh observations and review. Current tools do not implement that composite
recovery procedure: it blocks live rollout. Older images ignore reservations;
never run them against pending handoffs. Reverting code or restoring a backup
does not authorize replay. This coordinator does not enable restoration.
