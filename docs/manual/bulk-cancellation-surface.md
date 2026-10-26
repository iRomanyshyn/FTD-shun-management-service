# Version-2 Import Cancellation API and Web

Status: implemented for the explicit continuous profile. **No lab migration,
activation or deployment.** Connects [whole-root cancellation](bulk-cancellation-and-work.md)
and [captured settlement](bulk-captured-cancellation.md) to Web. It does not enable
ADD, resume maintenance or request device removal. Prerequisites:
[Standing Confirmation](bulk-standing-confirmation.md), [Continuous API](continuous-api.md).

## 1. Consequences and access

Cancellation stops an original import's uncompleted portion, leaving applied
additions and current shuns in place.

| Original accepted target | Result |
| --- | --- |
| Adopted/previously managed | Keep maintenance authority. |
| Owned VERIFIED/NOOP application | Keep maintenance; NOOP does not invent creation. |
| Unsent grant/owned QUEUED work | Retire exact original authority; cancel only its own unsent job. |
| First owned ADD is RUNNING | Capture WAITING_OUTCOME; let the shared command finish. |
| Failed/unknown first application | Stop future maintenance; retain failure/uncertainty. |
| Stopped/newer generation | Leave stopped/replacement authority untouched. |
| Protected/invalid exclusion | No imported authority to cancel. |

The shared result transaction settles captured commands. Success/no-op retains
still-enabled original authority; failure, uncertainty or exact deferral stops
future maintenance. Protection, prior retirement and newer authority take priority.
No second worker, REMOVE, interruption, re-enablement or uncertainty resolution.

Require the original owner with current Operator/Administrator or another current
Administrator. Actual trusted identity/roles supply private actor fields. Admin
cancellation access does not reveal another owner's private policy receipt.
Revocation needs no new admission gate: it works during ordinary pause, suspended
restoration and disabled ADD/standing admission. Existing exact v2/fenced/captured
storage is mandatory; constructor/startup/requests never initialize or repair it.

## 2. Browser procedure

1. Open the original receipt under **Imports → Saved policy receipts**.
2. Expand **Cancel uncompleted import work**; select **Review whole-import
   cancellation**. This CSRF POST prepares consent, not cancellation.
3. Inspect totals and at most 100 accepted members per page, distinguishing
   retained, stopped and waiting work.
4. Type the exact accepted device/IP **pair count**; select **Cancel uncompleted
   work only**. The complete original scope is confirmed together.
5. Open **Check original cancellation status** for current local settlement and
   attention. Original receipt counts, including initial WAITING, stay immutable.

The review binds original import/scope/authority/attempts, managed/protection
revisions, subject, canonical UTC time and digest for five minutes. Web consent
is immutable, subject/CSRF-cookie-bound, <=five minutes/five per subject/256 total
and lost on Web restart. Paging preserves entered count/key/digest and rechecks
the complete original review. Changes/expiry conflict without rebasing.

Confirmation accepts CSRF, token and exact typed count only. Recheck current role,
session and expiry after metadata I/O before one fixed private request. The import
UUID identifies cancellation, not a new operation key/action. Public forms never
supply actor/profile authority.

Lost/malformed reply means **unknown**. Explicitly retry only the same original
review/actual actor or inspect durable status. Matching retries return historical
receipts, even after draft pruning/expiry. Changed display name/roles or payload
may conflict: inspect status rather than impersonating the old actor. Optional
later metadata failure does not negate a checked receipt.

## 3. Private protocol and status

All POSTs under `/api/v2/managed-imports/`, private UDS/trusted actor/no-store:

| Suffix | Strict request / result |
| --- | --- |
| `cancellation-review` | Actor + original UUID; five-minute review/counts/digest or exact already-requested marker. |
| `cancellation-targets` | Actor + UUID/time/digest/accepted count/page; full review and end-of-read expiry checks, <=100 accepted members. |
| `cancel` | Actor + UUID/time/digest/accepted count; atomic cancellation and historical HTTP 200 receipt/replay. |
| `cancellation` | Actor + UUID/page; current settlement with immutable initial receipt, or explicit not-requested state. |

Count is a literal integer 1..100000; page 1..1000. UUID, lowercase digest and UTC
millisecond time are canonical. Boolean/string counts/pages, extra fields and
alternate scopes refuse. Revocation updates metadata without waking device work.
`bulk_import_cancellation_available=true` means interface support, not healthy
storage/new policy permission. No v1 fallback/conversion.

`/managed-imports/v2/cancellations/{original_uuid}?page=1` survives restart/draft
pruning. Passive local updates preserve open receipt details, distinguish initial
and current dispositions and show pending/attention with <=100 members. The exact
fenced profile requires complete captured-status counts/attention; missing fields
cannot downgrade to a legacy view. Corrupt/missing evidence is unavailable.
Completed owned history may legitimately retain an attempt digest without a pending
job reference. That is historical evidence, not a RUNNING capture; WAITING_OUTCOME
still requires its exact original job/history binding.

GET never confirms, settles, repairs, expires/promotes work or queries FTD.
SETTLED means no captured waits remain, not verified removal/resolved uncertainty.
Refusals: 403 permission, 409 changed/expired review, 422 strict input, 503 missing/
corrupt/unavailable state. Response failure after submission is not rollback proof.

## 4. Validation, rollout and rollback

```bash
python3 -m pytest -q tests/test_bulk_cancellation_surface.py tests/test_bulk_cancellations.py tests/test_bulk_waits.py tests/test_bulk_confirmation.py tests/test_continuous_api.py
node --test tests/browser/freshness.cjs
```

Disposable actual BFF/ASGI/SQLite tests cover 100000-pair cancellation/late pages,
retained policy, real fenced claims/shared success/no-op/failure/unknown settlement,
strict fields/CSRF/owner/Admin, pause/gates, unknown replies/original-review retry,
expiry/conflicts, cache/restart/pruning and no initialization/device work. Chromium
checks native consent, frozen focus/scope, local live settlement/attention,
historical receipt and mobile pagination/layout. No transport/production acceptance.

No DDL, agent/wire, runtime selector, Compose, credential or lab state changes.
Before separately approved rollout/conversion, drain owners/RPCs, verify profiles
and retain checked SQLite-safe backups with matching images/configuration.
Code rollback does not undo cancellation. Keep compatible writers or data offline;
never drop decisions/settlements, restore enabled retired policy or use writers
that ignore uncertainty/fences to force rollback.
