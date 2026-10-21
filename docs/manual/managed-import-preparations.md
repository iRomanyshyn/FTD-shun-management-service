# Durable Managed-Import Preparations

## Delivery boundary

This is the storage foundation for the working-version bulk flow, not an executable
import release. `ImportPreparations` freezes a private, unconfirmed local-state
plan that survives process restart. It does **not** save standing policy, adopt a
shun, submit a job, renew a user request or contact FTD. Current Import/Managed
Web workflows and their existing 1000-pair admission bounds remain unchanged.

There is no HTTP route, background dispatcher, runtime feature flag or automatic
schema initializer for this journal yet. No lab migration or bulk test is enabled.
Future confirmed imports need separately durable authority and progress, not jobs
attached to an expiring preparation. See the
[Working-Version Plan](../working-version-plan.md#capacity-contract-for-the-next-import-increment).

## Frozen scope and reporting

Preparation accepts the existing bounded parser's exact IPv4/free-text/comment
formats: at most 1 MiB UTF-8, 20,000 lines and 10,000 parsed rows. Select explicitly
1–10 distinct enabled device IDs; at most 100,000 unique device/IP rows are stored.
Duplicates are counted once in that product. Invalid/unsupported/ambiguous input
is retained as line-number/status/generated-reason diagnostics, never guessed or
silently turned into an address. An all-invalid/empty input can produce a zero-
target diagnostic report, not fake accepted work.

One SQLite transaction freezes author/display name/captured roles, UTC creation/
expiry, managed/protection revisions, device labels, normalized label/reason,
source-line diagnostics and every proposed pair:

| Classification | Meaning, not execution |
| --- | --- |
| `PROPOSE_ADD` | No active local observation or enabled maintenance; later admission needs fresh checks. |
| `PROPOSE_ADOPT` | Locally observed and not already maintained; propose explicit future maintenance, not past service creation. |
| `ALREADY_MANAGED` | Existing enabled intent is unchanged; preserve its original grant reference/generation. |
| `EXCLUDED_PROTECTED` | Enabled exact-IP protection excludes the pair, even if locally observed. |

Protected entries win over other classifications. Disabled entries do not protect.
Keep cached `observed_at` separate from a verified creation or a fresh Cisco read.
Stopped existing policy keeps its previous intent/generation/authorization metadata
without being re-enabled. Unknown/partial managed state refuses preparation;
an absent optional registry is explicitly **not initialized**, not migrated.
Queue conflicts, profiles, current actor permissions and fresh evidence are still
mandatory admission work; a proposed ADD is not a ready executable command.

Original pasted source, comments, excerpts and arbitrary text surrounding addresses
are not stored. Plain-text label/reason are retained intentionally (100/500
characters; never put secrets there). Header storage is capped at 2 MiB. Future
HTML must escape these fields. No credential, connection route or host-key material
is stored in the preparation. Captured roles are history, never current authority.

## Contributor interface

`ImportPreparations(store)` has no constructor side effects. The Store/database
and configured public devices must already exist. Methods are internal Python
interfaces only, not a substitute for future authenticated/CSRF admission:

| Method | Contract |
| --- | --- |
| `initialize(connection=...)` | Explicit empty two-table/two-trigger initialization, optionally within a caller-owned transaction. Refuse partial/modified schema; never repair it. |
| `create(...)` | Freeze a new unconfirmed UUID/digest under one transaction; return a reference and `can_execute=false`. |
| `list_for_owner(subject)` | Recover up to four retained private references after restart/lost response; absent schema returns uninitialized without writes. |
| `page(plan_id, subject, page=...)` | At most 100 target rows and 100 source-report rows per page; global totals remain explicit. No clamping, mutation, initialization or refresh hint. |
| `verify(plan_id, subject, expected_digest)` | Stream all target rows in 100-row chunks and check the frozen digest; integrity is not freshness or permission. |
| `cancel(plan_id, subject)` | Invalidate only this unconfirmed preparation; no policy retirement or queue cancellation. Repeated cancellation is a no-op. |
| `prune_expired()` | Explicitly delete expired preparations and their children only; never policy/queue/attempt/origin/audit records. |

Rows/header are immutable; only the first cancellation timestamp may change.
The SHA-256 digest is domain/version-bound, canonically framed and includes the
entire scope/diagnostics/author/metadata, not merely the visible page. Member counts
are checked before reports. Owner mismatch and unknown reference do not expose a
different user's contents. Modified/missing membership fails verification rather
than becoming a smaller accepted scope.

Reads do not reclassify after policy/observations change. They show that frozen
preparation, not a silently rebased current plan. The future confirmation workflow
must independently recheck current actor/session/CSRF, expiry/cancellation, exact
scope, devices/profiles, managed/protection revisions, adoption/observations,
conflicting work and retained uncertainty; conflicts require a refreshed review.

## Lifetime, capacity and cancellation

Preparations expire after ten minutes; maximum four retained per author/sixteen
globally, including cancelled/expired entries until explicitly pruned. Capacity
failure never evicts another review or writes part of a plan. Expired/cancelled
reports can still be inspected until pruning, but never authorize anything.
`verify` can confirm their integrity and still returns `can_execute=false`.

Lost creation responses may leave another harmless unconfirmed preparation;
recover references through the owner list instead of treating silence as accepted
work. There is no executable idempotency result here. Future confirmed-import
cancellation must preserve completed/adopted maintained targets and settle running
commands; cancelling this preparation is not that later operation.

## Validation, migration and rollback

Run `python3 -m pytest -q tests/test_import_preparations.py`. Fixtures are private
temporary SQLite only: maximum 10,000 addresses / ten devices / 100,000 rows,
restart, full-scope digest/100-row reads, provenance/exclusions/privacy, owner
separation, frozen revisions, corruption, concurrency/capacity, exact expiry,
draft pruning and late-insert/outer-transaction rollback. Queue, policy, attempts,
origins and audit outside the journal must remain byte-for-byte unchanged.
These are not FTD throughput, device ADD, adoption or production acceptance.

No migration was performed in the lab, and no service restart is needed for this
unconnected foundation. Do not initialize live tables merely to smoke-test code.
Before eventual activation, retain checked SQLite-safe backups and matching images,
review the additive journal schema and its full admission/lifecycle integration.
Never initialize optional managed/attempt tables, change gates or infer authority
from an old preparation as part of this migration.

Rollback of this isolated code does not undo any device state or standing policy;
there is none authorized by the journal. Retain its additive data for review until
normal approved draft expiry/pruning. Once a future confirmed import exists, its
authority/progress/evidence must be copied and retained independently of these
ephemeral rows; a draft-only rollback/prune must not delete admitted work.
