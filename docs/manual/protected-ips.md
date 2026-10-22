# Protected IPs

**Lifecycle update (2026-10-21):** explicit enabled-protection saves now permanently
retire matching managed maintenance. Disabling/deleting protection never restores
that old policy. Existing entries are not swept on startup or GET; legacy/deferred
maintenance is retired on a reviewed save before active protection can be removed.

## Purpose and permissions

Open **Protected IPs** in the navigation. Each enabled, exact IPv4 address is
eligible for automatic shun removal on **every enabled FTD device**. This is an
ongoing protection policy, not a manual blocklist import or a desired blocklist.
Use only independently verified egress addresses. CIDRs, ranges, hostnames and
IPv6 are unsupported; the list is bounded to 1,000 addresses.

All authenticated application roles can read names/comments, enabled state,
the number of devices with a locally observed active shun, and **Last
auto-removed**. That timestamp is the latest retained, agent-verified policy
removal, not an admission/no-op/unknown result. `Never recorded` can also mean
that older evidence expired under history retention. Observations can be stale:
check the persistent warnings and **Status** menu.

**Enabled** badges are green and **Disabled** badges are red, with text labels
so state does not depend on colour alone. If a disabled address is currently
observed in shun, its card is highlighted red with **Protection disabled —
currently shunned**. The active-shun list, search results and IP detail page
also flag disabled protection. This means automatic policy removal is off,
not that a removal has succeeded or that a new manual request was submitted.
An enabled address still in shun retains the amber operational warning.

**Every authenticated user** can add, edit, enable, disable or delete entries,
including Viewer, Operator and users with no mapped application group. A separate
Administrator group is not required. Admit only people trusted to manage this
fleet-wide policy through Authelia. This is specific to Protected IPs: manual
shun removal and cancellation of other users' requests retain their existing
role/ownership checks. The BFF requires CSRF and takes identity/roles only from
Caddy/Authelia; actual directory roles are audited without promoting them. Normal sensitive
session expiration applies. Name (100 characters) and comment (500 characters)
are optional plain text and escaped in HTML; they never become Cisco commands.

## Workflow and concurrent users

1. Open **Add protected IP**, enter an exact address and optional name/comment,
   and explicitly review the fleet-wide enabled checkbox before saving.
2. Open an address's editor to rename/comment or enable/disable it. To delete,
   open **Delete address** and type the address to confirm.
3. Saving changes SQLite only; it does not synchronously open SSH or bypass the
   shared scheduler. A subsequent successful snapshot discovers eligible shuns
   and queues verified automatic removal within existing cycle limits.
4. Enabling protection permanently stops matching managed maintenance, including
   targets missing from observations or on disabled devices. It cancels unsent
   ADD/restoration but never interrupts an already RUNNING command or claims a
   device removal succeeded. Required device verification/removal remains queued.
5. Disabling/deleting atomically cancels unstarted policy intentions. A shared
   manual request survives; already RUNNING operations cannot be interrupted.
   Disabling protection does not itself add a shun back to the device. Retained
   managed maintenance is not resumed. Only new explicit maintained-policy consent
   after protection is disabled can authorize another generation. A later FTD-
   detected shun without new service consent remains unmanaged.

Edits carry the global saved policy revision. Another user's change
causes `409 Conflict`, not last-writer-wins overwrite. Dynamic updates preserve
dirty values **and their original revision**, independently for each address.
Use **reload saved values** to discard drafts, review the latest policy and
resubmit. An interrupted save is not automatically retried: check the current
list first. Successful saves refresh the list and other tabs observe the
durable policy revision without triggering a Cisco query.

### Managed maintenance acknowledgement

Each card reports the number of **enabled managed intents** for that address,
including missing observations and disabled devices, excluding stopped intents.
These are desired-policy counts, not current shuns or proof of restoration.
Saving enabled protection retires matching enabled targets under one SQLite write
lock: preserve identity/generation/original authority, update retirement timestamp
and managed revision once, append real-actor retirement events linked to the policy
event, and cancel eligible unsent ADD. All authenticated users have this fixed
revocation authority; there is no role promotion or new standing grant. Full
managed-request ledgers do not prevent this revocation.

There is no resume checkbox in new forms. The strictly typed private compatibility
field `confirm_maintenance_resume` is accepted but cannot resume anything. Forms
carry the reviewed managed revision, including **Add protected IP**. A nonempty
retirement scope requires that current revision; a stale supplied revision conflicts
even for an empty scope. Dirty forms retain both original policy/managed revisions
and input values, not silently rebased authority. On 409, reload saved values and
review the current scope. Editing/deleting an already-disabled entry does not
retire a newly and explicitly authorized maintained policy.

Absent optional managed state is not initialized. Invalid/partial state is unknown,
not zero: protection can still be enabled, with retirement explicitly deferred.
Its persisted enabled flag is the barrier; disabling/deleting is refused until
state is readable and the same transaction retires remaining matching authority.
GET/restart never performs that retirement. After repair, reload/review and save
enabled protection, or disable/delete it to complete retirement before release.
Unverifiable queue evidence is preserved rather than rewritten as cancellation or
success; claims remain guarded. Existing protected automatic removal is separate.

