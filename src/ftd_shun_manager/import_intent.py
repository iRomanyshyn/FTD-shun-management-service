"""Canonical one-time import intent; no paste, CLI, authorization or dispatch."""

import hashlib
import json
from ipaddress import IPv4Address


def canonical_import(
    targets: list[tuple[int, IPv4Address]], policy_revision: int, label: str = "", reason: str = ""
) -> tuple[list, str, str]:
    if not 1 <= len(targets) <= 1000 or len(set(targets)) != len(targets):
        raise ValueError(
            "Select 1 to 1000 distinct device/IP targets; split larger batches explicitly."
        )
    if any(
        type(device) is not int or not 1 <= device <= 65535 or not isinstance(ip, IPv4Address)
        for device, ip in targets
    ):
        raise ValueError("Import targets require device IDs and exact IPv4 addresses.")
    if type(policy_revision) is not int or policy_revision < 0:
        raise ValueError("A non-negative policy revision is required.")
    label, reason = label.strip(), reason.strip()
    if (
        len(label) > 100
        or len(reason) > 500
        or any(ord(c) < 32 and c not in "\n\t" for c in label + reason)
    ):
        raise ValueError("Batch label/reason is too long or contains control characters.")
    targets = sorted(targets, key=lambda value: (value[0], int(value[1])))
    payload = json.dumps(
        {
            "scope": "import",
            "action": "ADD",
            "policy_revision": policy_revision,
            "label": label,
            "reason": reason,
            "targets": [(device, str(ip)) for device, ip in targets],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    # Integrity/confirmation binding only, never a bearer capability or permission.
    return targets, payload, hashlib.sha256(payload.encode()).hexdigest()
