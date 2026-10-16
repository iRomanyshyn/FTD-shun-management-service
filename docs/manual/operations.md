# Operations Manual

## Current queue increment and planned extensions

Manual and trusted-policy removals now use the durable shared SQLite queue.
The UI exposes execution state and cancellation of unstarted manual requests.
See [Operation Queue](operation-queue.md) for limits, expiry, failure handling,
migration, backup/restore, and rollback.

The working queue contains only queued/running work. **Needs attention** lists
failed/unverified results separately; **Completed operations** is collapsed by
default and shows only the latest 20 other terminal results. Display limits
and totals are explicit. Retained results are history, not pending execution;
they are never deleted or requeued merely to clear the working view.

**Request progress** shows processed/total jobs for each active request, with
verified and other outcomes listed separately. Percentages describe processing,
not success; a currently running command has an indeterminate indicator. The
actual request total spans devices/cycles and is not the 16-job cycle cap.
Addition/import remains unavailable.

This increment retains the current agent RPC: each read/removal opens its own
short-lived session. It processes at most one queued removal per device per
fleet cycle, with a persisted minimum of 60 seconds after cycle completion.
An experimental, default-off [session-cycle protocol](agent-cycle-protocol.md)
can handle up to 16 jobs per device/session with 64-command and 120-second work
budgets and safe priority refresh checkpoints. It requires new agent/API
versions and live laboratory validation before enablement. Addition and manual
imports remain future work in the [Development Plan](../development-plan.md).

A separate default-off [Large Snapshots](large-snapshots.md) extension uses
typed multi-frame reads (cycle v2 when sessions are enabled). It keeps complete
validation before reconciliation, 32 KiB chunks, 20,000-entry/2 MiB payload
budgets, and bounded full CLI collection. It adds no write operation or new
queue budget. Both flags must be true for new reads; a newer agent still
supports explicit legacy API selection. Errors never downgrade/replay.

## Roles

| Group | Application role | Capability |
| --- | --- | --- |
| `ftd-shun-viewers` | Viewer | Read active state/history and manage Protected IPs. |
| `ftd-shun-operators` | Operator | Read, request removal, and manage Protected IPs. |
| `ftd-shun-administrators` | Administrator | Removal plus Protected IP policy management; identity-system administration remains separate. |
| No mapped group | Authenticated user | Read active state/history and manage Protected IPs; no manual shun removal or cross-user queue cancellation. |

Protected IPs intentionally has one shared management permission for every user
admitted by Authelia. Restrict service admission to trusted staff accordingly;
this exception does not grant a synthetic Administrator role or change queue
ownership checks. Real roles remain in every audit event.

## Removal workflow

For the separate, non-executable **Import preview** page, follow the
[preview manual](import-preview.md). Parsing/classification never queues work,
opens SSH, issues a refresh hint or saves a server-side batch. Ready rows are
candidate data only; additions remain unavailable for all roles.

1. An operator selects **Queue removal from this device** for the displayed hostname/IP.
2. The BFF verifies its CSRF token and obtains the Authelia identity passed by Caddy.
3. The internal API atomically records the queued request, actor, role snapshot, expiry, device/IP, and audit events, then returns `202 Accepted` with the parent operation ID. This is not removal success.
4. The leased background worker refreshes device state, revalidates live queued work, and sends only the fixed binary `REMOVE_SHUN` operation for an observed target. Duplicate users share the execution but retain separate audited requests.
5. The agent pins the FTD host key, reads the target `show shun <IPv4>` state, removes only positively identified allowlisted interfaces, and reads it again for verification.
6. The worker commits `VERIFIED` and `SHUN_REMOVED_BY_UI` only after the verified agent response. A lost/rejected response becomes `UNVERIFIED`; it does not clear active state or automatically retry the write.

**Queue removal from all devices** is separate. It requires typing the target IP and freezes the matched devices at admission, with one execution/result per device. An idempotent retry uses the original target set even if the current list has changed. Check the queue for completion or partial results.

