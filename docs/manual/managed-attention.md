# Offline Attention Inspection

## Purpose and boundary

Use this report to identify retained cases requiring investigation before
managed-policy resume. It is read-only: no latch resolution, new authorization,
policy retirement/resume, queue insertion, audit append, feature change or FTD
query occurs. A report digest is not an executable confirmation. There is no
HTTP endpoint or automatic background inspector in this increment.

Use the current source/package. Existing lab images were not replaced for this
offline tool. Do not initialize optional schemas or enable any gate merely to
obtain a report: ordinary uncertainty can be inspected with no managed tables.
Partial/changed managed schema instead refuses inspection, not an empty result.

## Procedure

Follow the stop-services/settle-RPC prerequisites in
[Offline Managed Maintenance](managed-maintenance.md). Stop the sole API/Web pair
and prevent restart. Ensure no previous agent RPC can still execute; stop the
agent too if necessary. `--confirm-offline` is the operator's assertion, not proof
provided by the CLI. An expired database lease does not prove remote settlement.
Use the database owner's UID and the reviewed existing absolute SQLite path,
including its WAL. The tool uses a read-only connection and never creates a
missing database. Paths below are illustrative, not the actual lab paths.

```bash
ftd-shun-managed-maintenance attention \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

The module form is `python3 -m ftd_shun_manager.managed_maintenance attention`
with the same arguments. No backup is created because this command does not
write. Do not infer that the report replaces a checked backup for any later
maintenance operation. Output contains private device names, addresses and
authorization IDs; keep any captured copy in an operator-owned private directory.
Raw errors, CLI output, batch labels/comments, credentials, host keys and full
import/fleet payloads are not returned.

## Reading a report

`retained_case_count` and `counts` describe only evidence still retained, not all
lifetime failures. `managed_initialized=false` means managed component counts,
pending state and desired suspension are `null`, not proof of zero incidents.
Known empty initialized components have numeric zero counts.

| Case kind | Evidence and interpretation |
| --- | --- |
| `operation` | Retained ordinary UNVERIFIED ADD/REMOVE. Never repeat its original request to infer the outcome. |
| `restoration` | Immutable FAILED/UNVERIFIED system attempt, original intent/generation/authorization and linked job if retained. The matching uncertain queue row is not counted again. |
| `device_cleanup` | Single-target ATTENTION handoff. Its related job is the captured predecessor **ADD**, not proof that a REMOVE ran. |
| `fleet_cleanup` | Whole-scope ATTENTION barrier, exact retained target count and at most five sampled targets. Malformed/mismatched scope is explicitly inconsistent with unknown count, never a smaller inferred scope. |

Stable `case_id` names the source and its original record ID. A restoration
case retains its pair-wide latch even if policy was retired or a later generation
exists. New generation/current intent and the attempt's original generation are
shown separately. None of these fields is a reset/retry capability.

`related_job.state` distinguishes `retained`, `not_retained`, `inconsistent` and
`not_applicable`. Pruned job/delegation history is not success. Inconsistent
action/pair/outcome is not silently trusted or used to hide another uncertain
operation. Original request-link count is informational, not current permission.

Target context shows current persisted device/maintenance/protection state and
cached active-interface count/last-seen UTC timestamp. Missing current device or
policy remains explicit. `observation_basis=cached_not_write_verification` means
exactly that: cache presence, absence, a retired target or a later observation
cannot change an old UNVERIFIED result into VERIFIED. Inspection does not fetch
a fresh device snapshot; obtain one through an independently authorized read
workflow and retain the distinction between observation and write verification.

`pending_jobs` and `pending_managed` are separate from terminal cases. They show
unfinished queue/restoration/single/fleet work and inconsistent fleet admission
phases that can also block resume. Recovery pause, desired suspension and an
outstanding executor lease are reported independently. Missing pending system
queue evidence, invalid optional metadata and unsupported capacity refuse the
report rather than being treated as no work.

## Pagination and consistency

Each page contains at most 100 cases, ordered by original request time newest
first, then source/record ID for stable ties. `has_next` and `total_pages` describe
the retained snapshot. To read page 2, copy page 1's `snapshot_digest`:

```bash
ftd-shun-managed-maintenance attention \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --page 2 --snapshot-digest DIGEST_FROM_PAGE_1
```

All subsequent pages require that original digest. It binds retained cases,
managed authority, queue/link state, executor, devices, protection and cached
observations. Changes refuse with **start again at page 1**, not automatic rebase
that might skip incidents. A digest has no authority/expiry semantics and cannot
be supplied to a write command as a managed confirmation.

The tool streams fingerprint input rather than collecting all history in Python
memory, but scans retained context on each invocation. It is an offline diagnostic,
not a cheap Web polling API. Database work is not limited to the 100 returned
cases; large retained databases require an appropriate maintenance window.

## Inspecting one complete case

The catalog samples at most five fleet devices. Use `attention-case` to inspect
all retained members, without executing or preparing a resolution. Copy the
exact `case_id` from the catalog; accepted prefixes are `operation`, `restoration`,
`device_cleanup` and `fleet_cleanup`, followed by a canonical UUID. The same
offline prerequisites and private-output handling apply.

```bash
ftd-shun-managed-maintenance attention-case \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --case-id fleet_cleanup:UUID_FROM_CATALOG
```

The result includes `case` evidence, `target_count`, `total_pages`, `has_next`
and up to 100 `targets`, sorted by original device ID. Each fleet target has
`reviewed` original device/intent metadata and separate `current` persisted
context. `reviewed_scope` carries original policy revisions/protection state.
A device missing from today's inventory stays in the retained scope, with null
current hostname/enabled fields; it is not silently removed. For non-fleet cases,
there is one target and `reviewed`/`reviewed_scope` are null rather than invented
historical metadata. Original intent/generation remain in `case` when retained.

Fleet catalog cases also report `predecessor_evidence_state` and
`predecessor_count`: malformed references are inconsistent/unknown, not zero.
Each fleet detail target has a separate `predecessor` object. `retained` exposes
the captured ADD's original outcome and request count; `not_captured` means that
member did not have a captured ADD, `not_retained` means its referenced job is
missing, and `inconsistent` means retained job identity/action does not match.
The cleanup's REMOVE/ATTENTION status is never substituted for the ADD outcome.
Validate all captured references against the full scope before any detail page;
malformed reference structure refuses detail. A predecessor outcome change also
invalidates the detail digest.

Queue pruning now retains UNVERIFIED jobs and captured predecessors of
WAITING_ADD/ADMITTING/ATTENTION cleanup beyond the configured retention window,
with linked requests/batches. Already-pruned historical evidence is not recreated.
These holds can grow storage; no automatic closure/archive was introduced, and
normal audit-event retention remains separate.

For page 2 use the **detail view's own** digest:

```bash
ftd-shun-managed-maintenance attention-case \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --case-id fleet_cleanup:UUID_FROM_CATALOG \
  --page 2 --snapshot-digest DIGEST_FROM_CASE_PAGE_1
