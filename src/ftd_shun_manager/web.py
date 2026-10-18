"""Browser-facing BFF protected by Caddy and Authelia ForwardAuth."""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlencode
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import Settings
from .import_preview import (
    MAX_FORM_BYTES,
    MAX_ROWS,
    MAX_TEXT_BYTES,
    PAGE_SIZE,
    paginate_preview,
    parse_blocklist,
    summarize_preview,
)
from .import_review import ImportReviews, ReviewUnavailable
from .managed_retirement_review import ManagedRetirementReviews
from .managed_review import ManagedRemovalReviews

PROJECT_ROOT = Path(os.environ.get("FTD_SHUN_ASSET_ROOT", Path(__file__).resolve().parents[2]))
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
templates.env.globals["new_operation_key"] = lambda: str(uuid4())
templates.env.globals["import_text_limit"] = MAX_TEXT_BYTES
templates.env.globals["product_version"] = __version__


@dataclass(frozen=True)
class Identity:
    subject: str
    display_name: str
    roles: tuple[str, ...]


GROUP_TO_ROLE = {
    "ftd-shun-viewers": "Viewer",
    "ftd-shun-operators": "Operator",
    "ftd-shun-administrators": "Administrator",
}


def identity_from_request(request: Request, development_auth: bool) -> Identity:
    """Read only Caddy-injected identity headers; never accept browser role input."""
    username = request.headers.get("remote-user")
    groups = request.headers.get("remote-groups", "")
    if development_auth and not username:
        username = request.headers.get("x-dev-user", "developer")
        groups = request.headers.get("x-dev-groups", "ftd-shun-administrators")
    if not username or not username.strip():
        raise HTTPException(status_code=401, detail="authentication required")
    roles = tuple(sorted({GROUP_TO_ROLE[group.strip()] for group in groups.split(",") if group.strip() in GROUP_TO_ROLE}))
    return Identity(subject=username, display_name=request.headers.get("remote-name", username), roles=roles)


def csrf_token(request: Request) -> tuple[str, bool]:
    token = request.cookies.get("ftd_shun_csrf")
    return (token, False) if token else (secrets.token_urlsafe(32), True)


def require_csrf(request: Request, supplied: str) -> None:
    existing = request.cookies.get("ftd_shun_csrf", "")
    if not existing or not hmac.compare_digest(existing.encode("utf-8"), supplied.encode("utf-8")):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


