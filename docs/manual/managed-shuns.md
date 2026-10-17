# Managed Shuns — Planned Desired-State Restoration

## Status and decision

**Approved product direction on 2026-10-17; not implemented or enabled.**
The operator requested re-adding manually added shuns when they disappear,
for example after FTD reboot. This replaces the former one-time-only target
requirement. The deployed [import workflow](import-review.md) is still one-time
and default-off; nothing in this document changes current runtime behavior,
delegates a live test mutation or reuses the consumed one-fixture approval.

Interpret "manually added" as an explicit managed addition/import through this
service. `show shun` does not supply reliable manual-versus-automatic origin.
Do not adopt every observed entry or infer desired policy from old audit rows.
Registering an existing/SSH-created shun would need its own explicit adoption
review; it is not implied by observing presence or a NOOP.

## User-visible behavior

| Situation | Intended behavior |
| --- | --- |
| Managed target remains present | Observe only; no repeated ADD. |
| Managed target absent in a new complete successful snapshot | Queue a bounded, verified restoration. No need to prove a reboot. |
| Device is unreachable, output partial or parser fails | Preserve prior state; do not infer absence or add anything. |
| Operator removes through the service | Stop maintaining that reviewed target and queue removal if needed; it must not return automatically. |
| Operator stops maintenance only | Keep any observed device shun; no further automatic restoration. |
| Operator removes directly through SSH | Restore on later confirmed absence while maintenance remains enabled. Stop maintenance first if absence is intended. |
| Enabled Protected IP matches | Block restoration; existing automatic-removal policy has priority. |
| Protection later disabled/deleted | An otherwise enabled managed intent may resume; show this warning before editing protection. |
| ADD result/worker outcome unknown | Needs attention; do not send another ADD under a new ID. |
| Later explicit managed import after retirement | New reviewed intent generation; an old-key retry never reactivates it. |

Desired and observed state are separate. A desired-present record without a
current shun must remain visible in a **Managed shuns** view, not disappear
into History. Show device hostname/IP, maintenance enabled/stopped, current
presence, blocked/pending/attention reason, source batch/authorizing actor and
last verified restoration with timezone. **Managed** is a policy label, not a
claim that the service created the current occurrence. Existing current-state
views must still distinguish actual active entries from desired-but-missing ones.

## Durable policy and authority

Use one effective `(device_id, IPv4)` intent, not hidden independently enforced
subscriptions per batch/user. Multiple users retain separate audit attribution
without causing competing restorers. A permitted explicit removal retires the
effective target for everyone in that reviewed scope. Do not automatically
extend an intent to a new device or reuse an ID after device replacement.

Future import review must clearly state **Maintain after disappearance until
stopped**, include that mode in immutable canonicalization/digest and require
current Operator/Administrator, CSRF and exact scope confirmation. Existing
one-time API clients/review tokens keep their current semantics. Changing mode
requires a new reviewed operation; it cannot reinterpret an accepted request.

Standing policy intentionally outlives login and the 15-minute manual request
window, as Protected IP policy already does. Store its authorizing actor/time,
scope, durable ID/generation, optimistic revision, enabled/retired state and
explicit revocation audit. Do not extend old request expiries, regenerate
captured Operator roles or persist browser credentials. Background restoration
uses a distinct `system:managed-shun-policy` actor, linked to current intent
revision and original authorization, rather than pretending the user is online.
Policy revocation and current Protected IP/device state are checked at claim.

Existing imported history/verified origins are **not** a migration source for
enabled intents. This includes the already cleaned-up laboratory fixture.
No-op on an existing entry must not establish creation provenance. A future
explicit adoption can authorize maintenance without claiming past creation.

## Reconciliation and queue contract

1. Obtain a complete successful snapshot through the ordinary cycle. It must
   be newer than the relevant verified operation; cached/pre-write observations
   cannot schedule a restoration after a newer ADD succeeded.
2. Read enabled intents, protection, device capability and outstanding/uncertain
   work consistently. Missing one occurrence is not absence if another matching
   interface is present on that device.
3. Admit at most one restoration intention per device/IP/intent generation and
   absence epoch. Repeated polls/tabs/restarts must not multiply work. Link it
   to the standing policy, not an expired manual request.
4. Use the same leased FIFO, 1000 unfinished-job bound, cycle cutoff, at least
   60-second persisted cooldown, combined 16-operation/64-command/120-second
   limits, mandatory verification and priority-read/final-snapshot reserves.
   No broker, second writer, standalone ADD or new SSH path is required.
