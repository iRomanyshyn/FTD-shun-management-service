"""Ephemeral single-target removal reviews. Preparation never admits work."""

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from threading import Lock
from uuid import UUID, uuid4

from .import_review import ReviewUnavailable
from .managed_intent import canonical_managed_removal


def select_managed_target(policy: dict, device_id: int, ip: IPv4Address, *, allow_disabled: bool = False) -> dict:
    """Validate one retained target for a frozen review, without trusting flags."""
    if policy.get("initialized") is not True:
        raise ReviewUnavailable("Managed policy is not initialized; no review was prepared.")
    entries = policy["entries"]
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError("Invalid managed target view.")
    selected = [entry for entry in entries if entry["device_id"] == device_id and entry["ip"] == str(ip)]
    if len(selected) != 1:
        raise ReviewUnavailable("Managed target is missing; review its current policy.")
    entry = selected[0]
    if (type(entry["generation"]) is not int or entry["generation"] < 1
            or str(UUID(entry["intent_id"])) != entry["intent_id"]
            or not isinstance(entry["hostname"], str)
            or any(type(entry[key]) is not bool for key in ("device_enabled", "observed_present", "protected", "enabled"))):
        raise ValueError("Invalid managed target metadata.")
    if not allow_disabled and not entry["device_enabled"]:
        raise ReviewUnavailable("Managed target device is disabled; review its current policy.")
    return entry


@dataclass(frozen=True)
class ManagedRemovalReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    device_id: int
    ip: IPv4Address
    hostname: str
    intent_id: str
    generation: int
    managed_revision: int
    observed_present: bool
    protected: bool
    maintenance_enabled: bool
    ttl_seconds: int
    reason: str
    digest: str


class ManagedRemovalReviews:
    def __init__(self, ttl: int = 600):
        self.ttl = max(1, min(600, ttl))
        self._entries: dict[str, ManagedRemovalReview] = {}
        self._lock = Lock()

    def _prune(self):
        current = time.monotonic()
        self._entries = {key: value for key, value in self._entries.items() if value.expires > current}

    def prepare(self, subject: str, cookie: str, policy: dict, device_id: int, ip: IPv4Address,
                ttl_seconds: int, reason: str = "") -> ManagedRemovalReview:
        if not subject.strip() or not cookie:
            raise ValueError("An authenticated session and CSRF cookie are required.")
        entry = select_managed_target(policy, device_id, ip)
        _, digest = canonical_managed_removal(device_id, ip, policy["revision"], ttl_seconds, reason)
        with self._lock:
            self._prune()
            if len(self._entries) >= 256 or sum(r.subject == subject for r in self._entries.values()) >= 5:
                raise ReviewUnavailable("Too many open managed reviews. Wait for expiry; nothing was queued.")
            review = ManagedRemovalReview(
                token=secrets.token_urlsafe(32), subject=subject,
                cookie_hash=hashlib.sha256(cookie.encode()).hexdigest(), request_id=str(uuid4()),
                expires=time.monotonic() + self.ttl,
                expires_at=datetime.fromtimestamp(time.time() + self.ttl, UTC).isoformat().replace("+00:00", "Z"),
                device_id=device_id, ip=ip, hostname=entry["hostname"], intent_id=entry["intent_id"],
                generation=entry["generation"], managed_revision=policy["revision"],
                observed_present=entry["observed_present"], protected=entry["protected"],
                maintenance_enabled=entry["enabled"], ttl_seconds=ttl_seconds, reason=reason.strip(), digest=digest,
            )
            self._entries[review.token] = review
            return review

    def get(self, token: str, subject: str, cookie: str) -> ManagedRemovalReview:
        with self._lock:
            self._prune()
            review = self._entries.get(token)
            if (review is None or review.subject != subject
                    or not secrets.compare_digest(review.cookie_hash, hashlib.sha256(cookie.encode()).hexdigest())):
                raise ReviewUnavailable("Managed review expired or belongs to another session. Inspect current state before preparing another.")
            return review
