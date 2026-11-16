# Current Import Addresses

Open an import through its readable **Import: …** link in Managed shuns or an IP's
details. The import receipt also offers **View current import addresses**.
The page shows the original author/time and separates addresses this import still
manages from other original entries. An IP may appear on several devices; counts
are device/IP pairs, not distinct addresses.

## Reading the list

- **Managed:** current auto-restoration still belongs to this import. The summary
  distinguishes blocks observed on a device from maintained addresses not observed
  at the last successful check. Requested addition is not proof of service creation.
- **Other:** already managed by another import, skipped because of protection,
  replaced by a later rule, or no longer maintained. A repeated import does not
  acquire ownership of an address already managed elsewhere.
- **All:** both categories, preserving the original membership for reference.

Each list has 100 rows per page and matching navigation above and below it. The
complete retained import is checked for the counts; only the displayed addresses
are rendered or passed to the read-only IP-context cache. Missing/corrupt original
policy evidence makes the view unavailable instead of presenting an empty scope.
Pending operations, unresolved results, protection and disabled devices remain
visible. These indicators do not grant permission to execute anything.

The list is a local snapshot with an explicit time. Status/Queue continue updating,
but do not replace its rows or request another device read. Use **Reload current
scope** for a fresh view. Pagination carries the managed-policy revision; if it
changes, reload rather than silently mixing two scopes. On a large import the
complete integrity/count check can take several seconds.

## Available actions

An owned row offers the existing **Unblock…** action for that IP/device. It opens
the normal separate review, which checks current policy again, stops matching
restoration and queues removal only after confirmation and existing execution
guards. Opening the import page submits no work. Other rows offer IP details.
Readable links on historical policy rows identify the original import, not an
assurance that it still owns the target.

With the optional cleanup profile enabled, **Unblock imported IPs…** opens a
whole-import review. Confirmation stops only currently owned restoration and
creates one rolling, cancellable task. See [Unblock imported IPs](import-unblocking.md)
for scope, progress and cancellation. Historical membership never grants cleanup
authority.

## Internal read API

The networkless state API exposes these GET routes through its existing Unix socket:

| Route | Result |
| --- | --- |
| `/api/v2/managed-imports/<UUID>/ownership?page=1&scope=owned` | Complete counts, ownership digest, managed revision, snapshot time and at most 100 targets. `scope` also accepts `excluded` or `all`; optional `revision` rejects stale pagination with HTTP 409. |
| `/api/v2/managed-import-labels?keys=<UUID>` | Labels/author/time for at most 100 presented import references; repeated `keys` are supported. |

The authenticated Web route is `/managed-imports/v2/imports/<UUID>`. Reads use the
existing continuous-managed profile and query-only SQLite snapshot. Current ownership
requires enabled maintenance and the exact original authorization request, intent
and generation. Original `ALREADY_MANAGED` and protected exclusions never become
ownership through this projection. The digest binds current authority, not a claim
that an observation was created by the service. Responses explicitly report
`read_only: true`, `can_execute: false` and `device_work_admitted: false`.

No schema/profile/gate, credential, agent command, provider request or recovery
decision is added. Normal existing per-IP write routes retain their own controls.
