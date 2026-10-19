"""Frozen all-or-nothing standing consent; no database, queue or agent access."""

from dataclasses import dataclass
from ipaddress import IPv4Address

from .import_preview import MAX_DEVICES, parse_blocklist
from .import_review import ReviewUnavailable
from .managed_grant_review import ManagedGrantReviews
from .managed_intent import canonical_managed_change
from .managed_review import ManagedRemovalReviews


def parse_standing_list(text, device_ids):
    if (not 1 <= len(device_ids) <= MAX_DEVICES or len(set(device_ids)) != len(device_ids)
            or any(type(device) is not int or not 1 <= device <= 65535 for device in device_ids)):
        raise ValueError("Select 1–64 distinct configured devices.")
    parsed = parse_blocklist(text)
    invalid = [row for row in parsed["rows"] if row["status"] not in {"Ready", "Duplicate"}]
    if invalid:
        lines = ", ".join(str(row["line"]) for row in invalid[:10])
        raise ValueError(f"Invalid, ambiguous or unsupported input on line(s) {lines}. Fix the input; no rows were silently skipped.")
    if not parsed["ips"] or len(parsed["ips"]) * len(device_ids) > 1000:
        raise ValueError("Select 1–1000 exact device/IP pairs. Nothing is truncated, split or saved.")
    return parsed


@dataclass(frozen=True)
class BatchTarget:
    device_id: int
    ip: IPv4Address
    hostname: str
    intent_id: str | None
    generation: int | None


@dataclass(frozen=True)
class ManagedBatchReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    targets: tuple[BatchTarget, ...]
    managed_revision: int
    protected_revision: int
    initialized: bool
    label: str
    reason: str
    digest: str
    duplicate_count: int
    ignored_lines: int

    def payload(self):
        return {"targets": [{"device_id": target.device_id, "ip": str(target.ip)} for target in self.targets],
                "managed_revision": self.managed_revision, "protected_revision": self.protected_revision,
                "label": self.label, "reason": self.reason, "confirmation_digest": self.digest, "maintain_present": True}


class ManagedBatchReviews(ManagedRemovalReviews):
    def prepare(self, subject, cookie, policy, classification, parsed, device_ids, label="", reason=""):
        if any(row["status"] not in {"Ready", "Duplicate"} for row in parsed["rows"]):
            raise ReviewUnavailable("Invalid rows cannot be silently dropped from standing consent.")
        ips = [IPv4Address(ip) for ip in parsed["ips"]]
        pairs = [(device, ip) for device in device_ids for ip in ips]
        pairs, _, digest = canonical_managed_change("MAINTAIN", pairs, policy["revision"], classification["policy_revision"], label, reason)
        if len(set(device_ids)) != len(device_ids) or not 1 <= len(device_ids) <= MAX_DEVICES:
            raise ValueError("Invalid batch device selection.")
        addresses = classification["addresses"]
        if not isinstance(addresses, list) or len(addresses) != len(ips):
            raise ValueError("Incomplete address classification.")
        address_map = {row["ip"]: row for row in addresses}
        if set(address_map) != {str(ip) for ip in ips} or len(address_map) != len(addresses):
            raise ValueError("Mismatched address classification.")
        device_map = {}
        for address in addresses:
            devices = address["devices"]
            if (len(devices) != len(device_ids) or len({device["id"] for device in devices}) != len(devices)
                    or {device["id"] for device in devices} != set(device_ids)):
                raise ValueError("Incomplete device classification.")
            for device in devices:
                if device["id"] in device_map and device_map[device["id"]] != device["hostname"]:
                    raise ValueError("Device identity changed within classification.")
                device_map[device["id"]] = device["hostname"]
        targets = []
        for device_id, ip in pairs:
            address = address_map[str(ip)]
            device = next(device for device in address["devices"] if device["id"] == device_id)
            one = {"policy_revision": classification["policy_revision"], "addresses": [dict(address, devices=[device])]}
            try:
                values = ManagedGrantReviews.validate(policy, one, device_id, ip, label, reason)
            except ReviewUnavailable as error:
                raise ReviewUnavailable(f"{device['hostname']} / {ip}: {error} The entire batch is unchanged.") from error
            targets.append(BatchTarget(device_id, ip, values["hostname"], values["intent_id"], values["generation"]))
        known = {(entry["device_id"], entry["ip"]) for entry in policy["entries"]}
        if len(known) + sum((device, str(ip)) not in known for device, ip in pairs) > 1000:
            raise ReviewUnavailable("Registry capacity includes stopped records; the entire batch cannot fit.")
        return self._save(ManagedBatchReview, subject, cookie, targets=tuple(targets),
                          managed_revision=policy["revision"], protected_revision=classification["policy_revision"],
                          initialized=policy["initialized"], label=label.strip(), reason=reason.strip(), digest=digest,
                          duplicate_count=sum(row["status"] == "Duplicate" for row in parsed["rows"]), ignored_lines=parsed["ignored_lines"])

    def get(self, token, subject, cookie):
        review = super().get(token, subject, cookie)
        if not isinstance(review, ManagedBatchReview):
            raise ReviewUnavailable("This is not a batch standing-policy review.")
        return review


def validate_batch_receipt(review, value):
    if (not isinstance(value, dict) or set(value) != {"operation_id", "status", "managed_revision", "changed_targets", "replayed"}
            or value["operation_id"] != review.request_id or value["status"] != "policy_saved"
            or type(value["managed_revision"]) is not int or value["managed_revision"] != review.managed_revision + 1
            or type(value["changed_targets"]) is not int or value["changed_targets"] != len(review.targets)
            or type(value["replayed"]) is not bool):
        raise ValueError("Invalid whole-batch policy receipt.")
    return value
