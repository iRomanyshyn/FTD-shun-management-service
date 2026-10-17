# Development Log

This is the chronological engineering record for material work in this repository. New entries are appended, never silently substituted for earlier decisions. Each entry should include the date, scope, validation, and remaining risk or follow-up.

## 2026-10-13 — Foundation implementation and operational documentation

**Status:** In progress

Implemented the first management-plane increment: the FastAPI Web/BFF and Unix-socket API, SQLite WAL state and audit history, validated static device inventory, semantic removal workflows, CSRF protection, and the fixed binary future-agent protocol. Added Caddy and Authelia deployment assets, local-user authentication with a documented LDAP(S) migration path, and structured development, deployment, and operations manuals.

The design supports multiple FTD devices using one shared FTD service account/key while retaining per-device IDs, display hostnames, management addresses, and pinned host keys. The user interface displays device hostnames and supports a device-specific removal or an explicitly confirmed removal across all matching devices.

**Validation:** `python3 -m compileall -q src tests`; `python3 -m pytest -q` (7 passed); `python3 -m ruff check .`; `git diff --check`; Compose configuration rendered with temporary non-secret local configuration.

**Known limitations:** No privileged Rust FTD SSH agent, polling, FTD output parsing, real reconciliation, external log shipping, metrics, or live FTD/LDAP(S) integration exists yet. Production write operations intentionally fail closed until the agent is implemented and returns a verified response.

## 2026-10-13 — Privileged removal agent

**Status:** In progress; laboratory validation required

Added the Rust `ftd-shun-agent` and deployed it as the sole component with a route to FTD management. It listens on a private `AF_UNIX/SOCK_SEQPACKET` socket, checks the API peer UID, rejects unknown/malformed RPC requests, and exposes only the typed `REMOVE_SHUN` operation. For each removal it pins the server host key, uses the configured public-key identity, reads the target `show shun <IPv4>` state, permits only configured interface names, issues `no shun <IPv4> interface <name>`, then reads the target state again before returning success. The Compose stack now supplies the credential as a protected runtime secret and gives the agent no persistent writable volume.

**Validation:** `cargo build --release --locked --manifest-path agent/Cargo.toml`; `cargo test --locked --manifest-path agent/Cargo.toml` (4 passed); `python3 -m compileall -q src tests`; `python3 -m pytest -q` (11 passed); `python3 -m ruff check .`; `docker compose --env-file .env -f deploy/compose.yml config` with temporary non-secret configuration; `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .` (image runs as UID/GID `10002:10001`); `git diff --check`.

**Known limitations:** The agent does not yet provide list/read responses, polling, reconciliation, structured external logging, or metrics. It has not yet been tested against an FTD lab; both CLI behavior and parser fixtures must be verified there before enabling production writes.

## 2026-10-13 — V1 simplicity decision and agent hardening

**Status:** In progress; laboratory validation required

Recorded the v1 decision to use one fleet-wide FTD service account/key inside the isolated agent. Reader/writer account separation and a one-time credential bootstrap remain deferred hardening options rather than release prerequisites. V1 removal uses a short-lived SSH connection per request; no persistent reader connection exists until polling is implemented and validated. Replaced the agent's private generic command-string execution primitive with a private `CiscoOperation` enum, so only source-defined typed operations can reach SSH. Marked the server-rendered CSRF cookie `HttpOnly`; the token remains available in the rendered form and is compared server-side.

**Validation:** `python3 -m compileall -q src tests`; `python3 -m pytest -q` (11 passed); `python3 -m ruff check .`; `cargo test --locked --manifest-path agent/Cargo.toml` (4 passed).

**Known limitations:** Docker Compose alone does not provide the required FTD egress ACL. Deployment still requires an environment-specific host/network policy and matching FTD SSH source restriction.

## 2026-10-13 — Polling and interactive-refresh policy

**Status:** Design recorded; implementation pending

Set the future baseline `show shun` polling default to five minutes and made it configurable. Authenticated UI state views may request a background refresh, but UI/API traffic must never open SSH directly or wait for Cisco output. The synchronizer will accept at most one interactive refresh sweep per 60 seconds globally and will enforce the same minimum interval per device. Interactive refreshes are considered only while there is Web/BFF activity. The UI will show last-successful refresh, a baseline countdown, and whether a refresh is idle, queued, or rate-limited.

**Validation:** Documentation-only design update; implementation is intentionally deferred until typed list/read agent responses and FTD parser fixtures exist.

**Known limitations:** The current agent rejects read operations and no synchronizer or freshness UI exists yet.

## 2026-10-13 — FTD lab-validation milestone

**Status:** Ready for operator input

Added a structured laboratory procedure for validating the current removal agent, collecting sanitized `show shun` parser fixtures, and recording fail-closed outcomes. This is the required gate before adding typed list/read RPC, polling, reconciliation, or the freshness UI.

**Validation:** Documentation-only update; `git diff --check` must pass with the associated change.

**Known limitations:** The next step requires a controlled FTD lab, approved network/source restrictions, and sanitized CLI output supplied by an operator.

## 2026-10-13 — FPR1010 CLI parser fixture

**Status:** Partial laboratory evidence recorded

Recorded a sanitized direct CLI fixture from a non-production Cisco Firepower 1010 Threat Defense 7.6.6 (Build 115). A temporary `198.51.100.250` shun was created and removed successfully. `show shun` returned `shun (management) 198.51.100.250 0.0.0.0 0 0 0`; after removal it returned no entries. Added this exact observed format as an agent parser unit test. The validated CLI-facing interface name is `management`, which must be the value included in the device's `allowed_interfaces` when this lab device is configured.

**Validation:** Direct operator-provided FTD CLI transcript; `cargo test --locked --manifest-path agent/Cargo.toml` remains required after the test addition.

**Known limitations:** This was a direct CLI test of the non-interface-qualified removal form. It does not yet demonstrate that FTD accepts the agent's `no shun <IPv4> interface management` command, nor does it exercise SSH host-key pinning, the agent socket, API, or Web/BFF.

## 2026-10-13 — FPR1010 interface-qualified removal confirmation

**Status:** Direct CLI syntax validation complete

The same non-production FPR1010 lab successfully removed a temporary TEST-NET-2 shun with the exact command form generated by the agent: `no shun 198.51.100.250 interface management`. A following `show shun` was empty. This closes the CLI-syntax portion of lab validation for the supported FTD 7.6.6 fixture.

**Validation:** Direct operator-provided FTD CLI transcript; `cargo test --locked --manifest-path agent/Cargo.toml` passed with 5 tests, including the recorded FPR1010 parser fixture; `git diff --check` passed.

**Known limitations:** This does not exercise SSH authentication or host-key pinning, the private agent socket, API, Web/BFF, audit trail, or deployment-level FTD source/egress restriction.

## 2026-10-13 — FTD CLI-role constraint recorded

**Status:** Laboratory check required before credential provisioning

Reviewed the current Cisco FTD command reference for version 7.6. It supports local-user SSH public keys through `configure ssh pubkeys add`, including FTD 7.6, but exposes broad `Basic` and `Config` roles rather than an application-specific command allowlist. The deployment and lab manuals now require a `Basic`-role removal test before any promotion to `Config`; a Config account would be a documented residual risk, not an assumed least-privilege control.

**Validation:** Official Cisco current command reference reviewed; `git diff --check` remains required after the documentation update.

**Known limitations:** The required `Basic`-role test on the FPR1010 is pending. Key-based agent authentication, host-key pinning, and full-path operation remain untested.

## 2026-10-13 — FPR1010 Basic-role removal validation

**Status:** Least-role laboratory validation complete for FTD 7.6.6

A newly created local `Basic` user (`ftd-shun-lab`) on the non-production FPR1010 successfully logged in, displayed the temporary TEST-NET-2 shun, removed it with `no shun 198.51.100.250 interface management`, and observed an empty `show shun` result. The FTD forced the account's initial password change as expected. The product profile now requires `Basic` for this supported fixture and prohibits an unnecessary `Config` account.

**Validation:** Direct operator-provided FTD SSH transcript; `git diff --check` remains required after the documentation update.

**Known limitations:** SSH public-key setup for the Basic service account, pinned server-host-key collection, the agent socket, API/Web flow, audit events, and source/egress restriction remain untested.

## 2026-10-13 — FTD Basic-account key-provisioning procedure

**Status:** Procedure recorded; operator execution pending

Added an explicit deployment procedure for a non-interactive ECDSA P-384 key owned by the Compose host and installed through `configure ssh pubkeys add` while logged in as the dedicated `Basic` FTD user. The procedure verifies key login against an already verified server host key and prohibits treating `ssh-keyscan` output as identity proof. It also documents why the agent's current non-interactive key requires an empty passphrase and which isolation controls compensate for that limitation.

**Validation:** Documentation reviewed against the Cisco FTD 7.6 command reference; `git diff --check` remains required.

**Known limitations:** The FPR1010 service-account key, FTD server-host-key pin, agent socket, API/Web flow, audit events, and source/egress restriction remain untested.

## 2026-10-13 — FTD Basic-account password authentication

**Status:** Implemented; laboratory integration validation pending

The FPR1010 `Basic` service account rejected `configure ssh pubkeys add`; that command requires a privileged FTD user and cannot be used to attach a key to the least-privileged service identity. Replaced agent public-key authentication with SSH password authentication backed by a Docker secret (`ftd_ssh_password`). The password is read into a zeroizing buffer only for connection setup, then dropped before Cisco commands run. The agent still strictly pins the FTD server host key, has the only management-network route, and accepts only fixed semantic operations. Updated Compose, architecture, deployment, lab, and operations documentation to make the supported `Basic` + password profile explicit. The prior key-provisioning entry remains as an historical investigation and is superseded by this entry.

**Validation:** `russh` 0.63.3 password-authentication API inspected locally; implementation tests and Compose validation are required after this change.

**Known limitations:** The new password-authentication agent path, FTD server-host-key pin, agent socket, API/Web flow, audit events, and source/egress restriction have not yet been tested against the FPR1010.

## 2026-10-13 — Password-authentication implementation validation

**Status:** Local implementation validation complete; FTD integration pending

Validated the agent's password-secret configuration and retained its strict fixed-operation and pinned-server-key design. Temporary ignored configuration with a dummy password secret rendered successfully through Docker Compose and was removed immediately after validation.

**Validation:** `cargo test --locked --manifest-path agent/Cargo.toml` (5 passed); `python3 -m pytest -q` (11 passed); `python3 -m ruff check .`; `docker compose --env-file .env -f deploy/compose.yml config` with temporary local non-secret configuration; `git diff --check`. The Rust formatting component is not installed in this environment, so `cargo fmt --check` could not run.

**Known limitations:** The FPR1010 password-authentication path, server-host-key pin, agent socket, API/Web flow, audit events, and source/egress restriction remain untested.

## 2026-10-13 — FPR1010 interactive-shell compatibility

**Status:** Prompt-driven agent support implemented; FTD integration pending

The FPR1010 accepted password authentication only through an interactive SSH PTY/shell workflow; a direct SSH `exec` request reached the login path but failed before executing `show shun`. A manual `ssh -tt` session reached the FTD `>` prompt after its approximately 1.5-second banner. Replaced the agent's `exec`-channel implementation with a PTY/shell driver that waits for the prompt, sends a typed fixed command, then waits for the next prompt. It strips only the expected command echo and prompt envelope. No fixed sleep is used; EOF, an unexpected prompt, invalid output, oversized output, unexpected removal output, and timeout fail closed.

**Validation:** `cargo fmt --manifest-path agent/Cargo.toml` followed by `cargo fmt --manifest-path agent/Cargo.toml -- --check`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` (8 passed); `python3 -m pytest -q` (11 passed); `python3 -m ruff check .`; `docker build -f agent/Dockerfile -t ftd-shun-agent:local-verify .`; `git diff --check`.

**Known limitations:** The complete password-authentication plus prompt-driven agent path, server-host-key pin, agent socket, API/Web flow, audit events, and source/egress restriction remain untested against the FPR1010.

## 2026-10-13 — Socket-volume initializer capability fix

**Status:** Local Compose IPC and persistence validation complete; FTD integration remains pending

The first minimal Compose startup exposed a least-privilege ordering defect in `socket-init`: after transferring `/agent` to UID/GID `10002:10001`, the intentionally capability-restricted initializer could no longer change its mode. The initializer now temporarily returns `/agent` to root ownership, sets mode `0770`, then transfers ownership. This makes a rerun safe even after a partially completed earlier initialization. The same startup check found the SQLite named volume was still root-owned, so the initializer now transfers that volume to the API UID before API startup. It retains only `CAP_CHOWN`; no capability was added.

**Validation:** The failed container log identified `chmod: /agent: Operation not permitted`; a first ordering-only repair also demonstrated that named-volume ownership persists after a failed run. The corrected initializer started successfully and the agent created an `agent.sock` owned by `10002:10001` with mode `0660`. API startup then exposed `sqlite3.OperationalError: unable to open database file`, which was addressed by initializing the state volume. `docker compose --env-file .env -f deploy/compose.yml config --quiet`, `git diff --check`, and a rebuilt minimal `socket-init`, agent, API stack passed; API opened SQLite in WAL mode and listened on its private Unix socket.

**Known limitations:** This repair does not exercise the FTD password credential, pinned host key, prompt-driven SSH path, API-to-agent request, audit trail, or egress/source restrictions.

## 2026-10-13 — Sanitized agent failure diagnostics

**Status:** Implemented; FTD failure cause under investigation

The first live typed removal request correctly received only a rejected response from the agent, but the agent had no local diagnostic event to distinguish a connection, authentication, shell, parser, or verification failure. Rejected removals now emit a structured local `agent.remove_shun.failed` event with only the device ID, target IP, and sanitized failure reason. The socket response remains the same one-byte rejection, so no diagnostic data crosses the privilege boundary. Credentials and raw Cisco output are never logged.

**Validation:** `cargo fmt --manifest-path agent/Cargo.toml -- --check`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` (8 passed); `git diff --check`.

**Known limitations:** The updated agent must be rebuilt and the single lab request retried to identify the FTD-path failure. A rejection is not evidence that the requested shun was removed; confirm the FTD state directly before any retry.

## 2026-10-13 — Required agent failure-log channel and secret-mount diagnosis

**Status:** Local diagnostic channel verified; secret ACL remediation awaiting operator application

The first prompt-driven laboratory request was rejected before FTD access. The new sanitized agent event was successfully retrieved through `docker compose logs` and identified the actual cause: the non-root agent could not read `/run/secrets/ftd_ssh_password`. Local Docker Compose implemented this file secret as a read-only bind mount preserving the host secret's `0600` ownership (`1000:1000`), while the agent runs as UID `10002`.

The agent now explicitly uses Docker's bounded `local` log driver, retaining operational JSON events through restarts. The operations manual makes this a required local collection channel and documents forwarding it with the host's approved collector. The deployment procedure now grants read access only to UID `10002` using a POSIX ACL on the host secret file; it does not make the secret group- or world-readable and does not run the agent as root.

**Validation:** Agent log retrieval returned the sanitized JSON event `agent.remove_shun.failed` with the reason `could not read SSH password secret /run/secrets/ftd_ssh_password`; `docker inspect` confirmed the Compose secret is a read-only bind mount and `stat` confirmed source mode `0600`, owner/group `1000:1000`. The diagnostic event contains no password and no raw Cisco output.

**Known limitations:** The operator must apply and verify the UID-specific ACL, recreate the agent, confirm the test shun's current state, and make one controlled retry. External forwarding requires the environment's selected host/container log collector and destination.

## 2026-10-13 — Agent/client timeout alignment and staged SSH diagnostics

**Status:** Implemented; laboratory retry awaits direct state check

The protected password became readable, but the first resulting FTD operation ran to the agent's 45-second global timeout. The local Python Unix-socket client had independently stopped waiting after 10 seconds, producing a misleading client timeout while the agent continued working. The API client now waits for the configured agent timeout plus a five-second local IPC margin; direct laboratory clients default to 125 seconds, covering the supported 120-second maximum.

The agent now applies explicit 15-second bounds to SSH connection/host-key verification, password authentication, PTY allocation, shell startup, the initial FTD prompt, and every command prompt. Its sanitized failure event identifies the failed stage while retaining the generic socket rejection and never recording credentials or raw Cisco output.

