# Deployment Manual

## Scope and current boundary

The Compose stack deploys Caddy, Authelia, Web/BFF, the internal API, and the isolated Rust FTD SSH agent. The agent currently implements only device-scoped removal with immediate post-write verification; polling and reconciliation remain unavailable. Keep the deployment in a non-production FTD lab until the validation checklist below is complete.

## Network and socket layout

```text
host TCP/443 -> Caddy -> Authelia (ForwardAuth)
                      -> Web/BFF UDS -> API UDS -> agent UDS -> FTD TCP/22
```

Only Caddy publishes a host port. Web and API use `network_mode: none`; the API has no Cisco network route. The agent is the sole service on the `ftd-management` network and must be restricted by host/network firewall policy to configured FTD management addresses on TCP/22. The `socket-init` one-shot container creates the three named socket volumes; the agent socket is writable only by the agent and its API group.

## Prepare protected configuration

```bash
cp .env.example .env
cp deploy/authelia/users.example.yml deploy/authelia/users.yml
cp deploy/devices.example.json deploy/devices.json
install -d -m 700 deploy/secrets
# Supply the approved service-account private key through the protected secret file.
install -m 600 /approved/key/path deploy/secrets/ftd_ssh_private_key
chmod 600 .env deploy/authelia/users.yml deploy/devices.json
```

Set the following values in `.env` before deployment:

- `PUBLISH_ADDRESS`: the approved internal server IPv4 address.
- `FTD_SHUN_HOST` and `AUTH_HOST`: distinct internal DNS names.
- `AUTH_COOKIE_DOMAIN`: common parent domain, for example `internal.example`.
- `AUTHELIA_SESSION_SECRET` and `AUTHELIA_STORAGE_ENCRYPTION_KEY`: independently generated high-entropy values.
- `AUTH_SENSITIVE_ACTION_MAX_AGE`: normally `24h`; set `1h` for tighter operator sessions.

Generate Authelia password hashes with the official Authelia tooling and replace the example hash. Never put a clear-text password in `users.yml`.

Replace the device example's hostname, management IPv4 address, SSH host key, and `allowed_interfaces` with values collected through an approved out-of-band process. `allowed_interfaces` must list every interface that the agent may remove from; the agent rejects an FTD-reported interface outside this list. The API rejects duplicate IDs/hostnames, invalid IPv4 addresses, a missing host key, and malformed interface names at startup.

Set `FTD_SHUN_SSH_USERNAME` in `.env` to the dedicated FTD service account. Configure that account and each FTD management ACL with the minimum permitted commands and this host's approved source address. The agent reads the private key from the Compose secret at operation time, zeroizes the encoded source buffer after decoding, and keeps no persistent writable volume. Never commit or back up `deploy/secrets/`.

## TLS and Caddy

The supplied Caddyfile assumes organization-controlled TLS is available for both hostnames. Before deployment, configure the certificate source appropriate for the organization and test the configuration. Do not expose either host to the public Internet.

Caddy must preserve the supplied `forward_auth` route and must not pass client-provided `Remote-*` identity headers to Web/BFF. Review this on every Caddy change.

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
- removal succeeds only for a lab shun on an allowlisted interface, then a direct FTD `show shun <IPv4>` confirms it is absent;
- a changed host key, unknown interface, malformed response, agent timeout, or unavailable agent causes a failed write and never an audit success.

## LDAP(S) migration

Authelia has one first-factor backend. To migrate, replace the `authentication_backend.file` block with its documented LDAP(S) configuration, map directory groups to the three FTD groups, install the directory CA, and validate certificate verification. Do not configure `skip_verify`.
