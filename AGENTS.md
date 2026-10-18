# Repository Working Agreement

This repository is an English-language product repository. Write source code, documentation, commit messages, configuration comments, and operator-facing text in English unless a user explicitly requests a translation.

## Source of truth

Read these documents before making a material change:

1. [`docs/architecture-and-security-design.md`](docs/architecture-and-security-design.md) is the normative architecture and security specification.
2. [`docs/project-status.md`](docs/project-status.md) records what is implemented, intentionally unavailable, and next.
3. [`docs/development-log.md`](docs/development-log.md) is the chronological engineering record.
4. [`docs/manual/`](docs/manual/README.md) contains contributor, deployment, and operator procedures.

If an implementation conflicts with the architecture document, stop and resolve the design before continuing. Do not silently weaken the security model to make a feature easier to implement.

## Required development records

Keep the written project record current. For every material change to code, security controls, deployment, data schema, API or agent protocol, authentication, or operating procedure:

- update `docs/project-status.md` to reflect the new current state;
- append a dated entry to `docs/development-log.md` describing the change, validation performed, and known limitations or follow-up work; and
- update the relevant manual and architecture document when their instructions or design guarantees changed.

Do not rewrite historical log entries except to correct an objective error; add a correction entry instead. Small spelling-only edits do not need a log entry.

## Security invariants

- The product exposes semantic operations only. Never add arbitrary Cisco CLI, command strings, free-form device routes, or unvalidated protocol fields.
- Keep FTD SSH credentials exclusively in the privileged agent. The web and API services must never receive them.
- Preserve the fixed binary Unix-socket protocol and its exact length/range validation. A successful state change requires a verified agent success response; otherwise fail closed.
- Caddy must remove client-supplied `Remote-*` headers and set trusted identity headers only after successful Authelia ForwardAuth. The Web/BFF may trust these headers only on its private Caddy Unix socket.
- Do not publish Web, API, database, Authelia, or agent ports. Caddy is the sole external listener.
- Development authentication headers and mock-agent mode are local-development tools only; they must not be enabled in a deployed environment.
- Do not commit `.env`, Authelia user files, device inventory files, private keys, secrets, database files, or production logs. Use the tracked example files instead.

## Implementation and validation

- While working on the current non-production lab stack, the operator authorizes
  deployment of validated, in-scope changes without a separate confirmation for
  each release (2026-10-16). Announce the affected services and operational impact,
  preserve rollback options, and record deployment checks. API restarts may
  execute already admitted queue/policy work. This does not authorize production
  rollout, new test mutations/bulk imports, destructive data changes or bypassing
  feature-specific validation/security gates. Reconfirm if the target environment
  is unclear or changes beyond the current lab.
- Prefer small, reviewable changes and preserve existing user work in a dirty tree.
- Use parameterized SQLite access and retain audit events as append-only records.
- Document migration, backup, rollback, and operational impact when changing schemas or deployment configuration.
- For Python changes, run at least:

  ```bash
  python3 -m compileall -q src tests
  python3 -m pytest -q
  python3 -m ruff check .
  git diff --check
  ```

- For agent changes, also run:

  ```bash
  cargo build --release --locked --manifest-path agent/Cargo.toml
  cargo test --locked --manifest-path agent/Cargo.toml
  ```

