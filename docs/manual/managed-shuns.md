# Managed Shuns — Registry Foundation and Planned Restoration

## Status and decision

**Registry foundation and read-only API/UI visibility implemented on 2026-10-17.
Restoration, managed confirmation and worker integration remain unimplemented/off.**
The [removal handoff coordinator](managed-removal-handoffs.md) is implemented
offline: atomic single-target retirement/cleanup and RUNNING-ADD settlement
are tested, but no runtime route or scheduler invokes it.
The operator requested re-adding manually added shuns when they disappear,
for example after FTD reboot. This replaces the former one-time-only target
requirement. The deployed [import workflow](import-review.md) is still one-time
and default-off; nothing in this document changes current runtime behavior,
delegates a live test mutation or reuses the consumed one-fixture approval.

Interpret "manually added" as an explicit managed addition/import through this
service. `show shun` does not supply reliable manual-versus-automatic origin.
Do not adopt every observed entry or infer desired policy from old audit rows.
Registering an existing/SSH-created shun would need its own explicit adoption
review; it is not implied by observing presence or a NOOP.

## User-visible behavior

| Situation | Intended behavior |
| --- | --- |
| Managed target remains present | Observe only; no repeated ADD. |
| Managed target absent in a new complete successful snapshot | Queue a bounded, verified restoration. No need to prove a reboot. |
| Device is unreachable, output partial or parser fails | Preserve prior state; do not infer absence or add anything. |
| Operator removes through the service | Stop maintaining that reviewed target and queue removal if needed; it must not return automatically. |
| Operator stops maintenance only | Keep any observed device shun; no further automatic restoration. |
| Operator removes directly through SSH | Restore on later confirmed absence while maintenance remains enabled. Stop maintenance first if absence is intended. |
| Enabled Protected IP matches | Block restoration; existing automatic-removal policy has priority. |
| Protection later disabled/deleted | An otherwise enabled managed intent may resume; show this warning before editing protection. |
| ADD result/worker outcome unknown | Needs attention; do not send another ADD under a new ID. |
| Later explicit managed import after retirement | New reviewed intent generation; an old-key retry never reactivates it. |

Desired and observed state are separate. A desired-present record without a
current shun must remain visible in a **Managed shuns** view, not disappear
into History. Show device hostname/IP, maintenance enabled/stopped, current
presence, blocked/pending/attention reason, source batch/authorizing actor and
last verified restoration with timezone. **Managed** is a policy label, not a
claim that the service created the current occurrence. Existing current-state
views must still distinguish actual active entries from desired-but-missing ones.

## Durable policy and authority

Use one effective `(device_id, IPv4)` intent, not hidden independently enforced
subscriptions per batch/user. Multiple users retain separate audit attribution
without causing competing restorers. A permitted explicit removal retires the
effective target for everyone in that reviewed scope. Do not automatically
extend an intent to a new device or reuse an ID after device replacement.

Future import review must clearly state **Maintain after disappearance until
stopped**, include that mode in immutable canonicalization/digest and require
current Operator/Administrator, CSRF and exact scope confirmation. Existing
one-time API clients/review tokens keep their current semantics. Changing mode
requires a new reviewed operation; it cannot reinterpret an accepted request.

Standing policy intentionally outlives login and the 15-minute manual request
window, as Protected IP policy already does. Store its authorizing actor/time,
scope, durable ID/generation, optimistic revision, enabled/retired state and
explicit revocation audit. Do not extend old request expiries, regenerate
captured Operator roles or persist browser credentials. Background restoration
uses a distinct `system:managed-shun-policy` actor, linked to current intent
revision and original authorization, rather than pretending the user is online.
Policy revocation and current Protected IP/device state are checked at claim.

Existing imported history/verified origins are **not** a migration source for
enabled intents. This includes the already cleaned-up laboratory fixture.
No-op on an existing entry must not establish creation provenance. A future
explicit adoption can authorize maintenance without claiming past creation.

## Reconciliation and queue contract

1. Obtain a complete successful snapshot through the ordinary cycle. It must
   be newer than the relevant verified operation; cached/pre-write observations
   cannot schedule a restoration after a newer ADD succeeded.
