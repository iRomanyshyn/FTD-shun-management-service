"""Static, read-only FTD inventory loader."""

import json
from ipaddress import IPv4Address
from pathlib import Path

from .store import Device


def _valid_interface(value: object) -> bool:
    """Accept only names that the agent can safely place into its fixed command form."""
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not value[0].isalpha():
        return False
    return all(char.isascii() and (char.isalnum() or char in "/._-") for char in value)


def load_devices(path: Path) -> list[tuple[Device, str]]:
    """Load the deliberately small JSON inventory and reject ambiguous definitions."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("device inventory must be a JSON array")
    devices: list[tuple[Device, str]] = []
    ids: set[int] = set()
    hostnames: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise TypeError("every device inventory entry must be an object")
        device_id = entry.get("id")
        hostname = entry.get("hostname")
        management_ip = entry.get("management_ip")
        host_key = entry.get("ssh_host_key")
        allowed_interfaces = entry.get("allowed_interfaces")
        if not isinstance(device_id, int) or not 1 <= device_id <= 65535:
            raise ValueError("device id must be an integer between 1 and 65535")
        if not isinstance(hostname, str) or not hostname or len(hostname) > 255:
            raise ValueError("device hostname is invalid")
        if not isinstance(management_ip, str) or not isinstance(host_key, str) or not host_key.strip():
            raise ValueError("device management_ip and ssh_host_key are required")
        if (
            not isinstance(allowed_interfaces, list)
            or not allowed_interfaces
            or any(not _valid_interface(interface) for interface in allowed_interfaces)
            or len(set(allowed_interfaces)) != len(allowed_interfaces)
        ):
            raise ValueError("device allowed_interfaces must be a unique, non-empty safe-name list")
        if device_id in ids or hostname in hostnames:
            raise ValueError("device IDs and hostnames must be unique")
        ids.add(device_id)
        hostnames.add(hostname)
        devices.append((Device(device_id, hostname, IPv4Address(management_ip), entry.get("enabled", True)), host_key))
    return devices
