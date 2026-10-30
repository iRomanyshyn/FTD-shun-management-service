# Fresh Working-Version Lab

## Purpose and scope

Use this path for the current unreleased internal lab. It creates a separate
complete v2 database, not a converter/reset of the old development store. Keep
the old file/volume and matching images privately. No queues, observations,
receipts or standing authority are adopted from it.

`continuous-managed` connects the existing managed-import, adoption, restoration,
ready/ordered removal and cancellation workflows to one continuous fenced owner.
The default selector remains `legacy`. This is not production acceptance,
Emergency Purge, automatic uncertainty recovery or multi-device/load validation.

## 1. Prepare a new database

Install the current package, select an existing private destination directory and
an absolute public inventory path. The initializer never reads `.env`, credentials
or SSH. Example host setup (choose actual absolute private paths):

```bash
ftd-shun-dev-init \
  --database /private/lab/managed-v2.db \
  --inventory /private/lab/devices.json \
  --concurrency 1
```

The directory must already exist. The destination must not exist, including a
symlink. Setup builds privately in that directory, validates the exact storage,
checkpoints SQLite and exclusively publishes a complete mode-0600 file. There is
no overwrite/reset option. On error, inspect any retained destination instead of
deleting it or assuming initialization failed before publication.

SQLite also needs a writable temporary directory for schema work. The existing
Compose `/tmp` tmpfs supplies it; reproduce that mount in read-only-container
smoke tests instead of mounting only the destination volume.

The profile accepts 1–10 total public devices, including disabled IDs. The sealed
enabled scope/concurrency must fit the real agent. It includes ordered removal
and its shared promoter. Initial empty desired execution is ready, but no policy
or device work exists: each new standing import still needs explicit user consent
and a later complete fresh read. The maintenance audit uses a real labelled
`maintenance:development-setup` actor, not an invented Web login.

Optional `--protection-from /private/lab/old-state.db` reads only validated current
Protected-IP address/name/comment/enabled settings. Disabled rows remain disabled;
new audit records identify this settings copy. It never imports legacy environment
policy or old managed generations/jobs/history. Omit it for a completely empty
policy. The source is opened readonly and is not converted or reset.

## 2. Select the executable profile

Set `FTD_SHUN_API_RUNTIME=continuous-managed` independently for API and Web.
Require socket mode, cycles, large snapshots, development authentication off and
matching declared agent capacity. Every enabled inventory device must have an
explicit supported ADD profile. For the already validated desk FPR1010/FTD 7.6.6:

```json
"addition_profile": "fpr1010-766-single-vf-management-v1"
```

Keep its `management` interface allowlisted and its existing stable ID/address/pin.
Do not assign this profile to an unvalidated model/version. The agent independently
requires `FTD_SHUN_AGENT_ADDITIONS_ENABLED=true`, cycles and large reads; there is
no downgrade when it refuses. Credentials remain exclusively in the agent.

Keep **legacy** import admission/execution, managed-policy/removal admission,
restoration and cleanup-worker switches false. The v2 selector supplies its own
exact scoped capabilities; it does not run an additional legacy scheduler. API
startup freezes/rechecks the complete public projection against retained devices.
Missing/incompatible storage or changed trust/identity refuses, never initializes.

## 3. Compose cutover

The opt-in `deploy/compose.managed-lab.yml` keeps the existing state volume but
selects `/var/lib/ftd-shun-manager/managed-v2.db`, leaving `state.db` intact. It
changes only API/Web selection and agent semantic protocol gates, not credentials,
authentication, networking or published ports. Use the same overlays for every
command after cutover. From the repository root:

```bash
dc() {
  docker compose --env-file .env \
    -f deploy/compose.yml -f deploy/compose.local-lab.yml \
    -f deploy/compose.managed-lab.yml "$@"
}
dc build api web agent
```

First retain the previous API/Web/agent image IDs or local rollback tags. Inspect
the old private queue/policy and drain work; do not abandon unknown or running
operations simply by changing files. Stop Web/API gracefully, then agent once
remote work has settled. The retained old `state.db` becomes an inactive archive;
use SQLite's backup API for an additional backup rather than copying a live main
file without its WAL. Never use `down -v`.

Create the absent new file with no other owner (include the final option only if
explicitly carrying Protected-IP settings):

```bash
dc run --rm --no-deps api ftd-shun-dev-init \
  --database /var/lib/ftd-shun-manager/managed-v2.db \
  --inventory /etc/ftd-shun-manager/devices.json \
  --concurrency 1 \
  --protection-from /var/lib/ftd-shun-manager/state.db
dc run --rm --no-deps api ftd-shun-api --check
dc up -d --no-deps agent api web
```

The check performs no RPC, policy grant or startup migration. It is not an agent
reachability test. API startup may execute already authorized work on the selected
new profile and automatic protected removals. Use exactly one owning API process;
never multiple Uvicorn workers or old/new schedulers simultaneously.

## 4. Verify and use

Inspect private `/api/v1/status`: `runtime_mode=continuous-managed`,
`bulk_execution_enabled=true`, matching scoped v2 admission flags, device freshness
and honest errors. The old generic `manual_mutations_available` and
`managed_workflows_available` flags remain false because **legacy** write routes
remain refused. Use the v2 controls shown by their separate capability flags.

In Web, open **Imports**, paste/select devices, review diagnostics and confirm the
explicit recurring-policy consent and accepted pair count. Invalid/protected IPs
are excluded and reported; an observed unmanaged target is adopted, not rewritten.
The shared worker reads fresh state, admits bounded portions and verifies writes;
it does not dump a 100000-job backlog into the queue. Confirmed disappearance of
managed targets permits restoration. Unknown ADD never receives blind replay.

For unblocking, use the frozen device/fleet removal review; retire authority and
queue REMOVE together. Ordered removal explicitly waits behind captured current
ADD evidence. Cancel an import to stop uncompleted work while retaining already
applied/adopted targets. Stop-maintaining alone does not remove the device entry.

Enabling protection permanently retires matching managed authority and initiates
protected cleanup. Disabling/deleting protection never re-enables that policy.
Check both the durable receipt and current device state; saved policy/queued work
is not verified device success. Ordinary synthetic tests do not establish load,
data-plane or production acceptance.

## 5. Rollback without overwriting data

Gracefully stop/drain Web/API and then agent; inspect unresolved/current work
before switching. Retain the new DB as well. Restore matching old images,
inventory metadata and the old two-file Compose selection targeting `state.db`;
leave v2 files untouched. Never run a legacy image against fenced v2 storage or
restore an old authority snapshot over live v2 jobs to bypass uncertainty.

If new device mutations have occurred, a configuration rollback does not undo
them: inspect/clean the exact new targets through semantic verified operations
and retire their new authority first. Do not replay archived queues or erase
evidence. For continued v2 operation use a compatible image/profile, not legacy.

## Validation

```bash
python3 -m pytest -q tests/test_dev_init.py tests/test_configured_managed.py tests/test_configured_runtime.py
```

These tests use disposable SQLite, actual API/BFF composition and semantic fake
RPCs. They cover exclusive publication/failure races, settings-only copy, exact
scope, no-init construction, strict mode selection, real consent/CSRF, creation,
restoration, protection retirement and confirmed cleanup admission.
