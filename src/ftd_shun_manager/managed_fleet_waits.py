"""Whole-scope cleanup barrier; no initialization, RPC or independent executor."""

import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from math import ceil
from uuid import UUID

from .managed_intent import canonical_managed_fleet_removal
from .managed_safety import fleet_waits_present
from .managed_shuns import _require_operator
from .operation_queue import QueueConflict, QueueFull, stamp
from .safety import mutations_suspended


def initialize_waits(db):
    """Explicit additive migration invoked only by offline fleet initialization."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS managed_fleet_waits (
            id TEXT PRIMARY KEY REFERENCES managed_fleet_removals(id),
            target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 1000),
            predecessors_json TEXT NOT NULL CHECK(json_valid(predecessors_json)),
            state TEXT NOT NULL CHECK(state IN ('WAITING_ADD','ADMITTING','ADMITTED','EXPIRED','CANCELLED','ATTENTION')),
            reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fleet_wait_state ON managed_fleet_waits(state,id);
        CREATE TRIGGER IF NOT EXISTS fleet_wait_authority_immutable
            BEFORE UPDATE OF id,target_count,predecessors_json ON managed_fleet_waits BEGIN
                SELECT RAISE(ABORT,'fleet wait evidence is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS fleet_wait_key_retained
            BEFORE DELETE ON managed_fleet_waits BEGIN
                SELECT RAISE(ABORT,'fleet wait evidence is retained'); END;
        CREATE TRIGGER IF NOT EXISTS fleet_wait_phase_monotonic
            BEFORE UPDATE OF state ON managed_fleet_waits WHEN NOT (
                (OLD.state='WAITING_ADD' AND NEW.state IN ('ADMITTING','EXPIRED','CANCELLED','ATTENTION'))
                OR (OLD.state='ADMITTING' AND NEW.state IN ('ADMITTED','CANCELLED'))
            ) BEGIN SELECT RAISE(ABORT,'fleet wait cannot be rearmed'); END;
    """)


