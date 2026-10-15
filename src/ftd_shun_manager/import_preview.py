"""Bounded, non-executable blocklist parsing and local-state preview."""

import re
from collections import Counter
from ipaddress import IPv4Address, IPv6Address

from .store import Store

MAX_TEXT_BYTES = 1024 * 1024
MAX_FORM_BYTES = 3 * MAX_TEXT_BYTES + 16 * 1024
MAX_LINES = 20000
MAX_ROWS = 10000
MAX_DEVICES = 64
MAX_PAIRS = 100000
PAGE_SIZE = 100

_DOTTED = re.compile(r"[0-9]\.[0-9]")
_LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*=(.+)")
_WRAPPERS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
_TIME = re.compile(r"(?:\d{4}-\d{2}-\d{2}[Tt])?\d{1,2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:?\d{2})?")


def _token(value: str) -> dict | None:
    """Inspect whole tokens; never search out a usable address substring."""
    for _ in range(4):
        if len(value) > 1 and _WRAPPERS.get(value[0]) == value[-1]:
            value = value[1:-1]
        else:
            break
    label = _LABEL.fullmatch(value)
    decorated = label is not None
    if label:
        value = label[1]
    if _TIME.fullmatch(value):
        return None
    try:
        ip = IPv4Address(value)
    except ValueError:
        pass
    else:
        return {"ip": str(ip), "status": "Ready", "reason": "Exact IPv4 address", "decorated": decorated}
    try:
        IPv6Address(value)
    except ValueError:
        pass
    else:
        return {"ip": None, "status": "Unsupported", "reason": "IPv6 is not supported", "decorated": decorated}
    if not _DOTTED.search(value) and "://" not in value and "::" not in value:
        return None
    reason = None
    if "://" in value:
        reason = "URLs are not supported"
    elif "/" in value:
        reason = "CIDRs and paths are not supported; no address was extracted"
    elif "-" in value or "–" in value or ".." in value:
        reason = "Ranges are not supported; no address was expanded"
    elif ":" in value:
        reason = "IPv6 and address-with-port forms are not supported"
    return {"ip": None, "status": "Unsupported" if reason else "Invalid",
            "reason": reason or "Not an exact IPv4 token; no substring was extracted", "decorated": decorated}


