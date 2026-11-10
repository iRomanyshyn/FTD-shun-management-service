# Repository Working Agreement

This repository is an English-language product repository. Write source code, documentation, commit messages, configuration comments, and operator-facing text in English unless a user explicitly requests a translation.

## Current development stage — operator alignment, 2026-10-30

This is an unreleased internal project with no production use. The current
FPR1010 is the operator's desk laboratory device, not a working production firewall.
Prioritize a usable end-to-end product over compatibility tooling for disposable
development state. This section and the matching architecture amendment supersede
older per-experiment lab approval and mandatory dev-migration planning below.

Operator reaffirmation, 2026-11-02: this is still the same test FPR1010. Controlled
experiments with its shuns and this product's lab dataset are authorized without
another per-fixture approval. Announce the selected scope, retain useful failure
evidence before changing data, use fresh labelled authority and verify cleanup.
This is not production authorization or permission to bypass executable guards,
invent successful results, alter credentials/trust or silently erase the dataset.

- Ordinary in-scope development, validated lab deployments, explicit fresh-profile
  initialization and bounded semantic ADD/REMOVE/restore tests on this known lab
  may proceed without another approval for every fixture or feature switch.
  Announce device writes/configuration changes and their bounded scope, use new
  labelled test requests/keys, verify outcomes and leave a short development record.
  Historical consumed experiments remain historical evidence, not reusable receipts.
- Do not implement a legacy-dev database converter as a release prerequisite.
  Prefer a clean database in a separate path/volume, retaining the old test DB as
  a private archive. Keep inventory/credentials; transfer useful configuration
  explicitly, not old queues, managed authority or uncertain operations.
  No silent overwrite/deletion, broad volume cleanup or automatic reset is allowed;
  destructive replacement still needs an exact, explicitly authorized scope.
- Existing executable guards are real product correctness checks, not paperwork:
  implement/select compatible tested profiles rather than bypassing gates, replaying
  unknown writes, clearing evidence or inventing verified outcomes. Keep the security
  invariants below, default-safe examples, real audit identity and agent-only secrets.
- Ask again for production/unknown targets, materially broader or destructive
  operations, secrets/trust/network changes, or a test with unclear impact. Do not
  repeat approval requests solely because old runbooks called every lab step gated.
- Strict released-data compatibility, upgrade/migration and release rollback
  obligations start with the first operator-designated real release published on
  GitHub with a version tag. A dev footer/commit or experimental tag is not that
  decision; publishing a release/tag still requires the operator's request.
  Follow [Versioning](docs/manual/versioning.md). Core security applies now too.

## Current recovery guidance and lab state — 2026-11-10

API `3713153a0892...` / `56b8447c125b`, Web `b65f21e7776d...` /
`e94577e7a389` add read-only `/api/v1/queue-recovery`, authenticated guidance/
download `/queue-recovery` and Queue attention's **Check and resume import**.
Current implementation is host-assisted, NOT online one-click recovery. The
separate `python -m ftd_shun_manager.lab_recovery` command requires explicit known
single-device lab inventory, exact epoch, real maintenance label/all overlays/
matching API image, private evidence, actual API/Web then agent exits, copy
rehearsal, fresh review and checked backup before the existing offline decision.
Failures after stop remain stopped; no Docker/host privilege is added to Web/API,
no new online release endpoint/unknown replay or implicit recovery initialization.
Follow docs/manual/queue-recovery.md. Agent `8d9f196ceea1...` / `4b2aa4744e96`
remains unchanged; current v6/original managed DB/import/all overlays remain.

Actual epoch 3044 failed on FTD prompt timeout with 13 new unknowns, 26 raw total.
After explicit operator approval and actual API/Web/agent exit 0, existing default
13-claim reconciliation was rehearsed and applied at 18:04:24.967Z, decision
`8dcf8343-c491-43d1-b5a1-01d7ceb493af`. Original schema/eleven data tables/six
prior receipts unchanged; all 26 unknowns retained, old jobs retried zero.
Backup `reconciliation-20261110-epoch3044/before-live-reconciliation.db`.
Actual new epoch 3045 settled 28 VERIFIED, 3046 read-only settled. Do not reuse
that receipt for another epoch. Timeout/SQLite contention causes are NOT cured.

Full Python 3578/659.43s, final focused 114 and browser/Node 91 pass; source
checks/configured non-executing candidate preflight pass. Final focused tests
include image-pin/stop-failure/timeout hardening added after full-run collection;
no second full-source run is claimed. New bundled control and report pass on
the archived actual 13-unknown copy; stale live epoch-3044 command refused before
stopping/restarting anything. No induced new device failure or live use of the
new whole helper is claimed. Prior real recovery used the existing offline tool.

Guidance rollout drained old API/Web exit 0, stopped epoch 3053 IDLE/no RUNNING;
agent stayed running. All nine post-recovery fingerprints and 26 unknown rows
unchanged before/after replacement, integrity ok. At 18:23:11Z fresh read, no
error/zero unresolved attention; reviewed history 26. Normal epoch 3054 LEASED,
not globally idle. Web 200/anonymous recovery+download 401, new private report
200/read-only and template/CSS hashes checked. Rollback pair:
`ftd-shun-{api,web}:lab-pre-recovery-assistance-20261110`; normal drain, never a
stale DB restore. Reload existing tabs for the new Queue link. Do not reset/
reimport/renew old consent or force-clear later uncertainty.

## Previous Web increment — stable IP action editors, 2026-11-10

Web `f8c36b7aeaeb...` / `3457285a8c0d` fixes bottom-of-page Managed-IP actions
closing during live refresh. Three review disclosures have stable IDs; explicitly
marked non-authoritative editor regions keep identical DOM (ignoring only local
details open state), preserving native selectors, inputs and summary/button focus.
Changed options/hidden fields/capabilities still refresh; removed actions stay
removed. Frozen confirmations and all server-side controls are unchanged.
Legacy review preparation gets the same protection. Status/Queue/observations
continue updating; no new Python, DB, policy, device or execution change.

Browser/Node 90 and affected Python UI 119 pass; Ruff/compileall/diff pass.
A broader Python run was interrupted after 302 passes, not a completed full run;
this increment only changes JS/templates. Only Web was rebuilt/restarted; API
`968a8fa02ff2...` / `7ba324a61af1`, agent `8d9f196ceea1...` / `4b2aa4744e96`
and all three overlays/current DB/import/v6 gates remain unchanged. Web health
200/anonymous managed page 401 and actual served JS/three file hashes checked.
Rollback Web image: `ftd-shun-web:lab-pre-stable-ip-editors-20261110`. Existing
tabs need one reload. Do not reset/reimport or reuse any old recovery key.

## Previous laboratory UI — bounded Shuns pages, 2026-11-10

API `968a8fa02ff2...` / `7ba324a61af1` and Web `b21d4d1d6e79...` /
`4246878c51cd` now display Shuns as server-side pages of 100 observations.
SQL LIMIT precedes hydration; provenance is selected-page only. Count/rows/origins
share one read snapshot; protected/newest order, global IP search and live page/
query retention remain. Continuous API explicitly permits the new read-only
`/api/v1/shuns-page` endpoint; browser never falls back to the full-list endpoint.
No schema, policy, protocol, gate, secret/trust/network or agent change.

Old API/Web exited 0; stopped epoch 2947 IDLE, zero RUNNING, integrity ok, all
nine authority/protection/inventory/recovery fingerprints and thirteen original
unknowns unchanged. All three overlays/same managed-v2 DB/original import remain;
agent `8d9f196ceea1...` / `4b2aa4744e96` stayed running. Compatible rollback tags:
`ftd-shun-{api,web}:lab-pre-shun-pages-20261110`; drain normally, never restore
stale data. API startup scheduling BUSY recovered automatically; new original-
task jobs are VERIFIED under normal epoch 2948, not globally idle. V6 remains
selected, v7 source-only. Do not reset/reimport/reuse old recovery keys.

Browser/Node 89 and final affected Python 153 pass. Full regression had 3566
pass/one initial missing-allowlist failure, fixed and explicitly rerun; no second
clean full run is claimed. Ruff/compileall/diff, built-image configured check and
actual read-only pages pass. Deployed 25,484-observation data returns 100/100/84
rows, ~28 KB per full page, not the whole list. First live response was 1.206s,
subsequent pages ~0.05–0.06s; not a production/load guarantee. Web 200/anonymous
401 and source-matching assets checked. Existing tabs need one reload. Follow
docs/manual/operations.md; preserve all original import/unknown/recovery evidence.

## Earlier laboratory runtime — SSH idle fix, 2026-11-10

Agent `8d9f196ceea1...` / container `4b2aa4744e96` now gives visit SSH transport
the unchanged hard visit budget (120s v1–v5/240s v6/v7), instead of prematurely
closing during 15s of local API persistence/root work. Standalone idle remains
15s; all CLI/opening/IPC/step/session/quota bounds and gates unchanged, no
keepalive/reconnect/resend. Actual pinned in-memory SSH reproduces old close
after 16s silence and new resumed data. Rust 97+7+4, locked release/Clippy/fmt and
configured non-executing image preflight pass; Python full 3563/shared 343 and
final wire/session 96 pass. Deferred retry replacement remains source-only; v7
is not enabled. Agent rollback: `ftd-shun-agent:lab-pre-ssh-idle-20261110` retains
compatible old image but loses this fix. Same API `20be29303cc7...` /
`6e9af86250a3` and Web `b86fac92f284...` / `f42288374e68` restarted unchanged.

After the prior epoch-2925 reconciliation, old agent failed again at epoch 2926
after 16 VERIFIED/one new UNVERIFIED, total unknowns 13. All were retained.
Actual API/Web/old-agent exits 0 preceded this rollout. Preliminary copy recovery
correctly refused 15 unstarted jobs; its full pre-maintenance copy is retained.
Existing `cancel_obsolete_policy()` cancelled exactly those 15 stale never-claimed
execution jobs, retaining standing roots, all 13 unknowns and ATTENTION unchanged.
Fresh post-maintenance rehearsal passed; new decision
`b106cc46-8d9f-4704-8644-3bdf671e2262` at 13:35:16.073Z covers only epoch 2926.
Backup: `reconciliation-20261110-epoch2926-ready/before-live-reconciliation.db`.
Schema, eleven post-maintenance tables and five old receipts unchanged; integrity/
FKs/profile valid. Neither consumed key releases a later epoch. No reset/reimport,
new consent or secret/trust/network change. All three overlays/original DB/v6
selection retained. Actual epoch 2927/owner `fa37922c-5776-4998-bad4-95ccfe17fbfe`
released at 13:39:53.445Z: 28 VERIFIED (16/12), one exact pre-write DEFER, real
settled shared session 216.921s. It crossed the old post-group failure boundary;
read-only epoch 2928 also settled. At 13:40:53Z original task 25,206 VERIFIED/
32,425 plus ten reviewed/present, 7,209 outstanding, ready/no error/zero unresolved
attention. At 13:40:46Z integrity ok, eight original authority/protection/inventory
hashes and all thirteen unknown rows unchanged; six receipts expected, zero pending
schema objects. Normal epoch 2929 LEASED, not global idleness. Web health 200/
anonymous 401 checked. Scheduling BUSY recovered in this sample; SQLite contention
and full-list speed are not fixed/proven. Source-only deferred-v7 ordered pending/
recovery and fresh-store activation remain next. See docs/manual/ssh-session-idle.md.