Running ADD, waiting/admitted cleanup, failed/unknown outcomes and retained
abandonment/isolation receipts are unchanged. Retirement does not resolve device
uncertainty, erase cleanup or admit immediate commands. Actual gates remain off
and no live managed-policy fixture is activated by this update.

### Version-2 bulk compatibility

The current protection coordinator also recognizes the exact suspended
[version-2 bulk storage](bulk-policy-storage.md#protected-ips-permanent-revocation)
profile, with the same reviewed-revision, permanent-retirement, actual-editor and
deferred-barrier rules. A matching enabled target is retired even if no shun is
observed or its device is disabled; a full bulk request ledger does not prevent
revocation. Disable/delete and old import retries never re-enable that policy.
Large identity scans use bounded chunks. Mixed/partial/unsupported optional bulk
state is unknown and cannot be used to release a protection barrier.

This narrow compatibility does not enable the bulk runtime/import/worker, initialize
its schema or change the current legacy lab profile. Legacy managed readers and
maintenance tools still refuse version2. New optional migration and live fixture
activation are not part of a protection save or service upgrade.

## Audit

`PROTECTED_IP_ADDED`, `PROTECTED_IP_UPDATED`, `PROTECTED_IP_DELETED`, and the
one-time `PROTECTED_IP_IMPORTED` events are committed with policy mutations.
SQLite retains before/after values, actor username/display name/roles, request
ID and fleet scope. Matching JSON stdout events include the request ID and
identity; free-form comments are deliberately excluded from collector payloads.
Protection saves also record retired-target counts/deferred retirement. Per-device
`MANAGED_SHUN_RETIRED` events share the protection event's request ID, retain the
original grant reference and real editor roles, and commit atomically. Saving
protection is not an agent-verified removal event.
Audit events follow the configured history retention; current policy entries
and the import marker do not expire. Device execution retains the separate
`SHUN_TRUSTED_AUTO_REMOVE_*` events under `system:trusted-ip-policy`.

## Upgrade from the environment-owned policy

1. Build paired API/Web images without replacing the running containers yet.
2. Stop Web, then gracefully stop API. Allow a bounded running device step to
   finish; check the [queue procedure](operation-queue.md#backup-restore-and-rollback).
3. Take a SQLite-safe backup of the state database (SQLite backup API or an
   offline copy with WAL handled consistently), protect it as operational data,
   and verify `PRAGMA quick_check` on the backup. Never commit it.
4. Start the new API with the existing protected environment unchanged for
   this first launch, then start the matching Web image.
5. Initialization adds `protected_ips` and singleton `protected_policy`, leaving
   state/events/queue data intact. Under one SQLite write transaction, it
   imports unique legacy `FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS` addresses as enabled
   **Migrated address** entries, appends audit events, and sets `legacy_imported`.
   An invalid list or more than 1,000 addresses aborts this import and API
   startup; correct the old input and retry. An empty list still sets the marker.
6. Verify the expected addresses in Protected IPs, names, count and audit.
   Remove the obsolete variable from `.env`. No policy variable belongs in new
   deployments. After the marker exists, even a malformed or changed legacy
   value is ignored; deleted/disabled addresses cannot be resurrected by restart.

New databases start empty when no legacy value exists. Do not reuse an old
environment file with that obsolete variable when intentionally creating a new
database: a new database necessarily has a new first-import marker.

## Backup, restore and rollback

Include policy tables in normal SQLite backups. Restarting an upgraded service
does not re-import, but restoring an old database restores **that backup's
policy, marker and queue**, not the current policy. Before running a restored
database, suspend old queue work using the queue manual. Initialize the schema
with the new `Store.initialize()` (not `create_app`, which also imports/starts
the service), then perform approved offline maintenance to disable policy:

```sql
BEGIN IMMEDIATE;
UPDATE protected_ips SET enabled=0;
UPDATE protected_policy SET legacy_imported=1, revision=revision+1 WHERE id=1;
COMMIT;
```

Record this maintenance in the audit/incident record. Remove the obsolete
environment value, start the matching API/Web, wait for a successful snapshot,
then explicitly review/re-enable addresses through the UI. Never blindly replay
restored policy or queued mutations.

The SQL disable step above is only valid when matching managed authority is
absent or already explicitly retired under the approved recovery plan. If optional
managed state is unknown or matching authority remains, retain enabled protection
as its barrier. Bring up the current gated services and use a freshly reviewed UI
save to finish retirement before disabling/deleting; do not bypass that transaction
with SQL, an older writer or a restored enabled-policy snapshot.

Schema changes are additive; do not drop tables to roll back presentation.
The permanent-retirement increment itself adds no schema or startup sweep. Retain
paired API/Web images and a checked SQLite backup before upgrading. Do not restore
old enabled policy to undo retirement. Older writers can resume legacy retained
policy after protection weakening: never use an older writer to release a deferred
barrier. Review/suspend writes and settle retirement before any such downgrade.
The enabled/disabled colour and warning update requires paired API/Web images
and a browser reload only: no schema migration, policy edit or backup restore.
Rolling back that presentation update leaves the saved policy unchanged.
An API predating SQLite policy support ignores SQLite policy and reads its old
environment list instead. It is **not** a safe policy-aware rollback: first
stop API/Web, suspend queued work, disable its legacy policy (remove the
variable), and keep device writes disabled until the desired policy/queue
behavior has been reviewed. Never run old and new executors together.
