# Import Admission — Staging Only

## Current boundary

This increment implements durable intentions and provenance, not executable
imports. `FTD_SHUN_IMPORT_ADMISSION_ENABLED=false` is a strict API-side default.
Setting it true permits **staging only** on the private API Unix socket. It does
not select cycle v3, enable the agent, create a device profile or dispatch ADD.
Keep it false in the current lab. There is no Web/BFF submit route or Queue
import button; [Import preview](import-preview.md) remains non-executable.

With execution disabled the leased scheduler selects REMOVE only. Held ADD rows do not
request extra device cycles. Queue metadata labels them **Held — ADD execution
disabled**; owners/Administrators can cancel them under existing role rules.
Unstarted authorization expires normally rather than waiting indefinitely for
a future release. `202 Accepted` means staged, never created on FTD.

The separate [queued execution](import-execution.md) increment integrates domain
claim/completion hooks with the same worker behind an independent default-off
API gate and explicit device capability. The HTTP handler never calls them. The existing
[agent ADD gate](addition-contract.md) remains separate and disabled. No mock
or synthetic completion is evidence of a real FTD operation.

## Private API contract

`POST /api/v1/imports` requires an explicit UUID `Idempotency-Key` and these
typed fields; unknown top-level/target fields are rejected:

| Field | Meaning |
| --- | --- |
| `actor` | Trusted BFF identity: subject, display name, captured roles. Operator/Administrator required; blank subject refused. |
| `targets` | 1–1000 distinct `{device_id, ip}` pairs; strict integer IDs 1–65535 and exact IPv4 addresses. |
| `policy_revision` | Non-negative revision of the reviewed Protected IP configuration. |
| `label`, `reason` | Optional plain-text batch metadata, at most 100/500 characters; escaped on output, never executable. |
| `confirmation_digest` | Lowercase SHA-256 of canonical intent, binding scope/action, sorted targets, policy revision and normalized label/reason. |

Use `canonical_import` in `import_intent.py` for deterministic canonicalization
and digest construction. The hash is an integrity/confirmation binding, not a
signed capability, user authentication or fresh browser confirmation. Raw paste,
source lines, CLI/context/interface, URLs and session credentials are not part
of the contract or persisted source. Label/reason are retained batch data; do
not put secrets in them. Structured logs omit them and the canonical payload.

The API is private and trusts its BFF caller, as with removal admission. Do not
publish it or send browser-supplied actor JSON through a future BFF route.
Future browser submission must derive identity from Caddy/Authelia, validate
CSRF and require fresh explicit confirmation of the canonical scope.

Admission is one transaction: recheck enabled devices, current policy revision,
enabled Protected IP exclusion, capacity/rate limits and conflicting jobs.
Enabled protection refuses the entire batch; a disabled policy entry is not
an exclusion. Enabling protection later fails matching unstarted ADD jobs
before policy removal may be generated. Other batch targets remain unchanged.

Same-action QUEUED/RUNNING device/IP requests share one job, with distinct
immutable actor/batch records and audit for every requester. An opposite
ADD/REMOVE intention rejects the entire request with `409`, without partial
jobs, events or accepted logs. A retry with the same key/actor/canonical intent
returns its original reference, even after completion or expiry. Different
intent/actor under that key returns `409`; replay never renews authorization.

Other responses are `403` for insufficient roles, `503` for disabled admission
or agent mode, `422` for invalid input/confirmation/key, and `429` for capacity
or rate limits. Existing limits are unchanged: 1000 unfinished jobs, 2000 active
requests, 10 new submissions per actor per minute, and authorization for at most
15 minutes (or the shorter sensitive-action age). Overflow is atomic; no silent
truncation or implicit chunking. Previewing 7,307 addresses does not authorize
that many jobs or promise completion before expiry. Large-list execution needs
separate bounded scheduling/explicit reauthorization design and live evidence.

## Occurrence provenance and audit

Immutable `manual_import_batches` stores source `manual_import`, actor/roles,
canonical targets, label/reason, policy revision and admission time. Its ID is
the parent request/batch UUID. Each `operation_jobs` row has immutable `action`.
For downgrade compatibility, `operation_requests` retains its original nine
columns and source CHECK: an import base request has source `manual`, while
batch metadata, API queue views, events and logs expose `manual_import`.

