# Execution Recovery

Temporary local contention should not require cancelling a valid import. Recovery
depends on the evidence available, not on how often Retry is pressed.

| Situation | Service behavior | Operator action |
| --- | --- | --- |
| SQLite `SQLITE_BUSY` during the running coordinator's local scheduling pass | Retry after 5, 10, 20, 40, then at most every 60 seconds; retain demands and the original import | Normally none; inspect persistent storage contention |
| Exactly proved pre-command SSH opening failure or settled claim-free read failure | Existing capped device reconnect backoff, with a new lease/session and fresh checks | Restore connectivity; no reimport |
| Unknown ADD/REMOVE result, lost lease or missing settlement | Retain original outcomes and device fence; no command replay | Inspect original job/session evidence and use only the applicable reviewed offline procedure |
| Invalid profile, missing schema, non-BUSY SQLite error or unexpected lifecycle failure | Stop dispatch and drain admitted sessions | Inspect logs/storage, correct the cause, then perform a controlled API restart |

## Automatic scheduling retry

Only an `OperationalError` with SQLite's numeric base error code `SQLITE_BUSY`
qualifies, including its extended codes. Text matching such as `database is
locked` alone does not establish safety. `SQLITE_LOCKED`, corruption, disk/I/O
errors and validation failures are not silently retried. Startup validation and
worker RPC/claim/result persistence retain their separate existing contracts.

Each retry performs the entire current scheduling validation again. This is not
a retry of a device command or a partially persisted result. An already admitted
worker keeps its original task, epoch, deadlines, settlement and uncertainty
rules. There is no replacement session merely because scheduling was busy.
Requests, desired policy, protection, cancellation, leases and audit evidence are
not cleared, renewed or reconstructed. Previously committed local promotions
are read normally on the next pass, not undone or granted twice.

Browser demand remains coalesced while scheduling waits. Repeated clicks do not
shorten backoff; normal stop wakes it promptly and drains workers. After a
successful scheduling pass the retry warning clears. This proves scheduling
availability only, not a successful Cisco write or fresh observation.

Status and Queue show the automatic-retry state. `execution_recovery` in private
status/BFF metadata includes state, failure count, retry eligibility, reason and
operator guidance for a stopped executor. The countdown is eligibility, not a
guarantee. `dispatcher.storage.retry`, `dispatcher.storage.recovered` and
`dispatcher.stopped` logs contain bounded diagnostics without job/IP/CLI content.
No new public mutation/restart endpoint or schema is introduced.

### Contention and presentation

An empty ordered-removal promotion sweep uses a validated read-only snapshot,
not `BEGIN IMMEDIATE`. It still checks the complete existing profile and rejects
incomplete admission tickets. Real candidate work repeats every original check
inside the original writer transaction; work arriving after an empty snapshot
waits for the next sweep. No authority or eligibility result is cached. This
removes an unnecessary competing writer during imports, not SQLite's single-
writer constraint or every possible storage failure.

The first two typed scheduling retries show neutral automatic waiting in Status
and Queue; attempt three and later warn. Only the matching coordinator reason is
quieted: independent device errors, stale data, stopped execution, unknown results
and action-submission failures remain actionable. Short GET network/timeouts or
HTTP 502/503/504 responses retry quietly while retaining displayed data; repeated
or sustained failures escalate. These are presentation rules, never permission
to replay a mutation, release an epoch or mark observations current.

## Resuming a stopped executor

Do not cancel/reimport just to get past an error. Inspect Status and service logs,
retain the failure evidence, and distinguish an idle stopped coordinator from
an active or uncertain device session. API HTTP health alone does not establish
that device dispatch is running; check `refresh_enabled` and `execution_recovery`.

After correcting a local cause, drain/stop API and verify its actual exit before
restarting the compatible API image. Retain the original database and import;
the restarted worker must pass normal profile/lease/current-policy checks and
obtain new complete device evidence. A restart never releases ATTENTION or makes
an unknown command safe to retry. On the current desk lab use all three Compose
overlays, including `compose.managed-lab.yml`.

For retained holds see [verified held-session recovery](verified-epoch-recovery.md)
or the narrower [quiescent managed-ADD reconciliation](quiescent-managed-reconciliation.md).
Their original scope, actual shutdown, fresh review, checked backup and immutable
receipts remain mandatory. Do not reuse a historical decision for a later epoch.

## Deployment and validation

API/Web-only update: no DDL, gate, credential, trust, inventory, network or agent
change. Keep the preceding profile-compatible images, retain bounded logs before
replacing containers, drain API, check actual stopped job/fence state and deploy
matching API/Web. Existing admitted work may continue after startup; do not add
test mutations merely to exercise retry. Rollback uses those compatible images,
not a stale database or authority restoration.

Tests cover a real SQLite BUSY exception, repeated contention/backoff, demand
preservation, active-session identity, prompt orderly stop, conservative error
classification and browser recovery/stopped presentation. Synthetic contention
tests do not certify disk-failure recovery or arbitrary unknown-command replay.
