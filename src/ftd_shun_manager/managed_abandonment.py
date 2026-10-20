"""Reviewed offline revocation only: unknown writes never become verified or replayed."""

import hmac
import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID

from .maintenance import _actor
from .managed_closures import LIMIT, present
from .managed_safety import fleet_target_held
from .operation_queue import stamp


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("An explicit canonical UUID is required.")
    return value


def _input(request_id, case_id, actor, reason, reviewed_at):
    from .managed_maintenance import _time

    _uuid(request_id)
    if not isinstance(case_id, str) or not case_id.startswith("restoration:"):
        raise ValueError("Only restoration incidents support abandonment; ordinary/fleet cleanup requires separate controls.")
    attempt_id = _uuid(case_id[len("restoration:"):])
    if not isinstance(reason, str):
        raise TypeError("Supply a reason.")
    reason = reason.strip()
    if not 1 <= len(reason) <= 500 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise ValueError("Supply a nonblank printable reason of at most 500 characters.")
    return {"request_id": request_id, "case_id": "restoration:" + attempt_id,
            "actor_subject": _actor(actor), "reason": reason, "reviewed_at": stamp(_time(reviewed_at))}


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _evidence(db, attempt_id):
    row = db.execute("SELECT * FROM managed_restoration_attempts WHERE id=?", (attempt_id,)).fetchone()
    if row is None or row["state"] not in {"FAILED", "UNVERIFIED"}:
        raise ValueError("A retained FAILED/UNVERIFIED restoration incident is required.")
    attempt = dict(row)
    attempt["ip"] = str(IPv4Address(row["ip"]))
    job = db.execute("SELECT id,device_id,ip,action,state,requested_at,started_at,completed_at FROM operation_jobs WHERE id=?",
                     (row["job_id"],)).fetchone()
    if job is not None and (job["action"] != "ADD" or job["device_id"] != row["device_id"] or job["ip"] != row["ip"]
                            or job["state"] != row["state"]):
        raise ValueError("Retained job disagrees with the incident; review inconsistent evidence separately.")
    target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (row["device_id"], row["ip"])).fetchone()
    if target is None:
        raise ValueError("Current managed target is missing; abandonment never invents policy.")
    target = dict(target)
    target["ip"] = attempt["ip"]
    retained_job = dict(job) if job else None
    if retained_job:
        retained_job["ip"] = attempt["ip"]
    return {"attempt": attempt, "current_target": target, "job": retained_job}


def _reserved(db, key):
    from .incident_acknowledgements import key_reserved

    if key_reserved(db, key):
        return True
    for table in ("operation_requests", "operation_jobs", "manual_import_batches", "managed_shun_requests",
                  "managed_removal_handoffs", "managed_incident_closures"):
        if db.execute(f"SELECT 1 FROM {table} WHERE id=?", (key,)).fetchone():
            return True
    return (db.execute("SELECT 1 FROM managed_restoration_attempts WHERE id=? OR job_id=?", (key, key)).fetchone()
            or db.execute("SELECT 1 FROM managed_fleet_removals WHERE id=? OR retirement_request_id=?", (key, key)).fetchone()) is not None


def prepare(db, request_id, case_id, actor, reason, *, reviewed_at=None, now=None):
    from .managed_attention import attention_report
    from .managed_maintenance import _hash, _time, recognized_schema

    if not db.in_transaction:
        raise ValueError("Abandonment review requires a caller-owned transaction.")
    current = _time(now or datetime.now(UTC))
    issued = _time(reviewed_at or current)
    inputs = _input(request_id, case_id, actor, reason, issued)
    if issued > current or current - issued >= timedelta(minutes=5):
        raise ValueError("Review expired or is in the future; no automatic rebase.")
    if not recognized_schema(db) or not present(db):
        raise ValueError("Explicit reviewed closure migration is required; no schema was initialized.")
    snapshot = attention_report(db)
    evidence = _evidence(db, case_id[len("restoration:"):])
    attempt, target = evidence["attempt"], evidence["current_target"]
    ip, device = IPv4Address(attempt["ip"]), attempt["device_id"]
    blockers = []
    if _reserved(db, request_id):
        blockers.append("Request key is reserved; do not replace or reuse another operation's authority.")
    if not snapshot["mutations_suspended"] or snapshot["restoration_suspended"] is not True:
        blockers.append("Ordinary and desired mutations must both be suspended for offline abandonment.")
    if snapshot["executor_lease_present"] or snapshot["pending_jobs"]:
        blockers.append("Executor lease/pending jobs remain; settle RPCs and suspend work first.")
    pending = snapshot["pending_managed"]
    if any(pending[kind] for kind in ("restoration", "device_cleanup", "fleet_cleanup")) or pending["inconsistent_fleet_admissions"]:
        blockers.append("Unfinished managed work remains; no partial incident abandonment is permitted.")
    if (fleet_target_held(db, device, ip, attention=True) or db.execute("""SELECT 1 FROM managed_removal_handoffs
            WHERE device_id=? AND ip=? AND state IN ('WAITING_ADD','ADMITTING','ATTENTION')""", (device, ip.packed)).fetchone()):
        blockers.append("Overlapping cleanup scope requires separate whole-scope review.")
    if db.execute("SELECT 1 FROM managed_incident_closures WHERE attempt_id=?", (attempt["id"],)).fetchone():
        blockers.append("Incident already has an immutable abandonment decision; use its original receipt.")
    if db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0] >= LIMIT:
        blockers.append("Retained closure ledger is full; no key recycling is available.")
    if current < datetime.fromisoformat(target["updated_at"]):
        blockers.append("Policy time is in the future; review clock/state before retirement.")
    digest = _hash({**inputs, "action": "ABANDON_MAINTENANCE", "snapshot_digest": snapshot["snapshot_digest"],
                    "evidence": evidence})
    return {**inputs, "action": "ABANDON_MAINTENANCE", "ready": not blockers, "blockers": blockers,
            "expires_at": stamp(issued + timedelta(minutes=5)), "confirmation_digest": digest,
            "snapshot_digest": snapshot["snapshot_digest"], "evidence": evidence,
            "warning": "Retire current maintenance only. Original failure/uncertainty and restoration latch remain; no retry or resume is authorized."}


