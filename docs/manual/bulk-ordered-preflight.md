# Version-2 Ordered-Removal Preflight

Status: local read-only inspection foundation. A separate default-off
[durable reservation component](bulk-ordered-reservations.md) now implements
atomic retirement/waiting on an explicitly initialized optional profile; this
inspector still does not admit or initialize anything. Worker coordination is now
implemented separately in the default-off [ordered promoter](bulk-ordered-promotion.md).
A separate [private ordered API](ordered-removal-api.md) now exposes this
read-only inspection and independently gated reservation/status/revocation.
Frozen Web execution control, an environment setting and live activation remain
unavailable. The
existing [ready-only confirmation](ready-removal-confirmation.md) remains separate
and rejects pending ADD rather than silently switching modes.

## What is inspected

`BulkOrderedRemovalScopes(store).snapshot(ip, device_id=None, now=None)` reads an
existing database with SQLite `mode=ro` in one transaction. `ip` must be an exact
`IPv4Address`; an optional device ID selects one retained/observed target.
Otherwise the complete fleet union is active observations plus enabled managed
policy for that IP, at most ten devices. Missing-but-maintained and disabled
members are not dropped; multiple interfaces remain one target. Unmanaged
observations do not acquire maintenance. Missing storage is never created, and
unrecognized/partial optional schemas fail closed.

The matching `read(db, ip, device_id=None, now=None)` composition hook accepts a
caller-owned transaction for atomic admission reinspection; it performs only the
same local reads and never commits, initializes or grants authority by itself.

The supplied inspection time must be timezone-aware UTC; omission uses current
UTC. It is not a clock override for execution. The result contains:

- The unchanged canonical v2 removal scope and its separate `scope_digest`.
- Each device's `READY`, `WAITING_ADD` or `BLOCKED` disposition, stable blocker
  codes and an optional exact predecessor description.
- Whole-scope disposition, waiting/blocked target counts and global blockers.
- `read_only=true`, `execution_available=false`, `device_work_admitted=false`.
- An `inspected_at` UTC timestamp and separate SHA-256 `preflight_digest` binding
  the complete descriptor. Same snapshot/time gives the same digest; later
  inspection, evidence or scope changes may change it.

`READY` means no inspected local blocker, not fresh Cisco absence, checked queue
capacity, authorized admission or proof that a session has ended. `WAITING_ADD`
means exact stored evidence can describe a possible future predecessor, not that
any durable waiting request has been accepted. A single blocked member blocks
the whole fleet. Ready members cannot be promoted separately.

## Exact RUNNING ADD evidence

A proposed predecessor must be the one current system-owned RUNNING ADD, with
its original linked request and retained RUNNING bulk attempt. Validate the
current intent, generation, authorization and target revision; a stopped or
different generation is not reinterpreted as permission. Bind original canonical
request/job/snapshot IDs, request/deadline/started/snapshot times and current live
executor owner, epoch and deadline. An indexed, at-most-two-row claim lookup must
find exactly one original `SHUN_OPERATION_RUNNING` audit receipt, matching the
job, actor, action, source, device/IP and current executor epoch. Missing,
duplicate, malformed or old-epoch audit is not replaced by a convenient record.

The predecessor exposes the original IDs, times, executor token and claim-event
ID, plus a domain-separated digest over the original attempt/job/request/fence/
claim records. No secret or Cisco output is read. It never extends the original
ADD deadline or proves a remote command has stopped.

## Blockers

| Code | Meaning |
| --- | --- |
| `MUTATIONS_PAUSED` | Global durable mutation pause; independent policy controls remain unchanged. |
| `DEVICE_DISABLED` | Target is retained but disabled. |
| `DEVICE_OUTSIDE_EXECUTOR_SCOPE` | Target is not in the sealed device executor profile. |
| `DEVICE_FENCE_ATTENTION` | Device has retained executor attention. |
| `DEVICE_FENCE_EXPIRED` | Original live lease deadline has passed; no successor is granted. |
| `DEVICE_CLOCK_REVERSED` | Inspection predates retained executor metadata. |
| `DEVICE_OUTCOME_UNKNOWN` | Device has UNVERIFIED/RECONCILED_ABSENT queue evidence or an unknown bulk attempt, including on another IP. |
| `PAIR_ADD_ATTENTION` | This pair retains failed/unknown ADD evidence. |
| `PENDING_REMOVE` | A REMOVE already owns the active pair. |
| `ADD_NOT_RUNNING` | ADD is queued, including exact pre-write deferral; no takeover/replay occurs. |
| `ADD_BINDING_UNAVAILABLE` | A running ADD cannot be bound to all required original/current evidence. |

Corrupt optional profile/held pending evidence may raise an unavailable-state
error instead of yielding a descriptor. Missing evidence is never an empty or
successful result. Blocker text contains no exception output or raw CLI data.

## No state transition or rollout

Inspection does not create an operation/request, reserve capacity, retire policy,
append audit, cancel/defer a command, acknowledge uncertainty, refresh the agent,
resolve an expired lease or migrate anything. Reinspection after VERIFIED/NOOP
may report ready; FAILED/UNVERIFIED remains blocked, and exact pre-write deferral
remains queued/blocked. No result authorizes a retry. The inspection digest is
not the ready-removal digest or a future ordered-admission action/key.

No schema or operating configuration changes, backup/restore, service restart or
lab command is needed for this packet. Code rollback removes the unused local
component only; no durable state has been created to undo. Do not initialize an
optional lab profile merely to try it. Tests explicitly create disposable v2
profiles, corrupt only those fixtures, and exercise actual synthetic queue claims
and results without a device transport.

The separately migrated reservation and promotion components now supply the
whole-scope barrier, original cleanup TTL/capacity transfer, atomic retirement,
predecessor evidence holds and shared-worker-only promotion. This inspector still
grants nothing. Retain original uncertain outcomes; observed absence cannot
release them. Exact deferral, cancellation, expiry, pause/restart, protection
priority and whole-fleet settlement remain part of the execution checks.
Frozen ordered Web/API consent and distinct default-
off admission capabilities must be added separately; no new lab authorization is
implied. See [the normative contract](../architecture-and-security-design.md#version-2-ordered-removal-preflight--2026-10-23).
