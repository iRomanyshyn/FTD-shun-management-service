# Project Status

Last updated: 2026-10-14

## Current increment

**Foundation / agent-enabled lab implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, manuals, and an isolated privileged agent for verified device-scoped removal. V1 deliberately uses one shared FTD service identity inside that isolated agent; reader/writer separation and one-time key bootstrap are deferred hardening options. The service remains unsuitable for production until it completes FTD lab validation and gains polling/reconciliation.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Complete for first increment | Server-rendered UI, role mapping, CSRF protection, and device hostname display. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, and semantic removal endpoints. Its agent-client timeout exceeds the configured agent operation timeout. |
| Local state and audit trail | Complete for first increment | SQLite WAL stores device state and append-only removal events. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, pinned host keys, and interface allowlists. |
| Agent boundary | Removal implemented and live-lab validated; read operations pending | Rust agent verifies pinned server host keys, authenticates the FTD `Basic` account with a protected password secret, uses a prompt-driven PTY shell, performs only `REMOVE_SHUN`, parses strictly, verifies the resulting state, and emits sanitized structured diagnostics for rejected operations to a bounded Docker log channel. |
| Authentication edge | Complete for first increment | Caddy and Authelia ForwardAuth, beginning with Authelia local users and allowing later LDAP(S) migration. |
| Container layout | Complete for first increment | Only Caddy TCP/443 is published; Web and API use private Unix sockets. The one-shot socket-volume initializer is capability-minimal and prepares ownership/mode for socket and SQLite state volumes before handing them to their service identities. |
| Manuals | Complete for first increment | Development, deployment, and operations manuals are present. |

## Explicit limitations

- Scheduled polling, FTD command parsing, reconciliation, and real shun collection are not implemented.
- A non-production FPR1010 / FTD 7.6.6 lab has validated the observed `show shun` line shape, empty-output case, agent host-key/password/PTY connection, interface-qualified removal, and post-write verification. The successful request used the typed client from the API container; Web/BFF, HTTP API authorization, Caddy, SQLite audit-event creation, and direct post-operation CLI observation still require validation. Production writes are not approved.
- Egress restriction to configured FTD TCP/22 targets and the matching FTD SSH source ACL are mandatory deployment controls, but are environment-specific host/network configuration rather than Compose-enforced policy.
- The original Fedora/`cscotun0` test host could not route its `ftd-management` bridge (`172.18.0.0/16`) to FTD TCP/22. Every deployment host must independently provide and review narrow agent-to-FTD TCP/22 egress and a matching FTD SSH source restriction.
- Agent RPC read operations and threat-detection counters are intentionally rejected until their typed result formats are designed and tested.
- FTD supplies broad `Basic` and `Config` CLI roles rather than a per-command authorization model. The FPR1010 / FTD 7.6.6 lab fixture confirms that `Basic` permits the product's `show shun` and interface-qualified removal; no `Config` account is needed for that supported profile.
- The agent's bounded Docker log is the required local operational channel. Host collection/forwarding to a chosen external JSON log platform, metrics, alerting integration, and production backup automation remain environment-specific and are not implemented by this stack.
- The stack has not yet been exercised against a live FTD lab or production LDAP(S).

## Recent validation

The foundation increment was checked with:

- `python3 -m compileall -q src tests`
- `python3 -m pytest -q` — 11 tests passed
- `python3 -m ruff check .`
- `cargo build --release --locked --manifest-path agent/Cargo.toml`
- `cargo test --locked --manifest-path agent/Cargo.toml` — 4 tests passed
- `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .` — successful; image user is `10002:10001`
- `docker compose --env-file .env -f deploy/compose.yml up -d --build socket-init agent api` — successful with local ignored configuration; the API opened its SQLite/WAL database and Unix socket, and the agent socket is `10002:10001`, mode `0660`
- `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config` with local ignored configuration
- `cargo fmt --manifest-path agent/Cargo.toml -- --check`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` — 8 passed
- `python3 -m pytest -q` — 11 passed; `python3 -m ruff check .`

## Next work, in order

1. Complete the [FTD laboratory validation](manual/ftd-lab-validation.md): validate the Web/BFF and HTTP API workflow, SQLite audit records, direct post-operation FTD observation, and all expected failure modes.
2. Add typed list/read agent responses, strict FTD output parsing, and reconciliation; implement the configurable five-minute baseline poll plus activity-gated interactive refresh with a 60-second global/per-device minimum.
3. Add agent/API failure-path integration tests, including host-key mismatch and private-socket peer checks.
4. Add structured external logging, metrics, backups, retention procedures, and operator alerts.
5. Test the full deployment with Caddy TLS, Authelia local users, LDAP(S), and a non-production FTD environment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

