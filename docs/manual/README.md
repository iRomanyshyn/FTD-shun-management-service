# Product Manuals

These manuals describe the first implementation increment. The service is safe to run for development and UI work today. Its separate FTD SSH agent implements verified removal for laboratory validation only; production Cisco writes remain unavailable until the documented FTD validation is complete.

| Manual | Purpose |
| --- | --- |
| [Development](development.md) | Local setup, test commands, and mock agent boundaries. |
| [Versioning](versioning.md) | Single version source, manual release numbering, pre-1.0 compatibility and planned build identity. |
| [Deployment](deployment.md) | Caddy, Authelia, Unix sockets, secrets, and container layout. |
| [Operations](operations.md) | Roles, removal workflow, logs, backup, health, and incident response. |
| [Operation Queue](operation-queue.md) | Queued removal, progress/cancellation, limits, lease recovery, migration, backup restore, and rollback. |
| [Protected IPs](protected-ips.md) | Shared authenticated policy editor, concurrency, one-time legacy import, audit, backup and rollback. |
| [Import Preview](import-preview.md) | Non-executable paste parsing, local-state classification, supported syntax, limits and the pending ADD release gate. |
| [Browser Import Review](import-review.md) | Frozen exact-target confirmation, identity/CSRF, bounded ephemeral drafts, same-key retry, default-off admission and rollback. |
| [Managed Shuns](managed-shuns.md) | Registry foundation and read-only visibility, lifecycle/storage bounds and planned managed confirmation/shared-worker restoration; no controller. |
| [Managed Removal Handoffs](managed-removal-handoffs.md) | Offline atomic retirement, waiting cleanup, original authorization, ordered settlement and remaining runtime/recovery gates. |
| [Import Admission](import-admission.md) | Default-off private staging, ADD/REMOVE conflicts, immutable occurrence provenance, additive migration and rollback; no executable import. |
| [Import Execution](import-execution.md) | Independent default-off scheduler gate, per-device v3, common FIFO/budgets, priority reads, no-replay recovery and disabled-mode rollout. |
| [One-Address Service Validation](single-address-service-validation.md) | Scoped runbook and recorded one-fixture VERIFIED/NOOP/cleanup evidence, idempotent replay and restored gates; new tests require new approval. |
| [Agent Cycle Protocol](agent-cycle-protocol.md) | Experimental bounded single-session removal/checkpoint protocol, feature gate, limits, and lab/rollback procedure. |
| [Large Snapshots](large-snapshots.md) | Default-off versioned multi-frame reads, complete-snapshot checks, console/transfer budgets and lab rollout/rollback. |
| [FTD Laboratory Validation](ftd-lab-validation.md) | Controlled agent, snapshot, and parser-fixture validation. |
| [Addition Readiness](addition-lab-validation.md) | Current snapshot-capacity blocker and staged Basic-account, one-address direct-CLI validation before ADD design. |
| [Addition Contract](addition-contract.md) | Default-off agent/transport cycle v3, explicit creation profile, exact ADD verification, shared budgets and remaining admission/lab gates; no executable import. |
| [Local Browser Laboratory](local-lab-web.md) | Workstation-only Caddy Internal CA and local Authelia setup without DNS. |
| [Project Status](../project-status.md) | Implemented scope, explicit limitations, and next work. |
| [Development Log](../development-log.md) | Chronological record of material engineering changes. |
| [Development Plan](../development-plan.md) | Planned multi-user queue, bounded device cycles, refresh reliability, and one-time manual blocklist imports; not a current operating procedure. |

The [Architecture and Security Design](../architecture-and-security-design.md) remains the normative security specification.

All contributors must follow the repository [working agreement](../../AGENTS.md): material work requires a status update, a dated development-log entry, and updates to any affected manual or design document.
