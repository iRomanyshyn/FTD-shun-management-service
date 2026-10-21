# Managed Shuns — Standing Policy and Gated Restoration

## Status and decision

**Registry foundation and read-only API/UI visibility implemented on 2026-10-17.
Combined cleanup admission and restoration are independently default-off.**
The [experimental restoration controller](managed-restoration.md) now implements
typed snapshot/intent-bound queue authority, claim/revocation/recovery hooks,
retained uncertainty and occurrence-bound results. Bounded complete-snapshot
discovery and shared dispatch require a separate disabled setting and all ADD
gates; no startup initializes schemas or grants standing authority. Separate
[frozen single-target consent](managed-grants.md) now supports policy-only grants
behind disabled admission, without adopting observations or queuing a command.
The [removal handoff coordinator](managed-removal-handoffs.md) is implemented
offline: atomic single-target retirement/cleanup and RUNNING-ADD settlement
are tested. A default-off worker advances waits; separate
[revocation controls](managed-controls.md) support policy-only retirement and
waiting cancellation. [Combined cleanup](managed-cleanup.md) now connects frozen
device/fleet confirmation to atomic coordination behind a separate gate; HTTP
never executes a device command. No actual lab gate or migration is enabled.
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
| Protection saved enabled | Permanently retire matching maintenance with actor audit; cancel unstarted additions, never interrupt RUNNING work. |
| Protection later disabled/deleted | Never resume old policy. Finish any legacy/deferred retirement before releasing active protection; new explicit consent is required for another maintained generation. |
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
normal API/Store startup. Job/policy generation linkage and retirement/protection
hooks, bounded default-off discovery/shared dispatch and single-pair standing
admission and default-off combined removal are implemented. Reviewed offline
migration/resume are available through [Managed Maintenance](managed-maintenance.md),
not invoked on the lab. Resolution/rearm and bulk managed admission remain pending.
All existing ADD gates/device profiles remain mandatory.
The separate default-off cleanup-worker setting does not enable restoration;
see [Managed Removal Handoffs](managed-removal-handoffs.md).

Before schema rollout take a SQLite-safe checked backup and retain paired
images. Never restore an older enabled desired policy and start restoration
automatically: use [Offline Recovery](recovery.md) to suspend both pending jobs
**and policy enforcement**, obtain fresh observations and require review. The
tool never resumes desired restoration. Downgrade must disable the new controller,
settle/suspend in-flight work and retain its additive policy tables. Ordinary
backup, upgrade, restart and audit retention are not new device-write authority.

## Implementation sequence and acceptance

1. Registry/revisions/explicit mode and durable authorization are implemented
   and tested in isolation (details below), without device execution. Resolve
   anti-churn defaults/restore suspension before applying a live migration.
