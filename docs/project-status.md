# Project Status

Last updated: 2026-10-14

## Current increment

**Agent-enabled polling, reconciliation, and trusted-IP policy lab implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, manuals, and an isolated privileged agent. V1 deliberately uses one shared FTD service identity inside that isolated agent; reader/writer separation and one-time key bootstrap are deferred hardening options. The service remains unsuitable for production until it completes the expanded FTD lab validation.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Authenticated UI removal live validated; unified search/events refinement implemented, deployment pending | Server-rendered UI, role mapping, CSRF protection, device hostname display, and an agent-verified single-device removal were exercised. The primary page supports server-side bounded local IPv4 prefix search across active state and retained history, clear current-versus-historical presentation, Protected-IP matches, a cooldown-aware refresh request, browser-local timestamps, and a collapsed 100-event local audit view. The BFF waits beyond the bounded API/agent timeout and fails closed with a controlled `503` if no result is returned. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, bounded local IP-history search, refresh hints, and semantic removal endpoints. Its agent-client timeout exceeds the configured agent operation timeout. |
| Local state and audit trail | Snapshot reconciliation, trusted-policy audit, and configurable retention implemented | SQLite WAL atomically reconciles complete successful device snapshots and retains append-only detection, reappearance, disappearance, manual-removal, and trusted-IP policy events within a configurable 366-day default retention window. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, pinned host keys, and interface allowlists. |
| Agent boundary | Typed snapshot and removal live-lab validated | Rust agent verifies pinned server host keys, authenticates the FTD `Basic` account with a protected password secret, uses a prompt-driven PTY shell, performs only source-defined `LIST_SHUNS` and `REMOVE_SHUN`, parses strictly, verifies writes, and emits sanitized structured diagnostics for rejected operations to a bounded Docker log channel. |
| Synchronizer and freshness | Agent/API/SQLite lab validated; trusted-policy success observed | The API made successful non-empty startup sweeps, reconciled records, emitted detection events, supplied freshness metadata, and rate-limited an immediate interactive hint. It gives an imminent scheduled baseline precedence over a redundant manual refresh within the configured interactive interval. The optional exact-IPv4 trusted-IP policy runs only after a complete successful snapshot. One configured match has completed through the agent's verified-removal path and is recorded in SQLite; the live failure path and independent direct FTD confirmation remain outstanding. |
| Authentication edge | Header-order repair implemented; end-to-end interactive retest pending | Caddy and Authelia ForwardAuth use protected read-only configuration mounts. A literal-order Caddy `route` removes browser-supplied identity headers before ForwardAuth copies authenticated values to Web/BFF. Authelia runs as the owner of the protected local user file, while a one-shot networkless initializer with only `CHOWN` prepares its SQLite volume. Non-secret templates are explicitly enabled; the in-image healthcheck metadata writer is disabled to preserve the main process's read-only root filesystem and no-Linux-capability boundary. The local file backend disables self-service password mutations. LDAP(S) remains a future migration. |
| Workstation browser lab | Authenticated UI and manual removal live validated | A separate Compose overlay provides Caddy Internal CA for local `.test` names and preserves Authelia ForwardAuth without requiring internal DNS. The authenticated browser path reached the API and completed an agent-verified removal; the new search and freshness copy require a browser retest after deployment. |
| Container layout | Complete for first increment | Only Caddy TCP/443 is published; Web and API use private Unix sockets. The one-shot socket-volume initializer is capability-minimal and prepares ownership/mode for socket and SQLite state volumes before handing them to their service identities. |
| Manuals | Complete for first increment | Development, deployment, and operations manuals are present. |

## Explicit limitations

