# Managed Import Web Workflow

The separate [v2 preparation workspace](bulk-preparation-web.md) is selected on the
compatible continuous profile. It supports 100000-pair draft inspection but no
standing confirmation/execution, and never falls back to the legacy flow below.

## Current boundary

Operators/Administrators use **Imports** in the navigation (`/managed-imports`).
The legacy preview/one-time workflow stays separately reachable at `/imports`;
viewers still see that read-only preview. Managed imports are the recommended
workflow for durable service-managed blocks, adoption and restoration consent.

This increment connects the existing private preparation/confirmation/cancellation
backends. It does **not** expand capacity, enable dispatch/restoration/ADD, migrate
optional schemas or create lab fixtures. Current confirmation still accepts at
most **1000 non-protected device/IP pairs**, including already-managed pairs;
stopped keys also consume existing registry capacity. Larger preparations remain
inspectable, but cannot be confirmed, split or silently truncated by this UI.

## 1. Prepare and inspect

Paste up to 10,000 IPv4 input rows and explicitly select up to ten configured
devices. Optional label/reason become retained metadata; do not put secrets there.
Supported parsing matches the [preparation backend](managed-import-preparations.md),
including surrounding text/comments, duplicate/invalid diagnostics and protected
exclusions. Raw pasted text is not retained in the journal.

**Prepare managed import** saves non-authoritative local state only. It does not
authorize recurring maintenance, submit jobs or query FTD. If its reply is lost,
open **Saved preparations** before pasting again. A duplicate draft is not policy,
but quota is bounded and drafts must not be treated as confirmed work.

Inspect exact classifications, selected device names/IDs, source diagnostics and
100-row pages. Actively protected pairs are visibly marked/excluded. An observed
unmanaged pair is proposed for adoption, not silently omitted or counted as a
service-created shun. Expired/cancelled preparations remain historical reports;
confirmed preparations identify their original receipt. Discarding an unconfirmed
preparation cannot cancel confirmed maintenance.

If storage is uninitialized, the page explicitly says so and disables preparation.
It never initializes tables or disguises unavailable state as an empty healthy
queue. There is no hidden migration/enablement button.

## 2. Confirm recurring policy

**Review recurring maintenance** creates a bounded browser review bound to the
current subject and CSRF cookie. It freezes the preparation ID/digest, accepted
pair count, consent semantics and original operation key, not another target list.
Review lifetime is at most the configured sensitive-action age and ten minutes;
the backend preparation's independent expiry still applies.

Inspect exclusions, type the exact accepted **pair count** and explicitly check
recurring-maintenance consent. Pagination/reloading the frozen review preserves
its token, typed count and checkbox; it does not reclassify, grant or hint work.
No background view replacement or automatic mutation retry occurs on these pages.
Times use the browser's local format with a timezone; UTC remains the fallback.

Both Web configuration and current API status must enable
`FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED`. The API still independently validates
the exact original scope, current roles, lifetime, revisions, profiles, holds and
already existing schemas. Admission remains off in the lab. Cancellation does
not require that new-admission capability.

Confirmation atomically saves canonical standing policy and an immutable report,
not verified device creation. A successful screen says **Standing policy recorded**,
not “IPs blocked.” Actual execution/restoration remains independently gated;
inspect current Managed shuns, queue and history separately.

## 3. Lost replies, restart and receipts

The operation key is UUIDv5 using the immutable preparation UUID as namespace and
`ftd-shun-manager:prepared-policy:v1` as name. This reproducible reference survives
Web restart, but supplies no authorization. All backend owner/digest/consent/
revision checks remain mandatory. A preparation cannot acquire a second root.

On an unknown/malformed reply, the page retains the original review/key and typed
fields. Inspect the saved receipt, then explicitly retry the same review; the BFF
does not generate another key or automatically repeat the mutation. If follow-up
reads fail, the known receipt or unknown-outcome warning remains and **Reload
frozen review** allows another read while the token is valid.

Web restart/expiry loses ephemeral tokens, not durable drafts/receipts. Reopen the
owner preparation or confirmed receipt. An unconfirmed live preparation derives
the same key in a new authenticated session; an already confirmed preparation
opens its original receipt instead. Expired browser tokens cannot submit. A saved
receipt survives preparation pruning and later retirement/newer policy, without
re-enabling anything. Receipt pages are historical, not live execution progress.

## 4. Stop only uncompleted work

From a confirmed receipt, **Review stopping uncompleted work** shows the original
exact scope and expected retained/stopped/waiting counts. Type the whole accepted
pair count within the five-minute cancellation/sensitive-action review window.
No recurring-consent switch or arbitrary action/target field is accepted here.

**This does not unblock already added addresses.** Added/applied/adopted targets
remain managed; only uncompleted initial application stops. A RUNNING ADD is not
interrupted. Its verified/no-op, failed, deferred or unknown result settles through
the existing queue transaction with protection/newer-generation priority. Original
uncertainty stays visible and is not “fixed” by cancellation.

**Cancellation decision recorded** is an immutable initial receipt. **Current
cancellation status** separately displays current settled/waiting/attention counts
and 100-row member pages. Use **Check latest status** to read later settlement;
it never submits another cancellation or sends commands. Reopening cancellation
review after a decision exists opens status rather than creating new authority.
Use the separate removal workflow when actual unblocking is intended.

## Security and deployment

All public POSTs require existing session CSRF and current Operator/Administrator;
no supplied actor/roles/targets/gates are forwarded. Private ownership checks still
apply. Browser review caches are separate by action and bound to subject/cookie,
five reviews per subject/256 globally, at most ten minutes for confirmation/five
minutes for cancellation. Reports use POST bodies to keep owner references out
of URLs; responses are `no-store` and metadata is escaped.

Read [confirmation](managed-import-confirmation.md#validation-migration-and-rollback)
and [cancellation](import-cancellation.md#migration-backup-and-rollback) migration
procedures before separately approved activation. This UI adds no new schema.
Normal startup/requests never create optional schemas, modify profiles or enable
gates. Browser cancellation currently starts from the owner's retained receipt;
the private API's separate Administrator cross-owner controls remain available
to trusted integrations, not a new global browser owner list.

For a lab UI rollout, retain matching previous API/Web images and a checked
SQLite-safe private backup, then update API/Web only. Existing admitted ordinary
work may execute after API restart. Preserve agent/Caddy/Authelia, credentials,
inventory and all experimental gates. Check optional schema absence/state and
queue/policy counts before/after; do not submit test policy/imports as a smoke
shortcut. If pending cancellation exists, never roll back to an older unaware
writer. Web rollback invalidates ephemeral forms; durable reports remain.

Run `python3 -m pytest -q tests/test_managed_import_web.py` and
`node --test tests/browser/freshness.cjs` on synthetic local state. These checks
are not live hardware, bulk throughput or production acceptance.