**Validation:** The initial operation emitted `agent.remove_shun.failed` with `operation timed out before verified completion`. `cargo fmt --manifest-path agent/Cargo.toml -- --check`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` (8 passed); `python3 -m pytest -q` (11 passed); `python3 -m ruff check .`; `git diff --check`.

**Known limitations:** The laboratory FTD must be checked directly before retrying: the previous timed-out attempt could have changed device state without a verified response. After state confirmation, rebuild API and agent, make one controlled request, and inspect the sanitized agent event if it fails.

## 2026-10-13 — FTD-management bridge egress laboratory finding

**Status:** Blocking environment control identified; remediation requires host-firewall authorization

The staged agent diagnostic reported `SSH connection or host-key verification timed out`. A credential-free TCP/22 probe from the `ftd-management` bridge (`172.18.0.0/16`) could not reach the configured FTD address, while an equivalent probe from the Compose host succeeded. The host routes this FTD traffic through VPN interface `cscotun0`; IP forwarding and firewalld are enabled, but no Docker NAT rule exists for the agent subnet.

This is an expected deployment gate, not a reason to weaken SSH validation: no password authentication, Cisco command, or state change was reached by the agent. A narrow persistent host firewall/NAT policy must permit only the agent bridge's configured FTD target(s) on TCP/22 through the VPN path, with a matching FTD source ACL added only after the stable translated source is known.

**Validation:** Host TCP/22 probe succeeded; the same credential-free probe from `deploy_ftd-management` failed. `ip_forward` is enabled, `firewalld` is active, and the FTD route uses `cscotun0`. Agent JSON diagnostics and Docker log retention were verified.

**Known limitations:** The host firewall/NAT policy has not been changed. Do not retry the agent request until the operator authorizes and validates a narrowly scoped egress policy.

## 2026-10-14 — Live FPR1010 typed removal validation

**Status:** Agent-to-FTD removal path validated in the non-production lab

The typed `UnixAgentClient` request from the API container for device ID `1` and TEST-NET-2 address `198.51.100.250` returned `verified removal`. The result proves the current isolated agent established an SSH connection with the pinned FTD server key, authenticated the dedicated `Basic` service account using the protected password secret, reached the FTD interactive PTY prompt, parsed the observed shun, issued only the interface-qualified typed removal, and confirmed absence through its post-write `show shun` check.

**Validation:** Operator-provided command result: `verified removal`. Earlier laboratory evidence establishes FPR1010 / FTD 7.6.6 parser fixture and `Basic`-role command compatibility. Agent, API, and socket transport had been rebuilt after timeout alignment and staged SSH diagnostics.

**Known limitations:** This direct typed-client check bypassed the Web/BFF and API HTTP endpoint. It does not prove Caddy/Authelia identity handling, CSRF, UI behavior, API authorization, SQLite removal audit events, Caddy routing, direct FTD post-operation CLI observation, or the documented negative/failure scenarios. Production writes remain unapproved.

## 2026-10-14 — Typed snapshots, reconciliation, and freshness scheduling

**Status:** Implemented; live FTD snapshot validation pending

Added the typed `LIST_SHUNS` agent operation and a bounded fixed binary snapshot response. The Rust agent opens its existing short-lived pinned-host-key/password/PTY session, runs only source-defined `show shun`, and accepts only the recorded FTD shun line layout with an allowlisted interface, IPv4/mask, and three numeric fields. The API decodes the complete response fail-closed; a malformed, truncated, duplicate, oversized, or rejected response is never interpreted as an empty snapshot.

Added SQLite snapshot reconciliation: new records produce `SHUN_DETECTED`, inactive records produce `SHUN_REAPPEARED`, unchanged records update only `last_seen_at`, and absent active records produce `SHUN_DISAPPEARED`. The API synchronizer starts an asynchronous initial sweep, then uses `FTD_SHUN_POLL_INTERVAL` (default `5m`). Authenticated Web/BFF state views can only post a local refresh hint; the scheduler enforces the configured 60-second minimum and never makes a browser request wait for SSH. The UI now displays last success, a metadata-derived next-baseline countdown, interactive state, and a refresh warning when a device fails.

**Validation:** `cargo fmt --manifest-path agent/Cargo.toml -- --check`; `cargo build --release --locked --manifest-path agent/Cargo.toml`; `cargo clippy --locked --manifest-path agent/Cargo.toml -- -D warnings`; `cargo test --locked --manifest-path agent/Cargo.toml` (10 passed); `python3 -m compileall -q src tests`; `python3 -m pytest -q` (22 passed); `python3 -m ruff check .`; `git diff --check`; `docker compose --env-file .env -f deploy/compose.yml config --quiet` using ignored local configuration.

**Known limitations:** The existing non-production FPR1010 evidence validates the write path, but has not yet exercised the new `LIST_SHUNS` response or a complete poll/reconciliation cycle. `GET_SHUN` and remote-access counter operations remain intentionally unavailable. Full Web/BFF, Caddy/Authelia, audit, failure-path, egress/source-ACL, external-log, and production validation remain required.

## 2026-10-14 — Live empty typed snapshot validation

**Status:** Empty snapshot path validated; non-empty reconciliation pending

The API-container `UnixAgentClient` issued `LIST_SHUNS` for laboratory device ID `1` through the private agent socket and received `[]`. The result verifies the live pinned-host-key/password/PTY session, exact empty `show shun` handling, fixed binary complete-snapshot response, and Python decoder. It did not make a Cisco configuration change.

**Validation:** Operator-provided typed-client output: `[]`.

**Known limitations:** This does not exercise a non-empty list parser result, SQLite reconciliation, scheduled/interactive polling, Web/BFF freshness display, browser authorization/CSRF, external logging, or failure paths. Production remains unapproved.

## 2026-10-14 — Live non-empty snapshot reconciliation validation

**Status:** Agent/API/SQLite path validated; browser and recurring baseline pending

The FPR1010 laboratory `LIST_SHUNS` request returned two non-empty allowlisted entries, including the documented TEST-NET fixture. The API's asynchronous startup sweep reconciled both entries into SQLite under device ID `1` and its configured hostname, and created `SHUN_DETECTED` for the fixture. The API status reported a successful sweep, a five-minute next-baseline timestamp, and no device error. A browser-style refresh hint issued only seconds later became `rate_limited`, demonstrating that it did not cause a second immediate FTD connection.

**Validation:** Operator-provided typed agent response, internal API `/shuns` and `/history/<TEST-NET-IP>` responses, and synchronizer status. The test results showed active records with `management` interface and a durable detection event.

**Known limitations:** This validates the initial non-empty sweep, not an elapsed five-minute baseline or browser rendering. It does not validate the Web/BFF/Caddy/Authelia path, UI countdown, UI removal audit, external disappearance/reappearance, failure paths, or production controls. The additional laboratory test address is intentionally not recorded.

## 2026-10-14 — Local browser-lab profile

**Status:** Implemented; workstation setup pending

Added a separate `compose.local-lab.yml` overlay and `Caddyfile.local-lab` for
controlled workstation testing before internal DNS and organization TLS exist.
It binds the existing Caddy routes to local `.test` names and uses only Caddy's
Internal CA. The profile preserves the normal Authelia ForwardAuth path,
server-rendered Web/BFF, private Unix sockets, and the prohibition on
development authentication. Added a structured Fedora procedure for local host
mapping, interactive Argon2 password-hash generation, local Authelia user-file
creation, Caddy root trust, start, and rollback to the normal profile.

**Validation:** Reviewed the merged Compose override design; `git diff --check`
will be run with the final validation set.

**Known limitations:** The local lab profile has not been started in a browser
yet. It is explicitly unsuitable for shared or production deployment, and the
operator must not commit `.env`, `users.yml`, local CA files, or other
deployment secrets.

## 2026-10-14 — Authelia read-only startup repair

**Status:** Implemented; browser retry pending

The first local browser-lab start returned a Caddy 502 because Authelia's
official image entrypoint tried to recursively `chown /config` and invoke
`su-exec`, while this service correctly mounts its configuration and user file
read-only and drops all capabilities. The service now invokes `/app/authelia`
directly with its explicit configuration path. It retains the read-only root
filesystem and `cap_drop: [ALL]`, rather than granting `CHOWN`, `SETUID`, or
`SETGID` or making the configuration writable.

**Validation:** Operator-provided Authelia logs identified the read-only
`chown` and denied `setgroups` calls. The upstream entrypoint behavior was
verified against the official Authelia source. Compose rendering is pending
with the final validation set.

**Known limitations:** The repaired Authelia container and full browser flow
need a lab retry. The local `.env` must define both local hostnames and their
shared cookie domain; a stale `AUTH_HOST` causes login redirection failure even
when Authelia is healthy.

## 2026-10-14 — Authelia configuration-template startup repair

**Status:** Implemented; browser retry pending

The preceding read-only-entrypoint repair exposed a separate Authelia startup
failure: the checked-in configuration uses deployment-name templates, but
Authelia disables file templates unless explicitly configured to apply them.
The Compose service now enables its `template` configuration filter. Session
and storage secrets were removed from the templated file and remain supplied by
Authelia's dedicated `AUTHELIA_SESSION_SECRET` and
`AUTHELIA_STORAGE_ENCRYPTION_KEY` environment configuration. This prevents a
template expansion from unnecessarily handling a secret.

The local file authentication backend is deliberately mounted read-only, so
self-service password reset and password change are now disabled. This also
removes the need to configure a reset-password JWT secret for the lab-only
local-user flow. A future LDAP(S) deployment must separately design and validate
identity-management and reset-password behavior before enabling it.

**Validation:** Official Authelia documentation confirms that configuration
file templates require the explicit `X_AUTHELIA_CONFIG_FILTERS=template`
setting, that normal environment configuration overrides file values, and that
password reset can be disabled under the authentication backend. Full Compose
and browser validation remains pending the operator retry.

**Known limitations:** This fixes the configuration-load failure reported by
the local profile but does not yet prove the browser login, ForwardAuth
redirect, Caddy local-CA trust, or application page. The local file backend is
not a production identity-management service.

## 2026-10-14 — Authelia local-user ownership repair

**Status:** Implemented; browser retry pending

The configuration-template repair let Authelia reach its provider startup
checks, which then correctly revealed that its protected `users.yml` file was
unreadable. The image's direct binary invocation starts as root, but the main
container intentionally drops every capability; a root UID without
`DAC_OVERRIDE` cannot read a mode `0600` file owned by the workstation user.

The service now runs under explicitly configured `FTD_SHUN_AUTHELIA_UID` and
`FTD_SHUN_AUTHELIA_GID`, matching the protected local user file owner. A networkless
one-shot `authelia-data-init` container owns only the Authelia SQLite volume and
has the minimal `CHOWN` capability required to prepare it. The primary
Authelia process remains read-only, capability-free, and unable to write its
configuration or user database. The manuals and environment example now make
the required host UID/GID explicit.

**Validation:** Operator-provided logs identified the failed read as
`open /config/users.yml: permission denied`. The local host owner is UID/GID
`1000:1000`, matching the safe default. Compose rendering and full local
browser retry remain pending.

**Known limitations:** This change has not yet been started on the laboratory
stack. Deployments using a non-default host UID/GID must set both values in the
ignored `.env`; using a mismatched value fails closed at authentication startup.

**Correction:** The first initializer invocation correctly changed ownership
but attempted its final permission change too late, after it had ceased to own
the directory. The command now applies mode `0700` before `chown`, preserving
the `CHOWN`-only capability boundary rather than adding `FOWNER`.

**Correction to the correction:** After the first ownership change, the
capability-minimal initializer also cannot change the directory mode on a
subsequent run. The mode operation was therefore removed entirely rather than
adding `FOWNER` or `DAC_OVERRIDE`. The named volume is not published and is
mounted only by Authelia and this networkless initializer; access isolation is
provided by the Compose mount topology and the main process UID.

**Follow-up:** After ownership was fixed, Authelia reached service provisioning
and reported that its optional in-image healthcheck metadata writer attempted
to create `/app/.healthcheck.env`. The `server.disable_healthcheck` option is
now set so the writer is not invoked on the intentionally read-only root
filesystem. This preserves the main container hardening rather than making
`/app` writable; the browser ForwardAuth flow remains the current laboratory
health validation.

## 2026-10-14 — Local Caddy/Authelia ForwardAuth path validation

**Status:** Unauthenticated path validated; interactive browser login pending

The local browser-lab profile was started successfully after the read-only
Authelia repairs. The `authelia-data-init` one-shot service completed, Authelia
reported `Startup complete`, and the container healthcheck became healthy. A
local HTTPS request to the protected service hostname returned a `302` redirect
to the local Authelia hostname. The redirect set an `HttpOnly`, `Secure`,
`SameSite=Strict` session cookie scoped to the configured shared local domain.
A direct local HTTPS request to the Authelia hostname returned `200`.

**Validation:** `docker compose --env-file .env -f deploy/compose.yml -f
deploy/compose.local-lab.yml config --quiet`; `git diff --check`; local Caddy
HTTPS requests with explicit loopback hostname resolution; Authelia container
state `healthy` and Caddy container state `Up`. No application service port was
published; Caddy remains the only host listener.

**Known limitations:** This does not prove a human browser trusts the local CA,
can submit the local credentials, receives forwarded identity headers, or can
view/remove a shun. It does not validate LDAP(S), MFA, production TLS, or any
write workflow.

## 2026-10-14 — Web/BFF container resource-path repair

**Status:** Implemented; runtime validation pending

Post-login ForwardAuth requests reached Caddy correctly but returned `502`
because the Web/BFF process repeatedly exited before creating its Unix socket.
Its installed-package path calculation looked for `static/` and `templates/`
below `/usr/local/lib/python3.12`, while the hardened runtime image copies those
assets to `/app`. The image now sets the internal
`FTD_SHUN_ASSET_ROOT=/app` value and the Web/BFF uses it when present, retaining
the source-tree path as the development fallback.

**Validation:** Operator-provided Caddy logs identified a missing
`/run/ftd-shun-manager/web.sock`; Web/BFF traceback identified the missing
`/usr/local/lib/python3.12/static` directory. Automated checks and rebuilt
container validation are pending.

**Known limitations:** This repair is limited to static/template resource
location. It does not yet prove a browser can render the authenticated page,
receive Caddy-provided identity headers, or invoke API-backed workflows.

**Follow-up validation:** `python3 -m compileall -q src tests`; `python3 -m
pytest -q` (22 passed); `python3 -m ruff check .`; `git diff --check`; and the
merged Compose configuration all passed. The Web/BFF image was rebuilt and its
server started on the private Unix socket. A private UDS request with test
Caddy-provided identity headers returned `200` and rendered the application
HTML. Interactive browser rendering after real Authelia login remains to be
confirmed by the operator.

## 2026-10-14 — Caddy ForwardAuth identity-header ordering repair

**Status:** Implemented; interactive retest pending

After the Web/BFF became available, an authenticated browser request still
received `401 authentication required`. Caddy's adapted configuration showed
that its default directive ordering placed the `Remote-*` request-header
deletion after the ForwardAuth response header copy. It therefore removed the
authenticated identity immediately before proxying to the BFF.

Both production and local-lab Caddyfiles now place identity-header deletion,
ForwardAuth, and the Web/BFF reverse proxy in a literal-order `route` block.
This restores the intended trust sequence: a browser cannot supply a trusted
identity header, while a successful Authelia decision can do so exactly once
for the BFF request.

**Validation:** Caddy's adapted JSON configuration demonstrated the incorrect
previous order, and the official Caddy `route` documentation confirms that
directives in the block are not reordered. Compose rendering and live
authenticated-browser retest remain pending.

**Known limitations:** The repair has not yet been exercised by a human browser
after Caddy reload. It does not change group mapping, authorization policy,
CSRF behavior, or the protected private-socket boundary.

## 2026-10-14 — Web/BFF removal-timeout alignment and live audit validation

**Status:** Implemented; rebuilt UI validation pending

An authenticated local-browser removal reached the internal API, completed with
`200`, and recorded both `SHUN_REMOVE_REQUESTED` and
`SHUN_REMOVED_BY_UI` (`verified: true`). The active local state no longer
contained the record. However, the BFF used a fixed 15-second internal API
timeout, while the verified FTD operation completed after roughly 16 seconds,
so the browser received an incorrect internal-server error after the successful
write.

The BFF now waits for the configured agent timeout plus ten seconds, exceeding
the API's agent-plus-five-second margin. Removal and bulk-removal requests also
convert internal HTTP failures into a controlled `503` which explicitly makes
no success claim. Added a unit test which locks the timeout relationship at 45
seconds agent timeout to 55 seconds BFF timeout.

**Validation:** Operator-triggered browser operation; API log `200`; local
read-only state and audit-history inspection; audit event `verified: true`.
The selected record was absent from local active state afterward. Automated
checks and rebuilt Web/BFF validation are pending.

**Known limitations:** This evidence uses the agent's verified response and
local audit record; it does not replace an independent direct `show shun`
observation on the FTD. The BFF timeout repair has not yet been deployed to the
running Web container.

**Follow-up validation:** `python3 -m compileall -q src tests`; `python3 -m
pytest -q` (23 passed); `python3 -m ruff check .`; `git diff --check`; and the
merged Compose configuration passed. The Web/BFF image was rebuilt and
restarted. Its effective internal API read timeout was verified as 55 seconds
for the configured 45-second agent timeout. No additional FTD operation was
issued during this deployment validation.

## 2026-10-14 — Trusted-IP automatic-removal policy and list usability

**Status:** Implemented; disabled by default; FTD policy validation pending

Added the optional `FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS` policy. It accepts only
comma-separated exact IPv4 addresses and starts empty. After a complete,
successfully parsed device snapshot, the synchronizer compares observed entries
with that allowlist and invokes the existing fixed, verified device-scoped
removal operation for an exact match. It records append-only
`SHUN_TRUSTED_AUTO_REMOVE_*` events under `system:trusted-ip-policy`; it does
not act after an unavailable or malformed snapshot, and a failed policy action
does not mark the shun removed.

The active-shun page now provides local IPv4 prefix filtering and presents
refresh state in operational language, with browser-updated last-confirmed and
next-refresh times. These display changes neither wait for Cisco output nor
change the existing global 60-second interactive-refresh limit.

The architecture, environment example, deployment and operations manuals, and
lab checklist now specify the policy's exact-IPv4 scope, event trail, alerting,
and required success/failure laboratory validation. No operator configuration
was enabled or changed by this increment.

**Validation:** `python3 -m compileall -q src tests`; `python3 -m pytest -q`
(29 passed); `python3 -m ruff check .`; `git diff --check`; and
`docker compose --env-file .env -f deploy/compose.yml config --quiet` all
passed.

**Known limitations:** The policy has automated success and failure coverage
only. It has not sent an automatic removal to the FTD lab and must remain empty
until the documented dedicated-fixture validation confirms both a verified
removal and its fail-closed behavior. The new browser search/freshness
presentation also awaits a post-deployment interactive check.

## 2026-10-14 — Visible trusted-IP policy status

**Status:** Implemented; browser retest pending

The authenticated primary page now has a read-only **Trusted-IP automatic
removal** table. It shows every configured exact address and its latest
verified automatic-removal timestamp across the fleet, or `Never` when no
verified policy removal has occurred. With an empty configuration it explicitly
shows that the policy is disabled. The internal status endpoint obtains this
from the current configuration and append-only success events; it does not
provide a web mutation path or expose any credential material.

**Validation:** Added store and API-status coverage for configured addresses,
the no-removal case, and a verified-removal timestamp. `python3 -m compileall -q src tests`; `python3 -m pytest -q` (31 passed); `python3 -m ruff check .`; and `git diff --check` passed.

**Known limitations:** The policy table has not yet been viewed in a browser
with a non-empty lab configuration, because the local policy remains disabled
until its documented FTD write validation is approved and completed.

**Correction:** After deployment, the ignored local environment was found to
contain two configured trusted addresses. The private status endpoint confirmed
both entries, no trusted-policy audit event, and no refresh error after the
startup snapshot. Therefore no automatic removal was observed or claimed. The
two values are intentionally not recorded in this repository; the required
dedicated-fixture policy validation remains outstanding.

## 2026-10-14 — Configurable history retention

**Status:** Implemented; production retention and backup policy remains an operator responsibility

Added `FTD_SHUN_HISTORY_RETENTION_DAYS`, defaulting to 366 days and limited to
1–3653 whole days. The background synchronizer runs the lifecycle task at most
once every 24 hours. It removes expired event rows and inactive state rows,
preserves active shuns, and records `HISTORY_RETENTION_PURGED` when data was
removed. Retention errors are surfaced in synchronizer status and structured
logs without changing the result of an FTD snapshot.

The UI now displays the current configured retention period. Architecture and
operator documents define the purge scope, the audit marker, and the required
SQLite-safe backup before reducing the period.

**Validation:** Added parsing and data-lifecycle tests, including preservation
of an active shun. `python3 -m compileall -q src tests`; `python3 -m pytest -q`
(35 passed); `python3 -m ruff check .`; and `git diff --check` passed.

**Known limitations:** The local SQLite file is not automatically compacted
after deletion; use an approved maintenance procedure if physical file-size
reclamation is required. External retained audit copies and backup automation
are not implemented by this stack.

## 2026-10-14 — Protected-IP visual marker

**Status:** Implemented; deployment pending existing write-side-effect approval

The Web/BFF now derives the configured exact trusted-IP set from its internal
status response and marks a matching active shun with an amber table row and
**Protected IP** badge. The shun detail page repeats this warning. The marker
is presentation only: it neither changes policy membership nor makes a Cisco
request, and it does not claim that automatic removal succeeded.

**Validation:** Added template coverage for the marker. `python3 -m compileall -q src tests`; `python3 -m pytest -q` (36 passed); `python3 -m ruff check .`; and `git diff --check` passed.

**Known limitations:** Rebuilding the API will trigger its ordinary startup
snapshot. Because the current local policy contains trusted addresses, that
snapshot could invoke existing automatic removal for a matching active shun;
deployment therefore awaits explicit operator approval.

## 2026-10-14 — Explicit browser timezone labels

**Status:** Implemented; deployment pending existing write-side-effect approval

All UI timestamp fields now use semantic `<time>` elements with their canonical
UTC ISO-8601 values. Browser-side rendering formats active-state, history,
freshness, and trusted-policy timestamps in the viewer's local timezone with a
timezone name or offset. The original `Z` timestamp remains as the fallback,
so the application never presents an unlabeled local time.

**Validation:** Updated template coverage. `python3 -m compileall -q src tests`; `python3 -m pytest -q` (36 passed); `python3 -m ruff check .`; and `git diff --check` passed.

**Known limitations:** The deployed containers still use the prior image until
the already-disclosed API restart risk is explicitly approved.

## 2026-10-14 — Approved API/Web deployment and policy outcome

**Status:** Deployed to the local laboratory stack

Following explicit operator approval, rebuilt and recreated the local API and
Web/BFF with configurable 366-day retention, Protected-IP presentation, and
explicit browser timezone labels. The retention preflight found no expired
local records; the first lifecycle run completed with no retention error.

The ordinary startup snapshot encountered one configured trusted-IP match. Its
append-only audit trail contains `SHUN_TRUSTED_AUTO_REMOVE_REQUESTED` followed
by `SHUN_TRUSTED_AUTO_REMOVED`; the local active-shun state was empty afterward.
This is the agent's existing verified-removal result, not a replacement for an
independent direct FTD `show shun` confirmation. Configured IP values are not
recorded in repository documentation.

**Validation:** Container services were `Up`; private API status reported a
successful refresh, `history_retention_days: 366`, and no retention or refresh
error. A local SQLite aggregate confirmed one trusted-policy request, one
trusted-policy verified-removal event, and zero active shuns.

**Known limitations:** A live trusted-policy failure and browser visual review
of timezone labels/Protected-IP highlighting still need their documented lab
checks.

## 2026-10-14 — Unified local IP search, refresh control, and recent-event view

**Status:** Implemented; deployment and browser validation pending

Replaced the active-table-only browser filter with a bounded internal
`GET /api/v1/search` resource and primary-page search workflow. It accepts a
strictly validated full IPv4 address or dotted prefix, searches only local
SQLite active state and retained audit history, and returns at most 100 matches.
Every result reports current status, last seen, latest event, last verified
manual or trusted-policy removal when available, device count, and exact
trusted-IP-policy membership. Historical-only entries are explicitly labelled
**Historical — not currently shunned** so they cannot be mistaken for a live
block.

The primary page now includes a CSRF-protected **Request refresh** control.
It only invokes the existing asynchronous refresh hint; the synchronizer still
enforces the global minimum interval. Synchronizer status now provides the next
interactive-refresh timestamp, including the initial queued request, so the
browser can present a live cooldown on the control. The page also has a
collapsed read-only **Last events log** that renders the newest 100 local audit
events. None of these views sends a new Cisco command or expands the fixed
agent protocol.

Architecture, deployment, operations, and status documents now cover the
bounded-search semantics, current-versus-historical visual distinction,
refresh-control constraints, and recent-event view.

**Validation:** Added store coverage for current/historical result composition
and invalid search inputs, synchronizer coverage for the initial interactive
cooldown, and template coverage for the historical Protected-IP state.
`python3 -m compileall -q src tests`; `python3 -m pytest -q` (43 passed);
`python3 -m ruff check .`; and `git diff --check` passed.

**Known limitations:** The new image has not yet been recreated and the
authenticated browser presentation has not yet been reviewed. Recreating API
may run the existing trusted-IP automatic-removal policy as part of its startup
snapshot; use the established explicit operator-approval procedure before
deployment.

## 2026-10-14 — Refresh presentation refinements

**Status:** Implemented; browser retest pending

Corrected the primary-page timestamp renderer so that removing the duplicated
interactive-refresh text does not bypass browser-local formatting of **Data
last confirmed**. Retention wording now appears beside the event/history view,
where it describes the records affected, rather than beside the refresh button.
When a scheduled baseline countdown reaches zero, the browser makes a single
page reload after a short delay to retrieve the newest locally reconciled
state. It does not send a direct Cisco command or claim a successful snapshot.

**Validation:** `node --check static/freshness.js`; `python3 -m pytest -q` (43
passed); and `git diff --check` passed.

**Known limitations:** The browser must still be refreshed with the rebuilt Web
image to confirm its presentation against the local stack.

## 2026-10-14 — Baseline-aware interactive refresh scheduling

**Status:** Implemented; browser and elapsed-time validation pending

The synchronizer now gives an imminent scheduled baseline precedence over a
manual browser refresh hint. When the baseline is due within the configured
interactive minimum interval (60 seconds by default), it reports
`baseline_pending` and does not queue a redundant FTD sweep. The Web control
then presents **Scheduled refresh** with the remaining seconds; the existing
baseline-expiry reload fetches the updated local state. If the baseline is
farther away, a permitted manual request remains immediate and resets the
following baseline interval after the resulting sweep.

While any bounded sweep runs, freshness status exposes a future baseline
timestamp so an expired browser countdown cannot enter a reload loop against
the previous deadline.

**Validation:** Added synchronizer tests for both the imminent-baseline deferral
and a distant-baseline immediate queue. `node --check static/freshness.js`;
`python3 -m compileall -q src tests`; `python3 -m pytest -q`; `python3 -m ruff
check .`; and `git diff --check` passed.

**Known limitations:** The behavior still requires authenticated browser
validation at both sides of the 60-second boundary and an elapsed five-minute
baseline check against the FTD lab.

## 2026-10-15 — Asynchronous freshness state machine

**Status:** Implemented; authenticated browser validation pending

Replaced the refresh UI's POST/redirect and deadline-reload behaviour with a
same-origin BFF freshness state machine. `POST /api/v1/refresh-hint` now runs
on the synchronizer's owning event loop and returns the actual scheduler state
in the same response, eliminating the prior cross-thread callback race. The
Web/BFF exposes a whitelisted read-only refresh-status response and accepts an
asynchronous CSRF-protected refresh form request.

The browser immediately applies the returned state to the button, then polls
only the BFF status endpoint. It reloads the server-rendered shun, history, and
event data once when the successful-refresh timestamp or refresh error changes;
it no longer reloads merely because a baseline countdown reaches zero. While a
sweep runs, status explicitly reports that in-progress condition and the button
stays disabled. This preserves the semantic agent boundary: browser polling
does not reach the agent or FTD directly.

**Validation:** Added API endpoint coverage verifying that a refresh hint
returns `queued` immediately. `node --check static/freshness.js`; `python3 -m
compileall -q src tests`; `python3 -m pytest -q`; `python3 -m ruff check .`; and
`git diff --check` passed.

**Known limitations:** The new BFF/API image has not been recreated or reviewed
in an authenticated browser. Validate manual, imminent-baseline, successful,
and failed refresh paths before treating the UI flow as production-ready.

## 2026-10-15 — Multi-user queue and manual blocklist import plan

**Status:** Design recorded; no runtime changes

Added `docs/development-plan.md` to preserve the agreed product direction and
implementation order. Manual blocklists are one-time, operator-confirmed shun
additions with `manual_import` provenance in SQLite and structured logs. A
later removal, external disappearance, restart, or reconciliation must not
automatically re-add them. The plan includes paste/parse/preview, comments and
embedded addresses, invalid/ambiguous/unsupported input handling, protected-IP
exclusions, batch progress, and per-device audit attribution.

Recorded a shared durable SQLite queue for concurrent users and bounded
per-device cycles combining additions, removals, and state refresh. Cycles use
one serialized SSH session, with at least 60 seconds from the preceding cycle's
completion to the next start. All device work, including trusted-policy
removals and retries, uses this budget. The plan covers duplicate admission,
conflicting intentions, cancellation, queue bounds, uncertain outcomes,
restart/backup recovery, and the absence of a physical exactly-once guarantee
across an SSH response loss.

Also recorded explicit cycle-completion revisions, per-device health, browser
response ordering, input preservation, and concurrency/failure acceptance
scenarios. Architecture Section 74 identifies the approved future exception
to the current prohibition on manual creation and the required typed protocol
and laboratory gates. README, manual index, operations, and project status
link the plan and clearly distinguish it from the current immediate-removal
implementation.

**Validation:** Documentation-only review of cross-document scope and relative
Markdown links; `git diff --check` passed. No runtime tests, deployment, CLI
operations, schema migration, or agent protocol changes were performed.

**Known limitations:** Queue storage/claims, bounded batch wire format, import
parser, addition operation, and browser completion revisions remain
unimplemented. Batch-size/time defaults and execution-time authorization are
detailed-design tasks; addition and single-session batching require live FTD
validation before enablement.

## 2026-10-15 — Queue visibility and priority refresh checkpoints

**Status:** Design refinement recorded; implementation pending

Extended the shared-queue plan with a visible operation/progress panel showing
device, active batch/action, requester, completed/total items, outcomes,
eligibility delays, and failure/backoff reasons. Added independent snapshot
and queue-progress revisions alongside completed-cycle revisions, so observed
state can update while a large import is still running.

An eligible UI refresh during an active batch now has planned priority at the
next safe command checkpoint in the current SSH session, before the next
background mutation. The current command and any outstanding write
verification finish first. Concurrent users share one pending refresh; the
interactive cooldown, one-extra-priority-snapshot limit per cycle, and command/
time budget bound console load and prevent background-work starvation. Session
uncertainty aborts the cycle instead of injecting another command. The future
typed cycle protocol must support checkpoint/progress signaling; a blocking
opaque batch RPC alone cannot implement the requirement.

Updated the development plan, normative next-increment architecture, project
status, and planned-operations note. Added acceptance scenarios for mid-import
refresh, multi-user coalescing, independent snapshot publication, budget
exhaustion, lost prompt, and continued background progress.

**Validation:** Documentation consistency review and `git diff --check` passed.
No code, runtime configuration, device commands, or deployments changed.

**Known limitations:** The queue/progress UI, priority refresh scheduler, and
agent checkpoint protocol remain planned. Their exact binary layout and batch
limits require detailed design and lab validation before implementation is
enabled.

## 2026-10-15 — Revision-based refresh and preserved browser state

**Status:** Implemented and tested locally; deployment/live integration pending

Added process identity and explicit status/data/completed-cycle revisions to
the synchronizer. Every sweep completion advances the cycle revision even for
the same repeated error or a partially successful fleet refresh. Committed
snapshots, local write outcomes, and retention deletions advance the data
revision. Status now includes cycle start/completion/outcome and detached
per-device health/freshness. Queued/running requests coalesce, so hints received
during a slow sweep cannot leave an unintended extra sweep queued. Disabled
agent mode no longer reports a refresh as queued.

Replaced the browser's timestamp/error comparison and automatic reload with
one sequential request loop covering manual POST, local BFF status, and
authenticated page reads. Request deadlines, failure backoff, visible errors,
hidden-tab suspension, and immediate retry controls avoid overlapping polling
or silently losing a failed request. Updated data regions preserve unsent
search text, confirmation values and focus, scroll, and expanded event history.
The same refresh control and per-device status table are available on list and
detail pages. Server timestamps are localized with timezone labels.

The BFF captures revision metadata before state reads, whitelists status fields,
and marks dynamic responses no-store. API status runs on the scheduler's event
loop. Existing immediate manual removals perform their blocking agent call in
a worker thread and publish a local data revision afterward, keeping status
responsive and other tabs informed; this is not the planned durable queue.
The Rust agent, fixed binary protocol, and verified-write requirements did not
change. No schema migration, new secret, or new runtime dependency is needed.

**Validation:** Python suite (51 passed) covers slow-cycle coalescing, repeated
failures, partial fleet success, restart identity, detached status, disabled
refresh, and BFF authentication/CSRF/no-store behavior. Real Chromium suite
passed all three scenarios (four reported tests including the parent) using
production templates/JavaScript and a synthetic localhost BFF: single-click
refresh, slow in-flight status, two tabs, imminent baseline, repeated identical
failures, status recovery, API restart, POST failure/retry, and preserved form/
history state. Node syntax checks, Python compileall, Ruff, and
`git diff --check` passed. The ASGI/thread-pool and Chromium checks required
execution outside the restricted sandbox; no test connected to FTD or used
the local deployment's credentials or users.

**Operational impact:** Rebuild API and Web together; old browser tabs need a
one-time reload to load the new script. Reverting both images is sufficient
for rollback because there is no schema/configuration change. The normal API
startup snapshot and configured trusted-IP policy still apply on restart.

**Known limitations:** No deployment or live FTD/Authelia test was performed in
this increment. Durable operation queues, cross-restart cycle gates, queued
mutation progress, agent session reuse, mid-batch priority snapshots, and shun
addition/import remain the subsequent planned work.

## 2026-10-15 — Durable removal queue and shared cycle gate

**Status:** Implemented and tested locally; deployment/live validation pending

Added a transactional SQLite queue with separate user requests and device/IP
jobs. Device-scoped and confirmed fleet-wide removals now return `202 Accepted`
rather than dispatching immediately. UUID idempotency preserves a request after
a lost response, frozen bulk targets prevent retry drift, and concurrent users
share one pending execution while retaining individual actor/audit attribution.
Capacity and per-user admission limits fail atomically. Operators may cancel
their own unstarted requests; Administrators may cancel another user's.

One leased executor serializes fleet cycles. A persisted cooldown survives API
restart. Each cycle obtains fresh snapshots and handles at most one queued
device/IP removal per device; trusted-IP policy shares the same queue and
budget. Requests arriving mid-cycle wait for the next cycle, except newly
discovered trusted-policy work. Expired/disabled requests settle without
requiring a successful snapshot. Removed trusted-IP policy cancels its pending
intent without cancelling an independently coalesced manual request.

Verified agent success, queue completion, local state, and actor events commit
atomically. A failed/lost write response or expired executor lease leaves an
UNVERIFIED outcome, never an automatic write replay. A later snapshot can mark
absence without claiming the original write succeeded. Queue progress,
requesters, deadlines, reasons, and cancellation appear on list/detail pages;
browser actions share the sequential update loop and preserve idempotency keys
across partial page updates and failed replies. Structured queue events go to
stdout; terminal queue records follow configured history retention.

Documented the authorization boundary explicitly: current authentication/write
role is required at admission/cancellation; execution uses captured authority
for at most 15 minutes (or the sensitive-action age, if shorter), not saved
session credentials or live directory revalidation. Logout/role changes do not
revoke admitted work within this window; explicit cancellation is available.

**Validation:** Python suite: 70 passed. Real Chromium suite: all four scenarios
passed (five reported tests including the parent), including lost admission
reply, DOM replacement, same-key retry, and cancellation. Tests also cover
concurrent actors, atomic overflow, expiry, durable cooldown, executor loss,
uncertain-write reconciliation, one-removal-per-device budgets, authentication/
CSRF forwarding, additive initialization, retention, and the documented restore
SQL. Python compileall, Ruff, Node syntax checks, and `git diff --check` passed.
ASGI/thread-pool and browser tests required execution outside the restricted
sandbox; all used fake agents/temporary data, not FTD or deployment credentials.

**Operational impact:** Four additive queue tables/indexes are created on API
initialization. Take a SQLite-safe backup first, rebuild API/Web together, and
reload browser tabs. The agent and fixed binary RPC are unchanged. The new
operation-queue manual includes migration, backup, restore, and rollback; a
restored queue must have stale pending work suspended before workers restart.
Do not run an old immediate writer beside the new executor.

**Known limitations:** No deployment or live FTD/Authelia validation was
performed. Each existing read/write RPC still opens a separate SSH session;
single-session batching, command-boundary priority refresh, shun addition, and
one-time manual blacklist import remain planned. This is a conservative queue
increment, not completion of the full queued-device-cycle design.

## 2026-10-15 — Experimental single-session removal cycles and priority checkpoints

**Status:** Implemented and tested locally; default-off, live validation pending

Defined the versioned BEGIN/SNAPSHOT/REMOVE/END protocol before implementing
the agent/client extension. It retains peer-UID-checked SOCK_SEQPACKET, exact
length/version/sequence validation, binary device/IP fields, the 64-KiB response
limit, strict parsers, interface allowlists, and verified success. No command,
route, arbitrary interface, addition, or import capability crosses the boundary.
Python and Rust share golden wire vectors. Both transports now detect truncated
packets explicitly; agent initial receive and sends have finite IPC timeouts.

The opt-in agent opens one pinned/password-authenticated PTY session per device
cycle, reuses it for sequential removals and snapshots, then disconnects. Hard
limits are 16 removal steps, 64 actual CLI commands, one extra priority snapshot,
and a 120-second work window. Each step is bounded by the smaller of the
configured operation timeout and 45 seconds; connect plus initial observation
share one bound. Preserve the existing 15-second prompt deadline. Reserve final
observation and all observed interface writes/verification before mutation;
an exact pre-write deferral returns the job to QUEUED with an append-only
`SHUN_OPERATION_DEFERRED` event and structured stdout log. Uncertain responses
remain UNVERIFIED and never trigger legacy fallback or automatic replay.

The scheduler retains the durable executor/cooldown, frozen manual-admission
cutoff, short captured authorization, and cancellation checks before each job.
Trusted-policy discovery uses the same session/budget. Each verified job commits
immediately; later final-snapshot/session failure preserves earlier success.
A coalesced eligible interactive hint is served at the next verified operation
checkpoint before another removal. Recent complete snapshots satisfy demand
without another read; further hints join the final snapshot. If an extra
snapshot cannot fit while reserving END, an exact read-deferral response joins
the final snapshot and leaves further mutations for the next cycle; this does
not consume a command or imply a successful snapshot. Snapshots publish
data revisions before cycle completion. The browser shows current device/action,
completed items, priority wait, and budget deferral, and enables a priority
refresh button during an eligible long cycle without losing editable state.

**Validation:** Python suite: 99 passed. Rust suite: 20 passed. Chromium:
five scenarios passed (six reported tests including the parent), including a
priority request and data update while the cycle remains running. Tests cover
shared wire vectors, malformed/reordered/truncated frames, one Unix connection,
count/command/time budgets, multi-interface pre-write deferral, failed/slow
verification, default-off gating, coalescing/cancellation/cutoff, trusted-policy
work, device isolation, preserved verified results, and shutdown/lease recovery
without replay. Compileall, Ruff, Node syntax checks, Cargo format/Clippy,
locked release build, and `git diff --check` passed. Socket/ASGI/Chromium tests
needed execution outside the restricted sandbox; no test used FTD, deployment
secrets, or the running Compose stack. Rust console tests use a fake console;
they do not establish real SSH compatibility.

**Operational impact:** `FTD_SHUN_AGENT_CYCLES_ENABLED=false` is the default in
both API and agent; the tracked environment example documents it. No new queue
table, dependency, listener, or Compose topology change is required. Enabling
the extension requires coordinated new agent/API/Web versions and the separate
cycle laboratory procedure, including independent FTD observations and session
counts. The existing queue migration still needs a SQLite-safe backup. Rollback
stops the executor/session before disabling the flag; unknown jobs must never
be manually reset to QUEUED. Backup restore retains its suspension procedure.

**Known limitations:** No deployment or live FTD/Authelia validation was
performed; `.env` and the running stack were untouched. Default mode remains
one removal per device per cycle. Session caps are fixed conservative limits,
not performance promises; disconnect cleanup is bounded to two further seconds
and sends no Cisco command. Fleet scheduling remains conservatively serialized.
Manual additions/imports and production readiness remain separate future work.

## 2026-10-15 — Approved lab deployment and live session read checks

**Status:** Deployed with experimental session mode enabled in the local lab;
queued batch-write and priority checks remain pending

Following explicit operator approval, built new Rust agent/API/Web images and
performed a coordinated upgrade: stopped Web, then API, then agent; started the
new agent before the new API and Web. Caddy, Authelia, runtime networks, secrets,
and data volumes were not recreated or reset. The ignored local `.env` now sets
`FTD_SHUN_AGENT_CYCLES_ENABLED=true`; the repository example/default stays false.
Restricted `.env` access from 0644 to owner-only 0600 without logging its secret
contents. The operator explicitly waived a SQLite backup for this development
migration; this is not a general change to shared/production backup procedures.

Preflight found four active entries, no match with the two configured protected
addresses, and no existing operation-queue tables. API initialization added the
four queue tables while preserving existing state. SQLite `PRAGMA quick_check`
returned `ok`, and queue counts remained empty. No test shun was created and
no removal was queued or performed.

The startup session cycle completed at `2026-10-15T15:59:05Z`. A subsequent
single internal `POST /api/v1/refresh-hint` returned `202`/`queued`, and its
cycle completed at `2026-10-15T16:00:56Z`. Both were successful with no device
error; structured agent logs reported two CLI commands and zero removal steps
per session, with durations 8151 ms and 7941 ms. All four entries remained.
The next hint inside the minimum interval returned `rate_limited`, without
another immediate session. This is live BEGIN/END snapshot/session-reuse
evidence, not proof of the new REMOVE or priority SNAPSHOT paths.

**Validation:** All three image builds and quiet merged Compose configuration
validation passed. Private API reported socket mode, session mode enabled,
successful cycle revision 2, ready device state, empty queue, and no error.
Web served the new queue/priority JavaScript; anonymous page and status requests
returned 401. HTTPS certificate verification succeeded and unauthenticated
access returned 302 through the unchanged Caddy/Authelia path. Only Caddy
loopback TCP/443 remains published; Authelia is healthy. `git diff --check`
passed. Source/unit suites were unchanged from the prior recorded 99 Python,
20 Rust, and five Chromium scenarios; they were not rerun for this deployment.

**Known limitations:** Authenticated browser submissions, queued multi-item
removals, direct post-removal FTD observations, live cancellation/concurrency,
mid-batch priority reads, budget/uncertain-outcome recovery, and a full elapsed
baseline interval still need their controlled lab checks. Do not infer
production readiness from read-only startup success. Old browser tabs need a
reload to load the new script and idempotent forms. Rollback must stop the
executor/session and preserve uncertain queue outcomes; follow the queue and
cycle manuals rather than resetting jobs or volumes.

## 2026-10-15 — Separate working queue from retained results

**Status:** Implemented, tested, and deployed to the approved development stack

Following the operator's successful queued-removal test and feedback about
completed rows cluttering the queue, separated the working view from retained
outcomes. Only QUEUED/RUNNING jobs appear in the working table; an idle queue
says `Queue is empty`. FAILED/UNVERIFIED results stay visible in a separate
Needs attention section. Other terminal outcomes move to Completed operations,
collapsed by default, with only the latest 20 results, completion information,
total counts, and IP-history links. User disclosure state survives dynamic
updates. Idle completed-cycle progress and irrelevant next-eligibility text
are hidden, and completed requesters are no longer misleadingly labelled ACTIVE.

Status independently selects up to 100 active jobs (RUNNING first, then FIFO),
20 latest failed/unverified results, and 20 other terminal results ordered by
completion. The additive `display_limits` metadata makes these bounds explicit.
Counts cover all retained work. Counts, rows, and requesters use one SQLite
read transaction to avoid contradictory groups during concurrent completion.
No queue record, audit event, authorization, idempotency rule, retention policy,
agent operation, or database schema was changed to clear the display.

The operator reported successful live queued removals; read-only private API
inspection independently confirmed two VERIFIED results, no active work, and
no device error. This adds durable result evidence without claiming independent
direct FTD observation or same-session multi-item/priority validation.

**Validation:** 101 Python tests passed, including a 156-job bounded-selection
fixture and concurrent completion/read-snapshot regression. All six Chromium
scenarios passed (seven reported tests including the parent), covering collapsed
completed rows, active-to-completed transitions, visible errors, bounded long
history, counts, links, cancellation, and disclosure/input preservation.
Compileall, Ruff, Node syntax, and `git diff --check` passed. Tests used temporary
data/fake devices; socket/thread/browser checks ran outside the restricted
sandbox. Rust source is unchanged and its prior 20-test validation still applies.

**Deployment:** After explicit approval, built and recreated API/Web together,
stopping Web before the API executor; the agent and authentication edge were
not recreated. Deployed status exposes the 100/20/20 limits, zero active rows,
both preserved verified results, a successful cycle, and no error. New Web
assets/templates are present; anonymous page/status requests return 401 and
HTTPS returns the expected 302 with TLS verification. No new removal was
submitted. Reload browser tabs once to load the new script.

**Operational impact and limitations:** No migration or data cleanup is needed;
roll back paired API/Web images without deleting queue/history data. Completed
records still follow configured retention (366 days by default), not the display
limit. These are bounded summaries, not a full paginated queue browser. Live
concurrency, direct FTD post-removal checks, and mid-batch priority validation
remain the separate documented lab work.

## 2026-10-15 — Actual request progress bars and running-job indicators

**Status:** Implemented, tested, and deployed to the approved development stack

Added bounded request-progress metadata to queue status: up to 20 active
request summaries with the total request count, actual linked-job total,
processed count, and per-state outcomes. Counts span devices/cycles and come
from the existing consistent SQLite read snapshot, rather than the cycle cap,
elapsed time, historical totals, or new process-local counters. Cancelled
requesters are excluded even when another requester still needs a shared job.
Coalesced execution may contribute to multiple request bars without creating
additional device operations.

The Web displays labelled native determinate request bars, processed/total
counts and percentages, queued/running counts, and separate verified, no-op,
failed, unverified, cancelled, and reconciled-absent outcomes. Failed/unverified
outcomes have warning treatment; processed does not imply successful removal.
RUNNING jobs show native indeterminate indicators without a fabricated command
percentage or ETA. Settled request cards disappear from active progress while
their outcomes remain in the existing attention/completed views. Read/priority
phases do not advance job progress.

Canonical metadata signatures preserve indicator nodes, animations, and focused
queue controls when only status phases or JSON object-key ordering differ.
The first browser regression exposed a template/BFF key-order-induced replacement;
normalizing comparisons fixed it and the final suite passed. This is generic
queued-job presentation, not an addition/import implementation.

**Validation:** 104 Python tests passed, including actual multi-job totals,
uncertain outcomes, cancelled coalesced requesters, 20-request bounds, and
consistent snapshots. All seven Chromium scenarios passed (eight reported
tests including the parent). The new scenario checks a real denominator of 3
instead of cycle limit 16, distinct unverified results, an indeterminate running
command, stable nodes through a priority-read phase, and removal of settled
cards without hiding errors. Compileall, Ruff, Node syntax, and
`git diff --check` passed. Tests used fake devices/temporary data outside the
restricted sandbox where socket/thread/browser support was required. Rust was
unchanged and was not rebuilt/retested for this increment.

**Deployment:** Following explicit operator approval, rebuilt and recreated
API/Web together, stopping Web before API; the agent, secrets, `.env`, schema,
and persisted outcomes were unchanged. Live API status exposes progress limit
20, zero active requests, both prior VERIFIED results, a successful cycle, and
no error. New template/JavaScript/CSS assets are present. Anonymous Web page/
status requests return 401 and HTTPS returns 302 with TLS verification. No new
device operation request was submitted for validation. Reload browser tabs once.

**Operational impact and limitations:** No schema migration or new dependency
is needed. Roll back paired API/Web images without changing stored queue data.
The current lab has no active request for a live visual check; the animated/
multi-job scenarios use Chromium fixtures. Addition/import, direct independent
FTD write checks, and live concurrency/priority failure cases remain separate
planned work. Displayed processing percentages are not success percentages.

## 2026-10-15 — Compact service menus and SQLite-owned Protected IP administration

**Status:** Implemented, tested and deployed to the explicitly approved lab

Moved device/refresh details into a compact Status disclosure and queue/progress/
cancellation/results into Queue. The primary page now concentrates on search
and active observations; separate Protected IPs and History pages provide policy
management and the latest 100 audit events with retention information. Native
keyboard activation, Escape/focus return, outside-click dismissal, responsive
panels and spaced progress labels are covered in Chromium. Stale/error warnings
and failed/unverified counts stay visible outside closed menus. The browser
fixture initially omitted native Enter keypress text; supplying the real CDP
key event fixed that test harness issue without adding custom keyboard emulation
to the product's native details/summary controls.

Added authoritative `protected_ips` and singleton `protected_policy` tables.
Administrator-only, CSRF-protected semantic CRUD accepts exact IPv4 addresses,
bounded name/comment fields and enabled state; deletion requires typed IP
confirmation. A global durable revision rejects stale concurrent edits. Dirty
forms preserve their original revision and per-IP values during dynamic updates,
so background rendering cannot silently authorize overwriting another user's
change. A save does not issue SSH or request an extra snapshot; normal successful
snapshot discovery queues automatic removal with the existing budgets.

Policy mutation, revision and before/after actor audit are one SQLite transaction.
Unstarted obsolete policy requests are cancelled under that same lock, retaining
independent manual requests. Every worker claim independently rechecks current
database policy, including within a multi-item session; RUNNING work completes
normally. JSON events correlate the actor/request ID without emitting comments.
Search includes protected-only addresses without inventing an observation.

The former environment list is now only a one-time additive migration input.
Import and a durable marker are atomic, including an empty import; invalid
input fails startup without marking success. Normal settings no longer parse
the value, and later edits/deletes cannot be reverted by environment changes or
restart. Removed the variable from `.env.example`. Added local-backup ignores
and a Docker context exclusion file so operational backups, actual configuration,
credentials and build caches are not sent as build context.

**Validation:** 115 Python tests passed; all ten Chromium scenarios passed
(11 reported tests including the parent). New tests cover atomic/empty/invalid
legacy migration, deletion/restart, concurrent administrator conflicts, live
policy reads, coalesced manual cancellation behavior, a disable during an
in-progress fake session, exact-IP validation, roles/CSRF, audit correlation,
safe HTML, preserved drafts/revisions and policy CRUD without refresh hints.
Compileall, Ruff, Node syntax and diff checks passed. Tests use temporary data,
fake agents and synthetic browser transports; Rust/protocol are unchanged.

**Operational impact:** API/Web must be upgraded together after a SQLite-safe
backup. The [Protected IP manual](manual/protected-ips.md) documents migration,
restore suspension, rollback and removal of the obsolete environment value.
No shun addition/import, agent capability, authentication bypass, or production
write approval is introduced. Authenticated live browser retesting and the
existing FTD lab backlog remain necessary.

**Deployment:** Preserved previous API/Web images as
`before-protected-policy-20261015t1705z`, built the replacements, stopped Web
before API, and created a mode-0600 SQLite backup with quick_check=ok. A second
copy is outside the state volume at the ignored
`.local/backups/state-before-protected-policy-20261015T1705Z.sqlite3` (directory
mode 0700). Recreated API then Web only. Live read-only checks confirmed both
prior addresses imported exactly, two import audit events, marker=1, revision=1,
quick_check=ok, all four previous VERIFIED outcomes retained, and a successful
cycle with no error. Removed the obsolete variable from the ignored `.env` only
after verifying migration. Caddy/Authelia/agent were unchanged. Anonymous Shuns,
Protected IPs, History and refresh-status requests return 401; static assets
return 200 and HTTPS Protected IPs returns the normal Authelia 302 with TLS
verification. No new mutation was queued or policy entry changed for validation.
Reload browser tabs once; authenticated live UI testing remains an operator task.

## 2026-10-15 — Expanded paginated history and non-shifting refresh feedback

**Status:** Implemented, tested and deployed to the explicitly approved lab

Removed History's obsolete details/summary disclosure. Its always-visible table
now pages through retained audit at 100 events per page, with page/total/range,
Previous/Next, numeric Page/Go and Latest events controls. The live first page
continues to update. Navigation carries an event-ID anchor resolved inside a
single SQLite read transaction, so newly appended rows do not shift older-page
boundaries. Timestamp ties use descending insertion order. Counts and rows are
consistent, out-of-range pages clamp after retention, and a missing anchor gives
an explicit expired-window message/Latest link. Hex UUIDs from the existing
offline restore procedure are supported. No database column/table/index changed.

Added a bounded semantic read endpoint `/api/v1/history-page`; existing list and
per-IP history contracts are unchanged. Invalid page/UUID parameters return 422
and expired anchors return 410. Web navigation, pagination and status polling
remain authenticated, no-store and read-only with respect to FTD. The BFF
canonicalizes direct older-page URLs to preserve their anchor during polling.

Moved routine refresh progress inside Status, eliminating the duplicate main-
page line whose visibility changed layout. A single-line grid toolbar remains
stable across status/count text changes, including mobile layout. Critical
device/stale/queue/submission failures remain visible in a fixed alert tray;
they do not push search/forms/tables down or disappear into closed menus.

**Validation:** 123 Python tests passed. All eleven Chromium scenarios passed
(12 reported tests including the parent). New Python coverage exercises a
251-event window, 100/100/51 slices, tied timestamps, no overlaps, inserts after
an anchor, retention and expired windows, empty history, query limits, normalized
restore UUIDs, concurrent snapshot consistency, authentication and BFF links.
Chromium navigates real templates, checks a new live 252nd record without
shifting an older page, and measures unchanged search coordinates across
refresh/device-error/queue-error/network-failure transitions at 1100px and 375px.
Compileall, Ruff, Node syntax and diff checks passed. Fixtures use temporary
SQLite/fake data only; Rust and the agent protocol are unchanged.

**Operational impact:** No migration, setting, data cleanup or device capability
was added. Upgrade paired API/Web and reload browser tabs. The preceding policy-
aware pair can be restored without changing SQLite; older pre-policy/pre-queue
versions remain subject to their documented rollback restrictions. Anchors are
temporary browsing windows, not immutable archives: retention/restore may remove
their boundary and require Latest events. External log retention remains an
operator responsibility.

**Deployment:** Preserved the preceding policy-aware API/Web images under
`before-history-pagination-20261015t172141z`, built replacements, stopped Web
then API gracefully, and recreated only API/Web. Live read-only probes show
51 retained events (one 100-row-capacity page), invalid-page 422, expired-anchor
410 and the unchanged legacy list response. SQLite quick_check is ok; two
protected addresses, policy revision 1, two migration audit events and all four
prior VERIFIED results are intact. The obsolete policy environment value is
absent from the new container. A post-upgrade cycle succeeded without error.
Anonymous Shuns/History/paged-History/Protected-IPs/status routes return 401;
assets return 200 and HTTPS History returns the expected Authelia 302 with TLS
verification. No device operation or policy edit was submitted for validation.
No schema/data migration or configuration change was performed. Reload browser
tabs once; the operator still needs to inspect the authenticated live UI.

## 2026-10-15 — Shared Protected IP management for authenticated users

**Status:** Implemented, tested and deployed to the explicitly approved lab

At the operator's request, removed the Administrator-only gate from Protected
IP forms, BFF, internal API and SQLite policy mutations. Every user admitted
through Authelia may add/edit/enable/disable/delete, including Viewer, Operator
and users with no mapped application group. Non-empty authenticated identity
remains mandatory; whitespace-only identity is rejected at the BFF and policy
boundaries. Actual directory roles remain unchanged in audit rather than being
replaced with a synthetic Administrator role. Service admission must therefore
be restricted to people trusted to manage the fleet-wide protection policy.

CSRF, IP validation, typed deletion confirmation, optimistic conflict handling,
append-only before/after audit, SQLite ownership, queue budgets and live policy
revalidation are unchanged. This is a scoped Protected IP permission change:
manual shun-removal roles and cancellation ownership/Administrator rules are
not broadened. Updated architecture, operations/deployment/policy manuals,
README, status and current plan to state that distinction explicitly.

**Validation:** 131 Python tests passed. All eleven Chromium scenarios passed
(12 reported browser tests). BFF/API tests exercise all three mapped roles and
the unmapped-user case, retained actual-role audit, blank/anonymous denial,
CSRF, forged form identity, revision conflicts and unconfirmed deletion.
Direct store calls cannot bypass the non-empty-identity requirement. Chromium
policy CRUD uses Operator, not Administrator. Existing manual-removal/queue
authorization regressions remain passing. Compileall, Ruff, Node syntax and
diff checks passed. Tests use temporary/fake state, not live policy changes.
Rust and the fixed agent protocol are unchanged.

**Operational impact:** Upgrade API/Web together and reload browser tabs.
No schema/data migration, group-file edit, new setting, secret change or agent
upgrade is needed. Reverting to the preceding paired images restores the old
Administrator requirement without changing policy data. Authentication and
existing sensitive-session expiration still apply; LDAP/directory admission
must not unintentionally admit an untrusted population to shared policy editing.

**Deployment:** Tagged the preceding API/Web images
`before-shared-policy-20261015t172819z`, built replacements, stopped Web before
API, and recreated only API/Web after explicit operator approval. Read-only
checks confirmed quick_check=ok, both protected addresses, unchanged policy
revision 1/two import events, all four previous VERIFIED outcomes, and a
successful cycle without error. Anonymous page/status requests still return
401; HTTPS Protected IPs returns the expected Authelia 302 with TLS verification.
Agent, Caddy, Authelia, user/group files, `.env` and schema were unchanged. No
policy edit or new device operation was submitted for validation. Reload tabs
once; authenticated live policy-editor testing remains an operator task.

## 2026-10-15 — Non-executable blocklist parsing and local-state import preview

**Status:** Implemented, tested and deployed to the explicitly approved lab

Added an authenticated Import preview page with optional label/reason, explicit
enabled-device selection, bounded paste field and an always-non-executable result.
The Web parser accepts exact IPv4 literals, explicit whitespace/comma/semicolon
lists, whole-line #/ // comments, inline # comments and one address in surrounding
text. Canonical duplicates retain source-line references and bounded comments.
Multiple address-like tokens in free text are ambiguous; CIDR/range/IPv6/URL/
path/port forms never yield a truncated target. Spaced IPv4 range/CIDR/port lines
are excluded as a whole. Maximum-length numeric/wrapper fixtures prompted
linear bounded token recognition rather than unbounded regex backtracking.

Raw text, label and reason remain only in Web/browser memory and escaped HTML,
not SQLite/logs/internal API/agent requests. The API exposes an ID/hostname/
enabled selector and a typed canonical-IP/device-ID classification read using
one SQLite transaction. Protected addresses and already-observed device/IPs are
excluded from candidate counts. Duplicates do not multiply pairs. Ready means
candidate data only; no ADD opcode, queue admission/confirmation, batch storage,
provenance relabeling, refresh hint or creation-interface scope is introduced.
Unrelated queued removals/policy execution continue normally.

Limits are 64 KiB UTF-8 text, 2,000 lines, 1,000 total rows, 64 selected devices
and 5,000 expanded unique IP/device pairs. The form rejects oversized declared
or chunked bodies above 256 KiB before decoding; uploads and unexpected/repeated
scalar fields are unsupported. CSRF remains mandatory; byte comparison now
rejects non-ASCII invalid tokens safely rather than raising a comparison error.
Synchronous API/render work runs in a worker thread, not the Web event loop.
Background metadata updates intentionally retain the point-in-time preview and
unsaved source instead of resubmitting or replacing the paste. New manual
documents supported syntax, limits, privacy, release boundary and rollback.

**Validation:** 169 Python tests passed. All twelve Chromium scenarios passed
(13 reported browser tests). New coverage checks valid/ambiguous/invalid/
unsupported input, comment exclusion, canonical duplicates and independent
source references, hostile maximum-length tokens, UTF-8/line/row/body/pair limits,
chunked/duplicate-field rejection, explicit enabled devices, changed policy,
per-device observations, typed-only API forwarding, CSRF/XSS/no-store and no
queue/audit changes. The browser fixture initially used an invalid unquoted
numeric attribute selector; quoting it fixed the harness. The final scenario
covers every outcome and source/result/focus preservation without extra parses,
hints or execution. Compileall, Ruff, Node syntax and diff checks passed.
Tests use temporary state/fake devices; Rust and the fixed protocol are unchanged.

**Operational impact and limitations:** Paired API/Web upgrade and tab reload
only; no schema migration, setting, secret, agent upgrade or data cleanup.
Rollback to the preceding pair removes preview without touching SQLite. This
is intentionally not executable import and not new FTD laboratory evidence.
Creation-interface scope, Basic permission, strict addition verification,
actual blocking behavior and narrow ADD encoding still need separate design
and live validation before admission/provenance/worker support is enabled.

**Deployment:** Tagged the preceding API/Web images
`before-import-preview-20261015t180217z`, built replacements, stopped Web before
API and recreated only API/Web after explicit approval. A typed local preview
for one documentation address on one enabled device returned preview_only=true
and can_execute=false, with zero audit-row change during the read. Before/after
checks retained all six already VERIFIED outcomes, both protected addresses
and policy revision 3 (existing operator changes, not this increment). SQLite
quick_check is ok and a cycle succeeded without error. Anonymous GET/POST
Import preview, other pages and status return 401; assets return 200 and HTTPS
Import preview returns the expected TLS-verified Authelia 302. No shun, policy
edit, queue admission or refresh hint was submitted for validation. Agent,
Caddy, Authelia, `.env`, secrets and schema were unchanged. Reload tabs once;
authenticated live paste/preview inspection remains an operator task.

## 2026-10-15 — Enabled/disabled Protected IP badges and disabled-shun warnings

**Status:** Implemented, tested and deployed to the explicitly approved dev lab

Added green Enabled and red Disabled badges to the Protected IP list, retaining
text labels for colour-independent state recognition. A disabled entry with
active local observations has a red card and explicit warning that automatic
removal is off. Search/current-shun rows and the IP detail view also identify
disabled protection instead of silently treating a saved disabled IP as an
unconfigured address. Existing amber warnings for enabled protected shuns remain.

The internal status response adds a separate bounded disabled-IP display list
from the same policy snapshot as the revision/enabled list. BFF display helpers
keep enabled and disabled sets separate; neither the worker policy nor queue
authorization changes. Existing revision-driven rendering updates the markers.
No migration, setting, secret, agent/protocol operation or device write was added.

**Validation:** 177 Python tests passed; all thirteen Chromium scenarios passed
(14 reported browser tests including the parent). Compileall, Ruff, Node syntax
and diff checks passed. New cases cover all four
enabled/disabled and active/inactive combinations through API/BFF, metadata
absence, unchanged eligibility/counts, and no queue/audit mutation during display.
Browser coverage checks actual badge colours and revision-driven replacement
across policy/shun/detail pages. The initial test adapter reused an asynchronous
HTTPX response stream in a synchronous mock; reconstructing the mock response
fixed the adapter without changing product behavior. The restricted sandbox
cannot run the browser's localhost server; validation uses the approved local
test execution outside that sandbox with fake devices and temporary state.

**Operational impact:** Paired API/Web upgrade and browser reload only. Rollback
to the preceding pair removes these display distinctions without changing
SQLite policy or queue data. The operator explicitly approved dev deployment
after checks, acknowledging that API restart can execute existing work. New
device writes/policy edits/refresh hints will not be submitted for validation.
Executable import and the operator's longer blocklist remain separate lab work.

**Deployment:** Preserved prior API/Web images under
`before-policy-badges-20261015t181200z`, built replacements, gracefully stopped
Web before API and recreated only those two services. Read-only checks retained
three existing policy entries (two enabled, one disabled), policy revision 3
and all six VERIFIED results. Enabled and disabled status sets exactly match
the SQLite snapshot and are disjoint; quick_check is ok and last_error is null.
The new process initially reports cycle_outcome=not_started; no extra refresh
was requested to bypass normal scheduling. Anonymous Shuns, Protected IPs,
detail, Import preview and status requests return 401; new CSS returns 200 and
HTTPS Protected IPs returns the expected TLS-verified Authelia 302. Agent,
Caddy, Authelia, schema, secrets and `.env` are unchanged. No policy mutation,
queue admission or new device write was submitted for validation. Reload tabs;
authenticated live UI inspection remains an operator task.

## 2026-10-15 — Large-list preview limits, byte validation and result pagination

**Status:** Implemented, tested and deployed to the explicitly approved dev lab

The operator supplied a 149,376-byte, 7,307-address list that exceeded the
original 64 KiB/2,000-line/1,000-row limits. HTML maxlength also truncated pastes
by characters while the server measured UTF-8 bytes, causing confusing partial
input and JSON-only errors. Raised the reviewed bounded preview limits to
1 MiB source, 20,000 lines, 10,000 rows, 64 devices and 100,000 expanded pairs.
The outer encoded-body cap is 3 MiB + 16 KiB for worst-case percent encoding
and metadata, including chunked requests. These are read/preview budgets,
not agent command or worker mutation limits.

Removed textarea maxlength and added a local UTF-8 byte counter using native
form CRLF line endings. Over-limit input remains editable and is blocked with
an explicit message; no silent truncation. Server-side decoded-text errors
retain escaped form data and HTML feedback even without JavaScript. Outer body
cap/encoding/CSRF failures remain controlled request rejections. The parser
runs in a worker thread and duplicate source-line tracking is linear in the
number of occurrences rather than repeatedly scanning the growing list.

All rows are parsed/classified before rendering 100-row pages with full-list
counts and First/Previous/Next/Last controls. Bounded page values submit the
same CSRF-protected form and recheck the current local snapshot; no URL text,
server-side draft, executable token, SQLite data or source logging is added.
The supplied attachment was processed locally in memory, producing 7,307
unique Ready candidates with no rejected/truncated rows; it was not committed,
queued, sent to an agent or applied to FTD.

**Validation:** 179 Python tests passed. Extended tests exercise the maximum
10,000-row batch, all-page coverage without omissions/overlap, full pair counts,
7,307-row BFF requests, page clamping/validation, oversized ASCII/multibyte HTML
feedback, worst-case UTF-8 encoding, chunked body caps and retained no-write
boundaries. All fourteen Chromium scenarios passed (15 reported browser tests),
including a real 7,307-row clipboard paste, first/next/last pages with 100/100/7
rows, preserved final source address, full candidate counts and oversized
multibyte input rejected without submission/truncation. Initial CDP text-entry
attempts timed out; the test now exercises actual clipboard paste within its
isolated headless profile with fixture-local permission, not the operator's
browser. CDP calls now have explicit 15-second deadlines. Spell checking is
disabled for the bulk address field. Compileall, Ruff, JavaScript syntax and
diff checks passed. No live authenticated UI or FTD write was used as evidence.

**Operational impact:** Upgrade API/Web together and reload tabs. No schema,
configuration, secret, agent/protocol or queue-budget change. Prior paired
images restore the former input limits without changing persisted state.
The operator approved deployment after tests, acknowledging that restart may
execute existing queue/policy work. No device mutation or new refresh hint is
needed for validation; actual addition/import remains unavailable.

**Deployment:** Tagged preceding API/Web images
`before-large-preview-20261015t182533z`, built replacements, gracefully stopped
Web before API and recreated only those services. The deployed Web's pure parser
read the operator attachment through stdin in memory and accepted all 7,307
unique addresses/149,376 bytes; only counts were printed. Raw attachment text
was not sent to API/agent or stored. A separate typed synthetic API preview
returned 7,307 addresses, preview_only=true/can_execute=false and zero audit
change during the read. All six VERIFIED outcomes, three existing protected
entries and policy revision 3 remain; quick_check is ok, last_error is null,
and the restarted scheduler initially reports not_started without an extra
refresh hint. Anonymous Import preview GET/POST and other pages/status return
401; the new script returns 200 and HTTPS redirects to Authelia with normal TLS
verification. No schema, environment, secret, policy, agent, Caddy or Authelia
change was made. Reload tabs and re-paste the original full list because the
old field's already-truncated content cannot be reconstructed. Authenticated
live browser inspection remains an operator task.

## 2026-10-16 — Colour-coded import preview outcomes

**Status:** Implemented, tested and deployed to the explicitly approved dev lab

Added consistent status badges to preview rows and full-list counts: Ready
green, Invalid/Unsupported red, Ambiguous/Protected amber, Already shunned blue
and Duplicate grey. Invalid/Unsupported rows have a red tint/leading border;
Ambiguous rows have amber cues. Existing protected-row highlighting is retained,
including the independent Protected IP marker on duplicate protected addresses.
Text labels and reasons stay visible; green is candidate data, not write success.

**Validation:** 186 Python tests passed; all fourteen Chromium scenarios passed
(15 reported browser tests). Compileall, Ruff, Node syntax and diff checks passed.
Seven template regressions cover explicit labels
in row/count badges. Chromium's existing synthetic preview scenario now covers
all seven outcomes, actual styles in light/dark themes, matching summary colours
and row warning borders/backgrounds while retaining no-write/no-hint behavior.
No source parser, policy, API, queue, schema, protocol, credential or setting
changed; test fixtures use synthetic source and temporary state only.

**Operational impact:** Rebuild/recreate Web and reload browser tabs only.
The operator explicitly approved Web-only deployment after tests. API and agent
remain running; no executor restart or new queue/refresh request is required.
The prior Web image restores the preceding presentation without data restore.
Authenticated live inspection remains an operator task; actual additions/import
and the outstanding FTD laboratory gates are unaffected.

**Deployment:** Preserved the old Web image as
`before-preview-colours-20261016t093234z`, built Web and recreated only Web
with --no-deps. Verified API, agent, Caddy and Authelia container IDs are
unchanged and running. New CSS status rules return 200 over the private Web
socket; anonymous preview GET/POST and refresh-status requests return 401.
HTTPS Import preview returns the normal Authelia 302 with TLS verification.
No policy mutation, queue admission, refresh hint or device write was submitted
for validation. Reload tabs; authenticated visual inspection remains an
operator task. Database, environment, credentials and agent were not changed.

## 2026-10-16 — Addition readiness and large-snapshot capacity blocker

**Status:** Read-only diagnosis and staged laboratory procedure completed and tested

Before adding an ADD capability, inspection found separate 64 KiB limits in the
Rust SSH output reader and fixed snapshot response protocol. 7,307 entries with
the ten-byte `management` interface need 109608 legacy response bytes/109612
cycle bytes. A generated benchmark-range CRLF CLI sample is 337679 bytes before
echo/prompt. These are synthetic calculations, not live FTD load evidence.
The 4,368-entry binary boundary is not an operational capacity claim: raw CLI
output can exceed its cap earlier. Preview's increased local input budget never
changed either agent limit. Current rejection behavior is retained.

Recorded the prerequisite for bounded complete-snapshot scaling, frame/byte/
entry/time budgets and atomic validation before reconciliation. Added a staged
operator manual for Basic-account preflight, one separately approved unused
TEST-NET creation and scoped cleanup, with stop conditions for pre-existing
state, policy races, failed prompts and unexpected interfaces. No new opcode,
arbitrary CLI path or actual write is introduced. Large-list application,
duplicate behavior and representative traffic-blocking proof remain gated.

Also corrected an objectively stale operating procedure: the main FTD lab
manual still instructed edits to the legacy policy environment variable even
though SQLite now owns policy. The current procedure uses Protected IPs, records
the baseline count/revision, deletes only the fixture and preserves unrelated
entries; no API restart is required. Historical engineering entries are intact.

**Validation:** All 189 Python tests passed; compileall, Ruff and diff checks
passed. Added synthetic management-snapshot regressions at
4,368/4,369/7,307 entries for both legacy and cycle decoding. They demonstrate
the exact fixed-packet capacity boundary and fail-closed rejection rather than
truncation or implicit support for preview-sized device populations.
Rust/runtime/UI source is unchanged in this increment; no new live FTD evidence
or browser result is claimed.

**Operational impact:** Documentation and local regression tests only. No
deployment, schema, environment, credentials, running services or device state
changed. The optional direct-CLI fixture requires separate operator approval;
the assistant has not executed it. The next read-path extension and ADD design
must be reviewed and tested before import admission/provenance implementation.

## 2026-10-16 — Operator-observed Basic single-address creation

**Status:** Direct CLI addition observed; scoped cleanup confirmation pending

Following an empty `show shun 198.51.100.251`, the operator ran the single
approved test addition as the reported Basic `ftd-shun-lab` account. FTD returned
`Shun 198.51.100.251 added in context: single_vf` and
`Shun 198.51.100.251 successful`; the next target read showed
`shun (management) 198.51.100.251 0.0.0.0 0 0 0`. The exact transcript is
recorded in the addition lab manual. The FPR1010/FTD 7.6.6 profile and account
role are operator-reported context, not an independent version/role recheck.

Requested cleanup only for this newly created target using its observed
`management` interface, followed by a target read. No cleanup result has yet
been supplied; absence is not assumed. No additional add, duplicate test or
bulk-list application was requested. This confirms a single Basic creation and
CLI observation only, not data-plane blocking, fleet-wide creation scope,
agent/protocol verification, timing bounds or large-snapshot capacity.

**Validation/impact:** Evidence-only documentation update; diff checks run.
The assistant did not execute an SSH command, mutate service policy/queue or
deploy/restart anything. The operator changed one lab fixture; its cleanup
remains the immediate next step. Historical entries and existing limits remain
unchanged. No imported provenance or production capability is claimed.

## 2026-10-16 — Operator-confirmed cleanup of the Basic addition fixture

**Status:** Single-fixture direct CLI lifecycle completed

The operator returned the exact follow-up transcript:

```text
> no shun 198.51.100.251 interface management
> show shun 198.51.100.251
>
```

This supplies the cleanup evidence missing from the preceding entry. Together
with the earlier absent preflight, successful Basic addition and `management`
observation, it completes absent → added → observed → removed → absent for
this one TEST-NET fixture. Updated the current status, plan and lab manual;
the prior pending-cleanup log entry remains unchanged as chronological history.

**Validation/impact:** Documentation-only evidence update; diff checks passed.
No assistant-issued device command, deployment, setting, schema or code change.
The operator removed the newly created lab fixture; its preflight absent state
is restored in the supplied CLI observation. This does not establish data-plane
blocking, duplicate behavior, agent ADD/provenance or large-snapshot capacity.
The next implementation prerequisite remains bounded complete-snapshot scaling;
the existing 64 KiB limits and fail-closed behavior have not changed.

## 2026-10-16 — Default-off bounded large snapshots and cycle v2

**Status:** Implemented, tested and deployed to the explicitly approved dev lab

Added a separate strict false-by-default API/agent flag selecting read-only
LIST_SHUNS_LARGE (07) and cycle version 2 snapshots. Request sizes and existing
mutation meanings/budgets remain fixed; no ADD/import or generic CLI primitive.
Agent rejects disabled new reads/v2 before SSH. v1 and legacy retain 64 KiB
limits and shared wire-vector regressions. No fallback or automatic negotiation.

Snapshots use an exact manifest, ordered indexed 32 KiB data chunks and mandatory
SHA-256 end. Bounds are 20,000 entries, 2 MiB data/64 chunks and 66 total frames;
every packet remains within the existing 64 KiB receive buffer. Typed interface
grammar, total count, size, binding, ordering, digest and exact entry decoding
all precede any reconciliation. Empty requires manifest plus end; EOF/rejection
is never empty. Partial/corrupt snapshots discard buffered data and retain prior
observations. SHA-256 is completeness, not a substitute for UID authentication.

Only opted-in full reads collect up to 4 MiB console output; login/target/write
reads retain 64 KiB. Prompt waits remain 15 seconds. All stream packets share
one <=10-second send/receive deadline within the existing operation/step/session
deadlines, preventing per-chunk timeout resets. No pager commands or guessed
output parsing. Added direct sha2 0.11 use of the already locked dependency,
without upgrading unrelated packages. Agent cycle logs include protocol version.

**Validation:** 230 Python tests and 26 Rust tests passed. Includes shared v2
vectors, real local SeqPacket streams, synthetic 7,307 and 20,000 entries (also
64-byte interfaces), legacy boundary/vector retention, malformed counts/lengths/
fields, missing/reordered/duplicate/corrupt frames, wrong bindings, truncated
packets, flag rejection, stalled peer and absolute deadlines. An interrupted
empty stream preserves the existing active SQLite record/events/revision and
queues nothing. v2 fake-console removals retain verified/no-op/deferral meaning.
Release build, Clippy -D warnings, compileall, Ruff and diff checks passed.
Initial un-escalated Rust socket tests hit sandbox EPERM; running the synthetic
socket tests outside that sandbox passed. Synthetic coverage is not live FTD
load evidence; the separate small-read deployment check is recorded below.

**Operational impact:** No schema/data migration. Preserve paired API/agent
images and a SQLite-safe backup; stop the API executor before agent replacement.
The operator explicitly approved deployment and flag opt-in in the dev lab,
acknowledging existing queue/policy execution on restart. Web needs no rebuild.
Never run old/new executors together. Rollback disables both flags and restores
paired images; it restores legacy capacity, not a large-population solution.
No new mutation/refresh hint will be submitted for validation. ADD, real large-
load FTD timing/paging and live v2 mutation/priority cases remain separate work.

**Deployment:** Preserved preceding API/agent images as
`before-large-snapshots-20261016t100451z` and built the new pair. Created a
SQLite-backup-API copy with quick_check=ok and mode 0600. Docker archive copy
could not see the first backup on container tmpfs despite exec confirming it;
a second verified backup on the state volume copied successfully to the ignored
mode-0700 `.local/backups/state-before-large-snapshots-20261016T100451Z.sqlite3`.
The retained host copy is mode 0600 and quick_check is ok. No database restore
or schema/data migration was performed.

Gracefully stopped API before agent, added only the approved true flag to
the ignored `.env`, and recreated API/agent only. No old/new executors overlap.
The first live cycle logged protocol_version=2, two full snapshot commands,
zero removals and 8282 ms, with successful API outcome and no error. Both new
flags report true; six existing VERIFIED outcomes and all three policy entries/
revision 3 remain. Live SQLite quick_check is ok. Web, Caddy and Authelia container
IDs are unchanged. Anonymous Shuns/Imports/Protected-IPs/status requests return
401 and HTTPS Import preview returns the normal TLS-verified Authelia 302.
No new queue admission, policy edit, refresh hint or device write was submitted.
This validates small live BEGIN/END framed snapshots only; large-population
FTD reads, paging/timing, v2 mutations/priority and ADD remain unvalidated.

## 2026-10-16 — Protected-first, newest-current-appearance active shuns

**Status:** Implemented and tested; paired API/Web rollout awaits approval

Active-list SQL now joins exact Protected IP membership (enabled or disabled)
and orders those warnings before other current rows, then current-appearance
time descending and numeric IP/hostname/interface ties. Existing `last_changed_at`
becomes additive `active_since_at` in list/detail JSON. Web labels it Observed
since, using the existing browser-local timezone formatter; lifetime first-seen
history is unchanged. Reappearance moves up; ordinary polling does not. No
FTD creation-time/order claim is made for rows discovered in the same snapshot.
Disabled matches remain ineligible for policy removal. Search/history ordering,
queue, agent protocol and SQLite schema are unchanged. Paired API/Web upgrade
and tab reload suffice; a field fallback supports older API responses during
rollback. API restart can execute existing queue/policy work as usual.

**Validation:** All 237 Python tests passed, covering both snapshot/single-row
observation paths, lifetime-vs-current timestamps, stable numeric/multi-device/
interface ties, enabled/disabled policy edits, inactive exclusion, complete
20,000-row sorted snapshots and API/BFF rendering. Fourteen real Chromium
scenarios passed (15 reported tests), including localized current-appearance
time instead of lifetime first detection. Compileall, Ruff and diff checks
passed. No new queued mutation,
policy edit, refresh hint or direct agent read was submitted to the lab.

Read-only deployed API inspection after operator-created additions returned
61 active records, no device error and last successful refresh at
2026-10-16T10:12:52Z. Agent cycle v2 logged two full snapshots, zero removals and
8072 ms. This is small-population read compatibility only: independent full
CLI-count agreement, real multi-chunk load/paging, v2 write/priority cases,
duplicate/creation-scope/data-plane validation and automated ADD remain pending.

No sorting rollout has been performed. Requested explicit paired API/Web
deployment approval, noting possible execution of existing queue/policy work
on API restart. Agent/Caddy/Authelia need no change for this increment.

## 2026-10-16 — Standing lab deployment authorization and active-order rollout

The operator explicitly authorized deployment while work remains on the current
non-production lab. Recorded the authorization in AGENTS.md and the deployment
manual: announce affected services/impact, deploy validated in-scope changes,
retain rollback options and record results. This includes normal existing
queue/policy execution on API restart, not new test mutations/imports,
destructive data operations, production rollout or bypassing feature gates.

Deployed the preceding tested sorting increment (237 Python tests and fourteen
Chromium scenarios previously passed). Preserved both old images with the
`before-active-order-20261016t102506z` tag and created a SQLite-backup-API copy
under the state volume, then copied it to the ignored mode-0700 host directory:
`.local/backups/state-before-active-order-20261016T102506Z.sqlite3`. Both backup
integrity checks returned ok and the host file is mode 0600. No restore, schema
migration, setting or credential change was needed. Built API/Web, gracefully
stopped the old API executor and started the new pair without dependencies;
no old/new API workers overlap. Agent/Caddy/Authelia IDs are unchanged.

**Post-deployment checks:** The new API returns `active_since_at` on all 61
active records and protected-first/newest-current-appearance ordering, with one
protected-policy match. Three policy entries/revision 3 and all six VERIFIED
results remain; live SQLite quick_check is ok. Anonymous Shuns/Imports/Protected
IPs/History/status requests return 401. HTTPS Shuns redirects to Authelia (302)
with TLS verification. No new queue admission, policy edit, refresh hint or
direct agent read was submitted. Reload tabs for the updated templates;
authenticated visual inspection and large-population/ADD lab gates remain.

The first normal post-restart cycle respected the existing persisted eligibility
gate and succeeded at 2026-10-16T10:26:58Z. Agent v2 logged two full reads,
zero removal steps and 8191 ms; API reports success/no error and the next
baseline at 10:31:58Z. No special validation refresh was submitted.

## 2026-10-16 — Offline ADD evidence model and protocol review draft

**Status:** Implemented/tested as offline preparation; live ADD still unavailable

Added an explicitly non-executable addition contract draft: agent-owned reviewed
creation profile, target preflight/no-op, exact known acknowledgement and fresh
source-only post-read, proposed cycle v3/ADD encoding, combined ADD/REMOVE
budgets, uncertainty/no replay and outstanding admission/provenance decisions.
It is not a normative live protocol or a waiver of the existing lab gates.

The Rust evidence model is linked only under `cfg(test)`, with no RPC/SSH sender,
socket or database. It requires both acknowledgement lines in order for the
same target/context, plus exactly the recorded interface/zero destination and
port/protocol fields. It uses the existing strict observation parser while
also checking fields omitted by the normal read DTO. Pre-existing targets on
any allowed interface are no-op and cannot be written/relabelled as imports.
Malformed preflight is not absence. Missing/partial/extra/reversed/duplicate
success, wrong target/context, controls/Unicode, oversize, unexpected interfaces,
multiple rows and non-source-only verification all refuse creation assessment.
Acknowledgement or observed presence alone is insufficient. Release agents do
not contain this model; current Python/Rust decoders still reject ADD/v3.

**Validation:** All 242 Python and 33 Rust tests passed, including synthetic
local socket suites, six new offline evidence tests and production-boundary
rejection regressions. Locked/offline release build, Clippy -D warnings, fmt,
compileall, Ruff and diff checks passed. Browser tests were not rerun: no Web
template/JavaScript/style changed (the preceding fourteen scenarios passed).
No runtime/schema/setting/queue contract changed, so no rollout/backup/migration
or data restore is needed. Existing lab services were not restarted.

The operator approved providing output for one Basic-account duplicate test.
Read-only API preflight found `198.51.100.251` locally absent, no enabled
protection and no unfinished queue (six VERIFIED outcomes). Supplied conditional
fresh device preflight, one creation/read, one duplicate/read and scoped cleanup/
read steps, with explicit stop conditions and no pre-existing-entry cleanup.
Recorded the staged procedure; actual duplicate results remain pending. No
assistant device mutation, direct agent read, policy/queue edit or refresh hint
was submitted. Live duplicate/scope/traffic, real large-read capacity, v3 runtime,
durable admission/provenance and executable imports remain separate next steps.

## 2026-10-16 — Operator duplicate-add evidence and no-ownership regression

The operator returned the approved one-fixture direct-CLI transcript: initially
absent `198.51.100.251`, successful source-only creation, one repeated add,
an identical single `management` row after each, interface-scoped removal and
an empty final target read. Both add acknowledgements contain identical
`single_vf` and successful lines. Model/version/role rely on the previously
reported FPR1010 / FTD 7.6.6 Basic profile, not a fresh read in this transcript.

Stored the normalized command outputs as a TEST-NET fixture, explicitly marking
operator origin, prompt omission/LF normalization and the difference between
observed empty output and transport EOF. Added a test-only Rust regression
checking the full command sequence, both identical acknowledgements, source-only
visibility and cleanup. Both acknowledgement grammars are valid; the model
must still take AlreadyPresent without a write on fresh nonempty preflight
and refuse to label a repeated write as new creation/import ownership. Updated
the addition procedure/contract, current status and plan with this evidence.
Earlier chronological pending-result entries remain historical records.

**Validation:** All 242 Python and 34 Rust tests passed. Locked/offline release
build, Clippy -D warnings, fmt, compileall, Ruff and diff checks passed. No Web
code changed, so browser tests were not rerun. No runtime protocol, SSH sender,
schema, setting, admission or policy behavior changed; no rollout/backup/restore
is required. No assistant-issued device mutation, agent read, queue/policy edit
or refresh hint was submitted; the reported fixture was cleaned up by the
operator, not the service.

This closes the visible direct-CLI duplicate/cleanup observation for one
fixture only. It does not prove internal counter/age stability, physical
exactly-once behavior, real traffic blocking, fleet scope, large-population
reads or service-executed ADD. Fresh preflight and no automatic replay remain
required. Runtime ADD and durable admission/provenance remain future increments
behind their documented review and enablement gates.

## 2026-10-16 — Default-off ADD/cycle v3 agent and transport

**Status:** Implemented/tested; disabled-gate lab deployment recorded below

Following the operator's request to continue with gated runtime ADD, promoted
the offline draft to the experimental contract without waiving enablement gates.
Added an agent-only strict false-by-default `FTD_SHUN_AGENT_ADDITIONS_ENABLED`
gate; v3 also requires cycle/large-read flags and an explicit recognized enabled
device profile. Missing gate/profile fails before secret access/SSH. Unknown
profile/type or profile outside the allowlist fails startup. Existing real
inventory/settings are not changed; tracked example profile is null.

The private typed sender constructs only source-only shun for a typed IPv4.
The cycle reuses strict production helpers now shared with the evidence model:
fresh target preflight, no write/ownership on existing targets, exact profile-
bound acknowledgement and fresh full-field source-only verification. No generic
CLI/interface/context enters the request. ADD is opcode 14 in version 3 only,
with exact no-op/verified-interface/pre-write-deferral results. No standalone
ADD or v1/v2 wire extension, fallback, reconnect, replay or automatic undo.
Snapshots retain bounded manifest/chunks/end and bind version 3 explicitly;
independent large reads stay v2. ADD/REMOVE share 16 attempts, including no-ops/
deferrals, 64 commands and existing absolute time/final-read/priority reserves.
The observed-entry budget prevents an absent-target add at 20,000; external
writers can still race it, and later failed snapshots do not replay writes.
JSON logs add sanitized per-ADD events and addition/combined attempt counts.

Python selection is explicit at the low-level client and requires large reads.
The ordinary API factory still selects v1/v2 even if the agent flag is true;
no route, queue admission/dispatch, provenance/schema or Web change is included.
Future integration must enforce roles, policy, idempotency, expiry and conflicts
before dispatch. A transport success is not a queued import or database origin.

**Validation:** All 275 Python and 38 Rust tests passed: shared exact v3 wire
vectors, complete 20,000-entry v3 streams with version binding, one real local
SeqPacket mixed add/no-op/priority/remove/final conversation, malformed/wrong/
lost responses, timeout close/no replay, no old-mode fallback, explicit selector,
profile validation, disabled/missing gates before SSH, combined budgets and
verification/capacity failures. Existing v1/v2 vectors, removal, scheduler and
state-retention regressions remain green. Locked/offline release build, Clippy
-D warnings, fmt, compileall, Ruff and diff checks passed. Browser tests were
not rerun because no Web assets/templates or browser-facing routes changed.
These synthetic results are not live ADD/timing/traffic or large FTD evidence.

**Operational plan:** Under standing lab deployment authorization, preserve
paired images and a SQLite-safe backup, stop API before replacing agent and
restart only API/agent. No schema migration/restore or real inventory/.env edit.
Preflight found 61 active records, six VERIFIED outcomes, three policy entries/
revision 3, no configured addition profiles and ADD false/absent; quick_check
is ok and no device error. Web/Caddy/Authelia must remain unchanged. This rollout
keeps ADD off and submits no new mutation, refresh hint or independent writer.
Admission/provenance, scoped live ADD, traffic/creation scope and real large-load
read checks remain next work before any actual import enablement.

**Deployment:** Preserved old paired images with the
`before-addition-v3-20261016t121152z` tag. SQLite backup API produced a checked
copy on the state volume, copied to the ignored mode-0700 host directory as
`.local/backups/state-before-addition-v3-20261016T121152Z.sqlite3`; host file is
0600 and quick_check is ok. Built API/agent, stopped API before agent and
recreated only that pair, with no overlapping executors. No real inventory/
`.env` edit, schema migration or restore. Web/Caddy/Authelia IDs are unchanged.
Deployed checks confirm ADD gate false/absent, no configured profiles, ordinary
API additions_enabled=false/large reads=true, all 61 active records with correct
ordering, three policy entries/revision 3, six VERIFIED outcomes and SQLite
quick_check=ok. No direct agent read, new queue admission, policy edit, browser
refresh hint or test device write was submitted during validation.

The first post-upgrade cycle completed at 2026-10-16T12:14:44Z with version 2,
two full reads, zero addition/removal/mutation steps and 8156 ms. API reports
success/no error and a next baseline five minutes later. Anonymous Shuns,
Imports, Protected IPs, History and freshness requests remain 401; HTTPS Import
preview redirects to Authelia (302) with TLS verification. This validates v2
compatibility with ADD disabled, not live ADD or authenticated visual behavior.

## 2026-10-16 — Staged import admission, conflicts and occurrence provenance

**Status:** Implemented/tested; gated-off API/Web lab rollout completed

Added strict false-by-default `FTD_SHUN_IMPORT_ADMISSION_ENABLED` and private
typed `POST /api/v1/imports`: explicit UUID key, canonical target/metadata digest,
captured write role, current policy revision, enabled-device/protection checks
and existing queue capacity/rate/short-expiry limits. The digest is confirmation
binding, not authority. Opposite ADD/REMOVE jobs reject the whole transaction;
same-action actors coalesce while retaining distinct batch/audit records.
Neither preview nor any BFF form submits ADD. Admission does not signal device
work; the scheduler remains REMOVE-only/v1/v2 and ignores held ADD for cycle
cadence. There is no automatic chunking/authorization extension for 7,307 IPs.

Additive migration introduces immutable job action/dispatch marker, immutable
manual-import batches and verified origin rows plus opaque current-occurrence
IDs. Existing jobs default to REMOVE, old dates/IDs/states remain, and the old
nine-column request layout stays compatible; effective import source is explicit
in batch data/events/views rather than a rewritten old CHECK. Legacy-claim and
occurrence triggers prevent ADD-as-REMOVE and inherited provenance under older
writers, but downgrade still requires offline pending-work suspension/review.

Future default-disabled domain claim/completion hooks are tested with synthetic
typed results only: verified creation commits state/origin/audit atomically;
pre-existing/no-op, failure, lease loss and uncertain replies never assign new
origin or replay. Later snapshots/retries cannot promote unknown ADD. A new
external occurrence loses the badge while continuous polling preserves it.
Active attribution survives queue pruning; inactive origins/unreferenced batches
age out under retention. API/UI adds one representative origin plus exact total,
blue badges, escaped batch details and localized verified times. Full batch JSON
is decoded once per distinct batch and is absent from queue display metadata.
Held jobs are explicitly labelled execution-disabled and remain cancellable.

**Validation:** All 297 Python tests passed, including concurrent actors,
conflict rollback without partial logs/audit, policy CAS/change, capacity/rate,
idempotency/expiry, no-op/unknown/lost-worker behavior, REMOVE-only scheduler,
old schema migration/positional inserts/claim triggers, restart/reappearance,
retention, 1000-target metadata bounds, escaping and nested API DTOs. Fifteen
real Chromium scenarios passed (16 reported tests), including held ADD
cancellation and badge/detail replacement on a new occurrence. Compileall,
Ruff and diff checks pass. The first sandboxed full-suite run stalled on local
ASGI/socket support and was interrupted; the full suite passed with local
permissions. Rust/agent/protocol are unchanged, so their previous 38-test/
release evidence was not rerun or claimed as live addition evidence.

Updated normative Section 74, status/plan, contributor rule and structured
manuals, including new Import Admission migration/backup/rollback procedure.
Pre-deployment read-only checks: 61 active rows, six VERIFIED jobs, three policy
entries/revision 3, no error, quick_check ok and no foreign-key errors. Baseline
completed at 12:47:58Z; cycles/large reads remain enabled. Rollout will preserve
old API/Web images and a fresh SQLite-safe backup, then recreate only API/Web
with admission/ADD off and inventory unchanged. No new job/policy edit, direct
agent read, refresh hint or test device mutation is submitted. Actual scheduler
integration, scoped live ADD, creation/traffic scope and large-load evidence
remain before any executable import enablement.

**Deployment:** Preserved preceding API/Web images with tag
`before-import-staging-20261016t125228z`. SQLite backup API produced an
integrity-checked private copy on the state volume and the ignored host path
`.local/backups/state-before-import-staging-20261016T125228Z.sqlite3` (0600;
directory 0700). Host quick_check is ok and foreign_key_check has no rows.
Built API/Web; the packaged Python 3.12 image passed isolated offline schema/
safe-default initialization without lab mounts, secrets or networking. Final
297-test Python and 15-scenario Chromium runs and static checks passed.
Stopped the sole API executor cleanly and recreated only API/Web. Agent,
Caddy and Authelia container IDs are unchanged; no overlapping executor,
real inventory/.env edit or backup restore.

Deployed read-only checks confirm 61 active rows, one protected match, correct
ordering, three policy entries/revision 3, six VERIFIED REMOVE jobs, nine-column
compatible requests and no null occurrence IDs. New batch/origin tables are
empty and existing shuns have no false manual-import badge. quick_check is ok;
foreign_key_check has no errors. Comparing the retained backup confirms all
legacy job fields and stable first-seen/current-appearance dates are unchanged.
API admission/execution and ordinary-client addition selector remain false.
One combined diagnostic was rejected by automatic review because it would read
the full confidential inventory to count profiles; it was not executed. That
optional count was omitted, not bypassed. Other aggregate/gate checks passed
without opening inventory; no profile-presence claim is made for this rollout.

The first ordinary post-upgrade v2 cycle completed at 12:55:30Z with two reads,
zero addition/removal/mutation steps and 8254 ms; no error and the next baseline
is 13:00:30Z. Anonymous Shuns, Imports, Protected IPs, History and freshness
requests return 401. HTTPS preview redirects to Authelia (302) with normal TLS
verification. No new admission, policy edit, refresh hint, independent agent
read or device test mutation was submitted. This validates disabled-mode
compatibility/migration only; authenticated visuals and live ADD remain separate.

## 2026-10-16 — Independently gated shared ADD/REMOVE worker

**Status:** Implemented/tested; disabled-mode API/Web lab rollout completed

The operator approved the next default-off integration step. Added independent
strict `FTD_SHUN_IMPORT_EXECUTION_ENABLED=false`; true requires socket mode,
session cycles and large reads. The ordinary validated inventory loader carries
recognized addition profiles as startup-only capabilities, not a schema/policy
or user-selected scope. API transport always receives an exact enabled-device
set, including empty: eligible devices explicitly select v3, others keep v1/v2.
The independent agent gate/profile remains authoritative; no fallback or new
agent binary/opcode is introduced. Intake can be disabled while authorized
work drains; no executable BFF import or new live device write is enabled.

The sole leased worker atomically claims common FIFO ADD/REMOVE under its
cutoff, with the existing trusted-policy exception, shared 16-processed-step/
command/time bounds, persisted cooldown and priority/final-read reserves.
Every claim rechecks current policy/device and captured authorization. Long
cycles now also expire unstarted coalesced actors before the next claim, so an
expired actor receives no new origin from another actor's still-valid request.
Already RUNNING work retains its original claim through completion.

ADD consumes only exact typed results: verified creation commits occurrence
provenance immediately, no-op does not assign origin, and explicit pre-write
deferral alone requeues/clears dispatch marker. Missing/malformed/lost results
settle UNVERIFIED and abort, never inferred from later presence or replayed.
Shutdown retains the lease for bounded in-flight RPC recovery; later/final-read
failure preserves earlier verified work. No extra SSH session/writer is used.
Published metadata reports API gate/eligible count and per-job eligibility;
the UI distinguishes held/running ADD and shows Adding and verifying. Eligible
new private admission wakes work; replay/held-only requests do not. No BFF submit.

**Validation:** All 320 Python tests passed, including prior compatibility plus
mixed FIFO/16-step/cooldown, independent gates/profile selection, version refusal,
per-claim policy/expiry/coalesced actor checks, priority-after-verification,
cancellation/cutoff, exact deferral, typed malformed/lost results, no-op origin,
multi-device isolation, final failure/restart, shutdown/lease recovery and actual
local SeqPacket worker success/lost-result conversations. Fifteen real Chromium
scenarios passed (16 reported tests), including held/running eligibility,
readable ADD phase, indeterminate progress and no mutation from metadata updates.
Compileall, Ruff and diff checks passed. All test state/transport is synthetic;
no SSH/password/.env/lab inventory is used by tests. Rust/agent/wire definitions
are unchanged; previous agent evidence is not claimed as new live validation.

Updated normative Section 74, working agreement, status/plan, relevant manuals
and new structured Import Execution manual (gates, bounds, recovery, capacity,
deployment/rollback). No schema change beyond the prior staged-admission
migration and no limit/authorization extension for 7,307 addresses. Scoped live
ADD/traffic/scope/read validation and executable browser submission remain next.

**Pre-rollout:** Read-only aggregates show 61 active rows, six VERIFIED jobs,
three policy entries/revision 3, both API gates off, no error, quick_check ok
and no foreign-key errors; last refresh 16:34:56Z. A narrow non-secret flag-name
check found no explicit ADD/admission/execution value in the real `.env`, so
their defaults remain false. No full inventory or other environment values
were read for diagnostics. Preserve a fresh SQLite-safe backup and preceding
API/Web pair, stop the API executor cleanly, and recreate only API/Web. Agent,
Caddy and Authelia remain unchanged. Startup can execute existing removal/policy
work, but no new jobs, policy edits, refresh hints or test mutations are submitted.

**Deployment:** Preserved preceding API/Web images with tag
`before-import-worker-20261016t163910z`. SQLite backup API created an
integrity-checked private volume copy and ignored host backup
`.local/backups/state-before-import-worker-20261016T163910Z.sqlite3` (0600;
directory 0700); host quick_check and foreign_key_check passed. Built API/Web
and ran packaged Python 3.12 ASGI/status/schema safe-default smoke offline with
no secrets, lab mounts or network. Existing dependency ranges resolved FastAPI
0.143.3 in this build (prior image 0.143.2); reproducible Python dependency
locking remains follow-up work, not implemented by this increment.

Stopped the sole API executor cleanly and recreated only API/Web. Agent,
Caddy and Authelia IDs are unchanged; no overlapping executor, schema change,
real inventory/.env edit, database restore or new work was submitted. Deployed
API reports admission/execution/client ADD selector false, eligible count zero,
61 active records/one protected match, six VERIFIED jobs and three policy
entries/revision 3. Ordering is correct; comparing the retained backup confirms
all old job fields and stable first-seen/appearance/occurrence IDs are unchanged.
Origin count remains zero, quick_check is ok and foreign_key_check has no rows.
No full inventory was read for diagnostics; capability count came from safe
runtime metadata and is not a claim about declared profiles while gates are off.

The normal post-restart v2 cycle finished at 16:42:18Z with two reads, zero
addition/removal/mutation steps and 8003 ms, no error and next baseline 16:47:18Z.
Anonymous Shuns, Imports, Protected IPs, History and freshness requests return
401. HTTPS Import preview redirects to Authelia (302) with normal TLS
verification. No refresh hint, independent agent read, new job/policy or test
device mutation was used for deployment checks. This is disabled-mode
compatibility evidence, not live v3/ADD/traffic/large-load validation.

## 2026-10-16 — Prepare, but do not execute, one-address service validation

**Status:** Runbook prepared; fresh device evidence and scoped approval pending

Following the operator's request to prepare and separately agree a service test,
added One-Address Service Validation: explicit target/window/temporary-config
authority, fresh Basic-account absence, private maintenance identity, canonical
one-target admission, same-key replay versus new-key already-present no-op,
expected verified occurrence provenance/audit, authenticated scoped cleanup,
no automatic re-add and safe gate/profile restoration. It is a proposed runbook,
not an executable helper or authorization. Any limited validation experiment
before general traffic/load acceptance still needs explicit review/approval.
No profile, privilege, raw CLI route, writer or application capability is added.

Read-only cached preflight at 2026-10-16T16:54:07Z confirmed device 1 enabled as
fpr1010-lab, fixture 198.51.100.251 locally absent, no enabled protection, zero
unfinished target/all jobs, API admission/execution false, eligible count zero,
cycles/large reads true and quick_check ok. Device ready/no error with last
ordinary observation 16:52:34Z. No independent agent read or refresh hint was
issued; cached absence is not fresh SSH evidence or address-unused assurance.

Updated status, normative Section 74 references and manual index/worker links.
Corrected readiness-manual present-tense claims that ADD/admission/provenance/
worker did not exist; retained direct-CLI transcripts and historical log entries.
Fresh Basic/model/version confirmation, device target absence and explicit
approval of one creation/no-op/cleanup plus temporary enablement remain needed.
No runtime/source code, schema, settings, inventory, deployment, admitted work
or FTD mutation changed. No rollout/restore is required; existing private backups
remain untouched. Documentation diff/link checks are performed before handoff;
Python/Rust/browser suites need no rerun for this documentation-only increment.

## 2026-10-16 — Approved one-fixture service experiment: scope and preflight

**Status:** Explicitly approved; execution/results pending

The operator separately approved the proposed one-IP experiment and supplied
fresh Basic-session `show shun 198.51.100.251` returning only the normal prompt.
Scope is device 1/fpr1010-lab, unused TEST-NET fixture only, temporary gate/profile
enablement, one queued creation, same-key replay/already-present no-op and scoped
cleanup, then restore ADD-disabled operation. This is a limited CLI-lifecycle
validation exception, not a waiver of traffic/scope/load/production readiness,
permission for the long list or general ADD enablement. Recorded the explicit
exception in the working agreement, normative design and runbook before setup.

Read-only recheck at 16:59:31Z confirms 61 active records, six existing VERIFIED
jobs, policy revision 3, no fixture presence/protection or unfinished work,
both API gates off, ready/no-error device, quick_check ok and no foreign-key
errors. Only selected non-secret inventory fields were inspected for the
authorized target edit: one device, management allowlist, no existing profile.
Service username is ftd-shun-lab, matching the prior validated Basic account;
actual model/version/role are operator-reported, not freshly probed via CLI.

Use maintenance:single-address-validation / Operator-approved lab validation
with the explicitly granted Operator role for trusted-host private API requests,
including device-specific queued cleanup if assistant-run. This is not an
Authelia user/session and does not validate BFF authorization. No authentication
headers are forged. The test uses only the leased worker; a fresh normal v3
snapshot must succeed with no mutation before admission. Keep .env unchanged
using a private local Compose override; add only the approved device profile
and remove that field after the test. Preserve a fresh SQLite-safe backup and
current API/agent/Web images before enabling anything. Retain evidence/unknown
outcomes; do not reset a database, replay an uncertain ADD or clean a pre-existing
row. Results will be appended only after observation.

## 2026-10-16 — Live one-address v3 creation/no-op/cleanup completed; gates restored

**Status:** Approved fixture passed; authorization consumed, general ADD off

Preserved exact current API/agent/Web image tags
`before-single-address-20261016t170037z` and a checked SQLite-safe backup on the
state volume plus ignored host file
`.local/backups/state-before-single-address-20261016T170037Z.sqlite3` (0600,
private directory 0700). The operator supplied fresh Basic target absence.
Added only device 1's recognized management profile and enabled temporary gates
using a private local Compose override, without editing .env. Stopped the sole
API before agent recreation; no overlapping writer, direct RPC or raw CLI write.
Account is ftd-shun-lab, matching the earlier operator-reported FPR1010/7.6.6/
Basic profile; no fresh model/version/role command was added or claimed.

A normal v3 zero-mutation initial/final read succeeded at 17:03:14Z (two
commands, 8972 ms), confirming fresh complete small state with fixture absent.
Private requests used the explicitly declared maintenance actor, not spoofed
Authelia/Web identity. Exact canonical body/key was saved privately before each
submission; target was only device 1 / 198.51.100.251 under policy revision 3.

Observed sequence:

- Creation request `cf13f6de-9eb8-4461-9713-497bd820606a`, job
  `ed1effdf-8e3d-467f-9e68-98cb57081641`: accepted 17:05:10.944Z, claimed
  17:05:17.657Z, VERIFIED 17:05:24.909Z. Agent emitted add_shun.verified;
  cycle five commands/15490 ms, successful final snapshot. One current
  management occurrence/origin and SHUN_ADDED_BY_IMPORT for maintenance actor.
  Operator independently observed the exact source-only row.
- Exact original-key replay returned replayed=true, same parent, one linked
  job/origin, without new work.
- Already-present request `8aa0f424-0ece-4f2c-a904-9ae5ff4f0437`, job
  `60efa008-f1d1-4004-b425-576be53bfcd1`: accepted 17:06:56.703Z, claimed
  17:07:03.531Z, NOOP 17:07:06.477Z. Agent add_shun.noop; three commands/
  11276 ms, no second creation command or new origin; original count remains one.
- Scoped removal request `d42bb709-f9a2-471a-bd5c-0843d50867ac`, job
  `bf6716af-c8cd-4909-8c84-57acabd780b9`: accepted 17:08:03.393Z, claimed
  17:08:14.810Z after persisted eligibility, VERIFIED 17:08:25.948Z. Exact
  verified response, successful final absence and independent operator empty
  target read confirm cleanup. The event uses the existing SHUN_REMOVED_BY_UI
  name, but actual caller was the declared private maintenance actor, not a
  browser login. Removal agent cycle counts/timing were not captured before
  recreation and are not inferred from expected command sequences.
- Original creation-key replay after cleanup returned the same completed
  reference. Total jobs stayed nine, unfinished zero, fixture absent: no re-add.

After terminal cleanup/replay, stopped API then agent, removed the temporary
profile and verified inventory/.env contents match pre-test checksums exactly.
Removed only the patch-added trailing LF to restore original inventory bytes;
no device address/key or unrelated configuration changed. Disarmed the retained
private override and recreated API/agent using ordinary base lab files. No image,
application/agent code, schema, secret, policy or database restore changed.
Web/Caddy/Authelia IDs are unchanged; audit was retained, not erased.

The restored normal v2 cycle completed successfully at 17:11:13Z with two reads,
zero mutations and 8997 ms; next baseline 17:16:13Z. At 17:11:48Z, admission/
execution false, eligible devices zero, agent ADD absent/default false,
fixture absent, unfinished jobs zero, original 61 active rows and policy three
entries/revision 3. Queue has eight VERIFIED/one NOOP: six old plus exactly
ADD VERIFIED, ADD NOOP and REMOVE VERIFIED test jobs. Backup comparisons prove
unrelated state/stable timestamps/occurrence IDs, old jobs and policy unchanged.
One inactive fixture origin and all request/audit records survive restart.
quick_check ok, foreign_key_check empty; anonymous pages/status 401 and normal
TLS-verified HTTPS Authelia redirect 302. No broad list/other target was touched.

Updated current status, working agreement, normative scope, plan, README and
structured manual with observed evidence. Validation is live one-fixture
service/CLI evidence plus read-only integrity/auth/restore checks and Compose
quiet/diff/link checks. Python/Rust/browser suites were not rerun: no program
code changed; their previous synthetic evidence is not a new live test claim.

Remaining limits: not data-plane blocking, fleet creation scope, large-load,
live failure/priority, actual browser submission/visuals or production acceptance.
Further live writes need new scoped approval. Record before future container
recreation or export logs externally: Docker local logs are container-scoped.
Follow-up UI issue found: eligible queued ADD retains the staging-disabled wait
reason until claim; fix that misleading reason before executable browser import.
No runtime fix or extra test mutation was made during this scoped experiment.

## 2026-10-17 — Frozen authenticated browser import confirmation

**Status:** Implemented, tested and deployed with lab ADD gates unchanged/off

Added a separate exact-target review/confirm flow after the non-executable
preview. Operator/Administrator plus trusted identity and CSRF are mandatory
on both POSTs. Fresh local classification excludes duplicates, refused lines,
enabled protection and already observed device/IP pairs; zero or over-1000
candidate sets reject as a whole. Every target/hostname, exclusions, normalized
metadata, policy revision, request key, disabled gates and expiry are visible.
Typed count confirmation submits only frozen canonical targets/metadata to the
existing private admission API with current Caddy-derived actor/roles. Browser
actor/target/digest fields are rejected. Admission rechecks policy/devices,
conflicts/capacity and its independent gate; no second writer or direct agent
read/refresh path was added.

Process-local immutable reviews retain canonical intent only, not paste/source
comments: unpredictable token bound to subject/cookie, independent UUID key,
at most ten minutes/shorter session age, five reviews per subject/256 globally.
Overflow rejects rather than evicting potentially admitted work. Expiry/cookie
change/Web restart fails closed, requiring queue inspection before a new review.
Explicit retries keep the same body/key even after a committed reply is lost;
no automatic retry, reclassification, authorization extension or re-add.
Malformed/unknown responses are uncertainty, not success. Accepted is queued/
held, never a device-success claim. Status/Queue poll independently without
GETting/replacing a frozen POST page, losing token or clearing typed input.
Navigation wraps on narrow screens and confirmation controls have spacing.

New ADD jobs no longer persist a misleading disabled placeholder. Metadata
hides only that exact legacy placeholder for currently eligible QUEUED ADD;
real deferral/error reasons and all stored history remain. No migration, wire,
agent, Compose, dependency, credential, inventory or .env change. All ADD gates
stay default-off; consumed fixture permission is not reused. No real import,
policy edit, refresh hint or new device test mutation is part of this work.

Structured review manual covers operation/retry/privacy, replica limitations,
rollout/rollback and lost drafts. Updated normative design/status and affected
manuals/plan/README. Preflight found admission/execution false, eligible zero,
61 active rows, three policy entries/revision 3, eight VERIFIED/one NOOP,
unfinished zero, successful ordinary cycle/no error, quick_check ok and no
foreign-key errors. Authenticated live submissions, remaining traffic/fleet/
large-load/failure/priority evidence and large-list scheduling remain separate.

**Validation:** All 330 Python tests pass; 16 real Chromium scenarios pass
(17 reported tests). New cases cover CSRF/current-role/identity, cookie/subject/
expiry/restart binding, count/field/body limits, whole-set bounds/cache caps,
atomic policy/device/opposite-intention conflicts, lost-after-commit replay with
identical key/body, malformed-result uncertainty and retained real deferrals.
Chromium covers frozen token/input/focus across status changes without POST-view
GETs or extra hints, disabled intake, native count validation and narrow layout.
Initial fixture assertions used a pre-migration policy revision/nonexistent
success wording; the final fixtures use current revision/real partial-cycle
feedback. An unavailable status exposed missing template metadata; the error
view now omits the panel when no valid status exists, preserving the retry form.
Compileall, Ruff, JavaScript syntax and diff checks pass. Tests use temporary
SQLite, fake transports and a synthetic localhost browser, not live devices.
Rust/protocol are unchanged; their prior evidence was not rerun or relabelled.

**Deployment:** Preserved prior API/Web images under
`before-import-review-20261017t112512z`. SQLite backup API produced checked
volume/host copies, host `.local/backups/state-before-import-review-20261017T112512Z.sqlite3`
mode 0600, ignored directory 0700; integrity and foreign keys pass. Built the
new pair, checked unchanged merged Compose quietly, and ran a packaged Python
3.12 review/admission/replay ASGI smoke in an isolated networkless/read-only
container using temporary synthetic SQLite and explicit fixture identity only.
No lab mount/secret or actual authentication was used. Existing unlocked
dependency ranges resolved during build; dependency locking remains follow-up.

Stopped the old API/Web cleanly, then recreated only that pair with --no-deps;
no overlapping executor, old-state restore, config edit or new work. Agent,
Caddy and Authelia IDs are unchanged. Deployed gates remain false/eligible zero;
61 active rows, stable first-seen/appearance/occurrence fields and all queue/
request/batch/origin/policy records compare unchanged against backup. Eight
VERIFIED/one NOOP, unfinished zero, policy three entries/revision 3, quick_check
ok/foreign keys empty. The normal post-start v2 cycle succeeded at 11:26:44Z,
two reads/zero mutations/8049 ms, next baseline 11:31:44Z and no error. Anonymous Shuns,
Imports, new review/confirm POSTs and status remain 401; new assets are present
and HTTPS preview returns TLS-verified Authelia 302. No forged live Web identity,
new queue/policy edit, refresh hint or independent agent read was submitted.
Reload tabs once; authenticated live confirmation and broader ADD readiness
still require separate scoped laboratory evidence. Rollback restores paired
images without schema restore; Web restart invalidates ephemeral reviews.

## 2026-10-17 — Managed manual-shun restoration requirement replaces one-time-only target

**Status:** Design amendment and implementation plan recorded; runtime unchanged

The operator requested re-adding manually added shuns after disappearance,
including reboot. Recorded the change explicitly in the normative architecture,
working agreement and plan; the former one-time-only target requirement is
superseded, not silently implemented against the old security model. Scope is
explicitly managed service additions/imports, because `show shun` does not
reliably distinguish manual CLI writes from FTD automation. No historical import,
NOOP, SSH-observed shun or cleaned-up laboratory fixture becomes managed by
inference. Earlier chronological implementation/validation entries remain true
of the previous one-time model and are unchanged.

New structured Managed Shuns design separates durable desired presence,
observed state and verified occurrence provenance. Future explicit managed-mode
confirmation must grant revocable standing authority and bind mode/scope into
canonical intent. This is not extension of the existing 15-minute delegation.
Restoration uses a distinct system actor/current intent revision, not saved
credentials or impersonated creator roles. Current API/review remains one-time.

Only a new complete successful snapshot may establish absence; failed/stale/
partial reads never cause restoration or claim reboot. Reuse one typed agent,
leased queue, cooldown/budgets, FIFO and priority checkpoints. Explicit service
removal atomically retires the effective device/IP intent and cancels unstarted
restorations; all-device review must include missing managed targets. An already
RUNNING ADD needs an ordered cleanup handoff, not bypassing opposite-action
conflicts or dispatching another writer. Failed/cancelled/expired cleanup must
not reactivate intent. Direct SSH removal while policy remains enabled will
be repaired; operators must stop maintenance in the service when intentional.

Enabled protection always wins; blocked intent remains visible and disabling/
deleting protection may resume it, requiring clear policy UI warning. Unknown
ADD latches attention rather than producing new restoration IDs. Active desired
policy survives observed loss/history retention, while creation provenance
still requires a new verified result. Backup restore must suspend policy as
well as jobs to prevent mass reapplication of an older desired set.

Implementation sequence: registry/standing authority/revisions/retention and
restore safeguards offline; managed UI/frozen confirmation; ordered removal/
protection/uncertainty/shared-worker integration with independent default-off
control; then a separately approved one-fixture restoration/removal test.
Capacity/anti-churn defaults and handoff design must be resolved before schema
rollout. The current long-list/traffic/fleet/load gates are not waived.

**Validation/impact:** Documentation-only review, relative-file link check and
`git diff --check`; no runtime test suite rerun is required or claimed. No code,
schema, environment, credentials, inventory, database, deployment/restart,
queue/policy admission, refresh hint, independent agent read or device mutation
was changed. All ADD gates remain off; no live permission is inferred from the
new requirement. Current behavior still does not restore missing imported shuns.

## 2026-10-17 — Offline managed-shun registry and standing-intent lifecycle

**Status:** Implemented in isolation; no runtime integration or live migration

Started the first implementation stage for the requested restoration model.
Added `managed_shuns.py`, deliberately not imported/initialized by ordinary
API/Store startup. Explicit initialization creates an empty registry state,
desired-target table and immutable request/result/authorization ledger. No
history, observations, origins or queued work is converted into desired policy.
Default durable restoration suspension is true and there is no resume/controller
in this increment. Current browser/import/worker remain one-time and gated off.

Canonical MAINTAIN/RETIRE binds fixed managed mode/scope, exact typed targets,
managed/Protected-IP revisions and normalized metadata. Require current
non-empty Operator/Administrator, explicit canonical UUID and matching digest;
the digest is not authorization. Keys from legacy imports/removal requests are
rejected. New policy requests use global optimistic CAS, persist real actors
and append per-target policy audit atomically. Another user's already-enabled
intent is NOOP without replacing its original authorizer. Explicit re-enable
after retirement rotates UUID/generation; replay of the original key returns
its original result without changing current policy or renewing anything.

MAINTAIN rejects protected, unknown/disabled and implicitly adopted observed
targets. Retirement does not require observed presence or an enabled device,
and a later Protected-IP revision cannot veto revocation. Original authorizing
metadata is retained while retirement records its actual actor separately.
The caller-owned write-transaction hook uses a savepoint to prevent partial
policy/audit/ledger effects even if its caller catches a failure; later outer
rollback also removes all effects. It is groundwork for future atomic queued
removal, not implementation of cancellation or running-ADD cleanup handoff.
Only the standalone wrapper emits bounded aggregate JSON after commit, without
labels/reason/raw source/full target lists. The snapshot is one consistent
bounded read separating desired, observed, device and protection state, not
verified creation or a Cisco query.

Initial storage limits are 1000 total device/IP keys including retired
tombstones and 10000 request keys with no automatic recycling/pruning. The last
1000 ledger slots are reserved for actual target retirement: new grant/NOOP
churn cannot exhaust revocation capacity. Overflow rejects atomically; an
over-limit store cannot silently render a truncated desired set. Policy/minimum
authority and tombstones survive ordinary history/queue retention. Future
archival/capacity expansion, system job source, uncertainty latch, bounded
restoration discovery/anti-churn and reviewed recovery/resume remain separate.

Updated the normative foundation contract, working agreement, status, plan,
README and structured development/managed manuals without rewriting prior
engineering history.

**Validation:** All 357 Python tests pass, including 27 new registry tests.
Coverage includes explicit/no-runtime migration boundary, distinct canonical
mode/digest, strict roles/UUID/typed targets/revisions, current protection CAS,
old import/removal-key exclusion, concurrent same-key replay and different-key
conflict, missing/protected/disabled retirement, new generations, whole-batch
limits, revocation reserve, complete 1000-target views, injected audit failure
under caught savepoint/outer rollback, history retention, restart and SQLite
backup preservation. Compileall, Ruff, relative-file link checks and
`git diff --check` pass. Tests use temporary SQLite and fake state only. The
first elevated targeted-test launch was not started because permission review
timed out; ordinary sandboxed SQLite checks then passed, and the final full
ASGI/socket suite passed with local permissions. No test failure was hidden.

**Operational impact:**
No real configuration, database, schema migration, service deployment/restart,
policy/queue admission, refresh hint, independent agent read or device mutation
was performed. This unused foundation needs no lab restart; future integration
requires a checked SQLite-safe backup, explicit restore suspension and staged
validation before normal startup may initialize it. Agent/wire/UI/Compose are
unchanged, so no new Rust/browser or live ADD evidence is claimed.

## 2026-10-17 — Version footer and read-only Managed shuns visibility

**Status:** Implemented, tested and deployed; no managed migration or ADD enablement

Added a normal-flow bottom footer on every base-template page showing v0.1.0,
the existing package version, not an invented readiness marker. Moved the version
literal into `ftd_shun_manager.__version__`; Hatch dynamic metadata and Jinja use
the same source. No Git/host/environment information is read to render it.
Flex page layout keeps short-page footers at the bottom and long-page footers
below content without fixed overlays; navigation wraps at mobile widths.

Added optional private managed GET plus authenticated all-role Managed shuns
tab. It probes registry presence under one read snapshot without DDL or policy
initialization. No tables is explicitly uninitialized; partial/invalid state
fails the managed resource with controlled 503, while ordinary monitoring/status
continues with managed availability false. Cheap availability/initialization/
revision fields join browser change detection without repeating canonical lists.
The read-only table distinguishes desired/stopped, local presence, protection/
disabled device, authorizing actor/time and unknown restoration provenance.
Escaped metadata and explicit controller-unavailable notice never imply pending
or verified restoration. There are no managed POST/PUT/DELETE, UI policy/resume
controls, queue hooks, new feature flags or automatic current/legacy adoption.

**Validation:** All 365 Python tests pass, including optional schema/no-mutation,
all-role authentication/escaping, missing/partial state, current transitions,
metadata and version-source tests. Seventeen Chromium scenarios pass (18
reported tests), including footer position at 1100/375px, mobile navigation,
read-only managed policy/protection revisions, escaping, localization and no
extra hints/executions. Compileall, Ruff, JavaScript syntax and diff checks pass.
All tests use synthetic state, temporary SQLite/local browser; no lab credentials
or device writes. Agent/Rust/protocol are unchanged and were not retested.

**Operational plan:** Under standing lab authority, preserve paired API/Web
images and a checked SQLite-safe backup, then recreate only API/Web with no
overlapping executor. Keep .env/inventory/agent/auth edge and all ADD gates
unchanged; no managed migration, new policy/job, refresh hint or independent
agent read. Startup may execute previously admitted removal/policy work. Check
unchanged aggregates/stable state, uninitialized optional registry/no new tables,
ordinary healthy v2 cycle, anonymous managed 401, TLS-verified Authelia redirect
and packaged version/footer alignment. Deployment results will follow.

**Deployment:** Preflight found admission/execution false, eligible zero,
eight VERIFIED/one NOOP, policy revision 3, zero unfinished work, integrity ok
and no managed tables. Active local state was already zero before rollout,
not the 61 rows from the previous recorded observation; no disappearance cause
or reboot is inferred, and no assistant cleanup/adoption/restoration was done.
Preserved prior paired images as `before-managed-view-20261017t124734z` and a
checked SQLite-backup-API copy on the state volume plus ignored host path
`.local/backups/state-before-managed-view-20261017T124734Z.sqlite3` (0600,
directory 0700). Host/volume integrity and foreign-key checks pass.

Built API/Web with dynamic package version 0.1.0; packaged Python 3.12 ASGI/
template/metadata smoke passed in a networkless/read-only container with only
temporary synthetic SQLite/identity, no lab mounts or secrets. Version source,
wheel metadata and footer agree, optional reads create no managed tables.
Quiet merged Compose validation passed. Cleanly stopped the sole API/Web pair,
then recreated only those two with --no-deps; no overlapping executor. Actual
agent/Caddy/Authelia IDs remain unchanged. No schema migration, actual .env/
inventory edit, new queue/policy, refresh hint or independent agent read.

Deployed optional GET is uninitialized/read-only/controller unavailable; cheap
status availability true/initialized false/revision zero. All ADD gates remain
off/eligible zero. No managed tables exist after repeated status/view reads.
Observed stable fields, queue requests/jobs, batches/origins and policy match
backup exactly; quick_check ok/foreign keys empty. Zero active rows and eight
VERIFIED/one NOOP remain. The normal v2 cycle succeeded at 12:50:20Z with two
reads/zero mutations/8448 ms and next baseline 12:55:20Z, no error. Anonymous
Shuns/Managed shuns/Imports/confirm/status reject with 401; TLS-verified Managed
shuns HTTPS redirects to Authelia (302). Deployed template/package show v0.1.0
and new assets are present; no live identity headers were fabricated. Reload
browser tabs once. Human-authenticated visuals and actual managed confirmation/
restoration remain separate next work; no production or live ADD acceptance.

## 2026-10-17 — Document manual versioning and release identification

Added the structured Versioning manual and links from README, the manual index
and contributor procedures. Recorded the current manual `__version__` source,
Hatch/package/footer wiring, no automatic build/deploy increments, independent
agent/protocol identifiers, MAJOR.MINOR.PATCH convention with explicit pre-1.0
breaking-change rules, and a manual release/verification/rollback checklist.
Development counters and short Git revisions are clearly future work; the
current footer cannot distinguish exact builds sharing a version. Release
numbers do not imply production acceptance or enable any device capability.

**Validation:** Cross-checked documentation against the version source, Hatch
configuration, Jinja global/footer and agent manifest. Relative documentation
links and `git diff --check` passed. Documentation-only: runtime suites were
not rerun. No code/configuration/version change, deployment, restart, database
access or device operation was performed.

## 2026-10-17 — Transactional queue admission prerequisite for managed retirement

Refactored ordinary queue admission through `apply_enqueue(connection, ...)`,
a trusted caller-owned transaction hook using an internal savepoint. The same
validation, semantic sources, coalescing, conflict/capacity/rate/TTL checks,
immutable import batches, request/job/link/audit writes and queue revision are
retained. The hook returns result plus bounded accepted-log records but never
commits or logs. The ordinary wrapper emits those records only after its commit;
replay emits none and does not renew authorization or bump the revision.

Synthetic composition tests combine explicit managed retirement with removal
admission under one outer transaction, including rollback of policy/ledger/
events on admission or later failure. Caught queue failures roll back their
own partial writes without erasing earlier caller work; callers must roll back
the entire composite action to avoid committing an earlier policy edit alone.
No managed runtime coordinator, composite confirmation/idempotency contract,
system source, queue-link cancellation, uncertainty latch or RUNNING-ADD cleanup
was implemented. Opposite active ADD remains a conflict, not fake cancellation
or a second writer. Those integration gates still block managed writes.

**Validation:** All 384 Python tests pass, including 19 new temporary-SQLite
transaction cases: no implicit transaction/migration, invisible pre-commit
state, savepoint and outer rollback, partial REMOVE/ADD admission/audit failure,
capacity/coalescing, roles/TTL/source/confirmation, silent replay, simulated
commit failure and retirement/QUEUED/RUNNING conflicts. An initial assertion
incorrectly assumed device-list ordering; it now selects the fixture by ID.
A restricted targeted socket/ASGI run stalled and was interrupted; the final
full suite passed with local socket permissions. Compileall, Ruff, relative
documentation links and `git diff --check` pass. UI/browser/agent/protocol are
unchanged; no new Chromium/Rust or live device evidence is claimed.

**Operational impact:** No schema/configuration/version change, live database
read/write, policy/job admission, refresh hint, independent agent request,
deployment or restart. This internal prerequisite provides no new user-facing
action requiring lab rollout. No backup restoration/migration is needed to
revert it; retain existing tables and outcomes. Managed registry initialization
remains explicit/offline, UI read-only, controller absent and all ADD gates off.

## 2026-10-17 — Offline managed removal coordinator and ordered ADD cleanup

Implemented explicit single-device/IP RETIRE_AND_REMOVE confirmation and atomic
coordinator, still disconnected from HTTP/UI/scheduler. Its optional additive
handoff table is initialized only explicitly in isolated development, never by
normal API/Store/queue startup. Root UUID/canonical mode/scope/revision/reason/
lifetime, current Operator/Administrator and digest bind durable immutable
authority. Deterministic separate retirement and cleanup/reservation/audit commit
together. Replay returns the original reference before revisions or new effects;
retained root keys prevent renewed cleanup after queue pruning or retirement of
a newer intent generation. Ledger is capped at 10000 retained one-target rows.

An exact RUNNING ADD remains the sole active command; WAITING_ADD reserves its
later removal without cancellation/overlap. Waiting records share queue job/
request/rate bounds, block new target ADD and pending/attention re-enable, and
protect predecessor evidence from retention. Ordinary opposite conflicts remain;
unstarted one-time imports require explicit cancellation. Leased, bounded
advance selects eligible rows without old-running head-of-line blocking. Settled
success/no-op/failure/uncertainty permits separate ordinary removal under the
original deadline, not renewed user authority or replayed ADD. Known pre-write
deferral can supersede that same unsent ADD. Missing/inconsistent evidence or
admission failure latches attention. Expiry/cancellation leaves policy retired
and never pretends to cancel running device work. Ordinary queue owns eventual
fresh snapshots, cutoff, verification/cooldown and budgets; no new RPC/writer.

Added a structured handoff manual and updated normative design, working
agreement, status, development plan and relevant manuals. State snapshots are
bounded to 20 entries plus full counts, separate handoff phase from queue state
and explicitly report missing scheduler integration. No UI/API exposes them.

**Validation:** All 409 Python tests pass, including 25 new temporary-SQLite
cases for no runtime initialization, atomic/no-overlap admission, typed verified/
no-op/uncertain settlement, pre-write deferral, lease recovery, expiry/cancellation
with actual actor attribution, key/generation/replay safety, full audit rollback,
concurrent same-key admission, shared capacity/rate reservations, pruning,
immutable authority and checked SQLite backup. Initial test NOOP used a string
rather than the required typed result; corrected the fixture without weakening
validation. The backup test now rolls back its deliberately failed immutable
write before backup, avoiding a self-held writer. One full-suite permission
review timed out before launch; its allowed retry passed. Final full suite,
compileall, Ruff, documentation-link and diff checks pass. No browser/agent/wire
changes; their suites and live Cisco evidence were not rerun or implied.

**Operational impact and remaining gates:** No actual database/configuration/
secret/inventory/version change, migration, live policy/job, refresh hint, agent
request, deployment or restart. Do not seed/test the coordinator in the lab.
Visible waiting/attention controls, frozen confirmation, shared-worker wake/
advance/expiry, all-device scope union, protection/system cancellation and
composite backup-restore suspension remain prerequisites to runtime rollout.
Old queue-only restore SQL does not suspend these waits/desired policy. Retain
additive authority/tombstones on rollback, and never start older workers ignoring
pending reservations. All ADD gates remain off; no consumed fixture permission
is reused and restoration is still unavailable.

## 2026-10-17 — Non-executable managed removal review and optional handoff visibility

Added compact single-target selection on Managed shuns for Operators/Admins and
an immutable preparatory review with exact device/IP, generation/revision,
observed/protection/desired distinctions, bounded reason, proposed cleanup
lifetime, ephemeral reserved key and timezone-qualified expiry. Five reviews
per subject/256 globally bind subject and CSRF-cookie hash, expire within ten
minutes/the shorter sensitive-action age and disappear on Web restart. No
review token is durable policy authority. Pure canonical intent moved into a
storage/dispatch-free module, retaining the coordinator's existing import alias.

Confirmation remains deliberately non-executable: disabled button and server-
side current-role/CSRF/token/expiry/exact-IP validation followed by unconditional
503, without admission/API POST or database changes even when upstream flags
claim enablement. Polling retains the frozen POST target/token/input/focus and
does not GET/reclassify it. No new environment selector or write endpoint exists.

Optional private GET and authenticated read-only handoff view distinguish absent
schema from unavailable/corrupt state without DDL. Optional failure does not hide
valid managed policy or invent an empty queue. Bounded 20-row views prioritize
active/attention, collapse completed records, color-code waiting/attention/
active/verified and separate admission phase from linked queue outcome. Retained
root phase never implies verification; missing pruned history is unavailable.
Escaped actor/diagnostic text, local timezone labels and existing queue revisions
drive display without refresh hints/FTD calls. No scheduler/coordinator admission
hook was enabled; pending controls/recovery/fleet/protection gates remain.

**Validation:** All 424 Python tests pass; 18 Chromium scenarios (19 reported
tests) pass, including managed review freezing, native disabled execution,
mobile layout, revision-driven handoff colors/outcomes, no additional hints or
device execution. Synthetic ASGI checks cover auth/current role/CSRF, strict
fields/selection/reason, malformed/absent optional state, cookie/expiry/restart,
concurrent/global cache bounds, escaping and no policy/job/audit changes on
preparation or direct confirmation. Initial fixtures used the pre-migration
Protected-IP revision; they now read the actual fixture revision. Existing
no-write endpoint checks now allow the new GET-only resource. A restricted
ASGI run was interrupted after stalling; the complete final suite passed with
local socket permissions. Compileall, Ruff, JavaScript syntax, relative links
and diff checks pass. Rust/wire unchanged; no new live write evidence is claimed.

**Lab rollout plan:** Under standing authorization retain paired rollback images
and a checked SQLite-safe backup, validate packaged Python 3.12 in a networkless/
read-only synthetic container, stop the sole API/Web pair then recreate only
them. No actual configuration/inventory/secret, schema, policy/job admission,
refresh hint, independent agent call or gate change. Startup may execute already
admitted ordinary queue/policy work. Validate unchanged state/queue/policy,
absence of all managed/handoff tables, disabled gates, healthy ordinary reads,
anonymous 401 and TLS-verified Authelia redirect. Deployment result follows.

**Deployment:** Preflight confirmed zero active shuns, eight VERIFIED/one NOOP,
no unfinished work or managed tables, three protected entries/revision 3,
disabled admission/execution and zero eligible devices; normal reads had no
error. Preserved preceding API/Web images under
`before-managed-review-20261017t143643z`. SQLite backup API produced volume and
ignored host copies, host
`.local/backups/state-before-managed-review-20261017T143643Z.sqlite3`, file 0600/
directory 0700; both integrity and foreign-key checks pass.

Built API `sha256:4d9a7507b73a27b3fb27f925bfd7dd67385d82ec1e6bb0f2cfdb9368608ed769`
and Web `sha256:39100c2115701d94f17ef9974323a00911096681807bdd8fad61baa1217ee576`.
Packaged Python 3.12 smoke passed in a networkless/read-only container with only
temporary synthetic SQLite/identity: optional GET does not initialize tables,
review renders from a synthetic policy, direct confirmation remains 503 without
API POST/audit/queue changes, package/footer version agree. No lab mounts or
secrets. Existing unlocked dependency ranges resolved at build; no dependency
pinning change or runtime compatibility claim beyond the smoke is implied.

Quiet merged Compose validation passed. Cleanly stopped the sole API/Web pair
then recreated only those two with --no-deps, with no overlapping executor.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21` and Authelia `76f3635ab737` stayed
unchanged. New API/Web are `83f95765d342`/`59b9764544d5`. No actual environment,
inventory, secret, gate, policy/job or schema edit; no seed or refresh hint.

