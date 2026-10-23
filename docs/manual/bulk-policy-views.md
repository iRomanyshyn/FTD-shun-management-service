# Version-2 Managed Policy Views and Local Retirement

Status: implemented for the explicit developer continuous API composition only.
Not an environment selector, migration/activation runbook or live acceptance.
Ordinary deployed legacy behavior is unchanged. See
[Restricted Continuous API](continuous-api.md) and the
[working-version target](../working-version-plan.md).

## What the page means

The Managed shuns page separates standing intent from current observations:

- **Maintain presence / Stopped** describes retained desired policy, not whether
  ADD execution is enabled. Global suspension and disabled devices remain visible.
- **Observed present** describes local device observations, not proof the service
  created an entry. Absence is not itself a verified disappearance or reboot.
- Retained FAILED/UNVERIFIED attempts need attention across generations. Missing
  original unknown-job evidence is a warning, never inferred success.
- Only VERIFIED attempts contribute to **Last verified ADD**. NOOP means the
  address was already present; it is not evidence of service creation.
- Original author, authorization time, generation, label and reason are retained;
  operator content is escaped and timestamps use the existing local-zone display.

This restricted profile does not expose creation, adoption, bulk import admission,
legacy combined device removal, policy resume or uncertainty resolution. Protection and
previously admitted REMOVE keep their independent existing execution safeguards.
Separate [ready-removal scope inspection](bulk-ready-removal.md) is available as
a readonly private GET. Separate [ready-only confirmation](ready-removal-confirmation.md)
has independent default-off Web/API capabilities; policy viewing never enables it.

## Bounded private reads

| Method and path | Contract |
| --- | --- |
| `GET /api/v2/managed-shuns/page?page=1&revision=N` | At most 100 target rows; total retained capacity 200000 keys. Omit revision only to open current policy. |
| `POST /api/v2/managed-shuns/selection` | At most 100 exact distinct device/IPv4 pairs, explicit selection descriptor including missing pairs; optional exact revision. |
| `POST /api/v2/managed-shuns/retire` | One exact pair, frozen revision/digest and original UUID key; policy-only revocation, not device removal. |

Reads use an existing SQLite `mode=ro` transaction, including metadata, rows and
evidence in one snapshot. They never initialize/repair tables, create an absent
database, call the agent, enqueue/hint work, adopt observations or resume policy.
Bulk authorization metadata is loaded once per distinct request on the page,
not copied once per target. No whole-registry or legacy-view fallback is used.

Missing/corrupt optional state is unavailable (503), not an empty policy. Invalid
page/selection is 422; a changed reviewed revision is 409. Pagination links pin
the revision; changing policy shows an explicit conflict and current-policy link,
never silently replacing the selected scope. JSON projections and BFF responses
retain authenticated/no-store behavior. The private API remains on its UDS.

## Stop maintaining, without removing a shun

1. As Operator/Administrator, open **Managed shuns** and expand **Stop maintaining
   one target — no device command**. Choose one enabled target on the current page.
2. Prepare the review and check device, exact IP, generation, policy format and
   revision. Review preparation only reads local selected state.
3. Type the exact IP and confirm. Current authentication/role and CSRF are checked
   again. The actor comes from the trusted BFF identity, not pasted form fields.
4. The existing v2 retirement transaction checks the exact digest/revision,
   disables matching support, increments policy revision and appends a real-actor
   audit event and immutable original-key receipt atomically.

This does **not** issue `no shun`, admit a queue request, cancel an independent
job, interrupt RUNNING ADD, clear failed/unknown evidence or change suspension.
Already running work still settles honestly. Existing claim-time authority checks
prevent unstarted standing work from gaining authority from retired policy.
Protected-IP removal is independent and may subsequently act on a protected shun.

Reviews freeze policy format as well as actor/session/target/generation/revision
and key. Confirmation uses that frozen versioned route, never current status to
rebase a review. `/api/v1` managed routes remain unavailable in this v2 composition;
a missing/failed v2 endpoint never triggers a v1 retry. A successful v2 receipt
must explicitly say `intent_format=2`, `policy_only=true`,
`device_work_admitted=false`. Malformed/lost receipts leave the outcome unknown:
retry only the same review/key, not a newly prepared request. A later optional
status error does not invalidate a checked receipt. Original-key retries return
the original result and never retire a newer grant/generation.

## Rollout and rollback boundaries

No DDL, migration, gate/profile activation, credentials or Compose change is needed
for this increment; no lab service/database/device was changed. New capability
fields advertise viewing and retirement independently from unavailable general
managed workflows. This code does not authorize creating v2 storage in the lab.

For a separately approved future continuous-profile rollout, retain checked
SQLite-safe backups and matching images/configuration, drain old owners and
validate actual transport/device behavior. Rollback removes UI/API access, not
recorded revocations: preserve retired policy, receipts and uncertainty. Never
delete fences or optional evidence to force an older runtime to accept storage.

## Validation

```bash
python3 -m pytest -q tests/test_bulk_policy_views.py tests/test_continuous_api.py tests/test_managed_controls.py tests/test_managed_view.py
node --test tests/browser/freshness.cjs
```

Disposable SQLite, ASGI and real Chromium fixtures cover readonly/no-init reads,
100-row pagination beyond the legacy 1000-key limit, concurrent snapshot changes,
exact selections, honest attempt provenance, authentication/CSRF/roles, stale and
malformed confirmation, frozen route version, original-key replay, drafts and
mobile overflow. No live SSH, new FTD mutation or production acceptance is implied.
