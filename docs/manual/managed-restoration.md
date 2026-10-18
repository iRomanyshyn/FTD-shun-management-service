# Managed Restoration — Offline System Queue Source

## Current boundary

The system-source lifecycle is implemented and tested on disposable SQLite.
It is **not a running restoration controller**. No discovery loop, HTTP admission,
managed-create/re-enable/resume/rearm action or environment switch enables it.
Runtime scheduler calls keep the independent internal restoration capability
false. Existing import admission/API ADD/agent ADD/device-profile gates remain
mandatory. The cleanup-worker flag enables neither discovery nor this source.

Normal startup, reads, worker and recovery never initialize its optional table.
The current lab remains default-off and uninitialized: deploying the package
does not create policy, jobs or a managed fixture. Low-risk lab operation does
not make incomplete integration executable. This manual does not authorize
bulk imports or reuse the consumed one-address experiment.

## Authority and evidence

`ManagedRestorations.admit_absence()` is a trusted offline integration hook.
Its `enabled` argument defaults false; the deployed application never calls it.
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
or a later verified/no-op operation. Future integration must obtain this evidence
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
| QUEUED | No command sent. Default runtime capability holds this source; it does not wake a separate executor. |
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
policy-priority bypass of the cycle cutoff. Runtime does not pass this capability;
the queue view accurately labels such jobs as held even if ordinary ADD is eligible.

All ordinary 1000 pending/2000 active bounds, lease recovery, minimum 60-second
cooldown and per-device combined command/time/write budgets remain. Discovery
budgeting/backlog pagination will be added with the controller, not an extra
worker. Initial tested admission bounds are a 300-second minimum gap and at most
three attempts per device/IP per rolling hour, across intent generations.
These are fixed offline-domain defaults, not new `.env` settings or large-load
acceptance. Backpressure/rolling-window holds are not successful completion.
Visible controller backlog/backoff and reviewed uncertainty/rearm remain pending.

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
Before a future approved migration, complete discovery, frozen managed-create/
combined controls, capabilities, resolution/rearm/backlog visibility and a scoped
lab lifecycle. Never roll back to an image unaware of pending system authority,
drop its ledger or restore old enabled policy to undo software changes.

## Validation

`tests/test_managed_restoration.py` uses synthetic SQLite and typed results only:
same/different snapshot concurrency, invalid/stale/pre-write reads, independent
work, gates/cutoff, source binding, provenance/NOOP, backoff/churn, expiry/lease
loss, retained uncertainty/pruning/generations, protected/retired/running races,
single/fleet cleanup, recovery, limits and late audit/lease rollback. Browser
fixtures check retained attention and timezone-labelled verified dates. Packaged
smoke must use a networkless disposable container without live volumes or secrets.
This evidence does not establish actual reboot/restoration or production readiness.