## Earlier source-only increment and lab reconciliation — 2026-11-10

Fresh deferred-v7 retry replacement now permits exactly proved pre-write cancelled
children, retaining original outcomes/delegations, new causal complete absence
and fresh IDs, full original current root/policy/protection/lease/freshness checks
and existing backoff/hourly limits. Missing/duplicate/foreign claim/DEFER, ACK,
pending membership or unknown result refuses. Historical replay ignores later
siblings as authority; retention preserves actual claim visits even if admission
was in another visit. No schema/default/configuration/deployment or live FTD test
write. Configured API/agent remain v6. Focused 62 pass (26 new), shared set 343
pass; clean full Python regression 3563 pass in 631.10s. Ruff/compileall/diff pass. No new Rust/browser
run. Next ordered pending capture/promotion,
compatible deferred recovery and deliberate fresh-store activation/acceptance.

Earlier read-only 13:08:18Z lab integrity ok, all nine post-recovery authority/protection/
inventory/recovery fingerprints unchanged. **New ATTENTION epoch 2925** follows
SSH shell-send failure at target read. New job
`68dbe319-361b-509c-b557-6698ff9961c6` / 151.230.131.112 is UNVERIFIED; twelve
unknown rows total, one unresolved. Original task 25,162 VERIFIED/32,425 plus ten
reviewed/present and one new unknown; 7,252 outstanding. Do not replay/relabel
that job, reset/reimport or reuse epoch-2921 receipt. Retain failure evidence.

The separate existing extended-v6 reconciliation contract was then successfully
rehearsed on a private copy: all 17 claims (16 VERIFIED/one UNVERIFIED), eleven
original tables/four prior receipts unchanged, zero old jobs retried. After actual
API/Web exit 0, then agent exit 0 and a new stopped whole-DB review, fresh decision
`921ebe04-5283-42be-9d1a-9eab92915739` at 13:20:14.995Z released only epoch 2925.
Backup: `reconciliation-20261110-epoch2925/before-live-reconciliation.db` in the
state volume; rehearsal has separate consumed key/files. Checked live comparison:
schema and eleven original tables unchanged, four old receipts unchanged,
integrity/FKs/profile valid, all twelve original unknowns retained. Same exact
API/agent/Web images and containers below restarted, agent first. No new source
deployment or v7 activation. Post-receipt continuation acceptance is being observed;
do not call mere startup/ACK a verified productive cycle. Neither old receipt can
release a later epoch. Follow docs/manual/extended-session-recovery.md.

## Earlier laboratory runtime — exact pre-write recovery, 2026-11-10

API `20be29303cc7...` / container `6e9af86250a3` now supports the distinct optional
`managed_bulk_prewrite_recovery` profile. After actual API/Web/agent exit 0,
fresh whole-DB review and exclusive checked backup, decision
`5d4551f5-609e-45f8-9587-b06d352e9e66` at 11:58:02.571Z released only held epoch
2921: 32 VERIFIED claims and one exact expired/cancelled pre-write DEFER. All
eleven original data tables and all three prior recovery receipts were unchanged
immediately after apply. The original cancelled job/request/attempt stay cancelled/
expired, never replayed or relabelled. Keep the original import and evidence.

Backup: `prewrite-recovery-20261110-epoch2921/before-prewrite-recovery.db` in the
private state volume. Older API image `ftd-shun-api:lab-pre-prewrite-20261110` is
an archive, **not compatible with this DB**. Compatible image tag:
`ftd-shun-api:lab-prewrite-recovery-20261110`. Same agent `e8cdc9925a8d...` /
`ea9085b90bf5` and Web `b86fac92f284...` / `f42288374e68` restarted unchanged.
Keep all three lab overlays, original managed-v2 DB and private v6 selection;
v7 remains unavailable/default disabled. No trust/secret/network/consent change.

Actual complete read at 11:59:13Z followed the receipt. Epoch 2922 actually
released at 12:02:27.965Z with 24 new VERIFIED ADDs in a settled shared v6 session
(203.869s); this is bounded continuation, not a speedup/load claim. Original
deferred address received a fresh VERIFIED job, while its old CANCELLED outcome
remains. At 12:03:32Z original task 25,116 VERIFIED/32,425 plus ten reviewed/
present unknowns, 7,299 outstanding, zero unresolved queue attention. Normal
epoch 2923 is active/LEASED, not global idleness. At 12:03:03Z integrity ok,
eight original authority/protection/inventory fingerprints and all eleven unknown
rows unchanged; fourth recovery receipt is the expected new one. Local scheduling
BUSY recovered once; maintenance expiry also reported database contention. Do not
claim SQLite contention fixed or status last_error clear. Web health 200/anonymous
401 checked. Full Python 3537 pass in 614.88s; focused recovery/history 116 pass,
Ruff/compileall/diff and non-executing image preflight pass. No new Rust/browser
run. Follow docs/manual/prewrite-epoch-recovery.md; this key cannot release another
epoch. Next finish deferred-v7 ordered pending/recovery/child replacement and
fresh-store configuration before bounded activation; do not widen selectors.

## Earlier lab hold and source-only lifecycle increment — 2026-11-10

Read-only 10:02:21Z lab integrity is ok, all nine original fingerprints and eleven
unknown rows unchanged, no pending-schema objects. Original import is at 25,092
VERIFIED/32,425 plus ten reviewed/present unknowns, 7,323 outstanding, but device 1
is ATTENTION epoch 2921. Audit has 33 claims: 32 VERIFIED and one exact same-owner/
epoch v6 SHUN_OPERATION_DEFERRED with write_sent=false, later CANCELLED after its
delegation expired. Final shell read/settlement failed; no new unknowns. Existing
extended recovery refuses the claimed CANCELLED/deferred member. Do not clear the
hold, replay a job, reset/reimport, reuse old receipts or pretend this is an
all-verified epoch. Implement/test compatible exact-defer recovery next. Runtime
and data were not mutated by this development slice.

Source-only deferred ordinary restoration now accepts a later causal absence
after OBSERVED_PRESENT under current exact standing scope, preserving 300s/three-
per-hour bounds and every original root/protection/lease/uncertainty check.
Retained later VERIFIED/NOOP/OBSERVED_PRESENT supersedes only strictly earlier
known absence in that same scope for scheduling; no outcome or command changes.
Ready device/fleet cleanup explicitly blocks AWAITING_CONFIRMATION; after actual
confirmation fresh whole-scope consent atomically retires policy and enqueues
REMOVE. Ordered inspection gives readable refresh/review guidance and no token
for pending confirmation. No schema, public selector, default/configuration,
authority, deployment/restart or FTD test write changed. Current runtime stays v6.

23 new synthetic lifecycle checks pass in 11.94s; focused shared set 342 pass in
85.16s, browser/Node 88 pass in 147.93s; Ruff/compileall/diff pass. Clean full
Python regression 3515 pass in 613.08s. No Rust change/run or live v7 acceptance
is claimed. Exact original API/agent/Web IDs/images were checked running;
device hold is still retained, not recovered by successful tests.
Next ordered pending capture/promotion, compatible deferred recovery, claimed/
deferred child replacement and configured fresh-store activation/acceptance;
ready cleanup and later disappearance restoration are no longer missing source
contracts. Follow docs/manual/deferred-confirmation.md and the new lab hold above.

## Earlier source-only checkpoint — continuous deferred scheduling, 2026-11-09

Default-disabled `DeferredContinuousDispatcher` now schedules causal confirmation
after actual pending handoff and fresh reads after confirmed-absence backoff.
Rotating bounded 64-candidate advisory scans use shared backoff/hourly arithmetic;
timers grant no write permission. Read-only confirmation continues during mutation
pause; pool/manual/removal priority and original scheduler backoffs remain. Only
actual complete-read publication satisfies browser demand/resets freshness, never
END_PENDING. Existing Queue UI distinguishes awaiting confirmation, known
observation/absence and neutral retry waits; actual unknown/device attention stays.
No DDL, current configured API/client/agent selector or live runtime change. Keep
the original v6 import and all authority/protection/unknown/recovery evidence.

Focused shared scheduler/worker/queue/retry/parallel set 190 pass in 66.15s;
browser/Node 88 pass in 114.97s. Ruff/compileall/diff pass; clean full Python
regression 3492 pass in 559.54s. Final new scheduler set 10 pass in 10.69s,
covering automatic confirmation/retry, paused
restart, actual-read demand causality, strict ms settlement margin, bounded scan
rotation and unknown holds. No Rust change/run or live v7 acceptance is claimed.
Next ordered managed/fleet cleanup, deferred recovery, later disappearance
restoration, claimed/deferred retry-child replacement and deliberate fresh-store
configuration before bounded lab activation. Do not widen public selectors or
convert/reset/reimport current data to demonstrate this source-only composition.
Read-only lab at 19:18:44Z: integrity ok/nine original fingerprints and eleven
unknown rows unchanged, normal epoch 2687 LEASED. At 19:22:18Z original import
17,583 VERIFIED/32,425 plus ten reviewed/present unknowns, 14,832 outstanding;
ready/no error/zero unresolved attention/zero pending-schema objects. Earlier
numeric scheduling BUSY recovered and maintenance expiry contention was observed;
do not claim contention eliminated. Exact v6 API/agent/Web containers unchanged.
See docs/manual/deferred-confirmation.md.

## Earlier source-only checkpoint — explicit deferred worker, 2026-11-09

