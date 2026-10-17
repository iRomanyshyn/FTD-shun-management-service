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
  authorize policy. All live gates
  remain off; UI/queue integration, reviewed migration and a separately approved
  live fixture are still required.
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

