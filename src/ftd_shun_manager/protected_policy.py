"""SQLite-owned exact-IP policy, optimistic edits and one-time legacy migration."""

import json
import sqlite3
from ipaddress import IPv4Address
from os import environ
from uuid import uuid4

from .config import _ipv4_csv
from .managed_safety import ManagedStateUnavailable, managed_state
from .operation_queue import OperationQueue, QueueConflict
from .store import Store, now


class ProtectedPolicy:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.queue = OperationQueue(store)
        self.queue.initialize()

    def migrate_legacy_environment(self) -> None:
        """Read the obsolete setting only before the durable first-import marker."""
        logs = []
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT legacy_imported FROM protected_policy WHERE id=1").fetchone()[0]:
                return
            ips = _ipv4_csv(environ.get("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", ""))
            if len(ips) > 1000:
                raise ValueError("legacy Protected IP policy exceeds 1000 addresses")
            for ip in sorted(ips, key=int):
                db.execute("""INSERT INTO protected_ips(ip,name,comment,enabled,updated_at)
                    VALUES (?,?,?,1,?)""", (ip.packed, "Migrated address", "Imported from legacy configuration", now()))
                logs.append(self._audit(db, "PROTECTED_IP_IMPORTED", ip,
                    "system:policy-migration", "Policy migration", (), None,
                    {"name": "Migrated address", "enabled": True}))
            db.execute("UPDATE protected_policy SET legacy_imported=1,revision=revision+1 WHERE id=1")
        for log in logs:
            print(json.dumps(log), flush=True)

    def enabled_ips(self) -> frozenset[IPv4Address]:
        with self.store._connection() as db:
            return frozenset(IPv4Address(row[0]) for row in db.execute("SELECT ip FROM protected_ips WHERE enabled=1"))

    def revision(self) -> int:
        with self.store._connection() as db:
            return db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]

    def snapshot(self) -> dict:
        with self.store._connection() as db:
            db.execute("BEGIN")
            revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
            rows = db.execute("""SELECT p.*,
                (SELECT MAX(timestamp) FROM shun_events e WHERE e.ip=p.ip
                  AND e.event_type='SHUN_TRUSTED_AUTO_REMOVED') AS last_auto_removed_at,
                (SELECT COUNT(DISTINCT device_id) FROM shun_state s WHERE s.ip=p.ip AND active=1) AS active_devices
                FROM protected_ips p ORDER BY p.ip""").fetchall()
            counts = {}
            try:
                managed = managed_state(db)
                if managed is not None:
                    counts = {r[0]: r[1] for r in db.execute("""SELECT ip,COUNT(*) FROM managed_shun_targets
                        WHERE enabled=1 GROUP BY ip""")}
                metadata = {"managed_policy_available": True, "managed_revision": managed["revision"] if managed else 0}
            except (ManagedStateUnavailable, sqlite3.DatabaseError):
                metadata = {"managed_policy_available": False, "managed_revision": None}
            return {"revision": revision, "limit": 1000, **metadata, "entries": [
                {**dict(row), "ip": str(IPv4Address(row["ip"])), "enabled": bool(row["enabled"]),
                 "maintained_devices": counts.get(row["ip"], 0) if metadata["managed_policy_available"] else None} for row in rows
            ]}

    def change(self, action: str, ip: IPv4Address, revision: int, subject: str,
               display_name: str, roles: tuple[str, ...], name: str = "", comment: str = "",
               enabled: bool = True, *, managed_revision: int | None = None,
               confirm_maintenance_resume: bool = False) -> None:
        if not subject.strip():
            raise PermissionError("authenticated user required")
        if action not in {"add", "edit", "delete"} or revision < 0:
            raise ValueError("invalid policy action or revision")
        if (managed_revision is not None and (type(managed_revision) is not int or managed_revision < 0)
                or type(confirm_maintenance_resume) is not bool):
            raise ValueError("invalid managed-policy acknowledgement")
        name, comment = name.strip(), comment.strip()
        if len(name) > 100 or len(comment) > 500 or any(ord(c) < 32 and c not in "\n\t" for c in name + comment):
            raise ValueError("name/comment is too long or contains control characters")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
            if current != revision:
                raise QueueConflict("Protected IPs changed. Review the current list before submitting again.")
            old = db.execute("SELECT * FROM protected_ips WHERE ip=?", (ip.packed,)).fetchone()
            if (action == "add" and old) or (action != "add" and old is None):
                raise QueueConflict("Address already exists or was removed. Review the current list.")
            if action == "add" and db.execute("SELECT COUNT(*) FROM protected_ips").fetchone()[0] >= 1000:
                raise QueueConflict("Protected IP limit reached (1000).")
            context = None
            if action == "delete" or (action == "edit" and old["enabled"] and not enabled):
                state = managed_state(db)
                current_managed = state["revision"] if state else 0
                count = db.execute("SELECT COUNT(*) FROM managed_shun_targets WHERE ip=? AND enabled=1",
                                   (ip.packed,)).fetchone()[0] if state else 0
                if managed_revision is not None and managed_revision != current_managed:
                    raise QueueConflict("Managed policy changed. Reload saved values and review the maintenance warning.")
                if count and (managed_revision != current_managed or not confirm_maintenance_resume):
                    raise QueueConflict("Maintained targets may resume when protection is removed. Review the current managed revision and explicitly acknowledge this.")
                context = {"revision": current_managed, "maintained_devices": count,
                           "resume_acknowledged": confirm_maintenance_resume}
            before = {key: old[key] for key in ("name", "comment", "enabled")} if old else None
            if action == "delete":
                db.execute("DELETE FROM protected_ips WHERE ip=?", (ip.packed,))
            else:
                db.execute("""INSERT INTO protected_ips(ip,name,comment,enabled,updated_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(ip) DO UPDATE SET name=excluded.name,comment=excluded.comment,
                    enabled=excluded.enabled,updated_at=excluded.updated_at""",
                    (ip.packed, name, comment, int(enabled), now()))
            db.execute("UPDATE protected_policy SET revision=revision+1,legacy_imported=1 WHERE id=1")
            # Same write lock as policy mutation and executor claim: no stale policy
            # intent can become RUNNING in the gap. Manual coalesced intents survive.
            self.queue._cancel_obsolete_policy(db)
            log = self._audit(db, {"add": "PROTECTED_IP_ADDED", "edit": "PROTECTED_IP_UPDATED",
                                  "delete": "PROTECTED_IP_DELETED"}[action], ip,
                              subject, display_name, roles, before,
                              None if action == "delete" else {"name": name, "comment": comment, "enabled": enabled}, context)
        print(json.dumps(log), flush=True)

    def _audit(self, db, event, ip, subject, display_name, roles, before, after, managed_context=None) -> dict:
        request_id = str(uuid4())
        details = {"before": before, "after": after, "scope": "fleet", "source": "protected_ip_policy"}
        if managed_context is not None:
            details["managed_context"] = managed_context
        self.store._insert_event(db, event, None, ip, None, subject, display_name, roles, request_id, details)
        # Free-form comments remain escaped in UI / SQLite, not collector payloads.
        return {"event": event, "ip": str(ip), "actor_subject": subject,
                "actor_display_name": display_name, "actor_roles": roles,
                "request_id": request_id, "scope": "fleet"}
