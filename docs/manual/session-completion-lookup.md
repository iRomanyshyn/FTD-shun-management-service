# Bound Session Completion Lookup

## What this recovers

If a tracked read-only session finishes but its terminal response is lost, the
API can ask the still-running agent about that exact session. This permits a new
read without blindly resending the old BEGIN or any mutation. It also covers a
locally aborted read after processing failure, if the agent completed cleanup.

It does **not** resolve unknown ADD/REMOVE, old held epochs, API/agent hard crashes,
failed cleanup, active sessions or missing/evicted evidence. Those retain holds.
No job becomes VERIFIED, policy changes or observation becomes fresh from lookup.

## Binding and fixed protocol

Configured continuous runtimes now select tracked BEGIN `18`, not `17`, retaining
strict large snapshots and their selected v2/v3 ADD scope. The controller derives
the nonzero 16-byte session ID from its current canonical UUIDv4 device-lease
owner. A browser cannot select it. Low-level/legacy clients default unchanged.

All integers are unsigned big-endian; opcodes below are hexadecimal. Peer UID,
inventory/device/profile/gates, pinned SSH and agent-only credentials remain.

| Frame | Exact bytes | Size |
| --- | --- | --- |
| Tracked begin | `18 version device:u16 session_id:16` | 20 |
| Local lookup | `19 version device:u16 session_id:16` | 20 |
| Lookup result | `status version 19 device:u16 session_id:16` | 21 |

Versions 1/2/3 keep existing snapshots, ADD/REMOVE/SNAPSHOT/END and budgets. Initial
snapshot and successful terminal settlement bind to `18`; pre-command opening
status `03` and failed-read status `04` use `18` only for their initial binding.
Legacy BEGIN `10`/`16`/`17` stay unchanged; never negotiate/fall back after failure.

Lookup status `00` means retained completed read-only, `02` active, `01` unknown/
unsafe. Validate the entire version/opcode/device/session echo, exact length,
truncation and status. Only `00` can supply evidence. Query is local memory only:
no SSH, FTD guard, CLI, cancellation, renewal, authority or work scheduling. At
capacity 1 the existing bounded kernel backlog may wait for the active handler;
lookup does not interrupt it or steal its worker.

## Agent journal and completion ordering

The agent reserves the exact key before the tracked handler can open SSH.
Retained duplicates reject without executing. The bounded process-local journal
stores at most 4096 keys/states; it never stores credentials, output, mutation
receipts or desired policy. At capacity it evicts only the oldest **completed**
key; active entries are never evicted. All-active capacity refuses new admission.
This is bounded evidence, not durable idempotency or a replay guarantee after
eviction/restart. A missing key always returns unknown; never resend its BEGIN.

```text
read/END → successful cleanup → handler/resource/guard return
         → worker IDLE → journal complete → terminal send
```

Preparing read-only evidence does not publish completion. Successful bounded
disconnect and zero ADD/REMOVE steps over the entire session are required; even
NOOP/deferred mutations disqualify it. A pre-command opening failure may prepare
the same no-write evidence. Normal IPC closure can finish read-only without
inventing a valid observation. Only the original completion postamble publishes
after the handler and guard end and the worker becomes idle, before the terminal
send. A closed peer may lose that send while lookup still finds real completion.
Panics/poisoned state, failed cleanup or any mutation never yield safe proof.
The journal records local completion, not remote TCP termination or write success.

## API release and retry

`UnixAgentClient(..., settled_cycles=True, recoverable_cycles=True,
tracked_cycles=True)` requires `open_tracked_cycle(device_id, lease_owner)`;
ordinary `open_cycle` cannot silently generate an unbound ID. The configured
factory selects this mode and rechecks its capabilities before startup. Optional
low-level clients and test adapters must select it deliberately.

Only the worker's own submitted tracked session with an RPC/local error or missing
strict settlement may trigger one separate completion lookup. It uses the same
durable lease owner and original device/version. Lookup has one absolute deadline
of at most five seconds; no new operation budget, reconnect loop, guessed delay
or blind BEGIN replay. Active/unknown/busy/error/malformed/timeout proof retains
the original fence. A cancelled caller cannot turn a late response into release.

Exact live owner/epoch/deadline, absence of RUNNING/uncertain work and **no mutation
claim in that epoch**, including completed claims, are checked transactionally.
Success atomically audits `DEVICE_LEASE_READ_RECEIPT_RECOVERED` and ordinary
release with real system identity and owner/epoch. Audit failure rolls back.
Old ATTENTION/LEASED, policy, results, attempts and uncertainty stay intact.

Status keeps the original error/stale data with category
`agent_read_receipt_recovered` and the existing 5/10/20/40/60s retry countdown.
Pending manual/policy demand survives. A retry uses a new lease UUID/epoch and
fresh complete initial read, rechecking current protection/cancellation/authority.
Healthy devices retain independent progress; a held lease still counts against
its sealed capacity. Lookup never publishes a snapshot or grants an ADD.

## Deployment, rollback and validation

No DB migration, new environment flag, network, credential, authentication or Web
change. Use the [three-file managed lab selection](fresh-development.md), retain
both running images and preflight without a second executor. Drain API, inspect
retained scope, stop agent with its 180s grace, deploy new agent **before** API.
The new configured API needs BEGIN `18`; an old agent rejects it and lookup, and
the API holds without fallback. Code-only rollback restores a compatible pair
after drain, never an old DB/authority snapshot or cleared fence.

```bash
python3 -m pytest -q tests/test_session_completion_lookup.py tests/test_configured_runtime.py tests/test_configured_managed.py tests/test_read_failure_recovery.py
cargo test --locked --manifest-path agent/Cargo.toml
cargo clippy --locked --all-targets --manifest-path agent/Cargo.toml -- -D warnings
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo build --release --locked --manifest-path agent/Cargo.toml
```

Shared vectors cover all versions/bindings/statuses. Local socket fixtures cover
lost initial/END responses, local processing abort, malformed/wrong/truncated
proof and new-session retry. Rust tests cover prepare-versus-complete, actual
guard/postamble ordering with closed peer, duplicate refusal, bounded eviction,
active preservation, restart-as-unknown and no-SSH lookup even with a held guard.
Disposable controller tests cover healthy independence, demand/backoff, completed
claim refusal, old/expired fences and audit rollback. No real secrets or FTD in
these tests. Record healthy/lost-receipt read-only lab acceptance separately.
