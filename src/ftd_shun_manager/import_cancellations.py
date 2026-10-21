"""Revoke an import's uncompleted application; never undo device state.

Optional explicit schema. In-flight settlement participates in the existing
queue transaction, not a new worker, retry mechanism or authority registry.
"""

import hashlib
import hmac
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from ipaddress import IPv4Address

from .import_preparations import _stamp
from .managed_imports import ManagedImports, _uuid
from .managed_imports import _present as imports_present
from .managed_restoration import present as attempts_present
from .managed_restoration import validate_binding
from .managed_safety import ManagedStateUnavailable, managed_state
from .managed_shuns import ManagedConflict, _require_operator
from .operation_queue import OperationQueue
from .schema import execute_schema, schema_connection

_DDL = """
CREATE TABLE import_cancellation_decisions (
    import_id TEXT PRIMARY KEY REFERENCES confirmed_import_receipts(id),
    actor_subject TEXT NOT NULL, actor_display_name TEXT NOT NULL,
    actor_roles_json TEXT NOT NULL CHECK(json_valid(actor_roles_json)),
    requested_at TEXT NOT NULL, reviewed_at TEXT NOT NULL,
    review_digest TEXT NOT NULL CHECK(length(review_digest)=64),
    accepted_count INTEGER NOT NULL CHECK(accepted_count BETWEEN 1 AND 1000),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TABLE import_cancellation_targets (
    import_id TEXT NOT NULL REFERENCES import_cancellation_decisions(import_id),
    device_id INTEGER NOT NULL, ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    intent_id TEXT NOT NULL, generation INTEGER NOT NULL,
    authorization_request_id TEXT NOT NULL,
    job_id TEXT UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('WAITING_OUTCOME','RETAINED_ADOPTED','RETAINED_EXISTING',
        'RETAINED_APPLIED','ALREADY_STOPPED','SUPERSEDED','STOPPED_UNSENT','STOPPED_FAILED','STOPPED_UNVERIFIED')),
    attention INTEGER NOT NULL CHECK(attention IN (0,1)), updated_at TEXT NOT NULL,
    CHECK(state!='WAITING_OUTCOME' OR job_id IS NOT NULL),
    PRIMARY KEY(import_id,device_id,ip)
);
CREATE INDEX import_cancellation_pending ON import_cancellation_targets
    (device_id,ip,intent_id,generation,authorization_request_id) WHERE state='WAITING_OUTCOME';
CREATE TRIGGER import_cancellation_decision_immutable BEFORE UPDATE ON import_cancellation_decisions
BEGIN SELECT RAISE(ABORT,'import cancellation is immutable'); END;
CREATE TRIGGER import_cancellation_decision_retained BEFORE DELETE ON import_cancellation_decisions
BEGIN SELECT RAISE(ABORT,'import cancellation is retained'); END;
CREATE TRIGGER import_cancellation_identity_immutable BEFORE UPDATE OF
    import_id,device_id,ip,intent_id,generation,authorization_request_id,job_id ON import_cancellation_targets
BEGIN SELECT RAISE(ABORT,'cancellation scope is immutable'); END;
CREATE TRIGGER import_cancellation_target_monotonic BEFORE UPDATE ON import_cancellation_targets
WHEN OLD.state!='WAITING_OUTCOME' OR NEW.state='WAITING_OUTCOME'
BEGIN SELECT RAISE(ABORT,'cancellation settlement is final'); END;
CREATE TRIGGER import_cancellation_target_retained BEFORE DELETE ON import_cancellation_targets
BEGIN SELECT RAISE(ABORT,'cancellation scope is retained'); END;
"""


def _objects(db):
    return [tuple(row) for row in db.execute("""SELECT type,name,sql FROM sqlite_master
        WHERE (name GLOB 'import_cancellation_*' OR tbl_name IN
            ('import_cancellation_decisions','import_cancellation_targets'))
            AND sql IS NOT NULL ORDER BY type,name""")]


@lru_cache(maxsize=1)
def _expected():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("BEGIN")
        execute_schema(db, _DDL)
        return _objects(db)


def present(db):
    objects = _objects(db)
    if not objects:
        return False
    if objects != _expected():
        raise ManagedStateUnavailable("Import cancellation schema is partial or unsupported; no repair was attempted.")
    return True


def _same(target, member):
    return target is not None and all(target[key] == member[key] for key in (
        "intent_id", "generation", "authorization_request_id"))