`DeferredParallelSynchronizer` now composes the fresh execution profile with an
explicit strict tracked-v7 client, default disabled. Separate queue/session
subclasses support v7; ordinary grouped queue/session selectors remain v5/v6.
Every complete read atomically confirms bounded prior groups under its current
lease before publication, then selects guarded fresh retries/ordinary discovery.
Read identity is shared, not reconstructed between confirmation and admission.
Intermediate groups retain strict verification; only the last acknowledged group
uses real END_PENDING and atomic handoff/release without another read or false
freshness/verified progress. Original coordinator completion never releases a
successor lease. Priority refresh/REMOVE/protection flush at command boundaries;
stop/pause/cancel and caller drain preserve actual pending settlement. Unknowns,
lost/mismatched terminal scope and local handoff failure still retain fences.
Internal retry counts/next eligible UTC metadata are available, not public UI.

Source-only, not configured startup or a continuous retry daemon. Configuration,
high-level Unix client/agent and current continuous service still refuse v7; no
live DDL/deployment, `.env`/inventory/secret/trust/network change, new authority,
reset/reimport or test FTD command. Current v6 import remains untouched. Do not
enable v7 by widening selectors: continuous confirmation/wait scheduling, public
UI/configuration, ordered managed/fleet cleanup, compatible deferred recovery,
later confirmed-presence disappearance restoration and claimed/deferred retry-
child replacement remain unfinished before bounded fresh-store lab acceptance.

31 new synthetic worker checks pass in 13.37s; final focused shared-worker/queue/
pending/parallel/continuous/timing set **245 pass in 62.62s**. Ruff/compileall/diff
pass; clean full Python regression **3482 pass in 575.63s**. A
two-device test now waits for actual DB handoff, not merely earlier remote
cleanup. Synthetic 64-attempt visits are not live throughput/capacity acceptance.
Read-only 18:53:05Z lab: integrity ok/all nine original fingerprints and eleven
unknown rows unchanged, normal epoch 2679 active/LEASED. At 18:55:20Z original task
17,324 VERIFIED/32,425 plus ten reviewed/present unknowns, 15,091 outstanding,
ready/no error/zero unresolved attention/zero pending-schema objects. Exact
API/agent/Web images/containers remain unchanged and running with all overlays.
No Rust/browser run or live v7 acceptance is claimed for this Python-only slice.
See docs/manual/deferred-confirmation.md.

## Earlier source-only checkpoint — confirmed-absence fresh admission, 2026-11-09

`PendingRetries` now creates new bounded jobs after exact settled
CONFIRMED_ABSENT predecessors, under still-current original root/intent and all
protection/cancellation/lease/uncertainty/serialization checks. Old jobs/RPCs are
never replayed or relabelled; unknowns still hold. Immutable provenance binds
original absence, new IDs, complete read/visit and policy audit. Backoff is
5/10/20/40/60s capped, with 12 retry admissions/device/IP/rolling hour and typed
next-eligible UTC waits. Same-read reuse requires identical full evidence and
existing freshness; cancelled-child replacement is limited to never-claimed
work. Claimed/deferred or unknown children never gain automatic replacement.
Queue/audit retention preserves linked jobs/requests/audits/visit claims and
refuses corrupt bindings before deletion. Original short-lived requests are not
renewed; fresh execution requests remain under original standing consent.

Internal/default-disabled only, included in the explicit fresh-empty execution
profile. No converter, live DDL/deployment, public route, init CLI or configured
retry loop. Current coordinator/client/configuration/grouped queue/agent still
refuse this worker profile/v7. Next matched worker/priority/removal/UI and later
confirmed-presence disappearance restoration, then bounded separate-fresh-DB lab
acceptance. Keep the current v6 original import and all authority/unknown/recovery
evidence; do not reset/reimport or widen selectors as an activation shortcut.
Final focused profile/retry/store/history set **144 pass in 19.20s**, including
36 new retry cases; Ruff/compileall/diff pass. Current-source query-only validation
of a separate consistent lab copy passes exact profile and all four full roots /
32,430 members, with zero local changes and zero pending-schema objects. This is
compatibility evidence, not activation or live v7 acceptance. Final 18:25:40Z
read-only comparison: integrity ok/all nine fingerprints and eleven original
unknown rows unchanged; normal epoch 2671 active/LEASED. At 18:25:46Z original task
17,050 VERIFIED/32,425 plus ten reviewed/present unknowns, 15,365 outstanding,
ready/no error/zero attention/zero pending-schema objects. Same images/containers
remain running. Clean final full Python regression **3451 pass in 574.10s**;
Ruff/compileall/diff pass. No Rust/browser run or live v7 acceptance is claimed.
See docs/manual/deferred-confirmation.md.

## Earlier source-only checkpoint — fresh deferred queue handoff, 2026-11-09

`PendingExecution` adds an explicit fresh-empty execution profile and internal
default-disabled transition hooks. Original settled-v7 scope/root/delegation/
claim/ACK evidence, whole-group AWAITING_CONFIRMATION states, real-identity audits
and original live lease release commit atomically. A new same-device visit's
causal complete read settles OBSERVED_PRESENT/CONFIRMED_ABSENT, never original
creation/occurrence provenance or old-command replay. Classification/results/
original-request closure and captured import cancellation settlement are atomic.
Cancellation retains confirmed-present entries and retires exact confirmed-absent
ones without attention; enabled protection retirement is never undone. Awaiting
confirmation/known-absence retry work stay outstanding, and retention preserves
all linked evidence. Ordinary discovery refuses deferred outcomes until the
current-policy/backoff new-attempt contract exists.

No live DDL/deployment/gate change. `initialize_empty()` refuses even VERIFIED
history: use a separate fresh database, never convert/delete/reset the current
task/DB. Existing ordered-removal/recovery combinations are unsupported in this
new execution profile (standalone ledger combinations remain unchanged). The
current coordinator explicitly refuses this profile before agent calls; current
configuration/client/grouped queue/agent still select v5/v6. No operator init
CLI/public route exists. Next implement fresh retry and matched worker/priority/
UI/ordered-removal integration before bounded live acceptance. Do not widen guards
or treat generic pending receipts as a release permission for other old holds.

36 new tests pass; focused state/ledger/protection/cancellation/progress/lease/
group/uncertainty set 249 pass in 25.17s. Clean full regression **3415 pass in
544.57s**, including the corrected older-schema simulation from the earlier
ledger checkpoint. Ruff/compileall/diff pass. Final read-only 17:46:29Z lab
comparison: integrity ok,
all nine original fingerprints and eleven historical unknown rows unchanged;
normal epoch 2660 active/LEASED. Exact API/agent/Web IDs/images remain unchanged
and running. At 17:42:29Z original task 16,643 VERIFIED/32,425 plus ten reviewed/
present unknowns, 15,772 outstanding, ready/no error/zero unresolved attention,
zero pending-schema objects. Existing v6 runtime and original import continue.
No test device commands, new authority or recovery decision were submitted.
See docs/manual/deferred-confirmation.md.

## Earlier source-only checkpoint — durable pending evidence, 2026-11-09

`PendingConfirmations` implements an explicit immutable optional profile for
original settled-v7 sessions, ordered original attempt/job/claim/ACK scope and
one later complete observation. Full-root/delegation/current live-lease checks
bound atomic recording. First classification requires same device, strict
post-settlement start, complete fresh UTC evidence and identical shared read
identity/content. Labels AWAITING_CONFIRMATION/OBSERVED_PRESENT/CONFIRMED_ABSENT
are evidence only: no original creation proof or old-command replay permission.
Recording/classification leave original jobs, attempts, managed consent,
protection, cancellation waits, occurrences, task progress and leases unchanged.
RUNNING still blocks release; current configuration/client/queue/agent refuse v7.
Do not widen those guards or apply the new profile to the live DB as a shortcut.
No current runtime consumes the ledger. It has no public route or init CLI;
explicit initialization requires paused mutations/quiescence and old writers
refuse its unsupported schema. Existing recovery profiles remain compatible in
the new validator. See docs/manual/deferred-confirmation.md.

Next integrate distinct durable queue/attempt states, settled release,
current-policy/backoff fresh attempts and UI/priority/protection/cancellation
before bounded live acceptance. No deployment, `.env`, live DDL, reset/reimport,
new consent/recovery decision or test device command in this source-only slice.
Final ledger checks 55 pass; final focused persistence/transport/protection/
cancellation/lease set 270 pass in 70.15s. Full regression: 3378 pass plus one
obsolete old-schema simulation failure (it dropped the last option rather than
explicitly selecting the pre-extended profile). Corrected that test, not a guard;
the corrected test and all 55 new cases pass together (56 in 7.73s). No second
clean full run is claimed. Ruff/compileall/diff pass. Read-only 16:14:19Z comparison: integrity ok,
all nine original fingerprints and all eleven unknown rows unchanged. Status
16:14:36Z: original task 15,793 VERIFIED/32,425 plus ten reviewed/present unknowns,
zero unresolved attention, ready/no error, and zero new pending-schema objects.
Normal v6 epoch 2633 was active/LEASED; not global idleness.

## Earlier source-only checkpoint — transport foundation, 2026-11-09

Tracked-v7 END_PENDING transport is implemented and synthetic-tested, **not
deployed or selectable in current configuration**. Status 06 plus exact ordered
ACK scope and actual terminal cleanup returns a separate settled-pending value,
never verified creation/presence/retry authority. No extra Cisco read at this
terminal step; no fallback/reconnect/resend after missing/malformed evidence.
Versions 1–6 retain their original contracts. V7 retains v6 time/attempt/command/
sequence bounds and pending<=16; mutation-session lookup stays unsafe. Current
API configuration/high-level client/grouped queue and agent configuration still
refuse v7; configured-agent admission rejects it before inventory/SSH. Do not
"enable" it by widening those guards: first implement the explicit durable
pending profile, exact original attempt/ACK/session binding, causal complete
read classification, cancellation/protection/retry rules and UI. No current
RUNNING/UNVERIFIED job or lease may be released from the new transport value.

