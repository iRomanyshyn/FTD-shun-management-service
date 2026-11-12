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

## 2026-10-17 — Offline atomic ready-target fleet retirement and cleanup admission

Implemented `ManagedFleetRemovals`, separate from the single-target ordered
handoff and deliberately not connected to API/BFF/CLI admission. One reviewed
IPv4 union is compared within a single `BEGIN IMMEDIATE`; enabled managed
members are retired together through one derived policy key/revision, then one
ordinary REMOVE delegation covers the complete scope. Observed unmanaged targets
are cleanup only, never adopted. Disabled devices, any QUEUED/RUNNING ADD and
existing WAITING_ADD cleanup reject the entire scope without silently dropping
members/cancelling independent ADD. Fleet ordered waiting remains pending.

Policy, jobs, links, immutable root receipt and audit either commit together or
roll back, including late capacity/audit failure. A savepoint-backed trusted
`apply_admit()` supports caller-owned transactions and returns un-emitted logs;
the standalone wrapper emits accepted JSON only after commit. Captured cleanup
authority is at most 900 seconds and is checked again at the end of admission;
partial/slow admission cannot extend it. Existing queue capacity/rate, REMOVE
coalescing, lease/cutoff/cooldown/budgets and verified-result semantics remain.
Atomic admission does not promise cross-device rollback/exactly-once writes.

Explicit isolated initialization adds retained `managed_fleet_removals` (10000
root-key limit, immutable actor/scope/action/receipt/deadline/retirement reference,
monotonic transaction-local ADMITTING → ADMITTED). Startup/reads/worker never
initialize it. Replay precedes current CAS/recovery pause/ledger capacity and
returns the original receipt without new audit/jobs or retiring a later intent,
including after cancellation/pruning/restart. Added cross-namespace root/derived
key guards to queue, registry and single-target admission. Recovery preserves
fleet authority/retirement while cancelling ordinary delegated work; orphaned
registry or committed transitional fleet phase refuses recovery. No new queue
source, waiting reservation, scheduler or SSH path.

Synthetic coverage includes whole-union mixed managed/observed scope, absent
startup schema, exact role/digest/UUID/scope binding, disabled/opposite/waiting
conflicts, late queue/audit rollback, caught savepoint failure/outer commit and
rollback, original and late expiry, same/different-key races, one-root actor
rate accounting, capacity, coalesced cancellation, namespaces both directions,
retention/new generations, lease/cutoff and checked offline backup/recovery.
All **549 Python tests pass** (19.87 seconds). Compileall, Ruff, diff and JS syntax
checks pass; Rust/wire unchanged. The first Chromium run exposed an existing
fixture race reading `document.body` during native navigation. Changed that
single polling expression to wait while the body is absent, preserving the
required receipt assertion; full Chromium rerun/package results follow.

Updated architecture, status, agent agreement and structured
[Atomic Fleet Removal](manual/managed-fleet-removals.md) manual plus affected
review/handoff/queue/recovery documentation. Combined Web confirmation stays
unconditional 503; no HTTP admission, optional live schema, gate enablement,
restoration or new test mutation. Future fleet waiting/system-source/generation/
claim/uncertainty controls and scoped live validation remain prerequisites.

Lab release preparation under standing authorization: announce API/Web-only
replacement and existing queue startup risk, retain paired rollback images
`deploy-api:before-fleet-atomic-20261017t1838z` /
`deploy-web:before-fleet-atomic-20261017t1838z`. Read-only preflight showed healthy
18:33:46Z ordinary reads/next baseline 18:38:46Z, eight VERIFIED/one NOOP, no
pending/active shuns, three Protected IPs, absent optional managed objects,
disabled ADD/admission/cleanup worker and zero eligible profiles. Quiet merged
Compose validation passes. Exclusive SQLite-safe volume backup
`state-before-fleet-atomic-20261017T1838Z.sqlite3` and ignored private host
`.local/backups/state-before-fleet-atomic-20261017T1838Z.sqlite3` are 0600, host
directory 0700; both integrity/FK checks pass. Build/pre-release checks underway,
no source schema/env/inventory/secrets or other services changed. No live policy
seed/control/job, direct agent call or forced refresh will be used for smoke.

**Pre-deployment result:** Full Chromium rerun passes all 21 scenarios/22 reported
tests, including native import confirmation, frozen single/fleet reviews,
CSRF/role controls, no hints and mobile layout. All 239 relative documentation
file links resolve. Packaged Python 3.12 smoke passes in a networkless/read-only
container using only temporary SQLite/synthetic actors: normal API startup
creates no optional tables; explicit isolated fixture demonstrates atomic late
audit rollback, whole-scope retirement/admission without unmanaged adoption,
one-root cancellation, new generation, pruning/replay/key reservation, recovery
pause and still-unavailable BFF confirmation without any new metadata-driven
work. Integrity/FK checks pass. No live state/credential/socket mounts or FTD
connection. Build resolves existing unlocked dependency ranges, not production
dependency-locking/compatibility evidence.

Built API `sha256:7d93f90c5b11324e9291416dda1ad32436d7e3524432a927876030fa8b4c95cc`
and Web `sha256:a03b330f299e6d8c090746046827aee6344e4556d2efc565115997be362e7a8a`.
Replacing only the sole API/Web pair with --no-deps after stopping both; no
overlapping executor or optional schema migration. Post-deploy checks follow.

**Final lifetime edge-case correction:** Post-package inspection found that
flooring a remaining fractional second made an otherwise valid 1-second cleanup
lifetime reject immediately. Use ceiling only for the queue's integer-duration
input; clamp the persisted queue deadline to the immutable original root expiry
and recheck expiry after all queue/audit work. A new half-second elapsed fixture
confirms 1-second admission succeeds without extending the original deadline;
existing pre/post-queue expiry rollback tests remain. Final Python rerun and
rebuilt-package/deployment checks follow. No live admission or optional schema
was exercised during this correction.

**Final validation/deployment result:** All **550 Python tests pass** (20.12
seconds); 21 Chromium scenarios/22 reported tests pass. Final compileall/Ruff/
JS syntax/diff and 239 relative file links pass. Rebuilt Python 3.12 package
smoke confirms half-second admission with a valid 1-second immutable deadline,
unchanged receipt replay and integrity/FK, in a disposable networkless/read-only
container. The final deadline correction changed no UI/runtime admission gate.

Final API image
`sha256:f4192b7d543b1046fcfa70cb190a6fd55b83d3b746d29519f7e642f3f1c709c3`
and Web `sha256:9ef4b50830b8e5fb39e83d7b4d9f2ac164bd6d8dfb78ec78e9e6cee6775509a3`
are running as `d61053998b5b` / `ea732cd8598e`. The release replaced only the
sole API/Web pair, including the final lifetime correction, with no overlapping
executor. The original checked backup/paired rollback tags remain valid and
retained. Intermediate pair `68c144283e65` / `1ab6f265b9fc` performed an ordinary
read at 18:40:03Z; final pair respected the persisted minimum interval, completed
its ordinary v2 cycle at 18:41:21Z with two commands/zero removal/addition/mutation
steps and 8429 ms, next baseline 18:46:21Z/no error. No refresh hint/direct RPC
was used to accelerate either cycle.

Full sqlite_master definitions and all eleven non-executor tables match the
18:38Z checked backup exactly; integrity ok/FK errors zero. No optional managed/
handoff/fleet tables were initialized, no policies/jobs/authority changed. Eight
VERIFIED/one NOOP, zero pending/active shuns, three Protected IPs, mutation pause
false. Actual ADD admission/API execution/agent execution/cleanup-worker flags
remain off and inventory has zero eligible addition profiles. Actual env/
inventory/secrets unchanged. Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia
`76f3635ab737` unchanged. Anonymous Managed/status/review/confirmation paths
return 401, TLS-verified HTTPS redirects 302 to authentication. New coordinator
is packaged/importable, not invoked or initialized on the live database. No
spoofed live Web actor, test mutation, fixture seed or production action.

Retain additive authority on any future approved migration/rollback; never
restore old enabled intent or use an older writer that ignores root keys merely
to revert software. The new offline ready-target atomic admission is complete;
fleet ordered ADD waiting, system/protection/generation/claim and uncertainty
integration, executable confirmation and scoped live validation remain next.
Do not present synthetic default-off deployment as managed-write or production
acceptance. No additional action is needed from the operator for this release.

## 2026-10-18 — Explicit ordered fleet cleanup barrier and shared-worker integration

Extended offline fleet admission through explicit `ordered_wait=True`, with a
different canonical mode/digest. Default ready-only bodies/receipts/replays keep
their old behavior; no browser review or HTTP admission acquires ordered mode.
RUNNING ADD may now be captured by exact device/job ID while one transaction
retires all desired members and reserves the full frozen scope. No ready target
is dispatched early. QUEUED one-time ADD, disabled devices or another waiting
single/fleet cleanup still reject the whole scope without partial retirement.

Explicit isolated initialization adds `managed_fleet_waits` linked to retained
root authority. Target count/predecessor evidence are immutable/retained; phases
are monotonic. Reservations share 1000 pending/2000 active bounds (one slot per
target, one active root), actor rate accounting including after cancellation,
new-ADD/managed-re-enable guards and predecessor retention. No auto initialization
from startup/worker/GET, no live seed, no new system restoration source.

`ManagedFleetWaits` promotes only whole roots under the current shared lease,
after every captured ADD settles. Skip still-running roots without starving
later eligible ones. Keep original actor/deadline and validate canonical mode,
retired UUID/generation, device/hostname, predecessor evidence and original UTC
lifetime; do not silently widen/shrink by later observations. Exact known
pre-write deferral may be cancelled atomically with full cleanup, not otherwise.
UNVERIFIED ADD stays uncertain and is never replayed/upgraded to creation.
Expiry/changed evidence/failed admission settles EXPIRED or ATTENTION, releasing
slots without reversing retirement. Lease/audit/database failure rolls back the
advance transaction; late expiry rolls back every materialized target first.
Accepted logs are emitted only after commit, without raw exception/metadata text.
Automated decisions are system audit events linked to the original requester;
materialized ordinary cleanup keeps only the captured short-lived authority.

Internal owner Operator/Administrator or Administrator cancellation is serialized
with promotion, audit-free when already cancelled, and conflicts once queue work
was admitted. It never cancels RUNNING ADD or restarts maintenance. Composite
offline recovery cancels all barriers/reservations, retains immutable roots and
preserves running uncertainty; orphan evidence refuses recovery. Ready-only old
schema still works without implicit migration; ordered waits require the explicit
new table. Retention holds predecessor jobs only while waiting.

The existing default-off cleanup flag now wakes/advances both single and fleet
waits under one persisted lease/cooldown. Budget is eight roots each, sixteen total,
once before the cycle cutoff and fresh device snapshots; no mid-cycle promotion
against a pre-ADD snapshot or independent SSH/executor. Unexpected handoff errors
skip cycle mutations, retain monitoring and publish sanitized diagnostics.
No actual env/gate, topology, wire or agent changes. Executable fleet controls/
visibility and restoration system/generation/claim/uncertainty/rearm/anti-churn
integration plus scoped live validation still gate combined execution.

Validation: **597 Python tests pass** (20.04 seconds), **21 Chromium scenarios /
22 reported tests** pass, compileall/Ruff/JS syntax/diff and 241 relative file links
pass. New synthetic SQLite/fake-agent cases cover explicit mode separation,
multi-predecessor no-overlap/full-scope promotion, role/cancel races, original TTL,
pending/active/rate bounds, generation/device/evidence corruption, atomic root/
promotion audit rollback, lease loss/late expiry, bounded no-starvation selection,
retention/recovery/replay and worker gating/fresh-read/cutoff behavior without ADD
replay. The prior single-worker error fixture now asserts its eight-root share.
No live Cisco, traffic, large-load or production acceptance is claimed.

Lab release preparation under standing authorization: API/Web only; startup may
execute already admitted work but no new test job/control/hint/agent RPC will be
submitted. Preflight: old IDs `d61053998b5b` / `ea732cd8598e`, agent/Caddy/Authelia
unchanged, no optional managed objects, eight VERIFIED/one NOOP, no pending/active
shuns, three Protected IPs, admission/API ADD/cleanup worker off, zero profiles,
integrity/FK pass. Ordinary reads healthy at 15:07:57Z, next baseline 15:12:57Z.
Retained paired images `before-fleet-waits-20261018t1510z` and exclusive checked
0600 volume/ignored host `.local/backups/state-before-fleet-waits-20261018T1510Z.sqlite3`
(0700 host directory), both integrity/FK pass. Quiet merged Compose validation
and build pass. Built API
`sha256:0473b945b25bf7d2b594a2f60a186c127df43366e8c8af97cc79226b0f7bb69e`
and Web `sha256:1b2b2b4930a18b8fa2a9e28278f9c627bd6e9e16bfbeee14e8601198453f5f24`.
Packaged pre-release/rollout checks follow; actual env/inventory/secrets and live
schema/gates remain untouched, with no optional fixture seed.

**Package/pre-deployment result:** Python 3.12 built-package smoke passes in a
read-only/networkless container with disposable SQLite and in-process synthetic
ASGI identities only. Normal startup creates no optional tables; explicit
isolated fixture captures two RUNNING ADDs and three reserved targets, proves
no early cleanup, rolls back a late promotion audit failure, then materializes
one full-scope request with original actor/deadline. ADD uncertainty remains,
same-key replay changes nothing, queue cancellation/recovery retain retirement,
and native BFF combined confirmation still refuses 503 without admission/hints
or metadata-driven work. Integrity/FK pass. No live mounts, credentials, agent
socket or FTD connection. The build resolved the existing unlocked dependency
ranges (including FastAPI 0.145.0); this isolated smoke is not production
dependency-locking/compatibility evidence. Stopping/recreating only the sole
API/Web pair with --no-deps, no overlapping executor. Rollout results follow.

**Deployment result:** Stopped the sole API/Web pair, then recreated only them
with --no-deps; no overlapping executor. API `2942cfd22f14`, Web `b527ecb1bfd0`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Full sqlite_master definitions and all eleven non-executor tables match the
checked pre-release backup exactly; integrity ok/FK errors zero. No managed/
handoff/fleet/barrier schema initialized, no authority/policy/job change. Queue
remains eight VERIFIED/one NOOP with no pending/active shuns; three Protected
IPs and mutation pause false. Actual ADD admission/API execution/agent execution/
cleanup-worker gates remain off, zero eligible addition profiles; env/inventory/
secrets unchanged. New barrier module is packaged/importable, not invoked or
initialized on live state. No test mutation, seed, direct agent call, refresh
hint or spoofed live Web identity.

Ordinary post-start v2 cycle completed at 15:15:29Z: two commands, zero removal/
addition/mutation steps, 8651 ms; next baseline 15:20:29Z/no error. Repeated
optional GETs leave schema absent and empty fleet scope correctly returns 409.
Anonymous Managed/status/review/confirmation paths reject 401; TLS-verified
HTTPS returns 302 to authentication. Checked backups and paired rollback images
retained; do not restore old desired authority/drop tables to revert code.
Clarified root-ledger transitional refusal versus barrier cancellation in the
recovery manuals. Final compileall/Ruff/JS syntax/diff and 241 relative file
links pass. Runtime fleet controls/visibility, system restoration/generation/
claim and uncertainty/rearm/anti-churn integration plus fresh scoped live
validation remain pending. No live ordered-cleanup, ADD or production acceptance
is inferred from these synthetic/default-off release checks.

## 2026-10-18 — Fleet status, waiting revocation and queue progress batch

Implemented an optional read-only fleet-root view and separate waiting-only
revocation endpoint/BFF control. No admission route, feature enablement, schema
change or device-write path. The architecture amendment explicitly permits only
observations/revocation; combined confirmation remains unconditional 503.

`ManagedFleetState` reads counts, roots, captured ADD evidence and linked REMOVE
outcomes in one SQLite read transaction. At most twenty roots are returned,
active/attention first, with whole-ledger counts and a labelled five-target
sample. Old ready-only ledgers need no migration. Unknown/partial/corrupt optional
state is unavailable; pruned job evidence is explicitly unknown. Captured ADD,
barrier, delegation state and linked jobs remain separate; a settled-jobs bar is
not success, and only all-target matching VERIFIED REMOVE is green. Shared jobs
may continue after a root delegation is cancelled/expired. Retained outcomes do
not assert current device presence after later changes.

Current owner Operator/Administrator or Administrator may cancel only WAITING_ADD.
The strict private actor POST and CSRF-only URL-encoded BFF form serialize with
promotion, append actual-canceller audit atomically and validate exact receipts.
No running ADD/ordinary queue cancellation, authority renewal, retirement reversal
or refresh hint. Repeated cancellation is audit-free; lost/malformed replies stay
uncertain and retry the same root. Optional schema/authority checks precede
revocation; startup/GET never initialize tables. Existing metadata revisions and
single-submission controller update keyed regions/disclosures without navigating
or replacing frozen forms. Completed records collapse, errors/waits stay visible,
progress labels have explicit spacing, and scope/deadline text stays bounded.

Added synthetic SQLite/ASGI coverage for current roles/CSRF/strict inputs,
owner/Admin, cancellation/promotion conflict, unknown replies, audit rollback,
optional absence/corruption, pruned history, independent delegation/job states,
all terminal outcomes, concurrent read consistency, bounded roots/samples and
no hints/work. Updated endpoint allowlist tests to allow only observational GET
and waiting revocation, never fleet admission. Chromium checks live outcome/color
changes, mobile spacing, disclosure retention and cancellation without navigation
or device hints. Initial fixture issues (policy revision, reason binding and
group spelling) were corrected without changing implementation safeguards.

Updated architecture, agent agreement, status, README and relevant manuals.
Validation: all **623 Python tests pass** (24.16 s), compileall/Ruff/diff/JS
syntax pass and 244 relative file links resolve. Chromium's new fleet scenario
passes alongside the existing suite (22 scenarios / 23 reported tests); a final
rerun covers the exact release templates. No Rust/wire changes. A built Python
3.12 package passes isolated networkless/read-only synthetic ASGI/SQLite smoke:
no optional startup initialization, three-target waiting view, strict BFF input,
waiting revocation/retry without extra audit, unchanged RUNNING ADD, no admission
route/hints and integrity/FK. The existing unlocked dependency ranges resolved
FastAPI 0.146.0/Starlette 1.9.0; this smoke is not a dependency-locking or
production compatibility claim.

Preflight of the authorized existing lab: no active work or optional tables,
queue eight VERIFIED/one NOOP, three Protected IPs, ADD/admission/cleanup-worker
off and zero eligible profiles. Paired old images retained as
`deploy-api:before-fleet-controls-20261018t1552z` / matching Web tag. SQLite-safe,
exclusive/no-symlink 0600 volume backup and checked private ignored host copy:
`.local/backups/state-before-fleet-controls-20261018T1554Z.sqlite3` (0700 directory).
Both copies pass integrity/FK. Quiet Compose validation and API/Web-only build
pass. Authorized default-off deployment/check results follow below.
Rust/wire and actual env/inventory/secrets
are unchanged. No optional live fixture, new job, consumed test-address reuse
or standing desired authority is authorized by this batch.

**Final browser/release result:** The exact release templates pass all 22
Chromium scenarios (23 reported tests), without JavaScript exceptions (85.87 s
suite). Stopped/recreated only API/Web with --no-deps, no overlapping executor.
API `0e22c10a595d`, image
`sha256:596c28eced77b63dc20920635612f3da230368bf18ade06aa3a7a89695f34a5f`;
Web `302264c35e6d`, image
`sha256:f81af6a735457d9835560f3cb0d79571a73465e6d4ce7b52f213fef37c5c8698`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.

Full sqlite_master and all eleven non-executor tables match the checked backup;
integrity ok/FK errors zero. Queue eight VERIFIED/one NOOP, no pending/active
shuns, three Protected IPs, pause unchanged. Actual API import admission/execution
and cleanup-worker gates remain off; agent ADD setting is absent, which source
explicitly defaults to false, and inventory has zero addition profiles. No env,
inventory or secret edits. Repeated optional GETs (including the new fleet view)
return initialized=false without creating tables. Anonymous Managed/status and
waiting-cancel/combined-confirm paths return 401; TLS-verified HTTPS returns 302
to authentication. No real Web identity was spoofed, no authenticated control
submitted and no optional data seeded. Post-check script table/route naming and
explicit-versus-default flag assumptions were corrected with read-only checks;
these were checker errors, not runtime failures or grounds for changing settings.

Normal post-start v2 read cycle completed at 2026-10-18T15:54:42Z, two commands,
zero removal/addition/mutation steps, 8586 ms; next baseline 15:59:42Z/no error.
No hint, direct agent RPC or new live mutation. Paired rollback images and checked
volume/private-host backups retained. Final compileall/Ruff/JS syntax/diff and
relative links pass. Fleet status/revocation is synthetically validated, **not**
live managed/fleet write acceptance. Combined admission, standing restoration/
generation/claim cancellation, uncertainty/rearm/anti-churn, reviewed migration
and separately scoped live validation remain pending; all live gates stay off.

## 2026-10-18 — Offline system restoration authority and lifecycle

Implemented the standing system ADD source as an offline integration increment,
not a runtime controller. Explicit optional attempt initialization only; no new
environment switch, HTTP admission, discovery loop, live seed or dispatcher call.
All deployed ADD/cleanup-worker gates and device profiles remain unchanged.

`ManagedRestorations` derives one request key per intent/snapshot, requiring
explicit managed authorization, fresh complete UTC absence after relevant policy/
operation timestamps, current lease, unpaused/unsuspended enabled target and no
protection/cleanup/conflicting or uncertain job. It inserts one ordinary ADD job/
link with an independent 900-second system delegation, empty captured roles and
retained immutable policy/generation/snapshot/authorization linkage. No expired
manual authority renewal, fake import batch or system/manual coalescing. Existing
shared capacity/FIFO/cutoff and budgets remain; default runtime capability holds
the source and does not wake a second executor. Admission rechecks lease and
freshness before commit; claim validates exact linkage/current authority and
checks expiry again before returning dispatch ownership.

The retained 10000-key optional ledger survives queue/history pruning and
reserves request/job keys across namespaces. Initial domain defaults are 300s
between attempts and at most three per pair/rolling hour across generations.
FAILED/UNVERIFIED latches never clear through new IDs/generations/observations or
lease recovery; reviewed resolution/rearm is not implemented. Exact pre-write
deferral preserves the same authority/deadline. VERIFIED alone records actual
occurrence/interface/date; NOOP never claims creation/import ownership. Terminal
evidence is immutable. System audit includes original policy/snapshot/job and
managed/protected revisions, not invented current user roles.

Registry retirement, Protected-IP edits/initial legacy import and offline
recovery now atomically cancel only queued system work. Running ADD can finish
and remains covered by explicit ordered cleanup; it is never falsely cancelled.
Single/fleet composite removal may supersede its unstarted system restoration,
while independent queued imports still conflict. Late queue/audit failure rolls
back retirement, cancellation and removal together. Recovery retains RUNNING
uncertainty and keeps restoration suspended on ordinary resume. Partial/orphan
optional evidence fails closed instead of being initialized or repaired.

Managed shuns reads optionally show retained attempt/attention across generations
and last verified restoration with localized timezone, while still warning that
the controller is unavailable. Queue metadata labels the system source honestly
and exposes no generic cancel for it. New source/manuals, architecture, agent
agreement, status, README and relevant queue/recovery/fleet procedures updated.

Validation uses disposable SQLite, typed synthetic outcomes and localhost browser
fixtures, never live source initialization or FTD mutation. Results, built-package
smoke and authorized default-off API/Web deployment checks follow below.

**Validation/build result:** all 676 Python tests pass (27.13 s), including 53
new system-source cases. Compileall/Ruff/diff/JS syntax pass. All 22 Chromium
scenarios (23 reported tests) pass without JavaScript exceptions (72.70 s suite),
including live optional attention and timezone-labelled verified dates. Synthetic
fixture cycle advancement was corrected to release/claim the lease across the
persisted cooldown, not renew an already expired lease; no product guard was
weakened to make a test pass.

Built Python 3.12 package smoke passes in a networkless/read-only disposable
container with no live mounts/secrets/socket. It verifies no optional startup
tables, default-held system authority, original-key replay, VERIFIED occurrence
without imported provenance, fresh later absence, retained UNVERIFIED latch,
Protected-IP cancellation, optional BFF rendering and integrity/FK. No remote
command is dispatched. Existing unlocked dependency ranges resolved FastAPI
0.146.0/Starlette 1.9.0; this is not dependency-locking/production acceptance.

Authorized lab preflight: no pending jobs/optional schemas, queue eight VERIFIED/
one NOOP, ADD/admission/cleanup-worker off, zero addition profiles. Quiet Compose
validation/API-Web build pass. Retained paired pre-release images:
`deploy-api:before-restoration-source-20261018t1634z` / matching Web tag. Checked
exclusive/no-symlink 0600 SQLite-safe volume backup plus private ignored host
`.local/backups/state-before-restoration-source-20261018T1636Z.sqlite3` (0700 dir);
both pass integrity/FK. Actual env/inventory/secrets and agent/wire unchanged.
Stopping/recreating only the sole API/Web pair with --no-deps; deployment checks
follow. No controller/worker gate, live policy/schema seed or new mutation.

**Deployment result:** Stopped/recreated only the sole API/Web pair with
--no-deps; no overlapping executor. API `955caa56f971`, image
`sha256:8f4472bb4229ae4d225628ba2c0d3016495c92a747517a234328185d0ddb17a4`;
Web `3cef0e149401`, image
`sha256:486a8e3ebede4d6283a69bdc34ce910ad13223bccc88829f276ac30a65b545a4`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Full sqlite_master and all eleven non-executor tables match checked backup;
integrity ok/FK errors zero. Queue remains eight VERIFIED/one NOOP, no pending
or active shuns, three Protected IPs and mutation pause unchanged. Actual API
ADD/admission/cleanup-worker off, agent ADD unset/source-default false, zero
eligible profiles. Env/inventory/secrets and Rust/wire unchanged.

Repeated optional GETs return initialized=false and create no registry, attempt,
handoff or fleet table. Anonymous Managed/status and revocation/combined-control
routes return 401; TLS-verified HTTPS redirects 302 to authentication. No live
Web identity spoofing, authenticated control, optional source/policy seed, new
job, hint or direct agent call. Normal post-start v2 cycle at
2026-10-18T16:37:31Z: two commands, zero removal/addition/mutation steps, 8623 ms;
next baseline 16:42:31Z/no error. Paired images and checked private backups retained.
Final compileall/Ruff/JS syntax/diff pass; 253 relative file links resolve.

Next: connect bounded default-off complete-snapshot discovery/backlog, frozen
standing-mode grant/combined controls and reviewed resume/uncertainty resolution,
then scoped lab restoration lifecycle. Offline tests/package/default-off release
do not establish live restoration/reboot/load/failure or production acceptance.
No new infrastructure, service, published port or arbitrary CLI was added.

## 2026-10-18 — Default-off snapshot discovery and shared system dispatch

Connected standing-policy absence discovery to complete successful initial,
priority and final snapshots, after reconciliation, with stable per-read UUIDs
and UTC read start/completion. Added strict independent false-by-default
`FTD_SHUN_MANAGED_RESTORATION_ENABLED`; ordinary ADD/cycles/large reads/profiles,
agent gate and existing explicitly initialized/unsuspended authority still apply.
No schema, policy adoption/grant/resume/rearm, extra executor/read, published
port, CLI primitive or combined-removal confirmation is introduced.

Discovery admits at most sixteen new jobs and performs sixty-four checks across
an entire sweep. New jobs cannot bypass its pre-read cutoff or persisted >=60s
cooldown. Retained last-admission ordering prioritizes never/least-served targets
and devices across restarts without a new cursor/table. Source admission binds
the assessed intent UUID so a same-millisecond retirement/regrant race cannot
rebase evidence. Capacity/conflicts are holds, not successful restoration.
Unexpected failures roll back source admission/audit and skip subsequent cycle
mutations; monitoring/final reads continue when available. Background optional
state failures do not kill the scheduler or cause an immediate retry loop.

Managed UI/API expose controller configuration, current target holds, localized
backoff deadlines, collapsed latest-sweep counts and sanitized failure warnings
in the existing fixed-height slot. Counts describe visited devices, not global
inventory or verified work. GET remains local/read-only/no-init/no-admission.
Updated normative design, agent agreement, README, status, plan and manuals.

Synthetic validation: all 705 Python tests pass (26.51 s), including 29 new
discovery cases for default-off/no-init, complete read/cutoff/cooldown, repeated
absence, restart fairness, budgets/backpressure, generation and lease races,
failed reads, audit rollback preserving final monitoring, independent pending
removal suppression on discovery failure, retained lost-result attention and
read-only holds/configuration. One further read-only API/template case verifies
enabled configuration without profile/schema grants and honestly labelled
collapsed counts. Final full suite: **706 passed (26.35 s)**. Compileall/Ruff/
JS syntax/diff pass. All 22 Chromium scenarios (23 reported tests) pass, including
the fixed-height restoration-error warning (78.95 s runner). Networkless,
read-only Python 3.12 built-package smokes with disposable SQLite and no live
volumes/secrets/sockets pass: no startup migration even with the gate configured,
complete snapshot discovery, cutoff/persisted cooldown, VERIFIED/new absence,
retained lost-result latch, source idempotency/provenance/protected cancellation,
optional BFF rendering and integrity/FK. No real remote calls.

**Authorized lab deployment:** Preflight confirmed all gates off/zero profiles,
optional schemas absent and queue eight VERIFIED/one NOOP with no pending/active
shuns. Quiet Compose config/build pass. Retained paired images
`deploy-api:before-managed-discovery-20261018t1700z` and matching Web tag. Created
exclusive O_EXCL/O_NOFOLLOW 0600 SQLite-safe checked volume backup and private
ignored host `.local/backups/state-before-managed-discovery-20261018T1700Z.sqlite3`
(0700 directory). Stopped old API/Web before --no-deps recreation, no overlapping
executor. Agent/Caddy/Authelia/env/inventory/secrets and Rust/wire unchanged.

API `cbdea24dd521`, image
`sha256:078ced6373c02dc32ab178e5c52d5b4204b4a2bcd054efd59acb5bccd9eb6213`;
Web `a5193eeba8be`, image
`sha256:58e9e9034ac0dffc25ae297182d247738f643f6017825ba3f598caa27c0a5a19`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Full sqlite_master and all eleven non-executor tables including sequence
metadata match backup; integrity ok/FK zero. Optional read endpoints remain
initialized=false and create no managed/attempt/handoff/fleet schemas. Three
Protected IPs, queue eight VERIFIED/one NOOP, no pending or active shuns and
mutation pause unchanged. API ADD/admission/cleanup/controller off, agent ADD
unset/source-default false, zero profiles. Anonymous Managed/status 401 and
TLS-verified HTTPS 302 to authentication. Normal post-start v2 cycle at
2026-10-18T17:03:28Z used two commands/zero removal/addition/mutation steps,
8580 ms; next baseline 17:08:28Z/no error. No identity spoofing, authenticated
control, source/policy seed, new job, refresh hint or direct RPC. Paired images
and checked backups retained; no Rust change/build was required.

Next: frozen standing grant and executable atomic combined cleanup, reviewed
migration/resume/uncertainty resolution, then separately scoped live restoration
and explicit retirement/no-readd acceptance. Disabled deployment and synthetic
tests are not live reboot/restoration/load/failure or production validation.

## 2026-10-18 — Frozen single-target standing consent and policy-only admission

Added a collapsed one-device/IPv4 standing-policy form, frozen immutable review
and explicit typed-IP/recurring-authority confirmation. This is separate from
one-time imports, device creation and policy-only retirement. It uses a separate
bounded cache with the existing subject/cookie hash, TTL, five-per-subject/
256-global mechanics. Frozen labels/metadata are escaped; inputs/checkbox/focus
are preserved through polling and unknown replies. A preview prepared with
uninitialized policy cannot become confirmable after later migration.

New strict false-by-default `FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED` permits
only one-pair policy MAINTAIN on the private API, with current role, explicit
canonical key, standing acknowledgement and fixed canonical action/mode. Requires
socket mode, explicit addition profile and existing optional registry/attempt
schemas. Inside one transaction, reject changed revisions/protection/devices,
recovery pause, observed adoption, enabled intent, cleanup or unfinished/uncertain
pair work and retained failure. Registry/audit/key updates are atomic; success
logs follow commit. No queue insertion, immediate refresh/wakeup, initialization,
adoption, resume/rearm or ADD/gate enablement. Combined confirmation remains 503.

An exact old request returns its historical receipt, not new authority: replay
after retirement cannot re-enable it. Lost/malformed replies keep the same key,
body and consent for explicit retry; no automatic submission/reclassification.
Updated normative design, agent agreement, status, plan, README and structured
grant/related manuals. No Rust/wire/dependency/schema/service changes.

Validation: all **750 Python tests pass (32.61 s)**, including 44 grant cases for
API/BFF consent/roles/CSRF/strict bodies, gates/profiles/no-init, transactional
state conflicts, original-key retry/retirement/new generation, retained failure
non-rearm, audit rollback/no success log, concurrent idempotency, cache/session/
purpose/expiry bounds and no job/wakeup. One further case verifies gate-disable
after a committed lost reply: disabled admission never implies the earlier
policy was unsaved. Final **751 tests pass (30.80 s)**. Compileall/Ruff/JS syntax/
diff and 268 relative file links pass. All 23 Chromium scenarios (24 reported
tests) pass (85.77 s runner), including frozen token/typed IP/checkbox/focus,
required native consent and 375px layout without hints/writes. The initial
new browser scenario found its synthetic route missing from the fixture allowlist;
registering that route corrected the harness, not product guards.

Final built Python 3.12 networkless/read-only synthetic package smoke passes:
standing gate configured without startup schemas, explicit isolated migration,
BFF recurring consent, committed lost reply, same-key historical receipt after
retirement without re-enable, no queue/request/attempt/wakeup/refresh hint and
integrity/FK. The shared-restoration packaged lifecycle also passes complete
read/cutoff/cooldown, verified restoration and retained lost-result attention.
No live mounts, credentials, sockets or remote commands were supplied.

Authorized lab preflight confirms absent optional schemas, no pending/active
shuns, queue eight VERIFIED/one NOOP, three Protected IPs and all gates off/zero
profiles. Retained paired `before-standing-grant-20261018t1718z` API/Web image
tags. Quiet Compose config/build pass. Checked exclusive O_EXCL/O_NOFOLLOW 0600
SQLite-safe volume backup and ignored private host copy
`.local/backups/state-before-standing-grant-20261018T1718Z.sqlite3` (0700 dir).
Stopping/recreating only API/Web with --no-deps after validation, no overlapping
executor. No live optional seed, grant, control, hint, job or gate change.
Deployment results follow.

**Deployment result:** Recreated only sole API/Web with --no-deps, no overlapping
executor. API `5c5c74dfa5fe`, image
`sha256:4363c5357bb10344c604b789cfe32280eb8c7124081bd4368480880fc562d604`;
Web `ce7d541859e5`, image
`sha256:570a82084e14fed4abaeb594c923470474e1d046cfbd3c90c4378632942a4579`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Full sqlite_master/all eleven non-executor tables including sequence metadata
match checked backup; integrity/FK pass. Optional reads remain initialized=false,
no managed/attempt/handoff/fleet table or new job. Queue eight VERIFIED/one NOOP,
no pending/active shuns, three Protected IPs and recovery pause unchanged. New
standing admission, ADD/admission/cleanup/controller gates off and zero profiles;
env/inventory/secrets/Rust/wire unchanged. Anonymous Managed/status/new grant
review and confirm reject 401, verified HTTPS redirects 302 to Authelia. No live
identity spoofing, authenticated control, grant/seed/job/hint or direct agent RPC.
Paired images and private checked backups retained. Ordinary baseline observation
follows below; persisted cooldown is not bypassed to accelerate verification.

Normal post-start v2 baseline completed at 2026-10-18T17:23:02Z, two commands,
zero removal/addition/mutation steps, 8502 ms; next 17:28:02Z/no error. Rechecked
schema and every non-executor table against backup after the read, unchanged.
Final compileall/Ruff/diff pass. No startup migration/new authority was introduced
by the disabled rollout. This is package/deployment evidence, not live standing
grant/restoration/reboot or production acceptance. Next: executable atomic
combined cleanup and reviewed migration/resume/uncertainty resolution, then bulk
standing consent and a newly scoped live lifecycle. No existing experiment
authorization was reused.

## 2026-10-18 — Combined cleanup batch: device, fleet and ordered confirmation

Connected frozen single/fleet reviews to their existing atomic coordinators
behind strict default-off `FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED`, requiring
socket mode and the shared cleanup worker. Fixed private device/fleet routes
accept exact typed scope/current actor/canonical key/digest/TTL only. Device
admission rechecks reviewed intent/generation, including replay; fleet compares
the complete frozen union under its existing write transaction and never loops
single-target commits. The preparation checkbox explicitly freezes ordered
mode and its distinct digest. Ready-only does not gain waiting automatically;
ordered roots hold all targets behind captured RUNNING ADD with no early member
cleanup. Independent QUEUED ADD still conflicts.

Added strict historical receipt validation and honest accepted/waiting display,
original-key/body retry with retained typed IP/ordered scope, unknown-response
handling (including wrong success HTTP status), current role/CSRF/configuration
and sensitive-age cap. Only newly accepted plans signal the existing worker;
no refresh hint, direct RPC, alternate executor, automatic retry/rekey/rebase,
schema initialization, policy resume or ADD/restoration enablement. Disabled
admission never disproves an earlier unknown accepted plan. Single-target late
expiry is now rechecked before commit so ready/waiting root/retirement/queue/
audit roll back together instead of accepting already-expired authority.

Updated normative design, agent agreement, structured combined-cleanup manual,
review/coordinator/standing/recovery-related operator boundaries, README, plan
and status. No Rust/wire/schema/service/dependency changes or live test authority.

Validation: **811 Python tests pass (34.93 s)**, including 60 new HTTP/BFF cases:
single/fleet ready and ordered lifecycle, mixed observed-only scope/no adoption,
protection/scope/generation changes, pending independent work, recovery pause,
disabled devices, role/CSRF/strict fields/caps, cache/frozen retry, malformed/lost
receipt, repeated original key after new generation, concurrent same/different
users, no per-target fleet commits, atomic queued-system cancellation/audit
rollback, late ready/waiting expiry and missing schemas/no migration. Existing
offline source/queue/coordinator/recovery suites remain green. Compileall/Ruff/
JS syntax/diff pass. All 24 Chromium scenarios/25 reported tests pass (98.49 s
runner), including enabled device/ready/ordered reviews, disabled-scope blocking,
native validation, frozen token/choice/input/focus, retained draft checkbox and
375px spacing, without refresh hints or device mutations. Packaged integration
and authorized default-off API/Web rollout checks follow.

Final Python 3.12 networkless/read-only built-package smoke passes with no live
mounts/secrets/device sockets. It checks no optional startup schemas even with
admission configured, isolated initialization, BFF single committed lost reply/
original receipt replay, explicit ordered mixed managed/observed-only fleet,
no early removal, UNVERIFIED ADD preserved, all three cleanup jobs materialized
together under original expiry, no observation adoption and integrity/FK.
Standing-grant compatibility/lost-reply/retirement smoke also passes. All 279
relative file links resolve; compileall/Ruff/JS syntax/diff pass.

Authorized lab preflight: optional schemas absent, queue eight VERIFIED/one
NOOP, no pending/active shuns, three Protected IPs, all gates off/zero profiles.
Quiet Compose config/build pass. Retained paired
`deploy-api:before-combined-cleanup-20261018t1740z` and matching Web tag. Exclusive
O_EXCL/O_NOFOLLOW 0600 SQLite-safe volume backup plus ignored private host copy
`.local/backups/state-before-combined-cleanup-20261018T1740Z.sqlite3` (0700 dir)
pass integrity/FK. Stopping/recreating only sole API/Web with --no-deps, no
overlapping executor. Actual env/inventory/secrets/agent/gates unchanged; no live
schema seed, grant/cleanup control, new job, hint or direct RPC was submitted.
Deployment observations follow.

**Deployment result:** Stopped/recreated only API/Web with --no-deps, without
overlapping executors. API `78c1a0968df4`, image
`sha256:28c00563bdbca068873241cd888af585a640127c8ffded8e6c84a37b3a9fed3f`;
Web `cce7282a7280`, image
`sha256:208dab764faeecfdafc3ae5668bb5220058bb9d7b9a43184729c7c99f449476c`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Full sqlite_master and all eleven non-executor tables including sequence metadata
match checked backup, including after the ordinary baseline; integrity/FK pass.
Repeated optional GETs remain initialized=false and create no managed/attempt/
handoff/fleet table. Queue eight VERIFIED/one NOOP, no pending/active shuns,
three Protected IPs and recovery pause unchanged. New combined/standing/import
admission, API ADD, cleanup worker and controller off, agent ADD source-default
false, zero addition profiles. Actual env/inventory/secrets/Rust/wire unchanged.

Anonymous Managed/status/device review/fleet review/confirmation reject 401;
TLS-verified HTTPS redirects 302 to authentication. Preserved persisted cooldown,
no verification refresh hint. Normal post-start v2 read at
2026-10-18T17:44:47Z: two commands, zero removal/addition/mutation steps, 8747 ms;
next baseline 17:49:47Z/no error. No live identity spoofing, authenticated control,
schema/fixture/policy seed, new job or direct RPC. Paired images/private backups
retained. Final compileall/Ruff/JS syntax/diff pass.

Next: reviewed optional migration, desired-policy resume/uncertainty resolution
and bulk standing consent, followed by separately scoped live acceptance.
Default-off implementation/package/deployment is not approval to enable gates,
initialize a fixture, reuse the consumed one-address authorization or claim
live managed cleanup/restoration/reboot/load/production validation.

## 2026-10-18 — Reviewed offline managed migration and desired-policy resume

Added `ftd-shun-managed-maintenance` with separately read-only preparation and
explicit offline initialization/resume commands. A five-minute UTC review binds
schema, retained policy/attempt/single/fleet authority, executor/protection
revisions and persisted device/protection state. Changed/expired/future reviews
refuse instead of silently rebasing. Trusted-host maintenance actors have empty
directory roles, never spoofed Web identity. Tool reads no environment/inventory
file/credentials and starts no service or network/agent operation.

Extracted the existing checked exclusive-file SQLite-API backup/concurrent-commit
wrapper without changing ordinary recovery semantics. Empty initialization
requires the ordinary durable pause, settled executor and no pending jobs;
existing/partial optional schemas are not repaired. All seven optional tables,
indexes/triggers, suspended empty metadata and audit share one transaction.
Refactored optional initializers to compose complete trusted statements with
sqlite3.complete_statement rather than executescript's implicit transaction
commit. Injected late DDL/audit failure rolls everything back even when the
caller catches the error and commits its outer transaction. No observation,
old import/job or event becomes standing authority; startup/GET still never
initialize optional state.

Separate offline resume requires reviewed ordinary recovery resume first, exact
schema and enabled canonical standing authority. Pending jobs/leases, retained
UNVERIFIED jobs, pending/FAILED/UNVERIFIED restoration, waiting/transitional/
attention cleanup, protection/disabled devices, absent targets and backwards
policy clocks refuse. It clears only desired suspension and bumps enabled
target revisions/updated-at plus registry revision and atomic maintenance audit.
A one-millisecond-after-control barrier rejects pre-resume snapshots using the
existing trusted source check. Preserve intent/generation, original authorization
dates/requests, retired rows, immutable keys/results and every queue entry.
Original-key grant replay remains observational. No uncertainty override, rearm,
new/re-enabled intent, delegation renewal, queue insertion, wake, HTTP resume or
feature/profile enablement. Added normative amendment and structured offline
runbook; updated agreement/status/plan and relevant manuals.

Validation: all 852 Python tests pass (39.35 s), including 41 new disposable-
SQLite maintenance cases covering no-init/no-adoption, quiescence, exact schema,
digest/CAS/clock/expiry, checked backup/no overwrite, caught-error transaction
rollback, original authority/retired targets/receipt replay, retained FAILED/
UNVERIFIED, fleet barriers and post-resume snapshot gating. Existing recovery,
source/discovery, queue, grant and cleanup admission suites remain green.
Compileall, Ruff and git diff --check pass. A normal sandbox ASGI-containing
diagnostic subset was interrupted on the known socket restriction; the complete
suite used local socket-capable execution, synthetic fixtures only.

Built wheel using an isolated temporary Hatchling backend (not installed into
the operator's Python environment); final-source package matches all eight
changed/new Python modules. Installed only under a temporary directory, checked
the new console entry point/help, and reran all 41 maintenance tests against
that installed package (0.78 s). No dependency bounds changed. Documentation
file links resolve. No browser templates/CSS/JS, Rust/protocol, Compose, actual
env/inventory/secrets or live database changed; no live command/deployment,
migration/resume/grant/cleanup/hint/fixture or device mutation was submitted.
Existing lab images remain in place; an offline-only tool does not require UI
restart. Live optional migration/policy activation still needs scoped approval.
Next: uncertainty resolution/rearm design and bulk standing consent, then a new
approved managed lifecycle; this is not live restoration/reboot/load/rollback
or production acceptance. Never reuse the consumed one-address authorization.

## 2026-10-19 — Offline retained attention inspection and resolution boundary

Added the non-executable `attention` action to the managed maintenance CLI and
a separate read-only report module. It unifies retained ordinary UNVERIFIED
ADD/REMOVE, immutable FAILED/UNVERIFIED restoration attempts and single/fleet
ATTENTION cleanup. Matching retained restoration jobs are not counted twice;
inconsistent pair/action/outcome remains explicit and does not hide another
ordinary uncertain operation. Retained/pruned/not-applicable job evidence,
original authorization/intent/generation, current policy/protection/device state
and cached active-interface count/last-seen timestamps remain distinct. A later
generation, retirement or cache observation does not clear a failure latch or
prove an unknown write succeeded. Captured single-cleanup predecessor is labelled
ADD, not falsely represented as completed REMOVE. Fleet reports preserve exact
scope count with five sampled targets; malformed/count-mismatched scope is unknown,
not an inferred smaller set. No raw CLI/errors/comments/payloads/keys escape.

Separate pending queue/system/single/fleet counts and inconsistent fleet admission
phases explain non-terminal resume blockers. Optional absence yields explicit
null component state; partial/changed/over-capacity schema, invalid metadata or
missing pending restoration evidence refuses inspection. CLI requires the same
offline/RPC-settlement assertion and existing absolute path, opens SQLite mode=ro
and never creates a missing DB. It requires no backup because it writes nothing.
No schema initialization, audit append, retirement/resume, latch resolution,
queue insertion, work hint, delegation renewal, configuration/profile enablement
or agent/network/device operation occurs.

Bounded 100-case pages use original request time/source/ID stable ordering.
Subsequent pages require a SHA-256 snapshot of retained evidence and policy/
queue/protection/device/observation context. Changed context refuses instead of
silently rebasing/skipping cases. Streaming fingerprints bound Python collection
memory, but still scan retained context: this is not a cheap live polling API.
Digest is a read-consistency token, not an executable review/permission.

Updated normative design, repository agreement, structured Attention Inspection
manual, recovery/maintenance/restoration/development manuals, README and plan.
Recorded planned resolution separately: exact-case evidence review, first
explicit abandonment/retirement with a durable decision separate from unchanged
outcomes, and no implicit new authorization/rearm. Whole-fleet and retention/
restore/audit semantics remain prerequisites. No resolution table/action or
resume exception is implemented in this increment.

Validation: all 892 Python tests pass (36.12 s final run; earlier run 37.41 s),
including 40 new disposable SQLite cases: optional absence/partial/capacity,
strict read-only connection/no changes, all incident sources, pruning/dedup/
generation/inconsistency, protected/cached context, 1000-member fleet five-target
sample, malformed/count mismatch, pending state, 205-case three-page consistency,
changed context, strict arguments, missing file and CLI/no-backup behavior.
Compileall, Ruff and git diff --check pass. Built the final-source wheel with
temporary isolated build dependencies; installed only into a temporary directory,
compared both changed/new Python modules byte-for-byte with source and verified
the console entry point/help. All 81 attention/maintenance tests also pass from
that installed package. Relative documentation links resolve.

No browser assets, Rust/agent protocol, Compose, schema or dependency bounds
changed. No actual lab database/env/inventory/secrets, migration, resume, fixture,
identity spoof, new queue job, device call or deployment was touched. Existing
services/images remain in place; no restart is required for offline diagnostics.
This is not executable uncertainty resolution, live recovery/restoration or
production acceptance; all feature-specific lab authorization limits remain.

## 2026-10-19 — Explicit offline abandonment batch and retained revocation guards

Implemented three linked increments after read-only attention: (1) separate
reviewed optional ledger migration; (2) exact restoration-incident abandonment;
(3) retained decision reporting and cross-authority/runtime protection. Added a
normative amendment and structured Incident Abandonment manual; updated current
status/plan/agreement, maintenance/recovery/restoration/attention/contributor
manuals and README. Preserved the pre-existing dirty attention increment.

The new optional managed_incident_closures ledger retains at most 10000 immutable
receipts, minimal original evidence, maintenance actor/reason and reviewed/closed
UTC dates. It references the retained attempt, not expirable queue jobs. Immutable
update/delete triggers prevent outcome/receipt/key recycling. Base initialization
still creates seven tables. review-enable-closures/enable-closures add the eighth
only to the exact base schema, requiring both pauses/no pending work/lease,
five-minute state confirmation and a checked exclusive 0600 SQLite backup.
DDL/contract/audit failure rolls back. Reads/startup never initialize it; both
explicit schema versions are recognized and unknown/orphan closure state refuses.

review-abandon/abandon support only one retained FAILED/UNVERIFIED restoration
case, binding original canonical request UUID, operator, printable bounded reason,
five-minute exact state, original attempt and current target intent/generation;
confirmation requires typed IPv4. Quiescent ordinary/desired pauses and settled
RPC assertion remain mandatory. Overlapping single/fleet attention or pending
work refuses instead of partially handling a fleet. Pruned terminal jobs remain
explicit; inconsistent retained pair/action/outcome refuses. Changed scope,
clock, device, protection or cached observation never silently rebases.

One transaction retires current enabled maintenance, increments registry revision,
retains evidence/receipt and appends MANAGED_RESTORATION_ABANDONED under a trusted
maintenance actor with empty directory roles. Original consent/intent/generation,
jobs/attempts/outcomes and already retired dates stay unchanged. Same original-key
retry, including after expiry, returns only the historical receipt; no later
generation is retired and no authority renewed. Distinct-key races cannot create
a second decision. Audit/late-expiry failure rolls back even if caught externally.
MAINTAIN/restoration reject abandoned pairs and queue/policy/cleanup/restoration
namespaces reserve closure IDs; old grant replay cannot re-enable policy. Recovery
validates and retains optional revocation state. Attention keeps failures/latches
visible with a separate abandonment receipt and count, no raw reason/error/CLI.

Important limit: this abandons maintenance, not the unknown device outcome.
No FAILED/UNVERIFIED latch is reset, no policy-resume exception is implemented,
and no ordinary/device/fleet incident resolution, rearm, ADD, REMOVE, delegation,
wake, HTTP action, feature gate or device profile is enabled. Unrelated healthy
policy resume remains blocked by the existing global recovery checks; that
requires its own durable-resolution design, not deleting evidence or ignoring
closed cases.

Validation: final full suite 930 passed (39.21 s), with 38 new abandonment cases;
maintenance/attention/abandonment subset 119 passed. Tests use synthetic standing
authority/shared queue hooks and disposable SQLite only. Covered migration/no
implicit initialization, private checked backup, immutable receipt/evidence,
failed/uncertain outcomes, original-key concurrency/replay, original consent/job/
attempt preservation, stale/future/late-expired review, reason/typed IP, namespace
guards, changed policy/protection/device/cache/generation, quiescence, overlapping
cleanup, pruned/inconsistent evidence, full ledger and caught audit/DDL rollback.
Early test runs exposed timestamp-order/clock and monkeypatched-capacity fixture
assumptions; fixtures corrected without relaxing production clock/capacity checks.
Compileall, Ruff and git diff --check pass. Built the final-source wheel using
temporary isolated build dependencies, installed only in a temporary directory,
verified eight changed/new source modules byte-for-byte and console entry point/
help. Installed-package subset results and final documentation checks follow.

No actual lab database, env, inventory, secrets, schema migration/closure, live
identity, new job/hint/RPC/device command or deployment was touched. No Web assets,
Rust/wire, Compose or dependency bounds changed. Existing services remain in
place; future authorized ledger activation requires matching current API/Web
code and a reviewed rollback plan. Never drop decisions or use an older writer
that ignores them. This is not live closure/recovery/restoration/reboot/load or
production acceptance, nor permission to reuse the consumed one-address fixture.

Final package checks: all 119 abandonment/attention/maintenance cases pass from
the isolated installed wheel (including the explicit policy-namespace replay
guard); all 38 abandonment cases also pass directly. All 313 relative file links
resolve. Final compileall, Ruff and diff checks pass. No live rollout performed.

## 2026-10-19 — Pasted standing-policy batch and lab UI rollout

Delivered a user-facing list workflow: Managed shuns and one-time Import preview
link to a separate **Maintain an address list** form. It explicitly selects
devices and freezes the full exact-address/device product, recurring consent,
metadata/revisions/prior intent and original UUID. Shared 1 MiB parser counts
duplicates but refuses all invalid/ambiguous/unsupported input without silent
filtering; scope is bounded to 1000 pairs/64 devices and registry tombstones
still count. Frozen POST pages show 100 pairs, retain typed count/checkbox and
never reclassify or submit. Drafts/frozen forms survive status updates, native
validation and mobile layout are exercised, and tokens never enter URLs.

Added strict fixed private `POST /api/v1/managed-shuns/maintain-batch` behind the
existing default-off standing gate. BFF requires both local/upstream capability,
current role/CSRF, exact pair count and recurring consent. The coordinator
reuses one whole-scope transaction/canonical MAINTAIN, not single-target commits;
current profiles/revisions/protection/observed adoption/recovery/cleanup/retained
uncertainty/abandonment/capacity guards remain. Policy/request/audit commit all
or none, without queue jobs, imports, hints, migrations or resume. Single grants
reuse the coordinator without changing their wire/body contract. Unknown/lost/
malformed replies keep the original review/key; retired-policy replay returns
only the historical receipt, never new authority or a verified-creation claim.
Architecture, manuals, contributor agreement, README, status and plan updated.

Validation: final full Python suite **973 passed** (42.73 s), including 43 new
batch cases; previous single-grant/registry subset 72 passed. Covered max1000
atomic admission, last-member conflicts, late-audit rollback, concurrency, strict
fields/role/CSRF/count/consent, stale revisions, cache/session/capacity, lost and
malformed receipts, disabled current capability/frozen uninitialized review,
retired-key non-reenable and unchanged queue/import/suspension. Chromium **26
scenarios / 27 tests passed** (91.93 s), including 102-pair pagination/frozen
consent and preserved untruncated paste draft. An initial assertion expected
literal “1 MiB” after the dynamic counter rendered localized bytes; corrected
the fixture expectation, not production limits. Compileall/Ruff/diff pass.
New images build/install the wheel under Python 3.12; a networkless read-only
container with disposable SQLite verifies packaged templates, whole-batch save,
retirement, same-key observational replay and zero queue/import work. Initial
smoke calls were corrected to use the explicit optional registry-view API.

Authorized lab rollout replaced **only API/Web**, stopping the sole pair before
replacement with `--no-deps --no-build`; no overlapping executor. Retained tags
`ftd-shun-api:rollback-20261019-standing-batch` and
`ftd-shun-web:rollback-20261019-standing-batch` identify prior paired images
`28c00563bdbc` / `208dab764fae`. New API container `7249a1aab2b9`, image
`70a7c1bad1b2f11618094db0a94f1b92276178e11073f2d6b9542e3970852fc3`;
Web `a05fdbb829c9`, image
`5325a1d3487c0ee64410d0fc741a19dc037564fc0ad1a12ae7425c3653f8573a`.
Agent `9d1f50d361ca`, Caddy `9c8fdb3a7f21`, Authelia `76f3635ab737` unchanged.
Exact image identities, not the unchanged development footer `v0.1.0`, identify
this build. No dependency bounds, Rust, protocol, Compose or service ports changed.

Exclusive SQLite-API backup is
`/var/lib/ftd-shun-manager/before-standing-batch-20261019T0904.sqlite3` (0600),
also copied into ignored private
`.local/backups/standing-batch-20261019T0904/state.sqlite3` (0600, directory0700).
Integrity/FK and schema/all11 non-executor-table digests match pre/post rollout;
queue8 VERIFIED/1 NOOP, no pending work, Protected IPs3, active shuns0. An initial
post-backup check expected a nonexistent top-level restoration status flag;
corrected the check to verify its Settings flag, without recreating/overwriting
the backup or changing configuration. All actual admission/ADD/controller/
cleanup gates remain false, addition profiles0, optional managed/attempt/handoff/
fleet/closure tables absent, recovery pause unchanged. Anonymous GET/form POST
checks of all four new BFF routes return401; verified TLS Caddy request returns
302 to authentication. No spoofed live identity, grant, schema migration, seed,
new test job, refresh hint, live ADD/REMOVE or production action performed.
An initial status had null last-success until its first normal baseline
completed. Follow-up confirmed a successful normal read at
`2026-10-19T09:08:43Z`, no reported error and the same checked schema/stable data;
no manual refresh was requested. Final compileall/Ruff/diff checks pass.

This delivers default-off batch policy consent, not live bulk/restoration/reboot/
load acceptance. Further activation requires separately scoped migration/policy/
device-test approval; retained ordinary/fleet uncertainty resolution and safe
unrelated-policy resume remain pending. Do not submit a live batch as smoke,
reuse the consumed fixture, delete latches or run older writers against future
managed/closure authority. Use current recovery/maintenance procedures before
any future authorized migration or downgrade.

## 2026-10-19 — Integrated managed operator lifecycle and prepared lab experiment

Added `tests/test_managed_lifecycle.py`: seven scenarios compose the production
offline recovery/managed CLIs, checked private backups, Web/BFF frozen standing
consent, private API and shared worker on disposable SQLite and typed fake
consoles. No policy/queue SQL edits shortcut initialization, authority, pause/
resume, attempts or results. A controlled clock exercises persisted >=60-second
cycle spacing and 300-second per-pair backoff without sleeps; fake observations
are explicitly synthetic, not SSH/FTD evidence.

Successful device/two-device cases cover empty migration, separate ordinary and
desired resume, retained original intent/generation/authorization, discovery
before next-cycle dispatch, restart across cooldown, verified creation, external
disappearance/restoration, browser combined cleanup, retirement/no-readd and
original-grant-key non-reenable. The final simulated window restores desired
suspension/disabled experimental capability and ordinary monitoring with all
receipts retained. Additional cases cover protection's atomic queued cancellation,
reviewed weakening and later automatic removal; disabled-controller restart
without deadline renewal; ADD reply loss surviving presence/absence/restart and
blocking offline resume; and device/fleet REMOVE reply loss retaining retirement,
independent member results and honest RECONCILED_ABSENT after a later snapshot.
Integrity, private backup mode, real system actor/empty roles, zero fabricated
one-time provenance and absence of implicit closure migration are checked.

All **980 Python tests passed** (46.30 s); seven new cases passed in the focused
run. Compileall, Ruff and git diff --check pass. Early harness failures were an
incorrect synthetic datetime return type and guessed audit-event name; corrected
fixtures to use the actual UTC datetime/event contracts. No production code or
invariant was weakened. No production source/assets/schema/Rust/protocol/Compose
or dependency changed. Existing browser checks remain applicable; no unnecessary
UI test rerun, image build or service restart was performed.

Added structured `docs/manual/managed-lifecycle-validation.md` with the executable
local acceptance command, evidence matrix and concrete proposed 60-minute live
window: device1/fpr1010-lab and new TEST-NET fixture198.51.100.252; reviewed base
managed initialization, one explicit standing intent, initial creation, one
external disappearance/restoration and final device-scoped retirement/removal,
two no-readd baseline reads including restart, original-key receipt check and
restored disabled gates/profile. It specifies private backups, retained schemas/
evidence, supported real Web or separately authorized trusted-host identity,
operator Basic-session disappearance with the executor stopped/RPCs settled,
stop conditions and honest uncertainty. No closure migration, reboot, long list,
production, auth spoofing or general ADD enablement is implied. Updated manual
index, contributor/maintenance/restoration manuals, current delivery sequence
and project status.

Read-only lab preflight at `2026-10-19T09:40:41Z`: device1 enabled; proposed fixture
cached absent/unprotected, historical fixture jobs0; unfinished/uncertain jobs0;
optional managed tables absent; addition profiles0; all import/managed/cleanup
gates false, cycle/large-read true, SQLite quick-check ok. Last normal successful
read `2026-10-19T09:39:38Z`, no error. Inspection used only private API/local
read-only SQLite and non-secret setting booleans, without a refresh hint, agent
RPC, live grant/migration/profile change or device mutation. No actual env,
inventory, secrets, policy or deployed service state was changed.

The runbook is ready for scoped operator approval and fresh Basic-session absence
before any live change. Existing lab deployment permission does not cover this
new migration/policy/device experiment, and the previous one-address permission
is consumed. Uncertainty resolution for ordinary/fleet incidents, safe unrelated-
policy resume, fleet/load/traffic/physical-reboot and production acceptance remain
separate work. No live managed-lifecycle result is claimed.

## 2026-10-19 — Managed lifecycle approval and pre-activation preservation

The operator explicitly approved the prepared one-pair experiment for device1 /
fpr1010-lab and unused TEST-NET 198.51.100.252: reviewed optional initialization,
bounded standing grant/temporary capability, initial creation, one Basic-session
external disappearance, restoration and final combined cleanup. The approved
trusted-host maintenance actor is limited to this fixture. Recorded the scoped
exception in AGENTS.md and updated the runbook/status; no general ADD, bulk,
fleet, reboot, closure migration or uncertainty replay permission is inferred.

Read-only preflight at 2026-10-19T10:02:59Z passed: cached fixture absent,
unprotected and zero previous fixture jobs; no unfinished/uncertain jobs;
optional managed tables absent; addition profiles0; all six experimental API
gates false; socket mode without development authentication. Retained queue
jobs9, Protected IPs3; SQLite quick-check/foreign-key check pass. Normal refresh
last succeeded at 10:00:15Z without error. Requested independent fresh Basic
absence plus unchanged device/version/role and unused-address confirmation.

Created a SQLite-API backup at 10:03:23Z, checked full integrity/foreign keys and
fixture/no-pending/no-managed-state prerequisites, with exclusive file mode0600
and parent0700. Volume path:
`/var/lib/ftd-shun-manager/managed-lifecycle-20261019T1003/before-activation.sqlite3`;
matching ignored host copy:
`.local/backups/managed-lifecycle-20261019T1003/before-activation.sqlite3`.
Both SHA-256: `bb622fbbac0de6b514a161a6fd4621143d026f5e1f6e96342589c590ba758ee6`.
Retained exact current images under suffix `rollback-managed-lifecycle-20261019T1003`:

- `ftd-shun-api`: `sha256:70a7c1bad1b2f11618094db0a94f1b92276178e11073f2d6b9542e3970852fc3`.
- `ftd-shun-web`: `sha256:5325a1d3487c0ee64410d0fc741a19dc037564fc0ad1a12ae7425c3653f8573a`.
- `ftd-shun-agent`: `sha256:72b045e182081c6f2d3c3a7d546a92402dd224179c0891ff7b50c9e85a71df41`.

Preparation only: no production source change, live migration/grant, env/inventory
edit, service restart, extra device read or device mutation. Services and normal
monitoring continue unchanged; activation clock has not started. Each later
offline control still needs its own fresh reviewed state and exclusive backup.
The pre-test database must not replace later authority/history as routine rollback.
The previously recorded 980-test integration result is unchanged; this increment
only records authority and preserves operational artifacts, not live acceptance.

## 2026-10-19 — Scoped managed lab migration, standing consent and activation

Operator supplied `show shun 198.51.100.252` returning only the normal prompt,
then confirmed the address is unused and the otherwise empty desk FPR1010 has
only management connected. Rechecked unchanged images and no pending/uncertain
queue work. Stopped API/Web and agent (agent stop needed its 30-second grace
period; no queued/running mutation or enabled ADD existed). API/Web were stopped
before offline suspension; all three were stopped before managed initialization.

Offline networkless UID10001 maintenance used only the state volume and the
retained matching API image. Every write created its own checked exclusive0600
backup in `managed-lifecycle-20261019T1003` under the state directory:
`before-initial-suspend.sqlite3`, `before-initialize.sqlite3`,
`before-initial-ordinary-resume.sqlite3`, `before-policy-resume.sqlite3`.
The exact-state initialization review at 10:06:44.905Z was ready/no blockers;
seven tables created atomically, zero targets adopted, desired suspension kept.
Ordinary resume cleared only the mutation pause.

Temporarily added device1 profile `fpr1010-766-single-vf-management-v1` and only
standing admission first; restarted matching API/Web/agent with ADD/controller
off. Pure classification/frozen request preparation confirmed an absent,
unprotected exact pair. The approved trusted-host actor
`maintenance:managed-lifecycle-validation` (Operator, explicitly not a Web
identity) admitted original request `3a7dd33d-93cf-4fd8-88b1-a94230494105` at
10:07:57.742Z. Receipt: policy_saved/revision1/changed_targets1/replayedfalse;
intent `54097200-c6d6-4408-8740-da3e00da594d`, generation1. No fixture job created
by admission. Original frozen body/key/response are retained as private0600 JSON
files alongside backups; no replacement key on unknown outcomes.

Inspection caught that early ad-hoc fixture SQL checks used text against packed
IPv4 BLOB columns. Corrected the temporary observer and rechecked both original
backup and current database using IPv4Address(...).packed before execution:
zero fixture jobs, active observations and protected rows in both. Production
classification/admission already used packed values and refused adoption;
no production guard was changed or bypassed.

Stopped all three services again. Offline policy review at 10:08:32.028Z was
ready and contained exactly the original pair/intent/generation/authority.
Reviewed resume raised revision2 and absence barrier10:08:57.860Z; no job queued
by that control. Enabled API ADD execution/controller/cleanup worker/cleanup
admission and agent ADD, retaining cycles/large reads and keeping one-time import
admission false. Matching API/Web/agent restarted at approximately10:09Z;
activation must end by11:09Z. Caddy/Authelia unchanged. No broad import or direct
CLI mutation was sent.

First successful complete read started10:09:02.269Z and completed10:09:09.982Z.
Discovery admitted attempt `c3fa4a90-8669-5fd8-8d67-06285b4c885f`, job
`1812e4de-ac7c-47d7-b5ab-b70c8f54ff4c`, snapshot
`fac1be68-15a1-465b-930a-f75ec6cc8c41`; original intent/generation/request retained,
system actor `system:managed-shun-policy`, empty roles and 900-second deadline
10:24:09.993Z. At10:09:27Z it is QUEUED behind the frozen cutoff/cooldown
(next eligible10:10:11.495Z), not verified creation. No unrelated pending work.
Normal read has no error. Creation, operator external loss, verified restoration,
combined cleanup, no-readd checks and disabled-mode closure remain pending.

## 2026-10-19 — First live managed creation verified; external-loss checkpoint

The first managed system attempt `c3fa4a90-8669-5fd8-8d67-06285b4c885f` /
job `1812e4de-ac7c-47d7-b5ab-b70c8f54ff4c` started at10:10:19.039Z and completed
**VERIFIED** at10:10:26.130Z, interface management, occurrence
`015b19c3-dc2e-4560-890e-97ffdef8c227`. The same standing intent/generation1 /
original authorization remain enabled; complete final snapshot succeeded at
10:10:27Z with no reported error. No new or duplicate attempt appeared and the
original 900-second deadline was not extended. No one-time import was admitted.

At10:10:39Z the shared executor was released, next eligible10:11:27.598Z.
Stopped API/Web gracefully for the approved operator-induced disappearance;
then independently checked both containers exited, zero QUEUED/RUNNING/FAILED/
UNVERIFIED jobs, null executor owner/lease and exactly one VERIFIED restoration
attempt. Agent remains running but has no active service executor. Caddy and
Authelia were not changed; Web is deliberately unavailable while paused.

Asked the operator to obtain Basic `show shun` presence, remove only the exact
expected `.252` management row once, then obtain absence. Unexpected initial
output must stop manual deletion. No external disappearance has yet been
reported, so no restoration success is claimed. Temporary settings/profile
remain configured; do not restart API/Web outside this runbook. Activation
window still ends11:09Z and must be checked on continuation. If that deadline
has passed, do not resume restoration as though authorization renewed; close
the window safely and request an extension for remaining test activity.
Current records pass git diff --check; production source/test result unchanged.

## 2026-10-19 — Independent external disappearance and restoration observation

The operator supplied Basic-session presence of the exact management `.252` row,
then `no shun 198.51.100.252 interface management`, followed by `show shun`
returning only the normal prompt. API/Web were stopped, no pending/uncertain
job/lease existed and the service did not perform this external deletion. Original
standing intent/generation and successful initial occurrence remain retained.
At10:12:19Z checked the original11:09Z activation deadline had not elapsed and
all three deployed image IDs matched the retained set.

`compose start api web` unexpectedly reran socket-init; its recursive chown
failed with Permission denied on `/state/backups` and the new private lifecycle
backup directory. API/Web remained stopped. Did not change backup permissions,
grant capabilities or repeat the initializer. Started only the already initialized
API/Web with `up -d --no-deps` successfully; agent/Caddy/Authelia unchanged.
Recorded the safe existing-volume restart procedure and a required initializer
follow-up in the lifecycle manual. This startup failure is not an FTD command
failure, new attempt or uncertain ADD; no rekey/retry of device work occurred.

Complete normal snapshot at10:12:52Z confirmed fixture absence and no device-read
error. Exactly the original VERIFIED attempt remains; the controller reports
`backoff` until10:14:09.993Z (300 seconds after original admission). Next baseline
is10:17:52Z, not an immediate write at backoff expiry. No interval/clock/cutoff
was changed and no refresh hint/manual ADD was submitted. Awaiting natural
discovery and the subsequent eligible dispatch. Prepared, but have not executed,
a bounded exact-pair final-cleanup helper requiring two VERIFIED attempts,
original intent/generation and no pending/uncertain work; it cannot widen scope.

## 2026-10-19 — Live restoration verified; independent confirmation checkpoint

Kept normal baseline300s, cycle cooldown>=60s and per-pair backoff300s unchanged.
At10:14:18Z the read-only hold became awaiting_snapshot, not an immediate new ADD.
Next complete read started10:17:53.031Z and completed10:18:00.162Z, snapshot
`ad3551d7-5b0f-41d1-b56d-1d8b63f0d916`. Discovery admitted exactly one new attempt
`4a175cb2-513c-5351-a3e1-875c35011524`, job
`37e3106e-ac84-446f-a312-6ec953d184a8`, at10:18:00.170Z. Original intent
`54097200-c6d6-4408-8740-da3e00da594d`, generation1, authorization request and
revision2 were retained; separate system delegation/empty roles expires at
10:33:00.170Z. No deadline renewal, key reuse or one-time import.

The next eligible cycle started the ADD at10:19:09.237Z and completed
**VERIFIED** at10:19:16.627Z on management, distinct occurrence
`fd8a7b09-f06b-46a2-87f4-508e0d73c0e6`. Final complete snapshot succeeded at
10:19:18Z without error. Exactly two attempts remain VERIFIED; no third attempt,
unrelated job or uncertainty. This is agent-verified restoration after the
operator's confirmed external disappearance, not physical-reboot/traffic proof.

Prepared (NOT submitted) exact device cleanup with original key
`4e11c548-34e0-461d-8a2b-ca7a22247169`, original intent/generation, managed revision2,
TTL900s and digest
`d5e44cab5fd84a4d4497ea67cc95c0d47c3660bfbd3136e74d32458c21d137b6`.
Frozen body is private0600 `cleanup-request.json` beside prior artifacts; retain
this key/body on continuation, never silently regenerate it. Preparation required
both VERIFIED attempts and no pending/uncertain work and did not retire policy,
create a handoff or enqueue REMOVE.

Stopped API/Web gracefully again to avoid unattended execution while waiting
for independent Basic `show shun 198.51.100.252`. Verified both exited, no executor
owner/lease, no QUEUED/RUNNING/FAILED/UNVERIFIED jobs, exactly two VERIFIED
management attempts and zero cleanup handoffs. Agent remains running, Web is
deliberately unavailable, experimental config/profile remain set. Original
activation deadline11:09Z still applies; check it before continuation. Final
independent presence, cleanup, no-readd cycles/restart/replay and desired
suspension/restored gates are pending, not claimed complete.

Read-only integrity checks confirmed five unrelated tables exactly equal to the
pre-activation backup: protected_ips, protected_policy, manual_import_batches,
shun_import_origins and devices. Seven managed tables only; FK check clean;
private artifact modes0600 and directory0700 unchanged after socket-init failure.
Repeated all seven synthetic lifecycle cases (4.48s), then full validation:
**980 passed in46.71s**, compileall/Ruff/diff clean. The first sandboxed focused
test process stalled on local IPC and was terminated without touching services;
the normal-permission rerun passed. No production source change was made.

## 2026-10-19 — Independent restoration, verified cleanup and replay/restart checks

Operator Basic-session output independently confirmed restored management `.252`.
At10:22:27Z the original11:09Z window was still valid; restarted the same API/Web
with `up -d --no-deps`, leaving agent unchanged. Submitted previously frozen
cleanup key `4e11c548-34e0-461d-8a2b-ca7a22247169` without regenerating/rebasing.
Response202 accepted/replayedfalse/waitingfalse; the transaction retired the
original generation at10:22:43.999Z, revision3, and queued REMOVE job
`f4c11dbf-cd41-4d76-ae9b-4ceb462b026a`. No separate policy-write loop or direct
agent mutation was used.

REMOVE started10:23:54.189Z and completed **VERIFIED** at10:24:05.666Z. Complete
final snapshot at10:24:07Z confirmed absence without error. Operator supplied
independent Basic `show shun 198.51.100.252` returning only the prompt. Exactly
two VERIFIED ADD attempts remain and the fixture has exactly three VERIFIED
jobs (ADD, ADD, REMOVE), with no pending/uncertain work or unrelated mutation.

Replayed original standing UUID/body while its admission gate remained enabled:
200 policy_saved with historical revision1/changed_targets1/replayedtrue. Actual
policy stayed disabled at revision3 with the original retirement timestamp; no
new grant, generation, attempt or queue entry. Retained replay response privately.
Restarted API/Web after removal with controller gates still on: first complete
post-restart snapshot at10:25:17Z confirmed absence, stopped policy and exactly
two attempts. Two scheduled baseline cycles and final offline suspension/
ordinary resume/configuration closure are still pending at this checkpoint.

## 2026-10-19 — Root-only socket/state initialization fix (validated, rollout pending)

Removed recursive chown from the one-shot socket-init command: it initializes
only /web, /api, /state and the existing agent root/mode sequence. It never
traverses private backups, existing database files or child symlinks. Preserved
CHOWN-only capability, network none, read-only filesystem and no-new-privileges;
did not add DAC_OVERRIDE or relax permissions. Added a static command/sandbox
contract regression, and deployment instructions for restored-file ownership,
existing-volume service-only updates, initializer recreation and rollback caveat.

Disposable Docker regression used ONLY its newly created synthetic volume:
reproduced old Permission denied on a0700 child directory, then ran the new
command twice successfully and verified0600 backup content,0700 directory,
unchanged child ownership and retained symlink. An initial fixture-provisioning
run used the API image's non-root default UID and failed before initializer
testing; corrected only synthetic provisioning to root+CHOWN. Both disposable
volumes were removed; only synthetic data was deleted, no lab artifact touched.
Compose config --quiet passes using copies of the tracked Compose and .env.example
under private temporary /tmp configuration, never actual credentials. Focused
unit/Ruff/diff pass; full regression is running. No actual lab initializer
replacement yet; API/Web no-readd baseline observation continues unchanged.

## 2026-10-19 — First scheduled no-readd baseline and final-source validation

First scheduled post-restart baseline completed at10:30:26Z. Recorded private
`baseline-1.json` at10:30:45.391Z after full SQLite integrity/FK checks: fixture
absent, original intent generation1 retired, exactly two VERIFIED attempts and
three VERIFIED fixture jobs, no pending/FAILED/UNVERIFIED work. Total retained
queue11 VERIFIED/1 NOOP. Controller/ADD capabilities still on, so this checks
retirement itself rather than a global gate hiding an active policy. Entire
pre-test audit remains unchanged and retained; five unrelated policy/import/
device tables equal the initial backup. Next normal baseline due10:35:26Z.
Preserved another private host artifact copy under
`.local/backups/managed-lifecycle-20261019T1030/` (directory0700/files0600).

Initializer fix final-source validation: **981 Python tests passed in47.85s**,
compileall/Ruff/diff clean. Architecture now explicitly requires root-only volume
ownership preparation and reviewed offline restoration of child ownership, no
recursive startup repair or privilege broadening. Current lab initializer still
awaits replacement after the active lifecycle observation window; no API/agent
binary rebuild or dependency change is needed for the Compose-only fix.

## 2026-10-19 — Stable baseline observation and preserved initializer regression

An additional complete read at10:33:38Z again confirmed absence and moved the
next baseline from10:35:26Z to10:38:38Z. Did not count an expired old deadline as
a completed scheduled cycle. Stopped only Web to prevent browser refresh hints
from repeatedly moving the baseline; API and normal monitoring continue, with
two retained attempts and zero pending/uncertain work. Added this practical
observation procedure to the runbook. No polling interval or device state changed.

Verified Caddy HTTPS with normal certificate validation and no identity headers:
302 authentication redirect. All337 local documentation links resolve. The
initializer's temporary regression volume has been deleted (synthetic fixtures
only); actual checked SQLite/receipt artifacts remain on-volume and in private
host copies. Final ordinary monitoring/Web restoration follows the second real
scheduled baseline, not a fabricated or accelerated observation.

## 2026-10-19 — Managed lab lifecycle completed, disabled-mode closure and initializer rollout

Second actual scheduled baseline completed10:38:47Z; retained private
`baseline-2.json` at10:38:50.221Z verifies no re-add with controller/ADD gates
still enabled, original policy retired and exactly two attempts/three fixture
jobs VERIFIED. Prior audit remains unchanged; five unrelated tables match the
pre-test backup; no pending/uncertain work. Independent Basic final absence was
already supplied by the operator. This completes required no-readd observation,
including API/Web restart and original-key non-reenable, without accelerated
timers or a replacement grant.

Stopped API/Web/agent and confirmed all exited before offline closure. Checked
`suspend` then reviewed `resume-mutations` each created a new0600 backup:
`before-final-suspend.sqlite3` and `before-final-ordinary-resume.sqlite3` in the
existing private lifecycle directory. Both controls committed; zero queued,
running, waiting or active-request cancellation was required. Desired restoration
is suspended, ordinary mutation handling resumed, evidence/retired intent intact.
Removed only the temporary seven .env keys (returning to original absent/default-
off values) and the device1 addition_profile. Cycle/large-read mode unchanged.

With services stopped, recreated the validated socket-init from the root-only
Compose command: exited0 on the actual lab volumes. Private directory0700,
artifact0600/UID10001 remained unchanged. No recursive chown, extra capability,
data migration or backup restore. Recreated API/Web/agent using the same retained
image IDs and original disabled configuration; Caddy/Authelia unchanged.

Final normal snapshot succeeded10:41:03Z without error. Private `closed.json`
at10:41:21.647Z verifies all six API experimental gates false, no addition profiles,
socket mode/development-auth false, desired suspensiontrue, ordinary pausefalse,
fixture absent, retired generation1, two VERIFIED attempts, three VERIFIED
fixture jobs, total queue11 VERIFIED/1 NOOP and no pending/FAILED/UNVERIFIED work.
Agent ADD environment is again absent/default-off; its cycle mode remains true.
All seven optional tables remain; no closure ledger initialized. TLS-verified
HTTPS returns normal302 authentication redirect. Window closed well before11:09Z;
the one-fixture authorization is now consumed and must not be reused.

Created full integrity/FK-checked exclusive0600 post-test SQLite-API backup:
`/var/lib/ftd-shun-manager/managed-lifecycle-20261019T1003/after-closure.sqlite3`.
SHA-256 `38dbde59910d55c78350fae8157166445a1a78320f97e087d8bfdbbad861cfb4`;
matching ignored host copy plus all original reviews/receipts/maintenance backups
under `.local/backups/managed-lifecycle-20261019-final/` (directory0700/files0600).
No pre-test database replaced live evidence and no table/history was dropped.

Updated status/runbook/working agreement/maintenance/restoration manuals and
delivery order to distinguish completed one-device SSH lifecycle from remaining
ordinary/fleet uncertainty resolution, safe unrelated-policy resume, bulk/load,
traffic, actual reboot and production acceptance. The deployment initializer
fix has981 passing tests (47.85s), compileall/Ruff/diff, disposable-volume
reproduction and sanitized Compose validation; no Rust/protocol/binary change.
No further operator CLI commands are required for this completed experiment.

## 2026-10-19 — Exact-case read-only inspection with complete fleet pagination

Added offline `attention-case --case-id kind:UUID` alongside the existing
attention catalog. Shared schema/capacity/metadata validation and fingerprinting
remain read-only and caller-transaction-bound. The command supports retained
ordinary UNVERIFIED operations, FAILED/UNVERIFIED restoration attempts and
single/fleet ATTENTION cleanup; it never creates optional tables or a database.

Fleet detail validates the entire original scope and matching barrier count
before exposing any page. Returns up to100 targets in device-ID order with
reviewed metadata separate from current context. Missing current inventory or
policy does not reduce original membership. Original intent/generation, outcomes,
predecessor semantics and missing/pruned job evidence remain explicit. No raw
CLI/error/comment/credential or full admission payload is exported. Malformed
scope stays honestly inconsistent in the catalog and refuses detailed pages.

Detail pagination hashes a versioned domain, exact case ID and retained-state
snapshot. Other-case/catalog digests, context changes, invalid IDs, missing cases
and out-of-range pages refuse rather than silently rebasing. The digest grants
no write authority. No audit, backup, policy retirement, latch change, retry,
queue insertion, feature gate, RPC or HTTP route was added. Original restoration
abandonment and all no-rearm/resume guards are unchanged.

Validation:26 new disposable-SQLite regressions cover all four case kinds,
205-target complete paging, original/current metadata and missing devices,
cross-case/catalog digest separation, changed observation, invalid last-page
target/count, strict IDs/pages, missing cases/files, partial schema, read-only
transaction/zero changes and CLI argument separation. Full suite1007 passed in
47.35s; compileall/Ruff/module CLI help/git diff checks pass. Package wheel build
was not run: local build/hatchling packages are absent; source/module CLI and
existing entrypoint routing were tested. No lab DB access or service deployment
was needed; existing lab stack and disabled gates were not changed.

Updated normative attention boundary, operator manual/index, plan and status.
Remaining: executable ordinary/fleet incident decisions and safe unrelated-policy
resume with immutable outcomes/whole-scope authority. Complete read-only scope
inspection is a prerequisite, not uncertainty resolution or production acceptance.

## 2026-10-19 — Reviewed offline resume of unrelated standing policy

Added an explicit architecture amendment and separate `review-resume-unrelated`
/ `resume-unrelated-policy` actions. Normal policy resume retains its global
failure refusal. The new action requires an already initialized exact closure
ledger and validates every immutable abandonment request/evidence/receipt against
the original attempt, retained job/delegation and current retired policy.
Each FAILED/UNVERIFIED attempt needs its own decision, including multiple attempts
on one pair. Missing/changed/re-enabled retired targets refuse; pruned terminal
jobs/delegations remain explicitly missing, never recreated or verified. Changed
or independently linked system requests cannot borrow a closure's exclusion.

No other UNVERIFIED operation, pending queue/restoration, lease, waiting/ATTENTION
single/fleet cleanup or transitional fleet root is exempted. All existing healthy
target/standing-authority/device/protection/time prerequisites remain. The new
action binds its five-minute confirmation to complete managed context, exact
case/job/link/delegation/cache state and isolation summaries. Cross-action/stale
reviews refuse without rebase. No operator-supplied exception list, rearm, HTTP
route, schema initialization, new desired authority or device command exists.

Reused checked exclusive SQLite backups and savepoint-protected control/audit.
Only desired suspension and enabled targets' fresh-read revision/barrier change.
Retired policies, consent, closure receipts, attempts, queue contents and original
FAILED/UNVERIFIED results remain unchanged. Distinct audit includes the isolated
incident count and summary digest, review/state digest and trusted-host actor;
it makes no claim of device success. Existing default-off discovery/dispatch and
pair-wide abandonment/latch checks remain in effect after a reviewed restart.

41 new disposable-state tests exercise successful FAILED/UNVERIFIED isolation,
read-only preparation, old-command refusal, retained/pruned jobs/delegations,
default-off/fresh-snapshot behavior, no rearm/original-key replay, extra attempts,
ordinary/fleet blockers, contradictory closures, extra request links, changed
context/delegations, stale/future/late expiry, caught audit rollback and the real
CLI checked backup. Initial tests exposed the actual trusted-policy delegation
link (not a user request): validation now checks its exact source/actor/empty
roles/payload/timing/link binding while refusing additional delegation, rather
than incorrectly rejecting every valid system job.

Final validation: all **1048 Python tests pass** in52.14s, including41 new cases;
compileall, Ruff, module CLI help and git diff checks pass. No Rust, protocol,
Compose or browser asset change in this increment; those build/rollout paths
were not invoked.

Updated architecture, working agreement, operator manual/index, abandonment/
attention/restoration/maintenance procedures, plan and status. No live DB access,
deployment/restart, closure migration, profile/gate enablement or FTD operation
was performed; this offline source increment does not require service rollout.
Existing consumed lab fixture authority is unchanged. Ordinary/fleet incident
closure and live recovery/bulk/load/reboot/production acceptance remain pending.

## 2026-10-19 — Preserve unresolved queue evidence and expose fleet predecessors

While preparing ordinary/fleet incident handling, found that daily completed-job
retention could delete UNVERIFIED work and captured ADD predecessors after cleanup
entered ATTENTION. This lost diagnostic/request evidence and could remove an
ordinary uncertainty blocker merely through age. Queue pruning now retains those
jobs and linked requests/batches; predecessor holds cover WAITING_ADD, ADMITTING
and ATTENTION. UNVERIFIED retention is independent of barrier expiry/cancellation
or restoration abandonment. Existing complete-read REMOVE reconciliation remains
RECONCILED_ABSENT, not VERIFIED, and follows ordinary retention once not held.

Pruning acquires one write transaction before optional-state reads, validates
canonical bounded unique fleet predecessor references, and refuses malformed held
references before deleting queue rows. Irrelevant terminal barrier JSON is not
evaluated. Queue deletion, orphan cleanup and purge audit roll back together;
separate event/inactive-state retention is not part of this transaction.

Offline fleet detail validates all references against the complete original scope
before paging. Per-target predecessor evidence exposes the original ADD role,
outcome and request count separately from REMOVE/ATTENTION. Missing, uncaptured
and inconsistent jobs remain explicit. Catalog reports reference inconsistency
without erasing a valid original fleet scope; changed predecessor outcomes invalidate
detail snapshots. No writes, fabricated verification, retry or device command.
History and detail pages explain why unresolved evidence can exceed retention.

29 new disposable-state regressions cover 367-day ADD/REMOVE evidence/link/batch
retention, old-key replay, real absence reconciliation, atomic audit rollback,
single/fleet ATTENTION with NOOP/FAILED/UNVERIFIED predecessors, expired barriers,
five original ADD states, missing/wrong-action evidence, malformed references and
changed digests. Updated older tests that expected UNVERIFIED jobs to disappear:
retained original keys now reject reuse at the existing idempotency guard, while
FAILED history can still expire and its independent restoration latch remains.
Full Python suite **1077 passed in53.62s**; **27 Chromium tests passed** in110.36s,
including the retention notice. Compileall/Ruff/git diff checks pass. No Rust or
protocol changes, and no new Compose changes in this increment.

Authorized lab deployment rebuilt/recreated API/Web only. Retained rollback tags
`ftd-shun-api:rollback-retention-evidence-20261019T1137` and
`ftd-shun-web:rollback-retention-evidence-20261019T1137`. Checked online SQLite
backup (quick_check ok, no FK violations), private0700 directory/0600 file:
`/var/lib/ftd-shun-manager/retention-evidence-20261019T1137/before-update.sqlite3`,
SHA-256 `3966fe4d3fa950eb72aa69003568e783b321a80e739112c780bf4a05cc5501a4`.
New API image `f9a4e1500f9e022b3d876b3a7c59ca85b9c8d261aebd6149371485b5d148437e`;
Web `04f4e4bbe0a9d1dd364f6324fe7c0a8abf2e902557f144d5440dd8a5a791594c`.
Agent unchanged at `72b045e182081c6f2d3c3a7d546a92402dd224179c0891ff7b50c9e85a71df41`.

Post-deployment API ready/socket, successful normal read `2026-10-19T11:41:58Z`,
no error; TLS-auth redirect302 and only loopback443 published. New pruning source
and both retention notices verified in running images. SQLite quick_check/FKs
pass; queue unchanged11 VERIFIED/1 NOOP, zero pending; registry4/suspended,
enabled targets0, seven optional tables/no closure ledger. Six experimental API
gates and development auth remain false, addition profiles0. Initial read-only
queue check used a nonexistent `status` column; corrected to `state` and repeated
successfully without changing data. No new fixture, grant, mutation, migration,
offline resume/closure invocation or agent restart. Previously source-only offline
inspection/resume modules are packaged but not activated.

Updated architecture, working agreement, retention/attention/cleanup/restoration/
unrelated-resume manuals, plan and status. Rollback needs paired images and current
evidence review: older code does not honor these new retention holds. Do not restore
the backup over current state or start an old pruner to undo this fix. Follow offline
recovery before any approved rollback; backups do not authorize request replay.
There is no schema migration. Already-pruned historical evidence stays missing;
unresolved records can increase storage. Executable ordinary/fleet incident closure,
bounded archival and separately approved load/recovery/production acceptance remain
pending. Evidence preservation is a prerequisite, not incident resolution.

## 2026-10-20 — Reviewed administrative acknowledgment of unresolved incidents

Added a normative amendment and the separate `ftd-shun-incident-maintenance`
entrypoint/module with review-enable/enable/review/acknowledge actions.
ACKNOWLEDGE_UNRESOLVED records trusted-host operator review/reason for a retained
ordinary UNVERIFIED operation or single/fleet ATTENTION cleanup. It preserves
all outcomes, policy, work, reservations, evidence holds and resume blockers.
Restoration abandonment remains separate. This delivers an administrative
decision record, not device uncertainty resolution or a new isolation exception.

The optional `incident_acknowledgements` table has exact recognized DDL,
immutable update/delete guards, one receipt per case and a10000-row capacity.
No startup/GET/Store/queue/managed initializer creates it. Ordinary-only databases
can use it without managed policy initialization. Explicit offline migration and
decision confirmation require both existing pauses, settled RPCs/no lease or
pending work, checked exclusive SQLite backups and five-minute frozen reviews.
The decision binds original UUID, maintenance actor/reason, complete schema/
queue/request/link/observation/protection/managed context and all fleet evidence.
Typed exact IP/count rejects partial scopes. Full paginated fleet inspection is
gathered within one transaction, retaining missing current members and separate
captured ADD outcomes. Missing historical jobs remain explicit; inconsistent or
unfinished related evidence refuses. Output excludes raw errors/CLI, credentials,
comments and full admission payloads.

One transaction stores minimal sanitized evidence/request/receipt and
INCIDENT_ACKNOWLEDGED audit with a maintenance actor and empty roles. Late expiry
and audit failure roll back even when an outer caller catches the exception.
Exact original-key replay returns its historical receipt after expiry or later
REMOVE absence reconciliation. Different inputs or second-case keys refuse.
Acknowledgment keys are reserved through existing queue/policy/restoration/
cleanup guards and restoration-abandonment admission. Offline recovery validates
the optional ledger instead of ignoring malformed state. Attention inspection
shows acknowledgment separately, with current-case and retained-receipt counts,
and retains original case counts and resolution-unavailable semantics.

36 new disposable-state tests cover read-only/no-startup migration, ADD/REMOVE
uncertainty, single/fleet predecessor separation, full205-target scope including
missing inventory, state/actor/reason/typed-scope/digest changes, quiescence,
expiry and late rollback, original-key concurrency/replay, checked CLI backups,
immutable/malformed ledger retention, key isolation, normal absence reconciliation
and unchanged resume blockers. Initial local test iterations corrected the
in-memory schema contract's explicit transaction and test assumptions about
immutable fleet references/recovery/key-guard ordering. Full suite **1113 passed
in56.27s**; compileall, Ruff, module help and diff checks pass. No browser asset,
Rust, wire protocol or Compose edits; browser/agent builds were not repeated.

Authorized lab update rebuilt/recreated API/Web only. Preflight had12 VERIFIED/
1 NOOP and no pending work, registry4/suspended, enabled targets0, seven optional
managed tables, no closure/acknowledgment ledger, six experimental gates and
development auth false, addition profiles0. No gates/profiles were changed.
Retained rollback tags `ftd-shun-api:rollback-incident-ack-20261020T0847` and
`ftd-shun-web:rollback-incident-ack-20261020T0847`. Checked private0700/0600 online
SQLite backup:
`/var/lib/ftd-shun-manager/incident-ack-20261020T0847/before-update.sqlite3`,
SHA-256 `0af3db6249723bee4b9037387e05aaa34374648de3b7ecfda10d3342bb373075`.
New API image `79ac6fbc4021c12de5ac2056e62043dd4b931a7331bc04beb6fdac1ba77018cc`,
Web `ab4ed354a9d8c66ccd57b3458f7793006c279d7281518ec097a18cefa156bed1`;
agent unchanged `72b045e182081c6f2d3c3a7d546a92402dd224179c0891ff7b50c9e85a71df41`.

Post-update API ready/socket, normal successful read `2026-10-20T08:48:40Z`, no
error and valid-TLS authentication redirect302. Queue unchanged12 VERIFIED/1 NOOP;
queue/request/link/protection/managed/import records match the checked backup
exactly. SQLite quick_check ok/no FK errors. Optional schema remains seven tables,
no acknowledgment ledger, enabled targets0 and desired suspension retained.
Experimental gates/development auth remain false. Running API imports the new
module without creating its ledger. No migration, acknowledgment, resume, grant,
new device fixture/mutation or agent restart was performed. Existing consumed
fixture authority remains consumed.

Updated working agreement, architecture, README, structured acknowledgment manual/
index, attention/development procedures, plan and status. Retain paired matching
images and backup for rollback; older code ignores acknowledgment keys/receipts.
If a ledger is later initialized, downgrade needs a separately reviewed offline
plan. Do not drop decisions/triggers or restore old enabled policy to revert code.
Unresolved evidence/receipts may outlive event retention and increase storage;
no archive/recycling or ordinary/fleet resolution is implemented. Whole-scope
uncertainty/isolation decisions, Web handling and separately approved recovery/
load/traffic/physical-reboot/production acceptance remain pending.

## 2026-10-20 — Whole-scope isolation and reviewed healthy-policy resume

Added a normative amendment and explicit offline ISOLATE_INCIDENT after a separate
administrative acknowledgment. Optional `incident_isolations` receipts and indexed
`incident_isolation_targets` have exact DDL, immutable guards, count/orphan checks
and10000 receipt/total-target bounds. Separate review-enable-isolation/
enable-isolation actions never initialize managed policy. Startup/GET/Store/queue/
acknowledgment/managed migration never create these tables. All live optional
ledgers remain absent and all experimental gates remain off.

One five-minute original-UUID/actor/reason/IP/count review freezes the whole
original case scope, every captured ADD, original acknowledgment, current policy,
jobs/links and complete retained context. Apply atomically retires current enabled
standing targets and adds pair latches/evidence/receipt/audit. Already retired
dates, absent policy, original outcomes, consent, queue and ATTENTION stay intact.
No per-member transaction or smaller fleet inference. Original-key replay remains
historical after expiry; changed inputs cannot replace a decision. Keys cannot
acquire queue/policy/cleanup/restoration/acknowledgment/abandonment authority.

Manual ADD/REMOVE, combined cleanup, MAINTAIN and restoration check pair exclusion;
fleet ordinary removal also checks isolated members absent from observed scope.
Claims cancel restored/older queued manual work before dispatch. Protected-policy
removal retains independent authority and priority. Policy-only retirement and
monitoring remain available. No release/rearm or HTTP action was introduced.
Attention shows separate isolation status and target exclusion without hiding
the original case or inventing a verified outcome. Queue retention now also holds
original isolation jobs/requests, including a later RECONCILED_ABSENT REMOVE;
bounded retained job references are validated before purge.

Distinct `review-resume-isolated` / `resume-isolated-policy` requires all original
isolation receipts/latches/scopes, acknowledgments, exact retired/absent policy
and retained jobs/links to agree. Every ordinary UNVERIFIED case needs its own
decision; a fleet receipt cannot exempt its separately listed uncertain ADD.
Every failed/uncertain restoration still needs its own valid abandonment. Existing
normal/restoration-only unrelated resume stay strict. Resume changes only desired
suspension and enabled healthy targets' fresh-read barrier, with atomic distinct
audit and original authority/outcomes preserved. Protected/device/time/lease/
pending-work/standing-authority checks remain. No job, wake, gate or new grant.

29 new disposable-state tests cover ordinary ADD/REMOVE and single/fleet cleanup,
205-member scope/missing devices, exact retirement/rearm refusal, healthy resume,
independent uncertain predecessor cases, changed policy/job/link/latches,
protected-removal priority, manual claim revalidation, stale/typed/expiry conflicts,
concurrent original-key replay, checked CLI migration, normal absence reconciliation
with retention and audit/late-expiry rollback even under an outer commit. Early
test iterations corrected synthetic policy CHECK invariants and recovery cooldown
clock assumptions. Full suite **1142 passed in58.42s**; prior1140-case run passed
in56.16s before adding single-cleanup/migration-rollback acceptance. Compileall,
Ruff, both CLI help routes and diff checks pass. No Rust/protocol/browser asset or
Compose edits; those unchanged build/test paths were not repeated.

Authorized lab rollout rebuilt/recreated API/Web only. Preflight confirmed12
VERIFIED/1 NOOP, no pending work, registry4/suspended, enabled targets0, seven
optional tables and no closure/incident ledger. All six experimental gates and
development auth false, addition profiles0. Retained paired rollback tags
`ftd-shun-api:rollback-incident-isolation-20261020T0905` and
`ftd-shun-web:rollback-incident-isolation-20261020T0905`.
Checked private0700/0600 online SQLite backup:
`/var/lib/ftd-shun-manager/incident-isolation-20261020T0905/before-update.sqlite3`,
SHA-256 `4014ef38f1e3ab8d222c00f84796d34de73206c65fd95f50a2894d015f37d886`.
New API image `80808a4b57a5b0bea42707bdeb64d4ed5aabc354da42dc805ea504c899e369ae`,
Web `2f264f75a4df65f1e82b8295b23d50130839747a40d43a2d629ec7d1dc20ff24`;
agent unchanged `72b045e182081c6f2d3c3a7d546a92402dd224179c0891ff7b50c9e85a71df41`.

Post-update API ready/socket, normal successful read `2026-10-20T09:06:48Z`, no
error and valid-TLS auth redirect302. SQLite quick_check/FKs pass and all queue,
request/link, protection, managed policy/attempt/cleanup and import records match
the checked backup exactly. Queue remains12 VERIFIED/1 NOOP, registry4/suspended,
enabled targets0, seven optional tables, no new ledger. All experimental gates/
development auth remain false. Running API imports isolation support without DDL.
No migration, isolation/resume, new grant/fixture/device mutation or agent restart.
Previous one-address test authority stays consumed. No production acceptance claim.

Updated architecture, working agreement, README, structured isolation manual/index,
acknowledgment/attention/unrelated-resume/managed-maintenance/queue/development
procedures, plan and status. Older writers ignore pair latches; after any approved
activation, downgrade requires a separately reviewed offline plan and matching
images/evidence. Never drop latches/receipts or restore old enabled policy to undo
code. Existing restoration abandonment still refuses overlapping ATTENTION cleanup,
so a combined failed-restoration/cleanup case remains blocked; a separate whole-
scope decision is still needed. No partial exception was added. Remaining: that
composite incident path, bounded archive, Web handling, release/rearm design and
separately approved live recovery/fleet/load/traffic/reboot/production acceptance.

## 2026-10-20 — Operator product alignment and working-version delivery reset

Recorded the sequential question/answer discussion in
`docs/working-version-plan.md`, with a normative architecture amendment and
source-of-truth/priority guidance in AGENTS. The operator wants a usable working
version with incremental UX improvements. This is documentation-only alignment;
existing runtime code, feature gates, profiles, credential delivery and lab state
are unchanged. Older implementation checkpoints and operating contracts remain
historical/current-version evidence, not proof that the revised target shipped.

Agreed core: all service additions become maintained device/IP policy, explicit
adoption of already-present unmanaged shuns,10000-IP import with device selection,
visible invalid/active-whitelist skips and reports, durable bounded dispatch and
cancellation that retains completed/adopted targets. Active whitelist protection
permanently retires matching maintenance and removes shuns; disabling protection
never resurrects that old policy. Exact IPv4 only. Selected mass removal and
offering restoration of disappeared unmanaged observations are deferred.

Inventory remains file-based with a path in .env and stable IDs across address
changes. Per-device explicit SSH login/secret replaces a shared fallback, keeping
credential loading agent-owned. Planning target10 FTDs/default4 configurable
concurrent devices, one serialized stream per device. Dispatch continues between
polls; interactive refresh and unblock/removal/Purge take the next appropriate
slot after the current operation and verification. Refresh remains submit-able
with visible pending/countdown badges; detailed state stays in pop-up panels.

Automatic recovery should reconcile fresh verified device evidence against
current intent after proving the prior RPC/session has settled. Preserve original
uncertainty/audit and design compatibility for existing retained latches/receipts;
do not blindly replay or label an unknown write verified. Conflicting concurrent
user actions require current-state review/reconfirmation. Emergency Purge is
explicitly confirmed and audited for every authenticated user, cancels current
imports, retires/removes managed scope and preserves whitelist/unmanaged state.
The operator did not approve a permanent global intake lock; precise new-import
behavior during outstanding Purge belongs to its concurrency contract.

Separate Managed/Unmanaged views; highlight unmanaged sightings on at least two
distinct device IDs in a rolling24-hour window, including disappeared entries,
with a direct selected-device Managed action. Preserve counts, hostnames/times
and the distinction between historical sightings and current presence.

Email is lower priority. Recorded SMTP relay/auth optional/plaintext/STARTTLS/
implicit-TLS/internal-CA configuration, .env sender/recipients/timing, secret-backed
password, test/status UI and asynchronous delivery. Ordinary events aggregate
with time-based10/20/40-minute increasing pauses toward a configurable cap,
one-hour quiet reset, conditional next-notification timing and cross-device
emphasis. Active-whitelist detections are urgent; notify first unblock attempt
and later state changes, not every identical retry. Whitelist additions identify
the actor. Concrete mail dispatch/outbox/network/retry design remains deferred.

Updated README, project status, development plan/order and manual index, with
explicit target/current-code notices in queue/import/protection manuals. The new
plan lists the exact mismatches to resolve: shared credentials,1000-pair bounds,
adoption rejection, whole-input rejection, global cooldown/serialized fleet,
protection-resumed policy and routine mandatory offline uncertainty handling.
Future implementation must supply reviewed concurrency, capacity, fresh-evidence
reconciliation, migration/rollback and Purge contracts while preserving unchanged
typed-command/verification/authentication/credential security invariants.

Validation: checked 187 local Markdown link targets/anchors across 10 documents,
reviewed target-versus-implemented wording and ran git diff --check. No Python,
Rust, browser, Compose, schema or runtime files changed; their test suites were
not rerun. The prior 1142-test result remains historical, not a new validation run.
No deployment/restart, environment/secret read or edit, live DB access, migration,
feature activation, device mutation or fixture reuse. Existing scoped lab
authorization rules and consumed experiment permissions remain intact.

## 2026-10-21 — Per-device credential foundation and compatible lab rollout

Implemented the first working-version infrastructure increment rather than
another offline incident feature. Explicit shared compatibility and opt-in
per-device modes now select agent-owned ID/login/password-secret references.
Strict mapping covers every configured stable ID, including disabled devices,
and rejects duplicate/unknown/missing/zero IDs, unknown/duplicate JSON fields,
unsafe login/basename values and >256 KiB input. References are distinct per
device under `/run/secrets/ftd`; values never belong in JSON/public inventory.
Per-device mode ignores shared settings, with no fallback after lookup/read/auth
failure. Legacy read/removal and cycles v1/v2/v3 share one authentication helper.

Secret reads preserve exact UTF-8 bytes, are bounded to 16 KiB, nonblocking and
regular-file-only, rejecting empty/final-symlink/directory/FIFO input. Source
buffers remain zeroized after authentication; files stay mounted for reconnects,
without a claim that SSH library/kernel copies never exist. `--check-config`
validates configuration/all secret files then exits with only mode/device count,
never SSH/socket binding/database access. Unsupported CLI arguments fail closed.
No protocol, credential-lifetime, policy authority or feature-gate redesign.

Public inventory rejects private/unknown/duplicate fields, boolean/zero IDs,
coerced enabled values, whitespace-only names and empty scope; agent also rejects
zero IDs/duplicate hostnames. SQLite regression proves same-ID IPv4 replacement
preserves observations/history. Both Compose consumers use the `.env`-configured
public host path. New opt-in overlay gives only agent read-only mapping/secrets,
removes legacy secret and refuses absent bind sources; requires Compose 2.24.4+.
Real mapping joins Git/build exclusions. Structured manual covers ACL/provisioning,
exact-byte rotation, non-network preflight, private config backup and matching
image/Compose rollback; an older agent must not use the new overlay. Base Compose
stays shared. Updated architecture, README, plans, manual index/deployment/
development and status. DNS/ports, bulk-policy capacity/adoption/exclusions,
permanent protection retirement and parallel dispatch remain next.

Validation: compileall, **1158 Python tests (55.82s)**, locked release build,
**43 Rust unit + 4 integration tests**, fmt, Ruff, all-target Clippy with warnings
denied and diff checks. Existing test-only unwraps prevented all-target lint;
replaced with propagated errors/context without weakening assertions. Initial
sandbox Rust socket tests hit EPERM; rerun with local socket permissions passed,
no skips. Python suite likewise uses synthetic temporary state/local sockets.
No browser assets changed; Chromium not rerun. Tests cover ID ordering/scope,
strict JSON/bounds, no fallback, unsafe references, missing/empty/oversized/
invalid-UTF8/symlink secrets, exact whitespace and preflight without listener.
Python adds inventory identity/type/private-field and SQLite/build-boundary checks.

Temporary non-secret Compose validation checked both modes, matching public paths,
agent-only read-only binds and legacy-secret removal. A disposable non-root,
read-only/no-network agent container passed per-device preflight for two synthetic
devices (one disabled), despite deliberately invalid shared settings. New image
also passed unchanged lab shared preflight, reading but never printing passwords
or contacting FTD. No real inventory/credential/environment/profile/gate edits,
new mapping activation, optional-schema migration or policy admission.

Authorized API/agent-only deployment retained prior images as
`ftd-shun-api:rollback-per-device-credentials-20261021T0745` and
`ftd-shun-agent:rollback-per-device-credentials-20261021T0745`. API stopped before
agent replacement. Checked private 0700/0600 SQLite backup:
`/var/lib/ftd-shun-manager/per-device-credentials-20261021T0745/before-update.sqlite3`,
integrity/foreign-key checks pass, SHA256
`65e896851ca2106b360ce8509a2ae1faf5b965efc83b60249785f14b1936b572`.
New API `sha256:95f0812d19fa153365c3c525e6554e4a72c54f2b626e22cb97794b5a124d55a5`,
agent `sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`.
Web/Caddy/Authelia unchanged. API ready/socket, valid-TLS HTTPS 302; 12 queue/policy
tables match backup exactly, 12 VERIFIED/1 NOOP/no pending, registry 4/suspended,
enabled targets 0, seven retained managed tables/no incident ledgers. All six
experimental flags/development auth/agent ADD false; mode remains shared.

Pre-existing network failure is not called live-read acceptance: old agent last
confirmed 07:35:41Z then timed out at SSH connection/host-key stage; new agent
repeats that failure after restart. Host TCP/22 is reachable through `cscotun0`,
but a disposable credential-free TCP-only diagnostic in the agent network
namespace times out; no Docker-subnet overlap. This identifies differing network
paths, not a proven VPN/firewall/ACL root cause. No routing/firewall/ACL changes,
test device writes or consumed-fixture reuse. Fresh post-restart monitoring,
per-device live authentication and bulk/parallel/recovery/production acceptance
remain pending. Preserve honest stale-data/error presentation.

Final review validated 214 local Markdown links/anchors across 10 changed
documents and repeated Ruff/diff checks. The exact per-device Compose overlay
also passed isolated no-network preflight with two synthetic devices and no
legacy secret file; its four verified empty fixture volumes were removed.

## 2026-10-21 — Permanent whitelist retirement and recovered lab monitoring

The operator confirmed the earlier network interruption was their temporary VPN
use and restored access. Ordinary monitoring confirmed08:37:32Z and08:52:58Z
without errors; no routing/firewall/ACL/credential change was needed. Prior failure
evidence remains historical, not a current blocker. Continued working-version
delivery rather than more offline incident features.

Implemented the protection-lifecycle prerequisite for managed imports. Every
explicit enabled-protection save retires all matching enabled managed targets,
including missing observations/disabled devices, under the same write lock as
policy and claim validation. Preserve intent UUID/generation/original grant;
increment managed revision once; append per-device MANAGED_SHUN_RETIRED events
with real editor roles and the root policy event's request ID. This is fixed
protection revocation for every authenticated editor, not role promotion or a
MAINTAIN grant. It consumes no immutable managed-request slots, so a full ledger
cannot prevent retirement. Root JSON logs include retired/deferred counts, not
free-form text. Valid unstarted ADD/restoration cancels atomically; RUNNING ADD,
waiting/admitted cleanup, unknown outcomes and original incident receipts remain.

Disabling/deleting active protection never resumes old authority. Explicit saves
also finish legacy/deferred retirement before release. Unknown/partial optional
state still permits strengthening: preserve enabled protection as a durable
barrier, report unknown/deferred honestly, and refuse weakening until repaired
state can be retired atomically. Do not rewrite unverifiable queue evidence.
No new schema, optional migration, GET/startup sweep, policy adoption or fake
verified removal. Editing/deleting an already-disabled entry leaves separately
and newly authorized maintenance alone. Old original-key grant receipts stay
observational after protection release; new recurring consent is required.

Forms bind managed revision including Add, preserve dirty revisions and show
permanent-retirement consequences instead of a resume checkbox. Stale supplied
revisions conflict and nonempty retirement requires current reviewed revision.
The old strictly typed confirm_maintenance_resume field is compatibility only,
not resume authority. HTTP SQLite-save failures return503/unconfirmed with no
success or refresh hint. Actor/CSRF/sensitive-session boundaries are unchanged.

Recorded the bulk storage constraint in the working-version plan:1000-target/
canonical scope,10000 immutable requests with retirement reserve,10000 retained
attempts and full-snapshot readers must be revised together. Raising targets
alone can exhaust the revocation reserve before the first grant. Next flow needs
durable import roots/exact accepted exclusions/adoption, paged policy reads,
rolling bounded jobs/restart progress and explicit cancellation of unsent scope,
not100000 immediately queued/expiring user requests. Current bounds/gates stay
unchanged; no new bulk schema or lab load/migration is authorized by the note.

Validation:1167 Python tests pass (55.55s),27 Chromium tests pass; compileall,
Ruff and diff checks pass. Added scope/identity/Viewer audit/full-ledger revocation,
deferred corruption/repair/restart barriers, old-key non-reenable, independently
new policy on disabled entries and per-target/root/HTTP audit rollback cases.
Integrated lifecycle now proves release/restart does not restore old policy;
new explicit consent can authorize another generation. Existing fleet/control/
scope tests updated for automatic retirement and stale scope rejection, not
weakened to permit stale confirmations. Chromium checks original revision/input
retention, clear permanent consequences, no resume field, mobile layout and no
device hints. All fixtures are synthetic; agent/protocol/Compose unchanged this
increment. Initial non-escalated targeted tests encountered the known local
socket sandbox limitation; the complete permitted-socket suite has no skips.

Authorized API/Web-only rollout retained prior images as
`ftd-shun-api:rollback-protected-retirement-20261021T0855` and
`ftd-shun-web:rollback-protected-retirement-20261021T0855`. Checked private SQLite
backup `/var/lib/ftd-shun-manager/protected-retirement-20261021T0855/before-update.sqlite3`,
integrity/foreign-key checks pass, SHA256
`640140715118a8927567c766352855f01193609df6377c0ba06314279c26076a`.
API stopped before paired recreation. Current API image
`sha256:c3cf13f4e28c285bd4675e4eebf76756d910772c2e3de3021c2b01827562db0d`, Web
`sha256:555268b734137a6ad9b6f9ef6d8edd0a043d125650441c0bc8d9109785c82329`;
agent remains `sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`.
API ready/socket, fresh complete read08:55:15Z/no error and valid-TLS HTTPS302.
Twelve queue/policy tables match backup exactly,12 VERIFIED/1 NOOP/no pending,
registry4/suspended, enabled targets0, seven managed tables/no incident ledger.
All six experimental flags/development auth remain false. Agent/shared credentials,
device inventory/profiles, Caddy/Authelia and optional schemas unchanged. No live
grant, policy edit, test write, fixture reuse or startup retirement was performed.
Older writers retain legacy protection-resume semantics: rollback must not release
a deferred barrier or restore old enabled policy. Updated architecture, agreement,
manuals, README, plan and status accordingly.

Final hardening adds explicit RUNNING ADD settlement coverage: a verified write
after protection retirement remains VERIFIED evidence, but protection release
cannot restore its authority. Shared optional-state validation now requires the
full retirement/authorization column set so partial schemas remain unknown to
ordinary removal as well as the protection editor. Additional corruption case
confirms strengthening is still possible while weakening/ordinary removal fail
closed. Final complete suite: **1169 passed (55.91s)**;27 Chromium cases remain
passing with unchanged browser assets since that run. Compileall/Ruff/diff checks
pass;241 local links/anchors validated across14 documents. Paired final build was
recreated with the same checked original backup/rollback images retained; no
active work or enabled managed target existed at either rollout.

Final running images supersede the first paired build above: API
`sha256:e1b5cdd4384b80186843f81f3c2679753e6f62c186e721f539fa308de1fa87e9`, Web
`sha256:047d15d16d2c8d815b03078c2e899d27d21801a808037ff0f4d98d6785c8e6f3`.
Final read09:01:43Z/no error,12 queue/policy tables still match original backup,
TLS-verified HTTPS302; agent unchanged. Stopped the initial sandbox-constrained
targeted test process after the permitted full suite completed; no background
test/fixture or live work was left running by the checks.

## 2026-10-21 — Durable large-import preparation journal

Continued the agreed managed-import delivery order with isolated, non-authoritative
storage rather than changing only text/queue limits. `ImportPreparations` explicitly
initializes two tables/two immutability triggers, never normal Store/API startup,
HTTP, GET, worker or a new CLI. Exact optional schema inspection refuses partial/
modified state without repair. Existing managed-state inspection still rejects
unknown policy rather than treating it as unmanaged. No second policy registry,
new standing authority, queue job, import-origin, audit success, hint or SSH path.

Preparation parses the existing bounded input and freezes up to 10,000 rows across
ten explicit enabled device IDs/100,000 pairs in one transaction. Retains owner,
display name/captured roles, UTC creation/ten-minute expiry, managed/protection
revisions, device labels and normalized label/reason; generated source-line
diagnostics preserve duplicates/invalid/unsupported/ambiguous inputs without
persisting pasted text/comments/excerpts. Protected pairs are explicitly excluded,
already-maintained targets preserve original references, locally present unmanaged
targets propose adoption without fabricated creation provenance, and absent
targets propose ADD without an eligibility/verified-absence claim. Previous stopped
intent metadata stays observational. No actual maintenance changes or re-enabling.

Domain/version-bound canonical framing hashes header and the entire sorted pair
scope, not only the current page. Immutable targets/header, count checks and a
streamed 100-row full verification prevent a changed/missing member from becoming
a silently smaller scope. Integrity is not freshness, consent or bearer authority.
Owner lists recover references after restart/lost response; pages return at most
100 target and 100 generated-report rows. All results remain non-executable.
Current-state changes never silently rebase a saved preparation.

Capacity: four retained plans per owner/sixteen globally, 2 MiB maximum header,
100,000 pairs per plan, with serialized admission to these draft-only bounds.
Cancellation invalidates only the preparation and is idempotent; it cannot retire
policy or cancel separately admitted work. Explicit expiry pruning deletes only
expired preparation roots/children, not queue/policy/attempt/origin/audit evidence.
Expired/cancelled reports remain historical until pruning. Future confirmation
must create a distinct durable root/standing authority with a retained exact scope,
author/report and progress, independent of draft expiry; no job may depend on an
expiring preparation or renewed legacy request.

Validation: **1196 Python tests pass (61.30s)**, including 27 new journal cases;
targeted suite: 27 passed in 3.52s. Compileall/Ruff/diff checks pass. Maximum fixture
stores 10,000 IPv4s on ten devices/100,000 rows, reopens the database, checks first/
middle/last pages and streams full digest verification. Other cases cover owner
privacy, explicit/bounded device selection, all-invalid/empty reports, per-pair
classifications/provenance, source non-retention, immutable/corrupt/missing rows,
wrong digest, exact expiry/cancellation/pruning, schema/outer rollback, late-target
failure and concurrent quota admission. Independent SQLite state remains equal,
with no jobs, managed initialization/authority, origins or audit effects. Existing
API/socket regressions ran with permitted local sockets; no lab settings, secrets,
volumes or FTD connections were used. Rust/browser/Compose unchanged; their
separate suites were not rerun.

Updated normative architecture, README, working-version/development plans, status,
structured preparation/contributor manuals and manual index; validated 208 local
Markdown links/anchors across nine documents. No service deployment/
restart or live schema migration: the module is not runtime-connected, so replacing
images or seeding unused live tables would not deliver an active feature. All
credential/gate/profile and consumed-fixture boundaries remain. Next: compatible
paged policy/attempt capacity, atomic confirmed-import adoption/accepted-subset
authority and durable progress, then bounded dispatch/UI integration. This is not
executable 10,000-address or hardware-load/production acceptance.

## 2026-10-21 — Bounded managed-policy pagination

Replaced the Managed tab's full registry read with a separate private GET page
resource: 100 keys, stable device/numerical-IP ordering, explicit global totals,
positive selectors without clamping and one SQLite snapshot for counts, authority,
observations, protection and status. Previous/Next bind the managed revision.
API conflicts return 409; Web keeps a live region with an explicit current-policy
link, suppressing stale target controls without pretending policy is empty or
silently rebasing. Observation/attempt updates remain live on that same page.
Independent cleanup panels remain available. BFF refuses incomplete/truncated
page responses; authenticated viewing, no-store and source escaping are retained.

Added bounded local read-scope queries to restoration summaries and hold reporting.
Only displayed pairs are grouped/materialized; retained older-generation attention,
latest attempt and verified-only timestamp match the legacy view. Global capacity
and missing pending-evidence checks remain strict. Missing target device/authority
links refuse the page instead of disappearing through joins. Shared serialization
keeps full-review responses unchanged. Existing full private GET remains for
legacy exact-scope review; no admission logic uses a visible page as full scope.

No schema/capacity/protocol/agent/gate/profile/credential change, optional migration,
policy activation, draft confirmation or device fixture. Existing 1000-key policy,
10000-request and 10000-attempt bounds remain. Large-import confirmation/adoption,
capacity-compatible durable roots and continuous bounded dispatch remain pending;
this increment delivers their bounded read-side prerequisite and usable pagination.

Validation: final complete **1217 Python tests passed (62.96s)**, including 21
new pagination cases; **28 Chromium cases passed (100.59s)**. Compileall/Ruff/
diff checks pass; 184 local links/anchors validated across eight documents.
Synthetic tests compare all 251 policy rows/older-generation attempt summaries
against the legacy view; cover full 1000-key pagination without raising its limit,
restart, immutable read effects, changed revisions, malformed selectors, missing
authority outside the selected page, explicit empty/uninitialized/partial state,
bounded SQL scope and truncated BFF responses. Chromium checks 100 rows per page,
page-local control targets, Previous/Next, live updates without navigation,
mobile overflow and explicit current-policy recovery with no hint/execution.
Final Python 3.12 image preflight passes 101 synthetic pairs/two API pages in a
non-root/read-only/no-network container with disposable state and no lab mounts.
Rust/agent/protocol/Compose unchanged; their separate suites were not rerun.
Stopped the initial sandbox-constrained test run and reran local-socket coverage
with the permitted execution profile; no background test or fixture remains.

Authorized paired API/Web lab rollout only; retained prior images under
`ftd-shun-api:rollback-managed-pages-20261021T1042` and
`ftd-shun-web:rollback-managed-pages-20261021T1042`. Checked SQLite-safe backup
`/var/lib/ftd-shun-manager/managed-pages-20261021T1042/before-update.sqlite3`,
directory 0700/file 0600, integrity/FK checks pass, SHA-256
`68e87691753de5cf42002c6534899c7c74687df02b5c99e6030edc170c785c11`.
Normal service-only recreation avoids rerunning initializers. Schema and all
twelve retained queue/policy tables match backup exactly after rollout; observations
continue normally. No backup restoration or table deletion was performed.

Running API image
`sha256:56a3af587587a364867114a31914dd2ca347fe338ae9392acf0efe322354c091`,
Web `sha256:2fcdb9b57c432f773a54dcc0151ffd1b442b5304abef567227e4383e8d38d1fe`.
Agent remains
`sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`;
Caddy/Authelia unchanged. API ready/socket, new successful read 10:44:43Z/no error;
paged GET no-store/read-only with existing one retired target/revision 4.
Anonymous private Web returns 401; verified-TLS browser HTML request redirects
302 to authentication (a request without HTML Accept correctly returned 401).
Sole published listener remains 127.0.0.1:443. Queue remains 12 VERIFIED/1 NOOP,
no pending jobs; registry 4/suspended, enabled managed targets 0. All six experiment
flags/development authentication remain false and addition profiles remain zero.
No optional journal migration, new grant, live ADD/REMOVE or fixture. Current
code rollback uses the retained paired images without restoring old policy/data;
if unrelated work later appears, review it before downgrade or backup recovery.

## 2026-10-21 — Prepared import confirmation and retained reports

Implemented `ManagedImports` and seven fixed private POST routes for owner-bound
preparation/list/report/cancel-draft, gated confirmation and retained receipt reads.
Startup constructs coordinators only; no optional initializer/migration is called.
Current Operator/Administrator, explicit boolean recurring consent, distinct
canonical operation key, owner draft ID/full digest, exact accepted count and
trusted standing gate/configured profiles are required. Extra action/target/enable
fields and coercion are refused. Read reports remain available with admission off.

One BEGIN IMMEDIATE verifies lifetime/backwards time/full original scope, current
managed/protection revisions, selected device IDs/names/enabled state, classifications
and original references, pending/uncertain/cleanup/latch/recovery/profile/capacity
guards. Classification changes conflict whole; normal observation heartbeats do
not impersonate fresh evidence. Existing canonical MAINTAIN request/target writes
are shared, not a single-target transaction loop or alternate policy registry.
Explicit adoption has no ADD or fabricated creation provenance; already-managed
pairs retain original intent/generation/author. Protected members and invalid/
duplicate diagnostics are visibly retained as exclusions rather than silently
truncating scope. Ordinary grant entry points still reject adoption.

Two separate `confirmed_import_*` report tables/four immutable UPDATE/DELETE guards
retain full scope and prior/assigned intent references, captured draft versus real
confirmation actor, diagnostics and independent full framed checksums. Constructor/
optional reads do not initialize them. Confirmed reports survive draft pruning,
history retention/restart and later policy generations; original-key replay never
re-enables authority. A preparation cannot acquire another operation key, and an
old policy key cannot be reinterpreted as an import. Draft pages/lists show their
original confirmed operation; cancel-draft explicitly refuses after confirmation.
No confirmed-import cancellation or actual execution-progress claim is introduced.

The existing 1000 accepted-pair/key, 10000 request/attempt and retirement-reserve
bounds remain. Oversize scopes reject without splitting or partial admission.
Confirmed evidence is additionally bounded to 128 roots/1,000,000 member rows,
without automatic eviction/recycling. Policy/receipt/audit late failures roll
back together. Root adoption/confirmation audit uses the real actor; minimal
structured confirmation counts log only after commit. No queue insertion, hint,
SSH, resume, credential/profile or live gate change is part of confirmation.

Validation: **1260 Python tests passed (65.59s)**, including 43 new confirmation/
private-API cases. Final combined confirmation/preparation check: **70 passed
(6.03s)** after preserving early digest rejection before opening a database.
Compileall/Ruff/diff pass; 221 local Markdown links/anchors checked across ten
documents. Coverage includes mixed accepted/adopted/already-managed/protected
scope and invalid/duplicate reporting, actual versus captured roles, no queue or
occurrence provenance fabrication, whole-scope conflicts/expiry/backwards time,
late audit and outer schema rollback, concurrent key replay, old namespace refusal,
immutable/tampered evidence, owner privacy, full current 1000-pair reports and
oversize refusal, receipt/retirement reserves and permanent protection retirement.
Legacy exact-schema managed-maintenance inspection accepts the unchanged canonical
adoption authority without modifying state or weakening its existing blockers.
Strict private routes reject unreviewed fields/coerced consent; disabled admission
and ordinary startup never initialize optional tables. ASGI/socket tests use
permitted local test execution only. Browser/Rust/Compose unchanged; their separate
suites were not rerun for this backend-only change.

Built a separate validation-only image, not the running Compose image tags:
`ftd-shun-api:prepared-import-validation-20261021`,
`sha256:b3d86cb0efc8a52c90b88da4870159e4300543245c891d3ddd19d1980ac2ea22`.
Non-root/read-only/no-network Python 3.12 smoke validation uses only temporary
synthetic inventory/SQLite with no lab mounts: prepare two accepted targets plus
an invalid line, adopt one without ADD, save policy/report, prune the draft,
replay the original key and read the retained report. Queue jobs/attempts remain
zero; SQLite integrity/FK checks pass. Image construction/fixture initialization
does not migrate or activate the laboratory stack.

No lab deployment/restart, database migration, new fixture, device connection or
mutation, gate/profile/credential change was performed. The current browser is
unchanged; restarting services would not expose this unfinished Web workflow.
Keep the prior recorded lab images/evidence in place. The reviewed additive
migration/backup/rollback procedure is documented, not invoked. Larger policy/
attempt capacity, confirmed-import cancellation, frozen Web integration and rolling
dispatch remain the next working-version increments; this is not hardware-load
or 10,000-address executable/production acceptance.

## 2026-10-21 — Confirmed-import cancellation and in-flight settlement

Implemented the next working-version cancellation increment, not another
device executor. A separate journal provides fixed private review/cancel/status
POSTs for original-owner Operator/Administrator or current Administrator. A
five-minute state-bound digest and typed accepted pair count bind the original
confirmed scope, current policy/protection revisions and retained ADD outcomes.
Whole-scope changes refuse; original-key retries return the immutable initial
decision without repeating effects. Current status separately pages at 100 rows.

One SQLite write transaction records the decision/scope, retires exact unsent
original generations, cancels only owned unstarted ADDs and appends real-actor
audit. Adopted/pre-existing or VERIFIED/NOOP-applied targets remain maintained;
observation alone never fabricates service application. Failed/uncertain work
retains its original outcomes/latches with attention even after future policy
retirement. No REMOVE, queue admission, hint, new canonical request slot, fake
identity, policy resume or device connection is involved.

Captured RUNNING predecessors settle inside the existing queue result transaction:
success retains already enabled original policy; failure/uncertainty or typed
pre-write deferral retires it. Protection/independent retirement and newer grants
always win. The exact original pending generation blocks new restoration dispatch.
Lease-expiry recovery records UNVERIFIED rather than replaying, then settles the
same decision atomically. Pruning validates/preserves captured jobs and linked
requests. A missed hook from an unsupported older writer stays honestly pending;
GET never repairs it. No downgrade to such writers while a decision is pending.

Explicit optional initialization adds only `import_cancellation_decisions` and
`import_cancellation_targets`, one partial pending-pair index and five guards.
It requires existing report/policy/attempt schemas and supports outer rollback;
startup/requests/GET never initialize or repair them. One decision per existing
root reserves capacity for revocation (at most 128 roots/128000 accepted members),
without increasing the current 1000-key/pair or 10000-request/attempt bounds.
New confirmation requires these controls; historical receipt/replay does not.
Updated architecture, status, delivery plans and the structured
[Import Cancellation manual](manual/import-cancellation.md), including schema,
backup, activation boundaries, compatibility and rollback hazards.

Validation: full Python suite **1305 passed (67.30s)**, including 45 new cancellation
cases; final cancellation/restoration suite **99 passed (3.79s)** after tightening
retirement row-count/completion-evidence validation. Compileall/Ruff/diff pass;
233 changed-document local links/anchors checked. Local ASGI/socket tests ran with
permitted test execution outside the restrictive sandbox; initially blocked runs
were interrupted, not treated as successful validation. Fixtures are temporary
SQLite/ASGI only. Coverage includes mixed adopted/existing/protected
scope, queued cancellation, four RUNNING outcomes, exact deferral, restart/lease
loss, original-key concurrency, stale/expired reviews/current roles, late decision
and settlement audit rollback, retained success after pruning/draft expiry,
1000-pair atomic revocation/100-row pages, ledger exhaustion, immutable evidence,
missing predecessor refusal and disabled-admission strict private API.

No lab rollout/restart, optional migration, credential/profile/gate change, new
fixture or FTD call was performed. Existing browser/agent/Compose assets are
unchanged; their separate suites were not rerun. Frozen Web confirmation/cancel
integration, larger compatible capacity and continuous bounded execution remain
pending. This is not live bulk/throughput or production acceptance.

## 2026-10-21 — Managed-import Web confirmation and cancellation

Connected the prepared-import backends to a separate authenticated BFF workflow
at `/managed-imports`, now recommended by Operator/Administrator navigation.
Saved preparations/owner receipts use private body references and 100-row report
pages. Exact classifications, protected exclusions, adoption, invalid/duplicate
diagnostics and selected device identity are visible. Uninitialized optional
storage is explicit, not an empty healthy/executable import state. The legacy
one-time preview remains separately accessible; no existing endpoint is silently
converted into standing policy.

Separate bounded subject/CSRF-bound review caches protect confirmation and
cancellation; configured sensitive age is capped at ten/five minutes respectively.
Confirmation requires exact accepted pair count and recurring consent plus both
BFF and current API admission capability. Deterministic UUIDv5 operation reference
from the immutable preparation preserves one original key through Web restart.
Unknown/malformed replies retain frozen key/body/token/count/consent, with explicit
inspection/retry, never automatic replay or silent reclassification. Reload/paging
never replaces the review or supplies authority. Current roles are checked again
on every POST; no browser actor/target/gate override exists. Metadata is escaped,
times localize with a timezone, and all non-static responses are no-store.

Cancellation is separately reviewed even when new admission is off. Its warning
explicitly says already applied/adopted addresses remain blocked and maintained.
Historical confirmation/initial cancellation receipt and current cancellation
settlement are distinct. Manual status reads page current retained/stopped/waiting/
attention members without commands or another decision. Opening a previously
cancelled root shows status instead of creating new authority.

New `managed_import_web.py` isolates the browser adapter instead of extending
the privileged executor. Five templates reuse existing controls/styles, with
explicit action spacing and no background refresh replacement on sensitive forms.
Updated architecture, working-version/development plans, status and structured
[Managed Import Web manual](manual/managed-import-web.md). No schema, fixed binary
protocol, agent, credential, Compose or storage/dispatch-capacity change is involved.

Validation: **1331 Python tests passed (77.33s)**, including 26 new real BFF/private
API integration cases on temporary SQLite. Coverage includes adoption/exclusions,
count/consent, subject/cookie/age/roles/CSRF/extra-field boundaries, frozen paging,
both gates, lost/malformed/post-commit follow-up replies, stable keys across BFF
restart, receipt reads after draft pruning and base-only startup without migration.
**30 Chromium cases passed (101.27s)**, including two new production-template
checks for native validation, field/focus/token preservation, escaped metadata,
colored exclusions, gate-independent cancellation warnings and mobile spacing.
The initial browser fixture incorrectly awaited a live-refresh control on these
frozen pages; fixed the fixture's readiness selector, without adding refresh or
weakening production behavior, then reran the complete browser suite.
Compileall/Ruff/diff checks pass; 247 local Markdown links/anchors checked.
Local socket/browser tests used permitted local
execution. Browser fixtures never invoke the lab or device mutations.

Built paired Python 3.12 images; a separate non-root/read-only/no-network container
with no lab mounts passed real synthetic BFF/API prepare, recurring confirmation,
cancellation and status. Explicit synthetic schema initialization created no live
state; zero device jobs, integrity/FK checks pass. This verifies installed assets/
dependencies, not hardware throughput or 100,000-pair execution.

Authorized API/Web-only rollout completed on the existing local-lab Compose
project, service-only `--no-deps --no-build` recreation after validation. Retained
previous images as `ftd-shun-api:rollback-managed-import-web-20261021` and
`ftd-shun-web:rollback-managed-import-web-20261021`. Checked online SQLite backup:
`/var/lib/ftd-shun-manager/managed-import-web-20261021T1330/before-update.sqlite3`,
0700 directory/0600 file, integrity/FK checks pass, SHA-256
`7442b5043f7325d5f16eae9d125bd86f1f714bb33af206154f510db0fc17633d`.
Schema SHA-256 `d1f2cc47eea097f9d873514cd448d173e9e24abaef37dbfb891436dc0d8f6132`
and every row in twelve retained queue/policy tables match the backup after
rollout; the active executor lease is intentionally excluded from row equality.

Running API `sha256:7bcbe11f777ddd9cf9e2564d994579fc00099f0029be52224bfa3dbd9da8e51e`,
Web `sha256:a21f63de26f037419a118c4db2948619dba8eeeae035c4ef26cbfdad4abe45b5`.
Agent remains `sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`;
Caddy/Authelia unchanged. API ready/socket, successful snapshot 13:33:10Z and no
error; 12 VERIFIED/1 NOOP/no pending, revision 4/suspended/enabled managed 0.
All six experimental flags and development auth remain false; addition profiles 0.
Preparation/confirmed/cancellation schemas remain absent, with private reads
reporting uninitialized honestly. Anonymous Web denies `/managed-imports` (401),
TLS-verified Caddy redirects it to authentication (302); API/Web retain network
mode none and only Caddy loopback443 is published. No synthetic Web actor was
submitted to the live BFF; live owner-list smoke used an explicitly labelled,
non-authoritative trusted-host read identity, not an impersonated user.

No optional live migration, fixture, ADD/restoration activation, inventory or
credential change is included. Larger compatible authority/attempt capacity,
continuous bounded dispatch/progress, per-device parallelism and automatic
uncertainty reconciliation remain working-version delivery gaps.

## 2026-10-21 — Deferred minimal IP-context idea

Recorded the operator's request to add minimal IP information in the Web UI using
RDAP or an equivalent source later. Added the working-version follow-up and linked
development/status records without changing the current core delivery priority.
Candidate fields are network/organization/range, optional ASN and registered
country when supplied, plus source/time/staleness. Registration context is not
physical geolocation, blocking reputation or mutation authority.

Recorded compact expandable presentation, asynchronous deduplicated/bounded
caching, TTL/backoff/rate/response/time limits and honest unavailable states.
Provider/coverage/terms, external-query privacy, private/special-address exclusion,
offline alternatives and SSRF-safe discovery need review before implementation.
Existing Web/API isolation and FTD-only agent egress stay unchanged; this idea
does not authorize provider traffic, a new network route, schema or deployment.

Validation: documentation-only change; `git diff --check` and changed-document
local link/anchor checks. No code/tests, IP lookup/provider research, live service
restart, configuration change or device operation was performed.

## 2026-10-21 — Occurrence-driven IP context and bounded review selections

Recorded the operator's refinement of the deferred RDAP/equivalent idea: enrich
once on detection, retain its result/unavailable status while shunned and permit
a new attempt only after confirmed disappearance/removal and redetection. Polling,
views, cache expiry, failures/restart and an additional-device sighting of an
already active IP must not restart lookup. Keep a durable occurrence completion
marker and same-IP coalescing; no periodic backfill/retry loop. No lookup/provider
research, implementation, new egress or live activation was performed.

Implemented another read-side prerequisite for larger managed capacity rather
than raising coupled constants prematurely. `ManagedShuns.selection()` and a
strict fixed private read-only POST accept 1–100 distinct literal device/IPv4
pairs and optional exact revision. One SQLite snapshot returns normalized requested
scope, global total/revision/limit and at most 100 existing policies with scoped
retained-attempt/queue summaries. Missing selected pairs are distinct from an
empty/uninitialized registry. Global device/authority corruption and partial
optional evidence remain unavailable, not silently filtered into a valid read.

Single-pair BFF grant, retirement and removal reviews now use that resource,
validate exact selection and refuse substituted global/page responses. Existing
read/CSRF/identity/review-age/generation/uncertainty/gate and final atomic-admission
contracts remain. No read grants/adopts/retires policy, submits work, refreshes
Cisco, writes audit or initializes schemas. Legacy complete/batch contracts and
all current capacity/ledger/retirement limits are unchanged; versioned larger
authority, remaining full readers and rolling dispatch still need coordinated
implementation. No new schema/protocol/agent/credential/Compose change.

Added synthetic selection/parity/strict-type/corruption/transaction/bounded-SQL
and real BFF-no-full-fallback cases. Updated existing test assertions/fault
injection to distinguish the new read-only POST from actual retirement/cleanup
POSTs, without relaxing no-mutation/auth/CSRF/old-key checks.

Validation: **1366 Python tests passed (75.42s)**, including 35 new selector/API/
BFF cases. Final affected review/control/grant/cleanup check: **181 passed
(17.13s)**. Compileall/Ruff/diff pass. Tests cover exact/missing membership versus
global totals, sorted maximum 100-row reads, legacy parity/older-generation
attention, bounded SQL summaries, restart/revision refusal, concurrent retirement
with consistent read metadata, orphan/partial-state refusal, strict/coerced/extra
fields, response substitution and zero whole-registry BFF fallback. Earlier
GET-only test assumptions were corrected to recognize the explicit read-only
POST; mutation counts/fault injection still target actual semantic writes.

Built paired Python 3.12 images and validated installed code through synthetic
ASGI/SQLite in a non-root, read-only/no-network container without lab mounts.
All three single-pair Web reviews pass without a whole-registry fetch, changed
policy or queued job; integrity check passes. Browser templates/JavaScript/CSS,
Rust agent and Compose are unchanged; their separate suites were not rerun.
No provider request, FTD fixture or schema/gate/credential change was made.
166 changed-document local links/anchors checked.

Authorized service-only API/Web lab rollout completed with prior paired images
retained as `ftd-shun-api:rollback-selected-policy-20261021T1415` and
`ftd-shun-web:rollback-selected-policy-20261021T1415`. Checked SQLite online backup
`/var/lib/ftd-shun-manager/selected-policy-20261021T1415/before-update.sqlite3`,
0700 directory/0600 file, integrity/FK checks pass, SHA-256
`61337cabe96eb777d48963708ad3e52b99d9ac15afb6154b2007247746274770`.
Schema SHA-256 `d1f2cc47eea097f9d873514cd448d173e9e24abaef37dbfb891436dc0d8f6132`
and every row of twelve retained queue/policy tables match backup after rollout;
the active executor lease is intentionally excluded from row equality.

Running API `sha256:7bc1aab618ca5ccce4f4fb97453057835b3bca2c37b57c3bc6e34fc560992da4`,
Web `sha256:52a21c6b3f54c174502a798b142f99f75932b789eddfd32bbf6cf6ec193c0f2e`.
Agent unchanged at
`sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`;
Caddy/Authelia unchanged. API ready/socket, successful read 14:16:31Z/no error,
12 VERIFIED/1 NOOP/no pending, registry revision 4/suspended/enabled managed 0.
The live read-only selector smoke returns global total 1/selected count 0 for an
absent TEST-NET/device selector, without creating any policy/observation/fixture.
All six experimental flags/development auth remain false, addition profiles 0,
optional import tables absent. Anonymous Web401, TLS-verified Caddy auth redirect302,
API/Web network mode none and sole loopback443 published. No authenticated live
form or policy mutation was submitted. Rollback may restore prior paired code,
not earlier enabled database state; no database restoration/table deletion occurred.

## 2026-10-21 — Whole standing-list selected reads

Extended the bounded-read prerequisite to legacy standing-list preparation. A
distinct fixed private `POST /api/v1/managed-shuns/selection/batch` accepts at most
1000 literal distinct device/IPv4 selectors and optional exact managed revision.
It returns a separate `selected_batch` marker, complete normalized requested
membership, global totals and only existing selected entries. The original
100-selector resource remains separately bounded and cannot substitute for it.

One SQLite read transaction uses at-most-100-pair SQL/attempt/hold chunks and one
reference time. Global orphan/partial-state refusal remains, including outside
selection; a late chunk error returns no partial success. Concurrent retirement
cannot combine early old rows and later new rows. Reads initialize no optional
schema and write no policy, audit, hint, origin or executable work.

The BFF now reads one complete selected batch, never a full registry, independent
pages or individual API calls. It validates exact scope once, indexes entries
once and derives exact one-pair views for existing target validation. Capacity
uses the global retained count, including stopped/unselected keys; selected
stopped keys consume no extra slot. Legacy all-or-nothing conflict/observed/
protected refusal, identity/CSRF, frozen consent and final atomic admission/replay
are unchanged. Adapted the existing uninitialized-response fixture to the new
read route without weakening confirmation guards.

Added synthetic maximum-scope/bounded-SQL/parity/restart/concurrent-read cases,
global versus selected capacity, stopped-key reuse, retained attention, strict
private fields, response substitution, late-chunk/partial-state refusal and
actual BFF preparation with full snapshots forbidden. Existing batch admission,
unknown replies, old-key replay, default-off and no-work cases remain.

Validation: **1396 Python tests passed (81.24s)**, including 30 new batch-selection
cases; focused batch/selection suite **73 passed (7.28s)**. Compileall/Ruff/diff
pass and 173 changed-document local links/anchors are valid. The initial full run
identified the strict route-inventory expectation, which was extended with only
the new fixed read route; no-init and admission checks remain. The maximum fixture
uses its actual protection revision, not an assumed zero. Final full run is clean.

The built Python 3.12 candidate exercised 1000 synthetic retired/absent selected
pairs through actual BFF/API/SQLite in a non-root, read-only/no-network container
without lab mounts. Exactly one batch read, no whole snapshot, ten review pages,
no queue jobs, unchanged dump and integrity OK. Browser templates/JavaScript/CSS,
agent and Compose are unchanged; their separate suites were not rerun. Python
dependency ranges are still not locked; this image used FastAPI 0.157.0 and the
installed-code smoke is not a reproducibility claim.

Authorized paired API/Web rollout completed on the existing lab. Prior images
are retained as `ftd-shun-api:rollback-batch-selection-20261021T1500` and
`ftd-shun-web:rollback-batch-selection-20261021T1500`. Checked online backup:
`/var/lib/ftd-shun-manager/batch-selection-20261021T1520/before-update.sqlite3`,
directory0700/file0600, integrity/FK checks pass, SHA-256
`7ed7bdb06e8b929f7000f0ced62b897b548d471c3a2900994883f1df9849a1e7`.
Schema SHA-256 (JSON `[type,name,tbl_name,sql]`, sorted by type/name, non-null SQL):
`8fb2366cda91358441071b2e24f86fe6df949adccba8c8b984e81a9e63ca47cd`.
This explicitly stated hash encoding differs from earlier log encodings; direct
schema equality to this backup passes. All rows in twelve retained queue/policy
tables match exactly; the active executor lease is intentionally excluded.

Running API `sha256:10f81188b79c5c34afb77d160fab96dbaaa9e55ef0fdf461b564f50c7d2718f4`,
Web `sha256:ac2039ba4c6851d60a98627d435b40ff77880287a8d574f38819e39f668f8fe2`.
Agent remains `sha256:bdd040aef2720ae80fe2caf90b715904ea60eef024ed594b52a74cdaf14a0b34`;
Caddy/Authelia unchanged. API ready/socket, ordinary successful read 15:20:33Z,
no error, 12 VERIFIED/1 NOOP/no pending, registry revision4/suspended/enabled managed0.
Read-only smoke selects two absent TEST-NET/device pairs: global total1, selected0,
exact requested2/no-store, with no fixture creation. All six experimental flags
and development auth remain false, addition profiles0, optional import tables
absent. Anonymous batch form401, TLS-verified Caddy auth redirect302, API/Web network
mode none and sole published loopback443. No live authenticated form was submitted.
Rollback restores matching prior code, not old enabled database state; no database
restoration, table deletion or optional migration occurred.

No capacity/schema/agent/protocol/credential/Compose change, optional lab migration, feature activation
or new FTD fixture is included. This is not 10,000-IP executable-import acceptance;
versioned retained authority, retirement reserve, attempts/reports/cancellation
capacity and rolling dispatch remain separate coordinated work.

## 2026-10-21 — Version-2 large-import intent foundation

Defined and implemented an isolated proposed-import format before changing the
coupled live authority limits. The pure `bulk_intent` module streams a complete
10000-address/ten-explicit-device/100000-pair classified manifest with a fixed
domain-separated seven-byte record encoding. Strict numerical order, literal
types, bounded distinct-address memory and full product/count checks refuse
duplicates, missing cells, oversized streams and unknown classifications rather
than truncating. Bind ADD/adoption/already-managed/protected exclusions exactly.

The compact canonical descriptor fixes version2/scope/MAINTAIN/standing mode and
binds separate operation/preparation UUIDs, original preparation digest, revisions,
normalized metadata and the complete manifest summary. It is limited to 8192
UTF-8 bytes with duplicate/unknown/noncanonical JSON refusal. Full verification
requires the separately retained original digest and complete matching stream;
neither a digest nor a constructible summary is authority or execution evidence.
Existing canonical requests/hashes/limits and all original key meanings remain.

An internal `ImportPreparations.propose_bulk_intent` read composes existing saved
journals with the format in one snapshot. It checks full original integrity,
owner, <=100-row scans, summary parity and expiry/clock before returning explicitly
non-executable/no-policy/no-work metadata. Already confirmed/expired/cancelled
preparations cannot become new-format proposals. Current observations/protection
do not rebase its frozen scope or authorize anything. No root/key reservation,
policy, schema, receipt, audit, origin, job or hint is written.

Added independent fixed vectors, maximum accepted and mixed classified streams,
bounded descriptor/working memory, exact order/product/typing/JSON/version refusal,
tampering with unchanged aggregate counts, legacy canonical hash/limit preservation,
actual 100000-pair journal composition, restart/owner/source privacy, expiry/clock,
confirmed-legacy refusal and unchanged independent state. Documented the format,
remaining coordinated persistence/reserve/attempt/report/cancellation transition
and the fact that no runtime route/controller/maintenance accepts it yet.

Validation: **1481 Python tests passed (85.19s)**, including **85 new format/journal
tests**; focused run **85 passed (6.66s)**. The broader existing import/preparation/
cancellation check passed **197 tests (14.59s)** before the final three refusal
cases were added; the subsequent full run includes all final cases. Compileall,
Ruff and diff pass; 226 changed-document local links/anchors are valid. The pure
maximum-stream test checks <8 MiB traced working memory and <1500-byte descriptor
for its synthetic metadata, not total process/SQLite memory or performance SLA.

Built a separate `ftd-shun-capacity-check:v2-format-20261021` Python 3.12 validation
image without changing deployment tags or running containers. Installed code in
a non-root, read-only/no-network container with no lab mounts creates/reopens a
100000-pair synthetic journal, builds and fully reverifies 100000 accepted pairs
with a 694-byte descriptor, and repeats the same proposal after restart. Integrity/
foreign-key checks pass; no managed/confirmed/cancellation policy schemas, queue
jobs or audit events are created. Python dependency ranges remain unlocked;
installed-code validation is not a reproducibility claim. Browser assets, Rust
agent and Compose are unchanged; their separate suites were not rerun.

No lab service restart/rollout, optional migration, live UDS/form/agent/provider
request, gate/profile/inventory/credential change, fixture or device mutation was
performed. The deployed API/Web remain the preceding selected-batch release;
this unused foundation does not need a runtime update. Corrected the preparation
module's stale pre-API docstring to describe its existing explicit-init boundary.

This adds no SQL schema, configured capacity, binary RPC, feature gate,
credential/network or deployed runtime caller.
No lab restart/migration, new fixture or FTD request is needed or authorized.
The format is not the persisted/executable 10000-IP release or storage/dispatch/
throughput acceptance. Retain all old receipts/latches and define migration/
older-writer rollback before version2 can become durable authority.

## 2026-10-21 — Isolated version-2 SQLite policy persistence

Implemented actual version-2 policy persistence rather than another preview.
`BulkPolicies` commits the canonical actor-attributed request, independent original
header/classified membership, effective device/IP policy and audit in one write
transaction. It reuses existing target/request tables with a distinct suspended
`managed_bulk_registry`, never a parallel effective-policy engine. Legacy readers
refuse partial/unsupported state even below 1000 keys; the legacy initializer
also refuses bulk objects instead of recreating a registry.

Explicit empty initialization accepts only a fresh managed namespace under an
ordinary pause with no lease/pending/uncertain work. It neither converts nor
erases the retained lab state. The fixed profile supports 200000 retained keys,
400000 immutable requests with the last 200000 reserved for actual revocation,
128 roots and 1000000 retained members. Deferred membership foreign keys and a
final count-checked immutable seal forbid partial roots or later member insertion.
Savepoint composition rolls back even when an outer caller catches an error.

An explicit preparation subclass reads the bulk profile; the normal runtime
classifier does not fall back to it. Shared optional preparation confirmation
lookup recognizes its retained roots only when bulk objects exist. The pure
descriptor decoder was factored from full manifest verification without changing
golden vectors or legacy canonicalization. No normal API/controller writer uses
the new storage path or initializes its schema.

Trusted internal confirmation requires explicit default-false capability, current
Operator/Administrator, consent/count/profiles and exact source/manifest/revision/
device/classification/generation checks. Any lease, pending/uncertain job or
unsupported optional evidence refuses new authority. Adoption emits no ADD or
fake occurrence provenance; already-managed generations keep original author/
authority. Original-key retries return historical results after pruning/retirement/
newer generations, never re-enable policy. Owner lists and 100-row immutable/current
pages survive restart. Separate exact-revision policy retirement works in reserve
and during admission pause, without REMOVE, job cancellation or uncertainty repair.

Added synthetic fresh-profile/initialization rollback/legacy refusal, real-actor
audit/adoption/exclusion, TTL/revision/device/work/identity/type/gate conflicts,
outer-commit late failure, same-key concurrency, actual retirement reserve,
uncertainty preservation, sealed/partial/corrupt scope, owner paging and a complete
100000-pair persistence/restart/pruning/idempotency scenario with zero queue work.
Documented developer-only scope, schema/backup/downgrade boundaries and integration
work. The operator reiterated this is development/non-production; no per-step
development approval ceremony or production rollout is added.

Validation: **1522 Python tests passed (109.34s)**, including **41 new storage
cases**. Initial storage-only suite: **29 passed (23.46s)** before the additional
strict/quota/uncertainty/corruption cases; the final full run contains them all.
Compileall/Ruff/diff pass; 235 changed-document local links/anchors are valid.

Built the separately tagged Python 3.12 validation image
`ftd-shun-capacity-check:v2-storage-20261021`, image
`sha256:ad534534c5035f54ee962dc4c9626d660c2af7878de6746e69789f33b3d11a4b`.
Installed code in a non-root, read-only/no-network container without lab mounts
persists 100000 policy pairs/members, prunes the draft, restarts the coordinator,
reads late 100-row receipt/current pages, retires one target and replays the
original grant without re-enabling it. No jobs; integrity/FK and legacy-refusal
checks pass. Only a synthetic temporary database was used. Browser assets, Rust
agent and Compose are unchanged; their separate suites were not rerun. Python
dependency ranges remain unlocked; image validation is not a reproducibility claim.

No lab database/schema/fixture, live API/agent request, profile/gate/secret change
or service restart is included. No SSH/provider operation or production change.
The profile remains suspended and unconnected to HTTP/Web, protections/cleanup/
cancellation/attempts or a dispatcher. Nonempty development migration and those
version-aware integrations remain necessary before a usable executable release;
storage success is not hardware throughput or production acceptance.

## 2026-10-22 — Version-2 permanent protection revocation

Connected the existing Protected-IP coordinator to exact version-2 bulk storage
for narrow read/revocation behavior, not generic legacy runtime compatibility.
Any bulk object selects strict profile recognition; partial/mixed/unsupported
optional state is unknown rather than empty. Enabled identity preflight uses
100-row chunks instead of loading the entire large registry into Python.

A freshly reviewed protection save retires all matching enabled targets in the
same transaction, including absent observations and disabled devices. It keeps
intent/generation/original grant, updates the bulk revision once and appends
linked real-editor audit without a new managed request slot or role promotion.
Every authenticated editor retains the existing protection authority. Full ledger
and ordinary mutation pause do not obstruct this fixed revocation.

Unknown state permits durable enabled protection with explicit deferred-retirement
audit, but refuses weakening until repair and reviewed completion. GET/restart
does not initialize, repair or retire policy. Disable/delete and original-root
replay do not re-enable a retired generation; subsequent explicit consent is
separate. Shared queue hooks reject eligible unsent ordinary ADDs, leave RUNNING
and uncertain outcomes unchanged, and preserve a manual removal coalesced with
an obsolete protected-policy intention. Late audit/cancellation failure rolls
back protection, targets, both revisions, events and queue changes.

Added 30 disposable protection cases: all actual roles, ten-device scope, old-key/
restart/new-generation behavior, revision conflicts, full ledger/pause, three late
failure boundaries, five unknown-state cases, repaired-barrier weakening, retained
queue evidence, coalescing and simultaneous grant/protection. Existing private
API routes are checked with explicit synthetic settings, disabled agent and no
worker. Extended the real 100000-pair storage fixture with ten-device protection,
historical replay and weakening without re-enable. No test uses the lab or FTD.

Validation: focused storage/protection suite **129 passed (32.90s)**; full suite
**1552 passed (112.59s)**. Compileall/Ruff/diff pass, as do 182 changed-document
local links/anchors. Browser assets, Rust agent and Compose are unchanged; their
separate suites were not rerun. No installed-image rebuild or service rollout was
needed for this still-suspended development-profile integration.

Updated normative integration contract, storage/protection/developer manuals,
working-version plan and status. No SQL schema, RPC, credentials, gate/profile,
network or Compose change. The legacy lab needs no migration/database restore
for this code; populated version2 must stay on compatible code or offline, not
be weakened through an older writer. No new fixture, live mutation, migration,
service restart or production action was performed. Cleanup/cancellation/attempt
capacity, rolling dispatch, nonempty conversion and executable Web integration
remain follow-up work; protection compatibility alone does not enable imports.

## 2026-10-22 — Bulk cancellation, local progress and bounded work preparation

Added optional version-2 cancellation controls and read-only rolling-work
preparation as successive product steps. The bulk reader recognizes the exact
original profile or its exact additive extension; legacy/mixed/partial state
remains unsupported. Explicit initialization adds two empty tables and six
triggers under ordinary pause/quiescence, preserves existing policy/roots and
rolls back DDL within caught outer transactions. Startup/GET never migrates.

Whole-root cancellation requires current Operator owner/Administrator, actual
actor, exact accepted-pair count and a five-minute streamed state-bound review.
It retires original enabled unapplied ADD generations, preserves adopted/existing
policy and leaves stopped/superseded authority untouched. Original classification,
assigned authority, reviewed revision and dispositions are independently retained
under one immutable count-checked seal; receipt, retirements and real-actor audit
commit atomically. No request-ledger slot, REMOVE or queue work is admitted.
Exact actor/review retries return immutable history after expiry/pruning/restart/
new generations; old import replay cannot re-enable policy.

The profile lacks a version-aware attempt ledger. Any retained ADD evidence or
independent unfinished work for a current proposed-ADD member therefore refuses
cancellation, rather than treating an unknown job as unsent/applied or pretending
RUNNING settlement exists. Observations alone do not prove service application.
Legacy attempt/cancellation hooks retain their original behavior; no evidence is
pruned, relabelled or reset. Actual attempt integration remains required before
execution, not bypassed by this increment.

Added local original-classification/current-disposition progress and <=16-pair
keyset portions with exact managed/protection revisions. Protection/device/work/
evidence holds exclude candidates. Cached presence is explicitly not verified
execution; missing policy is an error. Reads create no schemas/jobs/audit/grants,
reserve nothing and advance no durable execution cursor. Later dispatcher claims
still need fresh complete evidence, RPC settlement, capabilities and capacity.

Added 60 new disposable cases, including full 100000-pair cancellation, late100-row
pages, restart/pruning/replay, mixed adoption/exclusion, old/new generations,
current owner/Admin, strict actor/review payloads, simultaneous original-key
decisions, full ledger/pause, evidence refusal, late audit/clock/DDL savepoint
rollback, immutable/corrupt/partial state, protection integration and bounded
progress/portion scans. Initial focused 159-case run passed (78.52s); after final
coverage, 59 nonmaximum new-module cases passed (2.97s). Final full suite:
**1612 passed (157.96s)**, including all 60 new cases. Compileall/Ruff/diff and
194 changed/new-document local links/anchors pass. A restricted-sandbox ASGI
regression run stalled after 25 cases; its exact disposable pytest process was
terminated and the focused/full suites rerun with local test permissions. No
product process was affected. Browser assets, Rust agent and Compose are unchanged;
their separate suites were not rerun. No installed-image rebuild or rollout.

Updated architecture, storage/cancellation/developer manuals, working-version plan
and status. No agent, binary RPC, credential, network, Compose or feature-gate
change. No lab migration/database mutation, live fixture, service restart or
production action. Older version-2 code refuses the extension: retain compatible
code or keep data offline; never drop receipts or restore enabled policy for a
downgrade. No live backup/restore operation was needed. These are developer
components, not executable Web bulk imports, automatic reconciliation or measured
FTD throughput. Next: version-aware attempt binding/in-flight settlement and
shared bounded queue integration, then conversion and runtime/Web activation.

## 2026-10-22 — Bulk attempt journal and shared queue result hooks

Added the explicitly initialized optional `managed_bulk_attempts` ledger after
cancellation controls, preserving the exact suspended registry and earlier
roots/receipts. It retains up to 1000000 attempts with immutable authority,
terminal evidence and guarded transitions; no eviction or uncertainty reset.
Initialization requires pause/quiescence, rolls back caught outer-transaction
DDL failures and never runs at startup/GET or converts legacy attempts.

A default-false internal hook captures an already RUNNING exact system ADD before
external send in a caller-owned transaction. It checks fresh complete absence,
original intent/generation/root/revision, one original fixed-identity/no-role
request/job/link, shared lease, original 900-second request deadline, enabled/
unprotected device/policy and no earlier pending/uncertain work. Prior successful
work must precede the read; keys cannot gain attempt meaning across namespaces.
Capture creates no request/job, performs no claim, returns dispatch_authorized=false
and has no deployed caller. Tests simulate the future pre-send transaction, not
an implemented live admission path.

The existing shared queue result hooks now recognize exact bulk evidence while
legacy readers retain their meaning. Typed results, exact deferral, expired-lease
UNVERIFIED recovery, system status and audit commit with the original journal
and actual occurrence only for VERIFIED. NOOP is not service-created provenance.
Late audit failure rolls back job/journal/occurrence/events; protected/retired
policy is never re-enabled by in-flight success. Deferred bulk work cannot run
even with the old restoration capability. No second worker/session or retry.

Retention validates all pending/unknown bindings before pruning and retains their
jobs/links/requests; missing/malformed evidence refuses pruning. Independent
terminal journal evidence survives ordinary job/request pruning. Root-bound
100-row evidence pages check current Operator owner/Administrator and return no
execution authority. Reads never initialize, repair, retire or settle policy.
Running bulk cancellation remains explicitly refused: captured-wait settlement
and completed-application retention are not implied by this journal.

Added 40 disposable cases for results/occurrences, protection/retirement, deferral,
lease recovery, immutable keys/terminals, unknown/terminal retention, bad
predecessors, capture source/deadline/evidence/capacity/namespace guards, current
read permission, partial/no-init state and audit/DDL rollback. Initial 30 passed
(1.33s); shared bulk/legacy regressions passed 157 (6.00s), then final journal
suite passed all 40 (2.56s). Final full suite: **1652 passed (162.45s)**.
Compileall/Ruff/diff and 201 changed/new-document local links/anchors pass.
Browser assets, Rust agent and Compose are unchanged; their separate suites were
not rerun. No installed-image rebuild, service rollout or live device validation.

Updated architecture, manuals, working-version plan and status. No live database/
schema, gate/profile, credential, binary RPC, agent, Compose/network or service
change; no lab fixture, SSH request, production operation or backup restore.
Before non-disposable migration retain a checked SQLite-safe backup and compatible
code; older version-2 code refuses the journal extension. Do not delete evidence
or restore enabled policy to force rollback. Next integration remains atomic
admission/claim and captured-wait cancellation/reconciliation, not another executor.

## 2026-10-22 — Captured bulk cancellation and immutable result settlement

Implemented owned RUNNING capture and shared-result cancellation settlement as
an explicit optional profile after the journal, not a second executor or runtime
activation. Complete owned attempt history and original authority now bind review;
unattributable/independent work still conflicts. Verified/no-op application remains
maintained; failed/unknown/unsent first application is retired without changing
its original result. Owned queued cancellation occurs only after the entire
decision/member seal, scanning in <=100-row chunks rather than building a backlog.

The initial WAITING_OUTCOME receipt/membership remains immutable. Shared result,
typed pre-write deferral and expired-lease recovery append one immutable settlement
with actual cancelling actor/roles; protection/retirement/newer generations win.
Exact deferral settles before recursive queued cancellation. Late audit failure
rolls back job, journal, occurrence, retirement and settlement together. No REMOVE,
ADD replay, re-enable or uncertainty resolution is inferred.

Current cancellation status overlays settlements in 100-row pages and exposes
initial_state/current state, current counts, settled and attention separately
from the historical receipt. Original-key retry never re-applies revocation.
Pending captured jobs/requests survive retention, including a terminal result
whose settlement an incompatible writer omitted. Missing/malformed predecessors
refuse pruning; GET/restart does not repair. Quiescence now validates held journal
bindings and refuses still-pending waits even when queue rows look terminal.
Independent unknown latches remain after settlement/retirement/pruning.

Explicit initialization under pause/quiescence checks every old root/receipt,
transactionally rebuilds only cancellation membership with identical original
nine fields plus nullable captured-job/history bindings and expanded states,
reinstalls original immutable guards and adds the settlement ledger/three guards.
It checks unchanged receipts/hashes afterward and rolls back all DDL/data copy
on failure, including caught caller-owned transaction composition. Exact older
profiles remain readable; startup/GET never upgrades/repairs. No old outcome,
receipt or policy is converted into new authority.

Added 31 disposable wait cases: running/completed outcomes, deferral/lease recovery,
protection/retirement/coherent-newer-generation precedence, original receipt versus
current counts, source/history conflicts, audit/migration rollback, immutable
records, pending/unknown retention, incompatible-writer evidence holds and honest
inconsistent-generation refusal. The coherent replacement fixture explicitly
models a future compatible writer; normal RUNNING admission remains forbidden.
Extended the actual 100000-member cancellation fixture with preservation upgrade,
original-key receipt replay and late paging while keeping zero executable backlog.
Focused wait/cancellation run: **91 passed (61.85s)**. Earlier focused nonmaximum
bulk regressions: 128 passed (6.55s); first 20 wait cases passed (1.35s), then 31
passed (2.17s) before the final full/capacity run. Full-suite/documentation results
are now complete: **1683 passed (179.51s)**. Compileall/Ruff/diff and all 209
changed/new-document local links/anchors pass. Browser assets, Rust agent and
Compose are unchanged; their separate suites were not rerun. No installed-image
rebuild, live migration/rollout or actual FTD validation was performed.

Updated architecture, structured manuals, status and working-version plan. No
live DB/schema migration, fixture, gate/profile/credential, HTTP, agent/RPC,
Compose/network, service restart or FTD operation. Before eventual non-disposable
upgrade retain checked private SQLite-safe backup and compatible code; do not
drop history/settlements or restore enabled policy to force downgrade. No live
backup/restore action was needed. Admission/claim, actual dispatch, automatic
reconciliation, nonempty conversion and Web activation remain separate next work.

## 2026-10-22 — Atomic bulk queue portions and shared claim capability

Implemented real <=16-candidate same-device admission, not another read-only work
page or seeded RUNNING fixture. One caller-composable transaction validates exact
standing generation/authorization/target and global revisions, trusted device
profile, lease, complete fresh absence, root integrity, protection/observations,
earlier work/uncertainty, pair backoff/churn and shared queue/retained capacity.
It creates fixed system delegations, jobs, links, QUEUED attempts and actual audit
together. A final-member conflict/audit/expiry rolls back the entire portion even
under a caught outer transaction. No coalescing, fabricated user role/import
provenance, renewal or uncertainty replay. Deterministic keys return historical
state after retirement/restart/pruning; mixed old/new portions explicitly conflict.

Added a distinct default-false bulk capability to the existing shared queue claim,
not the legacy restoration gate. It preserves cutoff/cooldown, serializes each
device and revalidates original authority/evidence/lease/delegation before commit.
Existing typed result, protection, cancellation, captured deferral and expired-
worker hooks now compose with genuinely admitted jobs. Valid exact pre-write
deferral may reclaim only the same original job; lost outcomes remain unknown.
Read-only work metadata now reports actual profile suspension without granting
execution authority. Existing policy-only confirmation refuses active execution
until a separate concurrent standing admission contract is implemented.

The explicit developer upgrade requires exact captured-cancellation storage,
ordinary pause/suspension/quiescence, validates original roots, preserves rows and
receipts, adds the canonical UTC fresh-read barrier and replaces only dispatch
guards. It stays suspended/unset; older profiles retain their no-resume contract.
No activation command, runtime caller, auto migration/repair or lab authorization
is introduced. Older code refuses this new profile. Before eventual non-disposable
migration retain a checked private SQLite-safe backup and compatible code/config;
never delete evidence or restore enabled policy to force downgrade.

Added 55 disposable actual-admission/claim cases: 16-member portions, concurrent
duplicate keys, strict literals/revisions/evidence/profiles, capacity/backoff,
cutoff/default gates, device serialization, typed outcomes, protection and queued/
running cancellation, exact deferral, unknown lease recovery, pruning/restart,
resume barrier, schema preservation and late audit/clock/lease rollback. Final
review also made a device-level unknown block other IPs on that device and bound
job creation time to its original delegation for claim/retention. First new suite
passed 53 tests (3.44s); final focused new/legacy restoration run passed **109
cases (5.16s)**. Earlier focused bulk result/wait/protection regressions passed
135 cases (7.94s). First full suite passed **1736 cases (182.43s)**; final full
run after the last two guards passed **1738 tests (187.06s)**. Compileall/Ruff/diff
and all 196 changed/new-document local links/anchors pass. Browser assets, Rust
and Compose are unchanged; their separate suites were not rerun. Updated normative
architecture, working plan, status and manuals.

No `.env`, inventory, credential, live schema/data/profile/gate, binary RPC, Rust,
Compose/network, service rollout or FTD operation was changed. No backup/restore
was needed on the unchanged lab. Runtime discovery/refill, continuous/per-device
parallel scheduling, automatic uncertainty convergence, concurrent policy/cleanup,
nonempty conversion and Web exposure remain follow-up integration work.

## 2026-10-22 — Bounded bulk refill through the existing Synchronizer

Added a default-disabled version-2 discovery/refill controller to the existing
snapshot/session scheduler. It creates no executor, schema, authority or activation
path. Under the shared lease/write transaction it checks at most 64 policy rows,
admits at most 16 new jobs across all cycle snapshots/devices and applies a 16-job
per-device unfinished-work window, counting independent mutations. Atomic source
admission retains all identity/revision/root/evidence/protection/history/capacity
checks. Local scan hints/counters publish after commit; late failure rolls back
jobs and leaves hints unchanged. Capacity is an explicit held state, not eviction.

Bounded numeric keyset hints persist in memory across cycles and reset on managed/
protected revision or resume-barrier change. Restart rescans durable policy and
attempt evidence without replaying used snapshot/intent identities or renewing
requests. Retained last-admission times prioritize previously underserved devices
across restart. Status defensively reports sampled check counts and bounded
window/budget state, not total targets or verified progress percentages.

Synchronizer's separate internal bulk capability requires ADD/session support and
trusted profiles, and rejects mixed legacy restoration/cleanup modes. Pending/
status/claim use that capability consistently; the old flag cannot mark bulk work
executable. Successful initial/priority/final complete reads feed discovery; old
cutoff/session budget/global lease/cooldown remain unchanged. Missing optional
profiles show controller failure/skip mutations without migration while per-device
read timestamps remain visible. Newly discovered ADD still waits for a later
eligible cutoff. No deployed environment setting or Web activation was added.

An expired/disabled QUEUED bulk delegation is now CANCELLED as unsent rather than
FAILED as a fictitious CLI result; old failed/unknown latches are not rewritten.
A separate fresh eligible attempt can satisfy still-enabled standing intent only
after original backoff/evidence checks. Device-level unknown still blocks bulk
ADD, including legacy read-only RECONCILED_ABSENT: observation alone cannot prove
RPC quiescence. Dispatch-profile retention preserves those jobs and linked
requests; age/read/restart never clears the barrier. Older schema-compatible
writers may not honor the new barrier, so downgrade requires capabilities off,
ordinary pause and compatible code/checked recovery, not schema recognition alone.

Added 34 disposable refill cases, including actual existing-scheduler creation of
36 managed entries and restoration after synthetic disappearance, bounded scans/
windows, large present-prefix progress, epoch/reset/restart/device fairness,
current controls, capacity/late rollback, used-key avoidance, unsent expiry,
unknown/lost replies, legacy observational retention, strict config and missing-
profile reads without initialization. Focused new/admission/legacy-scheduler run:
**130 passed (11.10s)**. Full suite: **1772 passed (191.90s)**. Compileall/Ruff/diff
and all 203 changed/new-document local links/anchors pass. Browser assets, Rust
and Compose are unchanged; their separate suites were not rerun. No installed-
image rebuild, rollout or actual FTD validation was performed. Architecture, structured manuals, working plan
and status updated. No live inventory/credential, database/schema, feature gate,
profile, environment, agent/RPC/Compose/network, service rollout or FTD operation
changed. No live backup/restore was needed. Continuous writes, parallel device
leases, automatic uncertainty convergence, concurrent policy/cleanup, legacy
nonempty conversion and Web activation remain pending.

## 2026-10-22 — Bounded agent workers and full-cycle device guards

Inspection found that independent API scheduling would still stall behind the
agent's serial accept/handle loop. Implemented that transport prerequisite first:
a fixed opt-in 1–10 connection-worker limit with default one inline handler.
Authenticated requests are assigned only to idle slots; active handlers have no
queued successors and no new per-client thread is spawned. Saturation returns
the original rejection and closes. Initial IPC budget includes assignment delay;
expired assignments do not read/dispatch packets. Canonical environment validation
and check-config output are covered without binding a listener or opening SSH.

All semantic requests now use inventory-bounded try-lock guards, shared across
IDs with the same management address. Guards span SSH/verification and full-cycle
final snapshot/disconnect; duplicate/poisoned/unknown/disabled devices reject
before SSH. A panicking worker stops without replacement and poisons its held
device, preserving fail-closed behavior while other workers/devices continue.
Fixed worker threads explicitly enter the existing Tokio context before timer/
SSH future construction; the main runtime continues driving their asynchronous
I/O. Local tests check timer progress as well as actual dispatch on socket pairs.
No new opcode/status, arbitrary CLI, retry authority, credential exposure, timeout
relaxation or feature/profile enablement. Rejection is never an exact pre-write
deferral. Guards are process-local; restart never clears durable API uncertainty.

Added concurrency unit/socket/timer tests and an isolated preflight process case
for default/valid/invalid settings and unchanged ADD dependencies. Initial sandbox
test execution passed pure cases but two local socket fixtures hit EPERM; the
same local-only suite was rerun with socket-capable permissions, not lab/network
access. Final Rust tests: **57 passed** (52 unit plus 5 isolated process checks),
including 10 new concurrency/configuration cases. Rustfmt, Clippy with warnings
denied and locked release build pass. Full Python suite: **1772 passed (189.49s)**;
compileall/Ruff/diff and all 212 changed/new-document local links/anchors pass. Browser
assets and Compose are unchanged; their separate suites were not rerun. No actual
multi-FTD/load/production acceptance was performed. Updated architecture, operator/contributor manuals, status,
working plan and tracked .env example with the serial default.

No lab environment/inventory/credential, optional schema/migration, DB data,
feature gate/profile, Compose/network, image/service or FTD operation changed.
No live backup/restore was needed. Retain matching prior agent/configuration and
checked SQLite-safe backup for eventual reviewed rollout/rollback; settle RPCs
and preserve original unknown jobs rather than replaying or clearing latches.
The API global lease/cooldown/device loop is unchanged: this is not end-to-end
parallel dispatch, production capacity acceptance or permission to opt in on FTD.
Independent API device scheduling remains the next integration.

## 2026-10-22 — Fenced per-device API leases over the shared queue

Implemented an explicit optional profile after exact bulk dispatch storage, with
immutable configured device scope/concurrency and retained per-device executor
rows. Initialization requires ordinary pause/desired suspension, settled global
and device execution, no pending/unknown/captured wait, enabled existing devices
and full original-root validation. It preserves policy/receipts/attempts and never
resumes policy or grants work. All DDL/rows/sealing/checks roll back together,
including caught caller-owned transactions. Exact expected-profile construction
uses an in-memory dummy global trigger target only, not live queue initialization.

Claims use canonical worker UUIDs and strictly increasing epochs with 5–300-second
deadlines and an atomic 1–10 owner quota (default four). Same-device contention
returns no token. DeviceOperationQueue binds a token to the existing jobs and
shared admission/discovery/claim/result/deferral paths; it does not create a
second queue/executor or project owners into the legacy global row. Wrong device,
old nonce/epoch or expired deadline refuses ADD/REMOVE results, exact deferral,
renewal/release and late transaction completion. Queue running/result/deferral
audit retains actual request identity and adds the current executor fence only
where it actually owns that device; cross-device revocation is not misattributed.

Expiry never steals/replays: atomically mark only the expired device's RUNNING
jobs UNVERIFIED through the original journal/wait-settlement hooks, then retain
the captured lease as immutable ATTENTION. Read-only expiry also holds because
the RPC may still run. Other devices' RUNNING work is untouched. Missing original
evidence rolls back recovery, not reconstructing success. Age, restart, read-only
status, retention or capacity pressure cannot clear attention. Release refuses
RUNNING work; renewal cannot revive a previously expired deadline. Old global
owners are DB-blocked, and offline quiescence/desired resume cannot ignore a
device lease/attention. Global pause/revision/old cooldown remain unchanged.

Added 45 disposable cases covering true concurrent shared-queue owners, quota/
same-device races, reused-nonce epochs, wrong-device/expired ADD/REMOVE/deferral,
in-flight cancellation/protection/settlement, immutable read-only attention,
retention/restart, missing evidence/profile, original-root preservation, old-writer
exclusion, current epochs in audit and late schema/audit/clock rollback. Final
new suite: **45 passed (3.54s)**; earlier new/admission/discovery/serial scheduler
regressions passed **173 cases (13.74s)** before the last two guard cases. Full
suite: **1817 passed (191.80s)**. Compileall/Ruff/diff and all 220 changed/new-
document local links/anchors pass. Agent, browser assets and Compose are unchanged
in this increment; their separate suites were not rerun. No installed-image
rebuild, live migration/rollout or FTD validation was performed.
Architecture, structured manuals, working plan and status updated.

No lab DB/schema/profile migration, environment/gate/credential, runtime worker,
agent/RPC/Compose/network, service rollout or FTD operation changed. No live
backup/restore was needed. Before eventual approved migration keep a checked
SQLite-safe backup and matching code/configuration; never drop fences/attention,
reset epochs or restore enabled policy to force downgrade. Automatic RPC-quiescence
proof, parallel Synchronizer integration, independent read timing/continuous
dispatch, concurrent policy/cleanup and legacy conversion/Web activation remain
separate next work. No simultaneous-FTD or production acceptance is claimed.

## 2026-10-22 — Actual bounded parallel sessions over fenced device queues

Added a default-disabled internal ParallelSynchronizer round coordinator, not an
API/startup/environment selector. It validates exact existing sealed inventory
scope and declared matching agent capacity before any claim/RPC. Independent
Synchronizer contexts reuse the actual semantic collector, typed session/results,
shared job/attempt journal, protected removal and exact deferral paths. The only
serial-collector changes are a device-selection hook and stop-at-next-mutation
checkpoint. Legacy scheduling/cooldown behavior is unchanged. No second job
executor, fabricated actor or global-owner projection is used.

Local session slots and transactional fences bound active work; a slow device
does not block others. Per-device cutoffs freeze before initial read; fresh-read
discovery admits at most 16 jobs/checks 64 rows per device session with the existing
16-job unfinished window and global capacity. New discovery waits for a subsequent
round. Persistent in-memory cursor hints remain non-authoritative. Successful
rounds release device leases independently from the legacy global read cooldown;
there is no new automatic background loop or independent poll deadline yet.

Public cancellation requests drain rather than cancelling to_thread: retain the
current RPC/verification and session-completion slot, stop waiting devices and
new mutations/discovery, settle typed results, then rethrow cancellation. Repeated
cancellation joins the same drain. RPC failures retain the fence even on read-only
work; expiry uses original device-only uncertainty/immutable attention, never
stealing or replay. Final-read failure preserves earlier verified results; late
results cannot override expired fences. Forced internal/event-loop cancellation
marks the coordinator broken instead of spinning/admitting replacement RPCs.
Declared RPC bounds must fit the operation limit; orderly shutdown must be awaited
before event-loop closure. Detached local status never performs recovery or
claims successful Web freshness. Individual workers do not race retention passes.

Added 30 disposable runtime cases: real blocking fake-RPC overlap/quota, healthy
device progress, scope/capacity refusal without writes, actual shared ADD/protected
REMOVE outcomes and original source preservation, exact deferral, failed open/
ADD/final read, lease expiry, repeated cancellation during open/ADD and forced
shutdown holds. Focused new/lease/serial-refill suite: **109 passed (12.33s)**.
Full Python suite: **1847 passed (195.89s)**. Compileall, Ruff, diff and all **213
changed/new-document local links/anchors** pass. Rust, browser assets and Compose
are unchanged in this increment; their separate suites were not rerun. Architecture,
structured runtime/lease/development manuals, working plan and status updated.

No optional DDL/migration, lab policy/fixture/gate/profile, credential/inventory,
agent/wire/Compose/network, image rollout, service restart or FTD operation changed.
No live backup/restore was needed. Preserve a checked SQLite-safe backup and
matching code/configuration before any separately approved migration; never erase
fences/uncertainty or revive policy to downgrade. Actual agent END/device-guard
settlement, continuous service dispatch/read-demand timing, urgent REMOVE/Web
integration, automatic quiescence-backed convergence and legacy activation remain
next. No simultaneous-FTD, throughput or production acceptance is claimed.

## 2026-10-22 — Continuous internal device dispatch, coalesced reads and quick unblock

Added a default-disabled explicit ContinuousDispatcher lifecycle over the existing
parallel session runner, not a new job executor or application/env/Web activation
path. Factored the existing per-device visit for use by both bounded rounds and
independent continuous scheduling; serial scheduling remains unchanged. Exact
existing fixed scope, declared agent capacity, local task limits and transactional
device ownership/epochs still apply. Healthy devices can start another bounded
session without a fleet barrier or global minute-long cooldown; idle devices are
not reconnected just because another has pending work. Per-device/global capacity,
16-mutation sessions and fresh-evidence ADD cutoff/authority/results remain.

Independent monotonic baseline/manual demand preserves original pending deadlines
across repeated hints and is satisfied only by a complete successful current read,
including mandatory/in-flight reads. Due demand joins legal existing checkpoints,
after current command verification and within original budgets, or remains pending.
Read-only detached status exposes pending/active/countdowns/revision and explicit
runner execution mode without becoming a new HTTP freshness contract. Restart
requires fresh baseline evidence. Generic work hints only wake the loop; actual
protected/control resume changes trigger fresh scoped policy checks. One-second
queue fallback avoids requiring a hint for already committed work. Dispatch sequence
rotation provides same-class fairness even when the test clock does not advance.

Only the explicit scoped queue capability prioritizes FIFO REMOVE over ADD,
including already admitted REMOVE beyond the frozen ADD cutoff. Original role/
expiry/cancellation/pause/device/isolation/source/fence checks remain. The agent
verifies target state rather than accepting initial-snapshot absence as NOOP: an
earlier ADD/external command may have changed it. Protection enabled during a
running ADD permanently retires original managed authority; after typed completion
the original trusted-policy path admits its removal for the next slot. Complete
final reads also capture protected targets without waiting for baseline. This is
not new v2 ordinary/combined user admission; tests with pre-admitted requests are
explicit synthetic fixtures, not Web identities or lab seeding permissions.

Failed/contended/exact-deferred work uses short five-second rescheduling, not a
busy loop, global cooldown or unknown-write retry. Known results and original
uncertainty survive; lease expiry still retains attention and never steals.
Ordinary stop and repeated caller cancellation drain current RPC/verification/
session completion and prevent further admissions/mutations. Forced internal
cancellation marks the coordinator broken and refuses replacement/restart.

Added 29 disposable cases covering actual multi-session imports without advancing
clocks, slow/healthy independence, idle wake isolation, coalesced/separate timers,
in-flight reads/checkpoints, post-cutoff quick REMOVE/current absence verification,
protection during ADD, strict roles/expiry/cancellation/FIFO, pause, exact deferral,
lost results, restart, detached status and orderly/forced shutdown. Final focused
new/legacy scheduler regression: **173 passed (23.29s)**. Full Python suite:
**1876 passed (200.24s)**. Compileall, Ruff, diff and all **239 changed/new-document
local links/anchors** pass. Rust, browser assets and Compose are unchanged in this
increment; their separate suites were not rerun. Architecture,
structured manuals, working plan and status updated.

No optional schema/migration, application startup/environment gate, lab policy/
fixture/credential/inventory, agent/wire/Compose/network, image rollout/service
restart or real FTD operation changed. No live backup/restore was needed. Before
eventual approved migration preserve a checked SQLite-safe backup and matching
code/configuration, drain old writers and retain all fences/original unknowns;
never reset epochs, erase attention or revive policy to downgrade. Agent END/
guard-release settlement, automatic quiescence-backed recovery, concurrent user
admission/cleanup, application/Web/maintenance integration and nonempty legacy
activation remain pending. No large executable-load, multi-FTD or production
acceptance is claimed.

## 2026-10-22 — Opt-in local cycle settlement after guard release and worker idle

Implemented explicit strict BEGIN `16 version device:u16` across existing cycle
versions 1/2/3 and a separate exact `00 version 16 end_sequence` terminal record.
Initial snapshots bind to opcode16/sequence0; END framing stays unchanged. Old
agents/bindings fail closed without fallback/reconnect/repeated writes. Legacy
default packets, existing gates/profiles, budgets and verification remain. There
is no arbitrary CLI/interface/route field or new request-selected authority.

Strict disconnect cleanup must succeed within its existing two-second bound.
Cycle resources and device/address guards are dropped before a typed completion
object reaches the pool's IDLE boundary. Only its bounded local postamble sends
the receipt, once/nonblockingly, then closes the FD: no SSH/CLI or slow-peer wait.
Completion panic stops the worker instead of replacing it. The inline serial path
finalizes after handler return. Closed/pressured peers can lose proof and emit
agent.cycle.settlement_failed, never a guessed success/retry. One new assignment
may wait only for the local postamble, not behind an active semantic handler.

The explicit strict client returns/publishes final observations only after exact
receipt binding, within the original END deadline and at most five seconds after
complete snapshot reception. EOF, malformed/missing/truncated/oversized records
and cleanup failure retain the fence. Earlier verified ADD/REMOVE results remain
real; original attempts, unknowns, policies and incident latches are untouched.
Local settlement is not remote TCP/quiescence, process liveness, future capacity
or lost-write resolution. The internal continuous dispatcher now requires strict
client capability and cycle proof; default serial/round clients stay legacy.

Added 37 Python cases with real temporary SeqPacket fixtures/shared vectors:
strict versioned snapshots, delayed/missing/wrong proof, old-agent/legacy-binding
refusal, original deadline, explicit capability/opt-out denial, withheld final
callbacks/lease release and preserved verified ADD. Added six Rust cases for the
same vectors/budgets/gates, failed cleanup/binding, guard/IDLE-before-completion,
stopped completion panic, closed peers and 100 immediate same-device handoffs
without retry/yield. Full Python: **1913 passed (200.86s)**. Rust: **63 passed**
(58 unit, five process-isolated configuration cases). Rustfmt, all-target Clippy
with warnings denied and locked release build pass. Focused protocol/controller
regression: **179 passed (16.18s)**. Compileall, Ruff, diff and all **254 changed/
new-document local links/anchors** pass. Browser assets and Compose are unchanged;
their separate suites were not rerun. Architecture, structured manuals, working
plan and status updated.

No live backup/restore, optional schema/migration, application/env/Web gate,
lab policy/profile/fixture, credential/inventory, Compose/network, image rollout,
service restart or FTD operation changed. Before eventual separately approved
activation preserve a checked SQLite-safe backup and matching images/configuration,
drain old writers and validate matching agent/client/scope/pool/timeouts. Rollback
requires explicit settled stop before returning to a compatible legacy pair;
never fallback on uncertainty, reset jobs, erase fences/attention or restore
enabled authority to force compatibility. Application/Web/maintenance integration,
concurrent v2 admission/cleanup, nonempty legacy conversion, automatic evidence-
based recovery and real FTD/multi-device/load acceptance remain. No production-
readiness or automatic historical-uncertainty resolution is claimed.

## 2026-10-23 — Continuous browser projection and independent refresh rendering

Added a separate read-only `ContinuousDispatcher.refresh_status()` projection and
owning-loop `request_activity()` for eventual API lifecycle integration. The
projection carries explicit per-device scheduling mode, independent pending/
active counts/deadlines, existing complete observations, stale/held errors and
concurrent semantic phases, without choosing a fake fleet cycle or exposing
internal executor ownership. Aggregate confirmation uses the oldest observation
only when all enabled devices have one. Disabled inventory stays visible but does
not contribute to demand/deadlines. Missing/disabled storage is never initialized
by status. Stopped coordinators refuse demand. Thread-safe committed-state
notifications update browser revisions without scheduling/admitting device work.

Extended the existing BFF metadata allowlist and browser renderer: continuous
demand remains clickable during other device work or cooldown, except for the
current HTTP submission/unavailable controller; repeated requests coalesce at the
original deadline. Status indicators show pending counts/attention and details
show independent schedules, held failures and actual active phases. Eligibility
countdown expiry alone does not confirm data or change its revision; genuine
healthy-device updates replace content while preserving dirty fields/open menus.
Existing serial runtime behavior, authentication, CSRF and no-store remain.

Validation: **1921 Python tests passed (207.54s)** on the final tree. Added seven
controller/projection cases and a second BFF contract mode. Focused controller/BFF
regression: **39 passed (12.12s)**. Real Chromium: **31 passed (94.26s)**, including
new independent-demand, repeated-click, held-warning, no-timer-success and actual
revision-driven update coverage alongside the legacy/mobile/frozen-review suite.
Compileall, Ruff, JavaScript syntax, diff and **257 changed/new-document local
links/anchors** pass. Architecture, working plan, structured manual and status
updated. Agent/Compose unchanged in this increment; no new protocol or schema.

No `.env`, credential/inventory, optional migration, gate/profile, image/service,
lab database or FTD operation changed. API startup still constructs the legacy
synchronizer; the new controller is not selectable through environment/HTTP.
No backup/restore is necessary for these additive code/browser changes. An eventual
approved runtime switch still needs version-aware user admission/cleanup,
lifecycle/retention ownership, checked SQLite backup, drained writers, compatible
schema/images/configuration and real transport/device acceptance. Do not select
the controller against a legacy lab profile, reuse consumed test authorization,
drop fences or clear historical uncertainty to make integration pass. Automatic
evidence-based uncertainty recovery and nonempty migration remain separate work.

## 2026-10-23 — Single continuous maintenance owner and shutdown drain

Added `ContinuousMaintenance` and tied its lifecycle to the internal continuous
dispatcher after existing profile/capacity validation. Exactly one task per
controller serializes startup/five-second ordinary expiry and startup/daily
queue-then-history retention with the established configurable 366-day period
(literal 1..3653). SQLite work runs off the event loop, not in competing device
worker purges; one API lifecycle owner is still required, not distributed leader
election. Same-instance restart retains the daily schedule. Disabled construction/
status/start and missing storage do not initialize the database or optional state.

Reused original expiry/prune transactions and evidence holds. RUNNING/UNVERIFIED,
captured predecessors, linked requests, immutable attempts/cancellation receipts
and v2 absence barriers survive ordinary retention. Malformed held references
refuse queue deletion and skip the history stage. Expiry retains original unsent
ordinary/bulk result semantics and never invokes an agent, creates authority or
replays unknown work. Queue/history transactions remain separate; a later-stage
failure cannot masquerade as complete success or rollback of an earlier commit.

Expected errors have independent 60-second backoff, bounded structured logging
and detached browser-visible metadata/warnings while healthy monitoring continues.
Only actual queue revision/history changes publish browser data updates. Normal
stop prevents new stages and drains both synchronous SQLite work and device RPCs;
repeated stop-caller cancellation cannot start replacements. Forced internal or
unexpected task failure marks the owner broken and stops replacement execution.
Store locking bounds remain, not an invented hard whole-purge deadline.

Validation: **1941 Python tests passed (209.76s)**. Focused continuous lifecycle,
BFF, ordinary queue, bulk attempts/captured waits and legacy synchronizer regression:
**165 passed (19.07s)**. Added **20 cases** covering no-create/default-off/literal
configuration, cadence/restart, unchanged data revisions, actual expiry/uncertainty,
staged failure/backoff, repeated/forced cancellation, slow-maintenance independent
device reads, shared shutdown, visible errors/unexpected failure and real retained
bulk evidence/corruption. BFF metadata tests retain auth/CSRF/no-store/allowlist
coverage. Compileall, Ruff, diff and all **264 changed/new-document local links/
anchors** pass. Agent, browser assets and Compose are unchanged in this
increment; their separate suites were not rerun.

Updated normative design, working-version plan, structured maintenance/development
manuals and current status. No schema/DDL, environment selector, optional migration,
live gate/profile/fixture, inventory/credential, image/service restart, lab database
or FTD operation changed. API startup remains legacy. No live backup or restore
was needed; eventual separately approved activation requires a checked SQLite-safe
backup, drained old owners and matching compatible schema/images/configuration.
Retention deletion is irreversible without a backup. Runtime rollback must drain
maintenance and device sessions; never erase evidence/fences or revive retired
authority. Version-aware API runtime/admission/cleanup, nonempty legacy migration,
automatic evidence-based recovery and actual FTD/large-load acceptance remain.

## 2026-10-23 — Restricted continuous API composition, compatibility and Web controls

Completed three sequential integration tasks: developer API lifecycle composition,
existing-profile/settings/transport compatibility and actual capability-aware
Web/BFF integration. `create_app` accepts an explicit inactive continuous
dependency and constructs no serial synchronizer for that branch. ASGI lifespan
owns one dispatcher and its maintenance task, with original drain guarantees.
No environment/CLI/request selects this runtime; deployed defaults remain legacy.

The initial profile intentionally supports observations/history/search, independent
refresh demand, local preview and Protected-IP policy. ADD/bulk execution, old
admission and managed controllers must remain off with empty ADD scope. Strict
settlement, matching socket/deadline/large-read transport, existing fixed scope/
capacity, read-spacing floors, timer/retention agreement and completed durable
protection migration are checked without DDL or environment import. Startup
rechecks drift, refuses adopted running/duplicate application owners and never
falls back to a legacy/empty interpretation. Default legacy startup refuses device
fences before initialization. Protected readers and fenced workers explicitly skip
queue initialization while compatible legacy constructors retain their default.

Unsupported managed/import/manual mutation workflows return no-store 503 before
legacy handlers, rather than fake legacy context. Supported state failures report
unavailability without claiming committed edits rolled back. v2/capability metadata
passes through the authenticated BFF; unavailable navigation/removal/cancellation/
review controls are hidden and Status explains that protected automatic removal
and previously admitted REMOVE can still execute. Existing real-actor audit, CSRF,
typed-delete/revision checks and permanent protected-policy retirement remain.
Absent/null capability fields preserve legacy rendering. UI hiding is not the
enforcement boundary. No arbitrary CLI, identity trust or public listener changed.

Validation: **1978 Python tests passed (216.10s)**; focused API/legacy/parallel/
protection regression **146 passed (24.16s)**; real Chromium **32 passed (111.23s)**.
Compileall, Ruff, JavaScript syntax, diff and all **272 changed/new-document local
links/anchors** pass. Added 37 disposable Python composition cases plus a production-template Chromium
scenario: no-init factory/GET/first worker, mismatched settings/ownership/client/
scope/capacity, old/new startup rejection, duplicate ownership/schema drift,
actual ASGI/BFF lifecycle/status/demand/protection, auth/CSRF/audit and hidden
unsupported controls. An initial browser assertion selected the status submit
instead of the preview submit; the selector was scoped to the actual form and
rerun. The suite timeout accommodates its expanded scenarios; individual request/
assertion bounds were not relaxed. Normative design, working plan, structured
manuals and status updated.

No lab DB, optional migration/schema, live gate/profile/fixture, `.env`, inventory/
credentials, Compose/network, image/service restart or FTD operation changed.
Agent/wire unchanged in this packet; no live/production acceptance claimed. The
factory deliberately requires already loaded inventory and has no environment
activation path. No live backup/restore was needed; eventual approved rollout
requires checked SQLite-safe backup, drained old owners, matching schemas/images/
configuration and scoped transport/device validation. Fenced storage cannot be
downgraded by deleting its guards or clearing uncertainty/retired policy. General
v2 admission/cleanup and policy views, configured runtime/inventory selection,
nonempty legacy migration, automatic evidence-based recovery and real multi-FTD/
load validation remain separate work.

## 2026-10-23 — Bounded v2 policy views and frozen policy-only retirement

Completed three connected tasks on the explicit continuous developer composition:
readonly bounded policy/evidence projection, distinct private v2 routes/dedicated
Web page, and exact one-target policy-only stop-maintaining with frozen review.
Readonly SQLite snapshots bind revision/rows/evidence; at most 100 rows/pairs are
projected from the existing 200000-key capacity. Missing/partial state or changed
revision is explicit unavailability/conflict, never empty/legacy fallback or
silent membership rebase. Bulk authorization payload is loaded once per distinct
request, rather than duplicated for every returned target.

The page separates desired support, observations and actual retained ADD outcomes;
original author/generation, protection, disabled devices, pending work and failed/
unknown evidence remain visible. VERIFIED alone supplies an application time;
NOOP/presence/missing unknown evidence never invent creation. Metadata/capabilities
pass through authenticated/no-store BFF and refresh Status without hiding errors.
Paged membership updates preserve drafts; changed pinned scope removes stale
preparation controls and offers an explicit current-policy link.

Retirement uses existing atomic v2 policy/audit/immutable receipt semantics with
current Operator/Administrator authority, CSRF and typed-IP confirmation. Reviews
freeze policy format alongside actor/session/target/generation/revision/key. A v2
failure never retries v1; a malformed/lost receipt is unknown and permits only
same-key retry. Optional status failure cannot negate a checked durable receipt.
Old keys never retire a newer grant. Retirement does not admit a device operation,
cancel independent jobs, interrupt RUNNING ADD, resolve uncertainty or resume work.
Existing standing-claim guards and protection independence remain authoritative.

Validation: **2008 Python tests passed (223.42s)**; focused policy/API/BFF/legacy
control/registry regression **129 passed (12.64s)**; real Chromium **33 passed
(103.03s)** including new bounded v2 page, draft/focus/pinned-revision/mobile/
escaping checks. Compileall, Ruff, JavaScript syntax, diff and changed/new-document
local links/anchors pass. Agent/Compose unchanged in this packet; their separate
suites were not rerun. Added 19 readonly projection cases and 11 API/BFF cases.
Early test-only assertions used a
legacy receipt phrase or compared SQLite's integer flag with a Python boolean by
identity; corrected those assertions. A full preliminary run identified the old
exact route inventory assertion; updated it to include v2 and verify all three
routes refuse the legacy runtime without storage changes.

Updated normative architecture, working plan, current status and structured
manuals. No new DDL, optional migration, gates/profile, `.env`, secrets/inventory,
Compose/network, live database, image/service restart or FTD operation changed.
No live/production acceptance or lab authority implied; no live backup/restore was
needed. A future approved rollout needs checked SQLite-safe backups, drained
owners and matching images/configuration; preserve retired policy/receipts/fences
and uncertainty on rollback. General v2 write admission/combined removal, configured
runtime/inventory, nonempty migration and device/load validation remain separate.

## 2026-10-23 — Ready-only v2 removal scope and atomic continuous-queue coordination

Completed three sequential backend tasks: exact readonly scope inspection,
default-false whole-scope retirement/REMOVE coordination and actual continuous
worker integration tests. Single/fleet scope binds version/mode, IP, managed/
protected revisions, original target intent/generation/authorization/revision,
device metadata, observations and protection in one readonly SQLite snapshot.
Fleet union retains missing managed and disabled/out-of-executor devices;
observed unmanaged members are cleanup-only. A separate semantic digest binds
ready-only action, 1..900-second lifetime and bounded reason. No input commands,
fresh-observation claims, GET initialization or adoption.

Admission rechecks the complete scope under one write lock, requires real
Operator/Administrator and explicit internal capability on existing fenced
storage, and rejects pending/failed/unknown ADD, overlapping work, device unknown
outcomes and attention/expired fences. Ready-only never silently becomes ordered
waiting or cancels/replays ADD. One transaction retires all enabled matching
policy, admits one whole-scope shared manual REMOVE request, retains one immutable
action/receipt and appends real-actor audit. Existing request storage/reserved
retirement budget is reused, not new DDL or per-device coordinator loops.

The queue has a separate literal default-false ready-removal composition hook;
scope labels alone do not bypass legacy managed guards. Existing role/isolation/
pause/rate/backpressure, cutoff/lease/typed results and settlement remain. Pin
queue expiry to original admission time, check clock and fences again after late
validation, and roll back policy/queue/receipt/audit together on any final failure,
including when a caller catches an exception and commits the outer transaction.
Accepted logs follow commit only. Original-key replay survives terminal pruning
without new jobs, TTL renewal, newer-policy retirement or unknown-operation replay.
All retained bulk managed-request keys remain unavailable for new queue work.

The explicit continuous API adds readonly scope GET only; all v2/legacy removal
admission POSTs are refused. No Web execution control or live gate is wired. New
synthetic sessions actually dispatch the coordinator's shared jobs independently
of baseline polling, yielding verified removal through the existing worker rather
than hand-seeded successful history. Distributed FTD writes are not atomic:
individual outcomes/uncertainty remain independent after atomic admission.

Validation: **2049 Python tests passed (227.66s)**; focused scope/queue/bulk
journal/dispatch/API/legacy/maintenance regression **248 passed (18.51s)**.
Added **41 cases**. Compileall, Ruff, diff and all **294 changed/new-document
local links/anchors** pass. Agent/browser/Compose unchanged; their separate
suites were not rerun. Early test-only assumptions used a
nonexistent pruning method and treated the semantic fake's distinct-device set
as a session counter; corrected these to actual `prune_completed` and trace opens.
Normative design, working plan, current status and structured manuals updated.

No new schema/migration, gates/profile, `.env`, inventory/credentials, Compose/
network, lab database, service/image restart or FTD operation changed. Agent and
browser assets unchanged in this packet; no live/production acceptance claimed.
No live backup/restore was needed; any future separately approved migration/runtime
rollout requires checked SQLite-safe backups, drained owners and compatible
images/configuration. Never delete evidence/fences or revive retired authority
to force rollback. Frozen Web/gated admission, captured RUNNING-ADD ordering,
automatic recovery, concurrent grant/import intake, configured runtime/inventory,
nonempty legacy migration and real multi-FTD/load validation remain separate work.

During full regression, an existing maintenance test exposed a fake-clock race:
its thread-entry counter could advance before the asynchronous completion had
published the next expiry deadline. Advancing the clock by a day at that point
skipped the test's expected intermediate expiry. The isolated case passed, but
the ordering was genuinely nondeterministic. The test now waits for idle and the
published +5-second deadline before advancing time; no production timer or test
timeout/assertion bound was relaxed. The first full run had 2048 passes and this
one timing failure. The corrected case passed five further consecutive runs;
the repeat full suite passed all 2049 tests as recorded above.

## 2026-10-23 — Independently gated v2 ready-removal Web/API confirmation

Completed three sequential integration tasks: independent trusted API/Web factory
capabilities, strict fixed private ready-removal admission and frozen browser
review/confirmation with actual end-to-end synthetic execution. Both literal
capabilities default false; no environment/CLI/HTTP/status/DOM selector or legacy
cleanup switch enables them. Legacy API enablement refuses before initialization;
Web enablement requires socket/session/large-read and production identity handling.
Existing continuous preflight, disabled ADD/import/legacy gates and fixed agent
boundary remain unchanged. No optional startup/GET initialization or new DDL.

Dedicated device/fleet preparation forms read only compatible v2 scope/status,
validate exact readonly descriptors/digests and freeze canonical action/scope,
original authority/revisions, reason/lifetime, real subject/CSRF cookie, expiry
and UUID. Separate immutable cache retains <=5 reviews per subject/256 total for
<=10 minutes/the shorter configured age. Forged scope/action/gate fields and
cross-purpose tokens refuse. Disabled devices stay visible; ready-only never
silently becomes RUNNING-ADD waiting or partial fleet admission. Confirmation
rechecks current roles, CSRF, typed IP and ownership/expiry, including after
status I/O, then uses only the frozen v2 route and original key.

The API enforces bounded literal models, exact route mode, sensitive TTL and
independent capability before invoking the existing atomic coordinator once.
Disabled v2 endpoints refuse before body/legacy dispatch. Accepted/replayed
responses are HTTP 202, not verified removal; publish/wake occurs after commit.
BFF validates original scope/counts/revision, action/version/mode, unique canonical
device/job IDs, UTC expiry and explicit no-verification flags. Lost/malformed
responses remain unknown with same-review/key retry only. A valid durable receipt
survives a later optional status error. Native confirmation does not auto-submit;
metadata updates preserve frozen scope/token/typed IP/focus. New UI keeps existing
escaped text, local-zone timestamps and responsive scrolling/spacing.

Validation: **2072 Python tests passed (228.74s)**; final focused v2/API/BFF/
backend/legacy/refresh regression **183 passed (18.01s)**. Real Chromium passed
**34 tests (112.82s)** including new
default-off/enabled confirmation display, immutable fields, no automatic writes,
escaping and desktop/375px layout. Compileall, Ruff, JavaScript syntax, diff and
all **306 changed/new-document local links/anchors** pass. Agent/Compose unchanged;
their separate suites were not rerun. Added 23 Python cases and one browser
scenario. A first full run found a historical exact fleet-route inventory missing
the new v2 POST (2071 passes/one assertion failure); updated that expected set,
preserving the no-optional-initialization/default-off assertions.

Normative architecture, working plan, status and structured manuals updated.
No schema migration, `.env`/Compose/network, inventory/credentials, lab gate/profile/
fixture, database, image/service restart or FTD operation changed. Agent/wire
unchanged; no live/production acceptance claimed. No live backup/restore was
needed. Future approved rollout requires paired matching API/Web/assets, checked
SQLite-safe backups/configuration and drained old owners. Disabling admission
does not cancel previously committed jobs or resume retired policy. Preserve
receipts, original unknown outcomes and fences on rollback; never erase evidence
or restore enabled authority to force compatibility. Ordered RUNNING-ADD cleanup,
concurrent grant/import intake, configured runtime/inventory, nonempty legacy
migration and actual multi-FTD/load/recovery acceptance remain separate work.

## 2026-10-23 — Read-only v2 ordered-removal preflight

Continued the working-version removal sequence with a separate local inspection
component, not implicit conversion of the shipped ready-only action. Documented
the normative boundary first. `BulkOrderedRemovalScopes` reads the complete
one-IP single/fleet union in one SQLite `mode=ro` transaction on existing exact
fenced v2 storage; it never initializes or writes. Results distinguish READY,
WAITING_ADD and BLOCKED, with global pause and explicit per-device pending,
failed/unknown, disabled/out-of-scope, clock and executor-fence blockers. One
blocked member blocks the whole fleet rather than shrinking it.

Only an exact current system RUNNING ADD can supply a proposed predecessor.
Validate original request/job/link/attempt, current intent/generation/authority/
target revision, canonical UTC snapshot/request/start/deadline and a unique
bounded original claim-audit receipt matching owner/epoch, actor, action, source
and device/IP. Duplicate device streams, old epochs, missing/duplicate/malformed
claims or contradictory pending evidence cannot be treated as safe waiting.
Retain original deadlines/identities in the descriptor and separately hash the
raw original evidence and complete observational preflight. Digests cannot become
ready-removal confirmation or a future admission grant.

Synthetic coverage uses actual shared queue admissions/claims/results and two
parallel device tokens. It checks snapshot consistency across concurrent ADD
completion, all VERIFIED/NOOP/FAILED/UNVERIFIED/deferral outcomes, missing evidence,
unrelated device uncertainty, exact replay-free readiness, detached descriptors,
scope/epoch/deadline/audit refusal and byte-for-byte unchanged storage. Test
corruption touches disposable fixtures only, not retained operational audit.
Final validation: **2114 Python tests passed (232.57s)**; focused ordered/ready/
lease/settlement regression **159 passed (13.13s)**, with **42 new cases**.
The earlier full run passed 2113 tests before the last duplicate-stream case was
added; the full suite was rerun on final code. Compileall, Ruff and tracked/new-
file whitespace checks passed, with changed/new-document local links/anchors
validated. Agent/Compose/UI assets did not change in this packet, so Rust and
Chromium were not rerun.

No queue/API/Web/agent caller or schema/configuration changed in this packet; no
HTTP route, admission method, migration, audit write, reservation, retirement,
executor, feature activation, lab database/image/service or FTD command was added
or invoked. No live backup/restore is needed. Removing the unused local component
is a code-only rollback with no new durable state. Existing ready-only
confirmation, authorization/uncertainty and deployment boundaries are unchanged.
Next: explicitly reviewed durable whole-scope ordered barrier/reservations,
retention and original-deadline accounting, atomic retirement and shared-worker
promotion before distinct frozen ordered consent or scoped live acceptance.
See [Ordered-Removal Preflight](manual/bulk-ordered-preflight.md).

## 2026-10-23 — Durable v2 ordered reservations and retained predecessor evidence

Continued after read-only preflight with a separate optional exact fenced v2
profile: two retained root/member tables, pair index and immutable/monotonic
triggers. Initialization is explicit/default-disabled, requires existing storage,
ordinary pause, desired suspension and settled quiescence, and is fully transactional
including late caught failure. No startup/read/admission caller initializes it.
Legacy/partial/unexpected objects are not converted or repaired.

Implemented a distinct canonical STOP_AND_REMOVE_ORDERED action binding the
complete frozen device/fleet union, exact original RUNNING predecessor identities,
claim/epoch/snapshot/deadline evidence, literal cleanup lifetime and bounded reason.
The internal default-false coordinator requires real Operator/Administrator and
reinspects everything under one write lock. It atomically retires all enabled
policy, reserves the entire cleanup scope and retains one immutable original
action/receipt plus actual-actor audit. No single-target loop, ready fallback,
scope shrink, ADD interruption or REMOVE job/request is used. Late audit/capacity/
clock/expiry/lease failure rolls back all state even if an outer caller commits.
Original-key concurrency/restart/replay never renews authority or resumes policy.

Integrated reservation target/request/rate accounting with the existing shared
queue. Held pairs exclude independent manual and ready-only work; quiescent
standing admission sees the reservation. Protected system removal remains
independent. Owner/Admin local cancellation and bounded expiry in existing shared
maintenance release reservations without changing the original ADD or re-enabling
maintenance. Local readonly status exposes individual predecessor outcomes and
honest missing evidence; no automatic promotion is present. WAITING_ADD remains
waiting even after all ADD results, pending a separate execution contract.

Both queue and audit retention now validate captured predecessor jobs, original
linked requests and original claim receipts before any deletion, holding those
references even after local reservation cancellation/expiry. Captured identities
remain immutable while ordinary verified/no-op/failed/unknown or exact-deferral
results settle. Missing/malformed held evidence refuses pruning; age/revocation
does not resolve uncertainty. Retained roots/descriptors/membership have explicit
limits; no eviction or automatic hold release is introduced.

Synthetic tests exercise actual shared claims/results, two parallel device ADDs,
whole-scope admission, late rollback, concurrent original-key replay, profile
migration/refusal, pause/default-off/strict-type boundaries, all result types,
revocation/expiry, queue budgets, grants/manual conflicts, protected independence,
and queue/audit retention with deliberately damaged disposable evidence. The
initial focused run found the old v1 guard preceding the new reservation guard;
reordered the new pair check without bypassing the existing legacy guard. Final
validation: **2163 Python tests passed (231.46s)**; focused ordered/preflight/ready/
dispatch/maintenance/Store regression **210 passed (16.82s)**, including **49 new
cases**. Compileall, Ruff and diff/whitespace checks passed; changed/new-document
local links/anchors were validated. Agent/Compose/UI unchanged, so Rust/Chromium
were not rerun. Two initially mistyped targeted filenames caused collection-only
failures before the correct existing test files were selected; final focused and
full runs are green.

Updated architecture, working-version plan, status and structured migration/
backup/rollback/development manuals. No live optional migration, database/secret/
inventory/Compose setting, gate/profile, image/service restart or FTD operation
was invoked. Agent/wire/UI unchanged. Real rollout still needs separately scoped
approval, drained old writers and checked SQLite-safe backups/matching images.
Older retention writers do not know these holds and must not touch the upgraded
profile. Do not restore enabled pre-retirement policy or erase evidence to force
a downgrade. Worker promotion/attention, original-TTL capacity transfer and frozen
ordered Web/API consent remain next; no lab/production acceptance is claimed.
See [Ordered Reservations](manual/bulk-ordered-reservations.md).

## 2026-10-24 — Whole-scope ordered promotion through shared continuous workers

Implemented a separate explicit additive promotion-ledger profile and default-off
local coordinator, after documenting the normative transition/settlement contract.
Old reservation/root/request receipts remain immutable; new decisions distinguish
internal ADMITTING, complete ADMITTED and retained ATTENTION. Initialization
requires existing exact ordered storage, pause, desired suspension and settled
quiescence including no active reservations. It is transactional/idempotent and
never invoked by startup/GET/admission; no old authority is renewed to migrate.

The coordinator rechecks complete frozen scope, retired identities/revision,
inventory, protection, captured ADD/request/claim evidence, independent work and
current fences. RUNNING or completed-but-unreleased original sessions wait.
VERIFIED/NOOP needs local epoch release/supersession; exact original typed pre-write
deferral may cancel captured unsent work only after session settlement. Failed/
unknown/missing/inconsistent evidence, unsafe fence or changed scope produces
whole-scope ATTENTION without partial REMOVE or rewriting ADD outcomes. Bounded
lookahead avoids slow-root starvation, with at most eight decisions per call.

One transaction transfers the original-key whole scope to one shared manual
REMOVE delegation, retaining immutable device/job references and actual-actor
audit. The separate literal queue capability/fixed scope/private live ticket
discounts only this root's reserved capacity and preserves original actor rate
position plus exact millisecond request/deadline. Late audit/clock/expiry/capacity
failure cannot commit partial jobs/links/decisions; concurrent promoters delegate
once. Accepted logs are emitted only after commit. Incomplete persisted tickets
cannot resume, expire or claim; claim requires a complete ADMITTED receipt.

Existing continuous ownership can explicitly compose the default-false
`ordered_promotion_enabled` factory capability, after readonly startup compatibility
preflight and before selecting device work. No second device executor/task queue,
environment/HTTP selector or wire change. Promotion-profile rounds require strict
local settlement. Waiting revocation/expiry cannot reinterpret already admitted
queue work. Attention remains observable after local revocation/age. Queue/audit
retention holds delegated REMOVE jobs/requests and original deferral receipts
alongside captured ADD evidence, refusing missing/inconsistent references rather
than manufacturing success.

Synthetic coverage exercises actual shared continuous REMOVE execution on two
fake devices, multi-predecessor/session barriers, healthy-root fairness, exact
deferral proof/corruption, unchanged TTL and once-only budgets/concurrency, partial
ticket claim refusal, late rollback, migration preservation/refusal, strict/default-
off compatibility and terminal replay/expiry/retention. The first async integration
test used an unavailable pytest-asyncio marker; switched it to the repository's
existing asyncio.run pattern without adding dependencies. Final validation:
**2199 Python tests passed (246.17s)**; focused promotion/reservation/continuous/
parallel/ready/Store regression **207 passed (33.07s)**, including **36 new cases**.
Compileall, Ruff, diff/whitespace and all **280 changed/new-document local
links/anchors** passed. Agent/Compose/UI unchanged; Rust/Chromium were not rerun.

Updated architecture, working plan, status and structured migration/backup/
rollback/development manuals. No live database/secret/inventory/Compose setting,
feature gate/profile, service/image or FTD command was changed; no lab migration
or fixture/production acceptance was invoked. Agent/wire/UI unchanged. Rollout
still requires separately scoped approval, drained old writers and checked
SQLite-safe backups/matching images. Disabling promotion does not cancel already
delegated jobs; do not erase evidence or restore enabled pre-retirement policy to
force downgrade. Frozen ordered Web/API consent/status, configured runtime/
inventory, nonempty migration and real transport/multi-device/load/recovery
acceptance remain. See [Ordered Promotion](manual/bulk-ordered-promotion.md).

## 2026-10-24 — Strict private ordered-removal API and current outcome projection

Added distinct fixed v2 private device/fleet ordered reservation routes on the
explicit continuous composition, behind an independent literal default-false API
capability. Admission requires the compatible strict-settlement owner, its separate
promotion capability and an already complete exact reservation/promotion profile.
Validate before lifecycle binding and again at startup. No constructor/GET/admit
initializes optional state, enables ADD or falls back to legacy/ready admission.
Readonly preflight still works with admission disabled and no optional ordered
tables, using the shared queue's explicit UTC clock on the exact base fenced profile.

Strict request models bind the original canonical scope, typed complete sorted
RUNNING predecessor/request/claim/epoch/deadline evidence, distinct digest,
actual Operator/Administrator actor, original UUID and bounded TTL/reason. The
existing coordinator reserves/retires the entire scope atomically; changed scope,
wrong mode/actor/digest, coerced fields or late audit failure admit nothing.
New commits notify the existing owner; immutable original-key replay reports the
historical WAITING_ADD receipt with replay marker, without renewing TTL or waking
work. No new executor, device operation or arbitrary CLI field was introduced.

Expanded local status with original frozen scope/requested-at, explicit original
delegated REMOVE job states and all-jobs-VERIFIED removal. ADMITTED is not success;
failed/unknown attention survives waiting revocation. GET does not promote,
expire, renew, hint device reads or mutate policy. A dedicated absent-root exception
keeps 404 distinct from malformed retained evidence (503). Fixed actor-only
owner/Admin cancellation works while paused/admission disabled, audits the actual
actor and cannot alter a RUNNING ADD, resume retired policy, clear uncertainty or
revoke already delegated work as waiting.

Added 40 synthetic SQLite/ASGI/fake-session tests covering independent/literal
capabilities and startup drift, optional-profile absence, exact device/fleet scope,
strict metadata/actor/mode/digest/TTL, same-key concurrency/lost-reply retry,
unchanged original expiry, late transaction rollback, truthful partial/completed
job status, absent versus malformed state, pause/disabled-mode owner/Admin
revocation and actual API-lifecycle/shared continuous fake REMOVE execution.
Initial focused failures exposed an incorrect test expectation: replay intentionally
changes only the response replay marker; corrected tests, not stored receipts.
Focused ordered/API/legacy regression: **241 passed (25.67s)**. Final full suite:
**2239 Python tests passed (255.23s)**. Compileall, Ruff, diff/new-file whitespace
and all **299 changed/new-document local links/anchors** pass.

Updated normative architecture, working plan, current status and structured
API/queue/profile/development manuals, including prerequisites, original-receipt
semantics, failure handling, backup/rollback and operating impact. This packet
adds no DDL or configuration selector. No real database, credentials, inventory,
feature gate/profile, services/images or FTD state was changed; no lab migration,
fixture authorization or production acceptance was consumed. Agent/Compose/UI
unchanged; Rust/Chromium are not required for this API-only packet. Frozen
session/CSRF-bound ordered Web consent/status, configured runtime/inventory and
separately scoped transport/multi-device/load/recovery acceptance remain next.

## 2026-10-24 — Frozen ordered Web consent, durable local status and waiting revocation

Implemented three sequential product tasks over the existing strict private API:
separate ordered confirmation, a current-status permalink and local waiting
revocation. Managed shuns exposes collapsed exact device/fleet preparation forms.
Validate the complete bounded preflight digest, mode/IP/device, literal counts,
dispositions/blockers and canonical RUNNING predecessor evidence. READY/BLOCKED
inspection creates no token or action/fallback. WAITING_ADD freezes original
scope/predecessors/action/digest/UUID/TTL/reason in a separate immutable detached
actor/CSRF-cookie-bound cache (five per subject, 256 total, <=ten minutes).

The new literal default-false Web factory capability cannot be enabled by DOM or
API metadata. Production identity/socket/cycles/large-read compatibility remains
mandatory. Confirmation accepts only CSRF/token/typed exact IP, rechecks actor/
role/session and expiry after metadata I/O, then requires the separate compatible
API admission and owning promotion capabilities. One fixed private device/fleet
request uses the original cached body/key and actual actor. Strict checked 202
receipts bind all historical flags/counts/revision and exact canonical original
requested-at plus TTL; unknown replies permit only original-review/key retry.
Later optional metadata failure cannot negate a checked reservation receipt.

The authenticated canonical-UUID status permalink survives Web restart and
validates complete original scope/owner/deadline, every captured ADD outcome,
retained attention and every original delegated REMOVE job. Only all VERIFIED
implies verified removal; ADMITTED or local revocation is not success. Added
bounded owner/predecessor-count metadata to the existing API projection, no DDL.
GET/passive updates read local evidence only: no expiry/promotion/policy mutation
or device read hint. Frozen confirmation is never replaced; dirty live-status
fields/focus/open sections survive refresh. Native exact-IP validation and existing
responsive form classes keep confirmation separate and usable on mobile.

Waiting revocation is a distinct CSRF/typed-IP owner/Admin fixed-UUID POST with
actor-only private input, available under pause/disabled admission and after Web
restart. It never resumes maintenance, changes a RUNNING ADD, clears attention or
cancels delegated work. Race to ADMITTED conflicts. Checked cancellation receipt
survives failed follow-up status without showing a stale snapshot as current;
lost/malformed cancellation response remains unknown and retries only that root.

Added 60 disposable SQLite/ASGI/fake-session tests for independent capabilities,
strict preflight/receipts/status, CSRF/roles/session/cross-purpose controls, cache
bounds/immutability/post-I/O expiry, stale scope, unknown replies/original-key
retry, restart, owner/Admin pause/disabled revocation, ADMITTED races, malformed
complete-scope job evidence and actual BFF/API/shared continuous fake execution.
Added two real Chromium scenarios for frozen ordered consent and dynamic local
status/dirty-form/attention/verification/mobile behavior without device demand.
The first focused run caught an over-broad test assertion: device-only retirement
must leave the independent second device's policy intact; corrected that assertion.
The first Chromium run caught a real shared focus-restoration bug: reopening a
details section after trying to focus its field silently loses focus. Reopen
preserved details first; the new browser regression covers this sequence.
Focused ordered Web/API/ready/continuous/reservation/promotion regression:
**256 passed (48.10s)**. Final full suite: **2299 Python tests passed (278.63s)**;
real Chromium **36 passed (132.40s)**. Compileall, Ruff, JavaScript syntax,
diff/new-file whitespace and all **313 changed/new-document local links/anchors**
pass. Synthetic fixture/session results are not live transport or production
acceptance.

Updated normative architecture, current status, working plan and structured Web/
API/profile/queue/development manuals with limits, unknown-result behavior,
operating impact and backup/rollback boundaries. No schema, runtime selector,
agent/wire, Compose, real database/credential/inventory/gate/profile, services or
FTD state changed; no lab migration/fixture/activation or production acceptance
was invoked. Rust is not required for this Web/API-only packet. Configured runtime/
inventory, nonempty migration, bounded managed import/adoption/cancellation and
separately scoped transport/device/multi-device/load/recovery acceptance remain.

## 2026-10-26 — Non-authoritative v2 preparation API and full retained-report integrity

Connected fixed private v2 draft create/list/page/proposal/cancel-preparation
routes to the explicit compatible continuous API composition. Reuse the existing
bulk-profile classifier/journal and shared queue UTC clock, not legacy registry
fallback. No constructor/startup/request initializes, repairs, migrates, prunes or
resumes optional state. An absent journal is explicitly uninitialized on owner
list inspection; malformed prerequisites are unavailable. The narrow interface
capability is distinct from readiness, standing confirmation and device execution.

Strict real actor/role/plain metadata, literal distinct enabled-device selection
and 1 MiB UTF-8/20000-line/10000-row limits retain the complete <=100000-pair
product, invalid/duplicate diagnostics and protected exclusions. No raw pasted
source/comments are stored. New `BulkPreparationReports` uses the same journal
without DDL, streaming the entire original header/member digest in <=100-row
chunks before runtime metadata/pages/cancellation. Same-count substitution fails
closed instead of showing a different successful scope. Proposal additionally
binds the retained expected digest, original canonical UUIDs and full classified
manifest, checks expiry/clock and remains a pure read without a root/key reservation.

Owner references survive restart/lost create reply. Reads retain original device/
policy/protection classification and deadline, never rebase or renew. Current
Operator/Admin governs create/proposal; any authenticated owner may inspect or
revoke only their unconfirmed draft after role loss/during pause. Confirmed draft
revocation/proposal conflicts without retiring policy, changing jobs or masking
original authority. Four-owner/sixteen-global retained bounds include expired/
cancelled records; concurrent capacity failures never evict or partially stage.
No request wakes/hints device work or changes policy/queue/origin/audit state.
Response non-authority flags describe this operation, not absence of historical
separately confirmed policy. V1/general v2 confirmation/mutation paths remain refused.

Added **49 new synthetic tests**, including actual ASGI 10000-address × ten-device/
100000-pair staging and 100-row first/last pages; mixed classification/privacy and
actor attribution; owner separation/recovery/restart; literal UTF-8/input bounds;
frozen/expired/confirmed states; role-loss/pause revocation; missing/partial schema;
same-count corruption; owner/global concurrent bounds; late transaction rollback;
read-only <=100-row proposal streams; and legacy refusal. The first focused run
used a corruption fixture trigger name already replaced by the dispatch-profile
upgrade; corrected the synthetic fixture to remove an actually retained trigger.
No production behavior was weakened. Focused API/continuous/legacy/format regression:
**140 passed (24.57s)**. Full suite: **2348 Python tests passed (283.49s)**.
Compileall, Ruff, diff/new-file whitespace and all **300 changed/new-document
local links/anchors** pass.

Updated normative architecture, current status/working plan and structured API,
storage/format/preparation/continuous/development manuals with exact capability,
limits, original-report semantics, recovery, backup/rollback and operating impact.
No DDL, UI, agent/wire, Compose, secret, inventory, live database/gate/profile,
service/image or FTD state changed. No lab migration, new fixture, policy activation
or production acceptance was invoked. Rust/Chromium were not rerun for this
Python/API-only packet. Frozen v2 browser review, separately gated atomic standing
confirmation/admitted-import cancellation, approved draft retention and configured
runtime/inventory/migration plus scoped real transport/multi-device/load/recovery
acceptance remain. See [V2 Preparation API](manual/bulk-preparation-api.md).

## 2026-10-26 — Private v2 preparation workspace, frozen reports and pure proposal review

Connected durable drafts to a distinct Web workspace under the narrow v2
preparation capability. Compatible Imports navigation now opens `/managed-imports/v2`;
legacy navigation remains when the capability is absent. Direct v2 requests never
fall back to v1 registry/admission. Workspace reads private owner references/public
device labels; absent journal is explicit and creation disabled, while malformed/
unavailable state is never empty healthy success. No migration, repair or pruning.

Explicit Operator/Admin CSRF creation accepts only bounded source, canonical
selected device IDs and intentional metadata. Recheck actual actor and parser/
UTF-8/device limits before one fixed private call. Strict 201 UUID/digest/product/
non-authority validation precedes redirect. Unknown/lost replies preserve transient
source/metadata/device choices, disable repeat creation on that uncertain form and
recover through owner references, never automatic repost or guessed latest success.
No raw source/comments are persisted or logged by the workspace.

Canonical owner report links survive restart and show <=100 targets/100 generated
diagnostic rows per page, visible protected/source exclusions, original actor/
device/revision/deadline and closed/confirmed state. Typed complete flags/counters/
times/state/references/pages/members/diagnostics are checked before rendering;
underlying API already verifies full original integrity. A separate read-only exact
proposal binds canonical descriptor/digest/manifest, original preparation metadata/
revisions/exclusions and a stable namespace-separated v2 UUID. Pagination/restart
preserves the binding without reserving a key. Closed/zero-accepted drafts refuse
proposal. The disabled standing-confirmation control has no form/submit route;
no recurring consent, policy, adoption or job is created.

Any authenticated owner may explicitly CSRF-revoke only their unconfirmed draft
after role loss/pause. Exact draft-only receipt checks retain confirmed cancellation
when follow-up report fails; unknown replies permit only original-draft inspection/
retry. Confirmed-import cancellation remains separate and refused here. Passive
metadata updates preserve pasted text/device choices, focus and immutable reports/
reviews without draft actions, scope reclassification, deadline renewal or device
read hints. Metadata is escaped, timestamps localized with zone, responsive forms
and bounded tables reused without new CSS/dependencies.

Added **41 Python cases** forwarding actual BFF requests to the ASGI API on
disposable exact profiles, including maximum 100000-pair staging/pages/proposal,
owner/role/CSRF/restart, malformed/unknown replies, input preservation, strict
report/manifest binding and closed/confirmed refusal with unchanged non-journal
policy/queue/origin/audit. Updated the older continuous integration's navigation
expectation for the now-supported narrow draft capability, not its write boundary.
Two new Chromium scenarios exercise production templates/JS, absent storage,
frozen text/focus/devices, escaping/colors, 100-row pagination, stable proposal keys,
mobile overflow and no automatic device work. The initial browser failure was an
unquoted numeric attribute selector in the new test; corrected the fixture selector,
not production behavior. Final focused regression **221 passed (60.48s)**;
full Python **2389 passed (298.03s)**; real Chromium **38 passed (126.12s)**.
Compileall, Ruff, JavaScript syntax, diff/new-file whitespace and all **316
changed/new-document local links/anchors** pass.

Updated normative architecture, status/working plan and structured Web/API/
preparation/continuous/development manuals, including unknown-response behavior,
authority limits and backup/rollback boundaries. No DDL, agent/wire, Compose,
credential/inventory, live database/gate/profile, service/image or FTD state changed.
No lab migration, new fixture, policy activation or production/device acceptance
was invoked. Rust was not rerun. Separately gated atomic v2 standing confirmation/
admitted-import cancellation, approved draft retention and configured runtime/
inventory/migration plus scoped transport/multi-device/load/recovery acceptance
remain. See [V2 Preparation Web](manual/bulk-preparation-web.md).

## 2026-10-26 — Suspended v2 standing consent, atomic API confirmation and historical receipts

Connected the existing BulkPolicies.confirm contract to a separate fixed private
API route with strict canonical descriptor/digest/count/boolean consent, original
Idempotency-Key and actual current Operator/Admin. Independent literal default-
false API/Web factory capabilities are required. API composition additionally
attests a nonempty immutable reviewed eligible-profile device scope within the
sealed enabled devices; off requires an empty scope. This does not fetch agent
profiles/credentials or enable executable ADD. Existing exact storage/suspension/
scope is checked before binding and at lifespan startup, without migration.

Kept quiescent/suspended admission unchanged: no active sessions/global lease or
pending/uncertain work, unpaused new authority, original full preparation/manifest/
owner/device identity/revisions/classifications/expiry and capacity/reserve are
rechecked under one write transaction. Policy/membership/receipt/real-actor audit
commit together or not at all; no legacy single-target loop, enqueue, work hint,
resume or automatic retry. Busy observation sessions conflict. Adoption never
invents prior service creation, already-managed authority is preserved and
protected exclusions acquire no grant. Original-key replay returns historical
consent without re-enabling retired policy or changing newer authority.

Added a distinct CSRF/Operator consent-preparation POST and detached immutable
subject/CSRF-cookie-bound cache, five per owner/256 total and <=ten minutes.
Forms freeze the original descriptor/digest/summary/key, require exact typed
accepted count plus explicit recurring consent, and recheck identity/session/
local expiry after metadata I/O before one fixed private confirmation. Paged
inspection preserves count/consent and compares original summary without rebasing.
Receipt validation checks exact historical fields, typed counts/classes/revision/
flags and original actual actor. Unknown/lost/malformed replies retain only the
same frozen review/key for explicit retry or original-receipt inspection. Optional
follow-up metadata failure cannot negate a checked policy-only result.

Added private owner receipt list/pages and restart-safe Web historical permalinks,
with <=100 original members per page and full retained root integrity verification.
Immutable canonical descriptor/digest/membership is read independently of expired/
pruned drafts. Admission-off and role-loss inspection stays available to the
authenticated owner; another owner/Admin is not an override. Strict BFF validation
refuses missing/malformed actor, authority, pagination, flags and evidence rather
than claiming empty success/current policy or verified device progress. The owner
workspace now shows saved receipt references alongside separate drafts. GET and
passive metadata never submit, resume, query FTD or alter frozen input/focus.

Added **49 Python cases** with actual BFF-to-ASGI API requests on disposable exact
SQLite profiles: separate gates/factory refusal, actual actor/strict fields,
CSRF/session/role/count/consent, immutable cache/capacity and post-I/O expiry,
scope/lease/pause/profile conflicts without partial authority, lost/malformed
reply same-key recovery, retirement non-reenable, receipt corruption and restart/
draft-pruning independence, paged consent and maximum **10000 IP × ten devices /
100000 policy pairs**. Full Python **2438 passed (349.36s)**; focused confirmation/
draft/continuous/storage regression **228 passed (95.48s)**. Two new production-
template Chromium scenarios cover independent gating, native exact count/checkbox
validation, escaped metadata, frozen fields/focus/binding, historical read-only
pages and mobile spacing/overflow. Initial receipt test counted a status-menu row
with an overly broad table selector; narrowed it to the historical-member table,
without changing production behavior. Final real Chromium **40 passed (130.97s)**.
Compileall, Ruff, JavaScript syntax and diff/new-file whitespace checks pass.

Updated normative architecture, status/working plan and structured standing-
confirmation/preparation/continuous/development manuals. No DDL, agent/wire,
Compose/runtime selector, inventory/credential, live database/profile/gate,
service/image or FTD state changed. Rust was not rerun; agent code is unchanged.
This is suspended policy consent, not concurrent executable import or production/
transport/load acceptance. Confirmed-import cancellation, concurrent standing
admission, configured runtime/inventory/nonempty migration, approved retention
and scoped device/multi-device/recovery acceptance remain. No consumed fixture
permission was reused and no lab activation/deployment was invoked. See
[V2 Standing Confirmation](manual/bulk-standing-confirmation.md).

## 2026-10-26 — Exact v2 import cancellation API/Web and current captured status

Connected the existing BulkCancellations coordinator to fixed private review,
reviewed accepted-member pages, cancel and current-cancellation reports on the
explicit existing continuous composition. Current Operator owner or another
Administrator is required; actual trusted actor/roles remain authoritative.
Revoking existing uncompleted authority needs no new admission/execution gate and
works during ordinary pause/suspended execution. Admin cancellation access does
not expose another owner's private standing-policy receipt. No startup/request
initialization, profile conversion, extra executor or legacy fallback.

Added a read-only backend review_page contract: verify the full original root and
five-minute digest/count in one snapshot, stream complete scope in <=100-row chunks,
return <=100 accepted members and recheck expiry after reading. State/authority/
attempt/revision changes conflict without scope rebasing. The existing cancellation
write contract remains unchanged: one whole-root decision seals membership,
retires exact unsent/failed/unknown authority, cancels only owned unsent jobs and
retains adopted/existing/applied policy. First RUNNING ADDs remain captured until
the existing shared result transaction settles them, with protection/prior
retirement/newer generation precedence and retained original uncertainty. No
REMOVE, interrupted RPC, re-enable, resume, new managed-request slot or work hint.

Added separate frozen Web cancellation consent with subject/CSRF-cookie-bound
immutable <=five-minute/five-owner/256-global cache, exact typed accepted count,
strict fields/current roles and post-I/O expiry. Paging preserves input/key/digest
and verifies the exact original review; prepare/GET never submit revocation.
Original-review/actual-actor unknown-response retry returns only the immutable
initial receipt; actor changes may require inspection rather than replay. Checked
receipt remains visible after optional metadata failure.

Original cancellation permalinks survive Web restart/draft pruning, show <=100
accepted members and distinguish immutable initial disposition/receipt from current
settlement, pending and retained attention. Passive local updates preserve open
receipt details and never query FTD, settle/repair/expire/promote work or infer
missing evidence as success. Strict BFF validation requires the complete captured
projection for this exact fenced profile: stripping current counts/attention cannot
downgrade to a legacy view that hides uncertainty. Added a collapsed receipt entry
point with explicit retained-maintenance/no-unblock consequences and no arbitrary
actor/action/profile authority in forms.

Added **45 Python cases** forwarding actual BFF requests to the private ASGI API
on disposable exact SQLite profiles: pause/disabled admission/no initialization,
mixed adoption/existing/protected exclusions, strict fields/count/time/digest/CSRF/
roles/cookies, owner/Admin separation, immutable cache, post-I/O/stream expiry,
changed protection/conflicts, lost/malformed replies/same-review recovery, actor
changes, restart/pruning, exact 100-row review/current pages, corrupt projections
and **10000 IP × ten devices /100000 accepted-pair cancellation**. Actual fenced
queue admissions/claims in synthetic fixtures test RUNNING success/no-op/failure/
unknown and one shared settlement without interruption, replay or REMOVE.

An initial metadata-failure fixture kept its simulated outage armed after the
intended rejected role-change replay, incorrectly expecting a later review to
redirect. Restored metadata explicitly in that fixture; no production refusal was
weakened. Final standalone new cases **45 passed (69.41s)**; final full Python
**2483 passed (410.54s)**. Real Chromium **42 passed (139.53s)**, with two new
production-template cases for native exact-count consent/frozen focus and local
settlement updates/retained unknown attention/original receipt, mobile layout and
pagination without device demand. Compileall, Ruff, JavaScript syntax, diff,
changed/new-document local links/anchors and new-file whitespace pass.

Updated architecture, current status/working plan and structured API/Web/
cancellation/standing/development manuals; corrected the working plan's capacity
table to distinguish implemented isolated v2 storage from retained legacy limits.
No DDL, agent/wire, runtime selector, Compose, credential/inventory, live database/
profile/gate, service/image or FTD state changed. Rust was not rerun. No lab
activation/deployment, consumed fixture reuse or production/transport/load
acceptance. Concurrent standing admission, configured executable rollout/nonempty
migration, approved retention and scoped device/recovery acceptance remain.
See [V2 Cancellation Surface](manual/bulk-cancellation-surface.md).

## 2026-10-26 — Fenced concurrent standing admission and strict fresh-read execution

Added a separate opt-in concurrent standing coordinator/private route, retaining
the original suspended/quiescent confirmation contract. Independent literal
default-false API/Web concurrent capabilities require existing standing admission
and trusted eligible-profile scope. Composition validates context before binding/
initialization and still keeps agent ADD/bulk dispatch/legacy controllers off with
an empty executable ADD scope. Exact existing fenced/dispatch/captured storage is
required; no runtime selector, migration, resume or live activation.

Refactored only the shared policy transaction to reuse all original full manifest/
preparation/owner/current-role/count/consent, managed/protection revision CAS,
classification/authority/device identity, expiry/capacity/reserve and original-key
guards. New admission checks selected device healthy/live/no-future fences and
retained device unknowns, accepted-pair pending/failed/unknown/unattributed work,
unsettled cancellation and held ordered cleanup. Validate all held bindings even
outside the selected scope. Healthy independent sessions/queued/RUNNING jobs may
continue; one scoped conflict refuses the whole import. Recheck selected fences,
frozen expected suspension and clock before commit, with no lease mutation,
interrupted RPC, inferred settlement or uncertainty reset. A lease expiring during
apply rolls back the whole policy/membership/audit, including caught outer
transactions. Retained FAILED evidence stays a pair latch after ordinary job
pruning; unselected valid uncertainty remains preserved without globally blocking
healthy independent policy.

Concurrent immutable receipts add admission_mode=fenced and actual historical
restoration_suspended boolean while keeping policy_only=true and no device work
admitted. Root/BFF readers validate both exact receipt forms; old unmarked receipts
retain suspended semantics, cross-mode key reuse conflicts and same-mode original
replay preserves original suspension/authority without re-enabling retired policy.
Confirmation creates no queue backlog/hint/resume. Existing shared discovery/
portion/claim/budget/priority logic remains the only executor. New concurrently
admitted authority requires a complete read strictly newer than its timestamp,
including refusal of equal-millisecond snapshots; old independent claims can still
finish. This closes the pre-admission-read race without granting a new dispatch
capability or changing legacy suspended-receipt read behavior.

Web freezes mode and expected suspension with the immutable original proposal/
summary/key. Recheck actual identity/roles/CSRF/count/recurring consent and post-I/O
expiry plus both independent capabilities before one fixed mode-specific private
call. Mode drift refuses without fallback/rekey/rebase. Typed historical receipt
checks, optional follow-up failure behavior and same-key unknown-response recovery
remain; active desired policy is not falsely labelled suspended/resumed/verified.
Historical owner pages work with admission disabled. Removed the obsolete disabled
proposal placeholder; it now explains the separate consent entry point.

Also fixed cancellation BFF projection validation: completed owned attempt history
can legitimately have a digest without a pending job. Preserve that history for
applied/no-op/failed/unknown review/status, while RUNNING waits still require exact
captured job and digest. No original receipt, attempt, authority or outcome changed.

Added **39 concurrent tests and four completed-history cancellation tests** on
disposable actual SQLite/ASGI/BFF/shared-queue profiles. Coverage includes active
same-device independent ADD, strict older/equal read refusal then fresh bounded
discovery/claim/result, scoped blockers, old FAILED retention/new-generation refusal,
ordered and incompatible-writer cancellation holds, atomic late expiry rollback,
competing-user CAS, independent default-off capabilities/private strict fields,
mode/suspension/reply integrity, original-key replay and **100000-pair admission
with unchanged device leases and zero new executable jobs**. Initial synthetic
fixture setup incorrectly attempted to reinitialize a sealed ten-device scope
with the four-device helper, and another test named the settlement hook incorrectly;
corrected the fixtures without weakening production profile/evidence checks.
Focused concurrent/confirmation/preparation/cancellation **178 passed (143.37s)**;
final full Python **2526 passed (426.82s)**. Real Chromium **43 passed (138.23s)**,
including new concurrent gate/frozen active-consent/focus/history/mobile behavior.
Compileall, Ruff, JavaScript syntax, diff, document links/anchors and new-file
whitespace pass. No Rust rerun; agent and Compose unchanged.

Updated normative architecture, current status/working plan and structured
concurrent/preparation/standing/continuous/cancellation/development manuals,
including rollback incompatibility of fenced receipts with older code. No DDL,
credential/inventory, environment/configuration, lab database/profile/gate,
service/image or FTD state changed. No consumed fixture authority was reused,
lab deployment/activation invoked or production/transport/load acceptance claimed.
Configured executable runtime/inventory rollout, reviewed nonempty conversion,
approved retention, recovery and real multi-device/load validation remain.
See [Concurrent Standing Admission](manual/bulk-concurrent-admission.md).

## 2026-10-30 — Configured observation startup and frozen public inventory

Continued core working-version integration in three sequential pieces: explicit
process runtime selection on existing storage, full public-inventory assertions,
and a non-executing CLI preflight. Added the normative boundary before code.
`FTD_SHUN_API_RUNTIME` defaults to legacy and accepts only the separate restricted
continuous-observation mode. Configured composition builds the existing continuous
dispatcher/maintenance owner and strict large/settled Unix client with configured
spacing/deadline/retention/capacity, no ADD scope and no optional admission/promotion
capabilities. It refuses injected owners/clients, incompatible settings and absent,
legacy or partial storage without initialization/migration/fallback. Ordinary
default legacy still rejects fenced profiles. Existing admitted REMOVE and
Protected-IP behavior remain, rather than falsely calling this a no-write mode.

Public inventory now uses a <=256 KiB regular non-symlink/non-FIFO reader and an
immutable complete credential-free projection. Reject duplicate addresses and
control text as well as existing duplicate-field/identity/interface/credential
checks. Configured composition compares every retained device ID, hostname, IPv4,
enabled flag and exact pin, including disabled IDs, without upsert or evidence
deletion. Freeze complete semantic interface/profile data and recheck file/DB
before lifecycle tasks; harmless ordering/whitespace remains equivalent. There is
no watcher/hot reload or address/trust migration and the API cannot attest a
previously loaded running agent inventory.

`ftd-shun-api --check` composes/validates without Uvicorn/lifespan/tasks, environment
protection import, socket/credential/device I/O or state mutation. Legacy selection
refuses before its initializing path. Success prints only mode and honest
execution/migration flags. Normal SQLite WAL connections may touch sidecars; this
is not forensic byte immutability, a lease/reservation or transport acceptance.

Added disposable retained-profile tests for the actual factory/CLI/ASGI status,
default/invalid configuration, gated/injected composition refusal, nonempty legacy/
partial/absent schemas, public identity/trust/disabled membership, startup interface/
profile/file/DB drift, semantic ordering, lifecycle ownership/drain and bounded
malformed/nonregular inventory. Targeted initially **132 passed (9.70s)**, finally
**135 passed (9.58s)** including non-creating connections under a vanished-file
race, sanitized CLI refusal and normal private-UDS entrypoint composition.
The configured owner wraps the supplied storage path with SQLite `mode=rw`;
it cannot recreate a vanished file. Restarted the in-progress full regression
after this hardening so the final run tests the actual final code. The initial
restricted-sandbox run reached the synthetic threaded lifecycle and stalled;
interrupted it, then reran outside sandbox restrictions using only disposable
fixtures/fake RPCs. No production guard was relaxed to make tests pass.
Final full Python **2584 passed (434.99s / 7m14s)**. Compileall, Ruff, diff,
new-file whitespace and local links in all 12 changed/new Markdown files pass.
No browser/Rust rerun: templates/JavaScript and agent unchanged; Compose unchanged.

Updated example configuration, structured runtime/credential/continuous/settlement/
development manuals, manual index, product README, working plan and status. No new
DDL, wire/agent or Compose changes. No actual `.env`, inventory, credential, lab
DB/profile/gate/service/image or FTD state was inspected/changed; no fixture
authority reused. No deployment/activation or live acceptance claimed. Retain a
checked SQLite-safe backup and matching fenced-compatible code/configuration for
any separately approved transition; selecting legacy cannot downgrade fenced DBs.
Nonempty legacy conversion, inventory transition and broader configured workflow/
recovery/transport/multi-device/load validation remain separate work.
See [Configured Observation Runtime](manual/configured-runtime.md).

## 2026-10-30 — Read-only nonempty legacy transition manifest

Continued the next core runtime-transition prerequisite without modifying the lab.
Documented the normative read-only boundary, then added a dedicated module/CLI for
recognized current base/queue plus all seven legacy managed tables, optionally
the exact non-authoritative draft journal. Contracts are generated in `:memory:`
from trusted code, never by source initialization. Existing absolute regular-file
source opens `mode=ro`/`query_only` in one read snapshot; committed WAL is included.
Unknown/partial/modified/extra/v2/incident schemas and integrity failure refuse
without repair/drop/adoption. The candidate conversion scope remains retired-only.

Streamed <=100-row source batches produce typed length-framed/domain-separated
SHA-256 table/source manifests over full schema, SQLite logical header metadata,
sequence and every retained row, including old keys/actors/receipt payloads/results,
TTLs/links, attempts, retired generations, occurrences/origins, protection and audit.
Bind complete canonical public inventory, enabled future scope, concurrency and
five-minute time into a separate observational inspection digest. Original
reinspection refuses same-count/source/header/configuration drift and expiry/future
time without rebase; inventory changes during reading refuse the whole report.
No report contains raw IP/pin/actor/comment/payload output.

Fixed blocker summaries distinguish ordinary/desired pauses, any lease (including
expired), cooldown, unfinished protection import, enabled legacy policy, pending/
unknown/read-reconciled jobs, pending/failed/unknown attempts and single/fleet
cleanup holds, plus retained disabled identity/trust mismatch. Missing older
terminal jobs remain counted as missing, not reconstructed or promoted to success.
The report always keeps migration-ready/available and semantic-conversion validation
false. Zero operational blockers is not an archive/key-compatibility proof, apply
token, remote-quiescence attestation, policy resume or activation permission.

Added **74 disposable inspection tests**, including actual shared queue/typed
verified/no-op/failed/unknown attempts and evidence-aware pruning, retired grants,
held cleanup, full schema/FK damage, bounded batches, committed WAL, typed hashes,
same-count/header/configuration drift, exact replay/expiry, disabled IDs, nonregular
paths, source readonly/no-init and sanitized CLI/no apply. Initial fixture mistakes
used 12 values for the 11-column event table and lacked fetchone in a cursor proxy
after adding header reads; corrected tests without weakening production checks.
Focused inspection/maintenance/configured-runtime **151 passed (5.83s)**. A first
restricted run reached existing threaded lifecycle tests and was interrupted;
the complete focused set was rerun outside sandbox restrictions with synthetic
fixtures only. Final full Python **2658 passed (434.10s / 7m14s)**. Compileall,
Ruff, diff, new-file whitespace and local links in all ten changed/new Markdown
files pass. Browser/Rust not rerun: templates/JavaScript and agent unchanged;
Compose unchanged.

Updated structured inspection/runtime/storage/development manuals, manual index,
README, architecture, working plan and status. No selected-source DDL/data/control,
backup creation, environment/credential/socket/HTTP/SSH/device access, startup hook
or apply converter was added. No lab database/inventory was inspected or changed,
no service was deployed, no gate/profile activated or consumed fixture reused.
Code-only rollback needs no DB restore. Future conversion still needs a checked
SQLite-safe backup, original-key/archive compatibility, atomic validation/rollback
and separate scoped migration/activation acceptance. See
[Nonempty Transition Inspection](manual/migration-inspection.md).

## 2026-10-30 — Operator clarification: lab-first development, release boundary

The operator clarified that this is an unreleased internal project with no real
production use, running against their desk FPR1010 test device. Updated AGENTS
and normative architecture with explicit precedence over older per-experiment
approval and mandatory dev-migration planning. Ordinary in-scope development,
validated deployments, explicit fresh-profile setup and bounded semantic lab tests
can proceed without asking again for every fixture/gate. Announce writes/scope,
use fresh labelled test authority, verify outcomes and keep short records.

Removed legacy-dev conversion/archive-key compatibility from the delivery critical
path. Prefer a clean DB in a separate path/volume with the old test DB privately
archived, inventory/credentials retained and useful settings explicitly transferred;
do not revive old queues or standing authority. Existing inspector code remains
optional and unchanged. Revised next work toward fresh setup, executable managed
integration, end-to-end lab use, recovery/Purge and usability instead of a converter.

The first operator-designated real release published on GitHub with a version tag
starts released-data upgrade/migration/rollback obligations, even if its version
is still 0.x. A footer, commit, lab build or experimental/RC tag alone does not.
Tag/release publication still needs the operator's request. Security is not
deferred: typed operations, agent-only secrets, authentication/pinning/private
sockets and truthful verification remain. No gate bypass, unknown-write replay,
evidence clearing, silent DB reset/deletion or production expansion is authorized.
Materially destructive/unclear scope and secrets/trust/network changes still need
direction; historical consumed receipts are not recycled as fresh authority.

Updated README, working plan, current status, manual index and development,
versioning, configured-runtime, bulk-storage and optional-inspector guidance.
Preserved historical log entries and prior implementation work in the dirty tree.
Documentation-only validation: local links/changed heading anchors and
`git diff --check`; no unrelated Python/browser/Rust/Compose suite rerun. The prior
2658-test result remains historical, not a new claim for this policy update.
No code/configuration, database/archive, profile/gate, credential/inventory,
service/device or GitHub tag/release was changed. Next is the practical fresh
lab setup and working end-to-end path, not another approval/migration framework.

## 2026-10-30 — Clean development setup and configured managed execution

Implemented the practical fresh-profile route rather than a legacy converter.
`ftd-shun-dev-init` builds all base/queue/v2 policy, preparations, cancellations,
attempts, captured waits, dispatch, device leases, ordered waits and promoter
storage in private staging. It checks integrity, checkpoints and exclusively
publishes a mode-0600 complete file; existing/racing targets are never overwritten.
Optional explicit readonly settings transfer copies only validated Protected IPs,
including disabled rows, with a fresh maintenance audit. No old authority, jobs,
observations or history is converted. The initially empty ready profile has a
fresh-read barrier and no executable policy until real recurring consent.

Added explicit `continuous-managed` process selection for API/BFF on existing
exact fenced storage. It selects the real strict settled/large/v3 Unix client,
all enabled supported profiles and existing concurrent standing/ready/ordered
capabilities through the same continuous owner. No second/legacy controller,
arbitrary CLI, startup migration, fake actor or gate fallback. Legacy remains
default. Updated all five v2 Web compatibility checks for the explicit new mode,
retaining independent local capabilities, CSRF, frozen consent and original keys.
Status distinguishes executable v2 scope while refusing obsolete legacy routes.

Added the opt-in managed-lab Compose overlay targeting separate `managed-v2.db`,
with legacy controllers off, and a structured fresh setup/cutover/usage/rollback
manual. Updated normative architecture, examples, README, manual routing and
working plan/current status. Old DB conversion and cross-dev-version compatibility
remain optional; no production/tagged release is claimed.

Validation: 28 new disposable setup/configured-managed tests passed,
including publication races/failures, settings-only source preservation,
construction without init/RPC, exact configuration, actual API/BFF consent/CSRF,
shared-worker ADD/restoration, permanent protection retirement/removal and
no-readd after deleting protection. Full Python regression: **2686 passed in
460.97s (7m40s)**. Supporting checks are recorded below.

Prepared deployment without switching the lab: rollback-tagged existing API/Web/
agent images as `ftd-shun-{api,web,agent}:lab-pre-v2-20261030`; built all three new
images (agent release build succeeds). Read-only old state showed 13 terminal
jobs (12 VERIFIED, one NOOP), zero enabled managed targets and three protection
settings (two enabled). No unknown work was cleared. Current agent logs report
SSH timeout; a direct host TCP22 connection succeeds while a temporary read-only,
credential-free helper on the exact Docker management network cannot connect.
No network/VPN change is authorized implicitly, so no fresh-store activation,
inventory/profile/credential/.env change, service restart or device mutation was
attempted. The old live services and old DB remain in place. Live v2 acceptance
must follow restoration of Docker-to-FTD reachability; ordinary lab authorization
does not require another per-fixture ceremony once that path works.

Supporting checks: compileall/Ruff/diff and 361 local links in nine Markdown
files pass. Compose validates with a temporary nonsecret environment and
`--no-env-resolution` (no real env values printed). Browser regression: 43/43
passed (138.45s). Rust release build succeeds; 58 unit plus five integration tests
pass. The initial sandbox Rust run lacked local socket permissions (five EPERM
failures); the correctly permissioned synthetic rerun passes without code changes.
All three Docker images build. An isolated, network-disabled Python 3.12 image
smoke test creates its tmpfs synthetic profile, passes managed `ftd-shun-api --check`
without execution/migration and constructs Web. Its initial read-only-container
attempt omitted writable `/tmp`, causing SQLite schema I/O failure; repeating
with the existing real Compose tmpfs contract passes. No production workaround
or schema/security relaxation was needed.

## 2026-10-30 — Live clean-v2 lab activation and managed lifecycle

The operator repaired FPR reachability. Confirmed TCP22 from a credential-free
helper on the exact existing Docker management network, then identified the same
device 1 / `fpr1010-lab`. Old state had no queued/running/unknown jobs or enabled
managed targets. Gracefully drained Web/API, independently read a complete empty
agent snapshot and required absence of unused TEST-NET `198.51.100.253`.

Created exclusive mode-0600 SQLite-safe `state.pre-v2-20261030.db` beside retained
`state.db`, validated integrity and later proved their logical dumps still match.
Original inventory is privately retained in
`.local/lab-v2-20261030-Qd4LW3/devices.pre-v2.json`; added only the already validated
device-1 ADD profile, preserving address, interfaces and pinned key. Old image
rollback tags from the preceding increment remain. Stopped the idle old agent;
its stop used the full 180-second Docker window despite no outstanding commands,
so graceful idle-agent shutdown remains a hardening follow-up. No evidence or
unknown work was discarded to replace it.

Explicitly initialized the absent separate `managed-v2.db`, copying only three
current Protected-IP settings (two enabled/one disabled), not old authority,
queues or observations. Managed API preflight passed without execution/migration;
agent-only sanitized configuration check passed with the unchanged shared
single-device credential setup/capacity 1. Before API activation, a real strict
v3 read-only session completed three commands and confirmed final settlement.
Started API/Web/agent with base + local-lab + managed-lab overlays. `.env`, secret
files/login, pinning, authentication, networks and host publication were not
changed. Current lab remains one device/one serialized stream, not a multi-device
or per-device-credential acceptance result.

Bounded fixture actor: `maintenance:lab-v2-20261030`, explicitly labelled
trusted-host Operator authority scoped to device 1 / `.253`, not a spoofed Web
identity. New standing request `34649d38-521f-4e73-be81-52fff47f57e6` used the real
private preparation/proposal/concurrent confirmation workflow. Frozen diagnostics
show one duplicate, one invalid row and two EXCLUDED_PROTECTED targets; exactly
one new pair was accepted. A normal refresh hint respected the 60-second floor.
Initial shared-queue ADD `3f4678ef-3c34-5eea-974d-da25c669f7cb` was VERIFIED and
completed a real v3 session. Original-key confirmation replay returned its receipt
without adding new authority/jobs.

Drained Web/API again, independently verified exactly `.253` on `management`,
then issued one typed verified agent removal and confirmed absence. This was a
labelled controlled disappearance, not a physical reboot or a queued user cleanup;
the standing generation remained enabled. Restarted API/Web. The fresh absence
read correctly honored the retained 300-second per-pair backoff. An initial
180-second read-only observation window expired before that intentional deadline;
no request was rekeyed, clock/guard relaxed or uncertain write replayed. After
the real deadline, a normal coalesced refresh admitted restoration automatically.
ADD `7093622d-533a-5ae3-a425-800738cbfe5f` reached VERIFIED; successful complete
snapshot recorded at `2026-10-30T12:52:20Z`. The original grant replay remained
idempotent.

Final exact reviewed v2 device cleanup used fresh request
`bc39bd06-c70e-4123-b1af-77e0e9c070cf`: atomic permanent retirement plus shared
REMOVE `db5bfdc4-f166-462f-83e8-5a3dd6cbf59e`, VERIFIED. Complete final snapshot at
`12:53:17Z`, policy revision 2, generation 1 disabled, all three jobs VERIFIED,
both original ADD attempts retained. Replaying the standing key after retirement
did not re-enable it. With Web/API drained, another complete independent agent
snapshot was empty. Final API/Web restart produced a new complete successful read
at `2026-10-30T12:54:44Z`: no re-add, zero active maintenance, exactly two ADD jobs,
no error and IDLE device lease. No unrelated address or original protected setting
was changed. No queue pruning or manual outcome/evidence rewrite was performed.

Leave the usable managed profile active, rather than returning to the archived
legacy DB. Future lab Compose commands must include `compose.managed-lab.yml`;
updated AGENTS/current status/working plan and fresh-development manual to prevent
accidental two-file rollback. Deployed Web UDS health=200 and unauthenticated
index=401; Caddy application HTTPS=302 to Authelia, auth portal=200; only Caddy
publishes host TCP443. These edge probes used no login/header impersonation;
actual authenticated browser interaction was not independently repeated here.

No tracked product source, agent/wire, schema or Compose content changed during
this activation; the preceding 2686 Python/43 browser/63 Rust checks and image
builds remain its tested artifact baseline, not new suite runs. This increment's
validation is real semantic lifecycle/settlement/restart/backup/edge evidence,
documentation links and diff checks. Private helper scripts were linted and remain
ignored with local evidence. First-scan scheduling after new consent still relies
on baseline/ordinary activity/refresh hints; improving that latency is a concrete
follow-up. Automatic evidence-based uncertainty recovery, confirmed Emergency
Purge, live protection-retirement acceptance, 10000-IP load, multi-device/data-plane
and production acceptance remain. No release/tag was published.

## 2026-10-30 — Prompt first scan after managed confirmation

Added a selected-device advisory scan after a committed, changed, non-replayed
managed confirmation. Only configured executable composition requests it; the
policy-only/observation factory keeps its no-work contract. No direct queue
admission, authority/resume, new route/schema or agent/wire change. Existing saved
receipts remain policy-only, not device success.

The existing continuous owner coalesces at most one boundary per eligible device,
marshalling request-thread notifications onto its event loop. A complete read must
start strictly after the latest notification plus a millisecond precision margin;
older in-flight/equal-boundary reads cannot erase demand. Held leases/failed reads
retain demand without stealing/replaying. The scan honors >=60s read spacing,
manual/REMOVE priority, existing fresh-evidence claims, protection/retirement,
capacity, uncertainty and >=300s ADD backoff. A mandatory later read may satisfy
it; the existing startup baseline covers restart/lost advisory state. No demand
from replay, unchanged/refused policy, GET, construction or stopped lifecycle.
Per-device `policy_scan_pending` is advisory metadata, not a completion count.

Added 13 synthetic tests covering strict scope/no-init, cross-thread latest
coalescing, old/equal read exclusion, before-floor no-RPC, actual configured API
confirmation-to-shared-queue ADD without refresh/signal, replay/unchanged/refusal
and held/failed-read no-steal/no-replay. New cases pass; the initial focused
scheduling/configured/concurrent/dispatcher run passed 104 tests before the final
two held/failure cases were added (the complete new module passes 13 tests).
Full regression, code checks and live deployment evidence are recorded below.

Full Python regression: **2699 passed in 439.53s (7m19s)**. Compileall, Ruff,
tracked/new-file whitespace and local manual links pass. Browser/Rust were not
rerun: Web assets and agent are unchanged. Only the API image was rebuilt;
retained `ftd-shun-api:lab-pre-first-scan-20261030` for compatible code-only rollback.
Existing v2 lab preflight passed without initialization/execution/migration.

Updated normative first-scan contract and concurrent/continuous/fresh-development
manuals, working plan and current status. Corrected selected manuals' obsolete
observation-only/no-runtime descriptions to reference the current explicit managed
lab composition. No template/JavaScript/Compose, secret, inventory or auth change.

Deployed only API after graceful drain, leaving Web/agent and the same v2 database
in place. Full independent initial agent read was empty before the announced
new `.254` fixture. New labelled trusted-host actor
`maintenance:lab-first-scan-20261030` used standing request
`a63d6089-7396-4a07-8720-807967e2822f`; no impersonated Web identity or old fixture
key. At consent, 282 seconds remained until original baseline `13:57:21Z`, with
no manual demand. The advisory flag became true and no job was immediately
fabricated. First scan began at `13:53:22Z`, after the normal floor from the
`13:52:21Z` complete read. ADD `56469905-d838-53ee-85f5-047f94c9406c` was admitted
at `13:53:28.862Z` and VERIFIED at `2026-10-30T13:53:44.526Z`; final complete
snapshot/settlement at `13:53:46Z` cleared the scan flag. The new API container
logs contain zero `POST /api/v1/refresh-hint` calls. No validator refresh, clock
override, new capability/gate or direct device write was used.

Original-key replay after creation scheduled no new scan. Final exact v2 cleanup
request `6f0d03ed-f11f-4c90-9909-bdd65e65311b` permanently retired generation 1 and
admitted REMOVE `d55bdae6-2b8e-4e20-bcf1-5d57f7b6aa75`, VERIFIED at
`13:54:32.641Z`, complete final read at `13:54:34Z`. Replay after cleanup also left
policy disabled/scan clear and the same two fixture jobs. Another independent
complete agent read was empty, including both `.253` and `.254`. Final lab state:
five VERIFIED jobs, zero active managed targets, IDLE device lease, three unchanged
Protected-IP settings, no error and integrity `ok`. Edge still redirects to
Authelia (302); all services run and only Caddy publishes a host port. No restart
of Web/agent, schema migration, data reset, evidence pruning or secret/trust/network
change. Updated AGENTS/current manual with active behavior and closed fixture.
Multi-device/load, automatic uncertainty recovery and Emergency Purge remain;
no production or release/tag claim.

## 2026-10-30 — Automatic retry before agent submission

**Status:** Implemented, regression tested and deployed to the desk lab (API only).

Added typed `AgentCycleNotStarted` only for local socket creation/setup/connect
OS errors before BEGIN send, with descriptor cleanup and request validation first.
The fenced worker accepts it only on its first opening call. A live exact-epoch
release rejects unsettled jobs/attempts and any claim audit in that epoch, then
atomically records `DEVICE_LEASE_NOT_SUBMITTED` plus normal release. Audit failure
rolls back. Policy, job outcomes, last confirmed data and uncertainty stay intact.

Continuous dispatch retains pending demand and retries that device with 5/10/20/
40/60-second capped backoff and visible retry timing/count; healthy devices keep
running. A new complete initial read is still required before further discovery/
claims. Clicks do not override backoff. Any attempted send, generic rejection,
lost/malformed reply, later typed error or expired/old held lease keeps the original
hold. This is not remote SSH or unknown ADD/REMOVE recovery.

**Validation:** 26 new tests; **2725 full-suite Python tests passed (454.12s)**.
Compileall, Ruff, diff and quiet three-file Compose validation pass. New API image
`1588b9696095...` built and non-executing configured preflight passed; original
`02898cf25797...` retained as `ftd-shun-api:lab-pre-unsubmitted-20261030`. Gracefully
stopped/drained only API (under one second), then replaced it. Real strict startup
read completed at `2026-10-30T18:15:02Z`: ready, no error/retry/pending scan, five
VERIFIED jobs, zero enabled managed targets, one IDLE lease, three unchanged
Protected-IP settings (matching before/after fingerprint) and integrity `ok`.
Web/agent containers/images were not replaced; Web health 200, anonymous 401,
HTTPS app redirects to Authelia (302), API/Web still have no network. No new test
device mutation, induced live failure, schema/configuration/credential/trust/
network change, evidence pruning or data restore. Synthetic failures prove the
bounded retry path; healthy lab startup is only a non-regression check, not live
failure/remote SSH recovery acceptance. Code-only rollback needs no DB restore.

**Remaining:** Submitted-session recovery,
Emergency Purge and current browser/batch/multi-device/load acceptance. Updated
architecture, retry/lease/settlement manuals, working plan and current delivery
list; no production or release/tag claim.

## 2026-10-30 — Exact terminal proof for failed SSH opening

**Status:** Implemented, fully regression tested and deployed to the desk lab.

Added opt-in fixed BEGIN `17` with strict version-bound initial/END settlement.
Only an opening-future error/timeout before a Cisco executor exists returns exact
`03 version 17 00`, through the existing post-handler, guard-release, IDLE-slot
completion. No command/snapshot/result is implied. Other rejections and later
failures remain generic. The client accepts this only as its own exact first
response, closes the socket and raises distinct `AgentCycleOpenFailed`; no fallback.
Configured continuous modes explicitly select the new mode, with unchanged
legacy/low-level defaults and independent ADD/profile/secret/UID/trust boundaries.

The worker accepts proof only on its first opening call. Separately audited
`DEVICE_LEASE_OPEN_FAILED` release shares the original live-token, no-claim and
no-uncertainty transaction. Demand/backoff/status reuse the existing automatic
retry, with fresh observation/current authority checks after recovery. Neither
old held leases nor unknown writes are released. Extended tests preserve no-replay
behavior for later exceptions of either opening-failure type.

Final review also closed a pre-existing strict normal-release gap: a local error
processing the initial/priority snapshot could leave `rpc_failed=false` without
finishing the session. Normal strict release now requires terminal settlement
recorded in this epoch. Final-publication failure after proved settlement may
release the completed lease, but keeps its error and previous published data.

**Validation:** **2766 full Python tests passed (442.17s)** after the final
normal-release fix; 139 final focused tests and 66 Rust tests passed. Fmt,
Clippy `-D warnings`, locked release build, compileall/Ruff/diff and quiet Compose
checks pass. Shared
Rust/Python vectors, real local SeqPacket proof/guard/worker tests and disposable
continuous cancellation/protection fixtures access no real FTD/credentials.
The first full run passed 2763 tests; the repeated final run includes the three
normal-release cases. Final API image `024797983f31...` and agent image
`bc24c532b862...` built; non-executing `ftd-shun-api --check` and agent
`--check-config` passed. Prior API `1588b9696095...` / agent `ab056df42363...`
retained as `ftd-shun-{api,agent}:lab-pre-opening-20261030`.

Gracefully drained API, then independently checked zero RUNNING jobs/non-IDLE
leases on readonly storage before stopping the idle agent. Its existing listener
still ignored graceful SIGTERM: stopped after 30-second timeout, exit 137, with
no command/job interrupted. Record signal handling as an explicit follow-up, not
remote quiescence evidence for unknown operations. Started new agent first. With
API stopped, an independent strict BEGIN `17` / v3 plus END completed against
device 1: initial/final snapshots empty, terminal proof valid, zero mutations.
Started matching API; its successful fresh read completed at
`2026-10-30T18:49:53Z`. Final state ready, no error/retry/pending scan, five VERIFIED
jobs, zero enabled managed targets, IDLE lease, three unchanged Protected-IP
settings/fingerprint and SQLite integrity `ok`. Web image unchanged, health 200,
anonymous 401, HTTPS app redirects to Authelia (302). API/Web remain network-none.
No schema/environment/secret/trust/network change, new fixture/device mutation,
uncertainty clearing or DB restore. Failure acceptance is synthetic; live happy-
path transport is only a non-regression check. Documented matching rollout order
and code-only rollback without restoring data.

**Remaining:** Submitted-session/unknown-write recovery, Emergency Purge and current
browser/batch/multi-device/load acceptance; fix graceful idle-agent shutdown.
No production or release/tag claim.

## 2026-11-02 — Graceful agent signal handling and joined drain

**Status:** Implemented, regression tested and deployed to the known desk lab.

Replaced blocking accept/inline default dispatch with a nonblocking listener,
bounded 100ms poll and the existing fixed pool for all capacities 1–10. Capacity
1 still serializes one stream; successors wait in the existing bounded kernel
backlog while it is busy, preserving legacy response handoffs without accepting
an application work queue. STOPPED is never treated as busy/retryable.
Explicit Tokio SIGTERM/SIGINT handlers request
stop before accepting successors; already admitted sessions keep original budgets
and complete normally. The listener closes before joining all workers, including
their completion postambles, while Tokio remains alive. Repeated signals do not
cancel work. Listener/worker errors drain remaining workers then report failure;
stopped/panicked workers are not replaced. No result, remote-quiescence proof or
API uncertainty resolution is inferred from process exit. Checked stale-socket
startup cleanup stays unchanged; shutdown does not unlink a replacement path.

Agent Compose stop grace is now 180 seconds; API still needs explicit 180-second
drain first. No schema, wire, environment, credential/trust/network or policy
change. Enabled nix poll/signal and Tokio signal features; lockfile adds only
`signal-hook-registry` and `errno`, preserving existing pinned versions.

**Validation:** 74 Rust tests passed, including real subprocess signals at
capacity 1/4, joined handler/postamble drain, repeated signals during admitted
local HEALTH requests, refused new connections, clean idle exit and stale-socket
restart and serial legacy successor handoff. Ten repeated runs of the final four
signal integration tests passed. Fixtures are private,
synthetic and credential-isolated, with no SSH/device access. Saturation may
reset a connection with unread data; the test synchronizes on the real dispatch
`agent.dispatch.admitted` event rather than treating a guessed rejection packet
as proof. Assignment is not device success or replay authority. Locked release
build, fmt/Clippy `-D warnings` and 140 Python protocol/recovery tests pass. Base
Compose validates with a temporary non-secret configuration tree; actual lab
selection validates quietly. Current lab read-only precheck is healthy with five
VERIFIED jobs, zero enabled managed targets, IDLE lease, three unchanged protected
settings/fingerprint and integrity `ok`. Previous agent image retained as
`ftd-shun-agent:lab-pre-shutdown-20261102`.

Built/deployed final agent `09c4d1df4772...`; non-executing container preflight
passed. API drained with exit 0; a separate readonly storage check confirmed
zero RUNNING/uncertain jobs and IDLE before old-agent stop. The old agent needed
its 30-second timeout/exit 137 once more, with no active work. New agent had
180-second configured grace and passed strict read-only BEGIN `17` / v3 plus END:
complete initial/final snapshots empty, terminal settlement valid, no mutations.
Its real container PID-1 SIGTERM at `12:08:46.431Z` reached joined completion at
`12:08:46.524Z`, exit 0, without SIGKILL. Restart handled its checked stale socket;
a second strict read completed successfully with zero mutations.

Restored unchanged API image `024797983f31...`; successful startup read at
`2026-11-02T12:09:33Z`. Final state ready/no error, five VERIFIED jobs, no enabled
managed targets, IDLE lease, three unchanged Protected-IP settings/fingerprint
and SQLite integrity `ok`. Web `bf3f395e58eb...` unchanged; private health 200 and
anonymous 401 pass, API/Web remain network-none. CA-verified browser HTML request
returns HTTPS 302 to Authelia (a non-HTML probe correctly returns 401 with auth
location). No DB restore, schema, gates, credentials, pins, auth or network change;
no new fixture, device mutation or uncertainty clearing.

**Remaining:** Submitted-session/unknown-write recovery,
Emergency Purge and current browser/batch/multi-device/load acceptance. No
production or release/tag claim; code-only rollback needs no DB restore and
must retain all original authority/results/holds. Active-FTD signal interruption
was not induced; admitted-work/repeated-signal acceptance is synthetic.

## 2026-11-02 — Exact settled read-only failure and automatic retry

**Status:** Implemented, full regression/build passed and deployed to the known
desk lab with healthy read-only transport acceptance.

Added distinct terminal status `04 version failed_read sequence` to opt-in BEGIN
`17`, with unchanged legacy/strict modes, successful snapshots/END and opening
status `03`. Agent tracks exact valid initial/priority/final read failure and
zero mutation steps over the whole session; even NOOP/deferred ADD/REMOVE
disqualify it. Successful bounded disconnect cleanup and original resource/
handler/guard/worker completion precede terminal emission. Invalid IPC, generic
failure, failed cleanup or missing proof cannot release anything. Failed reads
retain failure logs and never become successful cycles/partial observations.

The real client validates exact version/read/sequence, including between stream
frames, closes on typed failure and never retries inside a session. It marks
ADD/REMOVE before even a short/failed send; proof in mutations, old modes or
after complete final snapshot while awaiting END settlement is rejected. The
worker binds proof to its first open/current session's read, rejecting later
misclassified types and cancelled callers. Transactional exact-live-epoch release
requires no unsettled work or any mutation claim, even already VERIFIED/NOOP;
audits `DEVICE_LEASE_READ_FAILED` and normal release atomically. Existing capped
backoff, healthy-device independence, demand and fresh-evidence/current-authority
rechecks are reused. Old held epochs, original uncertainty and policy stay intact.

**Validation:** **2830 full Python tests passed (451.71s)**, including 64 new
cases; 204 focused protocol/recovery cases pass. Rust 77 tests, locked release,
fmt and strict Clippy pass; two proof/worker-ordering tests passed ten repetitions.
Compileall/Ruff/diff pass. Shared vectors,
real local SeqPacket and guarded worker completion, partial-stream/malformed/
misbound/lost/late proof, no-op/deferral/send failure, expired/old fences, completed
claims, audit rollback, cancellation/protection before retry and cancelled
callers are covered. Fixtures are disposable/credential-isolated and never use
FTD. Initial fixture errors (ADD requires v3/allowlisted profile and claims must
predate the frozen cutoff) were corrected without relaxing product checks.
Matching API/agent images built, and non-executing preflights passed with the
existing managed lab configuration/storage. Rollback images retained as
`ftd-shun-{api,agent}:lab-pre-read-recovery-20261102`; no live failure induced or
device mutation requested.

After clean API drain, a separate readonly inspection confirmed five VERIFIED
jobs, no enabled managed targets, IDLE lease, unchanged three Protected-IP settings/
fingerprint and integrity `ok`. Previous graceful-shutdown agent stopped with
exit 0, no SIGKILL. Deployed API `e549c337c7b1...` and agent `d9e9efb3edd0...`.
With API still stopped, the matching client passed actual FPR BEGIN `17` / v3
and END: complete initial/final snapshots empty, valid terminal settlement and
zero mutation requests. API then started and completed a fresh successful read
at `2026-11-02T12:47:08Z`. Final state ready/no error, five VERIFIED jobs, zero
enabled managed targets, IDLE lease, original protected fingerprint and SQLite
integrity `ok`. Web `bf3f395e58eb...` unchanged; private health 200/anonymous 401,
CA-verified HTML HTTPS 302 to Authelia, API/Web network-none and quiet three-file
Compose checks pass. No DB restore, schema/gate/secret/trust/network/auth change,
new fixture/device mutation or induced outage. Failure recovery is synthetic;
the healthy live read is a transport non-regression check, not lost-proof or
unknown-write recovery acceptance.

**Impact/rollback:** No schema, selector/gate, secret/trust/network/auth or Web
asset change. Matching agent/API code-only cutover with API-first drain; old
BEGIN-17 code fails closed on unsupported failure proof. Retain images/evidence,
never restore old DB/authority to resolve a hold. Manual documents operating
scope, terminal semantics and rollback.

**Remaining:** Proof-loss/hard-crash/submitted-session
and unknown-write reconciliation, Emergency Purge and current browser/batch/
multi-device/load acceptance. This is not general unknown-outcome recovery or
production/release acceptance.

## 2026-11-02 — Lease-bound completion journal and lost read receipt lookup

**Status:** Implemented, full regression/build passed and deployed to the known
desk lab with read-only normal/lost-terminal lookup acceptance.

Added exact 20-byte tracked BEGIN `18` / local lookup `19`, using current durable
device-lease owner UUIDv4 as 16-byte correlation. Configured continuous modes
explicitly select tracking and reject capability drift before startup; low-level
legacy/strict/BEGIN-17 defaults remain. Initial/terminal/failure bindings retain
exact versions, selected ADD scope, typed results, budgets, UID and pinned secrets.

New process-local agent journal has 4096 entries, no credentials/output/mutation
authority. It reserves before tracked SSH, refuses retained duplicates, evicts
only oldest completed entries and never treats missing/restarted state as safe.
Successful cleanup and zero mutation steps (including no NOOP/deferral) prepare
read-only evidence; handler/resource/guard return and original worker-IDLE
postamble publish completion before the possibly lost nonblocking terminal send.
Active/unsafe/unknown lookup cannot release anything; no SSH, FTD guard, command,
cancellation or new executor follows the local query. Its 21-byte exact echo and
absolute <=5s client deadline prevent inference from timing/error text.

After only its own current tracked session misses settlement/fails, API may query
that identity. Exact live owner/epoch/deadline, no unsettled jobs/attempts and no
claim in the epoch (even completed claims) are independently rechecked before
atomic `DEVICE_LEASE_READ_RECEIPT_RECOVERED` plus normal release. Retain original
errors/data/results/authority. Retry uses new UUID/epoch/fresh read and ordinary
capped backoff/current-policy checks. Old holds/crashes and unknown ADD/REMOVE
remain unchanged; journal lookup is not general mutation reconciliation.

**Validation:** **2892 full Python tests passed (443.69s)**; 82 Rust tests,
strict Clippy/fmt, locked release, compileall/Ruff/diff and targeted Python checks
pass. There are 60 new lookup cases and two new configured drift cases.
Shared v1/v2/v3/status vectors, actual local sockets, closed-peer terminal loss,
guard/postamble ordering, duplicate refusal, active-preserving capacity/eviction,
restart-as-unknown, no-SSH lookup, missed initial/final receipts, local processing
abort, healthy-device independence, new nonce/backoff/demand, malformed bindings,
expired/old fences, completed claims and audit rollback are tested. Synthetic
clock/notification and held-capacity fixtures were synchronized without changing
product cooldown/lease checks. Configured test adapters now explicitly model the
tracked boundary instead of accidentally selecting old BEGIN. The first full
Python run completed with 2891 passing and one 100000-pair cancellation fixture
exceeding its synthetic 20-second bridge deadline while image/compiler work ran.
That unchanged fixture passed in isolation (55.56s for its whole scenario); the
full no-build-contention rerun passed. Product deadlines were not relaxed.
Matching images and non-executing preflights pass.

Retained previous matching API/agent as
`ftd-shun-{api,agent}:lab-pre-session-lookup-20261102`. Drained API (exit 0) and
independently inspected readonly storage: IDLE, five VERIFIED jobs, zero enabled
managed targets, unchanged three Protected-IP settings/fingerprint and integrity
`ok`. Old agent stopped cleanly (exit 0, no SIGKILL). Deployed agent
`b3335c280601...` before API `6c1484707809...`.

With API stopped, labelled trusted-host `readonly-session-lookup-20261102` ran
two fresh-UUID v3 sessions against device 1. Normal BEGIN `18` / END had complete
empty initial/final snapshots and valid strict settlement; exact lookup confirmed
read-only completion. A second complete END data response was consumed but its
terminal record intentionally was not; the test closed that client, then exact
lookup confirmed the original completion. Fresh unknown nonce returned unsafe.
Zero ADD/REMOVE requests or FTD writes; this is deliberate local receipt non-
consumption, not a network/trust/configuration outage or queued mutation test.

API restarted and completed a fresh read at `2026-11-02T13:41:34Z`: ready/no error,
five VERIFIED jobs, zero enabled managed targets, IDLE, original protected
fingerprint and SQLite integrity `ok`. Web `bf3f395e58eb...` unchanged; private
health 200/anonymous 401, CA-verified HTML HTTPS 302 to Authelia, API/Web network-
none and quiet three-file Compose/all-service checks pass. No schema/gate/DB
restore, credential/trust/network/auth change, new standing authority, clearing
of uncertainty or device mutation. Controller-level automatic loss recovery is
synthetic; direct live lookup is not hard-crash/unknown-write/fleet/load acceptance.

**Impact/rollback:** No DB schema/authority/gate, environment, credential, trust,
network, authentication or Web change. API-first drain and matching agent-first
deployment required; old agents reject new BEGIN/lookup without fallback. Retain
compatible images and all evidence, not a data restore/reset as recovery.

**Remaining:** Durable/crash/old-held-epoch
and mutation-result reconciliation, Emergency Purge, current browser/batch/
multi-device/load acceptance. No production/release claim.

## 2026-11-02 — Operator-facing import usability

Removed internal import-generation/legacy labels from operator pages without
renaming fixed routes, schema identities or validation contracts. Imports now
shows paste / review / confirm steps, Saved drafts, Confirmed imports and readable
colored planned actions. Primary review/confirmation actions precede long tables.
Full references/digests/revisions are retained under collapsed Technical details;
the product footer version is unchanged. Pair counts and expiry are explained,
device/input/action spacing works at narrow widths, and managed removal forms no
longer constrain reason/IP fields to a short count-sized input.

Replaced misleading unconditional "confirmation/execution unavailable" and "ADD
disabled" claims with draft/current-runtime-aware descriptions. The managed Queue
description no longer uses the disabled legacy import flag to describe configured
continuous-managed execution. Unknown confirmation responses are never labelled
unsaved/rolled back. Protected exclusions, closed drafts, paused maintenance,
unavailable storage, original-key recovery and the uncertain-draft lock remain
explicit. Exact count/recurring consent, owner/role/CSRF/local/API gates, frozen
scope/expiry, evidence/holds and passive input/focus preservation are unchanged.

Added a task-oriented Imports operator manual and presentation amendment. No DB,
authority, dispatch, RPC, credential, trust, network or authentication changes;
Web-only rollout needs no API/agent restart or device write.

Validation: all **44 real-Chromium cases pass**, including no internal version/
enum labels, readable colored exclusions, main action placement, collapsed/full
technical references, input/focus/consent preservation, native validation, gated
controls and the configured managed Queue description with legacy flags off.
Desktop/mobile synthetic screenshots were inspected; widths 360/768/1100 are
checked without page overflow. Compileall, Ruff, diff and all 34 packaged-template
compilations pass. Initial targeted/full runs found old visible-copy assertions;
the affected focused cases pass after expectation updates with policy/CSRF/scope/
unknown-result assertions preserved. The final clean full Python rerun passes:
**2892 tests in 456.96s**, without competing image/compiler builds.

Preserved original Web `bf3f395e58eb...` as
`ftd-shun-web:lab-pre-import-ux-20261102`, then deployed only Web
`fb2a2a5114c8...` using all three current lab Compose files and
`up -d --no-deps --no-build web`. API `6c1484707809...` and agent
`b3335c280601...` retain their original start times; API/Web remain network-none.
Private Web health 200/anonymous 401 and CA-verified HTML edge 302 to Authelia pass.
Pre-rollout read-only API/SQLite check: ready/no error, fresh read
`2026-11-02T14:46:26Z`, IDLE, five VERIFIED jobs, zero enabled managed targets,
three Protected-IP settings and unchanged fingerprint, integrity `ok`.
Post-rollout check retains those values with a fresh successful read at
`2026-11-02T14:51:35Z`; no new jobs or standing authority appeared.
No new lab authority, imports, device mutations, environment switches or schema
changes. Authenticated workflow/large-list acceptance remains synthetic, not a
new live bulk acceptance claim. Rollback is Web-image-only using the saved tag
and the same three-file no-dependencies update; no database restore is needed.

## 2026-11-02 — Restoration-off history and explicit unblock semantics

Replaced ambiguous Maintain presence/Stopped badges with Auto-restore on/off.
Shuns and Managed shuns share explanations separating observed device blocks,
automatic restoration and Protected-IP automatic removal. Policy-only revocation
is now "Turn off auto-restore only — leave device unchanged"; combined cleanup
and ordered removal names explicitly describe turning restoration off and queuing
the separate removal. No change to confirmation tokens, typed IP, CSRF/roles,
scope, original keys, receipts, protections or independent capabilities.

The configured managed view collapses only explicitly off, absent, zero-pending
rules with explicit no-attention/no-missing-evidence and known safe/no ADD history.
Observed blocks, pending operations, failed/unknown outcomes and incomplete fields
stay in the main table. Counts describe the same bounded page, never a fake fleet
zero; original revision-bound pagination covers all retained rules. Open keyed
history/activity disclosures survive passive replacement. Original generation,
actor and verified additions remain under "Past activity — not current device
state", avoiding a historical VERIFIED ADD masquerading as a current block.
No DB/schema, filtering API, authority, queue, worker or agent changes.

Validation: 22 new presentation cases cover quiet history, non-hidden active/
observed/pending/failed/unknown/missing fields, strict zero semantics, escaping and
honest page links/counts. Existing focused revocation/removal tests pass after
visible-copy expectation updates; original policy/audit/replay/unknown checks
remain. All 45 Chromium cases pass, including an actual live-region replacement,
preserved nested disclosures, a reobserved historical IP moving back into the main
table, no device hints/admissions and widths 360/768/1100. Synthetic desktop layout
was visually inspected. Compileall/Ruff/diff and all 35 packaged templates pass.
The final full Python suite passes: **2914 tests in 441.90s**.

Read-only lab rules show one current operator-enabled/observed target and two
quiet retired fixtures. Kept these unchanged; no test imports, fixture authority,
refresh hints or device writes were submitted. Preserved prior Web `fb2a2a5114c8...`
as `ftd-shun-web:lab-pre-restoration-ux-20261102`, then replaced Web only with
`cbdb212010e0...` using all three current Compose files and no-dependencies/no-build
up. API `6c1484707809...` and agent `b3335c280601...` retain their original start
times. Health 200/anonymous 401, CA-verified edge 302 to Authelia and private
networking pass. Read-only API/SQLite check: ready/no error, last successful read
`2026-11-02T15:16:52Z`, IDLE, six VERIFIED jobs, one enabled rule, unchanged three
Protected-IP settings/fingerprint and integrity `ok`.

An additional template-only render in the deployed Python image reads current
public rule/status metadata through GET, preserves all three rows and confirms
the history section and on/off labels. Its labelled maintenance identity is only
local template data, not an HTTP identity or grant; no forms, hints, authority or
device commands were submitted. Actual browser workflow tests remain synthetic.

Rollback is the saved Web image only; no database restore or API/agent restart.
Web restart invalidates ephemeral confirmation forms, not retained drafts,
receipts, rules or queue work. Browser workflow testing remains synthetic; this
increment is not live bulk/load/production acceptance.

## 2026-11-02 — Requested-refresh timing and compact activity indicators

Fixed a presentation mismatch: pending manual demand previously left the periodic
4m30s remainder visible as though it were the requested refresh wait; an earlier
successful read then reset it to five minutes. Header/device rows now distinguish
requested eligibility, waiting for device/current command, active reading and
the next periodic check. Mutation phases are device work, not snapshot progress.
Only server revisions update data; a local zero timer never proves completion or
admits another command. Current per-device demand stays coalescible/clickable.

Status/Queue now have compact CSS activity icons and badges: quiet idle, static
wait clock, small running ring and paused queue, with independent error/attention
markers. Successful history is not active work. Full counts/descriptions remain
accessible and in hover text; large counts abbreviate to 99+. Reduced-motion
preferences disable rotation without hiding state. Fixed-height triggers and
existing out-of-flow alerts keep content stable; no per-second live announcements
or extra working-page paragraphs. Routine details remain inside Status/Queue.

The same pure metadata projections are exercised without DOM/network through a
Node-only export of the existing browser asset. Added 20 deterministic cases and
two Chromium scenarios for request/wait/read/completion, periodic reset, no fake
refresh at zero, trigger activity/attention, real data replacement, 360/768/1100
layouts and reduced motion. Existing per-device fixture flags now track its
reported pending count; old display-copy assertions were updated, not product
gates. Final combined browser/Node run: **67 passed (47 Chromium / 20 pure)**.
Focused existing Python refresh/auth/BFF/template contracts: **77 passed**.
JS syntax, Ruff and diff checks pass. No Python/agent implementation changed;
the full Python/Rust suites were not rerun for this frontend-only increment.
Synthetic desktop waiting and narrow attention-state screenshots were inspected.

All 35 packaged templates compile in an isolated networkless image. Preserved Web
`cbdb212010e0...` as `ftd-shun-web:lab-pre-status-ux-20261102`, then deployed only
Web `c97c9240588c...` with all three current lab Compose files and
`up -d --no-deps --no-build web`. API `6c1484707809...` and agent
`b3335c280601...` retain their original images/start times; API/Web network-none.
Health 200/anonymous 401 and CA-verified HTML edge 302 to Authelia pass. Read-only
API/SQLite check: ready/no error, last successful device read
`2026-11-02T16:15:54Z`, IDLE, six VERIFIED jobs, one enabled rule, unchanged three
Protected-IP settings/fingerprint and integrity `ok`. Compileall also passes.
No new API/RPC, DB schema, setting, authority, backend scheduling/dispatch, credential,
trust, network or authentication changes. No live refresh hints/imports/device
writes are used for this UI validation. Rollback is Web-image-only; API/agent
do not need restart. Web restart clears ephemeral confirmation forms, not saved
rules, drafts, receipts or queue work.

## 2026-11-02 — Large pasted Cisco exports and 100,000-address imports

Operator reported refusal of a 95,081-line list in Cisco `show shun` format and
explicitly selected raising import capacity to 100,000 IPs. Two independent bugs/
limits were involved: generic free text classified source plus destination as
ambiguous, and the old 1 MiB/20,000-line/10,000-row bounds rejected the source
before parsing. Added an exact structured export path with full literal-address/
port/protocol validation, source-only extraction and explicit non-cloning of
original interface/destination/traffic qualifiers. Malformed rows never fall back
to a different address or raw CLI. Existing plain lists/comments remain supported.

Coordinated parser, strict input models, source diagnostics/line references, bulk
manifest and BFF/report limits at 16 MiB UTF-8 / 100,000 lines/rows/unique addresses.
Retained the 100,000-pair complete-product bound, existing 200,000 retained target
capacity/retirement reserve and bounded rolling dispatch; 95,081 IPs fit one
device, not two. Reports stay 100 rows/page with a separately bounded 32 MiB
diagnostic header. Main Imports now uses the production byte counter with native
CRLF accounting. Specific validation errors preserve the editable input instead
of replacing all problems with one generic message. Large parsing runs outside
the BFF event loop. Raw paste/comments are still not persisted.

Found the older 20,000-entry observation cap would prevent reading an applied
large list. Matching API/agent now cap complete snapshots at 200,000 entries,
16 MiB typed data / 512 chunks and 32 MiB full CLI output. Fixed binary framing,
complete digest/strict decoding, target/login/write output caps, absolute stream/
operation/session deadlines and command/write budgets remain unchanged. No DDL,
credential, authentication, trust, network or new execution authority is involved.

Synthetic checks include the exact reported 95,081-line shape through real BFF/
private API/SQLite draft, first/last report, explicit count/recurring confirmation,
protected exclusion, retained policy and restart/pruning. No shared jobs/FTD work
are admitted by that suspended storage fixture. A two-device oversized product
is refused before draft POST. Other cases cover malformed Cisco fields, no zero-
destination target, 100,000 duplicate line references, overflow and extended
Python/Rust snapshot populations. Final full Python run: **2934 passed in 521.52s**;
after the small parser extraction/error-response robustness follow-up, **142
focused tests pass in 72.61s**. **82 Rust tests** (including a 95,081-entry real
local SeqPacket transfer), locked release/fmt and strict all-target Clippy pass.
**67 browser/Node checks pass**, including 95,081 rows retained in the actual
main workspace, live byte counter, no auto-submit and mobile layout. An initial
browser run exposed an obsolete aria-describedby assertion and Chromium's costly
layout of a single eight-million-character Unicode line; the assertion now
includes the new counter, and only that pathological byte-guard fixture hides
its textarea to avoid unrelated font layout. The real multiline long-list and
server byte-bound tests remain intact. Compileall/Ruff/diff/JS syntax pass.
The built networkless Python image parses all 95,081 sources and compiles all
35 templates without lab mounts; agent `--check-config` passes without SSH.

Preserved old API/Web/agent images under fresh
`ftd-shun-{api,web,agent}:lab-pre-large-import-20261102` tags. Used all three lab
Compose files. API drained with exit 0; a read-only storage-only one-off showed
IDLE, six VERIFIED jobs, no active/unknown work and integrity `ok`. Old agent
exited 0 promptly. Started new agent before matching API/Web: API
`94cc9f70d6e5...`, Web `c52b571aa546...`, agent `6620e6618a0d...`.
Post-start complete small FPR read finished `2026-11-02T17:48:16Z`: ready, no
error, IDLE, six VERIFIED jobs, the operator's one enabled rule and unchanged
three protected settings/fingerprint. Private networks remain unchanged; Web
health 200/anonymous 401, deployed new counter and CA-verified HTTPS Authelia
redirect 302 pass. No configuration/secrets/schema reset or user list submission.
API restart resumes ordinary existing maintenance; no development test jobs or
live ADD/REMOVE/refresh-hint requests were created by this increment.

Code-only rollback needs the saved matching images after API-first drain;
older code can refuse newly saved large descriptors/reports or large device
snapshots. Retain evidence/authority; do not restore an old DB or truncate data
to fit it. Web restart clears ephemeral confirmation forms, not retained drafts,
receipts or rules. The operator's real list is not imported by development
checks, and synthetic capacity support does not establish real FPR1010 large-
table/paging/deadline throughput or production acceptance.

## 2026-11-02 — Whole-import progress and nonblocking local execution

Operator reported transient browser NetworkError/lag, sixteen one-address progress
cards, slow import execution and no whole-task cancellation from Queue. Read-only
diagnosis found a 32,425-pair operator-confirmed import with live queued work;
status took 2.759s and full immutable root verification took 0.804s. The SSH code
already reused a bounded session for up to sixteen sequential verified mutations;
it did not open one SSH login per address. Device/state/authority was not altered
or a live import cancelled to obtain that diagnosis.

Queue status previously repeated the entire retained bulk-profile validation for
each displayed job. It now validates once inside the same read-only transaction,
then reads per-job metadata and complete task-level initial application counts.
The new bounded projection includes unmaterialized addresses and retained attempt
results, separates verified/no-op/adopted/unchanged/observed/pending/stopped/
superseded/failed/unverified/missing-evidence states and never grants authority.
Old completed jobs can be pruned without erasing the original attempt outcome.
Internal bulk delegations no longer appear as individual user-request bars;
original evidence/queue detail remains. Finished import cards collapse.

Cards link through a real CSRF POST to the existing owner/Administrator whole-
import cancellation review. Actual cancellation still needs frozen count/consent,
keeps applied/adopted blocks, drains running work and retains uncertainty. No
development check invokes cancellation on the operator's task. Labels are escaped
and only exact UUIDs form navigation paths; focus/mobile layouts are preserved.
Pending import work keeps the Queue trigger active even between queue portions.

Per-device local reconciliation/discovery/claim/settlement now uses awaited worker
threads, with shielded drain before cancellation returns. Scheduling callbacks
remain on the owning loop. Detached status avoids acquiring a discovery lock
held across slow SQL. Repeated eligibility tests share already validated state
only inside their owning transaction, with full revalidation before portion
commit. No cross-transaction cache, removed root/claim guard, new authority,
blind CLI batch or skipped per-address verification is introduced. The existing
16-operation/session and all command/time/lease/protection/cutoff limits remain.
Private status obtains its heavy queue snapshot outside the loop and then projects
controller state on-loop. Browser transport failures retain data and use a clear
retry message instead of raw NetworkError text.

Nine new focused progress/responsiveness/drain/shared-session tests pass, as do
301 dispatch/recovery checks and 112 queue/attempt/cancellation regressions.
Full Python suite: **2943 passed in 522.21s**. Query-only execution of the new
image's queue projection against the live data took **0.221s**, reported the
32,425-pair task with 80 processed / 32,345 outstanding and no internal request
bars, and compiled all 35 packaged templates. This is not a matched end-to-end
API latency comparison or measured write throughput. Final combined browser/Node
run passes **73 checks** in 156.95s, including held-device attention, readable
network/body-read errors, task totals, review-only cancellation, focus, escaping
and compact recent results on desktop/mobile. Compileall/Ruff/diff/JS syntax pass.
No agent, wire, DDL,
credential, gate, network or authentication change. Full original manifest checks
still cost work per admission/claim; real large-list throughput is not established
by synthetic traces, and no speculative ETA or blind replay is supplied.

While the unchanged old runtime continued the operator's import during testing,
it hit `Restoration lease or delegation expired during claim.` Device 1 retained
ATTENTION in epoch 942 (last complete read `2026-11-02T18:17:56Z`); its in-memory
cycle reported three completed steps before failure. The retained diagnostic
snapshot had 86 VERIFIED and 52 CANCELLED jobs, no RUNNING/UNVERIFIED. Original
attempts, authority, jobs and hold are not cleared/relabelled/replayed. Recent
snapshot admission groups were smaller than sixteen and included cancelled
delegations, so the synthetic max-sixteen trace is explicitly not a claim that
every real lab session achieved sixteen. This existing stale-claim/hold recovery
limitation requires separate verified recovery, not a lease reset during rollout.
The updated UI flags device errors alongside outstanding task progress. Agent
remains running unchanged; no direct refresh/SSH or cancellation was requested.

Preserved previous API/Web as `ftd-shun-{api,web}:lab-pre-import-tasks-20261102`.
Old API stopped with exit 0. Read-only post-drain inspection captured the exact
ATTENTION fence fingerprint, protected configuration, 86 VERIFIED / 52 CANCELLED
jobs and 32,428 retained / 32,426 enabled targets. Deployed only API
`fe364708324f...` and Web `161fef4f92f0...` with all three lab Compose files;
agent `6620e6618a0d...` and its `2026-11-02T17:47:59Z` start are unchanged.
The new API status responds in 0.549s, reports the held device honestly and shows
the complete 32,425-pair task at 80 processed / 32,345 outstanding, with zero
one-address request bars. The exact original fence and protected fingerprints,
job/target counts and integrity `ok` remain unchanged. This held/no-write state is
not evidence of improved real write throughput. Web health 200/anonymous 401,
new asset, network-none API/Web and CA-verified HTTPS Authelia redirect 302 pass.
No new import, cancellation, direct device command, schema/credential change or
hold release. Code-only rollback uses the saved API/Web images after drain,
never an old DB restore or erased evidence. The still-held operator import needs
a separately correct recovery path; the update does not claim it resumed.

## 2026-11-02 — Lab permission reaffirmation and late pre-send claim settlement

Operator explicitly reaffirmed permission to experiment with shuns and the product
dataset on the same desk FPR1010. Recorded it in AGENTS, architecture and the
development manual: no repeated fixture approval, announce scope, retain useful
failure evidence, use fresh labelled authority and verify actual cleanup. This
does not broaden production/secret/trust scope or permit fabricated verification.

Read-only inspection of the original held import retained epoch 942. Its last
executed group used evidence starting `18:16:26.020Z`; the last VERIFIED job
finished `18:18:24.304Z`, just before the 120-second boundary. The original combined
"lease or delegation" exception does not independently identify its exact failed
guard, but the timeline is consistent with evidence expiry during expensive claim
validation. Reproduced that boundary in disposable worker/SQLite tests.

Created a new mode-0600 SQLite backup
`managed-v2.pre-claim-expiry-20261102.db` in the private state volume with exclusive
creation and SQLite backup, not a WAL-unsafe main-file copy or overwrite.
Integrity `ok`, 86 VERIFIED / 52 CANCELLED jobs, original ATTENTION epoch 942.
No test command, task cancellation, root replacement or dataset reset was sent.

The claim boundary now distinguishes exact late eligibility expiry before return
from lost executor ownership. Its transaction rolls back RUNNING/attempt/audit
together as local `ClaimNotSubmitted`. The executor stops selecting mutations,
logs `queue.claim.not_submitted` and still obtains actual END/final snapshot and
strict settlement for earlier verified work. No rejected job is sent, marked
successful or retried within that session. Later discovery uses fresh evidence,
current standing authority and existing backoff/cutoff/protection checks. Generic
local errors, expired leases, unknown RPCs and failed terminal settlement do not
gain this classification. No schema, wire, agent, deadline or security gate change.

Focused regression run: **121 passed in 13.41s**, including complete claim rollback,
one prior VERIFIED result with no rejected-job RPC/audit, real worker END before
IDLE, later distinct admission and preserved holds for generic errors/lost leases.
Compileall/Ruff/diff pass. Full Python suite: **2947 passed in 521.60s**. The built
API image validates configured `continuous-managed` composition (64 routes)
without starting another lifecycle, RPC or startup migration. No agent/frontend
implementation changed in this increment, so no unrelated Rust/browser rerun.

Retained old API under `ftd-shun-api:lab-pre-claim-expiry-20261102`. Used all three
lab Compose files, stopped old API with exit 0 and replaced only API with
`2fb926892ab3...` (started `2026-11-02T19:04:18Z`). Web `161fef4f92f0...` and agent
`6620e6618a0d...` keep their previous images/start times and network modes.
Before and after rollout, read-only whole-table fingerprints match the new private
archive for device fences, protected settings, managed targets, manifests/members,
attempts and shared jobs. Retained 86 VERIFIED / 52 CANCELLED, exact ATTENTION
epoch 942 and integrity `ok`. Post-start private status takes 0.608s while held
and reports the actual device error; CA-verified HTTPS still redirects to Authelia
with 302. This fix prevents a new stranded session and does not recover historical
ATTENTION or establish active-write throughput. No shun ADD/REMOVE, refresh hint,
policy grant, root cancellation, schema/secret/network change or dataset reset was
performed. Rollback is API-only after drain with the saved image, not an old DB
restore or erased evidence. Historical import recovery remains separate work.

## 2026-11-02 — Offline recovery of the fully verified held import epoch

Implemented a narrow exception for the original lab import's held epoch, not
unknown-operation replay. The trusted-host `ftd-shun-device-recovery` inspector is
read-only; recovery requires real API/Web/agent stop, a five-minute whole-DB
review and a checked exclusive private backup. It verifies original roots,
1–16 exact claim/result/attempt bindings and realistic timestamp ordering, refusing
missing/failed/unknown/pending work, transitional cleanup and other owned devices.
One transaction installs the optional exact recovery profile, retains the original
ATTENTION fence and verified claim digests in an immutable receipt with a real
maintenance actor, and permits only that same-epoch IDLE transition. Audit failure
rolls back DDL/receipt/fence together. Jobs, standing policy and protection do not
change; old keys cannot release later epochs or gain mutation authority. Later
bulk evidence must be strictly newer than recovery. Startup never initializes or
recovers. Older images fail exact-profile validation rather than ignoring it.

23 disposable checks pass, including later audit ticks, unknown/failed and
missing-evidence refusal, stale review, rollback, backup, key/epoch guards and
freshness. The focused lease/dispatch/local-claim run passes 127 tests. The built
inspector validates the real epoch 942's three VERIFIED claims. A new private
rehearsal copy (`verified-recovery-rehearsal-20261102/working.db`, with its own
checked pre-recovery backup) recovers to IDLE epoch 942 with integrity `ok`.
Full table fingerprints confirm unchanged original jobs, requests, attempts,
targets, roots/members and protection; built API composition of the recovered
copy succeeds without lifecycle/RPC. The active original DB is unchanged at this
checkpoint; full regression and actual offline lab recovery follow below.

Full suite passed **2970 tests in 517.44s**; compileall/Ruff/diff pass. Preserved
pre-ledger API as `ftd-shun-api:lab-pre-verified-recovery-20261102`. Automatic
permission-review service timed out on several checks before execution; successful
retries/approved Compose diagnostics then confirmed actual API/Web exit 0 and
agent graceful exit 0. This was not SIGKILL, claimed quiescence from expiry or
removal of retained evidence.

Applied the rehearsed original-device recovery at `2026-11-02T19:36:55.272Z` with
fresh key and actor `maintenance:lab-verified-recovery-20261102`. The new private
checked backup is `verified-recovery-20261102/before-recovery.db`. Receipt retains
ATTENTION epoch 942 and its three VERIFIED claims. Exact table comparisons prove
unchanged original jobs, requests, attempts, targets, roots/members and protection;
integrity `ok`, jobs 86 VERIFIED / 52 CANCELLED, no RUNNING/unknown jobs.
Started unchanged agent `6620e6618a0d...` before compatible new API
`553abe73cab2...` and unchanged Web `161fef4f92f0...`, using all three overlays.
No credential/pin/authentication/network configuration or new standing consent.
Web health 200/anonymous 401 pass. Older API images cannot read the new optional
profile; rollback must not drop its ledger/guards or restore stale authority.

Post-start acceptance exposed an external availability blocker, not new verified
progress: agent opening reports `SSH connection or host-key verification timed
out`. Separate disposable read-only, capability-free TCP/banner probes, without
credentials/CLI/listeners/secret mounts or network configuration changes, both
timed out in 5 seconds from the existing agent namespace and Docker host.
The bounded six-minute read-only monitor ended without its 24-new-ADD target:
seven successor epochs released on exact pre-command failure, no new ATTENTION or
unknown results, status 0.530–0.856s and unchanged 80/32,425 processed. No complete
fresh read or ADD/REMOVE was obtained; do not call this throughput/write acceptance.
Final read-only comparison retains authority/protection/jobs exactly and the old
hold in its receipt, with 32,426 enabled targets, three protected settings and
integrity `ok`. Requested operator device/VPN/routing check. API/Web/agent remain
running with normal capped retry backoff, ready to continue original consent after
reachability returns; no reimport/reset is needed.

## 2026-11-02 — Automatic reconnect and continued original import after lab outage

Operator confirmed the earlier SSH/TCP outage was caused by their unrelated lab
work and reported restored access. Performed only read-only API/SQLite observation;
no new import, queue admission, refresh hint, recovery, service restart, image,
schema, credential or network change. The same running runtime automatically
returned to fresh complete reads, zero connection retry streak and verified
execution under the original standing consent. First observation was already
123/32,425 processed, up from the outage's 80.

Bounded active-write sample: **127 to 151/32,425**, **24 new VERIFIED in 260.25s
(5.53/minute)** and four completed epochs during observation. Full sampled epochs
964, 965 and 966 each verified seven operations in the same SSH session; 963 and
967 contribute partial boundary counts of two and one. No new ATTENTION or
UNVERIFIED/read-reconciled jobs, no device error and integrity `ok`. Status samples
were 0.530–2.160s under actual writes without a fetch timeout. Retained job timings
showed typical operation durations about 5–6s, including transport and local result
processing; this is not a measured SQL-versus-Cisco time split. One original
offline-recovery audit remains; no second recovery was needed for connectivity.

This accepts automatic **pre-command** failure/backoff/reconnect with continued
existing work, not unknown in-flight mutation replay, complete 32,425-address
execution, multi-device behavior or production capacity. The original task is left
running. Throughput remains a material large-import limitation; recorded phase
profiling and measured optimization as the next delivery priority. Updated current
status/agent context to remove the resolved connectivity blocker. Documentation
validation uses diff/link checks; no implementation change or unrelated full
Python/Rust/browser suite rerun in this observation-only increment.

## 2026-11-03 — Profile and reduce repeated import dispatch validation

Continued the original operator-confirmed import, without reimporting or creating
test authority. Initial read-only state: 4,213/32,425 VERIFIED, six rolling pending/
running jobs, no unknown result or device error. Profiled only query-only SQL in
one consistent snapshot: 16 eligibility calls consumed 1.084s, with repeated whole
profile validation dominating; full root verification separately took 1.609s under
cProfile (instrumentation overhead included, not baseline claim latency).

Changed the obsolete-delegation sweep to validate the full profile at entry/exit
of its caller-owned transaction and use existing same-transaction eligibility
checks per candidate. Removed the redundant caller validation only on that
dispatch branch. Original binding/current policy/protection/time/recovery/unknown
checks and whole-root claim verification remain. Final validation failure rolls
back cancellation states and audit. Added regressions for 16-member validation
count, expiry, between-transaction suspension, final-failure rollback and refusal
without a transaction.

Added bounded `device.session.timing` events per bound visit with fixed local phase
labels, numeric elapsed/local/agent times and device/epoch correlation. Local
renewal is excluded from agent time; failures and orderly drain are measured too.
No CLI, arguments or secrets, no new status freshness/success/retry authority.
Initial focused checks: 71 pass; final-source focused checks: **152 pass**.
Full suite: **2978 passed in 565.93s**, compileall/Ruff/diff pass. Built API
`399df3aedb97...` passes configured `--check` without lifecycle/RPC/migration.
Three paired query-only samples over the same actual snapshot gave identical
16-member eligibility results: median repeated validation **1.6505s** versus
boundary validation **0.2436s**. These are local validation timings, not a claimed
6.8-fold whole-import speedup. Before deployment the original runtime verified
24 more addresses in 281.84s (**5.11/minute**), with four settled epochs, no new
hold/unknown and integrity `ok`; full Python tests were running concurrently.
No schema/deployment configuration, protection, consent, agent protocol or device
operation limits changed.

Retained compatible API `553abe73cab2...` as
`ftd-shun-api:lab-pre-dispatch-timing-20261103`. Drained only API: actual exit 0,
IDLE epoch 1612 and zero running/unknown jobs before replacement. Deployed API
`399df3aedb97...`; Web container `236f2c0c5f50` / image `161fef4f92f0...` and
agent container `e73bc6221426` / image `6620e6618a0d...` stayed unchanged.
Exact fingerprints of protection (three IPs), bulk registry, 32,428 targets,
six standing requests, four manifests/32,430 retained members and the original
single recovery receipt match before/after. No new import/authority or direct
device command was submitted by the acceptance monitor.

Post-update bounded sample: **4,280 to 4,304/32,425**, **24 VERIFIED in 241.98s
(5.95/minute)**, four settled epochs, no device error/new hold/unknown results,
status **0.639–2.081s** and integrity `ok`. This is an observed same-task comparison,
not an isolated causal throughput benchmark (the before sample shared CPU with
tests). Complete epochs 1613–1615 verified five each; 1616 verified eight and
deferred one further call before writing; 1617 is a partial sample boundary.
Diagnostic events for those complete epochs retain actual settlement and show
agent-call time **33.217–46.602s**, local work **14.779–23.096s** (initial 1613
local time 18.230s). Remaining local claim work is **8.249–14.398s/session**.
Agent timing includes IPC, initial/final snapshots and semantic CLI verification;
it does not yet isolate individual Cisco commands. Web health 200/anonymous 401
and verified-CA HTTPS/Authelia redirect 302 pass. Original import remains running.
No whole-list, 100,000-address, multi-device or production performance acceptance;
roughly six/minute remains too slow for large lists. Next isolate agent phases
and reduce avoidable session/refill overhead, retaining outcomes/priority and
never renewing expired delegation or replaying uncertain work.

## 2026-11-03 — Exact source hashing reuse and bound agent-phase diagnostics

Continued the original lab import with no new authority or direct Cisco commands;
initial observation was 4,955/32,425 processed, no device error/unknown jobs.
Implemented at most ten per-verification framing templates for unobserved
PROPOSE_ADD members without predecessors. Every literal IP is still decoded and
all original length-prefixed source bytes are hashed. Other shapes use the same
general UTF-8 encoder. Full root/source/manifest/descriptor/receipt/current-policy
checks remain; no cached digest, membership, validation result or cross-transaction
authority. No schema/protocol/format/TTL/queue/credential/network change.

Pure 32,425-row paired source encoding: median 0.2468s original versus 0.1113s
framing, identical hashes. Built candidate API `4a328de7b593...` passes configured
`--check` without lifecycle/RPC/migration. A separate query-only non-serving process
compared complete original versus optimized verification of the actual 32,425-pair
root on one consistent database snapshot: medians **0.7949s / 0.6246s**, identical
root row, receipt and summary (three pairs). The serving API was not patched or
restarted for this benchmark. These local timings do not establish device speed.

Added fixed `agent_phases_seconds`/`agent_phase_calls` to the existing one-event/
session diagnostics: actual method-bound open+initial read, snapshot, ADD, REMOVE
and finish+final read/settlement. Other methods collapse into `other`; no argument
or CLI logging. Failed/deferred calls count as attempts only; renewal remains
excluded. Pure SSH-login/per-CLI-command timing is not provided by these wrappers.

Read-only queue inspection saw 17 completed releases in a 20-minute window, none
without a VERIFIED mutation; the first epoch overlaps the window boundary.
A separate 20-minute query saw 36 cancellations with combined expiry/revocation
reason, which does not prove expiry alone. No cutoff/refill/TTL/claim semantics
were changed on that evidence. Original tasks/receipts/protection remain retained.

Initial focused validation: **129 passed**, including exact byte vectors, mixed
streams, template bound/fallback, malformed IPs, retained root checks, worker
drain and method-bound diagnostic labels. Compileall/Ruff/diff pass. Full-suite
validation: **2998 passed in 513.58s**. API-only deployment/phase measurement are
pending below.

## 2026-11-03 — Restart-prefix starvation found and bounded selection correction

Deployed tested API `4a328de7b593...` after actual exit-0 drain/IDLE epoch 1734,
zero running/unknown jobs and unchanged original protection/standing-authority/
root/recovery fingerprints. Retained `ftd-shun-api:lab-pre-root-framing-20261103`.
Web/agent containers/images stayed unchanged. First epoch 1735 verified three
operations and settled: agent phases open+initial read **6.677s**, three ADD calls
**15.663s**, finish/final read **1.796s**; local **11.128s**, elapsed **35.361s**.
Those ADD calls matched the three new VERIFIED jobs, but diagnostic counts alone
are still not operation evidence or a pure per-CLI-command measurement.

The read-only monitor then exposed an existing unchanged selector weakness after
restart: discovery checked 64 already-present prefix members, admitted zero and
exhausted its scan budget. The queue became empty at **5,042/32,425**, IDLE with no
error/uncertainty, so the controller waited for baseline despite unfinished work.
The 240-second sample ended with one additional observed VERIFIED since its
baseline/one settled epoch, not its 16-target acceptance goal. Do not report it
as throughput acceptance. No force-refresh loop, new consent or replay was used.

Added an indexed same-device/IP active-observation exclusion before the bounded
Python candidate scan. It only removes pairs already unconditionally excluded by
current authority; fresh snapshot membership and every original root/policy/
protection/backoff/uncertainty check remain. Discovery never clears observations;
normal complete-snapshot reconciliation makes disappeared targets eligible again.
No quota, cutoff, TTL, authority, protocol, schema or scheduler-demand change.

Focused **169 passed**: scoped already-applied prefix beyond the 64-row budget,
other-device presence, stale presence as exclusion only, confirmed disappearance,
and actual continuous startup/20 missing additions without a hint or clock advance,
plus existing dispatch, drain, root hashing and phase tests. Compileall/Ruff/diff
pass. A second full validation and API-only rollout are in progress.

Final-source supplemental checks: **170 passed**, including a defensive exact-field
guard: future source metadata falls back to canonical encoding rather than being
omitted by a cached framing template. Final built candidate `01a5c191d81d...`
passes non-executing configured checks. Repeated paired complete-root benchmark
with that guard: **0.8063s original / 0.6487s framing**, identical root/receipt/
summary on the actual 32,425-pair snapshot. Read-only actual selector comparison:
old first 64 rows were all already observed, corrected first 64 had none observed;
query times 0.00154s / 0.00230s. No candidates were admitted by that measurement.
Second full suite: **3003 passed in 500.80s**, plus final-source 170 focused
checks above; compileall/Ruff/diff pass. API-only rollout follows below.

Final rollout: retained prior `4a328de7b593...` under
`ftd-shun-api:lab-pre-observed-prefilter-20261103`, drained API to actual exit 0,
verified IDLE epoch 1737 with no running/unknown jobs and unchanged fingerprints,
then started only API `01a5c191d81d...` / container `130959323b44`. Web
`236f2c0c5f50` / `161fef4f92f0...` and agent `e73bc6221426` / `6620e6618a0d...`
remain unchanged. No schema/gate/credential/pin/network change or new authority.

Real restart acceptance now passes without a hint, new confirmation or test
fixture. Startup read-only epoch 1738 settled after bounded discovery filled the
queue (12.119s elapsed; open+initial read 6.735s, final read 1.724s). The frozen
cutoff still prevented same-session execution of newly admitted ADDs. Successor
epochs continued the original task automatically. Bounded read-only sample:
**5,042 → 5,065/32,425**, **23 new VERIFIED in 207.95s (6.64/minute)**, three
settled mutation epochs. Actual audit, not call counts, proves 1739/1740/1741
had **7/8/8 VERIFIED** and one exact pre-write deferral each. Zero unknown jobs,
ATTENTION or device error; status **0.624–1.841s** and integrity `ok`.

Final exact fingerprints retain all three Protected IPs, registry, 32,428 standing
targets, six policy requests, four manifests/32,430 members and the original
immutable recovery receipt. Queue legitimately continues with 15 QUEUED/one
RUNNING at the final health snapshot, not a hold. Web health 200/anonymous 401 pass.
Original import remains running. Root-local speedup and restart correctness do
not establish complete 32,425/100,000-address or multi-device/production acceptance.
About five seconds per semantic ADD/verification remains the main execution cost;
next delivery should review bounded batch/session execution with truthful
per-target evidence/priority rather than weakening checks or recreating work.

## 2026-11-03 — Default-off grouped ADD verification foundation

The operator proposed batch additions followed by one full `show shun`, possibly
waiting for baseline. Reviewed the measured v3 hot path: the same SSH session
already serves multiple jobs, but each genuine ADD performs a target preflight,
write and target post-read. Added a separate gated tracked-v4 agent/client path
which shares only the post-read across at most eight acknowledged ADDs. Preserve
individual fresh preflight because Cisco's identical duplicate ACK does not prove
creation. Delaying confirmation outside the current bounded session is not part
of this increment; the five-minute baseline outlives the current live lease and
cannot safely resolve unknown writes by presence alone.

STAGE_ADD returns distinct pending status `05`, never successful creation. The
agent retains ordered pending IPs, refuses duplicate staging and ordinary read/
REMOVE/END until VERIFY_ADDS, and verifies each exact source-only/profile scope
in one complete strict table read. It returns the ordered receipt and existing
bounded/digested typed snapshot stream. Python requires the whole matched stream
and exact scope before exposing verified results; receipt-only, lost ACK, missing
IP, duplicate/extra interface, bad sequence/digest and malformed evidence refuse
success/retry. No v3 ADD meaning changes. Mutation attempts remain 16, CLI 64,
session 120 seconds and existing step/prompt/IPC bounds remain; v4's 34 wire
steps accommodate explicit per-command verification checkpoints, not more writes.

This is source-only protocol/executor/client foundation, NOT end-to-end batching
or a deployment. Configured API/worker still selects v3, and no Compose setting,
schema, data, authority, protection, credentials, trust or network was changed.
Next integrate durable RUNNING group acknowledgements bound to the exact live
owner/epoch, revalidated claims, explicit partial flush for refresh/removal/
stop/defer/END, result-before-snapshot provenance ordering and failure/drain
handling. Only then activate the matched path and measure/verify bounded lab work.
Do not loosen the single-device queue guard globally or recreate the import.

Initial validation: **284 Python focused protocol/recovery tests passed**;
**81 Rust unit + 9 integration tests passed**, locked release build and Clippy
passed. The initial sandboxed Rust test run hit EPERM for socketpair; rerunning
the same tests with authorized local-socket access passed. Compileall/Ruff/diff
checks pass. Full Python suite and additional boundaries are in progress.

Read-only GET of the existing lab API (all three overlays) reports `ready`, no
device error and **5,456/32,425** processed, five queued/one running at that
snapshot. No refresh POST/new task/device fixture/restart/deployment was invoked;
the original runtime continues unchanged. This is not live v4 throughput,
whole-import, multi-device or production acceptance.

Final validation: **3031 full Python tests passed in 527.95s**, plus **288
final-source focused checks** including four supplementary tests added after
the full collection (NOOP/deferral preserving pending scope, unsafe END refusal,
7,308-entry chunked group observation and exact receipt ordering/request binding).
Final Rust: **82 unit + 10 integration tests passed**, including strict default-off
configuration and before-SSH gate refusal. Locked release build, fmt, Clippy,
compileall, Ruff and diff checks pass. Synthetic eight-write console coverage
proves one group post-read instead of eight separate target post-reads, not a
live throughput gain. No source/runtime activation followed validation; pending
queue integration and bounded end-to-end lab acceptance remain next.

## 2026-11-03 — Fenced pending groups and grouped worker integration

Connected the default-off v4 transport to a separate fenced device-queue adapter
and the existing continuous worker. The default same-device RUNNING exclusion
is unchanged. Only ADDs whose original claims and durable ACKs match the exact
current owner/epoch/fresh group may coexist (maximum eight). No original root/
current protection/freshness/delegation/cutoff/lease checks are cached or removed.
An exact pre-write deferral may retain historical claims for the same job;
current binding explicitly selects only the new owner/epoch and preserves those
earlier events. A new queue cannot adopt acknowledged work, even with the token.

Nonterminal SHUN_ADDITION_ACKNOWLEDGED audit retains original requester identity,
batch_session binding and wire sequence, without a second claim/terminal record
or creation provenance. Group results must match the full ordered pending scope
and complete observation. Commit each verified result separately, then publish
the shared snapshot; later local failure retains prior successes and unknown
members/fences. No unknown-write replay or periodic-presence inference.

Partial groups flush for priority refresh/removal, stop/pause, exact deferral,
pre-send claim expiry and END. Newly protected pending targets force a read and
ordinary protected removal before subsequent background ADDs. Whole-import
cancellation verifies already-sent additions, leaves their blocks and cancels
unstarted work. Status labels staging/group verification and the pending count;
task progress never counts ACK as success. Fixed diagnostic phases distinguish
stage_add and verify_adds. Matching managed-only setting/transport/worker checks
and default-false example added; no schema, authority, credentials/trust/network
change. Existing Compose env_file propagation supplies the shared setting.

Initial/final focused checks: 157 then 149 passed, plus 37 cancellation/protection/
binding checks; 74 Node/Chromium checks and 92 Rust tests pass. Locked release
build, compileall/Ruff/diff checks pass. Full Python regression is in progress.
Prepared rollback tags ftd-shun-{api,web,agent}:lab-pre-batch-20261103 using exact
resolved old image IDs. Matching image build is in progress, not deployment.
The private lab gate remains unchanged/off and the original v3 import continues;
no new task, consent, fixture or device command was submitted by these checks.
Runtime preflight/drain/rollout and real grouped execution acceptance follow
only after validation. Source command-count improvements are not live speedup.

Final grouped-worker validation: **3060 full Python tests passed in 514.94s**,
plus **233 final-source focused tests** after epoch-history filtering and
status-only staging refinements. Pending ACKs no longer force data-table reload;
verified results/full reads still publish data. **74 Node/Chromium and 92 Rust
tests passed**, with locked release build, compileall, Ruff, Clippy and diff
checks. Matching built-image preflight with batch enabled starts no execution.

Retained prior API `01a5c191d81d...`, Web `161fef4f92f0...`, agent
`6620e6618a0d...` as ftd-shun-{api,web,agent}:lab-pre-batch-20261103. Old API
drained to actual exit 0; exact DB inspection confirmed IDLE epoch 1832, zero
RUNNING/unknown jobs, integrity ok and unchanged nine original inventory/
protected/standing-root/manifest/member/recovery fingerprints. Old agent then
exited 0 promptly. Enabled only the shared private `.env` batch flag and started
agent before matching API/Web, always with all three overlays. Final images:
API **c1e2552697f19e4da19d6fdf64e65d595ec07c3b067bba823679a75846f6e66b**
(`806fdeaafd0c`), Web **51dddbe0d7f5ea791bef4d3029350dbafd3073e7e437b75aa32abc0b0e062815**
(`f7cf49f282bd`), agent **cbb6492d90a63c5729cc6df3e28087625bbd396f32eab62df0576836c1cd0e12**
(`bbc1607fb1da`). No schema/reset/receipt change, new task/consent/fixture,
credentials/pins/network/auth change or refresh POST. This continues the original
approved import; its intended blocks were not test-cleaned away.

Live epoch 1833 acknowledged eight ADDs, emitted one group proof at sequence 9
and committed eight VERIFIED results before snapshot publication. Agent reports
**19 CLI commands**, zero pending members and real v4 terminal settlement:
initial read + eight preflights/eight writes + group read + END. First-session
diagnostics: 64.432s; open/initial 6.951s, eight stage calls 27.054s, group read
1.783s, final/settlement 1.854s, local 26.698s. These are method wall times,
not isolated Cisco-command timing or success proof.

Retained claim/release and terminal audits, not ACK/call counts, prove completed
epochs 1833/1834/1835 had **8/9/8 VERIFIED** and one exact pre-write deferral in
each of the latter two, with real releases. First claim 13:12:57.429Z through
third release 13:16:24.495Z on 2026-11-03: **25 VERIFIED in 207.066s,
7.24/minute**, including session gaps. More groups continued, including an
honest four-address partial group in epoch 1837. Final bounded read at 13:18:34Z:
API ready, **5,766/32,425**, no device error/unknown/ATTENTION, integrity ok and
all nine baseline fingerprints unchanged. Status samples 0.770–1.646s; Web health
200/anonymous 401. Ongoing RUNNING work is expected, not global quiescence.

This accepts shared post-verification/original-import continuation, not whole-list/
load, live priority/cancellation/failure or multi-device/production behavior.
Adversarial paths remain synthetic tests only. Speedup is modest and inadequate
for large lists: local work costs about 27–30s per sampled 8/9-write session,
with 15–16s in claim calls. Next profile/factor repeated exact local transaction
checks and pending-audit overhead; preserve root/current eligibility, bounds and
uncertainty. Never renew expired delegation, drop checks, recreate the task or
clear evidence for speed. Drain and disable the batch gate before v3 rollback.

## 2026-11-03 — Narrow grouped-claim scan reduction and local settlement phases

Read-only profiling used a query-only SQLite transaction on the current desk-lab
database, without mutation admission, device RPC or a refresh POST. Three full
profile scans took 0.260s including first-import overhead; most SQL time was
the complete target/member binding scan, followed by attempt and manifest
coherence. Full original-root verification was also profiled without omitting
members or changing its hash. Profiling overhead is not normal runtime timing.

Removed only two adjacent redundant scans in grouped claims: the running-scope
hook uses the executor validation immediately preceding it, while the additional
managed-attempt membership probe leaves complete exact-profile validation to
the base audit path before insertion in the same transaction. The final executor
check, original root verification, fresh authority/protection/delegation checks,
pending-group evidence and expiry/uncertainty behavior remain unchanged. No cache,
schema, protocol, authority, gate, time/write-bound or agent change. Added fixed
local timing labels for ACK persistence, group settlement and failed-group
settlement to expose the remaining `other` work honestly.

Focused regression: 63 passed, including both executor boundaries and complete
rollback after a synthetic unexpected profile object appears before base audit.
Compileall, Ruff and diff checks pass. Full Python regression is running. No
deployment or new task/consent/fixture/write was submitted by these checks; the
original import continues. This is a small measured hot-path reduction, not a
claim of acceptable large-list throughput. API-only rollout and actual epoch
observations follow validation; Web/agent need not restart.

Final validation: **3065 Python tests passed in 528.86s** on the final source;
compileall, Ruff and diff checks pass. API image
`d5eff09ed2284744c1df6bf3db66d5ca99c5f690a13937353a74557e62bd3048`
passed configured `--check` without execution/migration. Retained the exact
running batch-capable API `c1e2552697f1...` as
`ftd-shun-api:lab-pre-claim-scans-20261103`; Web/agent remain unchanged. Announced
API-only drain/rollout; no new import, hint, fixture or authority was submitted.

API-only rollout: old container `806fdeaafd0c` exited 0; stopped-API query-only
inspection confirmed IDLE epoch 1856, zero RUNNING/unknown jobs, integrity `ok`
and all nine baseline hashes unchanged. Started the checked API with all three
overlays, leaving Web/agent, configuration and database schema untouched. Initial
status at 13:39:22Z was ready, **5,899/32,425**, device error `null`, unchanged
fingerprints and 1.260s status response. Web health remained 200/anonymous 401.
No new request/consent, fixture, refresh hint or reset; existing intended blocks
remain. Completed post-update epoch/throughput observation follows.

Completed post-update epochs 1857 and 1858 have retained original RUNNING and
terminal audit plus real lease releases: **8+8 VERIFIED**, with one exact
pre-write deferral in epoch 1858. From first claim 13:39:16.090Z to second release
13:41:29.226Z: **16/133.136s = 7.21 verified/minute**, including the gap. ACKs
and diagnostic call counts were not counted as successful writes. No new hold,
unknown or failed job was observed.

New local method aggregates show ACK persistence **2.130/1.938s**, group result
settlement **3.898/3.801s**, and claims **13.737/14.703s** in those sessions.
Total local **28.480/26.635s**, elapsed **67.641/64.959s**; startup discovery
was slower in the first session. These wall-time aggregates are not isolated
command/SQLite timings. There is no demonstrated significant overall speedup;
the previous bounded grouped sample was 7.24/minute. Remaining local work and
per-command/session overhead still prevent acceptable large-list throughput.

Final bounded query-only/status check at 13:42:15Z: **5,915/32,425**, API ready,
device error null, zero FAILED/UNVERIFIED/ATTENTION, integrity ok, all nine
original fingerprints unchanged; active RUNNING jobs belong to the continuing
epoch 1859, not global quiescence. Status samples 1.260–2.075s; Web health
200/anonymous 401. New API container `07877f61d020` uses `d5eff09ed228...`;
Web `f7cf49f282bd` and agent `bbc1607fb1da` are unchanged. This accepts clean
code-only restart/continued grouped settlement/new diagnostic labels, not
whole-list/load/live failure/priority/multi-device/production behavior. Retain
the original import and its authority/evidence; next address measured remaining
claim/result-persistence cost without bypassing root/current checks or bounds.

## 2026-11-03 — Equivalent profile SQL and scoped exact result handoff

Continued the measured local claim/result-persistence work rather than changing
device commands or recreating the original import. Query-only paired SQL runs
used one live SQLite read snapshot with eight alternating pairs: target binding
median **0.040209 -> 0.036794s**, attempt binding **0.013966 -> 0.009925s**.
Every result matched. No RPC, authority write, refresh hint or fixture was submitted.
These isolated SQL numbers are not end-to-end throughput proof.

Complete profile validation now derives target request existence through the
already checked whole member/manifest/request chain only while an existing
transaction fixes the snapshot; autocommit keeps the original independent join.
Pending attempt/job presence uses equivalent conditional NOT EXISTS for exactly
QUEUED/RUNNING; all retained capacities and member bindings remain. Separate
UNVERIFIED/captured-evidence retention is not weakened.

Device-scoped claim/result code hands off its already resolved exact attempt
inside the owning write transaction. Persistence re-reads the row, compares all
fields and validates current original delegation/request/job links. Both full
executor/profile boundaries and base audit validation remain. Global/legacy
resolution is unchanged; there is no generic profile opt-out. Per-target commits,
partial-failure retention, original-root/current eligibility and all session/
command/deadline/uncertainty behavior are unchanged. No schema, profile, protocol,
gate, credentials, trust, network or standing-authority change.

Initial focused 177 passed. After explicitly narrowing the direct handoff to the
device-scoped queue, final focused **223 passed** (including stale row, changed
delegation/rollback, exact-schema corruption and global-path independence).
Compileall/Ruff/diff pass. Interrupted an earlier partial full run after 323
passing tests to test the final scoped-only implementation; the final full suite
is now running. API-only image preparation is underway, not rollout. Original
import, authority, protected addresses and retained recovery evidence remain.
Deployment/actual bounded execution observations follow validation.

Final image `cb8c07f85edeb74cb863ea93a3b2662e768b589f3fc926ddc43da43fb0f04d1a`
passes configured `--check`, reporting execution/migration false. One-off query-only
comparison of complete old/new profile checks in that image used eight alternating
pairs after warmup, one SQLite snapshot and identical returned profile state:
median **0.069125 -> 0.061464s** (~11% lower). Baseline reconstruction restored
only the previous two SQL joins inside that disposable profiling process, never
patched a running service. This is profile-validation timing, not overall import
speed or successful writes. Retained running API `d5eff09ed228...` as
`ftd-shun-api:lab-pre-result-handoff-20261103`. No deployment yet; full regression
continues and current lab work remains untouched.

Final source validation: **3095 full Python tests passed in 509.07s**, plus the
223 focused checks; compileall, Ruff and diff checks pass. No Rust/JS/source
protocol or frontend change in this increment. Announced API-only drain/rollout
using checked image `cb8c07f85ede...` and all three overlays; Web/agent,
configuration and original import/standing authority remain unchanged.

API-only rollout: old API `07877f61d020` actually exited 0. The stopped-API
read-only inspection at 14:04:28Z confirmed IDLE epoch 1877, zero RUNNING/unknown
jobs, integrity ok and all nine original inventory/protection/standing-root/
membership/recovery fingerprints unchanged. Started checked image `cb8c07f85ede...`
as API `4fbd4d8ec75e`, using all three overlays. Web `f7cf49f282bd` and agent
`bbc1607fb1da` did not restart; Web health remained 200/anonymous 401. No new
request, hint, import, consent, fixture, schema/configuration/credential/trust/
network change or reset. Observing completed original-import sessions follows.

Live post-update terminal audit confirms completed epochs 1878/1879/1880 each
VERIFIED nine original ADDs; the latter two each had one exact pre-write deferral.
First claim 14:04:44.717Z to third real release 14:08:17.096Z:
**27 VERIFIED / 212.379s = 7.63/minute**, including gaps. ACKs, call counts and
generic observations were not counted as successful writes. This small sample
does not establish controlled throughput improvement, whole-list/load or live
failure/priority/multi-device/production acceptance.

Nine-address group settlement method totals **3.346/3.130/3.192s**, versus prior
sampled nine-address totals **4.172/4.193/4.307s** (epochs 1871/1876/1872).
New claim totals **13.652/13.869/13.979s**, ACK **2.270/2.060/1.904s**,
local **26.151/25.973/26.262s**, session **68.059/69.380/69.223s**. These include
different attempt/deferral counts and method wall time, not isolated SQLite or
Cisco-command CPU. Root/claim and SSH/session costs remain substantial; this is
an incremental result-persistence improvement, not large-import readiness.

Bounded inspection at 14:08:05Z: **6,098/32,425**, API ready, device error null,
zero FAILED/UNVERIFIED/ATTENTION, integrity ok and all nine original fingerprints
unchanged. Epoch 1880 was then still active (eight results committed), not global
quiescence; its subsequent terminal audit above confirms all nine. Status samples
0.692–0.912s; Web health 200/anonymous 401. Actual final image IDs verified:
API **cb8c07f85edeb74cb863ea93a3b2662e768b589f3fc926ddc43da43fb0f04d1a**,
unchanged Web **51dddbe0d7f5ea791bef4d3029350dbafd3073e7e437b75aa32abc0b0e062815**
and agent **cbb6492d90a63c5729cc6df3e28087625bbd396f32eab62df0576836c1cd0e12**.
The original import continues, with its intended blocks and all retained authority/
recovery/protection evidence. No new fixture/import, hint, reset or configuration
change was used to obtain these outcomes. Next address remaining measured
original-root/claim/session overhead without bypassing guards or extending bounds.

## 2026-11-03 — Exact root UUID/IP decoding without cached verification

Profiled the existing original root with a query-only SQLite snapshot. Replacing
only per-member UUID object construction/formatting with the mathematically
equivalent bounded canonical text predicate gave **0.636346 -> 0.573828s** median
over five alternating pairs after warmup, checking all 32,425 members each time
with identical complete root/receipt/summary. No RPC, hint, authority mutation or
fixture was submitted by profiling.

Implemented that exact assigned-ID check (including nil/max and all version/
variant bits, not a UUIDv4 restriction). Shared source-member encoding now returns
the same freshly parsed IPv4 object to the pair-manifest stream, avoiding its
second parse. Every member/source byte remains hashed and all source/descriptor/
receipt/actor/classification/assigned-binding checks remain. Existing formatting
template bounds/general fallback are unchanged. No root/member/authority result
cache, source format/digest, schema/profile/protocol, gate, eligibility, timeout,
write bound, credentials/trust/network or configured runtime change.

Initial focused **186 passed**, including 2,002 canonical UUIDs across format
variants, wrong types/Unicode/control text, malformed assigned IDs inside complete
roots and invalid IPs. Final focused **79 passed** after changing expected source
bytes to a frozen independent pre-refactor encoder, with exact legacy/new bytes,
fallback metadata and one parse per literal. Compileall/Ruff/diff pass. Final
full Python regression is running; no rollout yet.

Built API image **e00a76582543c093ef3729220323c18bdb87806c45eb52179c1010fd5905d09a**
passes configured --check without execution/migration. Captured the exact running
previous root/member/digest source into a private temporary benchmark, not repo
or a running service patch. In the final image, complete old/new verification
using five alternating pairs after warmup, one query-only SQLite snapshot and
all 32,425 members each time gave **0.636790 -> 0.539228s** median (~15% lower),
with identical complete root/receipt/summary. This is not end-to-end execution
speed or large-list acceptance. Original lab import/authority/protection/recovery
evidence remain untouched; validated API-only rollout and actual observations
follow regression.

Final source: **3117 full Python tests passed in 519.76s**, plus the 79 final
focused checks; compileall, Ruff and diff checks pass. No agent/JS/frontend or
wire-protocol source changed. Retained exact running API `cb8c07f85ede...` as
`ftd-shun-api:lab-pre-root-decoding-20261103`. Announced API-only drain/rollout
with checked image `e00a76582543...` and all three overlays, leaving agent/Web,
configuration, original task and standing authority unchanged.

API-only rollout: old API `4fbd4d8ec75e` actually exited 0. Stopped-API inspection
at 14:27:32Z confirmed IDLE epoch 1897, zero RUNNING/unknown jobs, integrity ok
and all nine original inventory/protection/standing-root/membership/recovery
hashes unchanged. Started API `5a6711f0717f` with checked image
**e00a76582543c093ef3729220323c18bdb87806c45eb52179c1010fd5905d09a** using all
three overlays. Web `f7cf49f282bd` / image `51dddbe0d7f5...` and agent
`bbc1607fb1da` / `cbb6492d90a6...` did not restart. Web health 200/anonymous 401;
no schema/configuration, credential/trust/network, new import/consent/fixture,
hint, reset or authority change. Original intended blocks remain.

Startup epoch 1898 completed a real settled read-only visit (15.364s, no mutation
calls), not successful additions. Subsequent retained terminal/release audit
proves epochs 1899/1900/1901 each VERIFIED nine original ADDs and each had one
exact pre-write deferral. First write-epoch claim 14:28:29.167Z to third release
14:32:05.533Z: **27/216.366s = 7.49 verified/minute**, including gaps. Excluding
the separately disclosed read-only startup visit does not make this a whole-run
or controlled benchmark. No overall throughput gain is established; the previous
bounded sample was 7.63/minute. Do not imply the local 15% gain applies to import.

Per-session method wall times: claims **12.867/12.873/14.256s**, result settlement
**3.229/3.205/3.319s**, local **24.743/25.078/27.484s**, agent calls
**42.338/43.846/42.058s**, elapsed **67.173/69.017/69.623s**. Command/prompt and
network/IPC components are not separately timed. Final bounded status/DB snapshot
at 14:32:18Z: **6,251/32,425**, ready, device error null, no FAILED/UNVERIFIED/
ATTENTION, integrity ok and all nine fingerprints unchanged. Active epoch 1902
is ordinary continuing work, not global IDLE. Status samples 0.806–1.160s.
Actual final image IDs match the checked API and unchanged Web/agent above.

Read-only source review identified the coordinator's DEFER_SECONDS=5 after a
successful budget-deferred session, even with terminal progress; measured gaps
between these write epochs are 5.174/5.184s. The next targeted change should
distinguish productive settled boundaries from no-progress/error backoff, with
tests for real terminal counts/current visits, unchanged holds and fresh
admission. This is not implemented or activated by this increment. Then add
bounded fixed per-CLI phase duration/count diagnostics; the normal prompt reader
awaits channel messages without an artificial sleep. Do not infer isolated Cisco
latency yet, pipeline blindly, raise bounds or drop verification to claim speed.
Whole-list/load/live failure/priority/multi-device/production acceptance remains
pending. Keep the original task, grants, recovery evidence and protected policy.

## 2026-11-03 — Productive continuation and nonwrapping list statuses

The coordinator now distinguishes successful settled terminal progress from an
empty pre-write deferral. Only the current result epoch, completed worker phase,
actual settlement and positive integer terminal count avoid the five-second
empty-defer delay. Bind resets old progress. Failure/held/zero-progress cooldown,
opening/read capped retries, normal release and all next-visit fresh admission/
priority/authority checks remain; no budgets, gates, protocol or schema changes.

Plain statuses in dynamic device/queue rows and managed/import/review/history
lists now use one atomic label style, alongside existing colored badges. Reasons,
notes and timestamps remain independent wrapping text. Wide tables and standalone
cleanup labels scroll locally; no clipped or ellipsized status text is introduced.
Synthetic Chromium checks use real assets in light/dark desktop/mobile layouts.
No new fixture/import/cancellation, protection, standing authority, credentials,
trust or networks are changed. Existing original lab import remains the workload.

Validation: 120 initial focused and 77 final focused Python checks pass. Full
Python run: 3126 passed, two old `STOPPED_UNSENT</td>` count assertions failed
after adding the status span (526.53s). Updated both assertions to the actual
atomic label; both passed in the final 77-check run and a separate `--lf` rerun
(2 passed, 56.67s). No runtime logic was weakened to satisfy them. Final real
Chromium/Node run: 75 passed; compileall/Ruff/diff pass. API/Web images
`72d6ba21997c...` / `f00749a88b58...` are built; configured preflight reports
execution/migration false. Exact prior running images are retained as
`ftd-shun-{api,web}:lab-pre-productive-continuation-20261103`.

Old API container `5a6711f0717f` exited 0 after drain; stopped DB was IDLE epoch
1923, zero RUNNING/unknown jobs, integrity `ok`, with all nine original authority/
protection/inventory/recovery fingerprints unchanged. Replaced API/Web only using
all three lab overlays. Actual new images match the built IDs; agent image remains
`cbb6492d90a6...` and did not restart. Startup epoch 1924 is a read-only visit,
not mutation progress. API ready / sampled status 0.890s, Web health 200/anonymous
401, initial task 6,428/32,425. No new import, renewed grant or test fixture.
Retained original claim/terminal/release audit proves:

- epoch 1925: 14:58:22.953Z–14:59:30.259Z, 67.306s, 9 VERIFIED;
- epoch 1926: 14:59:30.614Z–15:00:38.482Z, 67.868s, 9 VERIFIED;
- both had one exact before-write DEFER, each with nine ACKs, not counted as
  additional successes. Range 135.529s, 18 VERIFIED = 7.97/minute, startup read
  excluded explicitly. Gap **0.355s** versus the earlier 5.174/5.184s gaps.

This confirms removal of the productive-session pause, not overall large-list
capacity or a controlled performance benchmark. Epoch 1925 timing still shows
42.542s agent / 24.608s local work; remaining CLI/session overhead needs separate
measurement. Bounds, per-IP verification, authority and recovery were unchanged.

Final bounded check at 15:01:14Z: API ready, 6,446/32,425 original pairs processed,
device error null, no FAILED/UNVERIFIED/ATTENTION, integrity `ok`, all nine original
fingerprints unchanged. Ordinary epoch 1927 was active (not globally idle).
Sampled status 0.781s; Web health 200/anonymous 401. HTTP CSS/JS SHA-256 matches
the tested source assets. Actual API/Web containers `3bc17872eb05` / `a22c285d6e96`
are running; agent remains original container `bbc1607fb1da`. No fixture to clean
up, new request/task, schema, configuration, authority, credentials/trust/network
or protection change. Continue the original import; do not reset it for speed.

## 2026-11-03 — Fixed CLI phase diagnostics without execution changes

Added session-local fixed `full_read` / `target_read` / `add` / `remove` timing
aggregates to the existing agent cycle log, plus opening time and the existing
tracked owner ID as bounded lowercase hex. No input-derived phase name, command,
IP, credential, output or error content enters these aggregates. Timed scopes
cover command send, prompt wait and shell envelope parsing; later semantic ACK/
shun parsing remains outside. Normal return is deliberately named `returned`,
never verification/success. Outer timeout/drop counts cancellation without
reclassifying a possible write; unpolled futures are not attempts. No extra CLI,
wait, deadline, wire/profile/schema/gate, authority, queue or verification change.

All-target Clippy additionally found two existing test-only denied unwrap/expect
calls in the batch fixtures. Replaced them with checked errors preserving the
original assertions and fixture checks, not lint allowances.

Validation: 96 Rust checks (86 unit / 10 integration) pass, including original
settlement, grouped wire/unknown-outcome and real signal drain cases. Locked
release build, fmt/all-target Clippy, Ruff/diff and 133 focused Python fixed-wire/
session checks pass. No Python/UI code or dependency changes in this increment;
unrelated full Python/browser runs were not repeated. Docker agent build is
`08e5251f765c...`; non-executing `--check-config` passes (an initial unsupported
`--check` invocation correctly returned usage without starting execution).
Exact old compatible agent retained as `ftd-shun-agent:lab-pre-cli-timing-20261103`.

Pre-rollout at 15:38:43Z: original task 6,739/32,425, API ready, integrity `ok`,
ordinary epoch 1961 active. API container `3bc17872eb05` drained exit 0; stopped DB
at 15:39:51Z was IDLE epoch 1962, zero RUNNING/unknown work, integrity `ok` and
nine original authority/protection/inventory/recovery hashes unchanged. Old agent
`bbc1607fb1da` then exited 0 with requested/draining/completed shutdown events.
Started new agent, confirmed listener ready, then restarted the same API. All
three overlays retained. Agent is now `6c844c0e08d1` / image `08e5251f765c...`;
API/Web images remain `72d6ba21997c...` / `f00749a88b58...`, Web container unchanged.

Retained claim/terminal/release audit proves initial epoch 1963 VERIFIED one
address in 25.453s (not a read-only startup), then 1964/1965 VERIFIED nine each in
67.862/68.018s. Normal write range 136.248s, 18 VERIFIED = 7.93/minute; including
all three first epochs, 162.063s / 19 VERIFIED = 7.03/minute. This is a diagnostic
rollout, not a measured speedup. One pre-write deferral per full visit is not a
successful mutation or an extra CLI command.

Canonical diagnostic IDs match the actual original lease owners. For the two
full visits, all 22 command envelopes returned, zero errors/cancellations, zero
pending at END: 9 target reads + 9 ADDs + 4 full reads, matching command count.
Opening 3.536/4.309s, target reads 14.937/14.711s, ADD 14.989/14.177s, full reads
8.706/9.338s. API local aggregate 25.356/25.046s, including claim 13.248/13.016s.
No login-per-address: each such batch used one shared settled SSH session. These
are command/runtime/network wall times, not isolated FTD CPU. Remaining local
claim work is the next profiling target, without skipping authority/root checks.

Final bounded check 15:45:08Z: original task 6,768/32,425, API ready, device error
null, no FAILED/UNVERIFIED/ATTENTION, integrity `ok` and nine original fingerprints
unchanged. Normal epoch 1967 active, not globally idle. Status 0.819s; Web health
200/anonymous 401. No new import/task, renewed consent, fixture/cleanup, schema,
configuration, protection, credentials/trust/network or outcome reclassification.
Failure timing tests are synthetic; no live outage/unknown-write experiment.

## 2026-11-03 — Lower-allocation original member verification

Profiled a real claim on disposable synthetic 32,425-member storage, without any
RPC/live DB access. cProfile found one complete root scan and eight complete
profile validations per claim; do not mistake profiler wall time for device
throughput. A separate query-only live snapshot confirmed the row construction/
source/binary encoding cost. No claim or mutation ran against the live dataset.

Removed temporary assigned-field equality tuples/generators and intermediate
source dictionary merging; common JSON framing retains exact fields and general/
future-field fallback. Binary manifest scans now reuse only the at-most-ten
literal device prefixes/four class bytes and one numeric IPv4 conversion per row.
Every source/member byte, classification/assignment, type/order/unique/capacity/
product check still participates per original root scan, before every claim.
No root/profile/result cache, validation boundary removal, schema, digest format,
gate/configuration, protocol/dependency, authority, time or verification change.

163 focused Python checks pass, including independent frozen source and binary
record expressions, all classification assignments, invalid assigned fields with
unchanged source/digests and existing claim/root tests. Compileall/Ruff/diff pass.
Actual 32,425-member root comparison: eight alternating pairs after warmup in one
query-only snapshot, identical complete receipts/summaries; median 0.543971 ->
0.466692s (14.2% less). This is only complete-root verification timing, not live
throughput. Full suite, API-only build/rollout and live measurements are pending.
Keep the original import/protection/standing authority and current agent/Web.

A separate connection-local, query-only page-cache experiment did not show a
useful gain: complete-profile medians 0.06322s at the default ~2 MiB, 0.06275s
at 8 MiB and 0.06092s at 16 MiB in one snapshot. Service cache/memory settings
were not changed. Corrected the old manifest verifier docstring: it now is used
before managed claims; a successful scan alone still grants no execution.

Full Python: 3143 passed in 511.13s; compileall/Ruff/diff pass. Final API image
`124fad2d64df...` includes the docstring correction and passes configured
non-executing preflight. Compatible prior API retained as
`ftd-shun-api:lab-pre-literal-allocation-20261103`. Pre-rollout status at 16:21:12Z:
7,049/32,425, ready, integrity `ok`, normal epoch 2001 active. API drain/rollout
and bounded execution measurements are in progress. No Web/agent restart planned.

Old API container `3bc17872eb05` exited 0; stopped DB at 16:23:16Z was IDLE
epoch 2002, zero RUNNING/unknown work, integrity `ok` and nine original authority/
protection/inventory/recovery hashes unchanged. API-only replacement uses all
three lab overlays and the actual final image `124fad2d64df...`. Web/agent images
and containers did not change. New API ready / initial status 0.802s, task
7,063/32,425; Web health 200/anonymous 401. No new task, authority, migration,
feature/configuration, credential/trust/network or protection change. Bounded
real execution/timing measurements follow.

Original owner/epoch-bound claim/terminal/release audit proves:

- epoch 2003: 16:23:28.418Z–16:24:13.649Z, five VERIFIED in 45.231s; startup was
  productive, not a read-only visit;
- epoch 2004: 16:24:14.004Z–16:25:25.664Z, ten VERIFIED in 71.660s;
- epoch 2005: 16:25:26.031Z–16:26:37.821Z, ten VERIFIED in 71.790s;
- epoch 2006: 16:26:38.175Z–16:27:46.762Z, nine VERIFIED in 68.587s.

Each full visit had one exact pre-write DEFER, not a successful extra address.
Full range 212.758s / 29 VERIFIED = 8.18/minute, including gaps; all four visits
258.344s / 34 VERIFIED = 7.90/minute. This includes the third full visit with nine
rather than selecting only the two ten-address batches. The preceding small
normal-write sample was 7.93/minute. This is a modest observed gain, not a
controlled benchmark, fixed batch-size promise or large-list acceptance.

API claim durations for 2004/2005/2006 were 13.610/13.468/12.485s with 11/11/10
attempts; normalized per attempt about 1.22–1.25s versus the earlier 1.30–1.32s.
Local totals 26.700/26.560/24.875s include different successful batch sizes;
agent totals 44.808/45.078/43.551s. Normal command latency still dominates.
The two ten-address agent cycles each had exactly 24 CLI commands (ten target
reads, ten ADDs, four complete reads), zero errors/cancellations/pending at END.
No limits, prompts, verification, root/profile boundaries or authority changed.

Final bounded check at 16:27:58Z: original task 7,092/32,425, ready, device error
null, no FAILED/UNVERIFIED/ATTENTION, integrity `ok` and nine original fingerprints
unchanged. Normal epoch 2007 active, not global idleness. Status 0.713s; Web
health 200/anonymous 401. API container `9c58b6329751`; Web `a22c285d6e96` and
agent `6c844c0e08d1` unchanged. Next profile equivalent SQL/full-profile cost;
do not drop checks, renew authority, clear evidence or recreate the original task.

### 2026-11-03 — Larger import groups with a shared terminal observation

The operator requested larger batches, reuse of refresh snapshots for confirmation,
more import work per SSH session and fresh ADD after confirmed absence. Reviewed
the architecture before implementation. New tracked v5 retains exact v4 support,
allows 16 pending addresses and uses VERIFY_END to bind one final whole-table read
to every pending result and actual post-handler terminal settlement. The API
persists proven results before publishing that same snapshot. V5 staging is capped
at 30s; its reserve is that step plus the final 15s interaction, while sessions
remain bounded by 120s / 16 attempts / 64 commands. Priority flush, cancellation,
root/protection/preflight and uncertainty boundaries remain. No schema, authority,
credential/trust/network or Web change. No new task/import was submitted.

Initial focused Python checks: 70 pass, including v4 compatibility, 16 pending
claims and final-stream/settlement failures. Rust: 88 unit plus 10 integration
checks pass with actual local sockets; all-target Clippy passes. An initial
sandboxed Rust run hit EPERM on sockets, not semantic failures; rerun outside the
restricted socket sandbox passed. Full Python/build/preflight/rollout and actual
throughput measurement are pending; do not infer a speedup from synthetic tests.

Desired-state restoration of a previously verified block remains implemented.
Cross-session first confirmation and retry after ACK plus confirmed first absence
are explicitly not implemented here; that needs a separate durable result and
settlement contract. Lost writes remain held, never blindly repeated.

Final focused Python set: 357 pass, including real socket framing, old v4 limits,
16-member scope, lost/false terminal settlement, partial local result persistence,
priority/cancellation and retained read/opening recovery. Full regression run:
3150 pass, two stale tests still treating version 5 as unknown fail; those exact
expectations were corrected to version 6 and both pass with `pytest --lf`.
This is a full run plus targeted corrections, not a second clean full run.
Compileall/Ruff/diff, Rust fmt/all-target Clippy and locked release pass.

Built matching API `ddae8a1863d2...` and agent `75d48be22122...`; both configured
non-executing preflights pass. Retained exact prior images under
`ftd-shun-{api,agent}:lab-pre-shared-final-20261103`. At 17:24:34Z the original
task was 7,528/32,425, ready, integrity ok, ordinary LEASED epoch 2059;
baseline authority/protection/inventory/recovery fingerprints retained privately.
API-first drain and matched rollout are now in progress. No Web update planned.

Deployment attempt aborted before agent replacement. Old API stopped exit 0,
but the stopped DB at 17:33:08Z retained ATTENTION epoch 2060, one UNVERIFIED
ADD and no RUNNING jobs. All nine original hashes were unchanged, integrity ok.
The unknown job is `db174cf8-3496-53d8-aa78-1096bc39b251`, claimed at
17:26:23.366Z and terminal unknown at 17:26:24.529Z; ATTENTION audit followed
17:27:45.664Z, before the deployment stop. Agent's original v4 session diagnostics
show eight ADDs, eight preflights and two full reads, pending zero, then EAGAIN.
API logs additionally retain `maintenance.expiry.failed: database is locked`.
This suggests the ten-second idle receive wait expired during local work after
group verification. Logs/timing do not prove non-submission of the next claimed
ADD; do not convert its unknown result to NOOP/VERIFIED or replay it.

Restored the exact old API container/image with `compose start`, not new `up`.
Agent/Web were not stopped/replaced, settings/authority/uncertainty unchanged.
A new exclusive private SQLite backup
`managed-v2.pre-shared-final-hold-20261103.db` has integrity ok. The verified-only
epoch-942 recovery design does not cover this unknown claim. Keep the original
task and evidence; no fence reset, reimport, new consent or device write was
submitted by this development turn. Original admitted work ran on the old code.

The candidate v5 agent now separately allows 30s waiting for the next local
request, capped by the absolute remaining session time; send/transfer stays 10s,
v4 stays 10s, CLI bounds unchanged. Real socket-option tests verify all three
limits. Final Rust: 89 unit + 10 integration pass, fmt/Clippy/locked release pass.
Rebuilt candidate agent `d972adf099df...` replaces only the unused candidate tag,
not the running agent. Candidate API remains `ddae8a1863d2...`. No v5 live speedup
can be measured while the original device epoch is held.

17:37:25Z after restoring old API: ready HTTP service, original task 7,545
verified / one unverified / 24,879 outstanding. `processed=7546` includes the
unverified item, not an extra success. Integrity ok, nine hashes unchanged;
ATTENTION epoch 2060 / one UNVERIFIED / zero RUNNING retained. Status 0.853s,
Web health 200 / anonymous 401. Next implement/review an explicit compatible
resolution contract for this retained case; do not apply verified-only recovery
to unknown work or turn diagnostic absence of log lines into execution proof.

Final unused candidate agent `d972adf099df...` also passes configured
non-executing `--check-config`; final Ruff/diff checks pass. It remains built
only, not deployed. The old running pair and held epoch are unchanged.

### 2026-11-03 — Explicit quiescent managed-ADD reconciliation

Implemented a separate desired-state review/decision for the retained unknown
ADD case, after an architecture amendment. Actual API/Web/agent shutdown, exact
whole-epoch claims/terminal/diagnostic audit, original system attempts/requests/
roots, checked exclusive backup and a fresh whole-DB digest are required. An
immutable optional table binds only those unknown job/attempt digests to one
recovery receipt. Original outcomes, policy, delegations, protection and audit
remain; no old job is retried or labelled successful. Runtime barriers exempt
only valid reviewed original records; later unknowns, failed/manual/REMOVE or
foreign work stay blocked. New current managed attempts require a complete read
after the decision, current root/protection/retirement and existing backoff.

The new exact profile is opt-in only through this offline tool; old DB writers
refuse it. Startup/GET do not initialize or reconcile. Managed views label reviewed
unknown history separately; progress uses current pending/presence or later real
verification, not fabricated old success. No credentials/trust/network/auth
change, generic CLI or second executor. Current lab is still held epoch 2060;
no decision or new device work has been submitted during implementation.

Initial focused checks: 162 lease/discovery/removal/recovery tests and 155
concurrent/ordered/recovery tests pass; additional proof/refusal tests and full
regression are in progress. Build, actual-dataset rehearsal and any later lab
activation must be recorded separately; implementation is not live acceptance.

Full Python regression: 3170 pass in 539.05s. Final expanded reconciliation/
policy-view/import-progress set: 53 pass; all 75 browser checks pass. Compileall,
Ruff/diff pass. Further synthetic cases cover stale/foreign/missing/actor/REMOVE
evidence, actual policy retirement/protection, queue-retention preservation,
later unknown epochs, old-receipt non-release and a future genuinely verified
recovery alongside reviewed unknown history. No original unknown is relabelled.

Built profile-aware API `517de8921634...` and Web `45392bd7edec...`; API
non-executing configured preflight passes. Rehearsed on a disposable SQLite
backup of the actual original dataset: epoch 2060, nine claims, one unknown;
strict verified-only tool refuses, new reconciliation succeeds, original job/
attempt counts and unknown bytes unchanged, integrity ok. Live source opened
read-only; zero SSH/device work. Private original failure logs were retained in
`/tmp/ftd-quiescent-20261103.uJWZai/`. Old running API/Web retained under
`lab-pre-quiescent-reconciliation-20261103`; old writers cannot use the new
optional profile. Actual API/Web/agent shutdown and exact offline lab activation
are now in progress; do not treat this as completed activation yet.

All original services actually stopped exit 0: API `9c58b6329751`, Web
`a22c285d6e96`, agent `6c844c0e08d1`. Applied only epoch-2060 reconciliation
at **18:20:30.926Z**, new decision `e73e4081-5c21-44cb-a3fc-6c9cce80e3bc`.
The private checked archive is
`quiescent-reconciliation-20261103-epoch2060/before-reconciliation.db`.
Exactly nine original claims / one unknown reviewed; original job/attempt bytes,
eight policy/protection/inventory fingerprints and prior recovery receipts all
unchanged. Zero jobs retried, policy unchanged, integrity ok. Epoch 2060 becomes
IDLE only through the new receipt-bound transaction; original unknown remains.

Profile-aware API and matching agent non-executing preflights pass after the
decision. New v5 agent listener ready, then API/Web started with all three lab
overlays: API `517de8921634...`, Web `45392bd7edec...`, agent `d972adf099df...`.
No new task, standing grant, credential/trust/network or authentication change.
Post-receipt complete reads, real successor execution, history preservation and
throughput are being checked; not yet measured whole-list acceptance.

Durable audit proves startup epoch 2061 was read-only (18:21:07.683Z–
18:21:20.935Z), followed by three settled write epochs:

- 2062: 18:21:21.287Z–18:22:46.711Z, 14 VERIFIED / 14 ACKs / one pre-write DEFER;
- 2063: 18:22:47.084Z–18:24:12.863Z, 14 VERIFIED / 14 ACKs / one pre-write DEFER;
- 2064: 18:24:13.218Z–18:25:39.356Z, 14 VERIFIED / 14 ACKs / one pre-write DEFER.

The three complete write visits verified **42 in 258.069s (9.76/minute)**,
including gaps. Including the read-only startup gives 42 in 271.673s (9.28/min).
The preceding small v4 sample was 8.18/min; this is an unpaired bounded observed
gain, not a controlled benchmark or adequate whole-list acceptance. Actual batch
size remains deadline-dependent, not a promise of 16. First full v5 agent record:
30 commands, exactly 14 preflights, 14 ADDs and **two** complete reads rather
than four, zero CLI errors/cancellations, zero pending additions at terminal.
Agent event/timing is diagnostic; original epoch-bound job/release audit is the
success evidence. No new unknowns, reimport or consent renewal were submitted.

The reviewed pair has a distinct new attempt `30caf7ae-3cb2-5ee4-96bb-b9fc7c1d6eaa`,
captured from a complete read started 18:24:03.861Z, after the reconciliation
receipt. It was RUNNING at the bounded check, not yet claimed successful. Original
job `db174cf8-3496-53d8-aa78-1096bc39b251` stays UNVERIFIED, original request
CANCELLED with unchanged 17:40:06.650Z expiry. This is a fresh desired-state
attempt, not replay/renewal of the original unknown job.

The new reviewed-pair attempt subsequently became **VERIFIED** at
18:26:58.233Z, using snapshot started 18:24:03.861Z. Its original unknown
predecessor remains UNVERIFIED with the unchanged cancelled/expired delegation.
This completes actual live acceptance of the explicit reviewed-quiescence,
new-full-absence, new-current-attempt path; it does not retroactively prove the
original command. No new grant or old-key replay was used.

Owner-bound diagnostics for all three measured epochs confirm exactly 30 CLI
commands: 14 target preflights + 14 ADDs + two complete reads, with zero command
errors/cancellations/pending at terminal. Epoch 2065 also reports the same
14-address/two-read pattern. Final template assertions explicitly prove the
reviewed-unknown caption preserves the unknown historical result and displays
neither fabricated creation nor an unresolved-hold warning. Final focused set
remains 53 passing; static checks pass. Whole-list execution, production, broad
automatic unknown recovery and cross-session first confirmation remain pending.

Final sample includes all first five settled write visits 2062–2066, each
14 VERIFIED and one exact pre-write DEFER: **70 in 429.536s (9.78/minute)**
including gaps. Last two visits took 85.233s and 85.494s; the initial three were
not selectively retained as the only benchmark. Final 18:28:36Z: original task
7,615/32,425 verified / 24,810 outstanding, ready, no device error or new unknown/
ATTENTION, integrity ok and eight original policy/protection/inventory hashes
unchanged. The one original reviewed UNVERIFIED remains retained. Normal epoch
2067 active, not global idleness; status 1.056s, Web health 200/anonymous 401.
No full-list completion/production/automatic unknown recovery acceptance claimed.

## 2026-11-04 — Evidence-scoped scheduling recovery

Operator reported a locked UI with only cancellation available. Read-only checks
found the original import stopped at 12,582/32,425 VERIFIED, 19,843 outstanding,
two QUEUED jobs, no RUNNING jobs and IDLE epoch 2423. Last complete read was
03:13:16Z. The coordinator's retained error is `database is locked`; the agent's
last session and 14 additions completed normally. Integrity is ok and no new
unknown job appeared; the single historical reviewed UNVERIFIED stays retained.
The runtime remains HTTP-ready even though dispatch stopped, so HTTP health alone
was insufficient. No cancellation, reimport, guard reset or new authority used.

Implement local scheduling retry for numeric SQLite BUSY only, with capped
5/10/20/40/60-second backoff, retained demand and unchanged active sessions. Hints
cannot defeat backoff; orderly stop wakes it. Retry revalidates current scheduling
state rather than replaying worker RPCs/results. Non-BUSY/profile/unknown failures
retain stop/drain and existing evidence-based recovery. Add private/BFF recovery
metadata and compact Status/Queue states with operator guidance instead of a
misleading periodic countdown. Add recovery operator manual and normative scope.
No DDL, credential/trust/network, authority, agent/protocol or feature-gate change.

Validation: full Python 3190 pass in 540.08s, 244 focused lifecycle/concurrency/
recovery checks pass, final classification subset 10 pass, browser 78 pass in
157.55s including a real retry/stopped/recovered DOM flow without device demand.
Compileall, Ruff and diff-check pass. An initial 50ms timing assertion included
first-import overhead; replace it with measured minimum backoff intervals and
rerun successfully. Two restricted-sandbox focused runs stalled and were stopped;
normal local socket/thread runs passed. No product process was terminated by that
test cleanup. Agent source unchanged; no new Rust validation claimed.

Built API/Web `639135b3f440...` / `7e10ec88e7b5...`; configured non-executing API
preflight reports no execution/migration. Retained old compatible images as
`ftd-shun-{api,web}:lab-pre-storage-retry-20261104` and bounded old service logs plus
status/fingerprints in private `/tmp/ftd-storage-recovery-20261104.DrN9qN/`.
Old API `1baf2e6533d5` and Web `7ab80990315e` actually exited 0. Stopped DB remained
IDLE epoch 2423, no RUNNING work, same two QUEUED/one historical UNVERIFIED and
12,588 VERIFIED jobs, integrity ok and all nine original fingerprints unchanged.
No DDL, recovery receipt or unknown-state change. Started only new API/Web using
all three lab overlays; agent `e2d0128319c2` / `d972adf099df...` was not restarted.
Web health 200 and anonymous refusal 401. At 10:09:55Z new API exposes running
recovery, refresh enabled and a complete read at 10:09:48Z; the same original
32,425-pair task has 12,582 VERIFIED and 16 queued. This is startup/read acceptance,
not new ADD proof or a live induced-contention/unknown recovery experiment.

Post-deployment acceptance: read-only epoch 2424 settled in 14.457s; epoch 2425
settled 14 independently VERIFIED ADDs (14 ACKs, one exact no-write DEFER) in
89.583s. These are durable original claim/result/release audits, not timing-based
success inference. At 10:12:02Z the original import is 12,596/32,425 VERIFIED,
19,829 outstanding, normal epoch 2426 active/LEASED. Integrity ok, all nine
original authority/protection/inventory/recovery fingerprints unchanged, no new
unknown/ATTENTION; original reviewed unknown retained. BFF exposes the running
recovery state; shipped JS SHA-256 matches source. No live DB contention/outage
was induced. Read-only metadata snapshots can differ slightly during active
work; no global idleness, full-list completion or throughput gain is claimed.

## 2026-11-04 — Quiet reviewed queue history

Operator correctly reported that the persistent one-unknown warning and red Queue
badge still made an already reviewed historical case look actionable. Diagnosis
found the original epoch-2060 unknown and exact existing reconciliation receipt;
the same pair has a later independent VERIFIED addition. Status had retained raw
UNVERIFIED=1 and presented it as current attention. Nothing was cancelled,
reconciled again, deleted or retroactively marked successful.

Separate read-only unresolved attention counts and a bounded reviewed-history
group after complete optional-profile validation. Keep raw counts/job/attempt/
receipt/audit unchanged. Update Queue warning/badge and add quiet collapsed
Reviewed history with original outcome/reason, review time and IP link; real
Needs attention now precedes long progress/active lists. Legacy or inconsistent
metadata conservatively retains raw warnings. No new schema, acknowledgment,
recovery decision, authority, fence release, agent/protocol or security change.
Focused queue/reconciliation/private-API checks: 105 pass; complete browser rerun
82 pass in 161.75s. A stale DOM-order expectation was updated for the intentional
attention-first layout. Initial new-test fixture/placement mistakes were fixed
before the final focused run; an obsolete full run was stopped and replaced with
a clean full run. Final full Python suite: **3194 pass in 532.53s**;
compileall/Ruff/diff pass. Tests cover raw outcome preservation,
read-only projection, invalid original evidence refusal, separate later unknowns,
legacy/malformed metadata fallback, quiet collapsed history and no browser demand.

Built API `7a005907d019...` / Web `b86fac92f284...`; configured non-executing
preflight passes. Candidate read-only queue projection on actual lab data gives
raw UNVERIFIED=1, zero unresolved attention and one reviewed historical record
still UNVERIFIED. No additional executor or new device operation is started by
that check. Compatible rollback images retained as
`ftd-shun-{api,web}:lab-pre-reviewed-history-20261104`. After all final checks,
announced API/Web-only rollout begins with orderly original-session drain;
agent, original import/authority and all evidence remain unchanged.

Rollout completed: old API `fc50da873188` / Web `5bdeb73b4ed4` actually exited 0.
Stopped DB IDLE epoch 2472, zero RUNNING jobs, raw one historical UNVERIFIED,
integrity ok and all nine original authority/protection/inventory/recovery hashes
unchanged. Retained bounded pre-update logs/status in private
`/tmp/ftd-reviewed-history-20261104.bZxpWL/`. Started matching API/Web with all three
overlays; agent `e2d0128319c2` unchanged. New API `15830248969b`, Web `f42288374e68`.
Deployed BFF reports zero unresolved attention, raw UNVERIFIED=1, one reviewed
historical UNVERIFIED and no unresolved rows. Shipped JS SHA-256 matches source,
history template present; Web health 200, anonymous 401. At 11:17:15Z original
task 13,168/32,425 VERIFIED, normal epoch 2474 active/LEASED, integrity ok and all
nine original fingerprints unchanged; no new unknown/ATTENTION. No new task,
authority, fixture, acknowledgment/recovery or rewritten outcome. Already-open
pages need one reload to replace old browser code; normal ongoing imports retain
their working activity indicator, without the obsolete reviewed-history warning.

## 2026-11-04 — Align policy evidence with complete-snapshot capacity

Read-only runtime inspection found the original import running at 13,292/32,425
VERIFIED with zero unresolved attention and normal recovery state. Source review
found a deterministic larger-import blocker: bulk admission/refill, pre-send
attempt capture and legacy managed restoration each retained a 65,536-IP evidence
cap while the matched full reader accepts 200,000 entries. A valid large read
would therefore fail policy processing before the agreed 100,000-pair import
could complete. No new import or device fixture was submitted to reproduce it.

Use the reader's shared MAX_SNAPSHOT_ENTRIES constant in all three policy guards.
Preserve input/pair capacities, strict complete typed evidence, presence/current
authority/protection/freshness/lease/suspension/cancellation checks, bounded refill/
commands/time, verification and all unknown history. No DDL, agent/protocol,
network/trust/credential/gate or runtime-selection change. Add synthetic tests
at 65,537/95,081/200,000 and rejection at 200,001 without state changes, including
actual bounded discovery, independent evidence capture and suspended/present
refusals. Initial test incorrectly treated a legacy request ID as its job ID;
use its retained request/job link instead. Final dedicated 19 checks pass.
Combined final dispatch/attempt/discovery/legacy-restoration/large-transport
regressions: **255 pass in 21.56s**; compileall/Ruff/diff pass. An early full run
that collected the obsolete request/job assertion was replaced; final full run
now passes **3213 tests in 556.07s**. Configured non-executing preflight also
passes without execution/migration. API-only orderly drain/rollout announced.
Candidate API `f8ab909fdb10...` is built; prior
API retained as `ftd-shun-api:lab-pre-policy-snapshot-cap-20261104`. Web/agent
are unchanged. No live large-capacity or throughput acceptance is claimed.

Also profiled one read-only SQLite snapshot of the original lab dataset, with
query_only enabled and no device requests: three full profile validations and
one complete 32,425-member root scan took 1.364s under cProfile. Root 1.022s /
profile checks 0.334s, with source/member decoding dominant. Instrumentation and
import warmup affect these figures; this is neither a paired speedup nor device
throughput. Retain original root validation, not an authority cache; use these
diagnostics to guide the later execution/batch work after this capacity fix.

API-only rollout completed: old API `15830248969b` actually exited 0; stopped
DB IDLE epoch 2493, zero RUNNING jobs, integrity ok and all nine original
authority/protection/inventory/recovery hashes unchanged. Retained bounded logs/
status in private `/tmp/ftd-policy-snapshot-cap-20261104.5Q3clr/`. New API
`2f00c613a2c7` / `f8ab909fdb10...`; Web `f42288374e68` and agent `e2d0128319c2`
unchanged. All deployed policy/capture/restoration/decoder caps equal 200,000.
At 11:45:54Z same original import 13,412/32,425 VERIFIED, normal epoch 2495
active/LEASED, ready, integrity ok and all nine hashes unchanged; no new unknown/
ATTENTION, unresolved queue counts zero. Fresh read 11:45:30Z, status 0.862s,
Web health 200/anonymous 401. No new fixture, task, consent, renewal, schema or
recovery decision. This is small-observation read/startup acceptance, not live
large-state ADD capacity/throughput proof; the large evidence cases remain
synthetic. Web/Rust sources unchanged; no new browser/Rust run is claimed.

## 2026-11-04 — Explicit bounded multi-group import sessions (candidate)

The operator accepted larger useful batches and shared complete verification.
Read-only initial lab inspection at 13:31:01Z found the original 32,425-pair task
14,338 VERIFIED, normal active epoch 2571, integrity ok and retained reviewed
unknown only. No dataset reset, new import, consent renewal or recovery action.

Implement explicitly selected tracked v6: 240s including opening, 64 combined
mutation attempts, 256 commands and sequence <=130. Keep <=16 pending targets,
immediate per-target preflight, strict ACK, one complete group verification,
result-before-observation publication and actual final settlement. Only complete
initial/intermediate published evidence can freeze a new queue segment; whole-
session refill is <=64 admissions/256 checks, window <=16. Every claim retains
current original-root/protection/cancellation/lease/freshness/uncertainty checks;
no original job deadline is extended. V5 remains explicit default with unchanged
bounds/cutoff; no protocol fallback. Same selection is required on API/agent,
with default-off grouped gate and managed-only runtime. No schema/auth/secret/
trust/network/authority change. Increase agent Compose grace to 300s and document
API-first drain, matching rollback and limits in multi-group-sessions.md.

Synthetic worker/protocol/configured-runtime focused checks: 94 pass, including
four groups/64 addresses over one connection, second-group interruption for
refresh/unblock/protection/cancellation/stop, and retained first-group success
plus later unknowns. A new test initially expected immediate ATTENTION on failed
return; corrected to require retained exact LEASED fencing (expiry can later mark
ATTENTION), never an IDLE release. Sandbox-only socket tests had EPERM/stalled
threads; stopped only the identified test process and reran with local socket
permission. Rust then passed 91 unit +6 config +4 shutdown before the latest
shared-vector/config additions. Final full checks are in progress. Two older
unknown-version tests used now-supported version 6; update them to truly unknown
7 without weakening exact v6 selection. No full-clean run claimed yet.

Known limitations: this does not supply durable cross-session first confirmation
or automatic unknown-write retry. Existing offline reviewed tools intentionally
refuse whole epochs above 16 claims; compatible larger-epoch ledger/review work
is separate, not a reason to bypass evidence. No live v6 activation or throughput
gain is established by synthetic capacity tests. Retain the original task and
all outcomes/receipts/protection during any later matched lab rollout.

### Final validation and initial v6 lab deployment

The first complete Python run had 3237 pass and exactly two obsolete unknown-
version expectations; corrected both to unsupported 7. Focused regression 244
pass; final clean full run **3239 pass in 547.83s**. Final Rust **91 unit +7
configuration +4 shutdown pass**; locked release build, fmt/Clippy, compileall/
Ruff/diff pass. V6 ACK bindings and claim/terminal audit explicitly retain the
selected version; v5 audit shape remains unchanged. Shared v6 vectors bind both
languages. Three-overlay Compose validates using tracked non-secret example
interpolation/no private env-file resolution; only Caddy publishes 443 and agent
grace is 300s. No browser run claimed because no Web/assets changed.

Candidate API `c8e66dbd66c6...`, agent `e8cdc9925a8d...` passed separate non-
executing configured preflights. Exact old images retained as
`ftd-shun-{api,agent}:lab-pre-multi-group-20261104`. Old API actually exited 0;
stopped DB IDLE epoch 2591, zero RUNNING jobs, original reviewed unknown only,
integrity ok and all nine original policy/protection/inventory/recovery hashes
unchanged. Old agent then exited 0 promptly. Only then private `.env` selected
version 6; no secret/trust/network/auth/controller gate changed. Repeat configured
non-executing preflight passed. Start agent, then API, with all three overlays.
No new task, consent, reimport, manual fixture or recovery decision was submitted.

Actual containers: API `7d02442055d0`, agent `ea9085b90bf5`; Web `f42288374e68`
unchanged, health 200/anonymous 401. At 13:59:12Z original import 14,567/32,425
VERIFIED, epoch 2592 normally active/LEASED, cycle limit 64, ready, status 0.978s,
integrity ok/nine fingerprints unchanged and no new unknown. This is startup/read
and dispatch observation, not completed v6 session/throughput acceptance.
Four pre-change released epochs 2576–2579 verified 41 addresses in 290.777s
(8.46/minute, including a short visit); retain this as a bounded unpaired baseline,
not isolated load acceptance. Private evidence: `/tmp/ftd-multi-group-20261104.wwxJsu/`.
Continue observing original durable claims/results/releases before claiming gain.

### Two complete v6 laboratory visits — bounded acceptance

Durable original claim/terminal/release audits prove epoch 2593 VERIFIED 33 in
201.266s, then 2594 VERIFIED 33 in 201.118s. Each has 34 claims, 33 strict ACKs,
one exact before-write DEFER, three confirmed groups 16/16/1 and actual terminal
settlement/release. Total 66/402.819s including gap = 9.83/minute; adding startup
2592 gives 70/446.268s =9.41/minute. Earlier four-visit baseline was 8.46/minute.
This is bounded/unpaired, a modest improvement, not full-list capacity or stable
throughput acceptance. The old 13–14-address visit has become 33 per login in
these healthy samples, not the configured maximum 64. No old outcome is changed.

Argument-free diagnostics independently show one opening (~3.6s), 33 target
preflights, 33 ADD acknowledgements and four complete reads per healthy visit.
Native CLI phases: target reads ~51.5s, ADD ~50.3s, full reads ~10–11s. API call
time ~116–117s and local work ~84s: claims ~47–48s, result persistence ~13–14s,
ACK persistence ~9s, discovery ~6s and lease renewal ~6.6s. These are aggregate
wall times, not isolated CPU/SQLite/FTD costs or execution proof. Local processing
remains a material bottleneck; do not skip original-root/current controls or
claim large-import performance solved. Preserve compatible larger-epoch recovery
and durable cross-session first-confirmation as explicit follow-ups.

At 14:07:10Z original task 14,637/32,425 VERIFIED, 17,788 outstanding; normal epoch
2595 active/LEASED, not globally IDLE. Integrity ok, all nine original hashes
unchanged, no new unknown/ATTENTION, raw historical UNVERIFIED one retained.
Actual private API reports unresolved FAILED/UNVERIFIED zero, reviewed history
one, execution recovery running and ready. Status 1.033s; unchanged Web health
200/anonymous 401. No new task/consent/cancellation/test write/fixture, schema,
credential/trust/network/auth change or offline recovery decision. Continued
original intended blocks stay on FPR; no destructive dataset cleanup is needed.
Private before/stopped/startup/mid/final snapshots, epoch sample and bounded
argument-free diagnostics are retained under the private evidence directory above.
All three overlays and explicit lab v6 remain selected. Final source diff checks
pass; Python/agent results are recorded above, not invented live failure tests.

## 2026-11-09 — Held v6 session and explicit extended recovery

After the operator requested continued development, read-only checks found the
same original import held in ATTENTION epoch 2600 since 2026-11-04T14:27:14.829Z.
Its 26 original v6 claims retain 16 VERIFIED and 10 UNVERIFIED outcomes, reasons
`database is locked`; raw unknown count 11 includes the separately reviewed old
epoch-2060 record. Agent diagnostics report 26 ADD ACK envelopes, ten pending
at failure and no terminal settlement; those logs do not prove original success.
API reports 14,821 VERIFIED/ten unverified original-task members, 17,594 remaining.
The host/services restarted on November 9, but correctly did not release the
hold or replay old commands. SQLite integrity is ok. Preserve this failure;
do not cancel/reimport, relabel outcomes or renew old requests.

Created a new checked 0600 SQLite archive in the private state-volume directory
`private-backups/extended-v6-20261109/source-online.db`, without overwriting live
data. The old November 4 `/tmp` helper/evidence directory is absent after the host
pause; historical records describe that earlier checkpoint, not current file
availability. New diagnostics/rehearsal files use private
`/tmp/ftd-held-session-20261109.gJNiMX/`; useful live backup stays in the volume.

Implement explicit `--extended-v6` review/apply for 17–64 same-epoch system ADDs,
with matching literal v6/group claim/terminal metadata and every old full-root,
job/attempt/request, whole-scope, fresh review, checked backup, quiescence and
foreign-work barrier. Default mode remains <=16; verified-only still rejects
unknowns. New optional immutable `managed_bulk_extended_recovery` binds the exact
compact six-field ordered claims and digest, preserving the 16-KiB receipt bound
and old receipts byte-for-byte. Operator output stays expanded/readable. Profile-
aware schema recognition refuses missing/drifted markers; old writers refuse the
new optional profile. Startup/GET never create it. Reconciliation preserves old
unknowns and requires a complete post-receipt read before any newly authorized
current-intent attempt. No agent/protocol/auth/secret/network or default change.
Documented the procedure and unchanged deferred/missing/manual/REMOVE/FAILED/
foreign-case refusals in extended-session-recovery.md. This is not a generic
automatic unknown-write retry or a claim that SQLite contention is fixed.

Disposable actual-worker tests cover 17/26/64 claims, original job/policy
preservation, compact bounds, old-profile refusal, rollback, damaged/missing
audit and malformed tuples; focused recovery/lease/batch/claim set: 195 pass.
System Python lost its old dev packages after restart, so installed the declared
development dependencies in a task-private temporary virtualenv (Python 3.15),
not system Python or live containers. Ruff/compileall/diff pass. Full tests and
actual-dataset copy rehearsal were initially in progress. The verified application
and its limits are recorded below; do not treat this initial checkpoint as a
claim that merely restarting the host resolves the hold.

### Rehearsal and exact offline application

Full regression completed with 3262 passes in 505.00s. An additional SQL release
guard and direct missing-marker rollback test then passed the final focused
recovery set (77 tests in 18.50s). Clean final-source full rerun then passed
**3263 tests in 500.21s**, with no failures.
Two separate actual-dataset copy rehearsals passed, including the final SQL
guard: legacy and verified-only modes refused, exact 26-claim reconciliation
retained all eleven original unknown jobs, every original job/attempt/request/
policy table and both older base receipts. Integrity/foreign-key checks pass;
the final rehearsal's compact receipt is 5931 bytes. Rehearsal keys/receipts
were never copied into live authority.

Built profile-aware API `d3005b86a025...`, with configured non-executing preflight
before activation. Explicitly stopped API/Web (actual exit 0), then unchanged
agent (actual exit 0). Stopped epoch 2600 remained ATTENTION with no QUEUED/RUNNING
jobs, integrity ok and all nine pre-change fingerprints unchanged. With fresh
whole-DB review at 14:30:37.282Z, checked exclusive 0600 backup and new real
`maintenance:lab-extended-v6-20261109` identity, applied decision
`ed150402-84bc-407b-a1b2-23982d625ca0` at **14:30:43.356Z**. Only original epoch
2600 moved to IDLE. All original 26 outcomes, eleven unknown jobs, attempts,
requests, policy tables and older receipts remain unchanged; compact receipt
5926 bytes. New marker and ten exact unknown-ledger rows are retained atomically.
Backup: `private-backups/extended-v6-20261109/before-live-reconciliation.db` in
the state volume. No guard bypass, original command replay, reset/reimport,
consent renewal or credentials/trust/network change occurred.

Post-activation non-executing preflight passed. Restarted the same agent and Web;
new API container `c8bb2950bdce` is profile-compatible. Old image retained as
`ftd-shun-api:lab-pre-extended-recovery-20261109` is forensic, not a compatible
rollback writer now that the optional marker exists. Do not restore a stale DB
or remove guards/markers to force rollback. Complete owned fresh read at
14:31:33Z is strictly after the decision. Epoch 2601 automatically admitted new
work under the original intent, without a new hint/import/request. At 14:33:58Z
original task 14,837 VERIFIED plus ten observed/reviewed unknowns, zero unresolved
attention; eight original authority/protection/inventory fingerprints and all
unknown rows unchanged, integrity ok. Sixteen new ADDs already have durable
VERIFIED outcomes; the session has not yet settled at this checkpoint. Later
presence never relabels the old unknown results. Web health 200/anonymous 401.

### Bounded post-recovery acceptance

Original audit proves epoch 2601 actually released at 14:34:50.395Z with 33
VERIFIED ADDs, followed by epoch 2602 released at 14:38:10.351Z with 32 VERIFIED.
Each retains one exact pre-write DEFER, not an unknown or fabricated success.
Together **65 in 405.906s including the gap =9.61/minute**. This is bounded,
unpaired continuation evidence, not throughput improvement or whole-list/load
acceptance. Runtime diagnostics also showed a numeric local scheduling BUSY
retry/recovered pair; the already implemented coordinator retry worked without
new uncertainty. No live lock was induced, and ACK/result persistence retry is
still not implemented by this increment.

Final 14:38:27Z snapshot: original import **14,886 VERIFIED/32,425**, ten reviewed
unknowns currently observed (14,896 processed), 17,529 outstanding, zero unresolved
attention. All eleven original unknown rows and eight authority/protection/
inventory fingerprints unchanged; integrity/foreign keys ok. Normal epoch 2603
is active/LEASED, not globally idle. Later holds still require their own evidence;
the epoch-2600 decision is not reusable authority. Clean final-source Python
3263 passed, focused 77 passed, Ruff/compileall/diff and image preflights passed.
Agent/Web sources were unchanged; no new Rust/browser run is claimed here.

This is explicit recovery acceptance for this known lab scope, not automatic
unknown retry, a live SQLite-lock prevention test, completed 32,425-list/load/
production acceptance or durable cross-session first confirmation. Continue
measuring actual settlement and prioritize the local SQLite-contention cause;
never reuse this decision to release a later held epoch.

## 2026-11-09 — Local grouped-result storage resilience (candidate)

Following the operator's request, separated local SQLite result persistence from
remote command execution. The original import remains active; initial read-only
checkpoint 15:04:07Z: 15,133 VERIFIED/32,425, normal epoch 2610 LEASED, eleven
reviewed unknowns retained and zero unresolved attention. No new task, authority,
fixture, device command or recovery decision was submitted by development checks.

Only grouped ACK and ADD-terminal-result callbacks select `persist_result`.
It opens existing WAL storage in mode=rw (never initializes a missing DB), uses
fresh BEGIN IMMEDIATE transactions, numeric BUSY classification and successful
explicit rollback proof after BEGIN. Three attempts, 2s lock waits, 50/150ms
backoff and a 7s retry-start window; check the window again after scheduler wakeup.
The callback repeats only local SQL with the same response/diagnostic and all
original executor/profile/job/attempt/request checks. It never calls the agent,
claims a job, extends lease/session/delegation or changes queue memory before
commit. The base/global queue retains its original transaction behavior via a
private result-commit hook; grouped queues alone select the retry helper.

Commit ambiguity after the transaction ends, failed rollback, absent/wrong
numeric error, non-BUSY, validation/lease failures and exhausted bounds still
propagate into existing uncertainty/fence handling. Earlier target results stay
VERIFIED if later local persistence fails. Fixed phase/count/code diagnostics
report retry/recovery without device text or credentials. No schema/profile,
wire/agent/Web, default/gate, credential/trust/network or authority change.

Initial grouped regression 40 pass; initial storage+grouped set 60 pass. Real
competing SQLite writers exercise ACK/result through the actual synthetic worker,
one connection/one stage per address and one complete verification. Numeric
fault tests cover partial rollback, pre/post-commit failures, count/time/wakeup
bounds, stale lease, failed rollback, duplicate prevention and a later failed
result preserving the first VERIFIED plus eleven UNVERIFIED jobs. A preliminary
full run was deliberately interrupted after the final wakeup guard was added
(454 pass, no failure; not a clean full acceptance). Final focused/full runs
are in progress at this initial checkpoint. Built API `52e05efca40d...` then
passed configured non-executing preflight. Final storage/group/lease/recovery
set: 161 passed in 41.98s; legacy/global paths: 127 passed in 2.52s.
Ruff/compileall/diff pass. Documented the boundary in architecture, plan and
manual/result-storage-retry.md. This is not automatic unknown-write recovery,
a hard preemption deadline for running SQL or a throughput improvement claim.

### API-only deployment

With the complete full regression still running, deployed after the critical
focused checks above. Retained compatible image d3005b86a025 as
`ftd-shun-api:lab-pre-result-retry-20261109`. Explicit API drain actually exited
0, stopped epoch 2613 IDLE, zero RUNNING, integrity ok, all nine original
authority/protection/inventory/recovery fingerprints and all eleven old unknown
rows unchanged. One safe unstarted QUEUED item remains; it was not erased.
Agent/Web containers did not restart. New API `7d82c196f5cc` / image
`52e05efca40d...` started at 15:14:48.854Z with unchanged all-three-overlay
configuration. No schema, backup restore, recovery decision, new consent,
fixture, secret/trust/network or device-command change. Startup 15:14:52Z:
original task 15,231 VERIFIED plus ten reviewed/present unknowns, zero unresolved
attention, epoch 2614 active/LEASED; actual settlement is being observed.

First retained claim/result/release audit confirms epoch 2614 settled with 15
VERIFIED ADDs at 15:16:32.777Z. At 15:17:20Z original task 15,246 VERIFIED,
normal epoch 2615 active/LEASED, complete fresh read, integrity ok/eight authority
hashes and all eleven old unknown rows unchanged, no new uncertainty/attention.
Unchanged Web health 200/anonymous 401 checked. A coordinator-local scheduling
BUSY retry/recovered pair occurred in that visit; no result-storage retry was
observed live or lock induced. The latter acceptance remains real competing-
writer testing on disposable SQLite, not claimed as a live FPR failure test.

### Final validation and bounded acceptance

The clean final-source full Python suite passed **3285 tests in 527.10s**, with
no failures. Final Ruff/compileall/diff pass. No Rust/browser run is claimed:
agent/Web sources and runtime identities are unchanged. Exact original audit
confirms epoch 2615 released at 15:20:00.384Z with 33 VERIFIED ADDs and one exact
pre-write DEFER. Together with startup's 15, **48 additions have actual persisted
verification and session release** after deployment. This is healthy bounded
continuation, not a throughput improvement or completed large-import acceptance.

At 15:20:34Z original task **15,279 VERIFIED/32,425**, ten historical reviewed
unknowns currently present (15,289 processed), 17,136 outstanding, zero unresolved
attention. Normal epoch 2616 active/LEASED, complete fresh read 15:20:11Z, no
device error. Final 15:20:56Z read: integrity ok, all nine original authority/
protection/inventory/recovery fingerprints and all eleven old unknown rows
unchanged. No live result-storage BUSY retry is claimed; real competing-writer
fault acceptance remains disposable/local, not an induced FPR or production test.
Original import continues without reset/reimport, receipt reuse or extra consent.
Durable cross-session first confirmation and measured root/claim overhead remain
follow-up work; this increment does not resolve arbitrary uncertain writes.

## 2026-11-09 — Deferred-confirmation transport foundation (source only)

Continued the agreed next import-completion slice. Read-only initial checkpoint
15:23:40Z: same original 32,425-pair task, 15,312 VERIFIED plus ten reviewed/
present unknowns, normal epoch 2617 LEASED, zero unresolved attention and no
device error. Do not reset/reimport or use those historical unknowns as test
authority. The lab remains on API 52e05efca40d/7d82c196f5cc and agent
e8cdc9925a8d/ea9085b90bf5, with unchanged Web/all three overlays/private v6.

Added a separate tracked-v7 terminal `END_PENDING` (0x1d). The agent returns
status 06 and the exact ordered nonempty pending IP scope, without another
Cisco read or verification. Existing strict post-cleanup/resource/guard/worker
completion supplies the terminal receipt; failure cannot manufacture success.
The Python low-level client validates original ordered ACK identities/sequences,
the exact end scope and terminal binding before returning immutable
`SettledPendingAdditions` with device/session/sequence/ACKs. It has no creation,
interface, snapshot or verified-success field. Missing/lost/malformed ACK/end/
settlement closes without fallback, reconnect or resend. Pending writes still
block ordinary END/snapshot/REMOVE; v7 can still request strict group verification.
V6's 240s/64-attempt/256-command/sequence<=130 limits and pending<=16 remain.
Mutated sessions never acquire read-only completion lookup proof.

This is transport foundation, not an activated mode or completed cross-session
workflow. Current configuration/API high-level client/grouped queue and agent
configuration still refuse v7. The agent's explicit selection gate refuses it
before inventory/SSH. No current job/attempt/lease outcome is changed, no schema
or durable pending authority is initialized, and no new gates/defaults, credentials,
trust, network or Cisco command text exists. No live deployment, fixture, imported
authority, recovery decision or device test write was submitted. Documented the
new boundary and remaining durable queue/causal observation/retry/UI work in
architecture, working plan and manual/deferred-confirmation.md.

Shared Python/Rust fixture covers the exact frame bytes. Synthetic Rust consoles
prove no extra command/read, original stage checks and bounds, pending barriers,
wrong/empty/duplicate scope refusal, cleanup failure and pre-SSH admission refusal.
Real synthetic Unix sockets cover NOOP exclusion, typed pending-only output,
wrong/lost/truncated/reordered scope, foreign/absent terminal and lost ACK without
fallback or duplicate send. Initial focused Python 146 pass; final expanded
transport/worker/snapshot/config set **283 pass in 18.51s**. Rust **95 unit +7
configuration +4 shutdown** pass; locked release build, all-target Clippy, fmt,
Ruff/compileall/diff pass. One old unknown-version=7 expectation was objectively
stale; moved it to 8 while retaining high-level v7 refusal. The first full run
was interrupted with that one failure/396 passed; clean final full regression is
running, not yet claimed. Local release binary is validation, not deployment.

Actual release-binary preflight with isolated synthetic inventory/credentials
accepted v6 (all normal ADD/group gates enabled) and refused v7 with the exact
configuration-selection error. Neither process bound its synthetic socket or
started SSH; no live inventory or secret was used. Synthetic files are private
under `/tmp/ftd-pending-end-check.EE5vdJ/`. This is an additional admission guard
check, not a v7 lab deployment or write acceptance.

### Final validation and unchanged-runtime check

Clean final-source full Python suite: **3324 passed in 527.36s**, no failures.
Final Ruff/compileall/diff and Rust fmt checks pass; locked release/all-target
Clippy and 95+7+4 Rust checks are recorded above. No browser run is claimed for
unchanged UI code. At 15:42:56Z lab integrity ok, all nine original authority/
protection/inventory/recovery fingerprints and all eleven historical unknown
rows are unchanged. Source-only transport work never replaced an image or
selected v7 in the lab.

Read-only status caught a normal coordinator-local numeric scheduling BUSY at
15:43:33Z; retained diagnostics prove automatic retry/recovered at 15:43:38Z,
without an agent command replay or new unknown. At 15:44:12Z execution recovery
is running, last_error null, zero unresolved attention; original task
**15,502 VERIFIED/32,425**, ten reviewed/present unknowns (15,512 processed),
16,913 outstanding, ordinary next session active. This is unchanged v6 import
continuation, not live v7 or induced storage-fault acceptance. Next implement
the explicit durable pending profile and causal confirmation/absence handling;
no current RUNNING/UNVERIFIED/old receipt is permission to skip that work.

## 2026-11-09 — Durable settled-pending evidence and causal observation (source-only)

Implemented `pending_confirmation.py` as an internal default-disabled composition
hook over three immutable optional tables: exact terminal sessions, ordered
original members and first complete observations. Explicit initialization requires
the existing device-scoped bulk profile, quiescence and a durable mutation pause;
startup/GET/constructors never install it. Extended the exact-profile validator
without changing old profile DDL or dropping retained recovery profiles. Older
writers refuse the optional schema. No initialization CLI, public route, new
configuration flag or runtime selection was added.

Atomic recording requires the actual typed settled-v7 transport receipt, exact
original RUNNING device scope, ordered ACKs and original live owner/epoch/group/
version/sequence claim and ACK audits. Validate original attempt/delegation and
complete source root; recheck the same lease before/after insertion. Retain a
conservative local post-receipt settlement time rather than guessing from remote
output. Missing ACK/cleanup proof, v5/v6 audit, foreign/expired lease, damaged root,
wrong/duplicate/reordered scope and capacity exhaustion refuse without partial
ledger writes. No receipt replay replaces an existing terminal session.

Classification uses one typed complete same-device snapshot started strictly
after settlement, finished by now and started within 120 seconds. Retain its ID,
times, SHA-256 of the full sorted packed-address set and exact present member
ordinals. Shared snapshot identity requires identical device/times/content.
The first observation is immutable; exact fresh replay writes nothing. Partial,
stale, future, foreign and pre-settlement/overlapping reads classify nothing.
Restart inspection exposes AWAITING_CONFIRMATION, OBSERVED_PRESENT or
CONFIRMED_ABSENT as evidence labels only, never original creation provenance,
verified progress, automatic unknown resolution or retry permission.

Original jobs/attempts/requests, standing authority, protection/cancellation waits,
events, occurrences and leases are unchanged by record/classify. RUNNING still
blocks release. Tests explicitly preserve cancellation/protection behavior;
RUNNING import cancellation keeps its original ordered wait (it does not instantly
retire the target), while enabled protection retires matching authority. Corrected
an initially overbroad test expectation of immediate retirement for both paths;
no existing behavior was changed to satisfy it. A test-only v7 audit producer is
not a relaxation of the real grouped queue's v5/v6 guard.

Initial final ledger suite: **55 passed in 6.55s**. Earlier focused scope passed
267 checks before the shared-snapshot identity/final three test cases; final
focused and full regression are running, not yet claimed. A preliminary full run
was deliberately interrupted at 371 passed to complete those final checks.
Ruff/compileall/diff pass. Synthetic tests exercise restart/read classification,
immutable/retained scope, initial/final lease checks, atomic rollback, capacity,
source/audit corruption, profile refusal, cancellation/protection preservation
and coexistence with existing recovery/reconciliation/extended marker profiles.

No lab schema/profile, `.env`, service image, credentials/trust/network, original
import/authority, recovery decision or test device command changed. Read-only
16:08:00Z lab check: integrity ok, original nine fingerprints and all eleven
unknown rows unchanged; normal epoch 2631 active/LEASED, not global idleness.
Current API remains 52e05efca40d with the v6 agent/Web runtime described above.
Queue/attempt awaiting-state transitions, safe actual-settlement lease release,
current-policy/backoff fresh admission, UI and priority/protection/cancellation
integration remain unfinished. Do not enable v7 or install the source-only
ledger in the live database before that compatible worker contract is complete.
This is not live deferred confirmation, a speedup or whole-import acceptance.

### Final focused validation and unchanged-runtime comparison

Final-source focused persistence/transport/protection/cancellation/lease set:
**270 passed in 70.15s**. Ruff/compileall/diff pass. Clean final full regression
is still running. Read-only 16:14:19Z comparison against the pre-change baseline:
integrity ok, all nine original authority/protection/inventory/recovery fingerprints
and all eleven unknown rows unchanged. Normal epoch 2633 LEASED/active; no hold
release or inferred global idleness. At 16:14:36Z API status ready/no error,
execution recovery running, zero unresolved attention; same original task
**15,793 VERIFIED/32,425**, ten reviewed/present unknowns, 16,622 outstanding.
SQLite catalog confirms zero `managed_bulk_pending_*` objects in the lab.
No service image/agent/Web/profile was replaced by this source-only increment.

### Full regression result and corrected old-reader simulation

Full regression finished **3378 passed /1 failed in 516.83s**. The sole failure
was `test_old_expected_profile_refuses_extended_marker_and_damaged_marker_still_blocks`:
its simulated older reader used `args[:-1]`. After adding the pending option,
that no longer removed the earlier extended-profile option, so it accidentally
simulated a reader that supported the very marker it should refuse. Changed the
test to explicitly use the nine pre-extended options (`args[:9]`), preserving
the refusal assertion and production guards. The corrected compatibility test
and all 55 new ledger cases pass together: **56 passed in 7.73s**. No second
clean full run is claimed. Final Ruff/compileall/diff checks pass. Two isolated
non-escalated async test attempts were interrupted after they stopped making
progress in restricted execution; no pass is claimed for them. The reported
corrected run used the same normal local async/
socket permissions as the full suite. No laboratory fault was induced.

## 2026-11-09 — Fresh deferred queue states and atomic settled-session handoff

Added source-only `PendingExecution`, an explicit fresh-empty execution profile
and default-disabled internal hooks over the original pending evidence ledger.
Job/attempt/captured cancellation-result schemas recognize AWAITING_CONFIRMATION,
OBSERVED_PRESENT and CONFIRMED_ABSENT without relabelling old failures/unknowns
or claiming created occurrences/interfaces/import origins. Exact job schema,
immutable profile marker, original member links and SQL transition guards are
validated. Current coordinator refuses this profile before agent calls; current
configuration/high-level client/grouped queue/agent still refuse selecting v7.

Initialization requires existing evidence/device profiles, paused mutations,
quiescence and empty execution/history tables. It replaces only those checked
empty queue/attempt/result layouts in one transaction; no copy/conversion/delete
of retained data. Even VERIFIED history refuses. There is no startup/GET DDL,
new configuration selector, public route or operator initialization CLI. New
execution does not yet compose with ordered-removal/offline recovery profiles;
the standalone ledger's older recovery combinations remain unchanged. This is
not a converter or permission to reset/reimport the original 32,425-pair lab DB.

`await_confirmation()` atomically validates/stores the exact original settled-v7
receipt/root/delegation/claim/ACK scope, changes the whole group and original
attempts, emits original-identity queue/attempt audits and releases the same live
lease. Added caller-owned connection composition to existing evidence and private
lease release, retaining their default standalone transaction contracts. Failure
at evidence, audit, release or final deadline rolls back everything. No remote
command is retried; other unresolved device work refuses this handoff. Restart
cannot see new awaiting state with its old unreleased owner after a successful
commit. Old RUNNING/UNVERIFIED work without this proof remains fenced.

`confirm()` requires a live current same-device visit and its first complete read
started after original settlement. Read verdict, exact queue/attempt results,
request closure, real-identity audits and captured cancellation settlement commit
together. Original delegation expiry does not forbid read-only confirmation and
never grants another write. Exact immutable first-read replay adds no events or
results. Cancellation before/after handoff waits; known presence keeps applied
policy and known absence retires only the exact cancelled target without error
attention. Enabled protection permanently retires matching policy; neither a
later observation nor disabling protection re-enables it.

Queue reads expose awaiting state without success. Import progress counts
awaiting confirmation and known-absence `awaiting_retry` as outstanding, observed
presence as `present`, never `verified`. Retention preserves all original ledger-
linked jobs/requests/results. Ordinary discovery explicitly refuses deferred
terminal outcomes until capped-backoff/current-policy fresh-attempt admission is
implemented. No automatic unknown retry or end-to-end new mode is claimed.

New synthetic suite: **36 passed in 5.41s**. Final focused state/ledger/protection/
cancellation/progress/lease/group/uncertainty set: **249 passed in 25.17s**.
Ruff/compileall/diff pass; full regression is running, not yet claimed. Tests cover
initialization rollback/idempotence/history refusal, actual state+lease atomicity,
original token fencing, invalid reads, unknown work, raw state laundering, audit/
deadline rollback, protection/cancellation ordering, restart after old delegation
expiry, no automatic fresh job, pending progress and retained terminal evidence.
An initial test used the wrong conflict subclass; corrected it to expect the
existing ManagedConflict instead of altering the guard. One restricted async
focused attempt stopped making progress and was interrupted; no pass is claimed
for it. The reported final focused run uses normal local async/socket permissions.

No live schema/profile, images, `.env`, credentials/trust/network, original import/
authority, recovery decision or test device command changed. Read-only 17:38:34Z
comparison: integrity ok, all nine original authority/protection/inventory/recovery
fingerprints and all eleven historical unknown rows unchanged. Normal epoch 2657
was active/LEASED, not globally idle. The same v6 API/agent/Web and original import
continue. Next implement new-attempt backoff/current authority and matched worker/
priority/UI/ordered-removal behavior, then separately scoped fresh lab acceptance;
do not enable v7 or install this fresh profile into the running historical DB.

### Clean final regression and unchanged laboratory runtime

Clean full-source Python suite: **3415 passed in 544.57s**, no failures. This
also covers the earlier corrected pre-extended-schema simulation. Final focused
249 checks and new 36-case suite are recorded above; Ruff/compileall/diff pass.
No Rust/browser run is claimed for this Python-only increment.

Final read-only 17:46:29Z DB comparison: integrity ok, all nine original authority/
protection/inventory/recovery fingerprints and all eleven historical unknown rows
unchanged. Normal epoch 2660 active/LEASED, not global idleness. Exact unchanged
containers/images are API `7d82c196f5cc` / `52e05efca40d...`, agent `ea9085b90bf5` /
`e8cdc9925a8d...`, Web `f42288374e68` / `b86fac92f284...`, all running. API status
at 17:42:29Z ready/no error, recovery running, zero unresolved attention; same
original task **16,643 VERIFIED/32,425**, ten reviewed/present unknowns, 15,772
outstanding. SQLite catalog shows zero pending-schema objects. No new profile,
device test command, recovery receipt or authority was applied. The runtime
still uses v6; synthetic fresh-profile handoff is not live v7 or throughput
acceptance. Next current-policy/backoff fresh attempts and matched worker/
priority/ordered-removal/UI integration before a new bounded lab validation.

## 2026-11-09 — Confirmed-absence fresh jobs with bounded backoff

**Status:** Source-only internal composition; current lab and original import
remain on v6, without live DDL/deployment or configured retry activation.

Added default-disabled `PendingRetries.admit()` on the explicit fresh-empty
deferred execution profile. A 1–16-member transaction creates fresh job/attempt/
execution-request IDs after exact settled CONFIRMED_ABSENT predecessors, retaining
original outcomes, standing intent and immutable predecessor/origin/read/owner/
epoch/audit provenance. It composes the existing shared queue's original full-root,
current intent/generation/authorization/revision, protection/cancellation/device,
pause, serialization, uncertainty, capacity and fresh-evidence checks. Claims
recheck current permission; revocation cancels unstarted children, not old evidence.
Original expired delegation stays expired; new requests have their own bounded
900-second execution lifetime under unchanged standing consent.

Backoff is 5/10/20/40/60 seconds capped; at most 12 fresh retry admissions per
device/IP/rolling hour across origins. `RetryDeferred.retry_at` is a typed UTC
scheduling wait, not failure/attention or permission to extend a read deadline.
The first confirming read may be reused only with identical device/ID/times/full
address-set digest and existing 120-second freshness/current visit. New evidence
starts strictly after the predecessor result. Shared read IDs cannot change
content between admissions. Only same-origin known absence is exempted from its
own result-time barrier; unrelated history retains causal checks. Existing
ordinary admission retains its previous churn limits.

Another child blocks replacement unless CANCELLED and never claimed. Claimed
even if subsequently deferred-before-write, pending/sent/failed/unknown children
never gain automatic replacement. Later absent children use their own first-read
proof. OBSERVED_PRESENT does not authorize this first-confirmation retry path.
Original-key replay reads retained history after revocation without renewing
authority, deadline, lease or a remote command. Partial scope, stale/foreign/
changed evidence, late lease expiry and mixed ineligible portions roll back all
new jobs/provenance/audits atomically.

Extended queue and audit retention to preserve pending members and retry children
(including cancelled never-claimed jobs), execution requests, all associated
request events and referenced DEVICE_LEASE_CLAIMED audits. Full retained binding
validation precedes pruning outside intermediate result transactions; missing
admission audit or request/job link refuses all deletion. Unrelated expired
events still purge. This also fixes the evidence ledger's claim/ACK foreign-key
conflict with ordinary event retention; evidence is retained rather than deleted
or converted into apparent nonexecution.

Updated normative design, manual index/contract, working plan and agent/status
records. No initializer CLI/public route, schema conversion, configured v7
selector, worker loop, live deployment, original import reset/reimport, new consent,
recovery decision, credentials/trust/network change or test device command.
Matched worker/priority/removal/UI, later confirmed-presence disappearance
restoration and bounded separate-fresh-DB lab acceptance remain next.

Final validation is recorded in the follow-up below. One initial focused
command referenced nonexistent `tests/test_history.py` and collected no tests;
it was corrected to the real store/history modules. Two intermediate full runs
were deliberately interrupted after 454 passes each when strengthening retention
bindings and then bidirectional shared-read identity validation. No clean full
pass is claimed for those superseded runs. The final focused profile/retry/store/
history set passes **144 tests in 19.20s**. Read-identity coverage includes a later
confirmation attempting to reuse an already-bound retry-read UUID with different
times/content: the observation transaction refuses, leaving the original verdict
and new awaiting group intact. Ruff/compileall/diff pass; final full regression
is running.

### Current-data compatibility check, no activation

Created a new private consistent SQLite backup through the running API with its
original DB opened read-only. Docker archive copy could not see the temporary
tmpfs file; transferred that already-created copy through exec instead. An initial
in-memory restore refused its WAL header; normalized **only the temporary copy**
to DELETE journal mode, then restored it into the separate private target
`/tmp/ftd-fresh-retry-check-20261109.yVn63L/runtime.db`. No live journal/configuration
or source data was changed. Copy integrity is ok.

The current candidate Python source opened that target in `mode=ro`/query-only,
validated the exact existing composite profile and all **four full import roots /
32,430 members**. Integrity ok, total_changes=0, pending-schema objects=0. No
initializer, scheduling/admission/claim callback, agent connection or device command
ran. This validates compatibility with the retained current-data profile, not
activation, throughput or unknown recovery. The copy is private temporary evidence,
not a new authority receipt or a stale-DB runtime rollback plan.

Read-only live comparison at 18:10:58Z: integrity ok, all nine original fingerprints
and all eleven original unknown rows unchanged; normal epoch 2667 active/LEASED.
At 18:14:17Z API ready/no error, recovery running, zero unresolved queue attention,
retention_error null; same original task **16,937 VERIFIED/32,425**, ten reviewed/
present unknowns and 15,478 outstanding. Exact API/agent/Web IDs/images remain
unchanged and running. No lab deployment or test device command was submitted.

### Final read-only laboratory checkpoint

At 18:25:40Z: integrity ok, all nine original authority/protection/inventory/
recovery fingerprints and all eleven historical unknown rows unchanged. Normal
epoch 2671 active/LEASED, not global idleness. At 18:25:46Z: same original task
**17,050 VERIFIED/32,425**, ten reviewed/present unknowns, 15,365 outstanding;
ready/no error, recovery running, zero unresolved attention, retention_error null
and zero pending-schema objects. No live profile, service/image, gate, original
authority, unknown outcome or recovery decision changed. This observation does
not establish deferred-mode execution or a throughput improvement.

### Clean final regression

Final-source complete Python suite **3451 passed in 574.10s**, no failures.
Final focused profile/retry/store/history set **144 passed in 19.20s**, including
36 new retry cases. Ruff/compileall/diff pass. No Rust/browser run is claimed for
this Python-only slice. No deployment or activation followed these checks.
Next matched worker/priority/removal/UI and later confirmed-presence disappearance
restoration before bounded live acceptance with fresh labelled authority in a
separate clean store; preserve the original v6 import and all retained evidence.

## 2026-11-09 — Explicit deferred per-visit worker and command-boundary priority

**Status:** Source-only internal opt-in; not configured startup, live v7 mode or
the continuous retry daemon. Current v6 laboratory import/runtime are unchanged.

Added `DeferredParallelSynchronizer` and separate fresh-profile v7 queue/session
subclasses. Ordinary grouped queue/session version admission stays v5/v6. Matching
strict tracked client capabilities, exact fresh storage, fixed device inventory/
concurrency and settlement are checked; construction/startup never initializes or
converts storage. No public configuration/client/agent v7 selector was enabled.

Factored a common complete-read processing hook in the existing collector and
grouped session. Ordinary paths retain publication then discovery. The deferred
worker creates one evidence identity, confirms at most 16 prior groups in one
current-lease BEGIN IMMEDIATE transaction, then publishes that same read and
admits fresh retry/ordinary work. Any failed classification rolls back all groups
and publishes nothing. Optional caller-owned confirmation transaction preserves
the original standalone checks/semantics. Internal retry selection checks at most
64 candidates/admitting up to 16 per complete read within the device window;
each real admission still checks current full authority/protection/cancellation/
uncertainty/capacity/time. Advisory cursors and wait metadata are not authority.

Intermediate groups retain strict verified result-before-snapshot settlement and
fresh cutoff renewal. Only the final nonempty acknowledged group calls actual
END_PENDING, requires actual terminal completion and commits its exact original
handoff/lease release. No final read, publication/freshness callback or verified-
progress increment is invented. The old visit checks its retained handoff rather
than releasing again or touching a possible successor lease. Empty/read-only
visits keep strict normal END/release. Synthetic 64-attempt visits verify three
16-member groups and leave only the last 16 awaiting a later complete read.

Refresh demand, priority REMOVE and enabled protection flush the current group
at a command boundary before proceeding in the same serialized SSH session.
Stop/pause/import cancellation can settle the final group awaiting observation.
Next-read cancellation/protection retirement remains original; caller cancellation
drains the actual RPC and required terminal evidence. Lost ACK/terminal evidence,
mismatched original scope, absent settlement and failed local handoff keep original
unknowns/fences; no old RPC, completion journal or generic presence permits replay.
NOOP preflight is excluded from pending creation scope.

The new internal status reports awaiting counts, confirmation outcomes and bounded
retry counts/next eligible UTC waits. This is not public UI wiring or a timer
that initiates visits. Continuous scheduling/public transport/configuration/UI,
ordered managed/fleet cleanup, compatible deferred recovery, later OBSERVED_PRESENT
disappearance restoration and claimed/pre-write-deferred retry-child replacement
remain unfinished before bounded fresh-store lab activation.

Validation: **31 new synthetic worker tests pass in 13.37s**; final focused shared
worker/queue/pending/parallel/continuous/timing **245 pass in 62.62s**. Ruff/
compileall/diff pass; full final-source regression is running. Tests cover restart
read-before-publication, automatic fresh admission on later visits, typed waits,
64-attempt visits, lost stage ACK/terminal proof, foreign/reordered scope, local
handoff rollback, successor lease protection, priority/protection ordering, caller
drain, cancellation retirement, multi-device overlap and all-group observation
rollback. Initial checks caught one obsolete error-text assertion and a two-device
test race: remote cleanup precedes local DB handoff. The test now explicitly waits
for the real committed state instead of treating the remote signal as commit proof;
no product guard was weakened. An initial patch-format error made no file change.

No live DDL/deployment, `.env`, inventory, credential/trust/network change, original
task reset/reimport/new authority/recovery decision or test device command. Synthetic
visits are not live Cisco throughput, 100,000-list or production acceptance.

### Unchanged laboratory runtime

Read-only comparison at 18:53:05Z: integrity ok, all nine original authority/
protection/inventory/recovery fingerprints and all eleven historical unknown rows
unchanged; normal epoch 2679 active/LEASED, not global idleness. At 18:55:20Z
the same original task has **17,324 VERIFIED/32,425**, ten reviewed/present
unknowns and 15,091 outstanding. API ready/no error, recovery running, zero
unresolved queue attention, retention_error null and zero pending-schema objects.

Exact unchanged images/containers remain running: API `52e05efca40d...` /
`7d82c196f5cc`, agent `e8cdc9925a8d...` / `ea9085b90bf5`, Web `b86fac92f284...` /
`f42288374e68`. All three lab overlays/current v6 selection remain intact. No
new profile, authority, recovery decision, fixture or test FTD command was applied.

### Clean final regression

Final-source complete Python suite **3482 passed in 575.63s**, no failures.
Focused shared orchestration/queue/pending/parallel/continuous/timing **245 passed
in 62.62s**; new worker suite **31 passed in 13.37s**. Ruff/compileall/diff pass.
No Rust/browser run is claimed for this Python-only slice. No deployment or live
activation followed the checks. Next continuous confirmation/retry-wait timing,
public status/UI/configuration and remaining removal/recovery/restoration contracts
before a new labelled bounded fresh-store lab validation; keep the original v6
task, authority, protection, unknown history and all recovery evidence intact.

## 2026-11-09 — Continuous deferred confirmation/retry scheduling and neutral Queue UI

### Scope and implementation

Added explicit internal/default-disabled `DeferredContinuousDispatcher` over the
existing continuous scheduler and strict fresh-profile worker. A settled pending
group requests another causal complete read without a periodic-interval wait;
read-only confirmation remains allowed during mutation pause. Require the next
millisecond after stored settlement. A rotating bounded 64-candidate advisory
scan shares retry backoff/rolling-hour arithmetic with admission and requests new
read evidence when eligible. The timer grants no authority, renews no delegation,
replays no RPC and never sleeps inside an SSH session. Existing original root/
current intent/protection/cancellation/lease/uncertainty checks, pool/priorities
and scheduler backoffs remain. Ordered-promotion composition refuses explicitly.

Added narrow base scheduler composition/read hooks with unchanged ordinary
defaults. Already settling/awaiting terminal sessions retain refresh demand for
the next actual read, rather than pretending END_PENDING refreshed anything.
Status exposes bounded per-device sampled eligibility, not a total or successful
outcome. BFF projection preserves that metadata. Existing Queue popup recognizes
neutral awaiting confirmation and known observation/absence outcomes, plus absence
retry eligibility; awaiting jobs remain active without running animation or a
queued-job cancel control. Whole-import labels distinguish waits. Real unknowns,
errors, protected-policy semantics and authentication/CSRF boundaries are unchanged.

### Validation and limits

Initial new coordinator tests corrected fixture expectations (existing profile
concurrency, field names, error type and pre-start callback setup). The lost-END
test checks the actual retained non-IDLE fence, not an invented immediate
ATTENTION transition. No product guard was weakened. Eight initial end-to-end
tests passed in 9.64s. The final new scheduler set has ten cases, including strict
ms causality and a synthetic bounded-selection rotation with zero admitted work.
Focused shared scheduler/worker/queue/retry/parallel **190 pass in 66.15s**;
browser/Node **88 pass in 114.97s**, including actual production templates/JS
against a local synthetic BFF. Ruff/compileall/diff pass. Complete Python
regression is running; final results will be recorded below.

No live DDL, profile selection, deployment/restart, `.env`/inventory/secret/trust/
network change, original task reset/reimport/renewed authority/recovery decision
or test FTD command. Current configured API/client/agent still refuse v7, and the
original v6 import continues. No Rust change/run or live v7/large-list throughput
acceptance is claimed. Next finish ordered managed/fleet cleanup, compatible
deferred recovery, later confirmed-presence disappearance restoration and
claimed/deferred retry-child replacement, followed by deliberate fresh-store
configuration and bounded lab acceptance. Updated architecture/manual/plan/status
and agent handoff records; no legacy development converter is a release gate.

### Read-only laboratory observations

At 19:18:44Z, integrity is ok, all nine original authority/protection/inventory/
recovery fingerprints and all eleven historical unknown rows match the preceding
worker checkpoint. Normal epoch 2687 is active/LEASED, not globally idle. Exact
API `52e05efca40d...` / `7d82c196f5cc`, agent `e8cdc9925a8d...` / `ea9085b90bf5`
and Web `b86fac92f284...` / `f42288374e68` remain running, all three overlays.
No deferred-schema objects were added.

At 19:18:00Z the original import has 17,550 VERIFIED/32,425 plus ten reviewed/
present unknowns and 14,865 outstanding; ready, recovery running and zero
unresolved queue attention. The status also reported `OperationalError: database
is locked`. Retained diagnostics show numeric scheduling SQLITE_BUSY/automatic
recovery and a maintenance expiry contention error; settled epoch 2686 completed
with continued VERIFIED results. No intervention, induced failure, new recovery
decision or claim that contention is eliminated follows from these observations.

At 19:22:18Z status is ready, `last_error` null, recovery running, zero unresolved
queue attention/retention error and zero pending-schema objects. Original task
17,583 VERIFIED/32,425 plus ten reviewed/present unknowns, 14,832 outstanding.
This is a bounded healthy continuation observation, not a new deployment or proof
that every storage-contention path is resolved. Final new scheduler suite:
**10 passed in 10.69s**, including read-only BFF projection.

### Final regression

Clean complete Python regression **3492 passed in 559.54s**, no failures. Focused
shared set **190 passed in 66.15s**, final scheduler set **10 passed in 10.69s**,
browser/Node **88 passed in 114.97s**. Ruff/compileall/Node syntax/diff checks pass.
No deployment or live v7 acceptance followed these checks. Source-only mode stays
default disabled; current v6 task, unknowns and authority remain intact.

## 2026-11-10 — Deferred managed restoration and ready device/fleet cleanup

### Implementation

The explicit fresh deferred profile now treats OBSERVED_PRESENT as a known
terminal observation, not permanent restoration inhibition or service-creation
proof. A later causal complete absence read can admit a new ordinary managed
attempt under current exact intent/generation/authorization/revision. Normal
300-second pair backoff/three admissions per rolling hour remain. In this exact
profile only, later validated VERIFIED/NOOP/OBSERVED_PRESENT can supersede strictly
earlier known absence in that same scope for scheduling. Original results/audits
stay unchanged. Newer known absence keeps the explicit fresh-retry contract;
unknowns, protection/retirement/suspension, current roots, lease/freshness and all
original admission/claim gates remain. No old RPC is replayed or delegation renewed.

Ready-only admission now explicitly rejects AWAITING_CONFIRMATION before any
policy retirement/queue mutation. Ordered inspection and its strict BFF validator
recognize ADD_AWAITING_CONFIRMATION as BLOCKED, not READY or a waitable RUNNING
predecessor. The actual review template gives readable refresh/review guidance
without creating a token. After confirmation, existing fresh frozen ready consent
can atomically retire the entire selected device/fleet scope and enqueue one
shared REMOVE request. Verified cleanup does not later re-add the address. No
ordered pending capture/promotion or new schema/configuration selector is implied.

### Verification

New disposable strict-v7 lifecycle set **23 passed in 11.94s**. Coverage includes
disappearance/restoration, repeated known-absence/presence chains, strict VERIFIED
and NOOP retry results, normal backoff/churn, cross-generation and causal-read
refusal, protection retirement even after disable, policy revocation/pause/device
scope, retained applied policy after import cancellation, unknown preservation,
pending/stale removal refusal, exact-key replay, whole-fleet cleanup and late
audit rollback. The blocked-review test renders the real template and checks that
no confirmation token exists. Initial fixture errors were corrected to use the
actual Store/ProtectedPolicy methods and required suspended standing admission;
no product guard was weakened. Focused shared dispatch/discovery/removal/retry/
worker/scheduler/Web set **342 passed in 85.16s**. Browser/Node **88 passed in
147.93s**; Ruff/compileall/diff pass. Full regression is running; final results
will be recorded below. No Rust change/run or live v7 acceptance is claimed.

### Unchanged runtime and newly observed lab hold

No deployment/restart, live DDL, selector/default/`.env`/inventory/credential/trust/
network change, original task reset/reimport/new authority/recovery decision or
test FTD write was performed. Current lab remains the original v6 runtime.

Read-only 10:02:21Z comparison: integrity ok, all nine original authority/
protection/inventory/recovery fingerprints and eleven historical unknown rows
unchanged; zero pending-schema objects. Original import is **25,092 VERIFIED /
32,425**, ten reviewed/present unknowns, 7,323 outstanding. Status is ready but
reports device attention; normal scheduling is running, unresolved queue counts
zero, retention error null. This is **not healthy import progress**: device 1 is
held at ATTENTION epoch 2921 since 08:47:54.981Z, before this development turn.

Original audit has 33 claims: 32 VERIFIED and one exact same-owner/epoch v6
SHUN_OPERATION_DEFERRED with write_sent=false. That job
`d9203d0e-c518-53be-810b-bc8a69d07cc4` / attempt
`1da27139-6f0f-5063-8d69-de69843ac1b9` returned to QUEUED at 08:46:33Z and became
CANCELLED at 09:01:33Z after its original delegation expired. Agent diagnostics
report final full-read send failure (`could not send fixed Cisco command to FTD
shell`), zero pending additions, protocol v6/session
`41530116d06b45ccaa7239ac6db01851`; API reports unsettled final cycle. Logs alone
do not release the fence. The exact retained claim/defer/results, not generic
observed presence, identify this narrower failed case.

Existing extended recovery covers VERIFIED/NOOP or reviewed unknowns, not a
claimed/deferred/CANCELLED member. No tool/guard/row/receipt was changed to force
this scope to fit, and no recovery or restart was attempted. Next implement a
compatible proof-based recovery contract for this exact mixed scope, preserving
all current authority, unknowns and original outcomes. Also finish deferred
ordered capture/recovery/claimed-child replacement and deliberate configured
fresh-store lab acceptance; current source is not an enabled v7 product mode.

### Final regression and handoff

Clean full Python regression **3515 passed in 613.08s**, no failures. Focused
shared set **342 passed in 85.16s**; browser/Node **88 passed in 147.93s**;
Ruff/compileall/diff pass. Exact current API `52e05efca40d...` / `7d82c196f5cc`,
agent `e8cdc9925a8d...` / `ea9085b90bf5` and Web `b86fac92f284...` /
`f42288374e68` were checked running and unchanged. These checks did not deploy
new source, release epoch 2921 or resume the held import. Keep its exact evidence;
compatible mixed VERIFIED/pre-write-DEFER recovery is the next practical task.

## 2026-11-10 — Exact cancelled pre-write-DEFER recovery

Implemented separate explicit `--extended-v6 --prewrite-defer` offline recovery
for 17–64 original system ADD claims, exactly one final expired/cancelled typed
pre-write DEFER and otherwise VERIFIED/NOOP. Full original owner/epoch/version/
source/action/claim/requeue/defer/cancellation/job/attempt/request evidence is
required; no ACK, subsequent claim, uncertainty or generic CANCELLED interpretation.
Equal timestamps use queue sequence instead of UUID order; original requeue is
selected by exact typed reason, not arbitrary ordering among equal timestamps.

The distinct compact profile retains the original 16-KiB receipt bound and adds
immutable `managed_bulk_prewrite_recovery` proof/full-scope count/digest. Existing
recovery/reconciliation receipts and modes remain unchanged. Exact SQL marker
guards, full current root checks, actual executor-stop assertion, five-minute
whole-DB review, exclusive checked backup and post-receipt read barrier remain.
No startup/GET DDL, old job replay/outcome change, authority renewal or v7 mode.
Retention preserves original proof and refuses missing/corrupt bindings. Old
readers refuse the new exact schema rather than silently ignoring the marker.

Focused recovery/history **116 passed in 45.42s**; Ruff/compileall/diff pass.
Actual-copy rehearsal on the 203,100,160-byte consistent private SQLite copy
passed: all 33 claims, 32 VERIFIED/one CANCELLED, zero jobs retried. Eleven
original data tables and every prior recovery receipt match the checked pre-
rehearsal backup; integrity/profile valid. Rehearsal key
`d70c8d93-3549-4d78-9cff-88656c729097` is consumed on that copy only and must never
authorize the original DB. Private artifacts are under
`/tmp/ftd-prewrite-rehearsal-20261110.Z2dIib`; API/agent epoch-2921 diagnostics were
retained there as private logs. Docker cp could not access the API tmpfs artifact;
explicit tar transfer to the private directory succeeded, without changing source DB.

API candidate `20be29303cc7...` built successfully, all four relevant source
hashes match the image and configured non-executing preflight passes. Existing
API `52e05efca40d...` is archived as `ftd-shun-api:lab-pre-prewrite-20261110`, not
a post-profile rollback. Compatible candidate tag:
`ftd-shun-api:lab-prewrite-recovery-20261110`. Full Python regression is running;
no live recovery/deployment or v7 activation yet. Actual apply/acceptance, if
performed, will be appended below with fresh key and process-stop evidence.

### Final validation, actual offline apply and bounded continuation

Clean complete Python regression **3537 passed in 614.88s**, no failures. Final
focused recovery/history **116 passed in 45.42s**; Ruff/compileall/diff pass. No
new Rust/browser run or live v7 acceptance is claimed. Four exact source hashes
and configured non-executing preflight match the candidate image.

Actual API `7d82c196f5cc` and Web `f42288374e68` exited 0, then agent
`ea9085b90bf5` exited 0 with actual drain; restart counts zero. Fresh stopped
review at 11:57:12.520Z covered all 33 claims of ATTENTION epoch 2921, owner
`41530116-d06b-45cc-aa72-39ac6db01851`; stopped baseline at 11:57:31Z had integrity
ok, original nine fingerprints/eleven unknowns unchanged, no RUNNING/QUEUED jobs.
New decision `5d4551f5-609e-45f8-9587-b06d352e9e66` applied at 11:58:02.571Z under
real `maintenance:lab-prewrite-recovery-20261110` identity. Exclusive checked
0600 backup in private 0700 directory:
`/var/lib/ftd-shun-manager/prewrite-recovery-20261110-epoch2921/before-prewrite-recovery.db`.
Receipt, distinct proof marker/audit and exact same-epoch IDLE release committed;
jobs retried zero. After apply, before restart, all eleven original data tables
and all three prior receipts matched the stopped baseline/backup. No original
job/request/attempt outcome, authority, protection or unknown history changed.
Private host review/receipt and original failure diagnostics remain under the
rehearsal directory above; its key was never used for the live apply.

Started the same agent first, then new API `20be29303cc7...` / `6e9af86250a3`,
then same Web. Agent image `e8cdc9925a8d...` and Web `b86fac92f284...` unchanged;
all three overlays/current managed-v2 DB/private v6 selection retained. No v7,
new import/consent, credentials/trust/network change or stale data restore.
Complete read at 11:59:13Z is strictly after the receipt. Actual epoch 2922,
owner `c56e5dbe-2e07-461a-b0ac-387fc43fb9e1`, claimed at 11:59:03.933Z and
released at 12:02:27.965Z. Its 24 ADDs are VERIFIED, with real final settlement
and agent pending count zero, not merely ACKs. API diagnostic elapsed 203.869s,
local work 107.729s; this small continuation sample is not speedup/capacity proof.
Original deferred job `d9203d0e-c518-53be-810b-bc8a69d07cc4` remains CANCELLED;
fresh job `6b2d2f43-ce5c-555e-b4d7-b3be5a741da0` became VERIFIED at 12:00:21.706Z.
Original request expiry/attempt/cancellation evidence is retained unchanged.

At 12:03:03Z DB integrity ok, eight original authority/protection/inventory hashes
and all eleven unknown rows unchanged. Recovery receipts four (expected new
decision), normal successor epoch 2923 LEASED, not global idleness. At 12:03:32Z
original task **25,116 VERIFIED/32,425**, ten reviewed/present unknowns, 7,299
outstanding, zero unresolved attention. Web health 200/anonymous 401 checked.
One coordinator-local numeric BUSY recovered; maintenance expiry also reported
contention and status retained database-lock last_error. Import continuation is
real, but SQLite contention is not fixed. Old image
`ftd-shun-api:lab-pre-prewrite-20261110` is now forensic/pre-apply only: it refuses
the new exact profile. Use compatible `lab-prewrite-recovery-20261110`, never
remove the marker or restore old authority to downgrade. This key cannot release
a successor epoch. Deferred-v7 ordered pending capture/recovery, claimed-child
replacement and deliberate fresh-store configuration/acceptance remain next.

## 2026-11-10 — Fresh replacement of proved pre-write cancelled retry children

### Implementation

The source-only fresh deferred-v7 retry path now accepts a cancelled child only
when never claimed under the old contract, or after one exact original tracked-v7
pre-write DEFER. The latter validates original system identity/target/group/owner/
epoch/visit, literal write_sent=false, all original requeue/cancellation/claim
evidence and unchanged job/attempt/request binding. ACKs, pending membership,
multiple/missing/foreign claims/DEFERs, legacy versions and unknown results refuse.
No old RPC is retried, outcome relabelled, execution request renewed or fence
released. New admission/claim require a causal full absence read after all replaced
children, still-current full original root/scope/protection/cancellation/device/
pause/lease/freshness, original exponential/hourly limits and new IDs. Existing
immutable retry provenance is reused; no new schema. Historical validation of
earlier admissions does not incorrectly consume later sibling outcomes. Advisory
selection now includes cancelled candidates; it never supplies authority.

Audit retention preserves actual original claim-visit openings even when the
claim occurred after a separate admission visit. Replacement proof is revalidated
before retention; corruption refuses both pruners without deletion. Source-only,
default disabled, no selector/configuration/deployment/live DDL, device test,
new authority/receipt/reset/reimport or change to the original v6 dataset.

### Validation and newly observed laboratory hold

Focused retry set **62 passed in 14.23s** (26 new), covering later claim visits,
expired/stale cancellation, original outcome/request preservation, fresh IDs/key
replay, negative literal/identity/version/claim/ACK/requeue/cancellation proof,
causal reads, retained proof and synthetic end-to-end worker discovery followed
by actual deferred observation. Initial new negative fixtures had the wrong
audit-column count; corrected those fixtures, not guards. Original ordinary/
non-v7 claim refusal test remains valid. Restricted async runner stalled; it was
interrupted and the same suite completed outside that restriction. Ruff/diff pass;
full Python regression running, final outcome will be appended. No new Rust/
browser run or live v7/throughput acceptance is claimed.

Read-only lab 13:07:59Z reports original import **25,162 VERIFIED/32,425**, ten
reviewed/present unknowns, one new unverified, 7,252 outstanding/one attention.
At 13:08:18Z integrity ok and all nine post-recovery fingerprints unchanged,
but device 1 is **ATTENTION epoch 2925**, owner
`7756ce5a-1816-4af2-9447-a42cc81eb7e2`, held since 12:09:58.763Z. New job
`68dbe319-361b-509c-b557-6698ff9961c6` / 151.230.131.112 started 12:08:32.479Z,
UNVERIFIED at 12:08:33.677Z; total unknowns twelve. Agent diagnostics show the
preceding 16 ADDs/group read, then fixed-command shell-send failure during target
read, sequence 18, 17 attempted mutations/35 CLI commands, zero pending additions.
Logs are diagnostic, not proof of nonexecution or permission to reinterpret the
unknown. API reports one unresolved item; last successful read 12:08:27Z. Existing
epoch-2921 decision does not cover the successor. No restart/recovery/relabel/replay
was performed; retain original task/unknown/evidence for compatible separate review.

Shared final-source retry/ledger/queue/worker/scheduler/lifecycle/dispatch/recovery
set **343 passed in 104.69s**. Ruff/compileall/diff pass. Two preliminary focused
commands named nonexistent retention test files and collected nothing; the
corrected existing-file selection above completed successfully. Private original
epoch-2925 timestamped diagnostics and exact read-only integrity/hash/unknown
inspection were retained mode 0600 under
`/tmp/ftd-deferred-child-20261110.7ZBcXO` (directory 0700). No live state changed.

### Clean full regression and separate epoch-2925 reconciliation

Clean complete Python regression **3563 passed in 631.10s**, no failures;
focused 62/shared 343 pass, Ruff/compileall/diff pass. No new Rust/browser run.
The source-only deferred replacement code was not deployed or activated.

The original FPR was reachable in a bounded direct read-only `list_shuns` probe
(25,173 entries); that read was not published or used to resolve uncertainty.
The first probe named a nonexistent client keyword and issued no RPC; corrected
to existing `large_snapshots=True`. Existing read-only extended reconciliation
inspection accepts the exact current 17-claim scope, not all-verified recovery.

Announced a separate controlled offline reconciliation using existing matched
runtime code. Actual same API/Web exited 0, then same agent exited 0; restart
counts zero. Private-copy rehearsal under
`reconciliation-20261110-epoch2925/rehearsal.db` passed all 17 claims, eleven
original tables/four old receipts unchanged, integrity/FKs/profile valid, zero
jobs retried. Rehearsal key `9dcce1a5-97db-4f95-9926-456bf9bd9c91` is consumed
on that copy only; separate checked backup `before-rehearsal.db` retained.
Stopped baseline at 13:19:24Z had integrity ok, ATTENTION 2925, no QUEUED/RUNNING
jobs, all twelve original unknowns retained. Fresh whole-DB review at
13:19:38.914Z used digest
`a8fb3c943de9a1c19c6cd84ef9df761a2d025c876eb5a84b4bf04a34a2ff9f18`.

New live decision `921ebe04-5283-42be-9d1a-9eab92915739`, real
`maintenance:lab-epoch2925-20261110`, applied at **13:20:14.995Z**. Exclusive
checked 0600 backup in private 0700 directory:
`/var/lib/ftd-shun-manager/reconciliation-20261110-epoch2925/before-live-reconciliation.db`.
It retains 16 VERIFIED/one UNVERIFIED original outcomes and records exactly that
reviewed unknown; original policy is unchanged and old jobs retried zero. Before
restart, comparison to backup proves schema and eleven original tables unchanged,
all four prior receipts unchanged, integrity/FKs/profile valid and exact IDLE
epoch 2925. All twelve unknown jobs remain unknown. Same exact original API
`20be29303cc7...` / `6e9af86250a3`, agent `e8cdc9925a8d...` / `ea9085b90bf5`
and Web `b86fac92f284...` / `f42288374e68` restarted, agent first; no rebuild,
new schema/profile, v7, new import/consent, secret/trust/network change or reset.
Post-receipt fresh read and actual productive settlement will be recorded below.
Neither this nor the epoch-2921 key may release a later epoch. Keep all three
overlays and original dataset; a future failure requires its own evidence/review.

## 2026-11-10 — Shared SSH transport idle budget and repeated hold

### Reproduction and bounded fix

Post-epoch-2925 recovery did obtain fresh read 13:21:25Z and new verified work,
but **did not achieve productive terminal settlement**. Old agent failed again
at the next target read after one 16-member verified group, sequence 18. New job
`e644f850-d2df-5ed7-bbda-a14c8a20ff0a` / 151.231.148.59 became UNVERIFIED at
13:23:27.638Z; epoch 2926/owner `b7fbd060-ba96-4510-9a9c-3baff39fac6e` entered
ATTENTION at 13:24:47.421Z. It is not excused by either prior receipt. Timestamped
diagnostics are retained as `epoch2926.log` in the private host directory above.

Inspection found fixed 15-second `russh` client inactivity, independent of API
local result persistence/root validation. The locked russh source explicitly
returns InactivityTimeout on that timer. Actual in-memory pinned SSH test proves
old 15s client closes during 16s with no traffic, while new cycle configuration
remains usable and echoes subsequent data. No real SSH credentials, listener,
keepalive or FTD command in this test. Initial fixture public-key comment did
not match wire encoding; removed that fixture comment, not host-key validation.
This reproduces a real local premature-disconnect defect consistent with the
lab failure pattern, not proof of every prior outage's sole cause.

Private cycle opening now selects transport inactivity from the existing hard
visit budget: v1–v5 120s, v6/v7 240s. Standalone operations retain 15s. Shared
duration arithmetic is unchanged. Opening/CLI/IPC/step/overall deadlines,
mutation/command/sequence limits, pinning/credentials/gates unchanged. No wire,
network settings, keepalive/reconnect/resend, old-result interpretation or v7
activation. New manual documents the independent timer layers and deployment.

Validation: actual SSH test plus all Rust **97 unit/7 configuration/4 shutdown**
pass, locked release/all-target Clippy/fmt pass. Final-source Python wire/session
**96 passed in 15.77s**; prior complete Python **3563 passed in 631.10s**, shared
343/retry 62 pass. No Python functional change after that full run; later source
change is Rust-only. No new browser run. Agent candidate built as
`8d9f196ceea14937d17b049e9010530ce3e1ad12306a484e13d8c37c0e1df5c7`; configured
`--check-config` exits 0 with existing v6/one-device settings, no SSH/socket.
Old compatible agent retained as `ftd-shun-agent:lab-pre-ssh-idle-20261110`.

### Quiescence, ordinary obsolete-work cleanup and distinct decision

Actual API/Web then old agent exited 0 (restart counts zero). Stopped 13:31:24Z
baseline: integrity ok, ATTENTION 2926, 15 QUEUED/zero RUNNING/13 UNVERIFIED.
Preliminary consistent copy at `reconciliation-20261110-epoch2926/rehearsal.db`
correctly refused recovery because of those QUEUED jobs; no key/receipt was
applied on that copy. Preserve it as pre-maintenance archive, never overwrite.
Confirmed its integrity and exact original twelve-table equality with the live
stopped DB. All 15 jobs are device-1 ADDs with no original claim/start/dispatch.
Existing product `OperationQueue.cancel_obsolete_policy()` then cancelled exactly
these stale, now-ineligible execution jobs, retaining all nine standing/protection/
inventory/recovery tables, thirteen unknowns and exact ATTENTION fence. No force
expiry, direct SQL outcome edits, policy retirement or old command replay. The
private `obsolete-cleanup.json` lists exact IDs. Their original rows/audits remain.

Fresh post-cleanup copy `reconciliation-20261110-epoch2926-ready/rehearsal.db`
passed 17 claims, 16 VERIFIED/one UNVERIFIED, zero jobs retried, eleven original
post-maintenance tables and five prior receipts unchanged. Its consumed rehearsal
key is `eefda9d8-08a1-4b03-9444-78fa53ca4536`, never live authority; checked
`before-rehearsal.db` retained. Fresh stopped review at 13:34:31.728Z, digest
`aa626cad7d285b2fe4865940dfda149999b27cd09a06fa5655123b23319f1283`.
New live key `b106cc46-8d9f-4704-8644-3bdf671e2262`, real maintenance actor
`maintenance:lab-ssh-idle-2926-20261110`, applied at **13:35:16.073Z**. Checked
exclusive backup:
`/var/lib/ftd-shun-manager/reconciliation-20261110-epoch2926-ready/before-live-reconciliation.db`.
Comparison before restart proves unchanged schema/eleven post-maintenance tables/
five prior receipts, integrity/FKs/profile valid, exact IDLE epoch 2926. All
thirteen old unknown outcomes remain unknown. This records desired-state review,
never proof the old command did/did not execute; no old key releases later epochs.

### Agent-only rollout; acceptance pending

Replaced only cleanly stopped old agent with `8d9f196ceea1...`, container
`4b2aa4744e96`, then restarted same API `20be29303cc7...` / `6e9af86250a3` and
Web `b86fac92f284...` / `f42288374e68`. All three overlays, original managed-v2
DB/import/standing authority/protection/private v6 settings retained. No API/Web
rebuild, source-only retry deployment, new import/consent, reset/reimport, trust/
credential/network change or v7 activation. Actual post-fix read, multi-group
write results and terminal settlement are being observed and will be appended.
Do not claim success from mere startup/ACK, or that SQLite contention/all outages
and large-list throughput are fixed.

### Actual post-fix continuation and final integrity

New complete read **13:36:26Z** is strictly after the 13:35:16.073Z receipt.
Epoch **2927**, owner `fa37922c-5776-4998-bad4-95ccfe17fbfe`, claimed at
13:36:16.374Z and actually released at **13:39:53.445Z**. Original audit has
29 claims: **28 VERIFIED ADDs**, groups 16/12, and one exact pre-write DEFER.
Same SSH session resumed after the first group/local persistence interval and
crossed the formerly failing sequence-18 boundary. Agent actually completed with
zero pending, 59 CLI commands, no CLI error and 201.594s including opening. API
reported actual settlement and 216.921s total, local 115.915s (claims 58.947s,
group persistence 21.174s). Read-only epoch 2928 subsequently settled at
13:40:11.114Z. This is bounded idle-fix continuation, not large-import speedup.

Fresh job `c5b49bb2-f331-5609-9752-1301852a5911` / attempt
`0ca9137b-790b-558d-8ede-90343d2b1030` became VERIFIED at 13:38:09.813Z for
151.231.148.59. Original `e644f850-d2df-5ed7-bbda-a14c8a20ff0a` remains
UNVERIFIED; no retrospective creation proof or original command replay.
At **13:40:46Z**, integrity ok, eight original authority/protection/inventory
fingerprints and every original thirteen unknown row unchanged. Six recovery
receipts are expected; all earlier receipts were checked unchanged before restart.
Normal successor epoch 2929 LEASED, not global idleness; zero pending-schema
objects. At **13:40:53Z**, original task **25,206 VERIFIED/32,425**, ten reviewed/
present, **7,209 outstanding**, ready/last_error null/zero unresolved attention.
Web health 200/anonymous 401 checked; exact new agent/unchanged API/Web images
and no process restart verified. One local scheduling BUSY recovered in this
sample; SQLite contention is still real, not eliminated by the transport fix.

Final source checks Ruff/compileall/diff/fmt pass. Complete Python 3563/shared
343/final wire-session 96, Rust 97+7+4, locked release/all-target Clippy and
configured built-image non-executing preflight pass. No new browser run, full-list/
production/v7 acceptance, release/tag or claimed stable throughput. Next finish
ordered pending/deferred recovery and explicit fresh-store activation for the
source-only cross-session confirmation mode. Preserve original import and all
authority/protection/unknown/recovery evidence; never reuse consumed keys.

## 2026-11-10 — Bounded Shuns pages instead of whole-list browser rendering

The operator reported browser lockup with the long observed-Shuns list. Added
read-only `/api/v1/shuns-page?page=N` and BFF server-side pagination of 100 device/
IP/interface observations. SQL limits before hydration; provenance loads only
selected occurrences, retaining one representative and exact coalesced count.
Count, selection and provenance share one read transaction. Protected/newest
ordering gains a deterministic final device-ID tie; positive out-of-range pages
clamp to the current last page. The old full-list API remains internal-compatible,
never a browser fallback. Navigation retains the query; global IP search remains
independent of the page. Existing live replacement retains the current page and
does not append old rows. No schema, policy, agent, execution, secret/trust or
network change; no fixture/authority/reimport/reset or device command submitted.

Focused Python **38 passed**, including 100,000 synthetic observations, selected
provenance with coalesced origins, concurrent removal and authenticated BFF/no
admission checks. Browser/Node **89 passed**, including 100-row initial rendering,
live replacement and page navigation. An initial candidate's real-profile local
check returned 503 because the continuous API allowlist lacked the new GET route;
fixed the exact read-only route and added explicit no-state-change coverage.
Final continuous/policy/page set **80 passed**. Ruff/compileall/diff pass.
The full run recorded **3566 passed / one failure in 681.76s**: the initial
continuous allowlist omission caused a BFF workspace-navigation 503. It ran with
the pre-fix module already imported. The exact failing suite and all affected
tests are being rerun on corrected source; no second clean full run is claimed.
Corrected built-image non-executing configured preflight passed. Actual local
read-only composition against **25,466** observations returned 100/100/66 rows
for first/second/clamped-last pages, **28,247/28,238/18,603 bytes** in
**0.076/0.052/0.063s**. No lifespan/worker/SSH/admission was started by this check.
Final affected suites, including the exact full-run failure, now have **153
passed in 35.69s**. Final Ruff/compileall/diff pass. No second full run is claimed.

### API/Web lab deployment and retained evidence

Archived compatible old images as `ftd-shun-{api,web}:lab-pre-shun-pages-20261110`.
Actual old API/Web exit 0, stopped epoch **2947 IDLE** at **14:17:12.089Z**,
zero RUNNING; integrity ok, all nine original authority/protection/inventory/
recovery fingerprints and thirteen original unknown rows unchanged. Deployed
API **968a8fa02ff2... / 7ba324a61af1**, Web **b21d4d1d6e79... / 4246878c51cd**.
Agent **8d9f196ceea1... / 4b2aa4744e96** stayed running and unchanged; original
DB/import/all three overlays/v6 selection retained, v7 still source-only.

Real UDS page checks against **25,484** active observations returned **100/100/84**
rows, **28,255/28,235/23,660 bytes**; initial request **1.206s**, subsequent
**0.054/0.060s**. Invalid page 0 returns 422; responses remain no-store. Web
health 200 and anonymous root 401; template/JS hashes match source. No trusted
Web identity was invented. Existing browser tabs need one reload. These are
bounded local checks, not an end-to-end production/load guarantee.

Post-deployment integrity, all nine fingerprints and original thirteen unknowns
remain unchanged. Normal epoch **2948 LEASED** with current work, not global
idleness. One startup scheduling SQLITE_BUSY retried and actually recovered;
retained audit/logs show new original-task VERIFIED ADDs. No failure clearing,
receipt reuse, task reset/reimport or new fixture/consent was performed. Private
before/drained/after checks: `/tmp/ftd-shun-pages-20261110.Tye2fY` (not committed).
Do not restore stale DB state for rollback; drain the compatible API/Web pair.

Synthetic capacity tests do not prove live 100,000-IP FTD throughput. Pagination
is a moving list, not a frozen export; rows may move after new detections/removals.
Original lab import and all uncertainty/recovery evidence remain in scope for
preservation. See [Operations](manual/operations.md#browsing-long-shuns-lists).

## 2026-11-10 — Keep IP action panels usable during live refresh

The operator could not use the bottom-of-page IP actions before refresh closed
them. Managed retirement/ready-removal/ordered-removal disclosures lacked IDs,
so generic expansion restoration skipped them. Equivalent form replacement
also destroys native select popups and summary/button focus. Added stable IDs
and an explicit `data-live-editor` marker for non-authoritative review preparation.
If old/new server markup matches after stripping only local details open state,
leave the actual region DOM intact. Target choices, hidden values, disabled
controls, form actions and capability removal remain meaningful differences:
refresh them normally, restore matching drafts/open state, never retain an action
the server removed. Legacy review preparation gets the same treatment. No global
refresh pause, frozen-confirmation mutation, Python/backend, authority, CSRF/CAS,
schema, policy, agent, credential/trust/network or device-work change.

**Validation:** affected Python UI suites **119 passed in 31.52s**; browser/Node
**90 passed**, full Chromium parent 134.36s. New browser regression opens all
three panels, verifies same connected controls/draft/summary-select-button focus
across three real result updates, then verifies changed target options replace
controls without closing disclosures, and revoked capabilities remove actions.
No demand/admission counter increases. Ruff/compileall/diff pass. A broader
Python run was interrupted after **302 passed in 86.79s** to scope this JS/template-
only validation appropriately; no complete full regression is claimed.

**Deployment:** archived prior Web as
`ftd-shun-web:lab-pre-stable-ip-editors-20261110`, rebuilt/deployed only Web
**f8c36b7aeaeb... / 3457285a8c0d** with all three existing overlays. API
**968a8fa02ff2... / 7ba324a61af1** and agent
**8d9f196ceea1... / 4b2aa4744e96** remained running unchanged; no worker restart,
new fixture/task/consent, DB operation, reset/reimport or recovery invocation.
Web health 200, anonymous `/managed-shuns` 401. Served JS hash and both managed
templates match source. No Web identity spoofing or device mutation for checks.
Existing tabs need one reload. True server-side scope/capability changes still
update controls; this is interaction preservation, not a permission reservation.

## 2026-11-10 — Recover held import and provide explicit recovery assistance

The operator reported thirteen unverified rows and no way forward from Queue.
Read-only inspection found a new **ATTENTION epoch 3044**, not merely old warnings.
Agent timed out waiting for the FTD prompt during target read 13, with twelve
staged ADDs lacking final observation. All thirteen new outcomes remained unknown
(26 raw total); diagnostics are not retrospective proof of sent/not-sent writes.
Failure evidence and authority snapshots were retained privately under
`/tmp/ftd-queue-attention-3044-20261110.0mIV7h`.

### Explicit existing-tool recovery

Operator explicitly approved lab recovery and a product recovery workflow. Actual
API/Web/agent exited 0. Existing 1–16-claim reconciliation was rehearsed on a copy
of the real data: 13 UNVERIFIED, all eleven original data/outcome/authority tables,
original schema and six old receipts unchanged, integrity/FKs/profile valid.
Fresh live review and checked exclusive backup preceded new exact decision
**8dcf8343-c491-43d1-b5a1-01d7ceb493af** at **18:04:24.967Z**. Backup:
`reconciliation-20261110-epoch3044/before-live-reconciliation.db`.
All 26 unknowns remain unchanged; no old job replay, authority renewal, reset or
reimport. Same agent/API/Web images restarted. New complete reads preceded current
standing work; actual epoch **3045** settled **28 VERIFIED ADDs**, followed by
settled read-only **3046**. At **18:08:59Z**, fresh read/no error/zero unresolved
attention. This decision covers only epoch 3044 and does not fix the FTD timeout
or intermittent local SQLite contention.

### Product workflow and security boundary

Added read-only `GET /api/v1/queue-recovery`, authenticated `/queue-recovery`
guidance/report download, and Queue attention's **Check and resume import** link.
Inspection reuses exact existing default/extended review contracts but never
initializes a ledger, releases a hold or sends a device command. Unsupported
state explains refusal; eligible scope is not permission to replay unknowns.

Current workflow is explicitly **host-assisted**, not one-click online recovery.
Web/API receive no Docker socket, host-control access or new privilege. A separately
invoked `python -m ftd_shun_manager.lab_recovery` requires the known single-device
lab, exact epoch, explicit lab confirmation, real maintenance label, all three
overlays and matching API images. It retains private logs/review/container IDs,
verifies actual clean API/Web then agent exits, rehearses a copy, obtains fresh
review/backup and applies the existing offline tool with a fresh decision, retaining
all original outcomes/authority/receipts. Changed inventory/epoch/image, stop
failure/timeout, missing proof and recovery failures refuse; after-stop failures
stay stopped. Restart means pending a fresh complete read, never verified import
completion. True online recovery remains separate coordinator work.

### Validation and actual API/Web rollout

Full regression **3578 passed in 659.43s**; final focused **114 passed in 26.50s**,
new helper **12 passed**, browser/Node **91 passed**. Final focused tests include
image pinning and stop-failure/timeout checks added after the broad run collected;
no second full-source run is claimed. Tests cover actual disposable-copy control,
old unknown preservation, read-only report/no initialization, authenticated BFF/
download, exact route allowlisting, host refusal/order and no automatic restart.
Ruff/compileall/diff and final configured non-executing image preflight pass.
New bundled control/report also rehearsed on a separate copy of the real archived
13-unknown data; live DB/archive untouched. A stale real epoch-3044 invocation
refused before stop, and original container start times were unchanged. No new
live failure was induced; the new whole host helper has not run on a live hold.

Rollback tags: `ftd-shun-{api,web}:lab-pre-recovery-assistance-20261110`.
Old API/Web actually exited 0, stopped **3053 IDLE/no RUNNING** at
**18:22:13.386Z**; unchanged agent stayed running. API
**3713153a0892... / 56b8447c125b** and Web
**b65f21e7776d... / e94577e7a389** deployed with all three overlays/same original
managed DB/import/v6 selection. No agent/protocol/gate/trust/credential/network
change or new device fixture. At **18:23:41Z**, integrity ok, all nine post-recovery
fingerprints and all 26 unknown rows unchanged, normal **3054 LEASED**. Fresh read
**18:23:11Z**, no error/zero unresolved attention, reviewed history 26. New private
report returns 200/read-only; Web health 200, anonymous recovery/download 401 and
new template/CSS hashes match source. No spoofed Web identity was used. Existing
tabs need one reload. Preserve seven receipts and original unknowns; never restore
stale data or reuse the consumed decision for later uncertainty.

## 2026-11-11 — Quiet navigation/loading and empty-promotion writer avoidance

Operator reported red service-busy notifications on tab changes and repeated
SQLite-lock notifications. Inspection found synchronous scheduling reserved
SQLite's writer for an ordered-removal promotion sweep even with no candidates;
six-hour old API diagnostics contained 347 matching expiry failure/scheduling
retry/recovery lines. Retained those bounded logs and read-only pre-rollout
fingerprints/unknown rows privately in `/tmp/ftd-quiet-loading-20261111.bC8ugi`.

Added an accessible fixed loading strip for native primary-tab GET navigation,
including reduced-motion behavior and back/forward reset. No SPA/page cache,
form replay or changed frozen-review/CSRF behavior. Brief GET network/timeout or
502/503/504 failures retain data and show neutral loading/retry details; failures
three onward or the next failure after 30 seconds warn. Authentication and
action-submission errors stay immediate, and an earlier actionable local failure
cannot be quieted by a subsequent transient failure before a successful read.
Typed scheduling retries one/two are neutral, later attempts warn; only their
exact coordinator reason is suppressed. Independent stale/device/unknown evidence
remains visible and real confirmation timestamps stay unchanged.

Empty promotion sweeps now validate the complete existing profile and incomplete
tickets in one read transaction. No candidate means no writer reservation; a
candidate repeats all original fresh checks in the existing writer transaction.
Concurrent newly arriving work waits until the next pass, without cached authority.
No DDL/protocol/gate/deadline/budget/timeout/credential/trust/network change, no
generic SQLite/device-command retry or unknown-outcome reinterpretation.

### Validation and lab rollout

Full Python **3582 passed in 649.57s**, final focused **117 passed in 28.71s**,
final browser/Node **93 passed in 151.75s**. New WAL regression completes an empty
sweep while another connection holds `BEGIN IMMEDIATE`, with unchanged data.
Browser checks cover native navigation, reduced motion, brief/persistent failure
presentation, authentication failure persistence, stable layout and unchanged
explicit action retry. An initial native-navigation test tried inspecting the
old page through CDP while Chromium suspended evaluation for navigation; changed
the test to retain a pre-navigation observation and inspect it after actual
arrival. Final run is clean. Ruff/compileall/diff and final configured non-
executing image preflight pass; API check started no execution or migration.

Saved compatible rollback images `ftd-shun-{api,web}:lab-pre-quiet-loading-20261111`.
Old API/Web actually exited 0 at **09:00:10Z**, stopped **3455 IDLE/no RUNNING**,
integrity ok and all nine authority/protection/inventory/recovery fingerprints
plus 26 original unknown rows unchanged. API **4ca90a19296d... / 395b756709a7**
and Web **b62bee8874f1... / e29afa27d782** started **09:00:57Z** using all three
overlays/original managed DB and v6. Agent **8d9f196ceea1... / 4b2aa4744e96**
was not restarted. No new device fixture/import/consent/recovery or evidence reset.

At **09:01:21Z**, coordinator running, fresh read **09:01:19Z**, no last error,
zero unresolved attention and 26 reviewed history; startup session still active.
Original import **32,425/32,425 processed** (32,403 verified/22 already present),
zero outstanding, completed before this deployment. Read-only status requests
took **1.868/1.732/1.906s** during startup. Web health200/anonymous pages401 and
actual served navigation/refresh/CSS hashes match local source. Reload old tabs.
Preserve all seven receipts/26 unknowns. This is not all-contention recovery or
active-large-list throughput acceptance: original import was already finished,
and no new live storage lock or mutation failure was deliberately induced.

Final **09:02:56Z** post-rollout read-only check confirms settled **3456 IDLE**,
no RUNNING jobs, integrity ok, all nine fingerprints and all 26 unknown rows
unchanged. Candidate templates match local hashes too. No matching storage/
maintenance/stopped errors in the short startup log sample; this is bounded idle-
work observation, not evidence that all live contention has been eliminated.

## 2026-11-11 — Separate unmanaged observations and correct observed removal reviews

Continued the agreed working-version usability slice after completing the large
original import. Added a separate authenticated Unmanaged tab, current exact-
device/IP maintenance badges in observed rows/details, and bounded filtered reads.
Enabled standing maintenance defines Managed even while execution is paused;
off/retired policy can leave an observed unmanaged block. Historical import origin
and observed presence never infer current maintenance or original creator.

New read-only classifier validates the existing bulk or legacy managed profile;
genuinely absent policy differs from malformed/partial storage. Count, selected
observations/provenance and flags share one SQLite read transaction. The fixed
unmanaged anti-join precedes LIMIT; only displayed pairs are annotated, never the
entire policy in Python. Added `ownership=all|unmanaged` on the existing paged API;
Unmanaged BFF rejects old/unfiltered metadata. Per-IP detail gains classification;
legacy full-list reads may remain explicitly unclassified. Universal IP search
still includes managed/history matches, clearly distinguished from the table.

Fixed observed-row actions in the actual v2 runtime: the previous index offered
legacy queue submission even though continuous v2 refuses that endpoint. New
rows/details prepare the existing CSRF/identity-bound exact frozen device-removal
review, labelled stop-restoring-and-remove when maintained. Final explicit consent
and all original admission/role/policy/protection/uncertainty guards remain. Legacy
maintained rows likewise use their existing combined review; unknown ownership
does not choose ordinary unmanaged removal. No new mutation or adoption endpoint,
DDL, protocol, bounds, timeout, gates, authority, credential/trust/network changes.

Added structured Shuns/maintenance manual and updated README/manual index/plan/
architecture. This is the separate view and review UX, not rolling 24-hour multi-
device correlation, direct adoption, Emergency Purge or deferred-v7 activation.

### Validation

Full Python **3597 passed in 621.08s**; final focused **119 passed in 14.97s**,
including two tests added after full collection (malformed-policy API refusal and
100,000-observation filtered paging under another WAL writer). No second full run
is claimed. Final browser/Node **95 passed in 138.26s**. Tests cover exact device/
interface scope, adoption vs creation, retired origins, absence vs damaged schema,
snapshot consistency during concurrent retirement, SQL LIMIT before hydration,
authentication/read-only roles, route/query/live page retention and frozen review
actions without queue admission. Early browser fixtures leaked v2 status/generation
into an older shared refresh scenario; isolated its initial state and reran cleanly.
Ruff/compileall/diff and configured non-executing image preflight pass.

Candidate rehearsal opened the actual lab DB with `mode=ro`/`query_only=ON`:
32,426 observations/325 pages, first/last 100/26 rows, all maintained; Unmanaged
zero. Query times 0.322/0.228/0.225/0.228s are bounded samples, not load claims.
Current capability metadata confirms exact v2 ready review is available/admitted,
legacy manual mutations unavailable. No test ADD/REMOVE was needed or submitted.

### Actual lab rollout

Retained preceding compatible pair as
`ftd-shun-{api,web}:lab-pre-unmanaged-20261111`. Private recent logs/authority/
unknown baseline: `/tmp/ftd-unmanaged-20261111.YSyhXE`. Old API/Web actually
exited 0 at **09:29:38Z/09:29:37Z**, stopped **3463 IDLE/no RUNNING**, integrity
ok and all nine fingerprints/26 original unknown rows unchanged. API
**3974a9f36ad7... / 8c1a1e8d943d**, Web **6e39cda4cef2... / 01a79bad4f26**
started **09:30:10Z**, using all three overlays/original managed DB/import/v6.
Agent **8d9f196ceea1... / 4b2aa4744e96** did not restart. No new consent, receipt,
test fixture, dataset reset, reimport or live authority/profile initialization.

Live API first/last pages return 100/26 in **0.558/0.235s**, Unmanaged zero in
**0.236s**; per-IP flags and invalid-filter422 checked. Web health200/anonymous
Unmanaged401, exact served CSS/JS and all changed template hashes match source.
At **09:31:21Z** fresh read **09:30:29Z**, coordinator running/no error/zero
unresolved attention, 26 reviewed historical unknowns. Original task remains
32,425/32,425 complete. At **09:31:40Z**, successor **3464 IDLE/no RUNNING**,
integrity ok, all nine fingerprints and all unknown rows still unchanged. All
seven recovery receipts remain; no old outcome was replayed or relabelled.
Existing tabs need one reload. Bounded single-device read acceptance does not
prove active-load performance, FTD capacity, live authenticated-browser behavior
or multi-device correlation. No spoofed Web identity was used during rollout.

## 2026-11-11 — Version 0.2.0, uniform paging and independent operator pauses

Operator clarified two independent controls: pause initial imports and pause
automatic restoration. Existing blocks stay; monitoring, removals and Protected-IP
automatic unblocking continue. Added separate exact optional control rows, immutable
real-actor/idempotency history and per-category monotonic revisions/resume barriers.
No rule retirement, unknown replay/relabel, recovery release or gate changes.
Existing databases require explicit quiescent initialization; new dev profiles
include it. Old writers refuse the new schema. Category uses exact current scope's
adoption/known presence evidence, not inferred original device-command creation.
Discovery filters paused categories before LIMIT, preserves the other category's
window, and claims recheck the current pause while allowing in-flight settlement.

Added CSRF-protected API/BFF controls in Managed shuns and neutral Queue/Status
indicators. Operator Resume requires a new causal read and never clears safety
holds. Common top/bottom pagers retain existing GET anchors/revisions/searches
and frozen POST tokens/consent. Active Queue shows RUNNING then newest queued
items; FIFO/priority dispatch remains unchanged. IP badges have their own layout;
interface names no longer split mid-word. Product version advances to 0.2.0,
with a mandatory contributor/agent bump rule for subsequent material deliveries.
Docker builds generate an explicit public source digest, never Git/private/host
inputs or per-request source inspection. Exact image IDs remain necessary.

Focused final-source Python 217 passed; Chromium/Node 97 passed in 156.33s.
These include independent button updates, neutral pause indicators, retained
unknown warnings, concurrency/replay/CSRF/roles, fresh-read resume, protected
removal, current-operation settlement and paused-prefix starvation checks.
Full regression and lab rollout are still in progress at this source checkpoint;
do not infer deployment or active-import/live-paused-write acceptance from it.
Later validation/deployment results are appended below. No tag/release publication.

### Final validation and actual lab rollout

Full Python run: **3618 passed, two failed stale assertions,672.92s**. One expected
FIFO presentation order, not execution order; corrected it to check capability
by device. The other enumerated the old route set; added the new semantic control
route while retaining the no-initialization assertion. Final broad boundary set
**256 passed/22.59s**; all managed-registry/import-execution/control cases and
source checks **66 passed/3.35s**. These also cover the extra NULL-row profile
test added after full collection. No second clean full-source run is claimed.
Final Chromium/Node **97 passed/156.33s**. Compileall/Ruff/diff pass. Candidate
and running package0.2.0/public digest/footer agree on **6638b65ca610**; no Git
inspection, environment override or tag publication.

Rehearsal on a private consistent actual-dataset copy passed with all **31 original
tables unchanged**. The actual old API image refused the new control schema.
Old API/Web then exited0; stopped **3512 IDLE**, no RUNNING, integrity ok, all nine
authority/protection/inventory/recovery hashes and all26 unknown rows unchanged.
Explicit `checked_offline` extension created the exclusive checked backup
`private-backups/ux-pauses-20261111/before-controls.db`, revalidated quiescence and
preserved every original table. No job/outcome/authority conversion or recovery.
Configured non-executing checks passed before and after extension.

API **454e6336b0b2... /6b548900c147** and Web **79a0dcfb1c10... /714f72fa976a**
started **11:36:47Z** with all three overlays/original managed DB/completed import/
v6 selection. Agent **8d9f196ceea1... /4b2aa4744e96** stayed running. No agent,
protocol, timeout, gate, credentials/trust/network or authentication change.
Retained old `lab-pre-operator-controls-20261111` images are forensic, not a
compatible rollback against the new schema. Current compatible pair retained as
`ftd-shun-{api,web}:lab-operator-controls-0.2.0-20261111` for future use; never
remove pause guards or restore stale authority to undo the feature.

Four fresh keys under real trusted-host label
`maintenance:operator-controls-lab-20261111` independently paused imports,
paused restoration, resumed imports and resumed restoration. Each original-key
repeat returned current state without another toggle. Both controls finish
**Active/revision2**; barriers **11:37:40.485Z/11:37:40.982Z**. Original queue counts
unchanged, no new shun fixture/admission/recovery. At **11:37:56Z**, normal3514
LEASED, integrity ok/nine hashes and26 unknown rows unchanged; not global idle.
Actual complete read **11:37:57Z** is after both resume barriers.

At **11:38:50Z** running/no error/zero unresolved attention,26 reviewed history;
original task32,425/32,425 complete (32,403 verified/22 present), observations32,426
in325 bounded pages, Unmanaged0. Webhealth200/anonymous protected pages401 and
served source-matching assets pass. These are bounded control/read acceptance,
not live active-import pause/write-race, multi-device or production acceptance.
Private host evidence `/tmp/ftd-ux-pauses-20261111.hFwoIA`, private rehearsal/results/
backup retained in the state volume. Existing tabs need one reload.

## 2026-11-11 — Compact operator workspace, Web v0.2.1

Operator requested less linear, description-heavy pages and intact IP/tag labels.
Widened/densified the workspace, aligned Status/Queue with headings, and put
reference-only descriptions behind stable native disclosures. Real errors,
unknown/current-block/protection warnings and frozen review consequences remain
visible. IP/badges stay on one line; wide tables scroll within their frame,
without hiding identifiers/actions or increasing bounded pages. Table buttons
are smaller; timestamp columns avoid excessive row height. Light/dark and narrow
layouts retain readable action targets.

Managed Actions above the table opens/focuses existing capability-filtered
editors, with outside-click/Escape dismissal and no request submission. Existing
CSRF/identity/frozen scope/revision/consent forms and live editor preservation
remain. Per-row Note/Activity reveal saved context on demand. Protected-IP cards
form a responsive grid, with disabled/currently-shunned warning still visible.
Import source sits beside device/label/reason fields; mobile stacks them.
No backend scheduling, refresh, paging, policy, schema, protocol or gates changed.

Full Python **3621/661.72s**, final focused **123/28.91s**, final browser/Node
**100/149.23s** passed. An intermediate browser rerun caught a harness race:
98 of100 table rows had parsed when it asserted. The helper now waits for complete
HTML and deferred controllers; final suite is clean. New synthetic layout tests
cover1440/960/375px light/dark intact labels/row heights/local scroll, protected
cards/typed deletion, action focus/no submission and responsive import panes.
Reviewed screenshots retained privately. Compileall/Ruff/diff, all38 compiled
templates, configured non-executing Web composition and installed package/build/
rendered footer consistency pass. Product advances0.2.0→0.2.1; no release/tag.

Built/deployed **only Web** `2d364ae45a57... /a7fff523b558`, started
**13:09:55Z**, public source ID **b4f8eccc19e8**. API `454e6336b0b2... /
6b548900c147` remains0.2.0; agent `8d9f196ceea1... /4b2aa4744e96` unchanged;
neither restarted. All three overlays/original managed DB/import/v6 remain.
Rollback Web `ftd-shun-web:lab-pre-compact-ui-20261111` retains compatible0.2.0.
No new ADD/REMOVE/control/consent/recovery request, data reset, gate, secret,
trust, network or authentication change.

Live health200/anonymous seven protected routes401, shipped asset hashes and
version/source/footer pass. At **13:10:22Z**, integrity ok/all nine original
fingerprints/all26 unknown rows unchanged, **3535 IDLE/no RUNNING**. At
**13:10:30Z**, coordinator running/no error/zero unresolved attention,26 reviewed
retained, original task32,425/32,425 complete, observations32,426/325 pages and
Unmanaged0. Both controls unchanged before/after: Active, imports revision2 and
restoration revision4, six existing requests. Seven recovery receipts retained.
Evidence `/tmp/ftd-compact-ui-20261111.fcKSDV`. Existing tabs need one reload.
Browser validation is synthetic, not live authenticated-browser/load/production
acceptance. Follow [Operator Workspace](manual/operator-workspace.md).

## 2026-11-11 — Grouped pause controls and current-only Queue, Web v0.2.2

Operator reported pause buttons visually drifting toward another control and
asked to keep history out of Queue. Removed space-between stretching; each
name/state/button now shares a compact outlined flex group. Groups wrap on narrow
screens without losing the button's association. No pause semantics changed.

Removed completed/reviewed-history tables and finished-import disclosures from
Queue. Active work/progress, unresolved FAILED/UNVERIFIED and inactive imports
with attention remain visible. Conservative invalid/missing-review metadata
fallback still warns; reviewed originals remain unknown in storage. Inactive
history cannot hold the waiting indicator. Queue links to existing audit and
supported saved-import pages. Stable row signatures ignore historical rows;
no outcome deletion, acknowledgment, retry, retention, authority or device change.

Product0.2.1→0.2.2. Full Python **3621/671.80s**, final focused **91/4.33s**,
final browser/JS **101/151.04s** pass. Tests cover1920/1440/960/375px button-label
association, completion/cancellation exit, inactive-import attention and invalid
review fallback. Intermediate old UI expectations were updated to require no
completed Queue rows. Compileall/Ruff/diff, configured non-executing Web,
all38 compiled templates and installed package/build/footer pass. Image comparison
confirms only CSS/freshness JS/refresh-panel template/version literal changed.

Deployed only Web **5fd215581cf8... /219bcead8193** at **15:27:12Z**, source
**c00f0cbd7a75**. API0.2.0 **454e6336b0b2... /6b548900c147** and agent
**8d9f196ceea1... /4b2aa4744e96** did not restart. All three overlays/original
managed DB/import/v6/gates remain. Compatible Web0.2.1 retained as
`ftd-shun-web:lab-pre-current-queue-20261111`. No new job, fixture, control request,
consent, recovery decision, schema, secret/trust/network or authentication change.

Live Webhealth200/seven anonymous protected routes401/source assets/footer pass.
At **15:27:35Z**, integrity ok/nine original fingerprints/all26 unknown rows
unchanged,3574 IDLE/no RUNNING. At **15:27:42Z**, coordinator running/no error/
zero unresolved attention,26 reviewed retained; original import32,425/32,425
complete,32,426 observed/325 pages,Unmanaged0. Controls unchanged Active/imports
revision2/restoration revision4/six existing requests; seven recovery receipts
retained. Private evidence/screenshots `/tmp/ftd-queue-ui-20261111.XbXQzR`.
Reload old tabs. Synthetic browser coverage is not live authenticated-browser
or production acceptance. See [Operator Workspace](manual/operator-workspace.md).

## 2026-11-11 — Visible IP workspace and concise action names, Web v0.2.3

Operator requested discoverable per-IP controls instead of long repeated buttons
and easily missed disclosures. Lists now link directly to the address workspace.
Visible device cards expose Unblock, Stop restoring and separate ordered review;
whole-fleet review stays explicit. These prepare existing reviews, not immediate
new mutation paths. Short confirmation labels retain visible frozen consequences,
typed IP, identity/CSRF/session binding, capabilities, revisions and no-replay rules.
Advanced editor disclosures get button styling. Observations/provenance/history
remain separate from current policy, with stable live/editor IDs and focus.

The BFF reads the existing complete local v2 fleet scope, including enabled but
absent managed targets. Extracted the existing strict inspection validator into
a pure shared helper; review creation retains identical canonical checks.
GET allocates no review token/authority. Invalid/empty-or-oversized/unavailable
scope stays explicit rather than becoming an empty registry. Disabled targets
cannot use an unblock button, while policy-only retirement remains available.
Validated-IP deep links prefill import text without device selection/draft save,
or open the matching protected-IP editor without policy changes. No new API
endpoint, schema, protocol, feature gate or executor behavior.

Product0.2.2→0.2.3. Full Python **3628 passed/one obsolete pre-collected URL
assertion in649.08s**: the test had collected the old unanchored protection URL
before the editor-fragment refinement. Final focused **173/50.80s** and explicit
new integration cases **8/2.72s** pass with the final anchored URL. No second clean
full run claimed. Final browser/JS **102/150.78s** pass, covering visible controls
without disclosures, absent maintained target, disabled/read-only behavior,
mobile/light/dark and focus retention. Existing frozen reviews/queued cancellation
still pass; integration GET/prefill snapshots prove no store mutation or agent
call. Ruff/compileall/diff and all39 template/package/source/footer checks pass.

Configured candidate read-only compatibility with the actual API validated one
existing complete scope (one target, managed revision6/protection revision1),
without a BFF identity spoof or device operation. Deployed only Web
**0aeccc99347c... /959f1f5edc81** at **16:02:07Z**, source **a659ca2aa480**.
API0.2.0 **454e6336b0b2... /6b548900c147** and agent **8d9f196ceea1... /
4b2aa4744e96** did not restart. All three overlays/original DB/import/v6/gates
remain. Compatible previous Web retained as
`ftd-shun-web:lab-pre-ip-workspace-20261111`. No lab job/fixture/control/consent/
recovery, credentials/trust/network/authentication or data reset change.

Live Web200/eight anonymous routes401/source assets/footer pass. At **16:02:32Z**
integrity ok/all nine original fingerprints/all26 unknown rows unchanged,
**3583 IDLE/no RUNNING**. At **16:02:39Z**, coordinator running/no error/zero
unresolved attention,26 reviewed retained; original import32,425/32,425 complete,
32,426 observed/325 pages,Unmanaged0. Independent controls unchanged Active,
imports revision2/restoration revision4/six existing requests; seven recovery
receipts retained. Private evidence/screenshots `/tmp/ftd-ip-workspace-20261111.nHVR54`.
Old tabs need one reload. Synthetic browser/integration and bounded readonly lab
checks are not live authenticated-browser/device-write or production acceptance.

## 2026-11-11 — unified pre-consent Unblock review (0.2.4)

Operator feedback: separate ready/wait buttons exposed internal scheduling and
an idle target's ordered inspection misleadingly showed a red unavailable state.
The IP workspace now has one Unblock entry, a separate policy-only Stop restoring,
and fleet removal only when multiple devices exist. Block-on-devices is secondary.
POST preparation authenticates/validates CSRF and canonical scope, reads status
and complete strict local preflight, and selects the existing token registry
before consent: READY uses the same exact scope in the ready contract; WAITING_ADD
uses captured predecessors in the ordered contract; BLOCKED creates no token.
Unavailable/invalid advertised inspection never falls back. Confirmed/uncertain
requests keep original mode, scope, key/deadline, independent gates and fences.
No new API/agent/storage contract or device write path.

Reviews keep outcome/consequences, exact device list, blockers and typed-IP
confirmation visible. Technical UUIDs/revisions/session evidence are collapsed.
Old explicit ordered READY shows a neutral explanation plus an explicit new
Review unblock button; it does not convert consent or execute automatically.
Architecture and operator manuals document the pre-consent boundary.

Final focused Python **152/36.64s** and browser/JS **102/146.23s** pass.
Tests cover readonly initial selection, fleet/device scope, blocked/no token,
invalid/substituted preflight, missing capability/default-off admission, role/
CSRF/field checks, state drift rejecting instead of changing mode, and original-key
retry after a lost ready response. Responsive desktop/mobile and light/dark
screenshots inspected; frozen scopes/focus and existing wait contracts pass.
An initial restricted synthetic runner stalled and was terminated; all reported
passing runs used the required local ASGI/browser permissions. Compileall/Ruff/
diff, candidate installed version/build/footer/all39 templates/66 routes and
actual unchanged API readonly READY scope compatibility pass.

Web image **5f662db4b804...**, source **e48a5a494686**, product0.2.4.
No listener or authenticated live BFF/device mutation was used in preflight.
Clean full Python **3646/637.56s** passes with final source/tests. Previous0.2.3
retained as `ftd-shun-web:lab-pre-unified-unblock-20261111`. At17:05:51Z readonly
baseline: integrityok/nine original fingerprints retained/26 raw unknowns retained,
3598 IDLE/no RUNNING. At17:06:11Z original import32425/32425 complete,32426
observations/325 pages,Unmanaged1, zero unresolved attention, coordinator running/
no error. Controls unchanged Active/importsrev2/restorationrev4/six requests.
Evidence `/tmp/ftd-unified-unblock-20261111.qgHlnY`. No lab fixture, new consent,
policy retirement, replay, recovery, secret/trust/network/authentication change.

Deployed only Web **b7ee92aab502** at **17:13:11Z**. API0.2.0
**454e6336b0b2... /6b548900c147** and agent **8d9f196ceea1... /4b2aa4744e96**
did not restart. All three overlays/original managed-v2 DB/import/v6/gates remain.
Web200/ten anonymous GET/POST routes401/source assets/package/footer pass. At
**17:13:30Z** integrityok/all nine original hashes/all26 unknown rows unchanged,
**3600 IDLE/no RUNNING**; at **17:13:37Z** running/no error/zero unresolved
attention, original import32425/32425 complete,32426 observed/325 pages,Unmanaged1.
Controls unchanged Active/importsrev2/restorationrev4/six existing requests; all
seven recovery receipts retained. Before/after private readonly snapshots are in
the evidence directory. No device mutation or authenticated live UI submission was
used for this delivery; do not claim such acceptance. Reload old tabs.

## 2026-11-11 — captured cleanup across deferred handoff (source-only0.2.5)

Continued the import/first-confirmation work rather than expanding unrelated UI.
The exact fresh deferred execution profile now recognizes existing ordered
reservation/promotion schemas. No new DDL or consent fields; initialization order
remains empty deferred setup, then explicit paused/quiescent ordered extension.
Recovery profiles still refuse; ordinary workers/public selectors remain v5/v6.
An existing qualifying RUNNING-ADD reservation may survive actual settled-v7
handoff. Awaiting confirmation waits neutrally rather than promoting on IDLE or
becoming false attention. After the exact member's first causal complete read,
promotion binds its original claim/owner/epoch and immutable observation verdict,
then uses the existing atomic full-scope urgent REMOVE delegation. Independent
awaiting work remains a conflict. Original deadlines/current policy/protection/
inventory/fences/capacity and unknown holds are unchanged. Cancelling/expiring a
reservation does not resume maintenance. Startup refuses an absent store without
creating a file. Deferred statuses are accepted only for captured ADDs, not REMOVE.

New real-coordinator/synthetic12-address tests reserve the first RUNNING ADD,
send one batch, settle without a final read, confirm from the next complete read,
then perform priority verified cleanup without another ADD. Lost settlement keeps
all12 unknowns/attention and admits no REMOVE. Other tests cover present/absent
device/fleet delegation, replay/deadline preservation, reopened state, noncausal
read refusal, cancellation/expiry, changed device/protection/pause, late whole-
fleet rollback, foreign capture and disagreeing verdict. No live FTD commands.

Final focused **125/41.51s**, clean full Python **3665/663.63s** and browser/JS
**103/147.03s** pass with final source/tests.
The browser test covers awaiting/observed/absent labels without false success,
automatic requests or device demand. Compileall/Ruff/diff pass. Product source
0.2.4→0.2.5, build **fcd5e3f4e342**. Separate validation image
**dadaed3d3b34181907313e266a0bf2a6a4fd6dcd7450c24ddbbf0de47491d2f7**
(`ftd-shun-manager:source-0.2.5-deferred-ordered`) agrees on package/build/footer/
all39 templates. Networkless readonly same-fixture comparison proves candidate
acceptance and actual0.2.4 image refusal of the combined profile. Candidate also
validates the actual existing v6 lab profile query-only; no initialization or
execution occurred. Private evidence `/tmp/ftd-deferred-ordered-20261111.5MJ4ky`.

No deployed tag/container/configuration, original task/data, credentials/trust/
network/authentication, lab gate, consent or recovery changed. Current Web0.2.4/
API0.2.0/agent remain running v6. This is not a configured v7 rollout, live import
speedup or general unknown-write recovery. Initial already-awaiting capture,
existing multiple-RUNNING preflight limits, compatible deferred recovery and
deliberate fresh-store composition/acceptance remain next. No old authority,
original import or recovery key may be replayed to demonstrate this source.

Readonly lab status **18:22:33Z**: coordinator running/no error, zero unresolved
attention/26 reviewed unknowns retained; original import32425/32425 complete,
32426 observations/325 pages,Unmanaged1. Actual Web/API/agent container IDs and
start times match the previous0.2.4 checkpoint. No new device command, service
restart or live profile change; no Rust/wire changes or Rust rerun claimed.

## 2026-11-11 — new cleanup consent while already awaiting (source-only0.3.0)

Continued deferred import/cleanup composition. Readonly ordered inspection can
now capture an exact still-maintained AWAITING_CONFIRMATION target after original
settled-v7 handoff, before its first complete read. This is an explicit second
predecessor variant, not a RUNNING alias: kind/session/settled_at replace live
lease_until, with original request/intent/generation/snapshot/claim/owner/epoch
and immutable claim/ACK/member/session digest. Bounded original actor/audit proof
is checked; current scope/protection/inventory/fences/uncertainty/capacity remain.
Mixed running/settled fleets freeze together. Old ADD authorization can be
expired, never renewed; only new actor-attributed cleanup consent is admitted.
An intervening first read rejects stale confirmation rather than converting it
to ready consent. Promotion/retention recheck exact original settled evidence.
Private request models use strict disjoint variants, rejecting extra live-lease
fields and unknown kinds. No new DDL, CLI/binary wire or runtime selector.

Web review distinguishes Wait for confirmation and completed SSH from still-
running work, preserving immutable typed-IP consent/focus and actual capability
gates. Product0.2.5→0.3.0 for the new consent feature/optional stored format;
old canonical running payloads remain unchanged.0.2.5 images refuse stored new
variant roots; no compatibility converter or live profile change follows.

Clean full Python **3688/644.99s**, final focused **271/62.98s** and browser/JS
**104/150.12s** pass on final source/tests.
Tests cover strict request parsing→actual reservation, device/fleet/mixed scopes,
expired original ADD, stale review conflict, malformed/foreign proof, complete
12-member scope, successor-lease preservation, fresh-coordinator confirmation/
verified cleanup without another ADD, and cancelled authority through retention.
Browser tests preserve focus/frozen key and responsive layout while explaining
already-completed SSH truthfully. Screenshots inspected. Compileall/Ruff/diff pass.

Final build **1fa9fb5b673b**, separate image
**6a239f767131cae952292ded362f9c8a68778551d5abe877ee4c07a27a5a855b**
(`ftd-shun-manager:source-0.3.0-pending-capture`) agrees on installed package/
build/footer/all39 templates. Networkless readonly checks prove candidate accepts
new and previous running-consent fixtures while actual0.2.5 refuses new data.
Candidate also validates a consistent actual-v6 snapshot query-only; no initializer,
listener, spoofed live identity or FTD call. Evidence
`/tmp/ftd-pending-capture-20261111.dgzULM`.

No deployed tag/container/configuration, original import/dataset, credentials/
trust/network/authentication, consent/control/recovery or live mode changed.
Current Web0.2.4/API0.2.0/agent remain v6. Compatible deferred recovery, deliberately
configured fresh-store composition and bounded lab acceptance remain next;
unknown writes and multi-RUNNING preflight guards were not relaxed. This is not
live throughput/production acceptance or a published GitHub release/tag.

Final hardening also rejects substituting any legacy/unknown outcome for a
settled descriptor, so it cannot bypass the required first observation via a
legacy success branch. Six extra negative cases pass. The first full run was
terminated at33% before this hardening and restarted on final source; it is not
a passing full run. Preliminary browser104/145.02s also passed; final browser
104/150.12s is the reported run.

A final direct readonly live-file preflight hit an SQLite WAL/checkpoint race
(`unable to open database file`), not a profile acceptance. Created an exclusive
consistent SQLite backup solely for query-only build validation:
`private-backups/pending-capture-validation-20261111-52158ed5/readonly-v6.db`
in the state volume,250531840 bytes, integrity/FKs ok. Final candidate validates
that immutable archive; it is not restored, executed, imported or used as new
authority. Services were never stopped. At18:53:00Z readonly status running/no
error/zero unresolved attention,26 reviewed retained; original import32425/32425
complete,32426 observed/325 pages,Unmanaged1. Web/API/agent identities/start times
match the prior checkpoint. No live dataset or execution-profile change.

## 2026-11-12 — Exact lost-terminal pending-v7 recovery (source-only v0.3.1)

Added a distinct bounded process-local completion lookup (`0x1e`) for the exact
original tracked-v7 END_PENDING sequence and ordered targets. The agent prepares
it only after real terminal execution and successful disconnect, including local
response-send failure. Publication remains in the existing postamble after
handler/resource cleanup, device-guard release and worker-IDLE. The 4096-entry
journal still evicts only completed entries. Mutated sessions never acquire
read-only lookup (`0x19`) authority, and lookup does not enter SSH/device guards.

The original low-level client may query once (at most five seconds) only after
fully sending END_PENDING and losing a response to EOF/socket failure/timeout.
It closes the original connection, validates the full original device/version/
nonce/sequence/nonempty ordered ACK scope, and returns only a typed settled-pending
value. Malformed/truncated/foreign packets, short terminal send or lost stage ACK
cannot choose this recovery. No BEGIN, ADD or END is resent; no snapshot or
verified creation is fabricated. The deferred worker retains the existing atomic
original live-lease/claim/ACK/root/delegation handoff, then logs recovered settlement.
The next causal complete read still confirms presence or absence normally.

Focused Python **233/46.81s** passes. Shared Python/Rust vectors and local seqpacket
tests cover response/header/timeout loss, active/unknown/foreign/closed journal,
bad bindings/scope/status/count/order/trailing bytes, lost ACK, malformed/truncated
original evidence and repeated-call refusal. A real-client/disposable-DB worker
test stages12 addresses, recovers a lost response, performs atomic pending handoff
and confirms after coordinator restart, without a second ADD. Active/foreign proof
and post-recovery audit transaction failure retain original unknowns and holds.
Rust **100+7+4** tests, locked release/Clippy/fmt and Ruff/compileall/diff pass.
Clean full Python **3739/693.26s** passes on final source/tests. No browser rerun:
no UI behavior changed.

Separate validation images, never deployed:

- App `e4225632b1199170348915c75e874c7bbbe67e1c1179a0187b8b4c42d8eab0fb`
  (`ftd-shun-manager:source-0.3.1-pending-lookup`), public source **7a2ee3fd0343**.
  Installed package/build/footer/all39 templates match. Networkless query-only
  validation accepts the previous immutable actual-v6 archive, integrity/FKs ok;
  that archive is not restored/executed or used as authority.
- Agent `aaaf7e590015601b1f1ed9ad23a3d849067caff456ea6055b41f1632ecb7d491`
  (`ftd-shun-agent:source-0.3.1-pending-lookup`). Release container check-only
  accepts a synthetic Basic user/password and TEST-NET inventory with networking
  disabled and no live credential/data mounts.

Evidence: `/tmp/ftd-pending-lookup-20261112.ZmmzuK`. Initial sandbox Rust run had
socketpair EPERM (88 pass/11 fail); rerun with local socket permission passes.
Early focused runs exposed an incomplete object-based old-version fixture and
an overly strong negative-test assertion about the pre-existing refused read-only
lookup. Version validation order/test expectation were corrected before the final
focused/full runs; those early runs are not passing validation claims.

Read-only actual lab check08:47:10Z: integrityok, all nine original fingerprints
and all26 unknown rows equal the prior checkpoint, epoch3779 IDLE/no RUNNING.
At08:47:12Z status running/no error/zero unresolved attention,26 reviewed history;
original import32425/32425 complete,32426 observations/325pages,Unmanaged1.
Imports/restoration controls remain Active, revisions2/4, six requests. Existing
Web0.2.4/API0.2.0/agent image/container IDs and start times are unchanged. All three
overlays/original DB/import/seven receipts remain. No service restart, live DDL,
new consent/control/recovery/import/device command, secret/trust/network change
or v7 selection. General crash/held-epoch recovery and deliberate configured
fresh-store composition/acceptance remain next; no live speedup claim follows.

## 2026-11-12 — Plain Protected-IP wording and operator guide (Web v0.3.2)

Replaced protection jargon with actions and consequences. Protected IPs explains
automatic unblocking after a successful check and all-enabled-device scope.
The short warning says disabling protection does not add a block. **How protection
works** explains on/off/delete, previously imported IPs, turning off auto-restore,
new imports, queued timing, running/manual work and concurrent edits without
requiring revision/intent knowledge. Checkbox text is **Automatically unblock
this IP**. Shared Managed help and IP notices use the same explanation. The
operator manual now opens with an on/off/delete table and concrete example;
implementation checks remain in the technical sections. Contributor guidance
requires outcome-based operator wording without hiding consequences/blockers.

Presentation only: no form names/hidden revisions, routes, policy behavior,
authorization/CSRF, queue cancellation, data/schema/protocol or feature selection
changed. Product version0.3.2; source build **2c31c6d962b1**. Existing Python checks
**248/45.47s** and final browser/Node **104/172.63s** pass, including protection
retirement, stale drafts/hidden revisions, CRUD without device hints, shared help,
IP actions and desktop/mobile layouts. Screenshot inspected. Ruff/compileall/
JS/diff pass. No new copy-mirroring tests or full Python/Rust rerun: the business
logic/controller/agent were unchanged in this increment.

Image **6aa4928a4a1ec20b098c90565a4f9f841a02b077b589f751b57cb78a17a91925**
(`ftd-shun-web:source-0.3.2-protection-copy`) matches package/build/footer,
all39 templates/66 routes and read-only current API preflight. The preflight
renders the page from actual policy/status GETs and validates the unchanged READY
scope; no server listener, hint, consent or FTD write is started. Only Web was
replaced at **09:19:29.966Z**, container
`3bd44ee1e4d9e77a857e78e267e6b0ee7ae58c69e5ed8ee023bb74d1977cf35b`.
API0.2.0 `454e6336b0b2...` / `6b548900c147...` and agent `8d9f196ceea1...` /
`4b2aa4744e96...` kept their original start times. All three overlays/original DB/
import/v6 selection remain. Source-only deferred-v7 work is not activated.
Compatible rollback: **ftd-shun-web:lab-pre-protection-copy-20261112** (0.2.4).

Live Web200, ten anonymous protected routes401, source-matching assets and all
three changed-template hashes pass. At09:19:50Z integrityok/all nine original
fingerprints/all26 unknown rows unchanged,3785 IDLE/no RUNNING. At09:19:54Z status
running/no error/zero unresolved attention,26 reviewed history; original import
32425/32425 complete. No policy/consent/control/recovery/device request was sent.
All receipts and data remain. Evidence/screenshots:
`/tmp/ftd-protection-copy-20261112.1emA7G`. Reload old tabs. Synthetic Chromium
acceptance is not a live authenticated-browser/device-write acceptance claim.

The initial browser run failed five screenshot writes because its output directory
was not created; it is retained separately and is not passing validation. The final
full browser rerun above uses the correct existing directory. An initial non-serving
preflight omitted the required refresh context; it was corrected to use actual
read-only status before the successful preflight and rollout. Neither helper
failure changed live data or involved a device command.

## 2026-11-12 — Fresh deferred storage and pause-aware retries (source-only v0.4.0)

Added explicit `ftd-shun-dev-init --profile deferred-confirmation`; default
`verified` retains its current layout. The initializer creates pending evidence/
execution/retries before ordered cleanup/promotion and both operator controls,
inside its existing private staging database. Profile selection is literal and
reported/audited. Destination refusal, mode0600, inventory drift checks, integrity/
checkpoint and exclusive publication remain; no old file, queue, authority or
history is converted. Optional protection copying remains explicitly selected
current settings only. This does not enable a configured v7 client/API/agent.

Deferred retry selection/discovery now checks the target's existing independent
import/restoration pause before emitting retry-only read demand or admission.
It advances bounded cursors and reports sampled pause counts instead of treating
paused targets as failed/ineligible. Other work, already claimed-group settlement,
causal first confirmation, manual/periodic reads and Protected-IP unblocking
remain available. A resumed child still requires a new read beyond its selected
control's barrier; the old confirmed-absence snapshot cannot authorize it.

Clean full Python **3764/728.06s**, final focused **206/103.67s** and Ruff/
compileall/diff pass. Tests cover both profiles' overwrite/symlink/race/partial-
failure refusal, private empty combined storage, actual maintenance identity,
old-profile preservation, ordinary-worker refusal, both independent pause kinds,
no retry-only read spin, manual refresh while paused, fresh Resume, already sent
confirmation and protected removal with both pauses. New tests use disposable
SQLite and semantic fake sessions; no lab FTD writes. No browser/Rust rerun:
frontend and agent code are unchanged in this increment.

Candidate image
**d367a403102ee44b327baac80d83de1a0e6000b8c5a7df1390b33b6da9a057a9**
(`ftd-shun-manager:source-0.4.0-deferred-profile`), source build **c9aa7db3143e**,
matches installed package/build/footer/all39 templates. Networkless release-image
preflight runs both CLI selections in disposable tmpfs and verifies exact profiles,
empty work/observations, both controls, audit identity/profile, mode0600, integrity/
FKs and existing-file refusal. Query-only validation accepts the prior immutable
actual-v6 archive. That archive is not restored, executed or used as authority.
Evidence: `/tmp/ftd-deferred-profile-20261112.IQ4AkE`.

No live profile/database/configuration, service restart, import/consent/control/
recovery or device request. At09:51:52Z actual lab integrityok, all nine original
fingerprints and26 unknown rows equal the prior Web checkpoint; normal epoch3792
LEASED, not globally idle. At09:51:56Z status running/no error/zero unresolved
attention,26 reviewed history, original import32425/32425 complete,32426 observed,
Unmanaged1. Current Web0.3.2 `6aa4928a4a1e...` / `3bd44ee1e4d9...`, API0.2.0
`454e6336b0b2...` / `6b548900c147...` and agent `8d9f196ceea1...` /
`4b2aa4744e96...` kept their exact start times. All three overlays/original DB/
import/seven receipts and v6 selection remain. Matching configured transport/API,
compatible crash/held-epoch recovery and bounded fresh-store lab acceptance remain
next; no live throughput or enabled-v7 claim follows.

## 2026-11-12 — Explicit configured deferred mode (v0.5.0, not activated)

Added literal default-off `FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED` across Settings,
the actual Unix client, configured API factory and Rust agent. It requires matched
grouped7/strict tracked ADD prerequisites, real deployed authentication and exact
bounded public device scope. Wire version7 alone or partial flags refuse. Defaults
and verified5/6 behavior remain. The configured factory now selects exactly the
deferred dispatcher on existing complete pending execution/ordered/control storage;
wrong/missing profiles never initialize, convert or fall back. Lifecycle validation
rechecks frozen configuration, transport/inventory and required controls. Existing
consent, priority, protection, pause/barrier and unknown-outcome guards remain.

The API keeps its continuous-managed workflow family and returns the explicit
deferred boolean, passed through by BFF metadata. API `--check` and agent
`--check-config` report selection without execution. Added an optional explicit
lab overlay with distinct `deferred-v7.db`; it is NOT applied. `.env.example`
stays default-off, and actual `.env`/inventory/credentials/trust remain unchanged.
Updated current manuals to distinguish configured support from remaining live
activation/recovery work instead of leaving obsolete unconditional-v7 refusals.

Clean full Python **3793/768.42s**, final affected **223/76.41s**, Rust **100+8+4**,
strict Clippy/locked release/fmt and Ruff/compileall/diff pass. New real API
preparation/consent→actual seqpacket client→local synthetic peer test sends two
ADDs, shows AWAITING_CONFIRMATION, confirms only on the next complete read as
OBSERVED_PRESENT, and replays original consent without another ADD or invented
creation provenance. Tests also cover canonical flags/versions, exact scopes,
wrong/absent/control-incomplete storage, no-init/no-connect/GET/preflight, and
changed transport before lifecycle start. Rust process-isolated checks cover
the separate canonical agent gate and default/legacy compatibility. No browser
rerun: templates/JS are unchanged; metadata pass-through is directly covered.

Final build **c7b297637706**; separate validation images:

- App **aaa47fe070ea1c922d06724dfdea5ccf31bbe1d1d9dfd04cb9104a905da779c9**
  (`ftd-shun-manager:source-0.5.0-configured-deferred`). Installed package/build/
  footer/all39 templates agree. Actual configured CLI preflights run against both
  disposable layouts with networking disabled, rejecting mismatched profiles
  and preserving all synthetic data. The actual-v6 immutable archive is read
  query-only, never restored/executed or used as authority.
- Agent **c226db65e8333a5f351b49a005379c8bc090f27341d073c5720574cbefdf16b8**
  (`ftd-shun-agent:source-0.5.0-configured-deferred`). Its packaged release binary
  reports matched7/deferredtrue in check-only mode using synthetic credentials/
  TEST-NET inventory, no networking/listener or lab mounts.

Composition check validates only selected flags/DB paths from the explicit four-
file composition with service env-file resolution disabled; no resolved secret
dump is retained. Evidence `/tmp/ftd-configured-deferred-20261112.5UWIQu`.
Subsequent module/comment alignment changed the public digest from the initial
candidate; final images were rebuilt and checked against the final source.

No live deployment/profile/schema/gate, import/consent/control/recovery or device
command. At10:35:31Z lab integrityok/nine original fingerprints/all26 unknowns
unchanged,3802 IDLE/no RUNNING. At10:35:36Z running/no error/zero unresolved
attention,26 reviewed history, original import32425/32425 complete,32426 observed,
Unmanaged1. Web0.3.2/API0.2.0/agent retain exact prior images/containers/start times;
original DB/all three live overlays/v6 and seven receipts remain. General crash/
held-epoch recovery and bounded real-device acceptance remain next before the
planned lab cutover. No new-mode live throughput or production acceptance claimed.

## 2026-11-12 — exact completed pending-END crash handoff, source v0.6.0

Added an append-only pre-END checkpoint to the explicit deferred worker. It binds
original ordered jobs/ACKs/sequence/group, public inventory and complete original
visit evidence, including a known verified/no-op prefix. A restarted worker checks
this before generic lease expiry can turn still-RUNNING jobs unknown. One real
bounded local completed-session lookup can then atomically retain the original
pending receipt, move jobs/attempts to awaiting confirmation and release exactly
that unchanged expired LEASED row. No renewal, ADD replay, new authority or
creation attribution is introduced; ordinary live handoff keeps its live guard.

Recovery returns to the scheduler to honor the existing strict causal next-read
barrier. Missing/active/foreign journal evidence, changed inventory/checkpoint/
visit, concurrent owner/epoch changes, clock reversal, historical unknowns and
ATTENTION refuse. Local failures roll back the whole handoff. Cancellation drains
the bounded local operation; retention keeps the checkpoint and complete unsettled
visit/prefix. Uses existing audit and exact pending storage, with no schema,
protocol, agent, default selection or live configuration change.

Clean full Python3849/730.65s and final focused232/83.81s pass, including all103
restart/lookup cases. Actual local
seqpacket tests and an additional fresh-interpreter synthetic probe pass: one
journal lookup, two awaiting jobs, original claim/ACK audit unchanged and a second
local recovery call does nothing. The maximum64-claim visit (48 known verified,
16 pending), retention, atomic rollback, changed fence/inventory/evidence,
missing/foreign journal proof and cancellation drain are tested. Ruff/compileall/
diff pass. No Rust/browser rerun:
no agent/JS/template change.

Candidate `fd022bf7556b`, app image
`sha256:37b22683c92f500b9f63c9d80f0e2d884379b3bdeac96697897661b7d1f89a77`,
local tag `ftd-shun-manager:source-0.6.0-pending-restart`, passes package/build/
footer/39 templates, both actual networkless configured profile checks,
wrong-profile refusal, unchanged synthetic DBs and immutable actual-v6 archive
readonly compatibility. Private evidence `/tmp/ftd-pending-restart-20261112.3pgwg6`.
At11:09:04Z lab integrityok/nine original fingerprints/all26 unknown rows
unchanged,3809 IDLE/no RUNNING. At11:10:40Z running/no error/zero unresolved
attention,26 reviewed, original import32425/32425 complete,32426 observations/
Unmanaged1. Actual Web0.3.2/API0.2.0/agent images, containers and start times,
original DB/all three overlays/v6 and all seven receipts remain unchanged.
No live deployment, consent, control, recovery decision or FTD command was sent.
General held-epoch/missing-journal recovery and real-device deferred acceptance
remain before laboratory cutover. Follow manual/pending-restart-recovery.md.

## 2026-11-12 — explicit dialog consent and row actions, Web v0.7.0 lab

Replaced typed-IP consent for unblock/retirement with named button consent over
the original frozen review. Added a native dialog with same-origin HTML loading,
script/refresh-controller removal, independent DOM/focus, explicit original-body/
key retry after unknown/5xx and native-form fallback. Ordinary browser unblock
prepares first. Browser exceptions/validation negotiate HTML; JSON clients keep
structured errors. Visible row actions expose unblock, selected-device managed
adoption/editor prefill, protection and details. Existing API authority, scopes,
gates, CSRF and legacy correctly typed submissions remain; no API/agent/schema
or default feature-gate change.

Full Python3840 passed/12 stale typed-input and no-row-form assertions, corrected
and rerun in final focused277/76.42s; no second full run claimed. Browser105/
152.73s pass. Mobile/light/dark screenshots checked; primary-button/copy refinement
received a further browser pass. Ruff/compileall/JS/diff, built package/footer/
source identity/all41 templates/66 routes/actual read-only API compatibility pass.

Only Web replaced at11:57:20Z: image
`sha256:a2519be248ae88f18009cadba495da9af0421cb8a0dc558b9a20a4803d9782fe`,
container `4b96861ec4e9...`, source `5c95f3c5609d`/version0.7.0. API0.2.0 and agent
identities/start times unchanged. Web200/ten anonymous401/served assets match.
At11:57:51Z integrityok/nine authority fingerprints/all26 unknown rows unchanged,
3818 IDLE/no RUNNING. Original DB/v6/three overlays/import/seven receipts retained.
Rollback `ftd-shun-web:lab-pre-action-dialogs-20261112`; evidence
`/tmp/ftd-action-dialogs-20261112.MrUpBt`. No policy/job/consent/device experiment.

Operator separately authorized background outbound RDAP on the lab. Announced
initial scope: two existing public IPs, no FTD writes; implementation follows.

## 2026-11-12 — isolated cached RDAP context, Web/helpers v0.8.0 lab

Implemented optional occurrence-driven IP registration context after explicit
operator outbound authorization. An internet-connected worker receives only a
dedicated observation UDS and own cache. A networkless helper serves bounded
query-only source observations/audit; Web gets cache RO, no internet. Persisted
attempts survive restart; no active-occurrence retry, page-triggered query,
additional-device query or silent initial/gap backfill. Complete disappearance
then redetection permits a fresh occurrence. Fixed IANA/RIR TLS destinations and
exact-IP referral paths, byte/time/rate/cache limits and429 cooldown apply.
Contact/person/email/postal fields are excluded; country/network/organization,
range/source/time remain advisory. Lists and addition/removal dialogs batch-read
only displayed entries; metadata revisions refresh lists without a device hint.

Disposable Docker testing exposed two SQLite read-only details before acceptance:
the source's absent WAL/SHM needs query-only housekeeping through a networkless
feed, and the separate cleanly stopped cache must use rollback journals for RO
Web mounts. The original DB's WAL mode remains unchanged. Initial failed cache
fixture/image/log retained; final actual UDS/no-network synthetic producer kept
source data unchanged, exited and left a readable cache on an actual RO mount.

Full Python3889 pass/one obsolete template-attribute adjacency assertion, fixed
and covered by final focused159/34.63s. No second clean full run claimed. Final
cache-journal correction received focused regression and Docker proof. Browser/
Node106/162.62s, Ruff/compileall/JS/diff and filtered configured isolation pass.
Final image package/build/footer/42 templates/66 routes and actual read-only API
scope preflight pass. Browser acceptance uses synthetic identities/fixtures;
actual Web acceptance is anonymous access/health/assets plus cache/template reads.

Final image
`sha256:26ffcb45c5e6c52a02f463edc27a3147c7c6a724c2d30dd5b6463508b18c3d3b`,
source `f57df396aeba`/version0.8.0. Feed `09e1d81a6be3...` started12:53:06Z,
worker `786052dc4a6a...`12:54:03Z, Web `b9c3a9bd978a...`12:54:25Z. New dedicated
cache/feed volumes and outbound network only; networkless Web/feed, worker only
its own network/mounts were inspected. API0.2.0/agent exact images/container/start
times unchanged. Keep original three overlays plus optional RDAP overlay;
source-only deferred-v7 remains off. Web rollback retained as
`ftd-shun-web:lab-pre-rdap-20261112`; never restore original DB for this rollback.

Explicit fresh first sample attempted only two of32426 existing observations:
1.2.188.158 returned APNIC TH/TOTNET;1.34.28.195's referral left the fixed allowlist
and remains unavailable/consumed. The other addresses were not backfilled.
Five repeated actual Web cache reads rendered country/network/source with still
exactly two attempts. No FTD command or new policy/job/consent/control/recovery.
At12:54:56Z integrityok/nine original fingerprints/all26 unknown rows unchanged,
3832 IDLE/no RUNNING. At12:55:02Z no last_error/zero unresolved attention, original
import32425/32425 complete,32426 observations,Unmanaged1. Web health200/ten
anonymous routes401/served assets match. No production/load/live authenticated
browser acceptance claimed. Evidence `/tmp/ftd-rdap-20261112.nnmWxu`.

## 2026-11-12 — local IPFire enrichment/backfill and refresh, v0.9.0 lab

The operator observed that the RDAP experiment enriched only one entry and chose
a new lifecycle: fill missing existing IP information and refresh periodically.
Evaluated official IPFire/Team Cymru documentation. Selected a local IPFire
Location source for country/ASN/network name; Team Cymru advises few-thousand
bulk WHOIS runs/DNS for recurring use and remains a possible supplement only.
The new architecture amendment supersedes the old no-backfill/once-per-occurrence
restriction for the selected local provider. No automatic WHOIS fallback added.

Kept networkless Web/query-only feed and separate metadata storage. Only an
optional Docker target installs official Debian location/python3-location. A
fixed native JSON bridge performs one process per bounded batch. The worker
fetches a fixed HTTPS XZ database without redirects/proxies, caps transfer/
expanded bytes/time/memory, verifies libloc's vendor signature/native readability
and atomically replaces only after validation. Source updates daily by default;
active cached entries refresh on generation change or after a seven-day fallback
interval. Missing data retries on update/interval, native failures15m/download
failures1h. Previous useful data is preserved. Persisted schedule/cache survive
restart; pages and action dialogs never trigger provider work. ASN/country/name,
source time and IPFire/CC BY-SA attribution render in compact rows/cards/footer.

Focused Python250/61.39s plus final core/config/template106/1.66s and Browser/
Node107/174.96s pass. Initial restricted ASGI run stalled; unrestricted core62/
1.09s passes. Ruff/compileall/JS/diff, final built package/footer/source identity/
42 templates/66 routes and real readonly API scope preflight pass. Tests cover
local batching/backfill, source unchanged, TTL/generation refresh, missing data,
old RDAP-cache refusal, restart, source disappearance/replacement, malformed
payloads, partial/native failures, backoff, signature/download/referral refusal
and retaining good data. No new full Python/Rust regression claimed.

Actual isolated official-dataset probe initially refused the published XZ memory
requirement at64MiB. Retained failure evidence, increased the bounded allowance
to128MiB (not unbounded), and verified signature/readability with native libloc.
Dataset SHA256 `b46e22fdc0f3efbe377642f2ec6b041871dbb07a42f71a1009d348ddc291b8bf`,
source creation2026-11-12T04:45:06Z. Probe had no lab/core/secret/device mounts.

Rolled out only Web/metadata worker at13:27:15Z, source `7456eaac341b`/0.9.0.
Web image `sha256:e0f1efbe5ecee4335883b4f1e58509581b765c43912c976fe434022052e349c0`,
container `560959a1c775...`; worker image
`sha256:159d343157bba1f0034e413e0596a6416ff61eb0c503095ca0587015bdb46efd`,
container `444f6cdc6ff2...`. API0.2.0/agent/feed/Caddy/Authelia exact identities/
start times unchanged. New separate location cache in the existing metadata
volume retains old cache.db/two RDAP attempts. All original overlays/v6/DB/import/
seven receipts remain; deferred-v7 is off. No shun command/policy/job/consent/
control/recovery mutation. Worker network/mounts remain isolated from core and
management; Web has no native location executable or network.

Actual initial backfill used65 local batches from13:27:33Z to13:28:02Z:32425
public IPs processed,29045 ready/3380 not_in_dataset/one special-use skipped.
No local_lookup_failed results. The formerly refused1.34.28.195 now has TW/
AS3462/Chunghwa Telecom; the other sample has TH/AS23969/TOT. Actual Web RO
cache/card/source-attribution reads, health200/ten anonymous401 and assets pass.
At13:28:42Z integrityok/nine original hashes/all26 unknowns unchanged,3842 IDLE/no
RUNNING. At13:28:48Z no last_error/zero unresolved attention, original import
32425/32425 complete,32426 observations/Unmanaged1. A real worker restart at
13:29:55Z retained results/attempt times/next daily update without downloading or
running another batch. No live authenticated-browser/production/100k-load claim.

Evidence `/tmp/ftd-location-20261112`. Web rollback image
`ftd-shun-web:lab-pre-location-20261112` (0.8.0), old helper retained as
`ftd-shun-ip-context:rdap-0.8.0-20261112`. Stop worker for update shutdown; retain
metadata/core datasets rather than reset or restore original authority.

## 2026-11-12 — direct IPFire Source links, Web v0.9.1

Changed IPFire card Source links to the exact canonical displayed IP's lookup
page, as requested. General footer attribution and existing RDAP registry links
remain; cached payload/schema, provider scheduling and permissions are unchanged.
No network request is made while rendering. Updated the existing Chromium
IPFire-dialog scenario to check the exact href, plus the operator manual.

Python81/1.44s, Chromium69/163.40s (including exact href) and source Ruff/compileall/diff
checks pass. Final built package/source/footer/42 templates/66 routes/actual
readonly API preflight pass. Actual existing217.61.226.186 context renders the
requested lookup URL; footer remains general. Web200/ten anonymous401/served
assets pass. Browser verification uses synthetic authenticated fixtures; the
actual context check is read-only, not a live authenticated browser session.

Only Web replaced at13:40:06Z: version0.9.1/source `47b0d5b73623`, image
`sha256:793fef28580af1bd96aa67f8aa752727186f8ea3242e5ebc5df2cae1a01f43c1`,
container `0bafb1487a9f...`. All other actual container/image/start identities
are unchanged, including worker0.9.0/API0.2.0/agent/feed/Caddy/Authelia. No DB,
cache, policy/job/consent/control/recovery/device change. Preserve all overlays
and data. Rollback `ftd-shun-web:lab-pre-ipfire-links-20261112` (0.9.0).
Evidence `/tmp/ftd-source-link-20261112`; reload old tabs.

## 2026-11-12 — shared IP presentation, navigable overlay and retained disclosures, Web0.10.0

Replaced inconsistent IP cells with one address/badge/context component across
observed/search/managed/protected/history/import tables; Queue builds equivalent
safe DOM with its Add/Unblock/device label retained. Fixed address width and a
reserved metadata line prevent badges/row heights shifting as cache data arrives.
A bounded presentation selector deduplicates canonical IPs across displayed
collections only, including protected/history previously omitted. Up to1000
protected/displayed keys use100-key SQL chunks within one read snapshot; ordinary
reader default100 remains. Full input/authority manifests are never scanned.
Synthetic real-Web integration proves protected/history reuse the same existing
cache without source mutation; pages never start provider requests.

Added a native GET-only IP frame, progressive over canonical links. Its URL is
shareable, Back/Close restores the list/query/page and Forward reopens. Direct
links/reload/Open page/modified clicks work normally. Background freshness now
captures its original document URL. Imported frame markup strips scripts,
controllers and live-region/editor ownership; IDs and label references are
namespaced. Underlying IP data may refresh, retaining scroll/disclosures/focus,
but frozen action reviews never refresh or change scope/token/key. A read-only
frame can open above a confirmation without changing it. Closing returns focus
to an equivalent replacement link when the original list DOM was refreshed.

Shared presentation-state capture supports details without IDs via stable keys,
restores summary focus and retains existing dirty-field/editor checks. Nested
live regions are replaced through their outermost owner only; dialogs are excluded.
Same-tab reload stores at most1000 disclosure booleans per URL, no form/token/body
values. Removed or changed actions still come from the fresh server response.

Broad Python284/61.62s and final core/template/integration86/1.59s pass; Ruff/
compileall/JS/diff pass. Initial browser fixture omitted the two new assets, so
several cases failed; serving them and keeping existing action-dialog DOM order
corrected that. Focused six affected subcases+parent7/22.97s pass. Broad browser
109 accounting:107 passed, one ADD operation-label regression plus parent failed.
Restored the label, then final four subcases+parent5/22.07s pass; final overlay/
replaced-link-focus subcase+parent2/10.05s pass. No clean second full Python/browser
run claimed. Screenshots include375px overlay plus desktop/mobile/light/dark
rows. No live authenticated browser or device-write acceptance claimed.

Final source `ec6c5836447e`/version0.10.0, Web image
`sha256:66f3c372de79df4142b58feb91a8934850ad7ea8abea98d7e7bf70696b219bc3`,
container `14ae4b55611c...`, started14:12:13Z. Final image package/source/footer/
43 templates/66 routes and actual readonly API scope preflight pass. Web200/ten
anonymous401/actual served navigation/freshness/action-dialog/ip-dialog/ui-state/
CSS hashes match. Only Web changed: metadata worker0.9.0/API0.2.0/agent/feed/
Caddy/Authelia exact images/containers/start times remain. All overlays, gates,
original DB/import/seven receipts and metadata caches are retained.

At14:12:53Z integrityok/nine original fingerprints/all26 unknown rows unchanged;
normal3857 LEASED, not global idleness. At14:12:59Z no last_error/zero unresolved
attention, original import32425/32425 complete,32426 observations/Unmanaged1.
No policy/job/consent/control/recovery or FTD command by this increment. Evidence
`/tmp/ftd-ip-workspace-20261112`, rollback
`ftd-shun-web:lab-pre-ip-frame-20261112` (0.9.1). Reload old tabs.

## 2026-11-12 — IP-frame backdrop close, Web0.10.1

Added geometric native-backdrop detection requiring a primary pointer press and
click outside the IP dialog. Padding/inside clicks and drags from inside are
ignored. Dismissal uses the existing history-aware close; URL/list/focus and
nested frozen confirmation behavior remain. No action-dialog submission or
cancellation behavior changed. Updated the existing Chromium scenario with real
pointer events and updated operator manuals.

Python19/.56s and focused Chromium overlay subcase+parent2/10.71s (69 skipped)
pass, including backdrop/inside/drag/history/frozen-review/reload behavior.
Ruff/JS/diff and final built package/footer/source/43 templates/66 routes/actual
readonly API preflight pass. No broad Python/browser suite claimed.

Only Web replaced14:35:00Z: version0.10.1/source `46e1c68725aa`, image
`sha256:df26509b4fc941f1418020014b89f0044b61efd7f3ca984e7086267ecc3bd8af`,
container `bb0de6058fb4...`. Every non-Web image/container/start identity unchanged;
all data/overlays/gates remain. No policy/job/consent/control/recovery/cache/device
mutation. Actual health200/ten anonymous401/six served asset hashes match.
Browser acceptance uses synthetic fixtures, not a live authenticated session.
Evidence `/tmp/ftd-ip-backdrop-20261112`, rollback
`ftd-shun-web:lab-pre-backdrop-20261112` (0.10.0); reload old tabs.

## 2026-11-12 — retain Team Cymru in the delivery plan

The operator accepted the bulk-import/lifecycle/Purge/release sequence and
explicitly reminded us to retain Team Cymru. Recorded it as a planned supplemental
ASN/network source for missing IPFire data after the bulk-import slice. The plan
requires bounded asynchronous bulk queries/cache/deduplication, distinct source
attribution, provider-aware retry/refresh and no page-triggered requests. Registry
country must not silently replace IPFire geography; metadata remains advisory.

Updated working plan, current priorities, operator manual and agent handoff.
Documentation-only; diff checked. No code/version/image/configuration/network,
provider query, cache/DB, queue/policy or FTD change. Current Web0.10.1 and local
IPFire worker remain the deployed behavior; Team Cymru is not enabled yet.

## 2026-11-12 — defer final full groups and validate on the desk FPR

**Source version: 0.10.2; isolated acceptance complete, main remains v6.**

Fixed a boundary defect: deferred groups ending at exactly 16, 32 or 48 addresses
were eagerly verified rather than handing off the final group. A bounded readonly
scheduling hint now distinguishes possible continuation/priority work from a final
tail. Intermediate groups and urgent refresh/removal/protection retain existing
verification; verified v5/v6 are unchanged. No schema, binary protocol, agent
source, authority, timeout, credential, trust or network change. Tests also cover
64/80-address boundaries and stop/pause/cancel. Updated the shared-IP ordering
test to accept its existing additional link attribute while retaining exact order.

Validation: deferred/shared 176 passed in 120.49s. Full Python run: 3929 passed,
one obsolete link assertion failed in 796.44s; corrected assertion and final
version/order set: 10 passed in 1.86s. No second clean full run claimed. Ruff,
compileall/diff, configured nonexecuting API/agent preflight and candidate installed
package/source/footer/all 43 templates pass. No new Rust/browser suite; no wire,
agent or UI behavior changed in this increment.

Original writers actually exited 0 at 15:25:49–50Z; original epoch 3877 was IDLE,
no RUNNING jobs. A separate prepared deferred-tail DB/socket profile used original
inventory and agent-only credentials. Fresh actor-attributed operation
`82603a46-dc48-474e-a05f-ec099aa23b1c` imported exactly 198.51.100.160–175 after
a complete absence read. One real v7 SSH visit took 60.378s: 16 ADDs, 16 retained
target preflights, one initial full read, pending tail 16. Actual settlement at
15:28:46.154Z preceded the next automatic complete read at
15:28:46.263–15:28:54.528Z. All 16 became OBSERVED_PRESENT, without ADD replay or
false VERIFIED creation. This is normal-path acceptance, not a bulk-load speedup.

Cleanup retired all 16 targets and completed 16 VERIFIED removals. The existing
ten-submissions/minute guard refused request 11 with 429; waited and reused that
exact saved key/body, without limiter changes. Clean API restart/full read kept
all fixtures absent and exactly 32 terminal jobs. Experimental API/agent exited
0 at 15:34:49Z; containers/separate volumes/state/requests/logs remain retained.
No unknown result or recovery release was created.

Restored the same original main containers/images at 15:35Z: API 0.2.0, tracked
v6 agent and Web 0.10.1. Fresh read 15:35:25Z, no error/unresolved attention,
original import complete 32425/32425, 32426 observed/Unmanaged 1, fixtures absent.
Integrity ok, all nine original fingerprints and all 26 historical unknowns
unchanged; original executor 3878 IDLE/no RUNNING. Web health 200, ten anonymous
routes 401 and source-matching assets pass. Metadata services, original DB,
overlays, pauses and seven recovery receipts remain unchanged.

Candidate application image:
`sha256:e341cf171af0ccb105d7de3255d6393a26ce22742aa7667d1bf405d0dc4fe791`,
source `936da7952899`; matched experimental agent:
`sha256:c226db65e8333a5f351b49a005379c8bc090f27341d073c5720574cbefdf16b8`.
Private evidence: `/tmp/ftd-deferred-tail-20261112`, including exact original/
candidate images and exits, immutable requests/receipts, telemetry and comparisons.
Persistent v7 cutover/general held-epoch recovery and broader lifecycle/failure
acceptance remain unfinished. Team Cymru remains the next metadata slice.

## 2026-11-12 — optional Team Cymru supplement, awaiting activation approval

**Source version: 0.11.0; candidate ready, current runtime unchanged.**

Implemented the retained metadata follow-up using Team Cymru's recommended DNS
interface for recurring queries. The existing isolated worker fills missing
IPFire ASN/network-name context in batches of at most500 addresses/minute, eight
questions concurrently, at most500 deduplicated ASN-name questions and a30s
whole-batch deadline. A resolver TTL cache and durable per-occurrence attempts
retain successful/negative results and15m failure backoff across restart. Active
complete IPFire entries and page views do not query Cymru; new occurrences become
eligible after the ordinary cooldown. Optional capability defaults false.

Only the metadata worker initializes the supplemental table in its separate
cache; no core storage/profile changes. The ordinary image has no DNS dependency.
Readers retain their existing snapshot/display limits, validate optional data
and preserve good IPFire context if a supplement is malformed. Primary IPFire
values win; conflicting-ASN names cannot merge. Lists and IP/action cards expose
Cymru attribution, multiple origins, source/time and separate registration
country from geography. Provider failures retain labelled last-known data.

Validation: full Python3959 passed691.12s; final affected99 passed1.57s includes
three later-added edge cases. Browser/Node110 passed167.14s, including mobile IP/
action frames, escaped names, country separation and unchanged action requests.
Ruff/compileall/JS/diff pass. Candidate installed package/source/footer/all43
templates/66 routes and actual readonly API/cache preflight pass; ordinary image
has no dnspython. No second full run including the three late cases claimed.

Real DNS probes for8.8.8.8/1.1.1.1 returned validated routing context. A temporary
copy of the actual cache filled exactly two missing IPs (2.38.150.66/4.4.242.26),
with unchanged primary IPFire values and repeated-read state; immediate subsequent
refresh/reconstructed supplement correctly did no work. Original metadata was
mounted readonly, and the copy was never applied to the live cache.

Candidate app image:
`sha256:208c23580f07a33dbdbf21d5678b047bd56081788a561b848dae7b54e76e9765`;
worker:
`sha256:30786f1d6e82e8775d39ab3f533df3a2553f6aeed962fcc1f76b893f7ef1e2a0`;
source/build `b4e13249d625`.

Automatic approval review rejected the proposed persistent `.env` enable flag
and metadata-only Web/worker rollout: existing instructions retained Cymru as
planned and required approval for activation/ongoing external DNS queries.
The rejected command did not execute; an explicit approval question is pending.
Do not bypass that decision. No live flag/table/backfill, service replacement,
FTD command or core/authority/secret/trust/network configuration change occurred.
All captured service image/container/start identities, nine core fingerprints,
all26 unknowns and primary cache hash remain unchanged; integrityok. Live cache:
32426 entries,29045 ready/3380 missing/one skipped,3383 eligible routing gaps.
Main remains Web0.10.1/API0.2.0/agentv6/worker0.9.0. Rollback image tags preserved:
`ftd-shun-web:lab-pre-cymru-20261112`,
`ftd-shun-ip-context-location:lab-pre-cymru-20261112`.
Private evidence: `/tmp/ftd-cymru-20261112`. Persistent activation, live backfill/
restart acceptance and actual authenticated UI acceptance are not claimed.

## 2026-11-12 — operator-approved v0.11.0 metadata deployment and backfill

The operator explicitly approved the pending Web/worker deployment and persistent
Team Cymru DNS supplementation. This resolves the earlier automatic-review
refusal for this exact lab scope. Enabled only `FTD_SHUN_CYMRU_ENABLED=true` in
private `.env` and replaced Web/metadata worker at17:45:12Z, retaining the tested
v0.11.0/source `b4e13249d625` images. No code/version change or new full test run
was needed. Previous3959 full/99 final affected/110 browser validation applies.

Web container `a93c99546b138b7a8ac7ca33ffb8d607a675d5ba82edbff866399f173dd606a2`,
image `sha256:208c23580f07a33dbdbf21d5678b047bd56081788a561b848dae7b54e76e9765`.
Worker container `3cc3ed3036122224b97a859b2a874c007a608a500524016366f28325934596bb`,
image `sha256:30786f1d6e82e8775d39ab3f533df3a2553f6aeed962fcc1f76b893f7ef1e2a0`.
Exact API/agent/feed images, containers and start times stayed unchanged. Existing
networks/mount isolation, core DB/import/seven receipts, trust and agent-only
credentials remain. Default tracked flag stays false. No shun ADD/REMOVE or
policy/control/recovery requests were submitted by this delivery.

Initial live backfill completed17:51:37Z:3383 eligible IPs attempted,3380 ready,
three not_mapped, zero failed/unattempted. Seven normal batches (six500/one383)
had persisted start intervals60/64/60/63/63/62 seconds. No acceleration or retry
override. Combined cached context is ready for32423 current observations; primary
IPFire data/hash is unchanged. Unmapped addresses are retained as genuine missing
provider information, with normal scheduled refresh, not invented geography.

A controlled worker-only stop at17:48:01Z exited0 after1500 completed entries.
Restart retained all1500 rows/attempt IDs/times and the exact original next-batch
deadline; no immediate repeat. Normal scheduled work resumed. Live Web health200,
ten anonymous routes401, all six asset hashes, installed package/build/footer and
actual cached Cymru card/source/registration-country rendering pass. Three repeated
readonly renders kept the original provider attempt. Ordinary Web has no DNS
dependency. No authenticated live-browser acceptance is claimed.

Immediately after rollout, core integrity/all nine fingerprints/all26 unknowns
matched. At the final17:52:33Z sample, integrity/seven other fingerprints/all26
unknowns still match; protected-policy/IP fingerprints changed. Readonly audit
identifies two PROTECTED_IP_UPDATED events from the authenticated operator at
17:48:13.436Z/17:52:12.258Z, current policy revision3. These concurrent operator
edits were preserved, not attributed to metadata or reverted. Original executor
3917 was IDLE at that sample. The primary metadata fingerprint remains unchanged.

Private rollout/restart/cadence/audit evidence: `/tmp/ftd-cymru-20261112`.
Rollback image tags remain `ftd-shun-web:lab-pre-cymru-20261112` and
`ftd-shun-ip-context-location:lab-pre-cymru-20261112`; disable only the worker flag
to stop future queries, retain cache/core data. Reload old tabs for current footer/
templates. This is known-desk-lab acceptance, not production or load certification.

## Adding future entries

Append a new entry for every material code, security, deployment, schema, protocol, authentication, or operational change. State what changed, what was verified, and what remains risky or incomplete. Update [`project-status.md`](project-status.md) in the same change.

