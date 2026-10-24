# Operation Queue

The explicitly migrated v2 developer profile now also supports
[ordered reservations](bulk-ordered-reservations.md). Waiting roots reserve
whole-scope target/request/rate budgets; shared expiry can revoke them, and both
queue and audit retention preserve captured ADD jobs/requests/claim evidence.
This is default-off internal admission, not ordered dispatch or a lab migration.

The separately migrated [ordered promoter](bulk-ordered-promotion.md) can now
transfer a complete reserved scope to this same queue after all original ADDs and
sessions settle. It uses a distinct literal capability, exact internal ticket,
unchanged original deadline and one-time accounting. Claims reject incomplete
tickets and retention holds original cleanup references. Existing deployed gates
remain unchanged; no ordered HTTP/Web confirmation or lab activation follows.

**Target update (2026-10-20):** [Working-Version Plan](../working-version-plan.md)
requires continuous parallel per-device dispatch, interactive priority and
automatic evidence-based recovery. This manual still describes current queue/
protocol limits and offline uncertainty controls; do not bypass them to emulate
the new target. No gates, schemas or live authorizations change with this plan.

An internal default-disabled [continuous fenced dispatcher](continuous-dispatch.md)
now supports independent sessions/read timing and scoped opt-in REMOVE priority
over this same queue. It is not selected by application startup or Web routes;
the deployed legacy behavior below is unchanged. Already admitted requests still
need their original authority; prioritization is not a new v2 removal-admission
path, uncertainty override or live activation permission.

The separate [v2 ready-removal backend](bulk-ready-removal.md) now supplies an
explicit default-false composition hook for atomic whole-scope retirement and
REMOVE admission on exact fenced storage. Its fixed scope label alone grants
nothing; all retained bulk managed-request keys stay reserved after queue pruning.
Readonly scope inspection and separate [frozen confirmation](ready-removal-confirmation.md)
are available; API/Web ready-removal admission remains independently default-off,
and no implicit RUNNING-ADD waiting is enabled. The ordinary legacy path remains
unchanged and cannot reinterpret v2 policy.

The separate [private ordered API](ordered-removal-api.md) now exposes fixed
device/fleet reservation and local owner/Admin waiting revocation on an explicit
developer composition. Admission needs its own default-false capability and the
already complete promotion profile/capability; no Web consent or live activation
is supplied. Original 202 waiting receipts are not current progress. Read-only
status keeps frozen scope, predecessor outcomes, delegated REMOVE job states and
all-jobs-VERIFIED removal separate, without expiry/promotion or device-read hints.

## Scope

The SQLite queue supports device-scoped and confirmed fleet-wide removals.
It does not execute shun creation/import. A separate default-off
[private admission](import-admission.md) can stage held ADD jobs; the ordinary
worker selects REMOVE only by default and the browser preview cannot submit them.
The separate [execution gate](import-execution.md) permits eligible ADD in the
same FIFO/session with a combined 16-operation budget, not another writer. Submissions
record intentions; only the leased background executor sends device operations.

This transitional lab increment retains separate SSH sessions for `LIST_SHUNS`
and `REMOVE_SHUN`. Each cycle refreshes configured devices and executes at most
one pending device/IP removal per device. One fleet-wide lease serializes all
work, with at least `FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL` after completion
before the next cycle (minimum 60 seconds). Pending work schedules the next
eligible cycle; otherwise the idle baseline remains five minutes by default.

An experimental alternative, `FTD_SHUN_AGENT_CYCLES_ENABLED=true` in **both**
API and agent, supports up to 16 removal jobs in one bounded SSH session per
device cycle, plus safe priority snapshots. Default is false pending live
validation. See the [exact protocol, limits, lab gate, and rollback](agent-cycle-protocol.md).
The fleet-wide cooldown, idempotency, cancellation, and audit rules are unchanged.

## Admission and authorization

- Operator/Administrator permission and CSRF are required for queued manual
  removals/cancellation. Protected IP editing is a separate shared permission
  for all authenticated users; queue ownership/role checks remain unchanged.
  Identity/roles come from Caddy/Authelia through the BFF.
- The API returns `202 Accepted`, a parent `operation_id`, and a replay flag.
  Acceptance is not verified removal. The parent identifies the user's request;
  each device execution has a separate job ID in queue/audit details.
- Forms carry UUID idempotency keys. Retrying the same request returns its
  original reference; a different scope/target under the same key returns
  `409`. A lost admission response must be retried with the same key.
- Concurrent requests for a device/IP share a QUEUED/RUNNING job while retaining
  each actor and request ID. Fleet-wide targets are frozen at admission.
