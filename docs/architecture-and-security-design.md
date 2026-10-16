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

Sections 1–73 describe the current removal-oriented scope. The approved next
increment in [Section 74](#74-approved-next-increment-queued-device-cycles-and-manual-imports)
and the [Development Plan](development-plan.md) extends that scope with queued
device cycles and one-time manual shun imports. The durable removal queue is
implemented; a bounded-session protocol is experimental and opt-in pending lab
validation. ADD transport and private staged-only admission are default-off;
executable imports remain planned. Default legacy protocol and
operating procedures remain in effect until the documented gates are completed.

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

Cisco FTD does not provide an application-specific per-command CLI authorization model for this use case; it provides broad `Basic` and `Config` roles.

The required FTD commands must be tested with `Basic` before a device is admitted. On the recorded non-production Firepower 1010 / FTD 7.6.6 fixture, a `Basic` user successfully executed both `show shun` and `no shun <IPv4> interface management`. Therefore, `Basic` is the required service-account role for this product profile. `Config` must not be used unless a documented exception is approved for a specific FTD version or deployment.

The application must still enforce its own operation-level separation, because `Basic` is broader than this application's two fixed Cisco operations and FTD has no way to authorize just those operations.

The security model must explicitly acknowledge:

> A complete arbitrary-code execution compromise of the privileged SSH executor while it owns an authenticated FTD session may allow an attacker to use operations available to that FTD role beyond the intended application functionality. A `Config`-role exception substantially increases this risk.

The architecture must make such a compromise difficult, short-lived, and isolated.

Compromise of any externally reachable component must not directly provide:

- the FTD SSH password;
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

Consequently, theft of the automation credential alone must not be sufficient to authenticate from an arbitrary source network.

The deployment documentation must clearly warn that changing the Cisco SSH access list replaces the configured list and therefore all required management sources must be included.

---

# 8. Cisco SSH Identity

A dedicated local Cisco FTD account must be created solely for this application. For the initial multi-device deployment, the same account name and independently generated high-entropy password may be provisioned on every managed FTD to keep operations simple.

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

The supported FPR1010 / FTD 7.6.6 profile uses SSH password authentication. The `Basic` account required for least privilege cannot run `configure ssh pubkeys add` to associate a public key with itself; the command is restricted to a more privileged user. Promoting the service account to `Config` solely to use a public key is prohibited by the normal deployment profile.

The password must be a unique, high-entropy secret supplied only to the isolated agent as a read-only runtime secret. It must never be reused for administration, interactive operations, or a second system.

Password authentication is an explicit FTD compatibility trade-off, compensated by the `Basic` role, fixed agent operations, strict server host-key pinning, source-address restrictions on FTD, host egress restrictions, a short-lived SSH session per operation, and isolated secret delivery.

This shared fleet identity is an intentional operational trade-off: compromise of its password would affect every FTD that accepts it. Cisco-side SSH source ACLs, strict per-device host-key pinning, and isolation of the agent are therefore mandatory on every managed device. A future deployment may split identities by device or device group without changing the Web/API authorization model.

---

# 9. SSH Password Handling

The FTD SSH password must never be available to:

```text
Caddy
Web/BFF
REST API
database
logs
browser
```

The password must not be:

- stored in the container image;
- stored in Git;
- stored in environment variables;
- passed as a command-line argument;
- returned by an API;
- written into logs.

---

# 10. Current v1 Credential Model and Deferred One-Time Bootstrap

The initial deployment intentionally uses one dedicated FTD `Basic` account and one high-entropy SSH password for the managed fleet. The password is delivered only to the non-root agent as a read-only runtime secret. It is not present in the image, environment, command line, API, database, logs, Web/BFF, or REST API.

This is the chosen v1 FTD-compatibility trade-off. It preserves the important isolation boundaries: only the agent has the password and a route to FTD; FTD-side source-address restrictions and host egress policy remain mandatory.

One-time bootstrap is a future hardening option, not a v1 release prerequisite. If adopted, the running SSH agent should not have permanent filesystem access to the password.

Example:

```text
1. FTD agent starts.
2. Agent is not yet operational.
3. Credential loader reads the password from protected storage.
4. Credential loader passes the password to the agent through a local-only IPC mechanism.
5. Agent establishes and authenticates the SSH session.
6. Agent destroys password material in its address space.
7. Credential loader exits or closes the bootstrap channel.
8. Bootstrap socket becomes unavailable.
9. Agent enters READY state.
```

In a future one-time-bootstrap implementation, the agent container itself should not have the password file mounted. V1 is an explicit exception: it mounts a read-only Docker runtime secret only in the isolated non-root agent container.

---

# 11. Secret Memory Handling

Sensitive password memory should use best-effort hardened handling.

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

Password buffers must support explicit zeroization where the selected SSH library permits it. The v1 agent reads the password into a zeroizing buffer, authenticates a short-lived SSH operation, then drops and zeroizes the source buffer before it runs Cisco commands. The SSH library's internal authentication-message copy is outside the agent's direct zeroization control.

For a future one-time bootstrap implementation, after successful SSH authentication:

```text
zeroize(password_buffer)
close(bootstrap_fd)
unmap(secret_memory)
```

The design must avoid immutable language strings for password material wherever possible.

A memory-safe language with explicit secret zeroization support is strongly preferred for the SSH agent.

Rust is the preferred implementation language for the privileged agent.

---

# 12. SSH Session Lifecycle

The v1 removal agent establishes a new SSH session for each semantic write and closes it after post-write verification. It does not retain an authenticated write session between user requests. This keeps the state model simple and lets each operation re-check the pinned host key.

The experimental Section 74 cycle extension is the explicit opt-in exception:
one authenticated session spans bounded sequential operations and is closed at
cycle end, never retained between cycles.

The supported FPR1010 / FTD 7.6.6 profile requires an interactive SSH PTY and shell; SSH `exec` requests are not a supported command path. The agent must therefore:

1. authenticate and request an `xterm` PTY plus an interactive shell;
2. wait for the exact FTD user prompt `>` within the configured operation timeout;
3. send one source-defined typed command followed by newline;
4. read until the next exact prompt; and
5. remove only the known command echo and prompt envelope before passing the response to the strict command parser.

It must never use a fixed sleep to wait for the login banner. An EOF, unexpected prompt, invalid UTF-8, oversized output, unexpected removal output, or timeout is a fail-closed operation failure. The agent still sends no arbitrary text across a trust boundary.

The future polling reader may use a persistent connection only after lab measurement demonstrates that reconnecting at the configured polling interval is unsuitable. A persistent reader must reconnect safely after loss and must never cause browser/API reads to trigger Cisco operations.

---

# 13. Optional Reader/Writer Separation

Reader/writer separation is not part of v1. The same isolated agent and fleet identity execute the small typed read/write operation set. This is an intentional simplicity decision, not an authorization boundary: FTD-side SSH source restrictions, host egress rules, pinned host keys, and the agent's fixed operations are mandatory.

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

`LIST_SHUNS` has a distinct fixed binary success response. Its maximum total
size is 64 KiB and it contains no Cisco text beyond a validated interface name:

```text
0x00 + 2-byte entry count + repeated entries
entry = 4-byte IPv4 + 1-byte ASCII interface length + interface bytes
```

The agent must reject a parsed `show shun` line unless it exactly matches the
validated FTD layout: `shun (<allowlisted-interface>) <IPv4> <IPv4-mask> <u16>
<u16> <u16>`. The API must reject a truncated, oversized, duplicate, malformed,
or trailing-byte response. A rejected snapshot must never be reconciled as an
empty snapshot.

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
no shun <canonical IPv4> interface <agent-observed allowlisted interface>
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
allowed_interfaces explicit interface allowlist for write operations
```

The device inventory is mounted read-only or otherwise managed as protected deployment configuration. It must be validated at startup: duplicate IDs, duplicate hostnames, malformed IP addresses, or a missing pinned host key prevent that device from entering READY state. One shared SSH service identity may be used for all records in this initial deployment, but the agent still maintains a separate authenticated session and health state per device.

`allowed_interfaces` is required before writes are enabled. The agent may remove a shun only from an interface both returned by its strict `show shun <IPv4>` parser and listed for that device. This protects the fixed `no shun <IPv4> interface <name>` command form from unexpected device output; an unlisted or malformed interface causes the operation to fail closed.

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

## History retention

`FTD_SHUN_HISTORY_RETENTION_DAYS` controls the local lifecycle of historical
data. Its default is `366` days and the accepted range is 1 through 3653 days.
Once per day, the synchronizer removes event rows older than the calculated UTC
cutoff and inactive `shun_state` rows whose `last_changed_at` is older than the
same cutoff. It never removes an active shun-state row.

Terminal operation-queue jobs and their orphaned request records follow the
same retention period. Unfinished QUEUED/RUNNING jobs are not purged; expiry
or recovery must settle them first. Queue cleanup records its deletion count
in a new `HISTORY_RETENTION_PURGED` event.

The history store remains append-only inside its configured retention window.
When a purge removes one or more records, it adds a new
`HISTORY_RETENTION_PURGED` event with the cutoff and deletion counts. The
retention change is intentionally irreversible in the live database; operators
must take a SQLite-safe backup before reducing the configured period. Restoring
an older backup is a separate recovery action and must be followed by a
successful FTD snapshot before its active state is trusted.

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

SHUN_TRUSTED_AUTO_REMOVE_REQUESTED
SHUN_TRUSTED_AUTO_REMOVED
SHUN_TRUSTED_AUTO_REMOVE_NOOP
SHUN_TRUSTED_AUTO_REMOVE_FAILED

SHUN_OPERATION_QUEUED
SHUN_OPERATION_RUNNING
SHUN_OPERATION_VERIFIED
SHUN_OPERATION_NOOP
SHUN_OPERATION_FAILED
SHUN_OPERATION_UNVERIFIED
SHUN_OPERATION_RECONCILED_ABSENT
SHUN_OPERATION_CANCELLED
SHUN_OPERATION_DEFERRED
OPERATION_QUEUE_RESTORE_SUSPENDED

HISTORY_RETENTION_PURGED

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

The FTD agent must periodically execute the fixed `show shun` operation through the background synchronizer.

The v1 polling policy is configurable. Its default is:

```text
baseline poll interval = 5 minutes
```

The implementation configuration names are:

```text
FTD_SHUN_POLL_INTERVAL=5m
FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL=60s
FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS=
```

The baseline interval must accept a practical range of `60s` to `24h`. The interactive minimum interval must not be lower than `60s`.

An authenticated state-viewing Web/BFF request (list, detail, history, or future search) may notify the synchronizer that an interactive refresh is useful. This notification is a local scheduling hint, not a Cisco operation. It must never synchronously open SSH or delay the HTTP response for FTD output.

At most one interactive refresh sweep may be queued globally within the configured interactive minimum interval. The synchronizer applies the same minimum interval to each individual enabled device. Repeated page loads, searches, multiple users, browser refreshes, and API flooding therefore cannot create a proportional number of FTD sessions.

An interactive hint is considered only while there is active authenticated Web/BFF use. If there is no such activity, the service performs only the baseline polling schedule.

Each successful poll produces a complete current snapshot.

The initial process sweep runs asynchronously at startup. It establishes state
without delaying an HTTP request; an unsuccessful device does not alter that
device's stored snapshot. The synchronizer records per-device success or
failure metadata and a next-baseline timestamp. The BFF uses that metadata for
the visible freshness state and browser countdown.

## Trusted-IP automatic removal

Protected IPs are an exact IPv4 allowlist stored authoritatively in SQLite,
empty by default. All authenticated users manage addresses, names, comments and enabled
state in the authenticated UI. CIDRs, hostnames, ranges and IPv6 are rejected.
Policy writes require CSRF protection, a non-empty authenticated subject, a matching
policy revision (409 on concurrent edits), and an atomic append-only audit event.
The policy is bounded to 1,000 entries and applies across the enabled fleet.

An additive migration imports the legacy `FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS`
value once, atomically with a durable import marker, even for an empty list.
After that marker exists, the environment variable is never read for policy:
disabled/deleted entries cannot reappear on restart. Remove the obsolete value
after verifying migration. Back up SQLite before upgrade; restoring an older
database also restores its policy and migration marker.

After the agent returns a complete, successfully parsed snapshot for a device,
the synchronizer compares each observed address with this policy. For every
exact match it admits a request into the shared durable removal queue. The
worker sends the existing fixed `REMOVE_SHUN` operation within the same
cycle budget as manual work (one removal in default mode; bounded multiple
removals in experimental session mode), and records a policy
success only after the agent's normal post-write verification. It uses the
actor `system:trusted-ip-policy`, never a browser identity. The policy does
not run after an unavailable or malformed snapshot, does not broaden the
agent protocol, and does not permit a command or route supplied by a user.

Each policy request, verified removal, verified no-op, and failure is retained
as an append-only event. A failure leaves the locally observed shun active and
visible. Operators must use this policy only for carefully verified addresses
whose automatic removal is intended on every enabled FTD device.

`GET /api/v1/status` exposes enabled addresses and a durable policy revision.
Its separate `disabled_protected_ips` list contains only disabled entries' IPs
for display; it never grants automatic-removal eligibility.
The separate Protected IPs page shows enabled and disabled entries, names,
comments, observed active-shun counts, and latest retained verified automatic
removal (`Never recorded` if absent). Every user admitted by Authelia may
add/edit/enable/disable/delete, including users without mapped application groups.
Directory roles are retained unchanged in audit, not promoted to Administrator.
Admission to this service must therefore be restricted to people trusted to
change the fleet-wide protection policy. Deletion requires typing the
IP. These local changes do not execute device commands. Disabled/deleted policy
requests are cancelled before the next claim in the same SQLite write
transaction; independent manual requests survive. RUNNING work is not interrupted.
The executor revalidates live SQLite policy before every claim, including within
a multi-item session. Newly enabled protection takes effect at a successful
snapshot through the existing queue and budgets, not a new out-of-band writer.
Enabled entries have green text-labelled badges; disabled entries have red
text-labelled badges. A disabled entry with locally observed active shuns has
a red warning in the policy list, current-shun/search rows and IP detail view.
The warning explicitly states that automatic removal is off. Enabled matching
shuns retain their existing amber operational warning. These display states
do not issue device operations or change policy/queue authorization.

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
3. Atomically persist the idempotent queued intention and SHUN_REMOVE_REQUESTED event.
4. Return 202 Accepted and the parent request/operation ID; do not claim removal.
5. The leased background worker refreshes state and claims an eligible queued item.
6. Send fixed REMOVE_SHUN only for a positively observed target.
7. Agent executes its fixed operation and immediate state verification.
8. Atomically persist verified local state, queue outcome, and final audit events.
```

A successful verified removal creates:

```text
SHUN_REMOVED_BY_UI
```

The queue panel reports pending and final states independently of HTTP
admission. Duplicate intentions share one job while preserving every actor.
The same key/payload returns the original request even after completion;
changed scope or target is a conflict. Unstarted manual requests may be
cancelled by their requester or an Administrator. Expired/disabled work fails
before dispatch. A lost/rejected agent response or abandoned running worker
produces UNVERIFIED, never a fabricated success or automatic replay.

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
POST   /api/v1/refresh-hint
GET    /api/v1/shuns
GET    /api/v1/shuns/{ip}
DELETE /api/v1/devices/{device_id}/shuns/{ip}
POST   /api/v1/shuns/{ip}/remove-all
POST   /api/v1/operations/{operation_id}/cancel

GET    /api/v1/history
GET    /api/v1/history/{ip}
GET    /api/v1/search?ip={exact_ipv4_or_dotted_prefix}

GET    /api/v1/threat-detection/authentication
GET    /api/v1/threat-detection/client-initiations
```

The API must never expose Cisco credentials or raw SSH functionality.

The two removal routes return `202 Accepted` with `operation_id` (the parent
request ID) and `replayed`. They do not return immediate `changed` results.
An optional UUID `Idempotency-Key` header makes retries explicit; otherwise
the API assigns a UUID. `/status` includes queue revision, retained outcome
counts, next eligible cycle, and independently bounded job groups: up to 100
active jobs (RUNNING first, then FIFO), 20 failed/unverified jobs, and the latest
20 other completed jobs, with associated parent requests. Counts cover all
retained jobs, not only displayed rows. No queue record is deleted to hide it.
Counts and selected groups use one consistent SQLite read snapshot, including
when a different worker completes an item during status collection.
The cancel route requires the mapped write role and enforces requester/admin
ownership; running work cannot be cancelled. Queue acceptance, updates, and
audit share SQLite transactions.

`/api/v1/search` searches only the bounded local SQLite active-state and
retained event history. It accepts a full IPv4 address or a dotted IPv4 prefix,
returns at most 100 addresses, and never triggers a Cisco operation. For each
match it returns the current-state flag, last observed time, last verified
removal time when applicable, latest event time, device count, and whether the
exact address is in the configured trusted-IP policy.

`POST /api/v1/refresh-hint` runs the scheduler transition on its owning event
loop and returns the resulting refresh metadata in the same `202` response.
It never waits for a device operation. The Web/BFF uses this response for the
button state and exposes a separate authenticated, same-origin status view for
browser polling; neither route exposes the agent socket or FTD credentials.

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
Every authenticated user may change Protected IP policy, regardless of mapped
roles. This explicit policy-management exception does not change manual shun
removal roles or ownership/Administrator checks for queue cancellation. Policy
changes use the same Authelia sensitive-action session age as other browser writes.

Suggested Authelia group mappings:

```text
ftd-shun-viewers       -> Viewer
ftd-shun-operators     -> Operator
ftd-shun-administrators -> Administrator
```

The immutable Authelia username, login/display name, and mapped role set must be retained with each write audit event.

## Sensitive-Operation Reauthentication

Admission or cancellation of a manual removal request requires a session no older than the configured maximum age. Authelia enforces this through its session expiration; when expired, Caddy redirects the user to log in again.

Queue admission delegates the captured write authorization for at most 15
minutes (or the configured sensitive-action age, if shorter). The executor
checks this expiry and the captured role before dispatch; it does not retain
browser credentials or revalidate the live Authelia session/directory role.
Logout or role revocation after admission therefore does not revoke an already
admitted request within that bounded window. Cancel unstarted requests explicitly.

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

The page must display data freshness rather than imply that every page render is a live Cisco query. At minimum it shows:

```text
last successful refresh
next baseline refresh countdown
interactive refresh state: idle, queued, or rate-limited
```

The countdown may update in the browser, but its displayed state must originate from synchronizer metadata. If a device or snapshot is stale, unavailable, or has a parser error, the UI must make that condition visible.

The primary page must provide an exact/prefix IPv4 search across local current
state and retained history. Search neither sends a query to Cisco nor bypasses
the refresh-hint rate limit. It must show a matching active address as
**Current shun**, and any historical-only address as **Historical — not
currently shunned**, together with last seen, last verified removal when
available, latest event, device count, and the Protected-IP marker where it
matches the trusted-IP policy.

The page also provides a CSRF-protected **Request refresh** control. It may
only enqueue the existing asynchronous refresh hint and must not wait for FTD
SSH. The control displays a browser countdown to the next permitted interactive
request and remains an advisory presentation of synchronizer metadata; the API
enforces the rate limit independently. User-facing text must explain `idle`,
`queued`, and `rate-limited` in operational language rather than expose those
internal state labels as unexplained status values.

If a scheduled baseline refresh is due within the configured interactive
minimum interval, an activity hint must not start another sweep first. The UI
must instead show that scheduled refresh and its remaining countdown. Outside
that final interval, an accepted activity hint may run immediately and resets
the following baseline interval after the sweep completes.

The authenticated browser must obtain freshness transitions through a dedicated
same-origin BFF status resource, not by relying on a POST/redirect race. A
refresh request returns the scheduler's resulting state immediately (`queued`,
`baseline_pending`, `running`, or rate-limited), and the browser polls the BFF
status while the page is visible. Requests received during a queued/running
sweep join that sweep and cannot schedule an additional one. With experimental
session cycles enabled, an eligible manual hint can request one priority
snapshot at a safe checkpoint; recent full snapshots satisfy demand without
another command. This exception does not start another cycle/session. The browser uses
one sequential request loop for refresh submissions, status, and state reads,
with finite request timeouts and failure backoff. Hidden pages suspend polling.

Status includes a process `instance_id`, monotonic `status_revision`,
`data_revision`, and `cycle_revision`, plus cycle ID, start/completion times,
outcome, and per-device state/freshness. Every finished sweep increments
`cycle_revision`, including identical repeated failures and partial fleet
success. `data_revision` advances after committed snapshots, verified local
mutation results, and history purges. These counters are process-local; a new
instance ID invalidates previous counters after restart. Timestamps remain
operator information, not completion/change tokens.

The Web/BFF captures status before reading state for a page, so a change during
rendering cannot be hidden behind a newer revision. When data/cycle revisions
or the instance change, the browser fetches that same authenticated page and
replaces only designated state/history regions. Preserve unsent search text,
confirmation values, focus, scroll, and expanded history; use fresh server CSRF
fields and do not automatically reload the page. Status responses, dynamic
state reads, and refresh responses use `Cache-Control: no-store`.

Per-device UI status distinguishes current, refreshing, stale, error, disabled,
and not-yet-confirmed data. An unsuccessful snapshot never clears the previous
observed state. Reaching a baseline countdown deadline alone is not proof of
snapshot completion and must not initiate a reload.

The working **Operation queue** shows QUEUED/RUNNING jobs only. Put FAILED and
UNVERIFIED results in a separate visible **Needs attention** section, and other
terminal outcomes in **Completed operations**, collapsed by default. Show
displayed/total counts when bounded lists omit rows and link IPs to retained
history. Completed work never remains visually pending or runs again because
it is retained. Preserve the completed-panel disclosure state across updates;
history retention and execution/idempotency behavior are unchanged.

Active request progress uses the actual jobs linked to that parent request,
across devices/cycles, never the per-cycle operation cap or elapsed time as its
denominator. Show processed/total jobs, queued/running counts, and separate
verified, no-op, failed, unverified, cancelled, and reconciled-absent outcomes.
Processed means a recorded terminal outcome, not verified success. A RUNNING
job has an indeterminate indicator until its outcome is known; no fabricated
within-command percentage or ETA is permitted. Cancelled requesters must not
remain in active progress merely because another requester shares their job.
Return at most 20 active request summaries with the total request count, using
the same consistent SQLite status snapshot. Idle historical results remain in
the collapsed completed view. This presentation does not enable addition/import.

The main working page prioritizes search and active shuns. Compact Status and
Queue disclosures hold device details, refresh controls, progress and retained
outcomes. Critical failures, stale data and attention counts remain visible
outside closed menus. Disclosures support keyboard, Escape and outside-click
dismissal. History and Protected IPs have separate navigation pages. History
is always expanded, newest-first, with 100 events per page, totals and page
navigation. The live first page includes new events; older-page links carry an
event-ID anchor so newly appended events cannot shift the browsing window.
Counts and rows use one SQLite read transaction. Retention may remove events
and shorten the available window; an expired anchor requires opening Latest
events. This anchor is a browsing aid, not a durable snapshot or authorization.
Routine refresh messages stay inside Status. Toolbar summary height is stable;
critical notices use an out-of-flow alert tray rather than shifting the content.
All timestamps retain timezone labels.

If an active shun exactly matches a configured trusted IP, the list row and IP
detail page must display a visually distinct **Protected IP** marker. This is
an operational warning based only on the configured exact-address policy; it
does not itself dispatch a Cisco operation or imply that removal has succeeded.

All persisted and API timestamps use UTC ISO 8601 with a `Z` suffix. The Web
UI renders timestamps in the browser's local timezone and explicitly includes
the timezone name or offset. If browser-side formatting is unavailable, the
UTC `Z` source timestamp remains visible rather than an unlabeled local time.

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
- never include SSH-password material;
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

The privileged agent must emit a sanitized structured local failure event for every rejected semantic operation. The Docker runtime retains this event in its bounded service log and makes it available to the host collector. The agent's socket response remains a generic rejection; detailed diagnostics must never cross into the Web/API trust zone. Failure events may contain the device ID, target IP, and a classified reason, but never the SSH password or raw Cisco command output.

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

Active-list reads prioritize exact Protected IP membership, including disabled
policy entries whose active shuns still need a visible warning. Within each
group, sort by the current appearance's observation time descending, then
numeric IPv4, device hostname and interface for deterministic ties. For active
rows, the existing `last_changed_at` is exposed as `active_since_at`; detection
or reappearance sets it, while ordinary successful polling changes only
`last_seen_at`. Preserve lifetime `first_seen_at` across reappearance/restart.
The UI labels the current-appearance time **Observed since** and localizes it
with timezone; it is not an FTD creation timestamp. Entries first discovered in
one snapshot have equal observation times, not an inferred device order.
Disabled membership affects display priority only, never automatic-removal
eligibility. Search/history retain their independent ordering contracts.

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

The Cisco SSH password must not be stored in the agent's persistent filesystem.

---

# 61. Backup

The SQLite event database should be included in normal server backup.

It contains operational history but no Cisco credentials.

Backup restoration must not automatically restore or recreate an FTD SSH password.

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

Manual creation remains unavailable in the current release. Section 74 records
the approved future exception for one-time, typed, audited manual imports; it
does not authorize arbitrary commands or enable an addition operation today.

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

12. The FTD SSH password is available only to the isolated non-root agent, through a read-only runtime secret; a future one-time bootstrap may remove that mount.

13. SSH-password source-buffer memory is explicitly destroyed after SSH authentication.

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

24. A stolen Cisco SSH password cannot authenticate from arbitrary source IP addresses because of Cisco-side SSH management ACL restrictions.

25. No component exposes a generic shell, command or SSH execution interface.

26. The service supports device-scoped removal and an explicitly confirmed bulk removal across matched configured devices, with one auditable result per device.

27. Web authentication uses Authelia ForwardAuth; the application has no LDAP password-handling code.

28. Admission/cancellation of manual removals requires recent authentication within `AUTH_SENSITIVE_ACTION_MAX_AGE`; queued execution uses the explicitly bounded captured authorization described above.

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

---

# 74. Approved Next Increment: Queued Device Cycles and Manual Imports

## Transitional removal queue

### Experimental bounded-session extension

The [Agent Cycle Protocol v1](manual/agent-cycle-protocol.md) defines the next
implementation contract: a versioned BEGIN/SNAPSHOT/REMOVE/END conversation on
one peer-checked SOCK_SEQPACKET connection and one pinned SSH session. It
supersedes the per-operation session rule only when explicitly enabled with
`FTD_SHUN_AGENT_CYCLES_ENABLED=true` in both API and agent. Default remains
false pending live laboratory validation. Hard per-session bounds are 16
removal steps, 64 CLI commands, 120 seconds, and one extra priority snapshot.
Exact frame validation, sequential checkpoints, final-verification reserves,
pre-write deferral, and abort-without-replay behavior are required by that
contract. No addition or generic execution capability is introduced.

The following transitional behavior remains the default while the extension
is disabled:

The implemented transitional queue increment retains the existing fixed agent RPC while
removing immediate browser/API dispatch. Use one durable, leased executor and
a persisted fleet-wide cycle gate (at least the configured 60-second minimum
after completion). This conservative gate serializes devices as well as users.
Allow at most one queued device/IP removal per device in a cycle, with the
existing complete snapshot and verified-removal operations. Each RPC still
opens its own short-lived SSH session; do not claim single-session batching or
mid-batch priority reads until the new protocol is implemented and lab tested.

Admission, duplicate coalescing, actor attribution, bounded capacity, expiry,
cancellation, and uncertain-outcome recovery must already be durable. A lost
worker's RUNNING items become UNVERIFIED after its lease expires and are
never automatically replayed. Queue acceptance returns 202, not write success.
Manual requests expire after at most 15 minutes (or the configured sensitive
action age, if shorter); admission requires the current mapped write role.
The worker uses that recorded, short-lived authorization, not saved session
credentials. Existing trusted-policy removals use the same queue and budget.
The lease must exceed the bounded in-flight RPC and be renewed before each
RPC. A restored database must be reviewed before starting the worker.

**Full-target status: bounded removal sessions and priority reads implemented
behind a default-off laboratory gate; parse-only preview implemented, write-side addition/import pending
(2026-10-15).**
The [Development Plan](development-plan.md) specifies sequencing, validation,
and the remaining detailed-design decisions. The following target requirements
supersede immediate manual dispatch and independent refresh/write scheduling
only once that increment is implemented and validated:

A preparatory **Import preview** may be implemented independently of addition.
It accepts bounded, CSRF-protected pasted text as data in the authenticated BFF
only. It parses exact IPv4 literals, recognizes explicit lists/comments and
rejects ambiguous/unsupported forms without substring extraction. Raw text is
not persisted, logged, or sent to the internal API/agent. The API receives only
bounded typed addresses and explicitly selected enabled device IDs for a local
SQLite classification read. It cannot enqueue work, issue refresh hints, open
SSH or claim a validated creation-interface scope. Preview results are point-in-
time advisory data; there is no Queue import action or executable preview token.
Limits are 1 MiB UTF-8 text, 20,000 lines, 10,000 preview rows, 64 selected devices
and 100,000 expanded device/IP pairs. The form request body is capped at
3 MiB + 16 KiB before decoding, including chunked bodies, allowing worst-case
percent encoding and bounded metadata. Browser validation counts UTF-8 bytes
with native form CRLF line endings; it must not silently truncate pasted text.
All rows are classified before rendering a 100-row result page with full-list
counts. Pagination re-submits the current form for a fresh local preview; no
source/batch is stored in a server session or URL. Decoded-source validation failures
retain the escaped form and explicit error rather than a JSON-only page.
Preview is available to authenticated
users; future admission still requires its separate write authorization and
fresh policy/state checks. No source text becomes a Cisco command.
The preview budget is not a supported active-device population. Current agent
command output and complete binary snapshot responses each remain bounded to
64 KiB; 7,307 `management` entries exceed both. Large additions must remain
blocked until a separately reviewed bounded snapshot-transport/console-reader
extension provides complete observations, including at the intended existing
plus imported load. Preserve fail-closed behavior and previous state on any
incomplete snapshot. Do not silently raise packet/output limits, reconcile a
partial result, or infer readiness from preview counts. See the
[addition readiness gate](manual/addition-lab-validation.md).
An explicitly versioned, default-off read extension is specified in
[Large Snapshots](manual/large-snapshots.md): typed `LIST_SHUNS_LARGE` and cycle
v2 snapshots use bounded manifest/data/end frames, 32 KiB chunks, an explicit
count/size and SHA-256 completion check before decoding/reconciliation. Bounds
are 20,000 entries, 2 MiB binary data and 4 MiB console output for full reads
only. Legacy/v1 limits and all command/session time budgets remain unchanged.
New reads require `FTD_SHUN_LARGE_SNAPSHOTS_ENABLED=true` in API and agent;
requesting new mode from a disabled/old agent fails closed without retry or
fallback. Explicit legacy API selection remains supported by a newer agent.
This extends reads, not addition or import.
Preview outcome badges and full-list counts use consistent colour cues with
visible text labels in both themes; invalid/unsupported and ambiguous rows
also have distinct background/border cues. Green Ready means candidate only,
never queued, added or agent-verified execution success.

- All user additions and removals enter a shared durable SQLite queue. Queue
  acceptance is distinct from verified FTD success. Preserve the actor,
  request ID, and outcome for every user's submission, including duplicates,
  conflicts, cancellations, and partial fleet results.
- One background scheduler combines queued writes and snapshot reconciliation
  into bounded per-device cycles. Use one SSH session at a time on each device
  and start no new cycle earlier than 60 seconds after the preceding one
  completes. Persist this eligibility across restarts. Baseline refresh,
  interactive hints, retries, and trusted-IP automatic removals share that
  budget; requests cannot bypass it through a separate write path.
- A cycle uses a strictly parsed initial snapshot, ordered typed operations,
  and post-write verification through one bounded prompt-driven SSH session.
  A versioned fixed binary cycle/batch protocol must be designed and reviewed
  before adding session reuse. No raw import text, comments, CLI, or arbitrary
  interface strings may cross the agent boundary.
- During a background batch, one coalesced, eligible interactive refresh may
  insert a typed full-snapshot read at the next safe command boundary, after
  any required write verification and before the next background mutation.
  It uses the existing session and bounded cycle budget. Enforce the shared
  interactive cooldown, reserve at most one extra priority snapshot per cycle,
  and coalesce later requests with final/next-cycle reads to prevent starvation.
  The typed protocol must support bounded checkpoint/progress signaling;
  concurrent CLI commands and extra SSH sessions are prohibited.
- Addition is a new narrow semantic capability, provisionally `ADD_SHUN`, not
  a generic executor. Its interface scope, Basic-role support, parsers, and
  verification require live laboratory validation before enablement.
  The [addition contract](manual/addition-contract.md) defines the approved next
  experimental agent/transport increment after the operator requested its
  disabled-by-default implementation. Cycle v3 adds typed ADD without changing
  v1/v2. `FTD_SHUN_AGENT_ADDITIONS_ENABLED=false` remains the agent default;
  v3 also requires cycle/large-read flags and an explicit agent-owned device
  `addition_profile` matching the reviewed laboratory profile. Missing/unknown
  profile cannot imply permission from the removal allowlist. Python selection
  is explicit; the default API scheduler does not select v3 or dispatch ADD.
  The staged-only admission increment below may enqueue held ADD intentions,
  but cannot execute them. Exact acknowledgement plus fresh source-only post-read,
  no write for pre-existing targets, shared ADD/REMOVE budgets and no automatic
  replay/provenance inference remain required. Implementation/deployment with
  gates off is not live validation or permission to enable ADD/import. Existing
  creation-scope, traffic and full-population read gates remain in force.

### Staged-only import admission — 2026-10-16

The private API may implement `POST /api/v1/imports`, guarded by the strict,
false-by-default `FTD_SHUN_IMPORT_ADMISSION_ENABLED`. This switch permits only
durable staging, not execution. No BFF submit route/button or executable
preview token is introduced. The browser preview remains non-executable.
Identity must come from the trusted BFF boundary in any future browser workflow;
caller-supplied API actor fields are trusted only on the private API socket,
not accepted directly from a public browser. Future BFF submission requires
CSRF and fresh, explicit confirmation; a digest is not authorization.

Admission freezes 1–1000 distinct typed device/IPv4 pairs, policy revision,
label/reason and captured actor under an explicit UUID idempotency key.
A SHA-256 digest binds canonical targets/metadata, not permission. Atomically
recheck enabled devices, enabled Protected IP exclusion, policy revision,
roles, rate/capacity limits and opposite intentions. Coalesce same-action
device/IP requests with separate actor audit; reject any queued/running
opposite ADD/REMOVE target for the whole request. Retain the existing limits
of 1000 unfinished jobs, 2000 active requests, 10 submissions/user/minute and
at most 15 minutes of captured authorization. Preview limits do not expand
admission or promise completion of a 7,307-address list within that window.

Additive SQLite migration marks existing jobs REMOVE, introduces immutable
job action and an explicit dispatch-kind marker, immutable manual-import batch
metadata and per-occurrence origin rows, and backfills opaque occurrence IDs
without changing existing dates. Preserve the nine-column request layout for
older removal writers; effective `manual_import` source is explicit in batch
metadata/events, while the compatible base request source remains `manual`.
Triggers reject a legacy claimant trying to run ADD as removal and rotate an
occurrence on reappearance even under older state writers. They are safety
nets, not permission to downgrade with active ADD work: suspend pending work
and retain additive tables under the documented rollback procedure.

In staged-only mode the scheduler must select REMOVE only. Held ADD jobs must not cause extra
minute-spaced device cycles. They remain visible/cancellable and expire under
the normal authorization rules. Enabling protection fails matching unstarted
ADD jobs transactionally before policy removals may be generated. No new
refresh hint, SSH read or write is caused by staged admission. Domain-level
claim/completion hooks are default-disabled; the independently gated worker
extension below may use them, never the HTTP admission handler.

Only an exact typed verified-add response may atomically create the current
observed occurrence and its batch/actor origins. No-op, failure, uncertainty,
later snapshots, restart or idempotent replay cannot assign/reassign origin or
regenerate work. A conflicting local active occurrence fails attribution closed.
Later externally observed reappearance receives a new occurrence with no
inherited badge. Keep all coalesced actor audit/origin rows, but expose only
one representative batch and the full origin count per active row to bound
API/UI metadata. Active occurrence attribution outlives pruned queue jobs;
inactive attribution/batches follow configured history retention. See
[Import Admission](manual/import-admission.md) for migration and rollback.

### Gated queued ADD execution — 2026-10-16

The operator approved integrating ADD with the existing leased scheduler while
keeping execution disabled. `FTD_SHUN_IMPORT_EXECUTION_ENABLED=false` is an
independent, strict API gate. True requires socket agent mode, session cycles
and large reads; it does not enable the agent's own ADD gate or supply a device
profile. Admission may be disabled independently to stop intake while draining
previously authorized work. No new public/BFF submit route is introduced.

At startup derive the allowed addition device IDs only from validated enabled
inventory records with an explicit recognized `addition_profile`. Keep that
capability in process configuration, not user input or a new database policy.
Only these devices select exact cycle v3; other devices keep their existing
v1/v2 read/removal mode. Missing profile holds ADD rather than breaking fleet
monitoring. Neither gate alone authorizes a write or implies lab compatibility.

Under the explicit API gate and device capability, atomically claim eligible
ADD/REMOVE in common FIFO sequence with the existing cycle cutoff and trusted
policy discovery exception. Otherwise select REMOVE only. Held ADD does not
schedule extra cycles. Eligible ADD shares the persisted cooldown, one leased
executor/session, 16 combined processed attempts, command/time reserves and
safe priority checkpoints. Recheck device, captured role/expiry, cancellation
and current enabled protection on every claim. RUNNING work is not cancellable;
an external policy change cannot atomically revoke an already dispatched CLI
command. Never open a second writer to resolve that unavoidable race.

Use exact typed `AdditionResult` and version-3 transport; never infer creation
from the scheduler's interface-less snapshot or fall back to another version.
Only explicit pre-write deferral can requeue. Missing/malformed/lost responses
settle UNVERIFIED and abort the session without replay. Commit verified creation
and provenance before publishing later snapshots; a failed final read must not
replay/erase an earlier verified result. No-op must retain existing provenance.
Publish ADD/remove/priority phases, combined progress, per-job held eligibility
and completion revisions without a new device-read path. Default-off rollout
is not scoped live ADD, traffic, creation-scope or large-population validation.

The [proposed one-address service validation](manual/single-address-service-validation.md)
separates fresh read-only preflight, explicit target/window/temporary-configuration
approval, creation/idempotent retry/no-op, verified cleanup and restoration.
Preparing that runbook or checking cached state is not approval to enable ADD
or mutate FTD. Any limited validation experiment before broader traffic/load
evidence must be explicitly scoped/reviewed, not inferred from deployment
permission or treated as general import readiness.

On 2026-10-16 the operator explicitly approved one such bounded experiment:
device 1/fpr1010-lab, unused TEST-NET 198.51.100.251, temporary per-device profile/
gate enablement, one queued creation, same-key replay/already-present no-op and
device-scoped cleanup, followed by restoring defaults. Fresh Basic-session
target absence was supplied. A clearly named trusted-host maintenance actor may
use the private semantic API for admission/cleanup; no Web identity/session is
fabricated and browser authorization is not validated by that route. This
exception establishes only small CLI lifecycle evidence if it succeeds. It
does not waive general traffic/creation-scope/load/production gates or authorize
other addresses, broad imports, a second writer or retaining ADD enablement.
That approved experiment completed with VERIFIED creation, NOOP, VERIFIED scoped
cleanup, operator before/present/after reads and no re-add on original-key replay.
ADD gates/profile were restored off and ordinary v2 observation succeeded. The
[recorded result](manual/single-address-service-validation.md#recorded-service-result--2026-10-16)
is one-profile CLI evidence only; the authorization is consumed and does not
extend to new test writes, traffic/fleet/load acceptance or general enablement.

### Remaining product requirements

- A pasted blocklist creates one-time manual additions. Successful removal,
  external disappearance, reconciliation, and restart never regenerate those
  completed add requests. It is not a continuously enforced blocklist or feed.
- SQLite events and structured logs identify `manual_import` provenance,
  batch, actor, targets, and verified results. Associate provenance with the
  actual operation/occurrence; do not claim ownership of a preexisting shun.
- Protected IPs cannot be added by import. Check policy at preview, admission,
  and execution. Serialize or explicitly reject conflicting user intentions;
  never silently replay an uncertain write or promise physical exactly-once
  execution across a lost SSH response.
- Publish cycle completion revisions, including failures and partial success,
  and per-device freshness. Publish observed-snapshot revisions independently
  so an interactive read can update the UI before the import finishes. Expose
  a shared queue/progress panel with counts, current device/action, requester,
  outcomes, and wait reasons. Browser polling reads local BFF metadata and
  updates displayed results while preserving user input; a current snapshot
  must not imply completion of a still-running batch.

The topology, credential isolation, pinned host keys, exact binary validation,
verified-success requirement, and prohibition on arbitrary Cisco commands are
unchanged. The queue and experimental removal-cycle extension are implemented
as recorded above; executable addition/import remains unavailable. Live validation of the
new protocol is required before default enablement.
