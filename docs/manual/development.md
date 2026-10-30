# Development Manual

## Lab-first development policy

Operator alignment, 2026-10-30: this is an unreleased internal project with no
production deployment. The current FPR1010 is the operator's desk test device.
Prioritize usable managed import/restoration, quick unblock and real lab feedback,
not compatibility infrastructure for disposable old development state.

Proceed with normal in-scope implementation, validated lab deployment, explicit
fresh-schema setup and bounded semantic ADD/REMOVE/restore tests without another
approval for every fixture or feature gate. Announce device writes and their scope,
use fresh labelled test keys/actors, verify actual outcomes and record a short
result. Old one-address approvals/consumed receipts describe old tests, not a
permanent requirement to ask again for every ordinary lab test.

Prefer a clean DB in a separate path/volume; keep the old test DB as a private
archive, not a mandatory conversion input. Keep inventory/credentials and transfer
useful configuration explicitly. Do not copy old queues, imports or observations
into standing authority, silently overwrite/reset stores or delete volumes.
Drain old work before switching. Destructive replacement needs an exact authorized
scope; a fresh separate store does not require a full legacy migration project.

Keep semantic-only RPC, agent-only credentials, host-key pinning, authentication,
private sockets, serialized device streams and truthful verified outcomes. Develop
compatible tested profiles rather than bypassing runtime guards, clearing unknown
work or fabricating success. Ask for direction on unknown/production targets,
material scope expansion, secrets/trust/network changes or destructive actions.

