# Version-2 Suspended Standing Import Confirmation

Status: implemented behind independent default-false API/Web factory capabilities.
**Not enabled, migrated or deployed in the lab.** This workflow saves durable
recurring policy only, with desired execution suspended. It does not admit ADD,
resume restoration, signal device work or prove that an IP is blocked.

Read [Preparation Web](bulk-preparation-web.md),
[Preparation API](bulk-preparation-api.md), [Bulk Storage](bulk-policy-storage.md)
and [Restricted Continuous API](continuous-api.md) first. These controls retain
the existing quiescent confirmation contract. Independently gated
[fenced concurrent admission](bulk-concurrent-admission.md) now checks selected
device/pair barriers without global quiescence. [Confirmed-import cancellation](bulk-cancellation-surface.md)
now has exact consent/private routes and local settlement status.

## 1. Composition and prerequisites

Only trusted Python composition can supply:

| Factory | Default | Meaning |
| --- | --- | --- |
| API `bulk_policy_admission_enabled` | `False` | Permit the fixed policy-only confirmation route on an explicit compatible continuous owner. |
| API `bulk_policy_device_ids` | Empty `frozenset` | Immutable reviewed eligible-profile scope, at most ten literal device IDs in 1..65535. |
| Web `bulk_policy_admission_enabled` | `False` | Permit submission from the frozen recurring-consent form. |

Enabled API admission requires a nonempty scope; disabled admission requires an
empty scope. Every eligible ID must belong to the existing sealed enabled device
scope. The factory validates exact existing profiles and suspended desired
execution before binding and again before startup. Invalid capability/context
refuses before database initialization. Web enablement requires socket/session/
large-read mode with development authentication disabled.

The scope is an explicit trusted-composition **attestation of reviewed addition
profile eligibility**. The API database does not store the agent's addition
profiles; these IDs do not fetch profiles/passwords, configure credentials or
enable agent ADD. They cannot come from a request, status edit or environment
selector. Agent credentials remain agent-only. Legacy ADD/import/restoration
gates, empty executable ADD scope and all current fixed-wire checks stay intact.

New confirmation requires an existing exact v2/fenced profile and preparation
journal, suspended desired execution, unpaused new authority, no active global
lease/device session, no pending/uncertain work, correct original owner and current
Operator/Administrator. It rechecks the complete manifest, preparation expiry,
device identities/profiles, observations/classifications, protection and managed
revisions, key collisions, capacity and retirement reserve inside one write
transaction. An active observation session conflicts; this workflow does not
interrupt it, wait inside its stream or automatically retry.

## 2. Review and explicitly consent

1. In `/managed-imports/v2`, save a non-authoritative draft with explicit devices.
2. Inspect the frozen report and exact policy proposal. Invalid/duplicate source
   diagnostics and protected exclusions remain visible; no scope is truncated.
3. Select **Prepare separate recurring-policy consent**. This CSRF-protected POST
   validates the report/proposal and freezes the original descriptor, digest,
   accepted scope and stable operation key; it does not submit policy.
4. Inspect up to 100 frozen members per page. Paging preserves entered count and
   consent without substituting scope. Type the exact **accepted pair count** and
   check the explicit recurring-maintenance consent.
5. Select **Save suspended standing policy** when both independent capabilities
   and every selected eligible profile are available. The server rechecks actual
   role, session cookie, expiry after metadata I/O and all API preconditions.

The immutable local review cache is subject/CSRF-cookie-bound, limited to five
per subject/256 globally and at most ten minutes. Its cache UUID is distinct from
the original operation key. Web restart loses the consent form, not saved policy
or historical receipts. Passive metadata updates preserve count, checkbox, focus
and frozen evidence; GET never confirms or requests FTD refresh.

Accepted PROPOSE_ADD/PROPOSE_ADOPT members acquire standing authority atomically;
adoption does not invent past service creation. ALREADY_MANAGED preserves original
authority. EXCLUDED_PROTECTED never acquires authority. One whole-scope transaction
stores policy, immutable membership, original actor and audit, or nothing. It does
not loop over single-target admission or create thousands of executable jobs.

## 3. Private protocol and recovery

All routes below are private fixed POSTs with the actual trusted actor, strict
fields and `Cache-Control: no-store`. Browser forms never supply actor/action or
profile JSON.

| Route under `/api/v2/managed-imports/` | Request / result |
| --- | --- |
| `confirm` | Canonical v2 descriptor, digest, literal accepted count and `maintain_present=true`; `Idempotency-Key` must equal the descriptor operation UUID. Returns checked HTTP 200 policy receipt. |
| `receipts` | Owner actor only; at most 128 immutable root references, available with admission disabled. |
| `receipt` | Owner actor, canonical original operation UUID and page 1..1000; at most 100 original members, full retained root integrity verified first. |

Receipt fields explicitly say `policy_saved`, `policy_only=true`,
`device_work_admitted=false` and `restoration_suspended=true`. This is historical
policy consent, **not device success, current effective policy or queue progress**.
Original-key replay returns the original receipt and actor without re-enabling
retired targets, replacing newer authority or repeating device work.

Lost/malformed confirmation replies are **unknown**. Inspect **Saved policy
receipts** or explicitly retry only the same frozen review/key. Never generate a
new key, split the scope, infer rollback, rebase classifications or replay ADD.
An optional follow-up status failure does not negate a checked policy receipt.
Malformed counts/classes/revision/flags, actor or member evidence refuse success.

`/managed-imports/v2/receipts/{operation_uuid}?page=1` is an owner-bound historical
permalink. It survives Web restart and preparation expiry/approved pruning;
retained membership is independent of the draft. Authenticated owners retain
read access after role loss, but may not create new standing consent. Another
owner, including Administrator, cannot inspect a private receipt. Missing or
corrupt evidence is unavailable, never an empty successful import.

Invalid input is 422, current-role refusal 403, changed scope/expiry/quiescence/
capacity 409 and disabled/missing/corrupt state 503. A 503 or lost connection after
submission is not proof of rollback. Preparation cancellation remains draft-only;
a confirmed import cannot be revoked through that route.

## 4. Validation, rollout and rollback

```bash
python3 -m pytest -q tests/test_bulk_confirmation.py tests/test_bulk_preparation_web.py tests/test_bulk_preparation_api.py tests/test_continuous_api.py tests/test_bulk_policy.py
node --test tests/browser/freshness.cjs
```

Tests forward actual BFF requests to the ASGI API on disposable exact SQLite
profiles, including 10000 IPs × ten devices, atomic policy/no device work, current
actor, separate gates, strict consent/CSRF/owner, changed scope/expiry/lease/pause,
lost/malformed replies, same-key replay after retirement, frozen pages and
restart recovery after draft pruning. Chromium uses production templates/JS and
a local synthetic server for native count/checkbox validation, focus/input,
independent Web gating, historical pages/escaping and mobile layout. These are
not FTD throughput, live ADD/restoration or production acceptance.

No DDL, migration, runtime/environment selector, Compose setting or secret changes.
No lab services, gates, profiles, fixtures or device state are changed. Before a
separately approved rollout, drain old owners/sessions, review existing-profile
compatibility and nonempty conversion, and preserve checked SQLite-safe backups
with matching images/configuration. Disabling admission only blocks new grants;
it does not delete earlier policy, receipts or jobs. Keep desired execution
suspended and separately control executable gates. Never drop authority/evidence
or restore pre-retirement policy to force compatibility. An old writer that
ignores v2/fence evidence is not a valid rollback target.
