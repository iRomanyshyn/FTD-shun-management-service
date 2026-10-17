"""Observational fleet scope and transactional comparison, never admission."""

import hmac
import json
from ipaddress import IPv4Address

from .managed_intent import canonical_managed_fleet_scope
from .managed_safety import managed_state
from .managed_shuns import ManagedConflict


class ManagedRemovalScopes:
    def __init__(self, store):
        self.store = store

    def snapshot(self, ip: IPv4Address) -> dict:
        with self.store._connection() as db:
            db.execute("BEGIN")
            return self.read(db, ip)

    @staticmethod
    def read(db, ip: IPv4Address) -> dict:
        """Read the entire union in the caller's consistent transaction."""
        if not db.in_transaction:
            raise ValueError("Fleet scope requires a caller-owned transaction.")
        if not isinstance(ip, IPv4Address):
            raise TypeError("An exact IPv4 address is required.")
        state = managed_state(db)
        managed = {row["device_id"]: dict(row) for row in db.execute(
            "SELECT device_id,intent_id,generation,enabled FROM managed_shun_targets WHERE ip=?", (ip.packed,),
        )} if state is not None else {}
        observed = {row[0] for row in db.execute(
            "SELECT DISTINCT device_id FROM shun_state WHERE ip=? AND active=1", (ip.packed,),
        )}
        targets = observed | {device for device, row in managed.items() if row["enabled"]}
        if not targets or len(targets) > 1000:
            raise ManagedConflict("Fleet scope is empty or exceeds 1000 targets; nothing was prepared.")
        devices = {row["id"]: dict(row) for row in db.execute(
            "SELECT id,hostname,enabled FROM devices WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(sorted(targets)),),
        )}
        if devices.keys() != targets or any(type(row["enabled"]) is not int or row["enabled"] not in (0, 1)
                                             for row in devices.values()):
            raise ValueError("Fleet device metadata is incomplete.")
        revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()
        if revision is None:
            raise ValueError("Protected policy is unavailable.")
        scope = {"ip": str(ip), "managed_initialized": state is not None,
                 "managed_revision": state["revision"] if state else 0, "protected_revision": revision[0],
                 "protected": db.execute("SELECT 1 FROM protected_ips WHERE ip=? AND enabled=1", (ip.packed,)).fetchone() is not None,
                 "targets": [{"device_id": device, "hostname": devices[device]["hostname"],
                              "device_enabled": bool(devices[device]["enabled"]), "observed_present": device in observed,
                              "maintenance_enabled": bool(managed.get(device, {}).get("enabled", 0)),
                              "intent_id": managed.get(device, {}).get("intent_id"),
                              "generation": managed.get(device, {}).get("generation")}
                             for device in sorted(targets)]}
        _, digest = canonical_managed_fleet_scope(scope)
        return {**scope, "scope_digest": digest, "execution_available": False, "read_only": True}

    @classmethod
    def require_current(cls, db, reviewed: dict) -> dict:
        """Composite writers must call within their write transaction.

        Comparison alone grants no authority, retires nothing and admits no job.
        Never call per-target admission in a loop and mistake this for atomicity.
        """
        fields = {key: value for key, value in reviewed.items()
                  if key not in {"scope_digest", "execution_available", "read_only"}}
        _, expected = canonical_managed_fleet_scope(fields)
        supplied = reviewed.get("scope_digest")
        if not isinstance(supplied, str) or not supplied.isascii() or not hmac.compare_digest(expected, supplied):
            raise ValueError("Invalid reviewed fleet scope binding.")
        current = cls.read(db, IPv4Address(fields["ip"]))
        if not hmac.compare_digest(current["scope_digest"], expected):
            raise ManagedConflict("Fleet scope changed. Inspect current state and prepare a new review.")
        return current
