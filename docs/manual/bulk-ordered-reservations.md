# Version-2 Ordered Reservations

Status: default-disabled internal reservation/revocation foundation. A separate
explicit optional schema migration is implemented, **not applied to the lab**.
Separate default-off [private ordered API](ordered-removal-api.md) routes now
expose reservation/status/revocation. Frozen Web consent, a configured runtime
selector and live activation remain unavailable.
A separately migrated/default-off [ordered promoter](bulk-ordered-promotion.md)
now transfers eligible whole scopes into existing shared workers; this reservation
coordinator still creates no REMOVE jobs by itself.
Existing [ready-only confirmation](ready-removal-confirmation.md)
does not fall back to this mode. Read the
[preflight contract](bulk-ordered-preflight.md) first.

## Frozen action and atomic reservation

`canonical_ordered_removal(scope, predecessors, ttl_seconds=900, reason='')` defines
a new `STOP_AND_REMOVE_ORDERED` action and domain-separated SHA-256 digest. It
binds the exact one-IP single/fleet union and original managed/protection/target
revisions, original authority and one or more sorted RUNNING-ADD predecessor
descriptions. Predecessors include request/job/snapshot/claim IDs, original
deadline, executor owner/epoch/deadline and evidence digest. No arbitrary command,
partial fleet, queued ADD takeover or empty/ready-only ordered action is accepted.
The separate read-only preflight/scope/ready digests are not confirmation digests.
Cleanup TTL is a literal 1..900 seconds; reason is at most 500 plain-text characters.

`BulkOrderedWaits(store, base_queue).reserve(...)` and the caller-owned
`apply_reserve(...)` require an explicit literal `enabled=True` from trusted
composition. It is not an environment/HTTP switch. The coordinator requires the
same existing database and the base shared `OperationQueue`, never a device
executor. No storage is created by admission or reads. Migration is separate.

Under one write transaction/savepoint, admission:

1. Checks real Operator/Administrator identity, canonical original UUID, exact
   action digest and existing exact optional profile. Original-key replay returns
   its immutable actor/action receipt before current-state rechecks, not new work.
2. Reinspects the entire scope and all exact original RUNNING predecessors in the
   same transaction. Scope, authority, audit/fence or readiness changes require
   a new review; there is no silent conversion to ready-only cleanup. Ordinary
   mutations must be unpaused and all targets eligible/enabled/in scope.
3. Checks the shared pending-target, active-request, actor-rate and retained
   authority/root budgets. Rejects an overlapping reservation without coalescing.
4. Permanently retires every enabled managed target in the scope, preserving its
   intent/generation/original grant and original ADD outcomes. Unmanaged observed
   members stay cleanup-only and are not adopted.
5. Saves one immutable original action/receipt and one whole-scope durable root,
   all target members and exact predecessor/claim captures. Appends real-actor
   retirement/reservation audit and bumps shared queue metadata.
6. Rechecks retained bindings, original ADD lease/deadline and the new cleanup
   deadline before returning. Clock reversal, late expiry/audit failure or any
   conflict rolls back **all** policy, reservations, receipts and audit, even when
   an outer caller catches the exception and commits its own transaction.

No REMOVE operation request/job is created. The receipt says `state=WAITING_ADD`,
`cleanup_reserved=true`, `device_work_admitted=false`, `verified_removal=false`.
It reports original cleanup request/deadline, target/predecessor/retirement counts
and resulting managed revision. It is neither verified removal nor a worker
activation. No background task, agent call or post-commit wake is introduced.

## Budgets and conflicts

Each waiting root reserves its **entire** target count in the existing
1000-pending-target budget, including ready devices. Original RUNNING ADD jobs
still occupy their own slots. Each waiting root uses one of 2000 active request
slots. Every root, including a subsequently cancelled/expired one, counts toward
the existing ten submissions per minute per actor; cancellation cannot reset rate
limits. At most 10000 ordered roots and their at-most-ten members each are retained.
Each root also occupies one of the existing 400000 immutable authority slots.
At least one predecessor must belong to currently enabled maintenance, so every
new reservation actually retires policy and may use the existing retirement
reserve. Nothing is silently evicted or partially accepted at capacity.

Held pairs reject independent manual ADD/REMOVE and ready-only cleanup, even for
an already ready target. New standing grants remain quiescence-guarded until the
whole reservation is revoked/expired. Automatic protected-policy removal keeps
its separate system authority; it is not blocked by the manual reservation guard.
No policy retirement or cancellation can interrupt a RUNNING ADD. Later automatic
bulk discovery sees retired policy and cannot rearm it. Disabling/deleting
protection does not re-enable the old managed generation.

## Status, cancellation and expiry

The local `status(key)` method reads a readonly SQLite snapshot and reports the
durable root phase, original expiry and individual predecessor job outcomes.
Missing retained evidence is honestly missing/unavailable, not success. It never
initializes storage, refreshes a device or promotes work. `WAITING_ADD` remains
waiting unless the separately migrated/default-off promoter decides the whole
scope. ADMITTED/ATTENTION is separate from the immutable original reservation
receipt; inspect individual ADD/REMOVE outcomes, not phase alone, for verification.

