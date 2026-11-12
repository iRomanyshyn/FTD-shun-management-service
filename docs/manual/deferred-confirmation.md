# Deferred First Confirmation — Evidence, Queue Handoff and Fresh Attempts

This is an **experimental, default-off development mode**. The current lab still
uses tracked v6 and complete in-session verification. Matched v0.5.0 API/client/
agent can explicitly select deferred confirmation on its separate prepared DB,
using the configuration below. Setting only the wire version to7 still refuses.
No current database, configuration or running service is switched automatically.

Source0.11.1 extends [local result persistence retries](result-storage-retry.md)
to the pre-END checkpoint and settled pending handoff. Short typed SQLITE_BUSY
contention can recover without resending an ADD/END or opening SSH. The same
live lease and evidence are revalidated; exhausted or invalid cases keep their
ordinary uncertainty/hold behavior. This does not complete general held recovery
or switch the main lab from v6.
Source0.10.2 has completed the bounded isolated normal-path FPR experiment below;
the original main lab was restored to v6 afterward.

## Final full groups (source v0.10.2)

A final group of exactly 16 addresses now follows the same deferred path as a
shorter final group. It ends the shared SSH visit without another full-table
verification; its jobs remain **Awaiting confirmation** until the next causal
complete device read. Acknowledgement is not verified presence or service-created
provenance. This fixes the redundant read for imports ending at 16, 32 or 48
addresses; the 64-attempt visit boundary already used that handoff.

Intermediate groups still verify before more work can enter the same session.
A bounded, read-only scheduling check looks for another segment or priority
removal/protection work. It does not claim jobs, create authority, extend a
deadline or bypass pauses. An interactive refresh still gets its existing
priority boundary. Stop, pause and cancellation settle the current acknowledged
tail; they do not discard it or mark it successful.

Versions 5 and 6 keep eager full-group verification. The 16-address pending
limit, 64 mutation attempts and 240-second visit budget remain unchanged. This
is one fewer redundant read for the final group, not an unbounded write batch or
a claim that every imported address is sent in one SSH session. Persistent v7
cutover and general held-epoch recovery remain separate work; an isolated,
labelled desk-lab acceptance profile does not convert the original database.

### Bounded FPR acceptance, 2026-11-12

With original writers cleanly stopped, a separate prepared profile used the
existing inventory, pinned trust and agent-only credentials to import16 fresh
TEST-NET addresses (198.51.100.160–175). They were absent in a complete device
read before authority was confirmed. One real v7 session sent16 ADDs, retained16
target preflights and performed one initial full read; it settled a pending16
tail in60.378s. Settlement15:28:46.154Z preceded the next automatic complete read
started15:28:46.263Z/completed15:28:54.528Z. All16 became OBSERVED_PRESENT with
zero repeated ADDs. This confirms presence, not original service creation.

Fresh ordinary cleanup requests disabled all16 managed targets and removed all16
with VERIFIED outcomes. The existing ten-submissions/minute limit refused the
eleventh request; its exact saved key/body was submitted after that interval.
No limiter/guard was changed. A clean API restart and complete read retained
absence and exactly32 terminal jobs. Experimental containers then exited0;
their separate state and receipts remain private evidence, not reusable authority.

The same original v6 main containers/images were restarted. Fresh main read
confirmed all fixtures absent; original nine authority fingerprints/26 historical
unknowns/import and seven recovery receipts remained unchanged. This is not a
persistent mode switch, crash/held-epoch recovery test, authenticated UI acceptance
or bulk-load benchmark. Per-target preflight dominated the small fixture visit;
it is still required. Evidence: `/tmp/ftd-deferred-tail-20261112`.

Source v0.6.0 also supports the exact [completed pending-handoff API crash
window](pending-restart-recovery.md), using the original checkpoint and agent
journal. General held-epoch recovery and broader lifecycle acceptance remain unfinished;
original unknown outcomes remain guarded. This is not an activated lab mode or a
measured throughput claim.

## Explicit configured selection (v0.5.0, 2026-11-12)

Use all of these together with matching images:

| Setting | API/Web | Agent |
| --- | --- | --- |
| `FTD_SHUN_API_RUNTIME` | `continuous-managed` | Not used |
| `FTD_SHUN_AGENT_MODE` | `socket` | Not used |
| `FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED` | `true` | `true` |
| `FTD_SHUN_AGENT_BATCH_SESSION_VERSION` | `7` | `7` |
| `FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED` | `true` | `true` |
| `FTD_SHUN_AGENT_CYCLES_ENABLED` / `FTD_SHUN_LARGE_SNAPSHOTS_ENABLED` | Both `true` | Both `true` |
| `FTD_SHUN_AGENT_ADDITIONS_ENABLED` | Not used | `true` |