- Validate Compose changes with `docker compose --env-file .env -f deploy/compose.yml config` using temporary, non-secret local configuration. Do not commit that configuration.
- Live evidence covers device-scoped removal and the separately approved one-address ADD/v3 creation/no-op/cleanup recorded on 2026-10-16. All ADD gates remain default-off and were restored off after that experiment. Traffic, fleet creation scope, large-load and production acceptance remain pending. Default-off implementation/deployment does not authorize new device mutations or general enablement. Do not present either write path, mock mode or socket transport as production-ready.
- On 2026-10-17 the operator requested restoring service-managed manual shuns
  after confirmed disappearance. The managed-shun architecture amendment and
  design manual replace the former one-time-only target requirement, not the
  current implementation. Restoration needs explicit durable/revocable desired
  policy, protection priority and atomic retirement on service removal. Do not
  convert old imports/history into standing authority, renew expired user
  requests or replay uncertain ADD. The isolated registry foundation is now
  implemented; optional read-only API/UI visibility does not initialize or
  authorize policy. Single-target/fleet cleanup now have default-off admission;
  its optional waiting-cleanup schema is not initialized by startup. Read-only
  visibility/review preparation never invoke admission. Confirmation requires
  the independent default-off `FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED` gate,
  socket mode/shared cleanup worker and explicit
  existing schemas. All live gates remain off. Follow docs/manual/managed-cleanup.md.
  Exact single intent/generation and full frozen fleet scope are rechecked;
  ready-only never silently becomes ordered waiting. Separate frozen
  fleet reviews read the observed/enabled-managed union with a transactional
  scope-comparison prerequisite. An offline ready-target fleet coordinator now
  retires enabled targets and admits one whole-scope REMOVE transaction; it
  rejects any unfinished ADD/waiting cleanup/disabled device without changes.
  A separately digested explicit ordered mode now reserves the whole scope
  behind captured RUNNING ADDs, preserving original deadlines and uncertainty;
  QUEUED one-time ADD still conflicts. Its optional retained authority/barrier
  tables are never initialized by startup. Strict fixed device/fleet private
  admission routes use those coordinators; no arbitrary action/scope. A default-off
  shared worker advances at most eight single/eight fleet roots before cutoff;
  no second executor or partial root promotion. Never simulate atomic fleet
  writes by looping over the single-target coordinator. Separate
  policy-only RETIRE and owner/Administrator waiting-cleanup cancellation are
  supported local revocation controls; neither admits device work nor cancels
  independent one-time jobs or a RUNNING ADD. A separate frozen single-pair
  standing grant now has default-off policy-only MAINTAIN admission behind
  `FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED=false`, requiring explicit consent,
  profiles and existing optional registry/attempt schemas. It never migrates,
  adopts observations/imports, wakes work or clears attention. Old-key replay
  cannot re-enable policy. Follow docs/manual/managed-grants.md. No HTTP resume route.
  Separate offline managed maintenance now supports reviewed atomic empty-schema
  initialization and existing-policy resume, with checked backups, exact-state
  five-minute digests and a fresh-read barrier. It never adopts observations,
  resets uncertainty, creates/re-enables intent, renews requests, queues work or
  changes gates. Never invoke migration/resume on the lab without separately
  scoped activation approval. Follow docs/manual/managed-maintenance.md.
  Protected-IP weakening checks matching intents and reviewed managed revision/
  acknowledgement atomically; dirty forms retain that revision. Unknown optional
  state is not zero. Ordinary manual removal is guarded against enabled policy,
  including missing fleet targets, and MAINTAIN rejects pending/running removal.
  Protected automatic removal remains independent. An offline system restoration
  source now binds fresh complete snapshots, intent/generation/authorization and
  retained attempts to shared jobs without fake user roles/imports. Claim has a
  separate default-false capability supplied only by the experimental restoration
  controller. `FTD_SHUN_MANAGED_RESTORATION_ENABLED=false` remains the default;
  enabling it also requires API ADD/cycles/large reads and explicit profiles,
  existing optional schemas and unsuspended standing policy. Discovery uses only
  complete successful fresh reads, bounds new work to 16 jobs/64 checks per sweep,
  and never bypasses the frozen cutoff or >=60s cooldown. Startup/GET never
  migrate, adopt or admit. All live gates remain off. Retirement/
  protection cancel unstarted system ADD atomically; RUNNING remains ordered.
  FAILED/UNVERIFIED latches survive queue retention and new generations; no rearm
  or HTTP resume route exists. Offline resume refuses those latches; standing
  admission remains disabled in the lab. No startup initializes its
  optional attempt ledger. Follow docs/manual/managed-restoration.md; do not
  seed the ledger or enable dispatch/discovery in the lab as a smoke shortcut.
  Follow docs/manual/managed-controls.md. A default-off cleanup-worker hook may advance
  existing waits under the shared lease before its cycle cutoff; it does not
  enable admission, ADD or restoration and never initializes optional schemas.
  Composite offline recovery now provides a durable mutation pause and ordinary
  resume only. Older images ignore that pause; follow docs/manual/recovery.md.
  Do not seed pending handoffs or enable the worker in the lab without scoped
  approval and remaining executable controls/protection/fleet validation. All live gates
  remain off; bounded fleet status and waiting-only Web revocation are available,
  but combined admission stays disabled. Offline migration/resume tooling is
  implemented, not invoked in the lab; uncertainty resolution and separately
  approved migration/policy activation/live fixtures are still required.
- On 2026-10-16 the operator separately approved the one-address service
  experiment on lab device 1/fpr1010-lab: unused TEST-NET 198.51.100.251,
  temporary gate/profile enablement for that device only, one queued creation,
  already-present/no-op verification and device-scoped cleanup, then restore
  ADD-disabled operation. Fresh Basic-session absence was supplied. Use an
  explicitly labelled trusted-host maintenance actor, not spoofed Web identity;
  cleanup may use the same private queued API. This is a bounded CLI-lifecycle
  validation exception, not approval for a long list, unrelated IPs, production,
  data-plane changes, arbitrary CLI or leaving ADD enabled. Stop on unexpected
  pre-existing/scope state; retain uncertainty without automatic replay.
  The experiment is now complete: VERIFIED creation, NOOP, VERIFIED cleanup,
  original-key replay without re-add and restored disabled-mode observation.
  Its one-fixture authorization is consumed, not reusable for new writes.

