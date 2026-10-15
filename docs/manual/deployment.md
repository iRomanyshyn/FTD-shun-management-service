# Deployment Manual

## Scope and current boundary

The Compose stack deploys Caddy, Authelia, Web/BFF, the internal API, and the isolated Rust FTD SSH agent. The agent implements typed complete `show shun` snapshots, five-minute polling by default, SQLite reconciliation, and device-scoped removal with immediate post-write verification. Keep the deployment in a non-production FTD lab until the validation checklist below is complete.

## Network and socket layout

```text
host TCP/443 -> Caddy -> Authelia (ForwardAuth)
                      -> Web/BFF UDS -> API UDS -> agent UDS -> FTD TCP/22
```

Only Caddy publishes a host port. Web and API use `network_mode: none`; the API has no Cisco network route. The agent is the sole service on the `ftd-management` network and must be restricted by host/network firewall policy to configured FTD management addresses on TCP/22. The `socket-init` one-shot container prepares the three named socket volumes and the SQLite state volume; the agent socket is writable only by the agent and its API group.

Before the first agent request, validate that the host firewall/NAT policy permits the agent bridge to reach each approved FTD management address on TCP/22 and denies other destinations and ports. This policy is especially required when the FTD route uses a VPN interface: host SSH reachability does not establish that a Docker bridge has the same routed and masqueraded path. Do not relax the agent timeout, pinned host key, or FTD source ACL to work around a missing host egress rule.

## Prepare protected configuration

```bash
cp .env.example .env
cp deploy/authelia/users.example.yml deploy/authelia/users.yml
cp deploy/devices.example.json deploy/devices.json
install -d -m 700 deploy/secrets
# Supply the approved service-account SSH password through the protected secret file.
install -m 600 /approved/password/path deploy/secrets/ftd_ssh_password
# Docker Compose bind-mounts file secrets without changing their identity. Grant
# read-only access only to the agent's numeric container UID, not to a broad group.
setfacl -m u:10002:r-- deploy/secrets/ftd_ssh_password
chmod 600 .env deploy/authelia/users.yml deploy/devices.json
```

Set the following values in `.env` before deployment:

- `PUBLISH_ADDRESS`: the approved internal server IPv4 address.
- `FTD_SHUN_HOST` and `AUTH_HOST`: distinct internal DNS names.
- `AUTH_COOKIE_DOMAIN`: common parent domain, for example `internal.example`.
- `AUTHELIA_SESSION_SECRET` and `AUTHELIA_STORAGE_ENCRYPTION_KEY`: independently generated high-entropy values.
- `FTD_SHUN_AUTHELIA_UID` and `FTD_SHUN_AUTHELIA_GID`: the numeric owner of
  `deploy/authelia/users.yml` (obtain them with `id -u` and `id -g`).
- `AUTH_SENSITIVE_ACTION_MAX_AGE`: normally `24h`; set `1h` for tighter operator sessions.

Generate Authelia password hashes with the official Authelia tooling and replace the example hash. Never put a clear-text password in `users.yml`.

Replace the device example's hostname, management IPv4 address, SSH host key, and `allowed_interfaces` with values collected through an approved out-of-band process. `allowed_interfaces` must list every interface that the agent may remove from; the agent rejects an FTD-reported interface outside this list. The API rejects duplicate IDs/hostnames, invalid IPv4 addresses, a missing host key, and malformed interface names at startup.

Set `FTD_SHUN_SSH_USERNAME` in `.env` to the dedicated FTD service account. FTD exposes the broad `Basic` and `Config` CLI roles rather than a per-command allowlist. Use `Basic`; the supported Firepower 1010 / FTD 7.6.6 laboratory fixture has verified that it permits both `show shun` and `no shun <IPv4> interface <name>`. A `Config` account is prohibited by the normal deployment profile; a version-specific exception requires explicit security approval, updated validation evidence, and a recorded risk acceptance. In every case, restrict the FTD management SSH ACL to this host's approved source address.

The agent reads the SSH password from the Compose secret at operation time, zeroizes its source buffer after authentication, and keeps no persistent writable volume. Never commit or back up `deploy/secrets/`.

