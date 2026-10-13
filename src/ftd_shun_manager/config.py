"""Configuration loaded from the process environment.

Deployment tooling may load a protected .env file, but this module never reads it
itself. That keeps secret handling outside application code.
"""

from dataclasses import dataclass
from os import environ
from pathlib import Path


def _duration(value: str) -> int:
    """Return a duration in seconds for a small, explicit duration grammar."""
    if value.endswith("h") and value[:-1].isdigit():
        return int(value[:-1]) * 3600
    if value.endswith("m") and value[:-1].isdigit():
        return int(value[:-1]) * 60
    raise ValueError("duration must use whole minutes or hours, for example 1h or 30m")


@dataclass(frozen=True)
class Settings:
    database_path: Path
    device_inventory_path: Path | None
    agent_socket: str
    web_socket: str
    api_socket: str
    agent_mode: str
    sensitive_action_max_age_seconds: int
    development_auth: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        agent_mode = environ.get("FTD_SHUN_AGENT_MODE", "disabled")
        if agent_mode not in {"disabled", "mock", "socket"}:
            raise ValueError("FTD_SHUN_AGENT_MODE must be disabled, mock, or socket")
        return cls(
            database_path=Path(environ.get("FTD_SHUN_DATABASE", "/var/lib/ftd-shun-manager/state.db")),
            device_inventory_path=(
                Path(environ["FTD_SHUN_DEVICE_INVENTORY"])
                if environ.get("FTD_SHUN_DEVICE_INVENTORY")
                else None
            ),
            agent_socket=environ.get("FTD_SHUN_AGENT_SOCKET", "/run/ftd-shun-manager/agent.sock"),
            web_socket=environ.get("FTD_SHUN_WEB_SOCKET", "/run/ftd-shun-manager/web.sock"),
            api_socket=environ.get("FTD_SHUN_API_SOCKET", "/run/ftd-shun-manager/api.sock"),
            agent_mode=agent_mode,
            sensitive_action_max_age_seconds=_duration(
                environ.get("AUTH_SENSITIVE_ACTION_MAX_AGE", "24h")
            ),
            development_auth=environ.get("FTD_SHUN_DEVELOPMENT_AUTH", "false").lower()
            == "true",
        )
