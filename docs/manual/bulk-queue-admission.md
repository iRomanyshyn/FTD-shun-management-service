# Version-2 Bulk Queue Admission and Claim

Status: implemented internal backend hooks, now composed by a separately
[default-disabled scheduler controller](bulk-refill-controller.md); no Web or
environment/lab activation. This is not an operator enablement runbook. The normal lab still
uses its existing legacy registry, restored disabled ADD gates and suspended
experimental restoration.

## What this increment does

`BulkDispatch.admit` admits **1–16 exact candidates on one device** in a single
SQLite write transaction. It creates fixed system requests, shared queue jobs,
one-to-one links, immutable attempt identities and append-only audit together.
It neither calls SSH nor inserts thousands of executable jobs for a large import.
Backpressure is explicit: at most 1000 pending jobs, 2000 active requests and
1000000 retained bulk attempts. A failing final member leaves no partial portion.

Each `BulkCandidate` freezes device/IP, intent, generation, original standing
authorization and target revision. Admission also checks whole managed/protected
revisions, an explicit trusted ADD-device set, unsuspended policy, ordinary mutation
pause, enabled device, protection, observed absence and full original source-root
integrity. Discovery cannot silently rebase onto a newer grant.

Evidence is a complete typed `CompleteSnapshot` from trusted controller code,
never a Web claim. Its start must follow the policy grant and the profile's fresh-
read resume barrier, precede completion/request creation, remain at most 120 seconds
old and show every selected target absent. Earlier pending/failed/unknown attempts,
independent work or unattributed ADD evidence block admission. Retained successful
or cancelled history must precede the new read; a 300-second pair backoff and
three-attempt hourly churn bound remain. No missing evidence becomes success.
An unknown result anywhere on the same device blocks new bulk ADDs there, not
only another ADD of that IP; a fresh read cannot establish that an earlier RPC
has stopped. Separate automatic reconciliation remains unimplemented. Job creation
time must match its original request/attempt before claim or retention proceeds.

## Shared queue execution

The separately explicit [device lease profile](device-leases.md) now supplies
token-bound queues over the same jobs for future independent workers. The global
profile described here remains supported; neither profile switches automatically.

Only the existing leased `OperationQueue` claims jobs. The new internal
`bulk_dispatch_enabled=False` capability is independent of the old restoration
flag; neither is a Web parameter or deployed environment switch here. ADD execution
must also be explicitly permitted by the existing queue call. There is no second
executor, new command primitive, wire-format change or cooldown bypass.

Claim respects the original cutoff and rechecks current authority, fresh evidence,
lease, request and original source integrity. It refuses overlapping RUNNING work
on the same device. A late expiry rolls back the RUNNING transition and audit.
Typed VERIFIED/NOOP, failure, unknown, exact pre-write deferral and lease recovery
use the existing shared result journal. A still-valid exact pre-write deferral can
claim the same job again without changing its original deadline/evidence. A lost
response is UNVERIFIED, never a deferral or replay opportunity.

Protection/retirement cancels an unsent owned job. Whole-import cancellation uses
the [captured settlement contract](bulk-captured-cancellation.md): running work
settles without interruption; successful application stays maintained, while an
exact deferred first application is retired/cancelled before another claim.
Unknown outcomes and original evidence holds survive retention.

## Idempotency and identity

Attempt IDs derive deterministically from the original intent and snapshot UUID;
job IDs use a separate fixed derivation. Retrying the exact literal identities and
evidence returns historical state, even after retirement, expiry, restart or
terminal job pruning. It does not recreate jobs, renew 900-second delegations,
re-enable authority or turn terminal outcomes back into QUEUED.

Changed evidence under an existing identity conflicts. A mixed portion containing
previously admitted and new members conflicts: recover the admitted subset first,
then submit the remaining exact candidates separately. No coalescing into another
actor's request or import-provenance fabrication is allowed. Original human consent
stays on its standing root; system execution uses its own fixed subject and no
invented user roles.

## Explicit schema and rollback boundary

`BulkDispatch.initialize` accepts only an existing exact captured-cancellation
profile, ordinary pause, suspended policy and quiescent shared executor. It
validates original source roots, adds a nullable `dispatch_resume_after` field and
replaces only the three specified dispatch guards, preserving all rows/receipts.
The replacement journal guard permits initial QUEUED capture and monotonic shared
claim/result transitions. All changes roll back together on validation failure,
including when an outer caller catches the error and commits its transaction.

Initialization leaves suspension enabled and the barrier unset. A future explicit
resume requires pause/quiescence and a strictly advancing canonical UTC read
barrier; active reads cannot rewrite it. Admission requires a new read at/after
that barrier. There is **no activation CLI/HTTP procedure in this increment**.
Disposable test SQL models that future writer; it is not a lab runbook or approval.
New policy-only confirmation still requires suspended execution; concurrent
runtime standing admission is not yet implemented.

No startup, GET, constructor, queue initialization or legacy service upgrades or
repairs this optional schema. Exact older profiles retain their earlier suspended/
no-dispatch behavior; malformed/partial profiles fail closed. Old code rejects
the new profile even while it remains suspended.

Before non-disposable upgrade, settle RPCs/stop writers, obtain scoped environment
approval and retain a private checked SQLite-safe backup with compatible code and
configuration. Do not copy an active WAL file. This increment did not touch lab
data and needs no live restore. Never drop attempts/receipts or restore enabled
policy with an older writer to force a downgrade; retain compatible code or take
the database offline for a separately reviewed recovery.

## Validation and remaining work

```bash
python3 -m pytest -q tests/test_bulk_dispatch.py
```

These tests actually admit/claim shared jobs on disposable SQLite and pass typed
results, rather than seeding already RUNNING rows. They cover 16-member portions,
simultaneous duplicate admission, cutoff/default gates, device serialization,
protection/cancellation, exact deferral, lease loss, pruning/restart history,
strict literal/freshness/revision/capacity guards and late audit/expiry rollback.
No test reads `.env`, uses credentials, starts a runtime scheduler or reaches FTD.

Bounded discovery/refill is now integrated internally as described above. Still
pending: environment/Web activation, continuous writes and independent
device leases/parallel streams, automatic evidence-based uncertainty recovery,
version-aware cleanup/concurrent admission, legacy nonempty migration and Web
integration. Existing shared cooldown/global lease behavior remains unchanged;
this component alone does not deliver the full working-version scheduler or
100000-pair executable-load/hardware acceptance.
