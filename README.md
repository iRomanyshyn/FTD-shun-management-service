# FTD Shun Management Service

Security-focused internal service for monitoring and managing Cisco Secure Firewall Threat Defense (FTD) `shun` entries across multiple devices.

The governing specification is the [Architecture and Security Design](docs/architecture-and-security-design.md). The repository now contains the first Web/BFF and internal-state API increment, together with deployment assets and operational manuals.

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
- Device-scoped and explicitly confirmed bulk removal UI workflows.
- Durable shared SQLite removal queue with multi-user audit, idempotent admission, progress/cancellation, and a persisted cycle gate.
- Compact Status/Queue menus, paginated history (100 events per page), and Protected IPs managed by all authenticated users in SQLite (no ongoing `.env` policy control).
- Container deployment assets that publish only Caddy TCP/443.

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
