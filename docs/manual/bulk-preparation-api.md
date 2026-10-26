# Version-2 Durable Import Preparation API

Status: implemented on the explicit compatible continuous API composition with
existing exact v2/fenced storage and the existing optional preparation journal.
**Not initialized, migrated, enabled or deployed in the lab.** This packet exposes
non-authoritative drafts and proposal inspection, not standing confirmation,
adoption, queue work or device execution. A separate
[Web workspace](bulk-preparation-web.md) now connects drafts/reports/pure proposals
and draft revocation; no standing confirmation or runtime selector is supplied.
Read [Durable Preparations](managed-import-preparations.md),
[Bulk Format](bulk-import-capacity.md), [Bulk Policy Storage](bulk-policy-storage.md)
and [Continuous API](continuous-api.md) first.

## Scope and authority

`BulkPreparationReports` uses the existing bulk-profile preparation classifier,
journal, owner boundaries and shared queue UTC clock. No parallel authority store,
new DDL or executor is introduced. Constructor, startup and every route refuse
missing/malformed prerequisites instead of initializing, repairing, pruning or
falling back to the legacy registry. The owner list alone may report an absent
journal as explicitly `initialized=false` with no writes.

Status advertises `bulk_import_preparation_available=true` as support for this
interface, **not journal readiness or policy/execution permission**. Inspect the
owner-list initialization result before creating a draft. General managed/manual
workflows and ADD/import admission/execution remain unavailable in this runtime.
No extra execution gate is needed for a harmless draft, and none is enabled.

All responses are `Cache-Control: no-store`; private Unix-socket and trusted BFF
actor boundaries remain unchanged. Actor fields must be supplied by trusted
composition, never treated as a public authentication mechanism. Credentials and
host-key material remain exclusively agent-owned.

## Fixed private routes

| Route, all POST | Meaning |
| --- | --- |
| `/api/v2/managed-imports/prepare` | 201: one durable local unconfirmed draft, not a policy or device receipt. |
| `/api/v2/managed-imports/preparations` | 200: recover at most four references owned by the current subject. |
| `/api/v2/managed-imports/preparation` | 200: one frozen page, at most 100 targets and 100 generated diagnostic rows. |
| `/api/v2/managed-imports/proposal` | 200: verified canonical v2 descriptor/digest/manifest only, no retained root/key reservation. |
| `/api/v2/managed-imports/cancel-preparation` | 200: revoke only the owner's unconfirmed draft; repeat revocation is side-effect-free. |

POST is used for private owner-bound inspection bodies as well as draft changes;
it does not imply device mutation. No `/confirm`, confirmed-import cancellation,
free action, arbitrary CLI or caller-selected profile/capability is accepted.
Existing v1 mutation routes remain refused in this composition. Fixed v2 routes
on the normal legacy API return unavailable; they do not convert its storage.

Every request contains `actor: {subject, display_name, roles}` with bounded plain
identity, distinct supported Viewer/Operator/Administrator roles and no extra
fields. Creation and proposal require current Operator or Administrator. Any
authenticated owner can inspect/revoke their own draft, including after role
loss or during a mutation pause. Administrator is not an override for another
author's private draft. Unknown reference/wrong owner returns the same bounded
unavailable result, never another user's report.

Creation also requires `text`, one to ten distinct literal integer `device_ids`
and optional 100/500-character `label`/`reason`. Reject boolean/string IDs,
disabled/missing devices, oversized UTF-8 and unknown action/scope fields. Metadata
is intentional plain text; never place secrets there. Inspection references use
canonical preparation UUIDs; page is a literal integer in 1..1000. Proposal adds
the original `preparation_digest` and canonical `operation_id`, not a policy action
or recurring-consent flag.

## Bounds, frozen reports and integrity

Retain the parser's 1 MiB UTF-8, 20000-line and 10000-row bounds. Explicit device
selection yields a complete product up to 10000 unique IPv4 addresses × ten
devices = 100000 pairs. Never truncate to fit a legacy 1000-pair scope. Invalid,
unsupported and duplicate source diagnostics remain visible; active protection
excludes pairs. The four frozen classes remain PROPOSE_ADD, PROPOSE_ADOPT,
ALREADY_MANAGED and EXCLUDED_PROTECTED. Observed unmanaged state does not become
past service creation or maintained policy merely because a draft exists.

