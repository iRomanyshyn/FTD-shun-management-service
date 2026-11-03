# Continuous Device Dispatch and Read Demand

Status: implemented default-disabled lifecycle over the explicit
[fenced profile](device-leases.md) and [parallel session runner](parallel-rounds.md).
The explicit [configured runtime](configured-runtime.md) now selects observation
or managed execution; the current [desk lab](fresh-development.md) uses managed
execution. Its [restricted API composition](continuous-api.md) connects lifecycle/
status/demand to the BFF. No HTTP request selects the runtime or enables authority.

## Independent scheduling

If expensive claim validation crosses a snapshot/delegation deadline before
returning a job, the exact local `ClaimNotSubmitted` rolls back that claim and
ends mutation selection for this session. `queue.claim.not_submitted` is an
operational diagnostic, not an unknown write or successful job. The worker still
requests the real END/final snapshot and strict settlement for earlier operations.
Only normal live-epoch release then makes the next session available. Subsequent
admission requires new fresh evidence and existing authority/backoff checks.
Generic errors, expired leases, failed END and attempted/unknown RPCs retain their
original holds. This prevention path never releases an old ATTENTION lease.

## Execution timing diagnostics

The 2026-11-03 API emits one `device.session.timing` JSON event after each bound
device visit (including failures), correlated by device ID and epoch. Inspect it
with the normal Compose API logs and all current lab overlays. No diagnostic
endpoint, device command, feature switch or schema upgrade is needed.

- `elapsed_seconds`: wall time since binding, including final release processing.
- `local_seconds` / `local_calls`: awaited local work, including thread scheduling,
  database locking, queue validation and result persistence, also on failed calls.
- `local_phases_seconds`: fixed labels for renewal, claims, result persistence,
  snapshot publication/discovery and obsolete-work sweeps; grouped execution
  separately labels `acknowledge_addition`, `finish_verified_group` and
  `fail_pending_group`. Other work is combined under `other`.
- `agent_seconds` / `agent_calls`: agent-call wall time/attempts, excluding their
  local lease-renewal time. Includes IPC, SSH/CLI and semantic verification; it is
  not a per-Cisco-command measurement or proof a call reached the agent.
- `agent_phases_seconds` / `agent_phase_calls`: fixed method-bound `open`,
  `snapshot`, `add`, `remove`, `stage_add`, `verify_adds`, `finish` and `other`
  aggregates. `open` includes SSH
  opening and the first complete snapshot; `finish` includes final observation
  and terminal settlement. This does not separately time pure login or each CLI
  command. Failed/deferred ADD calls are counted too, never treated as verified.
- `settled`: the existing session receipt flag, not success inferred from duration.

Totals need not sum to elapsed time: coordinator work outside these wrappers is
not separately timed. Labels/aggregates reset on every bind and contain no call
arguments, pasted lists, CLI output or credentials. Use real terminal outcomes to
measure verified throughput, not diagnostic call counts. Timing never releases a
fence or resolves uncertainty.

The obsolete-work sweep now performs full profile validation at transaction entry
and exit instead of once per queued candidate. Per-candidate current authority,
time/protection/uncertainty and original binding checks remain. Whole-root claim
verification is unchanged; there is no cross-transaction authority cache. This is
an API-only compatible update: no DDL, migration or data replacement. Drain API
before replacement; retain the prior profile-compatible API image for rollback.
Web/agent, inventory, credentials, protection and admitted import authority need
not change. Compare actual same-workload throughput after deployment; these local
optimizations do not establish 100,000-address device capacity.

Grouped claims also omit an adjacent duplicate executor scan and leave their
extra membership probe's full validation to the existing base audit path. The
original claim transaction retains both executor boundaries, complete profile
validation before audit insertion and all original-root/current eligibility
checks. No cache outlives a query, transaction or session.

### Transaction-local result persistence

The device-scoped queue now passes its resolved attempt within the same owning
claim/result transaction. Persistence re-reads the complete exact row and current
delegation/request/job binding; changed rows fail and roll back. Both full
executor/profile boundaries and base audit validation remain. Global/legacy
paths keep independent resolution; each verified target still commits separately,
before publishing its shared snapshot. No authority/result cache or replay.

