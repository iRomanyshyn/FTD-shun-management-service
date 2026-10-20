"""Offline administrative receipts; original uncertainty and controls stay intact."""

import argparse
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from ipaddress import IPv4Address
from pathlib import Path
from uuid import UUID, uuid4

from .maintenance import _actor, checked_offline
from .managed_maintenance import _hash, _time
from .operation_queue import stamp
from .schema import execute_schema

LIMIT = 10000
KINDS = {"operation", "device_cleanup", "fleet_cleanup"}
SCHEMA = """
CREATE TABLE incident_acknowledgements (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
    reviewed_at TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TRIGGER incident_ack_immutable BEFORE UPDATE ON incident_acknowledgements
BEGIN SELECT RAISE(ABORT,'incident acknowledgment is immutable'); END;
CREATE TRIGGER incident_ack_retained BEFORE DELETE ON incident_acknowledgements
BEGIN SELECT RAISE(ABORT,'incident acknowledgment is retained'); END;
"""


def _objects(db):
    return [list(row) for row in db.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE sql IS NOT NULL AND (tbl_name='incident_acknowledgements'
            OR name LIKE 'incident_ack_%') ORDER BY type,name""")]


@lru_cache(maxsize=1)
def _expected():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("BEGIN")
        execute_schema(db, SCHEMA)
        return _objects(db)


def present(db):
    actual = _objects(db)
    if not actual:
        return False
    if actual != _expected():
        raise ValueError("Acknowledgment ledger is incomplete or changed; no state was initialized.")
    if db.execute("SELECT COUNT(*) FROM incident_acknowledgements").fetchone()[0] > LIMIT:
        raise ValueError("Acknowledgment ledger exceeds this version's capacity.")
    return True


def key_reserved(db, key):
    return present(db) and db.execute("SELECT 1 FROM incident_acknowledgements WHERE id=?", (key,)).fetchone() is not None


def decision(db, case_id):
    if not present(db):
        return None
    row = db.execute("SELECT * FROM incident_acknowledgements WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["result_json"])
        if (result["request_id"] != row["id"] or result["case_id"] != case_id
                or result["decision"] != "ACKNOWLEDGE_UNRESOLVED"
                or result["acknowledged_at"] != row["acknowledged_at"]
                or result["outcome_unchanged"] not in {"UNVERIFIED", "ATTENTION"}
                or result["controls_unchanged"] is not True or result["replayed"] is not False):
            raise ValueError
        return {key: result[key] for key in ("request_id", "decision", "acknowledged_at", "outcome_unchanged", "controls_unchanged")}
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("Acknowledgment receipt is inconsistent.") from error


def _case_id(value):
    try:
        kind, key = value.split(":")
        if kind not in KINDS or str(UUID(key)) != key:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Supply an operation/device_cleanup/fleet_cleanup canonical case ID.") from error
    return value


def _inputs(request_id, case_id, actor, reason, issued):
    if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
        raise ValueError("Supply the original canonical acknowledgment UUID.")
    if not isinstance(reason, str):
        raise TypeError("Supply a printable acknowledgment reason.")
    reason = reason.strip()
    if not 1 <= len(reason) <= 500 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise ValueError("Supply a nonblank printable reason of at most 500 characters.")
    return {"request_id": request_id, "case_id": _case_id(case_id), "actor_subject": _actor(actor),
            "reason": reason, "reviewed_at": stamp(_time(issued))}


def _snapshot(db):
    from .managed_attention import attention_report
    from .managed_maintenance import _objects as schema_objects

    if not db.in_transaction:
        raise ValueError("Acknowledgment requires a caller-owned offline transaction.")
    snapshot = attention_report(db)
    blockers = []
    if not snapshot["mutations_suspended"] or (snapshot["managed_initialized"] and snapshot["restoration_suspended"] is not True):
        blockers.append("Suspend ordinary and existing desired mutations before offline acknowledgment.")
    if snapshot["executor_lease_present"] or snapshot["pending_jobs"]:
        blockers.append("Settle all RPCs, executor leases and pending jobs first.")
    pending = snapshot["pending_managed"]
    if pending and (any(pending[key] for key in ("restoration", "device_cleanup", "fleet_cleanup"))
                    or pending["inconsistent_fleet_admissions"]):
        blockers.append("Unfinished managed work remains; no partial acknowledgment is permitted.")
    return snapshot, blockers, _hash({"schema": schema_objects(db), "snapshot": snapshot["snapshot_digest"]})


def _review_time(reviewed_at, now):
    current = _time(now or datetime.now(UTC))
    issued = _time(reviewed_at or current)
    if issued > current or current - issued >= timedelta(minutes=5):
        raise ValueError("Review expired or is in the future; no automatic rebase.")
    return current, issued


def _reserved(db, key):
    from .incident_isolations import key_reserved as isolation_key_reserved

    if isolation_key_reserved(db, key):
        return True
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("operation_requests", "operation_jobs", "manual_import_batches", "managed_shun_requests",
                  "managed_removal_handoffs", "managed_incident_closures", "incident_acknowledgements"):
        if table in tables and db.execute(f"SELECT 1 FROM {table} WHERE id=?", (key,)).fetchone():
            return True
    if "managed_restoration_attempts" in tables and db.execute(
            "SELECT 1 FROM managed_restoration_attempts WHERE id=? OR job_id=?", (key, key)).fetchone():
        return True
    return "managed_fleet_removals" in tables and db.execute(
        "SELECT 1 FROM managed_fleet_removals WHERE id=? OR retirement_request_id=?", (key, key)).fetchone() is not None


def review_migration(db, *, reviewed_at=None, now=None):
    _, issued = _review_time(reviewed_at, now)
    snapshot, blockers, digest = _snapshot(db)
    if present(db):
        raise ValueError("Acknowledgment ledger already exists; no implicit repair or replay.")
    return {"action": "enable-acknowledgements", "reviewed_at": stamp(issued),
            "expires_at": stamp(issued + timedelta(minutes=5)), "ready": not blockers, "blockers": blockers,
            "managed_initialized": snapshot["managed_initialized"],
            "confirmation_digest": _hash(["enable-acknowledgements-v1", stamp(issued), digest])}


def enable(db, store, actor, reviewed_at, digest, *, now=None):
    subject = _actor(actor)
    current, _ = _review_time(reviewed_at, now)
    frozen = review_migration(db, reviewed_at=reviewed_at, now=current)
    _confirm(frozen, digest)
    db.execute("SAVEPOINT incident_ack")
    try:
        execute_schema(db, SCHEMA)
        present(db)
        result = {"action": "enable-acknowledgements", "acknowledgements": 0, "controls_unchanged": True}
        store._insert_event(db, "INCIDENT_ACKNOWLEDGEMENTS_INITIALIZED", None, None, None, subject,
                            "Offline incident maintenance", (), str(uuid4()), result, stamp(current))
        _check_commit_expiry(reviewed_at, now)
    except Exception:
        db.execute("ROLLBACK TO incident_ack")
        db.execute("RELEASE incident_ack")
        raise
    db.execute("RELEASE incident_ack")
    return result


def _evidence(db, case_id):
    from .managed_attention import attention_case

    first = attention_case(db, case_id)
    targets = list(first["targets"])
    for page in range(2, first["total_pages"] + 1):
        targets.extend(attention_case(db, case_id, page=page, snapshot_digest=first["snapshot_digest"])["targets"])
    case = first["case"]
    jobs = [case["related_job"]] + [target["predecessor"] for target in targets if "predecessor" in target]
    if any(job["state"] == "inconsistent" or job.get("outcome") in {"QUEUED", "RUNNING"} for job in jobs):
        raise ValueError("Incident predecessor/job evidence is inconsistent or unfinished.")
    ip = case.get("ip") if case["kind"] == "fleet_cleanup" else targets[0]["current"]["ip"]
    return {"case": case, "ip": ip, "target_count": first["target_count"],
            "reviewed_scope": first["reviewed_scope"], "targets": targets}


def prepare(db, request_id, case_id, actor, reason, *, reviewed_at=None, now=None):
    _, issued = _review_time(reviewed_at, now)
    inputs = _inputs(request_id, case_id, actor, reason, issued)
    _, blockers, digest = _snapshot(db)
    if not present(db):
        raise ValueError("Explicit acknowledgment migration is required; no schema was initialized.")
    evidence = _evidence(db, case_id)
    if _reserved(db, request_id):
        blockers.append("Request key is reserved; preserve the original receipt/key.")
    if decision(db, case_id):
        blockers.append("Incident already acknowledged; use its original receipt.")
    if db.execute("SELECT COUNT(*) FROM incident_acknowledgements").fetchone()[0] >= LIMIT:
        blockers.append("Retained acknowledgment ledger is full; no automatic recycling.")
    return {**inputs, "action": "ACKNOWLEDGE_UNRESOLVED", "ready": not blockers, "blockers": blockers,
            "expires_at": stamp(issued + timedelta(minutes=5)), "evidence": evidence,
            "confirmation_digest": _hash(["acknowledge-unresolved-v1", inputs, digest, evidence]),
            "warning": "Records operator review. Original outcomes, policy, evidence holds and resume blockers remain unchanged."}


def _confirm(frozen, digest):
    if not isinstance(digest, str) or not digest.isascii() or not hmac.compare_digest(frozen["confirmation_digest"], digest):
        raise ValueError("Reviewed state changed; no automatic rebase or new key after an unknown reply.")
    if not frozen["ready"]:
        raise ValueError("Acknowledgment blocked: " + " ".join(frozen["blockers"]))


def _check_commit_expiry(issued, now):
    if now is None and datetime.now(UTC) >= issued + timedelta(minutes=5):
        raise ValueError("Review expired before commit; changes rolled back.")


def apply(db, store, request_id, case_id, actor, reason, reviewed_at, digest, confirm_ip, confirm_target_count, *, now=None):
    if not db.in_transaction:
        raise ValueError("Acknowledgment requires a caller-owned offline transaction.")
    inputs = _inputs(request_id, case_id, actor, reason, reviewed_at)
    ip = IPv4Address(confirm_ip)
    if str(ip) != confirm_ip or type(confirm_target_count) is not int or not 1 <= confirm_target_count <= 1000:
        raise ValueError("Type the exact canonical IPv4 and original target count.")
    if not isinstance(digest, str) or not digest.isascii():
        raise ValueError("Exact review digest required.")
    if not present(db):
        raise ValueError("Explicit acknowledgment migration is required.")
    request = {**inputs, "confirmation_digest": digest, "confirm_ip": confirm_ip, "confirm_target_count": confirm_target_count}
    old = db.execute("SELECT request_json,result_json,case_id FROM incident_acknowledgements WHERE id=?", (request_id,)).fetchone()
    if old:
        decision(db, old["case_id"])
        if json.loads(old["request_json"]) != request:
            raise ValueError("Acknowledgment key was used for different reviewed inputs.")
        return {**json.loads(old["result_json"]), "replayed": True}
    current = _time(now or datetime.now(UTC))
    frozen = prepare(db, request_id, case_id, actor, reason, reviewed_at=reviewed_at, now=current)
    _confirm(frozen, digest)
    evidence = frozen["evidence"]
    if evidence["ip"] != confirm_ip or evidence["target_count"] != confirm_target_count:
        raise ValueError("Typed IPv4/target count does not match the entire reviewed scope.")
    db.execute("SAVEPOINT incident_ack")
    try:
        result = {"request_id": request_id, "case_id": case_id, "decision": "ACKNOWLEDGE_UNRESOLVED",
                  "ip": confirm_ip, "target_count": confirm_target_count, "acknowledged_at": stamp(current),
                  "outcome_unchanged": evidence["case"]["outcome"], "controls_unchanged": True, "replayed": False}
        def dump(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO incident_acknowledgements VALUES (?,?,?,?,?,?,?,?,?)",
                   (request_id, case_id, inputs["actor_subject"], inputs["reason"], inputs["reviewed_at"], stamp(current),
                    dump(request), dump(evidence), dump(result)))
        store._insert_event(db, "INCIDENT_ACKNOWLEDGED", None, ip, None, inputs["actor_subject"],
                            "Offline incident acknowledgment", (), request_id,
                            {**result, "reason": inputs["reason"], "review_digest": digest}, stamp(current))
        _check_commit_expiry(reviewed_at, now)
    except Exception:
        db.execute("ROLLBACK TO incident_ack")
        db.execute("RELEASE incident_ack")
        raise
    db.execute("RELEASE incident_ack")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline acknowledgment; stop API/Web and settle all RPCs first.")
    parser.add_argument("action", choices=("review-enable", "enable", "review", "acknowledge",
                                          "review-enable-isolation", "enable-isolation", "review-isolate", "isolate"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirm-offline", action="store_true")
    parser.add_argument("--confirm-reviewed", action="store_true")
    parser.add_argument("--case-id")
    parser.add_argument("--request-id")
    parser.add_argument("--reason")
    parser.add_argument("--reviewed-at")
    parser.add_argument("--review-digest")
    parser.add_argument("--confirm-ip")
    parser.add_argument("--confirm-target-count", type=int)
    args = parser.parse_args(argv)
    readonly = args.action.startswith("review")
    isolation = args.action in {"review-enable-isolation", "enable-isolation", "review-isolate", "isolate"}
    if isolation:
        from . import incident_isolations as workflow
    else:
        import sys

        workflow = sys.modules[__name__]
    if not args.confirm_offline or (not readonly and not all((args.backup, args.confirm_reviewed, args.reviewed_at, args.review_digest))):
        parser.error("Offline confirmation required; writes need a new backup and reviewed timestamp/digest/confirmation.")
    if args.action in {"review", "acknowledge", "review-isolate", "isolate"}:
        if not args.case_id or not args.reason or (not readonly and not all((args.request_id, args.confirm_ip, args.confirm_target_count))):
            parser.error("Case/reason required; acknowledgment also needs original UUID, typed IPv4 and target count.")
    elif any(value is not None for value in (args.case_id, args.reason, args.request_id, args.confirm_ip, args.confirm_target_count)):
        parser.error("Case/decision fields are not accepted for ledger migration.")
    try:
        _actor(args.actor)
        if not args.database.is_absolute() or (args.backup and not args.backup.is_absolute()):
            raise ValueError("Supply reviewed absolute database/backup paths.")
        if readonly:
            with closing(sqlite3.connect(args.database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Database integrity checks failed.")
                result = (workflow.review_migration(db) if args.action in {"review-enable", "review-enable-isolation"} else
                          workflow.prepare(db, args.request_id or str(uuid4()), args.case_id, args.actor, args.reason))
        else:
            issued = _time(datetime.fromisoformat(args.reviewed_at))
            if args.action in {"enable", "enable-isolation"}:
                result = checked_offline(args.database, args.backup, lambda db, store:
                                         workflow.enable(db, store, args.actor, issued, args.review_digest))
            else:
                result = checked_offline(args.database, args.backup, lambda db, store:
                    workflow.apply(db, store, args.request_id, args.case_id, args.actor, args.reason, issued,
                          args.review_digest, args.confirm_ip, args.confirm_target_count))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Incident acknowledgment refused: {error}. Any created backup was retained.\n")
    print(json.dumps({"event": "maintenance.incident.review" if readonly else "maintenance.incident.committed", **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