Shared vectors tests/fixtures/pending-end-v7.json; focused Python 283 pass,
Rust 95 unit +7 config +4 shutdown pass; locked release/all-target Clippy/fmt and
Ruff/compileall/diff pass. Clean final Python full suite: 3324 pass in 527.36s. One obsolete
unknown-version=7 test was corrected to 8; the earlier interrupted run had that
single stale expectation. No DDL, deployment, `.env`, credentials/trust/network,
authority/recovery decision, import reset or test device write. The existing
v6 original import keeps running on the runtime below. See
docs/manual/deferred-confirmation.md; do not claim cross-session confirmation,
automatic retry, throughput gain or live v7 acceptance from transport tests.
Actual release-binary isolated preflight accepts v6 and refuses v7 even with
all existing grouped/ADD gates enabled, without socket or SSH; synthetic config
only. No candidate image was deployed or live setting changed.
Final lab read 15:42:56Z: integrity ok/all nine original authority/protection/
inventory/recovery fingerprints and all eleven unknown rows unchanged. At
15:44:12Z original import 15,502 VERIFIED/32,425 plus ten reviewed/present
unknowns, zero unresolved attention, no error and execution recovery running.
A normal coordinator scheduling BUSY retried/recovered at 15:43:33–38Z; no
v7 command or recovery decision was submitted. Actual runtime remains below.

## Current laboratory runtime — updated 2026-11-09

API `52e05efca40d...` / container `7d82c196f5cc` now adds bounded local-only
BUSY retry for grouped ACK/ADD-result persistence. Only failed pre-write BEGIN
or a successful explicit rollback of the original still-open transaction permits
another DB-only callback; no RPC/claim/unknown commit is retried. Three attempts,
2s lock waits, 50/150ms backoff, 7s retry-start window checked after wakeup too.
All original fresh executor/profile/job/attempt bindings remain; failed rollback,
non-BUSY, lost ownership and exhausted bounds retain fences/partial results.
No schema/profile/protocol/authority/gate/deadline or Web/agent change. Compatible
rollback: `ftd-shun-api:lab-pre-result-retry-20261109` (the d3005b86a025 image,
which already understands the extended recovery marker). Keep all three overlays.

Critical final storage/group/lease/recovery checks: 161 pass; legacy/global paths:
127 pass; Ruff/compileall/diff and configured non-executing image preflight pass.
Clean final full Python regression: 3285 pass in 527.10s. Old API actually exited 0; stopped epoch 2613
IDLE, zero RUNNING, integrity ok, all nine authority/protection/inventory/recovery
fingerprints and all eleven historical unknown rows unchanged. Unchanged agent
`ea9085b90bf5` and Web `f42288374e68` did not restart. At 15:14:52Z original task
15,231 VERIFIED plus ten reviewed/present unknowns, zero unresolved attention;
startup epoch 2614 then actually released with 15 VERIFIED at 15:16:32.777Z.
Actual epochs 2614/2615 settled with 15/33 VERIFIED (48 total). At 15:20:34Z
original task 15,279 VERIFIED plus ten reviewed/present unknowns; normal epoch
2616 active/LEASED, fresh read, no new unknown/attention. Final 15:20:56Z integrity
ok, all nine original authority/protection/inventory/recovery hashes and all
eleven unknown rows unchanged. No speedup/full-list acceptance is claimed.
Web 200/401 checked. No live result-storage retry/induced lock is claimed.
Do not induce a live DB lock, reset/reimport
or replay old unknowns to test this. Follow docs/manual/result-storage-retry.md.

### Earlier checkpoint — extended recovery deployment

API `d3005b86a025...` / container `c8bb2950bdce` now supports the explicit
extended offline tracked-v6 recovery profile (17–64 system ADD claims). Agent
`e8cdc9925a8d...` / `ea9085b90bf5`, Web `f42288374e68`, all three overlays,
private v6 selection and the original 32,425-pair import are unchanged. After
actual API/Web/agent exit 0, fresh whole-DB review and checked exclusive backup,
decision `ed150402-84bc-407b-a1b2-23982d625ca0` at 14:30:43.356Z reconciled only
ATTENTION epoch 2600 (26 claims: 16 VERIFIED/10 UNVERIFIED after local SQLite BUSY).
All original job/attempt/request outcomes and old receipts remain byte-for-byte;
unknown total 11 remains, now reviewed history rather than unresolved attention.
The new optional immutable compact marker binds all claims within the unchanged
16-KiB receipt bound. **Older API writers are incompatible**; retained image
`ftd-shun-api:lab-pre-extended-recovery-20261109` is forensic, not a safe rollback
against this DB. Never remove markers/guards or restore stale authority to undo it.

Private state-volume archives: `private-backups/extended-v6-20261109/`
`source-online.db` and `before-live-reconciliation.db`, both checked. Earlier
November 4 `/tmp` evidence directories no longer exist after the host restart;
do not represent historical paths as current files. Actual-copy rehearsals passed;
Final-source full Python 3263 pass (500.21s), plus 77 focused recovery checks. Configured non-executing checks passed before/after activation,
Ruff/compileall/diff pass. Complete fresh read 14:31:33Z is after the receipt;
normal epoch 2601 admitted original-policy work, with no new hint/import/consent.
Epochs 2601/2602 actually settled with 33/32 VERIFIED ADDs (65 in 405.906s,
9.61/minute including their gap, bounded/unpaired and not a speedup claim).
At 14:38:27Z original task 14,886 VERIFIED plus ten observed/reviewed unknowns,
zero unresolved attention, original eight authority/protection/inventory hashes
and all unknown rows unchanged, integrity ok; normal epoch 2603 active/LEASED.
One coordinator-local numeric BUSY retry recovered automatically in this sample;
no unknown write was retried. It does not prove ACK/result-storage resilience.
Web health 200/anonymous 401. This does not fix SQLite contention or implement
durable cross-session first confirmation. Default recovery stays <=16; explicit
extended mode still refuses deferred/nonterminal/manual/REMOVE/FAILED/missing/
foreign scope. Later unknowns still hold; this receipt never releases later epochs.
Follow docs/manual/extended-session-recovery.md; keep the original import and
every existing authority/protection/unknown record. Do not reset or reimport.

### Historical runtime checkpoint — 2026-11-04

Latest matched API `c8e66dbd66c6...` / container `7d02442055d0`, agent
`e8cdc9925a8d...` / `ea9085b90bf5` explicitly select tracked grouped v6 via
private `FTD_SHUN_AGENT_BATCH_SESSION_VERSION=6`. All three lab overlays and the
same managed-v2 DB/original 32,425-pair import remain. V6 bounds are 240s/64
mutation attempts/256 commands/sequence <=130, pending groups <=16; only fully
verified/persisted/published fresh group reads permit new bounded queue segments.
Every claim retains original full-root/current policy/protection/lease/time/
uncertainty checks. Defaults remain v5/grouped false. Agent grace is 300s; drain
API first explicitly. Old API/agent exited 0, stopped epoch 2591 IDLE/no RUNNING/
new unknown; integrity ok/nine original fingerprints unchanged. Rollback pair
`ftd-shun-{api,agent}:lab-pre-multi-group-20261104` requires clean drain and explicit
v5 selection, never a stale DB restore. Web `f42288374e68` unchanged.
Full Python 3239, focused 244, Rust 91+7+4 pass; build/Clippy/fmt/compileall/Ruff/
diff/Compose and non-executing preflights pass. Actual released epochs 2593–2594
each VERIFIED 33 (groups 16/16/1), exact one pre-write DEFER and real settlement:
66 in 402.819s including gap, 9.83/minute. Short startup epoch 2592 verified four;
all first three visits 70/446.268s, 9.41/minute. Earlier unpaired four-visit sample
was 8.46/minute; gains are modest, not full-list/load/production acceptance.
At 14:07:10Z task 14,637/32,425, normal epoch 2595 active/LEASED, ready, integrity
ok/nine hashes unchanged, zero unresolved attention, one old reviewed unknown
retained; Web 200/401 checked. Do not reset/reimport/renew consent/clear evidence.
Known limitation: current offline recovery tools refuse epochs above 16 claims;
do not widen/bypass/reuse old receipts. Compatible larger-epoch recovery and
durable cross-session first confirmation remain unfinished. Session timing still
shows ~84s local work per ~201s visit (claims ~47s, result persistence ~13s);
diagnostics are not execution proof. Follow docs/manual/multi-group-sessions.md.

Latest API `f8ab909fdb10...` / container `2f00c613a2c7` aligns bulk admission,
attempt capture and legacy restoration to the existing 200,000-entry decoder
bound, replacing their stale 65,536-IP check. No wire/agent/schema/gate/secret/
network or authority change; old API exited 0, stopped IDLE epoch 2493 with no
RUNNING jobs, integrity ok and all nine original fingerprints unchanged. Web
`f42288374e68` / agent `e2d0128319c2` unchanged. Full Python 3213 and focused
255 checks pass; non-executing preflight passed. Rollback API reference:
`ftd-shun-api:lab-pre-policy-snapshot-cap-20261104`. Older API code can still
refuse valid snapshots above its old bound; do not clear device/database state
to fit rollback. At 11:45:54Z original task 13,412/32,425 VERIFIED, normal epoch
2495 active/LEASED, ready, integrity ok/nine fingerprints unchanged, no new unknown
or ATTENTION and zero unresolved queue attention. Deployed caps all 200,000,
fresh read and Web 200/anonymous 401 checked. Large policy evidence is validated
synthetically, not a live 200,000-IP FTD or throughput acceptance. Keep original
import, protection/receipts and all three overlays. See manual/large-snapshots.md
under docs; next work remains durable first confirmation/bounded batch execution.

Latest API/Web `7a005907d019...` / `b86fac92f284...` now separate validated
reviewed queue history from real unresolved attention. Raw UNVERIFIED=1 and its
original outcome remain; unresolved attention is zero, reviewed history one.
No new reconciliation, DDL, authority, replay or device command was submitted
by this presentation update. Old API/Web exited 0; stopped IDLE epoch 2472,
integrity ok, all nine original fingerprints unchanged. Agent stays
`e2d0128319c2` / `d972adf099df...`. Current containers API `15830248969b`, Web
`f42288374e68`; rollback tags `ftd-shun-{api,web}:lab-pre-reviewed-history-20261104`.
Full Python 3194 and browser 82 checks pass; BFF zero-attention/retained-history,
source-matching assets and Web 200/anonymous 401 checked. At 11:17:15Z original
import 13,168/32,425 VERIFIED, normal epoch 2474 active/LEASED, no new unknown/
ATTENTION, integrity ok and all nine fingerprints unchanged. Old open pages need
one reload. Later unknowns still warn; no old receipt suppresses them. Follow
docs/manual/operation-queue.md and retain all three lab overlays/current DB.

