"""Durable, owner-bound bulk preparations. Never standing authority or queue work.

Explicit initialization only. Runtime construction/reads never create its schema.
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
from uuid import UUID, uuid4

from .import_preview import parse_blocklist
from .managed_safety import managed_state
from .schema import execute_schema, schema_connection

PAGE_SIZE = 100
MAX_DEVICES = 10
MAX_PAIRS = 100000
MAX_PLANS = 16
MAX_OWNER_PLANS = 4
MAX_HEADER_BYTES = 2 * 1024 * 1024
LIFETIME = timedelta(minutes=10)
_CLASSES = ("PROPOSE_ADD", "PROPOSE_ADOPT", "ALREADY_MANAGED", "EXCLUDED_PROTECTED")

_DDL = """
CREATE TABLE import_preparation_plans (
    id TEXT PRIMARY KEY,
    actor_subject TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    cancelled_at TEXT,
    header_json TEXT NOT NULL,
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 0 AND 100000),
    digest TEXT NOT NULL CHECK(length(digest)=64)
);
CREATE TABLE import_preparation_targets (
    plan_id TEXT NOT NULL REFERENCES import_preparation_plans(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL CHECK(device_id BETWEEN 1 AND 65535),
    ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
    classification TEXT NOT NULL CHECK(classification IN
        ('PROPOSE_ADD','PROPOSE_ADOPT','ALREADY_MANAGED','EXCLUDED_PROTECTED')),
    observed_at TEXT,
    managed_enabled INTEGER NOT NULL CHECK(managed_enabled IN (0,1)),
    previous_intent_id TEXT,
    previous_generation INTEGER,
    previous_authorization_request_id TEXT,
    PRIMARY KEY(plan_id,device_id,ip)
);
CREATE TRIGGER import_preparation_header_immutable BEFORE UPDATE ON import_preparation_plans
WHEN NEW.id IS NOT OLD.id OR NEW.actor_subject IS NOT OLD.actor_subject
    OR NEW.created_at IS NOT OLD.created_at OR NEW.expires_at IS NOT OLD.expires_at
    OR NEW.header_json IS NOT OLD.header_json OR NEW.target_count IS NOT OLD.target_count
    OR NEW.digest IS NOT OLD.digest OR OLD.cancelled_at IS NOT NULL OR NEW.cancelled_at IS NULL
BEGIN SELECT RAISE(ABORT,'only first preparation cancellation is mutable'); END;
CREATE TRIGGER import_preparation_target_immutable BEFORE UPDATE ON import_preparation_targets
BEGIN SELECT RAISE(ABORT,'prepared targets are immutable'); END;
"""


class PreparationUnavailable(ValueError):
    """Missing/partial state, wrong owner, changed evidence or invalid scope."""


class PreparationCapacity(ValueError):
    """Retained preparation bound; never evict another user's review silently."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stamp(value):
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("Preparation time must be timezone-aware UTC.")
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _objects(db):
    return [tuple(row) for row in db.execute("""SELECT type,name,sql FROM sqlite_master
        WHERE name GLOB 'import_preparation_*' AND sql IS NOT NULL ORDER BY type,name""")]


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
        raise PreparationUnavailable("Preparation schema is partial or unsupported; no repair was attempted.")
    return True


def _feed(digest, value):
    raw = _json(value).encode("utf-8")
    digest.update(len(raw).to_bytes(4, "big"))
    digest.update(raw)


def _member(row):
    return {"device_id": row["device_id"], "ip": str(IPv4Address(row["ip"])),
            "classification": row["classification"], "observed_at": row["observed_at"],
            "managed_enabled": bool(row["managed_enabled"]),
            **{key: row[key] for key in ("previous_intent_id", "previous_generation", "previous_authorization_request_id")}}


def _state(row, current):
    return "CANCELLED" if row["cancelled_at"] else "EXPIRED" if row["expires_at"] <= current else "PREPARED"


def _confirmed_operation(db, row):
    # Optional retained receipts are separate from an expiring draft. Never
    # present cancelling a confirmed draft as cancellation of standing policy.
    if db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_*' LIMIT 1").fetchone():
        from .bulk_policy import confirmed_operation

        return confirmed_operation(db, row)
    from .managed_imports import _present as imports_present

    if not imports_present(db):
        return None
    receipt = db.execute("SELECT id,actor_subject FROM confirmed_import_receipts WHERE preparation_id=?", (row["id"],)).fetchone()
    if receipt is None:
        return None
    if receipt["actor_subject"] != row["actor_subject"]:
        raise PreparationUnavailable("Preparation and retained receipt authors are inconsistent.")
    return receipt["id"]


class ImportPreparations:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _managed_state(db):
        """The separate bulk-storage preparation subclass supplies its own reader."""
        return managed_state(db)

    def initialize(self, *, connection=None):
        """Explicit empty schema only; no optional policy/attempt initialization."""
        with schema_connection(self.store, connection) as db:
            if not _present(db):
                execute_schema(db, _DDL)

    def create(self, text, device_ids, subject, display_name, roles, *, label="", reason=""):
        """Freeze proposed local actions, not accepted policy or a fresh Cisco read."""
        if (not isinstance(subject, str) or not subject.strip() or len(subject) > 255
                or not isinstance(display_name, str) or len(display_name) > 255
                or not isinstance(roles, tuple) or any(not isinstance(role, str) for role in roles)
                or len(roles) != len(set(roles))
                or any(role not in {"Viewer", "Operator", "Administrator"} for role in roles)):
            raise ValueError("A bounded authenticated author and captured roles are required.")
        if (not isinstance(device_ids, list) or not 1 <= len(device_ids) <= MAX_DEVICES
                or any(type(device) is not int or not 1 <= device <= 65535 for device in device_ids)
                or len(set(device_ids)) != len(device_ids)):
            raise ValueError("Select 1–10 distinct configured devices.")
        if not isinstance(label, str) or not isinstance(reason, str):
            raise TypeError("Label/reason must be plain text.")
        label, reason = label.strip(), reason.strip()
        if (len(label) > 100 or len(reason) > 500
                or any(ord(c) < 32 and c not in "\t\n" for c in label + reason)
                or any(ord(c) < 32 for c in subject + display_name)):
            raise ValueError("Preparation metadata is too long or contains control characters.")
        if not isinstance(text, str):
            raise TypeError("Pasted input must be text.")
        parsed = parse_blocklist(text)
        ips = sorted((IPv4Address(ip) for ip in parsed["ips"]), key=int)
        if len(ips) * len(device_ids) > MAX_PAIRS:
            raise ValueError("Preparation exceeds 100,000 device/IP pairs.")
        current = self.clock()
        created, expires = _stamp(current), _stamp(current + LIFETIME)
        plan_id = str(uuid4())
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not _present(db):
                raise PreparationUnavailable("Preparation journal is not initialized.")
            if (db.execute("SELECT COUNT(*) FROM import_preparation_plans").fetchone()[0] >= MAX_PLANS
                    or db.execute("SELECT COUNT(*) FROM import_preparation_plans WHERE actor_subject=?",
                                  (subject,)).fetchone()[0] >= MAX_OWNER_PLANS):
                raise PreparationCapacity("Preparation capacity reached; expired drafts require explicit pruning.")
            state = self._managed_state(db)  # Unknown is never an invented unmanaged set.
            marks = ",".join("?" for _ in device_ids)
            devices = db.execute(f"SELECT id,hostname FROM devices WHERE enabled=1 AND id IN ({marks}) ORDER BY id",
                                 device_ids).fetchall()
            if len(devices) != len(device_ids):
                raise PreparationUnavailable("Select enabled configured devices only.")
            protected = {row[0] for row in db.execute("SELECT ip FROM protected_ips WHERE enabled=1")}
            protection = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
            observed, managed = {}, {}
            for offset in range(0, len(ips), 400):
                chunk = ips[offset:offset + 400]
                ip_marks = ",".join("?" for _ in chunk)
                parameters = [*device_ids, *(ip.packed for ip in chunk)]
                observed.update({(r[0], r[1]): r[2] for r in db.execute(f"""SELECT device_id,ip,MAX(last_seen_at)
                    FROM shun_state WHERE active=1 AND device_id IN ({marks}) AND ip IN ({ip_marks}) GROUP BY device_id,ip""", parameters)})
                if state is not None:
                    managed.update({(r["device_id"], r["ip"]): r for r in db.execute(f"""SELECT *
                        FROM managed_shun_targets WHERE device_id IN ({marks}) AND ip IN ({ip_marks})""", parameters)})
            members = []
            for device in devices:
                for ip in ips:
                    key = device["id"], ip.packed
                    old = managed.get(key)
                    maintained = bool(old and old["enabled"])
                    kind = ("EXCLUDED_PROTECTED" if ip.packed in protected else "ALREADY_MANAGED" if maintained
                            else "PROPOSE_ADOPT" if key in observed else "PROPOSE_ADD")
                    members.append({"device_id": device["id"], "ip": str(ip), "classification": kind,
                        "observed_at": observed.get(key), "managed_enabled": maintained,
                        "previous_intent_id": old["intent_id"] if old else None,
                        "previous_generation": old["generation"] if old else None,
                        "previous_authorization_request_id": old["authorization_request_id"] if old else None})
            counts = Counter(member["classification"] for member in members)
            header = {"version": 1, "scope": "managed_import_preparation", "plan_id": plan_id,
                "actor_subject": subject, "actor_display_name": display_name, "actor_roles": sorted(roles),
                "created_at": created, "expires_at": expires, "label": label, "reason": reason,
                "managed_initialized": state is not None, "managed_revision": state["revision"] if state else 0,
                "protected_revision": protection, "devices": [dict(device) for device in devices],
                "target_count": len(members), "address_count": len(ips), "ignored_lines": parsed["ignored_lines"],
                "source_row_count": len(parsed["rows"]), "source_counts": dict(Counter(row["status"] for row in parsed["rows"])),
                "classification_counts": {kind: counts[kind] for kind in _CLASSES},
                "line_report": [{key: row[key] for key in ("line", "ip", "status", "source_lines", "reason")} for row in parsed["rows"]]}
            header_json = _json(header)
            if len(header_json.encode("utf-8")) > MAX_HEADER_BYTES:
                raise PreparationCapacity("Prepared report exceeds its 2 MiB storage bound.")
            digest = hashlib.sha256()
            _feed(digest, header)
            for member in members:
                _feed(digest, member)
            value = digest.hexdigest()
            db.execute("INSERT INTO import_preparation_plans VALUES (?,?,?,?,NULL,?,?,?)",
                       (plan_id, subject, created, expires, header_json, len(members), value))
            db.executemany("INSERT INTO import_preparation_targets VALUES (?,?,?,?,?,?,?,?,?)", (
                (plan_id, member["device_id"], IPv4Address(member["ip"]).packed, member["classification"], member["observed_at"],
                 int(member["managed_enabled"]), member["previous_intent_id"], member["previous_generation"],
                 member["previous_authorization_request_id"]) for member in members))
        return {"plan_id": plan_id, "digest": value, "target_count": len(members), "can_execute": False}

    def _plan(self, db, plan_id, subject):
        try:
            if str(UUID(plan_id)) != plan_id:
                raise ValueError
        except (ValueError, AttributeError, TypeError) as error:
            raise PreparationUnavailable("Preparation not available to this author.") from error
        if not _present(db):
            raise PreparationUnavailable("Preparation journal is not initialized.")
        row = db.execute("SELECT * FROM import_preparation_plans WHERE id=? AND actor_subject=?", (plan_id, subject)).fetchone()
        if row is None:
            raise PreparationUnavailable("Preparation not available to this author.")
        try:
            header = json.loads(row["header_json"])
        except (TypeError, ValueError) as error:
            raise PreparationUnavailable("Preparation header is inconsistent.") from error
        if (not isinstance(header, dict) or type(header.get("version")) is not int or header["version"] != 1
                or header.get("scope") != "managed_import_preparation"):
            raise PreparationUnavailable("Preparation header is inconsistent.")
        if (header.get("plan_id") != row["id"] or header.get("actor_subject") != row["actor_subject"]
                or header.get("created_at") != row["created_at"] or header.get("expires_at") != row["expires_at"]
                or header.get("target_count") != row["target_count"] or not isinstance(header.get("line_report"), list)
                or db.execute("SELECT COUNT(*) FROM import_preparation_targets WHERE plan_id=?", (plan_id,)).fetchone()[0] != row["target_count"]):
            raise PreparationUnavailable("Preparation membership is incomplete.")
        return row, header

    def list_for_owner(self, subject):
        """Recover retained references after restart/lost response; never migrate."""
        current = _stamp(self.clock())
        with self.store._connection() as db:
            db.execute("BEGIN")
            if not _present(db):
                return {"initialized": False, "can_execute": False, "plans": []}
            rows = db.execute("""SELECT id FROM import_preparation_plans WHERE actor_subject=?
                ORDER BY created_at DESC,id LIMIT ?""", (subject, MAX_OWNER_PLANS + 1)).fetchall()
            if len(rows) > MAX_OWNER_PLANS:
                raise PreparationUnavailable("Retained owner scope exceeds this version's supported capacity.")
            plans = []
            for record in rows:
                row, header = self._plan(db, record["id"], subject)
                operation = _confirmed_operation(db, row)
                plans.append({key: header[key] for key in ("plan_id", "created_at", "expires_at", "label", "target_count",
                                                          "address_count", "classification_counts")}
                             | {"state": "CONFIRMED" if operation else _state(row, current),
                                "confirmed_operation_id": operation, "digest": row["digest"], "can_execute": False})
            return {"initialized": True, "can_execute": False, "plans": plans}

    def page(self, plan_id, subject, *, page=1):
        """At most 100 targets/line reports; expiry/cancellation never mutate reads."""
        if type(page) is not int or page < 1:
            raise ValueError("Select a positive preparation page.")
        current = _stamp(self.clock())
        with self.store._connection() as db:
            db.execute("BEGIN")
            row, header = self._plan(db, plan_id, subject)
            operation = _confirmed_operation(db, row)
            reports = header.pop("line_report")
            pages = max(1, (max(row["target_count"], len(reports)) + PAGE_SIZE - 1) // PAGE_SIZE)
            if page > pages:
                raise ValueError("Select a page within the frozen preparation.")
            rows = db.execute("SELECT * FROM import_preparation_targets WHERE plan_id=? ORDER BY device_id,ip LIMIT ? OFFSET ?",
                              (plan_id, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
            return {**header, "digest": row["digest"], "can_execute": False, "execution_started": False,
                "state": "CONFIRMED" if operation else _state(row, current), "confirmed_operation_id": operation,
                "page": page, "pages": pages, "page_size": PAGE_SIZE,
                "targets": [_member(member) for member in rows], "report_rows": reports[(page - 1)*PAGE_SIZE:page*PAGE_SIZE]}

    def verify(self, plan_id, subject, expected_digest):
        """Read-only full integrity check, streamed in 100-row chunks; no permission."""
        if not isinstance(expected_digest, str) or len(expected_digest) != 64 or not expected_digest.isascii():
            raise PreparationUnavailable("Invalid preparation digest.")
        with self.store._connection() as db:
            db.execute("BEGIN")
            self._verified_plan(db, plan_id, subject, expected_digest)
        return {"plan_id": plan_id, "integrity_verified": True, "can_execute": False}

    def propose_bulk_intent(self, plan_id, subject, expected_digest, operation_id):
        """Internal version-2 format read; not a policy grant or retained root.

        The separate v2 preparation API exposes this pure read on compatible
        bulk storage. It cannot translate an expired/cancelled/already confirmed
        preparation or grant standing policy/execution authority.
        """
        from .bulk_intent import canonical_bulk_intent

        current = _stamp(self.clock())
        with self.store._connection() as db:
            db.execute("BEGIN")
            row, header = self._verified_plan(db, plan_id, subject, expected_digest)
            if (row["cancelled_at"] is not None or not row["created_at"] <= current < row["expires_at"]
                    or _confirmed_operation(db, row) is not None):
                raise PreparationUnavailable("Only an unexpired, unconfirmed and uncancelled preparation can supply a new proposal.")

            def members():
                cursor = db.execute("""SELECT device_id,ip,classification FROM import_preparation_targets
                    WHERE plan_id=? ORDER BY device_id,ip""", (plan_id,))
                while chunk := cursor.fetchmany(PAGE_SIZE):
                    for member in chunk:
                        yield member["device_id"], IPv4Address(member["ip"]), member["classification"]

            summary, canonical, digest = canonical_bulk_intent(members(), tuple(device["id"] for device in header["devices"]),
                operation_id, plan_id, expected_digest, header["managed_revision"], header["protected_revision"],
                header["label"], header["reason"])
            if (summary.pair_count != header["target_count"] or summary.address_count != header["address_count"]
                    or summary.as_dict()["classification_counts"] != header["classification_counts"]):
                raise PreparationUnavailable("Classified manifest does not match the complete frozen preparation.")
            if not current <= _stamp(self.clock()) < row["expires_at"]:
                raise PreparationUnavailable("Preparation expired or clock moved backwards during the proposal read.")
        return {"intent_format": 2, "operation_id": operation_id, "preparation_id": plan_id,
                "canonical": canonical, "digest": digest, "manifest": summary.as_dict(),
                "can_execute": False, "policy_saved": False, "device_work_admitted": False}

    def _verified_plan(self, db, plan_id, subject, expected_digest):
        """Internal composition read: caller keeps the same transaction open."""
        if not db.in_transaction:
            raise ValueError("Preparation verification requires a caller-owned transaction.")
        if not isinstance(expected_digest, str) or len(expected_digest) != 64 or not expected_digest.isascii():
            raise PreparationUnavailable("Invalid preparation digest.")
        row, header = self._plan(db, plan_id, subject)
        digest = hashlib.sha256()
        _feed(digest, header)
        cursor = db.execute("SELECT * FROM import_preparation_targets WHERE plan_id=? ORDER BY device_id,ip", (plan_id,))
        while members := cursor.fetchmany(PAGE_SIZE):
            for member in members:
                _feed(digest, _member(member))
        if not hmac.compare_digest(expected_digest, row["digest"]) or not hmac.compare_digest(digest.hexdigest(), expected_digest):
            raise PreparationUnavailable("Preparation digest does not match retained scope.")
        return row, header

    def cancel(self, plan_id, subject):
        """Invalidate only an unconfirmed preparation; never cancels device work."""
        timestamp = _stamp(self.clock())
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row, _ = self._plan(db, plan_id, subject)
            if _confirmed_operation(db, row):
                raise PreparationUnavailable("Preparation is already confirmed. Draft cancellation cannot cancel its standing policy or admitted work.")
            if row["cancelled_at"]:
                return False
            db.execute("UPDATE import_preparation_plans SET cancelled_at=? WHERE id=?", (timestamp, plan_id))
        return True

    def prune_expired(self):
        """Explicit draft-only retention; no policy/queue/attempt/audit deletion."""
        timestamp = _stamp(self.clock())
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not _present(db):
                return 0
            return db.execute("DELETE FROM import_preparation_plans WHERE expires_at<=?", (timestamp,)).rowcount
