# FTD Shun Management Service

Security-focused internal service for monitoring and managing Cisco Secure Firewall Threat Defense (FTD) `shun` entries across multiple devices.

The governing specification is the [Architecture and Security Design](docs/architecture-and-security-design.md). The repository now contains the first Web/BFF and internal-state API increment, together with deployment assets and operational manuals.

Next requirement: [managed manual-shun restoration](docs/manual/managed-shuns.md)
after confirmed disappearance/reboot, while explicit service removal stops
maintenance. Its registry foundation and read-only Managed shuns tab are
implemented, including non-executable frozen reviews. Composite
[offline recovery controls](docs/manual/recovery.md) and a default-off shared
cleanup-worker hook are implemented. [Revocation controls](docs/manual/managed-controls.md)
now support policy-only stop-maintaining and waiting-cleanup cancellation.
Protected-IP weakening requires reviewed acknowledgement when managed intents
exist; ordinary removal cannot silently bypass enabled maintenance.
Combined device-removal admission, managed creation and desired restoration/
controller integration remain pending.
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
