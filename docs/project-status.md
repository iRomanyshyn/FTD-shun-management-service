# Project Status

Last updated: 2026-10-13

## Current increment

**Foundation / agent-enabled lab implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, manuals, and an isolated privileged agent for verified device-scoped removal. It remains unsuitable for production until it completes FTD lab validation and gains polling/reconciliation.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Complete for first increment | Server-rendered UI, role mapping, CSRF protection, and device hostname display. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, and semantic removal endpoints. |
| Local state and audit trail | Complete for first increment | SQLite WAL stores device state and append-only removal events. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, pinned host keys, and interface allowlists. |
| Agent boundary | Removal implemented; read operations pending | Rust agent verifies pinned host keys, performs only `REMOVE_SHUN`, parses strictly, and verifies the resulting state. |
| Authentication edge | Complete for first increment | Caddy and Authelia ForwardAuth, beginning with Authelia local users and allowing later LDAP(S) migration. |
| Container layout | Complete for first increment | Only Caddy TCP/443 is published; Web and API use private Unix sockets. |
| Manuals | Complete for first increment | Development, deployment, and operations manuals are present. |

## Explicit limitations

- Scheduled polling, FTD command parsing, reconciliation, and real shun collection are not implemented.
- The supplied agent has not been exercised against a live FTD lab; production writes are not approved.
- Agent RPC read operations and threat-detection counters are intentionally rejected until their typed result formats are designed and tested.
- External JSON log shipping, Syslog forwarding, metrics, alerting, and production backup automation are not implemented.
- The stack has not yet been exercised against a live FTD lab or production LDAP(S).

## Recent validation

The foundation increment was checked with:

- `python3 -m compileall -q src tests`
- `python3 -m pytest -q` — 11 tests passed
- `python3 -m ruff check .`
- `cargo build --release --locked --manifest-path agent/Cargo.toml`
- `cargo test --locked --manifest-path agent/Cargo.toml` — 4 tests passed
- `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .` — successful; image user is `10002:10001`
- `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config` with temporary local, non-secret configuration

## Next work, in order

1. Run the removal agent against a controlled FTD lab, recording sanitized command fixtures and all expected failure modes.
2. Add typed list/read agent responses, polling, strict FTD output parsing, and reconciliation.
3. Add agent/API failure-path integration tests, including host-key mismatch and private-socket peer checks.
4. Add structured external logging, metrics, backups, retention procedures, and operator alerts.
5. Test the full deployment with Caddy TLS, Authelia local users, LDAP(S), and a non-production FTD environment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

