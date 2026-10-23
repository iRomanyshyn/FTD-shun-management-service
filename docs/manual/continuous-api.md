# Restricted Continuous API Composition

Status: explicit developer factory integration, not environment-selectable or
deployed. The ordinary application/CLI still defaults to the legacy synchronizer.
No lab migration, runtime/profile activation, credentials or FTD fixture follows
from this implementation. See [Continuous Dispatch](continuous-dispatch.md) and
[Maintenance](continuous-maintenance.md) for the underlying lifecycle.

## Scope and factory boundary

The trusted Python `create_app` factory accepts an explicit `continuous_dispatcher`
dependency. No URL/header/body field, environment variable or Compose override
selects it. An explicitly supplied dispatcher must be the exact supported class,
enabled but inactive/unbroken, share the same Store object/path and supplied agent,
and match API read intervals, IPC timeout margin and retention. No running task
can be adopted; one dispatcher binds to one application for its lifetime. Reusing
that application's orderly lifespan is supported, not binding a second owner.

This first integration is deliberately a **continuous observation/Protected-IP
profile**, not the working-version bulk-write release. It requires socket mode,
session cycles, large reads, strict settlement and declared matching agent
capacity. API ADD/import/standing/legacy combined-removal admission and legacy managed
controllers must all be off; the dispatcher must have bulk execution off and an
empty ADD device scope. Development authentication is refused. A real Unix client
must also match the configured socket/timeout, have large/settled reads and ADD
disabled with an explicit empty scope. Synthetic injected agents are test fixtures,
not a deployed mock mode or evidence of SSH/FTD acceptance.

Inventory is already loaded into the existing sealed database profile; the factory
requires `device_inventory_path=None` rather than silently ignoring/upserting a
configured file. API-side reload/address reconciliation for this profile remains
future work. Per-device secrets/SSH identity remain exclusively agent-owned.

## Storage compatibility and startup

The factory validates existing exact v2/device storage and its enabled scope;
it does not call Store/queue initialization, migrate optional state, backfill
occurrences, resume policy or import legacy environment protection. The durable
Protected-IP legacy-import marker must already be complete, otherwise startup
refuses. Tests set that marker only on their disposable fixtures; there is no
live initialization shortcut or migration command in this increment.

Preflight runs during factory composition and again before lifespan start. Schema,
scope/capacity, deadlines or gates drifting between those points must refuse
before device/maintenance tasks start. A partial profile never becomes a legacy
fallback. Default legacy factory creation now explicitly refuses any device-fence
objects before base initialization, including partial device-profile storage.
Older non-fenced legacy/read-only protection behavior remains unchanged.

Protected policy access and fenced device workers use an explicit no-queue-init
constructor path. Legacy constructors retain their existing initialization default.
Construction/status remain read-only; startup alone starts one continuous
dispatcher and its one maintenance owner. Shutdown drains both; no serial
synchronizer is constructed/started for this composition.

## Supported private API surface

| Operation group | Current support |
| --- | --- |
| Status and refresh demand | Existing GET status and POST refresh-hint, per-device revision/countdown contract. |
| Observations and history | Shun list/detail, history/page/detail and IP search. |
| Protected IPs | Existing exact-IP list/CRUD, real BFF actor, revision/typed-delete checks and atomic permanent managed retirement. |
| Import preview | Existing local non-executable classification and device list; no durable import admission. |
| Managed policy v2 | Separate `/api/v2/managed-shuns/page` and `/selection`, bounded to 100 rows/pairs, with exact version and revision. |
| Policy-only v2 retirement | Separate `/api/v2/managed-shuns/retire`, one frozen exact pair; real-actor audit/original-key receipt, no queue/device command. |
| Ready-removal scope inspection | `GET /api/v2/managed-removal-scope/{ip}`, optional exact `device_id`; readonly snapshot, no admission. |
| Ready-only v2 removal admission | Distinct `/api/v2/managed-removals/device` and `/fleet`, independently default-off factory capability; strict frozen scope and 202 admission receipt. |
| Other managed/import/manual mutation workflows | Explicit 503 before handler dispatch, including all v1 managed reads/retirement, ordinary manual ADD/REMOVE, cancellation and legacy combined cleanup. |

