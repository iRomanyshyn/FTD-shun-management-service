# Project Status

Last updated: 2026-10-13

## Current increment

**Foundation / pre-agent implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, and manuals. It is suitable for development, interface work, and security review. It is not yet able to perform a production FTD write because the privileged FTD SSH agent is deliberately absent.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Complete for first increment | Server-rendered UI, role mapping, CSRF protection, and device hostname display. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, and semantic removal endpoints. |
| Local state and audit trail | Complete for first increment | SQLite WAL stores device state and append-only removal events. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, and pinned host keys. |
| Agent boundary | Protocol complete; implementation pending | Strict fixed binary framing is implemented and tested; no privileged SSH agent exists yet. |
| Authentication edge | Complete for first increment | Caddy and Authelia ForwardAuth, beginning with Authelia local users and allowing later LDAP(S) migration. |
| Container layout | Complete for first increment | Only Caddy TCP/443 is published; Web and API use private Unix sockets. |
| Manuals | Complete for first increment | Development, deployment, and operations manuals are present. |

## Explicit limitations

- The Rust privileged FTD SSH agent is not implemented.
- Scheduled polling, FTD command parsing, reconciliation, and real shun collection are not implemented.
- In the supplied Compose configuration, write requests use the agent socket mode and fail closed with a service error until a verified agent is connected.
- External JSON log shipping, Syslog forwarding, metrics, alerting, and production backup automation are not implemented.
- The stack has not yet been exercised against a live FTD lab or production LDAP(S).

## Recent validation

The foundation increment was checked with:

- `python3 -m compileall -q src tests`
- `python3 -m pytest -q` — 7 tests passed
- `python3 -m ruff check .`
- `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config` with temporary local, non-secret configuration

## Next work, in order

1. Implement the isolated privileged FTD SSH agent with pinned host-key verification, a restricted command set, and key lifecycle handling.
2. Add polling, strict FTD output parsing, reconciliation, and fixtures from a controlled lab.
3. Integrate the agent through the fixed Unix-socket protocol and add failure-path integration tests.
4. Add structured external logging, metrics, backups, retention procedures, and operator alerts.
5. Test the full deployment with Caddy TLS, Authelia local users, LDAP(S), and a non-production FTD environment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

