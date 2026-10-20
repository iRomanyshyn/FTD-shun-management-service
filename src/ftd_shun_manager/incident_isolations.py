"""Reviewed offline pair exclusion; original failures and device outcomes remain."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from ipaddress import IPv4Address
from uuid import UUID, uuid4

from . import incident_acknowledgements as ack
from .maintenance import _actor
from .managed_maintenance import _hash, _time
from .operation_queue import stamp
from .schema import execute_schema

LIMIT = 10000
SCHEMA = """
CREATE TABLE incident_isolations (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE,
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 1000),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TABLE incident_isolation_targets (
    isolation_id TEXT NOT NULL REFERENCES incident_isolations(id),
    device_id INTEGER NOT NULL CHECK(device_id BETWEEN 1 AND 65535),
    ip BLOB NOT NULL CHECK(length(ip)=4),
    PRIMARY KEY(isolation_id,device_id,ip)
);
CREATE INDEX idx_incident_isolation_pair ON incident_isolation_targets(device_id,ip);
CREATE TRIGGER incident_isolation_immutable BEFORE UPDATE ON incident_isolations
BEGIN SELECT RAISE(ABORT,'incident isolation is immutable'); END;
CREATE TRIGGER incident_isolation_retained BEFORE DELETE ON incident_isolations
BEGIN SELECT RAISE(ABORT,'incident isolation is retained'); END;
CREATE TRIGGER incident_isolation_target_immutable BEFORE UPDATE ON incident_isolation_targets
BEGIN SELECT RAISE(ABORT,'incident isolation target is immutable'); END;
CREATE TRIGGER incident_isolation_target_retained BEFORE DELETE ON incident_isolation_targets
BEGIN SELECT RAISE(ABORT,'incident isolation target is retained'); END;
"""


def _objects(db):
    return [list(row) for row in db.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE sql IS NOT NULL AND (tbl_name IN ('incident_isolations','incident_isolation_targets')
            OR name LIKE 'incident_isolation_%' OR name LIKE 'idx_incident_isolation_%') ORDER BY type,name""")]


@lru_cache(maxsize=1)
def _expected():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("BEGIN")
        execute_schema(db, SCHEMA)
        return _objects(db)


def present(db):
    objects = _objects(db)
    if not objects:
        return False
    if objects != _expected() or not ack.present(db):
        raise ValueError("Incident isolation schema is incomplete; no empty scope was inferred.")
    if (db.execute("SELECT COUNT(*) FROM incident_isolations").fetchone()[0] > LIMIT
            or db.execute("SELECT COUNT(*) FROM incident_isolation_targets").fetchone()[0] > LIMIT
            or db.execute("""SELECT 1 FROM incident_isolations r WHERE target_count!=(
                SELECT COUNT(*) FROM incident_isolation_targets t WHERE t.isolation_id=r.id) LIMIT 1""").fetchone()
            or db.execute("""SELECT 1 FROM incident_isolation_targets t LEFT JOIN incident_isolations r
                ON r.id=t.isolation_id WHERE r.id IS NULL LIMIT 1""").fetchone()):
        raise ValueError("Incident isolation latches are incomplete or exceed capacity.")
    return True


def key_reserved(db, key):
    return present(db) and db.execute("SELECT 1 FROM incident_isolations WHERE id=?", (key,)).fetchone() is not None


def retained_job_ids(db):
    if not present(db):
        return set()
    ids = set()
    try:
        for row in db.execute("SELECT target_count,evidence_json FROM incident_isolations"):
            jobs = json.loads(row["evidence_json"])["jobs"]
            if not isinstance(jobs, list) or len(jobs) > row["target_count"]:
                raise ValueError
            original = [item["id"] for item in jobs]
            if len(set(original)) != len(original) or any(str(UUID(key)) != key for key in original):
                raise ValueError
            ids.update(original)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("Retained isolation job evidence is inconsistent; queue pruning refused.") from error
    return ids


def pair_isolated(db, device, ip, *, fleet=False):
    return present(db) and db.execute("""SELECT 1 FROM incident_isolation_targets
        WHERE ip=? AND (? OR device_id=?) LIMIT 1""", (ip.packed, fleet, device)).fetchone() is not None


def require_manual_scope(db, targets, *, fleet=False):
    if any(pair_isolated(db, device, ip, fleet=fleet) for device, ip in targets):
        from .operation_queue import QueueConflict

        raise QueueConflict("Incident scope is isolated; no new manual device work is permitted.")


