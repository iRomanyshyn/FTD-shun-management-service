"""Durable one-shot intentions with independently gated ADD execution."""

from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

from .agent_protocol import AdditionResult, _valid_interface
from .import_intent import canonical_import
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
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(operation_jobs)")}
            if "action" not in columns:
                db.execute("ALTER TABLE operation_jobs ADD COLUMN action TEXT NOT NULL DEFAULT 'REMOVE' CHECK(action IN ('REMOVE','ADD'))")
            if "dispatch_kind" not in columns:
                db.execute("ALTER TABLE operation_jobs ADD COLUMN dispatch_kind TEXT CHECK(dispatch_kind IN ('REMOVE','ADD'))")
            # An older executor must not claim an ADD row as a removal. Requests
            # retain their nine-column layout for older removal admissions.
            db.execute("""CREATE TRIGGER IF NOT EXISTS guard_add_claim BEFORE UPDATE OF state ON operation_jobs
                WHEN NEW.action='ADD' AND NEW.state='RUNNING' AND OLD.state!='RUNNING'
                  AND NEW.dispatch_kind IS NOT 'ADD'
                BEGIN SELECT RAISE(ABORT,'ADD requires an explicit addition claimant'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS guard_add_requeue BEFORE UPDATE ON operation_jobs
                WHEN NEW.action='ADD' AND NEW.state='QUEUED' AND NEW.dispatch_kind IS NOT NULL
                BEGIN SELECT RAISE(ABORT,'ADD requeue must clear dispatch kind'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_operation_action BEFORE UPDATE OF action ON operation_jobs
                WHEN NEW.action!=OLD.action BEGIN SELECT RAISE(ABORT,'operation action is immutable'); END""")

    @staticmethod
    def _bump(db) -> None:
        db.execute("UPDATE operation_executor SET revision=revision+1 WHERE id=1")

    def _event(self, db, event: str, request, job, details: dict | None = None) -> None:
        imported = db.execute("SELECT 1 FROM manual_import_batches WHERE id=?", (request["id"],)).fetchone()
        self.store._insert_event(
            db, event, job["device_id"], IPv4Address(job["ip"]), None,
            request["actor_subject"], request["actor_display_name"],
            tuple(json.loads(request["actor_roles_json"])), request["id"],
            {"operation_id": job["id"], "source": "manual_import" if imported else request["source"],
             "action": dict(job).get("action", "REMOVE"), **(details or {})},
            stamp(self._now()),
        )

    def enqueue(
        self, request_id: str, targets: list[tuple[int, IPv4Address]], subject: str,
        display_name: str, roles: tuple[str, ...], ttl_seconds: int = 900,
        source: str = "manual",
        scope: str = "device",
        *, batch_label: str = "", batch_reason: str = "", policy_revision: int | None = None,
        confirmation_digest: str | None = None,
    ) -> dict:
        if source not in {"manual", "trusted_policy", "manual_import"} or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid queue request")
        if source in {"manual", "manual_import"} and not {"Operator", "Administrator"}.intersection(roles):
            raise PermissionError("operator role required")
        if not 1 <= len(request_id) <= 128 or not 1 <= len(targets) <= 1000:
            raise ValueError("invalid operation ID or target count")
        action = "ADD" if source == "manual_import" else "REMOVE"
        if action == "ADD":
            if not subject.strip():
                raise PermissionError("authenticated import actor required")
            if scope != "import":
                raise ValueError("Explicit import scope is required.")
            targets, payload, digest = canonical_import(targets, policy_revision, batch_label, batch_reason)
            if not isinstance(confirmation_digest, str) or not hmac.compare_digest(digest, confirmation_digest):
                raise ValueError("Import confirmation does not match the canonical targets and metadata.")
        else:
            targets = sorted(set(targets), key=lambda target: (target[0], int(target[1])))
            payload = json.dumps({"scope": scope, "targets": [(device, str(ip)) for device, ip in targets]})
        current = self._now()
        logs = []
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["actor_subject"] != subject or old["payload_json"] != payload or old["source"] != (
                    "manual" if action == "ADD" else source
                ):
                    raise QueueConflict("idempotency key was already used for another request")
                return {"operation_id": request_id, "status": "accepted", "replayed": True}
            if action == "ADD":
                if db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0] != policy_revision:
                    raise QueueConflict("Protected IPs changed; review the import again.")
                if any(db.execute("SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1", (ip.packed,)).fetchone()
                       for _, ip in targets):
                    raise QueueConflict("Import contains an enabled Protected IP; no targets were queued.")
            active_requests = db.execute("""SELECT COUNT(DISTINCT r.id) FROM operation_requests r
                JOIN operation_links l ON l.request_id=r.id JOIN operation_jobs j ON j.id=l.job_id
                WHERE r.state='ACTIVE' AND j.state IN ('QUEUED','RUNNING')""").fetchone()[0]
            if active_requests >= 2000:
                raise QueueFull("operation queue is full")
            if source in {"manual", "manual_import"}:
                recent = db.execute("""SELECT COUNT(*) FROM operation_requests
                    WHERE actor_subject=? AND requested_at>=?""",
                    (subject, stamp(current - timedelta(minutes=1))),
                ).fetchone()[0]
                if recent >= 10:
                    raise QueueFull("at most 10 operation submissions per minute per user")
            db.execute("""INSERT INTO operation_requests VALUES (?,?,?,?,?,?,?,?,?)""", (
                request_id, subject, display_name, json.dumps(roles), "manual" if action == "ADD" else source, payload,
                stamp(current), stamp(current + timedelta(seconds=ttl_seconds)), "ACTIVE",
            ))
            if action == "ADD":
                db.execute("INSERT INTO manual_import_batches VALUES (?,'manual_import',?,?,?,?,?)", (
                    request_id, subject, display_name, json.dumps(roles), payload, stamp(current),
                ))
            request = db.execute("SELECT * FROM operation_requests WHERE id=?", (request_id,)).fetchone()
            for device_id, ip in targets:
                device = db.execute("SELECT enabled FROM devices WHERE id=?", (device_id,)).fetchone()
                if device is None or not device["enabled"]:
                    raise ValueError("unknown or disabled target device")
                job = db.execute("""SELECT * FROM operation_jobs WHERE device_id=? AND ip=?
                    AND state IN ('QUEUED','RUNNING')""", (device_id, ip.packed)).fetchone()
                coalesced = job is not None
                if job is not None and job["action"] != action:
                    raise QueueConflict("Opposite ADD/REMOVE work already exists for this device/IP; no targets were queued.")
                if job is None:
                    pending = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
                    if pending >= 1000:
                        raise QueueFull("operation queue is full")
                    job_id = str(uuid4())
                    db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action,reason)
                        VALUES (?,?,?,'QUEUED',?,?,?)""", (job_id, device_id, ip.packed, stamp(current), action,
                            None))
                    job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
                db.execute("INSERT INTO operation_links VALUES (?,?)", (request_id, job["id"]))
                self._event(db, "SHUN_OPERATION_QUEUED", request, job, {"coalesced": coalesced})
                self._event(db, "SHUN_ADD_REQUESTED" if action == "ADD" else
                            "SHUN_TRUSTED_AUTO_REMOVE_REQUESTED" if source == "trusted_policy"
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

    def has_pending(self, device_id: int | None = None, *, addition_device_ids: frozenset[int] = frozenset()) -> bool:
        with self.store._connection() as db:
            if not addition_device_ids:
                return db.execute("""SELECT 1 FROM operation_jobs WHERE state='QUEUED'
                    AND action='REMOVE' AND (? IS NULL OR device_id=?) LIMIT 1""", (device_id, device_id)).fetchone() is not None
            return any(row["action"] == "REMOVE" or row["device_id"] in addition_device_ids
                       for row in db.execute("""SELECT action,device_id FROM operation_jobs
                           WHERE state='QUEUED' AND (? IS NULL OR device_id=?)""", (device_id, device_id)))

    def has_target(self, device_id: int, ip: IPv4Address) -> bool:
        with self.store._connection() as db:
            return db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=?
                AND state IN ('QUEUED','RUNNING')""", (device_id, ip.packed)).fetchone() is not None

    def expire_requests(self) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = self._expire_authorizations(db)
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

    def _expire_authorizations(self, db) -> int:
        return db.execute("""UPDATE operation_requests SET state='EXPIRED'
            WHERE state='ACTIVE' AND expires_at<=? AND NOT EXISTS (
              SELECT 1 FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
              WHERE l.request_id=operation_requests.id AND j.state='RUNNING')""",
            (stamp(self._now()),),
        ).rowcount

    def cancel_obsolete_policy(self) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cancel_obsolete_policy(db)

    def _cancel_obsolete_policy(self, db) -> None:
        for job in db.execute("""SELECT j.* FROM operation_jobs j JOIN protected_ips p ON p.ip=j.ip
            WHERE j.action='ADD' AND j.state='QUEUED' AND p.enabled=1""").fetchall():
            self._finish(db, job, "FAILED", "Protected IP enabled before addition; no write was sent")
        rows = db.execute("""SELECT r.*,j.id AS job_id,j.device_id,j.ip
            FROM operation_requests r JOIN operation_links l ON l.request_id=r.id
            JOIN operation_jobs j ON j.id=l.job_id
            WHERE r.source='trusted_policy' AND r.state='ACTIVE' AND j.state='QUEUED'
              AND NOT EXISTS (SELECT 1 FROM protected_ips p WHERE p.ip=j.ip AND p.enabled=1)""").fetchall()
        for request in rows:
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
        return self._claim_mutation(device_id, owner, cutoff, "REMOVE")

    def claim_next_mutation(self, device_id: int, owner: str, cutoff: int, *, additions_enabled: bool = False) -> dict | None:
        """One atomic FIFO claim; the leased scheduler supplies device capability."""
        return self._claim_mutation(device_id, owner, cutoff, None if additions_enabled else "REMOVE")

    def claim_addition(self, device_id: int, owner: str, cutoff: int, *, execution_enabled: bool = False) -> dict | None:
        """Explicit ADD-only domain hook; defaults disabled."""
        if not execution_enabled:
            return None
        return self._claim_mutation(device_id, owner, cutoff, "ADD")

    def _claim_mutation(self, device_id: int, owner: str, cutoff: int, action: str | None) -> dict | None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._cancel_obsolete_policy(db)
            # Long cycles can outlast a request. Expire unstarted requesters
            # before each claim, not just at sweep start: an expired coalesced
            # actor must not inherit origin from another actor's valid work.
            if self._expire_authorizations(db):
                self._bump(db)
            executor = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            if executor["owner"] != owner or not executor["lease_until"] or executor["lease_until"] < stamp(self._now()):
                raise QueueConflict("executor lease lost")
            jobs = db.execute("""SELECT * FROM operation_jobs
                WHERE device_id=? AND state='QUEUED' AND (? IS NULL OR action=?) AND (seq<=? OR EXISTS (
                    SELECT 1 FROM operation_links l JOIN operation_requests r ON r.id=l.request_id
                    WHERE l.job_id=operation_jobs.id AND r.source='trusted_policy' AND r.state='ACTIVE'))
                ORDER BY seq""", (device_id, action, action, cutoff)).fetchall()
            for job in jobs:
                job_action = job["action"]
                requests = db.execute("""SELECT r.* FROM operation_requests r
                    JOIN operation_links l ON l.request_id=r.id
                    WHERE l.job_id=? AND r.state='ACTIVE' AND r.expires_at>?
                      AND EXISTS(SELECT 1 FROM manual_import_batches b WHERE b.id=r.id)=?""",
                    (job["id"], stamp(self._now()), int(job_action == "ADD")),
                ).fetchall()
                device = db.execute("SELECT enabled FROM devices WHERE id=?", (device_id,)).fetchone()
                if device is None or not device["enabled"]:
                    self._finish(db, job, "FAILED", "target device is disabled")
                    continue
                valid = any(request["source"] == "trusted_policy" or
                            {"Operator", "Administrator"}.intersection(json.loads(request["actor_roles_json"]))
                            for request in requests)
                if not valid:
                    self._finish(db, job, "FAILED", "all requesting authorizations expired or were cancelled")
                    continue
                db.execute("UPDATE operation_jobs SET state='RUNNING',started_at=?,dispatch_kind=? WHERE id=?",
                           (stamp(self._now()), job_action, job["id"]))
                for request in requests:
                    self._event(db, "SHUN_OPERATION_RUNNING", request, job)
                self._bump(db)
                return {**dict(job), "state": "RUNNING", "dispatch_kind": job_action}
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
                self._event(db, "SHUN_ADD_FAILED" if job["action"] == "ADD" else
                            "SHUN_TRUSTED_AUTO_REMOVE_FAILED" if request["source"] == "trusted_policy"
                            else "SHUN_REMOVE_FAILED", request, job, {"reason": reason, "outcome": state})
        self._bump(db)

    def defer_removal(self, job_id: str, owner: str) -> None:
        """Only call after the agent's exact deferred-before-write response."""
        self._defer_mutation(job_id, owner, "REMOVE")

    def defer_addition(self, job_id: str, owner: str) -> None:
        """Never use for missing/uncertain responses; only exact pre-write deferral."""
        self._defer_mutation(job_id, owner, "ADD")

    def _defer_mutation(self, job_id: str, owner: str, action: str) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
            executor = db.execute("SELECT owner FROM operation_executor WHERE id=1").fetchone()
            if job is None or job["action"] != action or job["state"] != "RUNNING" or executor["owner"] != owner:
                raise QueueConflict("operation ownership lost")
            db.execute("""UPDATE operation_jobs SET state='QUEUED',started_at=NULL,dispatch_kind=NULL,
                reason='Deferred before write: session budget exhausted' WHERE id=?""", (job_id,))
            requests = db.execute("""SELECT r.* FROM operation_requests r JOIN operation_links l
                ON l.request_id=r.id WHERE l.job_id=? AND r.state='ACTIVE'""", (job_id,)).fetchall()
            for request in requests:
                self._event(db, "SHUN_OPERATION_DEFERRED", request, job, {"write_sent": False})
            self._bump(db)
        print(json.dumps({"event": "queue.addition.deferred" if action == "ADD" else "queue.removal.deferred", "operation_id": job_id,
                          "device_id": job["device_id"], "ip": str(IPv4Address(job["ip"])),
                          "write_sent": False}), flush=True)

    def reconcile_unknown(self, device_id: int, present: set[IPv4Address]) -> None:
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            jobs = db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND action='REMOVE' AND state='UNVERIFIED'",
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
            if job is None or job["action"] != "REMOVE" or job["state"] != "RUNNING" or executor["owner"] != owner:
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

    def finish_addition(self, job_id: str, owner: str, result: AdditionResult | str, *, reason: str | None = None) -> str:
        """Commit an exact worker result; return persisted state, not assumed success."""
        interface = None
        if isinstance(result, AdditionResult):
            if type(result.created) is not bool or (not result.created and result.interface is not None):
                raise ValueError("invalid addition result")
            if result.created and (not isinstance(result.interface, str) or not _valid_interface(result.interface)):
                raise ValueError("verified addition requires a safe observed interface")
            state = "VERIFIED" if result.created else "NOOP"
            interface = result.interface
        elif isinstance(result, str) and result in {"FAILED", "UNVERIFIED"}:
            state = result
        else:
            raise ValueError("invalid addition result")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (job_id,)).fetchone()
            executor = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            current = stamp(self._now())
            if (job is None or job["action"] != "ADD" or job["state"] != "RUNNING"
                    or executor["owner"] != owner or not executor["lease_until"] or executor["lease_until"] < current):
                raise QueueConflict("addition ownership or executor lease lost")
            requests = db.execute("""SELECT r.* FROM operation_requests r JOIN operation_links l ON l.request_id=r.id
                JOIN manual_import_batches b ON b.id=r.id WHERE l.job_id=? AND r.state='ACTIVE'""", (job_id,)).fetchall()
            if state == "VERIFIED":
                if db.execute("SELECT 1 FROM shun_state WHERE device_id=? AND ip=? AND active=1",
                              (job["device_id"], job["ip"])).fetchone():
                    state, reason = "UNVERIFIED", "local active occurrence conflicts with verified add; origin not assigned"
                else:
                    occurrence = str(uuid4())
                    db.execute("""INSERT INTO shun_state
                        (device_id,ip,interface,active,first_seen_at,last_seen_at,last_changed_at,occurrence_id)
                        VALUES (?,?,?,1,?,?,?,?) ON CONFLICT(device_id,ip,interface) DO UPDATE SET
                        active=1,last_seen_at=excluded.last_seen_at,last_changed_at=excluded.last_changed_at,
                        occurrence_id=excluded.occurrence_id""", (
                            job["device_id"], job["ip"], interface, current, current, current, occurrence))
                    for request in requests:
                        db.execute("INSERT INTO shun_import_origins VALUES (?,?,?,?,?,?,?)", (
                            request["id"], job_id, job["device_id"], job["ip"], interface, occurrence, current))
                        self.store._insert_event(db, "SHUN_ADDED_BY_IMPORT", job["device_id"], IPv4Address(job["ip"]),
                            interface, request["actor_subject"], request["actor_display_name"],
                            tuple(json.loads(request["actor_roles_json"])), request["id"],
                            {"operation_id": job_id, "batch_id": request["id"], "source": "manual_import",
                             "occurrence_id": occurrence, "verified": True}, current)
            if state == "NOOP":
                for request in requests:
                    self._event(db, "SHUN_ADD_NOOP", request, job, {"created": False})
            self._finish(db, job, state, reason)
        print(json.dumps({"event": "queue.addition.completed", "operation_id": job_id,
                          "source": "manual_import", "state": state, "device_id": job["device_id"],
                          "ip": str(IPv4Address(job["ip"])), "interface": interface if state == "VERIFIED" else None}), flush=True)
        return state

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

    def status(self, *, addition_device_ids: frozenset[int] = frozenset()) -> dict:
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
            target_counts = {}
            for row in rows:
                query = """SELECT r.id,r.actor_subject,r.actor_display_name,r.source,r.state,r.expires_at
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
                    if row["action"] == "ADD":
                        view["source"] = "manual_import"
                    # Do not materialize a 1000-target canonical payload for
                    # every shared job/actor. Count immutable linked targets
                    # once per displayed request within this read snapshot.
                    if request["id"] not in target_counts:
                        target_counts[request["id"]] = db.execute(
                            "SELECT COUNT(*) FROM operation_links WHERE request_id=?",
                            (request["id"],),
                        ).fetchone()[0]
                    view["target_count"] = target_counts[request["id"]]
                    request_views.append(view)
                reason = row["reason"]
                if (row["action"] == "ADD" and row["state"] == "QUEUED"
                        and row["device_id"] in addition_device_ids and reason == "ADD execution is not enabled"):
                    reason = None  # Legacy placeholder, not a real deferral/error.
                jobs.append({**dict(row), "ip": str(IPv4Address(row["ip"])), "reason": reason,
                             "execution_enabled": row["action"] == "REMOVE" or row["device_id"] in addition_device_ids,
                             "request_count": request_count, "requests": request_views})
            progress_filter = """FROM operation_requests r JOIN operation_links l ON l.request_id=r.id
                JOIN operation_jobs j ON j.id=l.job_id
                WHERE r.state='ACTIVE' AND j.state IN ('QUEUED','RUNNING')"""
            progress_count = db.execute("SELECT COUNT(DISTINCT r.id) " + progress_filter).fetchone()[0]
            progress_requests = db.execute("""SELECT DISTINCT r.id,r.actor_subject,r.actor_display_name,
                CASE WHEN EXISTS(SELECT 1 FROM manual_import_batches b WHERE b.id=r.id)
                THEN 'manual_import' ELSE r.source END AS source,r.requested_at """ + progress_filter + " ORDER BY r.requested_at,r.id LIMIT 20").fetchall()
            request_progress = []
            for request in progress_requests:
                outcomes = {row["state"]: row["n"] for row in db.execute("""SELECT j.state,COUNT(*) AS n
                    FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                    WHERE l.request_id=? GROUP BY j.state""", (request["id"],))}
                total = sum(outcomes.values())
                processed = total - outcomes.get("QUEUED", 0) - outcomes.get("RUNNING", 0)
                view = dict(request)
                request_progress.append({**view, "total": total, "processed": processed,
                                         "counts": outcomes})
        return {"revision": executor["revision"], "next_eligible_at": executor["next_eligible_at"],
                "counts": counts, "items": jobs,
                "display_limits": {"active": 100, "attention": 20, "completed": 20},
                "add_execution_enabled": bool(addition_device_ids),
                "progress": {"requests": request_progress, "total_requests": progress_count, "limit": 20}}

    def prune_completed(self, retention_days: int) -> None:
        cutoff = stamp(self._now() - timedelta(days=retention_days))
        with self.store._connection() as db:
            deleted = db.execute("""DELETE FROM operation_jobs
                WHERE state NOT IN ('QUEUED','RUNNING') AND completed_at<?""", (cutoff,)).rowcount
            db.execute("""DELETE FROM operation_requests WHERE requested_at<?
                AND NOT EXISTS(SELECT 1 FROM operation_links WHERE request_id=operation_requests.id)""", (cutoff,))
            batches_deleted = db.execute("""DELETE FROM manual_import_batches WHERE requested_at<?
                AND NOT EXISTS(SELECT 1 FROM shun_import_origins o WHERE o.batch_id=manual_import_batches.id)
                AND NOT EXISTS(SELECT 1 FROM operation_requests r WHERE r.id=manual_import_batches.id)""", (cutoff,)).rowcount
            if deleted or batches_deleted:
                self._bump(db)
                self.store._insert_event(
                    db, "HISTORY_RETENTION_PURGED", None, None, None,
                    "system:retention-policy", "History retention policy", (), None,
                    {"operation_jobs_deleted": deleted, "import_batches_deleted": batches_deleted, "cutoff": cutoff}, stamp(self._now()),
                )
