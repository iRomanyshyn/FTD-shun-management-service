# FTD Shun Management Service

## 1. Purpose

Develop a small, security-focused internal service for monitoring and managing Cisco Secure Firewall Threat Defense (FTD) `shun` entries across multiple similar devices.

The primary use case is Remote Access VPN Threat Detection, where legitimate or misbehaving users may cause their public IPv4 address to be automatically shunned by FTD.

The system must provide:

- continuous monitoring of active shun entries;
- detection and timestamping of newly observed shuns;
- tracking of shun disappearance;
- manual removal of an individual shun through a web interface;
- distinction between manually removed entries and entries that disappeared externally;
- historical event tracking;
- structured audit and operational logging;
- forwarding of logs to external log collectors;
- a hardened low-level SSH interface to FTD;
- strict prevention of arbitrary Cisco CLI execution through any exposed interface.

Each configured device has an immutable internal ID, display hostname, and management IP address. The initial deployment may use one dedicated Cisco service account and SSH identity for every configured FTD, while host-key verification remains specific to each device.

This is not intended to be a generic FTD management system, SSH proxy, terminal server, configuration management system, or command execution API.

Security takes priority over extensibility.

---

# 2. Core Security Principle

The application must expose semantic operations only.

Permitted operations are conceptually limited to:

```text
LIST_SHUNS
GET_SHUN
REMOVE_SHUN
GET_REMOTE_ACCESS_AUTHENTICATION_STATUS
GET_REMOTE_ACCESS_CLIENT_INITIATION_STATUS
GET_DEVICE_HEALTH
```

No component reachable from the network may accept Cisco commands.

The following interfaces must never exist:

```text
/exec
/command
/shell
/terminal
/ssh
/run
```

There must not be any request format containing fields such as:

```json
{
    "command": "show ..."
}
```

or:

```json
{
    "cli": "..."
}
```

Arbitrary Cisco CLI text must never cross a trust boundary.

---

# 3. Security Limitation of Cisco FTD

Cisco FTD does not currently provide sufficiently granular CLI authorization for this use case.

A writable FTD CLI account effectively has broader Config-level privileges than required by the application.

Therefore, the application itself must enforce privilege separation.

The security model must explicitly acknowledge:

> A complete arbitrary-code execution compromise of the privileged SSH executor while it owns an authenticated Config-level FTD session may allow an attacker to abuse that session beyond the intended application functionality.

The architecture must make such a compromise difficult, short-lived, and isolated.

Compromise of any externally reachable component must not directly provide:

- the FTD private key;
- an authenticated FTD SSH connection;
- network access to the FTD management interface;
- arbitrary command execution on FTD.

---

# 4. High-Level Architecture

Recommended architecture:

```text
                         INTERNAL USERS
                               │
                               │ HTTPS
                               ▼
                     ┌──────────────────┐
                     │      Caddy       │
                     │                  │
                     │ only published   │
                     │ TCP port: 443    │
                     └────────┬─────────┘
                              │
                              │ private container network
                              ▼
                     ┌──────────────────┐
                     │     Web/BFF      │
                     │                  │
                     │ Web UI           │
                     │ user auth        │
                     │ CSRF protection  │
                     └────────┬─────────┘
                              │
                              │ Unix Domain Socket
                              ▼
                     ┌──────────────────┐
                     │    REST API      │
                     │                  │
                     │ no FTD route     │
                     │ no Cisco secret  │
                     │ state/event API  │
                     └────────┬─────────┘
                              │
                 Unix Domain Socket / binary RPC
                              │
                              ▼
                  ┌───────────────────────┐
                  │   FTD SSH Agent       │
                  │                       │
                  │ fixed operations only │
                  │ owns SSH session      │
                  │ no HTTP               │
                  │ no shell              │
                  └───────────┬───────────┘
                              │
                              │ SSH TCP/22
                              ▼
                            Cisco FTD
```

During interactive sign-in, Caddy delegates authentication to Authelia using ForwardAuth. Authelia is outside the FTD trust path: it has no socket, credential, or network route to the REST API, FTD agent, or FTD management network.

Only Caddy may publish a host TCP port.

No other container may publish any host port.

---

# 5. Container Layout

The FTD service deployment should consist of at least the following containers:

```text
caddy
web
api
ftd-agent
```

Authentication is delegated to Authelia. It is an identity-system dependency, not a component trusted with FTD access: it must not receive an FTD credential, an agent socket, or network access to FTD management interfaces. The initial deployment uses Authelia's local file backend and SQLite; it may later switch to LDAPS without changing the FTD service authorization model.

An optional credential/bootstrap helper may be implemented as an additional isolated component.

Recommended runtime:

```text
Ubuntu Server
+
Podman/Quadlet
```

or:

```text
Ubuntu Server
+
Docker Engine
+
Docker Compose
```

Both must be supported architecturally.

No container may receive access to:

```text
/var/run/docker.sock
/run/podman/podman.sock
```

or any equivalent container-management socket.

Containers must not run privileged.

---

# 6. Network Segmentation

## 6.1 Caddy

Caddy is the only externally reachable component.

