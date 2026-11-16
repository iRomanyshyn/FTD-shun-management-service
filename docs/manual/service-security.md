# Service environment and browser security

Keep one private project `.env` for deployment configuration. Compose interpolates
explicit per-service `environment` entries; it does not pass that file wholesale
to containers. An unlisted variable is not automatically available inside a
service. Add new settings to the appropriate service mapping when implementing
them, and check optional overlays as well as the base composition.

| Service | Configuration boundary |
| --- | --- |
| Caddy | Public application and sign-in hostnames only. |
| Authelia | Public authentication settings and its own session/storage secrets. |
| Web | Public runtime settings, sign-in hostname and internal socket paths. No authentication-service secrets or SSH credentials. |
| API | Public execution settings, database/inventory/socket paths and environment IP protection. No authentication-service secrets or SSH credentials. |
| Agent | SSH identity/agent-only credential files, inventory, execution settings and environment IP protection. No authentication-service secrets. |
| Observation feed | Its existing read-only source/socket configuration. |
| Metadata worker | Its existing provider/cache configuration; no core database or device credentials. |

API and Web share public profile settings because both validate compatible
execution modes. This does not grant Web execution authority. The API publishes
read-only environment protection information for Web rendering; the agent also
enforces the configured ranges independently. The optional journal directory
remains absent unless explicitly configured; per-device credentials remain an
opt-in agent-only overlay.

## Browser policy

Web and the application Caddy site serve a Content Security Policy with same-origin
scripts, styles and fetches, no inline execution, no plugins and no embedding in
iframes. Native IP/action dialogs remain supported. Forms may return to the exact
configured HTTPS authentication origin when a session expires. New frontend assets
should be local files; do not relax the policy to add inline scripts or styles.

Responses also disable MIME sniffing, framing, camera, microphone and geolocation
access. Referrers stay on the same origin. Caddy's application error route retains
these headers and the original HTTP error status without displaying upstream
connection details. Authentication pages retain Authelia's own CSP; the application
CSP must not be imposed on them.

HSTS belongs at Caddy's HTTPS boundary: one year in the production example and
one day for the private-CA lab. Neither example enables preload or covers sibling
subdomains. Keep the existing CA and trust configuration when updating; HSTS is
not a replacement for installing/verifying the correct certificate authority.

## Updating an existing lab

Recreate services that previously used the common `env_file`: editing YAML or
reloading Caddy alone cannot remove variables from an existing container. Preserve
secret values, volumes, credentials, certificates, inventory, execution profile and
policy. Restarting Authelia with its current in-memory session backend may require
users to sign in again. A Web/API restart follows ordinary executor drain rules;
this change does not initialize storage or enable deferred execution.

Verify actual container environment **names**, plus private value comparisons for
settings that must remain unchanged. Do not print resolved Compose output or Docker
environment values into public logs: they can contain secrets. Check application
and sign-in HTTPS responses separately, including redirects and upstream failures.
Browser regression fixtures enforce the same application CSP.
