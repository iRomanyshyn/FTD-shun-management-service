"""Bounded optional fleet cleanup observations, never authority or migration."""

import json
from collections import Counter
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID

from .managed_intent import canonical_managed_fleet_removal
from .managed_safety import fleet_waits_present, managed_state

STATES = {"QUEUED", "RUNNING", "VERIFIED", "NOOP", "FAILED", "UNVERIFIED", "CANCELLED", "RECONCILED_ABSENT"}
WAIT_STATES = {"WAITING_ADD", "ADMITTED", "EXPIRED", "CANCELLED", "ATTENTION"}


class ManagedFleetState:
    def __init__(self, store, *, worker_enabled=False):
        self.store, self.worker_enabled = store, worker_enabled

    def snapshot_if_present(self):
        with self.store._connection() as db:
            db.execute("BEGIN")
            managed_state(db)  # Unknown optional state is not an empty registry.
            waiting = fleet_waits_present(db)
            initialized = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_fleet_removals'").fetchone() is not None
            result = {"initialized": initialized, "waiting_initialized": waiting, "items": [], "counts": {},
                      "display_limit": 20, "scope_display_limit": 5, "read_only": True, "admission_enabled": False,
                      "scheduler_integration_available": self.worker_enabled}
            if not initialized:
                return result
            if db.execute("SELECT COUNT(*) FROM managed_fleet_removals").fetchone()[0] > 10000:
                raise ValueError("Unsupported fleet history capacity.")
            # Older ready-only ledgers remain observable without adding a wait table.
            wait_join = "LEFT JOIN managed_fleet_waits w ON w.id=r.id" if waiting else ""
            wait_columns = "w.state,w.reason,w.predecessors_json,w.target_count AS reserved_count" if waiting else "NULL AS state,NULL AS reason,NULL AS predecessors_json,NULL AS reserved_count"
            query = f"""WITH outcomes AS (
                SELECT l.request_id,COUNT(*) AS linked,
                    SUM(j.state IN ('QUEUED','RUNNING')) AS active,
                    SUM(j.state IN ('FAILED','UNVERIFIED')) AS attention
                FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                JOIN managed_fleet_removals r ON r.id=l.request_id GROUP BY l.request_id
            ), roots AS (
                SELECT r.*,q.state AS queue_request_state,{wait_columns},
                    CASE WHEN {('w.state' if waiting else 'NULL')}='WAITING_ADD'
                            OR (q.state='ACTIVE' AND o.active>0) THEN 0
                         WHEN {('w.state' if waiting else 'NULL')} IN ('ATTENTION','EXPIRED')
                            OR o.attention>0 OR r.phase!='ADMITTED'
                            OR (COALESCE({('w.state' if waiting else 'NULL')},'ADMITTED')='ADMITTED'
                                AND COALESCE(o.linked,0)!=json_array_length(r.payload_json,'$.targets')) THEN 1
                         ELSE 2 END AS priority
                FROM managed_fleet_removals r {wait_join}
                LEFT JOIN operation_requests q ON q.id=r.id LEFT JOIN outcomes o ON o.request_id=r.id
            ) """
            labels = {0: "active", 1: "attention", 2: "settled"}
            result["counts"] = {labels[row["priority"]]: row["n"] for row in db.execute(
                query + "SELECT priority,COUNT(*) AS n FROM roots GROUP BY priority")}
            rows = db.execute(query + "SELECT * FROM roots ORDER BY priority,requested_at DESC,id LIMIT 20").fetchall()
            result["items"] = [self._item(db, row) for row in rows]
            return result

    @staticmethod
    def _item(db, row):
        payload = json.loads(row["payload_json"])
        ordered = payload.get("mode") == "stop_maintenance_and_remove_ordered"
        scope = {key: value for key, value in payload.items()
                 if key not in {"version", "scope", "action", "mode", "ttl_seconds", "reason"}}
        canonical, _ = canonical_managed_fleet_removal(scope, payload["ttl_seconds"], payload["reason"], ordered_wait=ordered)
        requested, expires = datetime.fromisoformat(row["requested_at"]), datetime.fromisoformat(row["expires_at"])
        if (canonical != row["payload_json"] or row["phase"] != "ADMITTED"
                or str(UUID(row["id"])) != row["id"] or not row["actor_subject"].strip()
                or requested.utcoffset() != timedelta(0) or expires.utcoffset() != timedelta(0)
                or expires - requested != timedelta(seconds=payload["ttl_seconds"])):
            raise ValueError("Invalid retained fleet evidence.")
        targets = {target["device_id"] for target in scope["targets"]}
        ip = IPv4Address(scope["ip"])
        state = row["state"] or "ADMITTED"
        if state not in WAIT_STATES or (row["state"] is not None and (not ordered or row["reserved_count"] != len(targets))):
            raise ValueError("Invalid fleet barrier state.")
        jobs = db.execute("""SELECT j.* FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
            WHERE l.request_id=? LIMIT 1001""", (row["id"],)).fetchall()
        seen, outcomes = set(), Counter()
        for job in jobs:
            if (job["device_id"] not in targets or job["device_id"] in seen or job["ip"] != ip.packed
                    or job["action"] != "REMOVE" or job["state"] not in STATES):
                raise ValueError("Linked REMOVE scope is inconsistent.")
            seen.add(job["device_id"])
            outcomes[job["state"]] += 1
        if (state != "ADMITTED" and jobs) or (jobs and row["queue_request_state"] not in {"ACTIVE", "CANCELLED", "EXPIRED"}):
            raise ValueError("Fleet barrier and queue evidence disagree.")
        predecessor_counts, predecessor_total = Counter(), 0
        if row["state"] is not None:
            evidence, captured = json.loads(row["predecessors_json"]), set()
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= len(targets):
                raise ValueError("Invalid predecessor evidence.")
            prior_jobs = {job["id"]: job for job in db.execute("""SELECT j.id,j.action,j.device_id,j.ip,j.state
                FROM operation_jobs j WHERE j.id IN (SELECT json_extract(value,'$.job_id') FROM json_each(?))""",
                (row["predecessors_json"],))}
            for entry in evidence:
                if (not isinstance(entry, dict) or set(entry) != {"device_id", "job_id"}
                        or type(entry["device_id"]) is not int or entry["device_id"] not in targets
                        or entry["device_id"] in captured or str(UUID(entry["job_id"])) != entry["job_id"]):
                    raise ValueError("Invalid predecessor scope.")
                captured.add(entry["device_id"])
                job = prior_jobs.get(entry["job_id"])
                if job is None:
                    predecessor_counts["UNAVAILABLE"] += 1
                elif job["action"] != "ADD" or job["device_id"] != entry["device_id"] or job["ip"] != ip.packed or job["state"] not in STATES:
                    raise ValueError("Invalid captured ADD evidence.")
                else:
                    predecessor_counts[job["state"]] += 1
            predecessor_total = len(evidence)
        unknown = len(targets) - len(jobs) if state == "ADMITTED" else 0
        settled = sum(n for key, n in outcomes.items() if key not in {"RUNNING", "QUEUED"})
        verified = state == "ADMITTED" and outcomes["VERIFIED"] == len(targets)
        attention = state in {"EXPIRED", "ATTENTION"} or bool(
            unknown or outcomes["FAILED"] or outcomes["UNVERIFIED"] or predecessor_counts["UNAVAILABLE"])
        active = state == "WAITING_ADD" or (row["queue_request_state"] == "ACTIVE" and bool(outcomes["QUEUED"] or outcomes["RUNNING"]))
        return {"id": row["id"], "ip": str(ip), "state": state, "reason": row["reason"],
                "actor_subject": row["actor_subject"], "actor_display_name": row["actor_display_name"],
                "requested_at": row["requested_at"], "expires_at": row["expires_at"],
                "target_count": len(targets), "scope_sample": scope["targets"][:5],
                "queue_request_state": row["queue_request_state"], "outcomes": dict(outcomes),
                "unknown_targets": unknown, "settled_targets": settled, "predecessor_counts": dict(predecessor_counts),
                "predecessor_total": predecessor_total, "verified": verified, "attention": attention, "active": active}