It must publish:

```text
TCP/443
```

on an explicitly configured internal server address.

It should not bind to every interface unless explicitly configured.

Example:

```text
10.20.10.50:443
```

rather than:

```text
0.0.0.0:443
```

Host firewall rules should additionally restrict access to approved internal administrative networks.

---

## 6.2 Web/BFF

The web component must:

- have no published ports;
- be reachable only from Caddy;
- expose browser-facing UI functionality;
- communicate with the REST API through a Unix Domain Socket or isolated internal channel.

The Web/BFF has no network interface in the recommended deployment. It receives identity headers only from Caddy over its Unix Domain Socket and must not have a route to the Cisco management network.

It should preferably act as a Backend-for-Frontend.

The browser should not directly communicate with the low-level REST API.

---

## 6.3 REST API

The REST API should preferably have:

```text
network_mode: none
```

or equivalent network namespace isolation.

It must communicate with:

- Web/BFF through Unix Domain Socket;
- FTD agent through a different Unix Domain Socket.

It must not have a route to the Cisco management network.

---

## 6.4 FTD Agent

The agent is the only component allowed to establish TCP sessions to FTD.

Its outbound network policy must be:

```text
ALLOW -> configured FTD management IPs TCP/22
DENY  -> everything else
```

It must not require:

- DNS;
- Internet access;
- HTTP;
- HTTPS;
- arbitrary outbound connections.

FTD management targets should therefore be configured by IP address.

The agent maintains independent, pinned-host-key SSH session state for every configured FTD. A failure, parser error, or circuit-breaker state for one device must not prevent monitoring of the remaining devices.

---

# 7. Dedicated Source IP

The FTD agent should have a stable dedicated source IPv4 address wherever practical.

Preferred options include:

- dedicated macvlan/ipvlan container address;
- dedicated host secondary IP combined with controlled SNAT;
- dedicated routed container subnet/address.

Example:

```text
FTD Agent source:
10.50.99.17/32
```

Cisco FTD must be configured to permit SSH only from approved management sources, including this address.

Conceptually:

```text
configure ssh-access-list \
    10.50.99.17/32,\
    10.50.1.10/32,\
    10.50.1.11/32
```

where:

```text
10.50.99.17 = automation agent
10.50.1.10  = administrator jump host
10.50.1.11  = secondary administrator jump host
```

The SSH ACL is a Cisco-side protection independent from application security.

Consequently, theft of the automation private key alone must not be sufficient to authenticate from an arbitrary source network.

The deployment documentation must clearly warn that changing the Cisco SSH access list replaces the configured list and therefore all required management sources must be included.

---

# 8. Cisco SSH Identity

A dedicated local Cisco FTD account must be created solely for this application. For the initial multi-device deployment, the same account name and dedicated SSH keypair may be provisioned on every managed FTD to keep operations simple.

Example logical identity:

```text
ftd-shun-agent
```

The identity must not be reused for:

- administrators;
- Ansible;
- Oxidized;
- monitoring;
- configuration backups;
- other automation.

SSH public-key authentication should be used.

Password-based automation authentication should not be used.

A dedicated SSH keypair must be generated exclusively for this service.

This shared fleet identity is an intentional operational trade-off: compromise of its key would affect every FTD that accepts it. Cisco-side SSH source ACLs, strict per-device host-key pinning, and isolation of the agent are therefore mandatory on every managed device. A future deployment may split identities by device or device group without changing the Web/API authorization model.

---

# 9. Private Key Handling

The FTD private key must never be available to:

```text
Caddy
Web/BFF
REST API
database
logs
browser
```

The private key must not be:

- stored in the container image;
- stored in Git;
- stored in environment variables;
- passed as a command-line argument;
- returned by an API;
- written into logs.

---

# 10. One-Time Key Bootstrap

The preferred design is that the running SSH agent does not have permanent filesystem access to the private key.

A bootstrap sequence should be implemented.

Example:

```text
1. FTD agent starts.
2. Agent is not yet operational.
3. Credential loader reads the private key from protected storage.
4. Credential loader passes the key to the agent through a local-only IPC mechanism.
5. Agent parses the key.
6. Agent establishes and authenticates the SSH session.
7. Agent destroys all private-key material in its address space.
8. Credential loader exits or closes the bootstrap channel.
9. Bootstrap socket becomes unavailable.
10. Agent enters READY state.
```

The agent container itself should not have the private-key file mounted.

---

# 11. Secret Memory Handling

Sensitive private-key memory should use best-effort hardened handling.

Where supported, consider:

```text
memfd_secret()
```

or locked anonymous memory.

At minimum:

```text
mlock()
MADV_DONTDUMP
PR_SET_DUMPABLE=0
RLIMIT_CORE=0
```

Private-key buffers must support explicit zeroization.

After successful SSH authentication:

```text
zeroize(private_key_buffer)
drop(private_key_object)
close(bootstrap_fd)
unmap(secret_memory)
```

The design must avoid immutable language strings for private-key material wherever possible.

A memory-safe language with explicit secret zeroization support is strongly preferred for the SSH agent.

