import asyncio
import json
from ipaddress import IPv4Address
from uuid import uuid4

import httpx

from ftd_shun_manager import web
from ftd_shun_manager.config import Settings
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer


def test_bff_refresh_authentication_csrf_and_read_only_status(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db", device_inventory_path=None,
        agent_socket="/unused/agent.sock", web_socket="/unused/web.sock",
        api_socket="/unused/api.sock", agent_mode="disabled", agent_timeout_seconds=45,
        poll_interval_seconds=300, interactive_refresh_min_interval_seconds=60,
        history_retention_days=366, sensitive_action_max_age_seconds=86400,
        development_auth=False, trusted_auto_remove_ips=frozenset(),
    )
    store = Store(settings.database_path)
    store.initialize()
    store.upsert_device(Device(1, "lab", IPv4Address("192.0.2.10"), True), "ssh-ed25519 AAAA")
    synchronizer = Synchronizer(store, object(), 300, 60)
    requests = []

    def internal(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v1/refresh-hint":
            return httpx.Response(202, json={"refresh": synchronizer.request_activity()})
        return httpx.Response(200, json={**synchronizer.status(), "private_unused": "excluded"})

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(
        transport=httpx.MockTransport(internal), base_url="http://internal",
    ))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web.create_app(settings)), base_url="https://lab.test",
        ) as client:
            assert (await client.get("/refresh-status")).status_code == 401
            assert requests == []
            client.headers["Remote-User"] = "viewer"
            response = await client.get("/refresh-status")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["devices"]["1"]["hostname"] == "lab"
            assert "private_unused" not in response.json()
            assert requests == [("GET", "/api/v1/status")]
            response = await client.post("/refresh", data={"csrf": "invalid"})
            assert response.status_code == 403
            assert len(requests) == 1
            client.cookies.set("ftd_shun_csrf", "token")
            response = await client.post(
                "/refresh", data={"csrf": "token"}, headers={"Accept": "application/json"},
            )
            assert response.status_code == 200
            assert response.json()["interactive_refresh_state"] == "queued"
            assert response.headers["cache-control"] == "no-store"
            assert requests[-1] == ("POST", "/api/v1/refresh-hint")

    asyncio.run(scenario())


def test_bff_queue_submission_uses_trusted_identity_and_preserves_operation_key(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "state.db", device_inventory_path=None,
        agent_socket="/unused/agent.sock", web_socket="/unused/web.sock",
        api_socket="/unused/api.sock", agent_mode="disabled", agent_timeout_seconds=45,
        poll_interval_seconds=300, interactive_refresh_min_interval_seconds=60,
        history_retention_days=366, sensitive_action_max_age_seconds=86400,
        development_auth=False, trusted_auto_remove_ips=frozenset(),
    )
    store = Store(settings.database_path)
    store.initialize()
    synchronizer = Synchronizer(store, object(), 300, 60)
    captured = []
    key = str(uuid4())

    def internal(request):
        captured.append(request)
        if request.method == "DELETE":
            return httpx.Response(202, json={"status": "accepted", "operation_id": key})
        return httpx.Response(200, json=synchronizer.status())

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(
        transport=httpx.MockTransport(internal), base_url="http://internal",
    ))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web.create_app(settings)), base_url="https://lab.test",
            headers={"Remote-User": "alice", "Remote-Groups": "ftd-shun-operators", "Accept": "application/json"},
        ) as client:
            data = {"csrf": "token", "request_id": key, "subject": "forged", "roles": "Administrator"}
            assert (await client.post("/devices/1/shuns/198.51.100.10/remove", data=data)).status_code == 403
            assert not captured
            client.cookies.set("ftd_shun_csrf", "token")
            result = await client.post("/devices/1/shuns/198.51.100.10/remove", data=data)
            assert result.status_code == 200
            assert result.json()["operation_result"]["status"] == "accepted"
            assert captured[0].headers["idempotency-key"] == key
            assert json.loads(captured[0].content) == {"subject": "alice", "display_name": "alice", "roles": ["Operator"]}

    asyncio.run(scenario())
