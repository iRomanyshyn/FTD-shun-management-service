# Prepared Managed-Import Confirmation

## Delivery boundary

The backend now confirms a saved [preparation](managed-import-preparations.md)
as standing policy in one transaction. It implements explicit unmanaged adoption,
protected/invalid exclusions and retained reports independent of preview expiry.
The [managed-import Web workflow](managed-import-web.md) now exposes saved
preparations, frozen confirmation and receipts, but is **not yet the 10,000-IP
executable release**. Confirmation remains behind the default-off
`FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED` gate and requires explicitly existing
policy, attempt, preparation, confirmed-report and cancellation schemas. Startup/requests never
initialize them. No lab migration, grant, profile or gate activation is authorized.

Preparations may hold 100,000 proposed pairs, but confirmation still accepts at
most **1000 non-protected device/IP pairs**, with the existing 1000-key registry
limit including stopped keys. A larger scope is rejected whole, never truncated,
split or turned into many requests. Compatible larger policy/attempt capacity,
rolling execution are pending. The
[cancellation backend](import-cancellation.md) stops uncompleted application only.

## Confirmation and provenance

Use a separate canonical UUID operation key, the original preparation ID/digest,
the exact accepted **pair** count and explicit recurring-maintenance consent.
Current Operator/Administrator identity is required; roles captured in the draft
are historical, not current permission. Every accepted device needs an explicit
addition-capable profile, including adoption because future maintenance can ADD.

Within one `BEGIN IMMEDIATE`, verify the entire original digest, owner, lifetime,
clock, selected enabled device IDs/names, managed/protection revisions and current
classification/prior intent references. Pending/uncertain jobs, failed/uncertain
attempts, recovery pause, cleanup, isolation and abandonment remain blockers.
Changes reject the entire confirmation and require a new review; no silent rebase.
Normal observation heartbeats do not conflict when pair classification is unchanged;
this is cached presence, never fresh device verification.

| Prepared classification | Confirmation effect |
| --- | --- |
| `PROPOSE_ADD` | Save explicit maintenance; no immediate job or verified creation. |
| `PROPOSE_ADOPT` | Save maintenance over locally present unmanaged state, without ADD or fabricated creation provenance. |
| `ALREADY_MANAGED` | Keep original intent/generation/authorizing request and author; do not adopt or replace them. |
| `EXCLUDED_PROTECTED` | Retain the visible exclusion; grant no authority for that pair. |
| Invalid/ambiguous/unsupported/duplicate input | Retain generated source-line diagnostics/counts; never manufacture another target. |

All-invalid/all-protected input has no accepted policy to confirm. Existing
admission capacity and retirement ledger reserve still apply. The coordinator
uses the **existing canonical MAINTAIN request and effective target registry**,
not a parallel policy engine or a loop of single-target transactions. Existing
grant endpoints continue to reject adoption; the internal exact adoption set is
not an HTTP field or a generic permission switch.

Commit canonical authority/targets, immutable report/scope and actor-linked audit
together or none. Adoption emits `MANAGED_SHUN_ADOPTED`; the root emits
`MANAGED_IMPORT_CONFIRMED`. A minimal structured log is emitted only after commit.
No ADD/REMOVE, queue insertion, refresh hint, policy resume or gate change is
performed by confirmation. Existing revocation cancellation checks stay intact.
The result is `policy_saved`, `policy_only=true`, `device_work_admitted=false`:
this is not verified creation/removal or current execution progress.

## Retained reports, retry and cancellation

Two explicit additive tables, `confirmed_import_receipts` and
`confirmed_import_members`, retain the author-attributed exact accepted/excluded
scope, generated diagnostics, original preparation digest and assigned/prior
intent references. Four UPDATE/DELETE guards retain immutable reports. Full
streamed checksums bind both original preparation membership and the enriched
confirmation receipt. No raw paste/comments/excerpts are copied; label/reason
are intentionally retained metadata and must be escaped in future HTML.

