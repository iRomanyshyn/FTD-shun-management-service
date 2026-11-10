# Local Result Storage Retry

The grouped import worker can briefly retry **local SQLite persistence**, not
FTD commands. This reduces unnecessary held imports when another local writer
temporarily owns SQLite during ACK or per-target ADD-result storage.

## What is repeated

Only a DB-only ACK or terminal ADD-result callback, with the same response or
diagnostic. Each attempt opens a fresh write transaction and repeats all original
executor/profile/job/request/attempt checks. Pending group memory changes only
after commit. Legacy/global queue paths and other storage operations keep their
existing behavior; the coordinator's separate scheduling retry is unchanged.

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

`queue.result_storage.retry` includes a fixed phase (`acknowledgement` or
`addition_result`), attempt, numeric SQLite code and short backoff.
`queue.result_storage.recovered` means only local persistence recovered; an ACK
still is not verified creation. Neither event is permission to replay a command.
No device output, credentials or arbitrary command text is logged here.

No environment setting, schema initialization or data conversion is needed. An
API-only update must retain all three lab overlays and use API-first drain.
The compatible rollback image must support the DB's current optional recovery
profiles. Never restore stale authority or remove receipts to fit an old image.

This cannot prevent every storage stall, crash or unknown mutation. Follow
[Execution Recovery](execution-recovery.md) for scheduler failures and
[Extended Session Recovery](extended-session-recovery.md) for a compatible,
explicitly reviewed held-epoch decision. Do not reuse an earlier recovery key.
