"""Version-2 proposed import bindings, not policy authority or execution.

Pure and deliberately separate from legacy canonical intents. No persistence,
request route, dispatch capability or migration is provided by this module.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from ipaddress import IPv4Address
from uuid import UUID

MAX_DEVICES = 10
MAX_ADDRESSES = 10000
MAX_PAIRS = 100000
MAX_DESCRIPTOR_BYTES = 8192
CLASSES = ("PROPOSE_ADD", "PROPOSE_ADOPT", "ALREADY_MANAGED", "EXCLUDED_PROTECTED")
FORMAT = "device-u16-ipv4-class-u8-v2"
DOMAIN = b"ftd-shun-manager:managed-import-manifest:v2\n"
_ROOT_FIELDS = {"version", "scope", "action", "mode", "operation_id", "preparation_id", "preparation_digest",
                "managed_revision", "protected_revision", "label", "reason", "manifest"}
_MANIFEST_FIELDS = {"format", "device_ids", "address_count", "pair_count", "accepted_count", "classification_counts", "digest"}


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid literal {name}.")


def _devices(value):
    if (type(value) is not tuple or not 1 <= len(value) <= MAX_DEVICES
            or any(type(device) is not int or not 1 <= device <= 65535 for device in value)
            or tuple(sorted(set(value))) != value):
        raise ValueError("Select 1–10 distinct explicit device IDs in numerical order.")
    return value


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("An exact lowercase SHA-256 digest is required.")


def _uuid(value):
    if type(value) is not str or len(value) != 36 or str(UUID(value)) != value:
        raise ValueError("An exact canonical UUID is required.")


@dataclass(frozen=True)
class ManifestSummary:
    """Immutable bounded description; neither membership proof nor permission."""

    device_ids: tuple[int, ...]
    address_count: int
    pair_count: int
    classification_counts: tuple[int, int, int, int]
    digest: str

    def __post_init__(self):
        _devices(self.device_ids)
        _integer(self.address_count, 1, MAX_ADDRESSES, "address count")
        _integer(self.pair_count, 1, MAX_PAIRS, "pair count")
        if (type(self.classification_counts) is not tuple or len(self.classification_counts) != len(CLASSES)
                or any(type(value) is not int or not 0 <= value <= MAX_PAIRS for value in self.classification_counts)
                or sum(self.classification_counts) != self.pair_count
                or self.pair_count != self.address_count * len(self.device_ids)):
            raise ValueError("Manifest counts must describe the entire selected-device/address product.")
        _digest(self.digest)

    @property
    def accepted_count(self):
        return self.pair_count - self.classification_counts[3]

    def as_dict(self):
        return {"format": FORMAT, "device_ids": list(self.device_ids), "address_count": self.address_count,
                "pair_count": self.pair_count, "accepted_count": self.accepted_count,
                "classification_counts": dict(zip(CLASSES, self.classification_counts, strict=True)), "digest": self.digest}


def summarize_manifest(rows, device_ids):
    """Consume sorted literal (device, IPv4Address, classification) rows once.

    Retains <=10000 distinct addresses, not a list of all pairs. The extra row
    detecting overflow is consumed, never truncated into an accepted prefix.
    """
    devices = _devices(device_ids)
    checksum, counts, addresses = hashlib.sha256(DOMAIN), [0] * len(CLASSES), set()
    previous, total = None, 0
    for row in rows:
        if total >= MAX_PAIRS:
            raise ValueError("Manifest exceeds 100000 pairs; nothing was truncated.")
        if (type(row) is not tuple or len(row) != 3 or type(row[0]) is not int or row[0] not in devices
                or type(row[1]) is not IPv4Address or type(row[2]) is not str or row[2] not in CLASSES):
            raise ValueError("Manifest rows require an explicit device, literal IPv4 and known classification.")
        device, ip, kind = row
        key = device, int(ip)
        if previous is not None and key <= previous:
            raise ValueError("Manifest pairs must be unique and in numerical device/IP order.")
        previous = key
        addresses.add(int(ip))
        if len(addresses) > MAX_ADDRESSES:
            raise ValueError("Manifest exceeds 10000 distinct IPv4 addresses.")
        code = CLASSES.index(kind)
        counts[code] += 1
        checksum.update(device.to_bytes(2, "big") + ip.packed + bytes([code + 1]))
        total += 1
    # Unique pairs are a subset of the declared devices x observed addresses.
    # Equality proves every cell exists, without storing that entire product.
    return ManifestSummary(devices, len(addresses), total, tuple(counts), checksum.hexdigest())


def _descriptor(summary, operation_id, preparation_id, preparation_digest, managed_revision, protected_revision, label, reason):
    if type(summary) is not ManifestSummary:
        raise ValueError("A validated manifest summary is required.")
    _uuid(operation_id)
    _uuid(preparation_id)
    if operation_id == preparation_id:
        raise ValueError("A preparation reference cannot become the policy operation key.")
    _digest(preparation_digest)
    for name, revision in (("managed revision", managed_revision), ("protected revision", protected_revision)):
        _integer(revision, 0, 2**63 - 1, name)
    if type(label) is not str or type(reason) is not str:
        raise ValueError("Label and reason must be plain text.")
    label, reason = label.strip(), reason.strip()
    if (len(label) > 100 or len(reason) > 500
            or any((ord(char) < 32 and char not in "\t\n") or 0xD800 <= ord(char) <= 0xDFFF for char in label + reason)):
        raise ValueError("Invalid label/reason length or characters.")
    if summary.accepted_count == 0:
        raise ValueError("There are no accepted pairs; an excluded-only manifest is not a standing proposal.")
    value = {"version": 2, "scope": "managed_import_policy", "action": "MAINTAIN", "mode": "maintain_present",
             "operation_id": operation_id, "preparation_id": preparation_id, "preparation_digest": preparation_digest,
             "managed_revision": managed_revision, "protected_revision": protected_revision,
             "label": label, "reason": reason, "manifest": summary.as_dict()}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode("utf-8")) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("Bulk intent descriptor exceeds 8192 UTF-8 bytes.")
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_bulk_intent(rows, device_ids, operation_id, preparation_id, preparation_digest,
                          managed_revision, protected_revision, label="", reason=""):
    """Build one bounded proposal from a complete stream, not a list of jobs."""
    summary = summarize_manifest(rows, device_ids)
    canonical, digest = _descriptor(summary, operation_id, preparation_id, preparation_digest,
                                    managed_revision, protected_revision, label, reason)
    return summary, canonical, digest


def _unique_object(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("Repeated descriptor fields are not allowed.")
        value[key] = item
    return value


def decode_bulk_descriptor(canonical, expected_digest):
    """Strict descriptor-only decoding, not membership verification or permission."""
    _digest(expected_digest)
    if type(canonical) is not str or not 1 <= len(canonical) <= MAX_DESCRIPTOR_BYTES:
        raise ValueError("A bounded canonical bulk descriptor is required.")
    raw = canonical.encode("utf-8")
    if len(raw) > MAX_DESCRIPTOR_BYTES or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_digest):
        raise ValueError("Bulk descriptor digest does not match the original binding.")
    try:
        value = json.loads(canonical, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid or excessively nested bulk descriptor JSON.") from error
    if (type(value) is not dict or set(value) != _ROOT_FIELDS or type(value["version"]) is not int or value["version"] != 2
            or value["scope"] != "managed_import_policy" or value["action"] != "MAINTAIN" or value["mode"] != "maintain_present"):
        raise ValueError("Unsupported bulk descriptor version, scope or fields.")
    manifest = value["manifest"]
    if (type(manifest) is not dict or set(manifest) != _MANIFEST_FIELDS or manifest["format"] != FORMAT
            or type(manifest["device_ids"]) is not list or type(manifest["classification_counts"]) is not dict
            or set(manifest["classification_counts"]) != set(CLASSES)):
        raise ValueError("Invalid classified manifest descriptor.")
    summary = ManifestSummary(tuple(manifest["device_ids"]), manifest["address_count"], manifest["pair_count"],
                              tuple(manifest["classification_counts"][kind] for kind in CLASSES), manifest["digest"])
    _integer(manifest["accepted_count"], 1, MAX_PAIRS, "accepted count")
    expected, _ = _descriptor(summary, *(value[key] for key in ("operation_id", "preparation_id", "preparation_digest",
                                                              "managed_revision", "protected_revision", "label", "reason")))
    if canonical != expected:
        raise ValueError("Bulk descriptor is not the exact canonical representation.")
    return value


def verify_bulk_intent(canonical, rows, expected_digest):
    """Verify the entire binding using a separately retained original digest.

    Construction/inspection only, not a full scan per dispatched job or a grant.
    """
    value = decode_bulk_descriptor(canonical, expected_digest)
    manifest = value["manifest"]
    summary = ManifestSummary(tuple(manifest["device_ids"]), manifest["address_count"], manifest["pair_count"],
                              tuple(manifest["classification_counts"][kind] for kind in CLASSES), manifest["digest"])
    if summarize_manifest(rows, summary.device_ids) != summary:
        raise ValueError("Classified membership does not match the original bulk descriptor.")
    return summary