Keep development authentication and all legacy admission/controller switches off.
Keep SSH credentials agent-only. Every enabled device needs its explicit supported
ADD profile. Select the separate DB prepared with
`ftd-shun-dev-init --profile deferred-confirmation`, including both controls and
ordered cleanup/promotion. The API never initializes or converts storage; the
ordinary verified worker refuses that profile, and deferred startup refuses a
verified, absent or incomplete DB. Inventory/scope, identity, pauses, uncertainty
and capacity checks are unchanged. The standalone high-level client also needs
literal `deferred_confirmation=True`, grouped tracked capabilities and its exact
nonempty bounded ADD-device set; protocol7 alone grants nothing.

`ftd-shun-api --check` and `ftd-shun-agent --check-config` report version7 and
`deferred_confirmation_enabled=true` without starting work. API status retains
the `continuous-managed` workflow family, adding this explicit boolean and the
existing confirmation/retry metadata. Configured API binds exactly
`DeferredContinuousDispatcher`; it cannot accept a verified dispatcher, injected
fake client or changed capability selection. Successful preflight is not a
device-write or crash-recovery acceptance result.

The explicit `deploy/compose.deferred-lab.yml` overlay selects
`/var/lib/ftd-shun-manager/deferred-v7.db` and matched flags after the existing
base/local-lab/managed-lab files. It does not prepare this file, copy old authority,
change trust/credentials or replace the original DB. It has **not** been applied
to the current lab. Complete the documented recovery/acceptance work before the
planned live cutover; do not treat merely adding the overlay as validation.

## Implemented boundary

A low-level tracked-v7 cycle can stage acknowledged ADDs and end with
`finish_pending_additions()`, without issuing a verification/full-table read at
that final step. It returns `SettledPendingAdditions` only after receiving both
the exact ordered pending scope and normal post-cleanup/guard/worker-IDLE
settlement, or the separately bound completed journal receipt described below.
The value contains the device, original tracked session identity,
terminal sequence and original ordered ACKs. It has no `created`, interface,
snapshot or verified-success field.

| Frame | Meaning |
| --- | --- |
| `1d 07 sequence` | End the nonempty pending group, not a device mutation or read. |
| `06 07 1d sequence count IPv4...` | Exact original ordered scope, 1–16 addresses, maximum 69 bytes. Not verified presence or creation. |
| `00 07 18 sequence` | Existing strict terminal settlement after real cleanup and worker/resource completion. Not a verified ADD outcome. |

Shared Python/Rust vectors are in `tests/fixtures/pending-end-v7.json`.
Every ACK sequence must be strictly increasing and earlier than terminal END;
NOOPs do not enter pending scope. Wrong status/version/opcode/sequence/count,
order, duplicate/foreign targets, trailing bytes or missing ACK refuse. Lost
settlement permits only the exact local completion lookup below, never a device
reconnect/resend or synthetic success. Mutated sessions remain unsafe in the
read-only completion journal lookup.

V7 retains 240 seconds, 64 combined mutation attempts, 256 commands, sequence
<=130 and pending <=16. Staging retains original target preflight, strict Cisco
ACK parsing, profile, capacity and time reserves. Plain END/snapshot/removal
still cannot overtake pending writes. Versions 1–6 retain their previous
verification contracts; v7 can also perform their strict grouped verification.

## Lost terminal response recovery (source-only v0.3.1, 2026-11-12)

If the original client fully sent END_PENDING but loses its response to EOF,
socket failure or timeout, it closes that connection and performs **one** local
completion lookup (maximum five seconds). The agent never opens SSH or issues
Cisco commands for this query, even while another visit holds the device guard.
The original ACKs stay in memory until exact proof is returned. Malformed,
truncated or foreign response evidence does not select this recovery path.

| Frame | Meaning |
| --- | --- |
| `1e 07 device:u16 session:16` | Exact original tracked-v7 identity, 20 bytes. |
| `status 07 1e device:u16 session:16` | 21-byte binding: 1 unavailable, 2 still active; neither is recovery proof. |
| `00 07 1e device:u16 session:16` + original `06 07 1d sequence count IPv4...` | Completed pending receipt, 30–90 bytes; exact original nonempty ordered group. |

