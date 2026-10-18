# Combined Managed Cleanup — Gated Device and Fleet Admission

## Boundary

This workflow atomically stops the reviewed desired maintenance and admits a
cleanup plan, or changes neither. It uses the existing single/fleet coordinators
and shared queue, not HTTP-to-SSH. **Admission is not verified removal.**
No cross-device atomicity or physical exactly-once command delivery is promised.

`FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED=false` is an independent strict
boolean. True requires socket mode and
`FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED=true`, so ordered waits are not knowingly
admitted without promotion capability. ADD, standing grants and restoration have
their own gates. This gate never initializes optional schemas or resumes policy.
All actual lab gates remain off; no fixture/migration or live cleanup is implied.

## Operator workflow

### One FTD

In **Managed shuns → Prepare a single-target removal review**, choose the exact
retained device/IP and optional reason. The frozen review shows hostname,
intent/generation, managed revision and retained observation/protection.
Missing observation is still a target. A disabled device blocks cleanup; use
policy-only retirement if it must be revoked without device work.

Type the exact IPv4 and confirm **Stop maintenance and queue removal** only
when admission is independently authorized/enabled and explicit schema migration
is complete. One transaction retires the intent, cancels its unstarted system
restoration and either delegates REMOVE or captures the exact RUNNING ADD in a
WAITING_ADD handoff. QUEUED one-time ADD conflicts; cancel it separately. No
in-flight command is cancelled, and uncertainty remains uncertainty.

### All reviewed devices

Open **Review all-device removal scope**, enter one IPv4 and optionally choose
**Allow the whole scope to wait for already RUNNING ADDs** before preparing.
Default is ready-only. The checkbox binds ordered mode and its distinct digest
into the immutable review; it cannot be changed at confirmation or inferred from
newly encountered work. Preparing another review is a new intention, not a retry.

The scope is the exact union of locally observed devices and enabled managed
targets, including managed-but-missing/disabled members. Multiple interfaces on
one device form one target. Observed-only targets receive cleanup, not adoption;
unrelated inventory and stopped-and-missing targets are excluded. Scope changes
must reject, never silently shrink, widen or rebase the reviewed set.

Ready-only rejects any RUNNING ADD. Ordered mode may reserve **all** original
targets behind the captured RUNNING ADDs: no ready member gets early cleanup.
After all settle, the shared leased worker materializes one full-scope REMOVE
delegation under the original deadline, or none. Disabled members, QUEUED
independent ADD or conflicting cleanup reject the entire request. The fleet
coordinator never loops over per-target commits to simulate atomicity.

## Receipts, execution and retry

An accepted receipt means local retirement/admission, not a completed device
operation. **Waiting for ADD settlement** means no opposite command overlaps.
Otherwise inspect the ordinary Queue. Existing Managed handoff/fleet sections
show subsequent delegation, verification, no-op, expiry and uncertain outcomes
separately; only verified agent results establish removal. A stopped policy
never restarts because cleanup fails, expires or is cancelled.

The plan expires within 900 seconds/the sensitive-action maximum from original
admission. Waiting/retry/worker promotion never extend it. Single-target admission
checks expiry again before commit, including after late queue/audit work; expiry
rolls the entire transaction back. All ordinary queue caps, actor rate limits,
FIFO, cutoff, persisted >=60s cooldown and console budgets remain unchanged.

Current Operator/Administrator, CSRF, exact typed IPv4 and the original
subject/cookie-bound frozen token are required. Unknown/lost/malformed replies
preserve token, scope, typed IP, ordered choice, canonical body and UUID for
explicit retry. Do not reparse/reclassify/rekey, automatically submit or prepare
replacement work. Gate disable only says the current attempt was not sent; it
does not disprove an earlier accepted plan. A validated receipt is historical,
not current policy/execution after later edits. Replay never retires a newer
generation, requeues a completed request or renews authority, even after pruning.

Reviews retain the shared combined-cache bounds: ten minutes/the shorter
sensitive-action age, five per subject, 256 globally; no eviction of active
reviews. Web restart/cookie change/expiry invalidates a review, not its possible
durable outcome. Inspect Managed/Queue/IP history before another review. Polling
does not replace frozen POST content or submit work. Optional status failure
does not negate a validated receipt. Both BFF configuration and API capability
must permit admission; status or DOM edits alone cannot enable it.

## Internal contracts

- `POST /api/v1/managed-removals/device`: strict current actor, one canonical
  device/IPv4, reviewed intent/generation/revision, original TTL/reason/digest and
  explicit canonical UUID `Idempotency-Key`.
- `POST /api/v1/managed-removals/fleet`: strict actor, exact nested frozen scope
  and digest, TTL/reason/action digest and explicit boolean ordered mode.
- BFF confirmation accepts only CSRF, opaque review token and typed IPv4. No
  browser actor, target list, revision, digest, mode or TTL is forwarded as authority.

The private APIs recheck schema/current roles, gate, sensitive-age cap, scopes,
generation, recovery suspension, conflicts/capacity and protected/system rules.
Missing/partial optional state is controlled failure, never implicit migration
or observed-only fallback. Policy/root/queue/reservations/audit commit together;
success logs follow commit. Exact scope-specific receipts are checked by the BFF,
including booleans/counts/revisions. Only newly accepted plans signal work; replay
is observational. No route accepts arbitrary action, CLI, credential or source.

## Validation, rollout and rollback

Synthetic ASGI/SQLite tests cover single/fleet admission, entire-scope atomicity,
ready versus explicit ordered mode, RUNNING/uncertain ADD settlement, deadline
binding, replay after retirement/re-enable, multiple actors, rate/capacity and
scope conflicts, strict schemas/roles/CSRF, late audit/expiry rollback, missing
schemas and frozen unknown-reply retry. Chromium uses localhost fixtures for
enabled/disabled/fleet-blocked states, ordered choice, mobile spacing and retained
token/input/focus without device requests. Networkless packaged smoke uses no
live volume, credential or device socket. This is not live cleanup acceptance.

No schema/protocol/dependency change. Keep actual gates off and optional lab
tables absent during rollout. Retain paired API/Web images and a checked private
SQLite-safe backup, stop the sole API executor and recreate only API/Web. Startup
can execute already admitted ordinary work; do not seed or submit a live cleanup
for deployment checks. Verify stable tables/schema/queue/policy, normal reads,
anonymous rejection and verified TLS authentication redirect. Preserve root
authority and uncertainty on rollback; do not restore enabled old policy or start
an executor unaware of reservations. Follow [Offline Recovery](recovery.md).
