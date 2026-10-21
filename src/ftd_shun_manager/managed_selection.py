"""Bounded local policy selectors; not executable targets or standing consent."""

from ipaddress import IPv4Address


def selected_pairs(pairs, *, batch=False):
    limit = 1000 if batch else 100
    if (type(pairs) is not list or not 1 <= len(pairs) <= limit
            or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not int
                   or not 1 <= pair[0] <= 65535 or type(pair[1]) is not IPv4Address for pair in pairs)
            or len(set(pairs)) != len(pairs)):
        raise ValueError(f"Select 1–{limit} distinct literal device/IPv4 pairs for a policy read.")
    return sorted(pairs, key=lambda pair: (pair[0], int(pair[1])))


def require_selection(policy, pairs, *, batch=False):
    """A partial read must match the exact intended review and read resource.

    Legacy complete snapshots remain supported, not confused with policy pages.
    These checks do not authorize admission or make cached presence fresh.
    """
    if "selection" not in policy:
        if "page" in policy or "selected_count" in policy or "read_scope" in policy:
            raise ValueError("A policy page is not an exact review selection.")
        return
    requested = [{"device_id": device, "ip": str(ip)} for device, ip in selected_pairs(pairs, batch=batch)]
    requested_keys = {(item["device_id"], item["ip"]) for item in requested}
    entries = policy["entries"]
    selection = policy["selection"]
    if (not isinstance(selection, list) or len(selection) != len(requested)
            or any(not isinstance(item, dict) or set(item) != {"device_id", "ip"}
                   or type(item["device_id"]) is not int or type(item["ip"]) is not str for item in selection)):
        raise ValueError("Invalid literal policy selection descriptor.")
    if (policy.get("read_scope") != ("selected_batch" if batch else "selected_pairs") or policy.get("read_only") is not True
            or selection != requested or type(policy.get("initialized")) is not bool
            or type(policy.get("revision")) is not int or policy["revision"] < 0
            or type(policy.get("limit")) is not int or policy["limit"] < 1
            or type(policy.get("total")) is not int or not 0 <= policy["total"] <= policy["limit"]
            or type(policy.get("selected_count")) is not int or not 0 <= policy["selected_count"] <= len(requested)
            or not isinstance(entries, list) or len(entries) != policy["selected_count"]
            or policy["total"] < len(entries)
            or any(not isinstance(entry, dict) or type(entry.get("device_id")) is not int or type(entry.get("ip")) is not str
                   or (entry["device_id"], entry["ip"]) not in requested_keys for entry in entries)
            or len({(entry["device_id"], entry["ip"]) for entry in entries}) != len(entries)
            or (policy["initialized"] is False and (policy["total"] != 0 or entries or policy["revision"] != 0))):
        raise ValueError("Policy selection does not match the exact requested review scope.")