2. Read enabled intents, protection, device capability and outstanding/uncertain
   work consistently. Missing one occurrence is not absence if another matching
   interface is present on that device.
3. Admit at most one restoration intention per device/IP/intent generation and
   absence epoch. Repeated polls/tabs/restarts must not multiply work. Link it
   to the standing policy, not an expired manual request.
4. Use the same leased FIFO, 1000 unfinished-job bound, cycle cutoff, at least
   60-second persisted cooldown, combined 16-operation/64-command/120-second
   limits, mandatory verification and priority-read/final-snapshot reserves.
   No broker, second writer, standalone ADD or new SSH path is required.
5. Recheck intent generation/enabled state, protection, scope, attention latch
   and gates before every claim. Deferrals do not renew user authority; system
   policy authorization is a separate explicit domain path, not forged roles.
6. Only verified creation records a new occurrence and restoration success.
   NOOP records observed presence without fabricated restoration/ownership.
   Keep authorizing policy reference separate from per-occurrence provenance.

Queue capacity is not desired-policy capacity or load acceptance. Large desired
sets need bounded discovery/pagination and visible remaining backlog, not
inserting thousands of jobs in one transaction or automatic 15-minute renewal
of legacy imports. Exact policy/anti-churn bounds are a review prerequisite;
the 7,307-address list remains unapproved. Repeated verified restoration followed
by immediate disappearance needs bounded backoff and a visible stop/attention
threshold, not an endless console stream. Idle discovery uses normal baseline
polling; eligibility alone must not create extra sessions with gates off.

## Removal, protection and race handling

Atomic intent retirement must precede the next claim. Cancel unstarted system
restoration links without misrepresenting an already RUNNING command as
cancelled. A running ADD may finish despite revocation; ordered cleanup must
then be retained/reported under a separately valid removal authorization and
the same serialized executor. Do not simply bypass the existing ADD/REMOVE
conflict check or drop cleanup on conflict. Failure/expiry/cancellation of
removal never turns maintenance back on. An already absent target must still
allow **Stop maintaining / remove** without requiring an active observation.

All-devices removal must review the exact union of currently observed and
maintained target devices, not silently miss a rebooted/missing managed entry.
A device-specific action retires only that device. Queue cancellation of system
work must either retire the associated policy through a clearly labelled action
or explicitly warn that enabled policy will rediscover it; avoid a misleading
Cancel control that immediately recreates work.

Protected IPs always win. Admission/claim suppress managed ADD; enabling
protection cancels unstarted restoration within the same policy transaction.
Do not lose a pending removal while protection/policy changes concurrently.
Display retained managed intent as blocked by protection. If protection is later
disabled/deleted, explicitly warn that maintenance can resume. RUNNING writes
finish/settle before another command; no parallel compensating writer.

Unknown ADD remains UNVERIFIED/attention even if the next snapshot is empty.
Distinguish a later disappearance after known verified success from uncertainty
about the same attempt. A new UUID does not make an unsafe automatic retry safe.
Explicit reviewed resolution/rearm is required before another uncertain attempt.

## Retention, backup and rollout

An active desired intent is live policy even when no active observation exists.
Ordinary 366-day history retention must not erase it or its minimum authorization
metadata. Retired targets/tombstones and original-key records need a defined
lifecycle preventing stale work/history from reactivating them. Historical
events remain append-only within configured retention; do not rewrite old import
outcomes to pretend they authorized future maintenance.

The explicit registry initializer now provides empty additive policy tables,
authorization/request ledger and optimistic revisions. It is not called by
normal API/Store startup. Job/policy generation linkage, atomic retirement/
protection hooks and independent default-off reconciliation control remain
unimplemented. All existing ADD gates/device profiles remain mandatory; no
setting is introduced into `.env` yet.

Before schema rollout take a SQLite-safe checked backup and retain paired
images. Never restore an older enabled desired policy and start restoration
automatically: suspend both pending jobs **and policy enforcement**, obtain fresh
observations and require review. Downgrade must disable the new controller,
settle/suspend in-flight work and retain its additive policy tables. Ordinary
backup, upgrade, restart and audit retention are not new device-write authority.

