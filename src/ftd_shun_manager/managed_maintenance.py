"""Explicit offline managed migration/resume; no environment, agent or service startup."""

import argparse
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4

from .maintenance import _actor, checked_offline
from .managed_fleet_removals import ManagedFleetRemovals
from .managed_intent import canonical_managed_change
from .managed_removals import ManagedRemovals
from .managed_restoration import ManagedRestorations, present
from .managed_safety import managed_state
from .managed_shuns import ManagedShuns
from .operation_queue import OperationQueue, stamp
from .store import Store

TABLES = {
    "managed_shun_registry": 1, "managed_shun_targets": 1000,
    "managed_shun_requests": 10000, "managed_restoration_attempts": 10000,
    "managed_removal_handoffs": 10000, "managed_fleet_removals": 10000,
    "managed_fleet_waits": 10000,
}


def _initialize(db, store):
    registry, queue = ManagedShuns(store), OperationQueue(store)
    registry.initialize(connection=db)
    ManagedRestorations(store, queue).initialize(connection=db)
    ManagedRemovals(registry, queue).initialize(connection=db)
    ManagedFleetRemovals(registry, queue).initialize(connection=db)


def _objects(db):
    return [list(row) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]


def _owned(objects):
    return [row for row in objects if row[1].startswith(("managed_", "idx_managed_", "fleet_wait_", "idx_fleet_wait_"))
            or row[2] in TABLES]


@lru_cache(maxsize=1)
def _expected_schema():
    # Generate the contract from the same trusted DDL, without a file or Store startup.
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE devices(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE operation_executor(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO operation_executor VALUES (1)")
        _initialize(db, Store(Path("/unused-managed-schema-contract")))
        return _owned(_objects(db))


def _hash(value):
    def encode(item):
        if isinstance(item, bytes):
            return {"bytes": item.hex()}
        raise TypeError("Unsupported reviewed database value.")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode).encode()).hexdigest()


def _time(value):
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("Maintenance time must be UTC with timezone.")
    return value


def review(db, action, *, reviewed_at=None, now=None):
    """Caller owns a read snapshot or write transaction; this function never writes."""
    if not db.in_transaction:
        raise ValueError("Review requires a caller-owned transaction.")
    if action not in {"initialize", "resume-policy"}:
        raise ValueError("Unsupported managed maintenance action.")
    current = _time(now or datetime.now(UTC))
    issued = _time(reviewed_at or current)
    if issued > current or current - issued >= timedelta(minutes=5):
        raise ValueError("Review expired or has a future timestamp; prepare a new offline review.")
    objects = _objects(db)
    owned = _owned(objects)
    if action == "initialize" and owned:
        raise ValueError("Existing or partial managed schema; initialization never repairs or adopts it.")
    if action == "resume-policy" and owned != _expected_schema():
        raise ValueError("Exact complete managed schema required; partial or changed schema needs separate review.")
    executor = db.execute("SELECT revision,owner,lease_until,next_eligible_at,mutations_suspended FROM operation_executor WHERE id=1").fetchone()
    protection = db.execute("SELECT * FROM protected_policy WHERE id=1").fetchone()
    if executor is None or protection is None or executor["mutations_suspended"] not in (0, 1):
        raise ValueError("Current queue/protection metadata required; no base migration is performed.")
    pending = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
    uncertain = db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='UNVERIFIED'").fetchone()[0]
    blockers = []
    if executor["owner"] is not None or executor["lease_until"] is not None:
        blockers.append("Executor lease remains; settle RPCs and use offline recovery first.")
    if pending:
        blockers.append("Pending jobs remain; use offline recovery first.")
    if bool(executor["mutations_suspended"]) != (action == "initialize"):
        blockers.append("Initialization requires the ordinary pause; policy resume requires reviewed ordinary resume first.")
    state = {"schema": objects, "executor": dict(executor), "protection": dict(protection),
             "protected_ips": [list(row) for row in db.execute("SELECT * FROM protected_ips ORDER BY ip")],
             "devices": [list(row) for row in db.execute("SELECT * FROM devices ORDER BY id")],
             "pending_jobs": pending, "uncertain_jobs": uncertain}
    targets = []
    if action == "resume-policy":
        registry = managed_state(db)
        if registry is None or not present(db):
            raise ValueError("Managed evidence is unavailable.")
        for table, limit in TABLES.items():
            # Names/limits are trusted constants, never CLI values.
            rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid LIMIT ?", (limit + 1,)).fetchall()
            if len(rows) > limit:
                raise ValueError("Managed state exceeds this version's capacity.")
            state[table] = [dict(row) for row in rows]
        if not registry["restoration_suspended"]:
            blockers.append("Desired restoration is not suspended.")
        if uncertain or db.execute("SELECT 1 FROM managed_restoration_attempts WHERE state IN ('QUEUED','RUNNING','FAILED','UNVERIFIED') LIMIT 1").fetchone():
            blockers.append("Pending or uncertain restoration/work requires separate resolution; resume never rearms it.")
        if (db.execute("SELECT 1 FROM managed_removal_handoffs WHERE state IN ('WAITING_ADD','ADMITTING','ATTENTION') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM managed_fleet_waits WHERE state IN ('WAITING_ADD','ADMITTING','ATTENTION') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM managed_fleet_removals WHERE phase!='ADMITTED' LIMIT 1").fetchone()):
            blockers.append("Unfinished or attention cleanup requires separate resolution.")
        rows = db.execute("""SELECT t.*, d.hostname,d.enabled AS device_enabled,r.actor_subject,r.payload_json,
            EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=t.ip AND p.enabled=1) AS protected
            FROM managed_shun_targets t JOIN devices d ON d.id=t.device_id
            JOIN managed_shun_requests r ON r.id=t.authorization_request_id WHERE t.enabled=1
            ORDER BY t.device_id,t.ip""").fetchall()
        if len(rows) != db.execute("SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1").fetchone()[0]:
            raise ValueError("Enabled target is missing its device or retained authority.")
        for row in rows:
            payload = json.loads(row["payload_json"])
            ip = str(IPv4Address(row["ip"]))
            _, canonical, _ = canonical_managed_change(
                "MAINTAIN", [(device, IPv4Address(address)) for device, address in payload["targets"]],
                payload["managed_revision"], payload["policy_revision"], payload["label"], payload["reason"])
            if canonical != row["payload_json"] or [row["device_id"], ip] not in payload["targets"]:
                raise ValueError("Enabled target lacks matching retained standing authority.")
            if current <= datetime.fromisoformat(row["updated_at"]):
                blockers.append("Policy time is not before resume time; review clock/state first.")
            if not row["device_enabled"] or row["protected"]:
                blockers.append("Enabled targets include disabled devices or protected addresses; retire/review them first.")
            targets.append({key: row[key] for key in ("device_id", "hostname", "intent_id", "generation", "authorization_request_id", "actor_subject")}
                           | {"ip": ip, "label": payload["label"], "reason": payload["reason"]})
        if not targets:
            blockers.append("No enabled standing targets to resume.")
    state_digest = _hash(state)
    timestamp = stamp(issued)
    return {"action": action, "reviewed_at": timestamp, "expires_at": stamp(issued + timedelta(minutes=5)),
            "ready": not blockers, "blockers": list(dict.fromkeys(blockers)), "targets": targets,
            "state_digest": state_digest,
            "confirmation_digest": _hash({"action": action, "reviewed_at": timestamp, "state_digest": state_digest})}