The private API middleware admits only these exact method/path families in this
profile. Unknown/unsupported operations cannot fall into legacy handler assumptions.
Their response says no request was admitted; it does not claim a successful device
operation. Supported operations encountering unavailable retained state return an
honest 503: a later response failure is not proof an already committed policy edit
rolled back. GET or timed-out demand never creates policy/jobs or proves freshness.

Status reports `runtime_mode=continuous-observation`, `managed_policy_format=2`,
`manual_mutations_available=false` and `managed_workflows_available=false`.
Initialized v2 storage is not misreported as a missing legacy registry. Corrupt
state is unavailable, not empty. Separate `managed_policy_view_available=true`
and `managed_policy_retirement_available=true` advertise the narrower local
capabilities; they do not enable general managed workflows or device admission.
Existing admission gates remain false. See
[Version-2 Policy Views](bulk-policy-views.md) for frozen reviews and evidence.

The name observation profile does **not** disable previously admitted REMOVE or
Protected-IP automatic removal: the dispatcher still uses the existing semantic
queue/verification path and all authority/fence checks. Adding/enabling protection
may permanently retire matching standing policy and remove an observed shun on
the next eligible device slot. It never enables ADD/restoration. Disabling or
deleting protection does not restore the old standing grant. No HTTP policy resume,
uncertainty resolution or arbitrary CLI is added.

## Web/BFF behavior

The existing authenticated/no-store BFF passes explicit capability and v2 metadata
fields. In this profile the normal Shuns/detail/history/Protected IP pages and
refresh control work. Navigation points to non-executable preview rather than
managed imports. Managed navigation now opens the dedicated v2 page, including
local stop-maintaining; unsupported import review, manual removal and
queue-cancellation controls are hidden. Status explicitly explains the restriction
and the still-active Protected-IP behavior. Direct unsupported requests remain
refused by the API; hiding controls is not the enforcement boundary.

Legacy pages retain their existing controls when capability fields are absent or
null; only explicit false restricts them. Existing authentication, real-actor audit,
CSRF, form revisions, typed deletion, frozen reviews and data-revision updates stay
in force. Runtime selection/capabilities cannot be changed by browser requests.

## Rollout, rollback and remaining work

No images/services, `.env`, Compose/network, secrets, lab database or device changed.
This is not an activation runbook, production acceptance or authority to initialize
a profile in the lab. Before any separately approved rollout, preserve checked
SQLite-safe backups and matching images/configuration, drain old owners and review
nonempty legacy migration plus actual transport/FTD behavior. No new DDL is needed
for this code. A fenced profile cannot simply be downgraded to the old global
executor: never drop fences, erase uncertainty/receipts or restore enabled policy
to force compatibility. Drain through the application's normal lifespan first.

Remaining product work includes concurrent v2 managed/import admission and
ordered RUNNING-ADD removal,
configured inventory/runtime selection, nonempty legacy
migration, evidence-based automatic uncertainty recovery and scoped real-device/
multi-device/load validation. This partial profile must not be described as the
completed bulk-managed working version.

The [ready-removal backend](bulk-ready-removal.md) now supplies separate
default-false atomic ready-target retirement/shared queue admission. Its readonly
scope GET and distinct ready-only POSTs have [frozen Web confirmation](ready-removal-confirmation.md).
API/Web factory capabilities are independent and default-false, not environment/
request selectors. Legacy enablement refuses before initialization; no live gate
changed. RUNNING-ADD ordering and general concurrent write workflows still need
their separate integration and acceptance.

## Regression checks

```bash
python3 -m pytest -q tests/test_continuous_api.py tests/test_app_creation.py tests/test_refresh_bff.py tests/test_parallel_synchronizer.py tests/test_continuous_dispatch.py tests/test_bulk_protection.py
node --test tests/browser/freshness.cjs
```

Disposable tests exercise no-DDL factory/GET/first-worker startup, settings/agent/
scope/capacity mismatch, exclusive binding, startup/status schema drift, refusal
before legacy dispatch, actual ASGI lifecycle and BFF-to-API refresh/protection,
unchanged auth/CSRF/audit and hidden unavailable controls. Browser fixtures use
production templates/JavaScript. None access a real inventory/secret, deployed
service or FTD; semantic fake verification is not transport/live acceptance.