Shared Python/Rust vectors: `tests/fixtures/pending-lookup-v7.json`. Only actual
END_PENDING execution plus successful SSH disconnect can prepare the receipt.
It remains unavailable until handler/resource cleanup, guard release and the
worker-IDLE postamble finish. A failed local response send does not erase that
completed proof. Normal END/verified-group/read-only/failed-cleanup sessions
cannot substitute for it. The existing process-local journal holds at most
4096 identities and evicts only completed entries; agent restart or eviction
loses proof and conservatively retains uncertainty.

The strict client checks version/device/session, terminal sequence, count and
ordered addresses against the original ordered ACKs. It sets `settled` only
after exact proof. The same existing queue transaction then requires its original
live owner/epoch, claims, ACKs, roots and delegations before recording the entire
group, transitioning to AWAITING_CONFIRMATION and releasing that original lease.
Only after this commit does the worker log
`queue.addition_batch.settlement_recovered`. No freshness/verified-progress or
creation attribution is published. The next causal complete observation confirms
presence or absence normally, including across coordinator restart.

An active, absent, foreign or unavailable receipt does not trigger polling, another
END, ADD replay or blind retry. Lost stage ACKs cannot use this path. Malformed
terminal packets also refuse without lookup. A local persistence failure retains
the previous unknown/hold behavior, even with valid transport completion. This
does not recover historical unknown operations or an arbitrary API/agent crash;
the original live caller and ACK/claim evidence must still exist. Read-only
lookup remains a separate proof and never accepts this mutated session. The
current lab remains on v6; this recovery proof does not select a mode or schema.

## Fresh deferred queue profile (source-only, 2026-11-09)

`PendingExecution` adds internal, default-disabled queue transition hooks. Its
explicit `initialize_empty()` requires an already initialized evidence ledger,
paused mutations, quiescence and **empty execution/history tables**. It installs
the expanded job/attempt/cancellation-result schema only in that fresh profile.
It does not copy, convert or discard retained execution data. Even fully VERIFIED
history refuses this initializer. A partial schema failure rolls back. There is
no startup/GET initialization. The development CLI below creates the whole
profile in a separate absent destination; runtime selection is separate above.

Use a separate disposable database for development. **Do not delete/reset the
live DB, reimport its original task or use this as a legacy-dev converter.**
The current lab and original import stay on v6. Older writers refuse the new
schema, and the current coordinator explicitly refuses it before any agent call.
The fresh execution profile may now be explicitly extended with the existing
ordered reservation/promotion schemas as described below. Initialize the empty
deferred execution layout first; its initializer still refuses pre-existing
ordered/recovery storage. Offline recovery profiles remain unsupported; the
separate evidence-only ledger retains its original recovery combinations.

### One-command fresh storage (v0.4.0, 2026-11-12)

`ftd-shun-dev-init --profile deferred-confirmation` prepares a separate new
development database with this evidence/execution/retry layout, ordered removal/
promotion and independent import/restoration pauses in the required order.
Default `--profile verified` keeps the existing verified-read layout. Both modes
require an absent absolute destination and explicit public inventory. Private
staging, integrity/checkpoint validation and exclusive publication prevent partial
or racing replacements. The setup event and JSON report identify the selected
profile. Optional protection copying reads only explicitly selected current
settings; no old managed authority, queue or history is transferred.

