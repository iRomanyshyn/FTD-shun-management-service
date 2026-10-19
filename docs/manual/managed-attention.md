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

## What to do next

Do not delete an attempt, edit an outcome, drop a trigger, replay an old ADD,
rekey a failed request or restore old enabled policy to make the report empty.
Existing [policy retirement and waiting cancellation](managed-controls.md) remain
separate revocation controls; neither resolves an uncertain write. Existing
[offline suspension](recovery.md) stops future execution and preserves uncertainty.
[Reviewed policy resume](managed-maintenance.md) still refuses unresolved latches.

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
   separately from the unchanged FAILED/UNVERIFIED outcome. Decide how
   unrelated healthy policy can resume without releasing that pair's latch.
3. Treat later new authorization/rearm as a different explicit review, never an
   automatic side effect of acknowledging an incident. Preserve original keys,
   unknown outcomes, protection priority and whole-fleet scope.
4. Specify retention/restore/replay, stopped/RUNNING predecessors, audit rollback
   and new-generation races before exposing any executable resolution action.

No outcome reset/rearm, HTTP resolution, resume exception or live fixture is
introduced. The optional abandonment ledger is distinct from device verification.

## Validation and rollout

`tests/test_managed_attention.py` uses disposable SQLite only: optional absence/
partial/capacity, read-only connection/no audit/no initialization, ordinary and
restoration evidence/deduplication/pruning, historical generations, inconsistent
jobs/scopes, bounded fleet samples, independent pending work, 205-case pagination,
snapshot changes, strict arguments and missing-file/CLI behavior. Existing
maintenance/recovery/source/queue suites remain required. No Rust/protocol,
runtime schema, Compose or Web assets change; no service restart or lab state
operation is needed for this offline-only source/package increment. This is not
live recovery, uncertainty resolution or production acceptance.
