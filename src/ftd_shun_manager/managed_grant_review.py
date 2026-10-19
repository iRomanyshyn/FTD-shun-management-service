"""Frozen one-pair standing consent; never policy, migration or device access."""

from dataclasses import dataclass
from ipaddress import IPv4Address
from uuid import UUID

from .import_review import ReviewUnavailable
from .managed_intent import canonical_managed_change
from .managed_review import ManagedRemovalReviews


@dataclass(frozen=True)
class ManagedGrantReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    device_id: int
    ip: IPv4Address
    hostname: str
    managed_revision: int
    protected_revision: int
    initialized: bool
    intent_id: str | None
    generation: int | None
    enabled: bool
    label: str
    reason: str
    digest: str


class ManagedGrantReviews(ManagedRemovalReviews):
    """Reuse session/TTL/bounds mechanics, with a separate cache and typed consent."""

    def prepare(self, subject, cookie, policy, classification, device_id, ip, label="", reason=""):
        return self._save(ManagedGrantReview, subject, cookie,
                          **self.validate(policy, classification, device_id, ip, label, reason))

    @staticmethod
    def validate(policy, classification, device_id, ip, label="", reason=""):
        """Pure pair validation, shared by single and whole-batch reviews."""
        if (type(policy["initialized"]) is not bool or type(policy["revision"]) is not int
                or policy["revision"] < 0 or (not policy["initialized"] and policy["revision"] != 0)):
            raise ValueError("Invalid managed registry view.")
        _, _, digest = canonical_managed_change("MAINTAIN", [(device_id, ip)], policy["revision"],
                                               classification["policy_revision"], label, reason)
        addresses = classification["addresses"]
        if len(addresses) != 1 or addresses[0]["ip"] != str(ip) or type(addresses[0]["protected"]) is not bool:
            raise ValueError("Invalid exact-address classification.")
        devices = addresses[0]["devices"]
        if (len(devices) != 1 or type(devices[0]["id"]) is not int or devices[0]["id"] != device_id
                or not isinstance(devices[0]["hostname"], str) or not devices[0]["hostname"].strip()
                or len(devices[0]["hostname"]) > 255 or type(devices[0]["already_shunned"]) is not bool):
            raise ValueError("Invalid exact-device classification.")
        if addresses[0]["protected"] or devices[0]["already_shunned"]:
            raise ReviewUnavailable("Protected or already observed shuns cannot be adopted by this workflow.")
        entries = policy["entries"]
        if not isinstance(entries, list) or len(entries) > 1000 or (not policy["initialized"] and entries):
            raise ValueError("Invalid managed policy entries.")
        matches = [r for r in entries if r["device_id"] == device_id and r["ip"] == str(ip)]
        if len(matches) > 1:
            raise ValueError("Ambiguous managed policy.")
        old = matches[0] if matches else None
        if old:
            if (type(old["enabled"]) is not bool or str(UUID(old["intent_id"])) != old["intent_id"]
                    or type(old["generation"]) is not int or old["generation"] < 1):
                raise ValueError("Invalid retained managed intent.")
            if old["enabled"]:
                raise ReviewUnavailable("This target is already maintained; inspect its current holds instead.")
            if old.get("restoration_attention"):
                raise ReviewUnavailable("Retained restoration attention requires reviewed resolution, not a new grant.")
        return {"device_id": device_id, "ip": ip, "hostname": devices[0]["hostname"], "managed_revision": policy["revision"],
                "protected_revision": classification["policy_revision"], "initialized": policy["initialized"],
                "intent_id": old["intent_id"] if old else None, "generation": old["generation"] if old else None,
                "enabled": old["enabled"] if old else False, "label": label.strip(), "reason": reason.strip(), "digest": digest}

    def get(self, token, subject, cookie):
        review = super().get(token, subject, cookie)
        if not isinstance(review, ManagedGrantReview):
            raise ReviewUnavailable("This is not a standing-grant review.")
        return review