Profile SQL avoids a repeated target/request join only inside an existing
transaction after validating the complete member/manifest/request chain. Reads
without a transaction retain that join. Pending job presence remains mandatory
for QUEUED/RUNNING attempts, using the equivalent conditional existence query.
This is not permission to prune UNVERIFIED or captured evidence. No DDL,
gate/configuration/protocol change or new consent is needed. Roll out/roll back
only the API after clean drain; retain Web/agent and current matching batch mode.

Full original-root verification now reuses at most ten common source-JSON framing
templates within each verification call. It still decodes/hashes every literal
member and verifies the same source/manifest/descriptor/receipt and authority.
Unusual shapes retain the original encoder; this is not a root-validation cache
or new format. Existing retained digests and profile-compatible rollback images
remain valid. No migration, initialization or new user consent is needed.

Repeated root decoding now checks assigned UUID canonical text directly instead
of constructing/formatting an object. It accepts exactly the same canonical
lowercase values, not only UUIDv4. Source JSON and binary manifest encoding share
each member's one freshly parsed IPv4 object; no literal, membership or root
verification is omitted or cached. Stored source bytes/digests and independent
operation-ID/descriptor validation are unchanged. This API-only optimization
needs no schema/gate/configuration or agent/Web change. Use a clean API drain
and retain the compatible prior API image for rollback. Query-only root timing
is not successful device execution or large-list acceptance.

## Session scheduling

`ContinuousDispatcher.start` validates exact existing storage, the complete fixed
device scope and declared matching agent capacity before launching work. It never
migrates/initializes optional storage, resumes policy, changes gates or adopts old
imports/history. `stop` drains the already running sessions rather than cancelling
their worker-thread RPCs. Construction and status do not start work. The same
lifecycle now owns one [maintenance task](continuous-maintenance.md) for request
expiry and evidence-aware retention; no device worker starts another purger.

One coordinator tracks at most ten devices and runs at most the sealed concurrency
limit (developer profile default four). There is one active task/session per device,
with actual ownership still enforced by the shared transactional lease quota and
epochs. It reuses the existing semantic collector and queue, not a second job
executor. A slow device occupies its slot but does not block healthy devices from
starting another session in other slots. Ordinary completion does not impose a
global minute-long pause or wait for a fleet round to finish.

Each session still freezes its ADD cutoff before its initial read, checks at most
64 policy rows, admits at most 16 jobs and executes at most 16 mutations under the
existing verification/command/time limits. Per-device unfinished work stays at
most the 16-job refill window; global queue/journal bounds remain transactional.
Newly discovered ADD waits for a subsequent fresh session, which can start as soon
as work is available. Verified outcome is not inferred from scheduling/progress.

After a complete snapshot is reconciled, candidate selection excludes stored
active observations on the same device/IP before its 64-row Python check budget.
These pairs would already fail current eligibility. This avoids an applied prefix
using the whole scan after restart and leaving a large import idle until baseline.
Presence elsewhere cannot exclude this device; stale stored presence can only
exclude work, never authorize an ADD. The normal publisher reconciles confirmed
disappearances before discovery. Fresh snapshot membership and every current
authority/root/protection/backoff/uncertainty check remain, as do cutoff, quotas
and original evidence. Sampled counters no longer count SQL-skipped observations.
No persisted cursor, migration, replay, forced refresh or TTL extension is needed.

Ready devices are ordered by due manual demand, pending REMOVE, due baseline,
then background work. Within the same class a dispatch sequence rotates devices,
even when the clock has not advanced. An active device is never started twice.
Successful device jobs continue between polls; idle devices do not reconnect
because another device has work. Queue checks have a one-second fallback; an
already committed admission/policy change can call `signal_work` to wake promptly.
That hint grants no authority and new work still needs all existing checks.
The hint alone does not poll idle devices. A changed protected-policy revision
or an actual ordinary/desired resume barrier requests a scoped fresh policy check;
those changes are detected from existing control rows, not invented by the hint.

