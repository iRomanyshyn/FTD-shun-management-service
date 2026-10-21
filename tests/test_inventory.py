import json
from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.inventory import load_devices
from ftd_shun_manager.store import Store


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
        devices = load_devices(inventory)
        assert len(devices) == 1
        assert devices[0][0].addition_profile == profile
    else:
        with pytest.raises(ValueError, match="addition_profile"):
            load_devices(inventory)


def public_device():
    return {"id": 1, "hostname": "branch-01", "management_ip": "192.0.2.1",
            "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"]}


@pytest.mark.parametrize("field", ["username", "password", "password_file", "password_secret", "credentials"])
def test_public_inventory_rejects_credential_fields(tmp_path, field):
    entry = public_device()
    entry[field] = "sensitive-test-value"
    inventory = tmp_path / "devices.json"
    inventory.write_text(json.dumps([entry]))
    with pytest.raises(ValueError, match="agent-only") as error:
        load_devices(inventory)
    assert "sensitive-test-value" not in str(error.value)


@pytest.mark.parametrize("changes", [{"id": True}, {"id": 0}, {"enabled": "false"}, {"enabled": 1}, {"hostname": " "}])
def test_public_inventory_does_not_coerce_identity_or_enabled_state(tmp_path, changes):
    inventory = tmp_path / "devices.json"
    inventory.write_text(json.dumps([public_device() | changes]))
    with pytest.raises(ValueError):
        load_devices(inventory)


def test_inventory_rejects_duplicate_fields_and_empty_scope(tmp_path):
    inventory = tmp_path / "devices.json"
    inventory.write_text('[{"id":1,"id":2}]')
    with pytest.raises(ValueError, match="duplicate"):
        load_devices(inventory)
    inventory.write_text("[]")
    with pytest.raises(ValueError, match="empty"):
        load_devices(inventory)


def test_address_change_preserves_stable_device_identity(tmp_path):
    inventory = tmp_path / "devices.json"
    inventory.write_text(json.dumps([public_device()]))
    before, key = load_devices(inventory)[0]
    inventory.write_text(json.dumps([public_device() | {"management_ip": "192.0.2.2"}]))
    after, new_key = load_devices(inventory)[0]
    assert (after.id, after.hostname, new_key) == (before.id, before.hostname, key)
    assert after.management_ip == IPv4Address("192.0.2.2")


def test_reloaded_address_does_not_recreate_observations_or_history(tmp_path):
    inventory = tmp_path / "devices.json"
    inventory.write_text(json.dumps([public_device()]))
    store = Store(tmp_path / "state.db")
    store.initialize()
    device, key = load_devices(inventory)[0]
    store.upsert_device(device, key)
    store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    history = store.list_events()
    observations = store.list_active_shuns()
    inventory.write_text(json.dumps([public_device() | {"management_ip": "192.0.2.2"}]))
    device, key = load_devices(inventory)[0]
    store.upsert_device(device, key)
    assert store.list_devices() == [device]
    assert store.list_events() == history
    assert store.list_active_shuns() == observations
