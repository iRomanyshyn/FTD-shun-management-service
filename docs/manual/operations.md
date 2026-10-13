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

## Logs and audit

The SQLite database is the UI and local audit source of truth. Application events are emitted as JSON to stdout for collection by the container runtime or host collector. The agent uses Docker's bounded `local` log driver (five 10 MiB files) so its operational and failure events survive container restarts and are available through Docker. This is a required local operational channel, not optional debugging output.

Retrieve recent agent events with timestamps:

```bash
docker compose --env-file .env -f deploy/compose.yml logs --timestamps --tail=200 agent
```

Forward those Docker logs through the host's approved container-log collector to the organization log platform. Alert on agent events named `agent.remove_shun.failed`; their `reason` is sanitized and intentionally excludes credentials and raw Cisco output. Collector failure must generate a host/platform alert, but must not make the agent claim a successful removal.

Useful event types include `SHUN_DETECTED`, `SHUN_DISAPPEARED`, `SHUN_REMOVE_REQUESTED`, `SHUN_REMOVED_BY_UI`, and `SHUN_REMOVE_NOOP`.

## Backup and recovery

Back up the `state` volume consistently while the service is stopped or using a SQLite-safe backup method. Back up Authelia's `authelia-data` volume separately. Neither backup contains the FTD SSH password; that credential is provisioned through the agent secret only.

After restoring state, the future FTD synchronizer must reconcile a fresh `show shun` snapshot before exposing the service as READY.

## Incident response

- **Unexpected removal:** search `shun_events` and external logs by request ID; preserve the actor identity, roles, device, and IP.
- **Authelia unavailable:** reject new browser access. Do not bypass Caddy ForwardAuth.
- **API or agent unavailable:** display stale/failed state; never claim that a removal succeeded.
- **Host-key mismatch or unexpected FTD output:** keep the device out of write service, investigate through the approved out-of-band channel, and update the pinned inventory only after verification.
- **Suspected Caddy compromise:** revoke Authelia sessions, inspect forwarded-header configuration, and treat identity headers as untrusted until revalidated.
- **Suspected FTD credential compromise:** remove the source IP from every FTD SSH ACL, rotate the dedicated password, and redeploy the protected agent secret.
