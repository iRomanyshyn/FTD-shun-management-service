# Operations Manual

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
`FTD_SHUN_POLL_INTERVAL` (default `5m`). An authenticated list or detail page
may queue one asynchronous refresh hint, but neither a page load nor a search
waits for FTD SSH. The global/device minimum is
`FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL` (default `60s`).

The UI shows the last complete successful sweep, a browser countdown derived
from the synchronizer's next-baseline timestamp, and the interactive state.
Treat a refresh warning as stale state for the named device; do not take a
write action based on an assumed current FTD state. A failed or malformed
snapshot is retained as a failure only and is never interpreted as an empty
device state.

The active-shun list has an in-browser IPv4 prefix search. It filters the
already displayed state only; it neither waits for nor directly triggers a
Cisco operation. A page view may still submit the normal asynchronous,
globally rate-limited refresh hint.

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