Latest API/Web `639135b3f440...` / `7e10ec88e7b5...` add evidence-scoped automatic
retry of local scheduling SQLITE_BUSY (5–60s capped backoff) and visible recovery/
stopped guidance. The old coordinator stopped at IDLE epoch 2423 after SQLite
contention, leaving the original import at 12,582/32,425 VERIFIED with no new
unknowns. API/Web actually exited 0 before replacement; stopped DB integrity and
all nine original authority/protection/inventory/recovery fingerprints unchanged.
Agent remains `e2d0128319c2` / `d972adf099df...`; gates/secrets/networks unchanged.
At 10:09:55Z new runtime reports running and a fresh read, original rolling queue
refilled to 16, but new write acceptance is still being observed. Keep the original
task and reviewed historical unknown; do not reset/reimport or reuse old receipts.
Rollback tags `ftd-shun-{api,web}:lab-pre-storage-retry-20261104` are compatible with
the current optional reconciliation profile. Full Python 3190, final focused
classification 10 and browser 78 checks pass. Follow docs/manual/execution-recovery.md:
only coordinator-local numeric BUSY retries; unknown RPCs/results and non-BUSY
storage/profile failures retain existing holds and operator review.
Bounded post-update acceptance now confirms read-only epoch 2424 and write epoch
2425 with 14 VERIFIED ADDs and actual settlement. At 10:12:02Z original task
12,596/32,425, integrity ok, all nine fingerprints unchanged, no new unknown or
ATTENTION; normal epoch 2426 active/LEASED, not global idleness. BFF recovery
metadata and shipped asset checked; retry tests are synthetic, not an induced
live storage lock or arbitrary unknown recovery.

Latest runtime: profile-aware API `517de8921634...`, Web `45392bd7edec...` and
shared-final v5 agent `d972adf099df...` are now deployed with all three lab
overlays. At 18:20:30.926Z, after actual API/Web/agent exit 0 and a checked
exclusive backup, new decision `e73e4081-5c21-44cb-a3fc-6c9cce80e3bc` reconciled
only original ATTENTION epoch 2060. Its nine original claims and one unknown
are retained; no old job/attempt was replayed or relabelled, original policy/
protection/inventory and old recovery receipts unchanged. The new optional
`managed_bulk_reconciled_jobs` profile binds that exact unknown to this decision.
Next work requires a complete read strictly after the receipt and all current
root/protection/backoff checks; later unknowns still block. Old DB writers refuse
this profile. Do not use an old image or restore stale authority to undo it.
The private archive is `quiescent-reconciliation-20261103-epoch2060/before-reconciliation.db`.
3170 full Python checks, 53 final focused checks and 75 browser tests pass;
actual-dataset rehearsal passed before activation. Read-only startup epoch 2061
and complete write epochs 2062–2064 settled; 14 VERIFIED each, 42 in 258.069s
(9.76/min excluding startup, 9.28 including). Native v5 visits use two complete
reads rather than four. Prior small v4 sample was 8.18/min; this is a bounded
unpaired gain, not whole-list/production acceptance. At 18:26:45Z task
7,587/32,425, one old reviewed UNVERIFIED retained, no new unknowns/ATTENTION,
integrity ok and eight original policy/protection/inventory hashes unchanged.
Normal epoch 2065 active, not globally idle; status 0.729s. Batch size is dynamic.
Later complete first-five sample (2062–2066): 14 VERIFIED each, 70 in 429.536s
(9.78/minute including gaps). At 18:28:36Z task 7,615/32,425, no new unknown/
ATTENTION, integrity ok/eight hashes unchanged, normal epoch 2067 active, status
1.056s. The reviewed pair's new job `30caf7ae-3cb2-5ee4-96bb-b9fc7c1d6eaa`
became VERIFIED at 18:26:58.233Z from a post-receipt read; its predecessor remains
UNVERIFIED and expired/cancelled. Do not relabel that old outcome or reuse keys.
Follow docs/manual/quiescent-managed-reconciliation.md, preserving original
unknown history and the receipt; never reuse this key to release a later epoch.

Historical pre-rollout checkpoint: shared-final v5 was **not yet deployed**.
During validation the old API/agent independently entered ATTENTION epoch 2060:
one ADD `db174cf8-3496-53d8-aa78-1096bc39b251` is UNVERIFIED. Agent diagnostics
show eight preceding ADDs/group read and an EAGAIN idle receive failure, with an
adjacent API SQLite-lock error. Logs are not proof that the ninth ADD was never
submitted; do not relabel/replay it, release the epoch or reuse the old epoch-942
verified-only recovery receipt. API drain exited 0, but stopped DB was ATTENTION,
not IDLE, so agent replacement and the new rollout were aborted. The exact old
API container `9c58b6329751` / image `124fad2d64df...` was restarted; agent
`6c844c0e08d1` / `08e5251f765c...` and Web `a22c285d6e96` are unchanged.
At 17:37:25Z: 7,545 verified / one unverified original-task member, 24,879
outstanding; integrity ok, nine original fingerprints unchanged, Web 200/401.
A new private consistent archive `managed-v2.pre-shared-final-hold-20261103.db`
has integrity ok. Keep that evidence and original task/authority/protection.

Candidate API `ddae8a1863d2...` / agent `d972adf099df...` implement v5 up to 16
pending ADDs and one shared final verification/snapshot/settlement, retaining
120s/16-mutation/64-command bounds and all current checks. V5 stage max is 30s;
receive-only local-processing wait is 30s capped by remaining session time, while
send/transfer stays 10s and v4 retains its exact old contract. 357 focused Python
checks and 99 Rust checks pass; full regression had 3150 pass plus two stale
version-expectation failures corrected and successfully rerun. See status/log;
do not claim a second clean full run or live throughput acceptance. Compatible
old pair retained as `ftd-shun-{api,agent}:lab-pre-shared-final-20261103`.
Do not invoke ordinary `up` against these candidate tags until the held case is
resolved under an explicit tested compatible recovery contract. No new migration,
authority, fixture, credential/trust/network change or task was submitted.

Latest API-only increment is `124fad2d64df...`: direct assigned-field equality
and canonical source construction avoid temporary containers; per-call manifest
encoding reuses only bounded literal device/class bytes. Every original member,
byte and profile/root/current eligibility check remains; no authority/result
cache, changed digest/input, schema, protocol, gate, deadline or verification.
3143 full Python tests and 163 focused checks pass; compileall/Ruff/diff and
built-image configured non-executing preflight pass. Same-snapshot query-only
32,425-member root median 0.54397 -> 0.46669s, not execution throughput.
Old API exited 0, stopped DB IDLE epoch 2002 with zero RUNNING/unknown work,
integrity ok and nine original authority/protection/inventory/recovery hashes
unchanged. Compatible rollback: `ftd-shun-api:lab-pre-literal-allocation-20261103`.
Web `f00749a88b58...` / agent `08e5251f765c...` and their containers are unchanged.
New API `9c58b6329751` is ready; Web health 200/anonymous 401. Retained audit
proves startup epoch 2003 VERIFIED five addresses, then 2004–2006 VERIFIED
10/10/9: 29 in 212.758s including gaps (8.18/minute); all four visits 34 in
258.344s (7.90/minute). This is a small sample, not a stable capacity/production
claim; batch size remains dynamic. At 16:27:58Z original task 7,092/32,425,
no device error/FAILED/UNVERIFIED/ATTENTION, integrity ok and nine hashes unchanged;
normal epoch 2007 active, not globally idle. Next profile equivalent SQL/full-
profile cost without dropping validation boundaries. A private larger SQLite
page-cache trial gave little gain; service memory/cache settings are unchanged.
Keep original task/authority/protection/recovery; no reset/reimport/consent renewal.

Current agent-only increment `08e5251f765c...` adds fixed CLI phase counters/timing
and opening time to existing cycle diagnostics; no changed commands, wire,
limits, semantic verification, authority, gates, configuration or dependencies.
Returned command envelopes/timing never prove successful writes or safe replay.
API/Web images remain `72d6ba21997c...` / `f00749a88b58...`. API drained exit 0,
IDLE epoch 1962 with no RUNNING/unknown work, integrity ok and nine hashes unchanged;
old agent then drained exit 0 before replacement. Agent rollback:
`ftd-shun-agent:lab-pre-cli-timing-20261103`. Same API restarted, Web unchanged.
96 Rust tests, locked release/fmt/all-target Clippy and 133 Python wire/session
checks pass. Diagnostic session IDs correlate with actual owner-bound audit.
Epoch 1963 verified one address; 1964/1965 verified nine each in 136.248s including
their gap (7.93/minute, not a speedup). Per full session: 9 target reads + 9 ADDs
cost 28.888–29.926s; four full reads 8.706–9.338s; opening 3.536–4.309s. API
local work still costs 25.046–25.356s, including 13.016–13.248s claiming work.
Next profile remaining local claim/validation overhead without skipping original
root/current eligibility checks or changing deadlines. At 15:45:08Z original
task 6,768/32,425, ready, no error/FAILED/UNVERIFIED/ATTENTION, integrity ok and
nine fingerprints unchanged. Normal epoch 1967 active; not globally idle. Web
health 200/anonymous 401. Do not reset/reimport or renew authority for throughput.

Previous API/Web increment is `72d6ba21997c...` / `f00749a88b58...`. Short list
statuses stay on one line, while explanations wrap and wide content scrolls
locally. Successful current-epoch productive settled sessions no longer impose
the empty-defer five-second cooldown; zero-progress/error backoff and all fresh
lease/session/admission/priority/uncertainty checks remain. Bind clears stale
progress. Agent `cbb6492d90a6...`, configuration and original authority are unchanged.
API drained exit 0 / IDLE epoch 1923, zero RUNNING/unknown jobs, integrity ok and
nine original fingerprints unchanged. Compatible rollback tags:
`ftd-shun-{api,web}:lab-pre-productive-continuation-20261103`. Startup epoch 1924
was settled read-only. Write epochs 1925/1926 verified 9/9 in 135.529s including
their 0.355s gap (7.97/minute, small sample, not whole-list acceptance). Prior
measured gaps were 5.174/5.184s. At 15:01:14Z: 6,446/32,425, ready, no device
error/FAILED/UNVERIFIED/ATTENTION, integrity ok and nine hashes unchanged. Normal
epoch 1927 was active, not globally idle. Web health 200/anonymous 401; tested
asset hashes match deployed HTTP assets. Agent container is still `bbc1607fb1da`.
Validation: 120 initial / 77 final focused Python, 75 browser checks; full run
3126 passed plus two obsolete HTML assertions corrected and passing separately
(including a final two-test rerun). Next measure per-CLI phases and remaining
execution overhead; keep the original task, authority and recovery evidence.
See status/log for precise scope and limits.

