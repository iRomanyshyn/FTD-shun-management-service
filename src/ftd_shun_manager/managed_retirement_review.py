"""Frozen policy-only revocation reviews, distinct from device cleanup consent."""

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from threading import Lock
from uuid import uuid4

from .import_review import ReviewUnavailable
from .managed_intent import canonical_managed_change
from .managed_review import select_managed_target


@dataclass(frozen=True)
class ManagedRetirementReview:
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
    device_enabled: bool
    reason: str
    digest: str
    intent_format: int = 1


class ManagedRetirementReviews:
    def __init__(self, ttl: int = 600):
        self.ttl = max(1, min(600, ttl))
        self._entries: dict[str, ManagedRetirementReview] = {}
        self._lock = Lock()

    def _prune(self):
        self._entries = {key: value for key, value in self._entries.items() if value.expires > time.monotonic()}

    def prepare(self, subject: str, cookie: str, policy: dict, device_id: int, ip: IPv4Address,
                reason: str = "") -> ManagedRetirementReview:
        if not subject.strip() or not cookie:
            raise ValueError("An authenticated session and CSRF cookie are required.")
        # Revocation must remain possible on disabled/protected/missing targets.
        entry = select_managed_target(policy, device_id, ip, allow_disabled=True)
        intent_format = policy.get('intent_format', 1)
        if type(intent_format) is not int or intent_format not in {1, 2}:
            raise ValueError('Retirement review requires an explicit supported policy format.')
        if not entry["enabled"]:
            raise ReviewUnavailable("Maintenance is already stopped. Review current state.")
        _, _, digest = canonical_managed_change("RETIRE", [(device_id, ip)], policy["revision"], 0, reason=reason)
        with self._lock:
            self._prune()
            if len(self._entries) >= 256 or sum(r.subject == subject for r in self._entries.values()) >= 5:
                raise ReviewUnavailable("Too many open retirement reviews. Wait for expiry; nothing was changed.")
            review = ManagedRetirementReview(
                token=secrets.token_urlsafe(32), subject=subject,
                cookie_hash=hashlib.sha256(cookie.encode()).hexdigest(), request_id=str(uuid4()),
                expires=time.monotonic() + self.ttl,
                expires_at=datetime.fromtimestamp(time.time() + self.ttl, UTC).isoformat().replace("+00:00", "Z"),
                device_id=device_id, ip=ip, hostname=entry["hostname"], intent_id=entry["intent_id"],
                generation=entry["generation"], managed_revision=policy["revision"],
                observed_present=entry["observed_present"], protected=entry["protected"],
                device_enabled=entry["device_enabled"], reason=reason.strip(), digest=digest,
                intent_format=intent_format,
            )
            self._entries[review.token] = review
            return review

    def get(self, token: str, subject: str, cookie: str) -> ManagedRetirementReview:
        with self._lock:
            self._prune()
            review = self._entries.get(token)
            if (review is None or review.subject != subject
                    or not secrets.compare_digest(review.cookie_hash, hashlib.sha256(cookie.encode()).hexdigest())):
                raise ReviewUnavailable("Retirement review expired or belongs to another session. Inspect current state before preparing another.")
            return review
