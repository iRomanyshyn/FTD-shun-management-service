# Bounded Bulk Refill Controller

Status: implemented internal Synchronizer integration, disabled by default. No
environment setting, API/Web activation, optional migration or lab activation is
included. The legacy lab and existing feature gates are unchanged. This is a
developer contract, not an enablement runbook.

## Admission and execution flow

The existing scheduler publishes a successful complete initial/priority/final
snapshot, then supplies typed evidence to `BulkDiscovery`. The controller scans
current standing policy and delegates exact eligible identities to
[BulkDispatch](bulk-queue-admission.md) in the same SQLite write transaction.
It does not run SSH, add an executor, invent an actor or adopt observed unmanaged
entries. Original standing roots and attempt identities remain authoritative.

Admission checks the exact dispatch profile, unsuspended policy, fresh read/resume
barrier, shared active lease and trusted addition-device set. Retired/protected,
present, disabled, conflicting, pending, failed or uncertain targets are skipped.
The original queue coordinator rechecks source integrity, identities, revisions,
backoff/churn, freshness, namespace and capacity before creating work atomically.
The entire portion rolls back on a late conflict/audit/clock/lease failure. Local
scan hints and counters publish only after a successful admission transaction.

## Bounds and backpressure

- At most 64 policy rows checked and 16 new jobs admitted across the whole cycle,
  including repeated priority/final snapshots and multiple devices.
- A 16-job unfinished-work window per device, counting independent ADD/REMOVE work
  too. A full window reports `window_full`; it does not build a giant backlog.
- Existing shared limits remain 1000 pending jobs, 2000 active requests and 1000000
  retained attempts. Capacity failure reports `capacity` and admits no partial
  portion. No evidence is evicted to make room.
- At most ten explicit trusted device profiles and bounded numerical-IP keyset
  pages; no full effective-registry list is built in Python.

Selection uses a non-authoritative in-memory cursor per eligible device. It
advances past checked rows and wraps at the end; a large present/held prefix cannot
permanently hide later missing targets. Managed/protected revisions and the
resume barrier define its epoch; changes restart scanning. `begin_cycle` resets
budgets, not scan positions. Restart discards the cursor and rescans safely using
retained policy/attempt evidence, rather than renewing or replaying old work.

Device order uses retained last-admission times. Devices without an earlier
admission go first, including after process restart, so a large first device does
not consume every cycle's new-work allowance. This is fairness, not parallelism:
the current global lease still serializes device sessions.

## Scheduler capability and status

`Synchronizer(..., bulk_dispatch_enabled=False)` is an internal constructor
capability. True also requires explicit ADD execution/session cycles and trusted
per-device profiles; it is incompatible with the legacy managed-restoration and
cleanup-worker modes. There is no deployed `.env` mapping in this increment.
Missing/partial/legacy profiles surface a managed-controller error, skip mutations
and retain per-device successful read timestamps; nothing initializes or repairs
the optional schema. An overall errored cycle is not labelled a successful sweep.

Pending-work, queue status and claims consistently use this separate bulk
capability. The legacy restoration flag alone cannot mark bulk ADDs pending or
executable. The existing queue claims and verifies operations with unchanged
cutoff/session budgets/global cooldown. Work discovered after the frozen cutoff
waits for a later eligible cycle; this does **not** yet implement continuous writes
between polls or independent device leases.

The local status payload adds `bulk_discovery`, with enabled state, checked/newly
admitted counts, limits, device window and each device's sampled hold counts/state.
`counts_are_sampled_checks` is true: these are bounded checks, not total desired
targets, unique addresses or verified completion percentages. Status returns a
defensive copy and never reads FTD or admits work. Existing queue progress remains
based on actual linked jobs; a dedicated Web presentation is still pending.

## Unknown results, expiry and restart

Failed/unknown original ADD evidence is never replayed or relabelled. A used
intent/snapshot key is skipped even after cancellation or job pruning. Any
device-level unknown stops new bulk ADD on that device while independent healthy
devices can still receive their bounded portions.

Legacy REMOVE `RECONCILED_ABSENT` only records an observation. It does not prove
that the earlier RPC has stopped, so it also remains a device-level bulk barrier.
On the dispatch profile, automatic retention preserves those jobs and linked
requests. A later read, age, process restart or cursor reset cannot release that
barrier. Automatic evidence-based reconciliation/session-quiescence proof remains
separate work; this controller does not implement it or invoke offline release.

A QUEUED bulk delegation that expires or loses its device before dispatch is
CANCELLED, with original history retained, not classified as a failed Cisco
command. Enabled standing policy may produce a separate new attempt only after
fresh absence, the original backoff and every other eligibility check. Old keys,
deadlines, terminal FAILED/UNVERIFIED latches and generations never change.
Exact typed pre-write deferral and in-flight import cancellation retain the
[existing settlement contract](bulk-captured-cancellation.md).

## Operational impact, rollback and validation

No new schema or live migration is introduced by this controller. The separately
explicit dispatch-profile initialization/backup/activation boundaries still apply.
No service restart or lab data/configuration change was performed. Never activate
this programmatically against non-disposable data as a smoke test.

Retain checked private SQLite-safe backups and matching code/configuration before
eventual activation. Older backend-only code may recognize the same dispatch
schema but lacks the reconciled-device retention/barrier and controller contract:
schema compatibility alone is not safe writer compatibility. Keep bulk capabilities
off and mutations paused for any reviewed downgrade; preserve evidence and use
compatible code or offline checked recovery. Do not prune barriers, restore enabled
policy or reuse consumed lab fixtures to make an older writer run.

```bash
python3 -m pytest -q tests/test_bulk_discovery.py tests/test_bulk_dispatch.py tests/test_managed_discovery.py tests/test_synchronizer.py
```

Disposable tests cover bounded scans/windows, a large present prefix, restart and
device fairness, epoch changes, gates/holds, capacity and late rollback, actual
scheduler creation/restoration, cooldown/cutoff, expiry without false failure,
unknown/lost replies, legacy observational reconciliation/retention and missing-
profile monitoring. The agent is an in-process fake; tests never read `.env`,
credentials or real inventory and never contact lab FTD.

The separate internal [continuous dispatcher](continuous-dispatch.md) now uses
independent device streams and per-device 64-check/16-admission session budgets;
the serial controller described here retains its global-cycle budget/cooldown.
Neither is a new live activation path. Remaining delivery: application/Web
integration, real transport acceptance, automatic quiescence-backed recovery, concurrent standing admission/
version-aware cleanup, nonempty legacy conversion and Web/runtime enablement.
Synthetic tests are not executable 100000-pair load/hardware/production acceptance.
