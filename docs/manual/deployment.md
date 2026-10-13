# Deployment Manual

## Scope and current boundary

The Compose stack deploys Caddy, Authelia, Web/BFF, and the internal API. It does **not** deploy a production FTD SSH agent yet. With `FTD_SHUN_AGENT_MODE=socket`, every write fails closed until the agent Unix socket is supplied. This is intentional.

## Network and socket layout

```text
host TCP/443 -> Caddy -> Authelia (ForwardAuth)
                      -> Web/BFF UDS -> API UDS -> agent UDS
```

Only Caddy publishes a host port. Web and API use `network_mode: none`; the API has no Cisco network route. The `socket-init` one-shot container owns only creation and permission setup of the three named socket volumes.

## Prepare protected configuration

```bash
cp .env.example .env
cp deploy/authelia/users.example.yml deploy/authelia/users.yml
cp deploy/devices.example.json deploy/devices.json
chmod 600 .env deploy/authelia/users.yml deploy/devices.json
```

Set the following values in `.env` before deployment:

- `PUBLISH_ADDRESS`: the approved internal server IPv4 address.
- `FTD_SHUN_HOST` and `AUTH_HOST`: distinct internal DNS names.
- `AUTH_COOKIE_DOMAIN`: common parent domain, for example `internal.example`.
- `AUTHELIA_SESSION_SECRET` and `AUTHELIA_STORAGE_ENCRYPTION_KEY`: independently generated high-entropy values.
- `AUTH_SENSITIVE_ACTION_MAX_AGE`: normally `24h`; set `1h` for tighter operator sessions.

Generate Authelia password hashes with the official Authelia tooling and replace the example hash. Never put a clear-text password in `users.yml`.

Replace the device example's hostname, management IPv4 address, and SSH host key with the pinned key collected through an approved out-of-band process. The API rejects duplicate IDs/hostnames, invalid IPv4 addresses, and a missing host key at startup.

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
- removal returns an unavailable error until the FTD SSH agent is added.

## LDAP(S) migration

Authelia has one first-factor backend. To migrate, replace the `authentication_backend.file` block with its documented LDAP(S) configuration, map directory groups to the three FTD groups, install the directory CA, and validate certificate verification. Do not configure `skip_verify`.
