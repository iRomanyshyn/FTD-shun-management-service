"""Read-only retained uncertainty inspection; no resolution, initialization or RPC."""

import hashlib
import hmac
import json
from ipaddress import IPv4Address

from .managed_intent import canonical_managed_fleet_scope
from .managed_restoration import present as restoration_present
from .managed_safety import fleet_waits_present, managed_state

PAGE_SIZE = 100
KINDS = ("operation", "restoration", "device_cleanup", "fleet_cleanup")


def _cases(initialized):
    ordinary = """SELECT 'operation' AS kind,j.id AS record_id,j.requested_at AS occurred_at,
        j.device_id,j.ip,j.action,j.state AS outcome,j.id AS job_id,
        NULL AS intent_id,NULL AS generation,NULL AS authorization_request_id,NULL AS scope_json
        FROM operation_jobs j WHERE j.state='UNVERIFIED'"""
    if not initialized:
        return ordinary
    ordinary += """ AND NOT EXISTS (SELECT 1 FROM managed_restoration_attempts a
        WHERE a.job_id=j.id AND a.device_id=j.device_id AND a.ip=j.ip AND j.action='ADD'
        AND a.state IN ('FAILED','UNVERIFIED'))"""
    return ordinary + """ UNION ALL
        SELECT 'restoration',a.id,a.requested_at,a.device_id,a.ip,'ADD',a.state,a.job_id,
            a.intent_id,a.generation,a.authorization_request_id,NULL
        FROM managed_restoration_attempts a WHERE a.state IN ('FAILED','UNVERIFIED')
        UNION ALL
        SELECT 'device_cleanup',h.id,h.requested_at,h.device_id,h.ip,'REMOVE',h.state,
            h.predecessor_id,h.intent_id,h.generation,h.retirement_request_id,NULL
        FROM managed_removal_handoffs h WHERE h.state='ATTENTION'
        UNION ALL
        SELECT 'fleet_cleanup',r.id,r.requested_at,NULL,NULL,'REMOVE',w.state,NULL,NULL,NULL,
            r.retirement_request_id,r.payload_json
        FROM managed_fleet_waits w JOIN managed_fleet_removals r ON r.id=w.id
        WHERE w.state='ATTENTION'"""


def _context(db, device, ip, initialized):
    row = db.execute("SELECT hostname,enabled FROM devices WHERE id=?", (device,)).fetchone()
    observed = db.execute("""SELECT COUNT(*) AS n
        FROM shun_state WHERE device_id=? AND ip=? AND active=1""", (device, ip.packed)).fetchone()
    last_seen = db.execute("SELECT MAX(last_seen_at) FROM shun_state WHERE device_id=? AND ip=?",
                           (device, ip.packed)).fetchone()[0]
    target = (db.execute("SELECT enabled,intent_id,generation FROM managed_shun_targets WHERE device_id=? AND ip=?",
                         (device, ip.packed)).fetchone() if initialized else None)
    return {"device_id": device, "hostname": row["hostname"] if row else None,
            "device_enabled": bool(row["enabled"]) if row else None, "ip": str(ip),
            "maintenance": ("enabled" if target["enabled"] else "retired") if target else
                           "not_registered" if initialized else "not_initialized",
            "current_intent_id": target["intent_id"] if target else None,
            "current_generation": target["generation"] if target else None,
            "protected": db.execute("SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1", (ip.packed,)).fetchone() is not None,
            "cached_present": bool(observed["n"]), "cached_active_interface_count": observed["n"],
            "cached_last_seen_at": last_seen, "observation_basis": "cached_not_write_verification"}


def _job_evidence(db, row):
    role = "captured_predecessor_add" if row["kind"] == "device_cleanup" else "original_operation"
    if not row["job_id"]:
        return {"state": "not_applicable", "job_id": None, "role": role}
    job = db.execute("SELECT id,device_id,ip,action,state FROM operation_jobs WHERE id=?", (row["job_id"],)).fetchone()
    if job is None:
        return {"state": "not_retained", "job_id": row["job_id"], "role": role}
    matches = (job["device_id"] == row["device_id"] and job["ip"] == row["ip"]
               and job["action"] == ("ADD" if row["kind"] == "device_cleanup" else row["action"]))
    if row["kind"] == "restoration":
        matches = matches and job["state"] == row["outcome"]
    return {"state": "retained" if matches else "inconsistent", "job_id": row["job_id"], "role": role,
            "action": job["action"],
            "outcome": job["state"], "retained_request_count": db.execute(
                "SELECT COUNT(*) FROM operation_links WHERE job_id=?", (row["job_id"],)).fetchone()[0]}


