"""Desired-policy registry; optional reads and explicit policy-only controls.

Initializing this registry is explicit: normal application startup does not
migrate it. Nothing here admits queue jobs, reads FTD or establishes creation.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
from ipaddress import IPv4Address
from uuid import UUID, uuid4

from .managed_intent import canonical_managed_change
from .managed_safety import fleet_key_reserved, fleet_target_held, managed_state
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection
from .store import Store, now

MAX_MANAGED_TARGETS = 1000  # Includes retired tombstones; never silently recycle.
MAX_MANAGED_REQUESTS = 10000  # No automatic expiry or idempotency-key recycling.


class ManagedConflict(ValueError):
    """Reviewed intent or revision conflicts with durable policy."""


class ManagedCapacity(ValueError):
    """The registry cannot accept the entire change within its bounds."""


class ManagedPageChanged(ManagedConflict):
    """Page membership changed; require an explicit current-policy view."""


class ManagedPageInvalid(ValueError):
    """Invalid page selector, distinct from corrupt retained policy."""


def _require_operator(subject: str, roles: tuple[str, ...]) -> None:
    if not subject.strip() or not {"Operator", "Administrator"}.intersection(roles):
        raise PermissionError("Authenticated Operator or Administrator required.")


class ManagedShuns:
    def __init__(self, store: Store):
        self.store = store

    def initialize(self, *, connection=None) -> None:
        """Add empty tables only; never adopt observations, old imports or jobs."""
        with schema_connection(self.store, connection) as db:
            execute_schema(db, """
                CREATE TABLE IF NOT EXISTS managed_shun_registry (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
                    restoration_suspended INTEGER NOT NULL DEFAULT 1 CHECK(restoration_suspended IN (0,1))
                );
                INSERT OR IGNORE INTO managed_shun_registry(id) VALUES (1);
                CREATE TABLE IF NOT EXISTS managed_shun_requests (
                    id TEXT PRIMARY KEY,
                    actor_subject TEXT NOT NULL,
                    actor_display_name TEXT NOT NULL,
                    actor_roles_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_shun_targets (
                    device_id INTEGER NOT NULL REFERENCES devices(id),
                    ip BLOB NOT NULL CHECK(length(ip)=4),
                    intent_id TEXT NOT NULL UNIQUE,
                    generation INTEGER NOT NULL CHECK(generation>=1),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    revision INTEGER NOT NULL CHECK(revision>=1),
                    authorization_request_id TEXT NOT NULL REFERENCES managed_shun_requests(id),
                    authorized_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    retired_at TEXT,
                    CHECK((enabled=1 AND retired_at IS NULL) OR (enabled=0 AND retired_at IS NOT NULL)),
                    PRIMARY KEY(device_id,ip)
                );
                CREATE TRIGGER IF NOT EXISTS managed_request_immutable_update
                BEFORE UPDATE ON managed_shun_requests BEGIN
                    SELECT RAISE(ABORT,'managed request is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS managed_request_immutable_delete
                BEFORE DELETE ON managed_shun_requests BEGIN
                    SELECT RAISE(ABORT,'managed request is retained for idempotency and authorization');
                END;
            """)

    def change(
        self, request_id: str, action: str, targets: list[tuple[int, IPv4Address]],
        managed_revision: int, protected_revision: int, confirmation_digest: str,
        subject: str, display_name: str, roles: tuple[str, ...],
        label: str = "", reason: str = "",
    ) -> dict:
        """Commit policy only. Future queue retirement must share apply_change's transaction."""
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            result = self.apply_change(db, request_id, action, targets, managed_revision,
                                       protected_revision, confirmation_digest, subject,
                                       display_name, roles, label, reason)
        if not result["replayed"]:
            # Emit only after commit. No comments, labels, raw source or full lists.
            print(json.dumps({"event": "managed_shun.policy.changed", "request_id": request_id,
                              "actor_subject": subject, "action": action,
                              "managed_revision": result["managed_revision"],
                              "changed_targets": result["changed_targets"]}), flush=True)
        return result

    def grant_reviewed(self, request_id, device_id, ip, revision, protected_revision, digest,
                       subject, display_name, roles, *, addition_device_ids=frozenset(), label="", reason=""):
        """Policy-only single-pair admission. No migration, queue insertion or wakeup."""
        return self.grant_batch_reviewed(request_id, [(device_id, ip)], revision, protected_revision, digest,
                                         subject, display_name, roles, addition_device_ids=addition_device_ids,
                                         label=label, reason=reason)

    def grant_batch_reviewed(self, request_id, targets, revision, protected_revision, digest,
                             subject, display_name, roles, *, addition_device_ids=frozenset(), label="", reason=""):
        """One whole-scope policy transaction, never per-target admission/queue work."""
        from .managed_restoration import present
        from .managed_safety import ManagedStateUnavailable

        _require_operator(subject, roles)
        targets, _, _ = canonical_managed_change("MAINTAIN", targets, revision, protected_revision, label, reason)
        if len({device for device, _ in targets}) > 64:
            raise ValueError("Select at most 64 distinct devices.")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if managed_state(db) is None:
                raise ManagedStateUnavailable("Managed policy is not initialized; explicit migration is required.")
            previous = db.execute("SELECT 1 FROM managed_shun_requests WHERE id=?", (request_id,)).fetchone()
            if not previous:
                if any(device not in addition_device_ids for device, _ in targets):
                    raise ManagedConflict("An explicit addition-capable device profile is required.")
                if not present(db):
                    raise ManagedStateUnavailable("Restoration evidence is not initialized; no policy was saved.")
                for device_id, ip in targets:
                    if db.execute("SELECT 1 FROM managed_shun_targets WHERE device_id=? AND ip=? AND enabled=1",
                                  (device_id, ip.packed)).fetchone():
                        raise ManagedConflict("Target is already maintained; inspect current holds instead.")
                    if (db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=?
                            AND state IN ('QUEUED','RUNNING','UNVERIFIED')""", (device_id, ip.packed)).fetchone()
                            or db.execute("""SELECT 1 FROM managed_restoration_attempts WHERE device_id=? AND ip=?
                                AND state IN ('FAILED','UNVERIFIED')""", (device_id, ip.packed)).fetchone()):
                        raise ManagedConflict("Unfinished or uncertain work requires resolution before a standing grant.")
            result = self.apply_change(db, request_id, "MAINTAIN", targets, revision,
                                       protected_revision, digest, subject, display_name, roles, label, reason)
        if not result["replayed"]:
            print(json.dumps({"event": "managed_shun.policy.changed", "request_id": request_id,
                              "actor_subject": subject, "action": "MAINTAIN", "managed_revision": result["managed_revision"],
                              "changed_targets": result["changed_targets"]}), flush=True)
        return result

    def apply_change(
        self, db: sqlite3.Connection, request_id: str, action: str,
        targets: list[tuple[int, IPv4Address]], managed_revision: int, protected_revision: int,
        confirmation_digest: str, subject: str, display_name: str, roles: tuple[str, ...],
        label: str = "", reason: str = "",
    ) -> dict:
        """Trusted internal composition hook: caller owns write transaction/commit/logging.

        Uses a savepoint so even a caught conflict cannot leave partial policy or
        audit writes inside the caller's transaction. This hook never admits
        queue work itself; composite callers own that separate admission.
        """
        if not db.in_transaction:
            raise ValueError("Managed changes require a caller-owned transaction.")
        _require_operator(subject, roles)
        try:
            if str(UUID(request_id)) != request_id:
                raise ValueError("Non-canonical UUID")
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("An explicit canonical UUID request key is required.") from error
        targets, payload, digest = canonical_managed_change(
            action, targets, managed_revision, protected_revision, label, reason,
        )
        if (not isinstance(confirmation_digest, str) or not confirmation_digest.isascii()
                or not hmac.compare_digest(digest, confirmation_digest)):
            raise ValueError("Confirmation does not match the exact managed intent.")
        db.execute("SAVEPOINT managed_policy_change")
        try:
            result = self._apply(db, request_id, action, targets, managed_revision,
                                 protected_revision, subject, display_name, roles, payload)
        except Exception:
            db.execute("ROLLBACK TO managed_policy_change")
            db.execute("RELEASE managed_policy_change")
            raise
        db.execute("RELEASE managed_policy_change")
        return result

    def _apply(self, db, request_id, action, targets, revision, protected_revision,
               subject, display_name, roles, payload, *, adopted_pairs=frozenset()):
        from .managed_restoration import cancel_obsolete, key_reserved
        from .operation_queue import OperationQueue

        # Only the prepared-import coordinator supplies a reviewed adoption set.
        # Ordinary change/grant entry points never pass this internal argument.
        if (type(adopted_pairs) is not frozenset or not adopted_pairs.issubset(targets)
                or (adopted_pairs and action != "MAINTAIN")):
            raise ValueError("Adoption requires an exact reviewed subset of maintained pairs.")
        previous = db.execute("SELECT * FROM managed_shun_requests WHERE id=?", (request_id,)).fetchone()
        if previous:
            if previous["actor_subject"] != subject or previous["payload_json"] != payload:
                raise ManagedConflict("Request key was already used for another managed intention.")
            return {**json.loads(previous["result_json"]), "replayed": True}
        if action == "MAINTAIN" and mutations_suspended(db):
            raise ManagedConflict("New managed authority is suspended for recovery; retirement remains available.")
        if key_reserved(db, request_id):
            raise ManagedConflict("Restoration keys cannot authorize a new managed policy.")
        if fleet_key_reserved(db, request_id):
            raise ManagedConflict("Managed-fleet keys cannot authorize another policy operation.")
        # A key from the one-time namespace cannot acquire standing semantics.
        legacy_queue = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_requests'").fetchone()
        if (db.execute("SELECT 1 FROM manual_import_batches WHERE id=?", (request_id,)).fetchone()
                or (legacy_queue and db.execute("SELECT 1 FROM operation_requests WHERE id=?", (request_id,)).fetchone())):
            raise ManagedConflict("One-time operation keys cannot authorize managed policy.")
        if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_removal_handoffs'").fetchone()
                and db.execute("SELECT 1 FROM managed_removal_handoffs WHERE id=?", (request_id,)).fetchone()):
            raise ManagedConflict("Managed-removal keys cannot authorize another policy operation.")
        current = db.execute("SELECT revision FROM managed_shun_registry WHERE id=1").fetchone()[0]
        if current != revision:
            raise ManagedConflict("Managed shuns changed; review the current policy.")
        request_count = db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0]
        if request_count >= MAX_MANAGED_REQUESTS:
            raise ManagedCapacity("Managed request ledger is full; no changes were applied.")
        if action == "MAINTAIN" and db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0] != protected_revision:
            raise ManagedConflict("Protected IPs changed; review the managed targets.")
        changes = []
        for device_id, ip in targets:
            old = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (device_id, ip.packed)).fetchone()
            if action == "MAINTAIN":
                from .managed_closures import pair_abandoned

                if pair_abandoned(db, device_id, ip):
                    raise ManagedConflict("Maintenance was explicitly abandoned for this pair; no rearm is available.")
                if fleet_target_held(db, device_id, ip, attention=True):
                    raise ManagedConflict("Fleet cleanup is waiting or needs attention; do not re-enable maintenance.")
                if (legacy_queue and db.execute("""SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=?
                        AND action='REMOVE' AND state IN ('QUEUED','RUNNING') LIMIT 1""",
                                               (device_id, ip.packed)).fetchone()):
                    raise ManagedConflict("Removal is pending or running; resolve it before authorizing maintenance.")
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_removal_handoffs'").fetchone():
                    cleanup = db.execute("""SELECT 1 FROM managed_removal_handoffs h
                        WHERE h.device_id=? AND h.ip=? AND (h.state IN ('WAITING_ADD','ATTENTION')
                        OR (h.state='ADMITTED' AND EXISTS (
                            SELECT 1 FROM operation_links l JOIN operation_jobs j ON j.id=l.job_id
                            WHERE l.request_id=h.id AND j.state IN ('QUEUED','RUNNING'))))""",
                        (device_id, ip.packed)).fetchone()
                    if cleanup:
                        raise ManagedConflict("Managed cleanup is pending or needs attention; do not re-enable maintenance.")
                device = db.execute("SELECT enabled FROM devices WHERE id=?", (device_id,)).fetchone()
                if device is None or not device[0]:
                    raise ManagedConflict("Unknown or disabled managed target device.")
                if db.execute("SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1", (ip.packed,)).fetchone():
                    raise ManagedConflict("Enabled Protected IPs cannot be maintained as shuns.")
                observed = db.execute(
                    "SELECT 1 FROM shun_state WHERE device_id=? AND ip=? AND active=1",
                    (device_id, ip.packed),
                ).fetchone() is not None
                if (device_id, ip) in adopted_pairs and (not observed or (old is not None and old["enabled"])):
                    raise ManagedConflict("Reviewed adoption no longer matches an unmanaged observed target.")
                if (old is None or not old["enabled"]) and observed and (device_id, ip) not in adopted_pairs:
                    raise ManagedConflict("Existing shun adoption requires a separate reviewed workflow.")
                changes.append((device_id, ip, old, old is None or not old["enabled"]))
            else:
                if old is None:
                    raise ManagedConflict("Target is not managed; review the exact retirement scope.")
                changes.append((device_id, ip, old, bool(old["enabled"])))
        total = db.execute("SELECT COUNT(*) FROM managed_shun_targets").fetchone()[0]
        if total + sum(old is None for _, _, old, _ in changes) > MAX_MANAGED_TARGETS:
            raise ManagedCapacity("Managed target limit reached, including retired records.")
        # Reserve one ledger slot per possible active target for revocation.
        # New grants/no-op churn cannot consume the ability to stop maintenance.
        if request_count >= MAX_MANAGED_REQUESTS - MAX_MANAGED_TARGETS and (
            action == "MAINTAIN" or not any(changed for _, _, _, changed in changes)
        ):
            raise ManagedCapacity("Managed ledger reserve is for retirement only.")
        timestamp = now()
        result = {"operation_id": request_id, "status": "policy_saved", "managed_revision": current + 1,
                  "changed_targets": sum(changed for _, _, _, changed in changes), "replayed": False}
        db.execute("INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)", (
            request_id, subject, display_name, json.dumps(roles), payload, json.dumps(result), timestamp,
        ))
        for device_id, ip, old, changed in changes:
            if changed:
                if action == "MAINTAIN":
                    db.execute("""INSERT INTO managed_shun_targets VALUES (?,?,?,?,1,?,?,?,?,NULL)
                        ON CONFLICT(device_id,ip) DO UPDATE SET intent_id=excluded.intent_id,
                        generation=excluded.generation,enabled=1,revision=excluded.revision,
                        authorization_request_id=excluded.authorization_request_id,
                        authorized_at=excluded.authorized_at,updated_at=excluded.updated_at,retired_at=NULL""",
                        (device_id, ip.packed, str(uuid4()), old["generation"] + 1 if old else 1,
                         current + 1, request_id, timestamp, timestamp))
                else:
                    db.execute("""UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=?
                        WHERE device_id=? AND ip=?""", (current + 1, timestamp, timestamp, device_id, ip.packed))
            row = db.execute("SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?", (device_id, ip.packed)).fetchone()
            self.store._insert_event(db, "MANAGED_SHUN_ADOPTED" if (device_id, ip) in adopted_pairs else
                                     "MANAGED_SHUN_AUTHORIZED" if action == "MAINTAIN" and changed else
                                     "MANAGED_SHUN_RETIRED" if changed else "MANAGED_SHUN_POLICY_NOOP",
                                     device_id, ip, None, subject, display_name, roles, request_id,
                                     {"source": "managed_shun_policy", "mode": "maintain_present",
                                      "intent_id": row["intent_id"], "generation": row["generation"],
                                      "enabled": bool(row["enabled"]), "action": action,
                                      "managed_revision": current + 1}, timestamp=timestamp)
        db.execute("UPDATE managed_shun_registry SET revision=? WHERE id=1", (current + 1,))
        cancel_obsolete(db, OperationQueue(self.store))  # Same transaction as retirement, never cancel RUNNING ADD.
        return result

    @staticmethod
    def _registry_state(db, *, if_present: bool):
        names = {row[0] for row in db.execute("""SELECT name FROM sqlite_master WHERE type='table'
            AND name IN ('managed_shun_registry','managed_shun_targets','managed_shun_requests')""")}
        if not names and if_present:
            return None
        if len(names) != 3:
            raise ManagedConflict("Managed registry is missing or incomplete.")
        state = db.execute("SELECT * FROM managed_shun_registry WHERE id=1").fetchone()
        if state is None:
            raise ManagedConflict("Managed registry state is incomplete.")
        return dict(state)

    def metadata(self) -> dict:
        """Cheap optional read for refresh metadata; no initialization or migration."""
        with self.store._connection() as db:
            db.execute("BEGIN")
            state = managed_state(db)
            return {"managed_policy_available": True, "managed_policy_initialized": state is not None,
                    "managed_policy_revision": state["revision"] if state is not None else 0}

    def snapshot_if_present(self, *, restoration_context=None, restoration_now=None) -> dict:
        """Read-only published view: missing registry is explicit, partial schema is error."""
        value = self.snapshot(if_present=True, restoration_context=restoration_context, restoration_now=restoration_now)
        return {**value, "controller_available": restoration_context is not None, "read_only": True,
                **({"controller_enabled": restoration_context.enabled} if restoration_context is not None else {})}

    def snapshot(self, *, if_present: bool = False, restoration_context=None, restoration_now=None) -> dict:
        """One consistent bounded view; observed presence is not creation proof."""
        from .managed_discovery import describe
        from .managed_restoration import snapshot_targets
        from .operation_queue import OperationQueue

        with self.store._connection() as db:
            db.execute("BEGIN")
            managed_state(db)
            state = self._registry_state(db, if_present=if_present)
            if state is None:
                return {"initialized": False, "revision": 0, "restoration_suspended": True,
                        "limit": MAX_MANAGED_TARGETS, "entries": []}
            rows = db.execute("""SELECT m.*,d.hostname,d.enabled AS device_enabled,
                r.actor_subject,r.actor_display_name,r.actor_roles_json,r.payload_json,
                EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=m.device_id AND s.ip=m.ip AND s.active=1) AS observed_present,
                EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=m.ip AND p.enabled=1) AS protected
                FROM managed_shun_targets m JOIN devices d ON d.id=m.device_id
                JOIN managed_shun_requests r ON r.id=m.authorization_request_id
                ORDER BY m.device_id,m.ip LIMIT ?""", (MAX_MANAGED_TARGETS + 1,)).fetchall()
            if len(rows) > MAX_MANAGED_TARGETS:
                raise ManagedCapacity("Stored managed targets exceed this version's supported limit.")
            restoration = snapshot_targets(db)
            holds = describe(db, rows, restoration_context, restoration_now or OperationQueue(self.store)._now()) if restoration_context is not None else {}
        return {**({"initialized": True} if if_present else {}),
                "revision": state["revision"], "restoration_suspended": bool(state["restoration_suspended"]),
                "limit": MAX_MANAGED_TARGETS, "entries": self._entries(rows, restoration, holds)}

    def page(self, page=1, *, revision=None, restoration_context=None, restoration_now=None):
        """Read 100 policy rows and only their summaries in one SQLite snapshot.

        This does not expand authority/storage capacity. The existing full view
        remains available to legacy frozen review workflows.
        """
        from .managed_discovery import describe
        from .managed_restoration import snapshot_targets
        from .operation_queue import OperationQueue

        if type(page) is not int or not 1 <= page <= 2**31 - 1:
            raise ManagedPageInvalid("Select a positive managed-policy page.")
        if revision is not None and (type(revision) is not int or revision < 0):
            raise ManagedPageInvalid("Managed revision must be a non-negative integer.")
        with self.store._connection() as db:
            db.execute("BEGIN")
            state = managed_state(db)
            current_revision = state["revision"] if state is not None else 0
            if revision is not None and revision != current_revision:
                raise ManagedPageChanged("Managed policy changed. Open the current policy before continuing pagination.")
            total = db.execute("SELECT COUNT(*) FROM managed_shun_targets").fetchone()[0] if state is not None else 0
            pages = max(1, (total + 99) // 100)
            if page > pages:
                raise ManagedPageInvalid("Select a page within the managed policy.")
            rows, restoration, holds = [], {}, {}
            if state is not None:
                # A join must not silently hide an orphaned policy/authority row.
                if db.execute("""SELECT 1 FROM managed_shun_targets m
                    LEFT JOIN devices d ON d.id=m.device_id
                    LEFT JOIN managed_shun_requests r ON r.id=m.authorization_request_id
                    WHERE d.id IS NULL OR r.id IS NULL LIMIT 1""").fetchone():
                    raise ManagedConflict("Managed target is missing its device or retained authority.")
                rows = db.execute("""SELECT m.*,d.hostname,d.enabled AS device_enabled,
                    r.actor_subject,r.actor_display_name,r.actor_roles_json,r.payload_json,
                    EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=m.device_id AND s.ip=m.ip AND s.active=1) AS observed_present,
                    EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=m.ip AND p.enabled=1) AS protected
                    FROM managed_shun_targets m JOIN devices d ON d.id=m.device_id
                    JOIN managed_shun_requests r ON r.id=m.authorization_request_id
                    ORDER BY m.device_id,m.ip LIMIT 100 OFFSET ?""", ((page - 1) * 100,)).fetchall()
                pairs = [(row["device_id"], row["ip"]) for row in rows]
                restoration = snapshot_targets(db, pairs=pairs)
                if restoration_context is not None:
                    holds = describe(db, rows, restoration_context, restoration_now or OperationQueue(self.store)._now(), scoped=True)
        return {"initialized": state is not None, "revision": current_revision,
                "restoration_suspended": state["restoration_suspended"] if state is not None else True,
                "limit": MAX_MANAGED_TARGETS, "page": page, "pages": pages, "page_size": 100, "total": total,
                "read_only": True, "controller_available": restoration_context is not None,
                **({"controller_enabled": restoration_context.enabled} if restoration_context is not None else {}),
                "entries": self._entries(rows, restoration, holds)}

    @staticmethod
    def _entries(rows, restoration, holds):
        entries = []
        metadata = {}
        for row in rows:
            entry = dict(row)
            if row["authorization_request_id"] not in metadata:
                data = json.loads(entry["payload_json"])
                metadata[row["authorization_request_id"]] = {key: data[key] for key in ("label", "reason")}
            del entry["payload_json"]
            entry.update(metadata[row["authorization_request_id"]])
            entry.update(restoration.get((row["device_id"], row["ip"]), {}))
            entry.update(holds.get((row["device_id"], row["ip"]), {}))
            entry["ip"] = str(IPv4Address(row["ip"]))
            entry["actor_roles"] = json.loads(entry.pop("actor_roles_json"))
            for key in ("enabled", "device_enabled", "observed_present", "protected"):
                entry[key] = bool(entry[key])
            entries.append(entry)
        return entries
