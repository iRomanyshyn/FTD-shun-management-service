# Acknowledging Unresolved Incidents

## Meaning

`ACKNOWLEDGE_UNRESOLVED` records that a trusted-host operator inspected an
ordinary UNVERIFIED ADD/REMOVE or a single/fleet ATTENTION cleanup and supplied
a reason. It creates an immutable administrative receipt. The attention report
keeps the original case, outcome and counts, and shows the acknowledgment
separately. This helps distinguish reviewed incidents from cases awaiting review.

The decision leaves queue work, policy, cleanup reservations, evidence holds and
resume blockers intact. It does not verify a device write or permit a retry,
release an uncertain pair, retire policy or resume execution. A fleet receipt
covers its entire original scope in one transaction. Missing current inventory
members remain in scope. Each captured predecessor ADD keeps its own outcome;
a fleet acknowledgment does not acknowledge an independently listed operation.
Restoration cases use [Incident Abandonment](managed-abandonment.md) instead.

There is no HTTP/Web action. The CLI is
`ftd-shun-incident-maintenance`; the module form is
`python3 -m ftd_shun_manager.incident_acknowledgements`. It reads no environment,
inventory file, SSH secret or agent socket. Building/deploying the package does
not authorize migration or acknowledgment on the lab database.

The separate [Incident Isolation](incident-isolation.md) workflow can retire and
exclude the whole acknowledged scope through an additional reviewed decision.
Its distinct migration/isolate actions and healthy-policy resume never follow
automatically from acknowledgment; original device outcomes remain unchanged.

## Offline prerequisites

Follow [Offline Recovery](recovery.md): stop the sole API/Web pair, prevent
automatic restart, settle all old agent RPCs (stop the agent if necessary), and
suspend ordinary mutations and existing desired restoration. An expired lease
does not prove remote settlement. `--confirm-offline` asserts these operator
responsibilities. No pending job, managed handoff/restoration, lease or incomplete
fleet admission may remain. Other terminal attention cases may remain.

Use the database owner's UID, current matched software and the existing absolute
database/WAL path. Review commands open the existing file read-only; a missing
database is never created. Output contains private addresses, device names and
authority IDs; keep it private. Raw device errors/CLI, comments, labels, complete
admission payloads and credentials are excluded. Typed operator reasons are
retained in the decision and audit.

Write commands create a new exclusive 0600 SQLite-API backup in an operator-owned
0700 directory. They check integrity/foreign keys and refuse concurrent commits.
Use a new backup filename for each attempt, including receipt replay. A failed
command retains any created backup. Paths below are illustrative.

## Explicit empty-ledger migration

This optional ledger works with an ordinary-only current queue or an exact
recognized managed schema. It does not initialize managed policy. Startup, Store/
queue initialization, GET/reporting and managed/closure migrations never create it.

```bash
ftd-shun-incident-maintenance review-enable \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

Inspect `ready`/`blockers`. Within five minutes, confirm using the returned
timestamp/digest:

```bash
ftd-shun-incident-maintenance enable \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-ack-ledger.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

One transaction creates `incident_acknowledgements`, its immutable-update and
retained-delete triggers, and `INCIDENT_ACKNOWLEDGEMENTS_INITIALIZED` audit.
No existing case is adopted. Partial/changed DDL refuses instead of being repaired.
The ledger retains at most 10000 decisions; there is no automatic archive/recycling.
Existing seven/eight-table managed schemas remain unchanged and recognized.

## Review the original incident

Use [Attention Inspection](managed-attention.md) to inspect the original
`operation:UUID`, `device_cleanup:UUID` or `fleet_cleanup:UUID`. For a fleet,
inspect every detail page using its snapshot digest. That digest is a read
consistency check and cannot authorize acknowledgment.

```bash
ftd-shun-incident-maintenance review \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --case-id fleet_cleanup:ORIGINAL_ROOT_UUID \
  --reason "Reviewed the complete cleanup incident; retain uncertainty"
```

Review returns an original request UUID, five-minute expiry, confirmation digest
and bounded evidence for **all** original targets (at most 1000). It gathers every
100-target detail page inside the same read transaction and validates the entire
scope/reference list. Original reviewed device/intent metadata stays separate
from today's inventory/policy/cache context. Missing historical jobs are explicit;
inconsistent or unfinished related jobs refuse. Cached presence is not verification.

The review binds schema, retained cases, queue/request/link identity and state,
observations, protection, optional managed policy, full target/predecessor evidence,
original UUID, maintenance actor and normalized printable reason (1–500 characters).
Changing any bound state requires a fresh deliberate review. Another case's or a
catalog digest is not accepted. Preserve the original request after an unknown reply.

## Confirm and retain the receipt

Type the exact reviewed IPv4 **and entire target count** (1 for a single case):

```bash
ftd-shun-incident-maintenance acknowledge \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-acknowledgment.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --case-id fleet_cleanup:ORIGINAL_ROOT_UUID \
  --reason "Reviewed the complete cleanup incident; retain uncertainty" \
  --request-id REQUEST_UUID_FROM_REVIEW \
  --confirm-ip EXACT_REVIEWED_IPV4 --confirm-target-count ENTIRE_REVIEWED_COUNT \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

The single transaction stores sanitized evidence, original request, receipt and
`INCIDENT_ACKNOWLEDGED` audit. Audit uses `maintenance:<label>` and empty roles;
no Web/directory identity is synthesized. A late expiry or audit failure rolls
back the decision even if an internal caller catches the exception and commits.
Concurrent confirmations create one receipt and one audit event. Different
inputs under an existing key refuse; a second key cannot acknowledge the same case.

Retrying the exact original request returns `replayed=true` with its historical
receipt, even after expiry or later absence reconciliation. It changes no current
controls or state. Keep the original request/body/reason/actor; do not generate a
new key to guess whether a prior write committed. Decision keys remain reserved
against device-work and policy/cleanup/restoration/abandonment authority.

## Reading status and retaining evidence

Attention catalog/detail adds `acknowledgment` beside the original case. Its
decision UUID/time, original outcome and `controls_unchanged=true` describe only
operator review. `acknowledged_case_count` counts currently retained matching
attention cases; `retained_acknowledgement_count` also includes historical receipts
whose REMOVE was subsequently reconciled absent. Uninitialized ledger counts
are `null`. Original case counts and `resolution_available=false` are unchanged.

Automatic queue retention still preserves UNVERIFIED jobs and captured predecessors
of WAITING_ADD/ADMITTING/ATTENTION cleanup. Acknowledgment does not release holds.
Existing normal REMOVE absence reconciliation may produce RECONCILED_ABSENT;
the historical acknowledgment remains and never turns that into VERIFIED.
Retained decisions can grow storage beyond the configured event-history window.

## Rollback and validation

Retain checked backups and matching paired images. Never drop acknowledgment
rows/triggers or restore old policy to undo an operational decision. Older images
ignore this ledger and its reserved keys: downgrade requires a separate offline
plan and current evidence review. The backup is for recovery, not replay authority.
No lab ledger migration, decision or additional device test was performed for
this implementation; the existing one-address authorizations remain consumed.

`tests/test_incident_acknowledgements.py` covers ordinary/single/fleet receipts,
205-target scope, missing/invalid evidence, read-only/no-startup initialization,
state/actor/typed-scope conflicts, expiry, concurrent original-key replay, atomic
audit rollback, checked CLI backups, immutable retention and unchanged resume
blockers. Executable uncertainty resolution, isolation of ordinary/fleet incidents,
Web acknowledgment and live recovery acceptance remain separate work.