Deployed GET reports explicit uninitialized/read-only/admission-disabled/
scheduler-unavailable handoffs, and repeated reads create no managed/handoff
tables. Stable devices/protected policy/queue requests/jobs/links/batches/origins/
shun state/events compare exactly to backup; quick_check ok and foreign keys
empty. Zero active shuns, eight VERIFIED/one NOOP and policy revision 3/three
entries remain. ADD admission/execution false and eligible devices zero.
Ordinary post-start v2 cycle succeeded at 14:40:16Z, two commands/zero removal,
addition or mutation steps, 11494 ms, next baseline 14:45:16Z/no error. Anonymous
managed/status/review/confirm requests over actual Web UDS are 401; packaged
templates/version are present, and TLS-verified HTTPS returns 302 to auth.lab.test.
No live identity headers were fabricated. Reload tabs once; actual authenticated
visuals, executable confirmation/recovery/worker integration and any further
device experiment require their remaining gates, not inference from this rollout.

## 2026-10-17 — Composite recovery pause and gated shared cleanup worker

**Change:** Added `ftd-shun-maintenance` offline suspend/resume-mutations with
explicit offline/review assertions, trusted-host maintenance attribution,
private exclusive checked SQLite backup and concurrent-commit refusal.
Transactionally cancel queued jobs/delegations/waits, preserve RUNNING as
UNVERIFIED, suspend optional desired restoration, clear lease and persist a
60-second ordinary-mutation pause with per-item/aggregate audit. Resume clears
only ordinary suspension; no work resurrection or desired restoration rearm.
Queue migration adds a default-zero executor column without resetting it on
restart. Block new admissions/claims and managed MAINTAIN/cleanup while paused,
but retain snapshots, read leases, policy-only retirement and old-key reads.
Replace insufficient queue-only restore SQL with a structured recovery manual;
older images ignore the new pause and must not run paused/restored work.

