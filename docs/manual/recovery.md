# Offline Recovery and Mutation Safety Pause

## Scope and prerequisites

Use this procedure on a **reviewed restored working copy**, not the sole original
backup. It changes local queue/policy state and writes audit records, never FTD.
It does not install policy, initialize managed tables, start services or read
`.env`, inventory or SSH credentials. The trusted-host operator is recorded as
`maintenance:<label>`, not an impersonated Web user.

Stop the sole API/Web pair and prevent an orchestrator from restarting it.
Ensure no previous agent RPC can still execute: settle it within its documented
timeout or stop the agent too before maintenance. An in-flight command cannot
be recalled by editing SQLite. `--confirm-offline` asserts these prerequisites;
the tool cannot verify remote command settlement for you. Do not run against a
live writer. Concurrent commits during backup are detected and refused, but
this is not a replacement for stopping services.

Use the current installed package (or `python3 -m ftd_shun_manager.maintenance`)
and the existing SQLite file, including its WAL state. Do not copy only an open
database file or initialize a fresh database over the restored copy.

## Suspend before restarting monitoring

Create a new private backup directory owned by the maintenance operator. Supply
explicit reviewed absolute paths and a new filename for each command:

```bash
install -d -m 0700 /approved/private/recovery-backups
ftd-shun-maintenance suspend \
  --database /approved/restored/state.db \
  --backup /approved/private/recovery-backups/before-suspend.sqlite3 \
  --actor operator-label --confirm-offline
```

Paths are illustrative; do not paste them until selecting the actual restored
working copy. Container users must run the same command with API/Web stopped,
under the database owner's UID, mounting only the reviewed state/backup paths.
Do not start a second API as a maintenance shortcut.

Before mutation, the tool checks SQLite integrity/foreign keys, creates a
SQLite-API backup (0600, exclusive new file, no overwrite/symlink), verifies it
and rejects a concurrent database commit. A failure retains any backup created;
inspect it before retrying with a **new** filename. A failed control/audit
transaction rolls back completely. Do not treat a printed error as success.

One transaction then performs:

| Existing state | Recovery result |
| --- | --- |
| QUEUED ADD or REMOVE | CANCELLED; no automatic replay. |
| RUNNING ADD or REMOVE | UNVERIFIED; uncertainty is preserved. |
| Active request delegations | CANCELLED; no renewed deadline. |
| WAITING_ADD / transitional cleanup | CANCELLED; no later promotion. |
| Whole-scope fleet barrier, if explicitly initialized | CANCELLED with all reservations released; captured RUNNING ADD becomes UNVERIFIED as above, never replayed. |
| Managed desired policy, if explicitly initialized | `restoration_suspended=1`; targets/authority retained, not adopted or erased. |
| Optional ready-target fleet authority | Immutable root/retirement retained; its ordinary delegation/jobs are suspended as above, never recreated by replay. |
| Shared executor | Durable `mutations_suspended=1`, lease cleared, 60-second cooldown. |

Per-job/per-wait and aggregate events are appended in that transaction. New
ordinary/import/trusted-policy admissions, managed MAINTAIN/cleanup admission
and mutation claims are blocked. Old-key replay is read-only; policy-only
RETIRE is still allowed. Reinitialization/restart does not clear the pause.

Start the matching current API/Web (and agent if stopped) for monitoring only.
Baseline snapshots and browser reads remain available. The Web shows a visible
recovery warning even with menus closed. Trusted-IP discovery does not generate
removals while paused. Review fresh device observations, uncertain outcomes,
retained policy and audit. Reading an absent target does not prove a write
succeeded; ordinary absence reconciliation remains distinct from verification.

## Resume ordinary mutations only

After review, stop API/Web and settle RPCs again. Keep ADD gates, device profiles
and cleanup-worker settings unchanged unless separately authorized. Then:

```bash
ftd-shun-maintenance resume-mutations \
  --database /approved/restored/state.db \
  --backup /approved/private/recovery-backups/before-resume.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed
```

Resume refuses if mutations are not paused, pending jobs/waits remain or a
managed registry is not restoration-suspended. It clears **only** the ordinary
mutation pause. Cancelled jobs/delegations/handoffs never restart; uncertain
results are not requeued. There is no desired-restoration resume/rearm command.
After restart, enabled Protected-IP policy may create fresh removals from new
observations. Submit still-required manual work as new reviewed requests under
the existing feature gates; backup recovery is not device-write authorization.

## Migration and rollback

Queue initialization adds `operation_executor.mutations_suspended` with default
0 to preserve ordinary behavior. Recovery can add that column to an existing
queue database, but refuses absent queue or partial managed schemas. Pre-queue
backups require a separately reviewed migration, not blind initialization here.
The optional [fleet ledger/barrier](managed-fleet-removals.md) is never initialized by
recovery. Orphaned fleet authority without its registry or a committed root-ledger ADMITTING
phase refuses recovery for inspection. Normal fleet admission commits ADMITTED
only; do not automatically repair/replay inconsistent restored authority. A
WAITING_ADD/transitional barrier is instead cancelled under the suspension
transaction; it never resets the immutable root phase.

Take a checked backup and retain paired API/Web images before upgrading. Keep
additive tables and authority/tombstones on rollback; do not restore old device
state merely to revert code. **Older images ignore the pause and handoff
reservations and fleet key authority. Do not start them against paused/restored/pending state.** A
downgrade needs a separately reviewed offline plan with no executable pending
work or active policy; disabling ADD alone does not disable trusted removals.
Never run old writers alongside the shared executor.

## Validation boundary

`tests/test_recovery_controls.py` uses disposable SQLite and synthetic agents:
backup/permissions/no overwrite, concurrent-commit refusal, transaction/audit
rollback, durable pause, resume without resurrection, optional schemas, paused
monitoring and default-off leased cleanup integration. Chromium checks visible
warnings without layout shifts. This is not a lab restore exercise, live FTD
mutation test or production recovery certification.
