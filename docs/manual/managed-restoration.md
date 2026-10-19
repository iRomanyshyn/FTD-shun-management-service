# Managed Restoration — Default-Off Shared Controller

## Current boundary

The system source and bounded runtime discovery/dispatch are implemented and
tested on disposable SQLite. **The controller is disabled in the lab.**
`FTD_SHUN_MANAGED_RESTORATION_ENABLED=false` is a strict boolean, independent
of the cleanup-worker setting. True requires API ADD execution, socket cycles
and large snapshots; explicit eligible device profiles and the independent agent
ADD gate are also mandatory. Import admission remains a separate control, not
standing authority. Existing optional schemas, explicitly authorized standing
targets and an unsuspended registry are required. Separate
[policy-only standing consent](managed-grants.md) has default-off admission;
it does not resume the registry or create a queue job. No policy resume/rearm
route exists. Combined cleanup has separately default-off
[atomic admission](managed-cleanup.md), without resuming maintenance.

Normal startup, reads, worker and recovery never initialize its optional table.
The current lab remains default-off and uninitialized: deploying the package
does not create policy, jobs or a managed fixture. Low-risk lab operation does
not make incomplete integration executable. This manual does not authorize
bulk imports or reuse the consumed one-address experiment.

## Authority and evidence

`ManagedRestorations.admit_absence()` is a trusted integration hook.
Its `enabled` argument defaults false; only the separately enabled controller
supplies it. Discovery binds the assessed intent UUID; a concurrent retirement/
new grant cannot rebase old assessment onto another generation, even when their
timestamps have the same millisecond.
It requires the existing shared lease and an explicit enabled managed target,
unpaused queue, unsuspended registry, enabled device and no Protected-IP/waiting
cleanup/conflicting job. It does not infer policy from old imports or observations.

`CompleteSnapshot` represents trusted complete successful read evidence, not a
browser body or proof supplied by a network client. It carries a canonical UUID,
device ID, UTC start/completion and a frozen set of all observed IPv4s. Reject
inconsistent evidence: use one stable ID per actual completed read, not a new ID
per retry/target or one reused across different reads within a device cycle. Reject
partial, stale (>120 seconds from start), future or reversed observations, any
matching interface, local active occurrence and evidence predating authorization
or a later verified/no-op operation. The controller obtains this evidence
from the ordinary complete-snapshot path, never a failed/partial/cached response.
Snapshot freshness and lease are rechecked before admission commits.

Each intent/snapshot derives one deterministic request key. Same-evidence retry
returns its old receipt without changing state or creating another job. Reused
evidence with a different target's presence/timestamps conflicts. New discovery
cannot coalesce with pending independent one-time work or bypass uncertainty.

The delegation is a new bounded decision by standing policy, not renewal of a
user's expired request: actor `system:managed-shun-policy`, empty captured roles,
original authorization request, intent UUID/generation/target revision and
snapshot/job linkage. It lasts 900 seconds and is never extended by deferral.
The existing SQL `trusted_policy` storage enum is reused internally, but the
validated payload/action/linkage and displayed/audit source are explicitly
`managed_shun_policy`; it is neither a Protected-IP REMOVE nor `manual_import`.
No import batch or imported-origin record is fabricated.

## Shared queue lifecycle

| State | Meaning and handling |
| --- | --- |
| QUEUED | No command sent. A disabled controller holds this source; an eligible enabled source wakes the common executor only. |
| RUNNING | Claimed through the common FIFO/cutoff/lease. Cannot be recalled by policy cancellation. |
| VERIFIED | Typed agent result confirms new creation; retain its exact local occurrence/interface and timestamp. |
| NOOP | No new creation established; no restored/imported provenance. |
| FAILED / UNVERIFIED | Requires explicit reviewed resolution. New snapshots, generations and queue retention do not clear the latch. |
| CANCELLED | Unstarted system authority was revoked/blocked. Old evidence/key never replays it. A later fresh decision still needs current policy and backoff. |

Claim requires both ordinary ADD capability and the separately explicit
default-false internal restoration capability, plus current policy generation/
revision/authorization, device/protection/cleanup state and valid delegation.
It verifies the exact system actor/empty roles, action, payload and one-to-one
request/job linkage. No shared manual/system jobs, arbitrary source switching or
policy-priority bypass of the cycle cutoff. Runtime passes this capability only
when the new setting is true; disabling it holds queued attempts without renewing
their original deadlines. The queue view labels their execution capability.

All ordinary 1000 pending/2000 active bounds, lease recovery, minimum 60-second
cooldown and per-device combined command/time/write budgets remain. Discovery
admits at most sixteen new jobs and performs at most sixty-four admission
attempts per entire sweep, across all devices/initial/priority/final reads. The
existing 1000 policy-key/10000 attempt bounds apply. Initial admission bounds
are a 300-second minimum gap and at most
three attempts per device/IP per rolling hour, across intent generations.
These are fixed domain defaults, not additional `.env` tuning or large-load
acceptance. Backpressure/rolling-window holds are not successful completion.

## Discovery, scheduling and visibility

For each actual complete successful initial/priority/final read, capture UTC
start/completion and one stable UUID. Publish/reconcile it first, then discover
absence; never use a cached, failed, partial or deferred read. New system jobs
are newer than the frozen sweep cutoff and cannot execute in that same sweep.
They wait for the next eligible cycle and persisted >=60-second cooldown.
Baseline reads discover missing policy; missing policy alone does not trigger
extra cycles. Already admitted eligible work uses the ordinary queue wakeup.

