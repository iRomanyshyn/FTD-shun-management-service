import asyncio
from ipaddress import IPv4Address

from ftd_shun_manager.api import create_app as create_api
from ftd_shun_manager.config import Settings
from ftd_shun_manager.web import api_client
from ftd_shun_manager.web import create_app as create_web


def test_apps_create_with_safe_defaults(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        device_inventory_path=None,
        agent_socket=str(tmp_path / "agent.sock"),
        web_socket=str(tmp_path / "web.sock"),
        api_socket=str(tmp_path / "api.sock"),
        agent_mode="disabled",
        agent_timeout_seconds=45,
        poll_interval_seconds=300,
        interactive_refresh_min_interval_seconds=60,
        history_retention_days=366,
        sensitive_action_max_age_seconds=86400,
        development_auth=False,
        trusted_auto_remove_ips=frozenset(),
    )
    assert create_api(settings).title == "FTD Shun Internal API"
    assert create_web(settings).title == "FTD Shun Manager"


def test_bff_waits_beyond_the_agent_operation_timeout(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        device_inventory_path=None,
        agent_socket=str(tmp_path / "agent.sock"),
        web_socket=str(tmp_path / "web.sock"),
        api_socket=str(tmp_path / "api.sock"),
        agent_mode="socket",
        agent_timeout_seconds=45,
        poll_interval_seconds=300,
        interactive_refresh_min_interval_seconds=60,
        history_retention_days=366,
        sensitive_action_max_age_seconds=86400,
        development_auth=False,
        trusted_auto_remove_ips=frozenset(),
    )
    with api_client(settings) as client:
        assert client.timeout.read == 55


def test_status_exposes_configured_trusted_ips_without_a_removal_timestamp(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        device_inventory_path=None,
        agent_socket=str(tmp_path / "agent.sock"),
        web_socket=str(tmp_path / "web.sock"),
        api_socket=str(tmp_path / "api.sock"),
        agent_mode="disabled",
        agent_timeout_seconds=45,
        poll_interval_seconds=300,
        interactive_refresh_min_interval_seconds=60,
        history_retention_days=366,
        sensitive_action_max_age_seconds=86400,
        development_auth=False,
        trusted_auto_remove_ips=frozenset({IPv4Address("198.51.100.10")}),
    )

    app = create_api(settings)
    status_route = next(route for route in app.routes if route.path == "/api/v1/status")
    status = status_route.endpoint()

    assert status["trusted_auto_remove_ips"] == [
        {"ip": "198.51.100.10", "last_auto_removed_at": None}
    ]


def test_refresh_hint_returns_the_queued_state_immediately(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        device_inventory_path=None,
        agent_socket=str(tmp_path / "agent.sock"),
        web_socket=str(tmp_path / "web.sock"),
        api_socket=str(tmp_path / "api.sock"),
        agent_mode="disabled",
        agent_timeout_seconds=45,
        poll_interval_seconds=300,
        interactive_refresh_min_interval_seconds=60,
        history_retention_days=366,
        sensitive_action_max_age_seconds=86400,
        development_auth=False,
        trusted_auto_remove_ips=frozenset(),
    )

    app = create_api(settings)
    refresh_route = next(route for route in app.routes if route.path == "/api/v1/refresh-hint")
    response = asyncio.run(refresh_route.endpoint())

    assert response["status"] == "queued"
    assert response["refresh"]["interactive_refresh_state"] == "queued"
