# Version-2 Ordered Promotion

Status: explicitly migrated, default-disabled internal coordination. **Not migrated,
enabled or deployed in the lab.** No ordered Web/API confirmation, environment
selector, unknown-outcome recovery or production acceptance is supplied. Read
[Ordered Reservations](bulk-ordered-reservations.md) and
[Local Cycle Settlement](cycle-settlement.md) first.

## Composition and bounded work

`BulkOrderedPromoter(store, base_queue).advance(enabled=False, limit=8)` coordinates
local admission, never device commands. False returns without accessing storage;
enablement must be a literal boolean. True requires the existing exact optional
promotion profile. Scan at most `limit + 10` roots (at most 18), commit at most
`limit` decisions (1..8). Bounded lookahead lets healthy scopes progress while an
earlier scope waits for a live session. Shared maintenance still owns expiry.

`ContinuousDispatcher(..., ordered_promotion_enabled=False)` is the separate
literal factory capability. When explicitly true, startup checks complete existing
storage read-only before maintenance/device work; the owning loop coordinates
promotions before choosing device work. Default composition never promotes.
No environment/CLI/HTTP input selects it, no startup initializes optional storage,
and no second command executor, task queue or wire operation is introduced.

## Whole-scope barrier

Revalidate the complete frozen one-IP device/fleet scope under one write lock:
original ADD jobs/requests/claim evidence, intent/generation/authorization and
retired revision, inventory identity/enabled state, protection revision, current
fences and independent pending/unknown work. Never expand/shrink the fleet or
rebase original authority on unrelated policy changes. Existing policy stays retired.

| Evidence | Result |
| --- | --- |
| RUNNING ADD or completed ADD with its original live unreleased lease | Wait; no mutation/admission. |
| VERIFIED/NOOP with captured epoch released or monotonically superseded | Eligible only if every other scope/fence check passes. |
| Exact pre-write deferral, original matching typed audit, unsent metadata and settled session | Cancel that captured unsent ADD atomically with whole-scope transfer. |
| Failed/unknown/missing/inconsistent result, expired/attention fence, changed scope/protection/authority or independent pending work | Whole-scope ATTENTION, no REMOVE delegation. |
| Pause, original cancellation or expired cleanup authority | No promotion, extension or replay. |

VERIFIED/NOOP alone is not session completion. A same-epoch leased executor must
release after strict local settlement. A later epoch must follow the existing
monotonic release/claim protocol and still have a safe current fence. Promotion
storage refuses parallel-round mode without strict settlement; continuous mode
already requires it. Failed final read/END/settlement retains its fence. A fresh
observation or timeout cannot resolve an unknown original ADD.

Deferral requires exactly one original `SHUN_OPERATION_DEFERRED` receipt bound to
request/job/device/IP, system actor/source, literal `write_sent=false`, ADD action,
original owner/integer epoch and canonical nonfuture UTC time. Duplicates, missing
proof, boolean epochs, sent metadata or guessed absence cannot authorize cleanup.
No independent or uncertain ADD is cancelled/replayed.

## Atomic shared-queue transfer

One transaction inserts an internal ADMITTING ticket, submits **one whole-scope**
manual REMOVE request under the original reservation UUID/actor, and saves an
immutable ADMITTED decision with complete sorted device/job references. Ticket,
unsent cancellation, jobs/links, decision and real-actor audit commit together.
No single-target admission loop or partial fleet commit. Expected conflicts retain
ATTENTION with no partial work; unexpected storage/audit failure rolls back the
sweep. Accepted logs are emitted only after commit. Concurrent calls serialize;
subsequent calls see the original committed decision rather than duplicate work.

The queue requires a separate literal default-false `bulk_ordered_removal_enabled`
capability, fixed `managed_v2_ordered_removal` scope and exact current private
ticket/actor/targets/deadline. It cannot be combined with the ready capability.
A scope label, old UUID or true flag without a ticket is not permission. Existing
isolation, device, fence, claim and typed verification checks remain authoritative.

Discount only this root's already reserved target/request slots. Its actor is not
charged twice: the operation request replaces the reservation's original accounting
position. Persist original requested-at and exact millisecond expires-at unchanged;
rounding a remaining-seconds argument never renews TTL. Final deadline, clock and
fence checks precede commit. Admission is not verified removal, and separate FTD
outcomes are not a distributed transaction.

Claim checks complete ADMITTED scope and request/job bindings before any ordered
command. ADMITTING is transaction-internal only. A persisted incomplete ticket
refuses startup/promotion, local status/expiry and claims, never automatic resume.
Do not delete markers or reconstruct evidence to force progress.

## Status, revocation and retention

The immutable original reservation receipt remains historical WAITING_ADD.
`status(key)` separately reports current ADMITTED/ATTENTION, original expiry,
predecessor outcomes, decision and admission/reservation flags. `attention` remains
true after waiting cancellation/expiry. ADMITTED means delegation occurred, not
verified device removal; ordinary queue jobs show actual outcomes.

Owner/Admin cancellation and shared expiry may revoke undecided/attention waiting
without changing ADD results or resuming policy. They cannot reinterpret ADMITTED
work as waiting/cancelled/expired: ordinary queue controls govern those jobs.
Original-key replay returns the old receipt only. No attention rearm or new UUID
is generated. Queue retention preserves delegated REMOVE jobs/requests as well as
captured ADD evidence. Audit retention also holds original deferral receipts.
Missing/malformed retained evidence refuses pruning, never manufactures success.
No automatic decision/hold eviction is provided.

## Explicit migration, backup and rollback

`initialize(enabled=True, connection=None)` adds only
`managed_bulk_ordered_promotions` and immutable/monotonic triggers. Exact schema
recognition distinguishes this profile. Require existing ordered storage,
ordinary pause, desired suspension and settled quiescence, **including no active
reservations**. Preserve all old terminal roots, receipts, evidence and suspension.
Late DDL failure rolls back even if a caller catches it and commits; repeat exact
initialization is idempotent. Do not cancel/expire/renew authority merely to force
upgrade or seed the lab. There is no migration CLI or live activation here.

Before a future separately approved rollout, drain old writers/sessions, inspect
unresolved work and retain checked SQLite-safe backups plus matching images and
configuration. Validate exact profile and original receipts before activation.
Older images do not understand these decisions/holds and must not write/prune
the database. Disabling promotion prevents new transfers, not already admitted
queue execution; pause stops mutation claims. Never drop decisions/fences or
restore enabled pre-retirement policy to force downgrade. A checked pre-upgrade
backup is safe only before post-backup authority/work; preserve current evidence
and use compatible repair otherwise. No lab migration/downgrade was performed.

## Validation and next

```bash
python3 -m pytest -q tests/test_bulk_ordered_promotion.py tests/test_bulk_ordered_waits.py tests/test_continuous_dispatch.py tests/test_parallel_synchronizer.py tests/test_bulk_removals.py tests/test_store.py
```

Use disposable SQLite and typed fake sessions only. Cover shared REMOVE execution
after settlement, multi-predecessor barriers, deferral proof, healthy-root fairness,
original TTL/accounting, once-only concurrency, late rollback, partial-ticket claim
refusal, terminal replay/retention, profile migration/compatibility and default-off
composition. Then run full pytest, compileall, Ruff and diff/local-link checks.

Next: frozen ordered Web/API consent/status with independent default-off
capabilities, configured runtime/inventory, reviewed nonempty migration and scoped
transport/multi-device/load/recovery acceptance. Fake sessions and prior consumed
one-address lab approvals are not permission or production validation.