def _item(db, row, initialized):
    from .managed_closures import decision

    result = {key: row[key] for key in ("kind", "record_id", "occurred_at", "action", "outcome",
                                      "intent_id", "generation", "authorization_request_id")}
    result.update(case_id=row["kind"] + ":" + row["record_id"], resolution_available=False,
                  next_step="Review original authority, retained evidence and a fresh authorized observation. Do not replay or clear outcomes.")
    result["related_job"] = _job_evidence(db, row)
    if row["kind"] != "fleet_cleanup":
        result["target"] = _context(db, row["device_id"], IPv4Address(row["ip"]), initialized)
        result["pair_latch_retained"] = row["kind"] == "restoration"
        if row["kind"] == "restoration":
            result["abandonment"] = decision(db, row["record_id"])
    else:
        # No raw payload/comment/reason escapes, including malformed evidence.
        try:
            payload = json.loads(row["scope_json"])
            keys = ("ip", "managed_initialized", "managed_revision", "protected_revision", "protected", "targets")
            canonical_managed_fleet_scope({key: payload[key] for key in keys})
            ip = IPv4Address(payload["ip"])
            targets = sorted(payload["targets"], key=lambda target: target["device_id"])
            barrier = db.execute("""SELECT w.target_count,r.phase FROM managed_fleet_waits w
                JOIN managed_fleet_removals r ON r.id=w.id WHERE w.id=?""", (row["record_id"],)).fetchone()
            if barrier is None or barrier["target_count"] != len(targets) or barrier["phase"] != "ADMITTED":
                raise ValueError("Inconsistent retained fleet scope.")
            result.update(scope_state="retained", ip=str(ip), target_count=len(targets),
                          targets_truncated=len(targets) > 5,
                          targets=[_context(db, target["device_id"], ip, initialized) for target in targets[:5]])
        except (ValueError, TypeError, KeyError, AttributeError):
            result.update(scope_state="inconsistent", ip=None, target_count=None, targets_truncated=None, targets=[])
    return result


def _snapshot_digest(db, cases, initialized):
    from .managed_closures import present as closures_present
    """Stream retained evidence, bounded in Python memory; never export raw rows."""
    from .managed_maintenance import TABLES

    queries = [("cases", "SELECT * FROM (" + cases + ") ORDER BY occurred_at DESC,kind,record_id"),
               ("executor", "SELECT revision,owner,lease_until,next_eligible_at,mutations_suspended FROM operation_executor ORDER BY id"),
               ("protection", "SELECT * FROM protected_policy ORDER BY id"),
               ("protected_ips", "SELECT * FROM protected_ips ORDER BY ip"),
               ("devices", "SELECT id,hostname,enabled FROM devices ORDER BY id"),
               ("observations", "SELECT * FROM shun_state ORDER BY device_id,ip,interface"),
               ("jobs", "SELECT id,device_id,ip,action,state FROM operation_jobs ORDER BY id"),
               ("links", "SELECT request_id,job_id FROM operation_links ORDER BY request_id,job_id")]
    if initialized:
        queries.extend((table, f"SELECT * FROM {table} ORDER BY rowid") for table in TABLES)
        if closures_present(db):
            queries.append(("closures", "SELECT * FROM managed_incident_closures ORDER BY id"))
    digest = hashlib.sha256()
    for name, query in queries:
        digest.update(json.dumps(name).encode() + b"\n")
        for row in db.execute(query):
            digest.update(json.dumps([{"blob": value.hex()} if isinstance(value, bytes) else value for value in row],
                                     separators=(",", ":")).encode() + b"\n")
    return digest.hexdigest()


