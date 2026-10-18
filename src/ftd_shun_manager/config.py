"""Configuration loaded from the process environment.

Deployment tooling may load a protected .env file, but this module never reads it
itself. That keeps secret handling outside application code.
"""

from dataclasses import dataclass
from ipaddress import IPv4Address
from os import environ
from pathlib import Path


def _duration(value: str) -> int:
    """Return seconds for an explicit whole-number seconds/minutes/hours grammar."""
    units = {"s": 1, "m": 60, "h": 3600}
    if len(value) >= 2 and value[-1] in units and value[:-1].isdigit():
        return int(value[:-1]) * units[value[-1]]
    raise ValueError("duration must use whole seconds, minutes, or hours, for example 60s, 5m, or 1h")


def _ipv4_csv(value: str) -> frozenset[IPv4Address]:
    """Legacy import parser only; runtime policy is owned by SQLite."""
    if not value.strip():
        return frozenset()
    values = [entry.strip() for entry in value.split(",")]
    if not all(values):
        raise ValueError("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS must be a comma-separated list of IPv4 addresses")
    try:
        return frozenset(IPv4Address(entry) for entry in values)
    except ValueError as error:
        raise ValueError("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS must contain only IPv4 addresses") from error


def _retention_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as error:
        raise ValueError("FTD_SHUN_HISTORY_RETENTION_DAYS must be a whole number") from error
    if not 1 <= days <= 3653:
        raise ValueError("FTD_SHUN_HISTORY_RETENTION_DAYS must be between 1 and 3653")
    return days


@dataclass(frozen=True)
class Settings:
    database_path: Path
    device_inventory_path: Path | None
    agent_socket: str
    web_socket: str
    api_socket: str
    agent_mode: str
    agent_timeout_seconds: int
    poll_interval_seconds: int
    interactive_refresh_min_interval_seconds: int
    history_retention_days: int
    sensitive_action_max_age_seconds: int
    development_auth: bool
    agent_cycles_enabled: bool = False
    large_snapshots_enabled: bool = False
    import_admission_enabled: bool = False
    import_execution_enabled: bool = False
    managed_removal_worker_enabled: bool = False
    managed_restoration_enabled: bool = False
    managed_policy_admission_enabled: bool = False
    managed_removal_admission_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.managed_removal_admission_enabled) is not bool:
            raise ValueError("managed removal admission setting must be boolean")
        if self.managed_removal_admission_enabled and (
            self.agent_mode != "socket" or self.managed_removal_worker_enabled is not True
        ):
            raise ValueError("managed removal admission requires socket mode and the cleanup worker")
        if type(self.managed_policy_admission_enabled) is not bool:
            raise ValueError("managed policy admission setting must be boolean")
        if self.managed_policy_admission_enabled and self.agent_mode != "socket":
            raise ValueError("managed policy admission requires socket agent mode")
        if type(self.managed_restoration_enabled) is not bool:
            raise ValueError("managed restoration setting must be boolean")
        if self.managed_restoration_enabled and not self.import_execution_enabled:
            raise ValueError("managed restoration requires the API ADD execution gate")
        if self.managed_removal_worker_enabled and self.agent_mode != "socket":
            raise ValueError("managed removal worker requires socket agent mode")
        if self.import_execution_enabled and (
            self.agent_mode != "socket" or not self.agent_cycles_enabled or not self.large_snapshots_enabled
        ):
            raise ValueError("import execution requires socket agent mode, session cycles and large snapshots")

    @classmethod
    def from_environment(cls) -> "Settings":
        cycles = environ.get("FTD_SHUN_AGENT_CYCLES_ENABLED", "false")
        if cycles not in {"true", "false"}:
            raise ValueError("FTD_SHUN_AGENT_CYCLES_ENABLED must be true or false")
        large_snapshots = environ.get("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED", "false")
        if large_snapshots not in {"true", "false"}:
            raise ValueError("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED must be true or false")
        import_admission = environ.get("FTD_SHUN_IMPORT_ADMISSION_ENABLED", "false")
        if import_admission not in {"true", "false"}:
            raise ValueError("FTD_SHUN_IMPORT_ADMISSION_ENABLED must be true or false")
        agent_mode = environ.get("FTD_SHUN_AGENT_MODE", "disabled")
        if agent_mode not in {"disabled", "mock", "socket"}:
            raise ValueError("FTD_SHUN_AGENT_MODE must be disabled, mock, or socket")
        import_execution = environ.get("FTD_SHUN_IMPORT_EXECUTION_ENABLED", "false")
        if import_execution not in {"true", "false"}:
            raise ValueError("FTD_SHUN_IMPORT_EXECUTION_ENABLED must be true or false")
        managed_worker = environ.get("FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED", "false")
        if managed_worker not in {"true", "false"}:
            raise ValueError("FTD_SHUN_MANAGED_REMOVAL_WORKER_ENABLED must be true or false")
        restoration = environ.get("FTD_SHUN_MANAGED_RESTORATION_ENABLED", "false")
        if restoration not in {"true", "false"}:
            raise ValueError("FTD_SHUN_MANAGED_RESTORATION_ENABLED must be true or false")
        managed_admission = environ.get("FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED", "false")
        if managed_admission not in {"true", "false"}:
            raise ValueError("FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED must be true or false")
        removal_admission = environ.get("FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED", "false")
        if removal_admission not in {"true", "false"}:
            raise ValueError("FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED must be true or false")
        agent_timeout_seconds = int(environ.get("FTD_SHUN_AGENT_TIMEOUT_SECONDS", "45"))
        if not 5 <= agent_timeout_seconds <= 120:
            raise ValueError("FTD_SHUN_AGENT_TIMEOUT_SECONDS must be between 5 and 120")
        poll_interval_seconds = _duration(environ.get("FTD_SHUN_POLL_INTERVAL", "5m"))
        if not 60 <= poll_interval_seconds <= 24 * 3600:
            raise ValueError("FTD_SHUN_POLL_INTERVAL must be between 60s and 24h")
        interactive_refresh_min_interval_seconds = _duration(
            environ.get("FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL", "60s")
        )
        if interactive_refresh_min_interval_seconds < 60:
            raise ValueError("FTD_SHUN_INTERACTIVE_REFRESH_MIN_INTERVAL must be at least 60s")
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
            agent_timeout_seconds=agent_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            interactive_refresh_min_interval_seconds=interactive_refresh_min_interval_seconds,
            history_retention_days=_retention_days(
                environ.get("FTD_SHUN_HISTORY_RETENTION_DAYS", "366")
            ),
            sensitive_action_max_age_seconds=_duration(
                environ.get("AUTH_SENSITIVE_ACTION_MAX_AGE", "24h")
            ),
            development_auth=environ.get("FTD_SHUN_DEVELOPMENT_AUTH", "false").lower()
            == "true",
            agent_cycles_enabled=cycles == "true",
            large_snapshots_enabled=large_snapshots == "true",
            import_admission_enabled=import_admission == "true",
            import_execution_enabled=import_execution == "true",
            managed_removal_worker_enabled=managed_worker == "true",
            managed_restoration_enabled=restoration == "true",
            managed_policy_admission_enabled=managed_admission == "true",
            managed_removal_admission_enabled=removal_admission == "true",
        )