async def preview_form(request: Request, *, allowed: set[str] | None = None,
                       max_bytes: int = MAX_FORM_BYTES) -> dict[str, list[str]]:
    """Bound the paste request before parsing; file/multipart uploads are unsupported."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Paste preview requires a URL-encoded form; uploads are unsupported.")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal() or len(length) > 10:
            raise HTTPException(400, "Invalid request length.")
        if int(length) > max_bytes:
            raise HTTPException(413, f"Encoded import form exceeds {max_bytes} bytes. Nothing was parsed or queued.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(413, f"Encoded import form exceeds {max_bytes} bytes. Nothing was parsed or queued.")
        body.extend(chunk)
    try:
        fields = parse_qs(body.decode("ascii"), encoding="utf-8", errors="strict", keep_blank_values=True, max_num_fields=80)
    except (ValueError, UnicodeError) as error:
        raise HTTPException(400, "Invalid preview form encoding or field count.") from error
    if set(fields) - (allowed if allowed is not None else {"csrf", "text", "device_ids", "label", "reason", "page"}) or any(
        len(values) != 1 for key, values in fields.items() if key != "device_ids"
    ):
        raise HTTPException(422, "Unexpected or repeated preview form field.")
    return fields


def api_client(settings: Settings) -> httpx.Client:
    transport = httpx.HTTPTransport(uds=settings.api_socket)
    # A removal can legitimately wait for the agent's bounded FTD SSH operation.
    # The API itself allows five seconds of local IPC margin, so the BFF must
    # never time out first and claim an internal error after a verified write.
    return httpx.Client(
        transport=transport,
        base_url="http://ftd-internal",
        timeout=settings.agent_timeout_seconds + 10,
    )


def protected_policy_ips(refresh: object, *, enabled: bool = True) -> frozenset[str]:
    """Read exact enabled/disabled policy addresses for display, not authorization."""
    if not isinstance(refresh, dict):
        return frozenset()
    entries = refresh.get("trusted_auto_remove_ips" if enabled else "disabled_protected_ips", [])
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(
        entry["ip"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("ip"), str)
    )


def refresh_metadata(refresh: object) -> dict[str, object]:
    """Whitelist the status fields required by browser-side freshness updates."""
    if not isinstance(refresh, dict):
        raise TypeError("State API returned an invalid refresh status")
    fields = (
        "instance_id",
        "status_revision",
        "data_revision",
        "cycle_revision",
        "cycle_id",
        "cycle_started_at",
        "cycle_completed_at",
        "cycle_outcome",
        "refresh_enabled",
        "server_time",
        "devices",
        "queue",
        "session_cycles_enabled",
        "import_execution_enabled",
        "managed_removal_worker_enabled",
        "managed_removal_worker_error",
        "managed_restoration",
        "managed_restoration_error",
        "addition_device_count",
        "device_cycle",
        "priority_refresh_available",
        "policy_revision",
        "managed_policy_revision",
        "managed_policy_initialized",
        "managed_policy_available",
        "last_successful_refresh",
        "last_attempt",
        "last_error",
        "refresh_in_progress",
        "next_baseline_refresh",
        "next_interactive_refresh",
        "baseline_interval_seconds",
        "interactive_min_interval_seconds",
        "interactive_refresh_state",
    )
    return {field: refresh.get(field) for field in fields}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="FTD Shun Manager", docs_url=None, redoc_url=None, openapi_url=None)
    reviews = ImportReviews(settings.sensitive_action_max_age_seconds)
    managed_reviews = ManagedRemovalReviews(settings.sensitive_action_max_age_seconds)
    retirement_reviews = ManagedRetirementReviews(settings.sensitive_action_max_age_seconds)
    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

    @app.middleware("http")
    async def prevent_state_caching(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def render(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
        token, set_cookie = csrf_token(request)
        response = templates.TemplateResponse(
            request, name, {**context, "csrf_token": token}, status_code=status_code
        )
        if set_cookie:
            response.set_cookie("ftd_shun_csrf", token, secure=True, httponly=True, samesite="strict")
        return response

    def queued_result(request: Request, response: httpx.Response, target: str) -> Response:
        if response.status_code not in {200, 202}:
            try:
                detail = response.json().get("detail", "Operation request was rejected.")
            except (ValueError, AttributeError):
                detail = "Operation request was rejected."
            raise HTTPException(response.status_code, detail)
        if "application/json" in request.headers.get("accept", ""):
            try:
                with api_client(settings) as client:
                    refresh = client.get("/api/v1/status")
            except httpx.HTTPError as error:
                raise HTTPException(503, "Request status is unknown. Retry with the same operation key.") from error
            if refresh.status_code != 200:
                raise HTTPException(503, "Request may be queued; status is unavailable. Retry with the same operation key.")
            return JSONResponse({**refresh_metadata(refresh.json()), "operation_result": response.json()})
        return RedirectResponse(target, status_code=303)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, q: str = "") -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        search_query = q.strip()
        with api_client(settings) as client:
            # Capture the revision before state reads. If reconciliation occurs
            # during rendering, the next poll will fetch the newer revision.
            refresh_status = client.get("/api/v1/status")
            response = client.get("/api/v1/shuns")
            search_response = (
                client.get("/api/v1/search", params={"ip": search_query})
                if search_query
                else None
            )
        if response.status_code != 200:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        if search_response is not None and search_response.status_code != 200:
            return render(request, "error.html", {"message": "IP search is invalid or unavailable."}, 422)
        refresh = refresh_status.json() if refresh_status.status_code == 200 else None
        return render(
            request,
            "index.html",
            {
                "identity": identity,
                "shuns": response.json(),
                "refresh": refresh,
                "trusted_policy_ips": protected_policy_ips(refresh),
                "disabled_policy_ips": protected_policy_ips(refresh, enabled=False),
                "search_query": search_query,
                "search_results": search_response.json() if search_response is not None else None,
            },
        )

    @app.get("/refresh-status")
    def refresh_status(request: Request) -> JSONResponse:
        identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                response = client.get("/api/v1/status")
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="State API is unavailable.") from error
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        try:
            return JSONResponse(refresh_metadata(response.json()))
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=503, detail="State API returned invalid status.") from error

    def require_import_operator(identity: Identity) -> None:
        if not {"Operator", "Administrator"}.intersection(identity.roles):
            raise HTTPException(403, "Operator role required for import confirmation.")

    async def import_page(request: Request, submitted: bool = False, prepare: bool = False) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        if prepare:
            require_import_operator(identity)
        text, label, reason = "", "", ""
        selected: list[int] = []
        parsed, error_message = None, None
        page = 1
        if submitted:
            fields = await preview_form(request)
            require_csrf(request, fields.get("csrf", [""])[0])
            text = fields.get("text", [""])[0]
            label = fields.get("label", [""])[0]
            reason = fields.get("reason", [""])[0]
            if len(label) > 100 or len(reason) > 500:
                raise HTTPException(422, "Label/reason exceeds 100/500 characters.")
            try:
                raw_page = fields.get("page", ["1"])[0]
                if (not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 3
                        or not 1 <= int(raw_page) <= (MAX_ROWS + PAGE_SIZE - 1) // PAGE_SIZE):
                    raise ValueError("Select a preview page between 1 and 100.")
                page = int(raw_page)
                raw_devices = fields.get("device_ids", [])
                if any(not value.isascii() or not value.isdecimal() for value in raw_devices):
                    raise ValueError("Select configured devices using the checkboxes.")
                selected = [int(value) for value in raw_devices]
                parsed = await run_in_threadpool(parse_blocklist, text)
                if not parsed["rows"]:
                    raise ValueError("Paste at least one non-comment line.")
            except ValueError as error:
                parsed, error_message = None, str(error)
        return await run_in_threadpool(import_view, request, identity, text, label, reason, selected, parsed, error_message, page, prepare)

    def import_view(request: Request, identity: Identity, text: str, label: str, reason: str,
                    selected: list[int], parsed: dict | None, error_message: str | None, page: int,
                    prepare: bool = False) -> HTMLResponse:
        try:
            with api_client(settings) as client:
                refresh = client.get("/api/v1/status")
                devices = client.get("/api/v1/import-devices")
                classification = client.post("/api/v1/import-preview", json={
                    "ips": parsed["ips"], "device_ids": selected,
                }) if parsed is not None else None
        except httpx.HTTPError as error:
            raise HTTPException(503, "Local preview state is unavailable. Nothing was queued.") from error
        if refresh.status_code != 200 or devices.status_code != 200:
            raise HTTPException(503, "Local preview state is unavailable. Nothing was queued.")
        preview = None
        if classification is not None:
            if classification.status_code == 422:
                detail = classification.json().get("detail")
                error_message = detail if isinstance(detail, str) else "Select 1–64 distinct enabled devices and at most 100,000 device/IP pairs."
            elif classification.status_code != 200:
                raise HTTPException(503, "Local preview state is unavailable. Nothing was queued.")
            else:
                preview = paginate_preview(summarize_preview(parsed, classification.json()), page)
        if prepare and preview is not None and not error_message:
            try:
                review = reviews.prepare(identity.subject, request.cookies.get("ftd_shun_csrf", ""), preview, label, reason)
            except ValueError as error:
                error_message = str(error)
            else:
                return review_view(request, identity, review, refresh.json())
        return render(request, "import-preview.html", {
            "identity": identity, "refresh": refresh.json(), "devices": devices.json(),
            "source_text": text, "batch_label": label, "batch_reason": reason,
            "selected_devices": selected, "preview": preview, "preview_error": error_message,
            "active_page": "imports", "auto_request": False,
        }, status_code=413 if len(text.encode("utf-8")) > MAX_TEXT_BYTES else 422 if error_message else 200)

    @app.get("/imports", response_class=HTMLResponse)
    async def imports(request: Request) -> HTMLResponse:
        return await import_page(request)

    @app.post("/imports", response_class=HTMLResponse)
    async def parse_import(request: Request) -> HTMLResponse:
        return await import_page(request, submitted=True)

    @app.post("/imports/review", response_class=HTMLResponse)
    async def prepare_import(request: Request) -> HTMLResponse:
        return await import_page(request, submitted=True, prepare=True)

    def review_view(request, identity, review, refresh, *, message=None, accepted=None, status_code=200):
        return render(request, "import-confirm.html", {
            "identity": identity, "review": review, "refresh": refresh,
            "message": message, "accepted": accepted,
            "admission_enabled": refresh.get("import_admission_enabled") is True,
            "retry_available": refresh.get("import_admission_enabled") is not False,
            "execution_enabled": refresh.get("import_execution_enabled") is True,
            "active_page": "imports", "auto_request": False, "frozen_view": True,
        }, status_code)

    @app.post("/imports/confirm", response_class=HTMLResponse)
    async def confirm_import(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_import_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "review", "confirm_count"}, max_bytes=4096)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            review = reviews.get(fields.get("review", [""])[0], identity.subject,
                                 request.cookies.get("ftd_shun_csrf", ""))
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        if fields.get("confirm_count", [""])[0] != str(len(review.targets)):
            raise HTTPException(422, "Type the exact target count shown in the review.")
        return await run_in_threadpool(submit_import, request, identity, review)

    def submit_import(request, identity, review):
        # Freeze the key/body across retries. Current trusted identity, never form JSON.
        refresh = {}
        try:
            with api_client(settings) as client:
                response = client.get("/api/v1/status")
                if response.status_code != 200:
                    raise httpx.RequestError("Status unavailable")
                refresh = response.json()
                if refresh.get("import_admission_enabled") is not True:
                    return review_view(request, identity, review, refresh,
                                       message="Import admission is disabled. No admission request was sent.", status_code=503)
                # Status can be slow; do not admit a review that expired while waiting.
                reviews.get(review.token, identity.subject, request.cookies.get("ftd_shun_csrf", ""))
                response = client.post("/api/v1/imports", json={**review.payload(), "actor": identity.__dict__},
                                       headers={"Idempotency-Key": review.request_id})
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except httpx.HTTPError:
            return review_view(request, identity, review, refresh,
                               message="Admission was not confirmed. Check Queue; retry only this same review/key, never a new batch.",
                               status_code=503)
        except (ValueError, TypeError, AttributeError):
            return review_view(request, identity, review, {},
                               message="Admission result is uncertain. Check Queue; retry only this same review/key.", status_code=503)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise TypeError("Invalid admission result")
        except (ValueError, TypeError):
            return review_view(request, identity, review, refresh,
                               message="Admission result is uncertain. Check Queue; retry only this same review/key.", status_code=503)
        if response.status_code != 202:
            detail = result.get("detail", "Import request was rejected.")
            return review_view(request, identity, review, refresh, message=detail, status_code=response.status_code)
        if (result.get("operation_id") != review.request_id or result.get("status") != "accepted"
                or type(result.get("replayed")) is not bool or type(result.get("execution_enabled")) is not bool
                or result.get("source") != "manual_import" or result.get("action") != "ADD"):
            return review_view(request, identity, review, refresh,
                               message="Admission result is uncertain. Check Queue; retry only this same review/key.", status_code=503)
        return review_view(request, identity, review, refresh, accepted=result)

    @app.get("/managed-shuns", response_class=HTMLResponse)
    def managed_shuns(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                refresh = client.get("/api/v1/status")
                policy = client.get("/api/v1/managed-shuns")
        except httpx.HTTPError as error:
            raise HTTPException(503, "Managed shun state is unavailable. No policy was changed.") from error
        if refresh.status_code != 200 or policy.status_code != 200:
            return render(request, "error.html", {"identity": identity,
                          "message": "Managed shun state is unavailable. No policy was changed."}, 503)
        cleanup, fleet_cleanup = None, None
        try:
            with api_client(settings) as client:
                response = client.get("/api/v1/managed-removal-handoffs")
            if response.status_code == 200:
                candidate = response.json()
                if (isinstance(candidate, dict) and type(candidate.get("initialized")) is bool
                        and isinstance(candidate.get("items"), list) and len(candidate["items"]) <= 20
                        and isinstance(candidate.get("counts"), dict) and candidate.get("read_only") is True):
                    cleanup = candidate
        except (httpx.HTTPError, ValueError, TypeError):
            pass  # Optional cleanup errors stay visible; never fabricate empty state.
        try:
            with api_client(settings) as client:
                response = client.get("/api/v1/managed-fleet-removals")
            if response.status_code == 200:
                candidate = response.json()
                if (isinstance(candidate, dict) and type(candidate.get("initialized")) is bool
                        and isinstance(candidate.get("items"), list) and len(candidate["items"]) <= 20
                        and isinstance(candidate.get("counts"), dict) and candidate.get("read_only") is True
                        and candidate.get("admission_enabled") is False):
                    fleet_cleanup = candidate
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        return render(request, "managed-shuns.html", {
            "identity": identity, "refresh": refresh.json(), "managed": policy.json(),
            "handoffs": cleanup,
            "fleet_cleanup": fleet_cleanup,
            "active_page": "managed", "auto_request": False,
        })

    def require_managed_operator(identity):
        if not {"Operator", "Administrator"}.intersection(identity.roles):
            raise HTTPException(403, "Operator role required for managed controls.")

    def retirement_view(request, identity, review, refresh=None, *, result=None, message=None,
                        confirm_ip="", status_code=200):
        return render(request, "managed-retirement-review.html", {
            "identity": identity, "review": review, "refresh": refresh, "result": result,
            "message": message, "confirm_ip": confirm_ip, "active_page": "managed",
            "auto_request": False, "frozen_view": True,
        }, status_code)

    @app.post("/managed-shuns/retirement-review", response_class=HTMLResponse)
    async def prepare_retirement(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "target", "reason"}, max_bytes=16384)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            raw_device, raw_ip = fields.get("target", [""])[0].split(":")
            device_id, ip = int(raw_device), IPv4Address(raw_ip)
            if raw_device != str(device_id):
                raise ValueError("Non-canonical device ID")
        except ValueError as error:
            raise HTTPException(422, "Choose an exact managed device and IPv4 address.") from error
        return await run_in_threadpool(prepare_retirement_review, request, identity, device_id, ip,
                                       fields.get("reason", [""])[0])

    def prepare_retirement_review(request, identity, device_id, ip, reason):
        try:
            with api_client(settings) as client:
                policy = client.get("/api/v1/managed-shuns")
                refresh = client.get("/api/v1/status")
            if policy.status_code != 200 or refresh.status_code != 200:
                raise httpx.RequestError("Policy state unavailable")
            review = retirement_reviews.prepare(identity.subject, request.cookies.get("ftd_shun_csrf", ""),
                                                policy.json(), device_id, ip, reason)
            state = refresh.json()
            if not isinstance(state, dict):
                raise TypeError("Invalid status")
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise HTTPException(422, "Invalid retirement review data; no change was submitted.") from error
        except httpx.HTTPError as error:
            raise HTTPException(503, "Retirement review is unavailable; no change was submitted.") from error
        return retirement_view(request, identity, review, state)

    @app.post("/managed-shuns/retirement-confirm", response_class=HTMLResponse)
    async def confirm_retirement(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "review", "confirm_ip"}, max_bytes=4096)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            review = retirement_reviews.get(fields.get("review", [""])[0], identity.subject,
                                             request.cookies.get("ftd_shun_csrf", ""))
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        if fields.get("confirm_ip", [""])[0] != str(review.ip):
            raise HTTPException(422, "Type the exact IPv4 address shown in the retirement review.")
        return await run_in_threadpool(save_retirement, request, identity, review)

    def save_retirement(request, identity, review):
        result, message, status_code, state = None, None, 200, None
        try:
            with api_client(settings) as client:
                response = client.post("/api/v1/managed-shuns/retire", headers={"Idempotency-Key": review.request_id},
                                       json={"actor": identity.__dict__, "device_id": review.device_id,
                                             "ip": str(review.ip), "managed_revision": review.managed_revision,
                                             "confirmation_digest": review.digest, "reason": review.reason})
                value = response.json()
                if response.status_code != 200:
                    detail = value.get("detail") if isinstance(value, dict) else None
                    message = detail if isinstance(detail, str) else "Policy retirement was rejected; inspect current state."
                    status_code = response.status_code
                else:
                    if (not isinstance(value, dict) or value.get("status") != "policy_saved"
                            or value.get("operation_id") != review.request_id
                            or type(value.get("changed_targets")) is not int or value["changed_targets"] not in (0, 1)
                            or type(value.get("managed_revision")) is not int
                            or value["managed_revision"] != review.managed_revision + 1
                            or type(value.get("replayed")) is not bool):
                        raise ValueError("Invalid policy receipt")
                    result = value
        except (httpx.HTTPError, ValueError, TypeError):
            message = "Retirement outcome is unknown. Retry this same review/key; do not prepare a new request merely to retry."
            status_code = 503
        # Optional status failure does not negate a validated durable receipt.
        try:
            with api_client(settings) as client:
                response = client.get("/api/v1/status")
                if response.status_code == 200 and isinstance(response.json(), dict):
                    state = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        return retirement_view(request, identity, review, state, result=result, message=message,
                               confirm_ip=str(review.ip), status_code=status_code)

    @app.post("/managed-shuns/handoffs/{request_id}/cancel")
    async def cancel_waiting_cleanup(request: Request, request_id: UUID) -> Response:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf"}, max_bytes=4096)
        require_csrf(request, fields.get("csrf", [""])[0])
        return await run_in_threadpool(cancel_waiting_cleanup_request, request, request_id, identity, "managed-removal-handoffs")

    @app.post("/managed-shuns/fleet-waits/{request_id}/cancel")
    async def cancel_waiting_fleet_cleanup(request: Request, request_id: UUID) -> Response:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf"}, max_bytes=4096)
        require_csrf(request, fields.get("csrf", [""])[0])
        return await run_in_threadpool(cancel_waiting_cleanup_request, request, request_id, identity, "managed-fleet-removals")

    def cancel_waiting_cleanup_request(request, request_id, identity, resource):
        try:
            with api_client(settings) as client:
                response = client.post(f"/api/v1/{resource}/{request_id}/cancel", json=identity.__dict__)
            if response.status_code == 200:
                value = response.json()
                if (not isinstance(value, dict) or value.get("status") != "cancelled"
                        or value.get("request_id") != str(request_id) or type(value.get("changed")) is not bool
                        or value.get("maintenance_reenabled") is not False or value.get("add_cancelled") is not False):
                    raise ValueError("Invalid cleanup cancellation receipt")
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise HTTPException(503, "Cleanup cancellation was not confirmed; inspect the handoff state before retrying.") from error
        return queued_result(request, response, "/managed-shuns")

    def managed_review_view(request, identity, review, refresh, *, message=None, status_code=200):
        return render(request, "managed-remove-review.html", {
            "identity": identity, "review": review, "refresh": refresh, "message": message,
            "active_page": "managed", "auto_request": False, "frozen_view": True,
        }, status_code)

    @app.post("/managed-shuns/removal-review", response_class=HTMLResponse)
    async def prepare_managed_removal(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "target", "reason"}, max_bytes=16384)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            raw_device, raw_ip = fields.get("target", [""])[0].split(":")
            device_id = int(raw_device)
            if raw_device != str(device_id):
                raise ValueError("Non-canonical device ID")
            ip = IPv4Address(raw_ip)
        except ValueError as error:
            raise HTTPException(422, "Choose an exact managed device and IPv4 address.") from error
        return await run_in_threadpool(prepare_managed_review, request, identity, device_id, ip,
                                       fields.get("reason", [""])[0])

    def prepare_managed_review(request, identity, device_id, ip, reason):
        try:
            with api_client(settings) as client:
                refresh = client.get("/api/v1/status")
                policy = client.get("/api/v1/managed-shuns")
            if refresh.status_code != 200 or policy.status_code != 200:
                raise httpx.RequestError("Managed review state unavailable")
            review = managed_reviews.prepare(
                identity.subject, request.cookies.get("ftd_shun_csrf", ""), policy.json(), device_id, ip,
                min(900, settings.sensitive_action_max_age_seconds), reason,
            )
            state = refresh.json()
            if not isinstance(state, dict):
                raise TypeError("Invalid status")
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise HTTPException(422, "Invalid managed review data; nothing was submitted.") from error
        except httpx.HTTPError as error:
            raise HTTPException(503, "Managed review is unavailable; nothing was submitted.") from error
        return managed_review_view(request, identity, review, state)

    @app.post("/managed-shuns/fleet-removal-review", response_class=HTMLResponse)
    async def prepare_managed_fleet_removal(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "ip", "reason"}, max_bytes=16384)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            ip = IPv4Address(fields.get("ip", [""])[0])
        except ValueError as error:
            raise HTTPException(422, "Enter one exact IPv4 address for fleet review.") from error
        return await run_in_threadpool(prepare_managed_fleet_review, request, identity, ip,
                                       fields.get("reason", [""])[0])

    def prepare_managed_fleet_review(request, identity, ip, reason):
        try:
            with api_client(settings) as client:
                response = client.get(f"/api/v1/managed-removal-scope/{ip}")
                refresh = client.get("/api/v1/status")
            if response.status_code == 409:
                raise ReviewUnavailable("No complete fleet scope could be prepared. Inspect current targets and limits.")
            if response.status_code != 200 or refresh.status_code != 200:
                raise httpx.RequestError("Fleet review state unavailable")
            review = managed_reviews.prepare_fleet(
                identity.subject, request.cookies.get("ftd_shun_csrf", ""), response.json(), ip,
                min(900, settings.sensitive_action_max_age_seconds), reason,
            )
            state = refresh.json()
            if not isinstance(state, dict):
                raise TypeError("Invalid status")
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise HTTPException(422, "Invalid fleet review data; nothing was submitted.") from error
        except httpx.HTTPError as error:
            raise HTTPException(503, "Fleet review is unavailable; nothing was submitted.") from error
        return managed_review_view(request, identity, review, state)

    @app.post("/managed-shuns/removal-confirm", response_class=HTMLResponse)
    async def confirm_managed_removal(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        require_managed_operator(identity)
        fields = await preview_form(request, allowed={"csrf", "review", "confirm_ip"}, max_bytes=4096)
        require_csrf(request, fields.get("csrf", [""])[0])
        try:
            review = managed_reviews.get(fields.get("review", [""])[0], identity.subject,
                                         request.cookies.get("ftd_shun_csrf", ""))
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        if fields.get("confirm_ip", [""])[0] != str(review.ip):
            raise HTTPException(422, "Type the exact IPv4 address shown in the review.")
        # Deliberately no admission call, even if upstream status advertises a flag.
        # Recovery, shared-worker and fleet/protection gates remain incomplete.
        return managed_review_view(request, identity, review, None,
                                   message="Execution is unavailable. No policy change or queue request was submitted.",
                                   status_code=503)

    @app.get("/protected-ips", response_class=HTMLResponse)
    def protected_ips(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                refresh = client.get("/api/v1/status")
                policy = client.get("/api/v1/protected-ips")
        except httpx.HTTPError as error:
            raise HTTPException(503, "State API is unavailable.") from error
        if refresh.status_code != 200 or policy.status_code != 200:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        return render(request, "protected-ips.html", {
            "identity": identity, "refresh": refresh.json(), "policy": policy.json(),
            "active_page": "protected", "auto_request": False,
        })

    @app.post("/protected-ips/{action}")
    def change_policy(request: Request, action: Literal["add", "edit", "delete"],
                      ip: Annotated[IPv4Address, Form()], revision: Annotated[int, Form(ge=0)],
                      csrf: str = Form(...), name: str = Form("", max_length=100),
                      comment: str = Form("", max_length=500), enabled: str = Form("false"),
                      confirm_ip: str = Form(""), managed_revision: int | None = Form(None, ge=0),
                      confirm_maintenance_resume: str = Form("false")) -> Response:
        require_csrf(request, csrf)
        identity = identity_from_request(request, settings.development_auth)
        if enabled not in {"true", "false"} or confirm_maintenance_resume not in {"true", "false"}:
            raise HTTPException(422, "invalid enabled state or maintenance acknowledgement")
        try:
            with api_client(settings) as client:
                response = client.post(f"/api/v1/protected-ips/{ip}/{action}", json={
                    "actor": identity.__dict__, "revision": revision, "name": name,
                    "comment": comment, "enabled": enabled == "true", "confirm_ip": confirm_ip,
                    "managed_revision": managed_revision,
                    "confirm_maintenance_resume": confirm_maintenance_resume == "true",
                })
        except httpx.HTTPError as error:
            raise HTTPException(503, "Policy save was not confirmed. Check the current list before retrying.") from error
        return queued_result(request, response, "/protected-ips")

    @app.get("/history", response_class=HTMLResponse)
    def events_page(request: Request, page: Annotated[int, Query(ge=1, le=2**31 - 1)] = 1,
                    anchor: UUID | None = None) -> Response:
        identity = identity_from_request(request, settings.development_auth)
        parameters: dict[str, str | int] = {"page": page}
        if anchor is not None:
            parameters["anchor"] = str(anchor)
        try:
            with api_client(settings) as client:
                refresh = client.get("/api/v1/status")
                events = client.get("/api/v1/history-page", params=parameters)
        except httpx.HTTPError as error:
            raise HTTPException(503, "State API is unavailable.") from error
        if refresh.status_code != 200 or events.status_code not in {200, 410}:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        pagination = events.json() if events.status_code == 200 else {
            "events": [], "page": 1, "pages": 1, "total": 0, "page_size": 100,
            "anchor": None, "expired": True,
        }
        if page > 1 and anchor is None and pagination["anchor"]:
            return RedirectResponse("/history?" + urlencode({"page": pagination["page"], "anchor": pagination["anchor"]}), 303)
        return render(request, "history.html", {"identity": identity, "refresh": refresh.json(),
            "recent_events": pagination["events"], "pagination": pagination,
            "anchored_history": anchor is not None,
            "active_page": "history", "auto_request": False})

    @app.post("/refresh")
    def request_refresh(
        request: Request, csrf: str = Form(...), q: str = Form("")
    ) -> Response:
        require_csrf(request, csrf)
        identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                response = client.post("/api/v1/refresh-hint")
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="State API is unavailable.") from error
        if response.status_code != 202:
            raise HTTPException(response.status_code, response.text)
        if "application/json" in request.headers.get("accept", ""):
            try:
                payload = response.json()
                return JSONResponse(refresh_metadata(payload["refresh"]))
            except (KeyError, TypeError, ValueError) as error:
                raise HTTPException(
                    status_code=503, detail="State API returned invalid refresh status."
                ) from error
        target = "/" if not q else f"/?{urlencode({'q': q})}"
        return RedirectResponse(url=target, status_code=303)

    @app.get("/shuns/{ip}", response_class=HTMLResponse)
    def detail(request: Request, ip: IPv4Address) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        with api_client(settings) as client:
            refresh_status = client.get("/api/v1/status")
            response = client.get(f"/api/v1/shuns/{ip}")
            history = client.get(f"/api/v1/history/{ip}")
        if response.status_code != 200 or history.status_code != 200:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        refresh = refresh_status.json() if refresh_status.status_code == 200 else None
        policy_ips = protected_policy_ips(refresh)
        return render(
            request,
            "detail.html",
            {
                "identity": identity,
                "ip": ip,
                "shuns": response.json(),
                "events": history.json(),
                "refresh": refresh,
                "is_trusted_policy_ip": str(ip) in policy_ips,
                "is_disabled_policy_ip": str(ip) in protected_policy_ips(refresh, enabled=False),
            },
        )

    @app.post("/devices/{device_id}/shuns/{ip}/remove")
    def remove_device(
        request: Request, device_id: int, ip: IPv4Address,
        request_id: Annotated[UUID, Form()], csrf: str = Form(...),
    ) -> Response:
        require_csrf(request, csrf)
        identity = identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                response = client.request(
                    "DELETE", f"/api/v1/devices/{device_id}/shuns/{ip}", json=identity.__dict__,
                    headers={"Idempotency-Key": str(request_id)},
                )
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503,
                detail="Queue admission was not confirmed. Retry with the same operation key.",
            ) from error
        return queued_result(request, response, f"/shuns/{ip}")

    @app.post("/shuns/{ip}/remove-all")
    def remove_all(request: Request, ip: IPv4Address, request_id: Annotated[UUID, Form()],
                   csrf: str = Form(...), confirm_ip: str = Form(...)) -> Response:
        require_csrf(request, csrf)
        if confirm_ip != str(ip):
            raise HTTPException(status_code=400, detail="confirmation must match the IP address")
        identity = identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                response = client.post(f"/api/v1/shuns/{ip}/remove-all", json=identity.__dict__,
                                       headers={"Idempotency-Key": str(request_id)})
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503,
                detail="Queue admission was not confirmed. Retry with the same operation key.",
            ) from error
        return queued_result(request, response, f"/shuns/{ip}")

    @app.post("/operations/{operation_id}/cancel")
    def cancel_operation(request: Request, operation_id: UUID, csrf: str = Form(...)) -> Response:
        require_csrf(request, csrf)
        identity = identity_from_request(request, settings.development_auth)
        try:
            with api_client(settings) as client:
                response = client.post(f"/api/v1/operations/{operation_id}/cancel", json=identity.__dict__)
        except httpx.HTTPError as error:
            raise HTTPException(503, "Cancellation was not confirmed; check the operation queue.") from error
        return queued_result(request, response, "/")

    return app


def main() -> None:
    settings = Settings.from_environment()
    uvicorn.run(create_app(settings), uds=settings.web_socket, log_level="info")
