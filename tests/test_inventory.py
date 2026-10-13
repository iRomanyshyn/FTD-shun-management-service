import json

import pytest

from ftd_shun_manager.inventory import load_devices


def test_inventory_requires_safe_unique_interface_allowlist(tmp_path) -> None:
    inventory = tmp_path / "devices.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "hostname": "ftd-branch-01",
                    "management_ip": "10.50.1.10",
                    "ssh_host_key": "ssh-ed25519 AAAA",
                    "allowed_interfaces": ["outside", "inside"],
                }
            ]
        ),
        encoding="utf-8",
    )
    assert load_devices(inventory)[0][0].hostname == "ftd-branch-01"


@pytest.mark.parametrize("interfaces", [[], ["outside", "outside"], ["outside;reload"]])
def test_inventory_rejects_unsafe_or_ambiguous_interfaces(tmp_path, interfaces: list[str]) -> None:
    inventory = tmp_path / "devices.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "hostname": "ftd-branch-01",
                    "management_ip": "10.50.1.10",
                    "ssh_host_key": "ssh-ed25519 AAAA",
                    "allowed_interfaces": interfaces,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="allowed_interfaces"):
        load_devices(inventory)
