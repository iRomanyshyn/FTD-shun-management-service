# Local Browser Laboratory

Use this workstation-only profile when internal DNS and organization-managed TLS
are not available yet. It keeps Caddy ForwardAuth and Authelia enabled; it does
not enable development headers, mock authentication, or a browser-to-API path.
The profile uses Caddy's local CA, so it must never replace the normal deployment
profile.

## 1. Set workstation-only names

On the Fedora host where the browser runs, use loopback names in the ignored
`.env` file:

```dotenv
PUBLISH_ADDRESS=127.0.0.1
FTD_SHUN_HOST=ftd-shun.lab.test
AUTH_HOST=auth.lab.test
AUTH_COOKIE_DOMAIN=lab.test
```

Keep the existing high-entropy `AUTHELIA_SESSION_SECRET` and
`AUTHELIA_STORAGE_ENCRYPTION_KEY`. If either is still an example value, replace
it before starting Authelia:

```bash
openssl rand -hex 32
```

Ask the workstation administrator to add this single line to `/etc/hosts` using
their normal privileged editor:

```text
127.0.0.1 ftd-shun.lab.test auth.lab.test
```

If the browser is on a different workstation, use the Compose host's approved
LAN address instead of `127.0.0.1` in both locations. Do not expose this
workstation profile beyond the controlled lab.

## 2. Create the local Authelia user

Create the ignored user file once:

```bash
cp deploy/authelia/users.example.yml deploy/authelia/users.yml
chmod 600 deploy/authelia/users.yml
docker run --rm -it authelia/authelia:4.39.15 \
  authelia crypto hash generate argon2
```

The final command prompts for the password, so it does not place it in shell
history. Copy only the resulting `Digest:` value into the `password` field for
`operator` in `deploy/authelia/users.yml`. Retain the
`ftd-shun-operators` group. The user file contains a password hash and remains
untracked. Ensure `.env` has the numeric owner of this file (usually `1000` on
a single-user Fedora workstation):

```bash
id -u
id -g
```

Set the two resulting values as `FTD_SHUN_AUTHELIA_UID` and
`FTD_SHUN_AUTHELIA_GID` in `.env`.

## 3. Start the local-lab profile

Validate the merged configuration, then start it:

```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml config
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml up -d --build
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml ps
```

## 4. Trust the local Caddy CA on Fedora

After Caddy starts, copy its public root certificate into Fedora's system trust
store and refresh trust. The certificate is public; never copy application
secrets from the containers.

```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml \
  cp caddy:/data/caddy/pki/authorities/local/root.crt /tmp/ftd-shun-local-lab-root.crt
sudo install -m 0644 /tmp/ftd-shun-local-lab-root.crt \
  /etc/pki/ca-trust/source/anchors/ftd-shun-local-lab-root.crt
sudo update-ca-trust
```

Restart the browser after refreshing the trust store, then open:

```text
https://ftd-shun.lab.test
```

Authelia should display its login page. Sign in as `operator`; the service page
should show the active shuns and the freshness state. If a browser reports a
certificate error after the trust step, inspect the Caddy logs and confirm the
hostnames and `/etc/hosts` entry exactly match the values in `.env`.

If Caddy returns `502`, inspect Authelia before changing any network settings:

```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml \
  logs --tail=100 authelia caddy
```

The Authelia service must report successful configuration loading. In this
stack the local file is read-only, so its password reset and password change
screens are deliberately unavailable.

## Return to normal deployment settings

Stop the local-lab stack with the same two Compose files. Restore the normal
internal DNS names and publish address in `.env`, then start using only
`deploy/compose.yml`. Do not use `compose.local-lab.yml` in a shared or
production environment.