Added independent strict default-off cleanup-worker flag (deployed socket mode
only), no optional schema initialization. Existing waits wake the shared
cooldown/lease worker. Advance once, at most 16 eligible waits before cutoff,
then fresh initial observations and ordinary bounded queue execution. Never
advance against a mid-cycle pre-ADD snapshot. Original delegation/deadline and
uncertainty remain intact; unexpected advancement errors skip mutations for
that cycle while retaining monitoring/final snapshots. Expose sanitized worker
status plus persistent recovery warnings; no Web/private admission POST and
preparatory confirmation remains unconditional 503. ADD/restoration not enabled.

**Validation:** Temporary SQLite/fake-agent tests cover migration, compound
suspension/resume/replay, current policy pause, backup permissions/no overwrite,
concurrent commit, audit rollback, no automatic schema initialization, continued
monitoring without trusted admission, strict flag and single leased/cutoff
worker promotion with fresh snapshots and preserved ADD uncertainty. Chromium
passes all 18 scenarios (19 reported tests), including visible pause/worker
warnings and stable search coordinates at desktop/mobile widths. The obsolete
manual-SQL regression was updated to exercise the documented checked CLI rather
than retain unsafe queue-only instructions. Final Python/static result follows.
Restricted async runs stalled and were interrupted; full tests run with local
socket/thread permissions. Rust and binary agent protocol unchanged.

