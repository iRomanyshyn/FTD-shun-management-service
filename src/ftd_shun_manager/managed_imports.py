"""Atomic prepared-import policy confirmation, not device execution.

Explicit optional initialization only. Confirmed reports outlive preparations;
the existing canonical managed request remains the sole standing authority.
"""

import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from functools import lru_cache
from ipaddress import IPv4Address
from uuid import UUID

from .import_preparations import ImportPreparations, _feed, _member, _stamp
from .managed_intent import canonical_managed_change
from .managed_restoration import present as attempts_present
from .managed_safety import ManagedStateUnavailable, managed_state
from .managed_shuns import (
    MAX_MANAGED_TARGETS,
    ManagedCapacity,
    ManagedConflict,
    ManagedShuns,
    _require_operator,
)
from .schema import execute_schema, schema_connection

MAX_RECEIPTS = 128
MAX_RETAINED_PAIRS = 1000000

_DDL = """
CREATE TABLE confirmed_import_receipts (
    id TEXT PRIMARY KEY REFERENCES managed_shun_requests(id),
    preparation_id TEXT NOT NULL UNIQUE,
    preparation_digest TEXT NOT NULL CHECK(length(preparation_digest)=64),
    actor_subject TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    header_json TEXT NOT NULL CHECK(json_valid(header_json)),
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 100000),
    accepted_count INTEGER NOT NULL CHECK(accepted_count BETWEEN 1 AND 1000),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=64)
);
CREATE TABLE confirmed_import_members (
    import_id TEXT NOT NULL REFERENCES confirmed_import_receipts(id),
    device_id INTEGER NOT NULL CHECK(device_id BETWEEN 1 AND 65535),
    ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    classification TEXT NOT NULL CHECK(classification IN
        ('PROPOSE_ADD','PROPOSE_ADOPT','ALREADY_MANAGED','EXCLUDED_PROTECTED')),
    observed_at TEXT,
    managed_enabled INTEGER NOT NULL CHECK(managed_enabled IN (0,1)),
    previous_intent_id TEXT,
    previous_generation INTEGER,
    previous_authorization_request_id TEXT,
    intent_id TEXT,
    generation INTEGER,
    authorization_request_id TEXT,
    PRIMARY KEY(import_id,device_id,ip)
);
CREATE TRIGGER confirmed_import_receipt_immutable BEFORE UPDATE ON confirmed_import_receipts
BEGIN SELECT RAISE(ABORT,'confirmed import is immutable'); END;
CREATE TRIGGER confirmed_import_receipt_retained BEFORE DELETE ON confirmed_import_receipts
BEGIN SELECT RAISE(ABORT,'confirmed import is retained'); END;
CREATE TRIGGER confirmed_import_member_immutable BEFORE UPDATE ON confirmed_import_members
BEGIN SELECT RAISE(ABORT,'confirmed import member is immutable'); END;
CREATE TRIGGER confirmed_import_member_retained BEFORE DELETE ON confirmed_import_members
BEGIN SELECT RAISE(ABORT,'confirmed import member is retained'); END;
"""


def _objects(db):
    return [tuple(row) for row in db.execute("""SELECT type,name,sql FROM sqlite_master
        WHERE (name GLOB 'confirmed_import_*' OR tbl_name IN ('confirmed_import_receipts','confirmed_import_members'))
            AND sql IS NOT NULL ORDER BY type,name""")]


@lru_cache(maxsize=1)
def _expected():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("BEGIN")
        execute_schema(db, _DDL)
        return _objects(db)


