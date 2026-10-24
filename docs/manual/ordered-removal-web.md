# Version-2 Ordered Removal in the Web Interface

Status: implemented with independent default-off Web/API capabilities. **Not
migrated, enabled or deployed in the lab.** This workflow does not authorize new
fixtures, optional migrations, runtime selection or device mutations. Read
[Private Ordered API](ordered-removal-api.md),
[Ordered Reservations](bulk-ordered-reservations.md) and
[Ordered Promotion](bulk-ordered-promotion.md) first.

## Inspect and confirm an exact scope

In a compatible explicit v2 continuous composition, Managed shuns includes a
collapsed **Review ordered removal — wait for a current managed ADD** section.
Choose one device/IP on the current policy page, or enter one exact IPv4 to inspect
the complete observed/enabled-managed fleet union. Both preparation forms require
the current Operator/Administrator identity and CSRF cookie. Inspection reads local
state, not Cisco, and never retires policy, reserves work or hints a device refresh.

The page retains every original target, including missing-but-maintained or
disabled devices, with separate readiness/blockers and captured original ADD IDs,
generation, epoch and expiry. Unmanaged members are cleanup-only, never adopted.
Validate the entire bounded preflight/digest, mode, IP/device, literal counters,
flags and canonical predecessor evidence before rendering.

| Inspection | Behavior |
| --- | --- |
| WAITING_ADD | Freeze a separate exact ordered review; confirmation remains disabled unless all independent capabilities qualify. |
| READY | Informational only; no token. A separately prepared ready-only action may be appropriate. |
| BLOCKED | Informational complete-scope blockers; no token or partial ready subset. |

`web.create_app(..., ordered_removal_admission_enabled=False)` supplies an
independent literal developer factory capability, not an environment/browser
setting. True requires socket mode, session cycles, large reads and deployed
trusted identity (development authentication remains forbidden). It cannot enable
the API or owning promoter, and a true API/DOM flag cannot enable a false local
Web capability. Confirmation rechecks compatible current v2 API metadata and both
its ordered admission and promotion capabilities. Ready-only and legacy routes
never silently substitute for this action.

An eligible review freezes scope, exact sorted predecessors, distinct ordered
action/digest, reason, original UUID and delegation TTL in the separate immutable
server-side cache. Cache limits are five reviews per subject, 256 total and at
most ten minutes. It is bound to the actual subject and hashed CSRF cookie; it is
lost on Web restart. Scope/data objects returned to callers are detached copies.
Browser status refresh never replaces this confirmation, its key or typed input.

Type the exact IPv4 and explicitly submit. Native validation helps prevent a
mistyped address; server checks remain authoritative. The form accepts only CSRF,
the opaque review token and typed IP, never posted scope/actor/predecessor JSON.
Recheck identity/role, CSRF/session and expiry **after** metadata I/O, then submit
one fixed private device/fleet route with the original cached key/body and actual
actor. Changed membership, authority, readiness or deadlines conflicts rather
than shrinking/rebasing the request.

## Understand the receipt

Confirmation permanently stops matching managed support and reserves the entire
cleanup scope, or changes neither. REMOVE waits for every captured ADD and its
session to settle. Failed/unknown evidence retains attention; no ADD is replayed.
Different FTD outcomes are not a distributed transaction.

**Waiting reserved — not verified removal** is a checked historical 202 receipt,
not current execution. The BFF verifies exact action/mode/UUID, literal counts/
flags/revision and canonical original requested-at plus unchanged TTL expiry.
Replay changes only its response replay marker; it never renews deadlines,
re-enables support or creates/wakes work. A later optional metadata failure cannot
negate an already checked receipt.

A lost/malformed reply is **unknown**, not rejection or success. The page retains
the same original key, typed IP and review for explicit retry within local expiry.
Never re-key, reduce scope, switch to ready-only or replay ADD. Inspect the original
request permalink. A missing status result does not authorize another identity/
scope/key; a Web restart/expired review needs original-state inspection, not
automatic reconstruction or submission.

## Current status and passive updates

The receipt/review links to
`/managed-shuns/v2/ordered-removals/{original_uuid}`. Bookmark this authenticated
read-only permalink; it survives Web restart because it reads retained API state,
not the ephemeral review cache. It requires a canonical UUID and validates the
complete typed projection before showing outcomes. Unknown/malformed state is
explicitly unavailable; it cannot show an empty successful scope.

The page shows original owner, scope, requested-at and expiry, each captured ADD
outcome, retained attention and every delegated REMOVE job. ADMITTED means queue
delegation, not device success. Only all original jobs explicitly VERIFIED produce
the all-verified label. This remains historical evidence, not a fresh guarantee
that the IP is absent now. Original ADD results remain independent.

GET never hints device work, expires/promotes requests, extends deadlines or
changes policy. The shared maintenance worker owns expiry, so show the original
deadline separately even if the stored phase still says WAITING_ADD. Passive
metadata/data-revision updates fetch local page regions, preserve dirty form
values/focus and open sections, and remove waiting controls when no longer
eligible. Reopen a details section before restoring field focus; closed details
cannot accept focus. **Check local status now** is also available without JavaScript.
All timestamps retain UTC fallback and are localized with a timezone in browsers.

## Cancel waiting only

The owner or Administrator can expand **Cancel waiting authority — leave
maintenance stopped**, type the exact IPv4 and explicitly submit. The separate
CSRF-protected POST accepts only the typed IP and CSRF; private input contains only
the actual actor. No new-admission/promotion capability is needed, including after
Web restart or during a mutation pause. A different ordinary operator is forbidden.
The API rechecks the durable original root and ownership; a race to ADMITTED
returns conflict, not cancellation of delegated jobs.

Revocation does not interrupt a RUNNING ADD, remove a shun, restore maintenance,
clear attention or resolve uncertainty. Terminal replay is side-effect-free. The
checked local cancellation receipt is historical and stays visible even if a
subsequent status read fails; the stale pre-submission snapshot is not presented
as current. If the revocation response itself is lost/malformed, show unknown and
inspect/retry only this same original request. Delegated jobs use ordinary queue
controls, never waiting revocation or hidden rearm.

## Validation and operating impact

```bash
python3 -m pytest -q tests/test_ordered_removal_web.py tests/test_ordered_removal_api.py tests/test_ready_removal_web.py tests/test_continuous_api.py tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_promotion.py
node --test tests/browser/freshness.cjs
```

Python uses disposable SQLite/ASGI/fake sessions for real BFF/API integration,
strict preflight/receipts/status, CSRF/roles/session/cache, stale scope, races,
unknown replies/retry, original TTL, cancellation and actual shared continuous
fake REMOVE execution. Chromium uses production templates/JavaScript with a local
synthetic server to check independent gates, escaping, native validation, frozen
focus/scope, live WAITING_ADD/ATTENTION/ADMITTED/VERIFIED rendering, dirty waiting
forms, mobile spacing and no passive device-refresh/execution requests.

No DDL, agent/wire, Compose, secret or runtime selector is added. The API projection
adds bounded original owner/predecessor-count metadata for honest controls and
complete scope validation. Do not use these controls to migrate or activate the
current lab. Future separately approved rollout requires checked SQLite-safe
backups, compatible images and drained old writers/sessions under the prerequisite
profile manuals. Disabling new Web/API admission does not cancel older reservations
or delegated jobs; preserve evidence and use compatible pause/queue controls.
Never drop receipts or restore pre-retirement enabled policy to force rollback.
No lab services or device state were changed by this development packet.