## Snapshot collection and freshness

The active list puts Protected IP matches first, including disabled entries
with their red warnings. Within that group and the remaining addresses, newest
current appearances come first. **Observed since** is when the service detected
the current shun, not when FTD created it. A reappearance moves the address up;
ordinary polling does not. Lifetime first detection remains in retained history.
Rows detected together use numeric IP, hostname and interface as stable ties;
their true creation order cannot be recovered from `show shun`. Search and
history ordering are unchanged. Disabled protection still never permits
automatic removal just because its row is pinned near the top.

The private shun-list/detail API adds `active_since_at` from the existing active
row's `last_changed_at`; no migration or device command is needed for ordering.
Deploy API/Web together and reload existing tabs. Web tolerates the preceding
API's absent field using lifetime `first_seen_at` during rollback, but that old
pair does not provide current-appearance sorting. Queue/policy state is unchanged;
an API restart may execute existing work under the normal worker limits.

The API schedules a complete typed `show shun` snapshot at startup and then at
`FTD_SHUN_POLL_INTERVAL` (default `5m`). An authenticated list or detail page may
queue one asynchronous refresh hint, but neither a page load nor a search waits
for FTD SSH. The global/device minimum is
`FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL` (default `60s`).
The minimum cycle gate is persisted in SQLite, so restarting does not bypass
it. A fresh database can start immediately; a previous worker lease may require
recovery waiting. Pending queued work schedules another eligible cycle instead
of waiting for the idle five-minute baseline. All reads and queued removals
are dispatched by the same worker.

The UI shows the last complete successful sweep, a browser countdown derived
from the synchronizer's next-baseline timestamp, and the interactive state.
Treat a refresh warning as stale state for the named device; do not take a
write action based on an assumed current FTD state. A failed or malformed
snapshot is retained as a failure only and is never interpreted as an empty
device state.

Use the primary-page **IP search** field with a full IPv4 address or dotted
prefix to find both active shuns and retained local history. Search does not
wait for or directly trigger a Cisco operation. A result marked **Current
shun** is active in the latest local state; **Historical — not currently
shunned** means that the address is retained only as history and must not be
treated as a present FTD block. Results show the last seen time, last verified
removal when one exists, latest event, number of known devices, and the
**Protected IP** marker for an exact trusted-policy match.

A page view may still submit the normal asynchronous, globally rate-limited
refresh hint. The **Request refresh** control gives that same hint explicitly;
it never waits for FTD SSH or promises an immediate live result. Its countdown
shows when another browser hint is permitted. The service independently enforces
the minimum interval, so reloading or using multiple browsers cannot bypass it.
If the next five-minute baseline is less than the configured minimum interval
away (60 seconds by default), the service preserves that scheduled refresh
instead of starting a redundant manual one. The button then displays the
scheduled-refresh countdown. At any earlier point, an accepted button request
queues an immediate refresh and the subsequent baseline is measured from that
sweep.

The page sends the refresh request asynchronously and receives its actual
scheduler state immediately. Requests from several users/tabs join an already
queued or running sweep. It then polls the same authenticated Web/BFF for
freshness metadata; it does not poll the agent or FTD. A completed-cycle
revision identifies every outcome, including repeated identical errors and
partial fleet success. A separate data revision identifies committed local
changes, and a process identifier handles API restarts.

In experimental session mode, the control can offer **Request priority refresh**
during a long cycle after the interactive minimum has elapsed. It shows
**Refresh waiting for current operation…** until the current command and its
verification finish. One extra full snapshot may then run before the next
removal, publishing data while the queue is still running. Recent full
snapshots satisfy demand without another CLI read; further demand joins the
final snapshot. No extra session or unlimited command budget is created.

The browser updates the state, history, and policy sections dynamically when
these revisions change. Search text, removal confirmation input/focus, scroll,
and expanded event history are preserved. The refresh controls and device
status update without navigating or reloading the page. Status/submission/view
requests run sequentially with finite timeouts, visible errors, and automatic
retry backoff; polling pauses in hidden tabs and resumes when visible.

