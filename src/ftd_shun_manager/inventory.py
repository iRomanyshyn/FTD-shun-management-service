"""Static, read-only FTD inventory loader."""

import json
import os
import stat
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from .store import Device

MAX_INVENTORY_BYTES = 256 * 1024


@dataclass(frozen=True)
class PublicDevice:
    """Complete credential-free configuration, not executable ADD authority."""

    device: Device
    ssh_host_key: str
    allowed_interfaces: tuple[str, ...]


def _read_inventory(path: Path) -> object:
    # Nonblocking open prevents a mistaken FIFO from hanging process startup.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Public inventory must be a regular, non-symlink file.')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            raw = source.read(MAX_INVENTORY_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError('Public inventory exceeds the 256 KiB limit.')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_fields)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("device inventory has duplicate object fields")
        fields[key] = value
    return fields


def _valid_interface(value: object) -> bool:
    """Accept only names that the agent can safely place into its fixed command form."""
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not value[0].isalpha():
        return False
    return all(char.isascii() and (char.isalnum() or char in "/._-") for char in value)


def load_public_inventory(path: Path) -> tuple[PublicDevice, ...]:
    """Load the deliberately small JSON inventory and reject ambiguous definitions."""
    raw = _read_inventory(path)
    if not isinstance(raw, list):
        raise TypeError("device inventory must be a JSON array")
    if not raw:
        raise ValueError("device inventory cannot be empty")
    devices: list[PublicDevice] = []
    ids: set[int] = set()
    hostnames: set[str] = set()
    addresses: set[IPv4Address] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise TypeError("every device inventory entry must be an object")
        if entry.keys() - {"id", "hostname", "management_ip", "ssh_host_key", "allowed_interfaces", "addition_profile", "enabled"}:
            raise ValueError("device inventory contains unknown fields; credentials belong in the agent-only mapping")
        device_id = entry.get("id")
        hostname = entry.get("hostname")
        management_ip = entry.get("management_ip")
        host_key = entry.get("ssh_host_key")
        allowed_interfaces = entry.get("allowed_interfaces")
        addition_profile = entry.get("addition_profile")
        if type(device_id) is not int or not 1 <= device_id <= 65535:
            raise ValueError("device id must be an integer between 1 and 65535")
        if (not isinstance(hostname, str) or not hostname.strip() or len(hostname) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in hostname)):
            raise ValueError("device hostname is invalid")
        if type(entry.get("enabled", True)) is not bool:
            raise ValueError("device enabled must be a boolean")
        if (not isinstance(management_ip, str) or not isinstance(host_key, str) or not host_key.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in host_key)):
            raise ValueError("device management_ip and ssh_host_key are required")
        try:
            address = IPv4Address(management_ip)
        except ValueError as error:
            raise ValueError('device management_ip must be an exact IPv4 address') from error
        if (
            not isinstance(allowed_interfaces, list)
            or not allowed_interfaces
            or any(not _valid_interface(interface) for interface in allowed_interfaces)
            or len(set(allowed_interfaces)) != len(allowed_interfaces)
        ):
            raise ValueError("device allowed_interfaces must be a unique, non-empty safe-name list")
        if addition_profile is not None and (
            addition_profile != "fpr1010-766-single-vf-management-v1" or "management" not in allowed_interfaces
        ):
            raise ValueError("device addition_profile is unknown or its interface is not allowlisted")
        if device_id in ids or hostname in hostnames or address in addresses:
            raise ValueError("device IDs, hostnames and management addresses must be unique")
        ids.add(device_id)
        hostnames.add(hostname)
        addresses.add(address)
        devices.append(PublicDevice(Device(device_id, hostname, address, entry.get("enabled", True), addition_profile),
                                    host_key, tuple(sorted(allowed_interfaces))))
    return tuple(sorted(devices, key=lambda entry: entry.device.id))


def load_devices(path: Path) -> list[tuple[Device, str]]:
    """Compatibility projection: credentials and interface strings never reach RPC."""
    return [(entry.device, entry.ssh_host_key) for entry in load_public_inventory(path)]
