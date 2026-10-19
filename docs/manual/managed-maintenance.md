# Offline Managed Migration and Policy Resume

## Boundary

`ftd-shun-managed-maintenance` (or
`python3 -m ftd_shun_manager.managed_maintenance`) is a trusted-host offline tool,
not a Web/API route. It never reads `.env`, inventory or credentials, starts a
service, contacts FTD, enqueues work or changes feature gates/device profiles.
Do not invoke it on the current lab database without separately scoped migration/
policy approval. Shipping the tool does not authorize that activation.

Stop the sole API/Web pair and prevent automatic restart. Settle every previous
agent RPC, or stop the agent and ensure commands cannot still execute. A database
lease expiring is not proof that a remote command stopped. `--confirm-offline`
asserts these operator prerequisites; the tool cannot prove them remotely.
Use a reviewed working copy for recovery, never the sole original backup.

All paths below are illustrative absolute paths. Select the actual approved
database (including WAL), its owner UID and an operator-owned 0700 backup directory
first. No second API container is needed. Each write requires a new exclusive
0600 SQLite-API backup, verified integrity/foreign keys and no concurrent commit.
Created backups survive refusal; use a new filename for each retry.

## Initialize empty optional schemas

First use [Offline Recovery](recovery.md) `suspend` with its own checked backup.
This cancels queued work, preserves RUNNING uncertainty and pauses ordinary
mutations; review that operational impact before doing it. No outstanding job
or executor lease may remain. Initialization requires a current initialized
queue/protection database and refuses **any** existing/partial managed objects.
It is not an upgrade/repair tool for older optional schema variants.

Prepare an offline read-only review:

```bash
ftd-shun-managed-maintenance review-initialize \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

Inspect `ready`, `blockers`, `reviewed_at` and `confirmation_digest`. A digest binds
the exact local state, not a permission to write Cisco. If ready, copy its exact
timestamp/digest into the write command within five minutes:

```bash
ftd-shun-managed-maintenance initialize \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-managed-initialize.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

One transaction creates registry, immutable request ledger, target tombstones,
restoration attempt ledger, single cleanup authority, fleet authority and fleet
waiting barrier, including indexes/triggers, plus a maintenance audit event.
On any DDL/contract/audit failure all changes roll back, even if an outer caller
catches the error. Initializers compose trusted statements without SQLite
`executescript()` implicit commits. No observations/imports/history are adopted,
no desired targets are created and both ordinary pause and desired suspension
remain set. Existing state/protection/jobs remain unchanged.

Ordinary startup and optional GETs still never initialize these tables.
Individual developer initializers remain for disposable tests, not a substitute
for this reviewed all-or-nothing deployed migration.

## Resume existing standing policy separately

Migration grants no standing authority. Any standing grants need their own
explicit consent and [independent admission gate](managed-grants.md). Likewise,
this tool cannot grant/re-enable targets or clear uncertainty. For policy resume,
perform reviewed `resume-mutations` through [Offline Recovery](recovery.md) first,
with a separate backup and services still stopped. That control leaves desired
restoration suspended. Keep all execution gates/profiles unchanged.

```bash
ftd-shun-managed-maintenance review-resume \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

The review lists all enabled pairs, hostnames, intent/generation, authorization
request/actor and original label/reason. Treat this output as private operator
data. The digest additionally binds complete schema, all retained optional
ledgers/targets (including retired), executor/protection revisions and device/
protection state. Inspect every enabled target and current deployment gates.
The tool does not inspect or enable startup-only addition profiles.

Resume refuses:

- absent, partial, modified or over-capacity optional schema/evidence;
- ordinary mutation pause, any executor lease or pending queue job;
- pending/failed/UNVERIFIED restoration, or any retained UNVERIFIED ordinary job;
- waiting/transitional/attention cleanup or inconsistent fleet authority;
- no enabled targets, enabled targets on disabled devices or protected addresses;
- missing matching standing authority, non-suspended desired policy or backwards
  policy time; and
- a changed, future or expired five-minute review.

There is deliberately no uncertainty override. A later observation does not prove
an earlier write succeeded. Resolution/rearm needs a separate reviewed increment;
do not delete ledgers, edit outcomes, rekey old requests or restore an older DB
to get around these checks.

Use the read-only [Attention Inspection](managed-attention.md) `attention` command
to identify retained ordinary/restoration failures and cleanup attention, with
bounded snapshot-bound pages, pending-work counts and explicit missing evidence.
It changes no latch or authority and cannot make a blocked resume ready.

Separate [Incident Abandonment](managed-abandonment.md) commands can explicitly
add a retained closure ledger and retire current policy for one restoration case.
They require their own review/backup; base `initialize` still creates only seven
tables. Abandonment preserves the failure latch and **does not relax resume**.

```bash
ftd-shun-managed-maintenance resume-policy \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-policy-resume.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

The transaction clears only `restoration_suspended`, increments the managed
revision and stamps enabled targets' revision/`updated_at` with a new absence
barrier one millisecond after the control time (the stored timestamp precision).
Fresh complete reads must start at/after that barrier, strictly after the resume
control. It retains intent ID/generation, original authorization/request dates,
retired targets, immutable keys/attempts, all outcomes and all queue contents.
It appends `MANAGED_POLICY_RESUMED` attributed to `maintenance:<label>`, with
empty directory roles, review time and state digest. It does not wake execution.

Restart only the reviewed matching services. Future restoration still requires
the independent controller/API ADD/agent ADD/cycle/large-read gates, explicit
device profiles, fresh absence, existing cooldown/cutoff, shared lease and all
protection/uncertainty/churn checks. A resume receipt is neither queued nor
verified creation. Reusing an old review after resume fails; no auto rebase/retry.

## Rollback and validation

Retain paired API/Web images and checked backups before rollout. Keep additive
schema/authority and tombstones on code rollback; do not drop them or restore
old enabled policy. To stop policy/execution, use current offline `suspend`
after stopping services/settling RPCs. Older images may ignore recovery pauses
or pending reservations; never run them against such state without a separate
offline downgrade plan. No migration/resume in the actual lab is part of tool
validation.

`tests/test_managed_maintenance.py` uses disposable SQLite only: no-init/read-only
review, empty atomic DDL/no adoption, exact schema checks, audit/DDL rollback,
digest/revision/protection/device/clock conflicts, backup/no overwrite, retained
uncertainty/barriers, CLI confirmations and post-resume fresh-snapshot gating.
Existing recovery/source/queue suites remain required. This is not live reboot,
restoration, rollback or production acceptance.
