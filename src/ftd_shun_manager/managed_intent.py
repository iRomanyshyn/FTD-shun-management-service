"""Pure canonical managed-removal intent; no storage, authority or dispatch."""

import hashlib
import json
from ipaddress import IPv4Address

from .import_intent import canonical_import


def canonical_managed_removal(device_id: int, ip: IPv4Address, managed_revision: int,
                              ttl_seconds: int = 900, reason: str = "") -> tuple[str, str]:
    if type(managed_revision) is not int or managed_revision < 0:
        raise ValueError("A non-negative managed revision is required.")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise ValueError("Removal authorization must last 1 to 900 seconds.")
    _, canonical, _ = canonical_import([(device_id, ip)], 0, reason=reason)
    payload = json.loads(canonical)
    payload.update(scope="managed_device_removal", action="RETIRE_AND_REMOVE",
                   mode="stop_maintenance_and_remove", managed_revision=managed_revision,
                   ttl_seconds=ttl_seconds)
    payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode()).hexdigest()
