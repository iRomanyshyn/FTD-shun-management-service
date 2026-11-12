# Working Version: Agreed Product Behavior

Agreed with the operator: 2026-10-20.
Status: approved target behavior and delivery plan; not a deployment procedure.

## Next delivery alignment — 2026-11-12

The operator accepted returning to bulk-import execution/confirmation and bounded
FPR acceptance, followed by integrated lifecycle checks, Emergency Purge and
working-release preparation. Keep the existing source-only deferred capabilities
and their remaining recovery/lab gaps distinct from the currently deployed v6.

**Team Cymru is a planned supplemental source**, explicitly reaffirmed by the
operator, not an idea to drop after selecting IPFire. Schedule it after the bulk
import slice. Fill missing IPFire ASN/network context through bounded background
bulk queries and a durable cache. Deduplicate across devices and views; batch
pre-existing misses as well as new ones, with bounded retries/provider-aware
refresh and no query from page rendering. Preserve provider attribution and
retrieval time. A Cymru registry country must not overwrite an IPFire country or
be presented as geolocation. Provider failure leaves existing useful context.

Retain Web/API/agent isolation and the dedicated metadata path; no credentials,
core-DB/control-socket access or blocking-policy authority is granted to the
provider component. This is a delivery-plan update, not an activated fallback.
See [IP Context](manual/ip-context.md).

Team Cymru supplement, v0.11.0 (2026-11-12): implementation/candidate validation
are complete and the operator explicitly approved persistent activation after
the initial review refusal. Only Web/metadata worker were updated. The worker uses bounded
DNS batches for missing IPFire ASN/name data, durable caching/retries and distinct
source/registration-country presentation. No page-triggered calls or changes to
blocking authority. Two real missing entries were filled on a temporary cache
copy; live enrichment supplements primary IPFire. See current status/log/manual for evidence
and the exact deployment boundary. This does not close remaining bulk recovery,
integrated lifecycle, Emergency Purge or release work.

Final full-group optimization, source0.10.2 (2026-11-12): deferred visits no longer
verify a final exact16 before END_PENDING. Bounded advisory scheduling preserves
intermediate-group verification and priority work; ordinary verified v5/v6 keep
their existing behavior. Tests cover16/17/32/48/64-address tails, 80-address visit
limits, urgent refresh/removal/protection and stop/pause/cancel. Bounded isolated
FPR acceptance used16 fresh TEST-NET addresses: one60.378s SSH visit,16 ADDs,
16 retained target preflights and one initial full read; its entire final group
was confirmed by the next automatic causal full read with zero ADD replay.
This is not a measured bulk-load speedup or persistent v7 cutover. General held-
epoch recovery remains unfinished. See status/log for cleanup and restoration.

Completed-handoff crash recovery, 2026-11-12 (source0.6.0, not activated): a
pre-END checkpoint binds the original visit; an exact completed agent journal
receipt can atomically finish the expired original LEASED handoff to awaiting
confirmation. The next causal full read confirms presence/absence. No old ADD is
replayed and no historical unknown/ATTENTION is released. General held recovery
and bounded real-device acceptance remain before the separate fresh-store cutover.
See manual/pending-restart-recovery.md.

Configured deferred mode, 2026-11-12 (source0.5.0, not activated): explicit default-off
API/client/agent capability now selects matched version7 and exact prepared deferred
storage. The configured factory binds the real strict client/deferred dispatcher,
controls and ordered workflows; old settings or wrong profiles never fall back.
Local binary API lifecycle confirms final pending groups on a new read without
creation attribution or repeated ADD. General crash/held-epoch recovery and
bounded real-device acceptance remain next before applying the separate lab overlay.

Deferred setup and pauses, 2026-11-12 (source-only0.4.0): the development initializer
can create a separate exact deferred profile, including ordered cleanup and both
independent pauses, without old-data conversion or runtime activation. Deferred
retry timing/discovery now skip operator-paused targets, avoiding extra retry-only
SSH visits. Confirmation, ordinary/manual reads and protected unblocking continue;
Resume still needs a new read. Configured matching transport/API composition,
crash/held-epoch recovery and bounded lab activation remain next.

Protection wording, 2026-11-12 (0.3.2): explain automatic unblocking, turning off
auto-restore and creating a new import in plain task language across Protected IPs,
IP notices, shared help and operator manuals. No policy behavior or API/agent
change. Contributor guidance now requires these outcome-based explanations.

Lost-terminal recovery, 2026-11-12 (source-only0.3.1): one bounded local query can
recover exact pending-v7 settlement after response loss, without replaying ADD
or opening SSH. Only a completed original session with exact retained ACK scope
can reach the unchanged atomic pending handoff and next causal confirmation.
Active/absent/foreign/malformed proof, lost stage ACK and persistence failure
retain uncertainty. No historical unknowns are resolved and no lab mode changes.
General crash/held-epoch recovery and configured fresh-store acceptance remain.

Initial settled-pending consent, 2026-11-11 (source-only0.3.0): new cleanup requests
can capture an exact awaiting target after its original SSH session settled.
Strict mutually exclusive running/settled descriptors support mixed fleets;
fresh consent never fabricates a live lease, renews ADD, replays unknowns or
silently switches mode after an intervening confirmation read. New-key cleanup
still retires maintenance and waits for complete causal observation. Current lab
is unchanged. Next compatible deferred recovery and deliberately configured
fresh-store composition/acceptance; original multiple-RUNNING guards remain.

Deferred cleanup increment, 2026-11-11 (source-only0.2.5): an accepted qualifying
RUNNING-ADD reservation now waits across settled-v7 handoff and the next complete
causal observation, then promotes exact urgent cleanup without another ADD.
Whole-scope/current-policy/uncertainty guards and original deadline remain;
initial already-awaiting capture, compatible deferred recovery and fresh-store
configured activation are still unfinished. Current lab remains0.2.4 Web/v6.
See manual/deferred-confirmation.md and status/log for actual validation.