Configured managed confirmation now additionally calls `request_policy_scan` only
after committed, changed, non-replayed authority. It coalesces one advisory
fresh-read boundary per selected eligible device on the owning loop. Unlike a
generic wake, this keeps a device eligible for a fresh scan before baseline,
without bypassing the 60-second read floor or lease/capacity/uncertainty checks.
Due manual refresh and REMOVE stay ahead of it. Old in-flight/equal-boundary reads
cannot consume it; the latest notification includes a one-millisecond SQL timestamp
precision margin. Failed/blocked attempts retain demand, not RPC replay authority.
Per-device `policy_scan_pending` is an advisory flag; it does not count jobs or
claim verified results. Startup's mandatory read covers a lost in-memory hint.
The policy-only/observation API, GET, replay and unchanged confirmations never
request this scan. See [concurrent standing admission](bulk-concurrent-admission.md).

## Baseline, manual refresh and status

Each device has its own last successful complete read, next baseline and pending
manual demand. Default baseline/manual spacing remains 300/60 seconds. Startup
and restart require fresh reads. Timing is monotonic, advisory and in-memory,
not a new durable policy/command authorization or HTTP freshness contract.

`request_refresh` records owning-loop demand for exact enabled configured devices;
`note_activity` is the thread-safe all-enabled-device hint. Repeated clicks join
the original request and cannot postpone its due time. A recent device read leaves
manual demand pending until the minimum spacing, independently of other devices.
Mandatory mutation/session snapshots can satisfy pending demand without redundant
manual reads. A successful read already in flight can satisfy a request received
before it completes; a previously completed read cannot.

When demand becomes due during an active session, it joins the next legal snapshot
checkpoint after the current operation and verification. Existing one-checkpoint/
session limits remain; final reading can satisfy demand, otherwise it stays pending
for another eligible session. Failed/partial output and elapsed timers never mark
demand complete. No RPC is interrupted to service a click.

Detached local status exposes per-device pending/active state, baseline/manual/
retry countdowns, revision and the runner's phases/results. It does not write,
refresh devices, clear attention or promise that zero seconds means success. A
held device can have due demand and a separate retry/attention condition. Web
aggregation/countdown/render support is described below; runtime selection remains
separate.

## Browser projection contract

The 2026-11-02 import-execution usability increment moves blocking per-device
local reconciliation, discovery, queue claim and settlement to awaited worker
threads. Work stays sequential within the same device/session; dispatched local
operations drain before cancellation can return. Snapshot scheduling callbacks
run back on the owning loop. Detached discovery status never acquires the lock
held over an admission transaction. No background thread starts another executor.

Queue display validates the complete existing bulk profile once per consistent
read transaction, not once per displayed job. Private status assembles its heavy
queue snapshot off-loop, then projects controller-owned state on the main loop.
Discovery factors repeated eligibility checks around its validated IMMEDIATE
transaction state; portion admission repeats full validation before commit.
There is no cross-transaction authority cache. Full original-root verification
at admission/claim and all current-authority/protection/freshness checks remain.

`queue.imports` is a bounded read-only whole-import projection (20 cards, recent
finished imports collapsed). It counts original accepted members, retained
attempt outcomes and separately labelled observations. It is not a grant,
execution receipt, cancellation or queue expansion. Internal per-address bulk
delegations are excluded from ordinary request progress, not erased from queue
details/evidence. Owner/Admin cancellation still uses the existing reviewed
CSRF-protected whole-root surface. See [Imports](imports.md).

`refresh_status()` is a read-only projection separate from internal `status()`.
It supplies the established instance/data/status/completion revision envelope with
`refresh_schedule_mode: per_device`, active/pending device counts, per-device
absolute baseline/manual deadlines, original errors/last complete observations and
`device_cycles` for concurrent phases. Internal executor owners/epochs are not
part of this projection. The existing Web/BFF allowlist passes these explicit
fields for authenticated GET and CSRF-protected refresh responses; unknown top-level
fields remain excluded. Actual API startup still constructs the legacy runtime.

The aggregate confirmation timestamp is the oldest enabled device's complete read
only when all enabled devices have one. Never display the newest healthy device
as evidence for an unread/failed device. Old observations remain visible with
stale/error labels. A held lease exposes a warning and unfulfilled demand, not a
successful read/retry. Disabled inventory remains visible but is excluded from
aggregate deadlines/demand. No arbitrary parallel session becomes a fleet cycle.

