# Development Manual

## Prerequisites

- Python 3.12+
- Rust 1.89+ for the privileged agent
- A virtual environment
- Docker Compose or Podman Compose only for container-level validation

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export FTD_SHUN_DATABASE="$PWD/.local/state.db"
export FTD_SHUN_API_SOCKET="/tmp/ftd-shun-api.sock"
export FTD_SHUN_WEB_SOCKET="/tmp/ftd-shun-web.sock"
export FTD_SHUN_AGENT_MODE=mock
export FTD_SHUN_DEVELOPMENT_AUTH=true
```

Start the internal API and BFF in separate terminals:

```bash
.venv/bin/ftd-shun-api
.venv/bin/ftd-shun-web
```

For local browser work, proxy the Web/BFF Unix socket with Caddy or use a test client that sends `X-Dev-User` and `X-Dev-Groups`. `FTD_SHUN_DEVELOPMENT_AUTH=true` is forbidden in deployed environments.

## Safety boundaries

- `mock` accepts the typed `LIST_SHUNS` and `REMOVE_SHUN` operations; it returns an empty snapshot and never opens an SSH connection.
- `disabled` is the safe default and returns an error for every removal attempt.
- `socket` is the only production mode. It requires an FTD agent on `FTD_SHUN_AGENT_SOCKET` to return the one-byte verified-success result.
- No test, fixture, route, or configuration field accepts Cisco CLI text.

## Checks

```bash
.venv/bin/python -m compileall src
.venv/bin/pytest
.venv/bin/ruff check .
docker compose -f deploy/compose.yml config
```

## Agent checks

```bash
cargo test --manifest-path agent/Cargo.toml
```

The agent test suite covers strict binary request decoding, the typed `LIST_SHUNS` response, and fail-closed parsing of `show shun` output. Do not use `mock` to validate Cisco behavior. The actual agent requires recorded, sanitized device output and a non-production FTD lab.

## Browser refresh regression checks

With Node.js 22+ (built-in WebSocket support), Chromium, and the Python package
available in the same environment, run:

```bash
node --test tests/browser/freshness.cjs
```

Set `CHROMIUM` to the Chromium executable if it is not `chromium-browser`.
The test uses the real repository templates and freshness JavaScript, an
ephemeral localhost server with synthetic status/state, and a temporary browser
profile. It requires local socket binding and Chromium's sandbox support; it
does not use Docker, `.env`, real authentication users, or FTD connectivity.
No npm installation is needed.

Scenarios cover a single manual request, a slow in-flight status response,
multiple tabs, imminent-baseline display, repeated identical failures, API
restart, status/network recovery, failed POST/retry, and preservation of search
text, expanded history, confirmation values, and focus during partial updates.
Python tests separately exercise the real scheduler's slow-cycle coalescing,
partial fleet success, detached revisions, and BFF authentication/CSRF/no-store
boundaries. The browser fixture is not evidence of live FTD or Authelia
compatibility; that remains an integration/laboratory check.