**Rollout plan:** Current authorized lab preflight has no pending work or
managed/handoff tables, eight VERIFIED/one NOOP, zero active shuns, disabled ADD,
zero eligible profiles, normal monitoring and clean integrity/FK checks.
Preserve paired API/Web images and a checked SQLite-safe backup; validate the
packaged CLI in a networkless/read-only synthetic container. Stop/recreate only
API/Web; startup adds default-zero pause metadata and may execute existing
ordinary queue/policy work. Do not run recovery against lab data, seed policy/
handoffs, change actual gates/environment/inventory or submit any new fixture.
Verify state preservation, optional-schema absence, default-off worker/gates,
ordinary reads, anonymous 401 and TLS-verified authentication redirect. Record
deployment result below; desired restoration/executable controls, protection/
fleet/system hooks and live validation remain future work.

**Final validation and deployment:** All **440 Python tests** pass in 12.98 s;
compileall, Ruff, JS syntax, relative documentation links and diff checks pass.
The actual packaged Python 3.12 maintenance console entrypoint successfully
performed checked backup/suspend/ordinary-resume on disposable SQLite inside a
networkless, read-only container. Private synthetic API reported the durable
pause/default-off worker and absent optional tables; production template showed
the recovery warning, resume retained cancelled jobs and integrity/FK checks
passed. No live mounts, identity or credentials were used in that smoke.