Previous API-only increment `e00a76582543...` removes repeated assigned UUID/IP
object conversion during complete original-root verification. Every member and
source byte is still checked per claim; canonical acceptance, stored digests and
all authority/profile/protocol/time/write guards are unchanged. No result cache.
Full Python 3117 and final focused 79 pass. Paired complete 32,425-member root
verification median 0.63679 -> 0.53923s (~15% lower), identical full results;
not a whole-import speedup. API drained exit 0/IDLE epoch 1897, no RUNNING/unknown
jobs, integrity ok and nine original hashes unchanged. Compatible API rollback:
`ftd-shun-api:lab-pre-root-decoding-20261103`; Web/agent/configuration unchanged.
Startup epoch 1898 was settled read-only. Write epochs 1899–1901 verified 9/9/9
in 216.366s including gaps (7.49/minute), no overall throughput gain established.
Bounded status at 14:32:18Z: 6,251/32,425, ready, no unknown/error/ATTENTION,
integrity ok and original hashes unchanged. Its five-second budget-defer follow-up
is implemented above; fixed per-CLI phase aggregates remain the next measurement.

Previous API-only increment `cb8c07f85ede...` uses equivalent profile SQL and an
exact same-transaction result handoff only in device-scoped claims/results.
Both full executor/profile boundaries, base audit validation, fresh exact-row/
delegation checks and original root/current eligibility remain. Global/legacy
paths keep independent resolution; no cache, schema, profile, gate, deadline,
protocol, authority or configuration change. Full Python 3095 and focused 223
tests pass. Complete query-only profile validation median fell from 69.13 to
61.46ms in eight paired same-snapshot checks, not an import speedup claim.
Old API exited 0, IDLE epoch 1877, no RUNNING/unknown jobs, integrity ok and all
nine original fingerprints unchanged. API rollback:
`ftd-shun-api:lab-pre-result-handoff-20261103`. Web/agent did not restart.
Retained audit confirms epochs 1878–1880 each VERIFIED nine addresses:
27 in 212.379s (7.63/minute including gaps). Nine-address result persistence
costs 3.130–3.346s versus earlier 4.17–4.31s; claims still cost 13.65–13.98s.
Bounded status at 14:08:05Z: 6,098/32,425, ready, no unknown/error/ATTENTION,
integrity ok and nine original hashes unchanged. This is not whole-list/load or
production acceptance; remaining root/claim/session overhead still matters.

Previous API-only increment `d5eff09ed228...` removes two adjacent redundant
grouped-claim profile scans while retaining both executor boundaries, complete
base audit validation and every original root/current eligibility check. No
validation cache or authority/bound/schema/gate change. Fixed local timing now
separates ACK persistence, group settlement and failed settlement. Full Python
3065 tests passed; built-image non-executing preflight passed. Old API exited 0,
IDLE epoch 1856, no RUNNING/unknown jobs, integrity ok and nine original
authority/protection/recovery/inventory hashes unchanged before replacement.
Compatible batch-capable API rollback tag:
`ftd-shun-api:lab-pre-claim-scans-20261103`. Web/agent did not restart. Original
32,425-pair task continues without reimport, hint or renewed consent. Consult
status/log for bounded live observations: settled epochs 1857/1858 verified
8+8 in 133.136s (7.21/minute); final status 5,915/32,425, no unknown/error/
ATTENTION, integrity ok and unchanged fingerprints. ACK persistence costs
about 2s/group, result settlement 3.8–3.9s and claims 13.7–14.7s. No significant
overall speedup is established; prioritize remaining measured local overhead.
This small reduction is not large-list throughput acceptance.

The lab now runs matching grouped-v4 API `e00a76582543...`, Web `51dddbe0d7f5...`
and agent `cbb6492d90a6...`, with private `.env`
`FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED=true`; examples default false. Keep all
three overlays. API/agent drained exit 0/IDLE epoch 1832 before replacement;
original authority/protection/recovery/inventory fingerprints are unchanged.
Durable owner/epoch-bound pending ACKs, priority/protection/cancellation/drain
flush and result-before-snapshot settlement preserve per-target outcomes and
all original bounds/checks. No schema, new import/consent, trust/network change
or reset. Rollback tags ftd-shun-{api,web,agent}:lab-pre-batch-20261103 retain old
matching images; drain and disable the batch gate before v3 rollback.
Real epochs 1833–1835 verified 8/9/8 (25 in 207.066s, 7.24/minute); first eight
used 19 CLI commands, one shared verification and a settled session. Latest
rollout checkpoint: 5,766/32,425, no unknown/error/ATTENTION, integrity ok. This is
not whole-list/priority-failure/multi-device/production acceptance. Full Python
3060, final focused 233, browser/Node 74 and Rust 92 checks pass. Next prioritize
measured local claim/validation overhead (15–16s per sampled session), not a
root-check bypass, expired-authority renewal, reset or reimport. See the batch
manual/status/log. Never infer uncertain ADD success from later generic presence.

Earlier API-only increment: `01a5c191d81d...` fixes restart-prefix starvation by
excluding same-device active observations before the 64-candidate scan. It retains
all fresh-snapshot/root/current-authority/protection/uncertainty checks, cutoff
and quotas. Full-root hashing reuses exact common JSON framing, never validation
results; fixed method-bound agent phases are diagnostic only. No schema/gates/
agent/Web/credentials/network changes. Compatible rollback tag:
`ftd-shun-api:lab-pre-observed-prefilter-20261103` (loses this restart fix).
API drained exit 0/IDLE epoch 1737 before replacement. Original 32,425-pair task
automatically refilled/continued without a refresh hint or new consent: 5,042 to
5,065 in a bounded sample, 23 VERIFIED/207.95s (~6.64/minute), three settled write
epochs, no unknown/error. Protection/standing roots/retained recovery receipt are
unchanged; task remains running. Full suite 3003 passed plus final-source focused
170 checks. Throughput remains inadequate for large lists: prioritize measured
ADD/verification/session execution next, not resetting work or removing checks.

Previous API-only increment: `399df3aedb97...` factors obsolete-work profile scans
within each transaction and logs bounded `device.session.timing` aggregates.
Rollback image `ftd-shun-api:lab-pre-dispatch-timing-20261103` supports the current
recovery profile. API drained exit 0/IDLE before replacement; Web/agent are unchanged.
Original 32,425-pair task continues (4,304 processed at the bounded observation),
with unchanged protected settings/standing authority/retained recovery receipt.
Observed throughput is only about six verified addresses/minute, not large-import
acceptance. Prioritize remaining execution/session overhead; do not recreate the
task, renew expired delegation, remove root checks or clear evidence to speed it up.
See current status/log for measurements and limits; timing is not execution proof.

The known desk lab now uses `deploy/compose.yml`, `deploy/compose.local-lab.yml`
and **`deploy/compose.managed-lab.yml` together**. Use all three for subsequent
lab operations. API/Web select `continuous-managed` on separate `managed-v2.db`;
device 1 / `fpr1010-lab` has its validated FTD 7.6.6 ADD profile, with agent
ADD/cycles/large reads enabled. Legacy admission/restoration controllers remain
off. Older statements below that every live feature is disabled are historical,
not the current lab configuration. Do not silently switch back to the old DB by
omitting the managed overlay.

Old `state.db` is retained unchanged alongside checked `state.pre-v2-20261030.db`;
only three current Protected-IP settings were copied, not authority or queues.
Prior images have `ftd-shun-{api,web,agent}:lab-pre-v2-20261030` rollback tags.
Credentials, pinned trust, authentication and networks were not changed.
The new labelled one-address `.253` lifecycle has VERIFIED initial creation,
automatic restoration and v2 retirement/removal, with independent absence reads.
Its generation 1 is retired; retain its requests/attempts/receipts, never reuse
them as permission to add again. See the current development-log entry for final
restart evidence and remaining acceptance limits. This is not a production
release, 10000-address/multi-device validation or uncertainty-recovery approval.

The API-only first-scan update now requests scoped fresh evidence after changed
managed consent, retaining minimum spacing and no-work behavior for replay/GET/
policy-only composition. Its separate `.254` fixture completed VERIFIED ADD and
v2 cleanup without any refresh-hint POST; that generation is also retired. The
lab has five VERIFIED jobs, no enabled targets and no outstanding scan. Do not
reuse either closed fixture's original keys as new authority.

The API now retries typed local failures before BEGIN and exact agent-proved
SSH opening failure before any Cisco command. Configured clients select strict
BEGIN `17`; missing/generic/later opening proof and unknown ADD/REMOVE retain holds.
Release needs a first-opening proof, live exact epoch and no claimed/uncertain
work; normal strict release also needs actual terminal settlement in that epoch,
including after local processing errors. Old LEASED/ATTENTION is never cleared.
Matching API/agent rollback tags are `lab-pre-opening-20261030`; Web is unchanged.
The idle old agent needed stop timeout/SIGKILL only after API drain and verified
zero RUNNING/non-IDLE state. That historical shutdown limitation is fixed by the
2026-11-02 increment below.
See docs/manual/opening-recovery.md before changing this boundary or rolling back.

Late pre-send claim eligibility expiry now has a separate local rollback-only
classification. The worker stops selecting mutations and obtains real END/final
read settlement for its existing session. No rejected job is sent or marked
successful. Lost/expired leases, generic local errors, unknown RPCs and existing
ATTENTION still retain their fences. The old lab epoch 942 is not released by
this prevention fix; its complete dataset has a separate private SQLite backup
`managed-v2.pre-claim-expiry-20261102.db` with integrity `ok`.

The subsequent narrow offline recovery design supersedes the absolute no-release
rule only for fully evidenced VERIFIED/NOOP claims after actual API/Web and agent
stop. Its optional compatible profile retains the exact original ATTENTION row
and claim evidence in an immutable ledger, checks a short-lived whole-DB review
and private backup, and permits only its receipt-bound same-epoch IDLE transition.
No unknown/missing/failed job is replayed or relabelled, old keys cannot release
later epochs, and later bulk evidence must be newer than recovery. Startup/GET
never create this ledger or recover. Follow docs/manual/verified-epoch-recovery.md;
this is the designed recovery path for the original lab import, not permission
to drop guards or reset its epoch. Old images refuse the new exact profile.