Rust is the preferred implementation language for the privileged agent.

---

# 12. SSH Session Lifecycle

Once the private key has been destroyed, the agent continues to use the already authenticated SSH transport.

If that SSH connection is lost, the agent must not silently obtain the key again.

Preferred behaviour:

```text
SSH connection lost
        ↓
agent enters FAILED state
        ↓
agent closes operational socket
        ↓
agent exits
        ↓
supervisor performs clean bootstrap/restart
```

This deliberately limits the lifetime of an exploited authenticated session.

---

# 13. Optional Reader/Writer Separation

A stronger implementation may use two agents.

## Reader Agent

Cisco role:

```text
Basic
```

Operations:

```text
show shun

show threat-detection service
    remote-access-authentication details

show threat-detection service
    remote-access-client-initiations details
```

This connection may be persistent.

## Writer Agent

Cisco role:

```text
Config
```

Allowed semantic operation:

```text
REMOVE_SHUN
```

only.

This dramatically reduces exposure of the high-privilege Cisco identity.

A future implementation may make the writer short-lived and create it only when an unshun operation is requested.

---

# 14. Internal Agent Protocol

The REST API must not send text commands to the SSH agent.

The preferred internal protocol is:

```text
AF_UNIX
SOCK_SEQPACKET
```

Message boundaries must be preserved.

Operations should use fixed binary messages.

Example:

```text
0x01 + 2-byte device ID                 LIST_SHUNS
0x02 + 2-byte device ID + 4-byte IPv4   GET_SHUN
0x03 + 2-byte device ID + 4-byte IPv4   REMOVE_SHUN
0x04 + 2-byte device ID                 GET_RA_AUTH_STATUS
0x05 + 2-byte device ID                 GET_RA_INIT_STATUS
0x06 + 2-byte device ID                 HEALTH
```

For example:

```text
03 00 07 CB 00 71 11
```

means:

```text
operation = REMOVE_SHUN
device ID = 7
IPv4      = 203.0.113.17
```

No textual IP representation crosses this trust boundary.

Unknown opcodes must cause rejection.

Invalid packet lengths must cause rejection.

For the example above:

```text
expected packet length = 7 bytes
```

Any other length must be rejected.

---

# 15. Cisco Command Generation

Cisco command strings must exist only inside the SSH agent source code.

Examples:

```text
LIST_SHUNS
→
show shun
```

and:

```text
REMOVE_SHUN + IPv4Address
→
no shun <canonical IPv4>
```

There must not be a generic function exposed across the internal API such as:

```text
ExecuteCommand(string)
```

The implementation should instead expose typed functions:

```text
ListShuns()
GetShun(ipv4)
RemoveShun(ipv4)
GetRemoteAccessAuthentication()
GetRemoteAccessClientInitiations()
```

---

# 16. Input Validation

IPv4 input must be parsed using a standard IP-address parser.

Regular expressions must not be the primary validation mechanism.

Examples that must be rejected:

```text
1.2.3.4;reload
1.2.3.4 && reload
1.2.3.4\nreload
$(reload)
`reload`
1.2.3.999
1.2.3.4/24
```

Only a valid single IPv4 address may reach the binary RPC boundary.

---

# 17. Current-State Model

The system must maintain an in-memory representation of currently observed shuns.

Suggested key:

```text
(device_id, IPv4, interface)
```

A single IP address must not be assumed to have only one shun entry.

Cisco supports an IP being shunned on more than one interface.

`device_id` must map to a configured device record containing its display hostname and management IP. The hostname is shown in every UI list and event view; the management IP is an implementation detail and must not be used as an authorization decision or display identity.

Current-state fields should include:

```text
device_id
ip
interface
first_seen_at
last_seen_at
status
detection_source
event_id
```

Typical status:

```text
ACTIVE
```

The current in-memory state is optimized for UI/API access.

UI reads must not normally result in Cisco CLI calls.

## 17.1 Device Inventory

The managed device list is static configuration, not discovered from the network. Each record includes:

```text
device_id          stable numeric internal identifier
hostname           operator-facing device name
management_ip      IPv4 address used by the SSH agent
ssh_host_key       pinned expected SSH host key or fingerprint
enabled            whether the device is monitored
```

The device inventory is mounted read-only or otherwise managed as protected deployment configuration. It must be validated at startup: duplicate IDs, duplicate hostnames, malformed IP addresses, or a missing pinned host key prevent that device from entering READY state. One shared SSH service identity may be used for all records in this initial deployment, but the agent still maintains a separate authenticated session and health state per device.

---

# 18. Persistent Event Store

Purely in-memory storage is insufficient because restart would destroy historical information.

A lightweight local SQLite database in WAL mode is recommended.

No external database service is required for the initial implementation.

Suggested persistent volume:

```text
/var/lib/ftd-shun-manager/state.db
```

SQLite stores the event history and enough current-state metadata to perform restart reconciliation.

Runtime access may additionally use an in-memory map/cache.

---

# 19. Shun Event Model

The event database should be append-oriented.

Suggested event types:

