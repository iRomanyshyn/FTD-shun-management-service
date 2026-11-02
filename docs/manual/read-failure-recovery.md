# Settled Read-Only Failure Recovery

## Supported scope

The original extension uses strict BEGIN `17`. Configured continuous runtimes
now use [tracked BEGIN `18`](session-completion-lookup.md), retaining the same
bound in-band failure contract and adding separate lost-read-receipt lookup.
They can now retry a failed initial, priority or final read when the agent proves
that the session attempted no mutation and has finished local cleanup. This
extends [opening recovery](opening-recovery.md), not unknown-write recovery.
No schema, HTTP action, setting, credential/trust or network change is needed.
Low-level/legacy clients still default to the old non-recoverable mode.

The conservative rule is **no ADD/REMOVE step attempted**, even if it returned
NOOP or deferral. A lost/failed mutation response or a failed later final read
after any mutation retains the fence. Original jobs, attempts, policy, receipts,
UNVERIFIED/ATTENTION and older held leases are never cleared or relabelled.

## Exact terminal record

On its existing private UID-checked SeqPacket connection, BEGIN `17` may return
four-byte `04 version failed_read sequence`, versions 1/2/3:

| Failed read | Opcode (hex) | Sequence |
| --- | --- | --- |
| Initial observation | `17` | `00` |
| Priority SNAPSHOT | `11` | Exact current 1–18 |
| Final END observation | `13` | Exact current 1–18 |

The record carries no CLI, interface, target, error text or authority. Normal
snapshot frames and successful END settlement stay unchanged. Opening status
`03 version 17 00` keeps its separate pre-command meaning. BEGIN `10`/`16` never
gains the new failure record or automatic read retry.

Only a valid read-step failure can prepare proof: no malformed request, idle IPC
timeout, peer-UID/device/gate/busy rejection or arbitrary failed response. The
agent checks zero mutation steps over the entire session, requires successful
bounded disconnect cleanup, and drops its local session resources. The handler
then returns through normal device/address guard release and worker-IDLE
completion; only that nonblocking completion sends the record. No future from
that handler can issue another command. An agent log alone is not a received
record or proof of remote TCP termination.

The agent keeps `agent.cycle.failed`, the original sanitized failure reason and
command/mutation counts. It does not report a successful cycle or observation.
Missing/lost proof, failed cleanup, a stopped/panicked worker or pressure on the
terminal send remains fail-closed. Existing operation/transfer/cycle deadlines
are not extended to obtain a retry receipt.

## Client and executor checks

The opted-in client validates the exact version/current read/sequence on its own
connection. It may consume proof before a manifest or between stream frames;
partial snapshots are discarded. It raises `AgentCycleReadFailed`, closes the
socket and never reconnects inside the cycle. This is not successful END and
does not set the cycle's normal `settled` success property.

The client marks any ADD/REMOVE attempt **before send**, including short/failed
sends. It rejects the new record in mutation responses, after any attempted
mutation, in an old mode, or after a complete final snapshot while waiting for
the ordinary END receipt. Truncated, oversized, misbound and missing records,
EOF and timeout cannot become this typed proof. No error-string inference.

The worker accepts the type only from its first opening call or its bound current
session's SNAPSHOT/END, with no earlier RPC failure. Release checks the exact live
owner/epoch/deadline, no RUNNING/UNVERIFIED/read-reconciled work or unknown bulk
attempts, and **no mutation claim in that epoch**, even already completed claims.
It atomically records `DEVICE_LEASE_READ_FAILED` and `DEVICE_LEASE_RELEASED` with
the original owner/epoch. Audit/check failure rolls back release. No startup/GET
repair or general-purpose HTTP release exists.

The continuous owner reports `agent_read_failed`, stale/error status and the
existing retry countdown. It retains demand and retries after 5/10/20/40/60s,
capped at 60s; clicks cannot bypass this backoff. Healthy devices continue.
The retry acquires a new fenced epoch and complete fresh initial evidence before
claims, rechecking current protection, retirement and cancellation. Earlier
complete reads remain valid observations; the failed/partial read is never
published or called a successful final refresh.

## Deployment and rollback

Use the [three-file desk-lab selection](fresh-development.md), preserving current
DB/queue/authority and both running image IDs. Preflight API and agent. Drain API
first, inspect retained state, then replace agent before API; retain the agent's
180-second stop grace. API restart may execute previously admitted work. Web and
its assets need no replacement.

Older BEGIN-17 agents simply cannot emit this proof, so the new API retains the
old hold behavior on read failure. Older APIs reject the new status and hold;
they cannot turn it into success. Prefer the matching tested pair. Code-only
rollback needs no DB restore: drain first, restore compatible images and keep
new audit/evidence. Never downgrade/reset a held operation to make it runnable.

## Validation and limits

```bash
python3 -m pytest -q tests/test_read_failure_recovery.py tests/test_opening_recovery.py tests/test_unsubmitted_recovery.py tests/test_agent_settlement.py
cargo test --locked --manifest-path agent/Cargo.toml
cargo clippy --locked --all-targets --manifest-path agent/Cargo.toml -- -D warnings
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo build --release --locked --manifest-path agent/Cargo.toml
```

Shared vectors cover all versions/read bindings. Actual local SeqPacket fixtures
cover partial streams, wrong/lost/truncated/late records, no-op/deferred mutations,
short/failed sends and closed sockets. Rust tests cover cleanup/guard/worker
ordering, read error/timeout and no mutation, failed cleanup and prior mutations.
Disposable controller tests cover independent healthy devices, fresh-epoch retry,
backoff/demand, current cancellation/protection, audit rollback, old fences,
completed claims and cancelled callers. They never access FTD or real secrets.

In-band proof alone does not recover hard API/agent crashes, cleanup failure,
lost terminal records, arbitrary later exceptions, old held epochs or unknown
ADD/REMOVE. The later bounded lookup recovers lost read-only completion only
while its exact process-local evidence and live epoch survive. Other cases
require the separate evidence-backed reconciliation contract.
Record live healthy transport acceptance separately; it is not induced failure,
multiple-device/load or production acceptance.