Preserved paired pre-upgrade images as `before-recovery-20261017t1505z`.
SQLite backup API created
`/var/lib/ftd-shun-manager/state-before-recovery-20261017T150139Z.sqlite3` and
ignored host `.local/backups/state-before-recovery-20261017T150139Z.sqlite3`;
file 0600/directory 0700, integrity and FK checks pass. Built API
`sha256:f226e98fb43c4ffb9127d9a751243f2fa8077411c09b1c193125542450f1185f`
and Web `sha256:190e80fff9a3458861c2a28dc16a66400e89c451f7bea8a736944bae0bb3c2bc`.
Build resolved the existing unlocked dependency ranges; smoke is not dependency
pinning or a production compatibility claim. Quiet merged Compose validation
passed. Stopped the sole API/Web pair cleanly, then recreated only them with
--no-deps; new IDs `c301d62eeb9f` / `466f4e540846`. Agent `9d1f50d361ca`,
Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` are unchanged.

API startup added only `mutations_suspended=0`. All ten other stable tables
match backup exactly, optional managed/handoff tables remain absent, integrity
ok/FK errors zero, queue eight VERIFIED/one NOOP/no pending, zero active shuns.
Worker/ADD admission/API execution/agent execution off and zero eligible device
profiles; no actual environment, inventory or secret changed. No lab recovery
command, new policy/job, refresh hint, independent device call or test mutation.
Healthy ordinary v2 cycle completed 15:02:33Z with two commands/zero removal,
addition or mutation steps in 8601 ms; next baseline 15:07:33Z/no error. Actual
anonymous Web managed/status/review/confirm paths are 401 and TLS-verified HTTPS
returns 302 to authentication; packaged entrypoint/warning assets present.
Reload tabs once for new assets. Do not enable cleanup or seed a live fixture:
executable cancellation/confirmation, protection/system/fleet integration and
separately scoped live acceptance remain pending. For this currently unpaused,
empty/no-managed lab only, paired rollback remains possible after rechecking
those conditions and stopping the sole executor; older images cannot honor a
future active pause or waiting reservations. No automatic rollback was needed.

## 2026-10-17 — Managed revocation controls without device-write admission

**Change:** Added a separate frozen, current-role/CSRF/session-bound policy-only
RETIRE review and strict private API. One exact pair/revision/reason/key/digest;
no generic action/mode/list/create/re-enable/resume. Move unchanged canonical
policy hashing into the pure intent module, retaining registry import alias so
Web imports no storage/coordinator. Preparation is observational. Confirmation
atomically uses existing registry ledger/CAS/audit, including during recovery
pause or on missing/protected/disabled devices. Existing one-time jobs/running
ADD/separate cleanup and current shun are not cancelled/removed. Show this before
confirmation. Same-key replay cannot retire a new generation. Validate exact
receipt/revision; unknown/lost/malformed replies preserve the frozen retry key
and typed IP, no auto-submit/rebase. A valid receipt survives optional status
failure and is explicitly not proof of latest policy/device state.

Added owner/Administrator waiting-cleanup cancellation over private API/BFF,
strict current identity/CSRF/body, collapsed explicit explanation and the shared
single-submission AJAX controller. Serialize WAITING_ADD cancellation with
promotion: admitted work conflicts, not silently cancelled; already cancelled
is audit-free no-op. Keep real cancelling attribution, original ADD/retirement
and no authority renewal. Validate cancellation receipt; unknown reply is not
success. Native form redirects, AJAX updates without navigation or device hints.
Combined removal review remains unconditional 503. No optional-schema startup,
controller/admission/ADD enablement, new live fixture, credentials/topology,
database schema or agent-wire change.

**Validation:** Synthetic SQLite/ASGI cases cover immutable reviews and role/
CSRF/scope/reason/session/cross-purpose/cache bounds, revision conflict between
users, same-key replay after new generation, optional-schema refusal, policy
retirement during pause, untouched one-time work/observations, audit rollback,
unknown replies/exact-revision receipt and original-key retry. Waiting tests
cover owner/Admin, promotion race, audit rollback, repeat/uncertain responses
and untouched RUNNING ADD. Existing GET-only/no-admission tests were narrowed
to explicitly allow only the two new revocation routes, not generic writes.
Real Chromium passes 19 scenarios (20 reported tests): frozen retirement token/
typed IP/focus through metadata updates and desktop/mobile layout, plus one
AJAX waiting-cancel submission with no navigation/refresh/device execution.
Initial synthetic ADD fixtures used the pre-migration protected revision and
now read the actual revision; no runtime restriction was relaxed. Final Python/
static/package/deployment results follow. Rust unchanged.

**Lab rollout plan:** Under standing lab permission preserve paired API/Web
images and checked SQLite-safe backup, validate packaged Python 3.12 with
temporary synthetic data in a networkless/read-only container, stop/recreate
only the sole API/Web pair. API startup may execute already admitted ordinary
queue/policy work. No managed/handoff seed or actual control submission in lab;
keep all actual gates/profiles/env/inventory/secrets unchanged. Verify absent
optional schemas, disabled gates, stable-table comparison/integrity, ordinary
reads, anonymous rejection and TLS-verified redirect. No live managed acceptance
is implied. Fleet/protection/system integration, combined admission and bounded
desired reconciliation/rearm/anti-churn remain required before device writes.

**Final validation:** All 465 Python tests pass (16.28 s), compileall/Ruff/JS
syntax/diff checks pass and 221 relative documentation links resolve. Production
transport review caught that the generic action controller used multipart while
the new bounded cancel endpoint intentionally requires URL-encoded forms. Only
that action now encodes URLSearchParams; the Chromium fixture asserts actual
Content-Type/CSRF and all 19 scenarios (20 reported tests) pass again. Synthetic
ASGI explicitly rejects multipart before cancellation. No deployed regression
occurred: this was corrected and images rebuilt before replacement.

Packaged Python 3.12 smoke passed in a networkless/read-only container using
temporary SQLite/synthetic identity only: actual BFF prepares/confirms policy
retirement, URL-encoded JSON/AJAX cancellation returns a validated receipt,
original ADD stays RUNNING, retirement stays effective and combined confirmation
still returns 503. Integrity/FK checks pass and no work hint is signalled. No lab
mounts, inventory, secrets or device writes. Build resolved existing unlocked
dependency ranges; no dependency pinning/production acceptance claim.

**Deployment preparation:** Quiet merged Compose validation and read-only lab
preflight pass: eight VERIFIED/one NOOP, no pending or active shuns/managed tables,
ordinary reads healthy, mutation pause false, ADD and cleanup worker off/zero
eligible profiles. Preserved previous paired images as
`before-managed-controls-20261017t1523z`. SQLite backup API created exclusive
`/var/lib/ftd-shun-manager/state-before-managed-controls-20261017T152446Z.sqlite3`
and ignored host `.local/backups/state-before-managed-controls-20261017T152446Z.sqlite3`;
file 0600/directory 0700, integrity/FK checks pass. Built API
`sha256:bd52e4950d8ffc2a5ec710f7431d5bcfb5bc1bdc066002f90deb3bbdfde93b06`
and Web `sha256:8fcdca04f6785422ce31fe691ce40d40242b01e9f356a0adead38388ee6d1de1`.
Only the sole API/Web pair is replaced, no overlapping executor. Post-deploy
checks/results follow; no schema/gate or lab policy/job changes are planned.

**Deployment result:** Cleanly stopped/recreated only API/Web with --no-deps;
new IDs `87a3a20c9abb` / `8142c72f110b`. Agent `9d1f50d361ca`, Caddy
`9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged. Full sqlite_master definitions
and ten stable tables compare exactly with backup (executor lease/cooldown
metadata is expected to change on ordinary cycles). Integrity ok/FK zero,
eight VERIFIED/one NOOP, no pending or active shuns. Repeated optional GETs
leave managed/handoff schemas absent. Mutation pause false, ADD admission/API
and agent execution/cleanup worker off, zero eligible profiles. Actual env,
inventory, secrets and policy/jobs unchanged; no live control action, seed,
device test mutation, independent agent call or forced refresh. Initial status
had no new-process success yet and preserved the existing 15:27:23Z cooldown;
waited normally rather than bypassing it. Ordinary v2 cycle then completed
15:27:31Z, two commands/zero removal/addition/mutation steps, 8493 ms, next
baseline 15:32:31Z/no error. Actual anonymous managed/status/new retirement/
cancel/combined-confirm Web paths reject 401; TLS-verified HTTPS returns 302
to authentication. New template and corrected JS encoding are packaged.