```text
SHUN_DETECTED
SHUN_REAPPEARED
SHUN_DISAPPEARED

SHUN_REMOVE_REQUESTED
SHUN_REMOVED_BY_UI
SHUN_REMOVE_NOOP
SHUN_REMOVE_FAILED

DEVICE_CONNECTED
DEVICE_DISCONNECTED
DEVICE_UNREACHABLE

SSH_AUTH_FAILED
SSH_HOSTKEY_MISMATCH

CISCO_CLI_PARSE_ERROR
CISCO_CLI_UNEXPECTED_RESPONSE

STATE_RECONCILED
SERVICE_STARTED
SERVICE_STOPPED
```

---

# 20. Detection Timestamp

When a shun appears for the first time during observation:

```text
first_seen_at = current UTC timestamp
```

This represents the first time the application observed the shun.

It must not falsely claim this is necessarily the exact Cisco creation timestamp.

A future optional integration with Cisco syslog message `733201` may provide a more accurate creation time and threat-detection reason.

---

# 21. Polling and Reconciliation

The FTD agent must periodically execute the fixed `show shun` operation.

Recommended default:

```text
poll interval = 10 seconds
```

Configurable reasonable range:

```text
5–300 seconds
```

UI/API requests must not trigger new polling.

Polling is performed by the background synchronizer.

Each successful poll produces a complete current snapshot.

The application compares:

```text
previous snapshot
vs.
current snapshot
```

and generates events.

---

# 22. Newly Detected Shun

If:

```text
current = present
previous = absent
```

generate:

```text
SHUN_DETECTED
```

or:

```text
SHUN_REAPPEARED
```

if historical records exist for the same IP/interface.

---

# 23. Still-Present Shun

If:

```text
current = present
previous = present
```

only update:

```text
last_seen_at
```

Do not generate a persistent event on every poll.

This prevents log/database flooding.

---

# 24. Disappeared Shun

If:

```text
previous = present
current = absent
```

and there is no matching successful manual removal transaction, generate:

```text
SHUN_DISAPPEARED
```

This means only:

> The entry was previously observed and is no longer reported by FTD.

Do not claim why it disappeared unless the cause is known.

Possible causes may include:

- external administrator action;
- another automation system;
- device restart;
- Cisco behaviour;
- other operational changes.

---

# 25. Manual Removal Workflow

When a user requests removal from one device in the UI:

```text
1. Authenticate and authorize user.
2. Validate the configured device ID and IPv4.
3. Create SHUN_REMOVE_REQUESTED event.
4. Send fixed REMOVE_SHUN operation to agent.
5. Agent executes fixed Cisco operation.
6. Perform immediate state verification.
7. Update in-memory state.
8. Create final audit event.
```

A successful verified removal creates:

```text
SHUN_REMOVED_BY_UI
```

Fields include:

```text
actor
actor_subject
actor_identity_provider
source_address
target_device
target_device_hostname
target_ip
interface
request_id
requested_at
completed_at
```

---

# 26. Removal No-Op

If the shun disappeared between page display and removal request:

```text
SHUN_REMOVE_NOOP
```

should be recorded.

The API should return success with:

```text
changed = false
```

rather than treat the operation as a system error.

---

# 27. Multiple Interfaces

Cisco can maintain a shun for the same IP on more than one interface.

The application must model this correctly.

The normal UI operation is device-scoped. For example:

```text
Remove 203.0.113.17 from ftd-branch-01
```

It must be clear in the UI that this affects every positively identified matching interface on that one device when Cisco exposes only the interface-independent `no shun <IPv4>` operation. The UI must display the affected interface count and names before confirmation. A per-interface removal must not be offered unless a documented and safely implemented Cisco operation exists for it.

The UI may also offer a separate bulk operation:

```text
Remove all shuns for 203.0.113.17
```

This means removal from all currently matched configured devices, not an unconstrained Cisco operation. Before dispatching writes, the Web/BFF must show the exact hostname and interface summary for each affected device and require an explicit confirmation of the IP address. The API creates one device-scoped removal request and audit result per target device, all tied to one parent request ID.

In every removal flow, the agent must remove only entries that were positively identified.

Interface strings obtained from Cisco output must never be blindly concatenated into a CLI command.

Acceptable approaches:

- map interfaces to a configured allowlist;
- assign internal numeric interface IDs;
- strictly validate parsed interfaces against device configuration;
- or safely use the documented interface-independent removal workflow where applicable.

Unknown interfaces must result in fail-closed behaviour.

---

# 28. REST API

The REST API is internal and is primarily consumed by the Web/BFF.

Suggested resources:

```text
GET    /api/v1/status
GET    /api/v1/shuns
GET    /api/v1/shuns/{ip}
DELETE /api/v1/devices/{device_id}/shuns/{ip}
POST   /api/v1/shuns/{ip}/remove-all

GET    /api/v1/history
GET    /api/v1/history/{ip}

GET    /api/v1/threat-detection/authentication
GET    /api/v1/threat-detection/client-initiations
```

The API must never expose Cisco credentials or raw SSH functionality.

`remove-all` is a semantic operation, not a command endpoint. Its request contains no Cisco CLI text and operates only on the matching configured device records returned by the current state snapshot.

