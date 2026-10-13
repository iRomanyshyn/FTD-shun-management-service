"""Browser-facing BFF protected by Caddy and Authelia ForwardAuth."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


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
    if not username:
        raise HTTPException(status_code=401, detail="authentication required")
    roles = tuple(sorted({GROUP_TO_ROLE[group.strip()] for group in groups.split(",") if group.strip() in GROUP_TO_ROLE}))
    return Identity(subject=username, display_name=request.headers.get("remote-name", username), roles=roles)


def csrf_token(request: Request) -> tuple[str, bool]:
    token = request.cookies.get("ftd_shun_csrf")
    return (token, False) if token else (secrets.token_urlsafe(32), True)


def require_csrf(request: Request, supplied: str) -> None:
    existing = request.cookies.get("ftd_shun_csrf", "")
    if not existing or not hmac.compare_digest(existing, supplied):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def api_client(settings: Settings) -> httpx.Client:
    transport = httpx.HTTPTransport(uds=settings.api_socket)
    return httpx.Client(transport=transport, base_url="http://ftd-internal", timeout=15)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="FTD Shun Manager", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

    def render(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
        token, set_cookie = csrf_token(request)
        response = templates.TemplateResponse(
            request, name, {**context, "csrf_token": token}, status_code=status_code
        )
        if set_cookie:
            response.set_cookie("ftd_shun_csrf", token, secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        with api_client(settings) as client:
            response = client.get("/api/v1/shuns")
        if response.status_code != 200:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        return render(request, "index.html", {"identity": identity, "shuns": response.json()})

    @app.get("/shuns/{ip}", response_class=HTMLResponse)
    def detail(request: Request, ip: IPv4Address) -> HTMLResponse:
        identity = identity_from_request(request, settings.development_auth)
        with api_client(settings) as client:
            response = client.get(f"/api/v1/shuns/{ip}")
            history = client.get(f"/api/v1/history/{ip}")
        if response.status_code != 200 or history.status_code != 200:
            return render(request, "error.html", {"message": "State API is unavailable."}, 503)
        return render(
            request,
            "detail.html",
            {"identity": identity, "ip": ip, "shuns": response.json(), "events": history.json()},
        )

    @app.post("/devices/{device_id}/shuns/{ip}/remove")
    def remove_device(
        request: Request, device_id: int, ip: IPv4Address, csrf: str = Form(...)
    ) -> RedirectResponse:
        require_csrf(request, csrf)
        identity = identity_from_request(request, settings.development_auth)
        with api_client(settings) as client:
            response = client.request(
                "DELETE", f"/api/v1/devices/{device_id}/shuns/{ip}", json=identity.__dict__
            )
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        return RedirectResponse(url=f"/shuns/{ip}", status_code=303)

    @app.post("/shuns/{ip}/remove-all")
    def remove_all(request: Request, ip: IPv4Address, csrf: str = Form(...), confirm_ip: str = Form(...)) -> RedirectResponse:
        require_csrf(request, csrf)
        if confirm_ip != str(ip):
            raise HTTPException(status_code=400, detail="confirmation must match the IP address")
        identity = identity_from_request(request, settings.development_auth)
        with api_client(settings) as client:
            response = client.post(f"/api/v1/shuns/{ip}/remove-all", json=identity.__dict__)
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        return RedirectResponse(url="/", status_code=303)

    return app


def main() -> None:
    settings = Settings.from_environment()
    uvicorn.run(create_app(settings), uds=settings.web_socket, log_level="info")