The per-device table shows **Current**, **Refreshing**, **Stale**, **Error**,
**Disabled**, or **Not yet confirmed**, last success, and error details. Data
becomes stale once its last successful observation is older than the polling
interval, or after a reported device failure. A failed device does not erase
its stored entries or hide a successful observation from another device.
Check the device table even when the fleet's last fully successful timestamp
has not advanced. Disabled agent mode offers no refresh action.

The countdown reaching zero does not itself reload the page or prove that the
snapshot finished. If status becomes unavailable, the page retains the last
displayed observations and shows an error. Authentication failures require a
normal page reload/sign-in; there is no authentication bypass.

### History pages

**History → Audit events** is always expanded and shows **100 events per page**,
newest first. Use Previous/Next or the Page/Go control; the summary shows the
page, available total and displayed range. Tied timestamps use reverse insertion
order. The first `/history` page updates dynamically as new events arrive.

Navigation carries an event-ID anchor: new events cannot move records between
the older pages being read. **Latest events** returns to the live first page.
Retention can shorten this browsing window and clamp its last page. If its
anchor has expired or is absent after a database restore, the page explicitly
asks you to open Latest events instead of silently changing windows. This is a
temporary browsing boundary, not an archived database snapshot. Page reads and
background metadata polls never issue FTD commands or refresh hints.

The private `GET /api/v1/history-page?page=…&anchor=…` response contains at most
100 events plus page/pages/total/page_size/anchor metadata, from one SQLite read
transaction. Invalid page/UUID input returns 422; a missing retained anchor
returns 410. Existing list and per-IP history API contracts are unchanged.
Use an IP detail page for that address's history and the container log collector
for external diagnostics and long-term forwarding.

Routine update messages are inside **Status**, with one stable-height summary
on the working page. Important stale/device/queue/submission errors remain
visible in a bottom-right alert tray without shifting search, forms or tables.
Open Status/Queue for the full context. Notices clear when the condition clears;
they are not automatically dismissed as if the operation had succeeded.

This display/API increment needs no schema migration or new setting. Upgrade
API/Web together, then reload existing tabs for the new script and styles.
Rolling back to the preceding paired API/Web images leaves all history/policy/
queue data intact; older releases predating policy/queue still require their
documented safety procedures.

The database and internal API use UTC timestamps. The Web UI displays those
times in the viewer's browser timezone and includes the timezone abbreviation
or UTC offset. A raw timestamp ending in `Z` is UTC, including the no-JavaScript
fallback.

## Trusted-IP automatic-removal policy

The SQLite-owned **Protected IPs** policy is disabled when no addresses are
enabled. All authenticated users manage exact IPv4 addresses through the UI; `.env`
does not control the policy. Do not use CIDRs,
hostnames, ranges, or a broad office subnet. Add only a verified egress address
for which automatic removal is explicitly acceptable on every enabled device.

After a complete successful snapshot, matching shuns are queued for removal through
the same pinned-host-key, allowlisted-interface, post-write-verified agent
operation as a manual removal. This is deliberately a background policy, not
a browser action: an unavailable or malformed snapshot runs no policy action.
The shared one-removal-per-device cycle budget also applies to this policy;
extra matches stay queued. Removing an address from the configured policy
cancels its unstarted policy request atomically, while preserving
an independent manual request for the same target.
The history records `SHUN_TRUSTED_AUTO_REMOVE_REQUESTED` and then either
`SHUN_TRUSTED_AUTO_REMOVED`, `SHUN_TRUSTED_AUTO_REMOVE_NOOP`, or
`SHUN_TRUSTED_AUTO_REMOVE_FAILED`, under the actor `system:trusted-ip-policy`.
On failure the active record remains visible; investigate the agent log before
retrying or changing the policy.

