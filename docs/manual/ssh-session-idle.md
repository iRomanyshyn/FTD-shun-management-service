# SSH Idle Time During a Device Visit

## Purpose

A shared SSH visit can be silent while the API persists a verified batch and
validates the original import roots before selecting more work. Silence is not
necessarily a stalled Cisco command.

## Timeout policy

| Boundary | Budget |
| --- | --- |
| Standalone SSH transport inactivity | Unchanged: 15 seconds |
| v1–v5 visit transport inactivity | 120 seconds, matching the original hard visit limit |
| v6/v7 visit transport inactivity | 240 seconds, matching the original hard visit limit |
| CLI prompt/opening/step/IPC and visit deadlines | Unchanged; still independently enforced |

No keepalive, reconnection, command resend, new setting or arbitrary CLI is added.
Host-key pinning and credentials remain unchanged. V7 remains unavailable in the
configured runtime. Increasing transport inactivity does not extend a session,
an expired lease/delegation, mutation/command quota or verification deadline.

## Diagnosis

The old shared 15-second transport idle timer can close SSH during legitimate
local group-result persistence/root checks. The next `show shun IP` then fails
to send, even if the FPR and network are reachable. Similar symptoms can have
other causes: do not infer a specific unknown command was never sent from logs.

The isolated regression uses real pinned in-memory SSH client/server sessions:
after 16 seconds with no packets, the old timer has disconnected; the visit
configuration remains usable and returns subsequent data. It uses no real
credential, network listener, keepalive or FTD command.

## Deployment and recovery

Validate locked Rust tests/build/Clippy/fmt and fixed-protocol compatibility.
Retain the matching old agent image, explicitly drain API/Web before the agent,
then replace only the agent and restart compatible API/Web with all lab overlays.
An existing ATTENTION/UNVERIFIED case does not disappear from a transport fix.
Use its own complete stopped-process rehearsal/review/backup/decision under
[extended recovery](extended-session-recovery.md); never reuse another key or
relabel an old result. Confirm a post-receipt read, groups beyond the old failure
boundary, actual terminal settlement and preserved original authority/unknowns.

This fixes a premature local idle disconnect, not every SSH outage, SQLite
contention, large-import throughput or production acceptance.
