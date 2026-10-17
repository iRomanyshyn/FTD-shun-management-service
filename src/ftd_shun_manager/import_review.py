"""Bounded, ephemeral browser reviews. Tokens are not admission authority."""

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from threading import Lock
from uuid import uuid4

from .import_intent import canonical_import


class ReviewUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class ImportReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    targets: tuple[tuple[int, IPv4Address], ...]
    devices: tuple[tuple[int, str], ...]
    policy_revision: int
    label: str
    reason: str
    digest: str
    counts: tuple[tuple[str, int], ...]

    def payload(self) -> dict:
        return {
            "targets": [{"device_id": device, "ip": str(ip)} for device, ip in self.targets],
            "policy_revision": self.policy_revision,
            "label": self.label, "reason": self.reason, "confirmation_digest": self.digest,
        }


class ImportReviews:
    def __init__(self, ttl: int = 600):
        self.ttl = min(600, ttl)
        self._entries: dict[str, ImportReview] = {}
        self._lock = Lock()

    @staticmethod
    def _cookie_hash(cookie: str) -> str:
        return hashlib.sha256(cookie.encode()).hexdigest()

    def _prune(self) -> None:
        now = time.monotonic()
        self._entries = {key: value for key, value in self._entries.items() if value.expires > now}

    def prepare(self, subject: str, cookie: str, preview: dict, label: str, reason: str) -> ImportReview:
        targets = [(device["id"], IPv4Address(row["ip"])) for row in preview["rows"]
                   if row["status"] == "Ready" for device in row["devices"]
                   if not device["already_shunned"]]
        targets, _, digest = canonical_import(targets, preview["policy_revision"], label, reason)
        with self._lock:
            self._prune()
            if len(self._entries) >= 256 or sum(r.subject == subject for r in self._entries.values()) >= 5:
                raise ReviewUnavailable("Too many open reviews. Wait for a review to expire; nothing was queued.")
            review = ImportReview(
                token=secrets.token_urlsafe(32), subject=subject, cookie_hash=self._cookie_hash(cookie),
                request_id=str(uuid4()), expires=time.monotonic() + self.ttl,
                expires_at=datetime.fromtimestamp(time.time() + self.ttl, UTC).isoformat().replace("+00:00", "Z"),
                targets=tuple(targets), devices=tuple((d["id"], d["hostname"]) for d in preview["devices"]),
                policy_revision=preview["policy_revision"], label=label.strip(), reason=reason.strip(),
                digest=digest, counts=tuple(preview["counts"].items()),
            )
            self._entries[review.token] = review
            return review

    def get(self, token: str, subject: str, cookie: str) -> ImportReview:
        with self._lock:
            self._prune()
            review = self._entries.get(token)
            if (review is None or review.subject != subject
                    or not secrets.compare_digest(review.cookie_hash, self._cookie_hash(cookie))):
                raise ReviewUnavailable(
                    "Review expired, unavailable or belongs to another session. Check Queue before preparing a new review."
                )
            return review