Reload tabs once. The current lab has no managed targets, so retirement forms
remain absent rather than demonstrating them through unauthorized seed data.
Paired rollback images/checked backup retained; do not restore old authority
just to revert UI. This is a default-off delivery of revocation-only controls,
not a managed-policy migration, live restoration/cleanup acceptance or approval
for new FTD writes. Remaining combined admission/fleet/protection/system and
controller/rearm/anti-churn work is tracked in the development plan.

## 2026-10-17 — Protected/managed lifecycle and ordinary-removal admission barrier

**Change:** Added bounded, non-initializing optional managed structural safety
reads shared by Protected-IP context, cheap managed status and ordinary-removal
admission. Publish enabled-intent counts independently of observed shuns,
including missing/disabled-device targets. Unknown/partial/malformed state is
not zero: show unavailable/unknown context and reject weakening/manual removal
while allowing monitoring/protection strengthening.

Protected-IP weakening now checks the current global managed revision and
explicit matching-intent acknowledgement under the policy write lock, sharing
atomic queued-ADD cancellation/audit. Existing no-intent clients stay compatible;
actual all-role authenticated permissions are unchanged. Record checked revision/
count/ack in policy audit, without changing desired authority, work deadlines or
submitting any work. Dirty forms preserve both reviewed revisions/checkbox
values; fresh reload resets acknowledgement. A stale acknowledgement cannot
silently widen scope on background updates.