---

# 29. Optional API-Key Authentication

The low-level REST API may support optional API-key authentication for future automation use.

Example:

```text
Authorization: Bearer <token>
```

Keys should support scopes:

```text
shun:read
shun:remove
history:read
threat:read
```

API keys must:

- contain strong random entropy;
- be stored hashed;
- support disable/revoke;
- optionally expire;
- optionally contain allowed source CIDRs.

API-key support must not require exposing the REST API to the Internet.

---

# 30. Web Authentication

The web interface must require Authelia authentication through Caddy ForwardAuth. The FTD service must not implement password authentication, LDAP bind authentication, or user-directory synchronization itself.

Authelia initially authenticates against its protected local user file. It may later authenticate against LDAP(S), Active Directory, or another directory supported by Authelia. Caddy must remove client-supplied `Remote-User`, `Remote-Groups`, `Remote-Email`, and `Remote-Name` headers before forwarding a request, then set them only from a successful Authelia ForwardAuth response.

The Web/BFF accepts these headers only over its Caddy-owned Unix Domain Socket. It makes authorization decisions from the authenticated user and explicitly mapped groups or roles, never from a browser-supplied header or display name.

Write permission should be separate from read-only permission.

Example roles:

```text
Viewer
Operator
Administrator
```

Only Operator and Administrator may remove shuns.

Suggested Authelia group mappings:

```text
ftd-shun-viewers       -> Viewer
ftd-shun-operators     -> Operator
ftd-shun-administrators -> Administrator
```

The immutable Authelia username, login/display name, and mapped role set must be retained with each write audit event.

## Sensitive-Operation Reauthentication

Removal of a shun requires a session no older than the configured maximum age. Authelia enforces this through its session expiration; when expired, Caddy redirects the user to log in again.

The limit is deliberately operationally configurable rather than hard-coded:

```text
AUTH_SENSITIVE_ACTION_MAX_AGE=24h
```

One hour (`1h`) and one day (`24h`) are both supported practical policies. The default should be `24h`; a deployment that needs stronger assurance may set `1h`. This setting must be read from a protected, non-versioned `.env` file or equivalent secret/configuration mechanism and recorded in startup diagnostics without exposing other secrets.

---

# 31. CSRF Protection

Because the application performs security-sensitive state changes, browser requests must be protected against CSRF.

At minimum:

- SameSite cookies;
- anti-CSRF tokens for state-changing requests;
- POST/DELETE write semantics;
- no state changes via GET.

---

# 32. UI Requirements

The primary page should show current shuns.

Suggested columns:

```text
IP Address
Interface
Device hostname
First Seen
Last Seen
Age
Status
Previous occurrences
Actions
```

An entry should visually distinguish:

```text
currently active
manually removed
externally disappeared
reappeared
```

Historical entries must remain searchable after removal.

For every row, the primary action is **Remove from this device**. It opens a confirmation dialog showing the device hostname, IP, and affected interfaces. A separate **Remove from all devices** action is shown only on the IP detail page and uses the bulk confirmation workflow defined above.

---

# 33. IP Detail View

Selecting an IP should show its lifecycle.

Example:

```text
203.0.113.17

Affected device:
ftd-branch-01

Current state:
ACTIVE

First observed:
2026-10-13 10:11:42 UTC

Last observed:
2026-10-13 10:18:02 UTC

Interface:
outside

History:

10:11:42  SHUN_DETECTED
10:18:20  SHUN_REMOVE_REQUESTED by user@example
10:18:21  SHUN_REMOVED_BY_UI
```

---

# 34. Threat Detection View

The UI should optionally expose the tracked Remote Access threat-detection counters obtained from fixed Cisco commands.

For example:

```text
203.0.113.18

Service:
remote-access-authentication

Count:
17 / 20

Hold-down remaining:
432 seconds
```

These entries are not yet shunned and must be visually distinct from active shuns.

---

# 35. Request Rate Limiting

Low-level throttling is required even though the service is internal.

Web/API rate limiting should be applied by:

```text
client identity
source IP
operation type
```

Example default limits:

```text
read:
60 requests/minute/client

write:
10 requests/minute/client

global:
300 requests/minute
```

Write limits should be substantially lower than read limits.

---

# 36. Cisco-Side Operation Throttling

User traffic must not directly control Cisco query rate.

The background poller controls read frequency.

Maximum concurrent SSH operations per FTD should default to:

```text
1
```

Write operations must be serialized.

A bounded internal queue must be used.

Queue overflow should return:

```text
429 Too Many Requests
```

or:

```text
503 Service Unavailable
```

without opening additional Cisco SSH sessions.

---

# 37. SSH Connection Security

The agent must perform strict SSH host-key verification.

The Cisco host key must be pinned.

Behaviour on mismatch:

```text
FAIL CLOSED
```

No equivalent of:

```text
StrictHostKeyChecking=no
AutoAddPolicy
```

is permitted.

Host-key changes must require explicit administrator action.

---

# 38. Cisco CLI Parsing

Cisco output must be treated as an external protocol with version-dependent formatting.

