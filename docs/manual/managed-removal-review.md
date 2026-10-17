# Managed Removal Review — Preparatory UI Only

## Current scope

The Managed shuns page exposes retained policy and optional cleanup state.
Separate [revocation controls](managed-controls.md) now support policy-only
retirement and waiting cancellation; they cannot execute this combined review.
Operator/Administrator users can prepare a **single-target** or **frozen fleet**
stop-maintenance-and-remove review. **Execution is unavailable:** preparation is not retirement,
queue admission or a device operation. There is no environment switch to enable
this form. ADD and automatic restoration remain disabled under their own gates.

In the current lab the managed/handoff tables are absent, so no retained-policy
single-target controls appear. Fleet review can still show existing observed
shuns without adopting them; an empty scope is refused. Opening the page/API
never creates optional tables, adopts old imports or queries FTD. Do not seed
live policy to demonstrate these controls.

## Review workflow

On an explicitly initialized development fixture, choose one enabled device/IP
from retained managed policy and optionally supply a bounded plain-text reason.
**Prepare stop/remove review** reads current local policy and freezes:

- exact device hostname/ID and IPv4, intent/generation and managed revision;
- observed-versus-missing state, maintenance and enabled protection;
- reason, proposed cleanup lifetime, reserved request UUID and review expiry.

The page explains the intended future effect: stop maintenance for this target
only, then use ordinary verified queue removal. A running ADD must settle first;
expired/cancelled/failed cleanup must not restart maintenance. Missing observation
does not remove the target from the review, and presence does not prove service
creation. This is not an all-device review or fresh Cisco query.

The confirm button is disabled. Direct `POST /managed-shuns/removal-confirm`
still checks current role, CSRF, review binding/expiry and exact typed IP, then
returns **503 Execution unavailable without contacting admission**. Changing
HTML or upstream status flags cannot enable it. No private admission POST exists.
The review grants no durable authority and is not an accepted queue request.

## Frozen all-device scope

Open **Managed shuns → Preview all-device removal scope — no execution** and
enter one exact IPv4 plus an optional reason. This preparatory form works without
an initialized registry if current observed shuns exist. It does not submit the
ordinary removal form or request a Cisco refresh.

Private `GET /api/v1/managed-removal-scope/{ip}` reads, in one SQLite transaction,
the union of locally active observations and enabled maintained targets for that
IP. Several interfaces on one FTD produce one target. Maintained-but-missing and
disabled devices remain included; stopped-and-missing entries and unrelated
inventory are excluded. An observed unmanaged address is labelled **cleanup
only**, never adopted. Unknown/partial policy returns 503, not an observed-only
fallback; empty/over-1000-target scopes return 409 without truncation.

The review lists every hostname/ID, device enablement, local presence, desired
policy and retained intent/generation. A disabled device is visibly a blocker
for future whole-scope cleanup, not silently omitted; policy-only retirement is
still available separately. Enabled protection is shown independently. No row
or digest proves service creation or live device freshness.

A versioned scope digest binds the exact sorted metadata, managed initialization/
revision and Protected-IP revision/state. Observation timestamps/additional
interfaces do not change device-level membership. The separate fleet action
digest also binds cleanup lifetime and reason; it cannot be reused as a
single-target or policy-only action. Fleet/single reviews share the existing
five-per-subject/256-global combined-review cache and immutable session/TTL rules.
Confirmation uses the same exact typed IP and always returns 503, with no
admission call even if upstream advertises enablement. Status polling never
changes a frozen scope; prepare a new review only after inspecting new state.

`ManagedRemovalScopes.require_current(db, reviewed)` is an internal comparison
prerequisite for a future composite writer, not that writer or an authorization
interface. It re-reads and compares within the caller's transaction and rejects
scope changes without commits, audit or queue work. Atomic fleet retirement/
handoffs are **not implemented**: never loop over single-target admissions to
simulate them. Existing ordinary device/fleet removal behavior is unchanged.

## Session and refresh behavior

Reviews are process-local immutable objects, bound to authenticated subject and
CSRF-cookie hash. TTL is at most ten minutes/the shorter sensitive-action age;
there are at most five open managed reviews per subject and 256 globally.
Overflow rejects without evicting another review. Cookie change, expiry or Web
restart invalidates the token; authentication/current role is checked again on
each POST. The server chooses scope/revision/key/digest; forged actor, targets,
revision, key or digest fields are rejected. Input/body limits and HTML escaping
remain mandatory. The pure canonical intent module performs no storage/dispatch.

Status polling continues on the initial review page, but its frozen target,
token, typed IP and focus are not fetched/replaced after a revision change.
There is no automatic submission, reclassification, retry or authority renewal.
Reload/back/restart may lose the ephemeral review; inspect current state before
preparing another. A disabled confirmation response also remains non-executable.

## Read-only cleanup visibility

Private `GET /api/v1/managed-removal-handoffs` returns an explicit uninitialized
empty envelope when the optional table is absent, not a migration. Invalid schema
fails with 503. The authenticated Managed shuns page shows an optional-resource
error without hiding valid desired policy or inventing an empty queue.

**Managed removal handoffs** shows at most 20 prioritized records and full phase
counts. Active/attention entries stay visible; completed records are collapsed.
Waiting is amber, attention/expiry red, admitted active work blue, and only a
linked VERIFIED removal is green. Admission and queue outcome are separate:
UNVERIFIED is unknown, and RECONCILED_ABSENT is later observed absence, not
verified actor-attributed removal. Missing pruned queue history is labelled as
unavailable, never pending or successful. Times include browser-local timezone.
Actor/diagnostic text is escaped; inventory routes, pins, raw payloads and
credentials are not exposed. Existing queue revisions drive local updates
without refresh hints or device queries.

The view reports the cleanup-worker flag (default off), separately from
unconditionally unavailable combined-removal admission. GET display never
advances/cancels handoffs. The separate owner/Administrator waiting-cancel POST
is documented in [Managed Controls](managed-controls.md).
See [the coordinator contract](managed-removal-handoffs.md).

## Validation and rollout

Synthetic ASGI/SQLite tests cover identity/CSRF, strict fields/scope/count limits,
cookie/expiry/restart/capacity binding, immutable review data, unconditional
execution refusal, optional schema/error handling, escaped admission/outcomes
and no database/queue/audit changes. Chromium exercises frozen token/input/focus,
revision-driven waiting/attention/verified displays and 375px layout without
execution or extra Cisco hints.

This UI increment needs paired API/Web images, not an agent update or migration.
Retain previous paired images and a checked SQLite-safe backup; stop the sole
API executor cleanly before replacement. Restart may execute already admitted
ordinary queue/policy work. Keep actual inventory/configuration/gates unchanged;
never create a managed fixture/job to test deployment. Verify absent managed/
handoff tables, disabled ADD, unchanged state/queue/policy aggregates, ordinary
healthy reads, anonymous 401 and a TLS-verified Authelia redirect. Revert paired
images without restoring old state if necessary; do not drop authority tables.

Before any execution release, connect the frozen all-device scope to atomic
multi-target retirement/handoff admission, protection/system cancellation and
target uncertainty handling. Visible revocation/cancellation is implemented. The
default-off shared-worker hook and [composite recovery controls](recovery.md)
have synthetic coverage, not live acceptance. The preparatory
POSTs and GET resource do not waive those gates or authorize a live mutation.
