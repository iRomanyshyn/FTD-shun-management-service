# Persistent Agent Completion Evidence

Source v0.12.0 adds optional storage for completed deferred-v7 sessions. It is
not enabled on the main laboratory stack. Main v6 and its original data stay
unchanged; this does not activate the separate deferred database/profile.

## Purpose

If an import's final ADD group has finished and the agent has closed its SSH
session, restarting the agent should not discard the proof that the session
ended. With this option, the next API instance can obtain that exact receipt
and complete the existing pending handoff. A later full device refresh confirms
which blocks are present. Recovery sends no ADD, END or SSH command.

This covers **completed session evidence surviving an agent restart**. It does
not resolve an interrupted command, an active session, lost stage ACKs, an old
UNVERIFIED outcome or an ATTENTION hold. Missing proof remains missing. See
[Interrupted Pending Handoff](pending-restart-recovery.md).

## Configuration and isolation

The default is process-local storage. To opt in, set this variable **only for
the agent** in an explicitly selected, matched deferred-v7 deployment:

```text
FTD_SHUN_AGENT_PENDING_JOURNAL_DIRECTORY=/var/lib/ftd-shun-agent-pending
```

Prepare a separate persistent directory owned by the agent UID (10002 in
Compose), mode0700. Its files require mode0600, the same owner and one hard
link. Directory symlinks, nonregular files and broader permissions refuse
startup. The agent never creates the directory. Do not mount it into Web/API,
reuse the socket volume, share the core DB volume or mount it in two agents.
The fixed directory lock prevents concurrent agent ownership.

`deploy/compose.agent-journal.lab.yml` is an optional storage-only overlay,
applied after the selected deferred overlay. Its networkless initializer changes
only the volume root's ownership/permissions; it does not traverse or repair
retained files. This overlay does not select v7, prepare a DB, enable commands
or supply compatible API/agent images. Do not apply it alone to the current v6
stack: a persistent path with v5/v6 is a configuration error.

`ftd-shun-agent --check-config` reads and validates existing journal data and
reports `persistent_pending_journal`. It creates no lock, receipt or scratch file,
performs no repair, binds no socket and opens no SSH session. On a new volume,
run only its initializer before the preflight; `run --no-deps` does not run it.

## Persistence and recovery guarantees

The existing postamble publishes completion only after SSH cleanup, handler
return, device-guard release and worker IDLE. In persistent mode it first writes
the bounded receipt set to a private scratch file, synchronizes that file,
atomically replaces the committed journal and synchronizes the directory.
Only then does it expose the pending receipt in memory and send the terminal
settlement. Storage can delay that reply; the existing client timeout and local
lookup rules remain. No filesystem failure triggers a device-command retry.

Only completed pending-v7 receipts persist. Active/prepared sessions and
read-only completion records do not. The fixed binary file includes an exact
format/version, count, session/device/ordered target scope and SHA-256 checksum;
the maximum is364,586 bytes and4096 entries. The checksum detects corruption, not an
untrusted host forging evidence. Host/agent-private storage remains a trust
boundary. No credential, Cisco output, desired policy or execution authorization
is stored.

The existing4096-key process-local capacity remains shared with active/read-only
sessions. Only the oldest completed entry may be evicted. Before reusing an
evicted pending identity, its removal must be durably saved. On restart, loaded
pending identities reject another BEGIN, and lookup returns the original exact
receipt. Missing or evicted identities return unknown, never permission to resend.

The API still validates the original checkpoint, expired LEASED owner/epoch,
ordered ACKs, inventory and full unchanged visit. A receipt only permits the
existing atomic transition to Awaiting confirmation; it neither grants VERIFIED
creation nor substitutes a device observation.

## Failure handling and rollback

An invalid committed journal refuses startup and is retained as evidence.
Startup under the exclusive lock may discard only a strictly private uncommitted
`pending-completions.next` scratch file; it never recovers success from scratch
or repairs/truncates the committed file. Interrupted replacement therefore
exposes either the old valid receipt set or the new valid set, never a partial
file interpreted as completion.

A persistence error logs `agent.session.completion_unavailable` with its local
error cause. The pending record remains unpublished in memory. A terminal
settlement may still report actual completed cleanup, allowing the ordinary
live API handoff; it does not claim that journal storage succeeded. Retain the
directory and process logs before diagnosing storage. Correct ownership, disk
space or mount problems rather than deleting the committed journal or resending
unknown commands. A crash before durable completion remains outside recovery.

To roll back this source capability, stop and drain the experimental writers,
restore their prior matching images/configuration and omit the journal path/
overlay. Retain the journal volume and separate experimental database as private
evidence. Do not reset the original lab DB or clear holds. A process-local agent
cannot use these persisted receipts, so that rollback can reduce recoverability.

## Development validation

Rust tests exercise real filesystem locking, process exit, exact receipt reload,
capacity/eviction, corruption, unsafe paths/permissions and failed publication.
An optional Python acceptance uses the actual agent executable and Rust's
`cfg(test)`-only receipt producer, kills/restarts the production executable, then
uses the actual Unix client and existing API recovery transaction. It has no
production seeding switch and never contacts Cisco:

```sh
cargo test --locked --manifest-path agent/Cargo.toml --no-run
cargo build --release --locked --manifest-path agent/Cargo.toml
FTD_TEST_AGENT_BINARY="$PWD/agent/target/release/ftd-shun-agent" \
FTD_TEST_AGENT_JOURNAL_SEED="<absolute path to the Rust unit-test executable>" \
  pytest -q tests/test_pending_restart.py -k real_agent_process_restart
```

Use the `ftd_shun_agent-…` **unit-test executable** printed by Cargo, not the
normal debug agent or the credential/shutdown integration-test executables.
These are synthetic crash/recovery checks, not FPR acceptance or main-lab cutover.
