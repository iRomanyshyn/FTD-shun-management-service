# Fenced Per-Device API Leases

Status: implemented optional lease/queue profile on disposable development state.
An internal [parallel round coordinator](parallel-rounds.md) now composes these
primitives with actual sessions; there is no background/API activation procedure. No lab migration,
feature gate, environment value, schema, service or FTD operation was changed.
The deployed serial profile remains supported without implicit conversion.

## Purpose and ownership

The transport can now handle [bounded agent concurrency](agent-concurrency.md),
but API coordination also needs one independent owner per device. `DeviceLeases`
supplies actual transactional claims with a fixed `DeviceLease` token containing
device ID, canonical worker UUID and strictly increasing epoch. `DeviceOperationQueue`
binds that token to the **existing** operation queue; no second job table or
executor, temporary global-owner projection or fabricated actor is used.

Claims are default-disabled internal capabilities. An enabled claim requires the
exact existing profile, an enabled in-scope device and no original device-level
unknown/read-reconciled barrier. A device already owned returns no token. The
immutable profile bounds simultaneous LEASED rows (including expired ones until
recovered), independently of the legacy global cooldown. Four is the developer
default, configurable to 1–10 at explicit initialization; it is not a changed lab
default or measured FTD capacity.

All mutation claims, ADD/REMOVE results, exact deferrals, renewals and releases
check device/nonce/epoch and a live deadline. Lease duration is a literal 5–300
seconds. Old epochs cannot publish even if a worker UUID is reused. Transaction-
end checks refuse late expiry, rolling back job, occurrence, audit and journal
updates together. A lease cannot be released while its device has RUNNING work.
Renewal never resets the epoch or revives an expired original deadline. Running/
result/deferral queue audit includes the exact executor epoch/owner without
changing original request actor, roles or standing authority.

## Expiry is not permission to steal

A claim encountering an expired device lease does not grant a replacement. It
atomically records that device's RUNNING jobs as UNVERIFIED through the shared
result/cancellation journal and captures the original lease as ATTENTION. Other
devices' RUNNING jobs/leases are untouched. Missing/malformed original evidence
refuses the whole recovery transaction; it is never reconstructed as success.

Even an expired read-only lease may have an outstanding RPC. Its ATTENTION retains
the original device, nonce, epoch and deadline; SQLite guards prohibit clearing
it. Status is read-only, reports overdue leases separately (`expired` and
`needs_attention`) and never performs recovery. Retention/restart/observation,
capacity pressure, a new owner or disabling the device cannot resolve it.
No release/rearm/HTTP decision route exists in this component.

### Local pre-submission release

The continuous/parallel worker now has one narrow automatic path for a typed local
socket-connect failure before its very first BEGIN send. `release_unsubmitted`
checks the exact live token and rejects RUNNING/UNVERIFIED/read-reconciled jobs,
UNVERIFIED bulk attempts and any `SHUN_OPERATION_RUNNING` audit for this epoch/
owner, even if that claimed job later succeeded. It atomically appends
`DEVICE_LEASE_NOT_SUBMITTED` and normal `DEVICE_LEASE_RELEASED`, leaving policy,
jobs and observations untouched. Audit/deadline failure rolls back the release.

