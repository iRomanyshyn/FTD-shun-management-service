# Continuous Device Dispatch and Read Demand

Status: implemented internal, default-disabled lifecycle over the explicit
[fenced profile](device-leases.md) and [parallel session runner](parallel-rounds.md).
Not selected by deployed startup or environment configuration. An explicit
[restricted developer API composition](continuous-api.md) now connects its
lifecycle/status/demand to the BFF; no HTTP request selects the runtime. The
deployed lab still uses its existing serial scheduler.

## Independent scheduling

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

Exact pre-write deferral, failed rounds and lease contention use a five-second
rescheduling delay to avoid a hot loop. A normally exhausted 16-mutation batch is
not such an error and continues without that artificial delay. Genuine RPC failure
retains the device lease; expiry records immutable ATTENTION/UNVERIFIED through the
existing path. Retrying lease acquisition is not reconnect/replay authority. Healthy
devices continue while held work/demand remains visible. No uncertainty latch,
original receipt or requested deadline is reset to make progress.

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

No new DDL, environment/feature gate, API/Web route, service image/restart, lab
inventory/credential or FTD operation accompanies this code. There is no activation
runbook for real devices. Do not directly construct an enabled controller against
the lab as a smoke test. Existing admission/restoration/migration permissions and
consumed one-address fixtures remain unchanged.

Eventual rollout requires separately reviewed schema/legacy-state compatibility,
drained old writers, matching agent pool/settlement, a checked SQLite-safe backup
and matching code/configuration. Never drop fences, clear attention/uncertainty,
reset epochs or restore enabled authority to force a downgrade. No live backup/
restore was needed for this increment. The controller now starts/stops one
maintenance owner for ordinary request expiry and evidence-aware queue/history
pruning, separately from device RPCs. Claim-time expiry checks remain mandatory.
API runtime selection must preserve that owner and must not also start the legacy
synchronizer. See [timing, failures and shutdown](continuous-maintenance.md).

Remaining: real transport acceptance and automatic evidence-based uncertainty recovery,
concurrent standing/combined cleanup admission, configured runtime/inventory
selection, nonempty legacy migration and scoped measured FTD acceptance. Explicit
restricted API/BFF composition is implemented but not selected by deployed startup.

## Validation

```bash
python3 -m pytest -q tests/test_continuous_dispatch.py tests/test_parallel_synchronizer.py tests/test_device_leases.py tests/test_bulk_discovery.py tests/test_import_execution.py tests/test_synchronizer.py
```

Disposable SQLite/fake-RPC tests cover continuous multi-session imports with no
clock advance, slow/healthy devices, idle isolation, independent/coalesced timers,
in-flight reads/checkpoints, late REMOVE and stale snapshot absence, protection
during ADD, original typed outcomes, role/expiry/cancellation/FIFO guards, pause,
short exact-deferral backoff, lost results, restart, detached status and orderly/
forced shutdown. No Docker, credentials, real inventory, SSH or FTD is accessed.
These tests do not establish executable 100000-pair throughput, transport cleanup,
Web refresh behavior, multi-FTD or production acceptance.
