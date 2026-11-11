# Deferred First Confirmation — Evidence, Queue Handoff and Fresh Attempts

This is a developer contract, **not an enabled import mode**. The current lab
continues to use tracked v6 and complete in-session verification. Do not set
`FTD_SHUN_AGENT_BATCH_SESSION_VERSION=7`: configuration and high-level composition
deliberately refuse it until the complete worker/retry/priority contract exists.

Explicit internal per-visit and continuous workers are implemented below. This does not
enable the configured service, high-level Unix client or agent v7 selector.

## Implemented boundary

A low-level tracked-v7 cycle can stage acknowledged ADDs and end with
`finish_pending_additions()`, without issuing a verification/full-table read at
that final step. It returns `SettledPendingAdditions` only after receiving both
the exact ordered pending scope and normal post-cleanup/guard/worker-IDLE
settlement. The value contains the device, original tracked session identity,
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
order, duplicate/foreign targets, trailing bytes, missing ACK or lost settlement
refuse. The client closes without fallback, reconnect, resend or synthetic success.
Mutated sessions remain unsafe in the read-only completion journal lookup.

V7 retains 240 seconds, 64 combined mutation attempts, 256 commands, sequence
<=130 and pending <=16. Staging retains original target preflight, strict Cisco
ACK parsing, profile, capacity and time reserves. Plain END/snapshot/removal
still cannot overtake pending writes. Versions 1–6 retain their previous
verification contracts; v7 can also perform their strict grouped verification.

## Fresh deferred queue profile (source-only, 2026-11-09)

`PendingExecution` adds internal, default-disabled queue transition hooks. Its
explicit `initialize_empty()` requires an already initialized evidence ledger,
paused mutations, quiescence and **empty execution/history tables**. It installs
the expanded job/attempt/cancellation-result schema only in that fresh profile.
It does not copy, convert or discard retained execution data. Even fully VERIFIED
history refuses this initializer. A partial schema failure rolls back. There is
no startup/GET initialization, configuration selector or operator init CLI.

Use a separate disposable database for development. **Do not delete/reset the
live DB, reimport its original task or use this as a legacy-dev converter.**
The current lab and original import stay on v6. Older writers refuse the new
schema, and the current coordinator explicitly refuses it before any agent call.
The fresh execution profile may now be explicitly extended with the existing
ordered reservation/promotion schemas as described below. Initialize the empty
deferred execution layout first; its initializer still refuses pre-existing
ordered/recovery storage. Offline recovery profiles remain unsupported; the
separate evidence-only ledger retains its original recovery combinations.

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

This replacement contract is source-only/internal. No schema, public selector,
configured runtime, current v6 import or device command changes. Ordinary workers
still refuse the deferred profile; ordered pending/recovery and explicit
fresh-store configuration/acceptance remain prerequisites for enabling it.

## Durable evidence ledger (source-only, 2026-11-09)

`PendingConfirmations` is an internal, default-disabled composition hook, not an
operator API or an enabled worker. Its explicit `initialize()` requires the exact
device-scoped bulk profile, paused mutations and quiescence. Nothing initializes
it at startup or on GET. Do not apply it to the live database merely to deploy
the source: older writers refuse the optional schema, and current workers cannot
finish the new workflow. There is no new configuration flag or initialization CLI.

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
ordinary queue/session selectors retain their v5/v6-only contracts. Public
configuration/high-level Unix client/agent still refuse v7.

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
explicit continuous scheduler below supplies those later visits; configured
runtime selection remains disabled.

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

Lost/mismatched/unsettled terminal evidence or local handoff failure retains old
unknown outcomes and its fence. Failed classification publishes no read. A NOOP
proven by preflight does not enter pending scope or gain creation attribution.
None of these paths resolves historical unknowns or uses a mutated completion
journal entry as read-only recovery.

## Explicit continuous scheduling and UI (source-only, 2026-11-09)

`DeferredContinuousDispatcher` is a separate default-disabled internal composition,
not a configuration selector or automatic initializer. It uses the exact fresh
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
anything or admitting jobs. Ordered read-only inspection reports
`ADD_AWAITING_CONFIRMATION`, with human guidance to request a refresh and review
again; it creates no confirmation token or executable predecessor. Never treat
awaiting state as a waitable RUNNING ADD or silently switch ready consent into
an ordered reservation. After actual confirmation, use a fresh frozen existing
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

This does **not** authorize initial capture of an already-AWAITING_CONFIRMATION
job, omit independent pending work, relax multiple-RUNNING preflight checks,
recover an unknown mutation, or activate a configured/lab mode. Such an initial
inspection still requests a refresh and a new review. Compatible deferred
recovery, remaining capture/composition and bounded fresh-store lab acceptance
are still required before activation.

## Not implemented or activated

No configured service consumes these hooks. Only the explicit fresh-profile
handoff above may release its exact settled group; the transport value or
standalone ledger never marks arbitrary jobs successful, releases old holds,
reclassifies unknowns or authorizes another write. No live schema, gate/default,
`.env`, inventory, trust, credential or service change follows merely from the
source-only code. The current
configured agent rejects v7 before SSH opening; high-level API client and grouped
queue also reject it. The new Rust release binary is validation, not deployment.

The pending-end receipt does not solve durable first confirmation on its own.
Next implementation steps, under the approved working-version behavior:

1. Connect the explicit continuous worker to a matching configured transport
   and deliberate fresh-store initialization.
   Do not merely widen existing v5/v6 settings or replay original lab authority.
2. Complete initial already-pending managed/fleet capture and compatible deferred
   recovery without weakening unknown holds. Captured RUNNING-to-pending cleanup,
   proved pre-write child replacement, ready cleanup and later confirmed-presence
   restoration are implemented above, not yet enabled in the lab.
3. Run new labelled bounded fresh-store lab acceptance, including the implemented
   awaiting/confirmed/waiting UI without false attention or freshness resets,
   before enabling the mode.

Do not reset/reimport the current 32,425-pair task, renew expired delegation or
reuse historical recovery keys to demonstrate the feature. These foundations are
not a throughput improvement or a completed cross-session retry workflow.

## Developer verification

Run the disposable profile, retry and retention checks with:

```bash
python3 -m pytest -q tests/test_pending_end.py tests/test_pending_confirmation.py tests/test_pending_execution.py tests/test_pending_retries.py tests/test_deferred_worker.py tests/test_deferred_dispatch.py tests/test_deferred_lifecycle.py tests/test_deferred_ordered.py tests/test_store.py tests/test_history_pagination.py
node --test tests/browser/status-presentation.cjs tests/browser/freshness.cjs
```

The tests synthesize original v7 claim/ACK/settlement and complete reads in
separate temporary databases; they do not enable runtime selectors or send FTD
commands. Include the full Python suite before handoff and Rust transport checks
when changing the wire/agent. Passing these checks is not live v7 acceptance.

See [Working-Version Plan](../working-version-plan.md),
[Grouped Additions](batch-additions.md) and [Multi-group Sessions](multi-group-sessions.md).