def parse_blocklist(text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Paste at most 1 MiB of UTF-8 text. Nothing was parsed; shorten the input and try again.")
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError(f"Paste at most {MAX_LINES:,} lines.")
    rows = []
    first = {}
    ignored = 0
    for number, original in enumerate(lines, 1):
        stripped = original.strip()
        if not stripped or stripped.startswith(("#", "//")):
            ignored += 1
            continue
        content, _, comment = stripped.partition("#")
        tokens = re.split(r"[\s,;]+", content.strip())
        parsed = [_token(token) for token in tokens if token]
        candidates = [token for token in parsed if token is not None]
        address_only = len(candidates) == len(parsed) and not any(token["decorated"] for token in candidates)
        base = {"line": number, "source_lines": [number], "excerpt": original[:200], "comment": comment.strip()[:200]}
        if re.search(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}\s*[-–/:]\s*[0-9]", content):
            entries = [{"ip": None, "status": "Unsupported", "reason": "Range, CIDR or address-with-port syntax is unsupported; no substring was extracted."}]
        elif len(candidates) > 1 and not address_only:
            entries = [{"ip": None, "status": "Ambiguous", "reason": "Multiple address-like tokens in free text; split into explicit address-only lines."}]
        elif not candidates:
            entries = [{"ip": None, "status": "Invalid", "reason": "No exact IPv4 address found."}]
        else:
            entries = candidates
        for entry in entries:
            if len(rows) >= MAX_ROWS:
                raise ValueError(f"Preview is limited to {MAX_ROWS:,} rows; split the input into smaller batches.")
            row = {**base, "source_lines": [number], **{key: entry[key] for key in ("ip", "status", "reason")}}
            if row["ip"] is not None:
                if row["ip"] in first:
                    previous = first[row["ip"]]
                    row.update(status="Duplicate", reason=f"Already listed on line {previous['line']}.")
                    if previous["source_lines"][-1] != number:
                        previous["source_lines"].append(number)
                else:
                    first[row["ip"]] = row
            rows.append(row)
    return {"rows": rows, "ips": list(first), "ignored_lines": ignored}


def classify_targets(store: Store, ips: list[IPv4Address], device_ids: list[int]) -> dict:
    """Read one consistent SQLite snapshot, without queue or agent access."""
    if len(ips) > MAX_ROWS or len(set(ips)) != len(ips):
        raise ValueError(f"At most {MAX_ROWS:,} unique IPv4 addresses may be previewed.")
    if not 1 <= len(device_ids) <= MAX_DEVICES or len(set(device_ids)) != len(device_ids):
        raise ValueError("Select between 1 and 64 distinct devices.")
    if len(ips) * len(device_ids) > MAX_PAIRS:
        raise ValueError(f"Preview exceeds {MAX_PAIRS:,} device/IP pairs; reduce the batch or selected devices.")
    with store._connection() as db:
        db.execute("BEGIN")
        placeholders = ",".join("?" for _ in device_ids)
        devices = db.execute(f"SELECT id,hostname FROM devices WHERE enabled=1 AND id IN ({placeholders}) ORDER BY hostname", device_ids).fetchall()
        if len(devices) != len(device_ids):
            raise ValueError("Select enabled configured devices only. Reload the device list.")
        protected = {row[0] for row in db.execute("SELECT ip FROM protected_ips WHERE enabled=1")}
        revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
        present = set()
        # Keep well below SQLite's older 999-variable limit.
        for offset in range(0, len(ips), 400):
            chunk = ips[offset:offset + 400]
            ip_placeholders = ",".join("?" for _ in chunk)
            present.update((row[0], row[1]) for row in db.execute(f"""SELECT DISTINCT device_id,ip FROM shun_state
                WHERE active=1 AND device_id IN ({placeholders}) AND ip IN ({ip_placeholders})""",
                [*device_ids, *(ip.packed for ip in chunk)]))
        return {"preview_only": True, "can_execute": False, "policy_revision": revision,
                "devices": [dict(device) for device in devices],
                "addresses": [{"ip": str(ip), "protected": ip.packed in protected,
                    "devices": [{"id": device["id"], "hostname": device["hostname"],
                        "already_shunned": (device["id"], ip.packed) in present} for device in devices]} for ip in ips]}


def summarize_preview(parsed: dict, classification: dict) -> dict:
    addresses = {entry["ip"]: entry for entry in classification["addresses"]}
    pairs = 0
    for row in parsed["rows"]:
        address = addresses.get(row["ip"])
        row["protected"] = bool(address and address["protected"])
        row["devices"] = address["devices"] if address else []
        if row["status"] != "Ready" or address is None:
            continue
        if address["protected"]:
            row.update(status="Protected", reason="Enabled Protected IP policy; excluded from addition candidates.")
        else:
            missing = sum(not device["already_shunned"] for device in address["devices"])
            pairs += missing
            if missing:
                row["reason"] = f"Candidate on {missing} selected device(s); addition is unavailable."
            else:
                row.update(status="Already shunned", reason="Already observed on every selected device; no addition candidate.")
    return {**parsed, "counts": dict(Counter(row["status"] for row in parsed["rows"])),
            "candidate_pairs": pairs, "devices": classification["devices"],
            "policy_revision": classification["policy_revision"]}


def paginate_preview(preview: dict, page: int = 1) -> dict:
    """Bound rendered rows only; classification and totals cover the entire input."""
    pages = max(1, (len(preview["rows"]) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    offset = (page - 1) * PAGE_SIZE
    return {**preview, "page": page, "pages": pages,
            "first_row": offset + 1, "last_row": min(offset + PAGE_SIZE, len(preview["rows"])),
            "page_rows": preview["rows"][offset:offset + PAGE_SIZE]}
