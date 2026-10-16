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


@pytest.mark.parametrize("profile,interfaces,accepted", [
    (None,["outside"],True),
    ("fpr1010-766-single-vf-management-v1",["management"],True),
    ("fpr1010-766-single-vf-management-v1",["outside"],False),
    ("unknown",["management"],False), (True,["management"],False),
])
def test_optional_addition_profile_never_uses_implicit_scope(tmp_path, profile, interfaces, accepted):
    inventory = tmp_path / "devices.json"
    inventory.write_text(json.dumps([{"id":1,"hostname":"lab","management_ip":"192.0.2.1",
        "ssh_host_key":"ssh-ed25519 AAAA","allowed_interfaces":interfaces,"addition_profile":profile}]))
    if accepted:
        assert len(load_devices(inventory)) == 1
    else:
        with pytest.raises(ValueError, match="addition_profile"):
            load_devices(inventory)