Each supported operation requires a dedicated parser.

Example parser modules:

```text
parse_show_shun()
parse_remote_access_authentication()
parse_remote_access_client_initiations()
parse_no_shun_result()
```

A generic text parser should not be shared blindly between unrelated commands.

---

# 39. Parser Versioning

Parser behaviour should be versioned independently from the application.

Example:

```text
show_shun_parser_v1
ra_auth_parser_v1
ra_client_init_parser_v1
```

The service should identify the FTD software version during startup using a fixed permitted read-only operation.

The detected version should be included in diagnostic events.

---

# 40. Fail-Closed CLI Parsing

If Cisco changes CLI output and the parser can no longer confidently interpret the response:

```text
DO NOT GUESS
```

The affected operation must fail.

For read failures:

```text
state = STALE / UNKNOWN
```

For write-result uncertainty:

```text
result = UNVERIFIED
```

No success response may be fabricated from partially understood output.

---

# 41. Cisco Console Error Logging

Unexpected Cisco responses are operationally important and must generate dedicated structured events.

Example:

```json
{
  "event": "CISCO_CLI_PARSE_ERROR",
  "device": "ftd-main",
  "operation": "LIST_SHUNS",
  "ftd_version": "x.y.z",
  "parser": "show_shun_parser_v1",
  "timestamp": "...",
  "request_id": "...",
  "output_sha256": "...",
  "output_excerpt": "..."
}
```

This is specifically intended to detect:

- Cisco CLI formatting changes;
- firmware-dependent output differences;
- changed prompts;
- unexpected error messages;
- unsupported commands;
- privilege changes.

---

# 42. Raw Cisco Output Handling

Unexpected raw output may be extremely useful for debugging but must be handled carefully.

The system should provide two levels.

## External log event

Send:

```text
operation
device
firmware version
parser version
error category
SHA-256 of complete raw output
sanitized/truncated excerpt
```

Recommended excerpt maximum:

```text
4096 bytes
```

## Local diagnostic record

Optionally retain a larger sanitized response locally.

Recommended maximum:

```text
64 KiB
```

for a limited retention period.

Raw output must:

- have ANSI escape sequences removed;
- remove unsafe control characters;
- normalize line endings;
- be JSON escaped when exported;
- never include private-key material;
- never include API authorization headers.

---

# 43. Cisco Write Error Handling

For a failed `REMOVE_SHUN` operation, capture:

```text
requested IPv4
device
interface if applicable
Cisco response classification
sanitized Cisco response excerpt
timestamp
request ID
actor
```

Generate:

```text
SHUN_REMOVE_FAILED
```

The UI should show a human-readable error without exposing a complete internal SSH transcript.

---

# 44. Write Verification

A Cisco CLI response alone must not be considered sufficient proof of success.

After `REMOVE_SHUN`:

```text
execute write
        ↓
immediate read/reconciliation
        ↓
verify target no longer present
```

Only then produce:

```text
SHUN_REMOVED_BY_UI
```

If the write appears successful but verification cannot be completed:

```text
result = UNVERIFIED
```

and generate an operational alert.

---

# 45. Structured Application Logging

All application logs should use structured JSON.

Example:

```json
{
  "timestamp": "2026-10-13T11:42:18.123Z",
  "level": "INFO",
  "service": "ftd-shun-api",
  "event": "SHUN_REMOVED_BY_UI",
  "device": "ftd-main",
  "device_hostname": "ftd-main.example.internal",
  "ip": "203.0.113.17",
  "interface": "outside",
  "actor_subject": "oidc-subject-id",
  "actor_display_name": "user@example",
  "actor_roles": ["Operator"],
  "request_id": "..."
}
```

Plain unstructured log lines should be avoided for application events.

---

# 46. Log Categories

Logs should distinguish at least:

```text
audit
security
operation
device
parser
application
```

Examples:

```text
AUDIT_SHUN_REMOVE
SECURITY_AUTH_FAILURE
DEVICE_SSH_DISCONNECTED
DEVICE_HOSTKEY_MISMATCH
PARSER_CISCO_OUTPUT_CHANGED
APPLICATION_DATABASE_ERROR
```

---

# 47. External Log Collectors

The service must support forwarding or collection by standard log systems.

Preferred strategy:

```text
structured JSON to stdout
```

so the container runtime or host collector can forward logs.

Additionally support optional:

```text
RFC 5424 syslog
```

over:

```text
TCP
TLS
```

UDP may be supported but should not be preferred.

The application should not require a specific SIEM/log collector product.

---

# 48. Audit Log Durability

Security-relevant audit events should be stored both:

```text
SQLite event journal
+
external structured logging
```

where configured.

Failure of the external log collector must not block normal shun monitoring.

However, failed log delivery should itself generate a local operational event.

SQLite is the local source of truth for the web UI, history, and audit trail. Structured JSON emitted to stdout is intentionally suitable for collection by the host/container runtime and forwarding to the organization's log-collection system. Optional direct RFC 5424 forwarding remains available where required.

---

# 49. Request Correlation

Every web/API write request must receive a unique correlation ID.

Example:

```text
request_id = UUID
```