Added transactional ordinary manual-removal guard: exact device scope and full
matching fleet maintained scope, including missing devices not enumerated from
observations. API checks before empty-scope handling; queue rechecks after
original-key/reserved-namespace checks before insertion. Scope names cannot
waive retirement. MAINTAIN rejects queued/running removal, serializing the
opposite-order race. Protected-policy removal stays independent/higher priority.
Offline combined coordinator still retires policy before queue admission under
the same transaction; combined Web confirmation remains 503. No system policy
source/generation/claim hook/controller is added or claimed complete.

**Validation:** All **488 Python tests** pass (16.63 s); compileall, Ruff, JS
syntax and diff checks pass. Synthetic tests cover scope counts, explicit/stale/
missing/strict API acknowledgement, role-preserving BFF, weak/strong/no-op
transitions, partial/corrupt optional state, healthy monitoring, running/waiting
cleanup preservation, audit rollback including unsent ADD cancellation, exact/
fleet/missing-target guards and concurrent MAINTAIN/removal. Legacy namespace
regression retains its original guard precedence; the old grant-after-queued-
remove fixture now explicitly cancels that removal first. Snapshot assertions
distinguish unchanged desired authority from changing observed protection.
Chromium passes **20 scenarios (21 reported tests)**, including stale dirty
managed revision/ack retention, fresh-form reset, required delete acknowledgement
and mobile warning layout. Fixtures only; no lab data or FTD writes. Rust/wire
unchanged. Updated structured manuals, normative amendment, status and plan.

**Rollout plan:** Use standing lab authority for API/Web only. Preserve paired
rollback images and a checked SQLite-safe backup, validate packaged Python 3.12
against temporary synthetic data in a networkless/read-only container, then
stop/recreate the sole pair. No schema/environment/agent change or managed seed;
all actual ADD/cleanup-worker gates and device profiles remain disabled. API
startup can execute already admitted ordinary/policy work, but no new job/control
submission, independent device command or forced hint will be used for validation.
Verify unchanged stable state/schema, absent optional managed tables, zero
pending work, disabled gates, private anonymous rejection/TLS redirect and an
ordinary cooldown-respecting read cycle. Package/deployment results follow.

**Package/pre-deployment:** Packaged Python 3.12 smoke passes inside a
networkless/read-only container, disposable SQLite/synthetic identities only.
Verify absent managed schema stays absent on initial reads, then explicitly
create a synthetic fixture: two-intent warning renders, missing acknowledgement
returns 409, real multipart BFF save forwards strict reviewed fields and actual
Viewer identity, managed intent stays enabled, missing-fleet ordinary removal
returns 409, malformed optional columns publish unavailability while monitoring
stays healthy, no work signal/jobs, integrity/FK pass. No live mounts/secrets,
SSH or agent socket. Build resolved existing unlocked dependency ranges, not a
production compatibility/dependency-locking claim.

Read-only lab preflight: eight VERIFIED/one NOOP, no pending or active shuns,
no managed tables, mutation pause false, ADD/API admission/execution and cleanup
worker off, zero eligible profiles; ordinary reads healthy/integrity pass.
Quiet merged Compose validation passed. Saved paired preceding images as
`before-managed-protection-20261017t1555z`. Exclusive SQLite-safe backup:
`/var/lib/ftd-shun-manager/state-before-managed-protection-20261017T155504Z.sqlite3`
and ignored host `.local/backups/state-before-managed-protection-20261017T155504Z.sqlite3`,
0600/private 0700 directory, integrity/FK checks pass. Built API
`sha256:18d9b5508d9a026d5c645f5b2d49e193b0c752e96d0a531df1c1d65d1a52664c`
and Web `sha256:bbaa34ba7f36aff39b0532e7877f0ba4e813df5051674e3d86a53338fc3db9d9`.
Only the sole API/Web pair is replaced, leaving all actual configuration,
inventory, secrets, schema and other services unchanged. Post-deploy checks
follow; no live weakening/removal/managed seed or refresh hint is submitted.

**Deployment result:** Stopped the sole API/Web pair and recreated only them
with --no-deps, no overlapping executor. New IDs `17eed6be119d` / `026c40c1517b`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21` and Authelia `76f3635ab737` stayed
unchanged. Full sqlite_master definitions and ten stable state/policy/queue/
authority/event tables match backup (ordinary executor lease/cooldown metadata
excluded), integrity ok/FK errors zero. Three Protected IP entries expose
available managed revision 0/count 0; repeated optional reads create no managed/
handoff tables. Eight VERIFIED/one NOOP, no pending or active shuns, mutation
pause false, actual ADD admission/API execution/agent execution/cleanup worker
off and zero eligible device profiles. No actual environment/inventory/secret,
schema, policy/job or authority change; no live acknowledgement, weakening,
removal, managed seed, new test fixture, direct agent read or refresh hint.

Normal post-start v2 cycle completed 15:57:55Z, two commands/zero removal,
addition or mutation steps, 8649 ms, next baseline 16:02:55Z/no error. Actual
anonymous Protected/Managed/status and managed POST paths reject 401;
TLS-verified HTTPS returns 302 to authentication. New warning/ack template and
dual-revision retention JS are packaged. All 224 relative documentation links
resolve; final Ruff/diff checks pass. Reload tabs once for current assets.
Paired rollback images/checked backup retained; no database restore or authority
reset is needed merely to revert code. Managed tables remain absent in this lab,
so no enabled-intent warning/ack is manufactured for demonstration. Combined
confirmation/fleet execution, system-generation/claim/protection hooks and
restoration uncertainty/rearm/anti-churn still require their next implementation
and separately scoped live evidence. Do not interpret this rollout as enabling
those paths or approving new FTD mutations.

## 2026-10-17 — Frozen all-device managed-removal scope, no execution

Implemented an observational union for one IPv4 in `managed_scope.py`, exposed
through private GET `/api/v1/managed-removal-scope/{ip}`. Read active observed
devices and enabled maintained targets in one consistent SQLite transaction,
including missing observations and disabled devices; collapse interfaces and
exclude unrelated inventory/stopped-and-missing targets. Unknown optional state
fails closed without breaking monitoring; entirely absent optional schema stays
absent. Empty/over-1000 scopes reject instead of silently truncating. No inventory
routes, pins, credentials or raw authorization payloads are published.

Added strict versioned canonical scope/action bindings and caller-transaction
comparison against current state. Generation, policy, inventory and union changes
invalidate the review; timestamp/additional-interface changes on the same target
do not. This comparison grants no authority and is **not** atomic multi-target
admission. Do not call the single-target coordinator in a loop to simulate a
fleet transaction. The future writer still needs atomic retirement/handoffs,
system/protection/generation/claim integration and uncertainty/rearm controls.

Managed shuns now offers a collapsed preparatory fleet review with every target,
desired/observed distinction and explicit disabled-device blocker. Immutable
target dataclasses share the existing single-review subject/CSRF-bound cache,
five per subject/256 globally and at-most-ten-minute lifetime. Strict forms,
current roles/CSRF and exact typed IP are rechecked. Combined confirmation stays
unconditional 503 even with fake enablement/DOM changes; no private admission
POST, retirement, job, hint or device operation. Ordinary removal is unchanged.
No schema, configuration or agent/protocol change; all ADD and cleanup-worker
gates remain disabled, no live fixture/managed seed is authorized.

Validation: all **509 Python tests** pass (18.64 seconds); **21 Chromium
scenarios / 22 reported tests** pass, including frozen token/input/focus, complete
scope, disabled blockers and 375px layout without navigation or hints. New
synthetic SQLite/ASGI tests cover union membership, multiple interfaces, missing/
disabled/retired targets, schema absence/corruption, exact validation/digests,
overflow, concurrent consistent reads, immutable cache/capacity, unchanged data,
identity/CSRF, escaping and unconditional execution refusal. The explicit API
route whitelist was extended only for the observational GET. Compileall, Ruff,
JS syntax and diff checks pass. Rust is unchanged.

Deployment preparation under standing lab authority: only API/Web, restart may
execute already admitted ordinary queue/policy work; no new work/control or
forced refresh will be submitted. Read-only preflight: integrity ok/FK zero,
no optional managed objects, eight VERIFIED/one NOOP, zero pending/active shuns,
three Protected IPs, disabled admission/API ADD/cleanup worker. Ordinary reads
healthy at 18:18:24Z, next baseline 18:23:24Z. Retained paired images
`deploy-api:before-fleet-review-20261017t1823z` and
`deploy-web:before-fleet-review-20261017t1823z`. Created exclusive checked 0600
SQLite-safe volume backup `state-before-fleet-review-20261017T1823Z.sqlite3`
and ignored private host `.local/backups/state-before-fleet-review-20261017T1823Z.sqlite3`
(0700 directory); both integrity/FK checks pass. Merged Compose quiet validation
and API/Web build pass. Built API
`sha256:d067d58bf1dad83c56b1aa068cba5fa8581aaa8418c8b4b8914e42a498872e21`
and Web `sha256:7844e383ea00ad1608858049edc1e7085ffe00998c4b9fb76464382d87ab34e2`.
Actual env/inventory/secrets/gates and all other services are preserved.
Packaged/pre-deployment and rollout results follow; no live mutation acceptance
is claimed by preparatory reviews or synthetic tests.

**Packaged/deployment result:** Python 3.12 packaged scope/BFF review smoke
passes in a read-only, networkless container with only temporary synthetic
SQLite and identities, no live mounts/secrets/agent socket. An absent registry
stays absent; the explicit fixture includes missing maintenance, observed-only
and disabled targets. Native URL-encoded review renders the complete union;
repeated exact confirmation returns 503 with the same token and no database/
queue/audit/hint change. The first fixture setup used a hard-coded Protected-IP
revision and correctly conflicted; using its actual revision passes without
relaxing canonical/CAS validation. Build uses existing unlocked dependency
ranges, not a production dependency compatibility claim.

Stopped the sole API/Web pair and recreated only them with --no-deps, avoiding
overlapping executors. New IDs `353554c15e15` / `41a490d14a70`; agent
`9d1f50d361ca`, Caddy `9c8fdb3a7f21` and Authelia `76f3635ab737` unchanged.
Full sqlite_master definitions and all eleven non-executor SQLite tables match
the checked backup exactly; integrity ok/FK errors zero. No managed schema,
mutation pause, pending job, new policy or live fixture. Queue remains eight
VERIFIED/one NOOP, zero active shuns, three Protected IPs. Repeated optional GETs
do not initialize anything; the empty fleet scope correctly returns 409.
Actual admission/API ADD/agent ADD/cleanup-worker flags remain off and inventory
has zero eligible addition profiles. Actual env/inventory/secrets unchanged.
The minimal agent image has no shell; its single ADD flag was checked through
filtered container metadata without disclosing environment values.

Ordinary post-start v2 cycle completed at 18:23:29Z with two commands, zero
mutations and 8466 ms; next baseline 18:28:29Z/no error. New packaged form/template
present, anonymous Managed/status/review/confirmation reject 401, TLS-verified
HTTPS returns 302 to authentication. No synthetic Web identity was used against
the live stack; no live controls, seeding, direct agent calls, refresh hints or
new work. Paired rollback images and backup retained; revert code without
restoring older authority or dropping tables, following the recovery manual.
Reload tabs for current templates. Frozen fleet scope is now a completed
prerequisite; atomic multi-target admission, executable combined controls and
system restoration/uncertainty integration remain next, with live validation
requiring fresh scoped authority. Synthetic/default-off rollout is not live
managed mutation or production acceptance.

## Adding future entries

Append a new entry for every material code, security, deployment, schema, protocol, authentication, or operational change. State what changed, what was verified, and what remains risky or incomplete. Update [`project-status.md`](project-status.md) in the same change.