`FTD_SHUN_AGENT_TIMEOUT_SECONDS` is the agent's end-to-end timeout and must be between 5 and 120 seconds. The API waits for that value plus five seconds of local Unix-socket margin, so it cannot abandon a still-running agent operation first. The direct Python client uses a safe 125-second default for controlled laboratory checks.

The Web/BFF waits for the configured agent timeout plus ten seconds when it
submits a removal to the internal API. This exceeds the API margin, so the UI
does not report an error first while a bounded removal is still awaiting its
verified agent result. If the internal API is unavailable, the BFF returns a
controlled `503` and never claims removal success.

`FTD_SHUN_POLL_INTERVAL` controls complete snapshot collection and defaults to `5m`; valid values range from `60s` through `24h`. `FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL` defaults to `60s` and cannot be lower. An authenticated state page can only queue a non-blocking, globally rate-limited refresh hint; it never directly waits for FTD SSH output.

`FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS` is optional and empty by default. It accepts
only a comma-separated list of exact IPv4 addresses, for example
`198.51.100.10,203.0.113.11`. CIDRs, hostnames, ranges, and IPv6 make API
startup fail rather than widen the policy. This policy automatically requests
verified removal of a matching observed shun on every enabled device after a
successful complete snapshot. Enable it only after a lab validation with a
non-production address; changing it requires recreating the API service.

`FTD_SHUN_HISTORY_RETENTION_DAYS` defaults to `366` and accepts whole days
from `1` through `3653`. The API purges expired history and inactive state once
daily. Active shuns are never removed by this lifecycle task. Reducing the
value can permanently delete more local audit data on the next API sweep, so
take a SQLite-safe backup before recreating the API with a smaller value.

### Provision the FTD service-account password

Use the unique high-entropy password set while creating the dedicated `Basic` FTD service account. Obtain it from the approved secret store and write it into `deploy/secrets/ftd_ssh_password` with mode `0600`; never enter the password on a shell command line or commit it to Git. The `0600` file mode, isolated agent, FTD SSH source ACL, host egress policy, and short-lived sessions are mandatory compensating controls.

```bash
install -d -m 700 deploy/secrets
install -m 600 /approved/password/path deploy/secrets/ftd_ssh_password
setfacl -m u:10002:r-- deploy/secrets/ftd_ssh_password
```

Local Docker Compose implements a file secret as a read-only bind mount and does not remap the source file owner to the agent UID. On the supported Linux/rootful-Docker profile, the explicit ACL above grants only host UID `10002` read access, which is the agent process UID inside the container. Keep ordinary owner mode `0600`; do not make the secret group- or world-readable. Verify the effective ACL without displaying the password:

```bash
getfacl -p deploy/secrets/ftd_ssh_password
```

If the host uses rootless Docker or user namespaces, validate the mapped host UID first and grant the ACL to that mapped UID instead. This deployment profile is not validated until the agent can read the secret and complete the laboratory operation.

On the supported FPR1010 / FTD 7.6.6 profile, a `Basic` user cannot add a public key to its own account; the key-management command requires higher privilege. Do not promote the service account to `Config` merely to enable public-key authentication. Test password login from the Compose host using an already verified SSH server host key; if SSH asks to trust a new server key, stop and establish the FTD server-key fingerprint through the approved out-of-band process first.

```bash
ssh -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  ftd-shun-lab@<FTD-management-IP> 'show shun'
```

After independently verifying the FTD server key, extract the key type and base64 payload from the verified `known_hosts` entry and put those two fields, without the host field, into `ssh_host_key` in `deploy/devices.json`:

```bash
ssh-keygen -F <FTD-management-IP> | awk '!/^#/ {print $2, $3}'
```

Do not use `ssh-keyscan` as proof of server identity. It can collect a public key, but it does not authenticate the FTD that supplied it.

## TLS and Caddy

The supplied Caddyfile assumes organization-controlled TLS is available for both hostnames. Before deployment, configure the certificate source appropriate for the organization and test the configuration. Do not expose either host to the public Internet.

