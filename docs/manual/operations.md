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

The SQLite database is the UI and local audit source of truth. Application events are designed for JSON stdout collection by the container runtime or host collector. Forward audit events to the organization log system and alert on collector failure without blocking monitoring.

Useful event types include `SHUN_DETECTED`, `SHUN_DISAPPEARED`, `SHUN_REMOVE_REQUESTED`, `SHUN_REMOVED_BY_UI`, and `SHUN_REMOVE_NOOP`.

## Backup and recovery

Back up the `state` volume consistently while the service is stopped or using a SQLite-safe backup method. Back up Authelia's `authelia-data` volume separately. Neither backup contains the FTD private key; that credential is provisioned through the agent bootstrap process only.

After restoring state, the future FTD synchronizer must reconcile a fresh `show shun` snapshot before exposing the service as READY.

## Incident response

- **Unexpected removal:** search `shun_events` and external logs by request ID; preserve the actor identity, roles, device, and IP.
- **Authelia unavailable:** reject new browser access. Do not bypass Caddy ForwardAuth.
- **API or agent unavailable:** display stale/failed state; never claim that a removal succeeded.
- **Host-key mismatch or unexpected FTD output:** keep the device out of write service, investigate through the approved out-of-band channel, and update the pinned inventory only after verification.
- **Suspected Caddy compromise:** revoke Authelia sessions, inspect forwarded-header configuration, and treat identity headers as untrusted until revalidated.
- **Suspected FTD key compromise:** remove the source IP from every FTD SSH ACL, revoke the key/account, and redeploy a new bootstrap identity.