IP usability refinement, 2026-11-11: one Unblock entry chooses ordinary or
wait-after-current-add review from complete local preflight **before consent**.
Blockers/invalid inspection never fall back, and confirmed/uncertain requests
never switch mode or key. Stop restoring remains policy-only. Hide redundant
single-device fleet controls; show operational consequences before technical
details. See [Operator Workspace](manual/operator-workspace.md#actions-and-help)
and status/log for actual validation and deployment.

Operator alignment, 2026-11-11: introduce independent import and automatic-
restoration pauses. Existing blocks/monitoring/removals/Protected-IP unblocking
continue; already claimed commands settle. Resume requires fresh relevant read
evidence and never clears recovery holds. Deliver version 0.2.0, mandatory future
delivery increments and a separate public application-source build ID; common
100-row top/bottom pagers and newest-first Queue presentation (FIFO execution
unchanged). Follow status/log for actual validation/deployment, not this plan.

Observed ownership increment, 2026-11-11: Shuns now annotates current maintenance
per device/IP, with a separately paginated **Unmanaged** view. Classification is
not detection/creation attribution, and historical imports do not imply enabled
maintenance. V2 observed rows/IP details prepare the existing frozen device-removal
review, not legacy immediate queue admission. Final consent and all execution
guards remain. This delivers the separate view, not rolling 24-hour correlation,
new adoption authority, Emergency Purge or deferred-v7 activation. See status/log
and manual/shuns-and-maintenance.md for validation/deployment scope.

Recovery UX increment, 2026-11-10: add explicit **Check and resume import**
inspection/guidance and known-lab host orchestration instead of an unactionable
unknown warning. Old outcomes remain unknown, a fresh complete read precedes
new currently eligible missing-target work. Current recovery remains host-assisted
with actual API/Web/agent quiescence; true online browser recovery needs a separate
proof-carrying coordinator contract, not Docker access granted to Web. See status/
log and manual/queue-recovery.md for actual deployment and validation scope.

Shuns browsing increment, 2026-11-10: server-side pages of 100 observations now
bound initial rendering and live replacements, including selected-page import
provenance. Protected/newest ordering and whole-dataset IP search remain. This
addresses browser lockup on long lists without changing device execution or
authority. See status/log for validation and deployment evidence.

Shared-session idle increment, 2026-11-10: a reproduced 15s SSH transport idle
disconnect during local group persistence/root checks is fixed in the agent.
Visit inactivity now fits its existing 120s/240s hard budget; no CLI/session/
IPC/quota extension, keepalive, reconnect/resend or v7 activation. Known unknowns
still need exact separate recovery decisions. Agent-only lab rollout and bounded
acceptance are recorded in status/log: a real 28-ADD session (16/12) crossed the
old failure boundary and actually settled, preserving all original unknowns.
No whole-list speedup is presumed; deferred-v7 activation remains unfinished.

Deferred retry-child replacement increment, 2026-11-10: exact retained tracked-v7
pre-write-DEFER followed by cancellation can now permit a new child under original
confirmed-absence lineage. New causal complete absence/read/lease/current-policy
checks, original backoff/hourly limits and fresh IDs remain; original outcomes
and requests are untouched. Missing/ambiguous/acknowledged/unknown evidence still
refuses. Actual claim-visit audit survives retention even across a different
admission visit. Source-only/default disabled; no live selector/schema/deployment.
Next ordered pending capture/promotion, compatible deferred recovery and explicit
fresh-store configuration before bounded lab activation. See current status/log.

Exact pre-write recovery increment, 2026-11-10: separate explicit offline v6
profile now validates 17–64 original claims with exactly one final expired/
cancelled typed pre-write DEFER and otherwise VERIFIED/NOOP outcomes. It retains
all outcomes/authority, requires actual process quiescence, fresh whole-DB review
and checked exclusive backup, and atomically records a distinct immutable marker/
receipt before exact same-epoch release. No old RPC is replayed. Real-copy
rehearsal and full 3537-test regression passed. Explicit offline lab apply at
11:58:02.571Z released only original epoch 2921 with all outcomes unchanged.
New compatible API resumed the original import after a causal complete read;
epoch 2922 actually settled with 24 VERIFIED ADDs. Original task/authority and
unknown history remain, no reset/reimport. SQLite contention remains observable.
Consult current status/log for backup/profile compatibility and bounded evidence.
V7 stays off; this v6 repair does not complete deferred-v7 recovery or activation.

Deferred lifecycle increment, 2026-11-10: ordinary standing-policy restoration
now accepts later causal absence after a validated OBSERVED_PRESENT, retaining
normal 300-second/three-per-hour bounds and all current authority/protection/
uncertainty checks. Only strictly earlier known absence in that exact scope may
be superseded for scheduling by later proven presence; no outcome or old command
changes. Ready device/fleet cleanup explicitly blocks awaiting confirmation, then
can use fresh atomic whole-scope retirement/REMOVE consent after confirmation.
Ordered inspection gives readable refresh/review guidance and no token while
pending. Source-only; current v6 lab/import unchanged. Next ordered pending capture,
deferred recovery, claimed/deferred child replacement and configured fresh-store
activation/acceptance. A newly observed v6 epoch 2921 hold has 32 VERIFIED and one
claimed pre-write-DEFER then CANCELLED; existing recovery refuses this mixed
scope. Preserve evidence and implement compatible recovery, never force release.

Continuous deferred scheduling increment, 2026-11-09: source-only/default-disabled
`DeferredContinuousDispatcher` now schedules causal confirmation after handoff and
fresh reads after confirmed-absence backoff, without waiting for the periodic
interval or sleeping inside SSH. Bounded advisory scans never grant permission;
all worker/root/current-policy/lease/uncertainty checks and scheduler limits remain.
Pending settlement never satisfies refresh demand or resets freshness. Existing
Queue UI now distinguishes neutral pending/known observation/retry waits from
actual unresolved attention. Current configured runtime/selectors and original
v6 lab import remain unchanged. Next complete ordered managed/fleet cleanup,
deferred recovery, later disappearance restoration and claimed/deferred child
replacement, then deliberate fresh-store configuration and bounded lab acceptance.

Explicit worker increment, 2026-11-09: source-only default-disabled
`DeferredParallelSynchronizer` now composes causal all-group confirmation before
publication, bounded guarded fresh-retry discovery and final settled-v7 handoff.
Intermediate/priority groups retain strict verification; the final pending group
does not falsely reset freshness or increase verified counts. Real cancellation
drain and successor-lease fencing are tested. Original configured v5/v6 paths,
current lab data/runtime and public selectors stay unchanged. Next connect
continuous confirmation/wait scheduling and public status/UI, complete ordered
managed/fleet cleanup, deferred recovery and later disappearance restoration,
then bounded separate-fresh-store lab acceptance. Do not reset/reimport the
original task or claim live v7/throughput acceptance from synthetic visits.

Fresh retry increment, 2026-11-09: source-only `PendingRetries` admits new jobs
after exact settled CONFIRMED_ABSENT results under current original standing
consent and all protection/cancellation/root/lease/uncertainty guards. Old attempts
are not requeued or relabelled. Immutable provenance binds new IDs to original
absence and the current complete read/visit; 5→10→20→40→60s backoff and a rolling
12/device/IP/hour cap expose typed scheduling waits. Same-read reuse requires
identical full evidence and existing freshness; cancelled child replacement is
limited to never-claimed work. Unknowns remain held. Retention preserves linked
jobs/requests/audits/visit claims. No live DDL/deployment/v7 selection or original
import change. Next compose matched worker/priority/removal/UI behavior and later
disappearance restoration, then bounded live acceptance in a separate fresh DB.
See manual/deferred-confirmation.md and current status.

Fresh queue handoff increment, 2026-11-09: source-only `PendingExecution` now
atomically retains original settled-v7 scope, transitions exact jobs/attempts to
AWAITING_CONFIRMATION and releases that original lease. A current causal read
settles presence/known absence and captured cancellation without inventing
creation or retrying the old command. Progress/retention distinguish pending
confirmation and known-absence retry work. Initialization is fresh-empty only,
not a converter or live schema change; current coordinator/configuration still
refuse this profile/v7. Next implement current-policy/backoff fresh admission
and matched worker/priority/UI/ordered-removal integration before bounded lab
acceptance. No reset/reimport of the running original task is part of this work.

Durable evidence increment, 2026-11-09: source-only `PendingConfirmations` now
retains exact original settled-v7 attempt/claim/ACK scope and classifies its first
causally later complete observation after a restart. Present/confirmed absent are
evidence labels, not verified creation or a retry/release capability. Immutable
optional storage requires explicit paused/quiescent initialization; no live schema
or mode was changed. Original jobs stay RUNNING/fenced and current composition
still refuses v7. Next integrate distinct queue/attempt states, safe settled
release, current-policy/backoff fresh attempts and UI/priority/protection/cancel
behavior before activation. See manual/deferred-confirmation.md.

Transport foundation, 2026-11-09: tracked-v7 END_PENDING can end acknowledged
scope without a final read, returning a distinct non-success value only after
strict actual settlement. Shared Rust/Python vectors and synthetic transports
are implemented. Current configuration/worker admission still refuses v7; no
deployment/activation or durable job/lease release follows from this code.
Complete the explicit pending profile and causal full-read classification below
before enabling it. See manual/deferred-confirmation.md and current status.

Recovery increment, 2026-11-09: an explicit extended tracked-v6 offline profile
is implemented for 17–64 system ADD claims. Keep original outcomes and all
quiescence/full-review/backup/fresh-read barriers. A separate immutable marker
binds compact complete evidence without raising the old 16-KiB receipt bound;
old tools/writers must refuse unsupported scope/profile. The lab's epoch 2600
(16 verified/10 unknown) passed actual-copy rehearsal and a fresh offline
decision, retaining every old outcome. The original import resumed after a
post-receipt complete read. See status for bounded settlement evidence, not an
assumption that any implementation or host restart resolves other holds. Local
SQLite contention prevention and durable first confirmation remain follow-ups.

Local result-storage slice, 2026-11-09: ACK/ADD-result callbacks now have bounded
numeric BUSY retry only after proved local rollback (or failed pre-write BEGIN).
Real competing-writer tests cover both paths and retain one original session/
command per target. Keep original session time budgets, per-target current
checks, partial-result preservation and fences. Unknown commits, lost ACKs,
expired/foreign leases and unknown device writes never qualify. See current
status for final validation/deployment rather than assuming this feature is
already enabled or prevents every storage hold. Durable first confirmation and
remaining measured root/claim overhead are still the next product work.

Multi-group execution increment, 2026-11-04: an explicit matched tracked v6
profile permits 240-second/64-attempt/256-command sessions with groups of 16.
Complete verified intermediate observations allow bounded new queue segments
and fresh admission without relogin, retaining every claim's current guards and
original evidence/deadline. V5 remains default and unchanged. Consult current
status and manual/multi-group-sessions.md for validation/deployment; no speedup
is presumed. Cross-session first confirmation/retry remains a separate unfinished
contract. Extended offline recovery above has its own narrower evidence rules,
not a general recovery guarantee supplied by these session bounds.

Capacity correction, 2026-11-04: policy admission/capture/restoration still had
a 65,536-IP complete-evidence cap despite the matched 200,000-entry reader and
100,000-pair import target. Align these internal guards to the reader's shared
constant, retaining exact bounds and all authority/time/protection/uncertainty
checks. Synthetic large evidence is not live capacity acceptance. This prevents
a deterministic future large-import stop; it is not a throughput improvement.
Continue with the durable first-confirmation/bounded-session work below, not
another source-input limit increase or reset of the original lab import.

Current batching follow-up, 2026-11-03: tracked v5 increases pending capacity to
16 and combines final group verification, visible snapshot refresh and terminal
session completion in one full read. The 120-second / 16-mutation bounds remain;
v5 staging has a shorter explicit 30-second bound and corresponding reserve.
Root/protection/preflight/lease checks and priority/cancellation remain. See current
status for tests and rollout, not a presumed throughput gain. Next design durable
known-absence outcomes so an acknowledged but unobserved first ADD can be retried
under current managed intent after actual settlement, separately from unknown
writes. Existing verified-managed disappearance restoration remains available.
Do not claim cross-session first-confirmation/retry is implemented yet.

The later explicit quiescent reconciliation supplies reviewed recovery of an
existing unknown managed ADD epoch after all original executors are stopped.
It preserves old unknown outcomes and requires a new complete read before
current managed intent can produce a fresh attempt. This is not automatic
cross-session first confirmation or retry without a reviewed quiescence decision.
The same original lab import resumed on matching v5; see current status/log.

Next delivery slice for the requested import-completion model:

1. Retain acknowledged-but-unconfirmed additions durably, bound to the original
   attempt/group, current managed authority and actual completed agent session.
   Display sent/awaiting verification separately from verified progress.
2. Use one causally later complete refresh to classify those exact addresses as
   present or confirmed absent; publish that same snapshot, never an extra
   per-address post-read. Partial/stale/failed reads classify nothing.
3. Retry only confirmed-absent, safely settled attempts with a fresh job under
   still-current managed consent, protection, cancellation and capped backoff.
   Retain previous attempt evidence. Lost ACK/session proof is uncertainty, not
   the same retryable condition; no automatic replay of unknown writes.
4. Increase useful session capacity under an explicit matched profile, with
   intermediate shared full reads renewing freshness and command-boundary
   interactive priority. Measure real throughput, rather than only raising caps.

This slice changes durable execution/result contracts and must be implemented
with corresponding schema/profile, queue and recovery tests. It is the next
product optimization, not a requirement for a legacy-dev database converter or
permission to recreate the original running import.

Grouped-verification increment, 2026-11-03: the operator requested batch ADDs
followed by a shared complete read. The gated tracked-v4 agent/client foundation
implements pending acknowledgements and an explicit verification of at most eight
targets, keeping per-target preflight and all existing mutation/session bounds.
Queue integration now retains pending evidence and flushes for priority/protection/
cancellation/drain, with an explicit matching managed-only setting. Consult current
status for actual rollout/acceptance; defaults remain off. Do not substitute generic later
baseline presence for verified creation. See [Grouped Additions](manual/batch-additions.md).

Execution-performance follow-up, 2026-11-03: exact root decoding is cheaper
without skipped members/cached authority, but measured import throughput remained
around 7.5 addresses/minute. The coordinator now skips its five-second empty-defer
delay only after successful current-epoch terminal progress and strict settlement;
no-progress/failure backoff, fresh session/lease admission and uncertainty holds
remain. Consult current status for bounded rollout measurements; this is not
whole-list acceptance. Fixed agent CLI-phase duration/count aggregates are now
implemented to distinguish target preflight, ADD and complete-read cost, without
arguments/raw output or using diagnostics as execution proof. See current status
for validation, lab rollout and measurements before selecting the next optimization.
Measured full sessions still spend about 25s in local work, including 13s claiming
nine jobs. A disposable full-claim profile confirms one full original-root scan
and eight full profile validations. Literal allocation reductions are implemented;
see current status for validation/rollout and actual effects before selecting
further equivalent SQL improvements. No original-root/current authority/protection/
uncertainty check may be skipped. CLI command wall times are not FTD CPU.
Do not make another input-capacity increase or remove verification to claim speed.

Latest execution checkpoint, 2026-11-03: exact per-call source framing reduces
full-root verification locally without changing its bytes/checks. Actual restart
acceptance exposed and fixed observed-prefix starvation: indexed same-device
presence exclusion now precedes the bounded candidate scan, retaining snapshot/
authority/uncertainty/quota/cutoff rules. Original import automatically resumed
without a hint or new consent; 23 VERIFIED in 207.95s, no unknown/hold. This remains
only ~6.64/minute, with semantic ADD/verification around five seconds per target.
Next prioritize a reviewed compatible bounded execution/batch improvement with
truthful per-target results, cancellation/interactive priority and retained
uncertainty. No whole-list/load/production acceptance is implied. See current
status/log for final image, compatible rollback and preserved original state.

Execution-performance increment, 2026-11-03: transaction-boundary obsolete-work
validation removes repeated per-candidate profile scans without dropping current
eligibility/root checks. Bounded per-session diagnostics separate local phases
from agent-call time. API-only lab rollout continues the original task; observed
24-result samples were 5.11/minute before and 5.95/minute after, not isolated load
benchmarks. This remains too slow for large imports. Next distinguish agent
login/full-snapshot time from per-target CLI/verification and reduce avoidable
session/refill overhead. Do not solve throughput by renewing expired authority,
replaying unknown writes or dropping verification/interactive priority. See the
current status/log for exact validation and retained-data evidence.

Execution-performance checkpoint, 2026-11-02: after an operator-caused pre-command
network outage, the managed runtime automatically reconnected and continued its
original 32,425-pair import without another restart, hint or confirmation. A live
sample verified 24 additional targets in 260.25s (5.53/minute), with no new unknown
results; complete sampled SSH sessions verified seven operations each. This is
not whole-list load acceptance, and that rate is not adequate for large imports.
The immediate next delivery task is to profile local admission/claim/settlement,
SSH command/verification time and between-session work separately, then optimize
the measured hot path while retaining protection, verified results, whole-task
cancellation and interactive priority. Re-measure actual throughput and status
responsiveness on the same lab workload; raising input limits alone is not enough.

Delivery-policy update, 2026-10-30: this is still an unreleased internal lab project
on the operator's desk FPR1010, with no production use. Ordinary in-scope lab
development/deployment/bounded tests do not need per-fixture approval ceremonies.
Use a clean separate dev database while archiving old test state; legacy conversion
and cross-dev-version key compatibility are not prerequisites for the working
version. Prioritize a complete usable path and lab feedback. The first explicitly
designated real GitHub tagged release starts released-data upgrade/compatibility
obligations. Core security, verification and scoped destructive-action safeguards
remain. This update supersedes conflicting older planning below; it does not
change which runtime capabilities are currently implemented. See
[Development](manual/development.md#lab-first-development-policy).

This records the sequential product discussion. The priority is a usable working
version, with usability refined during actual use. Bulk managed addition and
restoration belong in that version. Email is lower priority. The implementation
does not yet provide all behavior below; consult [Project Status](project-status.md).
The [architecture amendment](architecture-and-security-design.md#working-version-product-alignment--2026-10-20)
establishes precedence over conflicting older target decisions while preserving
the credential, typed-operation, verification and authentication boundaries.

## 1. Managed and unmanaged

First-scan checkpoint (2026-10-30): changed confirmation in the executable managed
profile now requests a selected-device advisory fresh scan automatically, without
an extra refresh click or baseline wait. Coalescing retains latest-read freshness,
minimum spacing, manual/unblock priority and all existing mutation guards. The
policy-only composition/replays/unchanged grants do not schedule work. Current
validation/deployment evidence is in project status and the development log.

Live checkpoint (2026-10-30): the desk lab now uses the clean v2 profile and
explicit managed overlay. One new TEST-NET target completed VERIFIED creation,
controlled disappearance, automatic restoration and exact v2 retirement/removal;
old authority replay did not re-enable it. Old DB/backup/rollback images remain
retained, with no credential/pin/network changes. See current status/log for
acceptance evidence; multi-device/load, recovery and Purge are not covered.

Executable composition checkpoint (2026-10-30): `ftd-shun-dev-init` now prepares
a complete separate empty v2 store without overwriting/converting old state;
optional transfer is limited to validated Protected-IP settings. The explicit
`continuous-managed` API/Web selector connects existing concurrent standing
consent, exact profiled ADD scope, bounded continuous discovery/restoration and
ready/ordered cleanup through one owner. The opt-in managed-lab overlay selects
`managed-v2.db`; legacy remains default and startup never initializes. See
[Fresh Working-Version Lab](manual/fresh-development.md) and current status for
actual deployment/acceptance evidence. Automatic uncertainty recovery, Emergency
Purge, multi-device/load acceptance and release packaging still remain.

- A manually added service target is always maintained until explicitly removed.
  There is no one-time-add option in the working-version workflow.
- An observed device/IP without active service authority is unmanaged. Observation
  alone does not establish who created it: FTD output cannot distinguish automatic
  detection from an external administrator's command.
- Managed targets are restored after confirmed disappearance, including following
  a reboot. A missing entry is not itself evidence that a reboot occurred.
- Explicit service removal permanently stops maintenance in the selected scope.
- Explicitly importing an already present unmanaged IP adopts it into maintenance
  on the selected devices. No redundant ADD is needed and no historical service
  creation is invented. Adoption is an intentional user action, never a startup
  conversion of observed state, old imports or history.
- Offering to restore disappeared unmanaged entries is deferred. The first
  working version automatically restores managed targets only.

## 2. Devices, identity and credentials

Nonempty transition checkpoint (2026-10-30): a separate read-only inspector now
streams recognized retained legacy source state, binds full public inventory and
future scope/concurrency, reports operational blockers and supports five-minute
original-digest reinspection. It never converts old receipts into v2 authority,
retires policy, resolves uncertainty or changes storage/runtime. Migration ready/
available and semantic-conversion validation remain explicitly false. The actual
archive/original-key reservation contract, atomic checked conversion/rollback and
separately authorized activation remain. See
[Nonempty Transition Inspection](manual/migration-inspection.md).
Under the later lab-first policy above, these converter tasks are optional/deferred,
not prerequisites for a fresh working lab profile.

Configured observation checkpoint (2026-10-30): the private API now has explicit
default-legacy process selection on already prepared exact fenced storage,
strict full public-inventory/retained-device matching and a non-executing
`--check` path. Semantic configuration is frozen/rechecked before lifecycle start;
no upsert, migration, admission/promotion capability, ADD or lab activation follows.
Explicit clean-profile setup, deliberate connection-metadata handling, broader write
configuration and executable lab acceptance remain separate work; nonempty legacy
conversion is no longer required. See
[Configured Observation Runtime](manual/configured-runtime.md).

Keep device configuration outside the Web UI. `.env` points to `devices.json`;
the inventory contains stable internal IDs, display names, connection addresses
(IP or DNS), ports, enabled state and pinned SSH host-key configuration.

SQLite links observations, history and managed authority to stable device IDs.
Changing a connection address preserves those links. Configuration is reloaded
on restart. Address changes do not implicitly replace identity or trust a new
SSH host key. A temporarily missing/unavailable device is not permission to erase
its history or maintenance/cleanup obligations.

Every device explicitly supplies its SSH login and its own password-secret
reference. There is no shared-default credential fallback. Actual FTD passwords
are readable only by the agent; Web/API must not receive them. Do not place
password values in the inventory, database, tracked files or application logs.
Credential mapping is agent-owned; the lower-privilege services receive only the
public inventory projection, not a credential-loading interface or secret mounts.

Planning target: up to 10 configured FTDs, with up to 4 processed concurrently by
default and configurable concurrency. Each device has one serialized command
stream. Failure/reconnection on one device must not stall unrelated devices.
These are product planning targets, not validated FTD hardware capacity claims.

Transport prerequisite implemented 2026-10-22: the Rust agent now supports an
explicit 1–10 fixed connection-worker limit (default 1), with one nonblocking guard
per device/management address and no accepted backlog behind active workers.
Peer UID, fixed wire formats, existing feature gates and operation/session limits
remain unchanged. This does not supply independent API leases or end-to-end
parallel/continuous scheduling; no lab setting or new fixture was activated.
See [Agent Connection Concurrency](manual/agent-concurrency.md).

Fenced per-device API lease/queue primitives are now implemented on an explicitly
initialized optional developer profile (2026-10-22): immutable configured scope,
concurrent owner limit, increasing epochs, live-deadline checks across shared
admission/claim/results and retained expiry attention without stealing. Global
writers are excluded. An internal default-disabled parallel round coordinator now
runs actual independent bounded sessions/shared queue results and drains current
RPCs on cancellation. A separate internal continuous lifecycle now supplies
independent read timing/coalesced demand, between-poll device sessions and
scoped REMOVE priority. Application/API/Web integration, real transport acceptance
and automatic quiescence-backed recovery are still pending;
no profile or worker is activated by startup or deployed environment settings.
See [Fenced Device Leases](manual/device-leases.md).
See [Parallel Device Rounds](manual/parallel-rounds.md) for the implemented runner,
per-device discovery budgets, shutdown guarantees and remaining activation gaps.
See [Continuous Dispatch](manual/continuous-dispatch.md) for the explicit internal
lifecycle, independent countdowns, priority rules and unchanged deployment gates.
An opt-in [local settlement receipt](manual/cycle-settlement.md) now attests normal
cleanup/guard-release/worker-idle ordering; continuous execution requires it.
Legacy clients remain default and no runtime is activated. This does not resolve
remote quiescence or historical uncertain attempts.

Browser integration checkpoint (2026-10-23): an explicit per-device status/demand
projection, BFF field allowlist and renderer now preserve independent pending
counts/deadlines, held warnings and concurrent phases. The refresh button remains
usable while other FTDs work; only actual data/result revisions reload content.
This does not select the controller in API startup or provide v2 admission/cleanup,
retention ownership, a legacy migration or live activation. See
[the browser contract](manual/continuous-dispatch.md#browser-projection-contract).

Lifecycle checkpoint (2026-10-23): the internal continuous dispatcher now owns
one asynchronous maintenance task for ordinary expiry and evidence-aware daily
retention, drained together with device work on shutdown. This does not select
the runtime in the deployed API, enable authority or resolve old uncertainty.
See [Continuous Runtime Maintenance](manual/continuous-maintenance.md).

API checkpoint (2026-10-23): explicit developer factory composition now connects
the continuous lifecycle/status/demand to actual API/BFF routes, with existing
schema/settings/transport preflight, no startup initialization and honest v2
metadata. Its initial surface supports observations/preview and Protected IPs,
while explicitly refusing unavailable managed/import/manual mutation workflows.
ADD remains off; there is no deployed environment selector, inventory reload or
lab activation. This is not the completed bulk-managed release. See
[Restricted Continuous API Composition](manual/continuous-api.md).

Policy-view checkpoint (2026-10-23): that explicit composition now has dedicated
v2 read-only 100-row pages/exact selected reads and one-target policy-only
stop-maintaining. The Web freezes policy version/revision/actor/session/key;
original-key retry never retires a newer grant. Presence, VERIFIED creation,
NOOP and retained failed/unknown evidence remain distinct. This does not admit
ADD/imports, combined device removal or automatic recovery, and does not activate
the runtime/migrate the lab. See [Version-2 Policy Views](manual/bulk-policy-views.md).

Removal checkpoint (2026-10-23): an internal default-false v2 coordinator now
atomically retires ready targets and admits one whole-scope shared REMOVE request,
using existing immutable storage and actual fenced continuous execution. Separate
readonly single/fleet scope inspection is available in the developer API. Pending/
failed/unknown work conflicts instead of being cancelled or silently converted
into ordered waiting; no removal POST/Web control or lab activation is supplied.
Captured RUNNING-ADD ordering and general concurrent admission remain. See
[Version-2 Ready-Scope Removal](manual/bulk-ready-removal.md).

Confirmation checkpoint (2026-10-23): dedicated v2 single/fleet Web reviews now
freeze scope/action/key/session/expiry and submit to distinct private POSTs only
with independent explicit API/Web factory capabilities (both default-false).
Strict 202 receipts describe admission, not device success; lost replies permit
only original-key retry. No environment/runtime selection, lab activation or
ordered RUNNING-ADD cleanup is supplied. See
[Version-2 Removal Confirmation](manual/ready-removal-confirmation.md).

## 3. Bulk import and cancellation

Ordered-cleanup checkpoint (2026-10-23): a separate local read-only preflight now
classifies the complete v2 single/fleet scope, exact owned RUNNING ADDs and explicit
blockers, with original claim/epoch/deadline evidence and a separate observational
digest. It never admits/removes/retires/reserves work, and does not change the
ready-only confirmation. A separate explicitly migrated, default-off internal
coordinator now atomically retires/reserves the whole scope, retains immutable
receipts and predecessor/request/claim evidence, and supports local revocation and
shared maintenance expiry without device work. Whole-scope promotion/attention,
original-TTL capacity transfer, distinct ordered consent and feature activation
remain pending. See [Ordered Reservations](manual/bulk-ordered-reservations.md) and
[Ordered-Removal Preflight](manual/bulk-ordered-preflight.md).

Promotion checkpoint (2026-10-24): a separately migrated, default-off internal
coordinator now waits for original ADD/session settlement, transfers the whole
reserved scope to one original-key shared REMOVE delegation with unchanged TTL/
accounting, or retains ATTENTION without device work. Existing continuous ownership
can explicitly compose it; incomplete tickets/non-strict sessions cannot execute.
No ordered Web/API consent, runtime selector, lab migration/activation or actual
transport acceptance follows. See [Ordered Promotion](manual/bulk-ordered-promotion.md).

Private API checkpoint (2026-10-24): distinct default-off fixed device/fleet
ordered reservation routes now require the compatible owning promotion capability
and existing exact profile. Strict original scope/predecessor/digest/actor/TTL
validation delegates once; separate read-only current status includes original
scope, predecessor and delegated REMOVE outcomes, with verification only after all
original jobs are VERIFIED. Owner/Admin waiting revocation stays available under
pause/disabled admission and never resumes policy or resolves attention. Frozen
Web consent/status remains next; no new runtime selector, migration, lab feature
activation or acceptance follows. See [Private Ordered API](manual/ordered-removal-api.md).

Ordered Web checkpoint (2026-10-24): separate frozen device/fleet preparation and
confirmation now bind original scope/predecessors, actor/CSRF session, UUID/digest
and TTL behind independent literal default-off Web/API capabilities. READY/BLOCKED
preflight is informational only; no token/fallback/rebase. A durable original-key
status permalink shows complete original owner/scope/deadline, ADD outcomes,
attention and all delegated REMOVE job results; only all VERIFIED implies verified
removal. Local CSRF/typed-IP owner/Admin waiting revocation works while paused or
admission-disabled, conflicts after delegation and never resumes policy. Metadata
updates preserve frozen confirmation and dirty local-status forms without device
refresh demand. Scope/unknown-reply/race checks and actual BFF/API/shared fake
execution are covered; no runtime selection, migration or lab activation follows.
See [Ordered Web Controls](manual/ordered-removal-web.md).

Import-preparation API checkpoint (2026-10-26): fixed v2 private create/list/page/
proposal/cancel-preparation routes now use the correct bulk classifier and shared
UTC clock on existing exact v2/fenced/journal storage. Up to 10000 addresses on ten
devices/100000 pairs can be frozen, recovered by owner and inspected in 100-row
pages without creating policy or device work. Runtime reports/cancellation verify
the entire original digest in <=100-row chunks, so same-count substitutions refuse
rather than rebase scope. Strict actors/fields/UTF-8/devices, original expiry,
owner/global capacity and draft-only cancellation remain independent of captured
roles or any later confirmed import. No initialization/pruning, policy confirmation,
Web workflow, runtime selector or lab activation follows. Next is frozen v2 browser
review, independently gated atomic standing confirmation and admitted-import
cancellation. See [V2 Preparation API](manual/bulk-preparation-api.md).

Preparation Web checkpoint (2026-10-26): a distinct narrow-capability workspace
now saves private drafts, recovers owner references, shows frozen 100-row reports
and conspicuous source/protected exclusions, and revokes only unconfirmed drafts
with CSRF/current identity. A read-only exact v2 policy proposal binds the original
digest/metadata/revisions/manifest and a stable distinct operation key across
restart/pagination; no recurring consent or confirmation submission is present.
Strict replies, unknown-create recovery without automatic retry, transient input/
device preservation, owner/role boundaries and maximum 100000-pair Web scope are
covered. Legacy navigation remains when the v2 capability is absent. No schema,
runtime selection or lab activation follows. Next remains independently gated
atomic v2 standing confirmation and admitted-import cancellation. See
[V2 Preparation Web](manual/bulk-preparation-web.md).

Suspended confirmation checkpoint (2026-10-26): independent default-false API/Web
factory capabilities now connect exact recurring consent to one whole-scope v2
policy transaction. API enablement also requires immutable trusted eligible-profile
device IDs in the existing sealed scope; this is external eligibility attestation,
not executable ADD permission or credential access. The unchanged coordinator
requires suspended desired execution, no active sessions/leases or pending/
uncertain work, exact original scope/revisions/classifications and unpaused new
authority. Busy sessions conflict, never auto-retry or interrupt. Frozen
subject/CSRF-cookie reviews, typed accepted count, explicit recurring consent,
post-I/O expiry and same-key unknown-response recovery preserve the exact grant.
Owner historical receipt lists/100-member pages survive restart/draft pruning;
replay never re-enables retired policy or implies current device success. No
queue/hint/resume, migration, runtime selector or lab activation. Concurrent
standing admission, admitted-import cancellation and executable configured
rollout remain. See [V2 Standing Confirmation](manual/bulk-standing-confirmation.md).

Cancellation surface checkpoint (2026-10-26): fixed private v2 review/member-page/
cancel/current-status routes and frozen Web consent now reuse the existing atomic
whole-root cancellation/shared-result settlement contract. Exact five-minute
digest/accepted-count/member pages, actual current owner-Operator/Admin, CSRF/session
and post-I/O expiry prevent scope rebasing. Applied/adopted/existing maintenance
stays; owned unsent work stops and RUNNING ADDs settle without interruption,
REMOVE, re-enable or uncertainty resolution. Local current-status permalinks
distinguish immutable initial receipts from later outcomes/attention and survive
restart/draft pruning. Revocation needs no new admission gate and remains available
during pause; no initialization/migration/activation follows. Concurrent standing
admission and configured executable rollout remain. See
[V2 Cancellation Surface](manual/bulk-cancellation-surface.md).

Concurrent admission checkpoint (2026-10-26): a separate opt-in coordinator/private
route and independent default-false API/Web capabilities now admit whole original
scopes alongside healthy independent sessions/jobs. Selected device fences/unknown
outcomes and accepted-pair pending/failed/unknown/unattributed work, captured
cancellation and ordered holds remain barriers. Original revisions/classification/
authority, expected suspension, consent/count, expiry/capacity and end-of-write
fence/clock checks stay atomic. No subset/rebase, lease mutation, rearm, queue/hint/
resume or uncertainty resolution. Exact fenced historical receipts retain actual
suspension and original-key semantics; Web freezes mode/suspension and requires
both capabilities. Later enabled work needs a strictly newer complete read,
including the equal-millisecond boundary. Original suspended/quiescent confirmation
remains separate. No lab activation/executable runtime selection. See
[Concurrent Standing Admission](manual/bulk-concurrent-admission.md).

Target up to 100,000 IPv4 addresses in one import (operator increase, 2026-11-02),
with explicit device selection and a retained 100,000-pair total bound. One device
can therefore receive 100,000 addresses; ten selected devices fit 10,000 each.
Input supports 16 MiB UTF-8 / 100,000 lines/rows, including structured Cisco
show-shun exports with source-only extraction. Storage/report/manifest bounds and
matching complete snapshot reads must agree; a larger text field alone is not
sufficient. A real large-list execution/throughput test remains separate.

Preview and confirmation identify accepted, duplicate, invalid and actively
protected addresses. Invalid and protected inputs are skipped with a conspicuous
report and Web notification; they do not reject every valid member. Confirmation
binds the exact accepted scope and exclusions. Concurrent changes produce an
explicit conflict, not a silently changed acceptance list.

Accepted targets establish durable maintenance, rather than thousands of short-
lived one-time requests. Feed executable work into a bounded queue in portions;
do not materialize an unbounded job backlog. Progress and restart recovery must
preserve the original batch, target identities and author. The preview/admission
confirmation can expire without expiring an already admitted standing policy.

Cancelling an import cancels its unexecuted portion. Targets already added or
adopted remain maintained, and the result explicitly reports retained versus
cancelled work. An in-flight command must settle and be checked before its result
is classified. Cancelling an import does not roll back its completed additions.

Mass removal of an arbitrary selected address list is deferred. Individual
removal and the separately confirmed Emergency Purge cover initial removal flows.

## 4. Protected IPs / whitelist

Use exact IPv4 addresses only; CIDR/subnet rules are deferred. Users can add,
remove and temporarily disable entries while keeping disabled entries visible.
Disabled entries provide no active protection and should remain visually distinct.

Enabling protection permanently retires matching managed maintenance and cancels
its unstarted additions/restorations, then requests removal of matching observed
shuns on the relevant devices. A running ADD must settle before ordered removal.
While protection is active, newly observed matching shuns are removed again.

Disabling/deleting protection never reactivates the former managed policy. FTD
may subsequently shun that address through its own mechanisms; without a new
explicit managed action it remains unmanaged. This replaces the older design
that retained enabled maintenance behind protection and resumed it on weakening.

## 5. Scheduling, refresh and priority

Queued work continues between polling intervals. There is no artificial minute-
long pause between mutation batches. Keep command verification, bounded sessions,
timeouts and orderly reconnection; new batching limits require measurement and
validation rather than simply deleting the existing agent's safeguards.

The baseline full poll remains configurable with a five-minute default. Manual
full refreshes retain their configured minimum spacing, initially 60 seconds.
Those reading intervals must not impose a global write cooldown or serialize
independent devices. Web progress/status polling reads local state.

Interactive refresh and quick unblock requests take the next appropriate slot
after the current operation **and required verification**. Manual/protected
removals and Emergency Purge must not wait behind an entire bulk ADD list.
Multiple interactive requests are ordered/coalesced appropriately; conflicting
user intentions are not silently overwritten. Do not interrupt an in-flight CLI
operation or its verification to service another request.

The refresh button is always available to submit demand. Show a pending/countdown
indicator on the status trigger until the requested information is refreshed;
repeated clicks join demand rather than pushing its deadline farther away.
Update displayed data after completion without losing user input. Distinguish
waiting, reading, device errors and verified fresh data; an elapsed timer is not
proof that a refresh succeeded.

## 6. Recovery and conflicting users

An unavailable device waits for automatic recovery while healthy devices continue.
Keep its pending intent/progress and expose the wait/retry condition in status.

After a lost command response, automatically obtain valid device evidence and
converge to the still-authorized desired state. Routine network uncertainty must
not require an offline administrative ceremony. Preserve the original uncertain
attempt and audit; do not relabel it VERIFIED or blindly resend a lost command.
Before subsequent device work, establish that the earlier RPC/session cannot
still execute, obtain a complete successful fresh observation, and recheck current
intent/generation, protection, cancellation and purge scope. Timeout, partial
output or an unverified/stale snapshot cannot authorize a new mutation.

This requires a new reviewed reconciliation/attempt contract. The current
permanent-latch implementation is not automatically relaxed by this document.
The first implemented recovery slice (2026-10-30) retries only locally proven
socket failures before the very first BEGIN send, with audited live-epoch release
and capped backoff. A subsequent exact no-command terminal extension now also
recovers failed SSH opening before an executor exists. The 2026-11-02 settled
read-only extension additionally retries initial/priority/final read failures
only with exact post-handler completion proof, no mutation steps/claims and
successful cleanup. Missing proof, old holds, later mutation-session errors and
lost ADD/REMOVE replies retain their holds. A later tracked-session completion
journal adds exact lookup for a lost read-only receipt in the current live epoch;
no startup repair, old held-state release or mutation replay follows. See
[Bound Session Completion](manual/session-completion-lookup.md),
[Settled Read-Only Recovery](manual/read-failure-recovery.md) and
[the bounded retry contract](manual/continuous-dispatch.md#failure-backoff-and-shutdown).
Retained legacy abandonment/isolation decisions and uncertainty must be preserved
through an explicit compatibility/migration plan; never silently erase receipts
or release old exclusions to obtain automatic recovery.

When users submit contradictory actions on changed state, show a conflict with
the current state and require a refreshed review/confirmation. Do not silently
make the last stale submission win. Preserve authorship and distinguish admission,
in-flight work, observed presence and verified outcomes.

## 7. Web layout and multi-device correlation

Use separate Managed and Unmanaged tabs. Managed shows maintenance and execution
state, including pending restoration; do not present an absent maintained target
as an active observed shun. Retain the existing Protected IPs and history flows.

Keep detailed execution/freshness information in the pop-up status/queue panels.
Their triggers visibly indicate pending work, countdowns, failures and conditions
needing attention. Users should notice important changes without opening a panel.
Skipped import rows and cancellation consequences receive clear local notices.

Highlight an unmanaged IP observed on at least two distinct FTD IDs in a rolling
24-hour window, even if it has already disappeared from one device. Show device
count/names and relevant times, distinct from current simultaneous presence.
Repeated sightings on one FTD do not qualify as multiple devices. Provide a
direct action to take that IP into Managed with explicit device selection.

The later email digest must emphasize these correlated addresses too. Preserve
the existing local timestamp display with explicit timezone and history/search
behavior while reorganizing the interface.

### Local IP context / enrichment — requested 2026-10-21

2026-11-12 follow-up: the operator chose IPFire Location for local enrichment of
all current/missing IPs, daily signed-source updates and periodic cache refresh.
Team Cymru is a possible supplement only. See the latest architecture amendment
and manual/ip-context.md; the prior once-per-occurrence/no-backfill restriction
is superseded for the local provider.

Earlier2026-11-12 update: the operator authorized isolated background RDAP on the known
lab. Source0.8.0 implements a query-only UDS observation feed, separate bounded
worker/cache and cache-only Web rows/reviews. No network/control socket or original
DB is given to the internet-connected worker. Initial announced sample: two
existing public IPs, no FTD writes or full-list backfill. This acceptance is complete:
one result is ready, one referral is unavailable; the worker and Web0.8.0 are running.
Follow manual/ip-context.md and current status/log for evidence; original lifecycle rules
below remain, and the older no-outbound-permission sentence is superseded.

Add minimal informational context for each IP in the Web UI, using RDAP or an
equivalent source to be evaluated later. This is a follow-up idea, not implemented
functionality or permission to enable outbound lookups. Keep core working-version
delivery ahead of this optional feature.

Candidate fields, only where the selected source actually supplies them:

- Network/registered organization name and allocated prefix or address range.
- ASN/operator information, potentially requiring a separate source.
- Registered country, clearly labelled as registration data rather than the
  user's location or the physical origin of traffic.
- Source attribution and lookup timestamp, with explicit stale/unavailable states.

Prefer a compact expandable IP-context view shared by current/managed/unmanaged
lists, search and IP details, rather than adding several permanent table columns.
Context is advisory: never use it as blocking reputation, proof of ownership or
authority to add/remove/restore a shun or change protection.

Enrichment is occurrence-driven, not periodically refreshed (operator clarification
2026-10-21). Schedule at most one lookup attempt when a new shun occurrence is
detected. Keep its result or explicit unavailable/error status while that occurrence
remains active. Polling, page views, cache expiry, failures and service restart
must not trigger another lookup for it. Only a confirmed disappearance/removal
followed by a newly detected occurrence permits another attempt; a failed/partial
device read is not disappearance. Adopting an already observed shun is not a new
detection. Retain an occurrence-bound completion marker across restart.
An additional-device sighting while that IP is already active reuses its existing
context rather than refreshing it merely because another FTD reported it.

Use asynchronous deduplicated lookups with a bounded local cache, provider rate
limits, response-size limits and short timeouts. Coalesce concurrent detections
of the same IP across devices. Cache age may control reuse on a genuinely new
occurrence, but never starts a background refresh or failure-retry loop for an
existing one. Viewing a long list must not fan out into one live lookup per row
or delay Web responses, refresh, queue dispatch or Cisco operations. No-data/errors
must leave IP operations usable; stale cached context may be shown honestly.
Do not automatically backfill every existing active record on feature activation.

Before implementation, evaluate provider coverage/terms and query privacy:
external requests reveal queried IPs to the provider. Specify enablement,
retention and an offline/local-data option where appropriate. Do not query private
or special-use addresses externally. Keep browser third-party requests off and
retain the current Web/API network isolation and FTD-only agent egress; design a
separate constrained lookup path rather than granting these services Internet
access. Use fixed trusted discovery/provider rules, validated destinations and
bounded redirects to prevent SSRF; treat all returned text/links as untrusted.
Provider choice, exact fields, cache defaults, worker topology and any schema or
deployment migration remain future design decisions, not current configuration.

## 8. Emergency Purge

Emergency Purge is available to every authenticated service user, with explicit
confirmation and actual actor audit. This decision does not authorize anonymous
access or invent directory roles. It is an exceptional whole-managed-scope action:

1. Cancel current imports and their unexecuted additions/restorations.
2. Permanently retire all managed targets in the confirmed purge scope.
3. Remove their shuns from the corresponding FTDs with urgent scheduling after
   current operations/verification settle.
4. Preserve whitelist configuration and unmanaged targets outside that scope.
5. Report progress and outstanding/failed/unreachable-device cleanup honestly.

Unlike ordinary import cancellation, Purge also removes the managed entries that
have already been applied. Confirmation must state what will happen, with import,
target and device scope/counts and the fact that maintenance will stop. Missing
current observations do not remove managed targets from that frozen scope.
Retirement must prevent re-add while cleanup is pending, including across restart.

The operator selected cancellation of current imports, not an approved permanent
global import lock. Exact admission behavior for *new* imports while Purge remains
pending needs to be specified with the concurrency/confirmation contract. Do not
infer permission to clear unrelated state or activate Purge on the lab now.

## 9. Email: approved follow-up, lower priority

Use SMTP Relay with independent optional authentication and transport modes:
plaintext, STARTTLS or implicit TLS. Support certificate verification/internal CA;
configured TLS must not silently downgrade. Connection settings, sender, common
recipients and timing belong in `.env`; passwords use secrets. Web needs a test
message action and delivery status rather than another configuration editor.
Sending/retry must be asynchronous and must not delay FTD work. Concrete mail
dispatch topology, outbox/retry bounds and network isolation require a later design.

Notification rules:

- First new unmanaged event after a quiet period: immediate notification.
- During an active notification window, collect further ordinary events rather
  than send an email per IP/device. Send a digest after 10 minutes, then 20, then 40,
  increasing toward a configurable maximum. Exact maximum remains configurable/
  to be selected. Count elapsed time, not poll/command/manual-refresh cycles.
- An unchanged shun list alone causes no new digest. If new events accumulate,
  the message states when the next conditional digest will arrive ("in X").
- Reset the backoff after one hour without new unmanaged events; the next new
  event may notify immediately again.
- Whitelist additions identify who added which address and when.
- Detecting an actively protected address in shun is urgent, independent of the
  ordinary digest timer. Notify about detection, the first unblock attempt/result,
  and later state changes. Repeated identical attempts/failures do not send an
  email every time; successful unblock is a state change.
- Emphasize unmanaged multi-device sightings over the rolling 24-hour window
  within the digest; this does not bypass the ordinary anti-spam timer.

## 10. Delivery order and implementation gaps

These decisions supersede older *target behavior* in the named areas. The older
manuals still describe existing contracts until implementation is migrated.

| Area | Existing implementation constraint | Agreed working-version target |
| --- | --- | --- |
| Credentials | Opt-in agent-only per-device mapping implemented; lab still uses explicit shared compatibility mode | Separately reviewed per-device rollout; no shared fallback within that mode |
| Preparation storage | V2 100,000-pair journal/private API/Web, gated suspended confirmation and exact cancellation/shared settlement; legacy 1000-pair workflows retained separately | Configured executable rollout, concurrent standing admission and rolling progress |
| Policy display/reviews | Managed tab reads 100-row pages; single-pair and whole standing-list reviews use distinct exact selections with global totals; authority limits unchanged | Coordinate larger retained capacity, remaining full reviews and bounded dispatch |
| Capacity | Legacy 1000-pair bounds; explicit v2 100000-pair policy/cancellation with bounded internal dispatch, not activated in lab | 10,000 input IPs across selected devices in the executable working version |
| Existing shun | Gated prepared-confirmation Web/backend support adoption without ADD/provenance; legacy grants still reject it | Retain explicit selected-device adoption in the larger executable workflow |
| Invalid/protected rows | Managed-import Web/backend bind visible diagnostics/protected exclusions and exact accepted scope; legacy standing review still rejects whole scope | Retain exclusions/reporting during rolling execution |
| Scheduling | One fleet executor, global >=60s cooldown | Parallel devices, one stream each, continuous bounded writes |
| Protection | Explicit protection saves now permanently retire matching maintenance; unknown state holds enabled protection until retirement can finish | Retain this lifecycle in the new bulk workflow |
| Lost result | Latched offline attention/recovery | Automatic fresh-evidence reconciliation with original uncertainty retained |
| Purge | No working-version global managed purge | Confirmed cancel/retire/urgent cleanup, authenticated access |
| Correlation | No agreed rolling cross-device signal | Unmanaged rolling 24-hour badge and managed action |
| Email | No mail delivery implementation | Lower-priority SMTP relay/digest follow-up |

Implementation order:

1. Design per-device inventory/secret ownership and capacity-compatible durable
   policy/import records; define migration and rollback from current retained state.
2. Implement managed-only import/adoption, visible exclusions, whitelist retirement
   and cancellation semantics with explicit conflict reviews.
3. Refactor per-device dispatch/concurrency, continuous queues and interactive
   priority while preserving fixed typed protocol and verified outcomes.
4. Implement automatic uncertainty reconciliation with proven RPC settlement,
   current-policy checks and retained audit; integrate ordered removal/Purge.
5. Complete separate tabs, status indicators, refresh completion, import reports
   and 24-hour cross-device correlation/action.
6. Validate end-to-end with disposable state, then separately scoped lab scenarios
   and measured throughput. A 10,000-address target does not authorize a live bulk
   load or establish FTD capacity/production readiness.
7. Implement SMTP delivery and notification aggregation after the core workflows.

### Capacity contract for the next import increment

The [isolated version-2 SQLite component](manual/bulk-policy-storage.md) now
implements actual root/membership/effective-policy persistence, owner recovery,
100-row reads and a positive retirement reserve on a fresh suspended development
profile. It deliberately blocks legacy managed services; no live profile or API
limits were changed. The existing protection coordinator now supports narrow
version-aware permanent revocation/weakening barriers (2026-10-22), without
enabling runtime imports. Version-2 pre-execution cancellation and local progress/
bounded candidate portions are also implemented (2026-10-22), without queue
admission; see [their explicit limits](manual/bulk-cancellation-and-work.md).
An optional bulk result journal now connects retained original evidence to shared
completion/lease/retention hooks, without claim/admission or dispatch activation.
Nonempty conversion, version-aware cleanup/atomic attempt claims and actual
dispatch remain prerequisites for runtime exposure.
A separately explicit captured-cancellation profile now handles owned in-flight
settlement/completed-application retention while preserving earlier receipts.
At that checkpoint, atomic runtime admission/claim, actual dispatch and automatic
reconciliation were not yet supplied; no live profile or fixture was activated.

The next backend increment (2026-10-22) now supplies actual atomic <=16-pair
enqueue and shared queue claims behind a separate default-false bulk capability.
Its explicit developer-profile upgrade retains suspension/history, requires a
fresh-read resume barrier and never activates itself. Cancellation/protection,
typed completion, exact deferral and lease recovery use the same journal/worker.
There is still no runtime refill/controller/Web wiring, concurrent standing
admission, continuous/per-device lease scheduler, automatic reconciliation or
legacy nonempty conversion. See [Bulk Queue Admission and Claim](manual/bulk-queue-admission.md).
No live profile, lab migration, fixture or FTD command accompanies this component.

Bounded refill now composes that admission with the existing Synchronizer behind
an internal default-false bulk capability (2026-10-22). It scans <=64 rows without
adopting observations, admits <=16 new jobs per cycle and limits each device's unfinished
shared-work window to 16. Keyset hints, revision/barrier resets and retained
last-admission ordering provide bounded restart-safe scans and device fairness.
The existing cutoff/cooldown still apply; continuous writes/parallel leases are
not implemented by this integration. Pending/status/claim distinguish the bulk
capability from legacy restoration. Unknown or merely read-reconciled original
RPCs remain retained device barriers; unsent expired jobs are cancelled without
rewriting old failed/unknown outcomes. See [Bounded Bulk Refill](manual/bulk-refill-controller.md).
No environment/API/Web activation, new schema or live lab change was introduced.

The isolated [version-2 format foundation](manual/bulk-import-capacity.md) now
binds a complete 100000-pair classified manifest in a small canonical descriptor,
including explicit protected exclusions/adoption classification and original
preparation identity/digest. A read-only internal journal proposal does not save
authority, expand legacy limits or expose admission. The isolated persistence
checkpoint above is separate; its coordinated runtime migration remains pending.

Inspection on 2026-10-21 confirmed that raising one constant is insufficient.
The current 1000-target registry, shared 1000-pair canonical request, 10000 immutable
request slots with retirement reserve, 10000 lifetime restoration attempts and
full-snapshot readers are coupled. They stay unchanged until the whole path is
compatible. In particular, increasing targets beyond ledger capacity makes the
current retirement-reserve calculation reject every new grant.

Implement the new flow around one durable actor-attributed import root, an exact
accepted/excluded scope and durable per-pair maintenance; do not turn 100000 pairs
into 100000 immediately queued requests. Use paged policy/report reads and bounded
rolling dispatch/restart cursors, with retained provenance and no request-TTL
expiration of standing consent. Freeze managed/protection revisions and explicit
adoption vs missing state; late changes conflict, never silently alter acceptance.
Cancellation must distinguish completed/adopted retained targets, unsent cancelled
targets and unsettled running attempts. Define total retained capacity/retirement
reserve and legacy-latch compatibility together before migration or gate changes.
Synthetic 10000-address/10-device tests must demonstrate storage, paged reads,
backpressure, revocation and restart, not only a larger paste field. No new bulk
schema, live migration or large fixture is authorized by this design note.

Do not keep extending offline incident controls as the default next product
milestone while the core working-version workflows remain unavailable. Existing
operator procedures/receipts remain valid safeguards for their current version.
No runtime code, schema, gates, profiles, credentials or deployment is changed
by recording this plan. New lab fixtures/migrations/activation still require
the existing scoped authorization; old fixture permissions remain consumed.