## Implementation sequence and acceptance

1. Registry/revisions/explicit mode and durable authorization are implemented
   and tested in isolation (details below), without device execution. Resolve
   anti-churn defaults/restore suspension before applying a live migration.
2. Add managed-target UI and frozen confirmation, including missing targets,
   retirement, protection warnings and observed/provenance distinctions.
3. Integrate ordered removal handoff, revocation/cancellation/protection races,
   system queue admission and uncertain-outcome latch under independent gates.
4. Cover complete-versus-partial snapshots, reboot-like mass absence, unknown
   results, old-key replay after retirement, multiple users/instances, cutoff/
   backpressure, retention, backup restore and rollback using synthetic state.
5. Separately authorize one non-production managed fixture: verified creation,
   deliberate out-of-band absence, queued verified restoration, then explicit
   service removal and no restoration. No device reboot or new live write is
   authorized by this plan; a real reboot needs its own operational approval.

Until integration lands, current imports remain one-time and there is no
automatic restoration. The following foundation procedure is for isolated
development only, not enabling a deployed controller.

## Implemented offline registry

`ManagedShuns(store)` has no constructor side effects. Its explicit `initialize()`
requires an already initialized Store and adds:

| Table | Role |
| --- | --- |
| `managed_shun_registry` | Global optimistic revision and `restoration_suspended=1` default. No resume path/controller exists yet. |
| `managed_shun_targets` | One device/IP desired intent, UUID/generation, enabled/retired state, target revision, authorization reference and UTC dates. |
| `managed_shun_requests` | Immutable original actor/roles, canonical intent/result and timestamp, independent of pruned queue/history. |

`canonical_managed_change()` binds action MAINTAIN/RETIRE, literal managed mode,
exact typed pairs, both revisions and normalized bounded label/reason. Its digest
is not a capability. `change()` requires a matching digest, canonical UUID and
current Operator/Administrator. It validates the entire batch before changes.
Legacy one-time request keys cannot be reused in this namespace. No API actor
forwarding, CSRF route or browser action is implemented for this policy yet.

MAINTAIN validates enabled device, Protected IP revision/exclusion and rejects
implicit adoption of already observed shuns. Already-enabled desired targets
are actor-attributed NOOPs; their original authorizing record is not replaced.
RETIRE works without an active observation, on disabled devices and after
protection changes; it keeps original authorization and records the retiring
actor separately. Explicit re-enable rotates the intent UUID and increments
generation. A same-key replay returns the old result/revision without applying
it again, even after retirement, re-enable, restart or history cleanup.

The default limit is **1000 total device/IP keys, including retired tombstones**,
not 1000 active plus unlimited old keys. The ledger retains at most 10000
requests. Its final 1000 slots are reserved for actual retirement changes:
new grants and no-op churn are refused before they can exhaust revocation
capacity. Requests are not automatically expired/recycled. Initial archival/
capacity expansion is deliberately unsupported pending review; these limits
are not acceptance for the 7,307-address list. Overflow rejects the whole
change, not a partial selection. Snapshot rejects an over-limit restored store
rather than silently hiding rows.