The agent now handles SIGTERM/SIGINT with listener closure and joined worker
drain, retaining original session bounds/settlement and all uncertainty. The
180-second Compose agent grace does not replace explicit API-first drain.
Capacity 1 remains serialized with successors in the existing bounded kernel
backlog. Real PID-1 idle SIGTERM exited 0 promptly after a settled read-only FPR
cycle; synthetic tests also cover admitted work and repeated signals. API/Web
images, DB, credentials, gates and networks are unchanged. Agent rollback tag is
`ftd-shun-agent:lab-pre-shutdown-20261102`; older code loses graceful shutdown.
Follow docs/manual/agent-shutdown.md. Process exit never proves unknown remote
work safe to replay.

The 2026-11-02 matching API/agent update additionally consumes exact settled
read-only failure `04 version failed_read sequence` for initial/priority/final
reads, with zero mutation steps, successful cleanup and post-handler/guard/IDLE
completion. The client/worker bind its own current read; live-epoch release also
refuses any mutation claim, even completed, and audits `DEVICE_LEASE_READ_FAILED`.
Use the existing capped backoff/new fresh session, never clear old holds or replay
unknown ADD/REMOVE. API/agent rollback tags are now
`ftd-shun-{api,agent}:lab-pre-read-recovery-20261102`; no schema/gate/secret/network
change, Web unchanged. Healthy FPR read acceptance passed with five VERIFIED jobs,
zero enabled targets, IDLE and unchanged three protected settings. Failure tests
are synthetic, not induced live outages. See docs/manual/read-failure-recovery.md.

The later 2026-11-02 tracked-session rollout now selects BEGIN `18` with the
current lease-owner UUID. Local lookup `19` can recover a lost read-only terminal
receipt from the same still-running agent's bounded 4096-entry completion journal.
It publishes only after original handler/resource/guard/worker-IDLE completion;
missing/evicted/active/restarted/unsafe state never releases a hold. Exact live
epoch and no-claim/no-uncertainty checks remain, with separate
`DEVICE_LEASE_READ_RECEIPT_RECOVERED` audit. New API needs matching tracked-capable
agent; no fallback. Rollback pair is now
`ftd-shun-{api,agent}:lab-pre-session-lookup-20261102`. Healthy and deliberately
unconsumed-END read-only FPR checks passed, unknown nonce refused; API ready,
five VERIFIED jobs, no enabled targets, IDLE and unchanged protection. No writes,
DB/schema/gate/secret/network/auth changes; Web unchanged. This does not recover
old held epochs/crashes or unknown mutations. Follow
docs/manual/session-completion-lookup.md.

## Source of truth

The 2026-11-02 import-capacity update accepts source-only Cisco shun exports and
100,000 input IPv4s/lines/rows in 16 MiB UTF-8, retaining the 100,000 device/IP
pair total. Matching API/agent complete snapshots support 200,000 entries /
16 MiB typed data / 32 MiB full CLI output, without relaxing time/write bounds.
The lab runs the matched API/Web/agent update; rollback tags are
`ftd-shun-{api,web,agent}:lab-pre-large-import-20261102`. At that rollout no real
bulk list had been applied; synthetic 95,081-row storage is not live load acceptance.
Existing operator authority/jobs/protection remain unchanged. Follow current
project status and docs/manual/imports.md / docs/manual/large-snapshots.md.

Later on 2026-11-02 the operator confirmed a 32,425-pair lab import. The old
runtime hit `Restoration lease or delegation expired during claim.` At that
checkpoint device 1 was held in ATTENTION epoch 942; do not reset/reimport to bypass
the original evidence or the explicit compatible recovery procedure.
The new API/Web task-progress/nonblocking-local-work update preserves its exact
fence, authority, 86 VERIFIED / 52 CANCELLED jobs and protected policy. It displays
80/32,425 processed with 32,345 outstanding; the import has NOT resumed. Rollback
API/Web tags are `ftd-shun-{api,web}:lab-pre-import-tasks-20261102`; agent unchanged.
No live cancellation or new authority was submitted by development checks.
See current project status/development log for validation and the retained limit.

That original epoch was explicitly recovered at `2026-11-02T19:36:55.272Z` after
verified API/Web/agent exit 0, using the tested backup/review-bound offline tool.
The optional `managed_bulk_device_recovery` profile is now installed. Its immutable
receipt retains the exact original ATTENTION row and three VERIFIED claims; no
job, root authority or protection was changed/replayed. New API image is
`553abe73cab2...`; Web/agent images are unchanged. The private checked backup is
`verified-recovery-20261102/before-recovery.db`; rehearsal files are separate.
Old pre-ledger API images refuse this schema, so do not force a source downgrade.
At first, FPR TCP/22 timed out from both agent and Docker-host namespaces. Those
pre-command failures released safely with normal backoff and no new unknown jobs.
The operator then confirmed this was their other lab work and restored access.
The same running services automatically obtained fresh reads and continued the
original import without restart/recovery/hint/new consent. An active-write sample
advanced 127 to 151/32,425: 24 new VERIFIED in 260.25s, four settled epochs,
no new ATTENTION/unknown jobs, integrity `ok`. Complete sampled epochs verified
seven operations per shared SSH session; status latency was 0.530–2.160s.
This is pre-command outage/reconnect acceptance, not unknown-write recovery or
whole-list/load acceptance. Original task remains running on the same images and
profile. Next priority is measured large-import throughput (currently 5.53/minute),
not another hold reset or reimport. Keep all three lab overlays and original
authority/protection/verification/cancellation/priority behavior.

Read these documents before making a material change:

1. [`docs/architecture-and-security-design.md`](docs/architecture-and-security-design.md) is the normative architecture and security specification.
   Its 2026-10-20 working-version alignment incorporates
   [`docs/working-version-plan.md`](docs/working-version-plan.md), the latest
   operator-approved product target; distinguish that target from current code.
2. [`docs/project-status.md`](docs/project-status.md) records what is implemented, intentionally unavailable, and next.
3. [`docs/development-log.md`](docs/development-log.md) is the chronological engineering record.
4. [`docs/manual/`](docs/manual/README.md) contains contributor, deployment, and operator procedures.

If an implementation conflicts with the architecture document, stop and resolve the design before continuing. Do not silently weaken the security model to make a feature easier to implement.

## Required development records

Keep the written project record current. For every material change to code, security controls, deployment, data schema, API or agent protocol, authentication, or operating procedure:

- update `docs/project-status.md` to reflect the new current state;
- append a dated entry to `docs/development-log.md` describing the change, validation performed, and known limitations or follow-up work; and
- update the relevant manual and architecture document when their instructions or design guarantees changed.

Do not rewrite historical log entries except to correct an objective error; add a correction entry instead. Small spelling-only edits do not need a log entry.

## Security invariants

- The product exposes semantic operations only. Never add arbitrary Cisco CLI, command strings, free-form device routes, or unvalidated protocol fields.
- Keep FTD SSH credentials exclusively in the privileged agent. The web and API services must never receive them.
- Preserve the fixed binary Unix-socket protocol and its exact length/range validation. A successful state change requires a verified agent success response; otherwise fail closed.
- Caddy must remove client-supplied `Remote-*` headers and set trusted identity headers only after successful Authelia ForwardAuth. The Web/BFF may trust these headers only on its private Caddy Unix socket.
- Do not publish Web, API, database, Authelia, or agent ports. Caddy is the sole external listener.
- Development authentication headers and mock-agent mode are local-development tools only; they must not be enabled in a deployed environment.
- Do not commit `.env`, Authelia user files, device inventory files, private keys, secrets, database files, or production logs. Use the tracked example files instead.

## Implementation and validation

The dated checkpoints below retain implementation history. Interpret their old
per-fixture approval/no-lab-activation requirements under the newer development-
stage policy above. They do not justify repeated approval requests for ordinary
known-lab work or put legacy-dev conversion back on the critical path. Actual
runtime availability, evidence limitations and correctness/security checks remain.

- On 2026-10-20 sequential product alignment prioritized a usable working version:
  managed-only service additions/adoption,10000-IP selected-device import,
  per-device credentials/parallel serialized streams, continuous dispatch,
  interactive priority, permanent whitelist retirement, automatic evidence-based
  recovery and confirmed Emergency Purge. Follow docs/working-version-plan.md and
  the normative amendment before planning more offline incident extensions.
  Conflicting older product requirements are historical/current-code contracts,
  not the next delivery target. Do not bypass them ad hoc: implement reviewed
  reconciliation/concurrency/capacity/migration contracts, preserve original
  uncertainty/receipts and all security invariants, and retain existing live gates
  and fixture/migration authorization boundaries. This alignment is not approval
  to activate features, rearm old isolation, change secrets or mutate the lab.
- While working on the current non-production lab stack, the operator authorizes
  deployment of validated, in-scope changes without a separate confirmation for
  each release (2026-10-16). Announce the affected services and operational impact,
  preserve rollback options, and record deployment checks. API restarts may
  execute already admitted queue/policy work. This does not authorize production
  rollout, new test mutations/bulk imports, destructive data changes or bypassing
  feature-specific validation/security gates. Reconfirm if the target environment
  is unclear or changes beyond the current lab.
- Prefer small, reviewable changes and preserve existing user work in a dirty tree.
- On 2026-10-19 the operator approved the exact one-address managed lifecycle
  experiment in `docs/manual/managed-lifecycle-validation.md`: device 1 /
  `fpr1010-lab`, unused TEST-NET `198.51.100.252`, reviewed seven-table migration,
  one standing intent, initial creation, one operator-induced disappearance,
  one restoration and final combined retirement/removal. The approved
  trusted-host actor is `maintenance:managed-lifecycle-validation`, with Operator
  authority limited to this fixture; do not impersonate a Web identity. Temporary
  gates/profile are limited to that runbook's <=60-minute activation window.
  Fresh Basic-session absence/unused-address evidence is required before setup.
  Restore disabled experimental gates/profile and desired suspension afterward,
  retain evidence/schema, and resume ordinary monitoring. No bulk/fleet test,
  closure migration, physical reboot, unrelated address or uncertain ADD replay
  is authorized. This bounded exception does not relax the defaults below.
  The experiment completed and closed on 2026-10-19 by10:41Z: VERIFIED initial
  ADD, VERIFIED restoration, VERIFIED combined cleanup, independent Basic
  evidence, original-key non-reenable and two no-readd baseline reads including
  restart. Authorization is consumed, not reusable. Current lab retains seven
  managed tables, one retired generation1 and two verified attempts; do not
  expect empty optional schemas or erase them. All experimental gates/profile
  are restored off, desired restoration suspended and ordinary monitoring/work
  available. New policy activation/fixtures still need separately scoped approval.