def attention_report(db, *, page=1, snapshot_digest=None):
    """A transactionally consistent, non-executable page of retained attention."""
    from .managed_closures import present as closures_present
    from .managed_maintenance import TABLES, _objects, _owned, recognized_schema

    if not db.in_transaction:
        raise ValueError("Attention inspection requires a caller-owned read transaction.")
    if type(page) is not int or not 1 <= page <= 1000000:
        raise ValueError("Attention page must be an integer between 1 and 1000000.")
    if page > 1 and snapshot_digest is None:
        raise ValueError("Subsequent pages require the previous snapshot digest.")
    owned = _owned(_objects(db))
    initialized = bool(owned)
    if initialized:
        try:
            recognized_schema(db)
        except ValueError as error:
            raise ValueError("Exact complete managed schema required for attention inspection; partial state is not empty.") from error
    registry = managed_state(db)
    if initialized:
        for table, limit in TABLES.items():
            if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > limit:
                raise ValueError("Managed state exceeds this version's capacity.")
        if registry is None:
            raise ValueError("Managed registry metadata is missing.")
        restoration_present(db)  # Orphan pending evidence is unavailable, never empty.
        fleet_waits_present(db)
    executor = db.execute("SELECT mutations_suspended,owner,lease_until FROM operation_executor WHERE id=1").fetchone()
    if executor is None or executor["mutations_suspended"] not in (0, 1):
        raise ValueError("Initialized current queue metadata required; no migration is performed.")
    cases = _cases(initialized)
    digest = _snapshot_digest(db, cases, initialized)
    if snapshot_digest is not None and (not isinstance(snapshot_digest, str) or not snapshot_digest.isascii()
                                       or not hmac.compare_digest(snapshot_digest, digest)):
        raise ValueError("Attention snapshot changed; start again at page 1. No automatic rebase.")
    counts = {kind: 0 if initialized or kind == "operation" else None for kind in KINDS}
    for row in db.execute("SELECT kind,COUNT(*) AS n FROM (" + cases + ") GROUP BY kind"):
        counts[row["kind"]] = row["n"]
    total = sum(value or 0 for value in counts.values())
    rows = db.execute("SELECT * FROM (" + cases + ") ORDER BY occurred_at DESC,kind,record_id LIMIT ? OFFSET ?",
                      (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    pending = {row["state"]: row["n"] for row in db.execute(
        "SELECT state,COUNT(*) AS n FROM operation_jobs WHERE state IN ('QUEUED','RUNNING') GROUP BY state")}
    pending_managed = None
    if initialized:
        pending_managed = {}
        for kind, table in (("restoration", "managed_restoration_attempts"),
                            ("device_cleanup", "managed_removal_handoffs"), ("fleet_cleanup", "managed_fleet_waits")):
            pending_managed[kind] = {row["state"]: row["n"] for row in db.execute(
                f"SELECT state,COUNT(*) AS n FROM {table} WHERE state IN ('QUEUED','RUNNING','WAITING_ADD','ADMITTING') GROUP BY state")}
        pending_managed["inconsistent_fleet_admissions"] = db.execute(
            "SELECT COUNT(*) FROM managed_fleet_removals WHERE phase!='ADMITTED'").fetchone()[0]
    return {"read_only": True, "resolution_available": False, "managed_initialized": initialized,
            "offline_abandonment_available": closures_present(db) if initialized else False,
            "abandoned_case_count": (db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0]
                                     if initialized and closures_present(db) else None),
            "mutations_suspended": bool(executor["mutations_suspended"]),
            "restoration_suspended": registry["restoration_suspended"] if registry else None,
            "executor_lease_present": executor["owner"] is not None or executor["lease_until"] is not None,
            "pending_jobs": pending, "pending_managed": pending_managed,
            "page": page, "page_size": PAGE_SIZE, "total_pages": (total + PAGE_SIZE - 1) // PAGE_SIZE,
            "retained_case_count": total, "counts": counts, "snapshot_digest": digest,
            "has_next": page * PAGE_SIZE < total,
            "items": [_item(db, row, initialized) for row in rows],
            "warning": "Read-only retained evidence, not a resolution or current device verification. Missing history is not success; never replay uncertain ADD."}
