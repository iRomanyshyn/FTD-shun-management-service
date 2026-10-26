# Version-2 Import Preparation Web Workspace

Status: implemented for the explicit compatible v2 continuous API and existing
preparation journal. **Not migrated, activated or deployed in the lab.** These
pages create/inspect/revoke local drafts only. A separate independently gated
[standing-consent workflow](bulk-standing-confirmation.md) can save suspended
policy; these draft controls never grant authority, queue work or device execution. Read
[Preparation API](bulk-preparation-api.md),
[Durable Preparations](managed-import-preparations.md) and
[Bulk Format](bulk-import-capacity.md) first.

## 1. Open the private workspace

With literal `bulk_import_preparation_available=true` from a compatible API,
**Imports** links to `/managed-imports/v2`. This is not general managed/execution
enablement. Otherwise existing legacy navigation remains unchanged; direct v2
requests never fall back to a v1 registry or confirmation route. Standalone
non-executable preview remains available at `/imports`.

The workspace reads only public device labels and the authenticated owner's at
most four saved drafts. Wrong owner/unknown references never expose another user's
contents; Administrator is not a private-draft override. Missing journal is
explicitly uninitialized and disables creation. Unavailable/malformed state is not
an empty healthy workspace. No page initializes, repairs, migrates or prunes state.

Current Operator/Admin may create a draft. Other authenticated owners may inspect
or revoke their existing drafts after role loss, not create or inspect a new
policy proposal. Trusted Caddy identity supplies private API actor fields; forms
never accept posted actor/action/capability JSON. Existing no-store, private UDS,
trusted-header and secure HttpOnly CSRF boundaries remain.

## 2. Save a non-authoritative draft

Paste exact IPv4 tokens with supported surrounding text/comments, select one to
ten enabled devices and optionally supply 100/500-character label/reason. Metadata
is retained intentionally; never put secrets there. Bounds are 1 MiB UTF-8,
20000 lines and 10000 parsed rows, at most 100000 device/IP pairs. Invalid,
duplicate, unsupported, ambiguous and protected inputs remain visibly reported.
Raw source/comments are not stored in the journal.

**Save draft only** is an explicit Operator/Admin CSRF-protected URL-encoded POST.
The BFF rechecks parser/UTF-8/device/metadata limits and actual identity before one
fixed private call. Aliased/duplicate/boolean IDs, unexpected/repeated fields,
uploads and forged actors/actions are refused. A checked 201 must match the
requested product, canonical reference/digest and literal non-authority flags
before redirecting to the report.

A lost/malformed reply is **unknown**, not import success/failure. Transient text,
metadata and device choices remain, but repeat creation on that uncertain form is
disabled. Inspect **Saved preparations** before explicitly opening a new form.
Recovered references are not automatically selected as the successful result;
there is no automatic repost. Capacity remains four retained drafts per owner /
sixteen globally, including expired/cancelled entries until approved pruning.
Nothing is evicted; automatic pruning/executable idempotency is not implemented.

## 3. Inspect a frozen report

`/managed-imports/v2/{preparation_uuid}` survives Web restart because it reads
durable owner-bound state. Before rendering, the BFF checks exact v2 flags, owner,
UTC times/original ten-minute lifetime, state/confirmation references, complete
device/classification/source totals and bounded target/diagnostic pages. The API
has already verified the entire original header/member digest in one transaction.
Corrupt/missing evidence is unavailable, never a reduced successful scope.

| Frozen class | Meaning |
| --- | --- |
| PROPOSE_ADD | Future maintenance proposed for an originally absent/unmanaged pair; no job. |
| PROPOSE_ADOPT | Future maintenance over observed unmanaged state, not past service creation. |
| ALREADY_MANAGED | Preserve original authority, not a replacement grant. |
| EXCLUDED_PROTECTED | Conspicuously excluded pair, never authority. |

