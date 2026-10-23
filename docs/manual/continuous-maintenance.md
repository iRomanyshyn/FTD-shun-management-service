# Continuous Runtime Maintenance

Status: internal lifecycle integrated with the default-disabled continuous
dispatcher. A [restricted developer API composition](continuous-api.md) now owns
that lifecycle. No deployed API/env selector, optional migration or lab activation.
See [Continuous Dispatch](continuous-dispatch.md) for scheduling and prerequisites.

## Ownership and scheduling

The continuous dispatcher owns exactly one `ContinuousMaintenance` task. Start
validates the existing fenced device profile/capacity before starting maintenance;
construction, status and disabled start never create optional storage. Enabled
maintenance refuses a missing database. Device workers do not run retention.
The application must select one service lifecycle owner, not run the legacy
synchronizer alongside this controller. This is not a distributed leadership
lease or permission to deploy multiple competing API maintenance owners.

Ordinary request expiry runs at startup and every five seconds after completion.
Queue pruning followed by history pruning runs at startup and every 24 hours
after a complete successful pass. The history period defaults to 366 days and
accepts literal integers 1..3653. Future API wiring must pass the established
`FTD_SHUN_HISTORY_RETENTION_DAYS` value; there is no new environment switch here.
Same-instance orderly restart preserves the daily deadline; a new process has a
fresh startup pass. Scheduling uses monotonic time; retained UTC timestamps and
cutoffs use the existing queue clock, not browser time.

Synchronous SQLite operations run in one bounded-at-a-time worker-thread await,
so a slow housekeeping call does not itself block the event loop or wait for all
FTD sessions. Existing SQLite transactions serialize competing database writes;
this is not a new performance or lock-free guarantee. Busy/failed maintenance
cannot waive a device fence or renew any request. Claim-time expiry checks remain
mandatory independently of the housekeeping cadence.

Calls retain the Store's existing SQLite locking timeout. A complete purge has
data-dependent duration, not a new hard end-to-end timer; do not cancel its thread
and guess whether a transaction committed. Shutdown waits for the real outcome.

## Original authority and retained evidence

Expiry calls the existing `OperationQueue.expire_requests` transaction. It does
not claim jobs, open agent sockets or promote historical requests to standing
policy. Original ordinary unsent jobs retain their current FAILED contract;
unsent version-2 bulk attempts use CANCELLED, never a fabricated CLI failure.
RUNNING work keeps its original authorization/evidence and is not cancelled,
reconciled or replayed merely because its request deadline elapsed.

Retention calls the existing evidence-aware `prune_completed` before history
pruning. Keep QUEUED/RUNNING/UNVERIFIED work, captured cleanup/cancellation
predecessors, required request/link evidence, bulk attempt/receipt ledgers and
the stricter version-2 RECONCILED_ABSENT barrier. Age, acknowledgment or an
abandonment receipt does not resolve uncertainty. Malformed held references
refuse the queue transaction; the history stage is skipped on that failure.
Never invent missing settlement or infer an empty hold from damaged storage.

The history stage follows the existing lifecycle policy: purge expired audit
events, inactive observations and inactive occurrence attribution only. Active
observations are retained. These are two separately committed transactions, not
one atomic archive operation. A later history failure does not roll back an
already successful queue purge. Each existing purge records its actual deletion
counts in an append-only `HISTORY_RETENTION_PURGED` event. Immutable receipts,
attempts, desired authority and latches are not aged out by this task.

## Failure, status and shutdown

Expected SQLite/OS/validation errors retain a bounded structured failure message
and retry the affected maintenance stage after 60 seconds, not in a tight loop.
Expiry and retention have independent schedules/errors. A queue-validation error
never falls through to history deletion. No hidden repair, optional schema
initialization, policy resume, cleanup promotion or unknown-write recovery occurs.
Healthy monitoring may continue; writes retain every independent existing guard.

Detached status reports phase, attempt/success timestamps, next eligibility,
retention period and separate errors. The controller carries this metadata through
its browser projection/BFF allowlist. Maintenance errors appear in the existing
Status warning without hiding actual per-device observations. Clock expiry or an
attempt timestamp is not a successful purge. Unchanged housekeeping does not
increment the browser data revision; actual queue revisions/history deletions do.

Orderly stop prevents the next pass/stage, then awaits any already running SQLite
call. Repeated cancellation of the stop caller cannot free that call or start a
replacement task. If stop starts during queue pruning, finish that transaction
but do not launch history afterward or mark a complete retention success.
Forced internal cancellation drains a shielded call and marks maintenance broken;
unexpected task failure also stops the dispatcher after draining active device
sessions. In-process replacement is refused. Forced event-loop cancellation of
the underlying thread task cannot prove that synchronous work stopped: do not
close the event loop before awaiting normal controller stop.

## Deployment and rollback

No DDL, credential/inventory, gate/profile, Compose, agent/wire or lab state change
is needed for this increment; no live backup/restore or service restart occurred.
This remains preparation for API runtime selection, version-aware admission and
legacy migration, not an activation runbook. Existing separately scoped migration
and live-fixture permissions remain unchanged.

Before eventual approved runtime rollout, take a checked SQLite-safe backup and
preserve matching images/configuration; drain old runtime/maintenance owners
before starting the new one. Retention deletions are irreversible without a
backup. Do not reduce the period on live data without that backup. Rollback must
drain both device RPCs and maintenance before selecting a compatible old runtime;
never erase fences, receipts, uncertainty or retired policy to force compatibility.

## Regression checks

```bash
python3 -m pytest -q tests/test_continuous_maintenance.py tests/test_continuous_dispatch.py tests/test_refresh_bff.py tests/test_operation_queue.py tests/test_bulk_attempts.py tests/test_bulk_waits.py
```

Disposable SQLite/fake-RPC tests cover one owner, expiry/daily timing, idle data
revisions, restart, failure backoff, staged failure, repeated/forced cancellation,
shutdown drain, original ordinary uncertainty, actual bulk captured predecessors,
malformed evidence refusal, independent reads and controller failure visibility.
They do not initialize a lab schema, connect to FTD, resolve uncertainty or prove
large-load/real-device/production acceptance.
