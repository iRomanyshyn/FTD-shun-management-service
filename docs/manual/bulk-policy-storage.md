# Version-2 Bulk Policy Storage

## What is implemented

`BulkPolicies` is a development component that atomically persists an actual
version-2 policy grant, exact classified membership and audit. It supports up to
10000 addresses on ten explicit devices / 100000 pairs per import. It is not
merely a saved preview. It does **not** execute commands, enqueue jobs, resume
restoration or expose HTTP/Web admission. The current lab still uses the previous
legacy profile; no production deployment is involved.

The component deliberately uses a distinct, suspended storage profile. Existing
services cannot safely interpret the new roots yet and refuse this profile even
when it contains only one target. Do not start the old application against a
version-2 test database or expect its maintenance commands to resume it.

See [the format](bulk-import-capacity.md) and [working-version plan](../working-version-plan.md).
Integration with the usable Web/import/worker flow remains the next delivery work,
not a reason to turn the legacy feature flags on.

## Stored authority and atomicity

The profile keeps **one** effective `(device_id, IPv4)` policy and uses the
existing immutable request ledger, not a parallel enforcement engine:

| Table | Role |
| --- | --- |
| `managed_bulk_registry` | Exact version2/revision and suspended restoration; replaces the legacy registry name. |
| `managed_shun_requests` | Original actor/display/roles, canonical grant or retirement and immutable result. |
| `managed_shun_targets` | Effective intent/generation, enabled/stopped state and authorizing request. |
| `managed_bulk_manifests` | Independently retained original preparation header, descriptor digest/counts and unique preparation reference. |
| `managed_bulk_members` | Complete classified scope, original observations/prior intent and assigned authority references. |

Requests, manifest metadata and members have update/delete guards. Membership
is inserted before its manifest's final seal through a deferred foreign key.
The seal checks exact total/accepted counts and prohibits any later member insert.
All of this, effective policy and real-actor audit share one transaction. A failed
last member, audit or integrity/deadline check leaves no partial request, policy,
manifest, members or events. Savepoints preserve this guarantee when an outer
caller catches the error and commits its own unrelated work.

The new registry's different name is intentional: legacy `managed_state` sees
partial/unsupported state instead of assuming that a small version2 database is
legacy-compatible. The current legacy initializer also explicitly refuses bulk
objects instead of recreating a second registry. No startup/GET initializes or
repairs this profile.

## Capacity and retirement reserve

| Retained resource | Fixed profile bound |
| --- | ---: |
| Effective keys, including stopped keys | 200000 |
| Immutable request ledger | 400000 |
| Ledger slots reserved for actual retirement | Final 200000 |
| Bulk import roots | 128 |
| Classified members across retained roots | 1000000 |

The key limit leaves room for a complete 100000-pair import alongside other
retained keys. New grants and no-op churn cannot consume the final retirement
reserve. A retirement consuming it must actually stop at least one enabled key.
Capacity overflow rejects the whole new operation; no automatic eviction,
idempotency-key recycling, tombstone deletion or hidden splitting is performed.
These are SQLite storage bounds, not console throughput or device capacity claims.

## Prepare, confirm, recover and stop — internal interfaces

Use `BulkPolicies.preparations`, an explicit bulk-profile subclass of the existing
non-authoritative preparation journal. It classifies against the new registry,
not a fallback in the legacy application. Its original digest still binds all
generated diagnostics, metadata, owner and classified cells. Current classification
and generations are rechecked at confirmation, not inferred from that digest.

`confirm(canonical, digest, accepted_count, subject, display_name, roles, ...)`
requires current Operator/Administrator, recurring consent, typed accepted pair
count, explicit default-false trusted admission capability and eligible device
profiles supplied by the trusted caller. No public form can provide these
capabilities. Inside one transaction it checks:

1. Exact profile/schema, descriptor and complete source/manifest integrity.
2. Original owner and a live, unconfirmed/uncancelled preparation.
3. Frozen managed/protection revisions, selected enabled device identities/names,
   metadata, every classification and prior intent/generation/authorization.
4. No ordinary mutation pause, executor lease or pending/uncertain queue work.
   Unsupported optional managed/incident/cancellation state is refused, not erased.
5. Whole-scope retained capacity and positive retirement reserve.

Absent targets establish maintenance only. Observed unmanaged targets are adopted
without an ADD or invented service-created occurrence. Already-managed targets
keep their original intent/generation/authorization/author. Protected exclusions
grant no authority. Actual confirmation identity is retained separately from the
draft's historical Viewer/Operator roles. Restoration stays suspended.

The result is `policy_saved`, `policy_only=true`, `device_work_admitted=false`,
not VERIFIED creation. `list_for_owner` recovers original keys; `page` returns
historical confirmation in 100-member pages with full streamed integrity checking.
Receipts and independent membership survive draft pruning and later retirement/
generations. Exact original-key replay returns history without re-enabling anything;
a preparation cannot obtain a second root. Reads are owner-bound and create no
authority. `policy_page` returns 100 current retained keys and optional exact-
revision conflict checking, not an observed shun list or a device refresh.

`retire` is a separate exact-revision/digest, bounded literal-pair policy-only
operation. It preserves original intent/generation and authorizing root, records
the real revoking actor and remains available while new authority is paused or
disabled. No REMOVE, job interruption, uncertainty resolution or independent-job
cancellation follows. Missing members reject the entire retirement. Original-key
replay is observational. A later explicit grant needs a new reviewed generation;
pending/uncertain work still blocks it.

## Initialization, backup and rollback

There is intentionally no migration CLI, runtime profile switch or live runbook
yet. `initialize_empty` is an internal explicit empty-managed-namespace operation
for fresh development databases with existing base/queue tables. It requires an
ordinary mutation pause and no lease, pending jobs or uncertainty. It refuses any
existing legacy/bulk/partial/incident managed state; it never converts retained
policies, receipts or history and never initializes preparation schemas implicitly.

Do not delete the lab database or optional evidence to make this initializer run.
The lab's completed experiment remains retained in legacy format. Nonempty legacy
conversion is separate work. Before eventual conversion/activation, retain a
checked SQLite-safe private backup and matching code/configuration; stop writers
and settle RPCs. Filesystem copying of an active WAL database is not a backup.

Code-only rollback on today's unchanged lab needs no database restore. A populated
version2 database must be retained with compatible code or taken offline; older
writers/readers cannot be used as a downgrade. Do not rename its registry back,
discard membership, restore old enabled policy or relabel uncertain results.
The existing recovery tools describe their legacy profile, not this new one.

## Validation and remaining integration

```bash
python3 -m pytest -q tests/test_bulk_policy.py tests/test_bulk_intent.py tests/test_bulk_preparation_intent.py
```

Disposable SQLite tests cover real 100000-pair policy persistence, paged reads,
restart/draft pruning, same-key concurrency, source/classification conflicts,
adoption/exclusions, immutable sealing, late rollback including outer-commit
composition, actual retirement reserve, unknown-result preservation and legacy
fail-closed behavior. No lab fixture or FTD command is used.

Remaining: version-aware protection retirement/weakening barriers, cleanup and
import cancellation, retained attempt capacity and bounded rolling dispatch;
then nonempty development migration, API/Web and end-to-end lab validation.
The initial profile refuses unsupported optional state rather than bypassing it.
This is not yet executable 10000-IP import, live restoration, measured console
throughput, automatic uncertainty reconciliation or production acceptance.
