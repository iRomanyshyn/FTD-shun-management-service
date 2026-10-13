from ftd_shun_manager.api import create_app as create_api
from ftd_shun_manager.config import Settings
from ftd_shun_manager.web import create_app as create_web


def test_apps_create_with_safe_defaults(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        device_inventory_path=None,
        agent_socket=str(tmp_path / "agent.sock"),
        web_socket=str(tmp_path / "web.sock"),
        api_socket=str(tmp_path / "api.sock"),
        agent_mode="disabled",
        sensitive_action_max_age_seconds=86400,
        development_auth=False,
    )
    assert create_api(settings).title == "FTD Shun Internal API"
    assert create_web(settings).title == "FTD Shun Manager"
