# Development Plan

Last updated: 2026-10-18

**Status: refresh/queue implemented; bounded removal sessions and priority reads experimental; parse-only import preview implemented, addition pending.** This document records
the next product increments. It describes target behavior, not capabilities
already available. See [Project Status](project-status.md) for delivery evidence
and [Architecture and Security Design](architecture-and-security-design.md#74-approved-next-increment-queued-device-cycles-and-manual-imports)
for the approved scope extension and unchanged security boundaries.

## Default-off controller checkpoint — 2026-10-18

Complete successful snapshots now feed bounded standing-policy discovery and
shared dispatch behind `FTD_SHUN_MANAGED_RESTORATION_ENABLED=false`. Existing
ADD/cycle/large-read/device gates still apply. New jobs wait behind the frozen
cutoff and persisted cooldown; sixteen new jobs/sixty-four admission checks per
sweep and retained-time fairness prevent a large missing set monopolizing it.
Managed UI separates current holds/backoff from cached observation and verified
outcomes. A separate frozen single-target standing review now supports default-off
policy-only admission with typed IP/recurring consent and original-key retry.
No extra executor, schema initialization, adoption, live grant/resume/rearm
or live combined confirmation was enabled. Combined device/fleet admission now
connects to the existing atomic coordinators behind an independent default-off
gate; explicit ordered-mode review never silently changes ready-only semantics.
Next: bulk standing-mode authorization and reviewed migration/resume/uncertainty
resolution, then a newly scoped lab lifecycle. The historical checkpoints below
describe their own delivery dates, not current feature availability.

## Latest requirement amendment — 2026-10-17

**Preparatory UI checkpoint (2026-10-17):** Frozen one-target removal reviews and
optional read-only handoff visibility are implemented/tested. Confirmation is
unconditionally unavailable and never calls the coordinator. Review data is
ephemeral, not durable authorization. No automatic schema initialization or
restoration. Worker wake/advance/expiry, executable confirmation/cancellation,
all-device/protection/system handling and composite recovery remain before any
managed-write release. See [Managed Removal Review](manual/managed-removal-review.md).

**Offline removal handoff checkpoint (2026-10-17):** Single-target atomic
retirement and durable WAITING_ADD/ordinary cleanup admission now have a bounded
coordinator and immutable composite authority. Settlement preserves original
expiry, uncertainty and shared queue limits. It has no runtime route, UI or
scheduler call and does not initialize on startup. Next connect frozen reviewed
controls, waiting/attention visibility and shared-worker wake/expiry only after
all-device/protection/recovery gates are resolved. See
[Managed Removal Handoffs](manual/managed-removal-handoffs.md).

**Transactional admission prerequisite (2026-10-17):** Ordinary queue admission
now delegates to a caller-owned/savepoint-protected hook. Offline tests compose
managed retirement and removal admission in one transaction without partial
policy/jobs/audit or premature accepted logs. No runtime managed composition,
composite request contract, system cancellation or RUNNING-ADD handoff exists
yet. Resolve those together before enabling managed writes/confirmation; this
does not authorize live policy migration or restoration.

The operator now requires restoring manually added shuns after disappearance,
including reboot-like loss. Future explicitly confirmed service-managed imports
must persist desired presence independently of observed state and completed jobs.
Service removal revokes that intent; external disappearance alone does not.
Enabled Protected IPs win. Source cannot be inferred from raw `show shun`, so
unmanaged/old historical entries are not adopted automatically.

The [Managed Shuns design](manual/managed-shuns.md) and normative amendment
supersede earlier one-time-only **target requirements** below. Existing
implemented API/review/job behavior stays one-time, with all ADD gates off.
No historical record/test result is reinterpreted. Durable standing authority,
retirement, policy job source/generation, uncertain-result latch, bounded
discovery/backpressure and backup-restore suspension must be implemented before
connecting restoration to the worker. The existing 15-minute delegation is not
silently extended. This change does not authorize a new live test or enablement.

**Registry foundation checkpoint (2026-10-17):** `managed_shuns.py` now provides
an explicitly initialized, offline-only registry, managed-mode digest, immutable
request/authorization ledger, optimistic revisions, retirement/new generations
and caller-owned transactional composition. Normal API startup does not use or
migrate it. Storage is bounded to 1000 keys including tombstones/10000 request
keys, reserving 1000 ledger slots for actual retirement. Tests exercise atomic
failures, idempotency/concurrency, no legacy adoption, retention/restart/backup
and complete 1000-target snapshots without touching queue or FTD. Runtime UI,
system queue generation, uncertainty/anti-churn and removal handoff remain next;
this checkpoint does not implement automatic restoration or approve migration.

## Implementation checkpoint — 2026-10-15

### Addition readiness checkpoint — 2026-10-16

The [ADD/cycle v3 contract](manual/addition-contract.md) is implemented in the
agent and explicit Python transport behind the new false-by-default agent flag
and per-device creation profile. It promotes the preceding offline draft after
the operator requested gated runtime implementation, not live enablement.
Shared Python/Rust vectors, local transports and fake consoles cover exact
before/ack/after semantics, combined 16-attempt limits, command/time/final-read
reserves, profile/capacity failures and no fallback/replay on uncertainty.
Default API construction remains on v1/v2. The subsequent
[staged admission/provenance](manual/import-admission.md) increment now provides
a default-off private route, immutable batches/current-occurrence attribution,
same-action coalescing and whole-batch opposite-intention rejection. Its jobs
are held/cancellable unless the independent
[queued execution](manual/import-execution.md) gate and explicit per-device
profile permit v3 dispatch. The gated worker now shares FIFO, the 16-operation
budget, priority snapshots and verified provenance with removals; no new writer
exists. Bounded [BFF review/confirmation](manual/import-review.md) is now
implemented with default-off intake and frozen same-key retries. The deployed
lab keeps all ADD gates off.
The separately approved one-address service lifecycle has now passed VERIFIED
creation, NOOP, VERIFIED cleanup and original-key replay without re-add, with
operator before/present/after reads and all gates restored off. Broader live
traffic/scope/load/failure/priority validation and browser submission remain
next; no further write is authorized by that result. Existing 1000-job capacity and
at-most-15-minute authorization do not support a 7,307-address import by one
confirmation; design explicit bounded execution/reauthorization before claiming
that support. Actual ADD/traffic validation and
real large-population read evidence remain required before enablement.
The operator-run duplicate fixture returns identical success text and visible
state on repeated add, then cleanup/absence. It reinforces fresh preflight/no-op;
hidden state and actual traffic behavior are not established.

The bounded [large-snapshot extension](manual/large-snapshots.md) is implemented
with a default-off API/agent flag: opcode 07 and cycle v2 provide complete
manifest/chunk/digest reads while retaining legacy/v1 behavior and all write/
session budgets. Synthetic capacity/transport/atomicity tests pass. After
explicitly approved API/agent rollout and lab opt-in, a live v2 cycle completed
two full reads in one session in 8282 ms without removals or errors. Real
large-load timing/paging and v2 mutation/priority evidence remain separate gates.
Subsequent read-only inspection observed 61 active records without errors and
an 8072 ms v2 read-only cycle. This still does not exercise large multi-chunk
FTD output or establish independent CLI-count agreement. Active UI sorting now
prioritizes all Protected IP matches, then current appearance newest first;
it does not change this release boundary.
Addition/import remains unavailable. The capacity diagnosis below describes
the unchanged legacy/default path, not a completed large-load acceptance test.

The large preview exposed a prerequisite for actual imports: current SSH
command output and binary snapshots are independently capped at 64 KiB.
7,307 `management` entries require 109608 legacy packet bytes (109612 in a
cycle), plus a much larger CLI read. The preview budget is not device capacity.
Implement/review bounded complete-snapshot scaling before any large add load;
keep current rejection behavior until a versioned design is approved/tested.
No partial read may be reconciled as disappearance. A global buffer increase
alone is not sufficient. Keep one agent/worker and the existing isolated layout.

Use [Addition Readiness](manual/addition-lab-validation.md) for staged Basic
permission/scope observation with one explicitly approved TEST-NET fixture.
On 2026-10-16, the operator reported Basic creation of the initially absent
`198.51.100.251` and observed it on `management`, then confirmed its removal
with `no shun ... interface management` and an empty target read. This is
new direct-CLI evidence, not agent ADD or data-plane proof. The subsequent
repeat-add transcript above establishes visible duplicate behavior only;
hidden-state semantics, fleet creation scope and traffic blocking remain unproven. Existing
removal-cycle validation remains required. No new opcode or write is enabled.

### Previously delivered checkpoint

The independent preparatory [Import Preview](manual/import-preview.md) is
implemented: bounded pasted-text parsing in Web, typed local-state classification
in API, explicit target selection, protected/current/duplicate/refused outcomes
and advisory pair counts. It never queues, persists a batch, sends raw paste to
the API/agent or creates a write capability. Existing session-cycle laboratory
work and the narrow ADD design/validation gates still precede actual admission.

The compact UI/managed-policy increment adds Status and Queue disclosures,
separate History and Protected IPs pages, progress spacing and persistent safety
warnings. Protected IP policy is now SQLite-owned and editable by every authenticated user,
with names/comments, enabled state, revision conflicts, audit and atomic
unstarted-policy cancellation. The obsolete environment list is migrated once
with a durable marker; it is not a runtime configuration source. This does not
implement manual shun addition/import. See [Protected IPs](manual/protected-ips.md)
for the upgrade and restore/rollback contract.

The refresh reliability increment now provides process/cycle/data/status
revisions, coalesced active-sweep requests, per-device status, and serialized
browser requests with dynamic state updates preserving input. Python and real
Chromium tests cover concurrency, repeated failures, partial success, restart,
and recovery. Deployment and live FTD/Authelia verification remain pending.

The transitional removal queue now provides durable multi-user admission,
idempotency/coalescing, actor-preserving audit, cancellation, authorization
expiry, a leased executor, persisted fleet-wide cooldown, and a queue panel.
It deliberately handles one queued removal per device per cycle using the
existing per-operation SSH sessions. See the [queue manual](manual/operation-queue.md)
for the migration and recovery procedure.

The [cycle protocol](manual/agent-cycle-protocol.md) now implements opt-in
single-session removal batching and priority checkpoints, with shared Python/
Rust wire vectors and local scheduler/transport/browser tests. Its hard limits
are 16 removal steps, 64 CLI commands, a 120-second work window, and one extra
priority snapshot; each step is capped at the smaller of 45 seconds and the
configured operation timeout. `FTD_SHUN_AGENT_CYCLES_ENABLED=false` remains the
default in API and agent pending live validation. Exact pre-write deferral may
return a claimed job to QUEUED; uncertain writes never do. The extension uses
the existing queue tables, actor/expiry/lease rules, and persisted cooldown.
Manual addition/import execution remains unimplemented. The deployment checkpoint below
separates completed read-only checks from remaining live mutation validation.

Deployment checkpoint: on 2026-10-15 the operator approved the local upgrade
and waived a backup for development data. Queue schema migration, SQLite
integrity, two live BEGIN/END read-only session cycles, manual refresh/cooldown,
and unauthenticated edge checks passed. The local stack enables the extension;
tracked defaults remain false. Live queued batch removals, authenticated browser
retest, and mid-batch priority reads remain pending.

## 1. Product decisions

- Keep one isolated Rust agent, SQLite WAL, and the existing Web/BFF/API layout.
  A separate message broker, reader service, or writer service is unnecessary
  for this increment.
- Future explicitly managed imports maintain desired presence across confirmed
  disappearance/reboot, without a remote feed or extra service. Explicit service
  removal retires the corresponding desired targets and prevents re-add.
  Existing one-time imports do not become managed without a new reviewed policy.
- Record manual-import provenance in SQLite and structured logs, and show it
  in current state and historical views.
- Accept concurrent users through a shared, durable queue for all device
  mutations. Submitting a request does not immediately open FTD SSH.
- Execute additions, removals, and reconciliation together in scheduled device
  cycles, with at most one cycle per minute per device and one CLI session at a
  time on that device. The limit applies across users, tabs, retries, policy
  removals, and refresh requests. An interactive snapshot may take priority at
  a safe command boundary inside the running session, within the same cycle's
  command/time budget and the shared interactive-refresh rate limit.
- Preserve the configurable five-minute idle baseline. Pending work or active
  authenticated UI use may request an earlier cycle, subject to the shared
  one-minute minimum. A request inside the final minute before a baseline
  joins that scheduled cycle.

The minute limit concerns a bounded batch plus its refresh, not one individual
IP operation per minute. The batch still needs limits so a large paste cannot
produce an unbounded stream of console commands.

## 2. Stable refresh and browser behavior

Replace timestamp/error-text comparison as the completion signal with explicit
cycle metadata:

- a service instance identifier and a monotonically increasing completed-cycle
  revision, so a restart cannot be confused with the old process;
- cycle ID, queued/running/completed state, start/completion times, next eligible
  device-cycle time, and next baseline time;
- per-device last attempt, last success, freshness, error category, and outcome;
- separate observed-state freshness from pending or unverified operations.

Publish a new completed revision for successful, failed, and partially
successful cycles. Repeated identical failures must still be visible, and a
failure on one FTD must not hide changes already observed on another.

The button receives the real scheduling decision in its submission response.
While work is running, refresh requests join a coalesced priority snapshot
inside that cycle instead of creating another session. Browser polls read local BFF state only and are
serialized; late HTTP responses must not overwrite a newer revision. Status
and operation responses must not be cached.

Use clear UI states: **Queued**, **Scheduled in …**, **Refreshing…**,
**Completed**, **Partially completed**, and **Failed**. Surface network errors
next to the control and retain a usable retry action. Stop or slow polling in
hidden tabs, resume on visibility, and prevent overlapping polling loops.

Publish a separate observed-snapshot revision after each complete, successfully
parsed and committed snapshot, including an interactive snapshot partway
through a cycle. A snapshot can be current while the import is still running;
its publication must not imply that the cycle or queued batch has finished.
Maintain a queue/progress revision for item and scheduling transitions as well.

After a completed or observed-snapshot revision changes, refresh the displayed data once. Prefer
updating the relevant page sections while preserving the search query, scroll,
expanded event log, and typed confirmation fields. A full-page fallback must
not discard an in-progress import or removal confirmation. A countdown alone
must never claim completion or initiate a reload loop.

Show a compact per-device status summary with last successful observation and
an explicit stale/error indicator. Keep the current/historical distinction,
Protected-IP markers, timezone labels, and recent event view.

### Queue execution status in the UI

Provide a shared **Operation queue** panel showing pending/running counts,
device hostname, active batch and requester, current semantic action/IP,
completed/total items, and separate verified, no-op, failed, unverified,
cancelled, and deferred counts. Show queue position or scheduling priority,
elapsed time, the next eligible cycle, and any wait/backoff reason. Estimate
remaining time only when measured timings support it; otherwise display the
item counts and next scheduling opportunity without an invented ETA.

Use explicit states such as **Import running**, **Refresh requested — waiting
for current operation**, **Reading snapshot**, and **Import continuing**.
Update progress and snapshot results dynamically through the authenticated BFF
while preserving user input. Queue-status polling is local and must not itself
request more CLI work. Multiple users see the same device execution state,
with their own submissions identifiable by actor and operation ID.

## 3. Shared queue and device cycles

### Durable admission and ownership

Store requests and device-scoped operation items in SQLite. Commit admission
and its audit event atomically before returning **Accepted/Queued** with an
operation ID. A queued response is not verified success.

Use one background queue worker in the API service. Claim work transactionally
and ensure a second worker or restarted process cannot execute the same item
concurrently. Enforce single-device CLI serialization at the agent boundary as
well. Do not hold a SQLite transaction open while waiting for SSH.

Remember the last device-cycle completion/next-eligible time durably. Wait at
least 60 seconds after a device cycle completes before opening its next cycle;
long cycles never overlap or create catch-up bursts. Configuration may increase
this minimum but must not lower it below 60 seconds. Startup, retries, and
manual refreshes use the same gate. A fresh installation with no previous
cycle may perform its first startup cycle immediately.

### Cycle sequence

1. Select a bounded, ordered batch of eligible mutations for a device. Freeze
   that batch; new mutation requests wait for the next eligible cycle. A
   coalesced interactive snapshot is the narrow exception: it may be inserted
   at the next safe checkpoint within the running cycle.
2. Establish one pinned-host-key, prompt-driven SSH session for the cycle.
3. Obtain and strictly parse a complete pre-operation snapshot. A failed
   snapshot blocks writes for that device and preserves its previous state.
4. Revalidate target inventory, authorization/expiry, trusted-IP exclusions,
   conflicts, and current presence before each eligible change.
5. Apply the source-defined typed add/remove operations sequentially, waiting
   for each prompt. Use bounded command counts and session duration; defer
   excess work with a visible next-cycle estimate. At a safe checkpoint, serve
   an eligible interactive snapshot before the next background mutation.
6. Obtain the required post-write observations in the same session. Coalesce
   full snapshot refreshes where safe, while preserving per-operation verified
   results and fail-closed handling of unknown output.
7. Persist verified outcomes, reconciliation, audit events, cycle revision, and
   next eligibility. Close the session and publish the completed cycle.

The agent will need an explicitly versioned, bounded typed cycle/batch protocol
to reuse a session. Repeated calls to the existing one-session-per-operation
RPC are not sufficient to meet this connection-load goal. The exact binary
layout, count limits, and result bounds for removals are now defined in the
cycle protocol manual; addition encoding still needs separate design/review.
Raw pasted text and CLI
strings must never enter that protocol.

### Interactive refresh priority during a running batch

A manual refresh of a device with a large import in progress must not wait for
the entire import. Accept its scheduling hint immediately, then insert a
typed full-snapshot read before the next background mutation at the next safe
checkpoint in the current SSH session. The boundary requires a complete,
validated prompt and no outstanding write-verification obligation. Never
interrupt bytes/output of a running command or send concurrent CLI commands.

If a just-completed write still needs verification, perform that verification
first; a full priority snapshot may also fulfill the verification requirement
when the strict result is sufficient. A command timeout, lost prompt, or
uncertain session stops the cycle rather than attempting to insert a read.

For example, an interactive refresh arriving during item 24 of a large import
runs after item 24 reaches a safe boundary, publishes the observed state, and
then allows item 25 to proceed. The import remains **Running** until its own
items and verification finish. A priority snapshot is a read, not a new
mutation, cancellation, or replay of the batch.

All users share at most one pending interactive refresh per device. Concurrent
requests attach to that work and receive its ID/state instead of each creating
a new read. Keep the configured interactive minimum (at least 60 seconds)
between serviced interactive refreshes; a recent committed full snapshot can
satisfy a request, and otherwise the control shows the remaining eligibility
delay. Reserve at most one extra priority full snapshot per device cycle;
later demand coalesces with its final snapshot or the next eligible cycle.
Mandatory pre/post-write verification remains required and consumes the same
bounded command/time budget. This bounds console load and prevents repeated
refresh clicks from starving background operations.

Reserve a snapshot/verification budget before admitting another mutation.
Priority refresh does not extend the session deadline or batch-size limit. If
it cannot fit safely, close out the bounded cycle and defer the request to
the next eligible cycle with an explicit wait state. A refresh for an idle
device still obeys its persisted cycle gate; a busy device must never receive
a second SSH session to serve an interactive request.

The cycle/batch protocol must support bounded progress responses and a narrow
typed refresh signal that can be received while a batch is running. An opaque
blocking whole-batch RPC cannot provide these checkpoints. Design dispatch
and cancellation/connection-loss behavior explicitly without introducing
arbitrary commands, an unbounded control queue, or a new network listener.

Trusted-IP automatic removals join this same cycle and session budget. They
must not create independent SSH work. A newly discovered protected shun may be
removed within the current cycle if its reserved command/time budget permits;
otherwise it remains visibly pending for the next cycle. Other devices retain
independent state so one unavailable FTD does not prevent their progress.

### Multiple users and conflicting intents

- Give each submission an idempotency key. A repeat with the same key and
  payload returns its original operation; a changed payload is rejected.
- Coalesce identical pending device/IP/action work while retaining every
  requesting actor and request ID. Do not silently lose attribution.
- Serialize different actions for the same device/IP. For opposite requests
  from different users, keep the earlier admitted intent and mark the later
  request **Conflict**, identifying the pending work for review. Do not silently
  choose the last writer or execute opposing writes in one cycle.
- Allow an authorized operator to explicitly cancel an unstarted add. Record
  cancellation and invalidate all retries for that add. If it is already
  running, offer a subsequent queued removal with a visible dependency.
- Define cancellation permissions explicitly; all users with the appropriate
  role may see pending actions, but cannot impersonate another requester.
- For bulk work, freeze the confirmed target devices. Report partial results
  per device/IP rather than claiming an atomic fleet-wide transaction.
- Bound queue depth, paste size, item count, execution time, and per-user
  admission rate. Reject overflow before admission and display a useful error.
  Keep removals responsive during a large import with bounded fair scheduling.

### Failures, restarts, and retries

Operation states include `QUEUED`, `RUNNING`, `VERIFIED`, `NOOP`, `FAILED`,
`UNVERIFIED`, `CANCELLED`, and `CONFLICT`. Track deferred work separately from
completed work and retain batch totals and per-item outcomes.

Do not promise exactly-once physical execution across an SSH disconnect: a
command may have taken effect before its result was lost. Mark that item
`UNVERIFIED`, then inspect actual device state in a later eligible cycle.
Record a reconciled outcome separately from an immediate verified response.
Do not blindly replay an uncertain write. Retries need bounded attempts and
backoff through the same scheduler; a cancelled or completed request cannot
be revived by restart, import history, or a stale retry.

No automatic whole-batch rollback. It could remove shuns that predated the
import or overwrite another operator's work. Any compensating action is an
explicit, audited, queued request.

## 4. Manual blocklist import

### Parse and preview

Provide a large paste field with **Parse**, followed by a reviewable preview
and explicit **Queue import** confirmation. Initial support is individual IPv4
addresses only. Accept plain lines, whitespace/comma/semicolon-separated
address lists, inline comments, and a single address embedded in surrounding
text. Never treat surrounding text as an instruction.

For the initial parser, ignore whole-line `#` and `//` comments and strip an
inline `#` comment before extracting candidates. Comment contents are not
additional targets. Preserve a bounded, escaped comment as operator context.
Recognize explicitly delimited address-only lists; mark free-text lines with
multiple candidate addresses as **Ambiguous** rather than guessing which is
the attacker. Other comment syntaxes need explicit support and fixtures.

Use token extraction followed by a standard IPv4 parser. Reject malformed
addresses and do not extract an apparently valid substring from a malformed
address, CIDR, IPv6 address, range, URL, or address-with-port token. Display
unsupported CIDRs/ranges/IPv6 explicitly; never silently truncate or expand
them. Deduplicate canonical addresses while retaining source-line references.

Preview columns: canonical IP, source line(s), comment/reason, selected device
hostnames and configured interface scope, protection marker, and validation
result. Results include **Ready**, **Duplicate**, **Already shunned**,
**Protected**, **Invalid**, **Unsupported**, and **Ambiguous**. Explain skipped
rows and counts before confirmation. Check protected addresses at preview,
queue admission, and execution so configuration changes cannot bypass the
trusted-IP policy.

Capture an optional batch label and reason, require explicit target device
selection, and show the exact expanded device/IP operation count before
confirmation. Bind confirmation to the parsed batch and target snapshot;
changes require a new preview. Imported text is always HTML-escaped and must
not appear as an unrestricted raw payload in logs.

### Managed application and occurrence provenance

The existing implementation creates one-time durable jobs. The new target
workflow additionally creates explicitly reviewed standing desired policy for
service-managed imports. A later complete snapshot proving absence can create
a new bounded restoration intention, not replay the completed job. Explicit
service removal first retires desired state; external disappearance/reboot
does not retire it. A new import after retirement requires fresh confirmation
and a new intent generation; an old-key retry must never re-enable maintenance.

Preserve batch ID, source `manual_import`, submitting actor and roles,
submission time, reason/comment, canonical targets, request IDs, and per-device
execution/verification results in SQLite. Emit matching bounded structured
JSON events for the existing log-collection path. Show **Manually imported**
and the responsible batch/actor in active and historical views.

An **Already shunned** result records the import request/no-op but does not
relabel an existing observed shun as created by this service. Likewise, a
historical import must not imply ownership of a later externally recreated
shun. Associate provenance with the particular observed occurrence and verified
operation; leave unknown origins explicit.

Removal needs atomic desired retirement and cancellation of unstarted
restoration before ordinary queued device removal, with an explicit serialized
handoff for an already RUNNING ADD. Include missing-but-managed devices in
all-device review. Retain historical occurrence annotation under configured
history retention, but keep active desired policy/minimum authorization metadata
even when no current shun exists and history is purged. Preserve uncertainty;
later observation is not proof of who created or restored an occurrence.

## 5. Security and implementation gates

Addition is currently unavailable. First resolve the documented full-snapshot
capacity blocker without weakening atomic reconciliation or fixed-frame bounds.
Before enabling imports, define and review
the narrow `ADD_SHUN` operation and its fixed binary encoding. Resolve and lab
validate the creation interface scope, preexisting-entry/no-op handling,
Basic-account permission, strict response parsing, actual blocking behavior,
and post-write verification on the supported FTD version. Do not promote the
account or add generic command execution to work around a failed test.

Addition and removal require the mapped Operator/Administrator role and CSRF
protection. Capture trusted identity at admission; expired/cancelled requests
must not execute indefinitely. Specify execution-time authorization and request
expiry behavior before implementing the worker, without persisting session
cookies, passwords, or bearer credentials in queue records.

The implemented additive admission migration includes queue claims, idempotency,
batch provenance, backup instructions and a rollback procedure. Gated worker
integration adds no further schema and keeps cycle metadata in the existing path.
Restoring a backup must suspend pending mutations until device reconciliation
and operator review prevent replay of previously completed work.

Custom Security Intelligence feeds, automatic feed downloads, CIDR expansion,
expiration/TTL removal and additional reader/writer services remain deferred.
Desired-state restoration of explicitly managed manual shuns is now required,
but not implemented or enabled. Its independent system-policy authority must
not be implemented as automatic renewal/reimport of expired user requests.

## 6. Delivery order and acceptance

Current next work supersedes the older sequence below:

1. Delivered in isolation: desired registry/revisions, explicit managed mode and
   durable authorization with lifecycle/concurrency/retention/backup tests.
   Normal startup still does not initialize it. API/UI now expose optional
   observational visibility, frozen reviews and revocation-only policy RETIRE/
   waiting-cancel controls. Composite offline recovery and default-off leased
   cleanup promotion are implemented with synthetic tests, not live acceptance.
   Protected-IP warnings/current-revision acknowledgement and guarded ordinary
   removal/MAINTAIN admission are now implemented. They do not provide system
   restoration generation/claim hooks or executable fleet cleanup.
2. Complete combined executable cleanup confirmation, reviewed fleet scope and
   protection/system hooks; retain observed-versus-desired-versus-created
   distinctions. Policy-only revocation is not device removal or creation.
3. Shared-worker system intentions, ordered retirement/removal handoff, atomic
   protection checks, uncertainty latch, deduplication/backpressure and bounded
   anti-churn, independently gated off.
4. Separately authorized single managed-fixture create/disappear/restore/remove/
   no-readd test before any broader reboot/load or long-list trial.

The prior delivery sequence documents the foundational work; it is not approval
to enable current one-time imports as a restoration controller.

1. Stabilize cycle metadata and browser refresh. Exercise slow/failed devices,
   repeated identical errors, partial fleet success, multiple tabs, request
   ordering, and API restarts. Preserve input while updating displayed data.
2. Add the durable shared scheduler and migrate existing removals, refresh
   hints, and trusted-policy actions to it before enabling additions. Verify
   one device session per cycle, the persisted 60-second gate, bounded work,
   queue overflow, fairness, restart recovery, and simultaneous-user conflicts.
   Include a shared queue/progress panel and separately versioned snapshot,
   cycle-completion, and progress updates.
3. Define and lab validate the typed agent cycle/batch and `ADD_SHUN` protocol.
   Add malformed-packet, response-parser, cancellation, timeout, and uncertain
   write tests. Existing fail-closed removal guarantees remain required.
4. Add parse/preview, confirmed import admission, provenance, progress, and
   per-item results. Validate comments, embedded text, ambiguous rows,
   duplicates, unsupported formats, protected addresses, and input limits.
5. Run a full lab scenario: two users submit add/remove/refresh work; observe
   bounded CLI sessions; verify actual FTD state and audit attribution; remove
   an imported address; restart and reconcile; confirm it is not re-added.
   During a long import, submit refresh hints from several users and confirm
   one coalesced priority snapshot runs after the current operation and its
   required verification, updates the page before the import finishes, and
   then lets background work continue. Test refresh cooldowns, exhausted
   session budgets, prompt timeout, preserved input, and absence of starvation
   or additional SSH sessions.
6. Complete the existing production-readiness work: reproducible Python dependency
   locking/container builds, failure-path integration
   tests, source/egress restrictions, external structured-log collection,
   metrics/alerts, SQLite-safe backup and restore, TLS/authentication checks,
   and the outstanding FTD laboratory procedure. These remain tracked in
   [Project Status](project-status.md).

Removal-cycle limits, wire format, and captured-authorization expiry are now
specified and implemented behind laboratory gates. Addition/import schema,
protocol and worker integration are implemented and default-off; scoped live
validation, authenticated live BFF submission and large-list scheduling remain. Target requirements
above do not imply deployed or lab-validated batch/import capability.