Reports return at most 100 target and 100 diagnostic rows per page. They are
**historical confirmation reports**, not live queue progress. Owner lists recover
original keys after a lost response or restart; other subjects cannot read them.
The original-key retry returns its old result even after draft pruning, policy
retirement or a newer generation; it never re-enables policy. A different key
cannot confirm the same preparation again. Existing ordinary policy keys cannot
acquire import meaning. Receipt reads remain available when admission is off.

Preparation pages/lists show `CONFIRMED` and the original operation ID once saved.
Cancelling such a draft is explicitly refused: it cannot masquerade as cancellation
of standing policy or running work. Unconfirmed draft cancellation remains local
and idempotent. [Confirmed-import cancellation](import-cancellation.md) that retains
added/adopted targets and stops unsent work is a separate private operation, with
its own explicit schema and frozen whole-scope review. Existing
policy retirement and Protected-IP permanent retirement remain supported controls.

Retain at most 128 receipts and 1,000,000 report-member rows globally. These bounds
do not expand policy capacity. Overflow refuses new confirmation, without evicting
receipts or consuming the separate retirement reserve. No automatic report/key
recycling exists. Draft expiry/pruning cannot delete confirmed reports or authority.

## Private API and Web integration

All paths below are fixed private POSTs beneath `/api/v1/managed-imports/`, reachable
only through the existing private API socket. Actor identity must come from the
trusted authenticated BFF, never a public form/header override. Read POSTs keep
owner references out of URLs and change no state. Every response is `no-store`.

| Suffix | Strict body / behavior |
| --- | --- |
| `prepare` | Actor, text, explicit device IDs, optional label/reason; Operator required; creates an unconfirmed draft only. |
| `preparations` | Actor; list retained owner drafts without initialization. |
| `preparation` | Actor, preparation ID, optional positive page; frozen local report. |
| `cancel-preparation` | Actor, preparation ID; cancel only an unconfirmed owner draft. |
| `confirm` | Actor, preparation ID/digest, accepted count, strict boolean consent, canonical `Idempotency-Key`; separate trusted gate/profile capability, no caller-supplied targets/action/CLI. |
| `receipts` | Actor; owner confirmation references, including when admission is disabled. |
| `receipt` | Actor, operation ID, optional positive page; historical report only. |

The [Web forms](managed-import-web.md) enforce authentication/session/CSRF and
sensitive-action age, display exclusions/exact accepted scope and retain original
key/body after uncertain replies. Confirmation is not execution; retained receipts
remain readable after draft expiry. Draft cancellation is never presented as
confirmed-import cancellation, and the UI activates no hidden execution.

## Validation, migration and rollback

Run `python3 -m pytest -q tests/test_managed_imports.py tests/test_import_preparations.py`.
Fixtures use temporary SQLite/ASGI only. Validate mixed adoption/exclusions, current
actor versus captured roles, whole-scope conflict/expiry, late audit rollback,
concurrent original-key confirmation, draft pruning/restart, immutable receipts,
owner separation, permanent protection retirement, full current 1000-pair scope,
oversize refusal and unchanged queue/occurrence provenance. This is not hardware
throughput, a live bulk grant or production acceptance.

No migration is performed in the current lab. Before eventual activation, retain
checked SQLite-safe backup and matching API/configuration rollback, review the two
additive report tables/four triggers and separate unchanged preparation schema,
and finish larger-capacity/dispatch compatibility. New confirmation also requires the
separately reviewed [cancellation schema](import-cancellation.md#migration-backup-and-rollback).
The explicit internal
`ManagedImports.initialize(connection=...)` adds only empty report tables; it
requires existing policy/attempt schemas and never creates/adopts/unsuspends them.
There is no operational migration shortcut or automatic repair.

Normal API startup merely constructs coordinators and exposes gated routes.
The [Web increment](managed-import-web.md) uses paired API/Web rollout without
automatic schema migration or agent replacement; restart may execute already admitted ordinary work.
Keep all live flags/profiles/credentials unchanged. Retain report data on code
rollback; never delete authority, receipts or restore old enabled targets as a
software downgrade. Older offline tools continue validating the unchanged canonical
standing authority; reports are separate immutable evidence, not a bypass of their
uncertainty, suspension or exact-schema managed controls.
