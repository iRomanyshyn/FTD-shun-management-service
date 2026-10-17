"""Offline managed removal coordination; optional reads, no admission/scheduler hook.

One reviewed device/IP at a time. Initialize only an isolated database until the
managed UI, migration and scheduler integration gates have been completed.
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid5

from .managed_intent import canonical_managed_removal
from .managed_shuns import (
    ManagedConflict,
    ManagedShuns,
    _require_operator,
    canonical_managed_change,
)
from .operation_queue import OperationQueue, QueueConflict, QueueFull, stamp
from .safety import mutations_suspended

MAX_HANDOFF_RECORDS = 10000  # Retained request keys; no automatic recycling.


class ManagedRemovals:
    def __init__(self, registry: ManagedShuns, queue: OperationQueue, *, worker_enabled: bool = False):
        if registry.store.path != queue.store.path:
            raise ValueError("Managed removal must use one policy/queue database.")
        self.registry, self.queue, self.store = registry, queue, registry.store
        self.worker_enabled = worker_enabled

    def initialize(self) -> None:
        """Explicit additive migration; never called by normal API/Store startup."""
        with self.store._connection() as db:
            self.registry._registry_state(db, if_present=False)
            if db.execute("SELECT 1 FROM operation_executor WHERE id=1").fetchone() is None:
                raise ManagedConflict("Initialize the existing queue first.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS managed_removal_handoffs (
                    id TEXT PRIMARY KEY,
                    device_id INTEGER NOT NULL REFERENCES devices(id),
                    ip BLOB NOT NULL CHECK(length(ip)=4),
                    intent_id TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK(generation>=1),
                    retirement_request_id TEXT NOT NULL REFERENCES managed_shun_requests(id),
                    predecessor_id TEXT,
                    actor_subject TEXT NOT NULL,
                    actor_display_name TEXT NOT NULL,
                    actor_roles_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('WAITING_ADD','ADMITTING','ADMITTED','EXPIRED','CANCELLED','ATTENTION')),
                    reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_managed_removal_wait_target
                    ON managed_removal_handoffs(device_id,ip) WHERE state='WAITING_ADD';
                CREATE INDEX IF NOT EXISTS idx_managed_removal_wait_state
                    ON managed_removal_handoffs(state,requested_at,id);
                CREATE TRIGGER IF NOT EXISTS managed_removal_authority_immutable
                    BEFORE UPDATE OF id,device_id,ip,intent_id,generation,retirement_request_id,
                        predecessor_id,actor_subject,actor_display_name,actor_roles_json,
                        payload_json,result_json,requested_at,expires_at
                    ON managed_removal_handoffs BEGIN
                        SELECT RAISE(ABORT,'managed removal authority is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS managed_removal_key_retained
                    BEFORE DELETE ON managed_removal_handoffs BEGIN
                        SELECT RAISE(ABORT,'managed removal key is retained'); END;
            """)

    def _event(self, db, row, event, reason=None, *, subject=None, display_name=None, roles=None):
        self.store._insert_event(
            db, event, row["device_id"], IPv4Address(row["ip"]), None,
            subject or row["actor_subject"], display_name or row["actor_display_name"],
            roles if roles is not None else tuple(json.loads(row["actor_roles_json"])), row["id"],
            {"source": "managed_removal", "intent_id": row["intent_id"],
             "generation": row["generation"], "predecessor_id": row["predecessor_id"],
             "reason": reason}, stamp(self.queue._now()),
        )

    def admit(self, request_id: str, device_id: int, ip: IPv4Address, managed_revision: int,
              confirmation_digest: str, subject: str, display_name: str, roles: tuple[str, ...],
              ttl_seconds: int = 900, reason: str = "") -> dict:
        _require_operator(subject, roles)
        try:
            if str(UUID(request_id)) != request_id:
                raise ValueError("Non-canonical UUID")
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("An explicit canonical UUID request key is required.") from error
        payload, digest = canonical_managed_removal(device_id, ip, managed_revision, ttl_seconds, reason)
        if (not isinstance(confirmation_digest, str) or not confirmation_digest.isascii()
                or not hmac.compare_digest(digest, confirmation_digest)):
            raise ValueError("Confirmation does not match stop-maintenance-and-remove.")
        logs = []
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM managed_removal_handoffs WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["actor_subject"] != subject or old["payload_json"] != payload:
                    raise ManagedConflict("Request key was already used for another managed removal.")
                return {**json.loads(old["result_json"]), "replayed": True}
            if mutations_suspended(db):
                raise QueueConflict("Device mutations are suspended for recovery; no cleanup was admitted.")
            if any(db.execute(f"SELECT 1 FROM {table} WHERE id=?", (request_id,)).fetchone()
                   for table in ("operation_requests", "manual_import_batches", "managed_shun_requests")):
                raise ManagedConflict("An existing operation key cannot acquire managed-removal semantics.")
            if db.execute("SELECT COUNT(*) FROM managed_removal_handoffs").fetchone()[0] >= MAX_HANDOFF_RECORDS:
                raise QueueFull("Managed removal ledger is full; no changes were applied.")
            if db.execute("SELECT 1 FROM managed_removal_handoffs WHERE device_id=? AND ip=? AND state='WAITING_ADD'",
                          (device_id, ip.packed)).fetchone():
                raise QueueConflict("This target already has a waiting cleanup; inspect its original request.")
            target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?",
                                (device_id, ip.packed)).fetchone()
            if target is None:
                raise ManagedConflict("Target is not managed; use ordinary removal.")
            device = db.execute("SELECT enabled FROM devices WHERE id=?", (device_id,)).fetchone()
            if device is None or not device[0]:
                raise ManagedConflict("Device is disabled; stop maintenance separately without queuing cleanup.")
            job = db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING')",
                             (device_id, ip.packed)).fetchone()
            waiting = job is not None and job["action"] == "ADD" and job["state"] == "RUNNING"
            if job is not None and job["action"] == "ADD" and not waiting:
                raise QueueConflict("Unstarted one-time ADD conflicts; cancel it explicitly before removal.")
            current = self.queue._now()
            if self.queue._pending_count(db) + int(waiting) > 1000:
                raise QueueFull("Operation queue including reserved cleanups is full.")
            if self.queue._active_request_count(db) >= 2000:
                raise QueueFull("Operation queue is full.")
            if self.queue._recent_request_count(db, subject, current) >= 10:
                raise QueueFull("At most 10 operation submissions per minute per user.")
            retirement_key = str(uuid5(UUID(request_id), "managed-retirement"))
            retire_digest = canonical_managed_change("RETIRE", [(device_id, ip)], managed_revision, 0,
                                                     reason=reason)[2]
            retired = self.registry.apply_change(db, retirement_key, "RETIRE", [(device_id, ip)], managed_revision,
                                                 0, retire_digest, subject, display_name, roles, reason=reason)
            if retired["replayed"]:
                raise ManagedConflict("Derived retirement key was already used; prepare a new reviewed request.")
            result = {"operation_id": request_id, "status": "accepted", "replayed": False,
                      "waiting_for_add": waiting}
            db.execute("INSERT INTO managed_removal_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)", (
                request_id, device_id, ip.packed, target["intent_id"], target["generation"], retirement_key,
                job["id"] if waiting else None, subject, display_name, json.dumps(roles), payload,
                json.dumps(result), stamp(current), stamp(current + timedelta(seconds=ttl_seconds)),
                "WAITING_ADD" if waiting else "ADMITTING",
            ))
            if not waiting:
                _, logs = self.queue.apply_enqueue(db, request_id, [(device_id, ip)], subject,
                                                  display_name, roles, ttl_seconds, scope="managed_device_removal")
                self._bind_deadline(db, request_id, stamp(current), stamp(current + timedelta(seconds=ttl_seconds)))
                db.execute("UPDATE managed_removal_handoffs SET state='ADMITTED' WHERE id=?", (request_id,))
            row = db.execute("SELECT * FROM managed_removal_handoffs WHERE id=?", (request_id,)).fetchone()
            self._event(db, row, "MANAGED_SHUN_REMOVAL_ADMITTED")
            self.queue._bump(db)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        print(json.dumps({"event": "managed_shun.removal.admitted", "request_id": request_id,
                          "actor_subject": subject, "waiting_for_add": waiting}), flush=True)
        return result

    def advance(self, owner: str, limit: int = 16) -> int:
        """Bounded leased handoff step, called once before an opted-in cycle cutoff.

        Admit removal only after the predecessor settles, under the original
        deadline. No RPC, independent executor or automatic ADD replay exists.
        """
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Advance at most 16 handoffs per call.")
        logs = []
        admitted = 0
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if mutations_suspended(db):
                return 0
            current = self.queue._now()
            lease = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            if not owner or lease["owner"] != owner or not lease["lease_until"] or lease["lease_until"] <= stamp(current):
                raise QueueConflict("Executor lease lost; no cleanup was advanced.")
            rows = db.execute("""SELECT h.* FROM managed_removal_handoffs h
                LEFT JOIN operation_jobs j ON j.id=h.predecessor_id
                LEFT JOIN managed_shun_targets t ON t.device_id=h.device_id AND t.ip=h.ip
                WHERE h.state='WAITING_ADD' AND (h.expires_at<=? OR j.id IS NULL OR j.state!='RUNNING'
                    OR t.intent_id IS NULL OR t.enabled=1 OR t.intent_id!=h.intent_id OR t.generation!=h.generation)
                ORDER BY h.requested_at,h.id LIMIT ?""", (stamp(current), limit)).fetchall()
            for row in rows:
                current = self.queue._now()
                if lease["lease_until"] <= stamp(current):
                    raise QueueConflict("Executor lease expired during handoff; no changes were committed.")
                target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?",
                                    (row["device_id"], row["ip"])).fetchone()
                if target is None or target["enabled"] or target["intent_id"] != row["intent_id"] or target["generation"] != row["generation"]:
                    self._settle(db, row, "ATTENTION", "Managed intent changed; review cleanup scope.")
                    continue
                remaining = int((self._deadline(row) - current).total_seconds())
                if remaining < 1:
                    self._settle(db, row, "EXPIRED", "Original removal authorization expired; maintenance remains stopped.")
                    continue
                predecessor = db.execute("SELECT * FROM operation_jobs WHERE id=?", (row["predecessor_id"],)).fetchone()
                if predecessor is None or predecessor["action"] != "ADD" or predecessor["device_id"] != row["device_id"] or predecessor["ip"] != row["ip"]:
                    self._settle(db, row, "ATTENTION", "Predecessor evidence missing or inconsistent; cleanup was not admitted.")
                    continue
                if predecessor["state"] == "RUNNING":
                    continue
                # A captured RUNNING ADD can return to QUEUED only through the
                # exact deferred-before-write result. Supersede that same job,
                # not another user's unrelated new ADD or an uncertain result.
                db.execute("SAVEPOINT managed_cleanup_handoff")
                try:
                    if predecessor["state"] == "QUEUED":
                        if predecessor["dispatch_kind"] is not None:
                            raise QueueConflict("Predecessor has an inconsistent deferral marker.")
                        self.queue._finish(db, predecessor, "CANCELLED", "Known pre-write deferral superseded by reviewed managed removal")
                    db.execute("UPDATE managed_removal_handoffs SET state='ADMITTING',reason=NULL WHERE id=?", (row["id"],))
                    _, entries = self.queue.apply_enqueue(
                        db, row["id"], [(row["device_id"], IPv4Address(row["ip"]))],
                        row["actor_subject"], row["actor_display_name"], tuple(json.loads(row["actor_roles_json"])),
                        remaining, scope="managed_device_removal",
                    )
                    self._bind_deadline(db, row["id"], row["requested_at"], row["expires_at"])
                    db.execute("UPDATE managed_removal_handoffs SET state='ADMITTED' WHERE id=?", (row["id"],))
                except (QueueConflict, QueueFull, ValueError) as error:
                    db.execute("ROLLBACK TO managed_cleanup_handoff")
                    self._settle(db, row, "ATTENTION", str(error))
                else:
                    logs.extend(entries)
                    admitted += 1
                    self._event(db, row, "MANAGED_SHUN_CLEANUP_QUEUED", "Predecessor settled; separate removal authorization retained.")
                    self.queue._bump(db)
                finally:
                    db.execute("RELEASE managed_cleanup_handoff")
            logs.extend({"event": "managed_shun.cleanup.settled", "request_id": item["id"], "state": item["state"]}
                        for item in db.execute("""SELECT id,state FROM managed_removal_handoffs
                            WHERE id IN (SELECT value FROM json_each(?)) AND state!='WAITING_ADD'""",
                            (json.dumps([row["id"] for row in rows]),)))
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return admitted

    def has_waiting(self) -> bool:
        with self.store._connection() as db:
            return (not mutations_suspended(db) and self.queue._handoffs_present(db)
                    and db.execute("SELECT 1 FROM managed_removal_handoffs WHERE state='WAITING_ADD' LIMIT 1").fetchone() is not None)

    def advance_if_present(self, owner: str) -> int:
        with self.store._connection() as db:
            present = self.queue._handoffs_present(db)
        return self.advance(owner) if present else 0

    @staticmethod
    def _deadline(row):
        return datetime.fromisoformat(row["expires_at"])

    @staticmethod
    def _bind_deadline(db, request_id, requested_at, deadline):
        db.execute("""UPDATE operation_requests SET requested_at=?,expires_at=MIN(expires_at,?)
            WHERE id=?""", (requested_at, deadline, request_id))

    def _settle(self, db, row, state, reason):
        db.execute("UPDATE managed_removal_handoffs SET state=?,reason=? WHERE id=?", (state, reason, row["id"]))
        self._event(db, row, f"MANAGED_SHUN_CLEANUP_{state}", reason)
        self.queue._bump(db)

    def cancel_waiting(self, request_id: str, subject: str, display_name: str,
                       roles: tuple[str, ...]) -> bool:
        _require_operator(subject, roles)
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM managed_removal_handoffs WHERE id=?", (request_id,)).fetchone()
            if row is None or (row["actor_subject"] != subject and "Administrator" not in roles):
                raise PermissionError("Waiting cleanup cancellation is not permitted.")
            if row["state"] == "CANCELLED":
                return False
            if row["state"] != "WAITING_ADD":
                raise QueueConflict("Not waiting for ADD; inspect/cancel the admitted queue request instead.")
            db.execute("UPDATE managed_removal_handoffs SET state='CANCELLED',reason='Cancelled by operator' WHERE id=?",
                       (request_id,))
            self._event(db, row, "MANAGED_SHUN_CLEANUP_CANCELLED", "Maintenance remains stopped; ADD was not cancelled.",
                        subject=subject, display_name=display_name, roles=roles)
            self.queue._bump(db)
        print(json.dumps({"event": "managed_shun.cleanup.cancelled", "request_id": request_id,
                          "actor_subject": subject}), flush=True)
        return True

    def snapshot(self) -> dict:
        with self.store._connection() as db:
            db.execute("BEGIN")
            return self._snapshot(db)

    def snapshot_if_present(self) -> dict:
        """Optional display only; absence is not migration, invalid schema is error."""
        with self.store._connection() as db:
            db.execute("BEGIN")
            if not self.queue._handoffs_present(db):
                return {"initialized": False, "counts": {}, "items": [], "display_limit": 20,
                        "scheduler_integration_available": self.worker_enabled, "admission_enabled": False, "read_only": True}
            return {**self._snapshot(db), "initialized": True, "admission_enabled": False, "read_only": True}

    def _snapshot(self, db) -> dict:
        counts = {row["state"]: row["n"] for row in db.execute(
            "SELECT state,COUNT(*) AS n FROM managed_removal_handoffs GROUP BY state")}
        rows = db.execute("""SELECT h.id,h.device_id,d.hostname AS device_hostname,h.ip,h.state,h.reason,
                h.predecessor_id,h.actor_subject,h.actor_display_name,h.requested_at,h.expires_at
                ,(SELECT j.state FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                    WHERE l.request_id=h.id LIMIT 1) AS queue_state
                FROM managed_removal_handoffs h JOIN devices d ON d.id=h.device_id
                ORDER BY CASE WHEN h.state='WAITING_ADD' OR queue_state IN ('RUNNING','QUEUED') THEN 0
                    WHEN h.state='ATTENTION' OR queue_state IN ('FAILED','UNVERIFIED') THEN 1 ELSE 2 END,
                h.requested_at DESC,h.id LIMIT 20""").fetchall()
        return {"counts": counts, "items": [{**dict(row), "ip": str(IPv4Address(row["ip"]))} for row in rows],
                "display_limit": 20, "scheduler_integration_available": self.worker_enabled}