def apply_reviewed(db, store, action, actor, reviewed_at, digest, *, now=None):
    """Atomic DDL/control/audit; catches roll back even if the caller later commits."""
    subject, current = _actor(actor), _time(now or datetime.now(UTC))
    reviewed_at = _time(reviewed_at)
    frozen = review(db, action, reviewed_at=reviewed_at, now=current)
    if not isinstance(digest, str) or not digest.isascii() or not hmac.compare_digest(frozen["confirmation_digest"], digest):
        raise ValueError("Reviewed state changed; no automatic rebase. Prepare a new offline review.")
    if not frozen["ready"]:
        raise ValueError("Review is blocked: " + " ".join(frozen["blockers"]))
    db.execute("SAVEPOINT managed_maintenance")
    try:
        timestamp = stamp(current)
        if action == "initialize":
            _initialize(db, store)
            if _owned(_objects(db)) != _expected_schema():
                raise ValueError("Managed schema contract mismatch; migration rolled back.")
            result = {"action": action, "managed_revision": 0, "restoration_suspended": True, "enabled_targets": 0}
        else:
            revision = db.execute("SELECT revision FROM managed_shun_registry WHERE id=1").fetchone()[0] + 1
            # Not a new grant: retain intent/generation/authorized_at and every immutable request.
            barrier = stamp(current + timedelta(milliseconds=1))
            db.execute("UPDATE managed_shun_targets SET revision=?,updated_at=? WHERE enabled=1", (revision, barrier))
            db.execute("UPDATE managed_shun_registry SET revision=?,restoration_suspended=0 WHERE id=1", (revision,))
            result = {"action": action, "managed_revision": revision, "restoration_suspended": False,
                      "enabled_targets": len(frozen["targets"]), "absence_not_before": barrier}
        store._insert_event(db, "MANAGED_SCHEMA_INITIALIZED" if action == "initialize" else "MANAGED_POLICY_RESUMED",
                            None, None, None, subject, "Offline managed maintenance", (), str(uuid4()),
                            {**result, "reviewed_at": frozen["reviewed_at"], "state_digest": frozen["state_digest"]}, timestamp)
        if datetime.now(UTC) >= reviewed_at + timedelta(minutes=5) and now is None:
            raise ValueError("Review expired during maintenance; changes rolled back.")
    except Exception:
        db.execute("ROLLBACK TO managed_maintenance")
        db.execute("RELEASE managed_maintenance")
        raise
    db.execute("RELEASE managed_maintenance")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline managed schema/policy control; stop API/Web and settle RPCs first.")
    parser.add_argument("action", choices=("review-initialize", "initialize", "review-resume", "resume-policy"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--reviewed-at")
    parser.add_argument("--review-digest")
    parser.add_argument("--confirm-offline", action="store_true")
    parser.add_argument("--confirm-reviewed", action="store_true")
    args = parser.parse_args(argv)
    readonly = args.action.startswith("review-")
    if not args.confirm_offline or (not readonly and not (args.confirm_reviewed and args.backup and args.reviewed_at and args.review_digest)):
        parser.error("Explicit offline confirmation is required; writes also require backup and reviewed timestamp/digest/confirmation.")
    try:
        _actor(args.actor)
        if not args.database.is_absolute() or (args.backup and not args.backup.is_absolute()):
            raise ValueError("Supply reviewed absolute database and backup paths.")
        if readonly:
            with closing(sqlite3.connect(args.database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Database integrity checks failed.")
                result = review(db, "initialize" if args.action == "review-initialize" else "resume-policy")
        else:
            issued = _time(datetime.fromisoformat(args.reviewed_at))
            result = checked_offline(args.database, args.backup, lambda db, store:
                                     apply_reviewed(db, store, args.action, args.actor, issued, args.review_digest))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Managed maintenance refused: {error}. Any created backup was retained.\n")
    print(json.dumps({"event": "maintenance.managed.review" if readonly else "maintenance.managed.committed", **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
