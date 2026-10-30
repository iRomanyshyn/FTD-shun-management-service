from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.config import Settings, _ipv4_csv, _retention_days


def test_trusted_auto_remove_ips_accepts_exact_ipv4_addresses() -> None:
    assert _ipv4_csv("198.51.100.10, 203.0.113.11") == frozenset(
        {IPv4Address("198.51.100.10"), IPv4Address("203.0.113.11")}
    )


@pytest.mark.parametrize("value", ["198.51.100.0/24", "2001:db8::1", "198.51.100.10,"])
def test_trusted_auto_remove_ips_rejects_non_exact_ipv4_values(value: str) -> None:
    with pytest.raises(ValueError, match="FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS"):
        _ipv4_csv(value)


@pytest.mark.parametrize("value", ["0", "366.5", "3654"])
def test_history_retention_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="FTD_SHUN_HISTORY_RETENTION_DAYS"):
        _retention_days(value)


def test_api_runtime_is_legacy_unless_explicitly_selected(monkeypatch):
    monkeypatch.delenv('FTD_SHUN_API_RUNTIME', raising=False)
    monkeypatch.delenv('FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES', raising=False)
    assert Settings.from_environment().api_runtime == 'legacy'
    assert Settings.from_environment().agent_concurrency == 1
    monkeypatch.setenv('FTD_SHUN_API_RUNTIME', 'continuous-observation')
    monkeypatch.setenv('FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES', '4')
    assert Settings.from_environment().api_runtime == 'continuous-observation'
    assert Settings.from_environment().agent_concurrency == 4


@pytest.mark.parametrize('value', ['', 'continuous', 'mock', 'LEGACY', ' legacy'])
def test_unknown_runtime_never_silently_uses_legacy(monkeypatch, value):
    monkeypatch.setenv('FTD_SHUN_API_RUNTIME', value)
    with pytest.raises(ValueError, match='API_RUNTIME'): Settings.from_environment()


@pytest.mark.parametrize('value', ['', '0', '11', '+2', '02', '2.0', ' 2', 'true'])
def test_declared_agent_capacity_uses_the_agent_canonical_integer_grammar(monkeypatch, value):
    monkeypatch.setenv('FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES', value)
    with pytest.raises(ValueError, match='MAX_CONCURRENT_DEVICES'): Settings.from_environment()
