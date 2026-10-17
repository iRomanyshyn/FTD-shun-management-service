# Queued Import Execution — Experimental and Default-Off

## Release boundary

ADD is wired into the existing leased scheduler, not a separate writer. This
increment is implemented and synthetically tested, but the deployed laboratory
keeps it disabled. The separately approved
[one-address lifecycle](single-address-service-validation.md#recorded-service-result--2026-10-16)
now has live VERIFIED creation, NOOP and VERIFIED cleanup evidence, with independent
operator target reads and gates restored off. The
[browser confirmation](import-review.md) is implemented behind disabled intake;
it does not enable execution. Production, traffic blocking, fleet creation scope,
real large-load capacity and live failure/priority behavior remain unvalidated.

Do not enable execution merely to try a pasted list. Follow
[Addition Readiness](addition-lab-validation.md) and the
[exact ADD contract](addition-contract.md). A scoped service-executed fixture
requires explicit device-change authorization and review of those gates;
standing permission for code deployment does not authorize a test write.
The [one-address runbook](single-address-service-validation.md) separates
read-only preparation from explicit target/window approval and controlled
execution/cleanup. It is not evidence that the test has happened or permission
to turn on gates before the operator approves the scoped experiment.

## Independent gates and device eligibility

| Setting | Owner and effect |
| --- | --- |
| `FTD_SHUN_IMPORT_ADMISSION_ENABLED=false` | API: permits private typed admission only when true. Not execution authority. |
| `FTD_SHUN_IMPORT_EXECUTION_ENABLED=false` | API: enables eligible ADD claims and explicit per-device v3 selection only when true. Requires socket mode, session cycles and large snapshots. |
| `FTD_SHUN_AGENT_ADDITIONS_ENABLED=false` | Agent: independently rejects ADD/v3 unless true, with both cycle/large-read gates and a valid device profile. |

The API execution setting is strict lowercase `true`/`false`, including startup
validation of dependencies. It is independent of intake: turning admission off
can stop new requests while already authorized work drains. Agent ADD alone
cannot turn on API execution; API execution alone cannot bypass the agent gate.
An attempted v3 request to an old/disabled agent fails without fallback.

The normal validated inventory load derives a startup-only set of enabled
device IDs with an explicit recognized `addition_profile`. This is not a new
SQLite policy, user-selected interface, preview result or mutable API field.
The API always supplies an exact set to its transport, including empty. Devices
outside the set retain ordinary v1/v2 reads/removals and hold ADD; they do not
break fleet monitoring just because another device supports creation. A
profile is a declared capability, not evidence of actual compatibility.

`GET /api/v1/status` publishes the API gate and eligible `addition_device_count`.
Queue rows add per-device `execution_enabled`; an unstarted ADD without
eligibility says **Held — ADD execution disabled for this device**. Held rows
remain cancellable/expirable and do not accelerate device cycles. API admission
reports whether its submitted targets include any execution-eligible device;
this is not per-target execution success. Queue views remain authoritative for
mixed eligible/held requests. The agent's actual remote gate is checked when
opening a session, not inferred from API metadata.

## Common execution cycle

One durable fleet lease, persisted cooldown, one device-bound SSH session and
the existing priority-refresh rules cover both operations. No standalone ADD
RPC, independent agent read, fallback writer or new published port is added.

1. Open exact v3 only for a device permitted by the API gate/profile set; reject
   a mismatched cycle before claiming work. Obtain a complete initial snapshot.
2. Reconcile observations and discover trusted-policy removals through the
   existing queue. Freeze manual jobs at the sweep cutoff; later new jobs wait
   for a subsequent cycle. Same-target duplicate intentions can still share an
   already queued/running job with separate actor audit.
3. At each boundary service at most one coalesced eligible priority snapshot
   before claiming the next background job. It waits for current verification,
   shares command/time reserves and can join the final snapshot if deferred.
4. Atomically select common FIFO ADD/REMOVE sequence. Check live enabled
   device, captured role/authorization expiry, cancellation and enabled Protected
   IP exclusion. Newly discovered policy work retains the existing cutoff
   exception but not an extra budget. Without ADD eligibility select REMOVE only.
   Unstarted coalesced actors that expire inside a long cycle become EXPIRED
   before the next claim and receive no new verified-origin attribution from
   another actor's still-valid request. Already RUNNING authorizations remain
   attached through completion under the original claim.
5. Send only the typed operation. ADD's own fresh target preflight/strict ack/
   source-only post-read happen in the agent, not inferred from the initial
   scheduler snapshot. Existing targets are no-op without a creation write or
   new import origin.
6. Persist the exact verified result and provenance immediately. Publish local
   revisions/progress before the next step. Only exact pre-write deferral returns
   the job to QUEUED and clears its dispatch marker.
7. Obtain and reconcile the mandatory final complete snapshot, then close.
   A failed final read preserves earlier verified writes and marks freshness
   stale/error; it does not replay, erase origin or invent complete observations.

There are at most **16 combined processed operations**, not 16 of each. No-ops
consume a scheduler step; agent attempt/command accounting and reserves remain
independent safeguards. Keep 64 CLI commands, 120 seconds, configured step/IPC
deadlines, final-read reserve, one priority read and at least 60 seconds after
completion before another fleet cycle. Progress is whole processed jobs, not
successful writes or within-command ETA. Queue/Status displays **Adding and
verifying**, removal and snapshot phases using local BFF polling only.

Policy changes and cancellation take effect before the next claim. Already
RUNNING work cannot be cancelled or atomically revoked after CLI dispatch.
Protection enabled during such a write can be enforced by the next normal
successful observation/policy cycle, not by a second concurrent writer.

## Failure, recovery and one-time provenance

Missing, malformed, wrong-version or lost ADD results become UNVERIFIED and
abort the current session. They never become no-op, inferred creation, retry,
automatic undo or a legacy RPC. A later snapshot can observe presence but cannot
attribute it to an uncertain attempt. Database/lease failure cannot establish
success; abandoned RUNNING jobs settle UNVERIFIED after lease recovery.

API shutdown can interrupt an await while a bounded RPC thread still runs.
Abort the connection and keep the lease until expiry. A new owner must wait,
recover the uncertainty and observe state without resending the abandoned ADD.
Previously confirmed operations remain confirmed even when a later step fails.
Following healthy devices can still be monitored after a device-specific error.

Only a typed verified creation can commit occurrence-bound origins and each
coalesced actor's `SHUN_ADDED_BY_IMPORT`. Already-present/no-op retains any
existing origin without assigning a new one. A conflicting active local
occurrence refuses attribution and aborts the session. Removal, disappearance,
restart or idempotent replay never regenerates an import. See
[Import Admission](import-admission.md) for canonical batch metadata, immutable
schema, opposite-intention rejection and origin/queue retention.

Operational JSON adds `queue.addition.unverified` alongside completion/deferral
and cycle errors. Join job and batch/request IDs; never log source paste,
label/reason, Cisco output or secrets. Audit preserves sanitized failure reason.

## Capacity and remaining work

Admission still permits at most 1000 unfinished jobs and 2000 active requests,
10 submissions/actor/minute and at most 15 minutes of captured authorization.
The new worker does not waive these limits, silently truncate/chunk a list or
promise to complete even 1000 writes before expiry. A 7,307-address import needs
separate bounded scheduling/explicit reauthorization design and complete live
read evidence at intended load. The agent's 20,000-entry bound is a fail-closed
ceiling, not an advertised tested device capacity.

## Deployment and rollback

No new schema, opcode, agent binary or inventory format is introduced beyond
the preceding admission/transport increments. Preserve a fresh SQLite-safe
backup and prior API/Web images. Build/update only API/Web, stop the sole API
executor cleanly before replacement and ensure no previous RPC survives. Keep
all import/ADD flags false/absent and actual inventory unchanged. Starting API
can execute existing removals/policy, not new assistant-created test work.

Read-only deployment checks: both API gates false, client ADD selector false,
eligible device count zero, unchanged queue/policy aggregates and stable dates,
SQLite quick_check/foreign_key_check, normal v1/v2 baseline, private anonymous
401 and TLS-verified Authelia redirect. Do not read full confidential inventory
for diagnostics or spoof identity to check authenticated visuals; use published
safe capability metadata and operator browser checks instead.

Rollback stops API/Web and ensures no in-flight RPC remains; follow the queue's
[offline pending-work suspension procedure](operation-queue.md#backup-restore-and-rollback)
before starting an older executor. Restore the preceding API/Web pair, retain
additive schema/origins and false/absent execution flags, and do not restore old
device state just to revert code. Legacy-claim triggers are a safety net, not
permission to run an old worker with active ADD. No restore should replay work.