The journal stores generated line/status/reason diagnostics and intentional
label/reason, not original pasted text/comments/excerpts. Classification, devices,
managed/protection revisions, original author/captured roles and ten-minute expiry
stay frozen after observations, protection or current roles change. Stored roles
are historical metadata, not current authorization.

Before listing retained metadata, showing a page or cancelling a draft, verify
the entire original header/membership digest inside that operation's transaction,
streaming at most 100 members per Python chunk. Checking only counts would miss a
same-count IP/classification substitution. Corruption is unavailable (503), not a
smaller/changed successful report. The original expected preparation digest is
checked separately for proposal. Proposal also verifies the complete classified
manifest, metadata/count parity and end-of-read expiry/clock; it scans without
writing or contacting FTD. A valid hash is integrity, not freshness or consent.

Reports may honestly show PREPARED, CANCELLED, EXPIRED or CONFIRMED and the original
`confirmed_operation_id`. Response flags `can_execute=false`, `policy_saved=false`
and `device_work_admitted=false` describe **this non-authoritative operation**,
not a claim that no earlier separately authorized policy exists. Confirmed draft
revocation/proposal conflicts; original policy/receipts/jobs remain unchanged.
Expired/cancelled reports stay inspectable until separately approved pruning.

## Recovery, capacity and cancellation

Maximum four retained drafts per owner/sixteen globally, including expired or
cancelled records until explicitly pruned. Capacity failure returns 429, never
evicts another review or leaves part of a product. No automatic pruning endpoint
or startup cleanup is added; existing retention limitations remain an explicit
working-version follow-up, not a reason to erase authority/evidence.

A lost 201 reply may leave a harmless unconfirmed draft. Recover its original
reference from the owner list instead of blindly creating another. This is not
executable idempotency; no operation root or key was reserved. A repeated proposal
read with the same original operation UUID is deterministic across restart but
grants no permission. Future confirmation must recheck current actor, freshness,
scope/revisions, profiles, protection/conflicts/uncertainty and occupied keys.

Cancellation accepts only actor and original preparation UUID. It never retires
standing policy, cancels a confirmed import or interrupts ADD. If confirmation
already won the transaction race, cancellation refuses. It does not renew expiry,
re-enable maintenance or resolve uncertainty. Draft activity does not bump managed/
queue revisions or wake/hint device reads or work.

Strict invalid input returns 422; role refusal 403; wrong owner/reference,
changed/unavailable draft or closed proposal 409; retained capacity 429; missing
prerequisite, corrupt profile/integrity or database failure 503. An unknown creation
outcome is not a success/rejection proof: inspect owner references before another
create attempt. Read/report failure is never verified device success.

## Validation, migration and rollback

```bash
python3 -m pytest -q tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_managed_shuns.py tests/test_bulk_preparation_intent.py
```

Actual ASGI/private API on disposable exact profiles: mixed classifications and
diagnostics/privacy, actual actor, owner separation/restart, role-loss/pause
cancellation, unchanged policy/queue/origins/audit, strict input/UTF-8/source limits,
expiry/frozen revisions, unknown create recovery, confirmed-draft refusal,
concurrent owner/global limits, same-count corruption, late transaction rollback,
<=100-row read-only proposal streams and maximum 100000-pair API staging/pagination.
This is not FTD throughput, adoption, ADD, recovery/load or production acceptance.

No schema, deployment, secret, agent/wire, service or lab state changed. The existing
optional journal/v2/fenced profile is not initialized by this packet. Any eventual
activation/conversion requires separately scoped approval, drained old writers/
sessions, checked SQLite-safe backups and matching images/configuration under the
prerequisite manuals. Never delete the lab's retained legacy evidence to force an
empty migration. Do not roll back to an older writer that ignores v2 authority or
evidence holds. Preserve current state; a checked pre-upgrade backup is usable only
before post-backup authority/work. The separate [Web review](bulk-preparation-web.md)
does not enable independently gated atomic v2 standing confirmation or admitted-
import cancellation; those remain separate delivery.
