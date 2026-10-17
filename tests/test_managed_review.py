"""Read-only handoff visibility and non-executable browser reviews; synthetic only."""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import managed_review, web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_removals import ManagedRemovals, canonical_managed_removal
from ftd_shun_manager.managed_review import ManagedRemovalReviews
from ftd_shun_manager.managed_shuns import ManagedShuns, canonical_managed_change
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       development_auth=False, agent_mode="disabled")
    api = create_app(settings, store)
    store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    registry = ManagedShuns(store)
    registry.initialize()
    revision = registry.metadata()["managed_policy_revision"]
    with store._connection() as db:
        protected_revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, protected_revision,
                    canonical_managed_change("MAINTAIN", [(1, IP)], revision, protected_revision)[2],
                    "creator", "Creator", ("Operator",))
    calls, behavior = [], {}
    def internal(request):
        calls.append(request)
        if request.url.path == "/api/v1/managed-removal-handoffs" and behavior.get("cleanup_error"):
            return httpx.Response(503, json={"detail": "Synthetic failure"})
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        result = asyncio.run(send())
        if request.url.path == "/api/v1/status" and behavior.get("pretend_enabled"):
            return httpx.Response(200, json={**result.json(), "managed_removal_admission_enabled": True})
        return result
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, registry, api, web.create_app(settings), calls, behavior


def browser(app, group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                             headers={"Remote-User": "alice", "Remote-Groups": group})


async def prepare(client, **fields):
    await client.get("/managed-shuns")
    return await client.post("/managed-shuns/removal-review", data={
        "csrf": client.cookies.get("ftd_shun_csrf"), "target": "1:198.51.100.251",
        "reason": "<img src=x onerror=alert(1)>", **fields,
    })


def token(page):
    return re.search(r'name="review" value="([^"]+)"', page.text)[1]


def test_review_is_frozen_non_executable_and_server_refuses_direct_submission(lab):
    store, registry, api, app, calls, behavior = lab
    before = registry.snapshot(), store.list_events()
    behavior["pretend_enabled"] = True
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            assert page.status_code == 200
            assert "Preparatory review only" in page.text and "one exact device/IP target" in page.text
            assert "Not currently observed" in page.text and "lab-1 (1)" in page.text
            assert "&lt;img" in page.text and "<img src=x" not in page.text
            assert "disabled>Stop maintenance" in page.text
            assert 'data-frozen-view="true"' in page.text and 'data-auto-request="false"' in page.text
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            response = await client.post("/managed-shuns/removal-confirm", data=fields)
            assert response.status_code == 503 and "No policy change or queue request was submitted" in response.text
            assert token(response) == fields["review"]
            assert response.headers["cache-control"] == "no-store"
            # A valid prepared review is not a reusable execution capability.
            assert (await client.post("/managed-shuns/removal-confirm", data=fields)).status_code == 503
    asyncio.run(scenario())
    assert (registry.snapshot(), store.list_events()) == before
    assert api.state.synchronizer.queue.status()["counts"] == {}
    assert all(call.method == "GET" and call.url.path != "/api/v1/refresh-hint" for call in calls)
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_removal_handoffs'").fetchone()


def test_review_validates_current_identity_csrf_scope_and_exact_confirmation(lab):
    _, _, _, app, calls, _ = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            for extra in ({"actor": "forged"}, {"managed_revision": "0"}, {"request_id": "x"}, {"target": "1:1.2.3.4"}):
                assert (await client.post("/managed-shuns/removal-confirm", data={**fields, **extra})).status_code == 422
            for wrong in ("", "198.51.100.252", str(IP) + " "):
                assert (await client.post("/managed-shuns/removal-confirm", data={**fields, "confirm_ip": wrong})).status_code == 422
            for wrong in ("", "wrong", "неправильно"):
                assert (await client.post("/managed-shuns/removal-confirm", data={**fields, "csrf": wrong})).status_code == 403
            client.headers["Remote-User"] = "bob"
            assert (await client.post("/managed-shuns/removal-confirm", data=fields)).status_code == 409
            client.headers["Remote-User"] = "alice"
            client.cookies.set("ftd_shun_csrf", "changed", domain="lab.test", path="/")
            assert (await client.post("/managed-shuns/removal-confirm", data={**fields, "csrf": "changed"})).status_code == 409
            for group in ("", "ftd-shun-viewers"):
                client.headers["Remote-Groups"] = group
                assert (await client.post("/managed-shuns/removal-review", data={})).status_code == 403
                assert (await client.post("/managed-shuns/removal-confirm", data=fields)).status_code == 403
            del client.headers["Remote-User"]
            assert (await client.post("/managed-shuns/removal-review", data={})).status_code == 401
            assert (await client.post("/managed-shuns/removal-confirm", data=fields)).status_code == 401
    asyncio.run(scenario())
    assert all(call.method == "GET" for call in calls)


@pytest.mark.parametrize("target", ["", "01:198.51.100.251", "1:198.51.100.251:more", "1:555.555.555.666",
                                   "0:198.51.100.251", "1:198.51.100.252", "2:198.51.100.251"])