def _pending(db):
    """Validate every retained pending predecessor before allowing pruning."""
    if not present(db):
        return []
    rows = db.execute("SELECT * FROM import_cancellation_targets WHERE state='WAITING_OUTCOME'").fetchall()
    if len(rows) > 1000 or (rows and not attempts_present(db)):
        raise ManagedStateUnavailable("Cancellation predecessors exceed capacity or lack attempt evidence.")
    for row in rows:
        attempt = db.execute("SELECT * FROM managed_restoration_attempts WHERE job_id=?", (row["job_id"],)).fetchone()
        job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (row["job_id"],)).fetchone()
        member = db.execute("""SELECT * FROM confirmed_import_members
            WHERE import_id=? AND device_id=? AND ip=?""", (row["import_id"], row["device_id"], row["ip"])).fetchone()
        if (attempt is None or job is None or member is None or member["classification"] != "PROPOSE_ADD"
                or not _same(attempt, row) or not _same(member, row)
                or attempt["device_id"] != row["device_id"] or attempt["ip"] != row["ip"]
                or not db.execute("SELECT 1 FROM import_cancellation_decisions WHERE import_id=?", (row["import_id"],)).fetchone()):
            raise ManagedStateUnavailable("Cancellation predecessor or original scope is missing/inconsistent.")
        validate_binding(db, attempt, job)
    return rows


def held(db, attempt):
    if not present(db):
        return False
    return db.execute("""SELECT 1 FROM import_cancellation_targets WHERE device_id=? AND ip=?
        AND intent_id=? AND generation=? AND authorization_request_id=? AND state='WAITING_OUTCOME'""",
        tuple(attempt[key] for key in ("device_id", "ip", "intent_id", "generation", "authorization_request_id"))).fetchone() is not None


def retained_job_ids(db):
    return [row["job_id"] for row in _pending(db)]


def _retire(db, store, row, actor, timestamp, revision):
    changed = db.execute("""UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=?
        WHERE device_id=? AND ip=? AND intent_id=? AND generation=? AND authorization_request_id=? AND enabled=1""",
        (revision, timestamp, timestamp, row["device_id"], row["ip"], row["intent_id"],
         row["generation"], row["authorization_request_id"])).rowcount
    if changed != 1:
        raise ManagedStateUnavailable("Original import generation could not be retired atomically.")
    store._insert_event(db, "MANAGED_SHUN_RETIRED", row["device_id"], IPv4Address(row["ip"]), None,
                        actor["actor_subject"], actor["actor_display_name"], tuple(json.loads(actor["actor_roles_json"])),
                        row["import_id"], {"source": "import_cancellation", "intent_id": row["intent_id"],
                        "generation": row["generation"], "managed_revision": revision}, timestamp)


def settle_result(db, store, attempt, state, timestamp):
    """Called after the original result is recorded, in that same transaction."""
    if state == "RUNNING" or not present(db):
        return
    row = db.execute("SELECT * FROM import_cancellation_targets WHERE job_id=? AND state='WAITING_OUTCOME'",
                     (attempt["job_id"],)).fetchone()
    if row is None:
        return
    if not _same(attempt, row) or attempt["device_id"] != row["device_id"] or attempt["ip"] != row["ip"]:
        raise ManagedStateUnavailable("Settled ADD does not match the captured cancellation scope.")
    target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (row["device_id"], row["ip"])).fetchone()
    if target is None:
        raise ManagedStateUnavailable("Captured cancellation policy is missing.")
    attention = int(state in {"FAILED", "UNVERIFIED"})
    if not _same(target, row):
        outcome = "SUPERSEDED"
    elif not target["enabled"]:
        outcome = "ALREADY_STOPPED"
    elif state in {"VERIFIED", "NOOP"}:
        outcome = "RETAINED_APPLIED"
    else:
        outcome = {"FAILED": "STOPPED_FAILED", "UNVERIFIED": "STOPPED_UNVERIFIED",
                   "QUEUED": "STOPPED_UNSENT", "CANCELLED": "STOPPED_UNSENT"}[state]
    actor = db.execute("SELECT * FROM import_cancellation_decisions WHERE import_id=?", (row["import_id"],)).fetchone()
    if actor is None:
        raise ManagedStateUnavailable("Cancellation decision is missing.")
    # Settle first: an exact pre-write deferral can then cancel its QUEUED job
    # through _finish/record_result without recursively settling this member.
    db.execute("""UPDATE import_cancellation_targets SET state=?,attention=?,updated_at=?
        WHERE import_id=? AND device_id=? AND ip=?""", (outcome, attention, timestamp, row["import_id"], row["device_id"], row["ip"]))
    if outcome.startswith("STOPPED_"):
        revision = managed_state(db)["revision"] + 1
        _retire(db, store, row, actor, timestamp, revision)
        db.execute("UPDATE managed_shun_registry SET revision=? WHERE id=1", (revision,))
    store._insert_event(db, "MANAGED_IMPORT_CANCELLATION_SETTLED", row["device_id"], IPv4Address(row["ip"]), None,
                        actor["actor_subject"], actor["actor_display_name"], tuple(json.loads(actor["actor_roles_json"])),
                        row["import_id"], {"state": outcome, "attention": bool(attention), "job_id": row["job_id"]}, timestamp)
    if state == "QUEUED":
        job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (row["job_id"],)).fetchone()
        OperationQueue(store)._finish(db, job, "CANCELLED", "Import cancelled after exact pre-write deferral")


