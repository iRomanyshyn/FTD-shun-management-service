# Project Status

Last updated: 2026-10-17

## Current increment

**Preparatory managed-removal review and read-only cleanup visibility (2026-10-17).**
Operators/Administrators can select one retained managed target and prepare an
immutable session/cookie-bound review. Confirmation is unconditionally 503:
no admission call, policy/job/audit change or device action, even with a forged
enablement flag. Optional private GET and authenticated view distinguish absent
schema/unavailable state, waiting/attention and actual linked queue outcomes;
active/attention are prioritized and settled rows collapsed. Opening/reviewing
never initializes tables. Pure canonical intent is shared without Web importing
the coordinator. All 424 Python tests and 18 Chromium scenarios (19 reported
tests) pass; compileall/Ruff/JS syntax/diff/link checks pass. See
[Managed Removal Review](manual/managed-removal-review.md).

Deployed only API/Web to the authorized lab after preserving paired images
`before-managed-review-20261017t143643z` and a checked 0600 SQLite backup on the
volume/ignored host path. Packaged Python 3.12 isolated review/refusal/footer
smoke passed. No managed/handoff tables exist after deployed GETs; stable device,
policy, queue/request/origin/state/events match backup exactly. Eight VERIFIED/
one NOOP, zero active shuns, policy three entries/revision 3 and disabled ADD/
zero eligible devices are preserved. Integrity/foreign keys pass. Agent/Caddy/
Authelia IDs unchanged; normal v2 cycle at 14:40:16Z used two reads, zero mutations,
11494 ms, next baseline 14:45:16Z/no error. Anonymous new Web paths are 401 and
TLS-verified HTTPS returns 302 to auth.lab.test. No live identity spoofing, seed,
configuration change, admission or forced refresh. Reload browser tabs once;
authenticated visual checks and executable managed integration remain pending.

**Offline managed removal handoff coordinator (2026-10-17).** Implemented
single-target reviewed RETIRE_AND_REMOVE: atomic retirement and ordinary removal
or durable WAITING_ADD, without cancelling/overlapping a running ADD. Immutable
composite authority, original deadline, concurrent/idempotent replay, bounded
leased settlement, known pre-write deferral, uncertainty preservation and
attention/cancellation are covered. Optional waiting reservations share normal
capacity/request/rate limits and protect predecessor retention; old keys cannot
requeue after history pruning or retire a new generation. All 409 Python tests
pass, including 25 new coordinator cases, plus compileall/Ruff/diff/link checks.
No HTTP/UI/scheduler hook, normal-startup schema initialization, restoration,
live migration, job/policy admission or deployment. All ADD gates remain off.
Next: frozen controls and visible waiting/attention, worker wake/expiry, fleet/
protection handling and composite recovery before live integration. See
[Managed Removal Handoffs](manual/managed-removal-handoffs.md).

