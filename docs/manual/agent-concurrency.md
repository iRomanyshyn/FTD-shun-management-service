# Bounded Agent Connection Concurrency

Status: implemented opt-in transport prerequisite, **not end-to-end parallel
scheduling**. The deployed lab was not changed. The current API still uses one
global executor lease/cooldown and serial device collection. A separately explicit
[fenced API lease profile](device-leases.md) now supplies coordination primitives;
the internal [parallel runner](parallel-rounds.md) and
[continuous dispatcher](continuous-dispatch.md) now compose it in synthetic tests.
The opt-in [local settlement extension](cycle-settlement.md) now closes normal
completion ordering. Application activation and live acceptance remain pending.

## Configuration and limits

`FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES=1` preserves the serial inline dispatcher.
Accepted values are canonical decimal integers **1–10**, with no whitespace,
signs or leading zeros. Missing means 1; invalid values fail configuration before
serving requests. The agent's `--check-config` output includes
`max_concurrent_devices` and still exits without binding a socket or contacting
FTD. It validates credentials exactly as before; concurrency is not a credential
fallback or an ADD gate.

Values above 1 create a fixed number of connection workers. Four remains the
working-version planning target after coordinated validation; this increment
does not change the deployed default to four or validate FTD hardware capacity.
The existing Compose `env_file` already supplies agent environment values: no
Compose change, secret mount or additional listener was added.

At most the configured number of connections are assigned/running. An idle worker
gets one connection; **nothing queues behind an active handler**. Saturation
returns the existing generic rejection and closes the connection. The listener's
fixed kernel backlog remains 16; no unbounded per-client thread or application
backlog exists. A worker that panics is stopped, not automatically replaced.
If all workers stop, the listener fails rather than silently accepting an inert
queue. Resource use, simultaneous SSH sessions and snapshot buffers scale with
the chosen worker limit; validate host/device capacity before any opt-in.

## Device serialization

After the semantic handler/cleanup and device guard finish, a typed bounded local
postamble emits a strict settlement record only after marking its slot idle. It
retains only the completed FD/record and uses one nonblocking send/close: no SSH,
CLI or waiting for a slow peer. A next assignment may wait only for that postamble,
not behind an active handler. Completion panic stops the worker too.

All semantic wire requests acquire an inventory-owned nonblocking device guard,
including legacy one-shot requests, large reads and cycle versions 1/2/3. The
guard spans the handler's SSH work, verification and cycle final-read/disconnect
cleanup. Other devices can use other workers concurrently. A second connection
for the same device is rejected immediately without another SSH session.

IDs sharing a management IPv4 address share the same guard. Do not configure
different addresses for the same physical FTD as independent devices: the agent
cannot infer an identity alias from unrelated addresses. Stable inventory IDs,
host-key pinning and explicit credentials still define the operator's trust setup.
Unknown/disabled devices and malformed first packets fail before SSH.

A panic while a device guard is held poisons that guard for the process lifetime;
later requests for it fail closed while other healthy workers/devices can continue.
Restart replaces process-local guards, **not** durable API evidence or authority.
Never restart to reinterpret an unknown write as safe or automatically replay it.
Preserve original jobs, policy/latches and the separate reviewed recovery contract.
The guard serializes local handlers; a timed-out/dropped SSH future or disconnect
is not proof that a previously sent remote command can no longer execute. Caller
uncertainty barriers and future quiescence-backed reconciliation remain necessary.

## Protocol, timeouts and errors

SO_PEERCRED authorization occurs before assigning a worker. Legacy fixed binary
packets, exact length/version/range checks, feature/profile gates and typed
verification results are preserved; strict settlement is a separate explicit
begin/receipt extension. Workers enter the existing live Tokio runtime
context before constructing SSH/timer futures; there is no independent runtime or
reactor per connection.

The initial ten-second IPC deadline starts at accept, including worker assignment
delay. An already expired assignment is rejected without reading/dispatching its
packet. Every cycle retains its command/step/final-snapshot/session budgets and
existing SSH/operation/IPC bounds. No command strings, credentials or raw CLI
output cross into API responses.

Busy/saturated rejection is the existing generic rejection, **not** a new typed
pre-write deferral or negotiation response. It grants no automatic retry authority
and cannot turn a missing/uncertain reply into success. Existing API callers fail
closed and preserve unknown write outcomes. Actual exact deferral remains limited
to the documented cycle response and original policy/request/evidence checks.

Structured events `agent.dispatch.saturated`, `agent.device_busy` and
`agent.worker.failed` expose local scheduling failure without request payloads or
secrets. A busy event can also mean a poisoned guard; inspect preceding worker/
cycle errors. The configured limit is not a live healthy-worker count.

## Activation, rollback and validation

No lab `.env`, credential, inventory, gate/profile, schema, image/service or FTD
operation was changed. Leave the limit at 1 until separately scoped multi-device
acceptance. Setting it higher alone does not activate API parallelism, restoration,
bulk admission, session cycles, large snapshots or ADD. Existing gates stay off.

There is no database migration. For an eventual validated rollout, retain the
previous matching agent image/configuration and checked private SQLite-safe
backup, settle active RPCs and pause mutations before replacing the agent.
An agent restart can interrupt bounded sessions and leave original outcomes
unknown. Rollback may restore the serial image/limit only after settling those
operations; never clear evidence, enable older unsafe writers or restore enabled
standing policy to force compatibility. Existing API and binary packets remain
compatible in serial mode; this is not production-write acceptance.

```bash
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings
cargo build --release --locked --manifest-path agent/Cargo.toml
cargo test --locked --manifest-path agent/Cargo.toml
```

Tests use synthetic inventories, empty/temporary credential fixtures, local
SOCK_SEQPACKET pairs, bounded threads and local timers. They cover canonical
configuration/preflight, saturation without backlog, slow-versus-healthy devices,
same-address aliases, panic poison/stopped workers, peer UID checks, exact wire
dispatch, assignment expiry and shared-runtime timer progress. No real SSH/device
connection or deployment setting is used. Python regressions still exercise the
unchanged serial API scheduler; they do not claim simultaneous FTD acceptance.