The first operator-designated real release published with a GitHub version tag
starts released-data compatibility, upgrade/migration and formal rollback
obligations. A dev version/footer or experimental tag is not that decision. Do
not publish a tag/release without a request. See [Versioning](versioning.md).
Older manuals still describe their implemented gates and historical experiments;
their per-step approval language does not override this policy or the latest
[architecture amendment](../architecture-and-security-design.md#pre-release-laboratory-policy--2026-10-30).

For documentation-only changes, validate links and `git diff --check`; do not run
unrelated full code/browser/agent suites. Code, protocol and deployment changes
still get the applicable regression checks below and in `AGENTS.md`.

## Fresh working-version setup and execution

Use [Fresh Working-Version Lab](fresh-development.md) for the normal next-stage
lab setup. `ftd-shun-dev-init` creates only an absent separate database, optionally
copies current Protected-IP settings and never adopts old queued work/authority.
The explicit `continuous-managed` API/Web selector connects v2 recurring consent,
bounded continuous ADD/restoration and ready/ordered cleanup on that exact profile.
Legacy controllers remain off. See that manual for cutover/rollback and tests.

## Nonempty legacy transition inspection

```bash
python3 -m pytest -q tests/test_migration_inspection.py tests/test_managed_maintenance.py tests/test_configured_runtime.py
```

Use only disposable recognized legacy profiles. Tests cover a complete streamed
schema/row/header manifest, nonempty retired keys/receipts, actual shared-result
attempts and evidence-aware pruning, cleanup barriers, readonly WAL snapshots,
no-init/query-only source, bounded batches, type-separated hashes, same-count drift,
reinspection/expiry and sanitized fixed CLI/no apply. In-memory contract generation
may execute trusted DDL only in its own `:memory:` database. Do not point the
command at the lab or initialize/erase optional evidence as a smoke shortcut.
See [Transition Inspection](migration-inspection.md) for interpretation and limits.

## Configured observation-runtime checks

```bash
python3 -m pytest -q tests/test_configured_runtime.py tests/test_inventory.py tests/test_config.py tests/test_continuous_api.py
```

Disposable retained profiles cover explicit default-legacy selection, real strict
Unix-client construction without I/O, no-init/check/GET guarantees, mismatched
nonempty/partial state, full device/trust and disabled-ID matching, frozen startup
drift, canonical inventory ordering, independent gates and one lifecycle owner.
Only the lifecycle test substitutes semantic fake RPCs. No live DB/inventory,
credential, service or FTD is accessed. See [Configured Runtime](configured-runtime.md)
for the preflight/backup/rollback boundaries; it is not lab activation approval.

## Fenced concurrent standing-admission checks

```bash
python3 -m pytest -q tests/test_bulk_concurrent.py tests/test_bulk_confirmation.py tests/test_bulk_dispatch.py tests/test_device_leases.py tests/test_bulk_cancellation_surface.py
node --test tests/browser/freshness.cjs
```

Disposable SQLite/ASGI/BFF/shared-queue tests cover independent active ADD/observation
leases, whole-scope device/pair/held-evidence barriers, failed attempts after queue
retention, late expiry rollback, competing-user CAS, strict private fields/default-
off capabilities, mode drift/replay, historical suspension, fresh/equal-millisecond
read boundaries and 100000-pair admission without queue backlog/lease mutation.
Browser cases cover local gating, frozen active consent/input/focus, historical
receipts and mobile layout. Completed-history cancellation keeps digest-only
evidence distinct from a RUNNING captured-job binding. No inventory, secret,
lab/SSH/FTD or live gate is used. See [Concurrent Admission](bulk-concurrent-admission.md).

## Version-2 confirmed-import cancellation checks

```bash
python3 -m pytest -q tests/test_bulk_cancellation_surface.py tests/test_bulk_cancellations.py tests/test_bulk_waits.py tests/test_bulk_confirmation.py tests/test_continuous_api.py
node --test tests/browser/freshness.cjs
```

Disposable actual BFF/ASGI/SQLite tests cover 100000-pair cancellation/late pages,
retained adoption/existing policy, actual fenced RUNNING claims/shared typed
success/no-op/failure/unknown settlement, current actor/strict fields/CSRF/owner/
Admin, pause/gates, exact frozen pages/expiry, original-review unknown recovery,
restart/pruning, malformed evidence/status and forbidden initialization. Browser
cases cover native count consent, frozen scope/focus, local settlement updates,
retained unknown attention/original receipt, pagination and mobile layout. No lab,
transport, secret or FTD fixture is used. See
[V2 Cancellation Surface](bulk-cancellation-surface.md).

## Version-2 suspended standing-confirmation checks

```bash
python3 -m pytest -q tests/test_bulk_confirmation.py tests/test_bulk_preparation_web.py tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_bulk_policy.py
node --test tests/browser/freshness.cjs
```

Actual synthetic BFF/ASGI/SQLite confirmation covers independent default-off gates,
strict exact count/consent/actor/CSRF, immutable cache, post-I/O expiry, whole-scope
quiescence/revision/pause/profile refusal, maximum 100000-pair suspended policy,
unknown replies/same-key recovery, retirement non-reenable and owner historical
receipts after restart/draft pruning. Browser cases cover native form validation,
frozen focus/input/consent, historical pagination and responsive layouts. No lab
profile, fixture, migration, gate or device work is permitted by these tests.
See [Standing Confirmation](bulk-standing-confirmation.md).

## Version-2 preparation Web checks

```bash
python3 -m pytest -q tests/test_bulk_preparation_web.py tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_ready_removal_web.py tests/test_ordered_removal_web.py
node --test tests/browser/freshness.cjs
```

Actual BFF requests reach the ASGI API on disposable exact profiles. Cover narrow
capability navigation, immutable owner reports, strict 201/report/manifest checks,
role/CSRF/actor separation, unknown replies without automatic resubmit, preserved
transient source/device fields, closed/confirmed draft refusal, checked cancellation
with failed follow-up, restart and maximum 100000-pair pages/proposal. No authority,
queue/origin/audit or device state may change outside the draft journal. Chromium
checks production templates/JS, frozen input/focus/keys, native forms, colored
exclusions, 100-row pagination and desktop/mobile overflow without device demand.
No recurring-consent/submit route, new dependency, DDL or lab activation is needed.
See [V2 Preparation Web](bulk-preparation-web.md).

## Version-2 preparation API checks

```bash
python3 -m pytest -q tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_managed_shuns.py tests/test_bulk_preparation_intent.py
```

Use disposable exact v2/fenced profiles with an explicitly initialized test-only
journal. Exercise real ASGI routes, ten-device/100000-pair staging and bounded
pages, correct classification/privacy, owner restart/recovery, strict fields and
UTF-8/source bounds, full retained hashes/same-count substitution, original expiry,
role-loss/pause draft cancellation, confirmed-draft refusal, concurrency/capacity,
late rollback and unchanged non-journal authority/queue/origin/audit. Proposal
streams are read-only <=100-row chunks; constructible descriptors are not grants.
Do not initialize, prune, migrate or enable anything in the lab for these tests.
See [V2 Preparation API](bulk-preparation-api.md). No agent/Compose/UI change is
required; full Python regression remains mandatory.

## Ordered Web consent, local status and revocation checks

```bash
python3 -m pytest -q tests/test_ordered_removal_web.py tests/test_ordered_removal_api.py tests/test_ready_removal_web.py tests/test_continuous_api.py tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_promotion.py
node --test tests/browser/freshness.cjs
```

Use disposable profiles/semantic agents and local Chromium only. The BFF tests
forward actual synchronous private requests to the ASGI API; real queue/policy
transactions and the shared fake worker are exercised, not substituted responses
for the write path. Check separate literal capabilities; complete preflight,
historical receipt/current job projection; actor/role/CSRF/session/cross-purpose
refusal; immutable caches and post-I/O expiry; stale membership; unknown replies
and original-key retries; status after Web restart; owner/Admin revocation while
paused/disabled; race-to-ADMITTED conflict; checked revocation followed by failed
status; and malformed whole-scope evidence without success inference.

Chromium checks frozen input/key/focus, literal default-off gates, escaping/native
typed-IP validation, mobile form spacing and dynamic local status/dirty fields
with no device refresh or execution requests. Reopen preserved details before
restoring field focus, otherwise Chromium silently refuses focus in closed bodies.
No new pytest/npm dependency, lab fixture, gate, migration or deployment is needed.
See [Ordered Web Controls](ordered-removal-web.md).

## Private ordered-removal API checks

```bash
python3 -m pytest -q tests/test_ordered_removal_api.py tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_promotion.py tests/test_continuous_api.py tests/test_managed_shuns.py tests/test_managed_fleet_removals.py
```

Use disposable exact profiles and semantic fakes only. Exercise independent
default-off API/promotion capabilities, strict typed frozen predecessors, original
UUID/TTL and actor audit, whole-scope conflicts, same-key concurrency/lost response,
late rollback, read-only current job outcomes and local owner/Admin cancellation
under pause/disabled admission. Verify current status never promotes or expires
work and missing evidence is unavailable rather than 404/success. Run the actual
API-lifecycle/shared continuous fake REMOVE scenario without a second executor.
No optional migration, deployed capability or lab work is authorized. See
[Private Ordered API](ordered-removal-api.md); frozen Web consent remains separate.

## Ordered promotion and strict settlement checks

```bash
python3 -m pytest -q tests/test_bulk_ordered_promotion.py tests/test_bulk_ordered_waits.py tests/test_continuous_dispatch.py tests/test_parallel_synchronizer.py tests/test_bulk_removals.py tests/test_store.py
```

Disposable SQLite/fake sessions only: whole-scope barrier, original session release,
exact deferral, retained attention, TTL/budget transfer, once-only concurrency,
atomic late rollback, partial-ticket claim refusal, healthy-root fairness, strict
profile compatibility and actual shared continuous REMOVE execution. No new pytest
plugin is needed; async tests use the repository's `asyncio.run` pattern. Migration
and both execution capabilities remain default-off, with no lab activation. See
[Ordered Promotion](bulk-ordered-promotion.md).

## Durable ordered-reservation checks

```bash
python3 -m pytest -q tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_removals.py tests/test_bulk_removals.py tests/test_bulk_dispatch.py tests/test_continuous_maintenance.py tests/test_store.py
```

Initialize the optional profile only in disposable fixtures. Check atomic
whole-scope retirement/reservation, exact RUNNING predecessor binding, separate
action/capability, original-key concurrency, shared budgets/expiry, owner/Admin
revocation, late rollback and retained queue/request/claim evidence through all
outcomes and cancellation/expiry. Both pruners must refuse before deletion on
malformed/missing held evidence. The separate
[promotion](bulk-ordered-promotion.md) and [private API](ordered-removal-api.md)
packets retain independent capabilities; these tests do not activate them or
migrate the lab. See [Ordered Reservations](bulk-ordered-reservations.md).

## Ordered-removal preflight checks

```bash
python3 -m pytest -q tests/test_bulk_ordered_removals.py tests/test_bulk_removals.py tests/test_device_leases.py tests/test_bulk_waits.py
```

Use disposable SQLite profiles only. Exercise actual parallel RUNNING claims,
complete fleet membership, original request/claim/epoch binding, all terminal and
pre-write-deferral outcomes, unavailable evidence, concurrent completion and
unchanged storage. Corruption tests alter synthetic fixtures, never live audit.
This local read-only component provides no ordered admission, durable barrier,
HTTP/Web execution or lab activation. See [Ordered Preflight](bulk-ordered-preflight.md).

## Gated v2 removal confirmation checks

```bash
python3 -m pytest -q tests/test_ready_removal_web.py tests/test_continuous_api.py tests/test_bulk_removals.py tests/test_managed_shuns.py tests/test_refresh_bff.py
node --test tests/browser/freshness.cjs
```

Only disposable composition enables the separate API/Web factory capabilities.
Check frozen mode/scope/key/expiry, independent gates, strict receipt validation,
real identity/CSRF, post-I/O expiry and actual synthetic continuous execution.
No runtime selector/migration/lab activation follows. See
[V2 Removal Confirmation](ready-removal-confirmation.md).

## Version-2 ready-removal regression checks

```bash
python3 -m pytest -q tests/test_bulk_removals.py tests/test_operation_queue.py tests/test_bulk_dispatch.py tests/test_bulk_attempts.py tests/test_continuous_api.py tests/test_managed_shuns.py
```

Use disposable exact fenced storage and semantic fake sessions only. Verify
whole-scope atomic retirement/admission, no implicit RUNNING-ADD waiting, strict
default-off capability, late rollback, original-key replay after pruning and
actual shared continuous dispatch. Readonly scope GET must not grant authority.
No live activation follows. See [Ready-Scope Removal](bulk-ready-removal.md).

## Version-2 policy view and retirement checks

```bash
python3 -m pytest -q tests/test_bulk_policy_views.py tests/test_continuous_api.py tests/test_managed_controls.py tests/test_managed_view.py
node --test tests/browser/freshness.cjs
```

Use disposable SQLite/ASGI/Chromium fixtures only. The new private v2 routes are
distinct from v1; page/selected reads must never initialize state or admit work.
Stop-maintaining uses the frozen version/revision and original key, not live
status to select a fallback. No combined device removal or live policy activation
is covered. See [Version-2 Policy Views](bulk-policy-views.md).

## Restricted continuous API regression checks

`tests/test_continuous_api.py` checks explicit ASGI ownership, existing-schema/
settings/transport matching, read-spacing floors, no-DDL construction/GET/first
worker, startup/status drift, no legacy fallback, refused unimplemented workflows,
actual refresh/Protected-IP retirement and real BFF-to-API auth/CSRF/audit/metadata.
Chromium checks restricted navigation, hidden mutation/review controls and usable
demand against production templates/JavaScript; legacy cases remain in the same
suite. All storage/agents/transports are disposable synthetic fixtures, not a
live profile or migration. See [Restricted Continuous API](continuous-api.md).

## Continuous maintenance regression checks

`tests/test_continuous_maintenance.py` exercises actual ordinary expiry/retention
on disposable SQLite, daily/five-second scheduling, unchanged data revisions,
restart, independent error backoff, partial-stage failure and repeated/forced
cancellation of bounded thread work. Continuous-controller tests add independent
device reads during slow pruning, shared shutdown, browser error visibility,
unexpected-task failure, actual bulk uncertainty/captured-predecessor retention
and malformed-held-evidence refusal. No FTD, lab state, credentials or migration
is involved. See [Continuous Runtime Maintenance](continuous-maintenance.md).

## Continuous browser-contract regression checks

`tests/test_continuous_dispatch.py` checks the real controller's detached browser
projection, no-create disabled/missing storage, conservative partial-fleet
confirmation, pending/held demand, revisions, coalescing and thread-safe committed
state notifications. `tests/test_refresh_bff.py` checks explicit metadata fields
through authenticated/no-store GET and CSRF-protected demand POST. The Chromium
suite additionally exercises concurrent device phases, repeatedly usable demand,
held warnings, countdown eligibility without fabricated reload and independent
data updates with retained input/open menus. Legacy browser behavior remains in
the same regression suite. See [the contract](continuous-dispatch.md#browser-projection-contract).
No API runtime selector, optional migration or live activation is involved.

## Local cycle-settlement regression checks

`tests/test_agent_settlement.py` uses shared Rust/Python fixed vectors and actual
local SeqPacket fixtures for strict v1/v2/v3 begin/final/terminal receipts. Check
binding/length/status/range/truncation, delayed/missing proof, no old-agent/legacy-
binding downgrade, the original END deadline, capability refusal before claims,
withheld final publication and earlier verified ADD preservation. Rust tests also
check unchanged gates/budgets, failed cleanup, guard/IDLE-before-postamble ordering,
stopped completion panic and 100 immediate same-device socket handoffs without
retries. No SSH, real inventory, credentials or live activation is involved.
See [Local Cycle Settlement](cycle-settlement.md). Local ordering is not remote
quiescence proof and never resolves an old uncertain job or authorizes retry.

## Continuous dispatch regression checks

`tests/test_continuous_dispatch.py` exercises actual repeated semantic sessions
on disposable fenced journals: multi-batch work without advancing clocks, slow/
healthy independence, idle isolation, per-device baseline/manual demand, repeated
clicks/in-flight checkpoint reads, post-cutoff FIFO REMOVE, current agent target
verification instead of stale absence, protection during ADD, strict request
authority/pause/cancellation, exact-deferral backoff, unknown preservation, restart
and orderly/forced stop. Fixtures with already admitted ordinary requests are not
v2 Web admission or lab seeding permission. No real FTD, credential, Docker or live
activation is involved. See [Continuous Dispatch](continuous-dispatch.md).

## Parallel device-round regression checks

`tests/test_parallel_synchronizer.py` runs the existing semantic collector with
independent fenced workers, disposable bulk journals and bounded blocking fake
RPC threads. Check actual overlap/quota and healthy-device progress, exact
scope/capacity refusal, original roots and typed ADD/protected REMOVE results,
deferral, lost/final/late responses, repeated cancellation and forced internal
shutdown. Await orderly cancellation before closing the event loop. No FTD,
credentials, Docker, optional live migration or gate activation is used. The
internal coordinator has no startup/environment/Web selector; the separate
continuous lifecycle now supplies read timing/priority, while application
integration and real transport acceptance remain follow-up work. See
[Parallel Device Rounds](parallel-rounds.md).

## Isolated version-2 SQLite policy tests

`tests/test_bulk_policy.py` exercises actual 100000-pair policy/manifest persistence,
original-key/owner recovery, restart/pruning, adoption/exclusions and bounded reads.
It checks whole-scope conflicts, final audit rollback even when an outer caller
commits, same-key concurrency, sealed membership, retained-key/ledger budgets,
actual retirement reserve and preserved uncertainty. Legacy readers/initializers
must refuse the new registry even for one key. Fixtures explicitly create a fresh,
suspended development profile; no lab migration, old-state conversion or RPC.
See [Version-2 Bulk Policy Storage](bulk-policy-storage.md) before extending it.

## Large-import format regression checks

`tests/test_bulk_intent.py` validates an isolated version-2 descriptor and complete
classified membership: fixed binary/hash vectors, numerical order, literal types,
complete 10000-address/ten-device product, 100000 accepted pairs, bounded memory/
descriptor size, corruption, duplicate/unknown JSON fields and original legacy
canonical hash/limit compatibility. This is neither a new agent RPC nor authority.
`tests/test_bulk_preparation_intent.py` builds the proposal from actual disposable
journals with <=100-row scans, owner/restart/expiry/clock/conflict checks and no
independent writes. Already confirmed legacy drafts cannot acquire new meaning.
No runtime caller or optional schema is added. See
[the format and transition manual](bulk-import-capacity.md).

## Selected-policy review regression checks

`tests/test_managed_selection.py` validates at-most-100 exact read selectors,
global totals versus selected/missing membership, parity with legacy views,
retained attention, scoped SQL summaries and one-snapshot concurrent reads.
It exercises strict API types/fields, revision conflicts, absent/partial/orphaned
state, substituted/mismatched responses and actual single-pair BFF review paths
with full-registry reads deliberately forbidden. Existing controls/review tests
now explicitly distinguish the new read-only POST from mutation POSTs; all
auth/CSRF/sensitive-review/old-key/uncertainty checks remain. See
[selected-policy reads](managed-shuns.md#exact-selected-policy-reads-for-single-pair-reviews).

`tests/test_managed_batch_selection.py` adds complete standing-list selections:
one read transaction, at most 100 pairs per SQL/summary chunk and 1000 selectors
overall; no independent-page aggregation or whole-registry BFF fallback. Check
concurrent changes between chunks, original retained attention, strict scope
markers/echoes, late-chunk failures, absent/partial state and global capacity
including stopped/unselected keys. Existing batch admission, replay, authentication,
consent and no-work assertions remain unchanged. Tests use disposable SQLite/ASGI,
not lab schemas, credentials or device connections.

## Managed-import browser regression checks

`tests/test_managed_import_web.py` connects actual BFF forms and strict private
API to disposable SQLite. Tests cover preparation/adoption/exclusions, explicit
consent/count, deterministic original-key recovery after restart/unknown replies,
retained reports after pruning, cancellation versus actual removal, frozen paging,
both admission gates, current identity/CSRF/cache age, malformed replies and base-
only startup without optional migration. Chromium checks production templates,
native confirmation validation, escaping, marked exclusions, stable input/focus
and mobile spacing without hints/mutations. See [Managed Import Web](managed-import-web.md).

## Confirmed-import cancellation regression checks

`tests/test_import_cancellations.py` uses disposable policy/import/queue state to
test retained adoption/completed work, unsent revocation, RUNNING settlement,
typed pre-write deferral, lease recovery, old-generation/protection precedence,
retained uncertainty, concurrency/receipt replay and atomic audit rollback.
It covers full current 1000-pair cancellation/100-row reports, separate explicit
schema/guards, pruning holds and gate-independent strict private API. No lab
activation or device connection follows. See [Import Cancellation](import-cancellation.md).

## Prepared-import confirmation regression checks

`tests/test_managed_imports.py` validates atomic canonical policy plus immutable
report/audit, explicit adoption without ADD/creation provenance, protected/invalid
exclusions, owner/current-role binding, whole-scope conflicts, rollback, original-key
concurrency/replay after pruning/new generations and permanent protection retirement.
It covers full current 1000-pair reports without raising capacity, separate receipt/
retirement reserves, strict private routes, disabled capability and no startup/schema
side effects. See [Prepared Import Confirmation](managed-import-confirmation.md).
Only temporary SQLite/ASGI is used; no live migration, grant or execution follows.

## Managed pagination regression checks

`tests/test_managed_pagination.py` validates 100-row policy pages, one-snapshot
counts/summaries, legacy-view parity, restart/revision conflicts, bounded pair
queries, full 1000-key capacity without raising it, orphan/partial-state refusal,
API/BFF authentication/no-store/selector errors and no full-view fallback. Reads
leave the disposable database unchanged. The Chromium pagination scenario checks
Previous/Next, local status updates without navigation, 100-option target selectors,
mobile overflow and explicit changed-policy recovery without device hints/writes.
See [Managed Shuns](managed-shuns.md#read-only-managed-shuns-page). No live fixture,
policy grant, schema migration or gate change is part of these tests.

## Durable bulk-preparation regression checks

`tests/test_import_preparations.py` exercises an explicitly initialized preparation
journal, separate from authority and dispatch. A maximum synthetic 10,000-address/
ten-device scope stores 100,000 pair classifications, survives restart and verifies
its full digest in 100-row chunks. Owner lists/pages, exclusion/adoption honesty,
source privacy, immutable scope, concurrent quotas, expiry/pruning and late-write
rollback preserve all independent policy/queue/audit state. No normal startup/GET
initializes the journal; no runtime/HTTP path uses it yet. Follow
[Durable Import Preparations](managed-import-preparations.md), not a lab migration
or admission shortcut. Larger policy/attempt capacity and durable confirmed-import
progress remain the next integration work.

## Inventory and credential regression checks

`agent/src/credentials.rs` and `agent/tests/credential_configuration.rs` exercise
strict agent-owned ID/login/secret mapping, explicit legacy compatibility,
no per-device fallback, bounded exact-byte secrets and preflight with an isolated
process environment. `--check-config` validates configuration/secret files without
opening SSH or the agent socket. Tests use synthetic private temporary files,
never deployment settings or real passwords. Python inventory tests reject
credentials/duplicate fields/coerced IDs and preserve identity across IPv4 changes.
See [Per-Device Credentials](per-device-credentials.md) for Compose isolation,
activation boundaries and paired configuration/image rollback. No optional
schema/gate or current lab credential is changed by these checks.

## Offline managed-policy foundation

`tests/test_managed_lifecycle.py` connects checked offline CLI migration/resume,
browser batch consent, private admission, complete fake snapshots and the shared
executor through initial creation, disappearance/restoration, restart and final
single/fleet cleanup. It also tests protection priority, held deadlines when
the controller is disabled and lost ADD/REMOVE replies. Policy/queue tables are
not patched to shortcut state transitions. Seven integration cases use private
temporary backups, a controlled clock and typed fake consoles, never a lab
environment file, service volume, credential or device socket. See
[Managed Lifecycle Validation](managed-lifecycle-validation.md) for the local
command, evidence boundaries and the separately approved next lab procedure.

`tests/test_managed_cleanup_admission.py` covers the gated HTTP/BFF connection to
single/fleet coordinators using synthetic SQLite/ASGI: ready/ordered whole-scope
semantics, late audit/deadline rollback, generation/scope CAS, historical replay,
independent conflicting jobs, role/CSRF/strict body/capability checks, original
unknown-reply retry and no per-target fleet commits. Chromium checks enabled/
disabled/blocked review, immutable ordered choice, input/focus/native validation
and mobile spacing without commands or refresh hints. See
[Combined Managed Cleanup](managed-cleanup.md); no lab fixture/gate is initialized.

`tests/test_managed_grants.py` uses disposable SQLite/ASGI for explicit single-pair
standing consent, default-off policy admission without queue/wakeup, profiles/
schema/role/CSRF/revision/protection/conflicting-work checks, old-key replay after
retirement, retained failure non-rearm, concurrent idempotency, audit rollback,
cache/session bounds and lost/malformed reply retry. Chromium tests frozen
token/typed IP/checkbox/focus, native validation and mobile layout without hints.
See [Standing Managed Policy](managed-grants.md); tests never initialize a lab
fixture, enable a live gate or send an FTD command.

`tests/test_managed_batch_grants.py` covers the separate address-list standing
workflow: exact-token parsing/deduplication, full device/address product,
1000-pair admission, strict bodies, one-transaction rejection/late-audit rollback,
concurrent keys, replay after retirement, immutable 100-row pages, session/role/
CSRF/count/checkbox checks and unknown-reply original-key retry. Chromium checks
untruncated drafts and frozen consent through status changes plus mobile layout.
All admission fixtures are synthetic, with no agent connection or lab schema/
policy activation. See [Standing Address Lists](managed-batch-grants.md).

`tests/test_managed_discovery.py` exercises default-off runtime integration on
temporary SQLite with typed fake consoles: fresh initial/priority/final evidence,
next-cycle cutoff/cooldown, duplicate suppression, per-sweep bounds, restart
fairness across devices, generation races, backpressure, held configuration,
failed reads, audit rollback with final monitoring and retained lost-result
attention. No live schema, policy, secret, socket or FTD is used. Chromium also
checks the fixed-height restoration-error warning. See
[Managed Restoration](managed-restoration.md) for the independent gate and limits.

`tests/test_managed_protection.py` exercises atomic protection-driven permanent
retirement, reviewed revisions/all-role BFF identity, full request-ledger revocation,
old-key non-reenable, deferred protection across corruption/repair/restart, audit/
HTTP failure rollback and no work hints. RUNNING ADD, waiting cleanup, uncertainty
and unrelated/newly authorized maintenance remain intact. Synthetic lifecycle tests
prove release/restart never restores old policy, while new explicit consent can
authorize another generation. Chromium checks dirty managed revision retention,
stale rejection, retirement wording and mobile layout without a resume checkbox.
No test mutates lab policy, enables a feature or contacts FTD.

`tests/test_managed_controls.py` covers the distinct executable revocation-only
workflow: frozen/session-bound policy RETIRE, strict current role/CSRF/scope,
same-key retry/new-generation safety, concurrency, paused/disabled/protected/
missing targets, uncertainty/receipt validation and audit rollback. Waiting
cancellation tests owner/Admin, promotion conflict, unknown response/retry,
unchanged running ADD and separate one-time jobs, optional schemas and no new
work signal. All data/actors are synthetic. Chromium checks frozen retirement
token/input/focus and AJAX cancellation without navigation/device hints. See
[Managed Controls](managed-controls.md). Combined removal confirmation stays 503.

`python3 -m pytest -q tests/test_managed_shuns.py` exercises only temporary
SQLite: explicit empty initialization without legacy adoption, canonical managed
mode, current roles, UUID/digest binding, optimistic concurrency, idempotent
replay across retirement/re-enable, whole-batch rollback and caller-owned
savepoint failures, limits/retirement reserve, complete 1000-target views,
retention, restart and SQLite backup. The API now uses optional reads only;
neither normal startup nor the worker initializes/writes managed policy.
No FTD, deployment secrets or local .env is read. Its database tests run within
the ordinary filesystem sandbox; full ASGI/socket regressions may still require
local permissions. See [Managed Shuns](managed-shuns.md) before integration.

`tests/test_managed_view.py` covers optional missing/partial-schema reads,
authentication/all-role visibility, escaped author/metadata, no forms/writes or
refresh hints, observed/retired transitions and version consistency. Package
version lives only in `ftd_shun_manager.__version__`; Hatch reads that field for
wheel metadata and Jinja uses it for every page footer. Update that source on
a release, not separate template/configuration constants. It is not a readiness
badge or live feature indicator. Chromium checks footer placement on desktop/
mobile, the five-tab navigation and revision-driven read-only managed updates.

See [Versioning](versioning.md) for manual release numbering, the pre-1.0
compatibility convention and planned (not implemented) development-build identity.

`tests/test_queue_transactions.py` uses temporary SQLite to verify caller-owned
admission, invisible pre-commit state, savepoint/outer rollback, audit/commit
failure, unchanged authorization/limits/coalescing, and shared atomic retirement
plus queued removal. Tests deliberately retain QUEUED/RUNNING ADD conflicts;
ordinary admission does not invoke the offline coordinator. Returned
accepted logs belong to the caller and must not be emitted before outer commit.
No test in this module opens a device socket or dispatches a command.

`tests/test_managed_removals.py` tests the separate single-target offline
coordinator with real temporary SQLite/queue and synthetic typed outcomes.
It covers RUNNING/no-overlap, verified/no-op/uncertain completion, exact pre-write
deferral, lease recovery, original expiry/cancellation, full rollback, parallel
replay, shared reservations/rate/capacity, generation/key safety and retention/
backup. Startup/API never initializes or admits handoffs; the default-off worker
can advance existing waits before its leased cutoff. See
[Managed Removal Handoffs](managed-removal-handoffs.md) before integration.

`tests/test_recovery_controls.py` covers composite offline suspension, original
uncertainty, atomic audit rollback, private checked/no-overwrite backups,
concurrent-commit refusal, restart durability, resume without resurrection,
paused monitoring/protected-policy suppression, strict default-off worker
configuration and shared lease/cutoff/fresh-snapshot/error behavior. It uses
disposable SQLite and synthetic agents only. See [Offline Recovery](recovery.md).

`tests/test_managed_maintenance.py` covers separately reviewed offline empty
migration and policy resume: complete transactional DDL, exact schema contract,
no adoption, five-minute state digests, private checked backups, uncertainty/
cleanup/clock/protection holds, original authority preservation and new snapshot
barriers. No live database, environment settings, inventory or agent is used.
See [Offline Managed Maintenance](managed-maintenance.md).

`tests/test_managed_attention.py` covers read-only retained incident inspection:
no-init/no-audit, explicit absent/partial state, pruning versus inconsistent
evidence, restoration/queue deduplication, generation/protection/cached context,
bounded fleet samples, separate pending state, stable 100-case pages and changed
snapshot refusal. All fixtures are disposable SQLite; no device/agent/runtime
startup is used. See [Attention Inspection](managed-attention.md).

`tests/test_managed_abandonment.py` covers explicit optional closure migration,
quiescent five-minute/typed confirmation, immutable evidence/receipt, atomic
retirement/audit rollback, original-key concurrency/replay, pruned/inconsistent
evidence, generation/protection/cache conflicts, late expiry and persistent
MAINTAIN/key guards. Fixtures use synthetic source authority and disposable
SQLite only; no agent or live state. See [Incident Abandonment](managed-abandonment.md).

`tests/test_managed_review.py` covers the optional GET and non-executable Web
review: authentication/current role/CSRF, strict fields/scope/reason, immutable
subject/cookie/expiry-bound reviews, concurrent cache bounds, malformed optional
state, escaped outcomes and unconditional 503 on confirmation, even when an
upstream flag claims enablement. Tests never call the coordinator from Web or
admit live work. Chromium checks frozen token/input/focus and handoff color/state
updates using local fixture rendering only. See [Managed Removal Review](managed-removal-review.md).

`tests/test_managed_fleet_controls.py` covers optional fleet status, whole-scope
counts/bounded samples, consistent read transactions, outcome/progress semantics,
pruned/invalid evidence, current owner/Admin/CSRF, strict actor/forms, uncertain
reply retry, audit rollback and cancellation/promotion conflict. No optional
startup migration or device write is used. The Chromium fixture checks mobile
spacing, live revision updates, keyed disclosure preservation and revocation
without navigation or Cisco refresh hints. See [Managed Controls](managed-controls.md).

`tests/test_managed_restoration.py` covers the offline system queue source with
disposable SQLite/typed outcomes: snapshot freshness/pre-write exclusion,
generation/source binding, default-held claims, cutoff/capacity, concurrency,
provenance/NOOP, backoff/churn, retained uncertainty, retirement/protection/
recovery, ordered cleanup and late audit/lease rollback. No live source schema,
controller, discovery, dispatch or rearm is enabled by these tests. See
[Managed Restoration](managed-restoration.md).

Browser confirmation tests in `test_import_review.py` use synthetic ASGI/SQLite
only. They cover frozen exclusions/targets, escaped metadata, current trusted
identity/role and CSRF, unknown fields/counts, subject/cookie/expiry binding,
concurrent bounded cache admission, exact key/body retry after a committed but
lost reply, malformed response uncertainty, disabled intake and atomic policy/
device/opposite-intention rejection. Queue-reason checks retain real deferrals
and audit. Chromium exercises the actual review template, disabled button,
native count validation, token/input/focus retention without POST-view GETs,
live status and 375px layout. See [Browser Import Review](import-review.md).
These tests do not enable ADD or submit any work to the lab stack.

Offline incident acknowledgment tests use disposable SQLite only. They cover
administrative receipts for ordinary/single/fleet incidents, full 205-target scope,
separate predecessor outcomes, original-key concurrency/replay, checked backups,
expiry and atomic audit rollback. No test calls FTD or enables a lab ledger/gate.
See [Incident Acknowledgments](incident-acknowledgements.md) for the operator workflow.

Isolation tests additionally exercise entire-scope retirement/exclusion, missing
inventory, protected-policy priority, claim revalidation, independent uncertain
predecessor cases, healthy-policy resume, immutable latches and atomic migration/
audit rollback. All use disposable state; no live ledger or gate is enabled.
See [Incident Isolation](incident-isolation.md).

`tests/test_bulk_protection.py` exercises the existing protection coordinator and
private API against disposable version-2 storage: permanent whole-address
revocation, every authenticated role without promotion, full-ledger/pause access,
revision/concurrent-grant conflicts, unknown-state barriers and repair, late
rollback, original-key non-reenable and queued/RUNNING/uncertain/coalesced work.
The 100000-pair storage fixture also validates ten-device protection and weakening.
No test connects to an FTD, starts a worker or reads lab settings. This narrow
integration does not make legacy managed readers or dispatch version2-compatible.

`tests/test_bulk_cancellations.py` exercises the explicit version-2 cancellation
extension and bounded work planning on disposable SQLite. It covers actual
100000-pair revocation/restart/pruning/late pages with no executable backlog,
retained adoption/existing grants, generation/replay safety, current owner/Admin,
strict reviews, queue-evidence refusal, migration/audit/deadline rollback,
protection barriers and <=16-pair keyset portions. Local observed presence is
never counted as verified execution. See [Bulk Cancellation and Work Preparation](bulk-cancellation-and-work.md).
No test reads lab settings, starts a worker or opens an FTD connection.

`tests/test_bulk_attempts.py` constructs only synthetic future pre-send transactions
and exercises the actual shared completion/deferral/lease/status/retention hooks.
It covers original authority, verified versus no-op/unknown evidence, retirement/
protection, immutable history, missing predecessors, expiry/namespace/type guards,
late rollback and current owner/Admin read pages. No live claim, admission,
controller, runtime gate or FTD connection is enabled. See
[Bulk Attempt Result Journal](bulk-attempt-journal.md) for the precise boundary.

`tests/test_bulk_waits.py` covers explicit preservation-checked upgrade, initial
RUNNING/QUEUED/completed cancellation, shared typed-result/deferral/lease settlement,
protection/retirement/new-generation precedence, original receipt versus current
counts, old-writer pending evidence, strict retention/quiescence and atomic
audit/DDL rollback. The 100000-member cancellation fixture also verifies upgrade
without changing original checksums/receipts. All source jobs and hypothetical
replacement generations are disposable fixtures, not live admissions. See
[Captured Bulk Cancellation](bulk-captured-cancellation.md).

`tests/test_bulk_dispatch.py` exercises actual bounded admission and shared queue
claim on disposable version-2 state: 16-pair all-or-nothing creation, default-off
capabilities, original authority, cutoff/device serialization, cancellation and
typed outcomes, exact deferral, lease expiry, retained history, fresh-read barrier,
literal/capacity/revision guards and late rollback. Synthetic SQL activation is
limited to test fixtures, not a live enablement recipe. No runtime controller,
network connection or lab mutation occurs. See [Bulk Queue Admission and Claim](bulk-queue-admission.md).

`tests/test_bulk_discovery.py` additionally drives the actual existing Synchronizer
with version-2 desired policy and a fake session agent. It covers bounded refill,
windows/cursors/restart/device fairness, current holds, original-key avoidance,
capacity/late rollback, creation and restoration, cutoff/cooldown, unsent expiry,
unknown results and retained legacy observational barriers. Missing optional
profiles remain errors without migration while read timestamps stay visible.
No test accesses live credentials/settings or FTD. See [Bounded Bulk Refill](bulk-refill-controller.md).

## Prerequisites

`tests/test_device_leases.py` exercises explicit exact-profile initialization,
concurrent owners over the existing queue, same-device/quota contention, nonce/
epoch fences for ADD/REMOVE/result/deferral, expiry without stealing, old-writer
guards, original-source preservation, immutable attention, revocation/settlement
and complete rollback. Fixtures use disposable SQLite/local threads only; no live
profile or credentials. See [Fenced Device Leases](device-leases.md). This is not
an automatically running parallel Synchronizer or a replacement job executor.

Agent concurrency tests use a fixed bounded pool, synthetic device/address guards,
local SOCK_SEQPACKET pairs and local Tokio timers, never SSH or live credentials.
Process-isolated preflight tests check default/canonical limits and unchanged ADD
gates without binding a listener. Run Rust fmt/Clippy/release/test commands from
[Agent Connection Concurrency](agent-concurrency.md). The API's global lease remains
serial; these tests are transport prerequisites, not end-to-end parallel acceptance.

- Python 3.12+
- Rust 1.89+ for the privileged agent
- A virtual environment
- Docker Compose or Podman Compose only for container-level validation

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export FTD_SHUN_DATABASE="$PWD/.local/state.db"
export FTD_SHUN_API_SOCKET="/tmp/ftd-shun-api.sock"
export FTD_SHUN_WEB_SOCKET="/tmp/ftd-shun-web.sock"
export FTD_SHUN_AGENT_MODE=mock
export FTD_SHUN_DEVELOPMENT_AUTH=true
```

Start the internal API and BFF in separate terminals:

```bash
.venv/bin/ftd-shun-api
.venv/bin/ftd-shun-web
```

For local browser work, proxy the Web/BFF Unix socket with Caddy or use a test client that sends `X-Dev-User` and `X-Dev-Groups`. `FTD_SHUN_DEVELOPMENT_AUTH=true` is forbidden in deployed environments.

## Safety boundaries

- `mock` accepts the typed `LIST_SHUNS` and `REMOVE_SHUN` operations; it returns an empty snapshot and never opens an SSH connection.
- `disabled` is the safe default and returns an error for every removal attempt.
- `socket` is the only deployment mode. It requires an FTD agent on `FTD_SHUN_AGENT_SOCKET` to return the exact verified-success result. Default legacy removal uses one byte; experimental cycles use the versioned response envelope.
- No interface accepts executable Cisco CLI. Import preview accepts untrusted
  paste as data only; no raw text or comment reaches the agent.

## Checks

```bash
.venv/bin/python -m compileall src
.venv/bin/pytest
.venv/bin/ruff check .
docker compose -f deploy/compose.yml config
```

## Agent checks

The [addition contract](addition-contract.md) has an offline evidence model
in `agent/src/addition_contract.rs`, compiled only with `cfg(test)` and excluded
from release agents. Its parsers are now shared with gated production ADD;
the model itself has no sender/socket or queue linkage. Regressions
check exact recorded acknowledgement, fresh source-only verification, no-op
without ownership for pre-existing targets, wrong scopes/fields/targets, partial
success, controls/Unicode, duplicate output and bounded evidence. Python/Rust
boundary checks keep ADD outside legacy RPC/v1/v2 and require explicit v3,
agent flags and per-device scope before SSH. Shared v3 vectors and real local
SeqPacket tests cover mixed requests, exact responses, no fallback/replay,
lost/malformed results and complete 20,000-entry streams. Fake consoles verify
combined mutation limits, command/time/END reserves, pre-existing no-op,
capacity/profile rejection and uncertain post-write outcomes. The API still
constructs v1/v2 clients even if the new agent flag is present. These tests are
not live addition, timing or data-plane validation.

[Large snapshot](large-snapshots.md) tests share fixed v2 wire vectors across
Python/Rust, collect 7,307/20,000 synthetic entries over real temporary
SOCK_SEQPACKET sockets, and test exact bounds, chunk splits, digest/order/
binding/EOF/truncation rejection, absolute transfer deadlines and preservation
of prior SQLite state on an incomplete empty stream. Legacy vectors and v1
mutations remain covered. Both new production selectors default to false.
The tests do not create shuns, contact FTD or establish live large-load behavior.

```bash
cargo test --manifest-path agent/Cargo.toml
```

The agent test suite covers strict binary request decoding, the typed `LIST_SHUNS` response, and fail-closed parsing of `show shun` output. Do not use `mock` to validate Cisco behavior. The actual agent requires recorded, sanitized device output and a non-production FTD lab.

Experimental session-cycle tests share fixed wire vectors between Python and
Rust. They exercise sequence/version/length rejection, one Unix connection,
truncated responses, count/command/time limits, pre-write deferral, unknown
interfaces, and failed verification. Scheduler fixtures cover bounded batches,
safe priority checkpoints, recent-snapshot coalescing, mid-cycle admissions/
cancellation, independent snapshot publication, and retained verified results
after later failure. These are fake-console/transport tests, not live SSH
compatibility evidence. The opt-in flag remains false until the
[cycle laboratory procedure](agent-cycle-protocol.md#migration-and-laboratory-validation).

## Browser refresh regression checks

The [Import Preview manual](import-preview.md) documents its independent
preparatory boundary. Parser tests cover literal/list/comment/free-text rules,
ambiguous and unsupported forms, no substring extraction, duplicate references,
UTF-8/line/row/body/pair limits and maximum-length hostile tokens without
unbounded regex backtracking. API/BFF checks cover explicit enabled targets,
snapshot classification, CSRF/escaping, chunked-body limits, no queue/audit/agent
side effects and no raw-source forwarding to the internal API. They also cover
large synthetic batches up to 10,000 rows, complete classification before
100-row pagination, retained HTML errors for oversized decoded text and worst-
case percent-encoded UTF-8. Browser tests paste a 7,307-row synthetic list with
real input events, navigate result pages and block oversized multibyte input
without truncation, queue admission or device execution. The browser scenario
checks every preview outcome, escaping and draft/result/focus retention
through metadata updates without extra parses, hints or execution.

With Node.js 22+ (built-in WebSocket support), Chromium, and the Python package
available in the same environment, run:

```bash
node --test tests/browser/freshness.cjs
```

Set `CHROMIUM` to the Chromium executable if it is not `chromium-browser`.
The test uses the real repository templates and freshness JavaScript, an
ephemeral localhost server with synthetic status/state, and a temporary browser
profile. It requires local socket binding and Chromium's sandbox support; it
does not use Docker, `.env`, real authentication users, or FTD connectivity.
No npm installation is needed.

Scenarios cover a single manual request, a slow in-flight status response,
multiple tabs, imminent-baseline display, repeated identical failures, API
restart, status/network recovery, failed POST/retry, and preservation of search
text, expanded history, confirmation values, and focus during partial updates.
Python tests separately exercise the real scheduler's slow-cycle coalescing,
partial fleet success, detached revisions, and BFF authentication/CSRF/no-store
boundaries. The browser fixture is not evidence of live FTD or Authelia
compatibility; that remains an integration/laboratory check.

Staged admission tests use only synthetic SQLite/ASGI state: parallel actors,
atomic opposite-action rejection/overflow, canonical confirmation and immutable
replay, policy edits, expiry/lease loss, legacy schema/claim/state-writer guards,
per-occurrence provenance, retention and bounded 1000-target metadata. A normal
scheduler observation cannot execute a held ADD or assign origin. API responses
cover nested provenance; Chromium covers held/cancellable rows, escaped details,
blue badges and their disappearance after a new external occurrence. Future
completion hooks are invoked with synthetic typed results, never actual ADD.
See [Import Admission](import-admission.md); do not use private API requests as
an independent live writer or turn on gates just to run tests.

[Queued execution](import-execution.md) tests cover profile-bound v3 selection,
common ADD/REMOVE FIFO and 16-step/cooldown bounds, held jobs on ordinary devices,
policy changes, per-claim expiry including coalesced actors, priority reads,
cancellation and cutoff, exact deferral versus unknown results, later final-read
failure, restart/shutdown/lease recovery without replay, and actual local
SeqPacket worker success/lost-response conversations. Synthetic admission tests
check eligible new work versus held/replayed requests and metadata. Chromium
checks held/running transitions, indeterminate ADD progress and readable phase
text. These tests do not read `.env`/lab inventory, SSH credentials or actual FTD.

Queue coverage also exercises simultaneous SQLite admissions, atomic overflow,
idempotent replay after completion, scope binding, cancellation ownership,
expiry, one executor/cycle gate, abandoned-write recovery, policy changes,
retention, and the documented restore SQL. API tests verify that a 202 response
does not execute a write and that only the scheduler dispatches the fake agent.
The Chromium fixture covers queue progress/cancellation and idempotent retry
after an admission reply is lost and a dynamic render replaces the form.

Queue display regressions check independently bounded active/attention/recent
results, RUNNING-first ordering despite a large backlog, totals versus visible
rows, collapsed completed results, active-to-completed transitions, IP-history
links, and disclosure state across dynamic updates. Display changes never
delete stored jobs or alter execution.

Request-progress tests distinguish actual linked-job totals from historical
counts and per-cycle caps, processed versus verified outcomes, cancelled
coalesced requesters, bounded 20-request summaries, and consistent snapshots.
Chromium checks determinate request bars, indeterminate running commands,
warning outcomes, phase changes without false advancement, stable indicator
nodes across differently ordered JSON, and removal of settled progress cards.

Protected-policy tests cover SQLite-only runtime settings, atomic once-only
legacy import (including empty/invalid input), deletion across restart, parallel
revision conflicts, authentication/CSRF boundaries, actor attribution, protected-only
search, and policy revalidation before each claim. Chromium also checks menu
keyboard/Escape/outside-click behavior, narrow viewport bounds, persistent
warnings, progress spacing, separate history updates, per-IP drafts with original
revisions, escaped labels and the protected-IP add/edit/disable/delete flow.
Display regressions cover enabled/disabled badges, active versus inactive
observations, disabled protection in search/shun/detail views and live badge
transitions without policy writes, audit changes or refresh hints. Chromium
checks the actual green/red styles and revision-driven warning replacement.

Protected-IP authorization now intentionally permits every authenticated user:
Viewer, Operator, Administrator and users without a mapped group. Parameterized
BFF/API cases verify those paths, unchanged actual-role audit, denial of blank/
anonymous identities, CSRF and spoofed form identities. The real Chromium CRUD
scenario uses Operator. Manual shun-removal/queue ownership tests remain strict;
shared policy access does not promote roles or grant cross-user cancellation.

History tests cover fixed 100-row pages, stable timestamp ties, no overlap,
new inserts outside an anchored browsing window, retention/clamping/expired
anchors, empty state, restored hex UUID IDs, concurrent count/row consistency,
bounded query validation and BFF authentication/canonical links. Chromium
navigates a 251-event fixture, observes the live 252nd event without moving an
older page, and measures unchanged search coordinates during refresh, device/
queue errors and network failure at 1100px and 375px viewport widths.
