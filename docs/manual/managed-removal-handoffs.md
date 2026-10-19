# Managed Removal Handoffs — Atomic Coordinator Contract

## Current boundary

Implemented on 2026-10-17 as an internal coordinator in `managed_removals.py`,
now connected to independently default-off [combined admission](managed-cleanup.md).
A separately gated shared-worker hook is implemented, default off. Optional GET
visibility and frozen Web reviews never admit work; explicit confirmation alone
may call the coordinator when both admission/worker configuration permits it.
Separate owner/Administrator waiting-cancel controls are available without
admitting device work; see [Managed Controls](managed-controls.md). Normal API/Store/queue
startup does not initialize it. Do not initialize or call it against the lab/
production database for testing. No live mutation is authorized; ADD/restoration
gates remain off. The initial contract handles **one reviewed device/IPv4 pair**
per request, not a silently split fleet/bulk operation. A separate frozen
[fleet scope review](managed-removal-review.md#frozen-all-device-scope) now reads
the full union and supplies a transactional comparison primitive; it does not
extend this single-target handoff into fleet ordered waiting. A separate
[ready-target fleet coordinator](managed-fleet-removals.md) now atomically retires
and admits a complete scope in default ready-only mode. Its separate explicit
ordered mode now reserves the whole scope behind RUNNING ADD; it never loops
this single-target coordinator or commits partial fleet cleanup. Both remain
separate coordinators, with default-off device/fleet HTTP admission and no live
schema initialization.

## Atomic admission and durable authority

`canonical_managed_removal()` binds `RETIRE_AND_REMOVE`, fixed
`stop_maintenance_and_remove` mode, exact pair, managed revision, bounded reason
and a 1–900-second cleanup authorization. Its digest differs from policy-only
RETIRE or import; it is confirmation binding, not authentication.

`ManagedRemovals.admit()` requires current non-blank Operator/Administrator,
canonical UUID and matching digest. HTTP also supplies exact reviewed intent/
generation, checked both on new admission and historical replay. One `BEGIN IMMEDIATE` transaction checks
replay/namespaces/revisions/limits, retires the intent and either queues removal
or reserves `WAITING_ADD` against the exact already-RUNNING ADD. It never cancels
a running command or creates a second active device/IP job. Unstarted one-time
ADD conflicts: cancel it explicitly first. Disabled devices can be stopped via
policy-only retirement, but this coordinator does not admit their cleanup.
Failure rolls back root authority, retirement, queue/reservation and audit;
accepted logs are emitted only after commit. Original deadline is rechecked
before commit even for a waiting/ready plan; late expiry rolls the whole plan back.

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
at most 16 eligible handoffs per direct call. The shared scheduler calls `advance_if_present()`
once per cycle only with `FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED=true` (default
false; deployed Settings require socket mode). This does not enable admission,
ADD or desired restoration and never initializes optional tables. Waiting work
participates in the persisted 60-second cooldown; the current lease is required.
It now allocates at most eight roots each to single/fleet cleanup, sixteen total.
Advancement occurs after lease recovery but before capturing the cycle cutoff,
then each device supplies a fresh initial snapshot before ordinary removal.
It never runs mid-cycle against an old pre-ADD in-memory snapshot. Work admitted
after the cutoff, or an ADD settling during the cycle, waits for the next one.
Already ADMITTED jobs belong to the ordinary queue, not this promotion gate.
Unexpected advancement errors block mutations for the entire cycle, retain
monitoring/final snapshots and publish a sanitized status/log warning; they do
not create an independent writer or turn errors into empty policy. Global
recovery suspension blocks promotion, admission and mutation claims.
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

Default-off executable confirmation, all-device scope union and protection/
system cancellation now have synthetic coverage. Reviewed migration/resume/
uncertainty resolution and scoped fixture validation remain before live use.
Shared-worker wake/advance/expiry is tested with synthetic state;
it is not enabled in the lab and no handoffs are seeded there. Take a checked SQLite-safe backup and retain paired images
before an approved schema rollout. Do not drop authority/tombstones to revert.

Retention preserves a predecessor in WAITING_ADD, ADMITTING and ATTENTION,
including linked request evidence. UNVERIFIED jobs remain retained independently
even after cancellation/expiry; age is not uncertainty resolution. Handoff authority is
not ordinary expiring history. Backup recovery must suspend waiting cleanup,
queued jobs and desired restoration before starting any worker, followed by
fresh observations and review. [Offline Recovery](recovery.md) now implements
checked composite suspension and ordinary resume, never desired restoration
resume. Older images ignore both the durable pause and reservations;
never run them against pending handoffs. Reverting code or restoring a backup
does not authorize replay. This coordinator does not enable restoration.