Prefer never/least-recently admitted targets, and devices with the oldest last
admission, using retained timestamps rather than an in-memory cursor. This keeps
progress fair across restarts without another schema. Queue/ledger capacity
holds stop repeated admissions within the sweep. Expected conflicts/holds are
not device read failures. Unexpected discovery/optional-state errors sanitize
diagnostics, skip subsequent mutations and preserve monitoring/final reads when
available. No source-specific command, second executor or extra read is added.

Managed shuns displays controller configuration, per-target current hold and
backoff deadline with timezone. It also offers collapsed latest-sweep admission
counts and per-device assessment totals. These are not verified outcomes or a
global live inventory. Cached absence without new trusted evidence remains
"Waiting for a fresh complete snapshot", never "queued". Queue shows admitted
work and retained attempt outcomes separately. GET never fetches Cisco, admits
work or initializes optional state. Partial optional state is unavailable, not
empty. Metadata exposes bounded counts and sanitized errors, not raw CLI output.
Reviewed uncertainty resolution/rearm remains unavailable.
The separate offline [Attention Inspection](managed-attention.md) report now
combines retained latches/ordinary uncertainty/cleanup attention, without changing
outcomes, policy or current controller capability.
An explicitly migrated [abandonment ledger](managed-abandonment.md) can record
offline revocation of current maintenance for a restoration incident. It keeps
original FAILED/UNVERIFIED outcomes/latches and blocks subsequent MAINTAIN and
restoration for the pair; it is not rearm or a policy-resume exception.

Exact pre-write deferral reuses the same job/deadline. Unknown reply or lost lease
becomes retained UNVERIFIED, never an automatically replayed ADD. A future
snapshot showing presence or absence does not turn that attempt into VERIFIED.
Successful restoration followed by a later confirmed absence may form a new
attempt only with newer evidence and within all bounds.

## Revocation, protection and ordered cleanup

Policy RETIRE and Protected-IP enablement cancel queued system attempts under
the same SQLite transaction as the policy change. They do not cancel a RUNNING
command. Protection keeps desired intent enabled but blocked; disabling it still
uses the existing managed-revision acknowledgement. Any retained failure latch
continues to block later restoration. Cancellation failure/audit failure rolls
the entire policy change back.

Offline single/fleet combined removal may supersede its queued **system** ADD
atomically with retirement and ordinary removal admission. An independent queued
one-time import still conflicts and is never silently cancelled. RUNNING system
ADD uses the existing explicit ordered cleanup barrier; no REMOVE overlaps it.
A late cleanup admission failure restores retirement, cancellation and queue
state together. Removal failure never re-enables desired policy.

All domain outcomes have system-attributed append-only audit linked to original
authorization, generation, snapshot/job and managed/protected revisions. Only
VERIFIED stores restored occurrence provenance; NOOP and observation do not.
Managed shuns can read the latest retained attempt, attention across generations
and last verified restoration with timezone without enabling the controller.

## Schema, retention, recovery and rollback

Explicit isolated `initialize()` requires the existing registry/queue and adds
`managed_restoration_attempts`: at most 10000 retained immutable authority keys.
Terminal outcomes/provenance cannot be rewritten, deleted or rearmed. Job IDs
are retained as evidence without preventing normal completed-queue retention.
Failure latches, original keys and verified provenance survive job/request pruning.
Root and job keys cannot acquire ordinary/import/policy/cleanup authority after
pruning. A full ledger rejects new attempts; there is no automatic recycling or
archive/migration of historical imports.

The existing checked [Offline Recovery](recovery.md) now cancels queued system
attempts and records RUNNING ones as UNVERIFIED before suspending restoration.
Resume still clears ordinary mutation pause only. Orphan/partial pending evidence
fails closed for inspection, not repair or replay. No schema is created by recovery.

Deployments of this disabled integration retain paired API/Web images and a
checked SQLite-safe backup. Agent/wire protocol is unchanged. Verify unchanged
gates/profiles, absent optional tables, stable policy/jobs, ordinary read cycles
and anonymous rejection; do not submit a live fixture merely for smoke testing.
The separate [Offline Managed Maintenance](managed-maintenance.md) tool now
provides reviewed atomic empty-schema initialization and policy resume. Neither
has been invoked on the lab. Resume installs a new fresh-read barrier, preserves
original authority/outcomes and refuses unresolved uncertainty; it does not
enable this controller. Before live activation, complete uncertainty resolution
if needed, bulk managed admission if required and a newly scoped lab lifecycle.
Never roll back to an image unaware of pending system authority,
drop its ledger or restore old enabled policy to undo software changes.

## Validation

`tests/test_managed_restoration.py` and `tests/test_managed_discovery.py` use synthetic SQLite and typed results only:
same/different snapshot concurrency, invalid/stale/pre-write reads, independent
work, gates/cutoff, source binding, provenance/NOOP, backoff/churn, expiry/lease
loss, retained uncertainty/pruning/generations, protected/retired/running races,
single/fleet cleanup, recovery, limits and late audit/lease rollback. Browser
fixtures check retained attention and timezone-labelled verified dates. Packaged
smoke must use a networkless disposable container without live volumes or secrets.
This evidence does not establish actual reboot/restoration or production readiness.
