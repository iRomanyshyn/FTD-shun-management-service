# Version-2 Private Ordered-Removal API

Status: developer composition on existing exact fenced storage, default-disabled.
**Not migrated, enabled or deployed in the lab.** This is not a public API, a
runtime selector, frozen browser consent or permission to issue live mutations.
Read [Ordered Reservations](bulk-ordered-reservations.md),
[Ordered Promotion](bulk-ordered-promotion.md) and
[Continuous API Composition](continuous-api.md) first.

## Capabilities and storage

`api.create_app(..., continuous_dispatcher=dispatcher,
ordered_removal_admission_enabled=False)` supplies an independent literal factory
capability. True requires the explicit compatible continuous owner, strict cycle
settlement, its separate `ordered_promotion_enabled=True` capability and the
already complete optional reservation/promotion profile. Validate before binding
the dispatcher and again at API lifecycle startup. No constructor or request
initializes optional tables, imports environment policy or enables ADD.

The ready-only capability cannot enable ordered admission or vice versa. All
legacy ADD/admission/restoration gates remain off in this API composition.
No environment/CLI/HTTP input selects these developer capabilities. A future
configured runtime and separately authorized acceptance remain required.

Status advertises `ordered_removal_review_available`,
`ordered_removal_admission_enabled` and `ordered_removal_promotion_enabled`
separately. Capability metadata is not consent or verified device success.
Disabling admission does not revoke an earlier accepted reservation. Disabling
promotion does not stop already delegated jobs; pause and ordinary queue controls
retain their existing meanings.

## Fixed private routes

All responses are `Cache-Control: no-store`. Existing private UDS/network and
trusted BFF identity boundaries remain unchanged; no port is published.

| Method and route | Contract |
| --- | --- |
| GET `/api/v2/managed-ordered-removal-scope/{ip}` | Read-only whole-fleet preflight; optional `device_id` selects one exact pair. |
| POST `/api/v2/managed-ordered-removals/device` | One explicit ordered device reservation. |
| POST `/api/v2/managed-ordered-removals/fleet` | One atomic whole-fleet reservation, never a loop or ready subset. |
| GET `/api/v2/managed-ordered-removals/{operation_id}` | Original scope/expiry, predecessor outcomes, retained decision and delegated REMOVE job states. |
| POST `/api/v2/managed-ordered-removals/{operation_id}/cancel` | Owner/Administrator local waiting revocation; actor-only input. |

Inspection needs the exact base fenced profile, not optional ordered tables or
enabled admission. It uses the queue's explicit UTC clock and returns READY,
WAITING_ADD or BLOCKED with the full scope/blockers and original predecessor
evidence. There is no automatic ready/ordered fallback. Preflight alone never
retires policy, reserves capacity, expires work, promotes or hints a device read.

Admission requires `Idempotency-Key` as the original canonical UUID and a strict
body with `actor`, `reviewed`, `predecessors`, `confirmation_digest`, `ttl_seconds`
and optional `reason`. Actor includes the real subject/display name and actual
Viewer/Operator/Administrator roles; Operator or Administrator is required.
The fixed route must equal the frozen scope mode. TTL is a literal integer within
1..min(900, configured sensitive-action maximum); reason is bounded plain text.
Each sorted predecessor contains the exact device and all typed original
job/request/intent/generation/authority/snapshot/claim/epoch/deadline/digest fields.
Extra fields, coerced boolean/string epochs, missing evidence, reused ready-only
digest and substituted action/scope fail closed. No arbitrary command is accepted.

The coordinator rechecks the entire frozen state in one transaction and permanently
retires matching maintenance while reserving all cleanup targets. Drift, wrong
mode/actor/digest, capacity/rate/TTL or late audit failure cannot partially retire
or reserve. Only newly committed acceptance notifies the existing continuous
owner; replay does not create/wake work or renew authority.

## Historical receipt versus current status

HTTP 202 is the original WAITING_ADD reservation receipt, **not REMOVE admission
or verification**. It retains original requested-at/expiry, target/predecessor
counts, retired policy revision and `device_work_admitted=false`/
`verified_removal=false`. Original-key retry returns the same historical values
with `replayed=true`, even after later transfer/attention/cancellation. A lost or
unrecognized reply must be inspected/retried using that exact original key, never
re-keyed or reduced to a ready subset.

Use the distinct GET status for current state. It includes the immutable `scope`,
`requested_at`, `expires_at`, captured `predecessors`, `cleanup_reserved`,
`device_work_admitted`, retained `attention`, `decision`, and bounded
`cleanup_jobs` with original device/job IDs and current job states.
`verified_removal` becomes true only when every original delegated REMOVE job is
explicitly VERIFIED. ADMITTED with QUEUED/RUNNING/NOOP/failed/unknown jobs is not
verified removal. Missing/inconsistent evidence is unavailable, never an empty
successful list. The projection is local evidence, not a new Cisco query.

GET never runs maintenance or changes state after expiry: the shared maintenance
transaction owns expiry. A stored WAITING_ADD phase can therefore retain an
already elapsed deadline until that transaction runs. Always display the original
deadline independently; a read does not extend it. ATTENTION remains explicit
even when waiting authority is cancelled or expires.

Cancellation accepts only the current real `actor`; it needs no new-admission or
promotion capability and remains local during pause. A different ordinary
operator is forbidden; owner or Administrator may revoke. Repeating a terminal
revocation is side-effect-free. Cancellation never resumes retired policy,
changes a RUNNING ADD, clears uncertainty or hints device work. ADMITTED/internal
ADMITTING work conflicts; ordinary queue controls govern already delegated jobs.

## Errors, rollout and rollback

Disabled admission or unavailable profile/evidence returns 503; role/ownership
failure 403; stale/conflicting scope, retained-authority capacity or already
delegated cancellation 409; shared queue/rate exhaustion 429; invalid strict input
422. An absent canonical root
returns 404, distinct from malformed retained evidence (503). Noncanonical route
aliases are refused, not normalized into another root. Inspect original state
after an unknown response; HTTP failure never proves a previous attempt absent.

This packet changes no schema, deployment settings, credentials or FTD protocol.
It does not authorize the prerequisite optional migrations, fixture setup, live
enablement or production rollout. No dev services were restarted. A future
approved rollout must first drain old writers/sessions, inspect retained work and
take checked SQLite-safe backups with matching images/configuration, following
the prerequisite migration manuals. Older images must not write or prune ordered
evidence. Disable new admission/promotion and use compatible pause/queue controls
for rollback; never delete receipts or restore pre-retirement enabled policy to
force a downgrade. Frozen session/CSRF-bound Web confirmation/status remains next.

## Synthetic validation

```bash
python3 -m pytest -q tests/test_ordered_removal_api.py tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_promotion.py tests/test_continuous_api.py tests/test_managed_shuns.py tests/test_managed_fleet_removals.py
```

Disposable SQLite/ASGI/fake sessions only: separate default-off gates, literal
typed input, full device/fleet scope, stale membership, actual actor audit,
same-key concurrency/retry, unchanged TTL, rollback, truthful job status,
owner/Admin revocation under pause/disabled admission, missing/corrupt evidence,
startup drift refusal and actual shared continuous fake REMOVE execution.
No real lab migration, device mutation or transport acceptance is implied.