`apply_change(connection, ...)` is a trusted internal composition hook requiring
a caller-owned write transaction. A savepoint rolls back policy/ledger/audit
on error even if the caller catches it; a later failure in the outer transaction
also rolls everything back. It never emits a success log before commit. This
is the foundation for atomic retirement with future queued removal, **not** a
safe runtime replacement for current removal admission: queue-link cancellation,
uncertain-result latches and RUNNING-ADD handoff still need integration first.
The queue now has its matching `apply_enqueue(connection, ...)` hook, with a
savepoint and post-commit-only log records. Synthetic tests compose retirement
and queue admission under one outer transaction and verify rollback of both
ledgers/audit on failure. See the
[transaction contract](operation-queue.md#caller-owned-admission-transactions).
The offline coordinator now provides single-target composite idempotency and
bounded RUNNING-ADD handoff using that hook. No route performs the composition;
ordinary opposite-action conflicts are not bypassed. UI/worker integration,
system restoration cancellation, all-device scope and reviewed recovery remain
required before runtime use. See [Managed Removal Handoffs](managed-removal-handoffs.md).
The standalone wrapper logs only request/action/actor/revision/count after commit;
labels/reason/target lists are not copied into operating logs.

`snapshot()` uses one read transaction. It returns authorization metadata,
desired state, device hostname/enabled flag, observed presence and enabled
protection separately. It reads no SSH credential, management route or pin and
does not change shun state, origins, queue or policy. A desired-present result
is not a fresh observation or verified creation. Browser escaping remains a
requirement for the future UI.

### Validation, migration and rollback boundary

Tests use temporary SQLite only: concurrent CAS/idempotency, actor/confirmation
binding, old-key replay after retirement/new generation, protections/revocation,
whole-batch rollback including injected audit failure, capacities/reserved
retirement, 1000-target completeness, restart/history retention, immutable
ledger and SQLite-safe backup preservation. They never call FTD or dispatch ADD.

There is **no live schema rollout for the registry foundation**. Read-only
API/UI integration probes existing tables but never initializes/migrates them.
That visibility update requires paired API/Web replacement, not a new agent.
For an
isolated development DB, retain additive tables/ledger when reverting code;
do not drop tombstones or restore old policy just to roll back software.
Before eventual integration, take a checked SQLite-safe backup, suspend both
queue and policy restoration on backup recovery, define the reviewed resume
workflow and validate it with tests. Ordinary initialization does not clear
an existing suspension or convert old imports. An older one-time API has no
controller for these tables and must not be advertised as managed-shun support.

## Read-only Managed shuns page

Open **Managed shuns** in the navigation. Every authenticated user may view it.
The private `GET /api/v1/managed-shuns` resource and authenticated BFF page have
no POST/PUT/DELETE or policy/resume controls. Existing imports remain one-time.
The Web page now offers a separate **non-executable** preparatory removal review
to Operators/Administrators and read-only handoff visibility to authenticated
users. Those POSTs never contact admission or change policy; see
[Managed Removal Review](managed-removal-review.md).
Neither opening the tab nor status polling initializes tables, adopts an old
import, emits policy audit, admits jobs, requests a refresh or calls the agent.

An absent registry is explicitly labelled **not initialized**, with empty
entries, rather than being silently migrated. Partial/malformed registry state
returns a controlled unavailable page, never fabricated empty policy; normal
monitoring stays available. When a registry exists, desired maintenance,
stopped state, observed presence, protection and disabled-device blocking are
separate columns. A missing shun is not labelled pending restoration when no
controller exists. Authorization is escaped/localized with timezone; Last
verified restoration is **Not recorded**, never inferred from an import or
NOOP. The controller-unavailable notice remains visible regardless of the
registry's stored suspension flag. No route/key from device inventory is exposed.

Cheap status fields publish `managed_policy_available`,
`managed_policy_initialized` and `managed_policy_revision`. Browser updates
use these plus ordinary data/protection revisions; full canonical payloads are
not repeated in polling metadata. No supported runtime policy editor exists
yet; do not seed desired entries directly in the live SQLite database for testing.
Availability metadata checks structural registry state, not every saved payload;
the full GET separately validates its read and fails closed on malformed data.

Deployment: preserve paired API/Web images and a checked SQLite-safe backup,
stop the sole API executor cleanly, then recreate only API/Web. Starting API may
execute already admitted removal/policy work. Keep ADD gates and real inventory/
.env unchanged. Read-only checks should show uninitialized registry/no new
tables in the current lab, preserved queue/policy/shun state, anonymous page 401,
normal TLS-verified Authelia redirect, version footer assets and healthy ordinary
read cycles. Revert the preceding paired images to remove visibility; do not
restore old device state, erase policy tables or reset queue outcomes. Follow
the queue suspension procedure for older pre-ADD downgrades. This read-only
rollout is not a managed-policy migration or permission to create live work.
