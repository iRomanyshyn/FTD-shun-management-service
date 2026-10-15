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

## Adding future entries

Append a new entry for every material code, security, deployment, schema, protocol, authentication, or operational change. State what changed, what was verified, and what remains risky or incomplete. Update [`project-status.md`](project-status.md) in the same change.