def decision(db, case_id):
    if not present(db):
        return None
    row = db.execute("SELECT id,result_json FROM incident_isolations WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["result_json"])
        if (result["request_id"] != row["id"] or result["case_id"] != case_id
                or result["decision"] != "ISOLATE_INCIDENT" or result["replayed"] is not False):
            raise ValueError
        return {key: result[key] for key in ("request_id", "decision", "isolated_at", "target_count", "outcome_unchanged")}
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("Incident isolation receipt is inconsistent.") from error


def review_migration(db, *, reviewed_at=None, now=None):
    _, issued = ack._review_time(reviewed_at, now)
    _, blockers, digest = ack._snapshot(db)
    if not ack.present(db) or present(db):
        raise ValueError("An existing acknowledgment ledger and absent isolation schema are required.")
    return {"action": "enable-isolation", "ready": not blockers, "blockers": blockers,
            "reviewed_at": stamp(issued), "expires_at": stamp(issued + timedelta(minutes=5)),
            "confirmation_digest": _hash(["enable-incident-isolation-v1", stamp(issued), digest])}


def enable(db, store, actor, reviewed_at, digest, *, now=None):
    subject = _actor(actor)
    current, _ = ack._review_time(reviewed_at, now)
    ack._confirm(review_migration(db, reviewed_at=reviewed_at, now=current), digest)
    db.execute("SAVEPOINT incident_isolation")
    try:
        execute_schema(db, SCHEMA)
        present(db)
        result = {"action": "enable-isolation", "isolations": 0, "controls_unchanged": True}
        store._insert_event(db, "INCIDENT_ISOLATIONS_INITIALIZED", None, None, None, subject,
                            "Offline incident maintenance", (), str(uuid4()), result, stamp(current))
        ack._check_commit_expiry(reviewed_at, now)
    except Exception:
        db.execute("ROLLBACK TO incident_isolation")
        db.execute("RELEASE incident_isolation")
        raise
    db.execute("RELEASE incident_isolation")
    return result


def _target_policy(db, evidence):
    from .managed_safety import managed_state

    initialized = managed_state(db) is not None
    policies = []
    for target in evidence["targets"]:
        device, ip = target["current"]["device_id"], IPv4Address(evidence["ip"])
        row = (db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (device, ip.packed)).fetchone()
               if initialized else None)
        policy = dict(row) if row else None
        if policy:
            policy["ip"] = str(ip)
        policies.append({"device_id": device, "ip": str(ip), "policy": policy})
    return policies


def _jobs(db, evidence):
    ids = {evidence["case"]["related_job"].get("job_id")}
    ids.update(target.get("predecessor", {}).get("job_id") for target in evidence["targets"])
    jobs = []
    for key in sorted(ids - {None}):
        row = db.execute("SELECT id,device_id,ip,action,state,requested_at,started_at,completed_at FROM operation_jobs WHERE id=?", (key,)).fetchone()
        value = dict(row) if row else None
        if value:
            value["ip"] = str(IPv4Address(value["ip"]))
        links = [list(row) for row in db.execute("SELECT request_id,job_id FROM operation_links WHERE job_id=? ORDER BY request_id", (key,))]
        jobs.append({"id": key, "job": value, "links": links})
    return jobs


def prepare(db, request_id, case_id, actor, reason, *, reviewed_at=None, now=None):
    current, issued = ack._review_time(reviewed_at, now)
    inputs = ack._inputs(request_id, case_id, actor, reason, issued)
    _, blockers, digest = ack._snapshot(db)
    if not present(db):
        raise ValueError("Explicit isolation migration is required.")
    evidence = ack._evidence(db, case_id)
    acknowledgment = ack.decision(db, case_id)
    if acknowledgment is None:
        blockers.append("The original incident must first have an administrative acknowledgment.")
    evidence.update(policies=_target_policy(db, evidence), jobs=_jobs(db, evidence), acknowledgment=acknowledgment)
    if ack._reserved(db, request_id):
        blockers.append("Request key is reserved; use the original receipt.")
    if decision(db, case_id):
        blockers.append("Incident already isolated; use its original receipt.")
    if (db.execute("SELECT COUNT(*) FROM incident_isolations").fetchone()[0] >= LIMIT
            or db.execute("SELECT COUNT(*) FROM incident_isolation_targets").fetchone()[0] + evidence["target_count"] > LIMIT):
        blockers.append("Retained isolation capacity is full; no scope was reduced.")
    if any(entry["policy"] and current < datetime.fromisoformat(entry["policy"]["updated_at"]) for entry in evidence["policies"]):
        blockers.append("Policy time is in the future; review clock/state before retirement.")
    return {**inputs, "action": "ISOLATE_INCIDENT", "ready": not blockers, "blockers": blockers,
            "expires_at": stamp(issued + timedelta(minutes=5)), "evidence": evidence,
            "confirmation_digest": _hash(["isolate-incident-v1", inputs, digest, evidence]),
            "warning": "Retires current policy and permanently blocks new manual work in the entire scope. Original outcomes remain. No release/rearm is available."}


