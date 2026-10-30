# FTD Shun Management Service

Current stage (2026-10-30): unreleased, internal, lab-only development on the
operator's desk FPR1010. The latest
[development-stage amendment](#pre-release-laboratory-policy--2026-10-30)
supersedes older per-fixture approval and mandatory legacy-dev conversion planning,
not the security or verified-operation contracts.

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

The latest approved product target is the
[working-version alignment](#working-version-product-alignment--2026-10-20),
recorded after a sequential operator discussion. It supersedes conflicting older
product requirements only in the stated areas. Earlier protocol/runtime contracts
remain in force for existing code until reviewed implementation/migration; this
document does not activate new behavior or authorize a lab mutation.

Sections 1–73 describe the current removal-oriented scope. The approved next
increment in [Section 74](#74-approved-next-increment-queued-device-cycles-and-manual-imports)
and the [Development Plan](development-plan.md) extends that scope with queued
device cycles and one-time manual shun imports. The durable removal queue is
implemented; a bounded-session protocol is experimental and opt-in pending lab
validation. ADD transport, private admission, queued execution and separate
browser confirmation are implemented behind default-off gates; general imports
remain disabled pending the remaining validation. Default legacy protocol and
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
same retention period, with security-evidence exceptions: QUEUED/RUNNING and
UNVERIFIED jobs are not purged. Captured ADD predecessors of WAITING_ADD,
ADMITTING or ATTENTION single/fleet cleanup are also retained, regardless of
their terminal result. Linked request/delegation records remain while their jobs
remain. Age is not resolution; even restoration abandonment does not make an
UNVERIFIED queue result disposable. Existing fresh-read REMOVE reconciliation
may produce RECONCILED_ABSENT, not fabricated VERIFIED, after which ordinary
retention applies unless a cleanup hold remains. No automatic archive or incident
closure is implied; unresolved evidence may outlive configured history retention.

Queue pruning validates retained fleet predecessor structure before deleting
anything, in the same write transaction. Malformed/partial evidence refuses
queue pruning rather than interpreting unknown references as an empty hold.
It does not recover previously purged evidence or initialize optional schemas.
Explicit isolation receipts additionally hold their original related jobs and
linked requests, including a subsequently reconciled REMOVE. Validate those
bounded references before pruning; a malformed hold is never treated as empty.
Queue cleanup records its deletion count
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

The socket/state volume initializer changes ownership of the fixed mount roots
only. It must not recursively traverse or rewrite existing database files,
private backup directories or child symlinks. Keep its sole CHOWN capability;
do not add DAC_OVERRIDE or relax private file modes to make reinitialization
succeed. Existing/restored data ownership is an explicitly reviewed offline
operator concern, not an automatic startup repair.

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

### Authenticated browser confirmation — 2026-10-17

The BFF may prepare a separate review of up to 1000 candidate device/IPv4
pairs from a fresh local classification, excluding enabled Protected IPs and
already observed pairs. Parsing, pagination and review never admit work or
request device reads. Show all frozen targets/hostnames, exclusions, policy
revision, normalized metadata and whether admission/execution are disabled.
Require Operator/Administrator both at preparation and confirmation, CSRF on
both POSTs and explicit typed target-count confirmation. Never forward browser
actor, target, policy or digest fields as authority.

Store only canonical intent (not raw paste/comments), an independent UUID
idempotency key and bounded display metadata in a process-local review cache.
Use unpredictable tokens bound to authenticated subject and CSRF cookie;
never put tokens/targets in URLs. Reviews expire within ten minutes (or the
shorter sensitive-action age), with at most five per subject and 256 globally;
reject overflow, do not evict a potentially admitted review. Web restart loses
reviews and fails closed. Keep the same frozen key/body through explicit retries,
including after a lost admission reply; do not automatically retry or generate
replacement work. Expiry/restart requires inspecting Queue before a new review.

Only the explicit confirm POST calls private import admission using current
Caddy-derived identity and the original canonical body/key. The API rechecks
its independent intake gate, roles, policy revision, protected/device state,
conflicts and capacity atomically. A 202 is queued/held, not device success;
report uncertainty on transport failure and offer same-review retry. Never
reclassify or shrink a frozen review on retry. API execution/agent/profile gates,
short queued authority, budgets and live-validation requirements are unchanged;
deployment keeps all ADD gates off and creates no test work. Browser review is
not a waiver for general or large imports.

Queue eligibility is presentation derived from current process configuration.
Do not store a permanent execution-disabled reason when admitting new ADD;
hide only that exact legacy placeholder for eligible QUEUED ADD, retaining real
budget deferral/error reasons and all audit/history unchanged.

### Remaining product requirements

- The managed-shun amendment below supersedes the former one-time-only product
  requirement for future explicitly confirmed managed imports. Existing import
  requests still remain one-time: their completion/idempotent replay never
  creates standing authority or regenerates work.
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
unchanged. The queue, gated ADD worker and browser confirmation are implemented
as recorded above; general addition/import enablement remains unavailable. Live validation of the
new protocol is required before default enablement.

## Managed-shun requirement amendment — 2026-10-17

The operator requested restoring manually added shuns after disappearance,
including device reboot. This changes the earlier one-time-only product
decision, not the deployed behavior. The isolated registry foundation is
implemented below; browser/admission/controller integration is pending. The
[Managed Shuns design](manual/managed-shuns.md) defines the staged work and
remaining validation. All ADD gates stay off; no live mutation or conversion
of existing data is authorized by this design update.

- Maintain an explicit durable desired-present record per configured device/IPv4,
  separate from observed shuns, occurrence provenance, completed jobs and audit.
  Scope is additions/imports explicitly managed through this service, not all
  observed shuns. Cisco output alone does not identify manual versus automatic
  origin. No automatic adoption of old imports, SSH-created entries, pre-existing
  NOOPs or historical occurrences is permitted.
- Future managed-import confirmation must explicitly authorize persistence until
  revoked, bind managed mode into the canonical intent/digest and show exact
  device/IP scope. This is a revocable standing policy, not an extension or
  renewal of the existing at-most-15-minute captured user authorization.
  Current legacy API/review must not silently acquire these semantics.
  Restoration uses a distinct system policy actor linked to the authorizing
  user/intent revision, never impersonated user roles or stored credentials.
- After a new complete successful snapshot positively establishes absence,
  an enabled managed intent may generate bounded restoration work through the
  existing leased executor, typed v3 ADD, gates/profile, FIFO, priority reads
  and command/time/cooldown budgets. Never infer absence from timeout, parser
  failure, stale/partial snapshots, service restart or failed device login.
  Absence is not proof of reboot; do not invent a disappearance cause.
- An explicit device-scoped removal through the service must atomically retire
  that target's desired intent and cancel its unstarted restoration intentions
  with admission of removal. All-devices removal retires the exact reviewed
  scope, including managed-but-currently-missing targets. Do not clear the
  retirement when deletion fails, is uncertain, expires or is cancelled. A
  previously RUNNING ADD must settle before any queued cleanup; no concurrent
  opposite command, silent loss of cleanup or claim of cancelled device work.
  Opposite running-job admission needs an explicit ordered handoff design;
  the current whole-request conflict rule must not be bypassed ad hoc.
- Enabled Protected IPs always override managed presence and suppress/cancel
  unstarted ADD under the same transaction/claim rules. Keep the desired intent
  visible as blocked, not erased. Removing/disabling protection may resume
  maintenance under that still-enabled intent; warn explicitly in policy UI.
  Disabled devices/profile/gates likewise hold rather than widen target scope.
- Never replay an uncertain ADD under a new restoration ID. UNVERIFIED or lost
  lease/results must latch the target into attention until explicit reviewed
  resolution; later absence alone cannot clear it. A healthy completed ADD
  followed by a later complete absence is a new desired-state reconciliation,
  not resurrection of its old request. Coalesce duplicate discoveries, bind
  jobs to intent generation/absence epoch and recheck revision before claim.
- Active desired intent survives observed disappearance, reboot, service restart
  and ordinary 366-day history retention. Provenance remains occurrence-bound:
  only new verified creation establishes a restored occurrence's origin.
  Observing presence/NOOP never proves that the service restored it. Historical
  imported provenance is not standing policy and must not be migrated into it.

The new controller must be independently default-off as well as respecting all
existing ADD gates. UI must distinguish maintained policy, observed presence,
pending/blocked restoration, attention and last verified restoration. Stop
maintenance independently of whether a current shun is present. External CLI
removal is indistinguishable from another disappearance and will be restored
while intent remains enabled; operators must revoke it in the service first.
Bound backlog, suppress repeated churn and preserve unknown outcomes rather
than flooding the console. Migration, authorization, ordered removal handoff,
restore/rollback, anti-churn limits and tests must be implemented/reviewed before
connecting this policy to admission or the scheduler. No change to the isolation
topology, credential boundary, binary protocol or no-arbitrary-CLI invariant.

### Offline managed-policy registry foundation — 2026-10-17

`managed_shuns.py` implements only durable policy lifecycle, not restoration.
Explicit `ManagedShuns.initialize()` creates three additive, empty tables;
ordinary Store/API startup does not call it. No HTTP route, feature flag,
queue/scheduler hook, agent operation or live migration is introduced.

Canonical changes bind `scope=managed_shuns`, `mode=maintain_present`,
MAINTAIN/RETIRE, exact typed targets, managed/Protected-IP revisions and normalized
metadata. Require current non-empty Operator/Administrator identity, explicit
canonical UUID and matching digest. Reject keys already used by legacy imports
or queue requests. Keep immutable request/result/authorization ledger and
idempotent replay before revision checks, without applying old policy again.
The hash is confirmation binding only, never authority by itself.

One effective target retains authorizing request, intent UUID/generation,
enabled/retired state, revision and UTC dates. Explicit re-enable after retirement
creates a new UUID/generation; an old-key replay cannot re-enable it. Another
user's already-enabled intention is audited NOOP, not replacement authorization.
Fresh MAINTAIN rejects enabled protection, unknown/disabled devices, stale
policy and implicit adoption of existing observed shuns. Retirement can revoke
missing/disabled/protected targets; protection revision changes do not veto it.

Changes/CAS/audit/request ledger commit atomically; the caller-owned transaction
hook uses a savepoint so caught failures cannot leak partial policy. This permits
future atomic removal composition but does not implement queued cancellation or
running-ADD handoff yet. Only the standalone wrapper emits a sanitized aggregate
JSON log after commit. Snapshot reads are consistent/bounded and do not expose
full canonical lists, routes or pins, or claim verified creation.

Initial storage bounds: 1000 target keys including retained retired tombstones,
10000 immutable request keys. Reserve the last 1000 request slots for changes
that actually retire targets; new grants/no-op churn cannot consume revocation
capacity. Overflow is atomic, never eviction/truncation or key recycling. Active
authority, tombstones and request metadata are independent of ordinary history
retention. A future archival/capacity extension requires separate review; these
bounds do not support the long list. Initialization is repeatable and defaults
`restoration_suspended=1`; no resume/controller exists in this increment.
Future restore tooling must suspend enforcement in addition to jobs before
starting a controller. Anti-churn, uncertainty latch, system queue source,
ordered handoff and explicit UI remain prerequisites to runtime integration.

### Read-only managed visibility and product version — 2026-10-17

The API may publish optional read-only managed state/cheap revision metadata and
the authenticated BFF may display a Managed shuns page before write integration.
Neither path initializes/migrates the registry. An entirely absent registry is
explicitly uninitialized/empty, not adopted policy; partial/corrupt registry
fails the managed read closed while ordinary monitoring remains available.
Status includes managed availability/initialization/revision without loading
full canonical lists. Browser updates use these revisions plus existing data/
protection revisions, preserving the difference between desired and observed.

This page offers no policy write/resume/queue action, enables no gate and never
claims restoration is running or verified. Show stopped/missing/protected/
disabled-device cases, original authorization and an explicit controller-
unavailable notice. Missing observations must not be mistaken for created
restoration jobs. No full inventory routes/keys are exposed. Current runtime
still executes one-time imports only; atomic retirement/queue handoff and
explicit standing-mode confirmation are prerequisites to any managed writes.

Every server-rendered page has a normal-flow footer with the product package
version. `ftd_shun_manager.__version__` is the sole version source; build metadata
reads that value as well. Do not read Git, secrets, deployment configuration or
host details to render it. Footer must remain usable on mobile and must not
overlay content. This version is a release identifier, not production acceptance
or a claim that all planned capabilities are enabled.

### Queue transaction composition prerequisite — 2026-10-17

Admission may expose a trusted internal caller-owned transaction hook sharing
the same semantic validation/idempotency/limits and atomic audit as ordinary
admission. It must not commit the caller's transaction or emit accepted logs
before the outer commit. Failed partial admission must roll back to its own
savepoint, including batches/links/events/revision; failure of a composite
policy-plus-queue action must roll back the whole composite transaction.

The implemented `OperationQueue.apply_enqueue()` and isolated managed retirement
tests meet this primitive contract only. Normal HTTP/worker behavior and schema
are unchanged. No runtime managed coordinator, standing system queue source,
restoration cancellation, running-command cleanup dependency or composite
review/replay authority is added. Opposite ADD/REMOVE work still fails closed.
Keep managed writes unavailable until their complete retirement/cancellation/
ordered-handoff and uncertainty contracts are implemented together. Transaction
composition itself cannot authorize a device operation or waive existing gates.

### Offline single-target removal handoff coordinator — 2026-10-17

`ManagedRemovals` implements explicit reviewed single-device/IP retirement plus
cleanup admission in one transaction. It has no HTTP/UI or scheduler integration;
normal startup must not initialize its optional additive schema. This is not
restoration or a live migration. Canonical RETIRE_AND_REMOVE binds fixed mode,
pair, managed revision, reason and a bounded cleanup lifetime; current Operator/
Administrator, canonical UUID and exact confirmation are mandatory. Immutable
root authority/result and original expiry survive pruning/restarts. Same-key
replay cannot retire a later generation or re-admit cleanup after queue pruning.

If ADD is RUNNING, keep the unique active job intact and persist WAITING_ADD
against that exact predecessor, atomically with desired retirement. Reserve a
slot under the existing 1000 unfinished/2000 active-request bounds, share actor
rate limits, block new ADD coalescing and maintenance re-enable while cleanup is
pending/attention. Ordinary opposite-action admissions still conflict; an
unstarted one-time ADD is not silently revoked. Initial ledger limit is 10000
retained one-target requests; overflow never partially retires policy.

Only the current leased executor may explicitly advance at most 16 eligible
handoffs. The present scheduler does not call it. Running predecessors remain
waiting; settled VERIFIED/NOOP/FAILED/UNVERIFIED allow separate REMOVE under the
original deadline without changing ADD provenance/uncertainty. A known exact
pre-write deferral may cancel that same unsent ADD before cleanup is admitted.
Missing/inconsistent evidence, changed generation or admission failure latches
attention; no automatic replay. Expiry/cancellation/failure never re-enables
maintenance. Materialized removal uses the existing queue, cutoff, snapshots,
verification and budgets, not a second executor or SSH path.

Optional queue accounting and retention protect waiting capacity and predecessor
evidence only when the explicit schema exists. Normal monitoring/admission with
absent schema remains unchanged. Frozen UI, visible waiting/attention, worker
wake/expiry, all-device scope, system/protection cancellation and composite
restore suspension remain live-integration blockers. Backup/downgrade must not
start an older worker ignoring waiting reservations or replay restored intent.
See [Managed Removal Handoffs](manual/managed-removal-handoffs.md).

### Preparatory managed-removal review and optional visibility — 2026-10-17

Authenticated users may read optional handoff state via the BFF/private GET,
without schema initialization, audit/queue writes, refresh hints or device calls.
Missing schema is explicitly uninitialized; malformed state is unavailable, not
empty. Preserve valid managed policy visibility on optional-resource failure.
Bound views to 20 prioritized rows/full counts, distinguish admission phase
from linked queue outcome and collapse settled entries. Never label admitted,
unknown or reconciled absence as verified removal. Escape actor/diagnostic text
and display timezone-qualified dates; existing queue revisions drive updates.

Operator/Administrator may prepare a single-target frozen removal review from
retained current policy. Selectors/reason are untrusted data; server captures
scope/revision/generation/key/digest. Reviews bind subject/CSRF cookie, expire
within ten minutes/the sensitive-action age and are bounded to five per subject,
256 globally. Status updates must not replace/reclassify a POST review or lose
its token/input/focus. Pure canonical intent can be shared with Web without
importing storage/coordinator code or delegating device access.

This is **not executable confirmation**. The button stays disabled; direct
confirmation validates current identity/role/CSRF/token/expiry/exact IP then
unconditionally rejects 503 without contacting admission. No setting, DOM edit
or upstream flag enables it. No managed admission HTTP route exists. UI/GET
deployment does not authorize policy migration, seed data, work or restoration;
shared-worker, cancellation/protection/fleet and composite recovery gates still
precede any managed write. See [Managed Removal Review](manual/managed-removal-review.md).

### Composite offline recovery and gated cleanup worker — 2026-10-17

This amendment supersedes prior statements that composite recovery and shared
waiting-cleanup advancement are unimplemented; it does not enable managed Web
admission or desired restoration.

Queue schema adds durable `operation_executor.mutations_suspended` (default 0).
Offline maintenance requires stopped API/Web and no old executable RPC, a
checked SQLite-API backup in a private operator-owned directory, integrity/FK
checks, no overwritten backup and no concurrent commit during backup. Capture
an explicit trusted-host `maintenance:` actor, never fabricated Web identity.
Atomically cancel QUEUED jobs/delegations and WAITING/transitional handoffs,
preserve RUNNING writes as UNVERIFIED, suspend optional desired restoration,
clear the lease, impose 60 seconds and append per-item/aggregate audit.
Retain desired targets/tombstones/authority, not old work for automatic replay.

While paused, new manual/import/trusted admissions, managed MAINTAIN/composite
cleanup and all mutation claims are blocked. Old-key replay is observational;
policy-only RETIRE remains possible. Monitoring leases/complete snapshots
continue, with a persistent visible Web warning. Resume requires offline/fresh
review assertions, no pending jobs/waits and restoration still suspended; it
clears only ordinary mutation suspension, never resurrecting jobs or desired
restoration. New protected-policy removals may be admitted after ordinary
resume. Older executors ignore this flag and optional reservations: never
downgrade/start them against paused/restored/pending state. See
[Offline Recovery](manual/recovery.md) for the operating contract.

`FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED=false` independently gates promotion of
existing reviewed handoffs, not their admission or ADD/restoration. Deployed
Settings require socket mode. With the flag enabled, existing waits wake the
same persisted-cooldown executor. After acquiring/recovering its lease, advance
at most 16 eligible waits once, before freezing the cycle cutoff. Then require
fresh device snapshots and use ordinary FIFO/capacity/expiry/verified-removal
paths. Never promote mid-cycle after ADD using an earlier snapshot. A write
settling during that cycle is eligible for a later one; original deadlines are
not extended. Optional tables are never initialized by startup or worker reads.
Global pause blocks promotion; unexpected handoff/database errors skip all
mutations for that cycle but retain monitoring/final snapshots and surface a
sanitized status/log warning. Already ADMITTED jobs remain ordinary queue work.

The flag stays off in the lab, with no managed schema seed or fixture. Synthetic
SQLite/fake-agent/Chromium validation is not live managed acceptance. Executable
confirmation/cancellation, fleet scope, protection/system hooks, uncertainty
latches, anti-churn and separately authorized restoration evidence still gate
the controller and any live managed writes. Rust/agent wire protocol unchanged.

### Managed revocation controls without device admission — 2026-10-17

This amendment permits two local revocation controls before combined removal/
creation/controller release. It supersedes the earlier no-policy-POST/no-cancel
UI boundary only for these exact operations; ADD/restoration and combined
RETIRE_AND_REMOVE admission remain unavailable/default-off.

Operator/Administrator may prepare a separate frozen **Stop maintaining — policy
only** review for one enabled retained intent, including missing/protected or
disabled-device targets. Freeze pair, intent/generation, managed revision, reason,
UUID/digest and local metadata. Bind the cache to subject/CSRF-cookie, at most
ten minutes/the sensitive-action age, five per subject/256 globally per action
cache. Status polls cannot reclassify/replace its token, typed IP or focus.
Preparation is observational. Confirmation rechecks current identity/role/CSRF,
cache and exact typed IP; BFF sends only frozen fields/current trusted actor.

Private `POST /api/v1/managed-shuns/retire` fixes action RETIRE, one exact pair,
Protected-IP canonical revision 0 and an explicit UUID key. No mode/action/list
or creation/re-enable/resume capability is exposed. Share the existing atomic
registry revision/ledger/audit checks and replay-before-CAS behavior. Same-key
replay cannot retire another generation. Do not initialize optional schemas.
Policy-only retirement works while ordinary mutations are recovery-paused.
It neither removes a current shun nor cancels separately admitted one-time jobs,
running ADD or cleanup; show this before confirmation. Future system restoration
must atomically honour revocation/cancel unstarted system links before release.
No refresh/work signal or new queue/agent operation is generated.

Validate the exact policy receipt/key/revision and distinguish it from current
policy or verified device removal. Unknown/malformed responses retain the same
frozen retry key; no auto-submit/retry/rebase. Optional status failure cannot
negate an already validated receipt. Cross-purpose tokens cannot authorize this
operation or turn it into combined removal.

Private waiting-cancel POST and authenticated CSRF-protected BFF may invoke
`cancel_waiting()` for current owner Operator/Administrator or an Administrator.
Serialize with promotion: only WAITING_ADD changes to CANCELLED; already
CANCELLED is an audit-free no-op, other phases conflict, never silently cancel
an admitted queue job. Preserve retirement and original ADD/authority/outcome.
Audit/log the real cancelling actor after commit. Strict fields, exact root ID,
bounded form and receipt validation remain mandatory. A collapsed explicit
confirmation explains that ADD may finish and a shun may remain. Browser
cancellation uses the existing single-submission/metadata controller without
navigation or refresh hint; no-JS uses an ordinary redirect. GET snapshots
remain observational; their `read_only` flag is not a claim that separate
revocation routes do not exist. See [Managed Controls](manual/managed-controls.md).

These controls do not authorize live registry seeding, enable the cleanup worker,
change actual ADD gates/profiles, adopt history or consume another fixture.
Combined confirmation remains unconditional 503. Protection/system/fleet hooks,
uncertainty/rearm/anti-churn and separately approved live evidence still gate
device-write integration. No topology, credentials, schema or agent-wire change.

### Protected/managed lifecycle and ordinary-removal barrier — 2026-10-17

Protected policy reads may publish global managed revision/availability and per-IP
enabled-intent counts, including missing observations/disabled devices, excluding
retired targets. Read only optional existing tables; never initialize/adopt.
Malformed/partial/unsupported state is unavailable, not zero; expose unknown
counts, keep monitoring/strengthening protection available and refuse weakening.
Cheap managed status uses the same structural safety validation; canonical
authorizations still require their separate full registry validation.

When disabling enabled protection or deleting an entry with enabled managed
intents, require an explicit acknowledgement and reviewed managed revision under
the same SQLite write lock as policy mutation, queued-ADD cancellation and audit.
A supplied stale managed revision conflicts even if no enabled intents remain.
No matching intent permits old clients without the new fields. Keep real current
authenticated actor/roles and existing all-user Protected-IP permissions. Audit
the checked revision/count/acknowledgement; do not retire desired intent, renew
authority, admit work or enable any controller through this acknowledgement.

Warnings must distinguish desired counts from observed shuns and state that
maintenance may resume only when its future controller is enabled. Dirty forms
retain both protected and managed CAS revisions with the acknowledgement, never
silently upgrading its scope during polling. Fresh/reloaded forms reset the ack.
Unknown-state forms cannot bypass the server check. Existing RUNNING ADD and
waiting/admitted cleanup remain intact through protection changes; already
implemented cancellation of unsent protected ADD stays atomic with policy audit.

Ordinary manual removal cannot bypass enabled desired policy: device scope
checks the exact pair, fleet scope includes matching maintained-but-missing
devices not present in the observed list. Recheck within queue admission's write
transaction after original-key/namespace checks, before request/job insertion.
The API also checks before empty observed-scope rejection. A caller-supplied
scope name does not waive retirement; offline combined coordination retires
under that transaction before removal admission. MAINTAIN rejects queued/running
removal, so concurrent opposite-order grant/admission cannot both commit.
Old-key replay remains observational and does not retire or requeue. Protected
automatic removal is exempt: it implements the higher-priority policy without
erasing desired intent. Absent optional schema preserves one-time behavior;
unknown managed state fails ordinary admission closed with a controlled error.

These are lifecycle/admission barriers, not a system restoration queue source,
generation/claim hook, uncertainty latch, executable fleet confirmation or live
acceptance. Combined confirmation remains 503, ADD/cleanup worker stay off in
the lab, and managed tables are not seeded. No schema/protocol/isolation change.

### Frozen fleet-removal scope prerequisite — 2026-10-17

A private observational resource and preparatory BFF review may expose the exact
union, for one IPv4, of locally active observed devices and enabled managed
targets, including missing observations and disabled devices. Collapse multiple
interfaces into one device/IP target; exclude retired-and-missing records and
unrelated inventory. Never silently omit disabled devices, unknown optional
policy or overflow beyond 1000 targets. Read observations, desired generations,
device enablement and protection in one SQLite read transaction without schema
initialization, device calls, refresh hints, audit or queue writes.

Bind a versioned canonical scope digest to exact sorted target metadata,
managed initialization/revision and Protected-IP revision/state. Observation
timestamps are not authority and do not invalidate unchanged membership.
A trusted internal comparison hook must re-read the scope on the caller's
transaction and reject a changed digest, never widen/shrink/rebase targets.
This is a prerequisite, not an admission/transaction coordinator or guarantee
that an unconnected future writer has performed that check.

Fleet review shares the existing subject/CSRF-bound, immutable, TTL/size-bounded
combined-review cache. Bind a separate canonical fleet intent, UUID, reason and
cleanup lifetime; display all targets and disabled-device blockers. Current
role, CSRF and exact typed IP remain necessary, not sufficient. Confirmation
remains unconditional 503 with no private admission call, regardless of DOM or
upstream flags. Preparation neither retires policy nor grants durable cleanup
authority. Single-target admission must not be looped into partial fleet writes;
atomic multi-target retirement/handoffs, system/protection/uncertainty hooks and
separately scoped live acceptance remain prerequisites to execution.

### Offline atomic fleet removal, ready targets only — 2026-10-17

An internal coordinator may admit the full frozen fleet scope in a single
`BEGIN IMMEDIATE` transaction. This is an offline integration stage, not an HTTP
admission route, live migration or enablement of the preparatory confirmation.
Require current Operator/Administrator, canonical UUID, exact fleet action digest
and comparison of the complete scope under the write lock. Reject the entire
request on a disabled target, QUEUED/RUNNING ADD or existing waiting cleanup.
Do not shrink the scope, cancel independent ADD or loop over single-target
admissions/commits. Fleet ordered waiting remains a separate future increment.

Retire all enabled managed targets together using one derived policy key, then
delegate the entire reviewed union through one ordinary REMOVE request. Observed
unmanaged targets receive cleanup only, never adopted policy or invented origin.
Retirement, queue jobs/links, immutable fleet receipt and audit either commit
together or roll back. Reuse existing queue capacity/rate, captured at-most-900s
authorization, coalescing, cutoff/lease/budgets and verified-result rules. Never
emit accepted logs before commit or extend authority when retrying.

Explicit offline initialization may add a retained fleet request ledger, bounded
to 10000 keys without recycling. It binds original actor, canonical intent,
receipt, derived retirement key and original deadline. Same-key replay precedes
current scope/CAS/gate checks and returns only the original receipt, even after
queue pruning/restart/recovery; it never retires a later generation or recreates
jobs. Keys cannot cross into ordinary/import/policy/single-handoff operations.
Normal startup/reads never create this table. Composite recovery cancels the
ordinary queue delegation and suspends restoration while retaining immutable
fleet authority; older writers ignoring these reservations are unsafe.

This stage intentionally refuses rather than implements fleet WAITING_ADD.
Single-target ordered handoff remains distinct. Runtime controls, system-source/
generation/claim cancellation, uncertainty/rearm, migration and scoped live
validation still block combined execution/restoration. All lab gates remain off;
no optional schema seed or device mutation is authorized by this amendment.

### Ordered fleet cleanup barrier — 2026-10-18

Extend offline fleet admission only through an explicit `ordered_wait` mode
with a distinct canonical action digest. Existing ready-only payloads/replays
retain their semantics. A QUEUED one-time ADD, disabled target or another waiting
cleanup still conflicts the entire request. RUNNING ADD may instead produce one
durable whole-scope WAITING_ADD barrier, atomically with desired retirement and
the original actor/receipt/deadline. No target from that root is admitted to
REMOVE until every captured predecessor has settled. Do not adopt observations,
split roots into partial submissions or cancel in-flight commands.

Explicit offline initialization may add `managed_fleet_waits`, linked to the
immutable root ledger. Preserve exact predecessor IDs/device IDs and full frozen
scope; reserve one pending slot per target and one active delegation per root
within existing shared bounds/rate accounting. Reserve even ready/coalescible
targets conservatively; release reservations only through atomic promotion or
terminal settlement. New ADD and managed re-enable cannot bypass the barrier.
Retain predecessor evidence while waiting independently of ordinary retention.

Only the existing leased executor may advance bounded eligible roots before its
cycle cutoff; one root promotes all targets or none. Still-running predecessors
wait without head-of-line starvation. Preserve settled ADD uncertainty; never
replay it or treat it as verified creation. An exact known pre-write deferral may
cancel that same unsent predecessor, not independent queued work. Missing/
inconsistent evidence, changed generation, disabled scope or failed admission
settles ATTENTION; expiry settles EXPIRED under the original deadline. No
automatic retry/rearm or retirement reversal. Owner Operator/Administrator or
Administrator may cancel only WAITING_ADD; promotion/cancellation serialize.

The default-off cleanup-worker flag gates both single and fleet barriers under
one lease/cooldown, at most eight roots of each kind per cycle (sixteen total),
before fresh device snapshots and ordinary FIFO execution. Unexpected errors
skip cycle mutations while retaining monitoring. No startup/read/worker path
initializes optional tables. Recovery cancels fleet waits/reservations together
with ordinary work and suspends desired restoration, retaining immutable root
authority and uncertainty. Older workers ignoring reservations remain unsafe.

This is still offline admission/default-off integration, without HTTP/BFF
execution, a live optional-schema migration or a new mutation authorization.
Combined confirmation remains 503; system restoration/generation/claim hooks,
uncertainty rearm/anti-churn and scoped live validation remain prerequisites.

### Fleet cleanup visibility and waiting revocation — 2026-10-18

Permit optional private read-only fleet-root status and authenticated Web display
without initializing schemas or renewing authority. Bound retained display to
twenty roots, active/attention first, with a labelled five-target scope sample.
Keep barrier state, predecessor settlement, queue delegation and linked REMOVE
outcomes separate. Admission is not verification; missing/pruned history is
unknown, not success or zero work. Show green verification only when every
original target has a matching VERIFIED REMOVE. Read errors must remain visible.

A separate cancellation endpoint may revoke only an existing WAITING_ADD root,
under a current owner Operator/Administrator or Administrator, serialized with
promotion. Require current trusted identity, strict CSRF-only Web input and a
validated private receipt; repeated cancellation is audit-free. It must not
cancel ADD, ordinary queue work, reverse retirement, request refresh or enable
admission/restoration. GET, polling and cancellation never create optional
schemas. Combined admission/confirmation stays unavailable; this amendment
does not authorize live fixtures, migration or enabling any device-write gate.

### Offline system restoration queue source — 2026-10-18

Permit an isolated trusted coordinator to derive a bounded ADD attempt from an
explicit enabled managed intent and fresh complete successful absence evidence.
Use the ordinary jobs, links, lease, FIFO/cutoff and budgets, but a distinct
`system:managed-shun-policy` actor with no captured user roles or import batch.
Retain immutable intent/generation/authorization, snapshot and job linkage in an
explicit optional attempt ledger (10000 keys, no recycling). Never initialize it
on startup, reads or worker paths. No HTTP admission, discovery/controller loop,
resume/rearm route, live migration or new gate enablement is included.

Each system delegation lasts at most 900 seconds; its source is current standing
policy, not renewal of a user's expired request. Deterministic intent/snapshot
keys coalesce discoveries; old keys remain reserved after queue pruning. Require
snapshot start after policy authorization/latest completed attempt, age at most
120 seconds, and no matching interface. Bound one active attempt per pair,
minimum 300 seconds between attempts and three attempts per pair per rolling
hour across generations. FAILED/UNVERIFIED latches survive ordinary retention
and new generations; no automatic retry/rearm is permitted.

Claim requires a separate explicit default-false internal restoration capability
in addition to existing ADD capability, current generation/enabled intent,
unpaused queue/unsuspended registry, enabled device, no protection or waiting
cleanup and unexpired delegation. Runtime callers do not supply that capability.
Do not coalesce system and one-time authority. Retirement/protection atomically
cancel unstarted system jobs; RUNNING ADD remains running and must settle before
ordered removal. Composite cleanup may supersede only its own unstarted system
restoration, never an independent queued import. Lost lease/result is attention,
not replay; verified creation records occurrence-bound system provenance, NOOP
does not. Recovery cancels queued attempts, retains running uncertainty and
suspends restoration. Old images ignoring this source must not execute pending
system attempts. Synthetic validation is not live restoration acceptance.

### Default-off managed discovery and shared dispatch — 2026-10-18

An independent strict `FTD_SHUN_MANAGED_RESTORATION_ENABLED=false` switch may
connect the existing system source to complete successful initial/priority/final
snapshots and shared v3 claims. It requires the existing API ADD execution gate,
socket/cycles/large-read mode and per-device addition profiles; the agent's own
gate remains mandatory. This does not initialize policy/attempt schemas, grant
standing authority, unsuspend policy, enable import intake or expose managed
creation/combined confirmation/rearm. Deployment keeps every live gate off.

Create fresh stable evidence once per actual read, retaining UTC read start/end;
publish/reconcile the full snapshot before discovery. Never discover from failed,
partial, deferred or cached reads. Jobs discovered after the frozen sweep cutoff
wait for the next eligible cycle, never bypass FIFO or the persisted >=60s pause.
Existing priority/final-read reserves and shared budgets remain unchanged.

Bound new admission to sixteen jobs and sixty-four attempts per entire sweep.
Assess at most the existing 1000 policy keys with bounded retained-ledger reads.
Prefer never/least-recently admitted targets/devices using retained attempt times,
so repeated boot-like absence on one device cannot starve another across restarts.
No missing-policy-only wakeups or extra writer/reader; baseline discovers, admitted
eligible jobs use the existing pending-work wakeup/cooldown. No churn rearm or
uncertain-result replay. Expected holds/backpressure are visible states, not
device-read failures; unexpected discovery errors stop cycle mutations while
retaining complete monitoring/final reads and sanitized diagnostics.

Read-only Managed UI/status reports configuration, bounded discovery counts and
current hold reasons, separately from cached observed absence and verified work.
Reads never admit work, renew evidence or fetch Cisco; partial optional state is
unavailable, not empty. This increment is default-off integration tested with
synthetic agents, not live restoration approval or production readiness.

### Frozen single-target standing grant — 2026-10-18

Permit explicit policy-only MAINTAIN admission for one configured device/IPv4
behind independent strict `FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED=false`.
This supersedes the previous no-standing-grant-route boundary only for this
operation. It does not initialize schemas, resume policy, enable ADD/controller,
adopt old observations/imports, clear attention or enable combined removal.
Use existing optional registry/attempt evidence and all transactional policy
checks; known unfinished/uncertain pair work conflicts. Require an explicit
addition-capable device profile even when execution is held. The setting itself
requires socket mode; it is not an execution gate.

Prepare a separately bounded immutable subject/CSRF-cookie-bound review with
exact pair/hostname, old intent/generation if any, managed/protected revisions,
normalized label/reason, standing mode, canonical digest and original UUID.
Use the existing ten-minute/sensitive-age, five-per-subject/256-global bounds
in a separate grant cache. Review is local-only/no-init/no-hint; uninitialized
policy can be inspected but that frozen review cannot be confirmed later.
Confirmation requires current Operator/Administrator, CSRF, exact typed IPv4
and explicit standing-authority acknowledgement. Do not accept browser actor,
target, action, revision or digest fields. Same-review retries preserve all
frozen fields/key; unknown replies remain unknown, never auto-submitted/rebased.

The private policy API rechecks its gate, current role, canonical explicit key,
acknowledgement, schema/capability, revisions, protection, recovery pause,
observed adoption, cleanup/conflicting work and capacity under one transaction.
An exact previous request may return its historical receipt without applying
authority again; current roles/gate remain required. New or explicitly retired
policy receives an intent/generation through the existing registry, never old
one-time semantics. A policy receipt is not queued/verified device creation.
No queue insertion or immediate wake/read occurs: only later complete evidence
may create system work through the already gated controller. Policy-only RETIRE
and guarded ordinary removal remain separate available controls until atomic
combined confirmation is separately released. Keep live gates/schemas unchanged;
synthetic admission tests and disabled rollout do not authorize a live grant.

### Default-off combined cleanup confirmation — 2026-10-18

Connect frozen single/fleet reviews to the existing atomic coordinators only
behind strict `FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED=false`. True requires
socket mode and the existing cleanup worker enabled, so new ordered waits are
not knowingly admitted without promotion capability. This supersedes earlier
unconditional-503/no-HTTP statements for combined confirmation only. It does
not enable any live gate, initialize optional tables or grant ADD/restoration.
New private endpoints fix device or fleet RETIRE_AND_REMOVE semantics, validate
strict canonical pair/scope/intent-generation/digest/TTL/current actor and
explicit canonical UUID. No generic action, CLI, policy source or free-form
route. Cap TTL by 900 seconds and the configured sensitive-action maximum.

Single admission binds reviewed intent/generation in its write transaction
and original-key replay; new retirement/cancellation/root/cleanup admission
remain atomic. Recheck the original deadline before committing even a ready
or waiting single-target plan. Fleet uses one whole-scope coordinator, never
loops per-target admissions. Default ready-only still rejects RUNNING ADD;
an explicit preparation checkbox freezes ordered mode and its distinct digest.
All original members wait behind captured RUNNING ADDs, under the same original
deadline. QUEUED independent ADD still conflicts; no silent target omission,
rebase, partial retirement, in-flight cancellation or uncertain ADD replay.

Require current Operator/Administrator, CSRF, frozen session/token/expiry and
exact typed IP. Confirmation accepts no browser actor/scope/mode/digest fields.
Both local BFF configuration and private API capability must permit submission;
upstream status alone cannot enable it. Retain the original key/body, typed IP
and ordered choice after unknown replies; no auto retry, new key or shrinking
scope. Validate exact scope-specific receipts. Historical replay cannot stop
a newer policy generation, requeue or renew authority; do not call it current
execution status. A valid receipt remains valid if optional status later fails.

Show accepted/waiting as plans, not verified removal, and link existing Queue/
handoff/fleet visibility. Only new accepted work signals the same leased worker;
never call FTD from HTTP, bypass cutoff/cooldown, initialize optional schemas,
grant new policy or change protection. Expiry/cancellation/failure never resumes
maintenance. Disabled admission after uncertainty says only that this attempt
was not submitted, not that an earlier attempt failed. Retain checked backups
and paired images; keep all live gates/schemas unchanged. Synthetic tests and
disabled deployment do not authorize a live cleanup fixture or migration.

### Explicit offline managed migration and reviewed resume — 2026-10-18

Permit a trusted-host maintenance CLI, not HTTP/startup, to initialize the complete
empty optional managed schema in one transaction. Require the ordinary durable
mutation pause, a settled executor/no pending jobs, explicit offline assertion,
short-lived exact-state review and checked exclusive backup. Refuse any existing
or partial optional schema instead of repairing/adopting it. Keep restoration
suspended; never turn observations, imports or audit history into authority.
All optional DDL, metadata and migration audit must roll back together.

Separately permit offline resume of already enabled, explicitly authorized
policy. This supersedes the no-resume-command boundary only for this CLI.
Ordinary mutations must already be resumed through the existing reviewed
procedure, with services still stopped and no outstanding RPC/lease/job. Require
the exact complete schema, at least one enabled target and a five-minute frozen
review binding schema, registry/queue/protection revisions, device state and all
retained managed authority. Pending cleanup, attention, uncertain jobs or failed/
uncertain restoration refuse resume; there is no resolution override or rearm.
An expired/stale review never rebases automatically.

Resume changes only the global desired pause and the enabled targets' revision/
updated-at reconciliation barrier, atomically with maintenance audit. Preserve
intent IDs, generations, original authorization/request timestamps, retired
targets, immutable keys, attempts, outcomes and queue contents. Reject backwards
time. Future absence evidence must start strictly after this barrier; old reads
cannot authorize ADD. Do not enqueue/wake work or change ordinary pause, settings,
profiles or execution gates. Ordinary recovery resume continues to leave desired
restoration paused. No HTTP resume route, live migration, live policy activation
or new device-write authorization is implied.

### Offline attention inspection — 2026-10-19

Provide read-only offline diagnostics before implementing uncertainty resolution.
Combine retained ordinary UNVERIFIED operations, FAILED/UNVERIFIED restoration
attempts and single/fleet ATTENTION cleanup, without counting a matching retained
restoration job twice. Keep pending work separate from terminal attention.
Show missing/pruned or inconsistent evidence explicitly; cached presence/absence
is not verification. Old generations retain their pair-wide failure latch.
Optional managed state is absent or exactly recognized, never silently repaired
or treated as empty when partial. Permit ordinary-only inspection without it.

Return at most 100 cases per page and five sampled fleet targets. Bind subsequent
pages to a digest of the retained cases and relevant policy/observation context;
refuse a changed snapshot rather than silently skipping cases. This digest is a
read-consistency check, not an executable confirmation. Exclude raw CLI/errors,
comments, credentials and full import/fleet payloads from output. Inspection
does not initialize schema, append audit, retire policy, resolve a latch, resume,
enqueue, renew authority, signal work, change gates or contact FTD. No live
activation or new write authorization is implied.

An exact-case offline view may additionally return the entire retained fleet
membership in device-ID order, at most 100 targets per page. Require canonical
kind/UUID identity and bind its pagination digest to both that identity and the
same retained-state/context snapshot; catalog and other-case digests are not
interchangeable. Validate the whole original scope before returning any page;
malformed scope or a mismatched retained count refuses detail, never silently
filters members. Keep reviewed device/intent metadata separate from current
inventory/policy/cache context, including missing current devices. Reject missing
cases and out-of-range target pages explicitly. This view has all the same
read-only/no-initialization/no-resolution boundaries as the catalog above.

Fleet inspection also identifies every captured predecessor ADD separately from
the cleanup REMOVE outcome. Validate the complete predecessor reference list,
canonical unique job/device identities and original-scope membership before any
detail page. The catalog reports malformed references as inconsistent with an
unknown count, without erasing otherwise valid fleet scope. Detail distinguishes
retained, not-captured, missing and inconsistent related jobs; never infer ADD
success from cleanup state or missing evidence. Related job outcome changes
invalidate the snapshot digest. Queue evidence retention follows the explicit
UNVERIFIED and WAITING_ADD/ADMITTING/ATTENTION predecessor holds above; this view
does not resolve those holds or recover evidence pruned by older versions.

### Offline acknowledgment of unresolved operations and cleanup — 2026-10-20

Permit a separate administrative ACKNOWLEDGE_UNRESOLVED decision for a retained
ordinary UNVERIFIED operation or single/fleet ATTENTION cleanup. This records
that a trusted-host operator inspected the incident and supplied a reason. Keep
the original case/outcome, authority, policy, reservations and resume blockers
unchanged. It does not retire policy, verify a write, abandon restoration, release
uncertainty, archive evidence or authorize execution. Restoration incidents use
their separate abandonment workflow. Whole-fleet acknowledgment covers every
original member and captured predecessor, including missing current devices;
no per-member decision or inferred smaller scope is allowed.

Use a separately reviewed optional immutable acknowledgment ledger, recognized
with exact DDL/capacity validation independently of managed-schema initialization.
Startup, reads and the existing managed/closure migrations never create it.
Ordinary-only databases can use it without initializing managed policy. Explicit
offline migration and confirmation use checked exclusive backups, both existing
mutation pauses (desired pause when managed policy exists), settled RPCs/no lease
or pending work, and five-minute state-bound reviews. Bind schema, complete
retained context, original case, full scope, predecessor/request evidence,
canonical request UUID, maintenance actor and bounded printable reason.
Require typed exact IPv4 and exact original target count. Changed/inconsistent
evidence, partial schema, expiry or mismatched keys refuse; missing historical
jobs remain explicitly missing. No silent rebase, second fleet transaction,
partial acknowledgment or new action inferred from a review digest.

Commit minimal sanitized evidence, immutable request/receipt and a distinct
INCIDENT_ACKNOWLEDGED audit atomically. One retained acknowledgment per case;
at most 10000, with no automatic recycling. Original-key replay returns only the
historical receipt, including after expiry or later observation changes. Reserve
decision keys against queue/policy/restoration/cleanup/abandonment authority.
Attention inspection shows the acknowledgment separately and keeps all original
cases/counts and resolution-unavailable semantics. Historical acknowledgment
can survive normal REMOVE absence reconciliation without changing its meaning.
No HTTP action, feature activation, schema migration in the lab or new device
mutation follows from implementing this offline workflow. Executable ordinary/
fleet uncertainty resolution and isolation exceptions remain separate work.

### Offline isolation of reviewed ordinary and cleanup incidents — 2026-10-20

Permit a separate ISOLATE_INCIDENT decision after administrative acknowledgment
of an ordinary UNVERIFIED or single/fleet ATTENTION case. Require explicitly
initialized immutable isolation receipts and exact indexed device/IP latches;
startup/GET/base/acknowledgment migration never create these two optional tables.
At most10000 receipts/target rows are retained. Original full fleet membership,
captured ADD evidence, original acknowledgment and current policy are frozen in
one five-minute review. Use checked exclusive backups, both existing mutation
pauses, no outstanding RPC/lease/pending work, original UUID/actor/reason and typed
IP/whole target count. Missing historical predecessors remain explicit; changed
or inconsistent evidence refuses. Isolation of a restoration case is unavailable
through this action; use its separate abandonment procedure.

Atomically retire all currently enabled standing targets in the original scope,
retain immutable receipt/evidence and pair latches, and append audit. Preserve
already retired target dates, original authority, outcomes, cleanup ATTENTION/
reservations and queue evidence. Missing current inventory members still receive
their exact device/IP latch; never loop per-member transactions. Exact original
request replay returns only its historical receipt. Decision keys cannot acquire
other queue/policy/cleanup/restoration/abandonment authority. No new device command
or automatic uncertainty replay is authorized.

Isolated pairs cannot receive new manual ADD/REMOVE, managed cleanup, MAINTAIN
or restoration, including later generations. Fleet ordinary removal checks the
whole address scope, including isolated devices missing from its observed list.
Claims recheck isolation. Protected automatic removal retains its existing
independent authority and priority. Read-only monitoring and policy-only retirement
remain available. No release/rearm route exists; original evidence holds persist.
Partial or inconsistent isolation schema/latches fail closed.

Provide a distinct reviewed offline resume-isolated-policy action for other
already-enabled healthy targets. Ordinary resume and restoration-only unrelated
resume stay strict. Require every remaining ordinary UNVERIFIED and single/fleet
ATTENTION case to have its own fully validated original isolation receipt/scope,
matching retained jobs/links and permanently retired or originally absent policy.
Every failed/uncertain restoration still needs its own valid abandonment receipt.
Validate all isolation receipts, not just sampled targets; missing/changed latches,
extra uncertain cases or overlapping enabled policy refuse. Normal complete-read
REMOVE reconciliation may remain RECONCILED_ABSENT, explicitly not VERIFIED.
Preserve quiescence, fresh-read barrier, device/protection/standing-authority/time
checks and atomic resume audit. The acknowledgment alone grants no exception.
Attention reports keep the original incidents with separate isolation status.
No HTTP, live migration/isolation/resume or new fixture is implied by shipping.

### Reviewed abandonment of restoration incidents — 2026-10-19

Permit a separate optional immutable closure ledger and trusted-host offline
ABANDON_MAINTENANCE for one FAILED/UNVERIFIED restoration attempt. This is
revocation/operational acknowledgment, not resolution of the unknown device
outcome. Original attempts/jobs remain unchanged and their restoration latches
still block policy resume. No rearm, new grant, retry, device command or HTTP
admission is added. Ordinary and device/fleet cleanup incidents are not closable
through this single-pair operation; reject overlapping waiting/attention cleanup.

Initialize the closure ledger only through its own reviewed offline migration
on the exact existing seven-table managed schema. Require ordinary and desired
pauses, settled RPCs/executor and no pending work. Use checked exclusive backup,
five-minute exact-state confirmation and atomic DDL/audit rollback. Normal startup,
GET, base managed initialization and attention inspection never create it.

Abandonment requires original canonical request UUID, maintenance actor, exact
restoration case, nonblank bounded reason, five-minute reviewed state and typed
IPv4. Bind both the attempt's original generation and current target intent/
generation, including historical-generation cases. Atomically retain minimal
immutable evidence and receipt, retire current enabled policy and append audit;
never fabricate directory roles or adopt observations as proof. Preserve already
retired target dates, original authorization, job results and queue contents.
Exact original-key replay returns its receipt without renewed authority or
retiring later policy; mismatched reuse, stale/unknown replies never rebase.

Retain closure IDs and pair-wide abandonment independently of history retention.
Block later MAINTAIN and restoration for that pair, even a new generation; old
grant receipts remain observational. Reserve closure request IDs across other
authority namespaces. Attention reports show abandonment separately from the
unchanged failure/latch; a closed operational case is not VERIFIED, an executable
resolution or permission to resume. Unknown/partial closure state fails closed.
No live migration/abandonment or consumed-fixture reuse is authorized by shipping
this implementation.

### Explicit offline resume of unrelated policy — 2026-10-19

Introduce a separate `review-resume-unrelated` / `resume-unrelated-policy`
maintenance action. This narrowly supersedes the global failed-attempt resume
block above, not any pair-wide latch. Ordinary `resume-policy` remains unchanged.
Require the exact explicitly initialized closure ledger and at least one retained
abandonment decision. Every FAILED/UNVERIFIED restoration attempt must have its
own consistent immutable closure and unchanged original attempt/evidence. Every
closed pair must remain retired at the recorded intent/generation and authority;
missing or changed policy is not proof of isolation. A retained linked job must
match the original ADD evidence; pruned terminal jobs may remain explicitly
missing. Retained UNVERIFIED jobs not covered by these exact closed attempts
still block, including ordinary operations on the same address. No one closure
silently covers other attempts, devices or generations.

Preserve all other resume prerequisites: stopped services/settled RPCs, separately
resumed ordinary mutations, desired suspension, no lease/pending work, no waiting/
attention single or fleet cleanup, complete authority for every enabled target,
enabled devices, protection priority and backwards-time refusal. Bind a separate
five-minute confirmation to schema, complete retained context, closure evidence,
isolated incidents and enabled targets. A standard resume/report digest cannot
authorize this action. Do not repair, initialize or filter inconsistent evidence.

Use the existing checked exclusive backup and atomic control/audit transaction.
Clear only desired suspension and advance enabled targets' fresh-read barrier;
record a distinct audit event with isolated-incident count and evidence digest.
Preserve retired targets, receipts, failure outcomes, original grants, jobs and
per-pair no-rearm checks. Do not grant, enqueue, wake workers, change gates or
query FTD. Resume acknowledgment is not device verification. New authorization,
ordinary/fleet incident resolution and HTTP resume remain unavailable. Lab
activation requires separately scoped approval; none is implied by this source
implementation. Older code retains its stricter refusal and must never be used
to remove evidence or resurrect an excluded target.

### Frozen batch standing-policy consent — 2026-10-19

Extend explicitly reviewed MAINTAIN consent to 1–1000 distinct device/IPv4 pairs
selected from at most 64 enabled configured devices. Use a separate paste/review
workflow, never reinterpret a one-time import or old history as standing policy.
Reuse the bounded exact-token parser; duplicate IPs are explicitly deduplicated,
but any invalid/ambiguous/unsupported row rejects preparation rather than silently
discarding it. Freeze the entire selected address/device product, revisions,
hostnames/prior intents, metadata, original UUID and recurring consent. Any
protected/observed/already enabled/uncertain/abandoned member rejects the batch;
never silently shrink scope or loop single-pair admission transactions.

Require current Operator/Administrator, CSRF, session-bound ten-minute-or-shorter
review, exact typed pair count and explicit recurring-authority checkbox. Use a
separate bounded review cache and POST-only 100-row frozen pagination; do not put
tokens/source in URLs or reconstruct scope during polling. Preserve confirmation
fields and original key/body after unknown replies. An uninitialized review
cannot become confirmable after migration. Raw pasted source is not retained in
the review/authority/audit, and a review digest is not permission by itself.

Expose a fixed strict private batch-policy endpoint behind the existing default-
off standing-admission gate, with both local BFF setting and API capability needed
for submission. Recheck every profile, revision, protection, enabled device,
observed adoption, work/cleanup/uncertainty/abandonment and capacity in one SQLite
transaction. Commit one canonical request plus all policy/audit or nothing. An
original-key replay returns only its historical receipt, never re-enable/rebase.
Saving policy neither queues work nor wakes/reads FTD, initializes schemas,
resumes policy or enables any ADD/controller gate. Later execution remains
separately gated and snapshot/cooldown bounded. No live grant/import or new device
write approval follows from default-off implementation/deployment.

## Working-version product alignment — 2026-10-20

The operator prioritized a usable working version with ongoing usability
improvements. The complete agreed target and delivery order are in
[Working Version: Agreed Product Behavior](working-version-plan.md). That record
is part of this normative target amendment, not an operating procedure or claim
that the following changes are already implemented.

It replaces these earlier product decisions for the next working-version design:

- Service addition/import always creates durable maintained device/IP policy;
  omit one-time addition from that user flow. Explicit adoption of an existing
  unmanaged shun is allowed with selected-device confirmation, without inventing
  service creation provenance. Never infer standing consent from observation,
  startup, historical imports or an old request replay.
- Support an import target of 10,000 input IPs, selected devices, visible skipping
  of invalid/protected inputs and confirmation of the exact accepted subset.
  Storage/admission/dispatch need compatible bounds; retain a bounded executable
  backlog instead of equating input size with active queue capacity.
- Device IDs remain stable across address changes. Use `.env` for the inventory
  path and a device file for metadata. Explicit per-device SSH login/password
  secrets replace a shared fallback. Only the agent receives actual FTD passwords;
  host-key pinning is independent of the connection address. Plan for 10 devices,
  default 4 concurrent devices, configurable, and one command stream per device.
- Dispatch continues between polling intervals, with bounded verified sessions
  and per-device isolation. Remove the artificial global minute-long mutation
  pause as a target requirement, not by bypassing existing code/protocol guards.
  Keep five-minute baseline polling and initially 60-second manual full-refresh
  spacing configurable and distinct from writes. Interactive refresh/unblock and
  urgent removal/Purge take priority after current operations/verification.
- Refresh demand remains submit-able with visible pending/countdown state on
  the panel trigger; coalesce repeated clicks and publish updated data afterward.
  Status/queue triggers expose pending work and issues outside the open panels.
- Active whitelist protection permanently retires matching managed authority,
  cancels unstarted additions and orders removal after any in-flight ADD settles.
  Disabling/deleting protection never resumes that old maintenance. Exact IPv4
  rules only; entries can remain visible while disabled.
- Device outages and uncertain results require automatic evidence-based
  reconciliation toward current intent rather than routine mandatory offline
  acknowledgment/isolation. Prove prior RPC/session settlement, obtain a fresh
  complete successful observation and recheck authority/protection/cancellation
  before a subsequent attempt. Preserve original unknown outcomes and audit;
  never fabricate verified success or blindly replay an outstanding command.
  A reviewed compatibility plan must preserve existing retained decisions/latches.
- Import cancellation leaves completed/adopted targets maintained and reports the
  remaining cancelled scope. Contradictory concurrent user actions require a
  refreshed review/confirmation with current state, not silent last-write-wins.
- Emergency Purge is an explicitly confirmed, actor-audited action for every
  authenticated user: cancel current imports/restoration additions, retire and
  urgently remove all managed targets in scope, preserving whitelist/unmanaged
  state. Preview scope/counts/effects, retain missing-device cleanup obligations
  and prevent re-add. No permanent global import lock was approved; define new
  intake during pending Purge as part of its concurrency contract before release.
- Use separate Managed/Unmanaged tabs. Highlight unmanaged sightings across at
  least two distinct FTD IDs in a rolling 24-hour window, including disappeared
  observations, with a selected-device action to adopt into Managed.
- Email is lower priority: configurable SMTP relay with optional authentication,
  plaintext/STARTTLS/implicit TLS, certificate/internal-CA verification and no
  implicit downgrade; `.env` settings/recipients and secret-backed password.
  Ordinary unmanaged events are aggregated with increasing time-based pauses
  (10/20/40 minutes toward a configurable cap), reset after one quiet hour.
  Active-whitelist incidents are urgent; first unblock attempt and later state
  changes notify without emailing every identical retry. SMTP dispatch topology
  and network/outbox/retry details remain a later implementation design.

Mass selected-address removal, CIDR protection and user-triggered restoration of
disappeared unmanaged entries are deferred. Prioritize delivery of the core
working-version flows over further expansion of offline incident ceremonies.

All unchanged invariants still apply: semantic typed operations only; exact fixed
binary validation; agent-only FTD credentials; pinned host keys; authenticated
identity/CSRF; Caddy as the only external listener; verified responses for success;
append-only audit and honest uncertainty. Detailed concurrency, capacity,
reconciliation, migration/rollback and Purge contracts must be implemented and
validated before their gates are changed. This documentation approval neither
clears old evidence nor authorizes a new lab fixture, live migration, bulk load,
secret/gate change, or production rollout. Existing consumed authorizations remain
consumed. Current implementation manuals describe their version until migrated.

## Per-device SSH credentials — 2026-10-21

The first working-version increment separates public inventory from an agent-only
credential mapping. `FTD_SHUN_SSH_CREDENTIALS_MODE=per-device` requires an explicit
mapping file, with exactly one login and password-secret name for every configured
stable device ID (including disabled devices). Reject missing, duplicate, unknown
or zero IDs, invalid logins, unknown fields and unsafe secret names before opening
the agent socket. Secret names are single ASCII basenames resolved under the fixed
agent-only `/run/secrets/ftd` mount; they are not paths supplied over RPC. Each device
has a distinct secret reference. Password values never belong in either inventory.

All legacy reads/removals and cycle v1/v2/v3 use the same ID-based credential
lookup. Per-device mode ignores legacy shared variables and never falls back on
a missing/unreadable/empty secret or authentication failure. Load the selected
password only for SSH authentication and zeroize its source buffer afterward.
Configuration changes require restart; changing the management IPv4 address under
the same ID neither changes its credential mapping nor trusts a different host key.
IDs must never be reassigned to a different physical/logical device.

Password files must be nonempty UTF-8 regular files of at most 16 KiB, with exact
bytes preserved (no newline trimming); reject final symlinks/FIFOs/directories.
`--check-config` validates all configuration and secret-file reads then exits
without SSH, socket binding or database access, reporting only mode/device count.
It does not prove device authentication or host-key correctness. Unknown arguments
fail rather than silently starting the service.

Explicit `shared` mode remains the default solely for compatibility with existing
deployments. It is not a fallback within per-device mode. The opt-in Compose overlay
mounts the mapping/secrets only into the agent and removes the legacy secret mount.
The shared public inventory source path becomes configurable; it contains no
credential fields. No protocol, database, policy authority or feature-gate change
is required. DNS/SSH-port configuration, concurrency and other working-version
items remain separate increments. The lab retains shared mode until a separately
approved credential migration; deploying the compatible binary does not activate
the new mode. See [Per-Device Credentials](manual/per-device-credentials.md) for
validation, migration, backup and paired configuration/image rollback.

## Protected-IP permanent retirement — 2026-10-21

An explicit user save of enabled protection permanently retires all matching
enabled managed targets, including absent observations and disabled devices, in
the protection transaction. This is fixed protection revocation authority for
every authenticated policy editor, not an Operator-role promotion or MAINTAIN
grant. Preserve intent/generation/original authorization, increment the managed
revision once, and append actor-attributed per-target retirement audit linked to
the policy event. Do not consume managed-request ledger capacity to revoke policy.
Cancel unstarted ADD/restoration with existing validation; never change RUNNING
outcomes, waiting cleanup, retained uncertainty or isolation/abandonment receipts.
Device removal remains the independent protected-policy executor, not synchronous
SSH or a success claim from saving the form.

If optional managed state is missing, do not create it. If it is partial/invalid,
allow protection strengthening but report retirement as deferred/unknown. The
persisted enabled protection is the barrier: disabling/deleting it is refused
until managed state is readable and all matching enabled maintenance is retired
in that same weakening transaction. No GET/startup adopts or retires policy.
An explicit edit of enabled protection also completes retirement of legacy held
intents. Never infer invalid optional state means no intent. No new schema or
optional-ledger initialization is needed for this barrier.

Disabling/deleting active protection cannot re-enable old policy; stale supplied
managed revisions conflict, and retiring a nonempty scope requires its reviewed
current managed revision. Disabled entries do not suppress newly and explicitly
authorized policy: deleting/editing an already-disabled entry leaves that policy
alone. Legacy `confirm_maintenance_resume` remains a strictly typed compatibility
field, not an authority to resume. New UI shows permanent retirement consequences
instead of asking permission to resume. Old-key grants remain observational.
Existing protected entries are not silently swept at startup/deployment; a user
save performs the new transaction. Older images retain legacy resume semantics,
so preserve matching API/Web rollback images and never restore old enabled policy
or weaken a deferred barrier under an older writer.

## Durable bulk-import preparation — 2026-10-21

The next working-version increment introduces an explicitly initialized,
non-authoritative preparation journal, separate from standing policy and the
executable queue. It can freeze up to 10,000 parsed rows across at most ten
explicit devices / 100,000 device-IP pairs. Capture author, UTC preparation/expiry,
managed/protection revisions, device labels, normalized metadata, invalid/duplicate
line reports and exact local proposed ADD/adoption/already-managed/protected
classifications in one transaction. Never persist pasted source/comments/excerpts
as part of the journal. Observed presence is cached evidence, not a fresh read or
service creation provenance. Unknown managed state refuses preparation, not an
invented unmanaged classification.

Preparation creates no managed authority, import-origin, audit success, queue job,
refresh hint or SSH operation. Its UUID/digest is a preparation reference, never
a bearer permission or an executable operation key. Every returned report states
that it cannot execute. Preserve existing 1000-key policy/canonical bounds and
all gates until their coordinated replacement. No startup/GET initializes this
journal; the subsequent confirmation amendment defines its gated private API.
Web admission and rolling dispatch remain separate implementation work.

Prepared rows/header are immutable; separate cancellation only invalidates the
unconfirmed preparation, not any independently admitted work. Retain snapshots
across restart; owner-bound reads page at 100 rows. Full digest verification streams
bounded chunks and never authorizes admission. Expiry is ten minutes, with at most
four retained preparations per owner and sixteen globally. Explicit expiry pruning
may delete only this non-authoritative preparation data; it never touches policy,
queue, attempts, receipts or audit. Future confirmed imports require a distinct
atomic durable authority/root that retains its accepted scope, provenance and
progress independently of preparation expiry/pruning; never attach active work
to an expiring draft or renew an old manual request.

Optional partial/unsupported preparation schema fails closed without repair.
Document migration/backup/rollback before eventual activation; no journal migration,
new live fixture, feature gate or device write is authorized in the lab by this
foundation. Validate maximum synthetic scope, bounded reads, exclusion/adoption
honesty, owner separation, concurrency, restart, immutable digests, expiry and
transaction rollback before integrating the next working-version flow.

## Bounded managed-policy reads — 2026-10-21

The Managed tab uses a distinct observational paged resource: at most 100 policy
keys and their attempt/hold summaries, in one SQLite snapshot, with stable device/
IPv4 ordering and explicit global counts. Previous/Next links bind the managed
revision; a changed registry refuses continuation with an explicit current-policy
link instead of rebasing membership silently. Observation/attempt updates may
refresh within that revision and must not be advertised as frozen device evidence.
Invalid/out-of-range selectors refuse rather than clamping. Read summaries are
strictly bounded local pair selectors, never executable protocol fields.

Preserve older-generation uncertainty, latest retained attempt, verified-only
restoration timestamps and honest missing/unsupported state. Do not hide orphaned
device/authority rows through joins. The tab must not load the whole policy or
attempt ledger into application memory. Keep the legacy full resource for exact
frozen reviews until a coordinated replacement; a visible page is not the full
admission/removal scope. No optional initialization, authority, queue mutation,
refresh hint, SSH call or audit write follows from reading pages.

This change does not increase the 1000-policy-key, 10000-request or 10000-attempt
capacities, change any gate, authorize a fixture or migrate live optional tables.
Paired API/Web rollout needs matching rollback images and a checked SQLite-safe
backup; it changes no schema and leaves the agent unchanged.

## Prepared-import policy confirmation — 2026-10-21

Provide fixed private preparation/list/report/cancel-draft and confirmation/report
POSTs; trusted actors come from the authenticated BFF, not public header/form
overrides. Confirmation requires current Operator/Administrator, explicit recurring
consent, a distinct canonical operation UUID, original owner preparation ID/digest,
exact accepted count, the existing default-off standing-admission gate, profiles
and already initialized optional schemas. Unknown state never becomes empty.
No request/startup migrates or enables policy. Future Web must enforce CSRF/session/
sensitive-age checks and retain the exact key/body through uncertain replies.

Under one SQLite write transaction, verify the full frozen preparation, lifetime/
clock, selected enabled device labels/IDs, managed/protection revisions and current
pair classification/prior references. Unchanged observation heartbeats need not
invalidate a logical pair, but presence-to-absence/adoption changes conflict.
Recheck pending/uncertain work, restoration latches, isolation/abandonment, cleanup,
profiles, recovery and existing capacity/reserved revocation. Reject the entire
changed/oversize scope; never silently reduce or split it. Invalid input is retained
as generated diagnostics, enabled Protected IP pairs as exact exclusions.

Atomically save the existing canonical MAINTAIN request/effective policies plus
independent immutable confirmation reports and actual-actor audit. Explicitly
adopt observed unmanaged pairs without ADD or invented creation provenance.
Already-maintained pairs retain their original intent/generation/authorization.
Absent proposals authorize maintenance, not verified creation. The internal exact
adoption subset is never a caller-supplied HTTP switch; legacy grants still refuse
adoption. No queue insertion, refresh hint, SSH, resume or new gate follows.

The two `confirmed_import_*` report tables retain full accepted/excluded scope,
generated diagnostics, original and assigned intent references, captured draft
versus actual confirmation identity, original preparation and receipt checksums.
They are evidence, not a parallel authority registry. Canonical standing authority
remains independently retained and compatible with existing revocation/maintenance.
Owner-only reports page at 100 rows, stream full integrity checks and outlive draft
expiry/pruning. Retain at most 128 roots/1,000,000 report members; refuse overflow,
never recycle keys/evidence. Original-key replay returns history only after expiry,
retirement/new generation/protection; a preparation cannot acquire a second key.
Confirmed draft reads identify its operation; cancel-draft refuses after confirmation
instead of implying cancellation of standing authority or in-flight work.

This backend preserves current 1000 accepted-pair/key, 10000 request/attempt limits
and default-off gates. It is not the 10,000-address executable release: compatible
larger capacity, confirmed-import cancellation, bounded dispatch/progress and Web
confirmation remain pending. No new lab migration/fixture/activation is authorized.
An additive API-only rollout may preserve the unchanged Web/agent, with checked
SQLite-safe backup and previous images; startup must leave optional schemas alone.
Follow [Prepared Import Confirmation](manual/managed-import-confirmation.md).

## Confirmed-import cancellation — 2026-10-21

Cancellation is revocation of an import's uncompleted initial application, not
rollback. Retain adopted, previously managed and successfully applied targets.
Retire only the exact original uncompleted generation; never touch newer grants,
send REMOVE, interrupt RUNNING ADD or turn observations into execution evidence.
FAILED/UNVERIFIED outcomes remain uncertain/latched even when policy is retired.

A separate explicitly initialized optional cancellation journal records one
immutable decision per original import key and bounded per-member settlement.
It grants no ADD authority. New confirmations require this journal; historical
confirmation recovery does not. Owner Operator or Administrator reviews the
whole accepted scope, exact current authority/outcomes and policy/protection
revisions with a five-minute digest and typed accepted count. Cancellation is
one transaction, available even with admission disabled. Changed evidence rejects
the whole decision. Original decision retries are observational, not new authority.

Unstarted owned ADDs are cancelled atomically with retirement. Capture RUNNING
owned ADDs and block new dispatch for that exact generation until the existing
queue transaction settles the result: VERIFIED/NOOP retains already enabled
original policy; failure/uncertainty or exact pre-write deferral retires it.
Protection/other retirement always wins; settlement cannot re-enable anything.
Shared lease recovery records uncertainty and settles cancellation in the same
transaction. Preserve captured jobs/requests while pending; malformed evidence
refuses pruning. Startup/read never migrate or settle work. Do not downgrade to
writers lacking cancellation hooks while any captured outcome is pending.

No live migration, policy fixture, gate change or device mutation is authorized
by this backend increment. See [Import Cancellation](manual/import-cancellation.md).

## Prepared-import browser integration — 2026-10-21

The authenticated BFF may expose saved preparations, exact 100-row reviews,
explicit recurring consent, owner receipts and uncompleted-work cancellation.
Browser forms carry only session-bound opaque review tokens or read references,
never actors, executable targets, gates or arbitrary actions. All POSTs require
CSRF; mutations additionally require current Operator/Administrator and bounded
sensitive-action review age. Reads/pagination never grant, hint, migrate or settle.

Derive the confirmation operation UUID deterministically from the immutable
preparation UUID with UUIDv5 name `ftd-shun-manager:prepared-policy:v1`. This is
an idempotency reference, not permission. It survives BFF restart; backend actor,
digest, consent, revisions and one-root-per-preparation checks remain mandatory.
Keep the same frozen payload/key through unknown replies; require explicit retry,
never automatic mutation retry. A new session may inspect the retained preparation
or receipt, not reactivate retired policy. Expired browser tokens cannot submit.

Bound ephemeral review caches separately for confirmation and cancellation;
cancel reviews expire within five minutes. Pagination preserves tokens and typed
count/consent. Render exclusions, adoption and incomplete/uninitialized state
honestly. Distinguish historical policy confirmation, immutable cancellation
decision and current cancellation settlement; none is device execution progress.
No auto-navigation/refresh may replace a frozen sensitive form. Escape metadata.

Both BFF configuration and current private API status must enable new standing
confirmation. Cancellation remains independent of that gate. No GET/startup/Web
request initializes optional schemas or activates profiles, restoration or ADD.
The existing one-time import path remains a separate legacy gated workflow, not
the default recommendation. This UI does not expand the 1000 accepted-pair limit
or enable continuous dispatch. See [Managed Import Web](manual/managed-import-web.md).

## Bounded selected-policy reads — 2026-10-21

Before increasing standing capacity, remove whole-registry reads from single-pair
browser reviews. A distinct private read-only POST accepts at most 100 distinct
literal device/IPv4 selectors and an optional exact managed revision. Return the
normalized requested scope, global total/revision/capacity and only existing
selected policies with their pair-scoped observations/retained-attempt summaries.
Missing selected policies stay distinguishable from an empty/uninitialized registry.
Never present the returned entries as the entire registry or an executable batch.

One SQLite read transaction validates global structural/device/authority integrity
and bounds policy/summary results. Revision mismatch is explicit, not silent
rebasing; malformed/partial state is unavailable, never empty. No read initializes
schemas, emits audit/hints or grants/adopts/retires/enqueues policy. Web single-pair
grant/retirement/removal reviews bind the exact returned selection; existing full
and fleet/batch review contracts remain distinct. Future admission must still
revalidate complete scope/revisions and all existing gates/holds atomically.
This is a capacity prerequisite, not expanded limits, migration or live activation.

## Whole-batch selected-policy reads — 2026-10-21

Legacy standing-list browser preparation now reads a distinct fixed private
`POST /api/v1/managed-shuns/selection/batch`, not the complete registry and not
independently read pages. Accept 1–1000 distinct literal device/IPv4 selectors
and optional exact revision, with the same strict unknown/coerced-field refusal.
Return `read_scope=selected_batch`, the entire normalized requested selection,
global totals/limit/revision and only existing selected entries. The original
at-most-100 selector resource and its marker remain unchanged and cannot be
substituted for a whole batch, even when that batch contains fewer than 100 pairs.

One SQLite read transaction validates global integrity and reads selected policy,
observations, holds and retained summaries in chunks of at most 100 pairs, using
one reference time. No mixed-revision aggregation, whole-attempt materialization,
partial successful result, silent truncation, fallback or schema initialization.
The BFF validates exact scope once, indexes selected entries once and derives
exact per-pair views for existing validators. New keys consume global capacity,
including stopped keys outside selection; existing selected stopped keys do not
consume another slot. Never mistake selected membership for registry capacity.

This is read preparation only. Legacy all-or-nothing scope, invalid/protected/
observed refusal, current actor/CSRF, frozen consent and final atomic backend
revalidation remain unchanged. Existing authority, 1000-key/accepted-pair limits,
retirement reserve, attempts, reports/cancellation and all live gates are unchanged.
No migration, new fixture, device mutation or large executable-import acceptance
is authorized. Deploy matching API/Web with checked backup and rollback images;
agent/protocol/credentials and optional live schemas stay unchanged.

## Large-import intent format foundation — 2026-10-21

The next capacity increment defines an isolated version-2 proposed-import format,
not an expanded legacy request or a second policy engine. A fixed-size canonical
JSON descriptor binds operation/preparation UUIDs, original preparation digest,
managed/protection revisions, normalized label/reason and a classified membership
manifest. All existing unversioned canonical requests, hashes, idempotency keys,
uncertain outcomes and authority checks retain their original semantics.

The manifest covers the full selected-device/address product: 1–10 distinct
explicit devices, 1–10000 distinct literal IPv4 addresses and at most 100000
pairs, including exact protected exclusions. Stream rows in strict numerical
device/IP order; refuse duplicates, missing cells, overflow, invalid/coerced fields
and unknown classifications. Bind each pair and its PROPOSE_ADD/PROPOSE_ADOPT/
ALREADY_MANAGED/EXCLUDED_PROTECTED classification with a domain-separated SHA-256.
Use fixed seven-byte records (device unsigned big-endian16, IPv4 four bytes,
classification byte 1/2/3/4 in that order) after the exact ASCII domain prefix
`ftd-shun-manager:managed-import-manifest:v2` and one LF. Include total/accepted/
address counts, explicit devices and all four classification counts in the
descriptor; classifications cannot be swapped while preserving its digest.
Bound descriptor storage to 8192 UTF-8 bytes. Reject duplicate JSON keys, unknown
or noncanonical fields, wrong versions and any incomplete/corrupt stream. Hashes
are integrity/review bindings, never bearer permissions or evidence of execution.

An internal owner-bound preparation read may build this proposal in one read
transaction from an intact, unexpired, uncancelled, unconfirmed journal. Stream
existing rows in <=100-row chunks, check full preparation integrity first and
require summary parity with its frozen header. Return explicitly non-executable
metadata; create no policy, schema, retained root, receipt, audit, hint or job.
Never translate an already confirmed legacy preparation to new authority.

Existing runtime API/registry/dispatcher and offline maintenance commands still
do not accept this format. The following isolated-storage amendment provides its
first explicit development-only persistence. Integrated persistence must atomically commit actor-attributed
root, independently retained indexed membership and effective policies, preserving
one effective device/IP authority and original already-managed generations.
Do not attach standing work to an expiring draft or use the immutable reports
alone as replacement authority. Versioned migration must coordinate total retained
keys, positive revocation reserve, attempts, reports/cancellation, paged readers
and dispatch before larger admission is enabled. Legacy keys/receipts/latches
must remain readable and cannot gain version-2 meaning. Older writers cannot
be assumed to understand the new state; downgrade/migration needs explicit review.

This foundation changes no SQL schema, live capacity, startup/GET behavior,
feature gate, credential or binary RPC protocol and authorizes no live migration,
load fixture or FTD mutation. Synthetic 100000-pair format/preparation checks are
not storage-migration, queue-backpressure, throughput or production acceptance.

## Isolated version-2 policy persistence — 2026-10-21

Implement version-2 storage as an explicit, initially offline-only component,
not a second effective-policy registry or an expanded legacy gate. Reuse immutable
`managed_shun_requests` and the single `managed_shun_targets` device/IP key space.
Independently retained manifest metadata/members bind the complete source header,
classified scope and assigned/original intent references to each version-2 root.
Canonical root, exact membership, effective grants/adoption and real-actor audit
commit in one transaction; no device jobs, provenance or resume follows.

Use an exact recognized `managed_bulk_registry` instead of the legacy
`managed_shun_registry`. Initially permit only suspended restoration. Legacy
readers/writers must see partial/unsupported managed state and fail closed,
including when fewer than 1000 keys exist. There is no runtime fallback, HTTP,
controller, migration CLI or profile activation. Explicit initialization accepts
only an empty managed namespace under an ordinary mutation pause, with no lease,
pending/uncertain jobs or existing incident/confirmation/cancellation state. It
never converts the lab's retained legacy policy or deletes old evidence. Nonempty
legacy conversion and executor/cleanup/attempt compatibility remain separate work.

The fixed storage profile permits 200000 retained effective keys (stopped keys
included), 400000 immutable requests, 128 import roots and 1000000 retained
classified members. New authority/no-op churn cannot consume the final 200000
request slots reserved for actual policy retirement. A root accepts at most
100000 pairs and creates no executable backlog. Refuse capacity overflow whole,
never evict/recycle keys. These are storage bounds, not FTD throughput claims.

Trusted internal confirmation requires explicit default-false capability,
current Operator/Administrator, recurring consent, typed accepted count, exact
descriptor/source integrity, live preparation, frozen revisions/devices and
unchanged classification/generation. Refuse any pending/uncertain queue work,
lease or unsupported optional evidence in this initial profile; do not resolve
or ignore it. Already-managed targets retain original authorization; adoption
creates no ADD or historical service-created occurrence. New policy remains
unexecutable/suspended. Original-key replay returns the retained historical result
after draft expiry/pruning/retirement, without changing policy or restoring a grant.

Owner-bound 100-row historical reports and current policy pages stream validation,
survive restart/draft pruning and create no schemas. Exact-revision policy-only
retirement uses bounded literal pairs and immutable original-key receipts; it
works in the retirement reserve and while new authority is paused/disabled, sends
no REMOVE and does not cancel independent jobs. Preserve earlier generations and
all uncertain evidence. Unknown/partial schema is not empty or repairable by GET.

Initialization and confirmation must roll back their own work even if composed
into an outer transaction whose caller catches an error and commits. No lab
invocation, bulk fixture, feature activation or service rollout is authorized.
Before deployment with this profile, deliver reviewed nonempty migration/backup,
version-aware protections/cleanup/attempts/readers, bounded dispatch and older-
writer rollback. Do not downgrade a populated version-2 database or restore old
enabled state as a software rollback. The present lab stays in legacy mode.

## Version-2 protection revocation integration — 2026-10-22

The existing Protected-IP coordinator may recognize the exact suspended version-2
profile for its narrow protection read/revocation purpose. This is not a general
fallback in legacy managed readers, grants, cleanup, restoration or dispatch.
Recognize any bulk object before attempting the legacy reader: partial/mixed or
unsupported optional state is unknown, not absent. Validate enabled identities
in bounded chunks rather than materializing the entire retained registry.

Protection saves retain their existing real-authenticated-actor authorization and
reviewed protection/managed revisions. Under the same write transaction, retire
every matching enabled target, including missing observations and disabled devices,
preserve original intent/generation/authorizing root, increment the bulk revision
once and append linked real-actor audit. Retirement needs no new managed request
slot and remains possible at full ledger capacity and during ordinary suspension.
Cancel eligible unsent ordinary ADDs through the existing queue hook; do not
interrupt RUNNING work, rewrite uncertain outcomes or manufacture verification.
This profile still refuses restoration-attempt/cleanup/cancellation schemas;
their version-aware coordination remains separate, not silently skipped.

When exact retirement state is unavailable, strengthening protection persists an
enabled barrier and reports deferred retirement. Do not weaken/delete that barrier
until a reviewed save can complete retirement after repair. Reads/restarts do not
repair, retire or initialize optional state. Disable/delete never re-enables old
policy, and original bulk-key replay remains historical. A new grant still needs
new explicit consent, current classification and a new generation.

No schema migration, runtime profile switch, dispatch/admission activation or new
HTTP route accompanies this integration. Existing lab state stays legacy. Code
rollback there requires no database restore; retain a populated version-2 database
with compatible code or offline, never release a deferred barrier using an older
writer that cannot perform its permanent retirement.

## Version-2 cancellation and rolling-work preparation — 2026-10-22

Extend the suspended bulk profile with explicitly initialized cancellation
decisions and independently retained accepted-member dispositions. Support both
the exact original profile and its exact additive extension; partial/mixed state
is unknown. Initialization requires the existing bulk profile, ordinary pause and
quiescent queue, rolls back within a caller-owned transaction and never converts
legacy state, grants authority or resumes execution. Startup/GET does not migrate.

Cancellation is one original-root-scoped revocation, not a new grant/key/action.
Require current Operator owner or Administrator, actual actor audit, exact accepted
pair count and a five-minute state-bound review. Stream complete original source
verification and cancellation scope in bounded chunks. Bind original authority,
current managed/protection revisions and every accepted member's disposition;
concurrent changes conflict, never shrink/rebase the scope. Preserve historical
confirmation. Retain adopted/already-managed members, leave stopped/superseded
generations untouched, and retire exact original enabled unapplied ADD members
together. No new managed-request slot, REMOVE, queue claim or network call follows.
One immutable count-checked sealed decision and all member dispositions/retirements/
audit commit together; original-review/actor retries return only the saved result.

The initial extension has no version-aware attempt ledger. It must therefore
refuse cancellation of a current unapplied member with any retained ADD job or
independent unfinished work, rather than infer application from observation,
overwrite an unknown result or pretend RUNNING work has settled. This is an
explicit delivery limit, not the final working-version cancellation behavior.
Version-aware attempts and in-flight settlement are required before bulk dispatch
or executable import admission. Legacy cancellation hooks do not consume this
new ledger. A cancelled unsent generation cannot be resurrected by original-key
replay; new explicit consent remains a separate reviewed generation.

Provide bounded read-only progress and rolling-work preparation against exact
profile state: at most 16 candidate pairs per portion, numerical keyset cursor,
exact revision binding and eligibility/protection/work holds. A read portion is
not an executable capability, reserved job, receipt of dispatch or fresh FTD
observation; never translate it directly into an ADD without the later claim/
attempt/fresh-read contract. Reads do not initialize schemas, queue work, change
authority or advance a durable execution cursor. Cancelled/stopped policies stay
out; adopted/existing policy remains maintained. No old request TTL is renewed.

No runtime profile activation, private admission route, lab schema change, fixture
or service restart accompanies these developer components. Before using the new
optional tables, retain a checked SQLite-safe backup and matching code; old
version-2 code refuses the extension and must not be used as a populated downgrade.

## Version-2 shared result journal — 2026-10-22

Add an explicitly initialized optional bulk-attempt journal after cancellation
controls, preserving the suspended registry and all original roots/receipts.
Initialization requires ordinary pause/quiescence and never creates a queued job,
resumes policy, enables dispatch or converts legacy attempts. Recognize exact base,
cancellation and cancellation-plus-attempt profiles; partial/mixed state is unknown.
Bound retained attempts to 1000000 without eviction or uncertainty reset.

An internal default-false capture hook may bind an already RUNNING system ADD
before its external send, inside its caller's write transaction. This is evidence
capture for a future atomic dispatcher, not admission or permission to execute.
Require the shared active lease, exact fixed system identity/no user roles, one
request/job/link, original standing intent/generation/authorization, current target
revision, eligible device/unprotected enabled policy and complete fresh absence
evidence after the grant. Reject manual/import jobs and retroactive terminal
history adoption. Capture neither manufactures a user role nor renews the original
900-second request. No current runtime caller invokes capture.

The existing queue result transaction records VERIFIED/NOOP/FAILED/UNVERIFIED and
exact pre-write deferral in this journal with original authority and real occurrence
evidence only for VERIFIED. Terminal evidence/identity are immutable. A retired or
protected policy never becomes enabled again when its in-flight result arrives.
Lease recovery records UNVERIFIED, never replay or guessed success. Pending or
unknown evidence survives retention; malformed/missing predecessors refuse pruning.
Completed independent journal evidence survives ordinary job/request pruning.

Bulk queued dispatch remains unavailable regardless of the legacy restoration
capability. Exact pre-write deferral can be cancelled through the same worker;
no second executor or unsupported retry is introduced. Current whole-root bulk
cancellation still refuses unattributable/in-flight ADD evidence; captured-wait
admission/settlement, completed-application retention and fresh-evidence automatic
reconciliation remain the next integration, not silently enabled by this journal.
Shared completion/status/protection/retention hooks must recognize bulk evidence
without treating it as a legacy grant or clearing its uncertainty.

No HTTP route, runtime flag/controller activation, lab schema/fixture, migration of
existing attempts or FTD operation accompanies this component. Keep exact old
receipts and checked backup/compatible-code boundaries; older version-2 code
refuses the journal profile. No database restore is needed on the unchanged lab.

## Version-2 captured cancellation settlement — 2026-10-22

Add a separately explicit optional captured-wait profile after the bulk result
journal. Preserve original cancellation decisions/checksums and attempt outcomes.
Under ordinary pause/quiescence, rebuild only the cancellation member table with
the same original columns/data plus nullable captured-job/history bindings and
expanded dispositions. Retain immutable original rows and add a separate immutable
settlement ledger. Verify old root/receipt integrity before and after migration;
all DDL/data copy/checks roll back together. Startup/GET never upgrades or repairs.

New cancellation reviews bind the original accepted scope, exact owned attempt
history and captured RUNNING/QUEUED predecessor. Unattributable ADD/independent
unfinished work still conflicts. Retain previously VERIFIED/NOOP application,
adoption and existing policy. Retire unsent/failed/unknown first application without
rewriting original outcomes. Capture a first RUNNING ADD as WAITING_OUTCOME, not
stopped/applied; do not interrupt it or send REMOVE. Cancel only an owned unsent
job after the whole immutable decision is sealed. Original review/count/actor,
TTL, conflict and original-key history rules remain unchanged.

The shared result transaction settles a captured wait exactly once. VERIFIED/NOOP
retains still-enabled original authority; failure/unknown/exact pre-write deferral
retires it. Protection/prior retirement/newer generation wins: settlement never
enables authority, touches a newer grant or clears uncertainty. Append immutable
settlement and real-cancelling-actor audit with exact original references. Insert
settlement before recursively cancelling an exactly deferred job. Any late result/
audit/settlement failure rolls back job, occurrence, attempt and policy together.

Initial cancellation receipts stay historical, including original WAITING counts.
Current paged status overlays settlements and exposes pending/attention honestly;
GET/restart never settles. Every pending captured job/request survives retention,
including a terminal result left unsettled by an incompatible writer. Validate the
entire captured binding before pruning; missing/malformed evidence is not absence
or success. Terminal unknown attempt latches remain after settlement/retirement.

This enables backend cancellation/result coordination, not bulk job admission,
dispatch, profile activation or automatic uncertainty reconciliation. Keep the
registry suspended, current worker defaults and lab unchanged. No new HTTP route,
FTD fixture, live migration or external command is authorized. Older code refuses
the expanded profile; preserve a checked SQLite-safe backup and compatible code,
never drop history or restore enabled policy to force rollback.

## Version-2 bounded queue admission and claim — 2026-10-22

Introduce a separately explicit dispatch-capable developer schema after captured
cancellation controls. Upgrade only under ordinary pause, a settled executor and
no pending/unknown work; retain all rows, immutable authority and receipts. It
does not resume policy. Older exact profiles retain their no-resume/no-dispatch
contract. The new profile recognizes both suspended and unsuspended registry
states; changing suspension to active requires ordinary pause and quiescence.
No activation command, HTTP route, startup migration, runtime flag wiring or lab
permission is introduced here. A separately reviewed activation procedure and
legacy conversion remain required before non-disposable use.
The optional canonical UTC `dispatch_resume_after` barrier advances only during
explicit resume; a read predating it cannot admit or claim work. Upgrade leaves
that field unset and suspension enabled. Existing policy-only confirmation remains
restricted to suspended execution until concurrent standing admission is reviewed.

An internal default-false controller capability may atomically admit at most 16
literal same-device candidates from a complete fresh absence snapshot. Bind each
candidate's original intent/generation/authorization and target revision, plus
the whole managed/protected revisions and an explicit trusted ADD-device profile.
Require unsuspended policy, unpaused mutations, an active shared lease, current
enabled device/policy, absent observations, full original root integrity and no
independent pending work or earlier failed/uncertain ADD. Keep retained capacity,
300-second pair backoff and three-attempt hourly churn limits; never evict evidence.
Any retained device-level unknown outcome blocks new bulk ADD work on that device
until a separate reviewed reconciliation contract proves it safe; a fresh snapshot
alone cannot release that barrier. Bind job creation time to the original request
and attempt, including before retention.
Create fixed system requests (no invented human roles), jobs, links, QUEUED
attempts and audit together. Backpressure/conflict/late failure rolls back the
whole portion. Deterministic snapshot/intent identities recover historical
admission without renewing deadlines, changing outcomes or re-enabling policy.

Only the existing leased queue may claim these jobs, with a distinct default-false
bulk capability, the original cutoff and fresh current-authority/evidence checks.
Never infer permission from the legacy restoration flag. Keep one RUNNING command
per device; do not add an executor or bypass existing cooldown/session safeguards.
Recheck lease/delegation/evidence before committing a claim. Exact pre-write
deferral may queue the same job again only while its original evidence/deadline
remain valid; a captured cancellation settles first and prevents that retry.
Timeout/unknown remains a retained latch, not replay authority. Cancellation,
protection, typed results and lease recovery use the existing atomic journal hooks.
Continuous dispatch, per-device parallel leases, automatic uncertainty convergence
and Web admission are subsequent integrations, not supplied by this backend hook.

## Version-2 bounded refill controller — 2026-10-22

Add a default-disabled version-aware discovery/refill controller to the existing
Synchronizer, mutually exclusive with legacy managed restoration/cleanup workers.
It requires explicit ADD/session capability, trusted per-device profiles and the
existing exact dispatch schema; it never initializes/migrates/resumes state.
No environment/API activation path or lab activation accompanies this integration.
Successful complete initial/priority/final reads may feed discovery under the
shared lease. No cached, partial, failed or claimed browser snapshot is authority.

Across a cycle, check at most 64 policy rows and admit at most 16 new jobs, in
atomic portions through BulkDispatch. Limit unfinished shared work on each device
to a 16-job refill window, counting independent mutations too. Preserve the global
queue/journal bounds. Sampled hold counts are checks, not total targets or verified
completion. Eligibility observes protection, current standing identity/revision,
present observations, snapshot age/resume barrier, attempt history/backoff/churn,
pending conflicts and device-level uncertainty. Never automatically retry a used
snapshot/intent key or reconstruct missing evidence. Selection and admission share
one write transaction; failures cannot partially admit a discovered portion.

Use bounded numerical keyset scans with non-authoritative in-memory cursors, reset
on managed/protected revision or resume-barrier changes. Restart discards scan
position, not policy or original attempt identities; rescan skips retained work,
observations and history without renewing authority. Rotate device order using
retained last-admission times so a large first device does not consume every
cycle. Do not load the full effective registry or create a durable execution cursor.

Supply the separate bulk capability consistently to pending-work/status/claim;
the legacy flag must not mislabel bulk work as executable. Preserve the existing
frozen cutoff, session budgets, global lease and cooldown: newly discovered ADD
waits for a later eligible cycle, not an implicit bypass. Unsent bulk delegations
that expire are CANCELLED with original history, not fabricated failed CLI
outcomes or cleared old FAILED/UNVERIFIED latches. Continuous dispatch, parallel
device leases, automatic uncertainty convergence, legacy conversion and Web bulk
activation remain subsequent work. Schema and lab configuration remain unchanged.
Legacy REMOVE RECONCILED_ABSENT is observational, not RPC-quiescence proof: retain
it as a device-level bulk barrier, including its linked job/request through queue
retention. Older schema-compatible writers may lack this newer retention contract;
keep capabilities off/mutations paused and preserve compatible code/checked backup
for any downgrade rather than treating schema recognition as permission to write.

## Bounded agent connection concurrency — 2026-10-22

The current agent serializes accepted connections, independently of the API's
global executor lease. Introduce an opt-in fixed connection-worker pool as the
transport prerequisite for future independent device scheduling. Default to one
inline worker; accept only canonical concurrency values 1..10. The working-version
target remains four active devices, not a validated hardware capacity claim. No
API lease/cooldown bypass, scheduler activation or lab change accompanies this step.

Authenticate SO_PEERCRED before dispatch, preserve exact packet decoding and all
existing version/feature/profile gates. Bound active handlers to the configured
worker count: assign at most one connection to an idle worker, never queue behind
an active handler. The initial IPC deadline starts at accept, including assignment
delay, in addition to the existing fixed kernel backlog. On saturation return the existing generic
rejection and close; never allocate one unbounded thread per connection.

Acquire a nonblocking, inventory-bounded device guard before any semantic handler,
including legacy, large-read and cycle v1/v2/v3 paths. Hold it through the entire
SSH operation/cycle, verification, final snapshot and transport-disconnect cleanup.
IDs sharing a management address share a guard, preventing alias-ID overlap.
Different devices may progress concurrently; a duplicate/busy/poisoned device is
rejected without opening SSH or waiting behind a cycle. A worker panic poisons
its held guard and does not create permission to retry; do not automatically
replace failed workers or clear the poisoned device until reviewed recovery.

Busy/saturated rejection is not a typed pre-write deferral, success, RPC-quiescence
proof or retry authority. Preserve unknown-result handling at callers; no new wire
status/opcode, arbitrary command, credential exposure, request-size or session/
operation/IPC timeout relaxation. Credentials remain agent-only with existing
per-device loading/zeroization and host-key pinning. Validate using bounded local
threads/UDS fixtures only; real simultaneous FTD sessions require separate scoped
acceptance before enablement. No live gates/profiles or secrets are changed.

## Fenced per-device API lease profile — 2026-10-22

Add an explicitly initialized optional profile after exact bulk dispatch storage,
under ordinary pause, desired suspension and global/pending/uncertainty quiescence.
Freeze 1..10 configured stable device IDs and a 1..10 concurrent-lease limit
(developer default four). Preserve all prior policy, receipts and outcomes.
Startup/GET never initializes or activates it. Database guards reject legacy
global-owner leases and desired resume while any device lease/attention remains;
older writers must not execute beside the new mode. No lab migration/activation.

Claim each device independently with a canonical worker nonce, strictly increasing
epoch and bounded deadline. Count all LEASED rows, including expired ones, until
their owner finishes or recovery records uncertainty. Never steal/reuse an expired
lease: atomically mark its RUNNING jobs UNVERIFIED using the shared result journal
and retain the captured lease as ATTENTION. Even a read-only expired lease can
have an outstanding RPC. ATTENTION is retained, not cleared by age, restart,
observation, capacity pressure or a new worker. No release/rearm route is added;
automatic quiescence-backed reconciliation remains separate future work.

A token-bound OperationQueue reuses the same admission, claims, typed results,
deferral, protection/cancellation, audit and retention logic. Require exact device,
nonce, epoch and unexpired lease before mutation claim, result, deferral, renewal
and release; old/wrong-device tokens cannot publish late results. Bulk evidence
capture/discovery must use the same scoped executor selector, never a temporary
global-owner projection or fabricated lease. Recheck the fence at transaction
end; errors roll back all journal/job/occurrence/lease updates together. Release
only after RUNNING work has settled. No other device's jobs are recovered/changed.

This component supplies actual concurrent lease/queue primitives, not a parallel
Synchronizer loop, continuous dispatch, new retry authority or clock/timeout
relaxation. Existing serial profiles retain their old behavior. Optional profile
recognition, frozen device scope, fences/attention and old-writer guards are exact
and fail closed on partial state. Keep checked SQLite-safe backup and matching
code/configuration; never drop lease attention or restore enabled policy to force
an older writer or downgrade. Runtime/agent coordination and multi-device FTD
acceptance remain separately gated, with live configuration unchanged.

## Internal parallel device-round coordinator — 2026-10-22

Compose the existing fenced profile with actual semantic sessions in an internal,
default-disabled ParallelSynchronizer. Do not add automatic startup/GET migration,
API/environment/Web activation or lab writes. Preserve deployed serial behavior.
Each worker owns an isolated Synchronizer context, token-bound shared queue and
discovery state; never share mutable active-device/cycle/error state across FTDs,
project a device owner into the global row or introduce a second job executor.

Validate the exact profile and complete configured inventory scope before claims:
no missing/out-of-scope enabled device or ADD profile, and explicitly supplied
agent capacity must cover the immutable lease limit. Bound active sessions by
both local slots and transactional device leases; at most ten tasks may wait.
Slow/failed devices must not stall healthy devices in other slots. Retain source
actors, original policy/attempt identity and every typed verification/result hook.

Freeze a cutoff per device after token acquisition and before initial read.
Discovery from complete initial/priority/final reads may admit at most 16 jobs and
check at most 64 policy rows per device session, with a 16-unfinished-job window.
Across ten devices this is at most 160 admissions/640 checks per round, still
subject to existing global queue/journal capacity. This scoped budget replaces
only the serial collector's global cycle budget in the new coordinator. Retain
the 16-mutation agent/session cap, authority/freshness/backoff/uncertainty checks
and original cutoff semantics; new discovery waits for a later round.

Ordinary completion releases only that token after RPC/session settlement, without
using/resetting the legacy global read cooldown. Caller cancellation requests
orderly drain: stop waiting workers and new mutations/discovery, await the current
operation with verification and session completion, then release its slot/fence.
Repeated cancellation joins the same drain. Never cancel a to_thread await and
treat that as RPC termination. Require the configured bounded RPC deadline to fit
the 5..240-second operation bound; renew leases with that bound plus 30 seconds,
not manual-read spacing. Callers must drain before event-loop shutdown.

Any failed RPC retains its lease, even an initial/final read; timeout/rejection is
not remote-quiescence proof or permission to reconnect. Keep known earlier typed
results, original unknown/late outcomes and immutable expiry ATTENTION. Unexpected
worker failure retains the fence. Forced internal/event-loop cancellation marks
the coordinator broken and refuses replacement rounds in-process. Other devices'
completed results and retained authority remain independent. Local detached status
does not recover leases or claim successful Web freshness.

This is a callable internal round, not continuous background dispatch, independent
baseline/manual deadlines, coalesced browser demand, urgent REMOVE ordering or
automatic uncertainty recovery. Retention remains with the owning service, not
competing device workers. Matching real agent pool/END guard-release settlement,
legacy migration and end-to-end Web/FTD acceptance still require coordinated work
and scoped activation. No new DDL/backup/rollout was needed; preserve compatible
code/checked SQLite-safe backup before eventual approved migration and never
erase fences, uncertainty or disabled authority to downgrade. See
[Parallel Device Rounds](manual/parallel-rounds.md).

## Internal continuous dispatch and read demand — 2026-10-22

Extend the explicitly enabled developer coordinator with independent device
dispatch, not a fleet-round barrier. No API/env/Web activation, live migration,
new authority, uncertain replay or lab writes follow. Retain exact profile/scope,
transactional fences, bounded local slots, typed results and default-off bulk ADD.
At most one task/session may run per configured device; slow devices cannot stop
healthy devices from starting another bounded session when a slot is free.

Track successful complete reads, baseline deadlines and coalesced manual demand
independently per device. Default intervals remain 300/60 seconds. Repeated demand
must not push its original deadline later. Required mutation verification/session
snapshots may satisfy pending demand without scheduling redundant reads. Deadlines
and local status never prove fresh data or clear failed/unknown work. Queue work
may run between read deadlines; idle devices must not reconnect just because
another device has pending jobs. Genuine errors/deferral/lease contention use a
short bounded rescheduling delay, never a hot loop or a global minute-long write
cooldown. In-memory timing is advisory and restart requires fresh observations.

In this explicit fenced mode, admitted live REMOVE work takes the next mutation
slot before bulk ADD, including REMOVE admitted after the original ADD cutoff.
Preserve REMOVE FIFO, current authorization/expiry/pause/protection/isolation and
same-device serialization; priority is not admission or conflict-override authority.
ADD remains cutoff-bound. A priority REMOVE must use the agent's current target
verification, not an initial snapshot's absence: an earlier command may already
have added that target. Retain original uncertainty and typed no-op/results.
Complete final snapshots may admit matching protected removal through the existing
policy path, so protection enabled during ADD is not delayed until baseline.

Manual demand due during an active session joins its next legal checkpoint,
after the current command/verification. Respect the existing one-checkpoint and
session command/time limits; join final reading or the next bounded session when
needed. Do not abort or fabricate completion. Shutdown prevents new sessions and
drains active RPCs as in parallel rounds, including repeated caller cancellation;
forced internal cancellation disables replacement execution in-process. Status
is detached local metadata, not a new HTTP contract. A read-only status request
never enqueues device work or migrates state. Transport END/device-guard settlement,
automatic uncertainty recovery, Web integration and actual lab activation remain
separate prerequisites before real continuous execution.

## Opt-in local cycle-settlement receipt — 2026-10-22

Preserve legacy BEGIN `10 version device:u16`, versions 1/2/3, all mutation/gate/
profile/command/time limits and END snapshot framing unchanged. Introduce explicit
BEGIN_SETTLED `16 version device:u16` with the same exact four-byte length and
sequence zero. Its initial complete snapshot is bound to opcode 16, so an old
agent cannot silently satisfy the capability. Never fallback/reconnect/replay on
rejection. The connection still binds one configured device; no command text,
route, interface, nonce-controlled storage or arbitrary operation is added.

After a successful ordinary END snapshot in this mode, require a separate exact
four-byte local settlement record `00 version 16 end_sequence`. Only emit that
record after bounded disconnect cleanup succeeds, the cycle/session resources
are dropped, the device/address guard is released and the pool worker has been
marked idle. A typed internal completion object retains the FD/record across that
boundary; finalization sends at most one nonblocking terminal packet and closes
the FD, with no SSH/CLI work or waiting for a slow peer. Do not expose IDLE while
any semantic handler/verification/cleanup is still running. A newly assigned
request may wait only for this bounded local postamble, not behind an active
handler. Failed/panicked workers remain stopped; no replacement/rearm authority.

The receipt attests local completed-handler/guard/slot ordering, not remote TCP
termination, current process liveness, future capacity or resolution of a lost
write. EOF, timeout, busy rejection and a final snapshot alone are not a receipt.
Cleanup failure/timeout, malformed/missing/wrong-version/sequence receipt or send
failure must fail closed. A strict client returns/publishes the final snapshot
only after the receipt, within the original END deadline and at most five seconds
after snapshot completion. Earlier verified job results remain intact; no unknown
attempt, policy, latch or retained incident is cleared or retried by settlement.

The internal continuous dispatcher requires explicit strict client capability and
a confirmed settled cycle before normal release; ordinary serial/round clients
remain legacy by default. No deployed environment/startup selector, migration,
new fixture or feature activation accompanies this extension. Validate shared
fixed vectors, real local SeqPacket receipt ordering and rapid consecutive
sessions without SSH; live FTD/multi-device acceptance and Web/runtime migration
remain separately scoped work.

## Continuous browser-status projection — 2026-10-23

The explicit continuous controller may expose its independent read demand through
the existing browser revision envelope, with an explicit `per_device` scheduling
mode. Preserve enabled/disabled inventory, per-device complete-read timestamps,
errors/staleness, pending manual demand, monotonic-derived eligibility deadlines
and concurrent semantic phases. Do not choose an arbitrary active device as a
single fleet cycle or leak internal ownership/fencing identities into the browser
projection. Fleet confirmation is the oldest enabled-device observation only when
every enabled device has a successful complete observation; a healthy device must
not mask an unread or failed one. Previous observations remain labelled honestly.

Repeated manual requests join demand without postponing its original eligibility.
In this mode keep the browser request control available during other device work,
cooldown and held failures, except for its in-flight HTTP submission or unavailable
controller. Pending counts and attention remain visible on panel indicators.
Countdown expiry proves no read, settlement or mutation success. Publish browser
data revisions for actual read/result publication and explicit already-committed
API changes, not merely elapsed deadlines or accepted demand. Healthy-device
updates must not wait for a held device; preserve user drafts and frozen reviews.

Authenticated no-store status and CSRF-protected demand keep the existing explicit
BFF field allowlist. Status never creates optional schema, admits policy/jobs,
resumes execution or clears uncertainty. A missing database must not be created by
the projection. Runtime selection is deliberately not added: existing API startup
remains legacy until version-aware admission/cleanup, lifecycle/retention, schema
compatibility and separately scoped transport/live acceptance are integrated.
No gate/profile change, migration or new lab fixture follows from browser support.

## Continuous runtime maintenance ownership — 2026-10-23

The explicitly enabled continuous controller owns one maintenance lifecycle,
separate from device workers and never alongside the legacy synchronizer.
Run ordinary request expiry at startup and five seconds after each completed
expiry pass; run existing evidence-aware queue/history retention at startup and
24 hours after complete success. Retain the existing 366-day default and 1..3653
configuration range. These timings are not device-write cooldowns or renewed
authority. Monotonic scheduling and existing UTC queue/history cutoffs remain
independent of browser traffic. Construction, disabled start and GET initialize
no optional storage; an absent database is not created to service maintenance.

Use the original queue expiry transaction without claiming device work or
interfering with RUNNING commands. Keep original request deadlines/results;
unsent bulk expiry remains CANCELLED, not a fabricated CLI failure. Pruning must
preserve all existing uncertainty, captured predecessors, linked evidence and
v2 absence barriers. Validate queue evidence before deletion; a queue-validation
failure prevents the history stage. Never reconstruct missing settlement, resume
policy, release/rearm fences or replay unknown writes as housekeeping. History
retention remains the established exception to append-only event storage, keeping
active observations and immutable policy/attempt/cancellation ledgers unchanged.

Queue pruning and history pruning are separate committed transactions. Report a
later-stage failure honestly: neither claim complete success nor pretend earlier
commits rolled back. Expected database/OS/validation failures retry only the
affected maintenance schedule after 60 seconds and remain visible while healthy
monitoring continues. Status/attempt deadlines never prove a completed purge.
Actual queue revisions/deletions publish data changes; unchanged passes do not
cause periodic content reloads. Structured failure logging includes no device
output/credentials or retained payload dumps.

Run synchronous database maintenance off the event loop with at most one call in
flight per lifecycle owner. SQLite still serializes database writes; no lock-free
or distributed-leader guarantee follows. Stop prevents new stages, drains an
already started call and device sessions, and must resist repeated stop-caller
cancellation. Forced internal cancellation/unexpected failure marks the lifecycle
broken and refuses in-process replacement. Cancelling a thread await is never
proof that its synchronous operation stopped. The API still needs explicit
version-aware runtime selection/admission and scoped migration/live acceptance;
this internal lifecycle creates no deployed selector, schema or lab authority.

## Restricted continuous API composition — 2026-10-23

Permit an explicit trusted Python factory dependency for a continuous API runtime,
without adding a browser/environment/CLI selector or changing deployed defaults.
The first API surface is intentionally observations, refresh demand, local preview
and existing Protected-IP policy. Require disabled ADD/bulk execution, empty ADD
scope, all incompatible legacy admission/restoration/cleanup-controller gates off,
socket/session/large-read mode, strict settlement and declared matching capacity.
Development authentication is not allowed in this composition. A real Unix client
must match socket/timeout/large/settled/empty-ADD settings, never silently fall back.

Validate exact existing v2/device storage, Store/agent ownership, already loaded
fixed inventory, read-spacing floors, timeout margin, retention and completed
legacy-protection migration before any runtime starts. Recheck at lifespan entry.
Refuse a configured inventory file rather than silently ignoring/upserting it;
this developer surface does not yet implement configured runtime/inventory reload.
No base/optional initialization, occurrence backfill, legacy environment import,
policy resume or authority conversion is allowed at construction/GET/first worker.
Default legacy startup refuses device-fence objects before initialization; partial
or damaged profiles cannot acquire legacy meaning. Unavailable status returns 503,
not a fake empty registry or successful device operation.

Bind one inactive/unbroken dispatcher to one API application, start only that
dispatcher and its maintenance owner, and drain both on shutdown. Do not adopt a
running executor or construct a parallel serial synchronizer. Existing compatible
legacy constructors retain their default initialization behavior; fenced workers
and the restricted policy reader explicitly skip queue initialization.

Before route handlers run, restrict this profile to the fixed supported methods/
paths. Refuse incompatible managed/import/manual mutation and old policy-read
workflows with explicit unavailability; never call them with fabricated legacy
context or guess an empty v2 state. Publish v2-format and capability metadata to
the existing no-store/authenticated BFF. Hide unsupported controls/navigation and
explain the restriction, but retain API enforcement even for crafted direct calls.
Absent/null capability fields preserve legacy rendering; only explicit false
restricts controls. No new external listener or trusted identity mechanism exists.

Protected-IP saves remain real-actor, revision/confirmation checked and atomically
retire matching maintenance; automatic verified removal and existing admitted
REMOVE work may still execute through the shared fenced queue. Observation profile
does not mean a no-write mock or permission to enable ADD. Disabling protection
never restores old standing authority. No migration, new live fixture, runtime
activation, uncertainty resolution or production readiness follows. General v2
write workflows, bounded managed views, nonempty migration and actual FTD/load
acceptance remain separate work.

## Version-2 policy views and policy-only revocation — 2026-10-23

Extend only the explicit compatible continuous developer composition with three
fixed private versioned operations: bounded policy page, exact selected-pair read
and single-pair policy-only RETIRE. `/api/v2/managed-shuns/page`, `/selection` and
`/retire` do not reinterpret v1 requests; all v1 managed workflows remain refused
in that composition. No deployed environment selector or execution gate changes.

Read at most 100 rows/pairs from the existing exact v2 registry (200000 retained
keys), using a SQLite readonly transaction for metadata, rows and evidence in one
snapshot. Missing/partial state is unavailable, never empty/initialized/repaired.
Pin pagination to revision and return explicit conflict on membership changes;
never silently expand/rebase a reviewed selection. Load original bulk authority
metadata once per distinct request on a page, not repeated full manifests per
target. No reader performs RPC, reconciliation, adoption, resume or admission.

Represent desired policy independently from observations and actual ADD evidence.
Retain original actor/generation/authorization, disabled devices, protection,
pending jobs and FAILED/UNVERIFIED attention across generations. Only VERIFIED ADD
supports a verified-application timestamp; NOOP/presence/missing evidence do not
prove creation. Missing unknown-job evidence stays visibly missing. No response
format grants execution capability or resolves uncertainty.

Permit existing Operator/Administrator local RETIRE through a separate frozen
review. Bind policy format, exact pair/generation/revision, actor/session, semantic
digest and original UUID key; recheck current role/CSRF and typed IP. Confirm only
the frozen versioned route, never current status to select a fallback. Require
an explicit v2 policy-only/no-device-work receipt. Stale review conflicts; lost or
malformed receipt is unknown and permits only the same-key retry. A validated
receipt is not negated by an optional later status failure. Replay is observational
and never disables a newer grant/generation.

The existing retirement transaction atomically revokes local policy and records
audit/receipt. It never admits REMOVE, interrupts RUNNING ADD, cancels independent
jobs, clears uncertainty/latches or enables/resumes standing policy. Existing
claim-time authority guards continue to reject retired standing work. Protection
and previously admitted REMOVE retain their independent safeguards. New view/
retirement capability flags are separate from unavailable general managed work.
No optional DDL, migration/activation/lab fixture or production acceptance follows.

## Version-2 ready-scope removal coordination — 2026-10-23

Permit a separate internal, default-false ready-only coordinator on existing
exact v2 fenced device storage. Read a frozen single-device or whole-fleet scope
for one exact IPv4 in a readonly snapshot. Fleet scope is the complete union of
active observations and enabled maintained targets, including disabled devices
and maintained-but-missing entries; never silently omit an inconvenient member.
Bind v2 format, mode, sorted device metadata, original intent/generation/authority,
target and global managed revisions, observed membership and protection revision/
state. A distinct action digest additionally binds 1..900-second delegation and
bounded reason. These local reads/digests grant no device authority or freshness.

Ready-only admission must recheck the entire original scope under one write lock.
Require real Operator/Administrator, canonical original UUID, explicit internal
capability, unpaused mutations, enabled devices inside the sealed executor scope
and exact current bindings. Reject the whole request on any overlapping pending
job, prior unresolved/failed ADD for a selected pair, unknown device outcome or
retained expired/attention device fence. Do not cancel or replay ADD, convert to
ordered waiting, shrink a fleet, or loop over single-target admissions. Ordered
RUNNING-ADD cleanup remains a later separate contract, not an implicit fallback.

Atomically retire all enabled managed targets and admit one whole-scope manual
REMOVE request through the existing shared queue, then retain its immutable
action/receipt in the existing managed request ledger. Preserve original grants,
attempts and outcomes; unmanaged observations are cleanup-only, never adopted.
Use one retained request slot and the existing reserved retirement budget; no new
DDL or per-target retirement-root loop. Roll back policy, queue, links and audit
together on late failure, even if an outer caller catches the error. Publish
accepted logs only after commit. Admission is not verified device removal.

Queue composition needs a separate literal default-false v2 ready-removal
capability and fixed scope; a scope label alone never bypasses the legacy guard.
Preserve all queue role/pause/rate/capacity/deadline/claim/fence/result checks.
All retained bulk managed-request keys remain reserved against new queue work,
including after ordinary queue pruning. Exact coordinator replay returns only
its original immutable receipt, never recreates jobs, renews deadlines, retires
new policy or clears uncertainty. Existing quiescent standing confirmation cannot
create new authority while admitted removals remain pending; future concurrent
grant admission must preserve that exclusion explicitly.

Expose readonly scope inspection only in the explicit continuous API profile;
no v2 removal POST, browser execution control, runtime selector, gate activation,
startup/GET initialization, lab migration/fixture or production acceptance follows.
Actual dispatched work still uses the existing continuous device worker, typed
verified responses, local settlement and retained fences; no second executor.

## Frozen v2 ready-removal Web/API admission — 2026-10-23

Extend only explicit developer composition with independent literal default-false
`ready_removal_admission_enabled` factory capabilities in API and Web. API enablement
requires the compatible existing fenced continuous runtime; refuse legacy enablement
before initialization. Web enablement requires socket/session/large-read mode and
production identity handling. No environment/CLI/request selector or lab activation
is introduced; legacy cleanup flags never enable this separate v2 workflow.

Provide distinct fixed v2 device/fleet POSTs for ready-only action, strict bounded
literal scope/actor/TTL/reason models and original UUID/digest. A disabled API
capability refuses before legacy/body dispatch. An enabled endpoint verifies the
route's exact device/fleet mode and sensitive-action lifetime, invokes the existing
whole-scope coordinator once, then publishes/wakes committed work only. Return 202
for admission/replay, never verified device removal. Keep all backend conflict,
unknown-result, actor/rate/capacity, protection and fence guarantees unchanged.

Web preparation is a CSRF-protected local read, even with execution off. Freeze
the exact v2 inspection, original action/key, actor/cookie, reason/lifetime and
expiry in a separate immutable review cache (at most ten minutes, five per subject,
256 total). Read scope only from the fixed v2 resource; verify complete descriptor,
expected IP/device/mode, readonly markers and digest. No arbitrary target/action
JSON from forms, partial fleet, legacy fallback or status-driven rebase is allowed.

Confirmation rechecks authentication/current Operator/Administrator, CSRF, typed
exact IP and review binding/expiry. It needs the local Web capability plus fresh
compatible API status/capability; status/DOM edits cannot enable a local disabled
gate. Recheck review expiry after status I/O before POST. Frozen v2 confirmation
never prepares a replacement scope or auto-retries/rekeys. Validate the complete
202 receipt against frozen count, retirement/revision, action/mode, unique original
job references and explicit admission-not-verification flags. Lost/malformed replies
remain unknown and permit only same-review/key retry. Optional later status failure
cannot negate a checked receipt. Native confirmation remains explicit while status
polling continues without replacing the token, target list, typed IP or focus.

Expose clear ready-only blockers and historical receipts: disabled devices stay
visible, RUNNING ADD is not interrupted or silently converted to waiting, unmanaged
targets are cleanup-only, and individual FTD outcomes remain separate from atomic
local admission. Default-disabled code does not authorize migration, live test
mutations, gate/profile changes or production acceptance. No new DDL or executor.

## Version-2 ordered-removal preflight — 2026-10-23

Introduce a separate local, read-only preflight before implementing ordered
admission. Reuse the exact ready-removal single/fleet union, but never reinterpret
its action, digest or receipt. Inspect all targets in one readonly SQLite snapshot
on the existing exact fenced v2 profile. Return READY, WAITING_ADD or BLOCKED for
each target, bounded stable blocker codes and an all-scope disposition. One
blocked member blocks the whole fleet; a ready member must not be promoted alone.
These classifications describe stored evidence at a supplied UTC inspection time,
not verified remote state, an admission guarantee or permission to send work.

Only a single RUNNING system ADD with its original linked request, current exact
intent/generation/authorization/target revision, retained RUNNING attempt and
matching live device executor may be proposed as a predecessor. Bind its original
request/job/attempt identity, original deadline, complete-snapshot identity/times,
started time and claim-audit owner/epoch. Refuse missing/mismatched audit, queued
or independent ADD, pending REMOVE, expired delegation, disabled/out-of-scope
device, pause, failed/unknown pair history, device uncertainty or expired/attention
fence. An expired RUNNING RPC remains unknown, not cancelled or safe to replay.
Malformed optional storage fails closed rather than appearing empty.

Use a separate domain-separated digest over the complete bounded preflight,
including inspection time, scope and captured predecessors/blockers. It is
observational only: no confirmation/admission action, TTL extension, durable
reservation, retirement, audit write, migration, startup hook, HTTP execution
route or executor is introduced. Reinspection after settlement may change the
descriptor; it never rebases an already frozen confirmation. Ready-only admission
must continue to reject RUNNING ADD and must not consume this descriptor.

Future ordered admission still requires a separately reviewed optional durable
whole-scope barrier/reservation, original-deadline accounting, evidence retention,
atomic retirement and shared-worker promotion. VERIFIED/NOOP, exact pre-write
deferral and failed/unknown results need distinct settlement rules; fresh observed
absence must never release unknown evidence. This preflight does not implement or
authorize any of those transitions, lab migrations or new fixtures.

## Version-2 durable ordered reservations — 2026-10-23

Add a separate explicitly initialized optional profile after exact fenced v2
storage. Initialization requires ordinary pause, suspended desired policy and
quiescent settled executors, preserves existing authority/receipts and is never
called by startup, GET or admission. No live migration follows from implementation.
Recognize the complete additive schema exactly; partial state is unavailable.

A distinct default-false internal ordered reservation coordinator accepts only
the separate STOP_AND_REMOVE_ORDERED digest: exact frozen single/fleet scope,
one or more exact captured RUNNING predecessors, original evidence/deadlines,
1..900-second cleanup lifetime and bounded reason. Reinspect all scope/predecessors
under the same write lock; reject readiness changes instead of silently falling
back to ready-only admission. Require real Operator/Administrator, unpaused
mutations, complete eligible scope and existing storage. Atomically retire all
enabled targets, reserve the whole cleanup scope and retain immutable original
action/receipt plus real-actor audit. No REMOVE job or device authority is admitted
in this packet. Original-key retries return only the original receipt and never
renew deadlines, restore maintenance or recreate work.

Reservations share the ordinary 1000 pending-target/2000 active-request and
10-per-minute actor budgets, and reserve one retained request-ledger slot within
the existing actual-retirement reserve. Held pairs reject independent manual
ADD/REMOVE, new standing grants and ready-only cleanup; protected automatic
removal remains independent. Policy remains retired after cancellation/expiry.
Only the original owner or Administrator may cancel a waiting reservation.
Existing shared expiry maintenance may expire elapsed waits, never dispatch them.
Neither operation changes/cancels a RUNNING ADD or resolves its original outcome.

Retain every captured ADD job, original linked request and claim-audit receipt
even after local reservation expiry/cancellation. Validate all held references
before either queue or audit pruning; malformed/missing evidence refuses pruning
before any deletion. Preserve original attempt/job states and immutable captured
identities while permitting their ordinary verified, failed/unknown or exact
pre-write-deferral settlement. Age, a later read and administrative revocation
are not uncertainty resolution. Retained roots/members have explicit capacity
limits; no automatic eviction, partial fleet or receipt-key reuse.

There is no promotion/second executor, ordered HTTP/Web route, runtime/environment
selector, migration CLI, automatic feature activation or lab write. Future worker
promotion requires its own reviewed whole-scope state transition and must retain
original cleanup TTL/reservations/evidence and per-device settlement safeguards.

## Version-2 ordered promotion and attention — 2026-10-24

Provide a separately initialized exact additive promotion ledger after the ordered
reservation profile, never initialized by startup/GET/admission. Upgrade requires
explicit capability, pause, desired suspension and existing quiescence, including
no active reservations; preserve all terminal original receipts and evidence.
Default-disabled promotion is a bounded local coordinator in the existing
continuous lifecycle, not another device executor or an environment selector.

Under one write lock revalidate the complete frozen scope, original authority,
retired identities, captured jobs/requests/claims and current device fences.
Wait while any captured ADD still RUNNING or its original session lease remains
live/unreleased. VERIFIED/NOOP alone does not prove local session settlement.
Require the captured epoch to be released or superseded through the existing
monotonic lease protocol; expired/attention fences and failed/unknown outcomes
cannot be released by fresh observations. Exact original pre-write deferral may
be cancelled unsent only with a matching retained typed-deferral audit and settled
session; never cancel/retry an independent or uncertain ADD.

Any failed/unknown/missing/inconsistent evidence or changed frozen membership,
protection, identity, pending independent work or disabled device yields a retained
whole-scope ATTENTION decision with no REMOVE work. Do not overwrite original
ADD outcomes, historical reservation receipts or retire/re-enable other policy.
Malformed profile data refuses coordination entirely. Pause waits without sending;
original expiry/revocation releases reservation authority, not uncertainty.

When all predecessors and fences qualify, one internal ADMITTING ticket transfers
the whole reserved scope into one original-key shared manual REMOVE request and
retains immutable original device/job references as ADMITTED. The ticket, queue,
links, decision and audit commit together; no per-device admission loop or partial
fleet commit. A separate literal queue capability plus fixed semantic scope and
exact original actor/scope/deadline/ticket are mandatory; a scope label alone grants
nothing. Discount only this root's already reserved target/request slots and do not
charge its actor twice. Pin delegation to original requested-at/expires-at, never
ceil/renew the original TTL. Other budgets/leases/claims remain authoritative.

ADMITTING is transaction-internal, never runnable; a persisted incomplete ticket
is unavailable and cannot be resumed automatically. Claim validates a complete
ADMITTED whole-scope receipt before any device work. Keep immutable original
predecessor/deferral and delegated cleanup job/request references through queue/
audit pruning. Missing evidence refuses pruning rather than inventing success.
Owner cancellation/expiry may revoke undecided/attention waiting, never reinterpret
already admitted work; ordinary queue controls then govern those jobs separately.
No attention rearm, automatic unknown resolution, ordered HTTP/Web confirmation,
live migration/gate activation or production acceptance follows.

### Version-2 private ordered-removal API — 2026-10-24

Provide distinct fixed private device/fleet ordered-reservation routes, never a
ready-route mode switch or a fallback that silently shrinks/rebases scope.
Require a separate literal default-false API factory capability, compatible
continuous ownership, strict local settlement and an already complete optional
reservation/promotion profile. Admission additionally requires the owning
dispatcher's separate promotion capability; requests cannot select either
capability. Validate this composition before binding/startup and again at startup.
No environment selector, migration, ADD enablement or deployed activation follows.

The request binds the exact canonical v2 scope, sorted complete typed predecessor
evidence, distinct ordered digest, original UUID, bounded TTL/reason and real
Operator/Administrator actor. One whole-scope reservation transaction rechecks
all state. A 202 response is the immutable historical WAITING_ADD reservation,
not current progress, REMOVE admission or verification. Replay preserves that
receipt, expiry and retired policy; it neither renews authority nor wakes work.
Read-only preflight must also work with admission disabled and missing optional
ordered tables, provided the exact base fenced profile exists.

Provide a separate no-store read-only status projection of original scope and
expiry, captured predecessor outcomes, retained ATTENTION and delegated REMOVE
job outcomes. Reads never promote, expire, migrate, repair or hint device work.
An ADMITTED decision is not verification: report verified removal only when every
original delegated REMOVE job is explicitly VERIFIED. Missing/inconsistent
evidence is unavailable, never empty success. Canonical UUID routes refuse
aliasing or caller-selected arbitrary commands/scope.

Owner/Administrator cancellation is a separate fixed local revocation operation
with strict actor-only input. It remains available when new admission/promotion
is disabled and while mutations are paused; it never resumes retired policy or
modifies a running ADD. Already admitted work conflicts and remains governed by
ordinary queue controls. Cancellation does not clear ATTENTION or uncertainty.
Frozen session/CSRF-bound Web consent remains a separate delivery prerequisite;
private API implementation alone does not enable a user-facing workflow.

### Version-2 frozen ordered Web consent and status — 2026-10-24

Provide separate device/fleet ordered review preparation and one fixed confirmation
route. Preparation is authenticated Operator/Administrator plus CSRF, local reads
only, and validates the complete bounded preflight digest, exact requested mode/IP/
device, target dispositions/blockers and canonical predecessor evidence. READY or
BLOCKED inspection is informational only: no confirmation token, silent ready
fallback, scope shrink or automatic resubmission. WAITING_ADD freezes original
scope/predecessors, separate action/digest, UUID, TTL and reason in an immutable
bounded actor/CSRF-cookie-bound ephemeral cache (five per subject, 256 total,
at most ten minutes). Confirmation accepts only CSRF, token and typed exact IP.
Recheck current identity/role, local expiry after status I/O and independent
literal default-false Web/API admission plus owning promotion capabilities.
Neither DOM nor metadata edits enable a disabled local capability. Submit exactly
one fixed private route with the original cached key/body and actual actor.

Validate the complete historical 202 WAITING_ADD receipt, literal flags/counts,
original UUID/scope/revision and exact canonical requested-at plus TTL deadline.
A lost/malformed reply is unknown: retry only the same review/key, never a new
scope/action/key. Later optional status failure cannot negate a checked receipt.
Metadata refresh cannot replace a frozen confirmation form or its typed input.

Provide a canonical-UUID authenticated read-only status permalink, including after
Web restart, with complete original scope/owner/deadline, all captured predecessor
outcomes, retained attention and all delegated REMOVE job states. Validate exact
typed projection and full admission/verification invariants before rendering;
missing/malformed evidence must remain explicitly unavailable, never success.
Passive status updates fetch only local API state, never request/hint device reads,
expire/promote work or overwrite dirty forms. Keep command completion and original
expiry independent; ADMITTED or administrative cancellation is not verification.

Owner/Administrator waiting revocation is a distinct CSRF/typed-IP POST to the
fixed original UUID, with real actor-only private input and no admission gate.
Recheck the original identity/scope locally and at the coordinator; a race to
ADMITTED conflicts instead of cancelling delegated work. Preserve historical
checked revocation separately if subsequent status fails. Disabled admission,
pause or browser restart does not resume maintenance, clear attention or replay ADD.
No schema/runtime selector, deployment/gate activation, migration, new fixture or
live/production acceptance is authorized by these Web controls.

### Version-2 durable import preparation API — 2026-10-26

Expose separate fixed private v2 draft create/list/page/proposal/cancel routes only
in the explicit compatible continuous composition. Use the bulk-profile classifier
and the shared queue's UTC clock, never a legacy registry fallback. Existing exact
base/fenced v2 and optional preparation storage are prerequisites; constructor,
startup and requests never initialize, migrate, repair, prune or resume anything.
An absent journal is explicitly uninitialized on owner-list inspection, not an
empty initialized workspace. Malformed profile/journal is unavailable.

Creation requires a current real Operator/Administrator, strict bounded text and
metadata, and one to ten distinct explicit enabled device IDs. Preserve the parser's
1 MiB UTF-8/20000-line/10000-row bounds and the complete <=100000-pair Cartesian
product. Invalid/duplicate source diagnostics and protected exclusions remain
visible; no silent truncation, scope rebase or inferred adoption. Retain only
generated diagnostics and intentional label/reason, not raw source/comments.
The existing four-owner/sixteen-global retained-draft and ten-minute lifetime
bounds remain; capacity failure evicts nothing. A successful create response
means a non-authoritative local draft, never policy, queue work or device success.

List/page/proposal are owner-bound local inspections; actor fields are supplied
only by trusted composition/BFF and never credentials. Reports stay frozen and
bounded to 100 targets and 100 diagnostic rows per page. Owner mismatch/unknown
reference cannot disclose another author's draft. Before rendering retained
metadata/members or cancelling a draft, verify its complete original header and
membership digest in <=100-row chunks in the same transaction; a same-count
substitution is unavailable, never a smaller/changed accepted report. A proposal additionally requires
current Operator/Administrator, canonical original preparation/operation UUIDs and
the separately retained preparation digest. Stream and verify the full membership
and all exclusions, refuse expired/cancelled/already-confirmed drafts and return
only the canonical v2 descriptor/digest/manifest with explicit non-authority flags.
It neither reserves an operation key nor creates a root or audit event; repeat
inspection never extends authority or grants confirmation permission.

Any authenticated owner may cancel only their unconfirmed draft, including after
role loss or during pause/disabled admission. Cancellation is not import-policy
or queue cancellation, never retires an already confirmed import or interrupts
ADD. A confirmed draft conflicts; original policy/receipts/jobs remain unchanged.
Reads and draft changes never hint/wake device work or alter managed/queue revisions.
Lost creation replies are recovered through the owner list, not automatically
retried as executable admissions. Strict fixed input forbids actions, arbitrary
CLI, caller-selected profiles/capabilities and reinterpreting legacy admission
routes/digests as version-2 authority. A constructible proposal is not a key
reservation; future confirmation must still reject any independently occupied key.

Advertise preparation inspection separately from general managed workflows and
keep v2 policy confirmation/execution unavailable. No Web confirmation, runtime
selector, optional lab migration, live import fixture, policy activation or
production acceptance follows from this non-authoritative API increment.

### Version-2 preparation Web workspace and proposal inspection — 2026-10-26

Provide a distinct compatible-v2 Web workspace, selected by its narrow preparation
capability rather than general managed/execution flags. Preserve legacy navigation
when that capability is absent; direct v2 requests never fall back to v1. Workspace
reads recover only the authenticated owner's bounded saved drafts and configured
public device labels. Missing journal is explicitly uninitialized and disables
creation; unavailable/malformed state is not an empty healthy workspace.

Creation is an explicit Operator/Admin CSRF POST accepting only bounded source,
selected canonical device IDs and intentional label/reason. Revalidate UTF-8,
parser/device limits and the actual actor before the one fixed private API call.
Strictly check the 201 reference/digest/product and non-authority flags before a
canonical report redirect. Lost/malformed replies are unknown: do not automatically
retry, fabricate success or select the latest draft as the result. Recover through
the owner list. Preserve transient user input, without logging or persisting raw
source, and stop repeat submission of that uncertain form until explicit recovery.

Provide canonical owner-bound draft report links, 100-row pagination and separate
read-only exact v2 proposal inspection. Validate strict counts/flags/UTC times,
state/confirmation references, device/member/diagnostic pages and immutable
preparation digest before rendering. Mark invalid/duplicate/protected exclusions
conspicuously; show frozen classifications, not current device evidence. Derive a
stable domain-separated v2 operation UUID for proposal inspection only, distinct
from the preparation and legacy workflow. Validate the canonical descriptor/digest,
manifest, original preparation/revisions/metadata and all exclusion totals against
the report. Zero-accepted, expired, cancelled or confirmed drafts cannot prepare a
proposal. No recurring-policy consent, confirmation POST or device work is added.

Any authenticated owner may explicitly CSRF-cancel their unconfirmed draft using
its original UUID, including after role loss. Validate the draft-only receipt;
checked cancellation remains historical if follow-up status fails, while unknown
replies permit inspection/retry of only that draft. Confirmation races remain
conflicts, never cancellation of standing policy/jobs. Passive metadata refresh
must preserve pasted input, selected devices, frozen report/review and focus, and
never create/cancel drafts, refresh FTD or reclassify/renew anything. Escape all
operator metadata, localize timestamps with timezone and preserve no-store/identity
boundaries. No schema/gate/runtime selection, lab migration/activation, bulk fixture
or production acceptance is authorized by these non-authoritative Web controls.

### Version-2 suspended standing-import confirmation — 2026-10-26

Add a distinct fixed private standing-confirmation route and owner receipt list/
100-member report reads on the compatible existing v2/fenced continuous profile.
Require independent literal default-false API and Web factory capabilities, never
request/environment selectors. API enablement also requires a nonempty immutable
trusted set of reviewed addition-profile device IDs, bounded to the existing sealed
enabled device scope; it attests eligibility only and never enables agent ADD or
loads credentials into API/Web. Disabled admission requires an empty scope. Validate
composition before binding and at startup; never initialize optional state.

Use the existing atomic BulkPolicies.confirm contract unchanged: suspended desired
execution, unpaused new authority, settled/quiescent leases and no pending/uncertain
work; exact original full manifest/preparation/owner/device identities/revisions/
classifications/metadata; current Operator/Admin, exact accepted count and explicit
recurring consent; retained capacity/reserve and original-key guards. One write
transaction stores the whole classified scope/policy/receipt/audit or nothing.
Concurrent observation sessions cause conflict, not a relaxed lease or automatic
retry. No partial selected-device grant, legacy admission loop, resume or enqueue.

The strict private body binds bounded canonical v2 descriptor/digest, literal
accepted count, consent and real actor; original Idempotency-Key must equal the
descriptor operation UUID. Historical replay preserves original authority/receipt
and cannot re-enable retired targets. A checked result means policy_saved,
policy_only=true, device_work_admitted=false, restoration_suspended=true, not a
verified ADD. New commits update local metadata only, without waking device work.
Receipt reads remain owner-bound and available with admission disabled and after
draft expiry/pruning. Full retained root integrity precedes reports; missing or
corrupt evidence is unavailable, never fabricated success/current policy state.

Web preparation is a separate CSRF Operator/Admin POST that validates the complete
original proposal/report, freezes descriptor/digest/summary/operation key in a
bounded immutable subject/CSRF-cookie cache (five per owner, 256 total, <=ten
minutes) and never grants authority. Paged inspection rechecks original digest/
metadata without rebasing. Confirmation accepts only CSRF/token, canonical typed
accepted-pair count and an explicit literal recurring-consent checkbox. Recheck
identity/role/cookie/local expiry after metadata I/O and both independent gates
plus complete trusted profile scope before one fixed private submission.

Validate the complete historical receipt, typed counts/classes/revision/flags and
original subject/actual confirmation actor. Lost/malformed responses are unknown:
retry only the frozen original review/key, never rekey/split/rebase or replay ADD.
Optional follow-up metadata/report failure cannot negate a checked policy receipt.
Frozen forms retain focus/count/consent during metadata updates; GET never confirms.
Saved owner receipts provide restart/lost-reply recovery, explicitly separate from
device progress/current maintenance. Keep ADD/restoration/legacy gates off, desired
execution suspended, no runtime selector/DDL or lab migration/activation/fixture.
Confirmed-import cancellation and executable concurrency/recovery remain separate.

### Version-2 confirmed-import cancellation surface — 2026-10-26

Expose the existing whole-root BulkCancellations coordinator through fixed private
review, reviewed-member-page, cancel and current-cancellation-report POSTs on the
compatible continuous composition. Cancellation revokes existing authority, so it
needs no new admission/execution gate and remains available during ordinary pause,
suspended restoration and disabled ADD/standing admission. Existing exact optional
storage is mandatory; never initialize/migrate/repair from construction, startup
or requests. A narrow interface capability is not proof of storage readiness.

Require the original owner with current Operator/Admin permission or another
current Administrator. Bind actual current actor, original import UUID, five-minute
UTC review, digest and exact accepted pair count. New read-only member pagination
rechecks the complete review digest/count and expiry before returning <=100
accepted members; current state changes conflict without rebasing the review.
The full original scope, authority and held attempt evidence stay authoritative.

Reuse one atomic existing cancellation transaction. Retain adopted/existing and
verified/no-op applied policy, retire exact unsent/failed/unknown original grants,
cancel only their owned unsent jobs and capture RUNNING ADDs for shared-result
settlement. Never send REMOVE, interrupt RUNNING work, revive retired policy, touch
newer authority, clear uncertainty or add another executor. Current statuses do
not alter the immutable original cancellation receipt, including WAITING_OUTCOME.

Web consent is a distinct explicit CSRF/Operator POST with a bounded immutable
subject/cookie-bound cache, <=five minutes/five per subject/256 total. Freeze the
original review/count/digest, preserve typed count during paging/status updates,
and require its exact typed count before one fixed private cancellation call.
Recheck session/role/expiry after I/O; no request supplies actor/action/profile
authority or a replacement key. Validate exact receipts and member/outcome/attention
projections. Unknown replies allow only same original review/actual-actor retry or
inspection of the durable cancellation permalink; actor changes may require read
recovery rather than replay. Checked receipt survives failed follow-up reads.

Provide bounded local current-status pages with initial/current dispositions,
waiting/attention counts and conspicuous retained-policy/no-unblock consequences.
Passive updates preserve form state and read local evidence only. GET never
confirms, settles, expires/promotes work, queries FTD or infers missing evidence as
success. Owner policy receipts remain private; administrative cancellation authority
does not grant access to another owner's full private policy receipt. No schema,
new gate/runtime selector, lab migration/activation/fixture or FTD acceptance.

### Fenced concurrent standing admission — 2026-10-26

Add a separate opt-in policy-only coordinator and fixed `confirm-concurrent` route;
retain suspended/quiescent confirmation unchanged. Independent literal default-
false API/Web concurrent capabilities require their existing standing-admission
capabilities and trusted eligible device scope. They do not enable agent ADD,
resume execution, select a runtime/environment profile or migrate storage.

Concurrent admission requires the exact existing fenced-device/dispatch/captured
profile and an unowned global executor. Under the same write transaction, bind
the full original descriptor/preparation, current actor, count/consent, current
managed/protection revisions, classification/authority, device identity/profile,
expiry and retained capacity/reserve. Bind the expected desired-suspension boolean
from the frozen review; a new grant conflicts if it changed. Preserve one whole-
scope transaction and all original-key/evidence semantics.

Permit independent valid device leases and unrelated queued/running jobs. Every
selected device must be IDLE or have an unexpired valid LEASED fence with no future
timestamp; ATTENTION/expired fences or retained device-level unknown/reconciled-
absent evidence block it. Every accepted device/IP must have no queued/running/
uncertain work, no retained failed/unknown ADD across generations, no unattributed
ADD job, no unsettled cancellation or held ordered cleanup. Validate all retained
held references even outside this scope; malformed evidence never becomes absent.
Protected exclusions gain no authority. One conflicting member refuses everything.
Recheck selected fences, expected suspension and clock before commit; never renew,
steal/release a lease, interrupt a command or resolve an outcome from admission.

Reuse the common policy/membership/audit transaction. Concurrent receipts add the
literal `admission_mode=fenced` and actual historical `restoration_suspended`
boolean, while retaining `policy_only=true`/`device_work_admitted=false`. Existing
unmarked receipts remain the suspended contract. Full root/receipt validators
recognize both exact forms; cross-mode key reuse conflicts. Same-mode original-key
replay preserves the original suspension/authority and never re-enables policy.
No new job/hint/resume follows confirmation. The shared bounded dispatcher alone
may later act when separately enabled, using a complete read started after new
authority (equal millisecond timestamps also refuse); admission never makes an
older snapshot eligible. Old portion revision
checks and per-device serialization/priority/budgets remain intact.

Freeze Web admission mode and expected suspension alongside the immutable original
proposal/summary/key. No posted mode/action selects authority. Use one fixed route
for that frozen mode; require independent local/API concurrent capabilities and
refuse mode drift without fallback/rekey/rebase. Keep exact count/recurring consent,
CSRF/current actor/post-I/O expiry and same-key unknown-reply recovery. Forms and
historical receipts must honestly distinguish suspended and already-active desired
policy, never claim verified device work or resume execution. No live migration,
gate/profile activation, fixture or production acceptance follows this delivery.

## Configured continuous observation runtime — 2026-10-30

Add a strict process-start selector, `FTD_SHUN_API_RUNTIME`, defaulting to
`legacy`. The only new value is `continuous-observation`. It constructs the
existing restricted continuous composition, not a new executor or a general
bulk-write release. Explicit developer injection remains separate and cannot
be combined with configured selection. No request can select a runtime.

Configured selection requires an existing exact fenced profile and non-creating
SQLite `mode=rw` connections, including when a checked file disappears before
opening. A supplied Store contributes only its path to this configured owner.
Require a public inventory of at most ten devices. Compare every retained database device ID,
hostname, IPv4, enabled state and pinned host key against that file, including
disabled devices. Reject missing/extra/changed identities without upsert, deletion,
base initialization or migration. Freeze the full semantic public configuration,
including interface allowlists/addition profiles, and recheck it before lifespan
start. Reordering/whitespace alone is not drift. There is no hot reload or implicit
address/host-key reconciliation; a future reviewed inventory transition must
preserve evidence and old authority before changing connection metadata.

Use only the real strict Unix client, large settled cycles, empty executable ADD
scope and the existing single maintenance/lifecycle owner. Read spacing, timeouts,
history retention and declared agent concurrency must match the existing profile.
Reject development authentication, legacy admission/controllers and mixed factory
capabilities. All optional v2 admission/promotion capabilities remain false in
configured mode. Existing admitted REMOVE and Protected-IP removal remain possible;
the word observation is not a no-write promise. Construction/preflight starts no
task, reads no credentials and makes no socket/device call. `ftd-shun-api --check`
validates this composition without running it; it neither proves transport readiness
nor authorizes activation. Do not run that check through legacy initialization.

No optional schema or live gate is initialized/changed. Legacy/nonempty migration,
inventory edits, new fixtures and executable lab acceptance still require their
separate reviewed contracts/authorization. Rollback must retain matching code and
fenced storage: selecting legacy never downgrades or erases device fences.

## Legacy-to-fenced transition inspection — 2026-10-30

Before implementing nonempty conversion, supply a separate trusted-host read-only
inspection command. Its first supported source is the exact current base/queue
schema plus all seven legacy managed tables, optionally the exact non-authoritative
preparation journal. Unsupported, partial, modified, incident/closure or already-v2
profiles refuse; never suggest deleting evidence to make a profile eligible.
Generate expected contracts in memory from trusted code, not by initializing the
selected database. Open the source with SQLite `mode=ro` and `query_only=ON` inside
one snapshot; no Store startup, environment/credential/socket/device read, DDL,
audit, recovery action or backup file creation follows inspection.

Stream a deterministic, typed, domain-separated SHA-256 manifest over the complete
schema, logical SQLite header metadata and every retained row, including sequence state, not only active
targets or counts. Bound Python row batches. Bind complete canonical public
inventory and the requested future sealed scope/concurrency into a separate
five-minute inspection digest. Reinspection with the original timestamp/digest
must refuse drift/expiry/future time without rebase. This digest is observational,
not a policy/migration token or proof of remote quiescence, and cannot be passed
to an existing apply/resume action as authority.

Report only fixed summaries/counts/digests and explicit operational blockers:
unpaused ordinary or desired execution, any global lease, pending/uncertain/
read-reconciled work, failed/unknown managed attempts, unfinished/attention cleanup,
future cooldown, unfinished protection migration, enabled legacy policy or changed
device identity/trust. A first conversion contract will be retired-only; never
retire enabled policy as a preflight side effect. Missing old terminal queue
evidence must remain honestly missing, not reconstructed. Inventory must match
all retained IDs including disabled ones and have 1..10 total/at least one enabled
device. Preserve every original receipt/actor/key, generation/tombstone, attempt,
TTL/result, link, observation/occurrence/provenance, protection and audit record.

Always report `migration_available=false` and `migration_ready=false`: operational
preconditions alone do not complete semantic/archive/key-reservation compatibility,
the converter, checked backup, rollback or separately scoped activation. No HTTP,
startup hook, migration apply, policy grant/resume, uncertainty resolution, lab
inspection/mutation or fixture authorization is introduced by this increment.

## Pre-release laboratory policy — 2026-10-30

The operator confirms that this project has no production use and the current
FPR1010 is a test device on their desk. Optimize for a usable working version;
do not impose released-product compatibility requirements on unreleased dev data.
This amendment supersedes conflicting earlier lab-authorization and migration-
planning statements. Older experiment results/limitations remain truthful history.

Ordinary in-scope implementation, validated deployment, explicit clean-profile
initialization and bounded semantic device tests on the known lab can proceed
without a new approval for each fixture, schema initialization or tested gate
selection. Announce writes and scope, use fresh labelled test authority/keys,
verify results and record the outcome briefly. No arbitrary CLI, unsafe profile
shortcut, fake Web identity, automatic uncertain-write replay, evidence clearing
or fabricated success becomes permissible. Default-safe configuration examples
and the existing secret/authentication/UDS/host-key/verification boundaries remain.
Ask only when the target/impact is unclear, scope materially expands, secrets/
trust/network changes are involved, or the action is materially destructive.

Backward conversion of legacy development databases is not on the release critical
path. Prefer an explicitly initialized clean DB in a separate path/volume, keeping
the old test database as a private archive rather than overwriting it. Preserve
inventory/credentials and explicitly transfer useful settings such as Protected
IPs if needed; never infer new standing consent from archived imports, queues,
requests or observations. This is a new dev environment, not a migration or a way
to relabel old unknown operations as settled. Drain old work before switching.
No startup/GET silently resets, repairs or replaces a store; no broad deletion is
authorized. Existing migration inspectors/incident tools can remain optional, but
their further extension is not required to ship the working lab version.

Released-data compatibility, verified upgrade/migration and release rollback
procedures become required from the first operator-designated real release
published on GitHub with a version tag. A footer number, commit, dev deployment
or experimental/RC tag alone is not that release decision. Do not create/publish
tags without an explicit request. A real tag must identify tested artifacts,
documented capabilities/limits and supported installation/upgrade/backup/rollback
procedures; it is not proof of untested FTD behavior. Security and truthful
verification apply throughout development, not only after the first release.

## Fresh development profile and configured managed runtime — 2026-10-30

Provide an explicit development initializer for a new, absent database path.
Build the complete base/queue/v2 cancellation/attempt/captured/dispatch/device/
ordered-promotion profile privately, validate it, checkpoint SQLite and publish
the finished file exclusively without overwriting anything. Failure before
publication leaves no partial destination. Never convert/reset an existing store
or initialize from startup/GET. Load 1..10 public devices and their sealed enabled
scope; optionally copy only validated current Protected-IP settings from an
explicit readonly source, with fresh maintenance audit. Copy no old authority,
jobs, observations or receipts. Initial empty desired execution may be ready with
a fresh-read barrier: no target or ADD exists until real recurring Web consent.

Add `continuous-managed` as a separate explicit API/Web runtime selection on
existing exact prepared storage. Legacy/observation defaults and behavior remain.
Use the same one fenced continuous owner, strict settled large/v3 transport,
bounded discovery, per-device ADD profiles and configured matching agent capacity.
Require an explicit supported addition profile on every enabled device; freeze
that public scope and recheck at start. Select existing concurrent standing,
ready/ordered removal and shared promotion capabilities in this trusted process
composition, never from a browser field or by mixing injected owners/capabilities.
Both API and BFF must independently select the managed profile. Legacy admission/
restoration/controller switches remain off, rather than constructing two workers.

Use existing exact whole-scope reviews, real actor/CSRF, receipts, uncertainty,
lease, protection-retirement and original-key guards unchanged. Unavailable
legacy endpoints stay refused; no general command route or legacy policy resume
is introduced. Status must distinguish the managed runtime and its ADD capability
from actual authority, verified work and unsupported workflows. Startup/check
never grant policy, initialize storage or prove agent/device readiness. Selecting
managed mode can dispatch already authorized work and protection; announce that
operational impact. This is laboratory integration, not multi-device/load or
production acceptance, Emergency Purge or automatic uncertainty reconciliation.
