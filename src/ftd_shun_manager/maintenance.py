"""Offline recovery controls. No service startup, inventory, SSH or environment read."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4

from .managed_safety import fleet_waits_present
from .operation_queue import stamp
from .safety import mutations_suspended
from .store import Store


def _actor(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply a non-blank maintenance operator label of at most 100 characters.")
    return "maintenance:" + value  # Never impersonate a Web or directory actor.


def apply_recovery_control(db, store: Store, action: str, actor: str, *, now: datetime | None = None) -> dict:
    """Caller owns an offline write transaction. Audit and control changes are atomic.

    This cannot establish that remote RPCs have stopped; the operator must stop
    API/Web and ensure no previous RPC can still execute before calling it.
    """
    if not db.in_transaction:
        raise ValueError("Recovery controls require a caller-owned offline transaction.")
    if action not in {"suspend", "resume-mutations"}:
        raise ValueError("Unsupported recovery action.")
    subject = _actor(actor)
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Recovery time must include a timezone.")
    current = current.astimezone(UTC)
    timestamp, request_id = stamp(current), str(uuid4())
    db.execute("SAVEPOINT offline_recovery")
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"operation_executor", "operation_jobs", "operation_requests", "shun_events"}.issubset(tables):
            raise ValueError("An initialized queue database is required; recovery never initializes a service.")
        managed_tables = {"managed_shun_registry", "managed_shun_targets", "managed_shun_requests"}
        if tables & managed_tables and not managed_tables.issubset(tables):
            raise ValueError("Partial managed schema; repair/review the backup before recovery.")
        if "managed_removal_handoffs" in tables and not managed_tables.issubset(tables):
            raise ValueError("Handoffs without their policy registry; review the backup.")
        if "managed_fleet_removals" in tables:
            if not managed_tables.issubset(tables):
                raise ValueError("Fleet authority without its policy registry; review the backup.")
            if db.execute("SELECT 1 FROM managed_fleet_removals WHERE phase!='ADMITTED' LIMIT 1").fetchone():
                raise ValueError("Transitional fleet authority is inconsistent; review the backup.")
        if "managed_fleet_waits" in tables and "managed_fleet_removals" not in tables:
            raise ValueError("Fleet waiting cleanup without root authority; review the backup.")
        if "managed_fleet_waits" in tables:
            fleet_waits_present(db)  # Refuse orphan/partial evidence before any cancellation.
        columns = {row[1] for row in db.execute("PRAGMA table_info(operation_executor)")}
        if "mutations_suspended" not in columns:
            db.execute("ALTER TABLE operation_executor ADD COLUMN mutations_suspended INTEGER NOT NULL DEFAULT 0 CHECK(mutations_suspended IN (0,1))")
        if db.execute("SELECT 1 FROM operation_executor WHERE id=1").fetchone() is None:
            raise ValueError("Queue executor metadata is missing.")
        jobs = db.execute("SELECT * FROM operation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchall()
        waits = (db.execute("SELECT * FROM managed_removal_handoffs WHERE state IN ('WAITING_ADD','ADMITTING')").fetchall()
                 if "managed_removal_handoffs" in tables else [])
        fleet_waits = (db.execute("""SELECT w.*,r.payload_json FROM managed_fleet_waits w
            JOIN managed_fleet_removals r ON r.id=w.id WHERE w.state IN ('WAITING_ADD','ADMITTING')""").fetchall()
                       if "managed_fleet_waits" in tables else [])
        result = {"action": action, "queued_cancelled": 0, "running_unverified": 0,
                  "waiting_cancelled": 0, "requests_cancelled": 0, "restoration_suspended": None}
        if managed_tables.issubset(tables):
            policy = db.execute("SELECT restoration_suspended FROM managed_shun_registry WHERE id=1").fetchone()
            if policy is None:
                raise ValueError("Managed registry metadata is missing.")
            result["restoration_suspended"] = True
        if action == "resume-mutations":
            if not mutations_suspended(db):
                raise ValueError("Device mutations are not suspended.")
            if jobs or waits or fleet_waits:
                raise ValueError("Pending jobs/handoffs remain; suspend them before resuming.")
            if managed_tables.issubset(tables) and policy[0] != 1:
                raise ValueError("Desired restoration must remain suspended during ordinary resume.")
            db.execute("UPDATE operation_executor SET mutations_suspended=0,revision=revision+1 WHERE id=1")
        else:
            reason = "Suspended during offline recovery; review required, never automatically replay"
            for job in jobs:
                outcome = "UNVERIFIED" if job["state"] == "RUNNING" else "CANCELLED"
                db.execute("UPDATE operation_jobs SET state=?,completed_at=?,reason=? WHERE id=?",
                           (outcome, timestamp, reason, job["id"]))
                result["running_unverified" if outcome == "UNVERIFIED" else "queued_cancelled"] += 1
                store._insert_event(db, "SHUN_OPERATION_RECOVERY_SUSPENDED", job["device_id"],
                                    IPv4Address(job["ip"]), None, subject,
                                    "Offline recovery maintenance", (), request_id,
                                    {"operation_id": job["id"], "previous_state": job["state"], "outcome": outcome}, timestamp)
            for row in waits:
                db.execute("UPDATE managed_removal_handoffs SET state='CANCELLED',reason=? WHERE id=?", (reason, row["id"]))
                store._insert_event(db, "MANAGED_SHUN_CLEANUP_RECOVERY_SUSPENDED", row["device_id"],
                                    IPv4Address(row["ip"]), None, subject,
                                    "Offline recovery maintenance", (), request_id,
                                    {"handoff_request_id": row["id"], "predecessor_id": row["predecessor_id"]}, timestamp)
            result["waiting_cancelled"] = len(waits)
            for row in fleet_waits:
                db.execute("UPDATE managed_fleet_waits SET state='CANCELLED',reason=? WHERE id=?", (reason, row["id"]))
                store._insert_event(db, "MANAGED_SHUN_FLEET_CLEANUP_RECOVERY_SUSPENDED", None,
                                    IPv4Address(json.loads(row["payload_json"])["ip"]), None, subject,
                                    "Offline recovery maintenance", (), request_id,
                                    {"fleet_request_id": row["id"], "reserved_targets": row["target_count"]}, timestamp)
            result["waiting_cancelled"] += len(fleet_waits)
            result["requests_cancelled"] = db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE state='ACTIVE'").rowcount
            if managed_tables.issubset(tables):
                db.execute("UPDATE managed_shun_registry SET restoration_suspended=1,revision=revision+1 WHERE id=1")
            db.execute("""UPDATE operation_executor SET mutations_suspended=1,owner=NULL,lease_until=NULL,
                next_eligible_at=?,revision=revision+1 WHERE id=1""", (stamp(current + timedelta(seconds=60)),))
        store._insert_event(db, "RECOVERY_MUTATIONS_SUSPENDED" if action == "suspend" else "RECOVERY_MUTATIONS_RESUMED",
                            None, None, None, subject, "Offline recovery maintenance", (), request_id, result, timestamp)
    except Exception:
        db.execute("ROLLBACK TO offline_recovery")
        db.execute("RELEASE offline_recovery")
        raise
    db.execute("RELEASE offline_recovery")
    return result


def run_offline(database: Path, backup: Path, action: str, actor: str) -> dict:
    """Checked, exclusive-file backup before mutation; refuse concurrent commits."""
    _actor(actor)
    if action not in {"suspend", "resume-mutations"}:
        raise ValueError("Unsupported recovery action.")
    source_path = database.resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("Select an existing SQLite database file.")
    parent = backup.parent.resolve(strict=True)
    mode = parent.stat()
    if mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) & 0o077:
        raise ValueError("Backup directory must be owned by this operator and private (0700).")
    backup_path = parent / backup.name
    with closing(sqlite3.connect(source_path.as_uri() + "?mode=rw", uri=True)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database integrity checks failed; no recovery mutation was performed.")
        version = db.execute("PRAGMA data_version").fetchone()[0]
        fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        # Never call backup() on a connection holding a write transaction.
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok" or target.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup verification failed; no recovery mutation was performed.")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA data_version").fetchone()[0] != version:
            raise ValueError("Another process committed during backup. Stop writers; backup retained, no recovery mutation performed.")
        result = apply_recovery_control(db, Store(source_path), action, actor)
    return {**result, "backup": str(backup_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline recovery: stop API/Web and settle all old RPCs first.")
    parser.add_argument("action", choices=("suspend", "resume-mutations"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True, help="New file in an operator-owned private directory; never overwritten")
    parser.add_argument("--actor", required=True, help="Trusted-host operator label, stored with maintenance: prefix")
    parser.add_argument("--confirm-offline", action="store_true", help="Assert API/Web are stopped and no old RPC can still execute")
    parser.add_argument("--confirm-reviewed", action="store_true", help="Assert fresh observations and recovery state were reviewed before resuming ordinary mutations")
    args = parser.parse_args(argv)
    if not args.confirm_offline or (args.action == "resume-mutations" and not args.confirm_reviewed):
        parser.error("Explicit offline confirmation is required; resume also needs --confirm-reviewed.")
    try:
        result = run_offline(args.database, args.backup, args.action, args.actor)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, f"Recovery refused: {error}. Any created backup was retained.\n")
    print(json.dumps({"event": "maintenance.recovery.committed", **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