- Manual authorization expires after 15 minutes, or the configured sensitive
  action age if shorter. The worker checks expiry and captured write roles.
  It stores no session credentials and does not query LDAP at execution time;
  live role revocation is not re-evaluated within this short admission window.
- Limits: 1000 pending/running jobs, 2000 active attached requests, and 10 new
  submissions per user per minute. Overflow returns `429` atomically, including
  bulk admission: no partially admitted request is left behind.
- Disabled agent mode rejects new removals. Existing work remains visible and
  cancellable; the deployed Compose profile explicitly selects socket mode.

## Progress and cancellation

**Operation queue** shows only active work: up to 100 QUEUED/RUNNING jobs,
running first and then FIFO. An empty queue says **Queue is empty**, even when
historical results exist. Next eligibility appears only when work is pending.

**Needs attention** separately shows up to 20 latest FAILED/UNVERIFIED results
and their total counts; these are not pending automatic retries.
**Completed operations** is collapsed by default and contains the latest 20
VERIFIED/NOOP/CANCELLED/RECONCILED_ABSENT results. Opening/closing this panel
survives local polling and partial page updates. Old completed cycle progress
is hidden while idle.

All groups include device/IP, outcome, requesters, timestamps/reasons, and an
IP-detail link to retained audit history. Counts cover all retained rows, not
only the visible slice. The independent limits (100 active, 20 attention,
20 completed; at most 140 jobs per status response) keep a large backlog from
hiding results/errors or flooding the page. This is a bounded operational
summary, not a full paginated queue browser.

BFF polling updates it locally without generating CLI queries. Hiding completed
rows does not delete or requeue them: they remain under the configured history
retention (366 days by default), with the same idempotency and no-replay rules.
UNVERIFIED jobs are an exception: age never clears uncertainty. Captured ADD
predecessors of WAITING_ADD, ADMITTING or ATTENTION cleanup are also retained,
including their linked requests/batches. These records may outlive the configured
window; hiding them in the UI is not resolution or deletion.
An explicitly isolated incident also holds every original related job/request,
including a REMOVE later reconciled absent. Missing/invalid isolation references
refuse queue pruning. See [Incident Isolation](incident-isolation.md).
In session mode it also shows the active device/action/IP, completed item
count, priority wait/read state, and budget deferral. An eligible refresh
button can request a priority snapshot while background removals continue;
recent full snapshots satisfy demand without another CLI read. A priority
snapshot updates observed state without claiming the whole cycle is complete.

### Request progress bars

Open **Queue · N** in the compact service toolbar for current execution,
progress, cancellation, attention results and collapsed completed history.
Failure/unverified counts remain visible outside the closed menu. **Status**
holds refresh controls and per-device freshness; stale/error warnings also stay
visible outside it. Menus support keyboard activation, Escape (restoring trigger
focus) and outside-click dismissal. History and Protected IPs have separate
navigation pages. Progress bars have explicit spacing from labels/outcomes.

Active requests show a native progress bar with **processed / total jobs** and
a whole-job percentage. The denominator is the actual jobs linked to that
request, across devices and cycles, not the cycle limit (16) or the number of
historical jobs. Counts come from SQLite, so they survive API restarts. The
panel shows at most 20 active requests and their full total count; coalesced
jobs can contribute to several users' request bars and are still executed once.
Cancelling a request removes its bar even if another user still needs its job.

Processed includes terminal no-op, failed, unverified, cancelled, and
reconciled-absent outcomes as well as verified writes. Each outcome count is
shown separately; failed/unverified outcomes have a warning treatment. A
progress percentage is not a success percentage. A running command has an
indeterminate indicator until its verified result arrives: there is no reliable
within-command percentage or ETA. Snapshot/priority phases remain separate
from job progress and do not advance its bar.

Settled requests leave the active-progress panel; retained outcomes remain in
Needs attention or the collapsed Completed operations view. Unchanged metadata
does not recreate indicators while status polling or page-region updates run.
Progress is rendered generically for queued jobs. Staged ADD rows explicitly
say execution is disabled, do not schedule extra device cycles and can be
cancelled by their owner/Administrator; the product executes removals only.

Operators can cancel their own unstarted manual requests; Administrators can
cancel another user's. Cancelling one of several coalesced requests preserves
the others. A job becomes CANCELLED when no valid unstarted intention remains.
Running jobs cannot be cancelled; claim and cancellation are transactional.
Trusted-policy requests are controlled by policy configuration, not the user
cancellation button.

