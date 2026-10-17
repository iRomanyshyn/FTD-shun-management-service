"""Internal state and event API. It is intended to listen only on a Unix socket."""

import sqlite3
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from typing import Annotated, Literal
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .agent_client import (
    AgentClient,
    DisabledAgentClient,
    MockAgentClient,
    UnixAgentClient,
)
from .config import Settings
from .import_preview import MAX_DEVICES, MAX_ROWS, classify_targets
from .inventory import load_devices
from .managed_safety import ManagedStateUnavailable, require_ordinary_removal
from .managed_scope import ManagedRemovalScopes
from .managed_shuns import ManagedCapacity, ManagedConflict, ManagedShuns
from .operation_queue import QueueConflict, QueueFull
from .store import HistoryWindowExpired, Shun, Store
from .synchronizer import Synchronizer


class Actor(BaseModel):
    subject: str
    display_name: str
    roles: list[str]


class PolicyChange(BaseModel):
    actor: Actor
    revision: int = Field(ge=0)
    name: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=500)
    enabled: StrictBool = True
    confirm_ip: str = ""
    managed_revision: int | None = Field(default=None, strict=True, ge=0)
    confirm_maintenance_resume: StrictBool = False


class ManagedControlActor(Actor):
    model_config = ConfigDict(extra="forbid")


class ManagedRetirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    device_id: int = Field(strict=True, ge=1, le=65535)
    ip: IPv4Address
    managed_revision: int = Field(strict=True, ge=0)
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(default="", max_length=500)


class ImportPreviewRequest(BaseModel):
    ips: list[IPv4Address] = Field(max_length=MAX_ROWS)
    device_ids: list[Annotated[int, Field(ge=1, le=65535)]] = Field(min_length=1, max_length=MAX_DEVICES)


class ImportTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(strict=True, ge=1, le=65535)
    ip: IPv4Address


class ImportAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: Actor
    targets: list[ImportTarget] = Field(min_length=1, max_length=1000)
    policy_revision: int = Field(strict=True, ge=0)
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=500)


def _serialize(shun: Shun) -> dict[str, object]:
    return {
        "device_id": shun.device_id,
        "device_hostname": shun.device_hostname,
        "ip": str(shun.ip),
        "interface": shun.interface,
        "first_seen_at": shun.first_seen_at,
        "last_seen_at": shun.last_seen_at,
        "active_since_at": shun.active_since_at,
        "active": shun.active,
        "manual_imports": list(shun.manual_imports),
        "manual_import_count": shun.manual_import_count,
    }