def apply(db, store, request_id, case_id, actor, reason, reviewed_at, digest, confirm_ip, *, now=None):
    from .managed_maintenance import _time, recognized_schema

    if not db.in_transaction:
        raise ValueError("Abandonment requires a caller-owned transaction.")
    inputs = _input(request_id, case_id, actor, reason, reviewed_at)
    ip = IPv4Address(confirm_ip)
    if str(ip) != confirm_ip or not isinstance(digest, str) or not digest.isascii():
        raise ValueError("Canonical typed IPv4 and exact review digest required.")
    if not recognized_schema(db):
        raise ValueError("Explicit closure migration is required.")
    request = _dump({**inputs, "confirmation_digest": digest, "confirm_ip": confirm_ip})
    old = db.execute("SELECT actor_subject,request_json,result_json FROM managed_incident_closures WHERE id=?", (request_id,)).fetchone()
    if old:
        if old["actor_subject"] != inputs["actor_subject"] or old["request_json"] != request:
            raise ValueError("Closure request key was already used for different reviewed inputs.")
        return {**json.loads(old["result_json"]), "replayed": True}
    current = _time(now or datetime.now(UTC))
    frozen = prepare(db, request_id, case_id, actor, reason, reviewed_at=reviewed_at, now=current)
    if not hmac.compare_digest(frozen["confirmation_digest"], digest):
        raise ValueError("Reviewed state changed; do not rebase or rekey an unknown submission.")
    if not frozen["ready"]:
        raise ValueError("Abandonment blocked: " + " ".join(frozen["blockers"]))
    target, attempt = frozen["evidence"]["current_target"], frozen["evidence"]["attempt"]
    if target["ip"] != confirm_ip:
        raise ValueError("Typed IPv4 does not match the reviewed incident.")
    db.execute("SAVEPOINT managed_abandonment")
    try:
        timestamp = stamp(current)
        revision = db.execute("SELECT revision FROM managed_shun_registry WHERE id=1").fetchone()[0] + 1
        if target["enabled"]:
            db.execute("UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=? WHERE device_id=? AND ip=?",
                       (revision, timestamp, timestamp, target["device_id"], ip.packed))
        db.execute("UPDATE managed_shun_registry SET revision=? WHERE id=1", (revision,))
        result = {"operation_id": request_id, "case_id": case_id, "decision": "ABANDON_MAINTENANCE",
                  "device_id": target["device_id"], "ip": confirm_ip, "retired_intent_id": target["intent_id"],
                  "retired_generation": target["generation"], "retired_now": bool(target["enabled"]),
                  "managed_revision": revision, "closed_at": timestamp, "outcome_unchanged": attempt["state"], "replayed": False}
        db.execute("INSERT INTO managed_incident_closures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (request_id, attempt["id"], target["device_id"], ip.packed, target["intent_id"], target["generation"],
                    inputs["actor_subject"], inputs["reason"], inputs["reviewed_at"], timestamp, request,
                    _dump(frozen["evidence"]), _dump(result)))
        store._insert_event(db, "MANAGED_RESTORATION_ABANDONED", target["device_id"], ip, None,
                            inputs["actor_subject"], "Offline incident abandonment", (), request_id,
                            {**result, "reason": inputs["reason"], "snapshot_digest": frozen["snapshot_digest"]}, timestamp)
        if now is None and datetime.now(UTC) >= reviewed_at + timedelta(minutes=5):
            raise ValueError("Review expired before commit; abandonment rolled back.")
    except Exception:
        db.execute("ROLLBACK TO managed_abandonment")
        db.execute("RELEASE managed_abandonment")
        raise
    db.execute("RELEASE managed_abandonment")
    return result