| State | Meaning |
| --- | --- |
| QUEUED | Awaiting a cycle and fresh complete snapshot. |
| RUNNING | Claimed; no success is implied. |
| VERIFIED | Exact verified-success response received from the existing agent. |
| NOOP | Removal: snapshot confirms absence; ADD hook: already present without creation attribution. No write was sent. |
| FAILED | Pre-dispatch checks failed, such as expiry or a disabled device. |
| UNVERIFIED | Write response/worker was lost or rejected; effect unknown. |
| RECONCILED_ABSENT | Later snapshot confirms absence without attributing it to the uncertain write. |
| CANCELLED | No remaining unstarted intention will execute this job. |

Uncertain commands are never automatically replayed. Review device state and
use a new key for an explicit new request. Persistent trusted-IP policy may
create new work from a later fresh snapshot that still contains a protected
address; that is independent policy enforcement. Future one-time manual
imports must not re-add removed entries.

## Persistence, leases, and history

Initialization adds `operation_requests`, `operation_jobs`, `operation_links`,
and `operation_executor` plus indexes. It preserves existing device/state/event
data and is safe to repeat. There is no new environment setting or agent
protocol for the transitional mode. The separately gated session extension
uses the new binary conversation. The later staged-admission migration adds
job action/dispatch marker, immutable batches and occurrence origins; see its
[migration and rollback procedure](import-admission.md#migration-deployment-and-rollback).
Admission/audit and verified completion/state/audit are atomic.

### Caller-owned admission transactions

`OperationQueue.apply_enqueue(connection, ...)` is an internal composition
primitive, not an HTTP endpoint or new queue source. The caller must hold a
write transaction (use `BEGIN IMMEDIATE`). It executes the same validation,
idempotency, coalescing, limits, request/batch/link/audit writes and revision
update as ordinary `enqueue()`, without committing or emitting logs. It returns
`(result, accepted_log_records)`. Emit those records only after the outer commit;
discard them on rollback. A same-key replay returns no new accepted logs and
does not extend authorization or bump the queue revision.

An internal savepoint rolls back partial admission if a later target, audit or
capacity check fails, even when the caller catches the error. Earlier unrelated
caller work remains intact. When composing policy changes and admission, the
caller must also roll back the **whole composite operation** on failure: either
let the error escape the outer transaction or use an enclosing savepoint for
the entire workflow. Catching only the queue failure and then committing an
earlier policy edit would not be atomic composition.

The public Python `enqueue()` wrapper owns its transaction and logs only after
commit, preserving the existing HTTP/worker behavior. This hook is the tested
prerequisite for future managed retirement plus removal, not its runtime
integration. It neither retires policy nor cancels pending ADD. QUEUED/RUNNING
opposite actions still conflict; no cleanup dependency, second writer, standing
system authorization or uncertainty replay is introduced. A future coordinator
must bind/replay the **entire** reviewed action, cancel unstarted restoration
and retain ordered cleanup after RUNNING ADD before managed writes can ship.

The [offline managed-removal coordinator](managed-removal-handoffs.md) now
implements one reviewed device/IP handoff, but no route or scheduler invokes it.
Its explicit optional schema reserves WAITING_ADD capacity/request/rate slots;
ordinary ADD admission refuses those targets, and retention preserves their
predecessor evidence. Normal startup never creates that schema. All existing
ordinary opposite-action conflicts, dispatch/cutoff and authorization rules
remain in effect. The recovery SQL below suspends existing queue jobs only:
it is **not sufficient for future managed policies/waiting cleanups**. Composite
recovery tooling is a prerequisite to any managed live migration.

There is no schema/configuration/protocol migration for this refactor. Reverting
the code needs no database restore. No deployment is needed to expose a new
feature: no UI/API workflow uses managed transaction composition yet.

Only the exact session-protocol deferred-before-write response can return a
RUNNING item to QUEUED; record `SHUN_OPERATION_DEFERRED`. Any missing/malformed
write response remains UNVERIFIED. Remaining jobs wait for the next eligible
cycle when command, count, or time budgets are exhausted.

The executor renews its SQLite lease before each RPC. Lease duration is the
configured agent timeout plus the minimum interval plus 30 seconds. Keep API
and agent operation timeouts aligned. After a worker loss, another executor
waits for lease expiry and marks abandoned RUNNING jobs UNVERIFIED before
observing device state; it never replays the write. Normal completion persists
the next eligibility across restarts.

Audit uses `SHUN_OPERATION_*`. JSON stdout events include
`queue.request.accepted`, `queue.request.cancelled`, `queue.removal.completed`,
`queue.removal.unverified`, and `queue.executor.recovered`. Join parent request
and job IDs. Experimental pre-write deferral also emits `queue.removal.deferred`;
multiple actor events do not imply multiple CLI writes. Completed
queue records normally follow configured history retention; QUEUED/RUNNING and
UNVERIFIED work is preserved, as are captured predecessors still needed by
WAITING_ADD, ADMITTING or ATTENTION single/fleet cleanup. An existing complete
read can reconcile an uncertain REMOVE as RECONCILED_ABSENT, never VERIFIED;
that settled record follows normal retention unless another evidence hold applies.
Fleet predecessor references are validated before deleting queue records in the
same transaction. Malformed held references abort queue pruning, not silently
release evidence. Audit-event retention remains separately configured; this is
not indefinite retention of every historical event. Older already-pruned evidence
cannot be recovered by this change. There is no automatic incident archive/closure.

## Managed-policy admission guard

New ordinary manual removal cannot bypass enabled managed policy. Device scope
checks that exact pair; fleet scope checks all enabled intents for the IP,
including missing devices outside the observed target list. The queue repeats
the check inside its admission write transaction; a scope string is not an
override. The API checks before observed-only enumeration too, so a missing
managed target is not misreported as an ordinary empty scope. First explicitly
stop maintaining the relevant targets. Combined device-removal confirmation
remains unavailable; its offline coordinator retires policy in the same
transaction before queue admission and still passes this guard.

MAINTAIN refuses a queued/running removal, closing the opposite-order race.
No job/deadline is cancelled or renewed by a failed admission. Existing-key
replay remains observational. Enabled Protected-IP policy may still admit its
own removal without retiring managed intent. Malformed optional policy blocks
ordinary admission, not monitoring/protective removal. These are admission
barriers, **not** a system-restoration source/generation/claim implementation;
those hooks remain required before connecting a managed controller.

The [offline ready-target fleet coordinator](managed-fleet-removals.md) now
retires the whole reviewed enabled-policy scope before admitting one ordinary
REMOVE delegation. Its root/derived policy keys remain reserved after queue
history pruning. Only the uncommitted exact-scope fleet admission may materialize
that queue key; another source/scope or old-key re-admission conflicts. No
HTTP admission is connected. Default ready-only mode rejects unfinished ADD;
separately digested ordered mode may reserve one pending slot per original target
and one active request while captured RUNNING ADDs settle. QUEUED ADD and another
waiting cleanup still conflict. All roots share 1000 pending/2000 active bounds
and actor intake accounting; cancellation does not refund the submission. New
ADD/MAINTAIN cannot bypass a reservation, and retention preserves captured
predecessors. Promotion is atomic for the full scope under the shared lease,
original actor/deadline and ordinary FIFO/cutoff; no partial or automatic ADD
replay is allowed. See the [ordered contract](managed-fleet-removals.md#ordered-cleanup).

## Backup, restore, and rollback

The optional [system restoration source](managed-restoration.md) reuses jobs/
links/lease/cutoff with distinct standing authority, never a renewed manual
request or fake import batch. Runtime claims remain default-held. Retirement/
protection atomically cancel unstarted system ADD; combined offline cleanup may
supersede that system job only, while independent QUEUED imports still conflict.
RUNNING restoration uses the existing ordered barrier. Retained outcomes/
attention/provenance and root/job namespace survive completed queue pruning.
Generic cancellation cannot cancel this source; stop maintenance explicitly.
No startup initialization, controller or live source enablement is included.

Take a SQLite-safe backup before starting the first queue-enabled API. Rebuild
API and Web together, then reload browser tabs once: the write contract is now
`202`, and forms require an idempotency key. The current agent stays compatible.

For restoration stop API/Web and ensure no previous RPC can still execute.
Follow [Offline Recovery](recovery.md): checked backup, atomic suspension of
jobs/delegations/waiting handoffs and desired restoration, durable mutation
pause, fresh monitoring and reviewed ordinary resume. The former queue-only
SQL procedure is insufficient: trusted policy could recreate removals, and
managed waits/policy need suspension too. No automatic replay is authorized.

Initialization adds `operation_executor.mutations_suspended` (default 0).
Preserve the original backup and additive authority tables. Pre-queue backups
need separate reviewed migration. Retain paired API/Web images, but **older
images ignore the new pause, reservations and fleet-key authority**; do not start them against paused,
restored or pending work. Review downgrade offline rather than assuming a code
rollback is safe. Never run old immediate writers beside the new executor.
