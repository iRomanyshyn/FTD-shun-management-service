# Protected IPs

**Target update (2026-10-20):** the [Working-Version Plan](../working-version-plan.md#4-protected-ips--whitelist)
requires protection to permanently retire matching maintenance. The procedure
below describes existing code, which can still retain maintenance behind
protection and warn before its resumption. The new lifecycle is not implemented
or activated by the documentation update.

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
4. Disabling/deleting atomically cancels unstarted policy intentions. A shared
   manual request survives; already RUNNING operations cannot be interrupted.
   Disabling protection does not itself add a shun back to the device. Retained
   managed maintenance may become eligible when its future controller is enabled;
   review the acknowledgement described below.

Edits carry the global saved policy revision. Another user's change
causes `409 Conflict`, not last-writer-wins overwrite. Dynamic updates preserve
dirty values **and their original revision**, independently for each address.
Use **reload saved values** to discard drafts, review the latest policy and
resubmit. An interrupted save is not automatically retried: check the current
list first. Successful saves refresh the list and other tabs observe the
durable policy revision without triggering a Cisco query.

### Managed maintenance acknowledgement

Each card now reports the number of **enabled managed intents** for that address,
including missing observations and disabled devices, excluding stopped intents.
These are desired-policy counts, not current shuns or proof of restoration.
Enabled protection blocks future managed restoration without deleting intent.
Disabling/deleting protection is not a substitute for **Stop maintaining**.

If an enabled managed intent exists, disabling currently enabled protection or
deleting the entry requires an explicit **I understand** acknowledgement and
the reviewed global managed revision. Deleting an already-disabled entry also
requires this acknowledgement. The private API and SQLite transaction enforce
it; changing the DOM, omitting the fields or calling the API directly cannot
bypass the check. Existing clients remain compatible when no matching enabled
intent exists. Adding a disabled entry, renaming an already-disabled entry or
enabling/keeping protection on does not weaken protection and needs no resume
acknowledgement. All authenticated users retain policy-edit permission, with
their real roles in audit; there is no promotion to Administrator.

Dirty edit/delete forms retain **both** original saved revisions and the user's
checkbox values. Another user's managed change cannot silently rebase an old
acknowledgement onto a newer target set. The server returns 409; use **reload
saved values**, inspect current counts and acknowledge again. Fresh forms start
unchecked. Revocation of all matching intents can remove the need for an ack,
but a supplied stale revision still conflicts rather than silently rebasing.

Absent optional managed tables mean no registered intents and never initialize
them. Partial/malformed/unsupported optional state is **unknown**, not zero:
show a warning/unknown count and refuse disabling/deleting with 503 until
reviewed. Enabling protection and ordinary monitoring remain available. Status
publishes managed unavailability so revision-driven pages can update safely.

The acknowledgement does not enable ADD, resume restoration, adopt old imports,
extend authority or admit work. The controller remains unavailable and all lab
ADD/cleanup-worker gates stay off. A successful weakening audit records managed
revision/count/acknowledgement alongside the ordinary before/after policy.
Policy mutation, cancellation of queued ADD and its audit remain atomic. Already
RUNNING ADD and waiting/admitted cleanup retain their state/authorization;
protection changes must not erase pending cleanup. This is synthetic validation,
not live managed-policy acceptance.

## Audit

`PROTECTED_IP_ADDED`, `PROTECTED_IP_UPDATED`, `PROTECTED_IP_DELETED`, and the
one-time `PROTECTED_IP_IMPORTED` events are committed with policy mutations.
SQLite retains before/after values, actor username/display name/roles, request
ID and fleet scope. Matching JSON stdout events include the request ID and
identity; free-form comments are deliberately excluded from collector payloads.
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

Schema changes are additive; do not drop tables to roll back presentation.
The enabled/disabled colour and warning update requires paired API/Web images
and a browser reload only: no schema migration, policy edit or backup restore.
Rolling back that presentation update leaves the saved policy unchanged.
An API predating SQLite policy support ignores SQLite policy and reads its old
environment list instead. It is **not** a safe policy-aware rollback: first
stop API/Web, suspend queued work, disable its legacy policy (remove the
variable), and keep device writes disabled until the desired policy/queue
behavior has been reviewed. Never run old and new executors together.
