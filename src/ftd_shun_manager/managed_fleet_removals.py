"""Offline atomic fleet retirement/cleanup admission; no HTTP or startup hook.

Explicit ordered mode may reserve the entire scope behind captured RUNNING ADD.
Default ready-only semantics and receipts are unchanged. No desired restoration.
"""

import hmac
import json
import sqlite3
from datetime import timedelta
from ipaddress import IPv4Address
from math import ceil
from uuid import UUID, uuid5

from .managed_fleet_waits import initialize_waits
from .managed_intent import (
    canonical_managed_change,
    canonical_managed_fleet_removal,
    canonical_managed_fleet_scope,
)
from .managed_safety import (
    fleet_key_reserved,
    fleet_target_held,
    fleet_waits_present,
    managed_state,
)
from .managed_scope import ManagedRemovalScopes
from .managed_shuns import ManagedConflict, _require_operator
from .operation_queue import QueueConflict, QueueFull, stamp
from .safety import mutations_suspended

MAX_FLEET_RECORDS = 10000  # Retained keys, independent of ordinary history.


class ManagedFleetRemovals:
    def __init__(self, registry, queue):
        if registry.store.path != queue.store.path:
            raise ValueError("Fleet removal must use one policy/queue database.")
        self.registry, self.queue, self.store = registry, queue, registry.store

    def initialize(self) -> None:
        """Explicit isolated migration; not called by any deployed service."""
        with self.store._connection() as db:
            if managed_state(db) is None or not db.execute(
                "SELECT 1 FROM operation_executor WHERE id=1",
            ).fetchone():
                raise ManagedConflict("Initialize the registry and queue explicitly first.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS managed_fleet_removals (
                    id TEXT PRIMARY KEY,
                    retirement_request_id TEXT UNIQUE REFERENCES managed_shun_requests(id),
                    actor_subject TEXT NOT NULL,
                    actor_display_name TEXT NOT NULL,
                    actor_roles_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    phase TEXT NOT NULL CHECK(phase IN ('ADMITTING','ADMITTED'))
                );
                CREATE TRIGGER IF NOT EXISTS managed_fleet_authority_immutable
                    BEFORE UPDATE OF id,retirement_request_id,actor_subject,actor_display_name,
                        actor_roles_json,payload_json,result_json,requested_at,expires_at
                    ON managed_fleet_removals BEGIN
                        SELECT RAISE(ABORT,'managed fleet authority is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS managed_fleet_phase_monotonic
                    BEFORE UPDATE OF phase ON managed_fleet_removals
                    WHEN OLD.phase!='ADMITTING' OR NEW.phase!='ADMITTED' BEGIN
                        SELECT RAISE(ABORT,'managed fleet admission phase cannot be reset'); END;
                CREATE TRIGGER IF NOT EXISTS managed_fleet_key_retained
                    BEFORE DELETE ON managed_fleet_removals BEGIN
                        SELECT RAISE(ABORT,'managed fleet key is retained'); END;
            """)
            initialize_waits(db)

    def admit(self, request_id: str, reviewed: dict, confirmation_digest: str,
              subject: str, display_name: str, roles: tuple[str, ...],
              ttl_seconds: int = 900, reason: str = "", *, ordered_wait: bool = False) -> dict:
        """Commit all targets together. Never call the per-target coordinator."""
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            result, logs = self.apply_admit(db, request_id, reviewed, confirmation_digest,
                                           subject, display_name, roles, ttl_seconds, reason, ordered_wait=ordered_wait)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return result

    def apply_admit(self, db: sqlite3.Connection, request_id: str, reviewed: dict,
                    confirmation_digest: str, subject: str, display_name: str, roles: tuple[str, ...],
                    ttl_seconds: int = 900, reason: str = "", *, ordered_wait: bool = False) -> tuple[dict, list[dict]]:
        """Trusted composition: caller owns commit/logging; caught errors roll back."""
        if not db.in_transaction:
            raise ValueError("Fleet admission requires a caller-owned write transaction.")
        _require_operator(subject, roles)
        try:
            if str(UUID(request_id)) != request_id:
                raise ValueError("Non-canonical UUID")
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("An explicit canonical UUID request key is required.") from error
        scope = {key: value for key, value in reviewed.items()
                 if key not in {"scope_digest", "execution_available", "read_only"}}
        canonical, scope_digest = canonical_managed_fleet_scope(scope)
        if reviewed.get("scope_digest") != scope_digest:
            raise ValueError("Invalid reviewed fleet scope binding.")
        # Freeze caller-owned mutable objects before acquiring durable authority.
        frozen = json.loads(canonical)
        del frozen["version"], frozen["scope"]
        payload, digest = canonical_managed_fleet_removal(frozen, ttl_seconds, reason, ordered_wait=ordered_wait)
        if (not isinstance(confirmation_digest, str) or not confirmation_digest.isascii()
                or not hmac.compare_digest(digest, confirmation_digest)):
            raise ValueError("Confirmation does not match the exact fleet removal.")
        db.execute("SAVEPOINT managed_fleet_admission")
        try:
            result = self._apply(db, request_id, frozen, scope_digest, payload, subject,
                                 display_name, roles, ttl_seconds, reason, ordered_wait)
        except Exception:
            db.execute("ROLLBACK TO managed_fleet_admission")
            db.execute("RELEASE managed_fleet_admission")
            raise
        db.execute("RELEASE managed_fleet_admission")
        return result

    def _apply(self, db, key, scope, scope_digest, payload, subject, display_name, roles, ttl, reason, ordered_wait):
        old = db.execute("SELECT * FROM managed_fleet_removals WHERE id=?", (key,)).fetchone()
        if old is not None:
            if old["actor_subject"] != subject or old["payload_json"] != payload or old["phase"] != "ADMITTED":
                raise ManagedConflict("Request key was already used for another fleet removal.")
            return {**json.loads(old["result_json"]), "replayed": True}, []
        if mutations_suspended(db):
            raise QueueConflict("Device mutations are suspended for recovery; no fleet cleanup was admitted.")
        if fleet_key_reserved(db, key) or self._key_used(db, key):
            raise ManagedConflict("An existing key cannot acquire fleet-removal semantics.")
        if db.execute("SELECT COUNT(*) FROM managed_fleet_removals").fetchone()[0] >= MAX_FLEET_RECORDS:
            raise QueueFull("Fleet removal ledger is full; no changes were applied.")
        now = self.queue._now()
        current = ManagedRemovalScopes.require_current(db, {**scope, "scope_digest": scope_digest})
        if any(not target["device_enabled"] for target in current["targets"]):
            raise ManagedConflict("Fleet scope contains a disabled device; no targets were changed or queued.")
        ip = IPv4Address(scope["ip"])
        targets = [(entry["device_id"], ip) for entry in current["targets"]]
        predecessors = []
        for device_id, _ in targets:
            job = db.execute("""SELECT * FROM operation_jobs WHERE device_id=? AND ip=?
                    AND action='ADD' AND state IN ('QUEUED','RUNNING')""", (device_id, ip.packed)).fetchone()
            if job is not None:
                if not ordered_wait or job["state"] != "RUNNING":
                    raise QueueConflict("Fleet scope has unfinished ADD; no changes were applied. QUEUED ADD requires explicit cancellation; RUNNING ADD requires ordered mode.")
                if job["dispatch_kind"] != "ADD":
                    raise QueueConflict("RUNNING ADD has inconsistent dispatch evidence; no changes were applied.")
                predecessors.append({"job_id": job["id"], "device_id": device_id})
            if fleet_target_held(db, device_id, ip):
                raise QueueConflict("Fleet scope already has waiting cleanup; inspect its original request.")
            if self.queue._handoffs_present(db) and db.execute("""SELECT 1 FROM managed_removal_handoffs
                    WHERE device_id=? AND ip=? AND state='WAITING_ADD'""", (device_id, ip.packed)).fetchone():
                raise QueueConflict("Fleet scope has waiting cleanup; inspect its original request. No changes were applied.")
        if predecessors:
            if not fleet_waits_present(db):
                raise ManagedConflict("Ordered fleet schema is not initialized; nothing was admitted.")
            if self.queue._pending_count(db) + len(targets) > 1000:
                raise QueueFull("Operation queue including reserved fleet targets is full.")
            if self.queue._active_request_count(db) >= 2000:
                raise QueueFull("Operation queue is full.")
            if self.queue._recent_request_count(db, subject, now) >= 10:
                raise QueueFull("At most 10 operation submissions per minute per user.")
        retiring = [(entry["device_id"], ip) for entry in current["targets"] if entry["maintenance_enabled"]]
        retirement_key = str(uuid5(UUID(key), "managed-fleet-retirement")) if retiring else None
        if retirement_key is not None:
            if retirement_key == key or fleet_key_reserved(db, retirement_key) or self._key_used(db, retirement_key):
                raise ManagedConflict("Derived retirement key was already used; prepare a new reviewed request.")
            retired = self.registry.apply_change(
                db, retirement_key, "RETIRE", retiring, scope["managed_revision"], 0,
                canonical_managed_change("RETIRE", retiring, scope["managed_revision"], 0, reason=reason)[2],
                subject, display_name, roles, reason=reason,
            )
            revision = retired["managed_revision"]
        else:
            revision = scope["managed_revision"]
        requested, deadline = stamp(now), stamp(now + timedelta(seconds=ttl))
        result = {"operation_id": key, "status": "accepted", "replayed": False,
                  "target_count": len(targets), "retired_targets": len(retiring), "managed_revision": revision}
        if ordered_wait:
            result["waiting_for_add"] = bool(predecessors)
        db.execute("INSERT INTO managed_fleet_removals VALUES (?,?,?,?,?,?,?,?,?,'ADMITTING')", (
            key, retirement_key, subject, display_name, json.dumps(roles), payload, json.dumps(result), requested, deadline,
        ))
        remaining = ceil((now + timedelta(seconds=ttl) - self.queue._now()).total_seconds())
        if remaining < 1:
            raise QueueConflict("Fleet authorization expired during admission; nothing was committed.")
        logs = []
        if predecessors:
            db.execute("INSERT INTO managed_fleet_waits VALUES (?,?,?,'WAITING_ADD',NULL)",
                       (key, len(targets), json.dumps(predecessors, sort_keys=True, separators=(",", ":"))))
        else:
            _, logs = self.queue.apply_enqueue(db, key, targets, subject, display_name, roles, remaining,
                                               scope="managed_fleet_removal")
            db.execute("UPDATE operation_requests SET requested_at=?,expires_at=MIN(expires_at,?) WHERE id=?",
                       (requested, deadline, key))
        db.execute("UPDATE managed_fleet_removals SET phase='ADMITTED' WHERE id=?", (key,))
        self.store._insert_event(db, "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED", None, ip, None,
                                 subject, display_name, roles, key,
                                 {"source": "managed_fleet_removal", "target_count": len(targets),
                                  "retired_targets": len(retiring), "managed_revision": revision,
                                  "retirement_request_id": retirement_key,
                                  "waiting_for_add": bool(predecessors)}, requested)
        if self.queue._now() >= now + timedelta(seconds=ttl):
            raise QueueConflict("Fleet authorization expired during admission; nothing was committed.")
        self.queue._bump(db)
        logs.append({"event": "managed_shun.fleet_removal.admitted", "request_id": key,
                     "actor_subject": subject, "target_count": len(targets), "retired_targets": len(retiring)})
        return result, logs

    @staticmethod
    def _key_used(db, key):
        tables = ["operation_requests", "manual_import_batches", "managed_shun_requests"]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_removal_handoffs'").fetchone():
            tables.append("managed_removal_handoffs")
        return any(db.execute(f"SELECT 1 FROM {table} WHERE id=?", (key,)).fetchone() for table in tables)
