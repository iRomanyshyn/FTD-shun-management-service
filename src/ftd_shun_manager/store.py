"""SQLite state and append-only audit event store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Device:
    id: int
    hostname: str
    management_ip: IPv4Address
    enabled: bool
    # Startup-only capability from validated inventory; never persisted as policy.
    addition_profile: str | None = None


@dataclass(frozen=True)
class Shun:
    device_id: int
    device_hostname: str
    ip: IPv4Address
    interface: str
    first_seen_at: str
    last_seen_at: str
    active: bool
    active_since_at: str
    manual_imports: tuple[dict, ...] = ()
    manual_import_count: int = 0


class HistoryWindowExpired(ValueError):
    """The event anchoring a retained-history window is no longer available."""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS protected_ips (
                    ip BLOB PRIMARY KEY CHECK(length(ip)=4),
                    name TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS protected_policy (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    revision INTEGER NOT NULL DEFAULT 0,
                    legacy_imported INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO protected_policy(id) VALUES (1);
                CREATE TABLE IF NOT EXISTS devices (
                  id INTEGER PRIMARY KEY CHECK(id BETWEEN 1 AND 65535),
                  hostname TEXT NOT NULL UNIQUE,
                  management_ip BLOB NOT NULL UNIQUE,
                  ssh_host_key TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS shun_state (
                  device_id INTEGER NOT NULL REFERENCES devices(id),
                  ip BLOB NOT NULL,
                  interface TEXT NOT NULL,
                  active INTEGER NOT NULL CHECK(active IN (0, 1)),
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  last_changed_at TEXT NOT NULL,
                  PRIMARY KEY(device_id, ip, interface)
                );
                CREATE TABLE IF NOT EXISTS shun_events (
                  id TEXT PRIMARY KEY,
                  timestamp TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  device_id INTEGER REFERENCES devices(id),
                  ip BLOB,
                  interface TEXT,
                  actor_subject TEXT,
                  actor_display_name TEXT,
                  actor_roles_json TEXT,
                  request_id TEXT,
                  details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_shun_events_request_id
                  ON shun_events(request_id);
                CREATE TABLE IF NOT EXISTS manual_import_batches (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL CHECK(source='manual_import'),
                  actor_subject TEXT NOT NULL,
                  actor_display_name TEXT NOT NULL,
                  actor_roles_json TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shun_import_origins (
                  batch_id TEXT NOT NULL REFERENCES manual_import_batches(id),
                  job_id TEXT NOT NULL,
                  device_id INTEGER NOT NULL REFERENCES devices(id),
                  ip BLOB NOT NULL CHECK(length(ip)=4),
                  interface TEXT NOT NULL,
                  occurrence_id TEXT NOT NULL,
                  verified_at TEXT NOT NULL,
                  PRIMARY KEY(batch_id,job_id,occurrence_id)
                );
                CREATE INDEX IF NOT EXISTS idx_import_origin_occurrence
                  ON shun_import_origins(occurrence_id);
                """
            )
            db.execute("BEGIN IMMEDIATE")
            if "occurrence_id" not in {row["name"] for row in db.execute("PRAGMA table_info(shun_state)")}:
                db.execute("ALTER TABLE shun_state ADD COLUMN occurrence_id TEXT")
            db.execute("UPDATE shun_state SET occurrence_id=lower(hex(randomblob(16))) WHERE occurrence_id IS NULL")
            db.execute("CREATE INDEX IF NOT EXISTS idx_shun_state_occurrence ON shun_state(occurrence_id)")
            # Preserve occurrence semantics even during a rollback to writers
            # unaware of this new column. Reappearance must never inherit origin.
            db.execute("""CREATE TRIGGER IF NOT EXISTS shun_occurrence_on_reappearance
                AFTER UPDATE OF active ON shun_state
                WHEN OLD.active=0 AND NEW.active=1 AND NEW.occurrence_id IS OLD.occurrence_id
                BEGIN UPDATE shun_state SET occurrence_id=lower(hex(randomblob(16)))
                WHERE device_id=NEW.device_id AND ip=NEW.ip AND interface=NEW.interface; END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS shun_occurrence_on_insert AFTER INSERT ON shun_state
                WHEN NEW.occurrence_id IS NULL BEGIN UPDATE shun_state SET occurrence_id=lower(hex(randomblob(16)))
                WHERE device_id=NEW.device_id AND ip=NEW.ip AND interface=NEW.interface; END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_import_batch BEFORE UPDATE ON manual_import_batches
                BEGIN SELECT RAISE(ABORT,'accepted import metadata is immutable'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_import_origin BEFORE UPDATE ON shun_import_origins
                BEGIN SELECT RAISE(ABORT,'verified import origin is immutable'); END""")

    def list_devices(self) -> list[Device]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id, hostname, management_ip, enabled FROM devices ORDER BY hostname"
            ).fetchall()
        return [Device(row["id"], row["hostname"], IPv4Address(row["management_ip"]), bool(row["enabled"])) for row in rows]

    def upsert_device(self, device: Device, ssh_host_key: str) -> None:
        if not ssh_host_key.strip():
            raise ValueError("a pinned SSH host key is required")
        with self._connection() as db:
            db.execute(
                """INSERT INTO devices (id, hostname, management_ip, ssh_host_key, enabled)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET hostname = excluded.hostname,
                     management_ip = excluded.management_ip, ssh_host_key = excluded.ssh_host_key,
                     enabled = excluded.enabled""",
                (device.id, device.hostname, device.management_ip.packed, ssh_host_key, int(device.enabled)),
            )

    def list_active_shuns(self, ip: IPv4Address | None = None) -> list[Shun]:
        query = """
          SELECT s.device_id, d.hostname AS device_hostname, s.ip, s.interface,
                 s.first_seen_at, s.last_seen_at, s.active,
                 s.last_changed_at AS active_since_at, s.occurrence_id
          FROM shun_state AS s JOIN devices AS d ON d.id = s.device_id
          LEFT JOIN protected_ips AS p ON p.ip = s.ip
          WHERE s.active = 1
        """
        parameters: tuple[bytes, ...] = ()
        if ip:
            query += " AND s.ip = ?"
            parameters = (ip.packed,)
        # Both enabled and disabled policy matches need attention while shunned.
        # last_changed_at is the current appearance, not each polling timestamp.
        query += " ORDER BY (p.ip IS NOT NULL) DESC, s.last_changed_at DESC, s.ip, d.hostname, s.interface"
        with self._connection() as db:
            db.execute("BEGIN")
            rows = db.execute(query, parameters).fetchall()
            origins: dict[str, list[dict]] = {}
            origin_counts: dict[str, int] = {}
            # One representative plus exact total per occurrence: coalesced
            # actors remain fully audited without multiplying large API bodies.
            origin_query = """SELECT o.occurrence_id,MIN(o.rowid) AS representative,COUNT(*) AS n
                FROM shun_import_origins o
                JOIN shun_state s ON s.occurrence_id=o.occurrence_id AND s.active=1
                WHERE s.device_id=o.device_id AND s.ip=o.ip AND s.interface=o.interface"""
            if ip:
                origin_query += " AND s.ip=?"
            selected = db.execute("""SELECT o.*,live.n FROM (""" + origin_query + """
                GROUP BY o.occurrence_id) AS live JOIN shun_import_origins o ON o.rowid=live.representative""",
                parameters).fetchall()
            batches = {}
            batch_ids = sorted({row["batch_id"] for row in selected})
            # Decode each canonical batch once, not its potentially 1000-target
            # payload once per origin/active row. Bound SQL variable/body peaks.
            for offset in range(0,len(batch_ids),500):
                group = batch_ids[offset:offset+500]
                for batch in db.execute("SELECT * FROM manual_import_batches WHERE id IN (" + ",".join("?" for _ in group) + ")",group):
                    payload = json.loads(batch["payload_json"])
                    batches[batch["id"]] = {"actor_subject":batch["actor_subject"],
                        "actor_display_name":batch["actor_display_name"],"label":payload["label"],"reason":payload["reason"]}
            for origin in selected:
                origin_counts[origin["occurrence_id"]] = origin["n"]
                origins.setdefault(origin["occurrence_id"], []).append({
                    "source": "manual_import", "batch_id": origin["batch_id"], "operation_id": origin["job_id"],
                    **batches[origin["batch_id"]], "verified_at": origin["verified_at"],
                })
        return [
            Shun(
                row["device_id"], row["device_hostname"], IPv4Address(row["ip"]),
                row["interface"], row["first_seen_at"], row["last_seen_at"], bool(row["active"]),
                row["active_since_at"],
                tuple(origins.get(row["occurrence_id"], [])),
                origin_counts.get(row["occurrence_id"], 0),
            )
            for row in rows
        ]

    def active_shuns_for_device_ip(self, device_id: int, ip: IPv4Address) -> list[Shun]:
        return [shun for shun in self.list_active_shuns(ip) if shun.device_id == device_id]

    def list_events(self, ip: IPv4Address | None = None, limit: int = 200) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = """
          SELECT e.id, e.timestamp, e.event_type, e.device_id, d.hostname AS device_hostname,
                 e.ip, e.interface, e.actor_subject, e.actor_display_name,
                 e.actor_roles_json, e.request_id, e.details_json
          FROM shun_events AS e LEFT JOIN devices AS d ON d.id = e.device_id
        """
        parameters: tuple[bytes | int, ...] = (limit,)
        if ip:
            query += " WHERE e.ip = ?"
            parameters = (ip.packed, limit)
        query += " ORDER BY e.timestamp DESC LIMIT ?"
        with self._connection() as db:
            rows = db.execute(query, parameters).fetchall()
        return [self._event_dict(row) for row in rows]

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "event_type": row["event_type"],
            "device_id": row["device_id"],
            "device_hostname": row["device_hostname"],
            "ip": str(IPv4Address(row["ip"])) if row["ip"] else None,
            "interface": row["interface"],
            "actor_subject": row["actor_subject"],
            "actor_display_name": row["actor_display_name"],
            "actor_roles": json.loads(row["actor_roles_json"] or "[]"),
            "request_id": row["request_id"],
            "details": json.loads(row["details_json"]),
        }

    def history_page(self, page: int = 1, anchor: str | None = None) -> dict:
        """Bounded retained-history browsing; no new row can enter an anchored window."""
        if not 1 <= page <= 2**31 - 1:
            raise ValueError("page must be between 1 and 2147483647")
        with self._connection() as db:
            db.execute("BEGIN")
            if anchor is None:
                boundary = db.execute("SELECT rowid, id FROM shun_events ORDER BY rowid DESC LIMIT 1").fetchone()
            else:
                # Offline restore audit IDs may use UUID hex without hyphens.
                boundary = db.execute("SELECT rowid, id FROM shun_events WHERE id IN (?,?)",
                                      (anchor, anchor.replace("-", ""))).fetchone()
                if boundary is None:
                    raise HistoryWindowExpired("History window expired. Open Latest events.")
            ceiling = boundary["rowid"] if boundary else 0
            total = db.execute("SELECT COUNT(*) FROM shun_events WHERE rowid<=?", (ceiling,)).fetchone()[0]
            pages = max(1, (total + 99) // 100)
            current = min(page, pages)
            rows = db.execute("""SELECT e.*, d.hostname AS device_hostname
                FROM shun_events e LEFT JOIN devices d ON d.id=e.device_id
                WHERE e.rowid<=? ORDER BY e.timestamp DESC, e.rowid DESC LIMIT 100 OFFSET ?""",
                (ceiling, (current - 1) * 100),
            ).fetchall()
            return {"events": [self._event_dict(row) for row in rows], "page": current,
                    "pages": pages, "total": total, "page_size": 100,
                    "anchor": boundary["id"] if boundary else None}

    def search_ip_history(self, query: str, limit: int = 100) -> list[dict[str, str | int | bool | None]]:
        """Search local active and historical state by a validated IPv4 prefix."""
        normalized = _ip_prefix(query)
        if not 1 <= limit <= 100:
            raise ValueError("search limit must be between 1 and 100")
        with self._connection() as db:
            rows = db.execute(
                """SELECT ip FROM shun_state
                   UNION
                   SELECT ip FROM shun_events WHERE ip IS NOT NULL
                   UNION SELECT ip FROM protected_ips WHERE enabled=1"""
            ).fetchall()
            matches = sorted(
                (IPv4Address(row["ip"]) for row in rows if str(IPv4Address(row["ip"])).startswith(normalized)),
                key=int,
            )[:limit]
            result: list[dict[str, str | int | bool | None]] = []
            for ip in matches:
                state = db.execute(
                    """SELECT MAX(active) AS active, MAX(last_seen_at) AS last_seen_at,
                              COUNT(DISTINCT device_id) AS device_count
                       FROM shun_state WHERE ip = ?""",
                    (ip.packed,),
                ).fetchone()
                events = db.execute(
                    """SELECT MAX(timestamp) AS last_event_at,
                              MAX(CASE WHEN event_type IN
                                  ('SHUN_REMOVED_BY_UI', 'SHUN_TRUSTED_AUTO_REMOVED')
                                  THEN timestamp END) AS last_removed_at
                       FROM shun_events WHERE ip = ?""",
                    (ip.packed,),
                ).fetchone()
                result.append(
                    {
                        "ip": str(ip),
                        "active": bool(state["active"]),
                        "last_seen_at": state["last_seen_at"],
                        "last_removed_at": events["last_removed_at"],
                        "last_event_at": events["last_event_at"],
                        "device_count": state["device_count"],
                    }
                )
        return result

    def record_observed_shun(self, device_id: int, ip: IPv4Address, interface: str) -> None:
        if not interface or len(interface) > 128:
            raise ValueError("interface is invalid")
        timestamp = now()
        with self._connection() as db:
            previous = db.execute(
                "SELECT active FROM shun_state WHERE device_id = ? AND ip = ? AND interface = ?",
                (device_id, ip.packed, interface),
            ).fetchone()
            if previous is None:
                db.execute(
                    """INSERT INTO shun_state
                       (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at,occurrence_id)
                       VALUES (?, ?, ?, 1, ?, ?, ?,?)""",
                    (device_id, ip.packed, interface, timestamp, timestamp, timestamp,str(uuid4())),
                )
                event = "SHUN_DETECTED"
            else:
                event = "SHUN_REAPPEARED" if not previous["active"] else None
                if event:
                    db.execute(
                        """UPDATE shun_state SET active = 1, last_seen_at = ?, last_changed_at = ?,occurrence_id=?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, timestamp,str(uuid4()), device_id, ip.packed, interface),
                    )
                else:
                    db.execute(
                        """UPDATE shun_state SET last_seen_at = ?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, device_id, ip.packed, interface),
                    )
            if event:
                self._insert_event(db, event, device_id, ip, interface, None, None, (), None, {})

    def reconcile_snapshot(
        self, device_id: int, snapshot: Iterable[tuple[IPv4Address, str]]
    ) -> None:
        """Atomically reconcile one complete, successfully parsed device snapshot."""
        snapshot_entries = [(ip.packed, interface) for ip, interface in snapshot]
        observed = set(snapshot_entries)
        if len(observed) != len(snapshot_entries):
            raise ValueError("snapshot contains duplicate entries")
        if any(not _safe_interface(interface) for _, interface in observed):
            raise ValueError("snapshot contains an invalid interface")
        timestamp = now()
        with self._connection() as db:
            existing_rows = db.execute(
                "SELECT ip, interface, active FROM shun_state WHERE device_id = ?",
                (device_id,),
            ).fetchall()
            existing = {(row["ip"], row["interface"]): bool(row["active"]) for row in existing_rows}

            for packed_ip, interface in observed:
                ip = IPv4Address(packed_ip)
                active = existing.get((packed_ip, interface))
                if active is None:
                    db.execute(
                        """INSERT INTO shun_state
                           (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at,occurrence_id)
                           VALUES (?, ?, ?, 1, ?, ?, ?,?)""",
                        (device_id, packed_ip, interface, timestamp, timestamp, timestamp,str(uuid4())),
                    )
                    self._insert_event(
                        db, "SHUN_DETECTED", device_id, ip, interface, None, None, (), None, {}, timestamp
                    )
                elif not active:
                    db.execute(
                        """UPDATE shun_state SET active = 1, last_seen_at = ?, last_changed_at = ?,occurrence_id=?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, timestamp,str(uuid4()), device_id, packed_ip, interface),
                    )
                    self._insert_event(
                        db, "SHUN_REAPPEARED", device_id, ip, interface, None, None, (), None, {}, timestamp
                    )
                else:
                    db.execute(
                        """UPDATE shun_state SET last_seen_at = ?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, device_id, packed_ip, interface),
                    )

            for (packed_ip, interface), active in existing.items():
                if active and (packed_ip, interface) not in observed:
                    db.execute(
                        """UPDATE shun_state SET active = 0, last_changed_at = ?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, device_id, packed_ip, interface),
                    )
                    self._insert_event(
                        db,
                        "SHUN_DISAPPEARED",
                        device_id,
                        IPv4Address(packed_ip),
                        interface,
                        None,
                        None,
                        (),
                        None,
                        {"observed_during_reconciliation": True},
                        timestamp,
                    )

    def complete_removal(
        self, device_id: int, ip: IPv4Address, actor_subject: str, actor_display_name: str,
        actor_roles: tuple[str, ...], request_id: str,
    ) -> bool:
        """Persist only a verified device-scoped removal result."""
        timestamp = now()
        with self._connection() as db:
            rows = db.execute(
                "SELECT interface FROM shun_state WHERE device_id = ? AND ip = ? AND active = 1",
                (device_id, ip.packed),
            ).fetchall()
            if not rows:
                self._insert_event(
                    db, "SHUN_REMOVE_NOOP", device_id, ip, None, actor_subject,
                    actor_display_name, actor_roles, request_id, {}, timestamp,
                )
                return False
            db.execute(
                """UPDATE shun_state SET active = 0, last_changed_at = ?
                   WHERE device_id = ? AND ip = ? AND active = 1""",
                (timestamp, device_id, ip.packed),
            )
            for row in rows:
                self._insert_event(
                    db, "SHUN_REMOVED_BY_UI", device_id, ip, row["interface"], actor_subject,
                    actor_display_name, actor_roles, request_id, {"verified": True}, timestamp,
                )
            return True

    def create_trusted_auto_removal_requested(
        self, device_id: int, ip: IPv4Address, request_id: str
    ) -> None:
        with self._connection() as db:
            self._insert_event(
                db,
                "SHUN_TRUSTED_AUTO_REMOVE_REQUESTED",
                device_id,
                ip,
                None,
                "system:trusted-ip-policy",
                "Trusted IP policy",
                (),
                request_id,
                {"policy": "exact_ipv4_allowlist"},
                now(),
            )

    def complete_trusted_auto_removal(
        self, device_id: int, ip: IPv4Address, request_id: str
    ) -> bool:
        """Persist a verified policy-driven removal without attributing it to a user."""
        timestamp = now()
        with self._connection() as db:
            rows = db.execute(
                "SELECT interface FROM shun_state WHERE device_id = ? AND ip = ? AND active = 1",
                (device_id, ip.packed),
            ).fetchall()
            if not rows:
                self._insert_event(
                    db,
                    "SHUN_TRUSTED_AUTO_REMOVE_NOOP",
                    device_id,
                    ip,
                    None,
                    "system:trusted-ip-policy",
                    "Trusted IP policy",
                    (),
                    request_id,
                    {"policy": "exact_ipv4_allowlist"},
                    timestamp,
                )
                return False
            db.execute(
                """UPDATE shun_state SET active = 0, last_changed_at = ?
                   WHERE device_id = ? AND ip = ? AND active = 1""",
                (timestamp, device_id, ip.packed),
            )
            for row in rows:
                self._insert_event(
                    db,
                    "SHUN_TRUSTED_AUTO_REMOVED",
                    device_id,
                    ip,
                    row["interface"],
                    "system:trusted-ip-policy",
                    "Trusted IP policy",
                    (),
                    request_id,
                    {"policy": "exact_ipv4_allowlist", "verified": True},
                    timestamp,
                )
            return True

    def record_trusted_auto_removal_failed(
        self, device_id: int, ip: IPv4Address, request_id: str, reason: str
    ) -> None:
        with self._connection() as db:
            self._insert_event(
                db,
                "SHUN_TRUSTED_AUTO_REMOVE_FAILED",
                device_id,
                ip,
                None,
                "system:trusted-ip-policy",
                "Trusted IP policy",
                (),
                request_id,
                {"policy": "exact_ipv4_allowlist", "reason": reason[:256]},
                now(),
            )

    def list_trusted_auto_removal_status(
        self, trusted_ips: Iterable[IPv4Address]
    ) -> list[dict[str, str | None]]:
        """Return configured trusted addresses with their latest verified policy removal."""
        result: list[dict[str, str | None]] = []
        with self._connection() as db:
            for ip in sorted(set(trusted_ips), key=int):
                row = db.execute(
                    """SELECT MAX(timestamp) AS last_auto_removed_at
                       FROM shun_events
                       WHERE event_type = ? AND ip = ?""",
                    ("SHUN_TRUSTED_AUTO_REMOVED", ip.packed),
                ).fetchone()
                result.append(
                    {
                        "ip": str(ip),
                        "last_auto_removed_at": row["last_auto_removed_at"],
                    }
                )
        return result

    def prune_expired_history(
        self, retention_days: int, reference_time: datetime | None = None
    ) -> dict[str, int | str]:
        """Purge expired audit rows and inactive state under the configured lifecycle policy."""
        if retention_days < 1:
            raise ValueError("history retention must be at least one day")
        reference_time = reference_time or datetime.now(UTC)
        if reference_time.tzinfo is None:
            raise ValueError("history retention reference time must include a timezone")
        cutoff = (reference_time.astimezone(UTC) - timedelta(days=retention_days)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        with self._connection() as db:
            from .bulk_ordered_waits import present as ordered_present
            from .bulk_ordered_waits import validate_held_predecessors

            db.execute('BEGIN IMMEDIATE')
            preserve = ''
            if ordered_present(db):
                validate_held_predecessors(db)
                preserve = ''' AND NOT EXISTS (SELECT 1 FROM managed_bulk_ordered_members m
                    WHERE m.claim_event_id=shun_events.id OR (shun_events.event_type='SHUN_OPERATION_DEFERRED'
                        AND shun_events.request_id=json_extract(m.predecessor_json,'$.request_id')))'''
            origins_deleted = db.execute("""DELETE FROM shun_import_origins WHERE verified_at<?
                AND NOT EXISTS (SELECT 1 FROM shun_state s WHERE s.occurrence_id=shun_import_origins.occurrence_id
                  AND s.active=1)""", (cutoff,)).rowcount
            events_deleted = db.execute(
                "DELETE FROM shun_events WHERE timestamp < ?" + preserve, (cutoff,)
            ).rowcount
            inactive_state_deleted = db.execute(
                """DELETE FROM shun_state
                   WHERE active = 0 AND last_changed_at < ?""",
                (cutoff,),
            ).rowcount
            if events_deleted or inactive_state_deleted or origins_deleted:
                self._insert_event(
                    db,
                    "HISTORY_RETENTION_PURGED",
                    None,
                    None,
                    None,
                    "system:retention-policy",
                    "History retention policy",
                    (),
                    None,
                    {
                        "cutoff": cutoff,
                        "events_deleted": events_deleted,
                        "inactive_state_deleted": inactive_state_deleted,
                        "retention_days": retention_days,
                        "import_origins_deleted": origins_deleted,
                    },
                )
        return {
            "cutoff": cutoff,
            "events_deleted": events_deleted,
            "inactive_state_deleted": inactive_state_deleted,
            "import_origins_deleted": origins_deleted,
        }

    def create_removal_requested(
        self, device_id: int, ip: IPv4Address, actor_subject: str, actor_display_name: str,
        actor_roles: tuple[str, ...], request_id: str,
    ) -> None:
        with self._connection() as db:
            self._insert_event(
                db, "SHUN_REMOVE_REQUESTED", device_id, ip, None, actor_subject,
                actor_display_name, actor_roles, request_id, {}, now(),
            )

    @staticmethod
    def _insert_event(
        db: sqlite3.Connection, event_type: str, device_id: int | None, ip: IPv4Address | None,
        interface: str | None, actor_subject: str | None, actor_display_name: str | None,
        actor_roles: tuple[str, ...], request_id: str | None, details: dict, timestamp: str | None = None,
    ) -> None:
        db.execute(
            """INSERT INTO shun_events
               (id, timestamp, event_type, device_id, ip, interface, actor_subject,
                actor_display_name, actor_roles_json, request_id, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), timestamp or now(), event_type, device_id, ip.packed if ip else None,
             interface, actor_subject, actor_display_name, json.dumps(actor_roles), request_id,
             json.dumps(details, sort_keys=True)),
        )


def _safe_interface(interface: str) -> bool:
    return (
        1 <= len(interface) <= 64
        and interface[0].isalpha()
        and interface.isascii()
        and all(character.isalnum() or character in "/._-" for character in interface)
    )


def _ip_prefix(value: str) -> str:
    """Validate a dotted IPv4 prefix without accepting a route or hostname."""
    query = value.strip()
    if not 1 <= len(query) <= 15 or any(character not in "0123456789." for character in query):
        raise ValueError("IP search must be an IPv4 address or dotted IPv4 prefix")
    trailing_dot = query.endswith(".")
    parts = query[:-1].split(".") if trailing_dot else query.split(".")
    if not parts or len(parts) > 4 or any(not part or int(part) > 255 for part in parts):
        raise ValueError("IP search must be an IPv4 address or dotted IPv4 prefix")
    return query