Absolute deadlines are advisory wall-clock projections from monotonic scheduling,
including server-time offset for the browser. Reaching zero does not publish a
new data revision, clear demand or report success. Browser content replacement
follows real read/result revisions, independently for healthy devices, retaining
dirty fields, focus and open menus as before. Counters are not verification counts.

In this mode the request button accepts/coalesces another request while devices
are active, rate-limited or held; it is disabled only while its HTTP submission is
in flight or the controller is unavailable. It shows the number waiting and the
earliest manual eligibility, then waits for verification. Per-device details and
the Status indicator retain pending/attention state even while panels are closed.
Legacy mode keeps its existing single-cycle button behavior. No browser click
bypasses spacing, serialization, verification or authority checks.

`request_activity()` is owning-event-loop demand plus this projection; it refuses
a stopped/finished coordinator. `note_state_change()` advances the data/status
envelope for already committed API changes, marshaling worker-thread notifications
onto the owning loop, without reading/admitting/waking device work. Generic status
and construction never initialize optional storage. Disabled projection does not
open SQLite; enabled projection refuses a missing database without creating one.

There is no HTTP runtime selector or live activation procedure. The explicit
developer API composition retains one lifecycle/maintenance owner and refuses
unsupported legacy managed/admission routes. It does not enable ADD/bulk imports
or switch an existing lab database merely to exercise this display.

## Quick unblock and protection

Only this explicit scoped queue opts into REMOVE priority. Already admitted live
REMOVE jobs use FIFO before ADD and may join after the session's ADD cutoff. Every
claim still checks authorization, expiry/cancellation, current pause/device state,
isolation, source and exact executor fence. Priority is not admission authority,
permission to skip policy retirement or an override of conflicting user intentions.
Legacy/global/default scoped claims retain their old FIFO/cutoff behavior.

Priority REMOVE always goes through the agent's current target verification. Never
declare NOOP merely because the session's initial snapshot lacked an IP: a prior
ADD or an external command may have made it present since then. The agent still
returns the exact verified result or no-op; failed/unknown response stays uncertain.

Protection enabled during a running ADD permanently retires the matching managed
authority using the existing atomic policy path. The running ADD settles normally.
After a successful result the worker rechecks protection and admits matching
automatic removal through the original trusted-policy path for the next slot.
Complete final snapshots also admit matching protected removal, so other newly
seen protected IPs do not wait for the next baseline. Stop prevents new admission.
Disabled/deleted protection never resurrects retired managed policy.

Version-2 user-facing ordinary/combined removal admission is still separate work.
Tests with pre-admitted ordinary requests do not create a live v2 Web workflow or
authorize lab seeding. No removal is admitted merely by choosing its priority.

## Failure, backoff and shutdown

The 2026-11-02 [settled read-only failure extension](read-failure-recovery.md)
adds a separate exact terminal proof for failed initial/priority/final reads with
zero mutation steps/claims. Its `agent_read_failed` retry uses the same capped
backoff and fresh-epoch requirements below. It does not recover missing proof,
old held leases or unknown ADD/REMOVE; opening status `03` stays opening-only.

Exact pre-write deferral, failed rounds and lease contention use a five-second
rescheduling delay to avoid a hot loop. A normally exhausted 16-mutation batch is
not such an error and continues without that artificial delay. Submitted RPC failure
retains the device lease; expiry records immutable ATTENTION/UNVERIFIED through the
existing path. Retrying lease acquisition is not reconnect/replay authority. Healthy
devices continue while held work/demand remains visible. No uncertainty latch,
original receipt or requested deadline is reset to make progress.

The first automatic exception is a **local failure before the first BEGIN send**.
`UnixAgentCycle` raises `AgentCycleNotStarted` only for socket creation/setup/connect
OS errors before submission, after closing its local descriptor. The worker accepts
it only from the first `open_cycle` invocation in its current lease. The exact live
owner/epoch and absence of unsettled jobs/attempts or any mutation claim in that
epoch are rechecked transactionally. `DEVICE_LEASE_NOT_SUBMITTED` and normal release
are audited together; no job/policy outcome or complete observation changes.

