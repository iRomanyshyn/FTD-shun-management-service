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
- Keep the future FTD SSH key and FTD credentials exclusively in the privileged agent. The web and API services must never receive them.
- Preserve the fixed binary Unix-socket protocol and its exact length/range validation. A successful state change requires a verified agent success response; otherwise fail closed.
- Caddy must remove client-supplied `Remote-*` headers and set trusted identity headers only after successful Authelia ForwardAuth. The Web/BFF may trust these headers only on its private Caddy Unix socket.
- Do not publish Web, API, database, Authelia, or agent ports. Caddy is the sole external listener.
- Development authentication headers and mock-agent mode are local-development tools only; they must not be enabled in a deployed environment.
- Do not commit `.env`, Authelia user files, device inventory files, private keys, secrets, database files, or production logs. Use the tracked example files instead.

## Implementation and validation

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
- The FTD SSH agent currently supports only lab-validated, device-scoped removal. Do not present it, mock mode, or the socket transport as production-ready write capability until live FTD validation is documented.