The separate Protected IPs page exposes the list to all
authenticated application roles. For each address it shows **Last
auto-removed**, the latest verified policy-removal timestamp across all enabled
devices, or **Never recorded**. Every authenticated user can edit it; stale edits
are rejected rather than overwrite another user. See [Protected IPs](protected-ips.md)
for workflow, one-time migration, cancellation semantics and rollback. Treat the displayed addresses as
internal operational information; access to the application already requires
Authelia authentication.

An active shun whose address exactly matches an enabled entry is highlighted with a
**Protected IP** badge and an amber row. Its detail page repeats the warning.
Disabled entries use a red **Protection disabled** badge/warning instead.
Both kinds of match are prioritized at the top of the active list.
The marker indicates policy membership only: review the audit history to learn
whether an automatic removal was requested, verified, or failed.

## History retention

The service retains historical events and inactive shun state for
`FTD_SHUN_HISTORY_RETENTION_DAYS`, which defaults to **366 days**. Once daily,
the synchronizer purges records older than that UTC cutoff. Active shun state
is never purged. A non-empty run adds a `HISTORY_RETENTION_PURGED` event with
the cutoff and deletion counts; the status endpoint also reports the most
recent retention run and any retention error.

This is irreversible for the live SQLite database. Take a SQLite-safe backup
before reducing the period, and retain backups under the organization’s own
audit-retention policy. After restoring a backup, wait for a successful FTD
snapshot before treating any active state as current.

## Logs and audit

The SQLite database is the UI and local audit source of truth. Application events are emitted as JSON to stdout for collection by the container runtime or host collector. The agent uses Docker's bounded `local` log driver (five 10 MiB files) so its operational and failure events survive container restarts and are available through Docker. This is a required local operational channel, not optional debugging output.

Retrieve recent agent events with timestamps:

```bash
docker compose --env-file .env -f deploy/compose.yml logs --timestamps --tail=200 agent
```

Forward those Docker logs through the host's approved container-log collector to the organization log platform. Alert on agent events named `agent.remove_shun.failed`; their `reason` is sanitized and intentionally excludes credentials and raw Cisco output. Collector failure must generate a host/platform alert, but must not make the agent claim a successful removal.

Useful event types include `SHUN_DETECTED`, `SHUN_REAPPEARED`, `SHUN_DISAPPEARED`, `SHUN_REMOVE_REQUESTED`, `SHUN_REMOVED_BY_UI`, `SHUN_REMOVE_NOOP`, `SHUN_OPERATION_*`, and the `SHUN_TRUSTED_AUTO_REMOVE_*` policy events. Alert on `agent.list_shuns.failed`, `synchronizer.device_refresh_failed`, `queue.removal.unverified`, and `agent.remove_shun.failed`.

## Backup and recovery

Back up the `state` volume consistently while the service is stopped or using a SQLite-safe backup method. Back up Authelia's `authelia-data` volume separately. Neither backup contains the FTD SSH password; that credential is provisioned through the agent secret only.

Before starting API against a restored database, follow the [queue recovery procedure](operation-queue.md#backup-restore-and-rollback) to suspend old mutations. After startup, wait for a successful FTD snapshot before treating the UI state as current. Investigate any visible warning first.

## Incident response

- **Unexpected removal:** search `shun_events` and external logs by request ID; preserve the actor identity, roles, device, and IP.
- **Authelia unavailable:** reject new browser access. Do not bypass Caddy ForwardAuth.
- **API or agent unavailable:** display stale/failed state; never claim that a removal succeeded.
- **Host-key mismatch or unexpected FTD output:** keep the device out of write service, investigate through the approved out-of-band channel, and update the pinned inventory only after verification.
- **Suspected Caddy compromise:** revoke Authelia sessions, inspect forwarded-header configuration, and treat identity headers as untrusted until revalidated.
- **Suspected FTD credential compromise:** remove the source IP from every FTD SSH ACL, rotate the dedicated password, and redeploy the protected agent secret.
