"""Optional managed-policy reads and footer, synthetic ASGI/SQLite only."""

import asyncio
import re
import tomllib
from dataclasses import replace
from ipaddress import IPv4Address
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import __version__, web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.managed_shuns import ManagedShuns, canonical_managed_change
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    settings = replace(Settings.from_environment(), database_path=store.path,
                       device_inventory_path=None, development_auth=False, agent_mode="disabled")
    api = create_app(settings, store)
    store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    calls = []
    def internal(request):
        calls.append(request)
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, request.url.path)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        return asyncio.run(send())
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, api, web.create_app(settings), calls


def grant(store):
    registry = ManagedShuns(store)
    registry.initialize()
    targets = [(1, IPv4Address("198.51.100.251"))]
    with store._connection() as db:
        protected_revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    digest = canonical_managed_change("MAINTAIN", targets, 0, protected_revision, "<b>Fixture</b>", "<script>not executable</script>")[2]
    registry.change(str(uuid4()), "MAINTAIN", targets, 0, protected_revision, digest,
                    "alice", "Alice", ("Operator",), "<b>Fixture</b>", "<script>not executable</script>")
    return registry


def test_version_has_one_source_and_all_base_pages_include_normal_footer():
    config = tomllib.loads(Path("pyproject.toml").read_text())
    assert "version" not in config["project"] and "version" in config["project"]["dynamic"]
    assert config["tool"]["hatch"]["version"]["path"] == "src/ftd_shun_manager/__init__.py"
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.a-z0-9]+)?", __version__)
    html = web.templates.get_template("error.html").render(message="Fixture")
    assert f'<span data-product-version>v{__version__}</span>' in html
    assert html.index("</main>") < html.index('<footer class="app-footer"')


def test_optional_api_read_does_not_initialize_adopt_or_mutate(lab):
    store, api, _, _ = lab
    before = store.list_events()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            for _ in range(2):
                view = await client.get("/api/v1/managed-shuns")
                assert view.status_code == 200 and view.headers["cache-control"] == "no-store"
                assert view.json() == {"initialized": False, "revision": 0, "restoration_suspended": True,
                                       "limit": 1000, "entries": [], "read_only": True, "controller_available": False}
                status = (await client.get("/api/v1/status")).json()
                assert status["managed_policy_revision"] == 0 and status["managed_policy_initialized"] is False
                assert status["managed_policy_available"] is True
            for method in ("POST", "PUT", "DELETE"):
                assert (await client.request(method, "/api/v1/managed-shuns", json={})).status_code == 405
    asyncio.run(scenario())
    with store._connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'managed_shun_%'").fetchall()
    assert store.list_events() == before


@pytest.mark.parametrize("groups", ["", "ftd-shun-viewers", "ftd-shun-operators", "ftd-shun-administrators"])
def test_bff_view_requires_auth_read_only_for_all_roles_and_escapes_metadata(lab, groups):
    store, _, app, calls = lab
    grant(store)
    before = store.list_events()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test") as client:
            assert (await client.get("/managed-shuns")).status_code == 401
            assert not calls
            client.headers.update({"Remote-User": "viewer", "Remote-Groups": groups})
            response = await client.get("/managed-shuns")
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            assert 'href="/managed-shuns" aria-current="page"' in response.text
            assert "Maintain presence" in response.text and "Not currently observed" in response.text
            assert "Controller not implemented" in response.text and "Not recorded" in response.text
            assert "&lt;b&gt;Fixture&lt;/b&gt;" in response.text and "<script>not executable</script>" not in response.text
            assert "Alice (alice)" in response.text and f"v{__version__}" in response.text
            assert 'data-auto-request="false"' in response.text
            region = response.text.split('id="managed-shun-state"')[1].split("</section>")[0]
            assert "<form" not in region and "<button" not in region
            status = (await client.get("/refresh-status")).json()
            assert status["managed_policy_revision"] == 1 and status["managed_policy_initialized"] is True
            assert all(call.method == "GET" for call in calls)
            assert all(call.url.path != "/api/v1/refresh-hint" for call in calls)
    asyncio.run(scenario())
    assert store.list_events() == before


def test_uninitialized_and_partial_registry_have_distinct_fail_closed_views(lab):
    store, api, app, _ = lab
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                                     headers={"Remote-User": "viewer"}) as client:
            response = await client.get("/managed-shuns")
            assert response.status_code == 200 and "has not been initialized" in response.text
            with store._connection() as db:
                db.execute("CREATE TABLE managed_shun_registry(id INTEGER)")
            response = await client.get("/managed-shuns")
            assert response.status_code == 503 and "unavailable" in response.text
            assert "has not been initialized" not in response.text and "sqlite" not in response.text
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            status = (await client.get("/api/v1/status")).json()
            assert status["status"] == "ready" and status["managed_policy_available"] is False
            assert status["managed_policy_revision"] is None
            assert (await client.get("/api/v1/shuns")).status_code == 200
    asyncio.run(scenario())


def test_managed_status_and_views_report_changes_without_claiming_restoration(lab):
    store, api, app, _ = lab
    registry = grant(store)
    store.record_observed_shun(1, IPv4Address("198.51.100.251"), "management")
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                                     headers={"Remote-User": "viewer"}) as client:
            assert "Observed present" in (await client.get("/managed-shuns")).text
            store.reconcile_snapshot(1, [])
            assert "Not currently observed" in (await client.get("/managed-shuns")).text
            targets = [(1, IPv4Address("198.51.100.251"))]
            digest = canonical_managed_change("RETIRE", targets, 1, 1)[2]
            registry.change(str(uuid4()), "RETIRE", targets, 1, 1, digest, "alice", "Alice", ("Operator",))
            response = await client.get("/managed-shuns")
            assert "Maintenance stopped" in response.text
            assert (await client.get("/refresh-status")).json()["managed_policy_revision"] == 2
    asyncio.run(scenario())
    assert api.state.synchronizer.queue.status()["counts"] == {}