The ID must appear in:

```text
Web request log
REST API log
agent operation
SQLite event
external log
error event
```

This makes a complete operation traceable across components.

---

# 50. Database Design

A minimal SQLite schema should include logical tables equivalent to:

```text
devices
shun_state
shun_events
users_or_actors
schema_metadata
```

`shun_state` represents the most recently known durable state.

`shun_events` represents immutable lifecycle events.

---

# 51. Example shun_state

Fields:

```text
device_id
device_hostname
ip_binary
interface
active
first_seen_at
last_seen_at
last_changed_at
last_event_id
```

IPv4 should preferably be stored numerically/binary rather than free-form text.

---

# 52. Example shun_events

Fields:

```text
id
timestamp
device_id
ip_binary
interface
event_type
actor
actor_subject
actor_identity_provider
actor_roles_json
source
request_id
details_json
```

Event rows should normally be append-only.

Historical rows should not be rewritten when a shun disappears.

---

# 53. Restart Reconciliation

On application startup:

```text
1. Load previous durable state from SQLite.
2. Establish Cisco SSH monitoring session.
3. Obtain current show shun snapshot.
4. Compare stored state with current Cisco state.
5. Generate reconciliation events.
6. Populate current in-memory state.
7. Mark service READY.
```

Entries present both before and after restart preserve their original `first_seen_at`.

---

# 54. Unknown Disappearance During Downtime

If an entry was active before shutdown and absent when the service returns, the system cannot know exactly when or why it disappeared.

Generate:

```text
SHUN_DISAPPEARED
```

with metadata such as:

```text
observed_during_reconciliation = true
exact_disappearance_time_unknown = true
```

Do not fabricate a precise disappearance timestamp.

---

# 55. Service Health States

Suggested device states:

```text
STARTING
READY
STALE
DEGRADED
DISCONNECTED
AUTH_FAILED
HOSTKEY_ERROR
PARSER_ERROR
```

The UI must clearly indicate when the displayed shun data is stale.

Never show stale information as current without indication.

---

# 56. Circuit Breaker

Repeated Cisco failures must not cause an SSH reconnection storm.

Suggested defaults:

```text
5 consecutive failures
→ open circuit
→ 30-second cooldown
```

Use bounded exponential backoff with a configured maximum.

---

# 57. Container Hardening

All application containers should use:

```text
read_only: true
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
```

where compatible.

Containers should run with dedicated non-root UIDs.

Writable locations should be explicitly mounted.

Temporary directories should preferably use:

```text
tmpfs
noexec
nosuid
nodev
```

---

# 58. SSH Agent Image

The privileged FTD agent should have the smallest practical runtime image.

Preferred:

```text
Rust static binary
+
scratch
```

or a minimal equivalent.

The image should not contain:

```text
/bin/sh
/bin/bash
ssh executable
curl
wget
python
package manager
compiler
debugger
```

The SSH protocol must be implemented through a library.

---

# 59. System Call Hardening

The agent should use a restrictive seccomp profile where practical.

Unnecessary capabilities and dangerous system calls should be denied.

Particularly avoid allowing runtime use of:

```text
execve
execveat
ptrace
mount
setns
unshare
bpf
keyctl
```

if the selected runtime and libraries do not require them.

---

# 60. Persistent Volumes

Only components that need persistence receive writable volumes.

Expected persistent storage:

```text
SQLite database
Caddy certificate/config storage
```

The SSH agent should have:

```text
no persistent writable volume
```

The Cisco private key must not be stored in the agent's persistent filesystem.

---

# 61. Backup

The SQLite event database should be included in normal server backup.

It contains operational history but no Cisco credentials.

Backup restoration must not automatically restore or recreate an FTD private key.

Credentials are managed separately.

---

# 62. API/UI Flood Protection

The web/API stack must implement request throttling.

Cisco polling itself is independent from UI request volume.

Therefore:

```text
1000 page refreshes
```

must not produce:

```text
1000 show shun commands
```

The current page must be rendered entirely from application state.

---

# 63. Metrics

Optional Prometheus-style metrics should include:

```text
ftd_shun_active
ftd_shun_detected_total
ftd_shun_removed_total
ftd_shun_disappeared_total

ftd_agent_connected
ftd_agent_poll_failures_total
ftd_agent_parse_errors_total
ftd_agent_ssh_reconnects_total

http_requests_total
http_rate_limited_total
```

Do not use individual shunned IP addresses as Prometheus labels.

---

# 64. Testing Against Cisco Output

Each Cisco parser must have fixture-based tests.

Store sanitized examples of known Cisco CLI output for supported versions.

Tests should cover:

```text
normal output
empty output
one shun
multiple shuns
same IP on multiple interfaces
unexpected whitespace
changed column spacing
Cisco warning text
Cisco error text
partial output
truncated output
changed prompt
unsupported command
```

---

# 65. Parser Fuzz Testing

Cisco output parser components should undergo fuzz testing.

Parser crashes caused by malformed or unexpected Cisco output are unacceptable.

Malformed input should result in:

```text
CISCO_CLI_PARSE_ERROR
```