```

The digest binds both case identity and retained state. Catalog digests and
digests for another case are rejected. Changes require starting again at detail
page 1, not rebasing the remaining pages. Missing/non-attention cases and pages
beyond the retained scope refuse explicitly. The entire fleet scope is validated
before page 1: malformed metadata anywhere or a mismatched root/count refuses
detail, while the catalog still labels the scope inconsistent. Nothing is
resolved, retried, retired, initialized or fetched from FTD. No backup, migration
or rollback procedure is needed for this read-only command; retain existing
backups and do not restore an older DB merely to obtain a matching digest.

## What to do next

The separate [Incident Isolation](incident-isolation.md) workflow adds a reviewed
whole-scope exclusion decision and distinct healthy-policy resume. Inspection
shows `isolation` and `incident_isolated` without hiding original attention or
declaring a write verified. Each ordinary uncertain predecessor needs its own
decision; a group receipt is not an exception for its independent ADD case.

The separate [Incident Acknowledgments](incident-acknowledgements.md) workflow
records operator review of ordinary UNVERIFIED and single/fleet ATTENTION cases.
Its optional ledger requires explicit offline migration. Catalog/detail shows
`acknowledgment` separately; `acknowledged_case_count` counts current cases with
a receipt and `retained_acknowledgement_count` includes historical receipts.
Unavailable ledger counts are null. Original counts, outcomes, evidence holds
and resume blockers remain unchanged. The report never creates a decision and
`resolution_available` remains false. Restoration abandonment remains separate.

Do not delete an attempt, edit an outcome, drop a trigger, replay an old ADD,
rekey a failed request or restore old enabled policy to make the report empty.
Existing [policy retirement and waiting cancellation](managed-controls.md) remain
separate revocation controls; neither resolves an uncertain write. Existing
[offline suspension](recovery.md) stops future execution and preserves uncertainty.
[Reviewed policy resume](managed-maintenance.md) still refuses unresolved latches.
The separate [Unrelated Policy Resume](managed-unrelated-resume.md) command can
resume other enabled targets after validating every closed restoration pair;
this inspector neither performs that review nor authorizes resume.

Separate [Offline Incident Abandonment](managed-abandonment.md) now implements
the first revocation-only step for one restoration incident, with its own explicit
ledger migration, backup, five-minute review, original UUID and typed IPv4.
The report shows a separate `abandonment` decision/close time and
`abandoned_case_count`, retaining the original case/outcome/latch. It is not
verification or permission to retry/resume. Ordinary/fleet incidents remain
unsupported by that single-pair action. No actual lab activation is implied.

The remaining resolution design is **planned, not implemented or authorized**:

1. Prepare an exact incident/pair/intent-generation review with original evidence,
   fresh observation separately identified and a reasoned operator decision.
2. Build on explicit **abandon maintenance**, which retains a durable decision
   separately from the unchanged FAILED/UNVERIFIED outcome. Unrelated healthy
   policy now has a separate reviewed offline resume with exact isolation checks;
   extending decisions to ordinary/fleet incidents still requires design.
3. Treat later new authorization/rearm as a different explicit review, never an
   automatic side effect of acknowledging an incident. Preserve original keys,
   unknown outcomes, protection priority and whole-fleet scope.
4. Specify retention/restore/replay, stopped/RUNNING predecessors, audit rollback
   and new-generation races before exposing any executable resolution action.

This inspector introduces no outcome reset/rearm, HTTP resolution, resume action
or live fixture. The optional abandonment ledger is distinct from device verification.

## Validation and rollout

`tests/test_managed_attention.py` uses disposable SQLite only: optional absence/
partial/capacity, read-only connection/no audit/no initialization, ordinary and
restoration evidence/deduplication/pruning, historical generations, inconsistent
jobs/scopes, bounded fleet samples, independent pending work, 205-case pagination,
complete 205-target detail pagination, original/current metadata, missing devices,
cross-case/catalog digest refusal, invalid targets outside page 1, snapshot
changes, strict arguments and missing-file/CLI behavior. Existing
maintenance/recovery/source/queue suites remain required. No Rust/protocol,
runtime schema, Compose or Web assets change; no service restart or lab state
operation is needed for this offline-only source/package increment. This is not
live recovery, uncertainty resolution or production acceptance.
