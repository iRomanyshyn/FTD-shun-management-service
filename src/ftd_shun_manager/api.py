"""Internal state and event API. It is intended to listen only on a Unix socket."""

import sqlite3
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from typing import Annotated, Literal
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from .agent_client import (
    AgentClient,
    DisabledAgentClient,
    MockAgentClient,
    UnixAgentClient,
)
from .config import Settings
from .import_cancellations import ImportCancellations
from .import_preparations import ImportPreparations, PreparationCapacity, PreparationUnavailable
from .import_preview import MAX_DEVICES, MAX_ROWS, classify_targets
from .inventory import load_devices
from .managed_fleet_removals import ManagedFleetRemovals
from .managed_fleet_state import ManagedFleetState
from .managed_imports import ManagedImports
from .managed_safety import ManagedStateUnavailable, require_ordinary_removal
from .managed_scope import ManagedRemovalScopes
from .managed_shuns import (
    ManagedCapacity,
    ManagedConflict,
    ManagedPageChanged,
    ManagedPageInvalid,
    ManagedShuns,
)
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


class ManagedGrantRequest(ManagedRetirementRequest):
    protected_revision: int = Field(strict=True, ge=0)
    maintain_present: StrictBool
    label: str = Field(default="", max_length=100)

    @field_validator("ip", mode="before")
    @classmethod
    def canonical_ip(cls, value):
        if not isinstance(value, str) or str(IPv4Address(value)) != value:
            raise ValueError("Standing grants require an exact canonical IPv4 string.")
        return value


class ManagedSelectionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(strict=True, ge=1, le=65535)
    ip: IPv4Address

    @field_validator("ip", mode="before")
    @classmethod
    def canonical_ip(cls, value):
        if not isinstance(value, str) or str(IPv4Address(value)) != value:
            raise ValueError("Policy selectors require exact canonical IPv4 strings.")
        return value


class ManagedSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[ManagedSelectionTarget] = Field(min_length=1, max_length=100)
    revision: int | None = Field(default=None, strict=True, ge=0)


class ManagedBatchSelectionRequest(ManagedSelectionRequest):
    targets: list[ManagedSelectionTarget] = Field(min_length=1, max_length=1000)


class PreparedImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    text: str = Field(max_length=1048576)
    device_ids: list[Annotated[int, Field(strict=True, ge=1, le=65535)]] = Field(min_length=1, max_length=10)
    label: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=500)


class PreparedImportReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    preparation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PreparedImportPage(PreparedImportReference):
    page: int = Field(default=1, strict=True, ge=1, le=1000)


class PreparedImportConfirmation(PreparedImportReference):
    preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_count: int = Field(strict=True, ge=1, le=1000)
    maintain_present: StrictBool


class ConfirmedImportPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    page: int = Field(default=1, strict=True, ge=1, le=1000)


class ImportCancellationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ImportCancellationRequest(ImportCancellationReference):
    reviewed_at: str = Field(max_length=40)
    review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_count: int = Field(strict=True, ge=1, le=1000)


class ManagedDeviceCleanupRequest(ManagedRetirementRequest):
    intent_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    generation: int = Field(strict=True, ge=1)
    ttl_seconds: int = Field(strict=True, ge=1, le=900)

    @field_validator("ip", mode="before")
    @classmethod
    def canonical_ip(cls, value):
        if not isinstance(value, str) or str(IPv4Address(value)) != value:
            raise ValueError("Cleanup requires an exact canonical IPv4 string.")
        return value


class ManagedFleetCleanupTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(strict=True, ge=1, le=65535)
    hostname: str = Field(min_length=1, max_length=255)
    device_enabled: StrictBool
    observed_present: StrictBool
    maintenance_enabled: StrictBool
    intent_id: str | None
    generation: int | None = Field(strict=True, ge=1)


class ManagedFleetCleanupScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ip: str = Field(min_length=7, max_length=15)
    managed_initialized: StrictBool
    managed_revision: int = Field(strict=True, ge=0)
    protected_revision: int = Field(strict=True, ge=0)
    protected: StrictBool
    targets: list[ManagedFleetCleanupTarget] = Field(min_length=1, max_length=1000)
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManagedFleetCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    reviewed: ManagedFleetCleanupScope
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ttl_seconds: int = Field(strict=True, ge=1, le=900)
    reason: str = Field(default="", max_length=500)
    ordered_wait: StrictBool = False


class ReadyRemovalTarget(ManagedFleetCleanupTarget):
    intent_id: str | None = Field(min_length=36, max_length=36)
    authorization_request_id: str | None = Field(min_length=36, max_length=36)
    target_revision: int | None = Field(strict=True, ge=0)


class ReadyRemovalScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(strict=True, ge=2, le=2)
    scope: Literal['device', 'fleet']
    ip: str = Field(min_length=7, max_length=15)
    managed_revision: int = Field(strict=True, ge=0)
    protected_revision: int = Field(strict=True, ge=0)
    protected: StrictBool
    targets: list[ReadyRemovalTarget] = Field(min_length=1, max_length=10)


class ReadyRemovalActor(ManagedControlActor):
    subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(max_length=255)
    roles: list[Literal['Viewer', 'Operator', 'Administrator']] = Field(max_length=3)


class ReadyRemovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    actor: ReadyRemovalActor
    reviewed: ReadyRemovalScope
    confirmation_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    ttl_seconds: int = Field(strict=True, ge=1, le=900)
    reason: str = Field(default='', max_length=500)


class ImportPreviewRequest(BaseModel):
    ips: list[IPv4Address] = Field(max_length=MAX_ROWS)
    device_ids: list[Annotated[int, Field(ge=1, le=65535)]] = Field(min_length=1, max_length=MAX_DEVICES)


class ImportTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(strict=True, ge=1, le=65535)
    ip: IPv4Address


class ManagedBatchTarget(ImportTarget):
    @field_validator("ip", mode="before")
    @classmethod
    def canonical_ip(cls, value):
        if not isinstance(value, str) or str(IPv4Address(value)) != value:
            raise ValueError("Standing grants require exact canonical IPv4 strings.")
        return value


class ManagedBatchGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: ManagedControlActor
    targets: list[ManagedBatchTarget] = Field(min_length=1, max_length=1000)
    managed_revision: int = Field(strict=True, ge=0)
    protected_revision: int = Field(strict=True, ge=0)
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    maintain_present: StrictBool
    label: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=500)


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
    *,
    continuous_dispatcher=None,
    ready_removal_admission_enabled=False,
) -> FastAPI:
    if type(ready_removal_admission_enabled) is not bool or (ready_removal_admission_enabled and continuous_dispatcher is None):
        raise ValueError('Ready removal needs an explicit compatible continuous runtime and a literal capability.')
    settings = settings or Settings.from_environment()
    store = store or Store(settings.database_path)
    continuous = None
    if continuous_dispatcher is not None:
        from .continuous_api import ContinuousApiRuntime

        continuous = ContinuousApiRuntime(settings, store, continuous_dispatcher, agent_client,
                                          ready_removal_admission_enabled=ready_removal_admission_enabled)
    else:
        if store.path.is_file():
            with store._connection() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_device*' OR tbl_name GLOB 'managed_bulk_device*' LIMIT 1").fetchone():
                    raise QueueConflict('Fenced device storage requires explicit continuous API composition; legacy startup will not initialize or repair it.')
        store.initialize()
    managed = ManagedShuns(store)  # Optional registry; never initialize policy here.
    import_preparations = ImportPreparations(store)  # No optional initialization.
    managed_imports = ManagedImports(store)
    import_cancellations = ImportCancellations(store)
    addition_device_ids = set()
    if continuous is None and settings.device_inventory_path:
        for device, host_key in load_devices(settings.device_inventory_path):
            store.upsert_device(device, host_key)
            if device.enabled and device.addition_profile is not None:
                addition_device_ids.add(device.id)
    addition_device_ids = frozenset(addition_device_ids)
    agent = continuous_dispatcher.runner.agent if continuous else agent_client or _agent(settings, addition_device_ids=addition_device_ids)
    synchronizer = continuous or Synchronizer(
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
        managed_restoration_enabled=settings.managed_restoration_enabled,
    )
    policy = synchronizer.policy
    managed_removals = synchronizer.managed_removals  # Optional schema; no startup initialization.
    if continuous is None:
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
        if (request.method == 'POST' and request.url.path in {
                '/api/v2/managed-removals/device', '/api/v2/managed-removals/fleet'}
                and (continuous is None or continuous.ready_removal_admission_enabled is not True)):
            response = JSONResponse(status_code=503, content={
                'detail': 'Version-2 ready removal admission is disabled; no request was admitted. Inspect any earlier outcome.'})
        elif continuous is not None and not continuous.supports(request.method, request.url.path):
            response = JSONResponse(status_code=503, content={
                'detail': 'This continuous API profile supports observations, refresh demand, Protected IPs, '
                          'v2 policy views and policy-only retirement. Other managed/import/manual device '
                          'mutation workflows are unavailable; no request was admitted.'})
        else:
            try:
                response = await call_next(request)
            except (sqlite3.DatabaseError, ValueError, TypeError, KeyError):
                if continuous is None:
                    raise
                response = JSONResponse(status_code=503, content={
                    'detail': 'Continuous API state is unavailable. Inspect retained state before retrying; '
                              'no successful device operation is implied.'})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/status")
    async def service_status() -> dict[str, object]:
        policy_state = policy.snapshot()
        try:
            managed_metadata = continuous.managed_metadata() if continuous else managed.metadata()
        except (sqlite3.DatabaseError, ManagedConflict, ManagedCapacity, ValueError, TypeError, KeyError):
            # A malformed optional registry must not stop ordinary fleet monitoring.
            managed_metadata = {"managed_policy_available": False, "managed_policy_initialized": None,
                                "managed_policy_revision": None}
        return {
            "status": "ready",
            "agent_mode": settings.agent_mode,
            "large_snapshots_enabled": settings.large_snapshots_enabled,
            "import_admission_enabled": settings.import_admission_enabled,
            "managed_policy_admission_enabled": settings.managed_policy_admission_enabled,
            "managed_removal_admission_enabled": settings.managed_removal_admission_enabled,
            **synchronizer.status(),
            **managed_metadata,
            "policy_revision": policy_state["revision"],
            "trusted_auto_remove_ips": [entry for entry in policy_state["entries"] if entry["enabled"]],
            "disabled_protected_ips": [{"ip": entry["ip"]} for entry in policy_state["entries"] if not entry["enabled"]],
        }

    @app.get("/api/v1/managed-shuns")
    def managed_shuns() -> dict:
        try:
            return managed.snapshot_if_present(restoration_context=synchronizer.managed_discovery.context,
                                               restoration_now=synchronizer.queue._now())
        except (sqlite3.DatabaseError, ManagedConflict, ManagedCapacity, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Managed shun registry is unavailable; no policy was changed.") from error

    @app.get("/api/v1/managed-shuns/page")
    def managed_shuns_page(page: Annotated[int, Query(ge=1, le=2**31 - 1)] = 1,
                           revision: Annotated[int | None, Query(ge=0)] = None) -> dict:
        try:
            return managed.page(page, revision=revision,
                                restoration_context=synchronizer.managed_discovery.context,
                                restoration_now=synchronizer.queue._now())
        except ManagedPageChanged as error:
            raise HTTPException(409, str(error)) from error
        except ManagedPageInvalid as error:
            raise HTTPException(422, str(error)) from error
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Managed policy page is unavailable; no policy was changed.") from error

    @app.post('/api/v2/managed-removals/device', status_code=202)
    def ready_device_removal(change: ReadyRemovalRequest, request: Request) -> dict:
        return ready_removal(change, request, 'device')

    @app.post('/api/v2/managed-removals/fleet', status_code=202)
    def ready_fleet_removal(change: ReadyRemovalRequest, request: Request) -> dict:
        return ready_removal(change, request, 'fleet')

    def ready_removal(change, request, mode):
        if continuous is None or continuous.ready_removal_admission_enabled is not True:
            raise HTTPException(503, 'Version-2 ready removal admission is disabled; inspect any earlier outcome.')
        require_operator(change.actor)
        if change.reviewed.scope != mode:
            raise HTTPException(422, 'The exact reviewed mode must match this fixed ready-removal route.')
        if change.ttl_seconds > min(900, settings.sensitive_action_max_age_seconds):
            raise HTTPException(422, 'Removal lifetime exceeds the configured sensitive-action maximum.')
        try:
            result = continuous.ready_removals.admit(request.headers.get('Idempotency-Key', ''),
                change.reviewed.model_dump(), change.confirmation_digest, change.actor.subject,
                change.actor.display_name, tuple(change.actor.roles), ttl_seconds=change.ttl_seconds,
                reason=change.reason, enabled=True)
        except (PermissionError, ValueError, sqlite3.DatabaseError) as error:
            raise cleanup_error(error) from error
        if not result['replayed']:
            continuous.note_state_change()
            continuous.dispatcher.signal_work()
        return result

    @app.get('/api/v2/managed-removal-scope/{ip}')
    def bulk_removal_scope(ip: IPv4Address, device_id: Annotated[int | None, Query(ge=1, le=65535)] = None) -> dict:
        if continuous is None:
            raise HTTPException(503, 'Version-2 removal scope requires explicit compatible API composition.')
        try:
            return continuous.removal_scopes.snapshot(ip, device_id=device_id)
        except ManagedConflict as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/v2/managed-shuns/page')
    def bulk_policy_page(page: Annotated[int, Query(ge=1, le=2**31 - 1)] = 1,
                         revision: Annotated[int | None, Query(ge=0)] = None) -> dict:
        if continuous is None:
            raise HTTPException(503, 'Version-2 policy views require explicit compatible API composition.')
        try:
            return continuous.policy_views.page(page, revision=revision)
        except ManagedPageChanged as error:
            raise HTTPException(409, str(error)) from error
        except ManagedPageInvalid as error:
            raise HTTPException(422, str(error)) from error

    @app.post('/api/v2/managed-shuns/selection')
    def bulk_policy_selection(selection: ManagedSelectionRequest) -> dict:
        if continuous is None:
            raise HTTPException(503, 'Version-2 policy selections require explicit compatible API composition.')
        from .managed_selection import selected_pairs
        try:
            pairs = selected_pairs([(target.device_id, target.ip) for target in selection.targets])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        try:
            return continuous.policy_views.selection(pairs, revision=selection.revision)
        except ManagedPageChanged as error:
            raise HTTPException(409, str(error)) from error

    @app.post('/api/v2/managed-shuns/retire')
    def bulk_policy_retirement(change: ManagedRetirementRequest, request: Request) -> dict:
        if continuous is None:
            raise HTTPException(503, 'Version-2 policy retirement requires explicit compatible API composition.')
        try:
            result = continuous.policy_revocation.retire(request.headers.get('Idempotency-Key', ''),
                [(change.device_id, change.ip)], change.managed_revision, change.confirmation_digest,
                change.actor.subject, change.actor.display_name, tuple(change.actor.roles), reason=change.reason)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except (ManagedConflict, ManagedCapacity) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, 'Policy retirement was not confirmed. Inspect state and retry only the original key.') from error
        if not result['replayed']:
            continuous.note_state_change()
        return {**result, 'intent_format': 2, 'policy_only': True, 'device_work_admitted': False}

    @app.post("/api/v1/managed-shuns/selection")
    def managed_selection(selection: ManagedSelectionRequest) -> dict:
        return read_managed_selection(selection, batch=False)

    @app.post("/api/v1/managed-shuns/selection/batch")
    def managed_batch_selection(selection: ManagedBatchSelectionRequest) -> dict:
        return read_managed_selection(selection, batch=True)

    def read_managed_selection(selection, *, batch):
        from .managed_selection import selected_pairs

        try:
            pairs = selected_pairs([(target.device_id, target.ip) for target in selection.targets], batch=batch)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        try:
            reader = managed.batch_selection if batch else managed.selection
            return reader(pairs, revision=selection.revision,
                          restoration_context=synchronizer.managed_discovery.context,
                          restoration_now=synchronizer.queue._now())
        except ManagedPageChanged as error:
            raise HTTPException(409, str(error)) from error
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Selected policy is unavailable; no policy was changed.") from error

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

    def prepared_import_error(error, *, confirming=False):
        if isinstance(error, PermissionError):
            return HTTPException(403, str(error))
        if isinstance(error, ManagedStateUnavailable):
            return HTTPException(503, "Standing evidence or confirmed-import storage is unavailable; nothing was admitted.")
        if isinstance(error, (ManagedConflict, ManagedCapacity, PreparationUnavailable, PreparationCapacity)):
            return HTTPException(409, str(error))
        if isinstance(error, ValueError):
            return HTTPException(422, str(error))
        message = ("Import policy outcome was not confirmed. Inspect receipts and retry only the original operation key."
                   if confirming else "Import report is unavailable; no admission request was made.")
        return HTTPException(503, message)

    @app.post("/api/v1/managed-imports/prepare")
    def prepare_managed_import(change: PreparedImportInput):
        require_operator(change.actor)
        try:
            return import_preparations.create(change.text, change.device_ids, change.actor.subject,
                                              change.actor.display_name, tuple(change.actor.roles),
                                              label=change.label, reason=change.reason)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/preparations")
    def list_import_preparations(actor: ManagedControlActor):
        if not actor.subject.strip():
            raise HTTPException(403, "Authenticated author required.")
        try:
            return import_preparations.list_for_owner(actor.subject)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/preparation")
    def read_import_preparation(change: PreparedImportPage):
        try:
            return import_preparations.page(change.preparation_id, change.actor.subject, page=change.page)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/cancel-preparation")
    def cancel_import_preparation(change: PreparedImportReference):
        try:
            cancelled = import_preparations.cancel(change.preparation_id, change.actor.subject)
            return {"preparation_id": change.preparation_id, "cancelled": cancelled, "device_work_admitted": False}
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/confirm")
    def confirm_managed_import(change: PreparedImportConfirmation, request: Request):
        require_operator(change.actor)
        if not settings.managed_policy_admission_enabled:
            raise HTTPException(503, "Standing policy admission is disabled. Inspect any earlier receipt; this attempt was not submitted.")
        try:
            result = managed_imports.confirm(request.headers.get("Idempotency-Key", ""), change.preparation_id,
                change.preparation_digest, change.accepted_count, change.actor.subject, change.actor.display_name,
                tuple(change.actor.roles), maintain_present=change.maintain_present,
                enabled=settings.managed_policy_admission_enabled, addition_device_ids=addition_device_ids)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, PermissionError) as error:
            raise prepared_import_error(error, confirming=True) from error
        if not result["replayed"]:
            synchronizer.note_state_change()  # Publish local metadata only, no refresh/discovery wakeup.
        return result

    @app.post("/api/v1/managed-imports/receipts")
    def list_managed_import_receipts(actor: ManagedControlActor):
        if not actor.subject.strip():
            raise HTTPException(403, "Authenticated author required.")
        try:
            return managed_imports.list_for_owner(actor.subject)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/receipt")
    def read_managed_import_receipt(change: ConfirmedImportPage):
        try:
            return managed_imports.page(change.operation_id, change.actor.subject, page=change.page)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/cancellation-review")
    def review_import_cancellation(change: ImportCancellationReference):
        try:
            return import_cancellations.review(change.operation_id, change.actor.subject, tuple(change.actor.roles))
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, PermissionError) as error:
            raise prepared_import_error(error) from error

    @app.post("/api/v1/managed-imports/cancel-confirmed")
    def cancel_confirmed_import(change: ImportCancellationRequest):
        try:
            result = import_cancellations.cancel(change.operation_id, change.reviewed_at, change.review_digest,
                change.accepted_count, change.actor.subject, change.actor.display_name, tuple(change.actor.roles))
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, PermissionError) as error:
            if isinstance(error, (sqlite3.DatabaseError, TypeError, KeyError)):
                raise HTTPException(503, "Cancellation outcome was not confirmed. Inspect its status; retry only the original review.") from error
            raise prepared_import_error(error) from error
        if not result["replayed"]:
            synchronizer.note_state_change()
        return result

    @app.post("/api/v1/managed-imports/cancellation")
    def read_import_cancellation(change: ConfirmedImportPage):
        try:
            return import_cancellations.page(change.operation_id, change.actor.subject, tuple(change.actor.roles), page=change.page)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, PermissionError) as error:
            raise prepared_import_error(error) from error

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

    @app.post("/api/v1/managed-shuns/maintain-batch")
    def grant_managed_batch(change: ManagedBatchGrantRequest, request: Request) -> dict:
        require_operator(change.actor)
        if not settings.managed_policy_admission_enabled:
            raise HTTPException(503, "Standing policy admission is disabled. This attempt changed nothing; inspect any earlier outcome.")
        if change.maintain_present is not True:
            raise HTTPException(422, "Explicit standing-authority acknowledgement is required.")
        pairs = [(target.device_id, target.ip) for target in change.targets]
        if len({device for device, _ in pairs}) > MAX_DEVICES:
            raise HTTPException(422, "Select at most 64 distinct devices; no policy was saved.")
        try:
            result = managed.grant_batch_reviewed(
                request.headers.get("Idempotency-Key", ""), pairs, change.managed_revision,
                change.protected_revision, change.confirmation_digest, change.actor.subject,
                change.actor.display_name, tuple(change.actor.roles), addition_device_ids=addition_device_ids,
                label=change.label, reason=change.reason)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ManagedStateUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except (ManagedConflict, ManagedCapacity) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, "Standing batch outcome is unknown. Retry the original review/key.") from error
        if not result["replayed"]:
            synchronizer.note_state_change()
        return result

    @app.post("/api/v1/managed-shuns/maintain")
    def grant_managed_shun(change: ManagedGrantRequest, request: Request) -> dict:
        require_operator(change.actor)
        if not settings.managed_policy_admission_enabled:
            raise HTTPException(503, "Standing policy admission is disabled. This attempt changed nothing; inspect any earlier outcome.")
        if change.maintain_present is not True:
            raise HTTPException(422, "Explicit standing-authority acknowledgement is required.")
        try:
            result = managed.grant_reviewed(
                request.headers.get("Idempotency-Key", ""), change.device_id, change.ip,
                change.managed_revision, change.protected_revision, change.confirmation_digest,
                change.actor.subject, change.actor.display_name, tuple(change.actor.roles),
                addition_device_ids=addition_device_ids, label=change.label, reason=change.reason)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ManagedStateUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except (ManagedConflict, ManagedCapacity) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, "Standing policy outcome is unknown. Retry the original review/key.") from error
        if not result["replayed"]:
            synchronizer.note_state_change()  # Policy receipt only; no queue job or device hint.
        return result

    def require_cleanup_admission(actor, ttl):
        require_operator(actor)
        if not settings.managed_removal_admission_enabled:
            raise HTTPException(503, "Combined cleanup admission is disabled. This attempt changed nothing; inspect any earlier outcome.")
        if ttl > min(900, settings.sensitive_action_max_age_seconds):
            raise HTTPException(422, "Cleanup lifetime exceeds the configured sensitive-action maximum.")

    def cleanup_error(error):
        if isinstance(error, PermissionError):
            return HTTPException(403, str(error))
        if isinstance(error, ManagedStateUnavailable):
            return HTTPException(503, "Managed cleanup state is unavailable; no new plan was confirmed.")
        if isinstance(error, (ManagedConflict, ManagedCapacity, QueueConflict)):
            return HTTPException(409, str(error))
        if isinstance(error, QueueFull):
            return HTTPException(429, str(error))
        if isinstance(error, sqlite3.DatabaseError):
            return HTTPException(503, "Cleanup outcome is unknown. Inspect current state; retry the original review/key.")
        return HTTPException(422, str(error))

    @app.post("/api/v1/managed-removals/device", status_code=202)
    def admit_managed_device_cleanup(change: ManagedDeviceCleanupRequest, request: Request) -> dict:
        require_cleanup_admission(change.actor, change.ttl_seconds)
        try:
            result = managed_removals.admit(
                request.headers.get("Idempotency-Key", ""), change.device_id, change.ip, change.managed_revision,
                change.confirmation_digest, change.actor.subject, change.actor.display_name, tuple(change.actor.roles),
                change.ttl_seconds, change.reason, expected_intent_id=change.intent_id, expected_generation=change.generation)
        except (PermissionError, ValueError, sqlite3.DatabaseError) as error:
            raise cleanup_error(error) from error
        if not result["replayed"]:
            synchronizer.signal_work()
        return result

    @app.post("/api/v1/managed-removals/fleet", status_code=202)
    def admit_managed_fleet_cleanup(change: ManagedFleetCleanupRequest, request: Request) -> dict:
        require_cleanup_admission(change.actor, change.ttl_seconds)
        try:
            result = ManagedFleetRemovals(managed, synchronizer.queue).admit(
                request.headers.get("Idempotency-Key", ""), change.reviewed.model_dump(), change.confirmation_digest,
                change.actor.subject, change.actor.display_name, tuple(change.actor.roles), change.ttl_seconds,
                change.reason, ordered_wait=change.ordered_wait)
        except (PermissionError, ValueError, sqlite3.DatabaseError) as error:
            raise cleanup_error(error) from error
        if not result["replayed"]:
            synchronizer.signal_work()
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

    @app.get("/api/v1/managed-fleet-removals")
    def managed_fleet_removals() -> dict:
        try:
            return ManagedFleetState(store, worker_enabled=settings.managed_removal_worker_enabled).snapshot_if_present()
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise HTTPException(503, "Fleet cleanup state is unavailable; nothing was submitted.") from error

    @app.post("/api/v1/managed-fleet-removals/{request_id}/cancel")
    def cancel_managed_fleet_wait(request_id: UUID, actor: ManagedControlActor) -> dict:
        try:
            changed = synchronizer.managed_fleet_waits.cancel_waiting(
                str(request_id), actor.subject, actor.display_name, tuple(actor.roles))
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except QueueConflict as error:
            raise HTTPException(409, str(error)) from error
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, "Fleet cancellation was not confirmed; inspect current state before retrying.") from error
        if changed:
            synchronizer.note_state_change()  # Local revocation, never a refresh hint.
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
        except sqlite3.DatabaseError as error:
            raise HTTPException(503, "Protected policy save was not confirmed. Inspect current policy before retrying.") from error
        synchronizer.note_state_change()
        return {"status": "saved", "policy": policy.snapshot()}

    @app.post("/api/v1/refresh-hint", status_code=status.HTTP_202_ACCEPTED)
    async def refresh_hint() -> dict[str, object]:
        try:
            refresh = synchronizer.request_activity()
        except QueueConflict as error:
            raise HTTPException(503, 'Refresh coordinator is unavailable; no successful read was confirmed.') from error
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