`cancel(key, subject, display_name, roles)` permits only the original owner or
Administrator, with current Operator/Administrator authority. It is a local
revocation, allowed while ordinary mutations are paused. A waiting root becomes
CANCELLED atomically with actual-actor audit; terminal retries are side-effect-free.
Neither the original ADD nor its request is cancelled or rewritten. Policy stays
retired, and the original reservation receipt remains historical/immutable.

The existing shared `OperationQueue.expire_requests()` maintenance transaction
also expires up to 100 elapsed ordered waits per call, with system audit. There
is no new scheduler or executor. TTL remains the original requested-at plus
literal lifetime, not time-since-worker/retry. Expiry releases reservation slots
but never restores maintenance, resolves uncertainty or sends cleanup. Ordinary
queue expiry/result behavior remains independent. Automatic expiry runs only if
the existing maintenance lifecycle is running; otherwise waits remain conservatively
reserved until it runs or they are explicitly cancelled.

## Original evidence and retention

The optional profile contains `managed_bulk_ordered_roots` and
`managed_bulk_ordered_members`, one pair index and immutable/monotonic triggers.
Recognition checks exact SQL objects, bounded descriptors, complete sorted
membership, original action/receipt/deadline and cardinality. Roots can only move
from WAITING_ADD to CANCELLED or EXPIRED. No ADMITTING/ADMITTED transition exists.
Members, original root identity/deadline and all receipts cannot be rewritten or
deleted/rearmed. The separate additive promotion ledger preserves these original
constraints and records decisions without rewriting historical authority.

Both queue and Store audit retention validate captured ADD jobs, their original
linked requests, immutable attempt identities and original claim audit before
**any** deletion. Captured jobs/requests/claims are held even for revoked/expired
roots. This intentionally conservative bounded evidence hold cannot be released
by age, observed absence, cancellation or abandonment. Missing or malformed held
evidence refuses pruning without reconstructing it or fabricating success.
Legitimate VERIFIED/NOOP/FAILED/UNVERIFIED results, exact pre-write deferral and
subsequent unsent cancellation may update the ordinary job/attempt state while
its original captured identity remains immutable. Expiry/revocation never turns
an unknown ADD into a safe retry. No automatic ordered-ledger pruning is provided.

## Migration, backup and rollback

`initialize(enabled=True, connection=None)` is an internal developer composition
primitive, not a migration CLI or permission to run it on the lab. It upgrades
only an existing exact fenced v2 profile, with ordinary mutation pause, desired
policy suspended, no unsettled global/device lease/attention or pending/unknown
work. It preserves existing schemas/receipts and suspensions. DDL participates in
the caller transaction/savepoint; late failure rolls back the whole additive
upgrade. Exact already-initialized calls are observational/idempotent. Legacy,
partial or unexpected optional objects are never converted/repaired.

Before a future **separately approved** real migration, stop/drain old writers and
sessions, settle known work, inspect original uncertainty and retain a checked
SQLite-safe backup (backup API with integrity/foreign-key checks), matching images
and configuration. Apply via reviewed offline orchestration, then validate exact
profile, original receipts and retained evidence. No such orchestration, scoped
activation or data conversion is supplied by this packet; tests initialize only
disposable synthetic profiles.

Do not run older API/retention writers on the upgraded database: older profile
readers refuse its objects, and older audit pruning does not know these evidence
holds. Disabling admission does not cancel existing reservations or resume retired
policy. A checked pre-migration backup is a possible rollback only before any
post-backup authority/retirement/work; do not restore enabled pre-retirement policy
or drop ledger/fence tables to force a downgrade after admission. Preserve the
current database/evidence and use matching compatible images for repair. No
general live downgrade, unresolved-outcome release or lab migration is authorized.

## Validation and remaining work

```bash
python3 -m pytest -q tests/test_bulk_ordered_waits.py tests/test_bulk_ordered_removals.py tests/test_bulk_removals.py tests/test_bulk_dispatch.py tests/test_continuous_maintenance.py tests/test_store.py
```

All fixtures are disposable SQLite and typed fake outcomes; no SSH, secrets or
real inventory is involved. Cover original-key races, two parallel predecessors,
whole-scope late rollback, strict digests/capabilities, profile migration/refusal,
retention across every outcome/revocation, owner/Admin access and unchanged
ready-only/protected workflows. Then run the full Python suite, compileall, Ruff
and diff/link checks.

The separate promotion/attention protocol now provides whole-scope original-TTL/
capacity transfer and exact-deferral/settlement checks. Next is frozen ordered
Web/API consent/status. Do not simulate fleet
promotion by looping over single-device admission or release unknown evidence
from a fresh read alone. Transport, migration, load/multi-device/recovery and
scoped lab acceptance remain unfulfilled.
