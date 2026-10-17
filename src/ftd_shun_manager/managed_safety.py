"""Optional managed-policy safety reads. No initialization or authority grant."""

import sqlite3


class ManagedStateUnavailable(ValueError):
    pass


def managed_state(db) -> dict | None:
    """Distinguish absent policy from malformed/partial policy, fail closed."""
    expected = {
        "managed_shun_registry": {"id", "revision", "restoration_suspended"},
        "managed_shun_targets": {"device_id", "ip", "enabled", "intent_id", "generation"},
        "managed_shun_requests": {"id", "actor_subject", "payload_json", "result_json"},
    }
    try:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not names.intersection(expected):
            return None
        if not names.issuperset(expected):
            raise ValueError("Partial managed schema")
        for name, columns in expected.items():
            if not {r[1] for r in db.execute(f"PRAGMA table_info({name})")}.issuperset(columns):
                raise ValueError("Incomplete managed schema")
        row = db.execute("SELECT revision,restoration_suspended FROM managed_shun_registry WHERE id=1").fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0 or row[1] not in (0, 1):
            raise ValueError("Invalid managed metadata")
        if db.execute("SELECT COUNT(*) FROM managed_shun_targets").fetchone()[0] > 1000:
            raise ValueError("Unsupported managed capacity")
        if db.execute("""SELECT 1 FROM managed_shun_targets WHERE enabled IS NULL OR typeof(enabled)!='integer'
            OR enabled NOT IN (0,1) OR typeof(ip)!='blob' OR length(ip)!=4 LIMIT 1""").fetchone():
            raise ValueError("Invalid managed target")
        return {"revision": row[0], "restoration_suspended": bool(row[1])}
    except (sqlite3.DatabaseError, ValueError) as error:
        raise ManagedStateUnavailable("Managed policy is unavailable; review it before weakening protection or removing shuns.") from error


def require_ordinary_removal(db, targets, *, fleet: bool = False) -> None:
    """An observed-only removal must not bypass enabled desired policy."""
    if managed_state(db) is None:
        return
    for device_id, ip in targets:
        if db.execute("""SELECT 1 FROM managed_shun_targets WHERE ip=? AND enabled=1
            AND (? OR device_id=?) LIMIT 1""", (ip.packed, fleet, device_id)).fetchone():
            # Imported lazily to keep the shared metadata helper independent of
            # the queue's initialization and avoid a module import cycle.
            from .operation_queue import QueueConflict

            raise QueueConflict("Managed maintenance exists in this removal scope. Stop maintaining the relevant targets first; combined removal is unavailable. No work was queued.")
