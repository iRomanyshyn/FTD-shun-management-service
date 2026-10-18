# Standing Managed Policy — Single-Target Review

## Boundary

The experimental workflow authorizes one exact device/IPv4 as **maintain present
until explicitly stopped**. It is separate from one-time import and device
creation, restoration, policy resume or combined removal. The lab remains
disabled/uninitialized; do not seed policy or submit a live grant for smoke.

`FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED=false` controls only policy admission.
True requires socket mode, an explicit eligible addition profile and existing
optional registry/attempt schemas. It does not initialize either schema, resume
the registry, enable controller/ADD/import gates, add a queue job or request an
immediate device read. Future complete snapshots may produce system work only
through the independently gated controller. See [Managed Restoration](managed-restoration.md).

## Workflow

1. In **Managed shuns**, open **Maintain one device/IP — persistent policy**.
   Choose one configured enabled device and an exact IPv4. Label/reason are
   optional plain text, limited to 100/500 characters; they are not secret fields.
2. **Review standing maintenance** reads local classification/policy only.
   Protected or observed shuns and already enabled intent cannot be adopted by
   this workflow. A stopped absent target may receive a new generation, not
   reactivation by replay. Retained uncertainty is not resolved by a new grant.
3. Inspect exact hostname/device/IP, standing mode, prior intent/generation,
   managed/protected revisions, normalized metadata, expiry and original UUID.
   Uninitialized policy may be previewed, but that frozen review cannot later
   become confirmable merely because another process initializes policy.
4. When independently authorized admission is enabled and optional migration is
   complete, type the exact IPv4 and explicitly acknowledge recurring additions
   until maintenance is stopped. Current Operator/Administrator and CSRF are
   required both at preparation and confirmation. Protected-IP editing remains
   available to all authenticated service users under its separate rules.
5. **Standing policy recorded** is a historical policy receipt, not queued or
   verified creation. Inspect current Managed holds/Queue/History separately.
   With controller off or registry suspended the saved policy cannot execute.

Only one pair per review is currently supported; no paste/list mode or implicit
fleet expansion. Other page updates preserve a draft device/IP. Preparation
revalidates the configured device, and the API rechecks all state atomically.
No caller chooses a CLI interface or command. SSH-created/old imported entries
are not automatically adopted. A future bulk managed workflow needs its own
explicit frozen scope, capacity and authorization design.

## Atomicity, retry and revocation

Private `POST /api/v1/managed-shuns/maintain` fixes MAINTAIN and standing semantics,
with strict actor/pair/revisions/digest/acknowledgement, bounded metadata and
explicit canonical UUID `Idempotency-Key`. Unknown fields/actions/target lists
are rejected. The trusted BFF supplies the actor and all frozen fields; browser
confirmation accepts only CSRF, opaque review token, typed IPv4 and checkbox.

One write transaction checks schema, explicit capability, global revisions,
protection, enabled device, no recovery pause, no existing observed adoption,
cleanup, pending/running/uncertain pair work, retained failed restoration and
registry capacity. Policy/request/audit commit together; late failure rolls back
all of them. No queue authority or imported provenance is fabricated. Success
logs appear only after commit and do not include label/reason/raw lists.

Known previous request replay checks the current role/gate and exact original
actor/canonical body, returning its original result without applying it again.
It never re-enables a retired/newer generation or clears an uncertainty latch.
Unknown/lost/malformed responses retain the same review, typed IP, consent and
UUID. Inspect Managed/history, then explicitly retry that same review/key; never
automatically submit, change key/scope or reinterpret it as one-time admission.
A valid durable receipt is not negated by later status unavailability.

Reviews are immutable process-local records bound to subject and CSRF-cookie
hash, up to ten minutes/the shorter sensitive-action age, five per subject and
256 globally in a separate grant cache. Overflow rejects rather than evicting a
possibly saved review. Expiry, Web restart or cookie change requires inspection
before preparing a new review. Tokens are not in URLs. Polling preserves frozen
token/input/checkbox/focus and never requests Cisco refresh or resubmits policy.

Use **Stop maintaining — policy only** to revoke without cleanup, including absent/protected or
disabled-device targets. It atomically cancels unstarted system restoration;
already RUNNING commands stay ordered. Separate [combined cleanup](managed-cleanup.md)
has default-off atomic retirement/admission for device/fleet scopes. When that
admission is disabled, stop maintenance then explicitly use ordinary removal if
needed: those are two distinct actions, not a false claim of atomic cleanup. See
[Managed Controls](managed-controls.md). No resume/rearm route was added.

## Validation, deployment and rollback

Synthetic ASGI/SQLite tests cover preparation, explicit consent/role/CSRF,
strict inputs, profiles/gates, revisions/protection/observed state, pending work,
retained failures, audit rollback, concurrency/idempotency, old-key replay after
retirement, immutable session/expiry/cache bounds and unknown-reply retry.
Chromium checks frozen consent, native required validation, mobile spacing and
absence of device hints against localhost fixtures. Packaged smoke uses a
networkless read-only disposable container, never live state or credentials.

No new schema/protocol/dependency/service. Retain paired API/Web images and a
checked SQLite-safe private backup. Stop the sole API executor before replacement;
startup can run already admitted ordinary work. Keep all actual gates, profiles,
env/inventory/secrets unchanged. Check absent optional tables, unchanged queue/
policy/stable state, healthy normal reads, anonymous 401 and verified TLS auth
redirect. Do not submit a live grant as a deployment check. Older images unaware
of managed authority must not execute pending work; follow
[Offline Recovery](recovery.md) before downgrade or restored state.