def _agent(settings: Settings, *, addition_device_ids: frozenset[int] = frozenset()) -> AgentClient:
    if settings.agent_mode == "mock":
        return MockAgentClient()
    if settings.agent_mode == "socket":
        # Leave a small local-IPC margin after the agent's configured end-to-end
        # operation timeout. The API must never abandon a still-running removal first.
        return UnixAgentClient(settings.agent_socket, settings.agent_timeout_seconds + 5,
                               large_snapshots=settings.large_snapshots_enabled,
                               additions_enabled=settings.import_execution_enabled,
                               addition_device_ids=addition_device_ids)
    return DisabledAgentClient()


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    agent_client: AgentClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = store or Store(settings.database_path)
    store.initialize()
    managed = ManagedShuns(store)  # Optional read only; never initialize policy here.
    addition_device_ids = set()
    if settings.device_inventory_path:
        for device, host_key in load_devices(settings.device_inventory_path):
            store.upsert_device(device, host_key)
            if device.enabled and device.addition_profile is not None:
                addition_device_ids.add(device.id)
    addition_device_ids = frozenset(addition_device_ids)
    agent = agent_client or _agent(settings, addition_device_ids=addition_device_ids)
    synchronizer = Synchronizer(
        store,
        agent,
        settings.poll_interval_seconds,
        settings.interactive_refresh_min_interval_seconds,
        settings.history_retention_days,
        enabled=settings.agent_mode != "disabled",
        operation_timeout_seconds=settings.agent_timeout_seconds,
        session_cycles_enabled=settings.agent_cycles_enabled,
        import_execution_enabled=settings.import_execution_enabled,
        addition_device_ids=addition_device_ids,
        managed_removal_worker_enabled=settings.managed_removal_worker_enabled,
    )
    policy = synchronizer.policy
    managed_removals = synchronizer.managed_removals  # Optional schema; no startup initialization.
    policy.migrate_legacy_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.agent_mode != "disabled":
            await synchronizer.start()
        app.state.synchronizer = synchronizer
        try:
            yield
        finally:
            await synchronizer.stop()

    app = FastAPI(
        title="FTD Shun Internal API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.synchronizer = synchronizer

    @app.middleware("http")
    async def prevent_state_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/status")
    async def service_status() -> dict[str, object]:
        policy_state = policy.snapshot()
        try:
            managed_metadata = managed.metadata()
        except (sqlite3.DatabaseError, ManagedConflict, ManagedCapacity, ValueError, TypeError, KeyError):
            # A malformed optional registry must not stop ordinary fleet monitoring.
            managed_metadata = {"managed_policy_available": False, "managed_policy_initialized": None,
                                "managed_policy_revision": None}
        return {
            "status": "ready",
            "agent_mode": settings.agent_mode,
            "large_snapshots_enabled": settings.large_snapshots_enabled,
            "import_admission_enabled": settings.import_admission_enabled,
            **synchronizer.status(),
            **managed_metadata,
            "policy_revision": policy_state["revision"],
            "trusted_auto_remove_ips": [entry for entry in policy_state["entries"] if entry["enabled"]],
            "disabled_protected_ips": [{"ip": entry["ip"]} for entry in policy_state["entries"] if not entry["enabled"]],
        }

    @app.get("/api/v1/managed-shuns")
    def managed_shuns() -> dict:
        try:
            return managed.snapshot_if_present()
        except (sqlite3.DatabaseError, ManagedConflict, ManagedCapacity, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Managed shun registry is unavailable; no policy was changed.") from error

    @app.get("/api/v1/managed-removal-scope/{ip}")
    def managed_removal_scope(ip: IPv4Address) -> dict:
        try:
            return ManagedRemovalScopes(store).snapshot(ip)
        except ManagedConflict as error:
            raise HTTPException(409, str(error)) from error
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Fleet removal scope is unavailable; nothing was submitted.") from error

    @app.get("/api/v1/protected-ips")
    def protected_ips() -> dict:
        return policy.snapshot()

    @app.post("/api/v1/managed-shuns/retire")
    def retire_managed_shun(change: ManagedRetirementRequest, request: Request) -> dict:
        # Policy-only revocation: no generic action, queue delegation or SSH.
        key = request.headers.get("Idempotency-Key", "")
        try:
            result = managed.change(key, "RETIRE", [(change.device_id, change.ip)], change.managed_revision,
                                    0, change.confirmation_digest, change.actor.subject,
                                    change.actor.display_name, tuple(change.actor.roles), reason=change.reason)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except (ManagedConflict, ManagedCapacity) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, "Policy retirement was not confirmed. Retry the original review; do not create a new request.") from error
        if not result["replayed"]:
            synchronizer.note_state_change()  # Metadata only; never signal device work.
        return result

    @app.get("/api/v1/managed-removal-handoffs")
    def managed_removal_handoffs() -> dict:
        try:
            return managed_removals.snapshot_if_present()
        except (sqlite3.DatabaseError, ManagedConflict, ManagedCapacity, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Managed cleanup state is unavailable; no operation was submitted.") from error

    @app.post("/api/v1/managed-removal-handoffs/{request_id}/cancel")
    def cancel_managed_handoff(request_id: UUID, actor: ManagedControlActor) -> dict:
        try:
            changed = managed_removals.cancel_waiting(str(request_id), actor.subject, actor.display_name, tuple(actor.roles))
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, "Cleanup cancellation was not confirmed; inspect current state before retrying.") from error
        if changed:
            synchronizer.note_state_change()
        return {"status": "cancelled", "request_id": str(request_id), "changed": changed,
                "maintenance_reenabled": False, "add_cancelled": False}

    @app.post("/api/v1/protected-ips/{ip}/{action}")
    async def change_protected_ip(ip: IPv4Address, action: Literal["add", "edit", "delete"],
                                  change: PolicyChange) -> dict:
        # The private BFF supplies the authenticated subject. Policy management
        # is intentionally shared by every admitted user; keep real audit roles.
        if not change.actor.subject.strip():
            raise HTTPException(403, "authenticated user required")
        if action == "delete" and change.confirm_ip != str(ip):
            raise HTTPException(422, "confirmation must match the IP address")
        try:
            policy.change(action, ip, change.revision, change.actor.subject,
                          change.actor.display_name, tuple(change.actor.roles),
                          change.name, change.comment, change.enabled,
                          managed_revision=change.managed_revision,
                          confirm_maintenance_resume=change.confirm_maintenance_resume)
        except ManagedStateUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        synchronizer.note_state_change()
        return {"status": "saved", "policy": policy.snapshot()}

    @app.post("/api/v1/refresh-hint", status_code=status.HTTP_202_ACCEPTED)
    async def refresh_hint() -> dict[str, object]:
        refresh = synchronizer.request_activity()
        return {
            "status": str(refresh["interactive_refresh_state"]),
            "refresh": refresh,
        }

    @app.get("/api/v1/shuns")
    def list_shuns() -> list[dict[str, object]]:
        return [_serialize(shun) for shun in store.list_active_shuns()]

    @app.get("/api/v1/import-devices")
    def import_devices() -> list[dict]:
        return [{"id": device.id, "hostname": device.hostname, "enabled": device.enabled}
                for device in store.list_devices()]

    @app.post("/api/v1/import-preview")
    def import_preview(preview: ImportPreviewRequest) -> dict:
        try:
            return classify_targets(store, preview.ips, preview.device_ids)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/v1/shuns/{ip}")
    def shun_detail(ip: IPv4Address) -> list[dict[str, object]]:
        return [_serialize(shun) for shun in store.list_active_shuns(ip)]

    @app.get("/api/v1/history")
    def history(limit: int = 200) -> list[dict]:
        return store.list_events(limit=limit)

    @app.get("/api/v1/history-page")
    def history_page(page: Annotated[int, Query(ge=1, le=2**31 - 1)] = 1,
                     anchor: UUID | None = None) -> dict:
        try:
            return store.history_page(page, str(anchor) if anchor else None)
        except HistoryWindowExpired as error:
            raise HTTPException(410, str(error)) from error

    @app.get("/api/v1/history/{ip}")
    def history_for_ip(ip: IPv4Address, limit: int = 200) -> list[dict]:
        return store.list_events(ip=ip, limit=limit)

    @app.get("/api/v1/search")
    def search_ip_history(ip: str) -> list[dict[str, str | int | bool | None]]:
        try:
            results = store.search_ip_history(ip)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        protected_ips = {str(item) for item in policy.enabled_ips()}
        return [{**result, "protected": result["ip"] in protected_ips} for result in results]

    def require_operator(actor: Actor) -> None:
        if "Operator" not in actor.roles and "Administrator" not in actor.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator role required")

    def request_key(request: Request) -> str:
        value = request.headers.get("idempotency-key", request.headers.get("x-request-id"))
        if value is None:
            return str(uuid4())
        try:
            return str(UUID(value))
        except ValueError as error:
            raise HTTPException(422, "idempotency key must be a UUID") from error

    def enqueue_removal(request: Request, ip: IPv4Address, actor: Actor, device_id: int | None) -> dict:
        require_operator(actor)
        if settings.agent_mode == "disabled":
            raise HTTPException(503, "FTD agent is disabled; no removal was queued")
        key = request_key(request)
        scope = "all" if device_id is None else "device"
        try:
            replay = synchronizer.queue.replay(key, actor.subject, scope, ip, device_id)
            if replay:
                return replay
            with store._connection() as db:
                # Include missing maintained devices in fleet safety checks,
                # even when the observed-only target list would be empty.
                require_ordinary_removal(db, [(device_id or 0, ip)], fleet=device_id is None)
            targets = sorted({shun.device_id for shun in store.list_active_shuns(ip)}) if device_id is None else [device_id]
            if not targets:
                raise HTTPException(409, "no current matching devices; refresh the displayed state")
            result = synchronizer.queue.enqueue(
                key, [(target, ip) for target in targets], actor.subject,
                actor.display_name, tuple(actor.roles),
                ttl_seconds=min(900, settings.sensitive_action_max_age_seconds), scope=scope,
            )
        except ManagedStateUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        except QueueFull as error:
            raise HTTPException(429, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        synchronizer.signal_work()
        return result

    @app.post("/api/v1/imports", status_code=202)
    def admit_import(request: Request, batch: ImportAdmissionRequest) -> dict:
        require_operator(batch.actor)
        if not settings.import_admission_enabled or settings.agent_mode == "disabled":
            raise HTTPException(503, "Import admission is disabled; no targets were queued.")
        if not request.headers.get("idempotency-key"):
            raise HTTPException(422, "Import admission requires an explicit UUID idempotency key.")
        # Admission cannot execute a command. Only the leased worker may select
        # eligible ADD when its independent gate/device profile are configured.
        try:
            result = synchronizer.queue.enqueue(
                request_key(request), [(target.device_id, target.ip) for target in batch.targets],
                batch.actor.subject, batch.actor.display_name, tuple(batch.actor.roles),
                ttl_seconds=min(900, settings.sensitive_action_max_age_seconds),
                source="manual_import", scope="import", batch_label=batch.label, batch_reason=batch.reason,
                policy_revision=batch.policy_revision, confirmation_digest=batch.confirmation_digest,
            )
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        except QueueFull as error:
            raise HTTPException(429, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        execution_enabled = settings.import_execution_enabled and any(
            target.device_id in addition_device_ids for target in batch.targets
        )
        if execution_enabled and not result["replayed"]:
            synchronizer.signal_work()
        else:
            synchronizer.note_state_change()
        return {**result, "source": "manual_import", "action": "ADD",
                "execution_enabled": execution_enabled}

    @app.delete("/api/v1/devices/{device_id}/shuns/{ip}", status_code=202)
    async def remove_device_shun(device_id: int, ip: IPv4Address, request: Request, actor: Actor) -> dict:
        return enqueue_removal(request, ip, actor, device_id)

    @app.post("/api/v1/shuns/{ip}/remove-all", status_code=202)
    async def remove_all_shuns(ip: IPv4Address, request: Request, actor: Actor) -> dict:
        return enqueue_removal(request, ip, actor, None)

    @app.post("/api/v1/operations/{operation_id}/cancel")
    async def cancel_operation(operation_id: UUID, actor: Actor) -> dict:
        require_operator(actor)
        try:
            synchronizer.queue.cancel(str(operation_id), actor.subject, "Administrator" in actor.roles,
                                      actor.display_name, tuple(actor.roles))
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        synchronizer.note_state_change()
        return {"status": "cancelled", "operation_id": str(operation_id)}

    return app


def main() -> None:
    settings = Settings.from_environment()
    uvicorn.run(create_app(settings), uds=settings.api_socket, log_level="info")