- A non-empty typed snapshot has been collected through the isolated agent and reconciled into SQLite against the live FPR1010. The five-minute recurring baseline still needs elapsed-time validation. The browser freshness state is only as current as the most recent successful sweep.
- A non-production FPR1010 / FTD 7.6.6 lab has validated the observed `show shun` line shape, empty-output case, agent host-key/password/PTY connection, interface-qualified removal, and post-write verification. The successful request used the typed client from the API container; Web/BFF, HTTP API authorization, Caddy, SQLite audit-event creation, and direct post-operation CLI observation still require validation. Production writes are not approved.
- Egress restriction to configured FTD TCP/22 targets and the matching FTD SSH source ACL are mandatory deployment controls, but are environment-specific host/network configuration rather than Compose-enforced policy.
- The original Fedora/`cscotun0` test host could not route its `ftd-management` bridge (`172.18.0.0/16`) to FTD TCP/22. Every deployment host must independently provide and review narrow agent-to-FTD TCP/22 egress and a matching FTD SSH source restriction.
- `GET_SHUN` and the threat-detection counter operations remain intentionally rejected until their distinct typed result formats are designed and tested.
- FTD supplies broad `Basic` and `Config` CLI roles rather than a per-command authorization model. The FPR1010 / FTD 7.6.6 lab fixture confirms that `Basic` permits the product's `show shun` and interface-qualified removal; no `Config` account is needed for that supported profile.
- The agent's bounded Docker log is the required local operational channel. Host collection/forwarding to a chosen external JSON log platform, metrics, alerting integration, and production backup automation remain environment-specific and are not implemented by this stack.
- The full local Caddy/Authelia/Web/API path has exercised an agent-verified removal against the live FTD lab. It does not replace a direct post-operation FTD observation, recurring-baseline validation, production TLS, or LDAP(S) validation.
- The trusted-IP automatic-removal policy is disabled by default and must be tested with a dedicated non-production address before it is enabled for any office or other trusted egress address. The current local lab configuration contains two configured exact addresses; a startup snapshot recorded one agent-verified policy removal. Direct FTD confirmation and a live fail-closed policy test remain required. The policy applies to every enabled device by design.

## Recent validation

The foundation increment was checked with:

- `python3 -m compileall -q src tests`
- `python3 -m pytest -q` — 22 tests passed
- `python3 -m ruff check .`
- `cargo build --release --locked --manifest-path agent/Cargo.toml`
- `cargo test --locked --manifest-path agent/Cargo.toml` — 10 tests passed
- `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .` — successful; image user is `10002:10001`
- `docker compose --env-file .env -f deploy/compose.yml up -d --build socket-init agent api` — successful with local ignored configuration; the API opened its SQLite/WAL database and Unix socket, and the agent socket is `10002:10001`, mode `0660`
- `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config` with local ignored configuration
- `cargo fmt --manifest-path agent/Cargo.toml`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` — 10 passed
- `python3 -m compileall -q src tests`; `python3 -m pytest -q` — 29 passed; `python3 -m ruff check .`; `git diff --check`
- `docker compose --env-file .env -f deploy/compose.yml config --quiet` and the merged local-browser overlay configuration — successful
- Rebuilt/recreated local API and Web/BFF with an empty trusted-IP policy; private API status reported `trusted_auto_remove_ip_count: 0` and the normal startup snapshot completed without error.
- The policy-status additions passed `python3 -m compileall -q src tests`, `python3 -m pytest -q` (31 passed), `python3 -m ruff check .`, and `git diff --check`.
- Rebuilt/recreated local API and Web/BFF after the explicit operator approval. The private API reported a successful refresh, 366-day retention with no error, and a trusted-policy request followed by one verified removal; active local state was empty afterward.

## Next work, in order

1. Complete the [FTD laboratory validation](manual/ftd-lab-validation.md): deploy and validate the unified search, cooldown-backed refresh control, 100-event view, five-minute baseline, SQLite removal audit records, direct post-operation FTD observation, the trusted-IP policy, and all expected failure modes.
2. Add agent/API failure-path integration tests, including host-key mismatch, private-socket peer checks, and snapshot rejection.
3. Add structured external logging, metrics, backup automation, and operator alerts.
4. Test the full deployment with Caddy TLS, Authelia local users, LDAP(S), and a non-production FTD environment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