Only the gated worker's exact typed verified-add result may atomically write a
new current occurrence, origin rows, terminal job and `SHUN_ADDED_BY_IMPORT`
events for the coalesced actors. Provenance is per device/IP/interface/current
occurrence, not lifetime ownership. A conflicting local active row becomes
UNVERIFIED without relabelling it. Pre-existing/no-op, failed or uncertain jobs
cannot assign origin; later snapshots cannot promote uncertainty to creation.
Lease recovery settles abandoned ADD as UNVERIFIED without replay. Explicit
pre-write deferral is the sole requeue case and clears the dispatch marker.

Continuous observations preserve occurrence and origin. Removal/disappearance
followed by later external reappearance creates a new occurrence without the
**Manually imported** badge. Restart, idempotent retry and later no-op cannot
regenerate a completed import or overwrite an existing origin. This is a
one-time manual addition, not a feed, enforced blacklist or exclusive ownership
claim against administrators writing outside the service.

Active list/detail API rows expose `manual_imports` (one representative batch)
and `manual_import_count` (all verified batch requests for that occurrence).
The badge is blue; details show escaped actor/label/reason and local verified
time with timezone. All origin rows remain stored and request-level audit is
available under normal retention. One representative is not the sole creator.
Batch payloads are decoded once per distinct batch, not once per actor/row;
queue metadata never repeats full canonical lists.

Events add `SHUN_ADD_REQUESTED`, `SHUN_ADD_NOOP`, `SHUN_ADD_FAILED`,
`SHUN_ADDED_BY_IMPORT` and action/source in `SHUN_OPERATION_*`. JSON logs retain
batch request ID, job ID, actor/target and effective source; future completion
uses `queue.addition.completed`/`.deferred`. Accepted logs appear only after
transaction commit. No pasted text or Cisco output is logged.

Active occurrence origins and their immutable batches survive queue-record
pruning. Inactive origins expire by verification time under configured history
retention; unreferenced old batches are then eligible for removal. A retained
active badge does not extend retention of all old audit events. No foreign key
to prunable jobs is used for origins; batch/device relationships are retained.

## Migration, deployment and rollback

Take a checked SQLite-safe backup (SQLite backup API, not a bare copy of a live
WAL database), protect it as 0600 in an ignored private directory, and preserve
the prior API/Web images. API startup applies additive migration:

1. Create immutable batch/origin tables and indexes.
2. Add/backfill opaque `shun_state.occurrence_id` without changing timestamps.
3. Add job `action` defaulting to REMOVE for all existing jobs, and nullable
   `dispatch_kind`; preserve IDs, states and dates.
4. Install immutable-action/metadata and legacy-safe claim/occurrence triggers.

Initialization is repeatable. No queued removal, existing policy, state or
history is reset; no existing shun receives manual provenance. Stop the API
executor cleanly, ensure no previous RPC is still executing, and upgrade
API/Web together. Agent, Caddy and Authelia need no rebuild for this increment.
Starting API may execute existing removals/policy. Keep real inventory unchanged,
both import admission and ADD execution disabled, and do not submit test work.

Read-only checks: SQLite quick_check and foreign_key_check, migrated columns,
unchanged policy/queue aggregates, successful ordinary v1/v2 baseline, admission
and execution flags false, no configured addition profile, anonymous Web 401 and
TLS-verified redirect to Authelia. Do not spoof identity headers against the
live Web, force refresh, run an independent agent read or create live jobs just
to test deployment. Authenticated visual checks remain an operator task.

For rollback, stop API/Web and ensure no in-flight RPC survives. Review and
suspend **all pending work, including ADD**, using the offline maintenance SQL
in [Operation Queue](operation-queue.md#backup-restore-and-rollback), then restore
the preceding API/Web pair. This cancels QUEUED work and marks RUNNING work
UNVERIFIED. Keep additive tables/columns/triggers and false/absent new flags;
do not drop provenance or restore an older state file just to revert code.

The legacy-claim trigger aborts a worker trying to claim ADD without the
explicit ADD marker; it prevents ADD-as-REMOVE but is not an operational
downgrade strategy. Older workers do not understand pending additions and may
fail or misreport them. Occurrence triggers also protect external reappearance
when an older state writer ignores the new column. Old nine-value removal
request inserts remain compatible. Database restoration still requires the
queue suspension/review procedure: never replay work from an old backup.
