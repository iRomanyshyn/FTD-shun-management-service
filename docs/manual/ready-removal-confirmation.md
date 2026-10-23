# Version-2 Ready-Removal Confirmation

Status: implemented for explicit developer continuous composition, independently
default-disabled in API and Web. Not deployed or an environment/migration/lab
activation runbook. Ordinary legacy deployment remains unchanged. See
[Ready-Scope Backend](bulk-ready-removal.md),
[Continuous API](continuous-api.md) and [Policy Views](bulk-policy-views.md).

## Independent admission capabilities

API and Web `create_app` each accept a literal
`ready_removal_admission_enabled=False` factory argument. Neither accepts this
capability from HTTP, status, form fields, `.env`, CLI or Compose. The API requires
the explicit compatible fenced continuous dispatcher; enabling on legacy runtime
refuses before storage initialization. Web enablement requires socket/session/
large-read settings and production identity handling. The two factories must be
configured separately by trusted composition; status only advertises API readiness.

The legacy `FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED` and cleanup-worker switches
do not enable this workflow. ADD/import/restoration and incompatible legacy gates
remain off. No runtime/profile is selected or migrated by the new argument.

| Web capability | API capability | Result |
| --- | --- | --- |
| Off | Off or on | Preparation only; confirmation sends no admission POST. |
| On | Off/unavailable/incompatible | Preparation can work; confirmation refuses without submitting. |
| On | On, compatible | Exact frozen confirmation may submit; backend still rechecks every guard. |

The API refuses disabled v2 removal POSTs before body/legacy dispatch. DOM/status
edits do not change either local capability. New `ready_removal_review_available`
and `ready_removal_admission_enabled` status fields are separate from unavailable
general managed/import/manual mutation workflows.

## Prepare a single-device or fleet review

In the explicit v2 **Managed shuns** page, expand **Review stop maintaining and
remove — ready targets only**:

1. Choose one exact device/IP on the current page, or enter one exact IPv4 for
   the complete fleet union of observed/enabled-managed devices. Add a reason
   if useful. These are separate fixed preparation forms, not arbitrary scope JSON.
2. The CSRF-protected POST reads compatible v2 status and the exact readonly scope
   resource. It does not query Cisco, retire policy or enqueue/hint work.
3. Check every device, including missing/disabled ones, desired policy and original
   generation. Unmanaged targets are cleanup-only, never adopted. Disabled devices
   visibly block admission; they are not silently skipped.
4. Check reason, policy/protection revisions, cleanup lifetime and request key.
   Preparation is available with execution off, with a disabled confirmation.

The separate `/managed-shuns/v2/removal-review` and `/fleet-removal-review` POSTs
freeze exact mode, IP, original target identities, global/target revisions,
protection and observed membership. Readonly markers and scope digest must match
the requested resource exactly; malformed/partial/substituted scope refuses.
No v1 fallback or automatic replacement review exists.

The process-local immutable cache binds subject and CSRF-cookie hash. It retains
at most five open reviews per subject/256 total, expiring within ten minutes or
the shorter configured sensitive-action age. Overflow rejects without evicting
other reviews; cookie change, expiry or Web restart invalidates the token.
All mutable JSON is frozen as canonical text and decoded into fresh copies.

## Confirm explicitly

Type the exact IPv4 and submit the native confirmation form. The BFF checks
current authentication/Operator or Administrator, CSRF, review ownership/expiry,
typed IP and local Web capability. It reads current compatible API capability,
then rechecks review expiry **after** that I/O and before the admission POST.
Only the frozen token/typed IP/CSRF are accepted from the form; actor, key, mode,
targets, reason, revision, digest, lifetime and gates cannot be forged in fields.

The BFF selects only the frozen v2 device/fleet route, using the original UUID:

```text
POST /api/v2/managed-removals/device
POST /api/v2/managed-removals/fleet
```

These strict private routes enforce literal version/IDs/flags, at most ten targets,
bounded real actor/reason, exact mode/action digest and a 1..900-second delegation
not exceeding the configured sensitive-action maximum. The API invokes the
existing whole-scope coordinator once. It preserves ready-only conflict, unknown
ADD/device/fence, pause, protection, rate and capacity checks. No partial fleet,
RUNNING-ADD interruption, ordered-wait fallback or authority rebase is performed.
Only after commit does the API publish data change and wake existing queue work.

## Read admission separately from execution

HTTP **202** means local admission/replay, not verified FTD removal. The BFF checks
literal v2 action/mode/flags, original key, exact target/retirement counts and saved
revision, unique canonical job IDs for every original device, and original UTC
expiry. `verified_removal=false` must remain explicit. The page says **Removal
queued — not verified removal**; Queue/status reports subsequent individual
VERIFIED/NOOP/failure/expiry/unknown outcomes.

A changed scope returns conflict without partial retirement. Lost/malformed
responses are unknown: inspect state and explicitly retry only the same frozen
review/key. The server never auto-submits, rekeys, shrinks the fleet, renews TTL or
reconstructs pruned jobs. Original-key replay is historical and cannot retire a
newer grant. A validated receipt remains valid if a later optional status read
fails. Original outcomes and admission receipt remain distinct.

Status polling/local timezone display continue, but frozen confirmation never
GET-reloads/replaces its targets, token, typed IP or focus. Form data is escaped;
device tables scroll within mobile layout and the confirmation button is separated
from input. Unknown outcomes after cache expiry/restart need retained history/
Queue inspection, not a newly keyed blind retry. Automatic evidence-based recovery
and captured RUNNING-ADD ordering remain separate unfinished integrations.

## Rollout and rollback

No new DDL/schema, `.env`/Compose, optional initialization, runtime selector,
inventory/credentials, live gate/profile/fixture, lab database or image/service
changed in this increment. The synthetic factories enable capabilities only for
disposable tests. This does not authorize a lab migration or new device mutation.

Future separately approved rollout needs compatible paired API/Web images and
assets, checked SQLite-safe backup/configuration and drained previous workers.
API startup may execute already admitted queue/protection work. Keep rollback
images; disabling capability closes new submissions but does not cancel admitted
jobs or resume retired policy. Preserve receipts, original unknown evidence and
device fences; never erase them or restore enabled authority to force a downgrade.

## Validation

```bash
python3 -m pytest -q tests/test_ready_removal_web.py tests/test_continuous_api.py tests/test_bulk_removals.py tests/test_managed_shuns.py tests/test_refresh_bff.py
node --test tests/browser/freshness.cjs
```

Disposable ASGI/SQLite tests use actual BFF → API → coordinator → shared jobs,
including a semantic fake continuous-worker lifecycle. They cover independent
gates, real actors/auth/CSRF/roles, frozen scope/conflicts/cross-purpose tokens,
strict fields/modes, lost/malformed receipts, original-key replay, post-I/O expiry,
cache/cookie/restart bounds and optional status failures. Chromium uses production
templates/JavaScript for frozen fields, escaping, gate display and mobile spacing.
No live SSH/FTD/load or production acceptance is implied.
