# Shuns, Unmanaged and Managed Maintenance

## Choosing a view

| View | What it shows |
| --- | --- |
| Shuns | All active device/IP/interface observations from the latest successful reads. |
| Unmanaged | Active observations without enabled service maintenance for that exact device/IP. |
| Managed shuns | Saved maintenance policy, including absent targets and retained auto-restore-off history. |

**Managed** means the service has enabled maintenance for this pair. It does not
prove the service originally created the observed block or that a pending ADD
has succeeded. Pausing execution does not turn policy into unmanaged state;
inspect Status/Queue for execution and uncertainty.

**Unmanaged** means the service will not restore that pair merely because the
observation disappears. It does not identify Cisco automatic detection versus an
administrator's SSH command. An IP can be managed on one device and unmanaged on
another. Every interface on the same pair shares its maintenance classification.

Turning off auto-restore can leave the existing device block in place. If still
observed, it appears in Unmanaged even when an old import-origin record exists.
Only enabled Protected-IP policy provides automatic unblocking; an off/retired
managed record is not a whitelist entry. Importing/adopting an unmanaged IP into
maintenance still requires the normal selected-device import review and consent.

**Protection is the opposite of keeping an IP blocked.** Turning it on queues
unblocks and turns off auto-restore for that IP on every device. Turning it off
does not add a block or turn auto-restore back on. If you want the service to keep
the IP blocked again, disable protection and create a new import. See
[Protected IPs](protected-ips.md#what-the-switches-mean) for an example.

## Browsing and search

Both observed lists display at most **100 observations per page**. Counts include
interfaces, not unique IPs. Protection matches stay first, then newest detections.
Pagination and live updates retain the selected view/page; a disappearing last
page clamps to the current last page. The Unmanaged filter is applied in SQL
before pagination, not to the first 100 rows of the full list.

IP search remains universal, including managed/current/historical/protected
matches; it is not restricted to the table's selected page or Unmanaged filter.
Its description explicitly distinguishes this broader search from the table.
Normal page-view refresh hints retain existing coalescing/minimum spacing;
ownership classification itself reads local state and never sends Cisco commands.

## Removing an observed block

Each row offers **Manage IP**, opening the dedicated address workspace. Its
visible device cards offer **Unblock…** and, for maintained pairs, **Stop restoring…**.
The v2 workspace includes enabled managed targets even when absent from current
shuns. Unblock prepares the existing exact device/IP frozen review. It does not
enqueue a removal, retire maintenance or repeat an ADD. Final explicit consent,
current scope/policy/protection/role checks and independent admission gates remain.
Conflicting in-progress work can refuse a ready-only review; use the existing
**Unblock after current work…** review when applicable. **Unblock everywhere…**
reviews the complete fleet scope separately. No device mutation starts by
opening the IP page or a review. See [Operator Workspace](operator-workspace.md).

Legacy unmanaged removal retains its queued action. A legacy maintained pair
uses its separate combined-removal review instead. Unknown/unavailable
classification never selects a presumed unmanaged action. Read-only roles get no
mutation form. Changes after rendering are rechecked by the existing server-side
contracts; a displayed badge never grants permission.

## Availability and deployment

Classification validates the existing supported managed profile. Missing policy
is different from partial/corrupt policy: the latter returns unavailable, not an
empty managed set. Count, selected observations, import provenance and maintenance
classification share one read transaction. Only displayed pairs are hydrated.
There is no schema initialization, new authority or recovery action on GET.

Deploy matching API/Web for `GET /api/v1/shuns-page?ownership=unmanaged`. The BFF
refuses an older/unfiltered reply instead of labelling it Unmanaged. Unclassified
legacy full-list responses do not receive invented ownership labels. No agent,
protocol, database migration, credential or network changes are needed. Preserve
the original data/unknowns/receipts and drain API before replacement as usual.

Rolling 24-hour multi-device unmanaged correlation and its direct adoption flow
remain planned; this page does not implement or claim those features.
