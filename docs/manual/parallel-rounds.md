# Parallel Device Rounds

Status: internal, default-disabled coordinator over explicitly existing fenced
storage. Implemented and tested with disposable SQLite and fake semantic RPCs.
Not connected to API startup, environment configuration, Web refresh or the lab.

## What executes

`ParallelSynchronizer.sweep` now runs actual device-bound sessions, not just lease
primitives. Each device has an isolated Synchronizer context with its own cycle,
errors, snapshot timestamps, discovery cursor and budget. It reuses the existing
typed initial read, shared queue claim, ADD/REMOVE verification/result journal,
exact deferral, protected removal and final read. There is no second job executor,
arbitrary command channel or temporary global lease projection.

The immutable profile supplies 1–10 devices and the simultaneous-session limit
(developer initialization default four). An explicit agent capacity must cover
that limit. Enabled inventory devices outside the frozen scope, missing members,
out-of-scope ADD profiles and insufficient capacity refuse the whole round before
any lease/RPC. Disabled members are skipped, not removed from retained scope.
Use the actual matching agent configuration: the coordinator's capacity argument
is a trusted deployment assertion, not automatic agent negotiation.

At most ten small tasks wait locally, and a semaphore bounds active sessions to
the profile limit. A slow device occupies its slot until its full session ends;
healthy devices progress in other slots. Distinct coordinators still compete
through the same transactional lease quota/device fences. An already active
round cannot be entered again on the same coordinator.

Optional `settled_cycles_required=True` now requires the explicit
[strict client/terminal receipt](cycle-settlement.md) before final publication and
normal lease release. Default rounds remain legacy; ContinuousDispatcher requires
strict mode. Missing proof retains the fence and earlier typed results.

Each device freezes its queue cutoff after acquiring its token, before its initial
read. Jobs admitted by discovery wait for a later round. Per-device refill checks
at most 64 policy rows and admits at most 16 jobs across that session's complete
reads, with the existing 16-unfinished-job device window. Therefore a ten-device
round can check at most 640 rows/admit 160 jobs in total; global queue/journal
capacity still applies transactionally. This replaces the serial collector's
one-global-cycle discovery budget only in this explicit coordinator. Retained
last-admission ordering provides fairness. Cursors are hints, never authority.

Ordinary successful rounds release their individual leases without modifying or
waiting for the legacy global read cooldown. The same collector retains the
agent's 16-mutation/session and verification/time limits. No interval, protocol,
agent gate, capacity bound or current-policy/uncertainty check is relaxed.

## Cancellation and failures

Cancelling the public sweep await requests orderly stop. It prevents waiting
devices from starting and stops active devices before their next mutation. An
already running RPC, operation/verification and session completion are awaited;
their slots and leases are not freed merely because the caller cancelled. Repeated
cancellation joins that same drain. Successful current results keep their original
typed outcomes, unsent work remains queued, and no discovery/policy admission is
performed after stop is observed. The sweep then raises `CancelledError`.

The RPC timeout must fit the explicitly configured 5–240-second operation bound;
leases use that bound plus 30 seconds, independently of interactive read spacing.
The typed client must actually enforce its deadline. Cancellation is not a thread
kill or proof that SSH stopped. Callers must await orderly shutdown before closing
the event loop; an adapter that ignores its bound can prevent draining.

A failed RPC, including an initial/final read, retains its lease rather than
immediately reconnecting. Expiry uses the existing device-only UNVERIFIED/immutable
ATTENTION path; it never permits stealing or replay. Later snapshot failure cannot
undo an earlier verified ADD. Lost/late ADD replies preserve original uncertainty;
other devices keep their independent results. Unexpected worker failures retain
the acquired fence. Forced internal/event-loop task cancellation marks the local
coordinator broken and refuses replacement rounds; it is not orderly shutdown or
remote-quiescence evidence. No automatic recovery/rearm is implemented here.

Status returns detached, local per-device phase/results and sampled discovery
budgets. It is read-only and does not recover leases or claim browser freshness.

## Integration still required

The round coordinator has no `start`/environment/API/Web selection. A separate
internal [ContinuousDispatcher](continuous-dispatch.md) now owns explicit start/
stop, independent baseline/manual demand, continuous between-poll sessions and
scoped REMOVE priority using the same runner. Neither is wired to application
startup; the deployed serial service is unchanged. Web progress aggregation,
Local slot settlement now has an explicit protocol; real transport acceptance,
application integration and automatic uncertainty convergence remain pending.
Retention belongs to the eventual
owning service lifecycle; individual parallel workers do not run competing pruners.
Do not activate this component on a real FTD by directly calling `sweep` as a smoke
test. END reception alone still does not prove guard release: only the separate
strict receipt attests local ordering. Real immediate-reconnect acceptance still
needs validation. Generic busy rejection is never retry authority.

## Migration, rollback and validation

No new DDL, migration, activation procedure or lab writes accompany this change.
An eventual rollout must stop/drain old writers, obtain separately scoped approval
for the [fenced profile](device-leases.md), preserve a checked SQLite-safe backup
and matching code/configuration, and validate the matching agent pool. Do not drop
fences/ATTENTION, reset epochs, erase old uncertainty or restore enabled authority
to downgrade. No live backup/restore or service restart was needed in this increment.

```bash
python3 -m pytest -q tests/test_parallel_synchronizer.py tests/test_device_leases.py tests/test_bulk_discovery.py
```

Tests run the actual shared semantic collector on disposable journals with blocking
fake RPC threads: real bounded overlap, healthy-device progress, exact scope and
capacity refusal, repeated cancellation/open/ADD drain, typed results and original
authority, protected removal, exact deferral, late lease expiry, lost ADD/final
read and forced shutdown holds. No SSH, FTD credentials, real inventory, Docker or
live gate is used. These are runtime-coordination regressions, not FTD capacity,
simultaneous-device, end-to-end Web or production acceptance.
