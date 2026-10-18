"""Pure canonical managed intents; no storage, authority or dispatch."""

import hashlib
import json
from ipaddress import IPv4Address
from uuid import UUID

from .import_intent import canonical_import


def canonical_managed_change(
    action: str, targets: list[tuple[int, IPv4Address]], managed_revision: int,
    protected_revision: int, label: str = "", reason: str = "",
) -> tuple[list[tuple[int, IPv4Address]], str, str]:
    if action not in {"MAINTAIN", "RETIRE"}:
        raise ValueError("Managed action must be MAINTAIN or RETIRE.")
    if type(managed_revision) is not int or managed_revision < 0:
        raise ValueError("A non-negative managed revision is required.")
    targets, canonical, _ = canonical_import(targets, protected_revision, label, reason)
    payload = json.loads(canonical)
    payload.update(scope="managed_shuns", mode="maintain_present", action=action,
                   managed_revision=managed_revision)
    payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return targets, payload, hashlib.sha256(payload.encode()).hexdigest()


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


def canonical_managed_fleet_scope(scope: dict) -> tuple[str, str]:
    """Validate a complete local scope; hashes are bindings, never permissions."""
    if not isinstance(scope, dict) or set(scope) != {
        "ip", "managed_initialized", "managed_revision", "protected_revision", "protected", "targets",
    }:
        raise ValueError("Invalid fleet removal scope.")
    ip = IPv4Address(scope["ip"])
    if str(ip) != scope["ip"]:
        raise ValueError("Fleet scope requires a canonical IPv4 address.")
    if any(type(scope[key]) is not bool for key in ("managed_initialized", "protected")):
        raise ValueError("Invalid fleet policy state.")
    if any(type(scope[key]) is not int or scope[key] < 0 for key in ("managed_revision", "protected_revision")):
        raise ValueError("Invalid fleet policy revision.")
    if not scope["managed_initialized"] and scope["managed_revision"] != 0:
        raise ValueError("Absent managed policy cannot have a revision.")
    targets = scope["targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 1000:
        raise ValueError("Fleet review requires 1 to 1000 distinct device targets.")
    seen = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {
            "device_id", "hostname", "device_enabled", "observed_present", "maintenance_enabled", "intent_id", "generation",
        }:
            raise ValueError("Invalid fleet target metadata.")
        device = target["device_id"]
        if type(device) is not int or not 1 <= device <= 65535 or device in seen:
            raise ValueError("Fleet scope requires distinct valid devices.")
        seen.add(device)
        if (not isinstance(target["hostname"], str) or not target["hostname"].strip()
                or len(target["hostname"]) > 255 or any(ord(c) < 32 for c in target["hostname"])):
            raise ValueError("Invalid fleet device name.")
        if any(type(target[key]) is not bool for key in ("device_enabled", "observed_present", "maintenance_enabled")):
            raise ValueError("Invalid fleet target state.")
        if not target["observed_present"] and not target["maintenance_enabled"]:
            raise ValueError("A fleet target must be observed or maintained.")
        intent, generation = target["intent_id"], target["generation"]
        if intent is None and generation is None:
            if target["maintenance_enabled"]:
                raise ValueError("Maintained targets require retained intent.")
        elif (not isinstance(intent, str) or str(UUID(intent)) != intent
              or type(generation) is not int or generation < 1 or not scope["managed_initialized"]):
            raise ValueError("Invalid fleet intent generation.")
    payload = json.dumps({**scope, "version": 1, "scope": "managed_fleet_removal",
                          "targets": sorted(targets, key=lambda row: row["device_id"])},
                         sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode()).hexdigest()


def canonical_managed_fleet_removal(scope: dict, ttl_seconds: int = 900, reason: str = "",
                                   *, ordered_wait: bool = False) -> tuple[str, str]:
    if type(ordered_wait) is not bool:
        raise TypeError("Ordered fleet waiting requires an explicit boolean.")
    canonical, _ = canonical_managed_fleet_scope(scope)
    # Reuse strict reason/lifetime validation, but never reuse single-target intent.
    validated, _ = canonical_managed_removal(1, IPv4Address(scope["ip"]), scope["managed_revision"], ttl_seconds, reason)
    payload = json.loads(canonical)
    payload.update(action="RETIRE_AND_REMOVE", mode="stop_maintenance_and_remove_ordered" if ordered_wait else "stop_maintenance_and_remove",
                   ttl_seconds=ttl_seconds, reason=json.loads(validated)["reason"])
    payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode()).hexdigest()
