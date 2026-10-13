# Development Manual

## Prerequisites

- Python 3.12+
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

- `mock` accepts only the typed `REMOVE_SHUN` operation; it never opens an SSH connection.
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

Do not use `mock` to validate Cisco behavior. Parser fixtures and the eventual privileged agent require recorded, sanitized device output.