def _present(db):
    objects = _objects(db)
    if not objects:
        return False
    if objects != _expected():
        raise ManagedStateUnavailable("Confirmed-import schema is partial or unsupported; no repair was attempted.")
    if (db.execute("SELECT COUNT(*) FROM confirmed_import_receipts").fetchone()[0] > MAX_RECEIPTS
            or db.execute("SELECT COUNT(*) FROM confirmed_import_members").fetchone()[0] > MAX_RETAINED_PAIRS
            or db.execute("""SELECT 1 FROM confirmed_import_receipts r LEFT JOIN managed_shun_requests a ON a.id=r.id
                WHERE a.id IS NULL OR r.actor_subject!=a.actor_subject
                    OR r.target_count!=(SELECT COUNT(*) FROM confirmed_import_members m WHERE m.import_id=r.id)
                    OR r.accepted_count!=(SELECT COUNT(*) FROM confirmed_import_members m
                        WHERE m.import_id=r.id AND m.classification!='EXCLUDED_PROTECTED') LIMIT 1""").fetchone()
            or db.execute("""SELECT 1 FROM confirmed_import_members m LEFT JOIN confirmed_import_receipts r ON r.id=m.import_id
                WHERE r.id IS NULL LIMIT 1""").fetchone()):
        raise ManagedStateUnavailable("Confirmed-import membership or authority is incomplete or exceeds capacity.")
    return True


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("An exact canonical UUID is required.")


def _retained_member(row):
    return _member(row) | {key: row[key] for key in ("intent_id", "generation", "authorization_request_id")}


def _receipt_hash(request_id, preparation_id, digest, subject, confirmed_at, header, result):
    checksum = hashlib.sha256()
    _feed(checksum, {"version": 1, "scope": "confirmed_managed_import", "operation_id": request_id,
                    "preparation_id": preparation_id, "preparation_digest": digest,
                    "actor_subject": subject, "confirmed_at": confirmed_at, "header": header, "result": result})
    return checksum


_MEMBERS = """SELECT p.device_id,p.ip,p.classification,p.observed_at,p.managed_enabled,
    p.previous_intent_id,p.previous_generation,p.previous_authorization_request_id,
    CASE WHEN p.classification!='EXCLUDED_PROTECTED' THEN t.intent_id END AS intent_id,
    CASE WHEN p.classification!='EXCLUDED_PROTECTED' THEN t.generation END AS generation,
    CASE WHEN p.classification!='EXCLUDED_PROTECTED' THEN t.authorization_request_id END AS authorization_request_id
    FROM import_preparation_targets p LEFT JOIN managed_shun_targets t
        ON t.device_id=p.device_id AND t.ip=p.ip WHERE p.plan_id=?"""