def apply(db, store, request_id, case_id, actor, reason, reviewed_at, digest, confirm_ip, confirm_target_count, *, now=None):
    if not db.in_transaction:
        raise ValueError("Isolation requires a caller-owned offline transaction.")
    inputs = ack._inputs(request_id, case_id, actor, reason, reviewed_at)
    ip = IPv4Address(confirm_ip)
    if (str(ip) != confirm_ip or type(confirm_target_count) is not int or not 1 <= confirm_target_count <= 1000
            or not isinstance(digest, str) or not digest.isascii()):
        raise ValueError("Type the reviewed canonical IPv4, entire target count and exact digest.")
    if not present(db):
        raise ValueError("Explicit isolation migration is required.")
    request = {**inputs, "confirmation_digest": digest, "confirm_ip": confirm_ip, "confirm_target_count": confirm_target_count}
    old = db.execute("SELECT case_id,request_json,result_json FROM incident_isolations WHERE id=?", (request_id,)).fetchone()
    if old:
        decision(db, old["case_id"])
        if json.loads(old["request_json"]) != request:
            raise ValueError("Isolation key already used for different reviewed inputs.")
        return {**json.loads(old["result_json"]), "replayed": True}
    current = _time(now or datetime.now(UTC))
    frozen = prepare(db, request_id, case_id, actor, reason, reviewed_at=reviewed_at, now=current)
    ack._confirm(frozen, digest)
    evidence = frozen["evidence"]
    if evidence["ip"] != confirm_ip or evidence["target_count"] != confirm_target_count:
        raise ValueError("Typed IPv4/count does not match the entire reviewed isolation scope.")
    db.execute("SAVEPOINT incident_isolation")
    try:
        retiring = [item for item in evidence["policies"] if item["policy"] and item["policy"]["enabled"]]
        revision = None
        if retiring:
            revision = db.execute("SELECT revision FROM managed_shun_registry WHERE id=1").fetchone()[0] + 1
            for item in retiring:
                db.execute("UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=? WHERE device_id=? AND ip=?",
                           (revision, stamp(current), stamp(current), item["device_id"], ip.packed))
            db.execute("UPDATE managed_shun_registry SET revision=? WHERE id=1", (revision,))
        result = {"request_id": request_id, "case_id": case_id, "decision": "ISOLATE_INCIDENT", "ip": confirm_ip,
                  "target_count": confirm_target_count, "isolated_at": stamp(current), "retired_targets": len(retiring),
                  "managed_revision": revision, "outcome_unchanged": evidence["case"]["outcome"], "replayed": False}
        def dump(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO incident_isolations VALUES (?,?,?,?,?,?)",
                   (request_id, case_id, confirm_target_count, dump(request), dump(evidence), dump(result)))
        db.executemany("INSERT INTO incident_isolation_targets VALUES (?,?,?)",
                       [(request_id, item["device_id"], ip.packed) for item in evidence["policies"]])
        store._insert_event(db, "INCIDENT_ISOLATED", None, ip, None, inputs["actor_subject"], "Offline incident isolation", (),
                            request_id, {**result, "reason": inputs["reason"], "review_digest": digest}, stamp(current))
        ack._check_commit_expiry(reviewed_at, now)
    except Exception:
        db.execute("ROLLBACK TO incident_isolation")
        db.execute("RELEASE incident_isolation")
        raise
    db.execute("RELEASE incident_isolation")
    return result