- Use parameterized SQLite access and retain audit events as append-only records.
- Automatic queue retention must preserve UNVERIFIED jobs and captured ADD
  predecessors of WAITING_ADD/ADMITTING/ATTENTION cleanup, with linked requests.
  Age or abandonment never resolves uncertainty. Malformed held fleet references
  refuse queue pruning; inspection must distinguish ADD evidence from REMOVE
  attention. Older missing evidence stays missing, never reconstructed as success.
- Offline ACKNOWLEDGE_UNRESOLVED records administrative review of an ordinary
  UNVERIFIED or single/fleet ATTENTION case. Its separate optional ledger is never
  created by startup/GET/managed initialization. Keep outcomes, policy, evidence
  holds and resume blockers unchanged; review the whole original fleet scope.
  Decision keys cannot gain queue/policy/cleanup/restoration/abandonment authority.
  Follow docs/manual/incident-acknowledgements.md. No lab migration/decision or
  new fixture is authorized by implementation or default-disabled deployment.
- Document migration, backup, rollback, and operational impact when changing schemas or deployment configuration.
- Separate offline ISOLATE_INCIDENT now supports acknowledged ordinary/single/
  fleet cases with atomic whole-scope retirement and retained pair latches.
  Preserve original outcomes, ATTENTION and evidence. Block new manual mutations,
  cleanup, MAINTAIN/restoration and recheck claims; protected removal stays
  independent. A distinct resume-isolated-policy validates every original scope,
  latch, retired policy and job/link plus every separate uncertainty/abandonment;
  neither acknowledgment nor a fleet receipt covers an independent ADD case.
  No release/rearm/HTTP exists. Follow docs/manual/incident-isolation.md. Optional
  migration, isolation/resume or new lab fixtures still require scoped approval.
- For Python changes, run at least:

  ```bash
  python3 -m compileall -q src tests
  python3 -m pytest -q
  python3 -m ruff check .
  git diff --check
  ```

- For agent changes, also run:

  ```bash
  cargo build --release --locked --manifest-path agent/Cargo.toml
  cargo test --locked --manifest-path agent/Cargo.toml
  ```

- Validate Compose changes with `docker compose --env-file .env -f deploy/compose.yml config` using temporary, non-secret local configuration. Do not commit that configuration.
- Live evidence covers device-scoped removal and the separately approved one-address ADD/v3 creation/no-op/cleanup recorded on 2026-10-16. All ADD gates remain default-off and were restored off after that experiment. Traffic, fleet creation scope, large-load and production acceptance remain pending. Default-off implementation/deployment does not authorize new device mutations or general enablement. Do not present either write path, mock mode or socket transport as production-ready.
- On 2026-10-17 the operator requested restoring service-managed manual shuns
  after confirmed disappearance. The managed-shun architecture amendment and
  design manual replace the former one-time-only target requirement, not the
  current implementation. Restoration needs explicit durable/revocable desired
  policy, protection priority and atomic retirement on service removal. Do not
  convert old imports/history into standing authority, renew expired user
  requests or replay uncertain ADD. The isolated registry foundation is now
  implemented; optional read-only API/UI visibility does not initialize or
  authorize policy. Single-target/fleet cleanup now have default-off admission;
  its optional waiting-cleanup schema is not initialized by startup. Read-only
  visibility/review preparation never invoke admission. Confirmation requires
  the independent default-off `FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED` gate,
  socket mode/shared cleanup worker and explicit
  existing schemas. All live gates remain off. Follow docs/manual/managed-cleanup.md.
  Exact single intent/generation and full frozen fleet scope are rechecked;
  ready-only never silently becomes ordered waiting. Separate frozen
  fleet reviews read the observed/enabled-managed union with a transactional
  scope-comparison prerequisite. An offline ready-target fleet coordinator now
  retires enabled targets and admits one whole-scope REMOVE transaction; it
  rejects any unfinished ADD/waiting cleanup/disabled device without changes.
  A separately digested explicit ordered mode now reserves the whole scope
  behind captured RUNNING ADDs, preserving original deadlines and uncertainty;
  QUEUED one-time ADD still conflicts. Its optional retained authority/barrier
  tables are never initialized by startup. Strict fixed device/fleet private
  admission routes use those coordinators; no arbitrary action/scope. A default-off
  shared worker advances at most eight single/eight fleet roots before cutoff;
  no second executor or partial root promotion. Never simulate atomic fleet
  writes by looping over the single-target coordinator. Separate
  policy-only RETIRE and owner/Administrator waiting-cleanup cancellation are
  supported local revocation controls; neither admits device work nor cancels
  independent one-time jobs or a RUNNING ADD. A separate frozen single-pair
  standing grant now has default-off policy-only MAINTAIN admission behind
  `FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED=false`, requiring explicit consent,
  profiles and existing optional registry/attempt schemas. It never migrates,
  adopts observations/imports, wakes work or clears attention. Old-key replay
  cannot re-enable policy. Follow docs/manual/managed-grants.md. No HTTP resume route.
  A separate pasted-list standing workflow freezes at most 1000 exact pairs/64
  devices with explicit recurring consent and 100-row POST review pages. Its
  fixed MAINTAIN batch route uses the same default-off gate and one whole-scope
  transaction, never a single-target admission loop. Invalid/conflicting members
  reject the entire scope; original-key retries never re-enable retired policy.
  It does not initialize schemas, adopt imports, queue/hint work or permit lab
  grants. Follow docs/manual/managed-batch-grants.md.
  Separate offline managed maintenance now supports reviewed atomic empty-schema
  initialization and existing-policy resume, with checked backups, exact-state
  five-minute digests and a fresh-read barrier. It never adopts observations,
  resets uncertainty, creates/re-enables intent, renews requests, queues work or
  changes gates. Never invoke migration/resume on the lab without separately
  scoped activation approval. Follow docs/manual/managed-maintenance.md.
  The offline `attention` report is read-only and snapshot-bound, combines
  retained uncertainty/cleanup cases with honest missing/inconsistent evidence,
  and never resolves a latch, writes audit, initializes state or permits retry.
  Follow docs/manual/managed-attention.md. Separate offline restoration-incident
  abandonment now has its own explicitly reviewed optional ledger migration and
  five-minute/original-key/typed-IP confirmation. It records immutable minimal
  evidence/receipt, retires current policy and retains original outcomes/latches.
  No rearm, ordinary/fleet resolution or live activation is enabled. Normal
  resume remains strict. Separate offline `resume-unrelated-policy` requires
  an existing closure ledger, exact validation of every failed/uncertain attempt's
  own abandonment and permanently retired pair, no other uncertainty or pending/
  attention cleanup, checked backup and a five-minute state-bound review. It
  resumes only other already enabled policy with a fresh-read barrier; it never
  clears latches, creates authority, queues work or changes gates. Follow
  docs/manual/managed-unrelated-resume.md; no lab invocation is authorized.
  Abandoned pairs cannot receive MAINTAIN/restoration, and closure keys
  cannot gain other authority; original receipts remain observational. Base
  initialization/startup/GET never creates the ledger. Do not invoke migration/
  abandonment in the lab without scoped approval. Follow docs/manual/managed-abandonment.md.
  Protected-IP saves now permanently retire matching maintenance in the same
  transaction, with reviewed managed revision, original authority and real-actor
  audit. Disabled/deleted protection never re-enables old policy. Unknown optional
  state is not zero: allow strengthening, retain enabled protection as a barrier
  and refuse weakening until retirement can finish after repair. GET/startup
  never retires or initializes policy; RUNNING/uncertainty/cleanup evidence remains.
  Dirty forms retain reviewed revisions. Ordinary manual removal is guarded against enabled policy,
  including missing fleet targets, and MAINTAIN rejects pending/running removal.
  Protected automatic removal remains independent. An offline system restoration
  source now binds fresh complete snapshots, intent/generation/authorization and
  retained attempts to shared jobs without fake user roles/imports. Claim has a
  separate default-false capability supplied only by the experimental restoration
  controller. `FTD_SHUN_MANAGED_RESTORATION_ENABLED=false` remains the default;
  enabling it also requires API ADD/cycles/large reads and explicit profiles,
  existing optional schemas and unsuspended standing policy. Discovery uses only
  complete successful fresh reads, bounds new work to 16 jobs/64 checks per sweep,
  and never bypasses the frozen cutoff or >=60s cooldown. Startup/GET never
  migrate, adopt or admit. All live gates remain off. Retirement/
  protection cancel unstarted system ADD atomically; RUNNING remains ordered.
  FAILED/UNVERIFIED latches survive queue retention and new generations; no rearm
  or HTTP resume route exists. Normal offline resume refuses those latches;
  the separate unrelated-policy action preserves them on retired pairs. Standing
  admission remains disabled in the lab. No startup initializes its
  optional attempt ledger. Follow docs/manual/managed-restoration.md; do not
  seed the ledger or enable dispatch/discovery in the lab as a smoke shortcut.
  Follow docs/manual/managed-controls.md. A default-off cleanup-worker hook may advance
  existing waits under the shared lease before its cycle cutoff; it does not
  enable admission, ADD or restoration and never initializes optional schemas.
  Composite offline recovery now provides a durable mutation pause and ordinary
  resume only. Older images ignore that pause; follow docs/manual/recovery.md.
  Do not seed pending handoffs or enable the worker in the lab without scoped
  approval and remaining executable controls/protection/fleet validation. All live gates
  remain off; bounded fleet status and waiting-only Web revocation are available,
  but combined admission stays disabled. Offline migration/resume tooling is
  implemented, not invoked in the lab; uncertainty resolution and separately
  approved migration/policy activation/live fixtures are still required.
- On 2026-10-16 the operator separately approved the one-address service
  experiment on lab device 1/fpr1010-lab: unused TEST-NET 198.51.100.251,
  temporary gate/profile enablement for that device only, one queued creation,
  already-present/no-op verification and device-scoped cleanup, then restore
  ADD-disabled operation. Fresh Basic-session absence was supplied. Use an
  explicitly labelled trusted-host maintenance actor, not spoofed Web identity;
  cleanup may use the same private queued API. This is a bounded CLI-lifecycle
  validation exception, not approval for a long list, unrelated IPs, production,
  data-plane changes, arbitrary CLI or leaving ADD enabled. Stop on unexpected
  pre-existing/scope state; retain uncertainty without automatic replay.
  The experiment is now complete: VERIFIED creation, NOOP, VERIFIED cleanup,
  original-key replay without re-add and restored disabled-mode observation.
  Its one-fixture authorization is consumed, not reusable for new writes.

