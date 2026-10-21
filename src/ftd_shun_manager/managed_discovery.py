"""Bounded complete-snapshot discovery; no schema initialization or extra executor."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .managed_restoration import CompleteSnapshot, ManagedRestorations, present, read_scope
from .managed_safety import fleet_target_held, managed_state
from .operation_queue import QueueConflict, QueueFull, stamp
from .safety import mutations_suspended


@dataclass(frozen=True)
class RestorationContext:
    enabled: bool = False
    addition_device_ids: frozenset[int] = frozenset()


def targets(db, device_id=None):
    if managed_state(db) is None:
        return []
    return db.execute("""SELECT t.*,d.enabled AS device_enabled,
        EXISTS(SELECT 1 FROM protected_ips p WHERE p.ip=t.ip AND p.enabled=1) AS protected,
        EXISTS(SELECT 1 FROM shun_state s WHERE s.device_id=t.device_id AND s.ip=t.ip AND s.active=1) AS observed_present
        FROM managed_shun_targets t JOIN devices d ON d.id=t.device_id
        WHERE (? IS NULL OR t.device_id=?) ORDER BY t.device_id,t.ip LIMIT 1001""", (device_id, device_id)).fetchall()


def describe(db, rows, context, now, snapshot=None, *, scoped=False):
    """One read transaction; readiness without fresh evidence never means queued."""
    state = managed_state(db)
    available = present(db)
    cte, parameters = read_scope([(row["device_id"], row["ip"]) for row in rows]) if scoped else ("", [])
    selection = " JOIN selected s ON s.device_id=a.device_id AND s.ip=a.ip " if scoped else " "
    attempts = {}
    if available:
        attempts = {(r["device_id"], r["ip"]): dict(r) for r in db.execute(cte + """SELECT a.device_id,a.ip,
            MAX(requested_at) AS latest,MAX(completed_at) AS completed,
            SUM(requested_at>?) AS recent,MAX(state IN ('FAILED','UNVERIFIED')) AS attention
            FROM managed_restoration_attempts a""" + selection + " GROUP BY a.device_id,a.ip",
            [*parameters, stamp(now-timedelta(hours=1))])}
    selection = " JOIN selected s ON s.device_id=j.device_id AND s.ip=j.ip " if scoped else " "
    jobs = {(r["device_id"], r["ip"]): dict(r) for r in db.execute(cte + """SELECT j.device_id,j.ip,
        MAX(j.state IN ('QUEUED','RUNNING')) AS pending,MAX(j.state='UNVERIFIED') AS uncertain,
        MAX(CASE WHEN j.state IN ('VERIFIED','NOOP') THEN j.completed_at END) AS completed
        FROM operation_jobs j JOIN managed_shun_targets t ON t.device_id=j.device_id AND t.ip=j.ip
        """ + selection + " GROUP BY j.device_id,j.ip", parameters)} if state else {}
    paused = mutations_suspended(db)
    handoffs = db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_removal_handoffs'").fetchone() is not None
    views = {}
    for row in rows:
        key = row["device_id"], row["ip"]
        history, work = attempts.get(key, {}), jobs.get(key, {})
        ip = IPv4Address(row["ip"])
        reason, due = "awaiting_snapshot", None
        if not row["enabled"]:
            reason = "stopped"
        elif row["protected"]:
            reason = "protected"
        elif not row["device_enabled"]:
            reason = "device_disabled"
        elif history.get("attention") or work.get("uncertain"):
            reason = "needs_review"
        elif row["observed_present"] or (snapshot is not None and ip in snapshot.present_ips):
            reason = "present"
        elif not context.enabled:
            reason = "controller_disabled"
        elif row["device_id"] not in context.addition_device_ids:
            reason = "no_addition_profile"
        elif not available:
            reason = "not_initialized"
        elif state["restoration_suspended"]:
            reason = "suspended"
        elif paused:
            reason = "recovery_pause"
        elif work.get("pending"):
            reason = "pending_work"
        elif fleet_target_held(db, row["device_id"], ip, attention=True) or (handoffs and db.execute(
                "SELECT 1 FROM managed_removal_handoffs WHERE device_id=? AND ip=? AND state IN ('WAITING_ADD','ATTENTION')", key).fetchone()):
            reason = "cleanup_pending"
        elif history.get("latest") and now < datetime.fromisoformat(history["latest"]) + timedelta(seconds=300):
            reason, due = "backoff", stamp(datetime.fromisoformat(history["latest"]) + timedelta(seconds=300))
        elif history.get("recent", 0) >= 3:
            reason = "churn_limit"
        elif snapshot is not None:
            completed = max(history.get("completed") or "", work.get("completed") or "")
            if (stamp(snapshot.started_at) < row["updated_at"]
                    or (completed and stamp(snapshot.started_at) <= completed)):
                reason = "newer_snapshot_required"
            else:
                reason = "eligible"
        views[key] = {"restoration_hold": reason, "restoration_next_eligible_at": due,
                      "last_admitted_at": history.get("latest")}
    return views


class ManagedDiscovery:
    def __init__(self, store, queue, *, enabled=False, addition_device_ids=frozenset()):
        self.store, self.queue = store, queue
        self.context = RestorationContext(enabled, frozenset(addition_device_ids))
        self.source = ManagedRestorations(store, queue)
        self.begin_cycle()

    def begin_cycle(self):
        self.remaining, self.checked = 16, 0
        self.capacity = False
        self.devices = {}

    def status(self):
        counts = Counter()
        for device in self.devices.values():
            counts.update(device["counts"])
        return {"enabled": self.context.enabled, "admitted_this_cycle": 16-self.remaining,
                "admission_limit": 16, "checked_this_cycle": self.checked, "check_limit": 64,
                "counts": dict(counts), "devices": self.devices}

    def ordered_devices(self, devices):
        if not self.context.enabled:
            return devices
        with self.store._connection() as db:
            db.execute("BEGIN")
            if not present(db):
                return devices
            last = dict(db.execute("SELECT device_id,MAX(requested_at) FROM managed_restoration_attempts GROUP BY device_id"))
        return sorted(devices, key=lambda device: (last.get(device.id, ""), device.id))

    def discover(self, snapshot: CompleteSnapshot, owner):
        if not self.context.enabled:
            return 0
        current = self.queue._now()
        if (not isinstance(snapshot, CompleteSnapshot) or snapshot.complete is not True
                or snapshot.started_at.utcoffset() != timedelta(0) or snapshot.completed_at.utcoffset() != timedelta(0)
                or snapshot.started_at > snapshot.completed_at or snapshot.completed_at > current
                or current - snapshot.started_at > timedelta(seconds=120)):
            raise ValueError("Discovery requires fresh complete successful read evidence.")
        with self.store._connection() as db:
            db.execute("BEGIN")
            rows = targets(db, snapshot.device_id)
            views = describe(db, rows, self.context, self.queue._now(), snapshot)
        candidates = sorted(rows, key=lambda row: (views[(row["device_id"], row["ip"])]["last_admitted_at"] or "", row["ip"]))
        admitted = 0
        for row in candidates:
            view = views[(row["device_id"], row["ip"])]
            if view["restoration_hold"] != "eligible":
                continue
            if self.capacity:
                view["restoration_hold"] = "capacity"
                continue
            if not self.remaining or self.checked >= 64:
                view["restoration_hold"] = "cycle_budget"
                continue
            self.checked += 1
            try:
                receipt = self.source.admit_absence(snapshot, IPv4Address(row["ip"]), owner, enabled=True,
                                                     expected_intent_id=row["intent_id"])
            except QueueFull:
                view["restoration_hold"] = "capacity"
                self.capacity = True
            except QueueConflict:
                view["restoration_hold"] = "state_changed"
            else:
                view["restoration_hold"] = "pending_work"
                if not receipt["replayed"]:
                    admitted += 1
                    self.remaining -= 1
            with self.store._connection() as db:
                lease = db.execute("SELECT owner,lease_until FROM operation_executor WHERE id=1").fetchone()
                if lease["owner"] != owner or not lease["lease_until"] or lease["lease_until"] <= stamp(self.queue._now()):
                    raise QueueConflict("Discovery lost the shared executor lease.")
        self.devices[str(snapshot.device_id)] = {"snapshot_at": stamp(snapshot.completed_at),
                                                "counts": dict(Counter(view["restoration_hold"] for view in views.values()))}
        return admitted