def validated(db, *, now=None):
    """All retained receipts must agree with current latches, jobs and retired policy."""
    if not db.in_transaction or not present(db):
        raise ValueError("Explicit isolation ledger is required for isolated-policy resume.")
    from .managed_attention import attention_case

    isolated = []
    try:
        for row in db.execute("SELECT * FROM incident_isolations ORDER BY id"):
            result = json.loads(row["result_json"])
            evidence = json.loads(row["evidence_json"])
            request = json.loads(row["request_json"])
            decision(db, row["case_id"])
            issued = _time(datetime.fromisoformat(request["reviewed_at"]))
            closed = _time(datetime.fromisoformat(result["isolated_at"]))
            inputs = ack._inputs(row["id"], row["case_id"], request["actor_subject"].removeprefix("maintenance:"),
                                 request["reason"], issued)
            digest = request["confirmation_digest"]
            if (not issued <= closed <= _time(now or datetime.now(UTC)) or closed - issued >= timedelta(minutes=5)
                    or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
                    or request != {**inputs, "confirmation_digest": digest, "confirm_ip": result["ip"], "confirm_target_count": row["target_count"]}
                    or evidence["case"]["case_id"] != row["case_id"]
                    or result["ip"] != evidence["ip"] or evidence["target_count"] != row["target_count"]
                    or result["outcome_unchanged"] != evidence["case"]["outcome"]):
                raise ValueError
            if (ack.decision(db, row["case_id"]) != evidence["acknowledgment"]
                    or result["ip"] != request["confirm_ip"] or result["target_count"] != row["target_count"]
                    or request["confirm_target_count"] != row["target_count"]):
                raise ValueError
            expected_pairs = sorted((item["device_id"], IPv4Address(item["ip"]).packed) for item in evidence["policies"])
            original_pairs = sorted((item["current"]["device_id"], IPv4Address(evidence["ip"]).packed) for item in evidence["targets"])
            actual_pairs = [tuple(item) for item in db.execute("SELECT device_id,ip FROM incident_isolation_targets WHERE isolation_id=? ORDER BY device_id,ip", (row["id"],))]
            if len(expected_pairs) != row["target_count"] or expected_pairs != actual_pairs or expected_pairs != original_pairs:
                raise ValueError
            retiring = sum(bool(item["policy"] and item["policy"]["enabled"]) for item in evidence["policies"])
            if (type(result["retired_targets"]) is not int or result["retired_targets"] != retiring
                    or (retiring and (type(result["managed_revision"]) is not int or result["managed_revision"] < 1))
                    or (not retiring and result["managed_revision"] is not None)):
                raise ValueError
            # Policy must still equal the exact post-isolation retired state, including originally absent policy.
            for item in evidence["policies"]:
                current = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?",
                                     (item["device_id"], IPv4Address(item["ip"]).packed)).fetchone()
                current = dict(current) if current else None
                if current:
                    current["ip"] = item["ip"]
                expected = item["policy"]
                if expected and expected["enabled"]:
                    expected = {**expected, "enabled": 0, "revision": result["managed_revision"],
                                "updated_at": result["isolated_at"], "retired_at": result["isolated_at"]}
                if current != expected:
                    raise ValueError
            # Scope and every captured predecessor must remain original. Ordinary REMOVE may reconcile absent.
            for item in evidence["jobs"]:
                current = _jobs(db, {"case": {"related_job": {"job_id": item["id"]}}, "targets": []})[0]
                old_job, new_job = item["job"], current["job"]
                if old_job and new_job and old_job["action"] == "REMOVE" and old_job["state"] == "UNVERIFIED" and new_job["state"] == "RECONCILED_ABSENT":
                    current = {**current, "job": {**new_job, "state": old_job["state"], "completed_at": old_job["completed_at"]}}
                if current != item:
                    raise ValueError
            if row["case_id"].startswith("operation:"):
                key = row["case_id"].split(":")[1]
                if (evidence["case"]["record_id"] != key or len(evidence["jobs"]) != 1
                        or evidence["jobs"][0]["id"] != key or not evidence["jobs"][0]["job"]):
                    raise ValueError
                original_job = evidence["jobs"][0]["job"]
                if (original_job["state"] != "UNVERIFIED" or original_job["action"] not in {"ADD", "REMOVE"}
                        or expected_pairs != [(original_job["device_id"], IPv4Address(original_job["ip"]).packed)]):
                    raise ValueError
            else:
                first = attention_case(db, row["case_id"])
                if first["target_count"] != row["target_count"] or first["reviewed_scope"] != evidence["reviewed_scope"]:
                    raise ValueError
                original = [target["reviewed"] for target in evidence["targets"]]
                targets = list(first["targets"])
                for page in range(2, first["total_pages"] + 1):
                    targets.extend(attention_case(db, row["case_id"], page=page, snapshot_digest=first["snapshot_digest"])["targets"])
                if [target["reviewed"] for target in targets] != original:
                    raise ValueError
                old_refs = [target.get("predecessor", {}).get("job_id") for target in evidence["targets"]]
                if [target.get("predecessor", {}).get("job_id") for target in targets] != old_refs:
                    raise ValueError
                for key in ("kind", "record_id", "occurred_at", "action", "outcome", "intent_id", "generation", "authorization_request_id", "case_id"):
                    if first["case"][key] != evidence["case"][key]:
                        raise ValueError
                refs = {first["case"]["related_job"].get("job_id")}
                refs.update(target.get("predecessor", {}).get("job_id") for target in targets)
                if sorted(refs - {None}) != [item["id"] for item in evidence["jobs"]]:
                    raise ValueError
            isolated.append({"case_id": row["case_id"], "decision_id": row["id"], "target_count": row["target_count"],
                             "job_ids": [item["id"] for item in evidence["jobs"]], "outcome": result["outcome_unchanged"]})
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("Incident isolation evidence is inconsistent; resume refused.") from error
    return isolated