Caddy must preserve the supplied `forward_auth` route and must not pass client-provided `Remote-*` identity headers to Web/BFF. Review this on every Caddy change.
The request-header removal, ForwardAuth subrequest, and Web/BFF proxy must be
inside a Caddy `route` block in that exact order. Caddy normally reorders
directives; without `route`, it can remove the authenticated headers after
ForwardAuth has copied them.

Authelia's official image normally runs an entrypoint which recursively changes
ownership of `/config`. This stack bypasses that entrypoint and starts the
Authelia binary directly because its configuration and user database are
intentionally read-only mounts. The Authelia process runs as the configured
unprivileged `FTD_SHUN_AUTHELIA_UID:FTD_SHUN_AUTHELIA_GID`, so it can read its owner-only
`users.yml`. A separate networkless one-shot initializer, with only `CHOWN`,
prepares ownership of the Authelia SQLite volume. The main container retains
`read_only: true` and `cap_drop: [ALL]`; do not restore the image entrypoint,
make the user database world-readable, or grant capabilities to the main
Authelia process merely to make it start.

Authelia's optional in-image healthcheck metadata writer is disabled because it
writes below `/app`, which is part of the read-only root filesystem. This does
not alter Caddy ForwardAuth behavior; monitor the Authelia container's process
state and authenticated browser flow until an external health check is added.

The application image keeps its server-rendered templates and static files in
`/app`; its image-only `FTD_SHUN_ASSET_ROOT=/app` setting makes the installed
Web/BFF package locate those resources. Do not set this variable for a
source-tree development run, where the built-in source-tree path is used.

The stack also explicitly enables Authelia's configuration template filter for
the non-secret public names in `configuration.yml`. Its session and storage
secrets are not templates: `AUTHELIA_SESSION_SECRET` and
`AUTHELIA_STORAGE_ENCRYPTION_KEY` are read directly from the ignored
environment file. The local file authentication provider is read-only, so
self-service password reset and password change are disabled. When moving to
LDAP(S), review those identity-management flows and their required secrets
before enabling either feature.

For a workstation-only browser test without internal DNS or organization TLS,
use the separate [Local Browser Laboratory](local-lab-web.md) overlay. It uses
Caddy's private CA and Authelia's local file backend without weakening the
normal Caddy/ForwardAuth trust boundary. Never use that overlay for shared or
production deployment.

## Start and validate

```bash
docker compose -f deploy/compose.yml --env-file .env config
docker compose -f deploy/compose.yml --env-file .env up -d --build
docker compose -f deploy/compose.yml ps
```

Expected results:

- only `${PUBLISH_ADDRESS}:443` is published;
- Authelia prompts unauthenticated users;
- a member of `ftd-shun-viewers` has read-only access;
- `ftd-shun-operators` and `ftd-shun-administrators` can see removal actions;
- the agent process is healthy and its socket is owned by UID `10002`, group `10001`, mode `0660`;
- the API reports a successful initial snapshot and the UI shows its last-confirmed refresh, next baseline countdown, and a plain-language background-refresh status;
- the refresh controls show per-device freshness/errors and update state/history in place after revision changes, preserving search text and confirmation input; concurrent refresh hints join the same sweep;
- the primary page supports exact-IP/dotted-prefix local search across current state and retained history, clearly distinguishes historical-only results, and offers a countdown-backed **Request refresh** hint;
- the collapsed **Last events log** shows up to 100 recent local audit events;
- the UI reports the configured history-retention period (366 days by default);
- if configured, the UI reports the number of exact addresses covered by the trusted-IP automatic-removal policy; the policy's audit events are visible in history;
- if configured, the primary page lists each allowed address and its **Last auto-removed** timestamp (or `Never`); editing remains `.env`-only;
- removal succeeds only for a lab shun on an allowlisted interface, then a direct FTD `show shun <IPv4>` confirms it is absent;
- a changed host key, unknown interface, malformed response, agent timeout, or unavailable agent causes a failed write and never an audit success.

## LDAP(S) migration

Authelia has one first-factor backend. To migrate, replace the `authentication_backend.file` block with its documented LDAP(S) configuration, map directory groups to the three FTD groups, install the directory CA, and validate certificate verification. Do not configure `skip_verify`.
