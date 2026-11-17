# Local Result Storage Retry

## Core SQLite connection policy

Source v0.18.2 makes the ordinary Store lock wait explicit at five seconds
(`busy_timeout=5000`, installed by Python's `connect(timeout=5)`). This preserves
the previous wait; it is not a larger timeout or a hard transaction deadline.
Each connection enables foreign keys and `synchronous=FULL`. Existing WAL mode is
queried, with a mode change requested only when needed; a refused WAL transition
is an error. No process-wide cached assumption about the database file is used.
Connections close even if configuration fails; exceptions and interruptions roll
back the owning transaction without repeating its body.

The configured continuous runtime shares this policy, but still opens existing
files only (`mode=rw`), without creating a parent directory or replacement DB.
That check happens on every open, including after an earlier successful read.

The result writer below explicitly uses FULL too, retaining its separate two-second
wait and existing three-attempt/seven-second retry bounds. FULL is deliberate:
SQLite documents that NORMAL in WAL can lose recently committed transactions after
power loss. Losing an acknowledged claim/result would undermine execution evidence.
See [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous).
This setting relies on the underlying filesystem/storage honoring synchronization;
it is not a new power-failure acceptance result.

Failed typed BUSY/LOCKED operations on the ordinary Store emit a JSON
`store.sqlite_contention` diagnostic after rollback. Fields are `phase` (`open`,
`configure`, `transaction` or `commit`), numeric `sqlite_code` (including extended
codes) and `elapsed_seconds`. Elapsed time covers the connection's whole scope,
not exclusively time waiting for a lock. No SQL, database path, address list or
exception message is logged. The original exception propagates to its existing
caller; this event never authorizes a retry, unknown-write replay or success.
Result persistence and scheduler retry logs retain their own distinct meanings.

Inspect API logs with `docker compose --env-file .env -f deploy/compose.yml logs
--since=10m api` (include your usual overlays). Count these diagnostics alongside
`queue.result_storage.retry`/`dispatcher.storage.retry`; a lack of failed-operation
events does not measure successful lock waiting or prove contention is eliminated.
WAL allows readers alongside a writer but still serializes writes. Connection
pooling, writer scheduling and shorter large transactions remain separate work;
this patch is not a 100k-import throughput claim or a general BUSY fix.

A disposable 100,000-observation sample on 2026-11-17 ran four concurrent page
readers (40 successful 100-row pages) and one writer (100 committed transactions)
through ExistingRuntimeStore. It reported zero SQLite errors and integrity OK;
25.152 s includes fixture creation and competing host test load. No old/new speed
comparison, large-authority import transaction or device call is represented.

Regression checks use real independent WAL connections: snapshot consistency
while a writer commits, a waiting writer executing once, exhausted waits,
BUSY_SNAPSHOT without replay, interrupted rollback, configuration-failure cleanup
and the result writer's independent FULL/two-second settings. They do not send FTD
commands. No schema, wire, execution profile or environment setting changes.

## Scope of the existing result retry

The grouped import worker can briefly retry **local SQLite persistence**, not
FTD commands. This reduces unnecessary held imports when another local writer
temporarily owns SQLite during ACK or per-target ADD-result storage. Source0.11.1
also covers the deferred worker's pre-END checkpoint and settled pending handoff.

## What is repeated

Only a DB-only ACK, terminal ADD-result, pending-checkpoint or pending-handoff
callback, with the same response or diagnostic. Each attempt opens a fresh write transaction and repeats all original
executor/profile/job/request/attempt checks. Pending group memory changes only
after commit. Legacy/global queue paths and other storage operations keep their
existing behavior; the coordinator's separate scheduling retry is unchanged.

For deferred v7, a checkpoint retry happens before the one END_PENDING request.
A handoff retry uses the actual already-settled terminal receipt; it does not
send END_PENDING, ADD or another agent lookup. The whole original group, evidence
and lease release commit together on the callback's owning transaction. Only
after successful commit does queue memory record the handoff and clear pending
members. Every retry rechecks the original live lease/owner, exact ACK scope and
existing profile/evidence checks. Expiry or changed evidence refuses normally.

Bounds: three attempts, at most two seconds of SQLite lock waiting per attempt,
50 ms then 150 ms backoff, and no new retry starting after a seven-second local
window. This is not a hard cancellation deadline for a running SQL callback.
Retries occupy the owning SQL thread, not the event loop. Original SSH/session
and lease deadlines remain unchanged; a late/foreign lease refuses normally.

## What does not qualify

- Missing/incorrect numeric BUSY code, `SQLITE_LOCKED`, I/O, integrity, profile,
  owner or deadline errors.
- Lost/malformed agent ACK, lost verification or terminal session proof.
- A commit error after SQLite already ended its transaction, or a failed rollback.
- An exhausted retry window/count, old held epoch or previous unknown job.

After BEGIN, only an original still-open transaction with a successful explicit
rollback is retryable. No committed event is silently replayed. A successful
earlier target remains VERIFIED if a later target cannot settle; remaining work
retains the normal unknown/held handling. Unknown diagnostics can be persisted
locally without becoming proof of remote success.

## Logs and operation

`queue.result_storage.retry` includes a fixed phase (`acknowledgement`,
`addition_result`, `pending_checkpoint` or `pending_handoff`), attempt, numeric
SQLite code and short backoff.
`queue.result_storage.recovered` means only local persistence recovered; an ACK
still is not verified creation. Neither event is permission to replay a command.
Recovered pending handoff still means **Awaiting confirmation**, not verified
creation; a later causal full read must confirm presence or absence.
No device output, credentials or arbitrary command text is logged here.

No environment setting, schema initialization or data conversion is needed. An
API-only update must retain all three lab overlays and use API-first drain.
The compatible rollback image must support the DB's current optional recovery
profiles. Never restore stale authority or remove receipts to fit an old image.

This cannot prevent every storage stall, crash or unknown mutation. Follow
[Execution Recovery](execution-recovery.md) for scheduler failures and
[Extended Session Recovery](extended-session-recovery.md) for a compatible,
explicitly reviewed held-epoch decision. Do not reuse an earlier recovery key.
