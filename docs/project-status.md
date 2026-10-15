# Project Status

Last updated: 2026-10-15

## Current increment

**Agent-enabled polling, reconciliation, and trusted-IP policy lab implementation.** The repository provides the secured management-plane skeleton, local state, UI workflows, deployment layout, manuals, and an isolated privileged agent. V1 deliberately uses one shared FTD service identity inside that isolated agent; reader/writer separation and one-time key bootstrap are deferred hardening options. The service remains unsuitable for production until it completes the expanded FTD lab validation.

The [Development Plan](development-plan.md) records the approved next direction:
implemented cycle-based freshness plus a planned durable multi-user queue, device changes and
refresh in one bounded cycle no more than once per minute, and one-time manual
blocklist imports with recorded provenance. The plan also includes shared queue
progress and a coalesced interactive snapshot at the next safe checkpoint of
a running import, using the existing session and rate/budget limits. Queue/import work remains planning only; current
removals still dispatch immediately, the current agent opens a session per
operation, and no addition/import or durable queue is implemented.

## Delivered

| Area | Status | Notes |
| --- | --- | --- |
| Architecture and security design | Complete | Defines the trust boundaries, device model, state model, and fixed agent protocol. |
| Web/BFF | Authenticated UI removal live validated; revised refresh flow tested locally in Chromium, deployment pending | Server-rendered search, Protected-IP markers, history/events, and timezone labels are preserved. Refresh now uses process/cycle/data revisions, a single sequential browser request loop, coalesced active-sweep hints, per-device freshness, error backoff, and dynamic state updates preserving search, confirmation input/focus, scroll, and expanded history. Local browser regression scenarios cover slow responses, multiple tabs, repeated errors, network recovery, API restart, and failed POST/retry. |
| Internal API | Complete for first increment | Unix-socket-only FastAPI service with state, history, bounded local IP-history search, an immediate scheduler-state refresh-hint response, and semantic removal endpoints. Its agent-client timeout exceeds the configured agent operation timeout. |
| Local state and audit trail | Snapshot reconciliation, trusted-policy audit, and configurable retention implemented | SQLite WAL atomically reconciles complete successful device snapshots and retains append-only detection, reappearance, disappearance, manual-removal, and trusted-IP policy events within a configurable 366-day default retention window. |
| Device inventory | Complete for first increment | Static JSON validates numeric IDs, hostnames, management addresses, pinned host keys, and interface allowlists. |
| Agent boundary | Typed snapshot and removal live-lab validated | Rust agent verifies pinned server host keys, authenticates the FTD `Basic` account with a protected password secret, uses a prompt-driven PTY shell, performs only source-defined `LIST_SHUNS` and `REMOVE_SHUN`, parses strictly, verifies writes, and emits sanitized structured diagnostics for rejected operations to a bounded Docker log channel. |
| Synchronizer and freshness | Revision/coalescing regression tests passed; prior agent/API/SQLite lab validation retained | Each completed sweep publishes a cycle revision including repeated identical errors and partial fleet results; committed observations/mutations publish a data revision. Instance IDs distinguish restarts. Concurrent hints join queued/running sweeps without leaving extra work. The existing baseline, cooldown, and trusted-IP policy remain; durable mutation queuing and single-session batch cycles are still pending. |
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

1. Deploy and verify the locally tested revision-based refresh increment through the authenticated Caddy/Authelia stack, including a real baseline interval and per-device failures. The automated Python and Chromium scenarios for slow devices, repeated failures, partial success, multiple tabs, preserved input, and restarts now pass against local fixtures.
2. Design and implement the shared durable operation queue and one-minute device-cycle gate, including idempotency, conflicts, cancellation, bounded batches, restart recovery, and migration of existing removals and trusted-policy work. Expose queue progress and support coalesced priority refresh at safe checkpoints, with independent snapshot revisions and bounded fair scheduling.
3. Design and lab validate the typed single-session cycle/batch protocol and narrow addition capability before enabling the paste/preview/manual-import workflow. Record manual provenance in SQLite and structured logs; removed imported entries must never be automatically re-added. Follow the [Development Plan](development-plan.md) for acceptance criteria.
4. Complete the [FTD laboratory validation](manual/ftd-lab-validation.md), including direct post-operation observation, baseline behavior, queue load/concurrency, trusted-policy failures, host-key mismatch, private-socket checks, and snapshot rejection. Production writes remain unapproved.
5. Add structured external logging, metrics, backup automation, and operator alerts; validate TLS, Authelia local users, LDAP(S), and the complete non-production deployment.

## Record-keeping rule

This file is a required part of delivery. Update it whenever a material implementation, security, deployment, schema, authentication, protocol, or operational state changes. Append the corresponding dated entry to [`development-log.md`](development-log.md).

