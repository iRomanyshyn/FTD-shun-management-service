# Graceful Agent Shutdown

## Behavior and limits

The agent handles SIGTERM and SIGINT explicitly, including as container PID 1.
It stops admitting connections, closes its listener and joins the original fixed
workers. Already admitted requests/sessions finish under their existing bounds,
with normal verification and terminal completion. Repeated signals do not cancel
them or shorten their deadlines. The Tokio driver stays alive throughout drain.

An admitted cycle may finish its remaining valid semantic steps, not just the
single CLI command active at signal time. Shutdown is not a mutation pause,
policy retirement, cancellation, Emergency Purge or uncertainty resolution.
**Drain the API first** to stop admitting/dispatching more policy work.

Capacity 1 now uses the same fixed pool as capacities 2–10, rather than running a
handler inline on the listener. It still permits only one active handler/SSH
stream. Same-device/address guards, peer UID, credentials/pins, fixed packets,
strict settlement, ADD gates and budgets are unchanged. The listener can observe
shutdown while the sole worker is occupied. At capacity 1, successors wait in the
existing 16-entry kernel backlog until the worker is idle, preserving old serial
handoffs even for legacy replies without terminal receipts. There is no new
accepted/application work queue. Higher capacities keep fail-closed saturation;
generic rejection is not retry authority. Stop is checked during both polling
and bounded 100ms serial capacity waits.

The nonblocking listener uses a bounded 100ms poll to notice stop. An acceptance/
admission check before stop may finish; after observing stop, no successor is
assigned. Closing the listener refuses new connections before worker joining.
Unadmitted/queued kernel connections may close/reset; no outcome is fabricated.

Pool drain closes senders and joins every handler and its local completion
postamble. Idle workers exit promptly. A failed/panicked worker is not replaced;
healthy siblings still drain and shutdown reports failure, not clean success.
Listener errors also drain admitted work before returning failure. Preserve
original device-result uncertainty; process exit does not prove remote TCP/CLI
quiescence or authorize replay of unknown ADD/REMOVE.

## Operating procedure

Use the three-file `dc` helper in [Fresh Working-Version Lab](fresh-development.md).
Retain the running agent image and matching configuration before replacement.
Inspect current queue/lease state; do not clear it to make restart easy.

```bash
dc stop --timeout 180 api
# Inspect readonly retained queue/leases after drain; no second API executor.
dc stop agent
dc up -d --no-deps agent
# Validate read-only strict transport only when the retained scope is safe.
dc up -d --no-deps api
```

Compose now gives **agent** a 180-second stop grace. The API still needs the
explicit stop timeout above; this increment does not change its configuration.
Existing initial IPC/operation/cycle/cleanup/send budgets fit that agent grace
under their supported assumptions. Do not shorten it for active work. A shorter
Docker timeout, SIGKILL or an underlying operation violating its bound can still
interrupt a session; preserve the resulting original holds/unknown outcomes.

`agent.dispatch.admitted` marks local assignment only, never a command/read result.
Expected shutdown events are `agent.shutdown.requested` (signal),
`agent.shutdown.draining` (listener closed) and `agent.shutdown.completed` (all
workers joined successfully). `agent.listener.ready` means local serving is ready,
not FTD reachability or successful authentication. No secret/payload is logged.
Idle stop should be prompt with exit **0**, not timeout exit **137**. Reaching an
external timeout is not a successful drain. Check logs and retained API evidence.

The checked stale socket pathname remains after shutdown. The existing startup
cleanup handles it; do not manually delete a broad directory or unlink a possible
replacement while the old process drains.

## Configuration, backup and rollback

There is no database, wire, environment flag, credential/trust or network change.
Cargo enables existing nix poll/signal and Tokio signal support; Cargo.lock pins
the additional `signal-hook-registry` and `errno` dependencies. Use `--locked`.
Keep the new 180-second agent stop grace with its supported deadlines.

No DB restore is needed for code-only rollback. Gracefully drain API/agent, then
restore the previous compatible agent image and start agent before API. The
binary protocol and capacity remain compatible, but older images ignore SIGTERM
while idle and lack joined drain; roll back only with work settled and retain
the longer grace/manual precautions. Do not use restart/rollback to clear leases,
alter results or re-enable retired policy. No production acceptance is implied.

## Validation

```bash
cargo test --locked --manifest-path agent/Cargo.toml
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo clippy --locked --all-targets --manifest-path agent/Cargo.toml -- -D warnings
cargo build --release --locked --manifest-path agent/Cargo.toml
```

Tests use private synthetic files, local SeqPacket sockets and real child-process
signals, never SSH, inherited deployment settings or real inventory. Cases include
idle SIGTERM/SIGINT at capacity 1/4, repeated signals during full admission, refused
new connections while original HEALTH requests finish, clean exit, serial legacy
successor handoff and stale-socket restart. Unit tests hold a synthetic handler/
postamble to prove joined drain,
including healthy siblings after a worker failure, and bounded poll/stop behavior.
Wire/semantic fixtures remain unchanged. Docker PID-1/FTD acceptance is separate
from these synthetic process tests; record it in the current project status.
