"""Snapshot-bound system ADD authority; no migration or standalone executor."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid4, uuid5

from .managed_safety import ManagedStateUnavailable, fleet_target_held, managed_state
from .operation_queue import QueueConflict, QueueFull, stamp
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

ACTOR = "system:managed-shun-policy"
SOURCE = "managed_shun_policy"


def present(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_restoration_attempts'").fetchone():
        return False
    if managed_state(db) is None:
        raise ManagedStateUnavailable("Restoration attempts are missing their policy registry.")
    # Fail closed on a partial optional table before other code treats it as empty.
    try:
        db.execute("""SELECT id,job_id,device_id,ip,intent_id,generation,authorization_request_id,
            target_revision,snapshot_id,snapshot_started_at,snapshot_at,requested_at,state,
            completed_at,occurrence_id,interface FROM managed_restoration_attempts LIMIT 0""")
        if db.execute("""SELECT 1 FROM managed_restoration_attempts a LEFT JOIN operation_jobs j ON j.id=a.job_id
                WHERE a.state IN ('QUEUED','RUNNING') AND j.id IS NULL LIMIT 1""").fetchone():
            raise ManagedStateUnavailable("Pending restoration is missing its queue evidence.")
    except sqlite3.DatabaseError as error:
        raise ManagedStateUnavailable("Restoration evidence is incomplete.") from error
    return True


def attempt_for_job(db, job_id):
    from .bulk_attempts import for_job
    from .bulk_attempts import present as bulk_present

    if bulk_present(db):
        return for_job(db, job_id)
    return db.execute("SELECT * FROM managed_restoration_attempts WHERE job_id=?", (job_id,)).fetchone() if present(db) else None


def key_reserved(db, key):
    from .bulk_attempts import present as bulk_present
    from .bulk_attempts import reserved
    from .managed_closures import key_reserved as closure_key_reserved

    if bulk_present(db):
        return reserved(db, key)
    return (closure_key_reserved(db, key) or (present(db) and db.execute(
        "SELECT 1 FROM managed_restoration_attempts WHERE id=? OR job_id=?", (key, key)).fetchone() is not None))


def validate_binding(db, attempt, job):
    request = db.execute("SELECT * FROM operation_requests WHERE id=?", (attempt["id"],)).fetchone()
    expected = {"scope": "managed_restoration", "intent_id": attempt["intent_id"], "generation": attempt["generation"],
                "targets": [[attempt["device_id"], str(IPv4Address(attempt["ip"]))]]}
    links = db.execute("SELECT request_id,job_id FROM operation_links WHERE request_id=? OR job_id=?",
                       (attempt["id"], job["id"])).fetchall()
    if (request is None or request["source"] != "trusted_policy" or request["actor_subject"] != ACTOR
            or json.loads(request["actor_roles_json"]) != [] or json.loads(request["payload_json"]) != expected
            or request["requested_at"] != attempt["requested_at"] or len(links) != 1
            or job['requested_at'] != attempt['requested_at']
            or links[0]["request_id"] != attempt["id"] or links[0]["job_id"] != attempt["job_id"]
            or job["action"] != "ADD" or job["device_id"] != attempt["device_id"] or job["ip"] != attempt["ip"]
            or job["state"] != attempt["state"]
            or datetime.fromisoformat(request["expires_at"]) - datetime.fromisoformat(request["requested_at"]) != timedelta(seconds=900)):
        raise ManagedStateUnavailable("Restoration delegation does not match its retained authority.")


def _event(db, store, attempt, state, timestamp, reason=None):
    from .bulk_attempts import present as bulk_present

    bulk = bulk_present(db)
    registry = 'managed_bulk_registry' if bulk else 'managed_shun_registry'
    store._insert_event(db, ("MANAGED_BULK_ATTEMPT_" if bulk else "MANAGED_SHUN_RESTORATION_") + state, attempt["device_id"], IPv4Address(attempt["ip"]),
                        attempt["interface"] if state == "VERIFIED" else None, ACTOR, "Managed shun policy", (), attempt["id"],
                        {"source": SOURCE, "operation_id": attempt["job_id"], "intent_id": attempt["intent_id"],
                         **({"intent_format": 2} if bulk else {}),
                         "generation": attempt["generation"], "authorization_request_id": attempt["authorization_request_id"],
                         "snapshot_id": attempt["snapshot_id"], "reason": reason,
                         "managed_revision": db.execute(f"SELECT revision FROM {registry} WHERE id=1").fetchone()[0],
                         "protected_revision": db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0],
                         "occurrence_id": attempt["occurrence_id"] if state == "VERIFIED" else None}, timestamp)


def record_result(db, store, job, state, timestamp, reason=None):
    from .bulk_attempts import present as bulk_present

    attempt = attempt_for_job(db, job["id"])
    if attempt is None:
        return
    validate_binding(db, attempt, job)
    if job["action"] != "ADD" or attempt["device_id"] != job["device_id"] or attempt["ip"] != job["ip"]:
        raise ManagedStateUnavailable("Restoration job linkage is inconsistent.")
    occurrence = None
    if state == "VERIFIED":
        rows = db.execute("SELECT occurrence_id,interface FROM shun_state WHERE device_id=? AND ip=? AND active=1",
                          (job["device_id"], job["ip"])).fetchall()
        if len(rows) != 1 or not rows[0]["occurrence_id"]:
            raise ManagedStateUnavailable("Verified restoration is missing its occurrence.")
        occurrence = rows[0]
    table = 'managed_bulk_attempts' if bulk_present(db) else 'managed_restoration_attempts'
    db.execute(f"""UPDATE {table} SET state=?,completed_at=?,occurrence_id=?,interface=?
        WHERE id=?""", (state, None if state in {"QUEUED", "RUNNING"} else timestamp,
                       occurrence["occurrence_id"] if occurrence else None,
                       occurrence["interface"] if occurrence else None, attempt["id"]))
    if state in {"VERIFIED", "NOOP", "FAILED", "UNVERIFIED", "CANCELLED"}:
        db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=? AND state='ACTIVE'", (attempt["id"],))
    updated = db.execute(f"SELECT * FROM {table} WHERE id=?", (attempt["id"],)).fetchone()
    _event(db, store, updated, state, timestamp, reason)
    if table == 'managed_bulk_attempts':
        from .bulk_waits import settle_result as settle_bulk_result

        settle_bulk_result(db, store, updated, state, timestamp)
        return
    from .import_cancellations import settle_result

    settle_result(db, store, updated, state, timestamp)


def authority_valid(db, attempt):
    from .import_cancellations import held
    from .managed_closures import pair_abandoned

    row = db.execute("""SELECT t.*,d.enabled AS device_enabled,r.restoration_suspended
        FROM managed_shun_targets t JOIN devices d ON d.id=t.device_id
        CROSS JOIN managed_shun_registry r WHERE r.id=1 AND t.device_id=? AND t.ip=?""",
        (attempt["device_id"], attempt["ip"])).fetchone()
    return (row is not None and row["enabled"] and row["device_enabled"] and not row["restoration_suspended"]
            and row["intent_id"] == attempt["intent_id"] and row["generation"] == attempt["generation"]
            and row["revision"] == attempt["target_revision"]
            and row["authorization_request_id"] == attempt["authorization_request_id"]
            and not mutations_suspended(db)
            and not held(db, attempt)
            and not pair_abandoned(db, attempt["device_id"], IPv4Address(attempt["ip"]))
            and not db.execute("SELECT 1 FROM managed_restoration_attempts WHERE device_id=? AND ip=? AND state IN ('FAILED','UNVERIFIED')",
                               (attempt["device_id"], attempt["ip"])).fetchone()
            and not db.execute("SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1", (attempt["ip"],)).fetchone()
            and not fleet_target_held(db, attempt["device_id"], IPv4Address(attempt["ip"]), attention=True)
            and not (db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_removal_handoffs'").fetchone()
                     and db.execute("SELECT 1 FROM managed_removal_handoffs WHERE device_id=? AND ip=? AND state IN ('WAITING_ADD','ATTENTION')",
                                    (attempt["device_id"], attempt["ip"])).fetchone()))


def cancel_obsolete(db, queue):
    from .bulk_attempts import present as bulk_present
    from .bulk_policy import _state as bulk_state

    if bulk_present(db):
        bulk_state(db)
        from .bulk_dispatch import cancel_obsolete as cancel_bulk
        from .bulk_dispatch import present as dispatch_present

        if dispatch_present(db):
            cancel_bulk(db, queue)
            return
        for job in db.execute("""SELECT j.* FROM operation_jobs j JOIN managed_bulk_attempts a ON a.job_id=j.id
                WHERE j.state='QUEUED'""").fetchall():
            queue._finish(db, job, 'CANCELLED', 'Bulk dispatch/retry is unavailable; original attempt evidence retained')
        return
    if not present(db):
        return
    rows = db.execute("""SELECT j.* FROM operation_jobs j JOIN managed_restoration_attempts a ON a.job_id=j.id
        WHERE j.state='QUEUED'""").fetchall()
    for job in rows:
        if not authority_valid(db, attempt_for_job(db, job["id"])):
            queue._finish(db, job, "CANCELLED", "Standing restoration authority revoked or blocked before dispatch")


def read_scope(pairs):
    """Bound a local summary query to one page, never executable targets."""
    if (not isinstance(pairs, list) or len(pairs) > 100
            or any(not isinstance(pair, tuple) or len(pair) != 2
                   or type(pair[0]) is not int or not 1 <= pair[0] <= 65535
                   or type(pair[1]) is not bytes or len(pair[1]) != 4 for pair in pairs)
            or len(set(pairs)) != len(pairs)):
        raise ValueError("Read summaries require at most 100 distinct device/IP pairs.")
    if not pairs:
        return "WITH selected(device_id,ip) AS (SELECT NULL,NULL WHERE 0) ", []
    return ("WITH selected(device_id,ip) AS (VALUES " + ",".join("(?,?)" for _ in pairs) + ") ",
            [value for pair in pairs for value in pair])


def snapshot_targets(db, *, pairs=None):
    """Optional retained outcomes; never infer creation from observation or NOOP."""
    if not present(db):
        return {}
    if db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] > 10000:
        raise ManagedStateUnavailable("Restoration ledger exceeds this version's capacity.")
    if pairs is not None:
        cte, parameters = read_scope(pairs)
        rows = db.execute(cte + """, ranked AS (
            SELECT a.*,
                ROW_NUMBER() OVER (PARTITION BY a.device_id,a.ip ORDER BY a.requested_at DESC,a.id) AS position,
                MAX(a.state IN ('FAILED','UNVERIFIED')) OVER (PARTITION BY a.device_id,a.ip) AS attention
            FROM managed_restoration_attempts a JOIN selected s ON s.device_id=a.device_id AND s.ip=a.ip)
            SELECT r.*,(SELECT completed_at FROM managed_restoration_attempts v
                WHERE v.device_id=r.device_id AND v.ip=r.ip AND v.state='VERIFIED'
                ORDER BY v.requested_at DESC,v.id LIMIT 1) AS last_verified
            FROM ranked r WHERE position=1 ORDER BY device_id,ip""", parameters).fetchall()
        return {(row["device_id"], row["ip"]): {
            "restoration_state": row["state"], "restoration_attempt_id": row["id"],
            "restoration_generation": row["generation"], "restoration_attention": bool(row["attention"]),
            "last_verified_restoration_at": row["last_verified"]} for row in rows}
    rows = db.execute("SELECT * FROM managed_restoration_attempts ORDER BY requested_at DESC,id LIMIT 10001").fetchall()
    views = {}
    for row in rows:
        key = row["device_id"], row["ip"]
        view = views.setdefault(key, {"restoration_state": row["state"], "restoration_attempt_id": row["id"],
                                     "restoration_generation": row["generation"], "restoration_attention": False,
                                     "last_verified_restoration_at": None})
        view["restoration_attention"] |= row["state"] in {"FAILED", "UNVERIFIED"}
        if row["state"] == "VERIFIED" and view["last_verified_restoration_at"] is None:
            view["last_verified_restoration_at"] = row["completed_at"]
    return views


@dataclass(frozen=True)
class CompleteSnapshot:
    """Trusted complete-read evidence, not a browser/API request or capability."""
    id: str
    device_id: int
    started_at: datetime
    completed_at: datetime
    present_ips: frozenset[IPv4Address]
    complete: bool = True


class ManagedRestorations:
    def __init__(self, store, queue):
        if store.path != queue.store.path:
            raise ValueError("Restoration must use the shared queue database.")
        self.store, self.queue = store, queue

    def initialize(self, *, connection=None):
        """Explicit isolated migration only; never called by deployed services."""
        with schema_connection(self.store, connection) as db:
            if managed_state(db) is None or not db.execute("SELECT 1 FROM operation_executor WHERE id=1").fetchone():
                raise ValueError("Initialize the policy registry and queue explicitly first.")
            execute_schema(db, """
                CREATE TABLE IF NOT EXISTS managed_restoration_attempts (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
                    device_id INTEGER NOT NULL REFERENCES devices(id), ip BLOB NOT NULL CHECK(length(ip)=4),
                    intent_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    authorization_request_id TEXT NOT NULL REFERENCES managed_shun_requests(id), target_revision INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL,snapshot_started_at TEXT NOT NULL,snapshot_at TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED')),
                    completed_at TEXT,occurrence_id TEXT,interface TEXT,
                    UNIQUE(intent_id,snapshot_id)
                );
                CREATE INDEX IF NOT EXISTS idx_managed_restoration_pair ON managed_restoration_attempts(device_id,ip,requested_at);
                CREATE TRIGGER IF NOT EXISTS managed_restoration_authority_immutable BEFORE UPDATE OF
                    id,job_id,device_id,ip,intent_id,generation,authorization_request_id,target_revision,
                    snapshot_id,snapshot_started_at,snapshot_at,requested_at ON managed_restoration_attempts
                    BEGIN SELECT RAISE(ABORT,'restoration authority is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS managed_restoration_retained BEFORE DELETE ON managed_restoration_attempts
                    BEGIN SELECT RAISE(ABORT,'restoration evidence is retained'); END;
                CREATE TRIGGER IF NOT EXISTS managed_restoration_terminal_immutable BEFORE UPDATE ON managed_restoration_attempts
                    WHEN OLD.state IN ('VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED')
                    BEGIN SELECT RAISE(ABORT,'settled restoration evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS managed_restoration_monotonic BEFORE UPDATE OF state ON managed_restoration_attempts
                    WHEN NOT ((OLD.state='QUEUED' AND NEW.state IN ('RUNNING','CANCELLED','FAILED'))
                        OR (OLD.state='RUNNING' AND NEW.state IN ('QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED')))
                    BEGIN SELECT RAISE(ABORT,'restoration outcome cannot be replayed'); END;
            """)

    def admit_absence(self, snapshot: CompleteSnapshot, ip: IPv4Address, owner: str, *, enabled=False, expected_intent_id=None):
        """Trusted integration hook; only explicit controller capability admits work."""
        if type(enabled) is not bool:
            raise ValueError("Restoration capability must be boolean.")
        if not enabled:
            return None
        if (not isinstance(snapshot, CompleteSnapshot) or snapshot.complete is not True
                or type(snapshot.device_id) is not int or not 1 <= snapshot.device_id <= 65535
                or not isinstance(snapshot.id, str) or str(UUID(snapshot.id)) != snapshot.id or not isinstance(ip, IPv4Address)
                or not isinstance(snapshot.started_at, datetime) or not isinstance(snapshot.completed_at, datetime)
                or type(snapshot.present_ips) is not frozenset or len(snapshot.present_ips) > 65536
                or any(not isinstance(value, IPv4Address) for value in snapshot.present_ips)):
            raise ValueError("A complete validated snapshot is required.")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not present(db):
                raise ManagedStateUnavailable("Restoration schema is not initialized.")
            target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (snapshot.device_id, ip.packed)).fetchone()
            if target is None:
                raise QueueConflict("No explicit standing policy authorizes restoration.")
            if expected_intent_id is not None and target["intent_id"] != expected_intent_id:
                raise QueueConflict("Managed generation changed after discovery; no rebasing.")
            key = str(uuid5(UUID(target["intent_id"]), snapshot.id))
            old = db.execute("SELECT * FROM managed_restoration_attempts WHERE id=?", (key,)).fetchone()
            if old:
                if (old["snapshot_started_at"] != stamp(snapshot.started_at) or old["snapshot_at"] != stamp(snapshot.completed_at)
                        or ip in snapshot.present_ips):
                    raise QueueConflict("Snapshot key was reused for different evidence.")
                return {"operation_id": key, "status": "accepted", "replayed": True}
            from .managed_closures import key_reserved as closure_key_reserved

            if closure_key_reserved(db, key):
                raise QueueConflict("Incident closure keys cannot acquire restoration authority.")
            current = self.queue._now()
            if (snapshot.started_at.utcoffset() != timedelta(0) or snapshot.completed_at.utcoffset() != timedelta(0)
                    or snapshot.started_at > snapshot.completed_at or snapshot.completed_at > current
                    or current - snapshot.started_at > timedelta(seconds=120)
                    or stamp(snapshot.started_at) < target["updated_at"] or ip in snapshot.present_ips):
                raise QueueConflict("Absence evidence is stale, incomplete or predates policy.")
            candidate = {**dict(target), "target_revision": target["revision"]}
            if not authority_valid(db, candidate):
                raise QueueConflict("Standing restoration is suspended, retired or blocked.")
            if db.execute("SELECT 1 FROM shun_state WHERE device_id=? AND ip=? AND active=1", (snapshot.device_id, ip.packed)).fetchone():
                raise QueueConflict("A matching interface is still observed present.")
            latest = db.execute("""SELECT MAX(completed_at) FROM operation_jobs
                WHERE device_id=? AND ip=? AND state IN ('VERIFIED','NOOP')""", (snapshot.device_id, ip.packed)).fetchone()[0]
            if latest is not None and stamp(snapshot.started_at) <= latest:
                raise QueueConflict("Snapshot predates a newer verified/no-op operation; obtain a fresh read.")
            history = db.execute("SELECT * FROM managed_restoration_attempts WHERE device_id=? AND ip=? ORDER BY requested_at DESC",
                                 (snapshot.device_id, ip.packed)).fetchall()
            if any(row["state"] in {"QUEUED", "RUNNING", "FAILED", "UNVERIFIED"} for row in history):
                raise QueueConflict("Restoration is already pending or needs explicit reviewed resolution.")
            if history and (stamp(snapshot.started_at) <= history[0]["completed_at"]
                            or stamp(current - timedelta(seconds=300)) < history[0]["requested_at"]):
                raise QueueConflict("A newer snapshot and restoration backoff are required.")
            if sum(row["requested_at"] > stamp(current - timedelta(hours=1)) for row in history) >= 3:
                raise QueueConflict("Restoration churn limit reached; review the target.")
            if db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING','UNVERIFIED')",
                          (snapshot.device_id, ip.packed)).fetchone():
                raise QueueConflict("Independent work or uncertain ADD/REMOVE needs review; no coalescing.")
            if (db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] >= 10000
                    or self.queue._pending_count(db) >= 1000 or self.queue._active_request_count(db) >= 2000):
                raise QueueFull("Restoration ledger or shared queue is full.")
            lease = db.execute("SELECT * FROM operation_executor WHERE id=1").fetchone()
            if not owner or lease["owner"] != owner or not lease["lease_until"] or lease["lease_until"] <= stamp(self.queue._now()):
                raise QueueConflict("Executor lease lost; no restoration admitted.")
            job_id, timestamp = str(uuid4()), stamp(current)
            if any(db.execute(f"SELECT 1 FROM {table} WHERE id=?", (key,)).fetchone()
                   for table in ("operation_requests", "manual_import_batches", "managed_shun_requests")):
                raise QueueConflict("Restoration key is already reserved.")
            from .managed_safety import fleet_key_reserved

            if fleet_key_reserved(db, key) or (self.queue._handoffs_present(db) and db.execute(
                    "SELECT 1 FROM managed_removal_handoffs WHERE id=?", (key,)).fetchone()):
                raise QueueConflict("Restoration key is already reserved by cleanup authority.")
            db.execute("INSERT INTO managed_restoration_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'QUEUED',NULL,NULL,NULL)",
                       (key, job_id, snapshot.device_id, ip.packed, target["intent_id"], target["generation"],
                        target["authorization_request_id"], target["revision"], snapshot.id,
                        stamp(snapshot.started_at), stamp(snapshot.completed_at), timestamp))
            payload = json.dumps({"scope": "managed_restoration", "intent_id": target["intent_id"], "generation": target["generation"],
                                  "targets": [(snapshot.device_id, str(ip))]})
            db.execute("INSERT INTO operation_requests VALUES (?,?,?,?,?,?,?,?, 'ACTIVE')", (
                key, ACTOR, "Managed shun policy", "[]", "trusted_policy", payload,
                timestamp, stamp(current + timedelta(seconds=900))))
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,?,?,'QUEUED',?,'ADD')",
                       (job_id, snapshot.device_id, ip.packed, timestamp))
            db.execute("INSERT INTO operation_links VALUES (?,?)", (key, job_id))
            _event(db, self.store, db.execute("SELECT * FROM managed_restoration_attempts WHERE id=?", (key,)).fetchone(), "QUEUED", timestamp)
            self.queue._bump(db)
            final = self.queue._now()
            if lease["lease_until"] <= stamp(final) or final - snapshot.started_at > timedelta(seconds=120):
                raise QueueConflict("Executor lease or snapshot freshness expired during restoration admission.")
        print(json.dumps({"event": "managed_shun.restoration.queued", "request_id": key, "operation_id": job_id}), flush=True)
        return {"operation_id": key, "status": "accepted", "replayed": False}
