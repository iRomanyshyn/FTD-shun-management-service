# Product Manuals

These manuals describe the first implementation increment. The service is safe to run for development and UI work today. Its separate FTD SSH agent implements verified removal for laboratory validation only; production Cisco writes remain unavailable until the documented FTD validation is complete.

The [Working-Version Plan](../working-version-plan.md) records the newer approved
product target and differences from these current operating procedures. It is
not a runbook or permission to change gates, initialize schemas or run new fixtures.

| Manual | Purpose |
| --- | --- |
| [Development](development.md) | Local setup, test commands, and mock agent boundaries. |
| [Working-Version Plan](../working-version-plan.md) | Agreed product behavior, working-version priorities, implementation gaps and deferred SMTP notifications; not yet an operating procedure. |
| [Versioning](versioning.md) | Single version source, manual release numbering, pre-1.0 compatibility and planned build identity. |
| [Deployment](deployment.md) | Caddy, Authelia, Unix sockets, secrets, and container layout. |
| [Per-Device Credentials](per-device-credentials.md) | Agent-only ID/login/secret mapping, configuration check, opt-in Compose migration and rollback; legacy compatibility retained. |
| [Operations](operations.md) | Roles, removal workflow, logs, backup, health, and incident response. |
| [Operation Queue](operation-queue.md) | Queued removal, progress/cancellation, limits, lease recovery, migration, backup restore, and rollback. |
| [Offline Recovery](recovery.md) | Checked backup, durable mutation pause, composite queue/policy suspension and reviewed ordinary resume. |
| [Offline Managed Maintenance](managed-maintenance.md) | Explicit empty-schema migration, exact-state five-minute review and separate policy resume; no live activation or uncertainty override. |
| [Offline Attention Inspection](managed-attention.md) | Read-only uncertainty catalog and exact-case inspection, full fleet membership in snapshot-bound pages, evidence provenance and planned resolution boundaries. |
| [Incident Acknowledgments](incident-acknowledgements.md) | Reviewed offline ordinary/single/fleet administrative receipts, whole-scope evidence and unchanged uncertainty/controls. |
| [Incident Isolation](incident-isolation.md) | Whole-scope offline exclusion/retirement, permanent pair latches and reviewed resume of other healthy standing policy. |
| [Offline Incident Abandonment](managed-abandonment.md) | Explicit closure-ledger migration, reviewed restoration-policy abandonment, immutable receipts and retained no-replay latches. |
| [Unrelated Policy Resume](managed-unrelated-resume.md) | Separate reviewed offline resume of healthy enabled policy after exact abandonment/isolation checks; no rearm or ordinary/fleet uncertainty override. |
| [Managed Controls](managed-controls.md) | Frozen policy-only retirement, bounded single/fleet cleanup status and owner/Admin waiting cancellation; no device-write admission. |
| [Combined Managed Cleanup](managed-cleanup.md) | Default-off atomic device/fleet retirement/cleanup, explicit ordered waiting, original-key receipts and rollout. |
| [Protected IPs](protected-ips.md) | Shared authenticated policy editor, concurrency, one-time legacy import, audit, backup and rollback. |
| [Import Preview](import-preview.md) | Non-executable paste parsing, local-state classification, supported syntax, limits and the pending ADD release gate. |
| [Durable Import Preparations](managed-import-preparations.md) | Explicit, non-authoritative 100,000-pair journal, owner reports/restart, exclusions, integrity and draft-only expiry; no automatic initialization. |
| [Large-Import Format and Capacity](bulk-import-capacity.md) | Isolated version-2 classified manifest, bounded proposal/verification and remaining coordinated persistence/migration requirements; no expanded live limits. |
| [Version-2 Bulk Policy Storage](bulk-policy-storage.md) | Atomic 100000-pair SQLite authority/membership, bounded reads, retirement reserve, protection revocation and empty-development-profile boundary; no runtime dispatch/live migration. |
| [Bulk Cancellation and Work Preparation](bulk-cancellation-and-work.md) | Whole-root 100000-pair pre-execution revocation, retained adoption, immutable pages, honest local progress and <=16-pair candidate portions; no executor/live migration. |
| [Bulk Attempt Result Journal](bulk-attempt-journal.md) | Explicit pre-send evidence capture, shared completion/deferral/lease/retention hooks and original-root pages; no new admission/dispatch or live migration. |
| [Captured Bulk Cancellation](bulk-captured-cancellation.md) | Optional preservation-checked upgrade, exact RUNNING predecessor waits, immutable shared-result settlement and current status/retention; no dispatcher/live migration. |
| [Bulk Queue Admission and Claim](bulk-queue-admission.md) | Atomic <=16-pair enqueue, distinct default-off shared claim capability, fresh-read barrier, cancellation/results and explicit developer profile; no runtime/lab activation. |
| [Bounded Bulk Refill](bulk-refill-controller.md) | Default-disabled existing-scheduler discovery/refill, 64 checks/16 new jobs, per-device windows, restart/fairness and unknown-evidence holds; no environment/lab activation. |
| [Prepared Import Confirmation](managed-import-confirmation.md) | Gated confirmation/adoption/exclusions, immutable reports and original-key recovery within current 1000-pair policy bounds; no automatic execution/live migration. |
| [Import Cancellation](import-cancellation.md) | Whole-import uncompleted-work revocation, retained additions/adoption, in-flight settlement and immutable receipts; explicit schema, no automatic activation. |
| [Managed Import Web](managed-import-web.md) | Saved preparations, exact review/consent, retained receipts and uncompleted-work cancellation; current capacity/gates and unknown-reply recovery. |
| [Browser Import Review](import-review.md) | Frozen exact-target confirmation, identity/CSRF, bounded ephemeral drafts, same-key retry, default-off admission and rollback. |
| [Managed Shuns](managed-shuns.md) | Registry foundation, lifecycle/storage bounds, standing consent and independently gated restoration. |
| [Standing Managed Policy](managed-grants.md) | Frozen one-pair standing consent, default-off policy-only admission, retries/revocation and unchanged live gates. |
| [Standing Address Lists](managed-batch-grants.md) | Paste/device selection, frozen 100-row review and atomic default-off recurring policy for up to 1000 exact pairs; no immediate commands. |
| [Managed Restoration](managed-restoration.md) | Default-off bounded snapshot discovery/shared dispatch, retained uncertainty/provenance and queue/recovery hooks. |
| [Managed Lifecycle Validation](managed-lifecycle-validation.md) | Integrated synthetic operator acceptance and a concrete, separately approved one-address lab migration/create/restore/retire experiment. |
| [Managed Removal Handoffs](managed-removal-handoffs.md) | Atomic retirement, waiting cleanup, original authorization, ordered settlement and gated admission/worker integration. |
| [Atomic Fleet Removal](managed-fleet-removals.md) | Ready/explicit ordered whole-scope retirement/cleanup, reservation barrier, original deadline, cancellation and gated integration. |
| [Managed Removal Review](managed-removal-review.md) | Frozen device/fleet scopes, default-off confirmation, observational union/CAS and handoff visibility. |
| [Import Admission](import-admission.md) | Default-off private staging, ADD/REMOVE conflicts, immutable occurrence provenance, additive migration and rollback; no executable import. |
| [Import Execution](import-execution.md) | Independent default-off scheduler gate, per-device v3, common FIFO/budgets, priority reads, no-replay recovery and disabled-mode rollout. |
| [One-Address Service Validation](single-address-service-validation.md) | Scoped runbook and recorded one-fixture VERIFIED/NOOP/cleanup evidence, idempotent replay and restored gates; new tests require new approval. |
| [Agent Cycle Protocol](agent-cycle-protocol.md) | Experimental bounded single-session removal/checkpoint protocol, feature gate, limits, and lab/rollback procedure. |
| [Agent Connection Concurrency](agent-concurrency.md) | Opt-in bounded connection workers, device/address guards, fail-closed saturation and unchanged wire/gates; not yet parallel API scheduling. |
| [Local Cycle Settlement](cycle-settlement.md) | Opt-in terminal receipt after cleanup/guard release/worker idle, strict deadlines and no replay/recovery authority; no live activation. |
| [Fenced Device Leases](device-leases.md) | Explicit optional per-device owner/epoch/deadline profile, shared queue fencing, retained expiry attention and legacy-writer exclusion; no runtime/lab activation. |
| [Parallel Device Rounds](parallel-rounds.md) | Default-disabled actual bounded device sessions, shared typed queue/results and cancellation drain; no background/API/lab activation. |
| [Continuous Dispatch](continuous-dispatch.md) | Internal independent lifecycle, continuous work, priority and per-device browser status/demand contract; no API runtime selection or lab activation. |
| [Continuous Runtime Maintenance](continuous-maintenance.md) | Single controller-owned expiry/retention lifecycle, evidence holds, backoff, status and cancellation drain; no lab activation. |
| [Restricted Continuous API](continuous-api.md) | Explicit existing-profile API/BFF composition, lifecycle/compatibility checks and refused unavailable workflows; no environment selector or lab activation. |
| [Version-2 Managed Policy Views](bulk-policy-views.md) | Bounded read-only policy/evidence pages and frozen policy-only stop-maintaining; no creation, combined removal or lab activation. |
| [Version-2 Ready-Scope Removal](bulk-ready-removal.md) | Exact scope and default-off atomic retirement/shared queue admission for ready targets; no lab activation. |
| [Version-2 Removal Confirmation](ready-removal-confirmation.md) | Independent default-off API/Web factory capabilities, frozen ready-only confirmation and admission-not-verification receipts. |
| [Version-2 Ordered-Removal Preflight](bulk-ordered-preflight.md) | Read-only whole-scope readiness/blockers and exact RUNNING-ADD predecessor evidence; no ordered admission or activation. |
| [Version-2 Ordered Reservations](bulk-ordered-reservations.md) | Explicit optional migration, default-off atomic whole-scope retirement/reservation, revocation/expiry and retained predecessors; separate promotion gate, no live activation. |
| [Version-2 Ordered Promotion](bulk-ordered-promotion.md) | Separate default-off whole-scope queue transfer after settled ADDs, attention, original TTL/budgets, strict claims and evidence holds; no live activation. |
| [Version-2 Private Ordered API](ordered-removal-api.md) | Independently gated fixed device/fleet reservation, read-only original-scope/current-job status and owner/Admin revocation; no frozen Web consent or live activation. |
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
