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

## Current laboratory runtime — updated 2026-11-03

Latest API-only increment `e00a76582543...` removes repeated assigned UUID/IP
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
integrity ok and original hashes unchanged. Next review the five-second budget-
defer cooldown after successful progress (not zero-progress/error backoff), then
measure fixed per-CLI phase aggregates; neither follow-up is implemented yet.

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

