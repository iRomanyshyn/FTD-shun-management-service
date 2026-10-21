# FTD Shun Management Service

Security-focused internal service for monitoring and managing Cisco Secure Firewall Threat Defense (FTD) `shun` entries across multiple devices.

The governing specification is the [Architecture and Security Design](docs/architecture-and-security-design.md). The repository now contains the first Web/BFF and internal-state API increment, together with deployment assets and operational manuals.

The [Working-Version Plan](docs/working-version-plan.md) records the operator's
2026-10-20 product alignment and current delivery priority: usable managed bulk
import/restoration, continuous parallel device work, quick unblock, whitelist
retirement, clear status and Emergency Purge. Email is a later increment. This is
an approved target; the implementation boundaries below are not yet replaced.

Next requirement: [managed manual-shun restoration](docs/manual/managed-shuns.md)
after confirmed disappearance/reboot, while explicit service removal stops
maintenance. Its registry foundation and read-only Managed shuns tab are
implemented, with frozen reviews and separately gated confirmation. Composite
[offline recovery controls](docs/manual/recovery.md) and a default-off shared
cleanup-worker hook are implemented. [Revocation controls](docs/manual/managed-controls.md)
now support policy-only stop-maintaining and waiting-cleanup cancellation.
Protected-IP saves permanently retire matching managed authority with reviewed
revision checks; disabling/deleting protection never resumes old maintenance.
Ordinary removal cannot silently bypass enabled maintenance.
The [frozen fleet review](docs/manual/managed-removal-review.md#frozen-all-device-scope)
includes observed and maintained-but-missing targets without submitting work.
A [whole-scope fleet coordinator](docs/manual/managed-fleet-removals.md)
now atomically retires the reviewed scope and delegates cleanup. Default ready-only
mode rejects unfinished ADD/disabled targets; a separate explicitly digested ordered
mode reserves the whole scope behind RUNNING ADD under the original deadline.
The default-off shared worker promotes complete roots only. The Managed shuns
tab shows bounded fleet cleanup progress/outcomes and owner/Admin cancellation
of waiting scopes, without treating admission or settled jobs as verified removal.
No live admission or optional-schema initialization is enabled in the lab.
An [offline managed maintenance tool](docs/manual/managed-maintenance.md) now
provides explicitly reviewed atomic empty-schema initialization and separate
resume of existing standing policy, with checked backups and no uncertainty
override. It has not been invoked on the lab; no HTTP resume exists.
Its [read-only attention report](docs/manual/managed-attention.md) now identifies
retained uncertainty and cleanup incidents, with 100-case snapshot-bound pages;
inspection never clears a latch or authorizes retry.
A separate [offline acknowledgment](docs/manual/incident-acknowledgements.md)
records operator review of ordinary/single/fleet incidents with immutable receipts
and the whole original scope. It preserves uncertain outcomes and resume blockers;
its optional ledger is never created by startup.
An additional [offline isolation decision](docs/manual/incident-isolation.md)
can retire and permanently exclude the whole reviewed incident scope, then allow
separately reviewed resume of other healthy standing policy. Original outcomes
and pair latches remain; schema migration and live decisions are separate operations.
A separate [offline abandonment workflow](docs/manual/managed-abandonment.md)
now records an immutable decision and retires current maintenance for one failed/
uncertain restoration case. Original outcomes/latches and all execution gates
remain unchanged; ordinary/fleet resolution and rearm are not enabled.
[Combined cleanup](docs/manual/managed-cleanup.md)
now has separately default-off device/fleet admission: atomic retirement plus
cleanup, with explicit whole-scope waiting behind RUNNING ADD. Preparation/receipt
is not verified removal, and startup never initializes optional schemas.
A separate [single-target standing review](docs/manual/managed-grants.md) supports
policy-only MAINTAIN behind default-off admission, with explicit recurring
consent and original-key retry. It never initializes policy or queues a command.
A separate [standing address-list workflow](docs/manual/managed-batch-grants.md)
accepts pasted IPv4 text and explicit devices, freezes up to 1000 exact pairs
with 100-row review pages, and saves the whole recurring policy or none of it.
Its policy admission uses the same default-off gate; preview is not execution.
A [default-off restoration controller](docs/manual/managed-restoration.md) now
provides snapshot/generation-bound ADD authority, retained uncertainty/provenance
and atomic revocation/queue/recovery hooks. Bounded complete-snapshot discovery
and dispatch reuse the shared executor behind an independent false-by-default
setting; policy/schema migration and live restoration are not enabled.
Current imports remain one-time and all ADD gates stay
disabled in the lab. Old imports are not auto-adopted and no live migration
initializes the new registry yet.

The page footer displays the package version (currently `v0.1.0`) from the same
source used for build metadata; it does not imply production readiness. See
[Versioning](docs/manual/versioning.md) for how the number is assigned and changed.

## Design goals

- Monitor, reconcile, and retain the history of active FTD shuns.
- Allow operators to remove a specific shun through a secured web interface.
- Support device-scoped removal and explicitly confirmed bulk removal across matched devices.
- Prevent arbitrary Cisco CLI execution at every trust boundary.
- Isolate the privileged SSH capability and Cisco credential material.
- Use default-deny network segmentation and hardened containers.
- Delegate user authentication to Authelia through Caddy ForwardAuth; start with local users and migrate to LDAP(S) when needed.

## Current implementation status

- Web/BFF with Caddy/Authelia ForwardAuth trust boundary and CSRF protection.
- Internal Unix-socket API backed by SQLite WAL state and append-only audit events.
- Strict fixed binary protocol encoder/decoder and an isolated Rust FTD SSH agent.
- Opt-in [per-device SSH credentials](docs/manual/per-device-credentials.md), with agent-only mapping/secrets, ID-based selection and non-network configuration checks. Existing lab credentials remain unchanged in explicit shared compatibility mode.
- Default-off [large-snapshot extension](docs/manual/large-snapshots.md) with bounded multi-frame reads and complete-snapshot validation; synthetic 20,000-entry coverage, live small-read lab validation only.
- Default-off [agent ADD/cycle v3](docs/manual/addition-contract.md) with an explicit creation profile, strict acknowledgement/post-read verification and shared mutation budgets. One approved [lab lifecycle](docs/manual/single-address-service-validation.md#recorded-service-result--2026-10-16) passed creation/NOOP/cleanup; traffic, large-load and production acceptance remain pending.
- Default-off [private import staging](docs/manual/import-admission.md) with immutable batches, ADD/REMOVE conflicts and occurrence provenance; [browser review/confirmation](docs/manual/import-review.md) freezes exact targets and retries without enabling ADD.
- Independently default-off [queued ADD execution](docs/manual/import-execution.md): explicit per-device v3, common FIFO and 16 combined mutations per cycle, shared priority reads and no-replay recovery. Restored disabled after the approved one-address lab test.
- Device-scoped and explicitly confirmed bulk removal UI workflows.
- Durable shared SQLite removal queue with multi-user audit, idempotent admission, progress/cancellation, and a persisted cycle gate.
- Compact Status/Queue menus, paginated history (100 events per page), and Protected IPs managed by all authenticated users in SQLite (no ongoing `.env` policy control).
- Container deployment assets that publish only Caddy TCP/443.
- Non-executable [Import preview](docs/manual/import-preview.md) for pasted IPv4 lists: parsing, duplicates/protection/current-state checks and bounded candidate counts. No shun addition is enabled.

The agent implements typed `LIST_SHUNS` and verified, device-scoped `REMOVE_SHUN`. It pins each device host key, requires an explicit per-device interface allowlist, and re-reads `show shun <IPv4>` after removal. The API reconciles complete snapshots on a configurable five-minute baseline, provides freshness metadata and local IP search to the UI, and can optionally apply an exact-IPv4 trusted-IP automatic-removal policy. That policy is disabled by default and requires laboratory validation. Do not treat the service as production-ready until it has passed the laboratory validation in the deployment manual.

The detailed current state and planned sequence are maintained in the [Project Status](docs/project-status.md). Material engineering work is recorded chronologically in the [Development Log](docs/development-log.md).

The [Development Plan](docs/development-plan.md) records implemented refresh
reliability and the durable removal queue. Default mode uses the existing agent
RPC and at most one removal per device per minute-spaced cycle. Experimental
[single-session cycles](docs/manual/agent-cycle-protocol.md) support up to 16
removals, bounded command/time budgets, and priority refresh checkpoints; they
remain disabled by default pending live lab validation. See
[Operation Queue](docs/manual/operation-queue.md) before migration, backup
restoration, or rollback. One-time manual blocklist imports remain unavailable.

## Manuals

- [Development](docs/manual/development.md)
- [Deployment](docs/manual/deployment.md)
- [Operations](docs/manual/operations.md)
- [Protected IPs and migration](docs/manual/protected-ips.md)
- [Project Status](docs/project-status.md)
- [Development Log](docs/development-log.md)

## Contributor record-keeping

Follow the repository [working agreement](AGENTS.md). Every material change must update the current status, append a development-log entry, and update the applicable manual or architecture document.

## Quick start for contributors

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

See the [Development Manual](docs/manual/development.md) for the controlled mock-agent workflow. Never use mock mode in a deployed environment.