2. Add managed-target UI and frozen confirmation, including missing targets,
   retirement, protection warnings and observed/provenance distinctions.
   Read-only visibility, policy-only retirement/wait cancellation and frozen
   single/fleet removal review are implemented. The fleet union/comparison
   prerequisite is now used by an offline atomic cleanup coordinator, with default
   ready-only mode and separate explicitly bound whole-scope RUNNING-ADD waiting.
   Cleanup coordinators now have default-off frozen BFF/HTTP admission. Single-pair standing
   consent has separate default-off admission; bulk managed confirmation remains
   pending. See [Standing policy](managed-grants.md) and
   [Frozen all-device scope](managed-removal-review.md#frozen-all-device-scope).
3. Integrate ordered removal handoff, revocation/cancellation/protection races,
   system queue admission and uncertain-outcome latch under independent gates.
   The offline system source/claim hooks and atomic retirement/protection/
   recovery integration and default-off bounded runtime discovery are now tested.
   Single-target standing consent/admission is now separately default-off;
   reviewed offline resume is now separate; rearm and bulk managed grants remain unavailable. Combined
   cleanup remains disabled in the lab; hold/backoff and latest-sweep counts are read-only.
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
| `managed_shun_registry` | Global optimistic revision and `restoration_suspended=1` default. Separate reviewed offline resume; experimental controller stays separately gated. |
| `managed_shun_targets` | One device/IP desired intent, UUID/generation, enabled/retired state, target revision, authorization reference and UTC dates. |
| `managed_shun_requests` | Immutable original actor/roles, canonical intent/result and timestamp, independent of pruned queue/history. |

`canonical_managed_change()` binds action MAINTAIN/RETIRE, literal managed mode,
exact typed pairs, both revisions and normalized bounded label/reason. Its digest
is not a capability. `change()` requires a matching digest, canonical UUID and
current Operator/Administrator. It validates the entire batch before changes.
Legacy one-time request keys cannot be reused in this namespace. A separate
frozen/CSRF policy-only RETIRE route now forwards the current trusted actor;
MAINTAIN has no HTTP/browser action. See [Managed Controls](managed-controls.md).

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
queue and policy restoration on backup recovery, follow the separately reviewed
[offline resume workflow](managed-maintenance.md) and its validation gates.
Ordinary initialization does not clear
an existing suspension or convert old imports. An older one-time API has no
controller for these tables and must not be advertised as managed-shun support.

## Read-only Managed shuns page

### Exact selected-policy reads for single-pair reviews

Single-pair standing-grant, stop-maintaining and combined-removal browser reviews
now read `POST /api/v1/managed-shuns/selection` instead of the complete registry.
This is a **read-only** private resource, not a mutation/admission endpoint. Its
strict body contains `targets` (1–100 distinct `{device_id, ip}` selectors) and
optional non-negative integer `revision`. IDs are literal integers; addresses
are canonical IPv4 strings. Unknown/action/actor/route fields are refused.

One read transaction returns the normalized `selection`, `read_scope=selected_pairs`,
`read_only=true`, global `total`/`revision`/`limit` and only existing selected
`entries`/`selected_count`. Missing pairs stay in `selection`, not fabricated as
managed entries. Empty/uninitialized registry and “no selected pair exists in
this nonempty registry” remain distinct. At most 100 policy and pair-summary rows
are materialized; observations, original author metadata, older-generation
attention and verified-only restoration times retain their existing meaning.

Exact revision mismatch returns 409. Invalid selectors return 422; partial or
orphaned state returns 503, even when damaged authority is outside the requested
selection. No join/filter may make corruption look like a healthy empty result.
The BFF refuses a substituted full snapshot/page or mismatched selector rather
than falling back. All single-pair forms retain current identity/CSRF/review-age/
count/typed-IP and final atomic backend revalidation; this read supplies no grant,
retirement, cleanup, adoption, fresh Cisco evidence or queue authority.

This removes another full-read prerequisite for larger capacity, **not the
1000-key limit itself**. The [standing-list workflow](managed-batch-grants.md#bounded-whole-batch-policy-reads)
now uses a separate whole-batch selector; complete-fleet contracts stay separate.
Do not treat a selected page as their complete scope. Canonical request,
attempt ledger, retirement reserve, report/cancellation limits and dispatch still
need coordinated expansion. No schema/migration/gate/agent change is introduced.

Validation uses `tests/test_managed_selection.py` and existing grant/control/
cleanup suites with temporary SQLite/ASGI. It covers exact missing/existing scope,
100-row bounds, legacy parity, corruption, stable read snapshots across concurrent
retirement, strict private fields, response-substitution refusal and no full BFF
fallback or mutation. For rollout retain paired API/Web rollback images and a
checked SQLite backup, recreate only those services, and preserve all live gates/
optional state. API restart may execute already admitted ordinary work. No new
lab fixture, optional migration or device-write validation is authorized.

### Paged registry browsing

Open **Managed shuns** in the navigation. Every authenticated user may view it.
The tab now uses `GET /api/v1/managed-shuns/page?page=1` and displays at most
100 device/IP keys per page, ordered by stable device ID then numerical IPv4.
The total includes stopped records, not just this page. Previous/Next links bind
the registry revision; a changed policy returns private API 409 and a visible
Web notice with **Open the current policy**, never a silently rebased page or
an empty-registry claim. Invalid/out-of-range selectors return 422, not clamping.
Local observation/attempt changes still update the same page without navigation;
the membership anchor is not a frozen Cisco observation. Retirement/removal
selectors contain only targets on the displayed page. Cleanup panels remain
independent and available after a membership conflict.

One SQLite read transaction supplies membership/counts, author metadata, presence,
protection and only the displayed pairs' restoration summaries/holds. At most
100 policy rows and 100 summary rows are returned; no full attempt ledger is
materialized for this tab. Retained FAILED/UNVERIFIED attention from older
generations remains visible; latest NOOP or current presence never erases it.
Missing authority/device links and unsupported policy/attempt capacity refuse
the read rather than silently filtering damaged records. Reads initialize no
optional schema and change no policy, queue, provenance or audit.

This is a bounded-read integration, **not increased standing-policy capacity**:
the existing 1000-key/10000-request/10000-attempt limits still apply. Large-import
confirmation/adoption, compatible retained capacity and rolling dispatch remain
separate work. Single-pair and standing-list Web reviews use their exact selector
resources; remaining complete-view/offline contracts stay distinct. Do not replace
exact whole-scope validation with the visible page. Paged metadata does not grant
mutation authority.

The private `GET /api/v1/managed-shuns` resource remains observational, with no
write method on that path. Separate revocation-only POSTs now provide frozen
policy retirement and owner/Admin waiting cancellation. They do not create,
re-enable, resume or admit device work. Existing imports remain one-time.
The Web page now offers a separate **non-executable** preparatory removal review
to Operators/Administrators and read-only handoff visibility to authenticated
users. Those combined-review POSTs never contact admission or change policy; see
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
verified restoration is **Not recorded** unless an optional system ledger
retains a verified creation; it is never inferred from an import or NOOP.
Retained attempt/attention remains distinct from current presence, including
attention from an older generation. The controller-unavailable notice remains visible regardless of the
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
.env unchanged. Read-only checks should preserve the exact prior registry and
optional schema (the current lab retains a retired lifecycle fixture), queue and
policy state; never expect or manufacture empty schemas. Check anonymous page 401,
normal TLS-verified Authelia redirect, version footer assets and healthy ordinary
read cycles. Revert the preceding paired images to remove visibility; do not
restore old device state, erase policy tables or reset queue outcomes. Follow
the queue suspension procedure for older pre-ADD downgrades. This read-only
rollout is not a managed-policy migration or permission to create live work.
