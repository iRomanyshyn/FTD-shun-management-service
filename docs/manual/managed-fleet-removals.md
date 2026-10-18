# Atomic Fleet Removal — Offline Coordinator

## Boundary and prerequisites

`ManagedFleetRemovals` in `managed_fleet_removals.py` implements **atomic local
admission**, not atomic changes across Cisco devices. It is an internal offline
integration stage with no HTTP/CLI admission route, BFF call, startup migration
or enable switch. The combined review still returns 503. Do not call it against
the lab database, initialize its tables there or reuse the consumed live fixture.
All ADD/cleanup-worker gates stay off; restoration is not implemented.

It consumes the [frozen fleet scope](managed-removal-review.md#frozen-all-device-scope)
for one IPv4: the exact union of active local observations and enabled managed
targets, including maintained-but-missing devices. Interfaces collapse to one
device/IP. An observed unmanaged target receives cleanup only, never adoption.

In default **ready-only** mode the entire scope must be ready: every device enabled, no QUEUED/RUNNING ADD and
no single-target WAITING_ADD cleanup. A conflict on any target rejects the whole
request without retirement, cancellation or queue changes. A separate explicitly
bound **ordered** mode now supports a whole-scope barrier behind RUNNING ADD;
see [Ordered cleanup](#ordered-cleanup). Do not drop the conflicting target or loop over
single-target admissions/commits to simulate atomicity. The independent
[single-target handoff](managed-removal-handoffs.md) remains available only
within its existing offline integration boundary.

## Admission and durable receipt

Require a canonical UUID, current non-blank Operator/Administrator, complete
reviewed scope with its scope digest and exact fleet action digest. Digests bind
intent, not identity or permission. TTL is strictly 1–900 seconds; reason is
bounded/normalized as in the review. No arbitrary CLI, source, action or route
is accepted.

One `BEGIN IMMEDIATE` transaction performs:

1. Original-key replay/namespace/capacity/recovery-pause checks.
2. Full scope comparison under the same write lock: managed generations/revision,
   protection revision/state, device enablement/hostname and union membership.
   Reject stale scope; never rebase or silently shrink it.
3. Whole-scope conflict checks; retire all enabled desired intents with one
   deterministic separate policy key and one global managed revision increment.
4. Insert retained root authority, then admit **one** ordinary REMOVE request
   for every reviewed device/IP; existing REMOVE may coalesce normally.
5. Append actor-attributed aggregate audit and commit receipt/policy/jobs/links
   together. A late queue/audit failure rolls back all of them.

Observed-only scopes do not change the managed revision or invent policy ledger
entries. All members still receive cleanup. Stopped retained intent is not
re-enabled or unnecessarily re-retired. Accepted logs are emitted only after
commit; reason/full canonical scope are retained in SQLite, not stdout logs.

`admit()` owns its transaction. `apply_admit(db, ...)` is a trusted internal
composition hook: it requires the caller's transaction, uses a savepoint so
caught failures cannot leak partial changes, and returns `(receipt, logs)`.
The caller owns the final commit and must not emit accepted logs before it.
Neither entry point calls a device or creates a second executor.

The receipt contains root operation ID, accepted/replayed, target count, retired
count and resulting managed revision. **Accepted is not verified removal.** It
describes the original admission, not current generation or cleanup outcome.
One root request uses the normal ten-submissions/user/minute accounting, not one
submission per target. Normal 1000 unfinished jobs, 2000 active requests,
coalescing and original bounded deadline remain enforced. Admission time is
captured once; long admission cannot renew it. Expiry during admission fails
closed; queued deadline is never later than the root deadline.

## Execution, cancellation and replay

Materialized REMOVE jobs use the existing queue's sole lease, persisted cooldown,
FIFO/cutoff, fresh snapshots, command/time budgets and verified agent responses.
They do not bypass worker gates or run at admission. Individual device cleanup
may later fail, expire or become uncertain; local admission atomicity does not
promise cross-device rollback or physical exactly-once execution.

Ordinary queue cancellation acts on the one root delegation, preserving any
other users' coalesced REMOVE authority. No failure/cancellation/expiry reverses
desired retirement. A later explicit re-enable requires its own current policy
authorization; there is still no browser re-enable or restoration controller.

Original-key replay, after current role and canonical body checks, precedes
current scope/revision/recovery-pause/ledger-limit checks. It returns the original
receipt without new audit/jobs or retiring another generation, even after queue
history pruning or restart. Scope, lifetime, reason or actor changes under that
key conflict. Do not treat replay as current execution status or automatic retry.

Fleet root/derived retirement keys are reserved across ordinary queue/import,
managed policy and single-target handoff namespaces. After queue pruning the
retained root still prevents new authority. Only an uncommitted ADMITTING root
may delegate its exact REMOVE scope; ADMITTED cannot be reset to rearm cleanup.
An ordered wait may materialize the same root only through its transaction-local
ADMITTING barrier; the immutable root phase is never reset.

## Ordered cleanup

The internal caller must explicitly select `ordered_wait=True` and supply the
matching `stop_maintenance_and_remove_ordered` canonical digest. Ready-only
payloads/old-key replays do not acquire these semantics. No BFF/HTTP/CLI route
selects this mode, and current combined browser confirmation still returns 503.
This is not permission to initialize or seed policy/waits on the live lab.

A RUNNING ADD may be captured by its exact job/device IDs. Admission atomically
retires all enabled desired members and reserves the **entire** frozen scope in
one WAITING_ADD root. No ready member of that root receives early cleanup. An
unstarted QUEUED one-time ADD, disabled device or another waiting single/fleet
cleanup conflicts the whole request; do not silently cancel or omit it.
The offline [system restoration source](managed-restoration.md) is distinct:
its QUEUED ADD can be cancelled atomically by retiring that same enabled intent
before whole-scope removal admission. A late failure restores both; it does not
relax the conflict for independent imports or permit partial fleet writes.

Reservations count one pending slot per reviewed target and one active request
per root, together with existing jobs/single waits under the 1000/2000 bounds.
Even ready/coalescible targets reserve slots conservatively. Intake counts one
submission per actor/minute, including after cancellation. No refund, new grant
or renewed deadline is created by promotion. ADD cannot newly enter a reserved
pair; MAINTAIN is blocked while the fleet waits or needs attention. Retention
preserves captured predecessor jobs while waiting.

`ManagedFleetWaits.advance()` requires the current shared executor lease and is
bounded to 1–16 roots per call. Roots still waiting on a RUNNING ADD are skipped
without starving later settled roots; original expiry may settle a still-running
root without cancelling that command. All captured ADDs must settle first. Then
one transaction validates the original retired generations, device enablement/
hostname, canonical authority and predecessor evidence and admits **one** REMOVE
delegation for all original targets or none. Later observation membership does
not silently widen/shrink the frozen scope. A fresh snapshot is still required
by ordinary execution; absence is not inferred from failed/partial reads.

| Condition | Barrier result |
| --- | --- |
| Any captured predecessor RUNNING | WAITING_ADD; no command cancellation or partial cleanup. |
| All captured ADDs terminal | Materialize the full cleanup under original actor/deadline, preserving ADD outcomes/uncertainty. |
| Exact captured ADD returned to QUEUED with cleared dispatch (known pre-write deferral) | Cancel that same unsent job atomically with full cleanup admission; failure rolls it back. |
| Original deadline elapsed | EXPIRED; release all reserved slots, keep maintenance stopped. |
| Missing/inconsistent evidence, changed generation/device, failed queue admission | ATTENTION; no partial work or automatic retry/rearm. |

Promotion never turns UNVERIFIED ADD into verified creation and never replays
ADD. A lease/audit/database failure rolls back the whole advance transaction;
accepted logs appear only after commit. A late deadline failure rolls back all
materialized targets before EXPIRED settlement. Automated decisions use a system
audit actor linked to the original requester; the ordinary REMOVE delegation
keeps that original captured, short-lived user authority, not new impersonation.

Owner Operator/Administrator or an Administrator may `cancel_waiting()` while
WAITING_ADD; repeated CANCELLED is an audit-free no-op. Cancellation serializes
with promotion: once ADMITTED it conflicts and does not silently cancel ordinary
queue work. The running ADD, original receipt and retirement remain unchanged.
This revocation-only control is now exposed in the authenticated Web view;
see [fleet status and cancellation](managed-controls.md#fleet-cleanup-status-and-cancellation).
It does not expose fleet admission or create a waiting barrier.

The existing default-off `FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED` flag gates
shared-worker promotion of both kinds. Once per cycle, after lease recovery and
before the cutoff/fresh snapshots, process at most eight single-target and eight
fleet roots (sixteen total). All ordinary cooldown/FIFO/budgets remain. Unexpected
advancement errors skip cycle mutations but retain monitoring and sanitized
status diagnostics. No worker/read path initializes optional tables.

## Schema, backup and rollback

Explicit isolated initialization requires the existing registry and queue and
adds `managed_fleet_removals` and `managed_fleet_waits`. Normal Store/API/worker/read paths never call
it or adopt old observations/imports. At most **10000 immutable root keys** are
retained without automatic deletion/recycling; a full ledger rejects atomically.
Original actor, canonical scope/action, receipt, retirement key and requested/
expiry times are immutable. ADMITTING is transaction-local and becomes ADMITTED
before commit. Ordered barrier evidence (target count and exact predecessor IDs)
is immutable/retained, with one barrier per root and monotonic terminal states;
barrier ADMITTING is also transaction-local. Existing ready-only ledgers can be
used without implicit migration; ordered admission needing a barrier refuses
until the explicit offline migration has been reviewed/applied. No new system
restoration queue source is introduced.

No schema is created in the current lab by deploying this code. A future approved
migration needs a checked SQLite-safe backup, paired images and explicit scope
review after initialization (initialization state is bound in reviews). Do not
drop the ledger/tombstones or restore old enabled policy merely to roll back code.
Old writers ignore fleet key reservations; a downgrade requires a separately
reviewed offline plan, not just disabling ADD.

[Offline Recovery](recovery.md) suspends/cancels the ordinary root delegation and
pending jobs plus WAITING_ADD/transitional fleet barriers, retains root receipt/
retirement and suspends desired restoration. Reservations are released, not
rearmed by resume. Orphaned barrier/root evidence fails closed before changes.
Replay remains observational while paused. Orphaned fleet authority without its
registry, or a committed transitional root-ledger phase, refuses recovery for review,
not silent repair/replay. Recovery never initializes optional tables.

## Validation and remaining work

`tests/test_managed_fleet_removals.py` uses disposable SQLite/synthetic queue
state only: atomic retirement/admission, late capacity/audit rollback, outer
transaction ownership, mixed observed/managed scope, disabled/opposite/waiting
conflicts, concurrent same/different keys, immutable authority, namespaces,
retention/replay/new generations, original deadline, queue coalescing/lease/
cutoff and checked offline recovery. No live Cisco write is exercised.

Before connecting confirmation, complete system-source/
generation/claim cancellation, uncertainty handling and reviewed migration/live
fixture validation. No amount of synthetic/default-off deployment evidence
enables those paths or authorizes new FTD mutations.
