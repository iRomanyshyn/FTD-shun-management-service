# Unblock Imported IPs

Open an import from **Import: …** in Managed shuns or IP details, then choose
**Unblock imported IPs…**. Review the current count and confirm once. You do not
need to type IP addresses. Opening the review changes nothing.

Confirmation permanently stops this import's matching automatic restoration,
cancels additions that have not started, and creates one cleanup task. Current
blocks are removed through the normal verified queue. Addresses already absent
are checked and counted as verified absences. There can be up to 100,000 device/IP
pairs; each task page shows 100 rows.

## What belongs to the task

Only this import's currently enabled rules with the same original authorization,
intent and generation are included. Existing blocks explicitly adopted by this
import are included. **Already managed elsewhere**, protected exclusions,
previously retired rules and rules replaced by another import are excluded.
Other imports, unmanaged blocks and Protected-IP policy remain unchanged.

The review is valid for five minutes. Confirmation rechecks the complete owned
scope, device settings and policy revision together, in one transaction. A changed
scope requires a new review. An unresolved owned operation must be resolved first;
opening a review or finding a block on the device does not resolve uncertainty.

## Progress and cancellation

**Queue → Import cleanup** shows one progress card for the whole task. Its bar
counts verified removals and verified absences, rather than queue acceptance.
Follow its link for the paginated target list. The import page retains task links
after completion; completed tasks do not clutter Queue.

The scheduler fills a rolling window of at most 32 unfinished removals, in groups
of at most 16. Device commands use the existing shared SSH session and verification
limits. Interactive unblocking and Protected-IP work take priority; different
devices can progress independently. Import/restoration pauses do not pause removals.
A disabled or held device waits without preventing another eligible device from
progressing. The task has a fixed seven-day deadline; individual delegated queue
requests last at most 15 minutes and never outlive the task.

An already-running addition must finish and its original SSH visit must settle
before the matching removal is delegated. Unknown or failed command results remain
visible for attention; they are never blindly repeated or called successful from
a later observation. Existing recovery procedures still apply.

Offline epoch recovery is unavailable while an import cleanup is active, even
before its first removal is delegated. Recovery guidance links the active task.
If it cannot settle normally, inspect/cancel its remaining work, then obtain a
separate fresh recovery review. Cancelling cleanup does not resolve the original
uncertain command. Exact completed-session recovery remains available.

The task owner or an Administrator can choose **Cancel remaining removals** from
Queue or the task page. Already-started commands finish and retain their actual
results. Independent requests, including Protected-IP unblocking sharing the same
job, remain authorized. Cancellation or expiry never re-enables the retired rules,
re-adds removed blocks or resets the deadline. A new block requires a new explicit
managed import.

If a confirmation reply is lost, check **the original cleanup task** or retry the
same confirmation. The browser keeps the original key/body; a repeated acceptance
returns the same receipt, not a second task. A historical acceptance is not a claim
that device removal has completed.

## Deployment and storage

This is an optional profile for the continuous-managed API, default off:
`FTD_SHUN_IMPORT_UNBLOCKS_ENABLED=false`. Set the same public flag for API and Web.
The agent wire protocol, inventory, trust and credentials do not change.

For an existing supported development profile, stop API/Web and settle all device
writers first. Retain a private SQLite backup and the exact image identities.
Explicitly initialize the selected database with the candidate application image:

```sh
python -m ftd_shun_manager.import_unblocks   --database /absolute/path/to/selected-development.db --initialize
```

The initializer requires existing exact managed storage, no pending/unresolved work
and idle device fences. It creates no requests or device commands. Startup and GET
never create/upgrade this profile. Old writers refuse its additional schema. The
current release policy permits this explicit development initialization; it is not
a released-data converter. Do not select an archived test database for live writers.

After initialization, enable the flag and start the matching API/Web. A configured
API refuses to start without the complete profile; disabling the flag while active
tasks remain also refuses startup. Do not roll back to an old writer against the
new profile or restore an old database over newly accepted authority.

Retained root consent, frozen membership, delegated job links, captured ADD claims
and audit are preserved. Limits are 128 task receipts and 1,000,000 retained target
members; full capacity refuses a new task atomically. No task deletes its evidence.

## Internal API

All routes use the existing private API Unix socket. Web supplies the authenticated
actor and CSRF/session-bound review; these are not public network endpoints.

| Route | Purpose |
| --- | --- |
| `GET /api/v2/import-unblocks/review/<import UUID>` | Query-only current scope/digest/count and eligibility. |
| `POST /api/v2/import-unblocks` | Confirm exact import/digest/count/review time with actor and original `Idempotency-Key`. |
| `GET /api/v2/import-unblocks` | Bounded active-task summaries. |
| `GET /api/v2/import-unblocks/<task UUID>?page=1` | Original receipt/current counts and at most 100 targets. |
| `POST /api/v2/import-unblocks/<task UUID>/cancel` | Owner/Administrator cancellation; no retirement reversal. |

The status feed includes active-task summaries. Its queue retains real counts and
attention results but groups internal cleanup jobs under their parent task. Viewing
status never starts provider lookups or a new cleanup.
