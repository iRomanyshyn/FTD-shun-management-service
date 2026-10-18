"""Rate-limited background reconciliation of typed FTD shun snapshots."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from time import monotonic
from uuid import uuid4

from .agent_client import AgentClient, AgentUnavailable
from .agent_protocol import MAX_CYCLE_REMOVALS as MAX_CYCLE_MUTATIONS
from .agent_protocol import AdditionResult
from .managed_fleet_waits import ManagedFleetWaits
from .managed_removals import ManagedRemovals
from .managed_shuns import ManagedShuns
from .operation_queue import QueueConflict, QueueFull
from .protected_policy import ProtectedPolicy
from .store import Store


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class Synchronizer:
    """One-process scheduler; browser traffic can only request a rate-limited hint."""

    def __init__(
        self,
        store: Store,
        agent: AgentClient,
        poll_interval_seconds: int,
        interactive_min_interval_seconds: int,
        history_retention_days: int = 366,
        enabled: bool = True,
        operation_timeout_seconds: int = 45,
        session_cycles_enabled: bool = False,
        import_execution_enabled: bool = False,
        addition_device_ids: frozenset[int] = frozenset(),
        managed_removal_worker_enabled: bool = False,
    ) -> None:
        if import_execution_enabled and not session_cycles_enabled:
            raise ValueError("import execution requires session cycles")
        self.store = store
        self.agent = agent
        self.poll_interval_seconds = poll_interval_seconds
        self.interactive_min_interval_seconds = interactive_min_interval_seconds
        self.policy = ProtectedPolicy(store)
        self.history_retention_days = history_retention_days
        self.enabled = enabled
        self.session_cycles_enabled = session_cycles_enabled
        self.import_execution_enabled = import_execution_enabled
        self.addition_device_ids = frozenset(addition_device_ids) if import_execution_enabled else frozenset()
        self._device_cycle: dict[str, object] = {}
        self._active_device_id: int | None = None
        self._priority_pending = False
        self._priority_used = False
        self.queue = self.policy.queue
        self.managed_removal_worker_enabled = managed_removal_worker_enabled
        self.managed_removals = ManagedRemovals(ManagedShuns(store), self.queue,
                                               worker_enabled=managed_removal_worker_enabled)
        self.managed_fleet_waits = ManagedFleetWaits(store, self.queue)
        self._managed_removal_error: str | None = None
        self._lease_seconds = operation_timeout_seconds + interactive_min_interval_seconds + 30
        self._cycle_cutoff: int | None = None
        self.instance_id = str(uuid4())
        self._status_revision = 0
        self._data_revision = 0
        self._cycle_revision = 0
        self._cycle_id = 0
        self._cycle_started_at: str | None = None
        self._cycle_completed_at: str | None = None
        self._cycle_outcome = "not_started"
        self._activity = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_sweep_at: float | None = None
        self._refresh_in_progress = False
        self._interactive_state = "idle"
        self._last_successful_refresh: str | None = None
        self._last_attempt: str | None = None
        self._last_error: str | None = None
        self._next_baseline_refresh: str | None = None
        self._next_baseline_at: float | None = None
        self._next_interactive_refresh: str | None = None
        self._devices: dict[int, dict[str, object]] = {}
        self._device_success_at: dict[int, float] = {}
        self._last_retention_attempt_at: float | None = None
        self._last_retention_purge: str | None = None
        self._last_retention_error: str | None = None

    async def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run(), name="ftd-shun-synchronizer")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._loop = None

    def note_activity(self) -> None:
        """Queue at most one asynchronous refresh hint from a browser-facing request."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue_activity)

    def request_activity(self) -> dict[str, object]:
        """Queue an activity hint from the owning event loop and return its real state."""
        self._queue_activity()
        return self.status()

    def status(self) -> dict[str, object]:
        devices = {}
        for device in self.store.list_devices():
            details = deepcopy(self._devices.get(device.id, {}))
            last_success_at = self._device_success_at.get(device.id)
            stale = last_success_at is None or (
                monotonic() - last_success_at >= self.poll_interval_seconds
            ) or bool(details.get("last_error"))
            state = details.get("state", "pending")
            if not self.enabled or not device.enabled:
                state = "disabled"
            elif state != "refreshing" and stale and last_success_at is not None:
                state = "error" if details.get("last_error") else "stale"
            devices[str(device.id)] = {
                "hostname": device.hostname,
                "last_attempt": None,
                "last_successful_refresh": None,
                "last_error": None,
                **details,
                "state": state,
                "stale": stale,
            }
        active_success = self._device_success_at.get(self._active_device_id)
        priority_available = bool(
            self.session_cycles_enabled and self._refresh_in_progress
            and self._active_device_id is not None and not self._priority_used
            and not self._priority_pending and active_success is not None
            and monotonic() - active_success >= self.interactive_min_interval_seconds
            and self._device_cycle.get("action") not in {"final_snapshot", "completed", "failed"}
        )
        return {
            "instance_id": self.instance_id,
            "status_revision": self._status_revision,
            "data_revision": self._data_revision,
            "cycle_revision": self._cycle_revision,
            "cycle_id": self._cycle_id,
            "cycle_started_at": self._cycle_started_at,
            "cycle_completed_at": self._cycle_completed_at,
            "cycle_outcome": self._cycle_outcome,
            "refresh_enabled": self.enabled,
            "server_time": datetime.now(UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "last_successful_refresh": self._last_successful_refresh,
            "last_attempt": self._last_attempt,
            "last_error": self._last_error,
            "refresh_in_progress": self._refresh_in_progress,
            "next_baseline_refresh": self._next_baseline_refresh,
            "next_interactive_refresh": self._next_interactive_refresh,
            "baseline_interval_seconds": self.poll_interval_seconds,
            "interactive_min_interval_seconds": self.interactive_min_interval_seconds,
            "interactive_refresh_state": self._interactive_state,
            "trusted_auto_remove_ip_count": len(self.policy.enabled_ips()),
            "policy_revision": self.policy.revision(),
            "history_retention_days": self.history_retention_days,
            "last_retention_purge": self._last_retention_purge,
            "history_retention_error": self._last_retention_error,
            "devices": devices,
            "queue": self.queue.status(addition_device_ids=self.addition_device_ids),
            "import_execution_enabled": self.import_execution_enabled,
            "managed_removal_worker_enabled": self.managed_removal_worker_enabled,
            "managed_removal_worker_error": self._managed_removal_error,
            "addition_device_count": len(self.addition_device_ids),
            "session_cycles_enabled": self.session_cycles_enabled,
            "device_cycle": deepcopy(self._device_cycle),
            "priority_refresh_available": priority_available,
        }

    def signal_work(self) -> None:
        self.note_state_change()
        if not self._refresh_in_progress:
            self._activity.set()

    def note_state_change(self) -> None:
        """Publish a local mutation committed by an API write."""
        self._data_revision += 1
        self._status_revision += 1

    def _set_interactive_state(self, state: str) -> None:
        if self._interactive_state != state:
            self._interactive_state = state
            self._status_revision += 1

    def _queue_activity(self) -> None:
        if not self.enabled:
            self._set_interactive_state("disabled")
            return
        if self._refresh_in_progress:
            if self.session_cycles_enabled and self._active_device_id is not None:
                last = self._device_success_at.get(self._active_device_id)
                if last is not None and monotonic() - last < self.interactive_min_interval_seconds:
                    self._set_interactive_state("snapshot_recent")
                elif not self._priority_used:
                    self._priority_pending = True
                    self._device_cycle["priority_state"] = "waiting_for_checkpoint"
                    self._set_interactive_state("checkpoint_pending")
                else:
                    self._device_cycle["priority_state"] = "joining_final_snapshot"
                    self._set_interactive_state("running")
                self._status_revision += 1
                return
            self._set_interactive_state("running")
            return
        if self._activity.is_set():
            return
        if self.queue.delay() > 0:
            self._next_interactive_refresh = _timestamp_after(int(self.queue.delay()) + 1)
            self._set_interactive_state("rate_limited")
            return
        now = monotonic()
        if self._next_baseline_at is not None:
            until_baseline = self._next_baseline_at - now
            if 0 <= until_baseline <= self.interactive_min_interval_seconds:
                self._set_interactive_state("baseline_pending")
                return
        if self._last_sweep_at is not None and (
            now - self._last_sweep_at < self.interactive_min_interval_seconds
        ):
            self._set_interactive_state("rate_limited")
            return
        self._set_interactive_state("queued")
        self._activity.set()

    async def _run(self) -> None:
        next_baseline = monotonic() + self.queue.delay()
        self._next_baseline_at = next_baseline
        self._next_baseline_refresh = _timestamp_after(int(self.queue.delay()) + 1)
        while True:
            self.queue.expire_requests()
            if self._has_pending():
                due = min(next_baseline, monotonic() + self.queue.delay())
            else:
                due = next_baseline
            local_delay = 0.0 if self._last_sweep_at is None else max(
                0.0, self.interactive_min_interval_seconds - (monotonic() - self._last_sweep_at)
            )
            remaining = max(0.0, due - monotonic(), self.queue.delay(), local_delay)
            try:
                await asyncio.wait_for(self._activity.wait(), timeout=remaining)
                self._activity.clear()
                interactive = next_baseline > monotonic()
            except TimeoutError:
                interactive = False

            if self.queue.delay() > 0:
                continue

            if interactive and self._last_sweep_at is not None and (
                monotonic() - self._last_sweep_at < self.interactive_min_interval_seconds
            ):
                self._set_interactive_state("rate_limited")
                continue
            await self._sweep()
            next_baseline = self._next_baseline_at or monotonic()

    async def _sweep(self) -> None:
        if self._refresh_in_progress:
            return
        if not self.queue.claim_cycle(self.instance_id, self._lease_seconds):
            self._next_interactive_refresh = _timestamp_after(int(self.queue.delay()) + 1)
            return
        self.queue.expire_requests()
        self.queue.cancel_obsolete_policy()
        self._activity.clear()
        self._refresh_in_progress = True
        self._cycle_id += 1
        self._cycle_started_at = _timestamp()
        self._cycle_outcome = "running"
        self._next_baseline_refresh = None
        self._next_interactive_refresh = None
        self._set_interactive_state("running")
        self._status_revision += 1
        try:
            self._managed_removal_error = None
            if self.managed_removal_worker_enabled:
                try:
                    # Exactly once before the cutoff; never materialize removal
                    # against an in-memory pre-ADD snapshot later in this cycle.
                    self.managed_removals.advance_if_present(self.instance_id, limit=8)
                    self.managed_fleet_waits.advance_if_present(self.instance_id, limit=8)
                except (sqlite3.Error, ValueError):
                    self._managed_removal_error = "Managed cleanup handoff failed; mutations skipped for this cycle."
                    print(json.dumps({"event": "managed_shun.cleanup.worker_failed",
                                      "reason": self._managed_removal_error}), flush=True)
            self._cycle_cutoff = self.queue.cutoff()
            await self._collect()
        finally:
            self._active_device_id = None
            self._priority_pending = False
            self._refresh_in_progress = False
            self._last_sweep_at = monotonic()
            self._next_baseline_at = self._last_sweep_at + self.poll_interval_seconds
            self._next_baseline_refresh = _timestamp_after(self.poll_interval_seconds)
            self._next_interactive_refresh = _timestamp_after(self.interactive_min_interval_seconds)
            self._cycle_completed_at = _timestamp()
            if self._cycle_outcome == "running":
                self._cycle_outcome = "interrupted"
            self._cycle_revision += 1
            self._set_interactive_state("idle")
            self._status_revision += 1
            # Cancellation may leave a bounded RPC in a worker thread. Keep
            # its lease until expiry; the next owner reconciles, never replays.
            if self._cycle_outcome != "interrupted":
                self.queue.finish_cycle(self.instance_id, self.interactive_min_interval_seconds)

    async def _agent_call(self, function, *args):
        self.queue.renew(self.instance_id, self._lease_seconds)
        return await asyncio.to_thread(function, *args)

    def _has_pending(self, device_id: int | None = None) -> bool:
        if self.queue.has_pending(device_id, addition_device_ids=self.addition_device_ids):
            return True
        if self.managed_removal_worker_enabled and device_id is None:
            try:
                return self.managed_removals.has_waiting() or self.managed_fleet_waits.has_waiting()
            except (sqlite3.Error, ValueError):
                # A normal baseline cycle will surface the error; never spin.
                return False
        return False

    async def _collect(self) -> None:
        await self._prune_expired_history_if_due()
        self._last_attempt = _timestamp()
        failures = 0
        successful_devices = 0
        self._last_error = None
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            self._devices[device.id] = {
                **self._devices.get(device.id, {}),
                "state": "refreshing",
                "last_attempt": _timestamp(),
            }
            self._status_revision += 1
            cycle = None
            try:
                if self.session_cycles_enabled:
                    self._active_device_id = device.id
                    self._priority_pending = self._priority_used = False
                    self._device_cycle = {"device_id": device.id, "action": "opening_session",
                                          "completed": 0, "limit": MAX_CYCLE_MUTATIONS,
                                          "priority_state": "none", "budget_deferred": False}
                    cycle = await self._agent_call(self.agent.open_cycle, device.id)
                    if device.id in self.addition_device_ids and getattr(cycle, "version", None) != 3:
                        raise AgentUnavailable("addition-capable device requires exact cycle version 3; no fallback")
                    snapshot = cycle.initial_snapshot
                else:
                    snapshot = await self._agent_call(self.agent.list_shuns, device.id)
                self._publish_snapshot(device.id, snapshot)
            except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
                if cycle is not None:
                    cycle.abort()
                self._active_device_id = None
                if self.session_cycles_enabled:
                    self._device_cycle["action"] = "failed"
                failures += 1
                reason = str(error)
                self._last_error = f"device {device.id}: {reason}"
                self._devices[device.id] = {
                    **self._devices[device.id],
                    "state": "error",
                    "error_category": "refresh_failed",
                    "last_successful_refresh": self._devices.get(device.id, {}).get(
                        "last_successful_refresh"
                    ),
                    "last_error": reason,
                }
                self._status_revision += 1
                print(
                    json.dumps(
                        {
                            "event": "synchronizer.device_refresh_failed",
                            "device_id": device.id,
                            "reason": str(error),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                continue

            allowed = self.policy.enabled_ips()
            trusted_ips = sorted(
                {entry.ip for entry in snapshot if entry.ip in allowed},
                key=int,
            )
            if cycle is None:
                removal_error = await self._queued_removal(device.id, snapshot, trusted_ips)
            else:
                try:
                    removal_error = await self._session_mutations(device.id, cycle, snapshot)
                finally:
                    cycle.abort()
                    self._active_device_id = None
            if removal_error:
                failures += 1
            self._devices[device.id] = {
                **self._devices[device.id],
                "state": "error" if removal_error else "ready",
                "error_category": "device_cycle_failed" if removal_error else None,
                "last_successful_refresh": self._devices[device.id]["last_successful_refresh"],
                "last_error": removal_error,
            }
            successful_devices += 1
            self._status_revision += 1
            if removal_error:
                self._last_error = f"device {device.id}: {removal_error}"
        if failures == 0:
            self._last_successful_refresh = _timestamp()
            self._last_error = None
        self._cycle_outcome = (
            "success" if failures == 0 else "partial" if successful_devices else "failed"
        )

    def _publish_snapshot(self, device_id: int, snapshot) -> None:
        self.store.reconcile_snapshot(device_id, [(entry.ip, entry.interface) for entry in snapshot])
        self.queue.reconcile_unknown(device_id, {entry.ip for entry in snapshot})
        self._device_success_at[device_id] = monotonic()
        self._devices[device_id] = {**self._devices.get(device_id, {}),
                                    "last_successful_refresh": _timestamp(),
                                    "last_error": None, "error_category": None}
        if self.session_cycles_enabled:
            self._next_interactive_refresh = _timestamp_after(self.interactive_min_interval_seconds)
        self.note_state_change()

    def _admit_trusted(self, device_id: int, ips) -> None:
        if self._managed_removal_error or self.queue.mutations_suspended():
            return
        for ip in ips:
            if not self.queue.has_target(device_id, ip):
                try:
                    self.queue.enqueue(str(uuid4()), [(device_id, ip)], "system:trusted-ip-policy",
                                       "Trusted IP policy", (), source="trusted_policy")
                except (QueueFull, QueueConflict):
                    break

    async def _session_mutations(self, device_id: int, cycle, snapshot) -> str | None:
        try:
            allowed = self.policy.enabled_ips()
            self._admit_trusted(device_id, sorted({entry.ip for entry in snapshot
                               if entry.ip in allowed}, key=int))
            for _ in range(0 if self._managed_removal_error else MAX_CYCLE_MUTATIONS):
                if self._priority_pending and not self._priority_used:
                    self._priority_pending = False
                    last = self._device_success_at.get(device_id)
                    if last is None or monotonic() - last >= self.interactive_min_interval_seconds:
                        self._priority_used = True
                        self._device_cycle.update(action="priority_snapshot", priority_state="reading")
                        self._status_revision += 1
                        snapshot = await self._agent_call(cycle.snapshot)
                        if snapshot is None:
                            self._device_cycle.update(priority_state="joining_final_snapshot",
                                                      budget_deferred=self._has_pending(device_id))
                            print(json.dumps({"event": "queue.priority_refresh.deferred",
                                              "device_id": device_id, "joining_final_snapshot": True}), flush=True)
                            break
                        self._publish_snapshot(device_id, snapshot)
                        allowed = self.policy.enabled_ips()
                        self._admit_trusted(device_id, sorted({entry.ip for entry in snapshot
                                           if entry.ip in allowed}, key=int))
                    self._device_cycle["priority_state"] = "satisfied"
                    self._set_interactive_state("running")
                cutoff = self._cycle_cutoff if self._cycle_cutoff is not None else self.queue.cutoff()
                job = self.queue.claim_next_mutation(device_id, self.instance_id, cutoff,
                                                    additions_enabled=device_id in self.addition_device_ids)
                if job is None:
                    break
                target = IPv4Address(job["ip"])
                if job["action"] == "ADD":
                    self._device_cycle.update(action="add_and_verify", ip=str(target))
                    self._status_revision += 1
                    if not await self._session_addition(device_id, cycle, job, target):
                        self._device_cycle["budget_deferred"] = True
                        break
                    self._device_cycle["completed"] += 1
                    continue
                self._device_cycle.update(action="remove_and_verify", ip=str(target))
                self._status_revision += 1
                if not any(entry.ip == target for entry in snapshot):
                    result = False
                else:
                    try:
                        result = await self._agent_call(cycle.remove_shun, target)
                    except (AgentUnavailable, OSError, ValueError) as error:
                        self.queue.finish_removal(job["id"], self.instance_id, "UNVERIFIED", str(error))
                        self.note_state_change()
                        print(json.dumps({"event": "queue.removal.unverified", "device_id": device_id,
                                          "ip": str(target), "operation_id": job["id"], "reason": str(error)}), flush=True)
                        raise
                if result is None:
                    self.queue.defer_removal(job["id"], self.instance_id)
                    self._device_cycle["budget_deferred"] = True
                    self.note_state_change()
                    break
                self.queue.finish_removal(job["id"], self.instance_id, "VERIFIED" if result else "NOOP")
                self.note_state_change()
                self._device_cycle["completed"] += 1
                print(json.dumps({"event": "queue.removal.completed", "device_id": device_id,
                                  "ip": str(target), "operation_id": job["id"],
                                  "result": "VERIFIED" if result else "NOOP"}), flush=True)
            self._device_cycle.update(action="final_snapshot", ip=None)
            if self._device_cycle["completed"] >= MAX_CYCLE_MUTATIONS and self._has_pending(device_id):
                self._device_cycle["budget_deferred"] = True
            self._status_revision += 1
            snapshot = await self._agent_call(cycle.finish)
            self._publish_snapshot(device_id, snapshot)
            self._priority_pending = False
            self._device_cycle.update(action="completed", priority_state="satisfied")
            return self._managed_removal_error
        except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
            self._device_cycle["action"] = "failed"
            print(json.dumps({"event": "queue.cycle.failed", "device_id": device_id,
                              "reason": str(error)}), flush=True)
            return f"device cycle failed: {error}"

    async def _session_addition(self, device_id: int, cycle, job: dict, target: IPv4Address) -> bool:
        try:
            result = await self._agent_call(cycle.add_shun, target)
            if result is None:
                self.queue.defer_addition(job["id"], self.instance_id)
                self.note_state_change()
                return False
            if not isinstance(result, AdditionResult):
                raise AgentUnavailable("agent returned an invalid typed addition result")
            state = self.queue.finish_addition(job["id"], self.instance_id, result)
        except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
            # Even malformed/unavailable results after a possible send must not
            # be inferred from a later snapshot or automatically replayed.
            self.queue.finish_addition(job["id"], self.instance_id, "UNVERIFIED", reason=str(error))
            self.note_state_change()
            print(json.dumps({"event": "queue.addition.unverified", "device_id": device_id,
                              "ip": str(target), "operation_id": job["id"], "reason": str(error)}), flush=True)
            raise
        self.note_state_change()
        if state == "UNVERIFIED":
            raise AgentUnavailable("verified ADD conflicts with local occurrence; attribution refused")
        return True

    async def _queued_removal(self, device_id: int, snapshot, trusted_ips) -> str | None:
        if self._managed_removal_error:
            return self._managed_removal_error
        try:
            # Policy discovery may join this cycle; user mutations admitted
            # after its cutoff wait for the next cycle.
            self._admit_trusted(device_id, trusted_ips)
            cutoff = self._cycle_cutoff if self._cycle_cutoff is not None else self.queue.cutoff()
            job = self.queue.claim_removal(device_id, self.instance_id, cutoff)
            if job is None:
                return None
            target = IPv4Address(job["ip"])
            present = any(entry.ip == target for entry in snapshot)
            if not present:
                self.queue.finish_removal(job["id"], self.instance_id, "NOOP")
            else:
                try:
                    await self._agent_call(self.agent.remove_shun, device_id, target)
                except (AgentUnavailable, OSError, ValueError) as error:
                    self.queue.finish_removal(job["id"], self.instance_id, "UNVERIFIED", str(error))
                    self.note_state_change()
                    print(json.dumps({"event": "queue.removal.unverified", "device_id": device_id,
                                      "ip": str(target), "operation_id": job["id"], "reason": str(error)}), flush=True)
                    return f"removal outcome is unverified: {error}"
                self.queue.finish_removal(job["id"], self.instance_id, "VERIFIED")
            self.note_state_change()
            print(json.dumps({"event": "queue.removal.completed", "device_id": device_id,
                              "ip": str(target), "operation_id": job["id"],
                              "result": "VERIFIED" if present else "NOOP"}), flush=True)
        except (QueueConflict, ValueError, sqlite3.Error) as error:
            return f"operation queue failed: {error}"
        return None

    async def _prune_expired_history_if_due(self) -> None:
        if self._last_retention_attempt_at is not None and (
            monotonic() - self._last_retention_attempt_at < 24 * 3600
        ):
            return
        self._last_retention_attempt_at = monotonic()
        try:
            await asyncio.to_thread(self.queue.prune_completed, self.history_retention_days)
            result = await asyncio.to_thread(
                self.store.prune_expired_history, self.history_retention_days
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            self._last_retention_error = str(error)
            print(
                json.dumps(
                    {"event": "synchronizer.history_retention_failed", "reason": str(error)},
                    sort_keys=True,
                ),
                flush=True,
            )
            return
        self._last_retention_purge = _timestamp()
        self._last_retention_error = None
        if result["events_deleted"] or result["inactive_state_deleted"]:
            self.note_state_change()
            print(
                json.dumps({"event": "synchronizer.history_retention_purged", **result}, sort_keys=True),
                flush=True,
            )
