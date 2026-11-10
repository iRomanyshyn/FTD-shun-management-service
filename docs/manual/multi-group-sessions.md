# Multi-group import sessions

Status: implemented explicit tracked v6 profile; see project status for validation
and actual laboratory activation. This is not cross-session first confirmation.

The known desk lab selected v6 on 2026-11-04 after clean API-first drain. Two
complete visits each verified 33 addresses in groups 16/16/1 on one SSH session:
66/402.819s (9.83/minute including the gap). All current guards remained; no new
unknown or hold occurred. This is a bounded observation, not a promised size,
whole-list/load test or production acceptance. See current status for images,
rollback, original-task progress and retained evidence. Defaults remain unchanged.

## Operator behavior

An import still appears as one task. Its already-authorized device worker can
process several small groups over **one SSH login**, rather than reopening SSH
after every group. The matching optional configuration is:

```dotenv
FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED=true
FTD_SHUN_AGENT_BATCH_SESSION_VERSION=6
```

Use the same selection on API and agent. Default version is 5; grouped execution
itself remains disabled by default. Version 6 requires the existing configured
`continuous-managed` socket runtime and validated per-device ADD profiles. No
port, credentials, trust, network, database schema or standing consent changes.
Never enable it on an old/mismatched pair or fall back after a lost response.

V6 has absolute bounds of **240 seconds including opening, 64 combined mutation
attempts and 256 CLI commands**. Each pending group still contains at most **16
addresses**. These are maxima, not promised group size or throughput. Slow CLI,
priority work, stop or depleted reserve can end a visit earlier. One session
never spans the entire 100,000-address import.

Each IP keeps its immediate target preflight and strict Cisco acknowledgement.
The acknowledgement means sent/awaiting verification, not success. One complete
`show shun` confirms each group, and that same observation updates the UI.
The last group uses the existing combined verification/final-read/real terminal
settlement operation. No individual post-ADD read or duplicate final read is
introduced. Current full-root/protection/lease/cancellation checks remain.

## Fresh refill and responsiveness

After the initial complete read, and after a non-final group has been verified,
durably settled and published, the worker freezes a new queue segment. Discovery
can admit new jobs only from that fresh complete read and still-current standing
policy. Entire-session limits are 64 new admissions and 256 eligibility checks;
the rolling per-device queued/running window remains 16. Original job deadlines
and snapshot timestamps are never extended to fit the larger session.

Refresh, unblocking, protection changes, cancellation and shutdown are checked
between semantic commands, including after the first group. Pending additions
must be verified before another operation can overtake them. Cancellation keeps
already-applied blocks as before; it does not silently delete them. There is one
serialized device stream, not competing SSH sessions.

The v6 wire uses the same exact tracked BEGIN, STAGE, VERIFY and VERIFY_END
layouts with version byte `06`, and sequence range **1..130**. Each pending
receipt must match the complete ordered scope and matching full snapshot. Final
success also requires actual post-handler settlement. V1–v5 retain their exact
old bounds/cutoff and do not silently acquire v6 behavior. Shared fixture:
`tests/fixtures/batch-addition-v6.json`.

## Failures and deployment

Lost ACK, failed/partial read, invalid receipt, missing settlement or local result
persistence failure retains original uncertainty/fences. Earlier committed
verified groups remain verified. Do not infer success from logging or replay
unknown writes. Deferred first confirmation across sessions and automatic retry
of safely settled-but-absent initial additions remain separate future work.

Ordinary offline recovery still bounds epochs to 16 claims. The separately
selected [extended v6 profile](extended-session-recovery.md) supports 17–64 exact
system ADD claims with new immutable receipt bindings; consult current status
for activation. It is not automatic recovery or a guard bypass. Missing evidence,
deferred/nonterminal claims, manual/REMOVE/FAILED work and broader cases refuse.

Before replacing the pair, retain compatible images and current non-secret
evidence. Use all three managed-lab Compose overlays. Drain API first with an
explicit sufficient timeout, inspect stopped IDLE/no RUNNING/new unknown state,
then stop agent and require actual exit 0. Existing historical reviewed unknowns
remain history; do not clear them. Compose agent grace is now **300 seconds** to
cover the larger session and cleanup; it does not replace API-first drain.
Run non-executing API/agent preflight with the matching selection before startup.
Start agent, then API. Web assets do not change and Web need not restart.

For rollback, drain both at a clean settled boundary and explicitly restore
version 5 with its matching compatible images. Do not downgrade pending work,
release a hold for rollback convenience or restore stale DB authority. No schema
rollback/DB restore is needed for this code-only increment.

Measure durable per-epoch claim/result/release evidence, total verified progress,
number of shared group reads/logins and status latency on the same original task.
Synthetic 64-address success is not actual FTD throughput, load or production
acceptance. Do not reset or reimport the existing laboratory list to benchmark.
