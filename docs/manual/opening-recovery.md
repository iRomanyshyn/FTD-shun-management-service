# Automatic Recovery Before the First Cisco Command

## Scope

Configured `continuous-observation` and `continuous-managed` now explicitly select
recoverable opening on the existing strict client. Low-level clients default off;
legacy BEGIN `10` and strict BEGIN `16` are unchanged. This recovers a proved
opening failure, not an uncertain write, missing snapshot or old held lease.
No schema, HTTP recovery action, new credential/network configuration or policy
authority is introduced. The default API runtime remains legacy.

## Fixed protocol

The same private UID-checked Unix `SOCK_SEQPACKET` connection carries versions
1/2/3. Integers are big-endian. Every record has an exact binding and length.

| Frame | Exact bytes | Meaning |
| --- | --- | --- |
| Recoverable BEGIN | `17 version device:u16` | Four bytes; sequence zero, existing gates and scope. |
| Successful opening | Existing snapshot frames bound to `17`, sequence `00` | Complete initial observation; not terminal failure proof. |
| Opening failed | `03 version 17 00` | Four-byte terminal record; no Cisco command executor was created. |
| Successful END settlement | `00 version 17 end_sequence:u8` | Same strict cleanup/guard/worker completion requirement as BEGIN `16`. |

SNAPSHOT/ADD/REMOVE/END requests and budgets do not change. No interface, route,
command text or diagnostic output crosses this extension. BEGIN `17` retains
strict settlement; it cannot opt out or accept a terminal receipt bound to `16`.

## What the agent proves

The agent validates device/profile/gates and acquires its existing device/address
guard, then awaits the bounded SSH connection/authentication/channel/PTY/shell/
initial-prompt opening future (at most the configured operation timeout or 45s,
whichever is smaller; individual SSH interactions retain their 15s bounds).
Until that succeeds, there is no `Cycle` executor
and no fixed Cisco operation can be issued. Opening error or timeout drops this
future and its local resources. Only BEGIN `17` can then return failure proof.

The record uses the existing terminal completion: the handler must have returned,
the device/address guard released and the pool slot become IDLE before emission.
There is no replacement task, extra command or guessed delay. The failed opening
path cannot later run a CLI operation. This does not attest remote TCP termination,
reachability, valid credentials, a successful observation or an ADD/REMOVE result.

`agent.cycle.open_failed` records device/version, zero commands, elapsed time and
the existing sanitized error context, without password or Cisco output. Inspect
these logs for pin/authentication/configuration problems; retries never relax trust
or authentication. Repeated invalid credentials may meet device lockout policy;
repair the credential/configuration instead of treating retries as authentication
fallback. The 60-second cap limits reconnect frequency, not operator error risk.

Busy/saturated dispatch, malformed/unknown requests, wrong UID, disabled devices,
missing profiles/gates, initial snapshot errors and every later failure retain
generic rejection. None can manufacture an opening-failure record. A lost terminal
record remains a hold, even if the agent logged a no-command failure.

## Client, lease and status

`UnixAgentClient(..., settled_cycles=True, recoverable_cycles=True)` selects `17`.
The real client raises `AgentCycleOpenFailed` only for the exact first terminal
response on its own connection/version/sequence. Missing/truncated/oversized,
wrong-stage/opcode/version/sequence responses fail closed. It closes the socket,
never falls back to `16`/`10`, and never reconnects inside a cycle.

Only the first opening RPC in the current API lease can consume this type. The
transaction checks its live owner/epoch/deadline, no unsettled device jobs/attempts
and no mutation claim under that epoch, including already completed claims. It
atomically records `DEVICE_LEASE_OPEN_FAILED` and ordinary release; errors roll
back. `DEVICE_LEASE_NOT_SUBMITTED` remains distinct for a purely local failure
before any BEGIN send. Neither path changes jobs, policy, receipts or observations.

The continuous owner shows `retrying`, error category `agent_open_failed`, stale
previous observations and the existing retry countdown/streak. Retain pending
manual/policy-scan demand. Retry after 5/10/20/40/60 seconds, capped at 60, without
blocking healthy devices or letting clicks bypass the delay. The next new fenced
session needs a complete fresh initial read and current authority/protection/
cancellation checks before claims. Success resets the streak.

Old LEASED/ATTENTION, unknown ADD/REMOVE and failures after initial command/read
submission remain held. Neither a later typed exception nor a fresh observation
alone resolves them. Automatic submitted-session reconciliation remains unfinished.

## Deployment and rollback

Use the current [three-file managed lab selection](fresh-development.md).
Build matching API and agent images and retain both running image IDs/tags.
Preflight the existing configuration/storage without starting another executor.
Using the `dc` helper from that lab manual:

```bash
dc run --rm --no-deps api ftd-shun-api --check
dc run --rm --no-deps agent --check-config
```

Gracefully stop/drain the sole API, settle its sessions, then stop the idle agent.
Deploy the new agent first, then the new API. Web does not need replacement.
API startup can execute already admitted work; inspect existing queue/authority.
Do not induce a lab outage by changing pins, credentials or networks for a smoke
test. A healthy startup read is not live failure acceptance.

There is no migration/data conversion or need for DB restore. New agent accepts
old clients; old agent rejects `17`, and new clients deliberately do not negotiate.
For code-only rollback, drain the new API and restore a compatible pair (old API
with either matching old or new agent). Never roll back only the agent while
leaving a new configured client running, clear a resulting hold or restore old
authority snapshots to force progress. Keep all new audit/evidence.

## Validation

```bash
python3 -m pytest -q tests/test_opening_recovery.py tests/test_unsubmitted_recovery.py tests/test_agent_settlement.py tests/test_configured_runtime.py
cargo test --locked --manifest-path agent/Cargo.toml
cargo clippy --locked --all-targets --manifest-path agent/Cargo.toml -- -D warnings
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo build --release --locked --manifest-path agent/Cargo.toml
```

Shared Rust/Python vectors cover all versions, successful initial/END binding and
exact negative proof. Local sockets cover delayed/lost/malformed/truncated/wrong-
stage proof and no fallback. Real Rust handler/guard/worker fixtures fail opening
before TCP using synthetic missing credentials, then prove immediate same-device
reuse only after terminal completion. Disposable continuous tests cover recovery,
retained demand, cancellation/protection before retry, current claims and no
late-type release. These tests access no FTD, real credentials or lab inventory.

Strict normal release also tracks actual terminal settlement in the current
epoch. An initial/priority snapshot may decode successfully and then fail local
processing; no RPC exception alone is required to retain its unsettled fence.
Conversely, a local final-publication failure after valid settlement does not
invent an outstanding session: release is safe, but the error remains and no
failed publication is called a fresh successful observation.
