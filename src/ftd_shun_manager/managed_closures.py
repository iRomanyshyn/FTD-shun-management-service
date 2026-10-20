"""Retained revocation receipts; never device-success evidence or rearm authority."""

import json
import sqlite3
from contextlib import closing
from functools import lru_cache

from .managed_safety import ManagedStateUnavailable
from .schema import execute_schema

TABLE = "managed_incident_closures"
LIMIT = 10000
SCHEMA = """
CREATE TABLE managed_incident_closures (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES managed_restoration_attempts(id),
    device_id INTEGER NOT NULL REFERENCES devices(id),
    ip BLOB NOT NULL CHECK(length(ip)=4),
    retired_intent_id TEXT NOT NULL,
    retired_generation INTEGER NOT NULL CHECK(retired_generation>=1),
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
    reviewed_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE INDEX idx_managed_closure_pair ON managed_incident_closures(device_id,ip);
CREATE TRIGGER managed_closure_immutable BEFORE UPDATE ON managed_incident_closures
BEGIN SELECT RAISE(ABORT,'incident closure is immutable'); END;
CREATE TRIGGER managed_closure_retained BEFORE DELETE ON managed_incident_closures
BEGIN SELECT RAISE(ABORT,'incident closure is retained'); END;
"""


def initialize(db):
    """Explicit composition only. Never called by runtime or base initialization."""
    execute_schema(db, SCHEMA)


def objects(db):
    return [list(row) for row in db.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE sql IS NOT NULL AND (tbl_name='managed_incident_closures'
            OR name LIKE 'managed_closure_%' OR name LIKE 'idx_managed_closure_%') ORDER BY type,name""")]


@lru_cache(maxsize=1)
def expected():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("BEGIN")
        initialize(db)
        return objects(db)


def present(db):
    actual = objects(db)
    if not actual:
        return False
    required = {"managed_shun_registry", "managed_shun_targets", "managed_shun_requests", "managed_restoration_attempts"}
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if actual != expected() or not required.issubset(names):
        raise ManagedStateUnavailable("Incident closure evidence is incomplete; no reset or new authority is permitted.")
    if db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0] > LIMIT:
        raise ManagedStateUnavailable("Incident closure ledger exceeds this version's capacity.")
    return True


def pair_abandoned(db, device_id, ip):
    from .incident_isolations import pair_isolated

    return pair_isolated(db, device_id, ip) or (present(db) and db.execute(
        "SELECT 1 FROM managed_incident_closures WHERE device_id=? AND ip=? LIMIT 1", (device_id, ip.packed)).fetchone() is not None)


def key_reserved(db, key):
    from .incident_acknowledgements import key_reserved as acknowledgement_key_reserved
    from .incident_isolations import key_reserved as isolation_key_reserved

    return isolation_key_reserved(db, key) or acknowledgement_key_reserved(db, key) or (present(db) and db.execute(
        "SELECT 1 FROM managed_incident_closures WHERE id=?", (key,)).fetchone() is not None)


def decision(db, attempt_id):
    if not present(db):
        return None
    row = db.execute("SELECT id,closed_at,result_json FROM managed_incident_closures WHERE attempt_id=?", (attempt_id,)).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"])
    if (not isinstance(result, dict) or result.get("operation_id") != row["id"]
            or result.get("case_id") != "restoration:" + attempt_id or result.get("closed_at") != row["closed_at"]
            or result.get("decision") != "ABANDON_MAINTENANCE" or result.get("outcome_unchanged") not in {"FAILED", "UNVERIFIED"}):
        raise ManagedStateUnavailable("Incident closure receipt is inconsistent.")
    return {"decision": "ABANDON_MAINTENANCE", "decision_id": row["id"], "closed_at": row["closed_at"],
            "outcome_unchanged": result["outcome_unchanged"], "latch_retained": True}