5. Recheck intent generation/enabled state, protection, scope, attention latch
   and gates before every claim. Deferrals do not renew user authority; system
   policy authorization is a separate explicit domain path, not forged roles.
6. Only verified creation records a new occurrence and restoration success.
   NOOP records observed presence without fabricated restoration/ownership.
   Keep authorizing policy reference separate from per-occurrence provenance.

Queue capacity is not desired-policy capacity or load acceptance. Large desired
sets need bounded discovery/pagination and visible remaining backlog, not
inserting thousands of jobs in one transaction or automatic 15-minute renewal
of legacy imports. Exact policy/anti-churn bounds are a review prerequisite;
the 7,307-address list remains unapproved. Repeated verified restoration followed
by immediate disappearance needs bounded backoff and a visible stop/attention
threshold, not an endless console stream. Idle discovery uses normal baseline
polling; eligibility alone must not create extra sessions with gates off.

## Removal, protection and race handling

Atomic intent retirement must precede the next claim. Cancel unstarted system
restoration links without misrepresenting an already RUNNING command as
cancelled. A running ADD may finish despite revocation; ordered cleanup must
then be retained/reported under a separately valid removal authorization and
the same serialized executor. Do not simply bypass the existing ADD/REMOVE
conflict check or drop cleanup on conflict. Failure/expiry/cancellation of
removal never turns maintenance back on. An already absent target must still
allow **Stop maintaining / remove** without requiring an active observation.

All-devices removal must review the exact union of currently observed and
maintained target devices, not silently miss a rebooted/missing managed entry.
A device-specific action retires only that device. Queue cancellation of system
work must either retire the associated policy through a clearly labelled action
or explicitly warn that enabled policy will rediscover it; avoid a misleading
Cancel control that immediately recreates work.

Protected IPs always win. Admission/claim suppress managed ADD; enabling
protection cancels unstarted restoration within the same policy transaction.
Do not lose a pending removal while protection/policy changes concurrently.
Display retained managed intent as blocked by protection. If protection is later
disabled/deleted, explicitly warn that maintenance can resume. RUNNING writes
finish/settle before another command; no parallel compensating writer.

Unknown ADD remains UNVERIFIED/attention even if the next snapshot is empty.
Distinguish a later disappearance after known verified success from uncertainty
about the same attempt. A new UUID does not make an unsafe automatic retry safe.
Explicit reviewed resolution/rearm is required before another uncertain attempt.

## Retention, backup and rollout

An active desired intent is live policy even when no active observation exists.
Ordinary 366-day history retention must not erase it or its minimum authorization
metadata. Retired targets/tombstones and original-key records need a defined
lifecycle preventing stale work/history from reactivating them. Historical
events remain append-only within configured retention; do not rewrite old import
outcomes to pretend they authorized future maintenance.

Implementation needs an additive, empty-by-default registry plus explicit job/
policy generation linkage, revision checks, atomic retirement/protection hooks
and independent default-off reconciliation control. All existing ADD gates and
device profiles remain mandatory. No setting is introduced into `.env` yet.

Before schema rollout take a SQLite-safe checked backup and retain paired
images. Never restore an older enabled desired policy and start restoration
automatically: suspend both pending jobs **and policy enforcement**, obtain fresh
observations and require review. Downgrade must disable the new controller,
settle/suspend in-flight work and retain its additive policy tables. Ordinary
backup, upgrade, restart and audit retention are not new device-write authority.

## Implementation sequence and acceptance

1. Implement the registry/revisions/explicit mode and durable authorization with
   synthetic tests; do not hook it to device execution. Specify capacity,
   anti-churn defaults and restore suspension before applying a live migration.
2. Add managed-target UI and frozen confirmation, including missing targets,
   retirement, protection warnings and observed/provenance distinctions.
3. Integrate ordered removal handoff, revocation/cancellation/protection races,
   system queue admission and uncertain-outcome latch under independent gates.
4. Cover complete-versus-partial snapshots, reboot-like mass absence, unknown
   results, old-key replay after retirement, multiple users/instances, cutoff/
   backpressure, retention, backup restore and rollback using synthetic state.
5. Separately authorize one non-production managed fixture: verified creation,
   deliberate out-of-band absence, queued verified restoration, then explicit
   service removal and no restoration. No device reboot or new live write is
   authorized by this plan; a real reboot needs its own operational approval.

Until those stages land, current imports remain one-time and there is no
automatic restoration. This manual is a design/implementation plan, not a
procedure for enabling a deployed controller.