rather than process termination.

---

# 66. Security Testing

Explicitly test attempts such as:

```text
1.2.3.4;reload
1.2.3.4 && reload
1.2.3.4\nreload
$(reload)
`reload`
very large input
binary garbage
invalid RPC opcode
oversized RPC packet
duplicate REMOVE requests
```

No such input may result in arbitrary Cisco command execution.

---

# 67. Web Security

The web component must implement standard internal-web security protections including:

```text
secure cookies
HttpOnly
SameSite
CSRF protection
Content-Security-Policy
X-Content-Type-Options
clickjacking protection
reasonable request size limits
```

Caddy should apply appropriate HTTPS security headers.

---

# 68. HTTPS

Caddy terminates HTTPS using an organization-approved certificate.

Plain HTTP should either:

```text
not listen
```

or only redirect to HTTPS where operationally required.

The application must never be intentionally exposed to the public Internet.

---

# 69. Default-Deny Philosophy

Any unsupported, unknown, malformed or ambiguous state must fail closed.

Examples:

```text
unknown RPC opcode → reject
invalid IPv4 → reject
unknown interface → reject write
unexpected Cisco prompt → parser error
host-key mismatch → disconnect
unknown Cisco write response → unverified failure
database corruption → no writes
```

---

# 70. Explicitly Out of Scope

The application must not implement:

```text
manual shun creation
clear shun
arbitrary show commands
configuration changes
VPN configuration
FMC configuration
file transfer
expert mode
Linux shell
Cisco debugging
reload/reboot
configuration backup
terminal emulation
generic SSH proxy
```

Any future extension that introduces a new Cisco command must require explicit source-code implementation and security review.

---

# 71. Acceptance Criteria

The first production-ready release is accepted when all of the following are true:

1. The Web UI displays the complete active `show shun` state from FTD.

   The UI displays the configured device hostname for every active shun.

2. UI page refreshes do not generate Cisco CLI queries.

3. Newly observed entries receive a durable `first_seen_at`.

4. Entries that disappear without application action generate `SHUN_DISAPPEARED`.

5. Entries removed from the UI generate a distinct verified `SHUN_REMOVED_BY_UI` event.

6. Shun lifecycle history survives application restart.

7. The REST API has no Cisco credential.

8. The Web container has no Cisco credential.

9. Caddy is the only component with a published TCP port.

10. Only the SSH agent has network connectivity to FTD management TCP/22.

11. Cisco SSH access is restricted to approved source IP addresses.

12. The FTD agent does not have the private-key file permanently mounted.

13. Private-key memory is explicitly destroyed after SSH authentication.

14. Strict SSH host-key checking is enforced.

15. Arbitrary Cisco commands cannot be passed through Web, API or internal RPC.

16. The agent does not contain a shell or external SSH executable.

17. Invalid or unexpected Cisco output causes fail-closed parser behaviour.

18. Cisco CLI parser failures generate structured diagnostic logs.

19. Manual writes are verified by subsequent Cisco state observation.

20. All write operations have a complete actor/request audit trail.

21. Application logs can be collected by a standard external logging platform.

22. HTTP/API flooding cannot produce a proportional increase in Cisco SSH operations.

23. Application restart correctly reconciles durable state with the current Cisco state.

24. A stolen Cisco private key cannot authenticate from arbitrary source IP addresses because of Cisco-side SSH management ACL restrictions.

25. No component exposes a generic shell, command or SSH execution interface.

26. The service supports device-scoped removal and an explicitly confirmed bulk removal across matched configured devices, with one auditable result per device.

27. Web authentication uses Authelia ForwardAuth; the application has no LDAP password-handling code.

28. Removal requires a recent authentication within the configured `AUTH_SENSITIVE_ACTION_MAX_AGE` interval.

---

# 72. Preferred Initial Technology Stack

Recommended implementation:

```text
Host:
Ubuntu Server

Container runtime:
Podman + Quadlet
or
Docker + Compose

Reverse proxy:
Caddy

Web/BFF:
small server-side web application

Authentication gateway:
Authelia + Caddy ForwardAuth
local file backend initially; LDAPS migration path
SQLite storage and optional MFA configured in Authelia

REST API:
Python/FastAPI or Go

Privileged SSH agent:
Rust

Persistent state/history:
SQLite + WAL

Runtime current state:
in-process memory

IPC:
Unix Domain Sockets
AF_UNIX/SOCK_SEQPACKET for security-critical agent RPC

Logging:
structured JSON stdout
optional RFC5424 TCP/TLS

HTTPS:
Caddy with organization-controlled certificate
```

---

# 73. Design Priority

Development priorities, in order:

```text
1. Prevent arbitrary FTD command execution.
2. Protect Cisco credentials.
3. Restrict network reachability.
4. Produce reliable audit history.
5. Fail safely when Cisco output changes.
6. Minimize Cisco-side load.
7. Provide a simple operator experience.
8. Keep implementation small enough to audit.
```

Feature count is explicitly less important than maintaining these properties.

The final system should remain intentionally small, predictable, auditable, and difficult to repurpose into a generic privileged FTD management channel.
