# Version-2 Ready-Scope Removal

A separate [ordered preflight](bulk-ordered-preflight.md) can inspect exact
RUNNING-ADD predecessors locally. It does not admit waiting work or change any
ready-only scope/action/receipt or confirmation behavior described here.

Status: backend coordination, readonly inspection and a separately
[gated Web/API confirmation](ready-removal-confirmation.md).
The coordinator and API/Web admission are independently default-disabled.
There is no environment selector, new schema or live activation. This is
not a laboratory enablement runbook. See [Continuous API](continuous-api.md),
[Policy Views](bulk-policy-views.md) and the
[working-version target](../working-version-plan.md).

## Inspect the exact scope

The explicit continuous API composition supports:

```text
GET /api/v2/managed-removal-scope/198.51.100.1
GET /api/v2/managed-removal-scope/198.51.100.1?device_id=1
```

Without `device_id`, the scope is the entire union of active local observations
and enabled managed policy for that one IPv4. Missing-but-maintained and disabled
devices stay included; several observed interfaces on one FTD are one target.
Unmanaged observations are cleanup-only, not adopted. Stopped-and-missing targets
do not expand the fleet; an explicitly selected single retained target can still
be inspected. An out-of-executor-scope device is not silently dropped.

The readonly SQLite snapshot binds literal v2 format, device/fleet mode, IP,
global managed/protection revisions, protection state and at most ten sorted
targets. Each target includes hostname/enabled state, observed presence,
maintenance state, original intent/generation/authorization and target revision.
Observation timestamps/additional interfaces do not alter device-level scope.
Missing/corrupt optional state is 503, empty/over-ten scope 409, invalid selector
422. The existing private UDS/no-store boundary remains; no agent RPC occurs.

`scope_digest` binds this metadata, not fresh Cisco state or device authority.
`read_only=true`, `execution_available=false` and
`device_work_admitted=false` are explicit. The pure `canonical_removal` action
additionally binds `STOP_AND_REMOVE_READY`, delegation lifetime 1..900 seconds
and at most 500 plain-text reason characters. Its digest is not interchangeable
with the scope digest or any legacy/policy-only/import action. Internal callers
pass only the exact canonical scope fields, not the inspection envelope's
observational flags. The separate frozen v2 Web confirmation consumes this action
digest only when its local and API factory capabilities both permit submission.

## Atomic backend contract

`BulkRemovals.admit` and its caller-owned `apply_admit` hook require an explicit
literal `enabled=True` supplied by trusted composition code, never form/status
data. Default-off calls do not access/create storage. Admission requires existing
exact fenced v2 storage, real Operator/Administrator identity, a canonical UUID,
exact action digest, ordinary mutations unpaused and the whole reviewed scope
unchanged under one SQLite write lock.

Every selected device must be enabled and inside the sealed executor profile.
ATTENTION/expired device leases, same-pair pending ADD or REMOVE, retained failed/
unknown ADD and device-level unknown outcomes block the entire action. Later
observed absence (`RECONCILED_ABSENT`) is not proof the prior RPC settled. There
is no coalescing, cancellation, blind retry or automatic conversion to ordered
RUNNING-ADD waiting. A nonexpired active worker on another pair may finish its
current operation; the same per-device stream remains serialized.

The transaction then:

1. Permanently retires all enabled maintained targets in the exact scope, while
   preserving their intent/generation/original author and attempt evidence.
2. Admits **one whole-scope manual REMOVE request** using the existing shared
   queue with one job per device. It never loops through single-device admission
   to simulate atomic fleet behavior or turns unmanaged observations into policy.
3. Retains one immutable action/receipt in the existing managed request ledger
   and appends actual-actor retirement/admission audit. It uses the existing
   reserved retirement budget, not a new receipt slot for every target.

The queue composition uses a separate literal default-false ready-removal
capability and fixed semantic scope. A scope string alone cannot bypass legacy
policy checks. Existing roles, isolation, pause, request-rate, active-request and
1000-pending-job capacity checks remain. Queue TTL is pinned to the original
admission deadline; internal clock samples cannot slide it forward. Clock reversal,
expiry, late lease loss, capacity or final audit failure rolls back **policy,
request, jobs, links, receipt and audit together**, even if an outer caller catches
the error and commits. Accepted logs are emitted only after the owning commit.

## Execution, retry and uncertainty

An accepted receipt is **not verified removal**: it explicitly reports
`device_work_admitted=true`, `verified_removal=false`, the original job IDs,
retired count, revision and deadline. The existing continuous dispatcher discovers
the jobs without waiting for baseline polling. Its existing REMOVE priority,
per-device lease/cutoff, typed results, session settlement, retention and visible
uncertainty remain authoritative; no second executor or arbitrary Cisco command
is introduced. The individual FTD writes are not a distributed transaction:
one device may fail after another succeeds. All original admission scope and
outcomes remain retained, not silently rolled back or reported all-successful.

Exact original-key/actor/action retries return the immutable original admission
receipt only, including after terminal queue pruning. They never reconstruct jobs,
renew TTL, retire a newer grant, clear an unknown result or change history. All
retained bulk managed-request keys are reserved against acquiring new ordinary
queue work. Missing pruned job evidence is not a pending job or verified success.
Original queue outcomes remain independently inspectable through existing status.

Current bulk standing confirmation requires quiescence and cannot create new
authority while these removals are pending. Future concurrent admission must
preserve that exclusion. Failed/unknown/expired removal never resumes retired
maintenance. Protection remains independent and disabling protection never
restores old support. Policy-only stop-maintaining remains separately available
when ready removal is blocked.

## Rollout and rollback

No DDL/migration, optional initialization, gates/profile, lab database/secret,
Compose/network or image/service changed. Legacy behavior is unchanged except
stronger v2 key-reservation safety; its runtime refuses the new scope GET. The
continuous profile refuses removal admission POSTs by default; the new separate
factory capability does not enable ADD/import work or legacy cleanup.

Before any future separately approved runtime/data rollout, retain checked
SQLite-safe backups and matching images/configuration; drain previous owners and
validate migration, actual transport/devices and remaining write controls. Do not
drop fences/evidence or restore enabled policy to force a downgrade. Code rollback
must preserve recorded retirement and queued/uncertain obligations. General
concurrent grant/import intake, captured RUNNING-ADD ordering, automatic evidence-based recovery,
nonempty legacy migration, multi-FTD/load acceptance and Purge remain separate work.

## Validation

```bash
python3 -m pytest -q tests/test_bulk_removals.py tests/test_bulk_dispatch.py tests/test_bulk_attempts.py tests/test_continuous_api.py tests/test_operation_queue.py tests/test_managed_shuns.py
```

Tests use disposable SQLite/ASGI, actual shared queue claims/results and semantic
fake agent sessions. They cover exact fleet union, strict action digests, no-init/
default-off reads/admission, roles/protection/revision conflicts, late whole-scope
rollback, original-key races/pruning, owned ADD predecessor refusal, unknown REMOVE
non-replay, readonly API and actual continuous priority dispatch. No live inventory,
credentials, SSH/FTD mutation, lab migration or production acceptance is implied.
