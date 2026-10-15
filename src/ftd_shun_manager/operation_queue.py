"""Durable one-shot removal intentions and a single leased cycle executor."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

from .store import Store

ACTIVE = ("QUEUED", "RUNNING")


class QueueConflict(ValueError):
    pass


class QueueFull(ValueError):
    pass


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OperationQueue:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def initialize(self) -> None:
        with self.store._connection() as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS operation_requests (
                  id TEXT PRIMARY KEY,
                  actor_subject TEXT NOT NULL,
                  actor_display_name TEXT NOT NULL,
                  actor_roles_json TEXT NOT NULL,
                  source TEXT NOT NULL CHECK(source IN ('manual', 'trusted_policy')),
                  payload_json TEXT NOT NULL,
                  requested_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  state TEXT NOT NULL CHECK(state IN ('ACTIVE', 'CANCELLED', 'EXPIRED')),
                  UNIQUE(actor_subject, id)
                );
                CREATE TABLE IF NOT EXISTS operation_jobs (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  id TEXT NOT NULL UNIQUE,
                  device_id INTEGER NOT NULL REFERENCES devices(id),
                  ip BLOB NOT NULL,
                  state TEXT NOT NULL CHECK(state IN
                    ('QUEUED','RUNNING','VERIFIED','NOOP','FAILED','UNVERIFIED',
                     'RECONCILED_ABSENT','CANCELLED')),
                  requested_at TEXT NOT NULL,
                  started_at TEXT,
                  completed_at TEXT,
                  reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_operation_active_target
                  ON operation_jobs(device_id,ip) WHERE state IN ('QUEUED','RUNNING');
                CREATE TABLE IF NOT EXISTS operation_links (
                  request_id TEXT NOT NULL REFERENCES operation_requests(id) ON DELETE CASCADE,
                  job_id TEXT NOT NULL REFERENCES operation_jobs(id) ON DELETE CASCADE,
                  PRIMARY KEY(request_id,job_id)
                );
                CREATE TABLE IF NOT EXISTS operation_executor (
                  id INTEGER PRIMARY KEY CHECK(id=1),
                  owner TEXT,
                  lease_until TEXT,
                  next_eligible_at TEXT,
                  revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_operation_links_job ON operation_links(job_id,request_id);
                CREATE INDEX IF NOT EXISTS idx_operation_jobs_state ON operation_jobs(state,device_id,seq);
                CREATE INDEX IF NOT EXISTS idx_operation_request_rate ON operation_requests(actor_subject,requested_at);
                CREATE INDEX IF NOT EXISTS idx_operation_request_expiry ON operation_requests(state,expires_at);
                INSERT OR IGNORE INTO operation_executor(id) VALUES (1);
                COMMIT;
            """)

    @staticmethod
    def _bump(db) -> None:
        db.execute("UPDATE operation_executor SET revision=revision+1 WHERE id=1")

    def _event(self, db, event: str, request, job, details: dict | None = None) -> None:
        self.store._insert_event(
            db, event, job["device_id"], IPv4Address(job["ip"]), None,
            request["actor_subject"], request["actor_display_name"],
            tuple(json.loads(request["actor_roles_json"])), request["id"],
            {"operation_id": job["id"], "source": request["source"], **(details or {})},
            stamp(self._now()),
        )

    def enqueue(
        self, request_id: str, targets: list[tuple[int, IPv4Address]], subject: str,
        display_name: str, roles: tuple[str, ...], ttl_seconds: int = 900,
        source: str = "manual",
        scope: str = "device",
    ) -> dict:
        if source not in {"manual", "trusted_policy"} or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid queue request")
        if source == "manual" and not {"Operator", "Administrator"}.intersection(roles):
            raise PermissionError("operator role required")
        if not 1 <= len(request_id) <= 128 or not 1 <= len(targets) <= 1000:
            raise ValueError("invalid operation ID or target count")
        targets = sorted(set(targets), key=lambda target: (target[0], int(target[1])))
        payload = json.dumps({"scope": scope, "targets": [(device, str(ip)) for device, ip in targets]})
        current = self._now()
        logs = []
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["actor_subject"] != subject or old["payload_json"] != payload or old["source"] != source:
                    raise QueueConflict("idempotency key was already used for another request")
                return {"operation_id": request_id, "status": "accepted", "replayed": True}
            active_requests = db.execute("""SELECT COUNT(DISTINCT r.id) FROM operation_requests r
                JOIN operation_links l ON l.request_id=r.id JOIN operation_jobs j ON j.id=l.job_id
                WHERE r.state='ACTIVE' AND j.state IN ('QUEUED','RUNNING')""").fetchone()[0]
            if active_requests >= 2000:
                raise QueueFull("operation queue is full")
            if source == "manual":
                recent = db.execute("""SELECT COUNT(*) FROM operation_requests
                    WHERE actor_subject=? AND requested_at>=?""",
                    (subject, stamp(current - timedelta(minutes=1))),
                ).fetchone()[0]
                if recent >= 10:
                    raise QueueFull("at most 10 operation submissions per minute per user")
            db.execute("""INSERT INTO operation_requests VALUES (?,?,?,?,?,?,?,?,?)""", (
                request_id, subject, display_name, json.dumps(roles), source, payload,
                stamp(current), stamp(current + timedelta(seconds=ttl_seconds)), "ACTIVE",
            ))
            request = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
            for device_id, ip in targets:
                device = db.execute("SELECT enabled FROM devices WHERE id=?", (device_id,)).fetchone()
                if device is None or not device["enabled"]:
                    raise ValueError("unknown or disabled target device")
                job = db.execute("""SELECT * FROM operation_jobs WHERE device_id=? AND ip=?
                    AND state IN ('QUEUED','RUNNING')""", (device_id, ip.packed)).fetchone()
                coalesced = job is not None
                if job is None:
                    pending = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
                    if pending >= 1000:
                        raise QueueFull("operation queue is full")
                    job_id = str(uuid4())
                    db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at)
                        VALUES (?,?,?,'QUEUED',?)""", (job_id, device_id, ip.packed, stamp(current)))
                    job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
                db.execute("INSERT INTO operation_links VALUES (?,?)", (request_id, job["id"]))
                self._event(db, "SHUN_OPERATION_QUEUED", request, job, {"coalesced": coalesced})
                self._event(db, "SHUN_TRUSTED_AUTO_REMOVE_REQUESTED" if source == "trusted_policy"
                            else "SHUN_REMOVE_REQUESTED", request, job, {"queued": True})
                logs.append({"event": "queue.request.accepted", "request_id": request_id,
                             "operation_id": job["id"], "device_id": device_id, "ip": str(ip),
                             "actor_subject": subject, "source": source, "coalesced": coalesced})
            self._bump(db)
        for entry in logs:
            print(json.dumps(entry), flush=True)
        return {"operation_id": request_id, "status": "accepted", "replayed": False}

    def replay(self, request_id: str, subject: str, scope: str, ip: IPv4Address,
               device_id: int | None = None) -> dict | None:
        with self.store._connection() as db:
            row = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if row["actor_subject"] != subject or payload["scope"] != scope or any(
            address != str(ip) or (device_id is not None and device != device_id)
            for device, address in payload["targets"]
        ):
            raise QueueConflict("idempotency key was already used for another request")
        return {"operation_id": request_id, "status": "accepted", "replayed": True}

    def has_pending(self, device_id: int | None = None) -> bool:
        with self.store._connection() as db:
            return db.execute("""SELECT 1 FROM operation_jobs WHERE state='QUEUED'
                AND (? IS NULL OR device_id=?) LIMIT 1""", (device_id, device_id)).fetchone() is not None

    def has_target(self, device_id: int, ip: IPv4Address) -> bool:
        with self.store._connection() as db:
            return db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=?
                AND state IN ('QUEUED','RUNNING')""", (device_id, ip.packed)).fetchone() is not None

    def expire_requests(self) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE operation_requests SET state='EXPIRED'
                WHERE state='ACTIVE' AND expires_at<=? AND NOT EXISTS (
                  SELECT 1 FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                  WHERE l.request_id=operation_requests.id AND j.state='RUNNING')""",
                (stamp(self._now()),),
            ).rowcount
            jobs = db.execute("""SELECT j.* FROM operation_jobs j JOIN devices d ON d.id=j.device_id
                WHERE j.state='QUEUED' AND (d.enabled=0 OR NOT EXISTS (
                  SELECT 1 FROM operation_links l JOIN operation_requests r ON r.id=l.request_id
                  WHERE l.job_id=j.id AND r.state='ACTIVE' AND r.expires_at>?))""",
                (stamp(self._now()),),
            ).fetchall()
            for job in jobs:
                self._finish(db, job, "FAILED", "target disabled or all requesting authorizations expired/cancelled")
            if changed:
                self._bump(db)

    def cancel_obsolete_policy(self, allowed: frozenset[IPv4Address]) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT r.*,j.id AS job_id,j.device_id,j.ip
                FROM operation_requests r JOIN operation_links l ON l.request_id=r.id
                JOIN operation_jobs j ON j.id=l.job_id
                WHERE r.source='trusted_policy' AND r.state='ACTIVE' AND j.state='QUEUED'""").fetchall()
            for request in rows:
                if IPv4Address(request["ip"]) in allowed:
                    continue
                job = {"id": request["job_id"], "device_id": request["device_id"], "ip": request["ip"]}
                db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (request["id"],))
                self._event(db, "SHUN_OPERATION_CANCELLED", request, job, {"reason": "trusted-IP policy changed"})
                remaining = db.execute("""SELECT 1 FROM operation_links l JOIN operation_requests r
                    ON r.id=l.request_id WHERE l.job_id=? AND r.state='ACTIVE' AND r.expires_at>?""",
                    (job["id"], stamp(self._now())),
                ).fetchone()
                if not remaining:
                    db.execute("UPDATE operation_jobs SET state='CANCELLED',completed_at=? WHERE id=?",
                               (stamp(self._now()), job["id"]))
                self._bump(db)

    def delay(self) -> float:
        with self.store._connection() as db:
            row = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
        deadlines = [datetime.fromisoformat(value) for value in
                     (row["lease_until"], row["next_eligible_at"]) if value]
        return max([0.0, *((value - self._now()).total_seconds() for value in deadlines)])

    def claim_cycle(self, owner: str, lease_seconds: int) -> bool:
        current = self._now()
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            executor = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            if any(value and datetime.fromisoformat(value) > current for value in
                   (executor["lease_until"], executor["next_eligible_at"])):
                return False
            # A previous worker may have sent a command before it died. Never replay it.
            abandoned = db.execute("SELECT * FROM operation_jobs WHERE state='RUNNING'").fetchall()
            for job in abandoned:
                self._finish(db, job, "UNVERIFIED", "executor lease expired; device outcome is unknown")
            db.execute("""UPDATE operation_executor SET owner=?,lease_until=?,revision=revision+1
                WHERE id=1""", (owner, stamp(current + timedelta(seconds=lease_seconds))))
        if abandoned:
            print(json.dumps({"event": "queue.executor.recovered", "unverified_count": len(abandoned)}), flush=True)
        return True

    def renew(self, owner: str, lease_seconds: int) -> None:
        with self.store._connection() as db:
            changed = db.execute("""UPDATE operation_executor SET lease_until=?
                WHERE id=1 AND owner=? AND lease_until>=?""", (
                stamp(self._now() + timedelta(seconds=lease_seconds)), owner, stamp(self._now()),
            )).rowcount
            if not changed:
                raise QueueConflict("executor lease lost")

    def finish_cycle(self, owner: str, interval_seconds: int) -> None:
        with self.store._connection() as db:
            changed = db.execute("""UPDATE operation_executor SET owner=NULL,lease_until=NULL,
                next_eligible_at=?,revision=revision+1 WHERE id=1 AND owner=?""", (
                stamp(self._now() + timedelta(seconds=max(60, interval_seconds))), owner,
            )).rowcount
            if not changed:
                raise QueueConflict("executor lease lost")

    def cutoff(self) -> int:
        with self.store._connection() as db:
            return db.execute("SELECT COALESCE(MAX(seq),0) FROM operation_jobs").fetchone()[0]

    def claim_removal(self, device_id: int, owner: str, cutoff: int) -> dict | None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            executor = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            if executor["owner"] != owner or not executor["lease_until"] or executor["lease_until"] < stamp(self._now()):
                raise QueueConflict("executor lease lost")
            jobs = db.execute("""SELECT * FROM operation_jobs
                WHERE device_id=? AND state='QUEUED' AND (seq<=? OR EXISTS (
                    SELECT 1 FROM operation_links l JOIN operation_requests r ON r.id=l.request_id
                    WHERE l.job_id=operation_jobs.id AND r.source='trusted_policy' AND r.state='ACTIVE'))
                ORDER BY seq""", (device_id, cutoff)).fetchall()
            for job in jobs:
                requests = db.execute("""SELECT r.* FROM operation_requests r
                    JOIN operation_links l ON l.request_id=r.id
                    WHERE l.job_id=? AND r.state='ACTIVE' AND r.expires_at>?""",
                    (job["id"], stamp(self._now())),
                ).fetchall()
                valid = any(request["source"] == "trusted_policy" or
                            {"Operator", "Administrator"}.intersection(json.loads(request["actor_roles_json"]))
                            for request in requests)
                if not valid:
                    self._finish(db, job, "FAILED", "all requesting authorizations expired or were cancelled")
                    continue
                db.execute("UPDATE operation_jobs SET state='RUNNING',started_at=? WHERE id=?",
                           (stamp(self._now()), job["id"]))
                for request in requests:
                    self._event(db, "SHUN_OPERATION_RUNNING", request, job)
                self._bump(db)
                return {**dict(job), "state": "RUNNING"}
        return None

    def _finish(self, db, job, state: str, reason: str | None = None) -> None:
        current = stamp(self._now())
        db.execute("UPDATE operation_jobs SET state=?,completed_at=?,reason=? WHERE id=?",
                   (state, current, reason, job["id"]))
        requests = db.execute("""SELECT r.* FROM operation_requests r
            JOIN operation_links l ON l.request_id=r.id WHERE l.job_id=? AND r.state!='CANCELLED'""",
            (job["id"],),
        ).fetchall()
        for request in requests:
            self._event(db, f"SHUN_OPERATION_{state}", request, job, {"reason": reason})
            if state in {"FAILED", "UNVERIFIED"}:
                self._event(db, "SHUN_TRUSTED_AUTO_REMOVE_FAILED" if request["source"] == "trusted_policy"
                            else "SHUN_REMOVE_FAILED", request, job, {"reason": reason, "outcome": state})
        self._bump(db)

    def defer_removal(self, job_id: str, owner: str) -> None:
        """Only call after the agent's exact deferred-before-write response."""
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
            executor = db.execute("SELECT owner FROM operation_executor WHERE id=1").fetchone()
            if job is None or job["state"] != "RUNNING" or executor["owner"] != owner:
                raise QueueConflict("operation ownership lost")
            db.execute("""UPDATE operation_jobs SET state='QUEUED',started_at=NULL,
                reason='Deferred before write: session budget exhausted' WHERE id=?""", (job_id,))
            requests = db.execute("""SELECT r.* FROM operation_requests r JOIN operation_links l
                ON l.request_id=r.id WHERE l.job_id=? AND r.state='ACTIVE'""", (job_id,)).fetchall()
            for request in requests:
                self._event(db, "SHUN_OPERATION_DEFERRED", request, job, {"write_sent": False})
            self._bump(db)
        print(json.dumps({"event": "queue.removal.deferred", "operation_id": job_id,
                          "device_id": job["device_id"], "ip": str(IPv4Address(job["ip"])),
                          "write_sent": False}), flush=True)

    def reconcile_unknown(self, device_id: int, present: set[IPv4Address]) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            jobs = db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND state='UNVERIFIED'",
                              (device_id,)).fetchall()
            for job in jobs:
                if IPv4Address(job["ip"]) not in present:
                    self._finish(db, job, "RECONCILED_ABSENT", "snapshot confirms absence; original write was not verified")

    def finish_removal(self, job_id: str, owner: str, state: str, reason: str | None = None) -> None:
        if state not in {"VERIFIED", "NOOP", "FAILED", "UNVERIFIED"}:
            raise ValueError("invalid removal result")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
            executor = db.execute("SELECT owner FROM operation_executor WHERE id=1").fetchone()
            if job is None or job["state"] != "RUNNING" or executor["owner"] != owner:
                raise QueueConflict("operation ownership lost")
            if state in {"VERIFIED", "NOOP"}:
                interfaces = db.execute("""SELECT interface FROM shun_state
                    WHERE device_id=? AND ip=? AND active=1""", (job["device_id"], job["ip"])).fetchall()
                if state == "VERIFIED":
                    db.execute("""UPDATE shun_state SET active=0,last_changed_at=?
                        WHERE device_id=? AND ip=? AND active=1""",
                        (stamp(self._now()), job["device_id"], job["ip"]),
                    )
                requests = db.execute("""SELECT r.* FROM operation_requests r
                    JOIN operation_links l ON l.request_id=r.id WHERE l.job_id=? AND r.state='ACTIVE'""",
                    (job_id,),
                ).fetchall()
                for request in requests:
                    policy = request["source"] == "trusted_policy"
                    event = ("SHUN_TRUSTED_AUTO_REMOVED" if policy else "SHUN_REMOVED_BY_UI") if state == "VERIFIED" else (
                        "SHUN_TRUSTED_AUTO_REMOVE_NOOP" if policy else "SHUN_REMOVE_NOOP"
                    )
                    for interface in interfaces or [None]:
                        self.store._insert_event(
                            db, event, job["device_id"], IPv4Address(job["ip"]),
                            interface["interface"] if interface else None,
                            request["actor_subject"], request["actor_display_name"],
                            tuple(json.loads(request["actor_roles_json"])), request["id"],
                            {"operation_id": job_id, "verified": state == "VERIFIED"}, stamp(self._now()),
                        )
            self._finish(db, job, state, reason)

    def cancel(self, request_id: str, subject: str, administrator: bool,
               display_name: str | None = None, roles: tuple[str, ...] = ()) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            request = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
            if request is None or request["source"] != "manual" or (request["actor_subject"] != subject and not administrator):
                raise PermissionError("operation cancellation is not permitted")
            jobs = db.execute("""SELECT j.* FROM operation_jobs j JOIN operation_links l
                ON l.job_id=j.id WHERE l.request_id=?""", (request_id,)).fetchall()
            if request["state"] == "CANCELLED":
                return
            if any(job["state"] == "RUNNING" for job in jobs):
                raise QueueConflict("operation is already running; cancellation was not applied")
            if not any(job["state"] == "QUEUED" for job in jobs):
                raise QueueConflict("operation is already completed")
            db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (request_id,))
            for job in jobs:
                if job["state"] != "QUEUED":
                    continue
                actor = {**dict(request), "actor_subject": subject,
                         "actor_display_name": display_name or subject,
                         "actor_roles_json": json.dumps(roles)}
                self._event(db, "SHUN_OPERATION_CANCELLED", actor, job,
                            {"requested_by": request["actor_subject"]})
                other = db.execute("""SELECT 1 FROM operation_links l JOIN operation_requests r
                    ON r.id=l.request_id WHERE l.job_id=? AND r.state='ACTIVE' AND r.expires_at>?""",
                    (job["id"], stamp(self._now())),
                ).fetchone()
                if not other and job["state"] == "QUEUED":
                    db.execute("UPDATE operation_jobs SET state='CANCELLED',completed_at=? WHERE id=?",
                               (stamp(self._now()), job["id"]))
            self._bump(db)
        print(json.dumps({"event": "queue.request.cancelled", "request_id": request_id,
                          "actor_subject": subject}), flush=True)

    def status(self) -> dict:
        with self.store._connection() as db:
            # Counts and independently selected groups must describe one snapshot.
            db.execute("BEGIN")
            executor = db.execute("SELECT revision,next_eligible_at FROM operation_executor WHERE id=1").fetchone()
            counts = {row["state"]: row["n"] for row in db.execute(
                "SELECT state,COUNT(*) AS n FROM operation_jobs GROUP BY state"
            )}
            base = "SELECT j.*,d.hostname FROM operation_jobs j JOIN devices d ON d.id=j.device_id "
            rows = db.execute(base + """WHERE j.state IN ('QUEUED','RUNNING')
                ORDER BY CASE WHEN j.state='RUNNING' THEN 0 ELSE 1 END,j.seq LIMIT 100""").fetchall()
            rows += db.execute(base + """WHERE j.state IN ('FAILED','UNVERIFIED')
                ORDER BY j.completed_at DESC,j.seq DESC LIMIT 20""").fetchall()
            rows += db.execute(base + """WHERE j.state IN ('VERIFIED','NOOP','CANCELLED','RECONCILED_ABSENT')
                ORDER BY j.completed_at DESC,j.seq DESC LIMIT 20""").fetchall()
            jobs = []
            for row in rows:
                query = """SELECT r.id,r.actor_subject,r.actor_display_name,r.source,r.state,r.expires_at,r.payload_json
                    FROM operation_requests r JOIN operation_links l ON l.request_id=r.id WHERE l.job_id=?"""
                live = db.execute(query + " AND r.state='ACTIVE' AND r.expires_at>? LIMIT 2000",
                                  (row["id"], stamp(self._now()))).fetchall() if row["state"] in ACTIVE else []
                recent = db.execute(query + " ORDER BY r.requested_at DESC,r.id LIMIT 20", (row["id"],)).fetchall()
                live_ids = {request["id"] for request in live}
                selected = live + [request for request in recent if request["id"] not in live_ids]
                request_count = db.execute("SELECT COUNT(*) FROM operation_links WHERE job_id=?", (row["id"],)).fetchone()[0]
                request_views = []
                for request in selected:
                    view = dict(request)
                    payload = json.loads(view.pop("payload_json"))
                    view["target_count"] = len(payload["targets"])
                    request_views.append(view)
                jobs.append({**dict(row), "ip": str(IPv4Address(row["ip"])),
                             "request_count": request_count, "requests": request_views})
            progress_filter = """FROM operation_requests r JOIN operation_links l ON l.request_id=r.id
                JOIN operation_jobs j ON j.id=l.job_id
                WHERE r.state='ACTIVE' AND j.state IN ('QUEUED','RUNNING')"""
            progress_count = db.execute("SELECT COUNT(DISTINCT r.id) " + progress_filter).fetchone()[0]
            progress_requests = db.execute("""SELECT DISTINCT r.id,r.actor_subject,r.actor_display_name,
                r.source,r.requested_at """ + progress_filter + " ORDER BY r.requested_at,r.id LIMIT 20").fetchall()
            request_progress = []
            for request in progress_requests:
                outcomes = {row["state"]: row["n"] for row in db.execute("""SELECT j.state,COUNT(*) AS n
                    FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                    WHERE l.request_id=? GROUP BY j.state""", (request["id"],))}
                total = sum(outcomes.values())
                processed = total - outcomes.get("QUEUED", 0) - outcomes.get("RUNNING", 0)
                request_progress.append({**dict(request), "total": total, "processed": processed,
                                         "counts": outcomes})
        return {"revision": executor["revision"], "next_eligible_at": executor["next_eligible_at"],
                "counts": counts, "items": jobs,
                "display_limits": {"active": 100, "attention": 20, "completed": 20},
                "progress": {"requests": request_progress, "total_requests": progress_count, "limit": 20}}

    def prune_completed(self, retention_days: int) -> None:
        cutoff = stamp(self._now() - timedelta(days=retention_days))
        with self.store._connection() as db:
            deleted = db.execute("""DELETE FROM operation_jobs
                WHERE state NOT IN ('QUEUED','RUNNING') AND completed_at<?""", (cutoff,)).rowcount
            db.execute("""DELETE FROM operation_requests WHERE requested_at<?
                AND NOT EXISTS(SELECT 1 FROM operation_links WHERE request_id=operation_requests.id)""", (cutoff,))
            if deleted:
                self._bump(db)
                self.store._insert_event(
                    db, "HISTORY_RETENTION_PURGED", None, None, None,
                    "system:retention-policy", "History retention policy", (), None,
                    {"operation_jobs_deleted": deleted, "cutoff": cutoff}, stamp(self._now()),
                )
