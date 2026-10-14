"""SQLite state and append-only audit event store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class Shun:
    device_id: int
    device_hostname: str
    ip: IPv4Address
    interface: str
    first_seen_at: str
    last_seen_at: str
    active: bool


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
                """
            )

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
                 s.first_seen_at, s.last_seen_at, s.active
          FROM shun_state AS s JOIN devices AS d ON d.id = s.device_id
          WHERE s.active = 1
        """
        parameters: tuple[bytes, ...] = ()
        if ip:
            query += " AND s.ip = ?"
            parameters = (ip.packed,)
        query += " ORDER BY s.ip, d.hostname, s.interface"
        with self._connection() as db:
            rows = db.execute(query, parameters).fetchall()
        return [
            Shun(
                row["device_id"], row["device_hostname"], IPv4Address(row["ip"]),
                row["interface"], row["first_seen_at"], row["last_seen_at"], bool(row["active"])
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
        return [
            {
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
            for row in rows
        ]

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
                       (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at)
                       VALUES (?, ?, ?, 1, ?, ?, ?)""",
                    (device_id, ip.packed, interface, timestamp, timestamp, timestamp),
                )
                event = "SHUN_DETECTED"
            else:
                event = "SHUN_REAPPEARED" if not previous["active"] else None
                if event:
                    db.execute(
                        """UPDATE shun_state SET active = 1, last_seen_at = ?, last_changed_at = ?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, timestamp, device_id, ip.packed, interface),
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
                           (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at)
                           VALUES (?, ?, ?, 1, ?, ?, ?)""",
                        (device_id, packed_ip, interface, timestamp, timestamp, timestamp),
                    )
                    self._insert_event(
                        db, "SHUN_DETECTED", device_id, ip, interface, None, None, (), None, {}, timestamp
                    )
                elif not active:
                    db.execute(
                        """UPDATE shun_state SET active = 1, last_seen_at = ?, last_changed_at = ?
                           WHERE device_id = ? AND ip = ? AND interface = ?""",
                        (timestamp, timestamp, device_id, packed_ip, interface),
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