This is not an override for expiry, old holds or submitted-session uncertainty.
The worker must also prove that the error came from its first local connection
attempt; a later exception of the same type cannot release anything. No HTTP
caller or decoded wire response can select this classification. See
[retry behavior and limits](continuous-dispatch.md#failure-backoff-and-shutdown).

`release_unopened` applies those same checks with distinct
`DEVICE_LEASE_OPEN_FAILED` audit, only for a first-call exact terminal
[SSH-opening failure proof](opening-recovery.md), not a generic SSH error.
Neither method clears old holds or changes original results.

An expired lease converted to ATTENTION is no longer a valid LEASED owner, but
that does **not** prove its old RPC has stopped. A coordinator must still
bound outstanding local tasks and agent slots and obtain quiescence evidence;
do not treat a free lease quota as permission for unlimited replacement RPCs.
The automatic evidence-based recovery contract remains separate work.

## Explicit optional profile

`DeviceLeases.initialize` requires exact existing
[bulk dispatch storage](bulk-queue-admission.md), ordinary mutation pause, desired
suspension, no global owner/deadline, no pending/unknown work or captured waits,
and no existing device lease/attention. Full original source roots are validated.
It freezes 1–10 already configured enabled device IDs and the concurrency limit,
creates idle epoch-zero rows and seals the scope in one rollback-safe transaction.
It preserves every original policy/request/manifest/attempt/receipt and does not
resume desired policy or grant a lease.

The two optional tables are `managed_bulk_device_profile` and
`managed_bulk_device_executors`. Profile/device identity is immutable, rows cannot
be deleted or appended after sealing, epochs are monotonic and ATTENTION is
retained. Idempotent initialization requires the original scope/limit; it never
repairs partial state or extends the inventory scope. Adding another device to
this profile requires a separate reviewed extension, not restart-side adoption.

Database guards reject global-owner/deadline updates and desired-policy resume
while any device lease/attention remains. Old writers cannot silently execute in
parallel with the new mode. Exact schema/profile checks also reject unsupported
or missing state. In-memory expected-schema construction uses only a dummy global
trigger target; it does not initialize a real queue or run a live migration.

Startup, GET, base queue initialization and controller construction never create
these optional tables or unpause/resume anything. There is no activation CLI,
`.env` setting or Web route for this profile yet. Synthetic initialization and SQL
activation in tests are not a lab runbook or authorization.

## Shared behavior and runtime integration

Bulk admission/discovery use the same scoped executor selector as queue claims
and results. Current intent/generation, protected policy, fresh complete absence,
capacity/backoff, cutoff and typed-result requirements remain. Import cancellation
and permanent protection retirement still compose with RUNNING outcomes and
immutable wait settlement. Legacy global profiles keep their existing behavior.

The global executor row remains the mutation-pause/revision/legacy metadata
source, but it is never temporarily populated with a device's owner. Its old
read cooldown is preserved, neither copied into each device nor erased to speed
up work. The internal [parallel coordinator](parallel-rounds.md) now provides
independent worker/session lifecycles and per-device bounded refill over these
queues, including cancellation drain without releasing an outstanding RPC slot.
An internal [continuous lifecycle](continuous-dispatch.md) now adds independent
baseline/manual timing, checkpoint demand and opt-in REMOVE priority. Application/
Web integration and real transport acceptance remain pending; local strict
settlement is now [implemented separately](cycle-settlement.md). No current service startup
automatically switches to this profile or runs a device queue in the background.

## Backup, rollback and validation

Before any non-disposable use: settle RPCs, stop old writers, pause ordinary
mutations/suspend desired policy, obtain scoped migration/activation approval and
retain a private checked SQLite-safe backup with matching code/configuration.
Never copy an active WAL file. No backup/restore was needed for the unchanged lab.

Older bulk writers reject this exact profile; database guards also block their
global executor. Preserve compatible code or take state offline for separately
reviewed recovery. Never drop fences/ATTENTION, reset epochs, erase uncertainty,
restore enabled policy or remove the old-writer guard to force a downgrade.
There is no in-place downgrade or uncertainty override tool in this increment.

```bash
python3 -m pytest -q tests/test_device_leases.py tests/test_bulk_discovery.py tests/test_bulk_dispatch.py
```

Disposable tests cover two concurrent shared-queue device owners, quota/same-device
competition, reused-nonce epoch fences, wrong-device/late ADD/REMOVE/deferral,
original-source preservation, explicit/schema/audit rollback, expiry/unknown wait
settlement, read-only attention/retention/restart, missing evidence, current
protection/cancellation, independent global cooldown and strict configuration.
The lease suite uses no runtime worker, real FTD, SSH credential or lab inventory. These are
coordination tests, not simultaneous-FTD or production acceptance.
