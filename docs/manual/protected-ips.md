# Protected IPs

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
   Disabling protection does not add a shun back to the device.

Edits carry the global saved policy revision. Another user's change
causes `409 Conflict`, not last-writer-wins overwrite. Dynamic updates preserve
dirty values **and their original revision**, independently for each address.
Use **reload saved values** to discard drafts, review the latest policy and
resubmit. An interrupted save is not automatically retried: check the current
list first. Successful saves refresh the list and other tabs observe the
durable policy revision without triggering a Cisco query.

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
An API predating this increment ignores SQLite policy and reads its old
environment list instead. It is **not** a safe policy-aware rollback: first
stop API/Web, suspend queued work, disable its legacy policy (remove the
variable), and keep device writes disabled until the desired policy/queue
behavior has been reviewed. Never run old and new executors together.
