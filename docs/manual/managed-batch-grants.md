# Standing Managed Policy — Address Lists

## What this does

**Managed shuns → Maintain an address list** prepares explicit recurring policy
for every address on every selected device. This is **not** a one-time import.
If independently authorized execution is later enabled, maintained addresses may
be restored after confirmed disappearance until their maintenance is stopped.
Protected IPs take priority. External SSH deletion does not revoke that policy.

This increment delivers preparation, confirmation and atomic policy admission;
it does not enable the lab's admission, ADD, restoration or cleanup gates, migrate
optional schemas, resume policy or authorize a live bulk test. Saving policy does
not queue an immediate command or query Cisco. Controller execution remains a
separate [gated workflow](managed-restoration.md).

## Prepare and inspect

1. Paste exact IPv4 tokens or one address embedded in each line of text. `shun`
   prefixes and `#` comments are accepted by the shared
   [import parser](import-preview.md). Blank/comment lines are ignored and exact
   duplicate addresses counted once. Any invalid, ambiguous or unsupported row
   rejects the entire input; correct the reported lines and review again.
2. Explicitly select 1–64 configured enabled devices. Every unique address is
   paired with every selected device. No implicit fleet, CIDR/range expansion,
   substring extraction, truncation or automatic splitting is performed.
3. Supply an optional plain-text label/reason (100/500 characters; not secrets).
   Input has a 1 MiB UTF-8 limit, 20,000 lines and 10,000 parsed rows, but the
   resulting policy scope is limited to **1000 device/IP pairs**. Existing
   registry capacity also includes stopped records. For example, 600 addresses
   on two devices exceed this limit; no partial batch is created.
4. Review the exact frozen hostname/device/IP pairs, old intent/generation when
   present, managed/protection revisions, normalized metadata, expiry and
   original request UUID. Pages contain 100 pairs. Navigation uses POST with an
   opaque token, preserves typed consent and never reparses or reduces scope.
5. Protected, currently observed, already maintained or conflicting targets
   cannot be silently skipped or adopted. One bad target rejects the whole
   batch. Retained failed/uncertain work and abandoned pairs remain blocked.

Preparation uses cached local observations only, not a fresh Cisco query or
proof of absence. The API rechecks the complete scope when saving. A review made
with uninitialized policy remains unconfirmable even if policy is migrated later.

## Save, retry and stop

Confirmation requires a current Operator/Administrator, valid CSRF/session, the
exact device/IP **pair count**, and explicit recurring-maintenance consent.
The Web's and API's existing `FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED` gate
must permit admission. Existing optional registry/attempt schemas and eligible
per-device addition profiles are required; confirmation never creates them.

Private `POST /api/v1/managed-shuns/maintain-batch` fixes MAINTAIN and standing
semantics. Strict fields carry the frozen exact pairs, revisions, digest,
metadata, consent and trusted actor under the original canonical UUID
`Idempotency-Key`; arbitrary actions/CLI/interfaces are rejected. One SQLite
transaction commits the whole registry/request/audit change, or none of it.
The coordinator is not a loop over single-target admissions. A failure at the
last target or audit row rolls everything back; it creates no queue jobs or
one-time import provenance.

A saved receipt is **historical policy authorization, not verified creation**.
Inspect current Managed shuns, Queue and History separately. Unknown/lost or
malformed responses preserve the same token, scope, count, checkbox and UUID.
Inspect state, then explicitly retry the same review/key; do not automatically
resubmit or generate a new key. Original-key replay returns the old receipt
without re-enabling retired/newer policy or clearing attention.

Use **Stop maintaining — policy only** for revocation, and the separate reviewed
cleanup workflow when removal is also wanted. See [Managed Controls](managed-controls.md)
and [Combined Managed Cleanup](managed-cleanup.md). Existing one-time imports
retain their original meaning; this workflow does not convert them or history
into standing authority.

## Draft lifetime and privacy

The separate batch cache holds five immutable reviews per subject, 256 globally,
for at most ten minutes/the shorter sensitive-action age. It binds subject and
CSRF-cookie hash and rejects overflow rather than evicting a potentially saved
review. Expiry, cookie change or Web restart requires inspecting prior outcomes
before making a new review. Tokens are not in URLs. Raw pasted text is not
retained as policy authority or audit content. Label/reason are retained metadata.
Status polling never replaces a paste draft/frozen confirmation, submits it or
requests a Cisco refresh.

## Validation and rollout

Synthetic API/BFF/SQLite tests cover maximum scope, strict input, whole-scope
rollback, concurrent keys, original-key replay after retirement, lost responses,
sessions, CSRF/roles, default-off gates, no implicit initialization, and frozen
100-row pagination. Real Chromium fixtures exercise count/checkbox validation,
preserved drafts/consent and responsive layout without device hints or writes.
This is not live bulk/load/restoration or production acceptance.

No new schema, dependency, wire protocol, service or port. Preserve matching
API/Web rollback images and a checked SQLite-safe private backup. Stop the sole
API executor before replacement: startup may execute already admitted work.
Keep actual env/inventory/secrets, optional schemas, gates and profiles unchanged.
Check healthy normal reads, anonymous rejection and authenticated HTTPS redirect;
never submit a live grant or initialize policy just to smoke-test this page.
Older writers may ignore retained managed/closure authority. Follow
[Offline Recovery](recovery.md) before downgrade or restore.