class ManagedFleetWaits:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError("Fleet cleanup must use the shared queue database.")
        self.store, self.queue = store, queue

    def has_waiting(self) -> bool:
        with self.store._connection() as db:
            return (not mutations_suspended(db) and fleet_waits_present(db) and db.execute(
                "SELECT 1 FROM managed_fleet_waits WHERE state='WAITING_ADD' LIMIT 1",
            ).fetchone() is not None)

    def advance_if_present(self, owner: str, limit: int = 16) -> int:
        with self.store._connection() as db:
            present = fleet_waits_present(db)
        return self.advance(owner, limit) if present else 0

    def advance(self, owner: str, limit: int = 16) -> int:
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Advance at most 16 fleet roots per call.")
        logs, admitted = [], 0
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if mutations_suspended(db):
                return 0
            lease = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            self._require_lease(lease, owner)
            # A whole scope waits for all captured ADDs, without starving later
            # roots whose predecessors have settled. Invalid JSON is selected
            # for explicit attention rather than treated as an empty barrier.
            rows = db.execute("""SELECT w.*,r.payload_json,r.actor_subject,r.actor_display_name,
                    r.actor_roles_json,r.requested_at,r.expires_at,r.phase
                FROM managed_fleet_waits w JOIN managed_fleet_removals r ON r.id=w.id
                WHERE w.state='WAITING_ADD' AND (r.expires_at<=? OR NOT EXISTS (
                    SELECT 1 FROM json_each(CASE WHEN json_valid(w.predecessors_json)
                        THEN w.predecessors_json ELSE '[]' END) p
                    JOIN operation_jobs j ON j.id=json_extract(CASE WHEN json_valid(p.value)
                        THEN p.value ELSE '{}' END,'$.job_id')
                    WHERE j.state='RUNNING' AND j.action='ADD'))
                ORDER BY r.requested_at,w.id LIMIT ?""", (stamp(self.queue._now()), limit)).fetchall()
            for row in rows:
                self._require_lease(lease, owner)
                if row["expires_at"] <= stamp(self.queue._now()):
                    self._settle(db, row, "EXPIRED", "Original cleanup authorization expired; maintenance remains stopped.", logs)
                    continue
                db.execute("SAVEPOINT fleet_cleanup_promotion")
                try:
                    targets, predecessors, roles = self._validate(db, row)
                    for job in predecessors:
                        if job["state"] == "QUEUED":
                            self.queue._finish(db, job, "CANCELLED", "Known pre-write deferral superseded by reviewed fleet cleanup")
                    db.execute("UPDATE managed_fleet_waits SET state='ADMITTING',reason=NULL WHERE id=?", (row["id"],))
                    remaining = ceil((datetime.fromisoformat(row["expires_at"]) - self.queue._now()).total_seconds())
                    if remaining < 1:
                        raise QueueConflict("Original cleanup authorization expired.")
                    _, entries = self.queue.apply_enqueue(db, row["id"], targets, row["actor_subject"],
                                                          row["actor_display_name"], roles, remaining,
                                                          scope="managed_fleet_removal")
                    db.execute("UPDATE operation_requests SET requested_at=?,expires_at=MIN(expires_at,?) WHERE id=?",
                               (row["requested_at"], row["expires_at"], row["id"]))
                    if row["expires_at"] <= stamp(self.queue._now()):
                        raise QueueConflict("Original cleanup authorization expired during promotion.")
                    db.execute("UPDATE managed_fleet_waits SET state='ADMITTED' WHERE id=?", (row["id"],))
                except (QueueConflict, QueueFull, ValueError, TypeError, KeyError, AttributeError, PermissionError):
                    db.execute("ROLLBACK TO fleet_cleanup_promotion")
                    expired = row["expires_at"] <= stamp(self.queue._now())
                    self._settle(db, row, "EXPIRED" if expired else "ATTENTION",
                                 "Original cleanup authorization expired." if expired else
                                 "Fleet cleanup evidence or scope changed; review required, no work admitted.", logs)
                    # Do not log exception text: it may contain stored metadata.
                else:
                    logs.extend(entries)
                    self._event(db, row, "MANAGED_SHUN_FLEET_CLEANUP_QUEUED")
                    self.queue._bump(db)
                    logs.append({"event": "managed_shun.fleet_cleanup.queued", "request_id": row["id"],
                                 "target_count": row["target_count"]})
                    admitted += 1
                finally:
                    db.execute("RELEASE fleet_cleanup_promotion")
                self._require_lease(lease, owner)
            self._require_lease(lease, owner)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return admitted

    def _require_lease(self, lease, owner):
        if (not owner or lease is None or lease["owner"] != owner or not lease["lease_until"]
                or lease["lease_until"] <= stamp(self.queue._now())):
            raise QueueConflict("Executor lease lost; no fleet cleanup was advanced.")

    @staticmethod
    def _validate(db, row):
        payload = json.loads(row["payload_json"])
        scope = {key: value for key, value in payload.items() if key not in {"version", "scope", "action", "mode", "ttl_seconds", "reason"}}
        expected, _ = canonical_managed_fleet_removal(scope, payload["ttl_seconds"], payload["reason"], ordered_wait=True)
        if expected != row["payload_json"] or row["phase"] != "ADMITTED" or row["target_count"] != len(scope["targets"]):
            raise ValueError("Invalid retained fleet authority.")
        requested, expires = datetime.fromisoformat(row["requested_at"]), datetime.fromisoformat(row["expires_at"])
        if (requested.utcoffset() != timedelta(0) or expires.utcoffset() != timedelta(0)
                or expires - requested != timedelta(seconds=payload["ttl_seconds"])):
            raise ValueError("Retained cleanup deadline does not match its original authorization.")
        roles = tuple(json.loads(row["actor_roles_json"]))
        _require_operator(row["actor_subject"], roles)
        ip = IPv4Address(scope["ip"])
        targets = []
        for target in scope["targets"]:
            device = db.execute("SELECT hostname,enabled FROM devices WHERE id=?", (target["device_id"],)).fetchone()
            intent = db.execute("SELECT intent_id,generation,enabled FROM managed_shun_targets WHERE device_id=? AND ip=?",
                                (target["device_id"], ip.packed)).fetchone()
            if device is None or not device["enabled"] or device["hostname"] != target["hostname"]:
                raise ValueError("Device scope changed.")
            if ((target["intent_id"] is None and intent is not None) or
                    (target["intent_id"] is not None and (intent is None or intent["enabled"]
                     or intent["intent_id"] != target["intent_id"] or intent["generation"] != target["generation"]))):
                raise ValueError("Retired generation changed.")
            targets.append((target["device_id"], ip))
        evidence = json.loads(row["predecessors_json"])
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= len(targets):
            raise ValueError("Invalid predecessor evidence.")
        seen, jobs = set(), []
        for entry in evidence:
            if (not isinstance(entry, dict) or set(entry) != {"job_id", "device_id"}
                    or type(entry["device_id"]) is not int or entry["device_id"] in seen
                    or (entry["device_id"], ip) not in targets or str(UUID(entry["job_id"])) != entry["job_id"]):
                raise ValueError("Invalid predecessor scope.")
            seen.add(entry["device_id"])
            job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (entry["job_id"],)).fetchone()
            if (job is None or job["action"] != "ADD" or job["device_id"] != entry["device_id"] or job["ip"] != ip.packed
                    or job["state"] not in {"QUEUED", "VERIFIED", "NOOP", "FAILED", "UNVERIFIED", "CANCELLED"}
                    or (job["state"] == "QUEUED" and job["dispatch_kind"] is not None)):
                raise ValueError("Predecessor has not safely settled.")
            jobs.append(job)
        return targets, jobs, roles

    def _event(self, db, row, event, *, reason=None, subject="system:managed-cleanup",
               display_name="Managed cleanup worker", roles=()):
        # The automated decision is a system event, not new user authority.
        # Queue materialization separately retains the original short-lived actor.
        try:
            ip = IPv4Address(json.loads(row["payload_json"])["ip"])
        except (ValueError, TypeError, KeyError):
            ip = None  # Preserve attention/audit without inventing a target.
        self.store._insert_event(db, event, None, ip, None,
                                 subject, display_name, roles, row["id"],
                                 {"source": "managed_fleet_removal", "target_count": row["target_count"],
                                  "requested_by": row["actor_subject"], "reason": reason}, stamp(self.queue._now()))

    def _settle(self, db, row, state, reason, logs):
        db.execute("UPDATE managed_fleet_waits SET state=?,reason=? WHERE id=?", (state, reason, row["id"]))
        self._event(db, row, f"MANAGED_SHUN_FLEET_CLEANUP_{state}", reason=reason)
        self.queue._bump(db)
        logs.append({"event": "managed_shun.fleet_cleanup.settled", "request_id": row["id"], "state": state})

    def cancel_waiting(self, key, subject, display_name, roles):
        _require_operator(subject, roles)
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT w.*,r.payload_json,r.actor_subject FROM managed_fleet_waits w
                JOIN managed_fleet_removals r ON r.id=w.id WHERE w.id=?""", (key,)).fetchone()
            if row is None or (row["actor_subject"] != subject and "Administrator" not in roles):
                raise PermissionError("Fleet cleanup cancellation is not permitted.")
            if row["state"] == "CANCELLED":
                return False
            if row["state"] != "WAITING_ADD":
                raise QueueConflict("Fleet cleanup is not waiting; inspect the ordinary queue request.")
            db.execute("UPDATE managed_fleet_waits SET state='CANCELLED',reason='Cancelled by operator' WHERE id=?", (key,))
            self._event(db, row, "MANAGED_SHUN_FLEET_CLEANUP_CANCELLED", subject=subject, display_name=display_name, roles=roles)
            self.queue._bump(db)
        print(json.dumps({"event": "managed_shun.fleet_cleanup.cancelled", "request_id": key,
                          "actor_subject": subject}), flush=True)
        return True
