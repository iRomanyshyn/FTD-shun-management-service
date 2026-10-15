"""Internal state and event API. It is intended to listen only on a Unix socket."""

import asyncio
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from .agent_client import (
    AgentClient,
    AgentUnavailable,
    DisabledAgentClient,
    MockAgentClient,
    UnixAgentClient,
)
from .config import Settings
from .inventory import load_devices
from .store import Shun, Store
from .synchronizer import Synchronizer


class Actor(BaseModel):
    subject: str
    display_name: str
    roles: list[str]


def _serialize(shun: Shun) -> dict[str, str | int | bool]:
    return {
        "device_id": shun.device_id,
        "device_hostname": shun.device_hostname,
        "ip": str(shun.ip),
        "interface": shun.interface,
        "first_seen_at": shun.first_seen_at,
        "last_seen_at": shun.last_seen_at,
        "active": shun.active,
    }


def _agent(settings: Settings) -> AgentClient:
    if settings.agent_mode == "mock":
        return MockAgentClient()
    if settings.agent_mode == "socket":
        # Leave a small local-IPC margin after the agent's configured end-to-end
        # operation timeout. The API must never abandon a still-running removal first.
        return UnixAgentClient(settings.agent_socket, settings.agent_timeout_seconds + 5)
    return DisabledAgentClient()


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    agent_client: AgentClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = store or Store(settings.database_path)
    store.initialize()
    if settings.device_inventory_path:
        for device, host_key in load_devices(settings.device_inventory_path):
            store.upsert_device(device, host_key)
    agent = agent_client or _agent(settings)
    synchronizer = Synchronizer(
        store,
        agent,
        settings.poll_interval_seconds,
        settings.interactive_refresh_min_interval_seconds,
        settings.trusted_auto_remove_ips,
        settings.history_retention_days,
        enabled=settings.agent_mode != "disabled",
    )

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

    @app.middleware("http")
    async def prevent_state_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/status")
    async def service_status() -> dict[str, object]:
        return {
            "status": "ready",
            "agent_mode": settings.agent_mode,
            **synchronizer.status(),
            "trusted_auto_remove_ips": store.list_trusted_auto_removal_status(
                settings.trusted_auto_remove_ips
            ),
        }

    @app.post("/api/v1/refresh-hint", status_code=status.HTTP_202_ACCEPTED)
    async def refresh_hint() -> dict[str, object]:
        refresh = synchronizer.request_activity()
        return {
            "status": str(refresh["interactive_refresh_state"]),
            "refresh": refresh,
        }

    @app.get("/api/v1/shuns")
    def list_shuns() -> list[dict[str, str | int | bool]]:
        return [_serialize(shun) for shun in store.list_active_shuns()]

    @app.get("/api/v1/shuns/{ip}")
    def shun_detail(ip: IPv4Address) -> list[dict[str, str | int | bool]]:
        return [_serialize(shun) for shun in store.list_active_shuns(ip)]

    @app.get("/api/v1/history")
    def history(limit: int = 200) -> list[dict]:
        return store.list_events(limit=limit)

    @app.get("/api/v1/history/{ip}")
    def history_for_ip(ip: IPv4Address, limit: int = 200) -> list[dict]:
        return store.list_events(ip=ip, limit=limit)

    @app.get("/api/v1/search")
    def search_ip_history(ip: str) -> list[dict[str, str | int | bool | None]]:
        try:
            results = store.search_ip_history(ip)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        protected_ips = {str(item) for item in settings.trusted_auto_remove_ips}
        return [{**result, "protected": result["ip"] in protected_ips} for result in results]

    def remove_one(device_id: int, ip: IPv4Address, actor: Actor, request_id: str) -> bool:
        if "Operator" not in actor.roles and "Administrator" not in actor.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator role required")
        if not store.active_shuns_for_device_ip(device_id, ip):
            return False
        store.create_removal_requested(
            device_id, ip, actor.subject, actor.display_name, tuple(actor.roles), request_id
        )
        try:
            agent.remove_shun(device_id, ip)
        except AgentUnavailable as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        return store.complete_removal(
            device_id, ip, actor.subject, actor.display_name, tuple(actor.roles), request_id
        )

    @app.delete("/api/v1/devices/{device_id}/shuns/{ip}")
    async def remove_device_shun(device_id: int, ip: IPv4Address, request: Request, actor: Actor) -> dict:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        try:
            changed = await asyncio.to_thread(remove_one, device_id, ip, actor, request_id)
        finally:
            synchronizer.note_state_change()
        return {"changed": changed, "request_id": request_id}

    @app.post("/api/v1/shuns/{ip}/remove-all")
    async def remove_all_shuns(ip: IPv4Address, request: Request, actor: Actor) -> dict:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        device_ids = sorted({shun.device_id for shun in store.list_active_shuns(ip)})
        results = []
        for device_id in device_ids:
            try:
                changed = await asyncio.to_thread(remove_one, device_id, ip, actor, request_id)
            finally:
                synchronizer.note_state_change()
            results.append({"device_id": device_id, "changed": changed})
        return {"results": results, "request_id": request_id}

    return app


def main() -> None:
    settings = Settings.from_environment()
    uvicorn.run(create_app(settings), uds=settings.api_socket, log_level="info")