class ImportCancellations:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def initialize(self, *, connection=None):
        """Explicit additive migration only; never initialize prerequisites."""
        with schema_connection(self.store, connection) as db:
            if not imports_present(db) or managed_state(db) is None or not attempts_present(db):
                raise ManagedStateUnavailable("Existing confirmed imports, policy and attempts are required.")
            if not present(db):
                execute_schema(db, _DDL)

    @staticmethod
    def _root(db, import_id, subject, roles):
        _uuid(import_id)
        if (not isinstance(subject, str) or not subject.strip() or len(subject) > 255
                or any(ord(c) < 32 for c in subject) or type(roles) is not tuple
                or any(role not in {"Viewer", "Operator", "Administrator"} for role in roles)
                or len(roles) != len(set(roles))):
            raise ValueError("A bounded authenticated actor is required.")
        _require_operator(subject, roles)
        if not present(db) or not imports_present(db) or not attempts_present(db):
            raise ManagedStateUnavailable("Import cancellation is not initialized.")
        owner = db.execute("SELECT actor_subject FROM confirmed_import_receipts WHERE id=?", (import_id,)).fetchone()
        if owner is None or (owner[0] != subject and "Administrator" not in roles):
            raise PermissionError("Original import owner or Administrator required.")
        root = ManagedImports._root(db, import_id, owner[0])[0]
        decision = db.execute("SELECT accepted_count FROM import_cancellation_decisions WHERE import_id=?", (import_id,)).fetchone()
        if decision:
            count = db.execute("SELECT COUNT(*) FROM import_cancellation_targets WHERE import_id=?", (import_id,)).fetchone()[0]
            invalid = db.execute("""SELECT 1 FROM import_cancellation_targets c LEFT JOIN confirmed_import_members m
                ON m.import_id=c.import_id AND m.device_id=c.device_id AND m.ip=c.ip WHERE c.import_id=?
                AND (m.import_id IS NULL OR m.classification='EXCLUDED_PROTECTED' OR c.intent_id!=m.intent_id
                    OR c.generation!=m.generation OR c.authorization_request_id!=m.authorization_request_id) LIMIT 1""",
                (import_id,)).fetchone()
            if decision[0] != root["accepted_count"] or count != decision[0] or invalid:
                raise ManagedStateUnavailable("Cancellation scope does not match the whole confirmed accepted subset.")
        return root

    @staticmethod
    def _scope(db, import_id):
        members = db.execute("""SELECT * FROM confirmed_import_members
            WHERE import_id=? AND classification!='EXCLUDED_PROTECTED' ORDER BY device_id,ip""", (import_id,)).fetchall()
        items = []
        for member in members:
            target = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?",
                                (member["device_id"], member["ip"])).fetchone()
            if target is None:
                raise ManagedStateUnavailable("Original import policy evidence is missing.")
            attempts = db.execute("""SELECT * FROM managed_restoration_attempts WHERE device_id=? AND ip=?
                AND intent_id=? AND generation=? AND authorization_request_id=? ORDER BY id""",
                tuple(member[key] for key in ("device_id", "ip", "intent_id", "generation", "authorization_request_id"))).fetchall()
            pending = [attempt for attempt in attempts if attempt["state"] in {"QUEUED", "RUNNING"}]
            if len(pending) > 1:
                raise ManagedStateUnavailable("Multiple unfinished ADDs have the same import authority.")
            for attempt in attempts:
                if (attempt["state"] in {"QUEUED", "RUNNING"}) != (attempt["completed_at"] is None):
                    raise ManagedStateUnavailable("ADD outcome is missing or contradicts its completion evidence.")
                if attempt["state"] == "VERIFIED" and (not attempt["occurrence_id"] or not attempt["interface"]):
                    raise ManagedStateUnavailable("Verified ADD evidence lacks its occurrence/interface.")
                job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (attempt["job_id"],)).fetchone()
                if job is not None:
                    validate_binding(db, attempt, job)
                elif attempt["state"] in {"QUEUED", "RUNNING"}:
                    raise ManagedStateUnavailable("Unfinished ADD is missing its job.")
            states = {attempt["state"] for attempt in attempts}
            if member["classification"] == "PROPOSE_ADD" and _same(target, member) and target["enabled"]:
                owned = {attempt["job_id"] for attempt in pending}
                if any(row[0] not in owned for row in db.execute("""SELECT id FROM operation_jobs
                        WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING')""",
                        (member["device_id"], member["ip"]))):
                    raise ManagedConflict("Independent unfinished work changed the import scope; settle it before cancellation.")
            job_id = None
            if not _same(target, member):
                state = "SUPERSEDED"
            elif not target["enabled"]:
                state = "ALREADY_STOPPED"
            elif member["classification"] == "ALREADY_MANAGED":
                state = "RETAINED_EXISTING"
            elif member["classification"] == "PROPOSE_ADOPT":
                state = "RETAINED_ADOPTED"
            elif states.intersection({"VERIFIED", "NOOP"}):
                state = "RETAINED_APPLIED"
            elif pending and pending[0]["state"] == "RUNNING":
                state, job_id = "WAITING_OUTCOME", pending[0]["job_id"]
            else:
                state = "STOPPED_UNVERIFIED" if "UNVERIFIED" in states else "STOPPED_FAILED" if "FAILED" in states else "STOPPED_UNSENT"
                job_id = pending[0]["job_id"] if pending else None
            items.append({"device_id": member["device_id"], "ip": str(IPv4Address(member["ip"])),
                          **{key: member[key] for key in ("intent_id", "generation", "authorization_request_id")},
                          "state": state, "job_id": job_id, "attention": bool(states.intersection({"FAILED", "UNVERIFIED"})),
                          "current_revision": target["revision"],
                          "attempts": [{key: attempt[key] for key in ("id", "job_id", "state", "completed_at", "occurrence_id", "interface")}
                                       for attempt in attempts]})
        return items

    def _review(self, db, root, subject, reviewed_at):
        items = self._scope(db, root["id"])
        payload = {"version": 1, "operation_id": root["id"], "receipt_digest": root["receipt_digest"],
                   "actor_subject": subject, "reviewed_at": reviewed_at,
                   "managed_revision": managed_state(db)["revision"],
                   "protected_revision": db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0],
                   "targets": items}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"operation_id": root["id"], "reviewed_at": reviewed_at, "review_digest": digest,
                "expires_at": _stamp(datetime.fromisoformat(reviewed_at) + timedelta(minutes=5)),
                "accepted_count": root["accepted_count"], "counts": dict(Counter(item["state"] for item in items)),
                "attention_count": sum(item["attention"] for item in items), "can_cancel": True,
                "device_work_admitted": False}, items

    def review(self, import_id, subject, roles):
        with self.store._connection() as db:
            db.execute("BEGIN")
            root = self._root(db, import_id, subject, roles)
            existing = db.execute("SELECT 1 FROM import_cancellation_decisions WHERE import_id=?", (import_id,)).fetchone()
            if existing:
                return {"operation_id": import_id, "can_cancel": False, "already_requested": True}
            return self._review(db, root, subject, _stamp(self.clock()))[0]

    def cancel(self, import_id, reviewed_at, review_digest, accepted_count, subject, display_name, roles):
        if (not isinstance(review_digest, str) or len(review_digest) != 64
                or any(c not in "0123456789abcdef" for c in review_digest)
                or type(accepted_count) is not int or not 1 <= accepted_count <= 1000
                or not isinstance(reviewed_at, str) or len(reviewed_at) > 40
                or not isinstance(display_name, str) or len(display_name) > 255 or any(ord(c) < 32 for c in display_name)):
            raise ValueError("Exact review digest/count and bounded display name are required.")
        reviewed = datetime.fromisoformat(reviewed_at)
        if reviewed.tzinfo != UTC or _stamp(reviewed) != reviewed_at:
            raise ValueError("An exact UTC review timestamp is required.")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            root = self._root(db, import_id, subject, roles)
            previous = db.execute("SELECT * FROM import_cancellation_decisions WHERE import_id=?", (import_id,)).fetchone()
            if previous:
                if (previous["actor_subject"] != subject or previous["reviewed_at"] != reviewed_at
                        or previous["review_digest"] != review_digest or previous["accepted_count"] != accepted_count):
                    raise ManagedConflict("Cancellation already exists; inspect its original receipt/status.")
                return {**json.loads(previous["result_json"]), "replayed": True}
            if not reviewed <= self.clock() < reviewed + timedelta(minutes=5):
                raise ManagedConflict("Cancellation review expired or is ahead of the clock; review again.")
            review, items = self._review(db, root, subject, reviewed_at)
            if accepted_count != root["accepted_count"] or not hmac.compare_digest(review_digest, review["review_digest"]):
                raise ManagedConflict("Import scope, policy or ADD outcomes changed; review the whole cancellation again.")
            timestamp = _stamp(self.clock())
            actor = {"actor_subject": subject, "actor_display_name": display_name, "actor_roles_json": json.dumps(roles)}
            result = {**review, "status": "cancellation_requested", "requested_at": timestamp, "replayed": False,
                      "device_removal_requested": False, "can_cancel": False}
            db.execute("INSERT INTO import_cancellation_decisions VALUES (?,?,?,?,?,?,?,?,?)", (
                import_id, subject, display_name, json.dumps(roles), timestamp, reviewed_at, review_digest, accepted_count,
                json.dumps(result, sort_keys=True)))
            revision = managed_state(db)["revision"] + 1
            changed = False
            for item in items:
                row = {**item, "import_id": import_id, "ip": IPv4Address(item["ip"]).packed}
                db.execute("INSERT INTO import_cancellation_targets VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    import_id, row["device_id"], row["ip"], row["intent_id"], row["generation"],
                    row["authorization_request_id"], row["job_id"], row["state"], int(row["attention"]), timestamp))
                if item["state"].startswith("STOPPED_"):
                    _retire(db, self.store, row, actor, timestamp, revision)
                    changed = True
                    if item["job_id"]:
                        job = db.execute("SELECT * FROM operation_jobs WHERE id=?", (item["job_id"],)).fetchone()
                        OperationQueue(self.store)._finish(db, job, "CANCELLED", "Import cancelled before dispatch")
            if changed:
                db.execute("UPDATE managed_shun_registry SET revision=? WHERE id=1", (revision,))
            self.store._insert_event(db, "MANAGED_IMPORT_CANCELLATION_REQUESTED", None, None, None, subject, display_name,
                                     roles, import_id, {"counts": review["counts"], "attention_count": review["attention_count"],
                                     "device_removal_requested": False}, timestamp)
            if not reviewed <= self.clock() < reviewed + timedelta(minutes=5):
                raise ManagedConflict("Cancellation review expired before commit; review again.")
            return result

    def page(self, import_id, subject, roles, *, page=1):
        if type(page) is not int or not 1 <= page <= 10:
            raise ValueError("Cancellation report pages are 1–10, at most 100 targets each.")
        with self.store._connection() as db:
            db.execute("BEGIN")
            self._root(db, import_id, subject, roles)
            decision = db.execute("SELECT * FROM import_cancellation_decisions WHERE import_id=?", (import_id,)).fetchone()
            if decision is None:
                return {"operation_id": import_id, "requested": False, "read_only": True}
            count = db.execute("SELECT COUNT(*) FROM import_cancellation_targets WHERE import_id=?", (import_id,)).fetchone()[0]
            if count != decision["accepted_count"]:
                raise ManagedStateUnavailable("Cancellation membership is incomplete.")
            if page > (count + 99) // 100:
                raise ValueError("Cancellation report page is out of range.")
            _pending(db)
            counts = dict(db.execute("""SELECT state,COUNT(*) FROM import_cancellation_targets
                WHERE import_id=? GROUP BY state""", (import_id,)).fetchall())
            rows = db.execute("""SELECT * FROM import_cancellation_targets WHERE import_id=?
                ORDER BY device_id,ip LIMIT 100 OFFSET ?""", (import_id, (page - 1) * 100)).fetchall()
            return {"operation_id": import_id, "requested": True, "read_only": True, "page": page,
                    "pages": (count + 99) // 100, "counts": counts, "settled": not counts.get("WAITING_OUTCOME", 0),
                    "attention_count": db.execute("SELECT COALESCE(SUM(attention),0) FROM import_cancellation_targets WHERE import_id=?", (import_id,)).fetchone()[0],
                    "initial_receipt": json.loads(decision["result_json"]),
                    "targets": [{**dict(row), "ip": str(IPv4Address(row["ip"])), "attention": bool(row["attention"])} for row in rows]}
