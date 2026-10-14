from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.config import _ipv4_csv


def test_trusted_auto_remove_ips_accepts_exact_ipv4_addresses() -> None:
    assert _ipv4_csv("198.51.100.10, 203.0.113.11") == frozenset(
        {IPv4Address("198.51.100.10"), IPv4Address("203.0.113.11")}
    )


@pytest.mark.parametrize("value", ["198.51.100.0/24", "2001:db8::1", "198.51.100.10,"])
def test_trusted_auto_remove_ips_rejects_non_exact_ipv4_values(value: str) -> None:
    with pytest.raises(ValueError, match="FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS"):
        _ipv4_csv(value)
