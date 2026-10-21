"""Credential config is agent-owned and never packaged into an application image."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", [".gitignore", ".dockerignore"])
def test_real_credentials_are_excluded_but_sanitized_example_is_available(filename):
    rules = (ROOT / filename).read_text().splitlines()
    assert "deploy/agent-credentials.json" in rules
    assert any(rule.rstrip("/") == "deploy/secrets" for rule in rules)
    assert "deploy/agent-credentials.example.json" not in rules


def test_opt_in_overlay_changes_only_agent_and_removes_legacy_secret():
    overlay = (ROOT / "deploy/compose.per-device-credentials.yml").read_text()
    assert [line for line in overlay.splitlines() if line.startswith("  ") and not line.startswith("   ")] == ["  agent:"]
    assert "secrets: !reset []" in overlay
    assert "FTD_SHUN_SSH_CREDENTIALS_MODE: per-device" in overlay
    assert 'FTD_SHUN_SSH_USERNAME: ""' in overlay
    assert 'FTD_SHUN_SSH_PASSWORD_FILE: ""' in overlay
    assert overlay.count("read_only: true") == 2
    assert overlay.count("create_host_path: false") == 2
