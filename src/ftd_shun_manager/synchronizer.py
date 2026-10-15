"""Rate-limited background reconciliation of typed FTD shun snapshots."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from time import monotonic
from uuid import uuid4

from .agent_client import AgentClient, AgentUnavailable
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
        trusted_auto_remove_ips: frozenset[IPv4Address] = frozenset(),
        history_retention_days: int = 366,
    ) -> None:
        self.store = store
        self.agent = agent
        self.poll_interval_seconds = poll_interval_seconds
        self.interactive_min_interval_seconds = interactive_min_interval_seconds
        self.trusted_auto_remove_ips = trusted_auto_remove_ips
        self.history_retention_days = history_retention_days
        self._activity = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_sweep_at: float | None = None
        self._interactive_state = "idle"
        self._last_successful_refresh: str | None = None
        self._last_attempt: str | None = None
        self._last_error: str | None = None
        self._next_baseline_refresh: str | None = None
        self._next_baseline_at: float | None = None
        self._next_interactive_refresh: str | None = None
        self._devices: dict[int, dict[str, str | None]] = {}
        self._last_retention_attempt_at: float | None = None
        self._last_retention_purge: str | None = None
        self._last_retention_error: str | None = None

    async def start(self) -> None:
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

    def note_activity(self) -> None:
        """Queue at most one asynchronous refresh hint from a browser-facing request."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue_activity)

    def status(self) -> dict[str, object]:
        return {
            "last_successful_refresh": self._last_successful_refresh,
            "last_attempt": self._last_attempt,
            "last_error": self._last_error,
            "next_baseline_refresh": self._next_baseline_refresh,
            "next_interactive_refresh": self._next_interactive_refresh,
            "baseline_interval_seconds": self.poll_interval_seconds,
            "interactive_min_interval_seconds": self.interactive_min_interval_seconds,
            "interactive_refresh_state": self._interactive_state,
            "trusted_auto_remove_ip_count": len(self.trusted_auto_remove_ips),
            "history_retention_days": self.history_retention_days,
            "last_retention_purge": self._last_retention_purge,
            "history_retention_error": self._last_retention_error,
            "devices": self._devices,
        }

    def _queue_activity(self) -> None:
        now = monotonic()
        if self._next_baseline_at is not None:
            until_baseline = self._next_baseline_at - now
            if 0 <= until_baseline <= self.interactive_min_interval_seconds:
                self._interactive_state = "baseline_pending"
                return
        if self._last_sweep_at is not None and (
            now - self._last_sweep_at < self.interactive_min_interval_seconds
        ):
            self._interactive_state = "rate_limited"
            return
        self._interactive_state = "queued"
        if self._next_interactive_refresh is None:
            self._next_interactive_refresh = _timestamp_after(
                self.interactive_min_interval_seconds
            )
        self._activity.set()

    async def _run(self) -> None:
        next_baseline = monotonic()
        self._next_baseline_at = next_baseline
        while True:
            remaining = max(0.0, next_baseline - monotonic())
            try:
                await asyncio.wait_for(self._activity.wait(), timeout=remaining)
                self._activity.clear()
                interactive = next_baseline > monotonic()
            except TimeoutError:
                interactive = False

            if interactive and self._last_sweep_at is not None and (
                monotonic() - self._last_sweep_at < self.interactive_min_interval_seconds
            ):
                self._interactive_state = "rate_limited"
                continue
            self._interactive_state = "idle"
            # Expose a future baseline while the current bounded sweep is in
            # progress, preventing browser countdowns from repeatedly reloading
            # against the completed deadline.
            self._next_baseline_at = monotonic() + self.poll_interval_seconds
            self._next_baseline_refresh = _timestamp_after(self.poll_interval_seconds)
            await self._sweep()
            self._last_sweep_at = monotonic()
            next_baseline = monotonic() + self.poll_interval_seconds
            self._next_baseline_at = next_baseline
            self._next_baseline_refresh = _timestamp_after(self.poll_interval_seconds)
            self._next_interactive_refresh = _timestamp_after(self.interactive_min_interval_seconds)

    async def _sweep(self) -> None:
        await self._prune_expired_history_if_due()
        self._last_attempt = _timestamp()
        failures = 0
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            try:
                snapshot = await asyncio.to_thread(self.agent.list_shuns, device.id)
                self.store.reconcile_snapshot(
                    device.id, [(entry.ip, entry.interface) for entry in snapshot]
                )
            except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
                failures += 1
                reason = str(error)
                self._last_error = f"device {device.id}: {reason}"
                self._devices[device.id] = {
                    "last_successful_refresh": self._devices.get(device.id, {}).get(
                        "last_successful_refresh"
                    ),
                    "last_error": reason,
                }
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

            trusted_ips = sorted(
                {entry.ip for entry in snapshot if entry.ip in self.trusted_auto_remove_ips},
                key=int,
            )
            removal_error: str | None = None
            for trusted_ip in trusted_ips:
                request_id = str(uuid4())
                try:
                    self.store.create_trusted_auto_removal_requested(device.id, trusted_ip, request_id)
                    await asyncio.to_thread(self.agent.remove_shun, device.id, trusted_ip)
                    self.store.complete_trusted_auto_removal(device.id, trusted_ip, request_id)
                except (AgentUnavailable, OSError, ValueError, sqlite3.Error) as error:
                    removal_error = f"trusted-IP automatic removal failed: {error}"
                    failures += 1
                    try:
                        self.store.record_trusted_auto_removal_failed(
                            device.id, trusted_ip, request_id, str(error)
                        )
                    except sqlite3.Error as audit_error:
                        print(
                            json.dumps(
                                {
                                    "event": "synchronizer.trusted_auto_remove_audit_failed",
                                    "device_id": device.id,
                                    "ip": str(trusted_ip),
                                    "reason": str(audit_error),
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                    print(
                        json.dumps(
                            {
                                "event": "synchronizer.trusted_auto_remove_failed",
                                "device_id": device.id,
                                "ip": str(trusted_ip),
                                "reason": str(error),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
            self._devices[device.id] = {
                "last_successful_refresh": _timestamp(),
                "last_error": removal_error,
            }
            if removal_error:
                self._last_error = f"device {device.id}: {removal_error}"
        if failures == 0:
            self._last_successful_refresh = _timestamp()
            self._last_error = None

    async def _prune_expired_history_if_due(self) -> None:
        if self._last_retention_attempt_at is not None and (
            monotonic() - self._last_retention_attempt_at < 24 * 3600
        ):
            return
        self._last_retention_attempt_at = monotonic()
        try:
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
            print(
                json.dumps({"event": "synchronizer.history_retention_purged", **result}, sort_keys=True),
                flush=True,
            )
