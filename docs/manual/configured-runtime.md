# Configured Continuous Observation Runtime

## Status and boundaries

Policy update, 2026-10-30: ordinary bounded work on the known desk lab follows
[Lab-First Development](development.md#lab-first-development-policy), not repeated
per-fixture approvals. Use an explicitly prepared clean separate profile while
archiving the old dev store; a legacy converter is not required. This does not
change the implemented observation-only scope or bypass its compatibility checks.

Implemented process configuration on **already prepared** version-2 fenced
storage. Not enabled in the lab. This is not a migration/activation runbook,
general managed-import release or production acceptance. The legacy lab database
and its retained managed lifecycle evidence cannot be converted by startup.

This increment supplies three pieces: explicit runtime selection, immutable
public-inventory assertions, and a non-executing CLI check. It uses the existing
[restricted composition](continuous-api.md), [dispatcher](continuous-dispatch.md)
and [maintenance owner](continuous-maintenance.md), not another executor.

## Configuration

| Setting | Meaning |
| --- | --- |
| `FTD_SHUN_API_RUNTIME=legacy` | Default; existing serial startup, which refuses fenced storage. |
| `FTD_SHUN_API_RUNTIME=continuous-observation` | Explicit restricted continuous startup; existing exact profile only, no automatic fallback or initialization. |
| `FTD_SHUN_DEVICE_INVENTORY` | API-side mounted public JSON file. Compose maps host `FTD_SHUN_DEVICE_INVENTORY_PATH` to this mount. Required for configured continuous mode. |
| `FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES` | Canonical integer 1–10, default 1. Declares the real agent's capacity; it must cover the existing sealed profile's concurrency. Changing this alone does not expand that immutable profile. |

Socket mode, cycles, large snapshots and development authentication **off** are
required. Existing API import admission/execution, legacy managed policy/removal
admission, restoration and cleanup-worker settings must remain false. The strict
Unix client always has settled cycles, large reads and an explicit empty ADD
scope. There is no negotiation/downgrade to old agents or ordinary BEGIN.

The baseline/manual spacing, operation deadline (+5s IPC margin) and history
retention come from existing Settings. All API/Web v2 admission capabilities,
ordered promotion and bulk execution remain default-off; this selector cannot
enable them. Explicit developer dispatcher/client injection cannot be combined
with configured selection. Synthetic injection remains a test-only factory path.

## Public inventory and stable identity

Files are credential-free UTF-8 JSON, at most 256 KiB, regular and not final
symlinks/FIFOs/directories. Duplicate fields, IDs, hostnames or management IPv4s,
unsafe interfaces, control characters, credential/unknown fields and malformed
values refuse. Credentials remain in the [agent-owned mapping](per-device-credentials.md).
DNS/custom ports are still future work; this implementation uses IPv4/TCP22.

Configured continuous mode accepts 1–10 **total** devices, including disabled
ones. Every database device must match an inventory entry by immutable ID,
hostname, address, enabled state and exact pinned host-key text. Missing disabled
IDs are not discarded as history. New/changed addresses or keys refuse rather
than upsert, erase evidence or silently trust a replacement. Addition profiles
are metadata, never authority or executable ADD scope.

Composition freezes all semantic fields, including sorted interface allowlists
and addition profiles. Lifespan startup rechecks both the file and retained DB
projection before any maintenance/device task starts. JSON whitespace, entry
order and interface order alone are harmless. There is no hot reload, connection-
metadata migration or file watcher after startup. Keep API/agent on the same
reviewed public file and recreate them together for separately reviewed changes;
the API cannot attest what an already-running agent previously loaded.

## Non-executing preflight

Only on an approved, prepared profile, using its explicit environment (the command
does not load `.env` itself):

```bash
ftd-shun-api --check
```

With the continuous selector this composes and validates the real configuration,
then reports `api.runtime.checked`, `execution_started=false` and
`migration_performed=false`, without Uvicorn, lifespan/maintenance, socket calls,
HTTP, SSH, credentials or audit changes. It does not print inventory/host keys.
The check uses normal SQLite connections and may access WAL sidecars; it is not
a byte-for-byte forensic file reader or a lock on later state. Repeat validation
at actual start; a successful check is not a reservation or a transport probe.

Configured connections use SQLite `mode=rw`, never its file-creating default;
even removal of the file between existence checking and opening cannot create a
replacement empty DB. Supplied Store dependencies contribute only their path in
this configured mode; the API and dispatcher share the non-creating Store.

With legacy selected, `--check` refuses **before** legacy initialization. Missing,
partial, legacy or mismatched storage likewise refuses; no empty DB/directories,
optional tables, environment protection import, backfill, resume or repair are
created. Old uncertainty/receipts and policy remain untouched. Check failure must
not be worked around by dropping tables, clearing fences or reusing an ID.

## Start, stop and operational impact

Ordinary `ftd-shun-api` starts the selected lifecycle after repeating preflight.
Run exactly one owning API process, not multiple Uvicorn workers/replicas or a
second legacy scheduler. The API remains private UDS behind the existing BFF;
Caddy stays the sole external listener. No port/network/authentication changes.

The name **observation** is not a no-write guarantee: existing admitted REMOVE
jobs and automatic Protected-IP removals may execute. Enabling protection may
permanently retire matching managed authority. One maintenance owner expires
requests/prunes evidence-aware history at its established cadence. Startup never
grants/resumes maintenance or enables ADD. Preserve all existing independent
pause, uncertainty and feature-specific controls.

Normal shutdown drains current operations and local settlement; do not cancel
threads and assume remote work stopped. Runtime selection cannot resolve old
unknown work. Real agent settlement/capacity, traffic, simultaneous-device,
large-load and recovery acceptance remain pending.

## Migration, backup and rollback

No DDL is added and **no live migration is performed**. Before any separately
approved transition, stop/drain old owners and establish remote quiescence, retain
a verified SQLite-safe backup (including retained authority/evidence), matching
images/configuration, and private copies of public inventory plus agent-owned
credentials. Do not copy only a live main DB file while ignoring WAL.

Nonempty legacy conversion is optional/deferred, not a prerequisite for development.
An explicitly initialized clean DB in a separate path/volume is the preferred lab
route; archive the old test store rather than overwriting it or inferring new
authority from its records. Address/trust changes still need deliberate handling.
The separate [transition inspection](migration-inspection.md) now inventories a
recognized nonempty legacy source and its blockers without converting it or
authorizing startup. A successful inspection is not a prepared fenced profile.

Rollback on fenced storage requires a matching fenced-compatible image/configuration
and drained lifecycle. Switching to `legacy` deliberately refuses; never drop
fences, requeue unknown jobs, erase receipts, reenable retired policy or restore
an older authority snapshot to force compatibility. No lab services/settings,
inventory, credentials or FTD state changed for this increment.

## Validation

```bash
python3 -m pytest -q tests/test_configured_runtime.py tests/test_inventory.py tests/test_config.py tests/test_continuous_api.py
```

Disposable synthetic profiles cover no-init/no-connect construction/GET/check,
missing/nonempty incompatible profiles, mixed gates/injection, full public identity
and disabled IDs, startup drift, semantic ordering and single-owner lifecycle
drain. A semantic fake is substituted only at the test RPC boundary; these tests
are not live SSH/FTD/settlement acceptance.
