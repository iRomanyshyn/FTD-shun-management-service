# Product Manuals

These manuals describe the first implementation increment. The service is safe to run for development and UI work today. Its separate FTD SSH agent implements verified removal for laboratory validation only; production Cisco writes remain unavailable until the documented FTD validation is complete.

| Manual | Purpose |
| --- | --- |
| [Development](development.md) | Local setup, test commands, and mock agent boundaries. |
| [Deployment](deployment.md) | Caddy, Authelia, Unix sockets, secrets, and container layout. |
| [Operations](operations.md) | Roles, removal workflow, logs, backup, health, and incident response. |
| [Operation Queue](operation-queue.md) | Queued removal, progress/cancellation, limits, lease recovery, migration, backup restore, and rollback. |
| [Protected IPs](protected-ips.md) | Shared authenticated policy editor, concurrency, one-time legacy import, audit, backup and rollback. |
| [Import Preview](import-preview.md) | Non-executable paste parsing, local-state classification, supported syntax, limits and the pending ADD release gate. |
| [Agent Cycle Protocol](agent-cycle-protocol.md) | Experimental bounded single-session removal/checkpoint protocol, feature gate, limits, and lab/rollback procedure. |
| [FTD Laboratory Validation](ftd-lab-validation.md) | Controlled agent, snapshot, and parser-fixture validation. |
| [Local Browser Laboratory](local-lab-web.md) | Workstation-only Caddy Internal CA and local Authelia setup without DNS. |
| [Project Status](../project-status.md) | Implemented scope, explicit limitations, and next work. |
| [Development Log](../development-log.md) | Chronological record of material engineering changes. |
| [Development Plan](../development-plan.md) | Planned multi-user queue, bounded device cycles, refresh reliability, and one-time manual blocklist imports; not a current operating procedure. |

The [Architecture and Security Design](../architecture-and-security-design.md) remains the normative security specification.

All contributors must follow the repository [working agreement](../../AGENTS.md): material work requires a status update, a dated development-log entry, and updates to any affected manual or design document.