def test_review_does_not_adopt_unmanaged_or_malformed_targets(lab, target):
    _, _, _, app, _, _ = lab
    async def scenario():
        async with browser(app) as client:
            response = await prepare(client, target=target)
            assert response.status_code in (409, 422)
            assert 'name="review"' not in response.text
    asyncio.run(scenario())


def test_optional_handoff_api_no_migration_partial_failure_and_no_write_methods(lab):
    store, _, api, _, _, _ = lab
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            view = await client.get("/api/v1/managed-removal-handoffs")
            assert view.status_code == 200
            assert view.json() == {"initialized": False, "counts": {}, "items": [], "display_limit": 20,
                                   "scheduler_integration_available": False, "admission_enabled": False, "read_only": True}
            for method in ("POST", "PUT", "DELETE"):
                assert (await client.request(method, "/api/v1/managed-removal-handoffs", json={})).status_code == 405
            with store._connection() as db:
                db.execute("CREATE TABLE managed_removal_handoffs(id TEXT)")
            response = await client.get("/api/v1/managed-removal-handoffs")
            assert response.status_code == 503 and "unavailable" in response.text
            assert (await client.get("/api/v1/managed-shuns")).status_code == 200
    asyncio.run(scenario())


def test_optional_cleanup_error_does_not_hide_policy_or_claim_empty_queue(lab):
    _, _, _, app, _, behavior = lab
    behavior["cleanup_error"] = True
    async def scenario():
        async with browser(app, "ftd-shun-viewers") as client:
            response = await client.get("/managed-shuns")
            assert response.status_code == 200 and "Maintain presence" in response.text
            assert "This is not an empty queue" in response.text
            assert "No recorded cleanup requests" not in response.text
            assert 'action="/managed-shuns/removal-review"' not in response.text
    asyncio.run(scenario())


def test_handoff_view_separates_admission_from_verified_result_and_escapes_diagnostics(lab):
    store, registry, api, app, _, _ = lab
    handoffs = ManagedRemovals(registry, api.state.synchronizer.queue)
    handoffs.initialize()
    revision = registry.snapshot()["revision"]
    key = str(uuid4())
    handoffs.admit(key, 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                   "alice", "<script>Actor</script>", ("Operator",))
    with store._connection() as db:
        db.execute("UPDATE managed_removal_handoffs SET reason='<img src=x onerror=alert(1)>'")
    before = store.list_events()
    async def scenario():
        async with browser(app, "ftd-shun-viewers") as client:
            response = await client.get("/managed-shuns")
            assert response.status_code == 200 and "Queued for removal" in response.text
            assert "Verified removal" not in response.text
            assert "&lt;script&gt;Actor" in response.text and "&lt;img" in response.text
            assert "<script>Actor" not in response.text and "<img src=x" not in response.text
            assert "Original authorization deadline" in response.text
    asyncio.run(scenario())
    assert store.list_events() == before


def test_cache_bounds_concurrent_admission_cookie_expiry_and_frozen_values(lab, monkeypatch):
    _, registry, _, _, _, _ = lab
    policy = registry.snapshot_if_present()
    reviews = ManagedRemovalReviews(ttl=60)
    before = policy.copy()
    review = reviews.prepare("alice", "cookie", policy, 1, IP, 120, "Fixture")
    policy["entries"][0]["hostname"] = "changed"
    policy["entries"][0]["enabled"] = False
    assert review.hostname == "lab-1" and review.maintenance_enabled
    assert review.managed_revision == before["revision"]
    assert reviews.get(review.token, "alice", "cookie") == review
    with pytest.raises(ReviewUnavailable):
        reviews.get(review.token, "alice", "other-cookie")
    def attempt(_):
        try:
            return reviews.prepare("alice", "cookie", policy, 1, IP, 120)
        except ReviewUnavailable:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(attempt, range(10)))
    assert sum(item is not None for item in result) == 4
    for i in range(251):
        reviews.prepare(f"other-{i}", "cookie", policy, 1, IP, 120)
    with pytest.raises(ReviewUnavailable, match="Too many"):
        reviews.prepare("overflow", "cookie", policy, 1, IP, 120)
    original = managed_review.time.monotonic
    monkeypatch.setattr(managed_review.time, "monotonic", lambda: original() + 61)
    with pytest.raises(ReviewUnavailable):
        reviews.get(review.token, "alice", "cookie")
    with pytest.raises(ReviewUnavailable):
        ManagedRemovalReviews().get(review.token, "alice", "cookie")
    assert review.digest == canonical_managed_removal(1, IP, review.managed_revision, 120, "Fixture")[1]


@pytest.mark.parametrize("reason", ["x" * 501, "control\x00character"])
def test_review_rejects_invalid_reason_without_mutation(lab, reason):
    store, registry, _, app, _, _ = lab
    before = registry.snapshot(), store.list_events()
    async def scenario():
        async with browser(app) as client:
            assert (await prepare(client, reason=reason)).status_code == 422
    asyncio.run(scenario())
    assert (registry.snapshot(), store.list_events()) == before