This is storage preparation only: no environment reads, SSH, new authority,
configured v7 activation or live database conversion. The default configured
verified worker refuses the deferred execution profile. See
[Fresh Working-Version Lab](fresh-development.md#optional-deferred-confirmation-development-storage).

The new job and attempt states are distinct from old success/failure/unknowns:

| Transition | Required proof and effect |
| --- | --- |
| `RUNNING → AWAITING_CONFIRMATION` | Actual typed settled-v7 scope, original claim/ACK/root/delegation and live lease. Record evidence, transition the whole group, audit and release that original lease in **one transaction**. |
| `AWAITING_CONFIRMATION → OBSERVED_PRESENT` | First complete causal same-device read under a current visit lease. Retain observation, not original creation. No occurrence/import-origin attribution. |
| `AWAITING_CONFIRMATION → CONFIRMED_ABSENT` | Same full-read contract, address absent. Close the old attempt; never replay its old RPC or label it unknown/failed. |

Missing ACK/end proof cannot enter awaiting state. Arbitrary RUNNING/UNVERIFIED
work cannot use this path; other unresolved device work refuses handoff. SQL
guards reject direct awaiting insertion, transitions without original ledger
membership, wrong observation verdict and conversion back to QUEUED or old
terminal outcomes. Unknowns and original terminal evidence remain unchanged.
After successful handoff, restart cannot find a half-transitioned group or its
old unreleased lease. If storage/audit/lease validation fails before commit,
the whole transaction rolls back without remote resend or synthetic release.

`confirm()` requires a live same-device lease and a complete read begun within
that visit, strictly after original settlement. Classification, both queue/attempt
results, original-identity audits, delegation closure and captured import
cancellation outcomes commit together. The same immutable first-read replay
creates no duplicate result/event. The explicit worker below commits confirmation
before publishing that read. Ordinary configured workers still refuse the profile.

Cancellation before/after handoff waits for that original observation. Confirmed
presence keeps already applied policy; confirmed absence settles without
attention and retires the exact cancelled target. Enabled protection permanently
retires its matching policy; observation/disabled protection never re-enables it.
Interactive refresh/ordinary priority removal and ready managed/fleet cleanup
are composed below. Reservations captured while RUNNING may now survive the
pending handoff; initial capture of an already-awaiting target remains unfinished.
Original cancellation identities remain.

Queue reads expose awaiting jobs. Import progress counts awaiting confirmation
and confirmed-absent `awaiting_retry` as outstanding, not completed/verified.
Observed presence counts as `present`, never `verified`. Retention preserves all
original ledger-linked jobs/requests/results. Unbound ordinary discovery refuses
same-intent deferred outcomes. Only explicit admission below may create a fresh
confirmed-absence attempt; known absence alone supplies no write permission.

## Confirmed-absence fresh attempts (source-only, 2026-11-09)

`PendingRetries.admit()` is an internal **default-disabled** composition hook,
not a background loop, operator endpoint or device call. It uses the exact fresh
execution profile above. That profile now includes immutable retry provenance;
an older disposable experimental layout refuses exact schema validation rather
than being converted. No live DB initialization or configuration change follows.

Supply 1–16 exact CONFIRMED_ABSENT predecessors, a current same-device lease,
complete absence read and current managed/protected revisions. Each new attempt
and job gets a new identity; the old job, request and verdict remain unchanged.
Admission validates the full original import root and exact still-enabled managed
intent/generation/authorization/revision. Protection, cancelled import, disabled
device, mutation/restoration pause, uncertainty, queue capacity, causal read
barriers and existing current-claim checks still apply. Retirement is not undone.
An expired original short-lived delegation stays expired; the new attempt gets
its own 900-second execution request under the original standing consent.

Retry scheduling bounds are:

- Backoff after the predecessor result: **5, 10, 20, 40, then 60 seconds**, capped.
- At most **12 retry admissions per device/IP per rolling hour**, across origins.
- Existing complete-read freshness: **120 seconds**; device serialization and
  original queue/session/cutoff bounds are unchanged.

`RetryDeferred.retry_at` reports the next eligible UTC time. It is a scheduling
wait, not a failed/unknown operation; the Queue popup shows neutral waiting
without creating false attention. If the evidence has expired when the
wait ends, obtain a new complete read instead of extending its timestamp.

The first confirming read may be reused after backoff, if its ID/device/times/
entire address-set SHA-256 are identical and it still belongs to this live visit.
A replacement read must start strictly after the predecessor completed. A shared
read ID cannot acquire different contents between admissions. Historical known
absence is the only narrow exception to its own old result-time barrier; other
completed work still requires causal evidence.

The transaction retains the immediate predecessor, original absence, ordinal,
eligible/admission times, full-read digest and owner/epoch plus a separate
`MANAGED_BULK_RETRY_ADMITTED` audit. Whole-portion validation or late lease expiry
rolls back every new job/link/event. Exact admitted-key replay returns historical
results without reviving consent or requiring the old lease to become live.

A cancelled queued child may be replaced if it was **never claimed**, or if its
single original tracked-v7 claim has exact retained pre-write-DEFER proof. The
latter requires literal `write_sent=false`, original group/owner/epoch/visit,
matching requeue/cancellation audits and unchanged job/attempt/request binding;
any missing/duplicate claim/DEFER, ACK, pending membership, foreign identity or
unknown result refuses. Admission and claim require a new complete absence read
started strictly after every replaced child's cancellation. Both paths use new
IDs and the existing backoff/hourly limits, not renewal of the cancelled request.
Legacy/non-v7 claimed cancellation remains excluded. Pending/running, sent,
failed or unknown children are never replayed/replaced automatically. To retry a
later confirmed-absent child, use that child's own observation, not its old parent.
OBSERVED_PRESENT does not authorize this first-confirmation retry path; later
disappearance uses ordinary standing-policy restoration as described below.

Queue/audit retention preserves all original pending members and retry children,
including proved pre-write cancelled children, their requests/events and actual claim-visit
claim audits. This keeps old claim history from turning into apparent nonexecution.
Corrupt/missing proof refuses pruning atomically. Unrelated expired audit rows
still purge normally. These records have a bounded retained capacity; they are
not ordinary disposable display history.

This replacement contract changes neither schema nor current v6 imports. Ordinary
workers still refuse the deferred profile. The explicit configured selection above
can now compose it; crash recovery and real-device acceptance remain unfinished.

## Durable evidence ledger (source-only, 2026-11-09)

`PendingConfirmations` is an internal, default-disabled composition hook, not an
operator API or an enabled worker. Its explicit `initialize()` requires the exact
device-scoped bulk profile, paused mutations and quiescence. Nothing initializes
it at startup or on GET. Do not apply it to the live database merely to deploy
the source: verified workers refuse the optional execution profile. The ledger
alone neither selects a configured runtime nor initializes the execution workflow;
use the complete fresh-profile CLI and matching selection above.

Three retained, immutable tables bind a terminal session, its ordered original
members, and at most one later complete observation. The session stores the
original owner/epoch, group, terminal sequence and conservative local settlement
receipt time. Each member references its original job, attempt, claim and ACK.
Recording requires the exact tracked-v7 typed receipt, complete same-device
RUNNING scope, matching ordered ACKs and original version/group/sequence audits,
original delegation and fully verified original root, plus a live lease before
and after the atomic insert. Versions 5/6, raw ACKs, foreign/expired leases,
missing evidence and already recorded sessions refuse. Receipt time is recorded
after client settlement; it is not backdated from a remote banner or ACK.

After reopening the database, inspection distinguishes:

| Evidence label | Meaning (not a queue terminal outcome) |
| --- | --- |
| `AWAITING_CONFIRMATION` | Exact ACK scope and completed session retained; no qualifying later observation. |
| `OBSERVED_PRESENT` | Address appears in the first qualifying complete same-device read; no proof of who created it. |
| `CONFIRMED_ABSENT` | Address is absent from that read; no permission to replay its old command. |

The read must start **strictly after** recorded settlement, complete successfully
in UTC and be fresh (started within 120 seconds of classification). Partial,
stale, future, wrong-device and overlapping pre-settlement reads classify nothing.
The first observation retains its ID, start/completion times, full-address-set
SHA-256 and exact present-member ordinals; unrelated present addresses do not
become group members. A shared snapshot ID must describe identical device/time/
content evidence. Exact fresh replays do not write again; another read cannot
replace the first verdict. No per-address query or remote command is issued.

The standalone ledger intentionally changes **no job, attempt, request, occurrence, managed
authority, protection, queue progress or lease**. The old RUNNING jobs still block
release; a caller cannot use the ledger as a release or retry receipt. Recording
or observing after cancellation/protection does not re-enable retired authority
or finish an existing ordered cancellation wait. Current unknowns remain unknown;
no recovery receipt is consumed or replaced. All schema/data exercises use
disposable synthetic databases only.

## Explicit per-visit worker (source-only, 2026-11-09)

`DeferredParallelSynchronizer` is a separate internal opt-in coordinator, default
disabled. It requires an existing exact fresh execution profile and explicitly
matching strict tracked-v7 client capabilities. It does not initialize storage,
select configuration, connect an ordinary v5/v6 client as v7 or convert the lab
DB. Its `DeferredDeviceOperationQueue`/`DeferredBatchSession` accept only v7;
ordinary queue/session selectors retain their v5/v6-only contracts. Configured
use requires the separate literal deferred capability and matching components.

The worker reuses the original bounded parallel coordinator and shared queue,
not another executor. Per-device streams remain serialized; independent devices
may run within the fixed pool/agent limit. Before every read publication it:

1. Constructs one complete-read evidence identity and validates device/times.
2. Confirms all prior pending groups (maximum 16) inside one current-lease
   BEGIN IMMEDIATE transaction. One failed classification rolls back all groups.
3. Publishes that same observation and only then acknowledges freshness demand.
4. Selects at most 64 confirmed-absent candidates and admits at most 16 eligible
   fresh retries within the 16-work device window; normal discovery can use the
   same read for other targets. Every admission/claim retains full original guards.

Retry selection exposes bounded counts and `retry_at` through the internal
coordinator status. These are advisory scheduling waits, not failed queue jobs.
There is no sleeping inside SSH until backoff expires and no automatic replay
of an old attempt. A later requested visit supplies fresh read evidence. The
explicit continuous scheduler below supplies those later visits. Configured
selection remains default-off and requires the separate capability above.

Independent operator pauses are checked during both retry scheduling and worker
discovery. A paused target cannot create extra retry-only SSH visits or be
reported as ineligible merely because it is paused. Other eligible targets still
progress through bounded cursors. Scheduler metadata reports sampled
`operator_paused_candidates`; worker discovery counts `operator_paused`. Resume
still requires a new complete read beyond the selected control's barrier; neither
the earlier absence nor a retry timer grants another ADD. Already claimed groups
settle and causal confirmation, ordinary/manual reads, removals and Protected-IP
unblocking continue with both pauses on. Pause is not uncertainty recovery.

Within a visit, full intermediate groups use strict original shared verification
and refresh the existing admission cutoff. A 64-attempt synthetic visit verifies
three groups of 16 and hands off only the last 16. The final nonempty group uses
`finish_pending_additions()`, exact committed handoff and original lease release.
It performs **no extra read** and does not publish a fresh snapshot, fire a
freshness callback or increment verified progress. It reports
`awaiting_confirmation`; actual verified intermediate work remains separate.
The coordinator checks the exact retained handoff rather than releasing again,
even if another owner has already acquired the successor lease.

An interactive refresh, queued priority REMOVE or enabled protection first
flushes the current group with real strict verification. Priority action then
goes next at the command boundary, using the same SSH session. Stop/pause/import
cancellation can leave the last acknowledged group awaiting confirmation; the
next read applies the existing cancellation retirement/presence rules. Protection
of an awaiting address is confirmed before publication, then removed with the
normal priority policy. Caller cancellation drains the actual RPC/terminal path,
never abandons the thread and grants a replacement command.

Unrecoverable lost/mismatched/unsettled terminal evidence or local handoff failure
retains old unknown outcomes and its fence. Only the exact completed pending
lookup above may recover response loss before handoff. Failed classification
publishes no read. A NOOP
proven by preflight does not enter pending scope or gain creation attribution.
None of these paths resolves historical unknowns or uses a mutated completion
journal entry as read-only recovery.

## Explicit continuous scheduling and UI (source-only, 2026-11-09)

`DeferredContinuousDispatcher` is a separate default-disabled composition,
not an automatic initializer. The matching configured factory selects it only
with the explicit deferred capability above. It uses the exact fresh
execution profile and matching tracked-v7 client. Ordinary `ContinuousDispatcher`
still refuses that profile. Ordered promotion is independently default-off;
explicit internal composition requires the existing exact ordered storage below.

After actual handoff, a new visit confirms outstanding groups without waiting
for the five-minute periodic interval. Reads start after the stored settlement
timestamp, with a one-millisecond strict-causality margin. Paused mutations do not
prevent read-only confirmation. Existing per-device serialization, pool capacity,
manual/removal priority and local/connection/empty-defer backoffs still apply.

For confirmed absence, the scheduler checks at most 64 advisory candidates per
device/pass, rotating past future candidates rather than repeatedly scanning a
fixed prefix. The shared retry timing includes both exponential backoff and the
rolling-hour cap. Once eligible, request a **new complete read**, not a write or
old-RPC replay. Original root/current intent/protection/cancellation/lease/freshness/
uncertainty validation remains at actual worker admission and claim. Held devices
never gain automatic retry permission. No waiting inside SSH sessions.

Per-device `deferred_confirmation` status includes `awaiting_confirmation`,
`confirmation_not_before`, `confirmation_in_seconds`, `retry_at`,
`retry_in_seconds`, `checked_retry_candidates`, `counts_are_sampled`, `held`,
`mutations_paused` and `sampled_at`. Retry eligibility comes from a bounded sample,
not a fleet total or guaranteed execution ETA. GET/presentation creates no job,
schema, demand or success. Monotonic countdown projection cannot replace causal
wall-clock read evidence. No END_PENDING callback resets freshness or satisfies
pending browser demand; the next actual complete read can satisfy it.

The existing Queue popup displays `Awaiting confirmation` as neutral waiting,
without a running animation or queued-job cancellation control. Observation
results are `Observed present` (not service-creation proof) and `Confirmed absent`;
eligible absence waits are automatic scheduling, not failed operations. Whole
import progress distinguishes confirmation/retry waits from completed addresses.
Existing true errors/unknowns remain attention-worthy. The presentation is ready
for matching metadata but does not select this backend or enable it on the lab.

## Later disappearance and ready cleanup (source-only, 2026-11-10)

After a managed attempt becomes OBSERVED_PRESENT, a later complete absence read
can start ordinary restoration under the exact same still-enabled standing
intent/generation/authorization/revision. It creates a new bounded execution
request, never resends the old command or attributes original service creation.
Existing 300-second pair backoff and three admissions per rolling hour remain;
fast confirmed-absence retry keeps its distinct 5..60-second/12-per-hour contract.
Every admission/claim retains full original root, protection, suspension,
cancellation, device, lease, uncertainty and fresh causal-read checks.

An earlier CONFIRMED_ABSENT for this exact scope can stop blocking ordinary
restoration only after a later retained VERIFIED/NOOP/OBSERVED_PRESENT attempt
establishes subsequent presence. The exact profile validates that evidence. Old
outcomes and audit never change. A newer known absence is not superseded by older
presence; it still needs the explicit fresh-retry path. Other generations,
generic observation history, missing proof or any unknown cannot supply this
exception. The new absence read must begin strictly after retained terminal
evidence. No schema, wire, selector, credential or runtime change is required.

Ready-only removal explicitly rejects AWAITING_CONFIRMATION before retiring
anything or admitting jobs. An exact fresh execution profile can now prepare
separate settled-pending ordered consent as described below; missing/invalid
evidence remains blocked. Never pretend awaiting state is a live RUNNING ADD or
silently switch an existing ready consent into an ordered reservation. After
actual confirmation, a new frozen existing
ready-removal review to retire the complete selected device/fleet scope and
enqueue one shared manual REMOVE request atomically. Results remain per-device
VERIFIED/NOOP only after semantic execution. Late failure rolls back the entire
retirement/admission; exact-key replay never re-enables policy. Confirmed cleanup
does not later re-add the address. Enabled protection remains permanent policy
retirement even when subsequently disabled.

## Captured ordered cleanup across handoff (source-only, 2026-11-11)

The explicit fresh execution profile now recognizes the exact existing ordered
reservation and promotion layouts together with its original pending schemas.
No tables, wire fields or stored consent format are added. Empty deferred setup
must precede explicit paused/quiescent ordered initialization; startup/GET never
extends a profile. Old images reject the new combination. Ordinary workers and
public runtime selectors still refuse deferred execution.

An existing exact RUNNING-ADD reservation can survive this sequence:

1. Acceptance retires matching maintenance and freezes original scope, claim,
   executor identity and deadline, as before. Admission still requires the
   original qualifying RUNNING state and existing exclusivity checks.
2. Actual settled-v7 handoff may change that captured job to
   AWAITING_CONFIRMATION. Promotion waits without creating false attention or
   queueing REMOVE merely because the original lease is now IDLE.
3. The next complete causal read produces OBSERVED_PRESENT or CONFIRMED_ABSENT.
   Promotion binds the same ledger member/claim, original owner/epoch and first
   observation. Its verdict must match the immutable present-ordinal evidence.
4. Only then can the existing whole-scope transaction delegate ordinary REMOVE,
   retaining original consent/deadline, current protection/inventory/fences,
   policy retirement, priority and queue capacity. Device execution is serialized
   and separately verified; neither observation proves original service creation.

`DeferredContinuousDispatcher(..., ordered_promotion_enabled=True)` composes this
internally, without initializing storage or selecting v7 in configuration. A
captured first ADD in a synthetic 12-address batch waits through the complete
handoff/observation and then gets urgent cleanup without another ADD. Lost
settlement remains UNVERIFIED/held; expiry/revocation never resumes maintenance;
late fleet failure rolls back all cleanup. Status accepts deferred states only
for captured ADDs, never as REMOVE success, and labels them in plain language.

That0.2.5 increment did not authorize initial capture of an already-awaiting job;
the separate0.3.0 contract below adds it without pretending an old lease is live.
Neither increment relaxes multiple-RUNNING preflight, omits independent work,
recovers unknown mutations or activates a configured/lab mode.

## New consent while already awaiting (source-only0.3.0, 2026-11-11)

An exact still-maintained device/IP in AWAITING_CONFIRMATION can now be captured
after actual original session settlement, before its first complete observation.
Preparation is a readonly local snapshot; accepting the frozen request retires
matching maintenance and reserves cleanup just as existing ordered consent does.
One fleet may contain both still-running and already-settled predecessors.

The settled descriptor has `kind=AWAITING_CONFIRMATION`, `pending_session_id` and
`settled_at`, **no `lease_until`**. Its original claim/ACK/member/session digest,
request/intent/generation/snapshot identities and original executor owner/epoch
remain bound. It is not a synthetic live lease or a new ADD delegation. The
original ADD authorization may already be expired; cleanup has its own fresh
actor-attributed key and bounded deadline and cannot renew or retry that ADD.
Current inventory/protection/policy/fence/uncertainty/capacity checks still apply.

Acceptance re-reads the complete scope and predecessor variants atomically. If
confirmation arrived while the operator was reviewing, reject the stale request;
do not silently convert it to ready removal or replace its key. Mixed variants,
future settlement, substituted identities/digests, missing proof, unknown kinds
and a smuggled live-lease field cannot partially retire or admit cleanup. Later
promotion revalidates immutable settled evidence and still requires the actual
causal complete first read. That verdict is not verified service creation.

Private request models use strict mutually exclusive running/settled variants.
Frozen Web reviews describe **Wait for confirmation** and keep typed-IP consent,
scope/key and focus unchanged through status updates. No table/CLI/binary-wire or
public runtime selector changes are made. Old running payloads still validate;
0.2.5 images refuse stored new-variant data, so use matching components before
using it in a fresh profile. No compatibility converter or current-lab extension
is implied. Current lab stays v6. Configured composition is available above;
deferred crash recovery and bounded fresh-store activation/acceptance remain unfinished.

## Remaining activation and recovery work

Only the explicitly selected matching configured mode or internal fresh-profile
handoff above may release its exact settled group; the transport value or
standalone ledger never marks arbitrary jobs successful, releases old holds,
reclassifies unknowns or authorizes another write. No live schema, gate/default,
`.env`, inventory, trust, credential or service change follows merely from the
source code. Without the new explicit capability, the configured agent and
high-level API client still reject v7. The validated new Rust release binary
has not replaced the running lab agent.

The pending-end receipt does not solve durable first confirmation on its own.
Next implementation steps, under the approved working-version behavior:

1. Matching configured transport/API composition and explicit fresh-store CLI are
   now implemented above. Keep old settings/defaults and the current lab intact
   until the remaining recovery and acceptance scenarios below are complete.
2. Complete crash/held-epoch deferred recovery without weakening unknown holds.
   Bounded lost-terminal recovery is implemented above; it is not general crash
   recovery. Initial
   settled-pending consent and captured RUNNING-to-pending cleanup,
   proved pre-write child replacement, ready cleanup and later confirmed-presence
   restoration are implemented above, not yet enabled in the lab.
3. The isolated normal ADD/causal-confirmation/retirement/removal/restart path
   passed on the FPR above. Still validate disappearance/retry, protection,
   cancellation, relevant failure/recovery paths and awaiting/confirmed/waiting
   UI without false attention or freshness resets before persistent cutover.

Do not reset/reimport the current 32,425-pair task, renew expired delegation or
reuse historical recovery keys to demonstrate the feature. These foundations are
not a throughput improvement or a completed cross-session retry workflow.

## Developer verification

Run the disposable profile, retry and retention checks with:

```bash
python3 -m pytest -q tests/test_dev_init.py tests/test_deferred_pauses.py tests/test_pending_end.py tests/test_pending_completion_lookup.py tests/test_pending_confirmation.py tests/test_pending_execution.py tests/test_pending_retries.py tests/test_deferred_worker.py tests/test_deferred_dispatch.py tests/test_deferred_lifecycle.py tests/test_deferred_ordered.py tests/test_pending_ordered_capture.py tests/test_store.py tests/test_history_pagination.py
node --test tests/browser/status-presentation.cjs tests/browser/freshness.cjs
```

The tests synthesize original v7 claim/ACK/settlement and complete reads in
separate temporary databases; they do not enable runtime selectors or send FTD
commands. Include the full Python suite before handoff and Rust transport checks
when changing the wire/agent. Passing these checks is not live v7 acceptance.

See [Working-Version Plan](../working-version-plan.md),
[Grouped Additions](batch-additions.md) and [Multi-group Sessions](multi-group-sessions.md).