class ManagedImports:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.preparations = ImportPreparations(store, clock=self.clock)
        self.registry = ManagedShuns(store)

    def initialize(self, *, connection=None):
        """Explicit receipt-only migration; never create policy, attempts or drafts."""
        with schema_connection(self.store, connection) as db:
            if managed_state(db) is None or not attempts_present(db):
                raise ManagedStateUnavailable("Existing policy and attempt schemas are required.")
            if not _present(db):
                execute_schema(db, _DDL)

    def confirm(self, request_id, preparation_id, digest, accepted_count, subject, display_name, roles,
                *, maintain_present=False, enabled=False, addition_device_ids=frozenset()):
        """One policy/receipt/audit transaction, no queue, hint, SSH or resume.

        Capability is supplied by the trusted caller, never from a browser body.
        The current 1000-key authority limit is intentionally not expanded here.
        """
        if type(enabled) is not bool or type(maintain_present) is not bool:
            raise ValueError("Explicit boolean capability and recurring consent are required.")
        if not enabled:
            raise PermissionError("Prepared-import confirmation is disabled.")
        if not maintain_present:
            raise ValueError("Explicit recurring maintenance consent is required.")
        _uuid(request_id)
        _uuid(preparation_id)
        if request_id == preparation_id:
            raise ValueError("A preparation reference cannot be the policy operation key.")
        if (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                or type(accepted_count) is not int or not 1 <= accepted_count <= MAX_MANAGED_TARGETS):
            raise ValueError("Confirm 1–1000 accepted pairs and the exact preparation digest; larger scopes are not truncated.")
        if (not isinstance(subject, str) or not subject.strip() or len(subject) > 255
                or not isinstance(display_name, str) or len(display_name) > 255
                or any(ord(c) < 32 for c in subject + display_name)
                or not isinstance(roles, tuple) or any(not isinstance(role, str) for role in roles)
                or len(roles) != len(set(roles)) or any(role not in {"Viewer", "Operator", "Administrator"} for role in roles)):
            raise ValueError("A bounded current authenticated actor is required.")
        _require_operator(subject, roles)
        if (type(addition_device_ids) is not frozenset
                or any(type(device) is not int or not 1 <= device <= 65535 for device in addition_device_ids)):
            raise ValueError("Explicit configured addition-capable device IDs are required.")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not _present(db):
                raise ManagedStateUnavailable("Confirmed-import journal is not initialized.")
            previous = db.execute("SELECT * FROM confirmed_import_receipts WHERE id=?", (request_id,)).fetchone()
            if previous is not None:
                if (previous["actor_subject"] != subject or previous["preparation_id"] != preparation_id
                        or previous["preparation_digest"] != digest or previous["accepted_count"] != accepted_count):
                    raise ManagedConflict("Import key was already used for a different confirmed scope or author.")
                return {**self._root(db, request_id, subject)[1], "replayed": True}
            if db.execute("SELECT 1 FROM confirmed_import_receipts WHERE preparation_id=?", (preparation_id,)).fetchone():
                raise ManagedConflict("Preparation was already confirmed. Recover its original receipt; do not rekey it.")
            # A standalone older managed key must not acquire a new import receipt.
            if db.execute("SELECT 1 FROM managed_shun_requests WHERE id=?", (request_id,)).fetchone():
                raise ManagedConflict("Existing standing keys cannot be reinterpreted as a prepared import.")
            from .import_cancellations import present as cancellations_present

            if not cancellations_present(db):
                raise ManagedStateUnavailable("Initialize import cancellation controls explicitly before new confirmation.")
            plan, header = self.preparations._verified_plan(db, preparation_id, subject, digest)
            issued = _stamp(self.clock())
            if plan["cancelled_at"] is not None or not plan["created_at"] <= issued < plan["expires_at"]:
                raise ManagedConflict("Preparation expired, was cancelled or is ahead of the clock; review again.")
            state = managed_state(db)
            if state is None or header["managed_initialized"] is not True or not attempts_present(db):
                raise ManagedStateUnavailable("Preparation requires already initialized standing policy and attempt evidence.")
            if (state["revision"] != header["managed_revision"]
                    or db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0] != header["protected_revision"]):
                raise ManagedConflict("Managed or protected policy changed; review the whole import again.")
            selected = [device["id"] for device in header["devices"]]
            devices = [dict(row) for row in db.execute("SELECT id,hostname FROM devices WHERE enabled=1 AND id IN ("
                        + ",".join("?" for _ in selected) + ") ORDER BY id", selected)]
            if devices != header["devices"]:
                raise ManagedConflict("Selected device identity/name/enabled state changed; review again.")
            pairs, adoptions = self._current_scope(db, preparation_id, addition_device_ids)
            if len(pairs) != accepted_count:
                raise ManagedConflict("Typed accepted count does not match the whole frozen accepted subset.")
            if (db.execute("SELECT COUNT(*) FROM confirmed_import_receipts").fetchone()[0] >= MAX_RECEIPTS
                    or db.execute("SELECT COUNT(*) FROM confirmed_import_members").fetchone()[0] + plan["target_count"] > MAX_RETAINED_PAIRS):
                raise ManagedCapacity("Retained import journal is full; no policy was saved or evicted.")
            pairs, payload, _ = canonical_managed_change("MAINTAIN", pairs, header["managed_revision"],
                                                       header["protected_revision"], header["label"], header["reason"])
            # Uses the same canonical ledger, revocation reserve, per-pair holds,
            # retirement/generation and audit transaction as existing grants.
            policy = self.registry._apply(db, request_id, "MAINTAIN", pairs, header["managed_revision"],
                                          header["protected_revision"], subject, display_name, roles, payload,
                                          adopted_pairs=frozenset(adoptions))
            counts = header["classification_counts"]
            result = {**policy, "source": "prepared_managed_import", "policy_only": True,
                "device_work_admitted": False, "preparation_id": preparation_id, "preparation_digest": digest,
                "confirmation_actor": {"subject": subject, "display_name": display_name, "roles": list(roles)},
                "accepted_pairs": accepted_count, "proposed_adds": counts["PROPOSE_ADD"],
                "adopted_pairs": counts["PROPOSE_ADOPT"], "already_managed_pairs": counts["ALREADY_MANAGED"],
                "excluded_protected_pairs": counts["EXCLUDED_PROTECTED"], "source_counts": header["source_counts"]}
            checksum = _receipt_hash(request_id, preparation_id, digest, subject, issued, header, result)
            members = db.execute(_MEMBERS + " ORDER BY p.device_id,p.ip", (preparation_id,))
            while rows := members.fetchmany(100):
                for member in rows:
                    _feed(checksum, _retained_member(member))
            db.execute("INSERT INTO confirmed_import_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", (
                request_id, preparation_id, digest, subject, issued, plan["header_json"], plan["target_count"],
                accepted_count, json.dumps(result, sort_keys=True), checksum.hexdigest()))
            db.execute("INSERT INTO confirmed_import_members SELECT ?,m.* FROM (" + _MEMBERS + ") m",
                       (request_id, preparation_id))
            self.store._insert_event(db, "MANAGED_IMPORT_CONFIRMED", None, None, None, subject, display_name, roles,
                                     request_id, {key: result[key] for key in (
                                         "source", "preparation_id", "preparation_digest", "accepted_pairs", "adopted_pairs",
                                         "already_managed_pairs", "proposed_adds", "excluded_protected_pairs", "device_work_admitted")}, issued)
            if not issued <= _stamp(self.clock()) < plan["expires_at"]:
                raise ManagedConflict("Preparation expired or clock moved backwards during confirmation; nothing was saved.")
        print(json.dumps({"event": "managed_import.policy.confirmed", "request_id": request_id,
                          "actor_subject": subject, "accepted_pairs": accepted_count,
                          "adopted_pairs": result["adopted_pairs"], "managed_revision": result["managed_revision"]}), flush=True)
        return result

    @staticmethod
    def _current_scope(db, preparation_id, profiles):
        pairs, adoptions = [], []
        cursor = db.execute("""SELECT p.*,t.enabled AS current_enabled,t.intent_id AS current_intent,
            t.generation AS current_generation,t.authorization_request_id AS current_authorization,
            EXISTS(SELECT 1 FROM protected_ips q WHERE q.ip=p.ip AND q.enabled=1) AS protected,
            EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=p.device_id AND s.ip=p.ip AND s.active=1) AS observed
            FROM import_preparation_targets p LEFT JOIN managed_shun_targets t ON t.device_id=p.device_id AND t.ip=p.ip
            WHERE p.plan_id=? ORDER BY p.device_id,p.ip""", (preparation_id,))
        while rows := cursor.fetchmany(100):
            for row in rows:
                kind = ("EXCLUDED_PROTECTED" if row["protected"] else "ALREADY_MANAGED" if row["current_enabled"]
                        else "PROPOSE_ADOPT" if row["observed"] else "PROPOSE_ADD")
                if (kind != row["classification"] or bool(row["current_enabled"]) != bool(row["managed_enabled"])
                        or row["current_intent"] != row["previous_intent_id"]
                        or row["current_generation"] != row["previous_generation"]
                        or row["current_authorization"] != row["previous_authorization_request_id"]):
                    raise ManagedConflict("Observed membership or maintenance changed; refresh the whole review, not a subset.")
                if kind == "EXCLUDED_PROTECTED":
                    continue
                if len(pairs) >= MAX_MANAGED_TARGETS:
                    raise ManagedCapacity("Accepted scope exceeds the current 1000-pair policy capacity; nothing was split or saved.")
                device, ip = row["device_id"], IPv4Address(row["ip"])
                if device not in profiles:
                    raise ManagedConflict("An explicit addition-capable profile is required for every accepted device.")
                if (db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=?
                        AND state IN ('QUEUED','RUNNING','UNVERIFIED')""", (device, ip.packed)).fetchone()
                        or db.execute("""SELECT 1 FROM managed_restoration_attempts WHERE device_id=? AND ip=?
                            AND state IN ('FAILED','UNVERIFIED')""", (device, ip.packed)).fetchone()):
                    raise ManagedConflict("Pending or uncertain work blocks this accepted scope; no evidence was cleared.")
                pairs.append((device, ip))
                if kind == "PROPOSE_ADOPT":
                    adoptions.append((device, ip))
        return pairs, adoptions

    @staticmethod
    def _root(db, request_id, subject):
        if not _present(db):
            raise ManagedStateUnavailable("Confirmed-import journal is not initialized.")
        row = db.execute("SELECT * FROM confirmed_import_receipts WHERE id=? AND actor_subject=?", (request_id, subject)).fetchone()
        if row is None:
            raise ManagedConflict("Confirmed import is unavailable to this author.")
        result, header = json.loads(row["result_json"]), json.loads(row["header_json"])
        if not isinstance(result, dict) or not isinstance(header, dict) or not isinstance(header.get("line_report"), list):
            raise ManagedStateUnavailable("Confirmed-import report is malformed.")
        original_hash = hashlib.sha256()
        _feed(original_hash, header)
        retained_hash = _receipt_hash(request_id, row["preparation_id"], row["preparation_digest"], subject,
                                      row["confirmed_at"], header, result)
        cursor = db.execute("SELECT * FROM confirmed_import_members WHERE import_id=? ORDER BY device_id,ip", (request_id,))
        while members := cursor.fetchmany(100):
            for member in members:
                _feed(original_hash, _member(member))
                _feed(retained_hash, _retained_member(member))
        if (not hmac.compare_digest(original_hash.hexdigest(), row["preparation_digest"])
                or not hmac.compare_digest(retained_hash.hexdigest(), row["receipt_digest"])):
            raise ManagedStateUnavailable("Confirmed-import scope or receipt integrity is inconsistent.")
        authority = db.execute("SELECT * FROM managed_shun_requests WHERE id=?", (request_id,)).fetchone()
        targets = [(r["device_id"], IPv4Address(r["ip"])) for r in db.execute("""SELECT device_id,ip
            FROM confirmed_import_members WHERE import_id=? AND classification!='EXCLUDED_PROTECTED' ORDER BY device_id,ip""", (request_id,))]
        _, canonical, _ = canonical_managed_change("MAINTAIN", targets, header["managed_revision"], header["protected_revision"],
                                                  header["label"], header["reason"])
        policy = json.loads(authority["result_json"])
        if (authority["payload_json"] != canonical or header["plan_id"] != row["preparation_id"]
                or header["actor_subject"] != subject or header["target_count"] != row["target_count"]
                or result.get("operation_id") != request_id or result.get("preparation_digest") != row["preparation_digest"]
                or result.get("accepted_pairs") != row["accepted_count"]
                or result.get("confirmation_actor") != {"subject": authority["actor_subject"],
                    "display_name": authority["actor_display_name"], "roles": json.loads(authority["actor_roles_json"])}
                or any(result.get(key) != value for key, value in policy.items())):
            raise ManagedStateUnavailable("Confirmed-import receipt does not match its original standing authority.")
        return row, result, header

    def page(self, request_id, subject, *, page=1):
        """Historical confirmation report only, not current execution progress."""
        _uuid(request_id)
        if type(page) is not int or page < 1:
            raise ValueError("Select a positive confirmed-import page.")
        with self.store._connection() as db:
            db.execute("BEGIN")
            row, result, header = self._root(db, request_id, subject)
            reports = header.pop("line_report")
            pages = max(1, (max(row["target_count"], len(reports)) + 99) // 100)
            if page > pages:
                raise ValueError("Select a page within the retained confirmation report.")
            members = db.execute("""SELECT * FROM confirmed_import_members WHERE import_id=?
                ORDER BY device_id,ip LIMIT 100 OFFSET ?""", (request_id, (page - 1) * 100)).fetchall()
            return {"result": result, "header": header, "confirmed_at": row["confirmed_at"],
                "read_only": True, "historical_confirmation": True, "page": page, "pages": pages, "page_size": 100,
                "targets": [_retained_member(member) for member in members],
                "report_rows": reports[(page - 1) * 100:page * 100]}

    def list_for_owner(self, subject):
        """Recover original operation keys even after drafts expired/were pruned."""
        with self.store._connection() as db:
            db.execute("BEGIN")
            if not _present(db):
                return {"initialized": False, "read_only": True, "items": []}
            return {"initialized": True, "read_only": True, "items": [dict(row) for row in db.execute("""SELECT
                id,preparation_id,confirmed_at,target_count,accepted_count FROM confirmed_import_receipts
                WHERE actor_subject=? ORDER BY confirmed_at DESC,id LIMIT ?""", (subject, MAX_RECEIPTS))]}