The report retains original author/captured roles, labels, selected device names,
managed/protection revisions and expiry. Protected rows/badges and colored source
statuses remain visible, with global invalid/unsupported/ambiguous/duplicate and
protected totals. Each page has at most 100 targets and 100 generated diagnostics;
Previous/Next keep the exact draft/review mode across up to 1000 pages. No clamping,
truncation or reclassification occurs.

PREPARED, EXPIRED, CANCELLED and CONFIRMED remain distinct. Confirmed drafts identify
earlier policy receipts, not proof current maintenance is enabled. Non-authority
flags describe this read, not absence of historical policy. Opening/retrying a
report never renews expiry, queries FTD, grants policy or cancels work.

## 4. Inspect the future managed-policy proposal

For a live scope with accepted pairs, current Operator/Admin may open
**Inspect exact future managed-policy proposal**. This is a GET over a fixed
owner-bound report and pure private proposal inspection, not recurring consent.
The operation UUID is derived from the original preparation and a distinct v2
namespace, stable across restart/pagination and different from preparation/legacy
keys. Constructibility does not reserve a key or grant authority.

The BFF validates canonical descriptor/digest/manifest, exact preparation digest,
revisions, metadata, selected devices and all classified/excluded totals against
the report. The API independently checks original membership and its own UTC
expiry/clock. Expired/cancelled/confirmed/zero-accepted drafts cannot produce a
proposal. The original report stays inspectable without a fallback or rebase.

The page shows accepted/excluded classes, original reference, stable key and full
hashes. The proposal remains non-authoritative. **Prepare separate recurring-policy consent** opens a distinct
CSRF/Operator frozen review, not submission. Actual policy confirmation uses
[independent default-off capabilities and complete current-state checks](bulk-standing-confirmation.md).
The original mode saves suspended policy only. Separate
[concurrent consent](bulk-concurrent-admission.md) freezes actual mode/suspension;
device work remains separately disabled in this composition.

## 5. Cancel the unconfirmed draft only

Expand **Cancel this unconfirmed draft only** and explicitly submit. The fixed
original-UUID CSRF POST accepts only CSRF and supplies the actual authenticated
owner, including after role loss/pause. It never retires policy, cancels a confirmed
import, interrupts ADD or changes queue work. Confirmation winning the transaction
race causes conflict; repeated draft cancellation is side-effect-free.

The BFF checks the exact draft-only receipt. A checked receipt stays visible if
the later report becomes unavailable; an unknown cancellation reply permits only
inspection/retry of this same original draft. No automatic rekey, creation, scope
shrink or standing-policy cancellation is inferred.

## Browser behavior, validation and rollout

Passive status/queue metadata updates preserve pasted text, device choices,
labels/reasons, frozen report/proposal and focus. They never create/cancel drafts,
request FTD refresh or replace/reclassify scope. Explicit reload/check links read
current local draft state. All metadata is escaped; UTC fallback is localized with
a timezone in browsers. Existing responsive forms/table scrolling keep narrow
screens usable without overlapping controls.

```bash
python3 -m pytest -q tests/test_bulk_preparation_web.py tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_ready_removal_web.py tests/test_ordered_removal_web.py
node --test tests/browser/freshness.cjs
```

Actual BFF/ASGI API tests use disposable exact SQLite profiles, including maximum
100000-pair staging/pagination/proposal, owner/role/CSRF/restart, unknown replies,
strict reports/manifests, closed/confirmed refusal and unchanged policy/queue/
origin/audit. Chromium uses production templates/JS with a local synthetic server
for navigation, input/focus preservation, missing storage, escaping, colored
exclusions, frozen keys, 100-row pages and mobile overflow; no device demand.

No DDL, agent protocol, Compose setting, secret, runtime selector or live activation
is added. No lab migration/fixture/service/device changed. Future rollout requires
compatible existing profiles, scoped migration/activation approval, drained writers/
sessions and checked SQLite-safe backups with matching images/configuration.
Older writers must not reinterpret v2 authority/evidence. Preserve evidence rather
than dropping schemas or restoring pre-retirement policy to force rollback.
This browser implementation is not production/device acceptance.
