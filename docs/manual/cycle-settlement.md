# Local Cycle Settlement

Status: implemented opt-in protocol/client extension and required by the internal
[continuous dispatcher](continuous-dispatch.md). A separate opt-in
[configured observation runtime](configured-runtime.md) now selects the strict
client on already compatible storage; the lab still uses its prior mode.
No Web route selects it. No live gate, fixture,
migration, credential or lab service was changed.

## Why a final snapshot is not enough

Legacy END can reach the API before disconnect cleanup, device-guard release and
pool-idle publication. Immediately opening another session could hit generic busy
rejection. A guessed sleep, EOF or reconnect retry is not proof.

```text
verified operations → END snapshot → bounded cleanup/resource drop
                    → device/address guard released → worker IDLE
                    → settlement receipt → publish final snapshot/release API lease
```

This attests local handler/guard/slot ordering, not remote TCP termination, process
liveness, future spare capacity or resolution of an uncertain write. Original
UNVERIFIED outcomes, attempts and incident/policy latches stay unchanged. A receipt
never authorizes replay, new policy or an arbitrary command.

## Exact wire extension

AF_UNIX/SOCK_SEQPACKET, peer-UID checks, versions 1/2/3, device/sequence limits,
snapshot bounds, feature/profile gates and mutation verification remain. Integers
are unsigned big-endian; opcodes below are hexadecimal.

| Packet | Exact bytes | Meaning |
| --- | --- | --- |
| Strict begin | `16 version device:u16` | Open the same gated device-bound cycle, requiring settlement. Sequence zero. |
| Initial snapshot | Existing framing bound to opcode `16`, sequence `00` | Reject legacy `10` binding; no silent downgrade. |
| End | `13 version sequence:u8` | Same final full snapshot/budgets as legacy END. |
| Terminal receipt | `00 version 16 end_sequence:u8` | Exactly four bytes, only after successful local completion/guard release/pool idle. No payload or deferral. |

Versions 2/3 use their existing bounded manifest/chunk/digest framing for the new
initial binding. ADD remains v3-only with every independent gate/profile. END uses
its old framing in all versions. No command/route/interface/text field is added.

Old agents reject strict begin before cycle commands. Strict clients fail closed;
no ordinary-BEGIN fallback, reconnect negotiation or mutation retry. Legacy BEGIN
`10`/responses and the default client remain unchanged. A legacy-bound snapshot
cannot satisfy strict begin even if it otherwise parses correctly.

## Agent completion boundary

After its final snapshot, the cycle performs the existing at-most-two-second
disconnect cleanup. Strict cleanup failure/timeout returns rejection, never a
receipt; legacy cleanup behavior is preserved. The pending internal receipt is
not emitted while resources, device/address guard or semantic handler remain
active. A typed completion object retains FD/record until the pool marks itself
idle. The inline serial dispatcher finalizes only after its handler returns.

Finalization performs at most one nonblocking terminal send and FD close; no SSH,
CLI, peer waiting or replacement worker. One next assignment may wait only for
this bounded local postamble, not behind an active semantic handler. Device/pool
limits and stopped/poisoned-worker handling remain. Completion panic stops the
worker, never replaces it. Failed handlers cannot produce a successful completion.

A closed/slow/full peer can lose the nonblocking receipt. Event
`agent.cycle.settlement_failed` records that without payload/credentials; the client
conservatively retains its fence. Receipt availability is not promised under
pressure. A missing record is not permission for a guessed delay/retry. Live large-
transfer and simultaneous-device acceptance remain pending.

## Client and coordinator behavior

`UnixAgentClient(..., settled_cycles=True)` explicitly selects strict begin;
default false. A strict `UnixAgentCycle` starts with `settled=False` and sets it
true only after the exact matching receipt. `finish` returns the final snapshot
only afterward, then closes the socket. Missing/truncated/oversized or wrong-
status/version/opcode/sequence records and EOF all fail closed.

Receipt waiting consumes the original END absolute deadline and at most five
seconds after the complete snapshot. No fresh operation-timeout allowance or
relaxed snapshot/cleanup limit. Choose matching bounded timeout configuration for
eventual validation; never extend a deadline merely to infer success.

ParallelSynchronizer remains legacy by default. Explicit
`settled_cycles_required=True` checks the client before claims and requires a
settled cycle before final-read publication/normal lease release.
ContinuousDispatcher always requires that capability and refuses opt-out. Test
adapters explicitly model settlement; missing proof still holds the lease. This
is not automatic negotiation or authority from a boolean: the real strict client
also validates the wire capability and terminal receipt.

Earlier typed ADD/REMOVE results stay committed if settlement/final reading later
fails. Successful initial/priority reads remain real observations; an unsettled
final read does not publish a fresh callback, admit discovery or complete demand.
Missing proof retains the lease for the existing uncertainty/ATTENTION path.
Healthy devices remain independent; no latch is cleared/rearmed.

## Deployment and rollback

The original extension added no selector or SQLite migration. The later configured
observation selector requires strict settlement, without enabling ADD or optional
admission. The lab API still constructs legacy clients. Do not enable strict continuous execution
against the lab as a smoke test or reuse consumed one-address permissions.
Implementation is not live activation approval.

For eventual separately approved activation, deploy matching agent/client code,
validate scope/pool/timeouts and retained-policy compatibility, drain old writers,
and retain a checked SQLite-safe backup with matching images/configuration. New
strict clients cannot use an old agent. Rollback must explicitly drain/stop strict
execution before restoring a compatible legacy client/agent pair; never fallback
after unknown work, reset jobs to QUEUED, clear fences/attention or restore enabled
authority to force compatibility. No live backup/restore, image rollout or service
restart was needed here.

Remaining: application/Web/maintenance wiring, concurrent version-2 user admission/
cleanup, nonempty legacy migration, automatic evidence-based uncertainty recovery
and scoped FTD/simultaneous-device/load acceptance. Local settlement does not
resolve those authority or remote-quiescence requirements.

## Validation

```bash
python3 -m pytest -q tests/test_agent_settlement.py tests/test_agent_cycle.py tests/test_large_snapshots.py tests/test_continuous_dispatch.py tests/test_parallel_synchronizer.py tests/test_import_execution.py
cargo fmt --manifest-path agent/Cargo.toml -- --check
cargo clippy --locked --all-targets --manifest-path agent/Cargo.toml -- -D warnings
cargo test --locked --manifest-path agent/Cargo.toml
cargo build --release --locked --manifest-path agent/Cargo.toml
```

Shared fixed vectors cover v1/v2/v3 begin/snapshot/END/receipt. Local sockets cover
delayed/missing/malformed proof, strict downgrade refusal and remaining END time.
Rust tests cover cleanup errors, unchanged gates/budgets, callback ordering after
IDLE/guard release, completion panic, closed peers and 100 immediate same-device
handoffs without retry/yield loops. Disposable coordinator tests cover capability
refusal without claims, withheld final callbacks/lease release and preserved
verified ADD after missing proof. No SSH, FTD credentials, real inventory, Docker
or lab/network access is used; this is not live acceptance.
