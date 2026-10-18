"""Optional managed-policy safety reads. No initialization or authority grant."""

import json
import sqlite3


class ManagedStateUnavailable(ValueError):
    pass


def fleet_waits_present(db) -> bool:
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_fleet_waits'").fetchone() is not None
    if present and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_fleet_removals'").fetchone():
        raise ManagedStateUnavailable("Fleet cleanup reservation is missing its authority ledger.")
    if present and db.execute("""SELECT 1 FROM managed_fleet_waits w LEFT JOIN managed_fleet_removals r ON r.id=w.id
            WHERE r.id IS NULL LIMIT 1""").fetchone():
        raise ManagedStateUnavailable("Fleet cleanup reservation is missing its root authority.")
    return present


def fleet_target_held(db, device_id, ip, *, attention: bool = False) -> bool:
    if not fleet_waits_present(db):
        return False
    return db.execute("""SELECT 1 FROM managed_fleet_waits w JOIN managed_fleet_removals r ON r.id=w.id
        WHERE (w.state='WAITING_ADD' OR (? AND w.state='ATTENTION'))
        AND json_extract(r.payload_json,'$.ip')=? AND EXISTS (
            SELECT 1 FROM json_each(r.payload_json,'$.targets') t
            WHERE json_extract(t.value,'$.device_id')=?) LIMIT 1""", (attention, str(ip), device_id)).fetchone() is not None


def fleet_key_reserved(db, key: str) -> bool:
    """Optional immutable fleet authority survives ordinary queue retention."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_fleet_removals'").fetchone():
        return False
    return db.execute("SELECT 1 FROM managed_fleet_removals WHERE id=? OR retirement_request_id=?",
                      (key, key)).fetchone() is not None


def require_fleet_queue_key(db, key, targets, subject, source, scope) -> None:
    if not fleet_key_reserved(db, key):
        return
    row = db.execute("SELECT * FROM managed_fleet_removals WHERE id=?", (key,)).fetchone()
    promoting = (row is not None and fleet_waits_present(db) and db.execute(
        "SELECT 1 FROM managed_fleet_waits WHERE id=? AND state='ADMITTING'", (key,),
    ).fetchone() is not None)
    if (row is not None and (row["phase"] == "ADMITTING" or promoting) and row["actor_subject"] == subject
            and source == "manual" and scope == "managed_fleet_removal"):
        intent = json.loads(row["payload_json"])
        expected = [(entry["device_id"], intent["ip"]) for entry in intent["targets"]]
        if [(device, str(ip)) for device, ip in targets] == expected:
            return
    from .operation_queue import QueueConflict

    raise QueueConflict("Managed-fleet key is reserved for its exact original cleanup.")


def managed_state(db) -> dict | None:
    """Distinguish absent policy from malformed/partial policy, fail closed."""
    expected = {
        "managed_shun_registry": {"id", "revision", "restoration_suspended"},
        "managed_shun_targets": {"device_id", "ip", "enabled", "intent_id", "generation"},
        "managed_shun_requests": {"id", "actor_subject", "payload_json", "result_json"},
    }
    try:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "managed_fleet_waits" in names and "managed_fleet_removals" not in names:
            raise ValueError("Orphan fleet cleanup reservations")
        if not names.intersection(expected) and not names.intersection({"managed_fleet_removals", "managed_fleet_waits"}):
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
