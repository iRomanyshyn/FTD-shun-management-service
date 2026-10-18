"""Ephemeral exact-scope removal reviews. Preparation never admits work."""

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from threading import Lock
from uuid import UUID, uuid4

from .import_review import ReviewUnavailable
from .managed_intent import (
    canonical_managed_fleet_removal,
    canonical_managed_fleet_scope,
    canonical_managed_removal,
)


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
    scope: str = "device"

    def payload(self):
        return {"device_id": self.device_id, "ip": str(self.ip), "managed_revision": self.managed_revision,
                "intent_id": self.intent_id, "generation": self.generation, "ttl_seconds": self.ttl_seconds,
                "reason": self.reason, "confirmation_digest": self.digest}


@dataclass(frozen=True)
class ManagedFleetTarget:
    device_id: int
    hostname: str
    device_enabled: bool
    observed_present: bool
    maintenance_enabled: bool
    intent_id: str | None
    generation: int | None


@dataclass(frozen=True)
class ManagedFleetRemovalReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    ip: IPv4Address
    managed_revision: int
    managed_initialized: bool
    protected_revision: int
    protected: bool
    targets: tuple[ManagedFleetTarget, ...]
    scope_digest: str
    ttl_seconds: int
    reason: str
    digest: str
    scope: str = "fleet"
    ordered_wait: bool = False

    def payload(self):
        return {"reviewed": {"ip": str(self.ip), "managed_initialized": self.managed_initialized,
                             "managed_revision": self.managed_revision, "protected_revision": self.protected_revision,
                             "protected": self.protected, "targets": [asdict(target) for target in self.targets],
                             "scope_digest": self.scope_digest},
                "ttl_seconds": self.ttl_seconds, "reason": self.reason, "ordered_wait": self.ordered_wait,
                "confirmation_digest": self.digest}


class ManagedRemovalReviews:
    def __init__(self, ttl: int = 600):
        self.ttl = max(1, min(600, ttl))
        self._entries: dict[str, ManagedRemovalReview | ManagedFleetRemovalReview] = {}
        self._lock = Lock()

    def _prune(self):
        current = time.monotonic()
        self._entries = {key: value for key, value in self._entries.items() if value.expires > current}

    def prepare(self, subject: str, cookie: str, policy: dict, device_id: int, ip: IPv4Address,
                ttl_seconds: int, reason: str = "") -> ManagedRemovalReview:
        entry = select_managed_target(policy, device_id, ip)
        _, digest = canonical_managed_removal(device_id, ip, policy["revision"], ttl_seconds, reason)
        return self._save(ManagedRemovalReview, subject, cookie,
                          device_id=device_id, ip=ip, hostname=entry["hostname"], intent_id=entry["intent_id"],
                          generation=entry["generation"], managed_revision=policy["revision"],
                          observed_present=entry["observed_present"], protected=entry["protected"],
                          maintenance_enabled=entry["enabled"], ttl_seconds=ttl_seconds, reason=reason.strip(), digest=digest)

    def prepare_fleet(self, subject: str, cookie: str, view: dict, ip: IPv4Address,
                      ttl_seconds: int, reason: str = "", *, ordered_wait: bool = False) -> ManagedFleetRemovalReview:
        scope = {key: value for key, value in view.items()
                 if key not in {"scope_digest", "execution_available", "read_only"}}
        _, scope_digest = canonical_managed_fleet_scope(scope)
        if view.get("scope_digest") != scope_digest or str(ip) != scope["ip"]:
            raise ValueError("Fleet view does not match the requested scope.")
        _, digest = canonical_managed_fleet_removal(scope, ttl_seconds, reason, ordered_wait=ordered_wait)
        return self._save(ManagedFleetRemovalReview, subject, cookie,
                          ip=ip, managed_revision=scope["managed_revision"], managed_initialized=scope["managed_initialized"],
                          protected_revision=scope["protected_revision"], protected=scope["protected"],
                          targets=tuple(ManagedFleetTarget(**row) for row in sorted(scope["targets"], key=lambda row: row["device_id"])),
                          scope_digest=scope_digest, ttl_seconds=ttl_seconds, reason=reason.strip(), digest=digest,
                          ordered_wait=ordered_wait)

    def _save(self, review_type, subject, cookie, **fields):
        if not subject.strip() or not cookie:
            raise ValueError("An authenticated session and CSRF cookie are required.")
        with self._lock:
            self._prune()
            if len(self._entries) >= 256 or sum(r.subject == subject for r in self._entries.values()) >= 5:
                raise ReviewUnavailable("Too many open managed reviews. Wait for expiry; nothing was queued.")
            review = review_type(
                token=secrets.token_urlsafe(32), subject=subject,
                cookie_hash=hashlib.sha256(cookie.encode()).hexdigest(), request_id=str(uuid4()),
                expires=time.monotonic() + self.ttl,
                expires_at=datetime.fromtimestamp(time.time() + self.ttl, UTC).isoformat().replace("+00:00", "Z"),
                **fields,
            )
            self._entries[review.token] = review
            return review

    def get(self, token: str, subject: str, cookie: str) -> ManagedRemovalReview | ManagedFleetRemovalReview:
        with self._lock:
            self._prune()
            review = self._entries.get(token)
            if (review is None or review.subject != subject
                    or not secrets.compare_digest(review.cookie_hash, hashlib.sha256(cookie.encode()).hexdigest())):
                raise ReviewUnavailable("Managed review expired or belongs to another session. Inspect current state before preparing another.")
            return review


def validate_removal_receipt(review, value):
    """Validate historical admission, never infer current execution from a receipt."""
    expected = {"operation_id", "status", "replayed"}
    if (not isinstance(value, dict) or value.get("operation_id") != review.request_id
            or value.get("status") != "accepted" or type(value.get("replayed")) is not bool):
        raise ValueError("Invalid cleanup receipt")
    if review.scope == "device":
        expected.add("waiting_for_add")
        if type(value.get("waiting_for_add")) is not bool:
            raise ValueError("Invalid single-target cleanup receipt")
    else:
        expected.update({"target_count", "retired_targets", "managed_revision"})
        retired = sum(target.maintenance_enabled for target in review.targets)
        for key, count in (("target_count", len(review.targets)), ("retired_targets", retired),
                           ("managed_revision", review.managed_revision + int(retired > 0))):
            if type(value.get(key)) is not int or value[key] != count:
                raise ValueError("Invalid fleet cleanup receipt")
        if review.ordered_wait:
            expected.add("waiting_for_add")
            if type(value.get("waiting_for_add")) is not bool:
                raise ValueError("Invalid ordered cleanup receipt")
    if set(value) != expected:
        raise ValueError("Unexpected cleanup receipt fields")
    return value