The device result becomes `retrying`, with error category `agent_not_submitted`.
Status retains old observations as stale/error, pending manual/policy scan demand,
`retry_in_seconds` and `connection_retry_attempts`. Automatic delays are 5, 10, 20,
40, then at most 60 seconds; clicks/wakes do not bypass them. A successful next
session resets the streak and starts with a new fenced initial read, not a replay.
Retries remain eligible even when the original work was an advisory control hint.
Healthy devices retain their independent slots/timers. Backoff is advisory local
state: process restart resets it and starts the ordinary mandatory initial read.

An attempted send (including a short/failed send), generic rejection, timeout,
malformed/missing response, later typed exception or lost fence is **not** this
proof. The separate [opening-recovery extension](opening-recovery.md) now permits
one additional case: exact terminal `03 version 17 00` proof after a failed SSH
opening, before a Cisco command executor existed and after agent guard/slot
release. Configured continuous clients explicitly select this mode. The first
opening call alone can use audited `DEVICE_LEASE_OPEN_FAILED` release, with the
same no-claim/no-uncertainty checks and capped retry. No old LEASED/ATTENTION,
snapshot/command failure or unknown ADD/REMOVE is released. Missing proof remains
held; this is not full submitted-session/unknown-write recovery.

Ordinary stop prevents new sessions, mutations and discovery, then awaits current
RPC/verification and required session completion. Repeated cancellation of the
stop caller cannot free a still-running RPC slot; cancellation is rethrown after
drain. Close the event loop only after awaiting stop. A client that ignores its
declared RPC bound can prevent draining; Python cancellation cannot kill its thread.
Forced internal cancellation marks the coordinator broken and refuses restart/
replacement execution. A bad profile/scope fails closed and surfaces an error.

Continuous dispatch now requires the explicit [local settlement capability and
receipt](cycle-settlement.md) before final publication/normal lease release. It
does not resolve remote quiescence or old unknown attempts. END reception alone
still proves no guard/slot release, and busy rejection is not safe retry authority.
Matching real transport acceptance remains required before rollout; unknown/read-
only lease holds are not waived as a workaround.

## Deployment, rollback and remaining integration

Use [Fresh Working-Version Lab](fresh-development.md) for the current three-file
Compose selection and existing v2 store. First-scan/pre-submission retry update only API
code: no DDL, new selector/route, agent/wire, credential, trust or network change.
The later opening-recovery extension needs matching API/agent code and explicit
new BEGIN binding; follow its [rollout order](opening-recovery.md#deployment-and-rollback).
Drain the single API owner before replacement; an API restart can execute already
authorized work. Keep a matching image for code-only rollback. Startup performs
the normal fresh read; do not initialize/convert/reset retained storage.

Rollback loses prompt scans/local-connect retry, not standing authority or receipts.
Older images retain a lease on the next such connection failure; preserve the new
image if automatic retry is needed. Existing audit event types are compatible;
no schema migration or DB restore is needed. Never drop fences, clear unknown
outcomes, reset epochs or restore an older authority snapshot to force progress.
Keep one maintenance owner and do not also start the legacy synchronizer. Existing
request expiry, evidence-aware retention, claim-time checks and shutdown drain
remain; see [maintenance](continuous-maintenance.md).

Current lab evidence covers one profiled FPR1010 v3 creation/restoration/cleanup
lifecycle, not arbitrary hardware or production. Automatic evidence-based recovery,
Emergency Purge and multi-device/large-load/data-plane acceptance remain separate.
Legacy-dev conversion is optional, not a prerequisite for a fresh lab profile.

## Validation

```bash
python3 -m pytest -q tests/test_unsubmitted_recovery.py tests/test_continuous_dispatch.py tests/test_parallel_synchronizer.py tests/test_device_leases.py tests/test_bulk_discovery.py tests/test_import_execution.py tests/test_synchronizer.py
```

Disposable SQLite/fake-RPC tests cover continuous multi-session imports with no
clock advance, slow/healthy devices, idle isolation, independent/coalesced timers,
in-flight reads/checkpoints, late REMOVE and stale snapshot absence, protection
during ADD, original typed outcomes, role/expiry/cancellation/FIFO guards, pause,
short exact-deferral backoff, lost results, restart, detached status and orderly/
forced shutdown. No Docker, credentials, real inventory, SSH or FTD is accessed.
These tests do not establish executable 100000-pair throughput, transport cleanup,
Web refresh behavior, multi-FTD or production acceptance.
