# Nonempty Legacy Transition Inspection

## Status

Policy update, 2026-10-30: this remains an optional inspection utility, **not a
release prerequisite**. The operator chose clean separate dev profiles with old
test data archived instead of a mandatory legacy converter. See
[Lab-First Development](development.md#lab-first-development-policy). The tool's
read-only behavior and lack of apply authority are unchanged.

Implemented read-only engineering preflight for the planned legacy-to-fenced-v2
conversion. **No converter/apply command exists.** Nothing was run against the
lab; its retained experiment, original keys and ordinary legacy operation remain
unchanged. This manual is not migration, fixture or activation authorization.

The [configured observation runtime](configured-runtime.md) needs an already
prepared exact profile. Startup cannot convert a retained legacy database.
This tool inventories the data a future reviewed converter must preserve instead
of deleting the database or treating old receipts as new standing consent.

## Supported source and scope

The first inspection profile requires the exact current base/queue schema and
all seven legacy managed tables. The exact optional non-authoritative import-
preparation journal may also be present. Schema contracts are generated **in
memory** from trusted repository code; the source never runs Store initialization.

Missing/partial/changed/older-unrecognized schema, extra objects, v2/fenced state
and incident/closure/isolation/acknowledgment extensions refuse. An empty ledger
does not make an unsupported extension disposable. Never drop triggers, tables,
decisions or evidence to obtain a successful inspection. Historical schema
variants need separate compatibility review, not an inferred repair.

The candidate first conversion is **retired-only**: enabled legacy maintenance
is a blocker, never silently retired. Existing observations, old one-time imports,
drafts and history must not become standing authority. All enabled and disabled
device IDs must match credential-free public inventory, with 1–10 total and at
least one enabled device. IPv4/TCP22 remains the transport profile; credentials
are still [agent-owned](per-device-credentials.md).

## Run only on an approved offline source/copy

Stop owning services, drain operations and independently establish that no old
RPC can still execute. `--confirm-offline` is the operator's assertion, not a
network/device probe. Use explicit absolute paths to reviewed files:

```bash
python3 -m ftd_shun_manager.migration_inspection \
  --database /approved/offline/state.db \
  --inventory /approved/public/devices.json \
  --concurrency 1 \
  --confirm-offline
```

After package installation the equivalent entrypoint is
`ftd-shun-migration-inspection`. No `.env` or live configuration is loaded. The
only input file besides SQLite is public inventory; never supply the agent's
credential mapping. Database and inventory must be regular files, not final
symlinks/FIFOs/directories. Public inventory retains its 256 KiB limit.

`--concurrency` is a literal 1–10 future-profile parameter, default **1**, not an
agent setting or capacity probe. The planned sealed scope contains enabled IDs;
disabled IDs remain retained database identities. A different concurrency or any
public metadata, interface/profile or host-key change alters the inspection digest.
Nothing changes agent/API execution or their declared capacity.

## Read-only snapshot and manifest

The source opens with SQLite `mode=ro`, `query_only=ON` and one read transaction.
No DDL, audit, pause, retirement, expiry, pruning, optional initialization,
credential/socket/HTTP/SSH access or backup creation occurs. Missing database
paths are not created. Normal SQLite WAL/shared-memory access is still needed;
this is not an immutable forensic file/sidecar reader. Never use `immutable=1`
to ignore an active WAL and manufacture an older snapshot.

The source digest covers complete schema, encoding/journal mode/user-version/
application-ID metadata and **every retained table row**, including sequence
state, original request payload/results, actors, queue TTLs/links, attempts,
retired policy, observations/occurrences/import attribution, protection and audit.
Values are type-tagged and length-framed under a versioned domain; same counts
with different content do not compare equal. Rows stream in batches of at most
100, rather than loading the whole history into Python. This is a logical-state
fingerprint, not a hash of physical database pages or a cryptographic signature.

The report prints table counts/digests, fixed state summaries, source metadata,
planned device IDs/concurrency, blocker codes and timestamps. It does **not** print
raw IP lists, host keys, actor names, comments, request payloads or device output.
Keep reports private nonetheless: they describe local operational state.

## Interpret the result honestly

| Field | Meaning |
| --- | --- |
| `source_digest` | Complete retained source snapshot, not only enabled/active rows. |
| `inventory_digest` | Complete canonical public configuration, including disabled IDs and pins. |
| `inspection_digest` | Versioned snapshot/configuration/time binding, not authorization. |
| `operational_preconditions_satisfied` | No listed operational blocker in this snapshot; not full semantic-conversion validation. |
| `semantic_conversion_validated=false` | Archive/receipt/key-reservation compatibility is not implemented or proved. |
| `migration_available=false`, `migration_ready=false` | Always false in this increment, even with zero blockers. |
| `terminal_attempts_without_queue_evidence` | Honest missing older terminal job evidence; no result is reconstructed or upgraded. |

Operational blockers include unpaused ordinary/desired execution, any global lease
(even expired), future cooldown, unfinished protection import, enabled legacy
policy, pending jobs, UNVERIFIED/read-reconciled jobs, pending/failed/unknown
restoration, unfinished/attention single/fleet cleanup and mismatched retained
device identity/trust. Integrity failures or unsupported schema return no partial
report and exit 2. Blocked but successfully inspected sources return a report/exit
0: **exit 0 is not migration approval**.

Counts/integrity/schema checks are not a validator for every original authority,
receipt or cleanup payload. That semantic/archive validation and retained original-
key exclusion across namespaces must precede any future converter. A verified
historical ADD remains historical evidence, not permission to re-enable its policy.
FAILED/UNVERIFIED attempts and missing old queue records keep their exact meanings.

## Reinspect without rebasing

Within five minutes, pass both exact original fields along with the same paths
and requested concurrency:

```bash
python3 -m ftd_shun_manager.migration_inspection \
  --database /approved/offline/state.db \
  --inventory /approved/public/devices.json \
  --concurrency 1 --confirm-offline \
  --reviewed-at ORIGINAL_REVIEWED_AT \
  --inspection-digest ORIGINAL_INSPECTION_DIGEST
```

Future/expired timestamps, changed schema/data/header metadata/configuration or
inventory changes during reading refuse, never silently rebase. Whitespace,
entry ordering and interface ordering alone are equivalent. A reader sees one
consistent SQLite snapshot even if another writer violates the offline assertion;
inspection cannot prevent later commits or attest remote quiescence. The digest
is not a reservation, policy key, backup, apply token or resume permission, and
existing maintenance apply/resume commands do not accept it as their review.

## Backup, migration and rollback boundaries

No source schema or data changes, so this increment needs no DB restore. Package/
code rollback removes this optional CLI only; leave retained data untouched.

Before an eventual separately approved conversion, require a checked SQLite-safe
private backup and matching code/configuration, not a copy of a live main file
without WAL. Review a bounded source profile, archive visibility, original-key
reservation, retired generations and every uncertainty/cleanup exclusion.
Preserve all original rows/outcomes/TTL/authorship and audit actual migration with
a trusted-host maintenance actor; never forge a Web actor or rewrite receipts.
Require atomic failure rollback and independent post-conversion compatibility
checks while ADD/restoration/admission remain disabled. None of that is performed
by inspection. Fenced storage cannot be downgraded by renaming its registry or
restoring old enabled authority to make legacy code start.

## Validation

```bash
python3 -m pytest -q tests/test_migration_inspection.py tests/test_managed_maintenance.py tests/test_configured_runtime.py
```

Disposable fixtures cover nonempty retired policy, actual shared-queue verified/
no-op/failed/unknown attempts before/after retention, absent evidence, cleanup
holds, schema/foreign-key damage, committed WAL reads, bounded batches, typed
hashing, same-count/header/configuration drift, exact reinspection/expiry,
disabled identity preservation, no source initialization/write and sanitized CLI
refusal/no apply. They do not establish real-device migration or load acceptance.
