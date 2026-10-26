# Fenced Concurrent Standing Admission

Status: implemented behind independent default-false API/Web factory capabilities.
**Not enabled, migrated or deployed in the lab.** Saves standing authority alongside
independent device work, without executing ADD or resuming policy. Prerequisites:
[Standing Confirmation](bulk-standing-confirmation.md), [Device Leases](device-leases.md),
[Bulk Dispatch](bulk-queue-admission.md), [Continuous API](continuous-api.md).

## 1. Explicit capabilities and storage

API and Web factories each accept `bulk_policy_concurrent_enabled=False`. Enabling
it requires that factory's `bulk_policy_admission_enabled=True`; API also needs
the existing trusted eligible-profile IDs and explicit exact continuous owner.
Literal booleans only; invalid combinations refuse before initialization/binding.
No request/environment/Compose selector. Profile IDs attest eligibility, not agent
ADD scope or credential access. All credentials stay agent-only.

The original `confirm` coordinator/route retains full quiescence and suspended
execution. The new route requires exact existing device-fence/dispatch/attempt/
captured storage. Constructor/startup/requests never initialize, convert, resume or
repair it. This API composition keeps agent ADD/bulk dispatch/legacy controllers
off and executable ADD scope empty, regardless of concurrent policy permission.

## 2. Coexistence and conflicts

| Condition | Admission |
| --- | --- |
| Healthy observation lease or unrelated queued/RUNNING work | Allow without interrupting, renewing or releasing it. |
| Selected device ATTENTION, expired/future fence or retained unknown/reconciled-absent evidence | Refuse whole import. |
| Accepted pair pending command, failed/unknown ADD across generations, unattributed ADD, unsettled cancellation or held ordered cleanup | Refuse whole import. |
| Valid unrelated evidence outside the selected device/pair scope | Preserve; healthy independent scope may proceed. |
| Malformed held references anywhere | Unavailable evidence, never absence. |
| Protected exclusion | Never grant authority. |

All accepted members must qualify; no silent subset/split/rebase or single-target
loop. Ordinary pause blocks new grants; revocation is independent. New keys,
generations and ordinary queue retention cannot clear failed/unknown latches.
Global legacy execution must remain unowned under the exact fenced profile.

## 3. Atomic admission and fresh execution

Reuse the existing complete preparation/manifest, real Operator/Admin, exact count/
recurring consent, managed/protection revision CAS, classification/generation,
device identity/eligibility, expiry and capacity/reserve checks. A competing stale
review conflicts. Bind the frozen expected desired-suspension boolean for new
grants. Check selected fences, suspension and clock before changes and before
commit. Expiry during large writes rolls back policy/membership/audit, including
inside caught caller transactions. No lease stealing, attention clearing, command
settlement, new executor, queued job, hint or resume follows confirmation.

The separately enabled shared bounded worker alone may execute later. A complete
read must start **strictly after** concurrently admitted authority; equal
millisecond timestamps also refuse. Older portion revisions conflict, while valid
independent claims finish unchanged. Existing intent/generation/protection/fence/
deadline checks, priority, budgets and device serialization remain authoritative.

## 4. API, frozen consent and receipts

`POST /api/v2/managed-imports/confirm-concurrent` accepts the existing strict
descriptor/digest/count/consent/actor plus mandatory literal `expected_suspended`.
Original `Idempotency-Key` must equal descriptor UUID. Independent capability off
means unavailable, not old-route fallback. Public forms supply no actor/action/mode.

Status adds `bulk_policy_concurrent_enabled` and `managed_execution_suspended`.
Web freezes mode/suspension alongside original proposal/summary/key in its immutable
bounded session/CSRF cache. Both local/API concurrent capabilities precede one fixed
new-route call. Mode drift refuses without fallback/rekey. Count/checkbox, current
role, post-I/O expiry, frozen pages/input/focus and same-key unknown recovery remain.
New-grant suspension drift conflicts; original historical replay does not rearm.

Concurrent receipts add `admission_mode=fenced` and actual historical boolean
`restoration_suspended`, retaining `policy_saved`, `policy_only=true` and
`device_work_admitted=false`. Already-active desired policy is not reported as
suspended/resumed or verified ADD. Old unmarked receipts keep their exact contract.
Root/BFF readers recognize both forms; cross-mode key reuse conflicts. Owner
history works after restart/draft pruning/admission disablement. Lost/malformed
replies are unknown: inspect receipts or explicitly retry the same frozen route/
review/key. No split, automatic replay or inferred rollback. Optional later status
failure cannot negate a checked historical receipt.

## 5. Validation and rollout

```bash
python3 -m pytest -q tests/test_bulk_concurrent.py tests/test_bulk_confirmation.py tests/test_bulk_dispatch.py tests/test_device_leases.py tests/test_bulk_cancellation_surface.py
node --test tests/browser/freshness.cjs
```

Disposable SQLite/ASGI/BFF/shared-queue tests cover active same-device independent
ADD, strict fresh/equal-millisecond refusal then actual fresh discovery/claim/result,
whole-scope barriers, failed evidence after retention, held ordered/cancellation
gaps, late expiry rollback, competing-user CAS, gates/original-key recovery and
100000-pair admission with unchanged leases/no queue backlog. Chromium covers
independent gating, frozen active consent/focus, history labels and mobile layout.
No SSH/FTD throughput or new lab fixture is authorized by these tests.

No DDL, runtime selector, Compose, inventory, secret or lab state changes. Before
separately approved rollout, drain old owners/RPCs, verify exact profiles and retain
checked SQLite-safe backups with matching images/configuration. Update all readers/
writers before new receipts: older code does not recognize fenced receipts and
is not a valid downgrade after admission. Disabling admission does not delete
policy or pause enabled workers. Never restore enabled retired policy or discard
evidence to force rollback. Configured executable rollout/nonempty migration,
recovery and real multi-device/load acceptance remain separate.
