# Operations Manual

## Planned workflow changes

The [Development Plan](../development-plan.md) records a future shared queue
for multiple users, one bounded write-and-refresh cycle per device no more
than once per minute, and manually imported shuns with visible provenance.
Imports will be one-time additions: removing one will not cause reimport.
The planned UI will expose shared queue progress. During a running import,
an eligible interactive refresh will use a safe checkpoint in the current SSH
session, publish the snapshot, and let the import continue. Duplicate requests
will coalesce under shared rate and cycle-budget limits.
These capabilities are not available yet. The immediate removal and current
refresh procedures below describe the present implementation; do not assume
queue admission, delayed writes, session reuse, or import support until their
implementation and laboratory validation are recorded in Project Status.

## Roles

| Group | Application role | Capability |
| --- | --- | --- |
| `ftd-shun-viewers` | Viewer | Read active state and history. |
| `ftd-shun-operators` | Operator | Read and request removal. |
| `ftd-shun-administrators` | Administrator | Same write capability; identity-system administration remains separate. |

## Removal workflow

1. An operator selects **Remove from this device**. The UI displays the hostname and every observed matching interface.
2. The BFF verifies its CSRF token and obtains the Authelia identity passed by Caddy.
3. The internal API records `SHUN_REMOVE_REQUESTED` with actor, roles, device, IP, and request ID.
4. Only the fixed binary `REMOVE_SHUN` operation is sent to the agent.
5. The agent pins the FTD host key, reads the target `show shun <IPv4>` state, removes only positively identified allowlisted interfaces, and reads it again for verification.
6. The API records `SHUN_REMOVED_BY_UI` only after a verified agent result. Otherwise the write is unavailable or fails.

**Remove from all devices** is separate. It requires typing the target IP and creates one device-scoped audit result per matched device.

## Snapshot collection and freshness

The API performs a complete typed `show shun` snapshot at startup and then at
`FTD_SHUN_POLL_INTERVAL` (default `5m`). An authenticated list or detail page may
queue one asynchronous refresh hint, but neither a page load nor a search waits
for FTD SSH. The global/device minimum is
`FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL` (default `60s`).

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

Use the collapsed **Last events log** on the primary page for the latest 100
local audit events. It is a convenient recent view, not an external log
replacement; use an IP detail page for that address's history and the container
log collector for diagnostics and long-term forwarding.

The database and internal API use UTC timestamps. The Web UI displays those
times in the viewer's browser timezone and includes the timezone abbreviation
or UTC offset. A raw timestamp ending in `Z` is UTC, including the no-JavaScript
fallback.

## Trusted-IP automatic-removal policy

`FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS` is disabled when empty. When configured, it
contains only comma-separated, exact IPv4 addresses. Do not use CIDRs,
hostnames, ranges, or a broad office subnet. Add only a verified egress address
for which automatic removal is explicitly acceptable on every enabled device.

After a complete successful snapshot, each matching shun is removed through
the same pinned-host-key, allowlisted-interface, post-write-verified agent
operation as a manual removal. This is deliberately a background policy, not
a browser action: an unavailable or malformed snapshot runs no policy action.
The history records `SHUN_TRUSTED_AUTO_REMOVE_REQUESTED` and then either
`SHUN_TRUSTED_AUTO_REMOVED`, `SHUN_TRUSTED_AUTO_REMOVE_NOOP`, or
`SHUN_TRUSTED_AUTO_REMOVE_FAILED`, under the actor `system:trusted-ip-policy`.
On failure the active record remains visible; investigate the agent log before
retrying or changing the policy.

The primary page exposes the configured list as a read-only table for all
authenticated application roles. For each allowed address it shows **Last
auto-removed**, the latest verified policy-removal timestamp across all enabled
devices, or **Never**. The table is status only: update the ignored `.env` and
recreate the API service to change the policy. Treat the displayed addresses as
internal operational information; access to the application already requires
Authelia authentication.

An active shun whose address exactly matches that table is highlighted with a
**Protected IP** badge and an amber row. Its detail page repeats the warning.
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

Useful event types include `SHUN_DETECTED`, `SHUN_REAPPEARED`, `SHUN_DISAPPEARED`, `SHUN_REMOVE_REQUESTED`, `SHUN_REMOVED_BY_UI`, `SHUN_REMOVE_NOOP`, and the `SHUN_TRUSTED_AUTO_REMOVE_*` policy events. Alert on `agent.list_shuns.failed`, `synchronizer.device_refresh_failed`, and `synchronizer.trusted_auto_remove_failed` as well as `agent.remove_shun.failed`.

## Backup and recovery

Back up the `state` volume consistently while the service is stopped or using a SQLite-safe backup method. Back up Authelia's `authelia-data` volume separately. Neither backup contains the FTD SSH password; that credential is provisioned through the agent secret only.

After restoring state, wait for a successful FTD synchronizer snapshot before treating the UI state as current. Investigate and resolve any visible refresh warning first.

## Incident response

- **Unexpected removal:** search `shun_events` and external logs by request ID; preserve the actor identity, roles, device, and IP.
- **Authelia unavailable:** reject new browser access. Do not bypass Caddy ForwardAuth.
- **API or agent unavailable:** display stale/failed state; never claim that a removal succeeded.
- **Host-key mismatch or unexpected FTD output:** keep the device out of write service, investigate through the approved out-of-band channel, and update the pinned inventory only after verification.
- **Suspected Caddy compromise:** revoke Authelia sessions, inspect forwarded-header configuration, and treat identity headers as untrusted until revalidated.
- **Suspected FTD credential compromise:** remove the source IP from every FTD SSH ACL, rotate the dedicated password, and redeploy the protected agent secret.