**Caller-owned queue admission foundation (2026-10-17).** Added a savepoint-
protected `apply_enqueue()` hook, with ordinary admission using the same path.
Synthetic tests compose managed retirement and removal in one transaction:
failures roll back both policy/queue effects, and acceptance logs cannot be
emitted by the hook before outer commit. Idempotency, coalescing, permissions,
TTL/capacity checks and opposite ADD/REMOVE conflicts remain unchanged.
This is not a runtime managed coordinator or RUNNING-ADD cleanup handoff;
managed UI remains read-only and all ADD gates stay off. No schema/configuration/
protocol change, live policy/job, device operation or deployment. All 384 Python
tests pass, plus compileall/Ruff/diff and documentation-link checks. Browser/
agent code is unchanged and those suites were not rerun for this increment.
See [transaction composition](manual/operation-queue.md#caller-owned-admission-transactions).

**Versioning convention documented (2026-10-17).** The
[Versioning manual](manual/versioning.md) records the manual single-source
package/footer number, release increments and pre-1.0 compatibility, separate
agent/protocol identifiers, and release verification/rollback evidence. Git/
development-build identity is a future proposal, not implemented automation.
No version bump, runtime change or deployment was performed.

**Product version footer and read-only managed visibility (2026-10-17).** Every
server-rendered page displays v0.1.0 in a normal-flow footer; package build and
Jinja share `ftd_shun_manager.__version__` as their only source. Added a Managed
shuns tab for all authenticated users and optional private GET resource. Reads
never initialize/migrate/adopt policy or submit jobs. Missing registry is
explicitly uninitialized; partial/malformed state is unavailable, not fabricated
empty. Normal fleet monitoring remains available when optional managed state
is invalid. Cheap availability/initialization/revision metadata drives dynamic
updates alongside normal observation/protection revisions.

The view separates desired/stopped state, local presence, protection/device
blocking and original authorization; restoration is explicitly unavailable and
Last verified restoration is Not recorded. No forms/write/resume controls,
managed confirmation, controller, gate enablement or schema change. All 365
Python tests and 17 Chromium scenarios (18 reported tests) pass, plus compileall,
Ruff, JavaScript syntax and diff checks. The packaged Python 3.12 isolated smoke
confirms version/footer alignment and no managed migration. See
[Managed Shuns](manual/managed-shuns.md#read-only-managed-shuns-page).

API/Web are deployed to the approved lab with prior paired images and a fresh
checked SQLite-safe backup retained. Agent/Caddy/Authelia IDs are unchanged.
Optional managed GET reports uninitialized/read-only/controller unavailable;
no managed tables were created. Admission/execution remain false, eligible zero,
eight VERIFIED/one NOOP and policy three entries/revision 3 preserved. Preflight
already found zero active shuns, unlike the earlier 61-row observation; no cause
is inferred and no assistant deletion/restoration was submitted. Stable observed
state, jobs/requests/origins and policy match the backup after rollout; integrity
and foreign-key checks pass. The ordinary v2 cycle succeeded at 12:50:20Z with
two reads/zero mutations/8448 ms, next baseline 12:55:20Z/no error. Anonymous new
page/status remain 401 and HTTPS redirects to Authelia (302) with TLS verification.
No real configuration/inventory/.env or policy/job changed. Reload browser tabs;
authenticated live visuals and managed write/restore validation remain pending.

**Offline managed-policy registry foundation (2026-10-17).** Implemented
explicit maintained-mode canonicalization, durable desired targets, immutable
request/authorization ledger, optimistic revisions and atomic actor audit.
Retirement works for missing/disabled/protected targets; old-key replay cannot
reactivate it, and explicit re-enable creates a new intent UUID/generation.
Legacy one-time keys/history are not adopted. Existing observed shuns require a
separate adoption flow; duplicate enabled intent records actor NOOP without
changing its original authorization or fabricating creation provenance.

Initial bounds are 1000 total target keys including retired tombstones and
10000 retained request keys, with a 1000-slot retirement reserve. No eviction or
silent truncation; current history pruning does not erase policy/authorization.
Caller-owned transaction/savepoint supports future atomic removal composition;
queue cancellation/running-ADD handoff is not implemented. The consistent view
separates desired state, local observation and protection. Explicit initialization
creates three empty additive tables with restoration suspended; ordinary API/
Store startup does not initialize or use them. No routes, UI, settings, queue
discovery, device operations or live migration/deployment changed. All 357 Python
tests pass, including 27 new registry cases; compileall, Ruff, relative-file link
and diff checks pass. No Web/agent code changed, so browser/Rust suites were not
rerun. [Managed Shuns](manual/managed-shuns.md) documents the integration boundary
and remaining work. ADD remains off; current UI still has no managed workflow.

**Managed-shun restoration requirement (2026-10-17).** Recorded the operator's
change from one-time-only imports to explicit durable desired-present policy
for future service-managed additions. After a new complete successful snapshot
confirms absence, managed targets should restore through the shared bounded
queue; service removal retires the exact desired scope so it cannot reappear.
Protected IPs override maintenance. Failed/stale/partial reads never imply
absence; uncertain ADD must latch attention rather than be retried under a new
ID. Desired authorization is separate from the old 15-minute manual delegation;
legacy imports/history/SSH-observed entries are not silently adopted.

This is a design-only increment, **not implemented or enabled**. Updated the
normative amendment, working agreement, plan and relevant manuals with durable
policy/observed/provenance separation, removal/running-ADD handoff, missing-target
UI, protection-resumption warnings, retention/restore suspension and staged
acceptance. See [Managed Shuns](manual/managed-shuns.md). Current code/review
still implements one-time imports. No schema, code, settings, deployment,
queue/policy admission, device read or mutation changed. Documentation link/diff
checks are recorded in the development log; runtime suites were not rerun.

**Authenticated frozen import review (2026-10-17).** Operators/Administrators
can prepare an exact candidate set separately from read-only preview, inspect
all targets/exclusions/metadata and type the pair count before private queue
admission. CSRF and current trusted identity/role are required for both POSTs;
no browser actor/target/policy/digest is authoritative. Bounded process-local
reviews bind subject/cookie, expire within ten minutes and keep the original
UUID/canonical body on explicit retry. Unknown replies retain uncertainty;
no automatic replay/reclassification, renewed queued authority or re-add.
Status/Queue poll without replacing or GETting the frozen POST view. Intake
and execution/agent/profile gates remain independent and default-off; the lab
is not enabled and no new device test work is authorized.

Corrected the misleading execution-disabled wait reason: new ADD has no stored
placeholder; eligible queued legacy placeholders are hidden only in display.
Real budget deferral/errors and history are retained. No schema/agent/protocol
or Compose change. All 330 Python tests and 16 Chromium scenarios (17 reported
tests) pass, plus compileall, Ruff, JavaScript syntax and diff checks. Packaged
Python 3.12 isolated ASGI review/admission/replay smoke also passes with synthetic
state and no lab mounts/network/secrets. See [Browser Import Review](manual/import-review.md).

API/Web are deployed under standing lab authority, with a checked mode-0600
SQLite backup and prior paired images retained. Agent/Caddy/Authelia IDs are
unchanged. Admission/execution remain false, eligible devices zero; all 61 active
rows, stable timestamps/occurrences, eight VERIFIED/one NOOP jobs and three policy
entries/revision 3 are preserved against backup. No unfinished work or new test
admission; integrity/foreign-key checks pass. The normal v2 read-only cycle
succeeded at 2026-10-17T11:26:44Z, two reads/zero mutations/8049 ms, next baseline
11:31:44Z/no error. Anonymous new POST routes/pages/status return 401;
HTTPS preview redirects to Authelia (302) with TLS verification. No inventory,
.env, secret, policy, schema or new device-write change. Reload browser tabs;
authenticated live review/submission and the remaining broader live gates
are not established by these synthetic/anonymous checks.

**One-address service experiment completed (2026-10-16).** Under separate scoped
approval, TEST-NET 198.51.100.251 on device 1/fpr1010-lab completed queued v3
creation VERIFIED (17:05:24.909Z), already-present NOOP (17:07:06.477Z) and scoped
removal VERIFIED (17:08:25.948Z). The operator independently observed absence,
the exact source-only management row, then absence. Same-key replay before and
after cleanup returned the original parent without new jobs/re-add; origin
count stayed one through NOOP and its inactive history survives cleanup/restart.
Creation cycle: five commands/15490 ms; NOOP: three commands/11276 ms. Exact
removal cycle metrics were not captured before agent recreation; DB/agent result
and final/operator observations confirm cleanup without inventing those metrics.

All requests used the declared approved private maintenance actor, not direct
agent RPC or forged Web identity. .env stayed untouched; only device 1's profile
was temporary. Both API gates and agent ADD are restored off, eligible count
zero, original inventory/.env bytes match pre-test checksums, private override
disarmed and ordinary base configuration restored. The first normal v2 cycle
succeeded at 17:11:13Z (two reads, zero mutations, 8997 ms). Original 61 active
rows, all unrelated state/old jobs and three policy entries/revision 3 are
unchanged; total queue eight VERIFIED/one NOOP, unfinished zero. SQLite integrity
and private anonymous/TLS auth checks pass. Backup and previous image tags are
retained. Web/Caddy/Authelia and binaries are unchanged; no application code or
schema changed during validation. See [recorded evidence](manual/single-address-service-validation.md#recorded-service-result--2026-10-16).

This closes only the approved one-fixture CLI lifecycle and small-read v3 check.
Its authorization is consumed; general ADD, 7,307-address import, traffic/fleet
scope/large-load/live-failure/priority and production remain unapproved. Fresh
model/version/role were not queried; the account matches the earlier reported
Basic profile. Authenticated browser visuals/submission are not established by
private API testing. Follow-up: eligible QUEUED ADD still carries the historical
staging wait reason until claimed; fix that misleading presentation before
exposing executable import UI. Capture/export operating logs before recreation.

**One-address service-test preparation (2026-10-16).** Added a structured
[proposed runbook](manual/single-address-service-validation.md) covering fresh
Basic-account preflight and separate scoped approval, temporary gates/profile,
one queued creation, same-key retry, distinct already-present no-op, authenticated
device-scoped cleanup, no-readd check and restoration. No code, live configuration,
deployment, queue admission, refresh hint, independent agent request or device
write changed. Corrected stale readiness-manual statements about unimplemented
ADD/admission/worker; older direct-CLI/log observations remain historical.
Read-only preflight at 16:54:07Z found device 1/fpr1010-lab enabled, TEST-NET
198.51.100.251 locally absent/not protected, zero unfinished work, both API
gates off and SQLite quick_check ok. Device ready/no error; last normal success
16:52:34Z. Fresh SSH absence, address-unused/model/role confirmation and explicit
scoped enablement/mutation approval remain pending. No live ADD evidence yet.

**Independently gated queued ADD execution (2026-10-16).** Integrated ADD into
the existing leased scheduler behind `FTD_SHUN_IMPORT_EXECUTION_ENABLED=false`.
True requires socket agent mode, cycles and large reads, plus explicit enabled
inventory profiles per eligible device. The agent's own gate remains separate.
The API always supplies an exact device set: eligible devices select v3 only,
others keep ordinary v1/v2 reads/removals and hold ADD. Missing gate/profile does
not accelerate cycles or dispatch ADD. No executable BFF import or default
enablement, new schema, agent binary or wire format is introduced.

Eligible jobs share FIFO/cutoff, one fleet lease and cooldown, a combined
16-operation budget, priority checkpoints and final-read reserves. Recheck
policy/device/captured authorization on every claim. Expire unstarted actors
within long cycles before another valid coalesced request can create origin on
their behalf. Typed verified creation commits origin immediately; no-op does
not assign it, unknown replies/shutdown do not replay, and a failed final read
does not revoke a preceding verified result. UI metadata distinguishes held
versus eligible jobs and displays **Adding and verifying** with common progress.
Private intake wakes the worker only for new eligible work; replay/held-only
admission does not request extra cycles. Intake can be stopped independently.

All 320 Python tests and 15 Chromium scenarios (16 reported tests) pass,
covering real local socket worker conversations, mixed budgets/cutoff, priority,
expiry/coalesced actors, shutdown/recovery and unknown/no-replay behavior.
Compileall, Ruff and diff checks pass. API/Web were rebuilt/deployed with a fresh
checked SQLite-safe backup and prior paired images retained. Agent/Caddy/
Authelia are unchanged; no schema, real inventory/.env edit or test work.
Both API gates/client ADD selector are false and eligible device count is zero.
All 61 active rows, one protected match, six VERIFIED jobs, three policy entries/
revision 3, ordering and stable dates/occurrences are preserved; quick_check is
ok and foreign_key_check has no errors. The ordinary post-start v2 cycle finished
at 16:42:18Z with two reads, zero mutations and 8003 ms; no device error and
next baseline 16:47:18Z. Private anonymous pages/status remain 401; TLS-verified
HTTPS preview redirects to Authelia (302). Packaged Python 3.12 ASGI/schema
safe-default smoke also passed offline without lab mounts/network/secrets.
See [Import Execution](manual/import-execution.md) for gates, bounds,
failure/recovery, deployment and rollback. Live automated ADD, traffic/creation
scope and full-population reads remain unvalidated; real lab flags/inventory
remain unchanged and no new test mutation/import is authorized by deployment.

**Staged import admission/provenance (2026-10-16).** Added default-off private
`POST /api/v1/imports`, strict typed/canonical confirmation, explicit UUID
idempotency, enabled-device/policy/role/capacity checks and atomic opposite
ADD/REMOVE rejection. Concurrent same-action intentions share a job without
losing actor attribution. Existing 1000-job/2000-request/10-per-minute limits
and at-most-15-minute authorization remain; preview capacity does not expand
them. No executable BFF submission, ADD worker dispatch, v3 scheduler selection,
new refresh hint or live addition is introduced. Held ADD does not accelerate
background cycles; it is visible/cancellable and expires normally.

Additive schema adds immutable action/dispatch markers, manual-import batches,
per-occurrence origins and backfilled occurrence IDs without changing existing
dates. Legacy-safe triggers prevent ADD-as-REMOVE claims and origin inheritance
on external reappearance; nine-column old removal request inserts remain valid.
Verified-add completion hooks atomically attribute only a new occurrence;
no-op, uncertainty, later snapshots and retries cannot claim creation or replay
work. Queue retention does not erase active provenance. API/UI exposes a blue
badge, one representative batch plus exact count, escaped details and local
verified time; all coalesced origins remain stored. Full canonical lists are
not multiplied per displayed job/actor/row.

All 297 Python tests pass, including migration/restart/rollback guards, concurrent
admission, whole-batch conflicts/limits, policy edits, expiry/lease loss, ordinary
REMOVE-only scheduling, nested API serialization, 1000-target metadata reads,
retention and escaped attribution. Fifteen Chromium scenarios pass (16 reported
tests), including held/cancellable ADD and provenance clearing on reappearance.
Compileall, Ruff and diff checks pass. Agent/Rust/protocol files are unchanged;
live ADD, traffic/creation-scope and real large-load evidence remain pending.
See [Import Admission](manual/import-admission.md) for structured migration,
backup, rollback and remaining execution gates. API/Web were built/deployed to
the lab with both new capabilities off. A checked SQLite-safe private backup
and prior paired images are retained; agent/Caddy/Authelia IDs are unchanged.
Migration preserves all six legacy jobs and stable first-seen/appearance dates;
61 active records, one protected match, three policy entries/revision 3 and
correct ordering remain. All occurrences are backfilled, batch/origin tables
are empty, quick_check is ok and foreign_key_check has no errors. A normal v2
cycle completed at 12:55:30Z with two reads, zero mutations and 8254 ms; next
baseline is five minutes later, no device error. Anonymous Web/status returns
401; HTTPS preview redirects to Authelia (302) with TLS verification. No real
inventory/.env edit, new job/policy, direct agent read or refresh hint was made.
Inventory contents were not re-read during deployment checks; false admission,
execution and ordinary-client ADD selectors were verified independently.

**Gated agent/transport ADD (2026-10-16).** Implemented typed cycle v3 ADD
behind `FTD_SHUN_AGENT_ADDITIONS_ENABLED=false`, both existing cycle/large-read
gates and explicit per-device `addition_profile`. Missing gate/profile rejects
before secret access/SSH. Only the reviewed laboratory profile is recognized;
there is no client-supplied CLI/context/interface, standalone ADD RPC or silent
v1/v2 upgrade. Fresh preflight yields no-op for existing targets, otherwise
exact acknowledgement plus fresh source-only post-read is required. ADD/REMOVE
share 16 attempts, 64 commands, time/final-snapshot reserves and no-replay rules;
entry capacity is checked before an absent-target write. v3 uses complete
manifest/chunk/end snapshots with version binding. Agent logs add sanitized
per-ADD results and combined counts. No schema, queue admission, provenance,
API write route or UI change: ordinary scheduler clients remain v1/v2, even if
the new agent environment flag is true. No live ADD was submitted/enabled.
Deployment/validation evidence is recorded below and in the development log.
All 275 Python and 38 Rust tests pass, including shared v3 vectors, real local
SeqPacket conversations, lost/malformed responses, full 20,000-entry v3 streams,
gate-before-SSH and fake-console budget/verification cases. Release build,
Clippy, fmt, compileall, Ruff and diff checks pass. Paired API/agent images were
built and deployed under standing lab authorization, with ADD false/absent and
no real inventory profile. The API's explicit addition selector is false;
61 active records/correct sorting, three policy entries/revision 3 and six
VERIFIED results remain; quick_check is ok. A private SQLite-safe backup and
preceding paired images are retained. Web/Caddy/Authelia IDs are unchanged.
No new queue admission, policy edit, refresh hint, direct agent read or test
device write was submitted; no real `.env`/inventory edit or schema migration.
The first post-upgrade v2 cycle succeeded at 2026-10-16T12:14:44Z with two full
reads, zero mutations and 8156 ms; next baseline is five minutes later. Anonymous
pages/status remain 401 and HTTPS Import preview redirects to Authelia (302)
with TLS verification. This confirms old-mode compatibility only, not live ADD.

**Recorded direct-CLI duplicate behavior (2026-10-16).** Operator transcript
shows initially absent `198.51.100.251`, creation, one repeated add with identical
`single_vf`/successful acknowledgement, one identical source-only `management`
row after each, and scoped cleanup returning to absence. Stored a normalized
TEST-NET fixture and a test-only Rust regression: acknowledgement grammar
cannot distinguish creation, so an already-present target must remain no-op
without a write/provenance claim. Model/version/role use the previously reported
profile, not a fresh read. Hidden counter/age behavior, actual traffic blocking,
large-load reads and service-executed ADD remain unverified. No runtime path,
protocol, schema, policy/queue or deployment changed.
All 242 Python and 34 Rust tests pass; locked release build, Clippy, fmt,
compileall, Ruff and diff checks pass. No rollout is needed for the fixture
and test-only regression.

**Preceding offline ADD contract preparation (2026-10-16).** Added an explicitly review-
draft [addition contract](manual/addition-contract.md) and a Rust `cfg(test)`-
only evidence model. It requires exact target/context-bound acknowledgement
plus fresh source-only post-read; pre-existing shuns are no-op without writes
or import ownership. Missing/unknown/oversized/control-bearing evidence,
unexpected scope/target and more-specific fields cannot establish creation.
The draft proposes cycle v3/typed ADD, combined mutation budgets and explicit
agent-owned creation profiles; it does not implement or enable that protocol.
At that checkpoint Python/Rust boundary regressions kept ADD/v3 rejected; the
new gated implementation above supersedes that restriction. All 242 Python and 33
Rust tests pass; release build, Clippy, fmt, compileall, Ruff and diff checks
pass. No runtime path, schema, queue admission or settings changed, and no
rollout is needed. The operator approved running one direct-CLI duplicate test
and was given preflight/add/read/re-add/read/scoped-cleanup/read steps for the
previous TEST-NET fixture; the subsequent result is recorded above. No assistant-issued
device mutation or refresh hint was submitted. Remaining creation-scope/traffic,
large-population reads and subsequent runtime/admission/provenance work remain.

**Active shun ordering (2026-10-16).** Active list/detail reads prioritize exact
Protected IP membership (enabled or disabled), then newest current-appearance
observation, with numeric IP/hostname/interface ties. The API adds
`active_since_at` from existing `last_changed_at`; Web shows **Observed since**
in browser local time with timezone. Reappearance moves up without changing
lifetime first detection; ordinary polling does not reorder rows. Search/history
ordering and automatic-removal eligibility are unchanged. No schema, agent,
protocol or environment change. All 237 Python tests pass, covering policy edits, tie
ordering, both observation paths, reappearance, complete 20,000-row ordering
and API/BFF rendering. Fourteen Chromium scenarios pass (15 reported browser
tests), including local-time rendering of current appearance rather than
lifetime first detection. Compileall, Ruff and diff checks pass.
Live read-only inspection found 61 active records and successful cycle v2 reads
with no error (8072 ms, two commands, zero removals). This is small-population
evidence only, not multi-chunk FTD capacity or an ADD release gate.
Following the operator's standing authorization for validated lab deployments,
API/Web were rebuilt/recreated; agent/Caddy/Authelia IDs are unchanged. The
deployed API returns all 61 active records, one protected match, the new field
and correct protected-first/current-appearance order. Three policy entries,
revision 3 and six VERIFIED results remain; SQLite quick_check is ok. A private
SQLite-safe backup and preceding API/Web image tags are retained. Anonymous
pages/status return 401 and HTTPS redirects to Authelia with TLS verification.
Reload browser tabs for the updated templates; authenticated visual inspection
remains an operator task. No new queue admission, policy edit or refresh hint
was submitted.
The first normal post-restart v2 cycle succeeded at 2026-10-16T10:26:58Z:
two full reads, zero removals, 8191 ms and no error; the next baseline was
scheduled five minutes later.

**Lab deployment authorization (2026-10-16).** The operator allows deployment
of validated, in-scope changes to the current non-production lab without a
separate release confirmation. Recorded in AGENTS.md and the deployment manual;
announce impact and retain validation/rollback records. Production rollout,
new test device writes/imports, destructive data operations and bypassing
feature-specific security/lab gates are not covered.

**Bounded large-snapshot extension (2026-10-16).** Implemented default-off
`FTD_SHUN_LARGE_SNAPSHOTS_ENABLED` in API/agent, read opcode 07 and cycle v2
snapshots. Validated manifest, ordered 32 KiB chunks and mandatory SHA-256 end
precede strict typed decoding and reconciliation. Bounds are 20,000 entries,
2 MiB binary data and 4 MiB full-snapshot CLI output; login/target/write reads,
legacy/v1 limits, prompt/step/session/cooldown budgets and no-replay behavior
remain. A new-mode request to an old/disabled agent fails without fallback;
explicit legacy API selection remains supported. No ADD/import or schema
change. All 230 Python and 26 Rust tests pass, including real local socket
streams and incomplete-snapshot state retention; release/static checks passed.
After explicit approval, API/agent were upgraded and the new flag enabled in
the ignored lab `.env`. A live v2 cycle completed two full reads in one session
in 8282 ms with zero removal steps and no error. Six existing VERIFIED results,
three policy entries/revision 3 and SQLite integrity were preserved. A private
SQLite-safe backup and prior paired images are retained. Web/Caddy/Authelia were
not recreated; anonymous rejection and TLS redirect remain intact. This is
small-read compatibility evidence only. Large FTD load/paging, removal/priority
v2 live checks and production readiness remain pending.

**Addition readiness and large-snapshot blocker (2026-10-16).** A 7,307-entry
`management` snapshot needs 109608 legacy binary bytes/109612 cycle bytes,
exceeding the 64 KiB packet cap; matching CLI output also exceeds its separate
64 KiB cap. Local preview capacity does not establish writable/observable fleet
capacity. Legacy fail-closed limits are unchanged; the gated extension above
is a separate read path, not live large-population acceptance. A staged lab manual
prepares one explicitly approved Basic-account fixture before ADD design.
The operator subsequently confirmed an initially absent `198.51.100.251` was
successfully added under the reported Basic login and observed on `management`;
scoped removal then returned the target to an observed absent state. This
completes the one-address direct CLI lifecycle. Subsequent visible duplicate
behavior is recorded above; hidden-state semantics, data-plane blocking,
fleet creation scope and automated ADD remain unverified.
Large-snapshot scaling is a prerequisite to large additions, not a
new opcode. All 189 Python tests passed, including synthetic legacy/cycle
packet boundaries; compileall, Ruff and diff checks passed.
Corrected the old lab policy procedure to use Protected IPs, not the obsolete
environment list. No runtime deployment or assistant-executed device mutation
is part of this readiness increment; the single direct CLI fixture was created
by the operator and is not an application import.

**Colour-coded preview outcomes (2026-10-16).** Row and full-list count badges
now distinguish Ready (green), Invalid/Unsupported (red), Ambiguous/Protected
(amber), Already shunned (blue) and Duplicate (grey). Refused rows also have
red/amber background and leading-border cues; text labels/reasons remain
visible in both themes. This is presentation only, not addition success or a
change to parsing, eligibility, counts, pagination, API or worker behavior.
All 186 Python tests and fourteen Chromium scenarios passed (15 reported browser
tests), including all seven colours in light/dark themes and retained no-write
behavior. Deployed only Web after explicit approval; API, agent, Caddy and
Authelia container IDs are unchanged. New status styles return 200, anonymous
preview GET/POST/status remain 401 and HTTPS redirects to Authelia with TLS
verification. Reload browser tabs; authenticated live visual inspection remains
an operator task. No new operation, policy edit or refresh hint was submitted.

**Large-list preview fix (2026-10-15).** Removed the textarea character limit
that silently truncated pastes and conflicted with server UTF-8 validation.
Preview now accepts 1 MiB, 20,000 lines, 10,000 rows, 64 selected devices and
100,000 expanded pairs; the encoded body cap is 3 MiB + 16 KiB. A live byte
counter uses native form CRLF line endings and preserves over-limit input for
correction. Bounded decoded-text errors render the form rather than a JSON-only
page. Full-list parsing/classification precedes 100-row result pagination;
page changes re-parse current input without storing source. The supplied
149,376-byte list parses fully as 7,307 unique candidates (not executed).
179 Python tests and fourteen Chromium scenarios passed (15 reported browser
tests). API/Web were deployed after explicit approval. The updated Web parser
accepts all 7,307 supplied addresses; a deployed typed synthetic preview also
returns all 7,307 with can_execute=false and zero audit change. Six VERIFIED
outcomes, three policy entries and revision 3 remain intact; quick_check is ok.
Anonymous preview GET/POST remain 401 and HTTPS redirects normally to Authelia.
No ADD/queue admission or schema change. Reload tabs and paste the original
full source again: content truncated by the old field cannot be recovered by
the update. Authenticated live UI inspection remains an operator task.

**Protected IP state visibility (2026-10-15).** Enabled entries use green badges
and disabled entries use red badges, both with explicit text. Disabled addresses
still locally observed in shun get red warnings in Protected IPs, active rows,
search and detail. A separate read-only disabled-IP status list preserves this
distinction without making disabled addresses eligible for automatic removal.
No schema, agent, queue, policy or authentication behavior changed. All 177
Python tests and thirteen Chromium scenarios passed (14 reported browser tests),
covering the state combinations and live transitions. API/Web were deployed
after explicit approval; three existing policy entries (two enabled, one
disabled), revision 3 and six VERIFIED results were retained. Disabled display
metadata matches SQLite, quick_check is ok, anonymous pages/status remain 401
and HTTPS redirects to Authelia with TLS verification. Reload browser tabs;
authenticated live colour/warning inspection remains an operator task.

**Non-executable blocklist import preview (2026-10-15).** Authenticated users
can paste bounded text, explicitly select enabled devices and inspect exact
IPv4 candidates, duplicate source references, protected/already-shunned rows,
invalid/unsupported/ambiguous lines and expanded candidate pair counts. Raw
text stays in Web/browser memory; API receives typed canonical IPs/device IDs
for one SQLite classification snapshot. There is no queue admission, batch
storage, ADD opcode, creation-interface claim or extra refresh hint. Additions
and executable imports remain unavailable. 169 Python tests and twelve Chromium
scenarios passed (13 reported browser tests). Following explicit approval,
API/Web were rebuilt/recreated. A deployed typed preview read returned
preview_only=true/can_execute=false with no audit change; all six pre-existing
VERIFIED outcomes, both protected addresses and policy revision 3 remain intact.
SQLite quick_check is ok and a cycle succeeded without error. Anonymous GET/POST
preview routes return 401; HTTPS redirects to Authelia with TLS verification.
Reload tabs; authenticated live UI retest remains pending. See the
[preview manual](manual/import-preview.md).

**Shared Protected IP management (2026-10-15).** Every authenticated user may
add/edit/enable/disable/delete protected addresses, including Viewer/Operator
and users without a mapped application group. Only service admission through
Authelia is required, not an Administrator group. CSRF, typed deletion,
optimistic revisions, actual actor/role audit and queued policy execution remain.
Blank identities are rejected. Manual shun-removal roles and cross-user queue
cancellation are intentionally unchanged. 131 Python tests and eleven Chromium
scenarios passed (12 reported browser tests). Following explicit approval,
API/Web were rebuilt/recreated; SQLite quick_check is ok, both protected
addresses/policy revision 1 and all four prior VERIFIED results remain, and a
cycle succeeded without error. Anonymous pages/status return 401 and HTTPS
redirects to Authelia with TLS verification. No schema, agent, group-file or
environment change was made. Reload tabs; authenticated live retest is pending.

**Expanded paginated history and stable refresh layout (2026-10-15).**
History now displays 100 events per page with totals, Previous/Next, Page/Go and
Latest events controls. Event-ID anchors keep new arrivals from displacing older
pages; retention expiry is explicit. Routine refresh text stays inside Status,
the toolbar keeps a stable height, and critical alerts remain visible in an
out-of-flow tray. 123 Python tests and eleven Chromium scenarios passed (12
reported browser tests). No schema, configuration or agent change is needed.
Following explicit approval, API/Web were rebuilt/recreated while the agent,
Caddy and Authelia stayed unchanged. The deployed endpoint returns 51 retained
events on page 1 of 1, size 100; invalid pages return 422 and expired anchors 410.
SQLite quick_check is ok, both protected addresses and two original import
events remain, all four prior VERIFIED outcomes are retained, and a cycle
succeeded without error. Anonymous routes return 401; HTTPS History redirects
to Authelia with TLS verification. Reload existing tabs for the new assets;
authenticated live UI retest remains pending.

**Compact work surface and SQLite-managed Protected IPs (2026-10-15).**
Status and Queue disclosures replace the always-expanded operational panels;
critical stale/error/unknown warnings remain visible. Protected IPs and History
have separate pages. All authenticated users can add/edit/enable/disable/delete exact
addresses with names/comments, observed shun counts and last verified automatic
removal. Policy changes use optimistic revisions and append-only actor audit.
SQLite owns policy; a durable once-only legacy import replaces environment
management and prevents deleted/disabled entries returning on restart. Changes
cancel unstarted policy work atomically, preserve independent manual intentions,
and are rechecked before every claim. RUNNING commands are not interrupted.
See the [policy manual](manual/protected-ips.md) for migration and rollback.
115 Python tests and ten real Chromium scenarios passed (11 reported browser
tests including the parent). Following explicit approval, API/Web were upgraded
after an offline SQLite-safe backup and old-image tagging. Both prior protected
addresses match the imported SQLite entries, two import events and the durable
marker exist, quick_check is ok, all four previously VERIFIED results remain,
and a post-upgrade cycle succeeded. The obsolete setting was removed from the
ignored `.env`; agent/Authelia/Caddy were not recreated. Anonymous page/status
routes return 401 and HTTPS redirects to Authelia with TLS verification. No new
device operation was submitted; authenticated live UI retest remains pending.

**Agent-enabled polling, reconciliation, and trusted-IP policy lab implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, manuals, and an isolated privileged agent. V1 deliberately uses one shared FTD service identity inside that isolated agent; reader/writer separation and one-time key bootstrap are deferred hardening options. The service remains unsuitable for production until it completes the expanded FTD lab validation.

The [Development Plan](development-plan.md) records the approved next direction:
implemented revision-based freshness and a transitional durable multi-user
removal queue. A leased executor shares refresh and removal scheduling, with a
persisted fleet-wide minimum interval and one removal per device per cycle
in default mode.
Default agent mode still opens separate sessions per RPC. An experimental,
default-off single-session removal protocol now implements bounded batching
and priority refresh checkpoints. It requires live lab validation; no
addition/import operation is implemented.

On 2026-10-15, the operator approved deployment and experimental enablement in
the existing non-production lab. Agent/API/Web were rebuilt and recreated
together, the four queue tables were added, and two live read-only cycles
succeeded. Each used two full snapshots in one SSH session (about eight
seconds); no removal was queued or performed. The local ignored `.env` enables
the feature, while the tracked default remains false. The operator subsequently
reported successful queued UI removals, and private API inspection confirmed
two VERIFIED results with no active work or device error. Independent direct
FTD observation, same-session multi-item evidence, and mid-batch priority
validation remain pending. The operator explicitly waived
a backup for this development migration; no data volume was reset.

The subsequent queue-display refinement is deployed to API/Web with explicit
operator approval: active work only, separate visible failed/unverified
outcomes, and collapsed recent completed results. Independent 100/20/20 limits
and total counts prevent a growing history from flooding the working queue.
Both verified lab results remain stored; no record was deleted or requeued.

Request progress bars are implemented and deployed to API/Web with explicit
approval. They use each request's actual linked jobs across devices/cycles,
separate processed from verified outcomes, and show indeterminate running
commands. The status response includes at most 20 active request summaries
with their total count. No creation/import capability or device work was added.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Prior authenticated removal live validated; revised UI deployed to lab, interactive retest pending | Server-rendered search, Protected-IP markers, history/events, and timezone labels are preserved. Refresh now uses process/cycle/data revisions, a single sequential browser request loop, coalesced active-sweep hints, per-device freshness, error backoff, and dynamic state updates preserving search, confirmation input/focus, scroll, and expanded history. Local browser regression scenarios cover slow responses, multiple tabs, repeated errors, network recovery, API restart, and failed POST/retry. Deployed assets include queue/priority controls; anonymous page/status requests return 401 and HTTPS redirects to Authelia. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, bounded local IP-history search, an immediate scheduler-state refresh-hint response, and semantic removal endpoints. Its agent-client timeout exceeds the configured agent operation timeout. |
| Local state and audit trail | Snapshot reconciliation, trusted-policy audit, and configurable retention implemented | SQLite WAL atomically reconciles complete successful device snapshots and retains append-only detection, reappearance, disappearance, manual-removal, and trusted-IP policy events within a configurable 366-day default retention window. |
| Durable operation queue | Deployed/migrated in lab; operator reports successful UI removals | Removal admission returns 202 with a durable parent ID. Transactional coalescing/idempotency preserve multiple actors; ownership-checked cancellation, short authorization expiry, queue bounds, leases, persisted cooldown, uncertain-outcome recovery, queue progress, and matching JSON audit logs are implemented. Four additive tables exist and SQLite quick_check returned ok; inspection confirmed two VERIFIED results and no active work. Active, attention, and completed lists are now independently bounded; completed results collapse by default without deleting history. |
| Experimental session cycles | Enabled in approved lab; two read-only cycles passed, batch writes/priority pending | `FTD_SHUN_AGENT_CYCLES_ENABLED=false` remains the tracked default. Versioned BEGIN/SNAPSHOT/REMOVE/END frames reuse one SSH session per device cycle; hard limits are 16 removal steps, 64 CLI commands, a 120-second work window, and one priority read. Pre-write deferral is explicit; failed responses never fall back or replay. Startup and one manual hint completed with two commands/zero removals each; the next immediate hint was rate-limited. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, pinned host keys, and interface allowlists. |
| Agent boundary | Typed snapshot and removal live-lab validated | Rust agent verifies pinned server host keys, authenticates the FTD `Basic` account with a protected password secret, uses a prompt-driven PTY shell, performs only source-defined `LIST_SHUNS` and `REMOVE_SHUN`, parses strictly, verifies writes, and emits sanitized structured diagnostics for rejected operations to a bounded Docker log channel. |
| Synchronizer and freshness | Revision/coalescing, queue, and experimental cycle tests passed; prior agent/API/SQLite lab validation retained | Cycle/data revisions report partial and failed sweeps. One leased executor dispatches reads, queued manual removals, and trusted-policy removals. Pending work schedules the next eligible cycle; persisted cooldown prevents restart bypass. Opt-in session cycles coalesce interactive hints at verified checkpoints and publish full snapshots before cycle completion. |
| Authentication edge | Header-order repair implemented; end-to-end interactive retest pending | Caddy and Authelia ForwardAuth use protected read-only configuration mounts. A literal-order Caddy `route` removes browser-supplied identity headers before ForwardAuth copies authenticated values to Web/BFF. Authelia runs as the owner of the protected local user file, while a one-shot networkless initializer with only `CHOWN` prepares its SQLite volume. Non-secret templates are explicitly enabled; the in-image healthcheck metadata writer is disabled to preserve the main process's read-only root filesystem and no-Linux-capability boundary. The local file backend disables self-service password mutations. LDAP(S) remains a future migration. |
| Workstation browser lab | Authenticated UI and manual removal live validated | A separate Compose overlay provides Caddy Internal CA for local `.test` names and preserves Authelia ForwardAuth without requiring internal DNS. The authenticated browser path reached the API and completed an agent-verified removal; the new search and freshness copy require a browser retest after deployment. |
| Container layout | Complete for first increment | Only Caddy TCP/443 is published; Web and API use private Unix sockets. The one-shot socket-volume initializer is capability-minimal and prepares ownership/mode for socket and SQLite state volumes before handing them to their service identities. |
| Manuals | Complete for first increment | Development, deployment, and operations manuals are present. |
| Protected IP administration | Shared authenticated access implemented, tested and deployed to approved lab | SQLite policy, all-authenticated-user CSRF-protected editor, bounded fields/count, revision conflicts, one-time legacy import, actual actor/role audit and atomic unstarted-policy cancellation. No new agent operation or ongoing environment policy control. Authenticated live retest pending. |
| Blocklist import preview | Implemented, tested and deployed to approved lab | Bounded paste parser, explicit enabled-device selection, protected/current/duplicate/refused outcomes, source references and local pair counts. Preview only: no persisted batch, agent capability or queued addition. Authenticated live retest pending. |

## Explicit limitations

- The operator reports successful queued UI removals and private API counts confirm two VERIFIED outcomes. Direct FTD post-operation observation, same-session multi-item evidence, cancellation/concurrency, and priority reads during mutation still need live validation. Default throughput remains one removal per device per cycle; the local opt-in mode uses bounded batches and still requires the remaining [cycle laboratory checks](manual/agent-cycle-protocol.md#migration-and-laboratory-validation). Restore/downgrade must suspend old queued work using the [queue manual](manual/operation-queue.md#backup-restore-and-rollback); never run an older immediate-write API beside the executor.
- Queued authorization is checked from captured roles and expires within 15 minutes; live directory revocation is not queried during execution. Lost/rejected responses remain UNVERIFIED and are not automatically replayed. A later absence is RECONCILED_ABSENT, not verified actor-attributed removal.

- A non-empty typed snapshot has been collected through the isolated agent and reconciled into SQLite against the live FPR1010. The five-minute recurring baseline still needs elapsed-time validation. The browser freshness state is only as current as the most recent successful sweep.
- A non-production FPR1010 / FTD 7.6.6 lab has validated the observed `show shun` line shape, empty-output case, agent host-key/password/PTY connection, interface-qualified removal, and post-write verification. The successful request used the typed client from the API container; Web/BFF, HTTP API authorization, Caddy, SQLite audit-event creation, and direct post-operation CLI observation still require validation. Production writes are not approved.
- Egress restriction to configured FTD TCP/22 targets and the matching FTD SSH source ACL are mandatory deployment controls, but are environment-specific host/network configuration rather than Compose-enforced policy.
- The original Fedora/`cscotun0` test host could not route its `ftd-management` bridge (`172.18.0.0/16`) to FTD TCP/22. Every deployment host must independently provide and review narrow agent-to-FTD TCP/22 egress and a matching FTD SSH source restriction.
- `GET_SHUN` and the threat-detection counter operations remain intentionally rejected until their distinct typed result formats are designed and tested.
- FTD supplies broad `Basic` and `Config` CLI roles rather than a per-command authorization model. The FPR1010 / FTD 7.6.6 lab fixture confirms that `Basic` permits the product's `show shun` and interface-qualified removal; no `Config` account is needed for that supported profile.
- The agent's bounded Docker log is the required local operational channel. Host collection/forwarding to a chosen external JSON log platform, metrics, alerting integration, and production backup automation remain environment-specific and are not implemented by this stack.
- The full local Caddy/Authelia/Web/API path has exercised an agent-verified removal against the live FTD lab. It does not replace a direct post-operation FTD observation, recurring-baseline validation, production TLS, or LDAP(S) validation.
- The trusted-IP automatic-removal policy is disabled by default and must be tested with a dedicated non-production address before it is enabled for any office or other trusted egress address. The current local lab SQLite policy contains the two exact addresses migrated from the former environment configuration; an earlier startup snapshot recorded one agent-verified policy removal. Direct FTD confirmation and a live fail-closed policy test remain required. The policy applies to every enabled device by design.

## Recent validation

Latest preview increment: 169 Python tests passed; twelve Chromium scenarios
passed (13 reported tests). Checks cover comments/lists/free-text ambiguity,
malformed/unsupported forms without substring extraction, duplicate references,
max-length hostile tokens, UTF-8/row/line/body/target-pair bounds, chunked requests,
CSRF/escaping, typed-only API forwarding, enabled devices and no queue/audit side
effects. Browser preview covers all outcomes and retains text/result/focus through
metadata updates without extra parses, hints or execution. Compileall, Ruff,
Node syntax and diff checks passed. Rust/protocol are unchanged.

Previous shared-policy increment: 131 Python tests passed; eleven Chromium
scenarios passed (12 reported tests). BFF/API tests cover Viewer, Operator,
Administrator and unmapped authenticated users; blank/anonymous identities,
forged form identity, missing/invalid CSRF, stale edits and unconfirmed deletion
remain rejected. Audit preserves actual roles. Browser CRUD now uses Operator,
not Administrator. Existing manual-removal/cancellation authorization checks
still pass. Compileall, Ruff, Node syntax and diff checks passed; Rust unchanged.

Previous history/layout increment: 123 Python tests passed; eleven Chromium
scenarios passed (12 reported tests). New checks cover page bounds, tie ordering,
anchored insertion/retention behavior, consistent count/row snapshots, auth and
the unchanged legacy history API. Real browser assertions check 100/100/51 rows,
newest events, stable older-page URLs, no disclosure, and unchanged content
coordinates across refreshing/error/ready/network-failure states at desktop and
mobile widths. Compileall, Ruff, Node syntax and diff checks passed; Rust is
unchanged and was not rebuilt/retested for this increment.

Previous policy/UI increment: 115 Python tests passed; ten real Chromium scenarios
passed (11 reported tests). Coverage includes once-only/empty/invalid migration,
restart after deletion, concurrent administrators, admin/CSRF enforcement,
audit/log correlation, policy-only search, transactional policy cancellation,
and disabling the next item while a fake session command is running. Browser
checks cover native keyboard/mobile menus, visible closed-menu warnings,
progress spacing, per-IP drafts retaining original revisions, CRUD/escaping,
and separate History updates. Compileall, Ruff, Node syntax and diff checks
passed. Rust and the fixed agent protocol are unchanged.

Previous display increment: 104 Python tests passed; real Chromium passed seven
scenarios (eight reported tests including the parent). Rust is unchanged from
the prior 20-test pass. Queue tests cover bounded groups and consistent status
during concurrent completion; browser tests cover collapsed results, visible
errors, counts/limits, transitions, preserved disclosure state, and request
progress. Tests distinguish actual job totals from cycle caps, uncertain
outcomes from success, and stable indicators from metadata-only phase changes.
Compileall, Ruff, Node syntax, Rust format/Clippy, release build, and diff checks
passed. Session tests use fake consoles and synthetic Unix transport, not live
FTD. Subsequent approved deployment validated two live read-only cycles, private
API/Web health and queue migration, HTTPS authentication redirection, and refresh
cooldown. Full live batch-write/priority validation remains pending.

The foundation increment was checked with:

- `python3 -m compileall -q src tests`
- `python3 -m pytest -q` — 22 tests passed
- `python3 -m ruff check .`
- `cargo build --release --locked --manifest-path agent/Cargo.toml`
- `cargo test --locked --manifest-path agent/Cargo.toml` — 10 tests passed
- `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .` — successful; image user is `10002:10001`
- `docker compose --env-file .env -f deploy/compose.yml up -d --build socket-init agent api` — successful with local ignored configuration; the API opened its SQLite/WAL database and Unix socket, and the agent socket is `10002:10001`, mode `0660`
- `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config` with local ignored configuration
- `cargo fmt --manifest-path agent/Cargo.toml`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` — 10 passed
- `python3 -m compileall -q src tests`; `python3 -m pytest -q` — 29 passed; `python3 -m ruff check .`; `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config --quiet` and the merged local-browser overlay configuration — successful
- Rebuilt/recreated local API and Web/BFF with an empty trusted-IP policy; private API status reported `trusted_auto_remove_ip_count: 0` and the normal startup snapshot completed without error.
- The policy-status additions passed `python3 -m compileall -q src tests`, `python3 -m pytest -q` (31 passed), `python3 -m ruff check .`, and `git diff --check`.
- Rebuilt/recreated local API and Web/BFF after the explicit operator approval. The private API reported a successful refresh, 366-day retention with no error, and a trusted-policy request followed by one verified removal; active local state was empty afterward.

## Next work, in order

The separately approved one-fixture service lifecycle is complete. Frozen BFF
confirmation and the eligible-ADD reason fix are implemented with gates off.
The new restoration requirement now takes precedence for development. The
isolated registry/authorization/revision/retention foundation and read-only
visibility are implemented; next implement explicit managed confirmation/controls,
restore-suspension tooling and atomic retirement/removal handoff, followed by
default-off shared-worker integration. Do not enable reconciliation by deriving
policy from historical imports or by renewing old user jobs. Resolve controller
anti-churn defaults and any expansion beyond initial registry bounds before live
migration. Follow the
[managed-shun implementation sequence](manual/managed-shuns.md#implementation-sequence-and-acceptance).
Authenticated browser review can be checked read-only; separately agree any
further narrow submit/restore/cleanup experiment. Additional
live mutations require fresh scoped authority; traffic/fleet/load/failure/priority
checks remain before general imports. The staged admission flag is not the
execution gate. Real 7,307-entry imports remain blocked by
1000 pending-job capacity and bounded authorization as well as live read evidence.

Before enabling any large import, resolve and lab validate the independent
64 KiB CLI-output/snapshot-packet capacity blocker. Follow the staged
[addition readiness procedure](manual/addition-lab-validation.md) to collect
Basic creation/scope evidence without applying the pasted list. This does not
replace the removal/session checks below or authorize an automatic FTD write.

0. Retest compact menus, separate History and shared authenticated Protected IP CRUD
   in an authenticated lab browser. Use only a dedicated non-production address
   for policy execution checks; configuration changes apply fleet-wide.
   Exercise Import preview with a local paste only; Ready is not a write or
   validated creation scope. The ADD protocol and live addition gate remain next
   only after the documented removal/session laboratory checks.
1. Retest the newly deployed UI in an authenticated browser, including a real baseline interval and per-device failures. Automated Python/Chromium scenarios pass; HTTPS redirects and private unauthenticated rejection were rechecked after deployment.
2. Complete live queued-removal validation: 202 admission, duplicate users, cancellation, persisted cooldown, lease loss, expired authorization, queue bounds, audit attribution, and recovery without replay. The additive migration is deployed; SQLite integrity and empty-queue status passed. The operator waived a backup for this dev migration only, not future shared/production updates.
3. Lab validate the implemented opt-in session-cycle protocol: one SSH login per device cycle, multiple verified removals, priority checkpoints, budgets, disconnects, and no legacy fallback. Only then consider default enablement. Separately design/lab validate narrow addition before paste/preview/import; preserve manual provenance and never automatically re-add removed imports. Follow the [Development Plan](development-plan.md).
4. Complete the [FTD laboratory validation](manual/ftd-lab-validation.md), including direct post-operation observation, baseline behavior, queue load/concurrency, trusted-policy failures, host-key mismatch, private-socket checks, and snapshot rejection. Production writes remain unapproved.
5. Add structured external logging, metrics, backup automation, and operator alerts; validate TLS, Authelia local users, LDAP(S), and the complete non-production deployment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

