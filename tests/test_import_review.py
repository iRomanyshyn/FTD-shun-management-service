"""Browser confirmation uses synthetic ASGI/SQLite only; no live device work."""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager import import_review, web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_preview import classify_targets, parse_blocklist, summarize_preview
from ftd_shun_manager.import_review import ImportReviews, ReviewUnavailable
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store


def hidden(html, name):
    return re.search(r'name="' + name + r'" value="([^"]+)"', html)[1]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f"lab-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       agent_mode="mock", development_auth=False, import_admission_enabled=True,
                       import_execution_enabled=False)
    api = create_app(settings, store)
    calls = []
    behavior = {}

    def internal(request):
        calls.append(request)
        if behavior.get("status_lost") and request.url.path == "/api/v1/status":
            raise httpx.ReadTimeout("Fixture", request=request)
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, request.url.path,
                                                content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        response = asyncio.run(call())
        if behavior.get("intake_disabled") and request.url.path == "/api/v1/status":
            return httpx.Response(200, json={**response.json(), "import_admission_enabled": False})
        if request.url.path == "/api/v1/imports" and behavior.pop("lose_admission", False):
            raise httpx.ReadTimeout("Reply lost after commit", request=request)
        if behavior.get("malformed") and request.url.path == "/api/v1/imports":
            return httpx.Response(202, content="broken")
        return response

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    app = web.create_app(settings)
    return store, api, app, calls, behavior


async def prepare(client, **changes):
    await client.get("/imports")
    fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "device_ids": "1",
              "text": "198.51.100.251", "label": "<b>Fixture</b>", "reason": "Fixture only"}
    fields.update(changes)
    return await client.post("/imports/review", data=fields)


def browser(app, *, subject="alice", group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


def test_review_freezes_exact_pairs_excludes_rows_escapes_and_only_confirm_admits(lab):
    store, api, app, calls, _ = lab
    policy = ProtectedPolicy(store)
    policy.change("add", IPv4Address("198.51.100.10"), policy.revision(), "fixture", "Fixture", ())
    store.record_observed_shun(1, IPv4Address("203.0.113.20"), "management")
    before = store.list_events()

    async def scenario():
        async with browser(app) as client:
            source = "198.51.100.10 # secret source\n203.0.113.20\n198.51.100.251\n198.51.100.251\n555.555.555.666"
            page = await prepare(client, text=source, device_ids=["1", "2"])
            assert page.status_code == 200
            assert "3 exact device/IP targets" in page.text
            assert "&lt;b&gt;Fixture&lt;/b&gt;" in page.text and "<b>Fixture</b>" not in page.text
            assert "secret source" not in page.text and "555.555.555.666" not in page.text
            assert "lab-1" in page.text and "lab-2" in page.text
            assert store.list_events() == before
            assert not any(r.url.path == "/api/v1/imports" for r in calls)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": hidden(page.text, "review"), "confirm_count": "3"}
            accepted = await client.post("/imports/confirm", data=fields)
            assert accepted.status_code == 200 and "accepted into Queue" in accepted.text
            assert "not verified device success" in accepted.text and 'name="review"' not in accepted.text
            admission = next(r for r in calls if r.url.path == "/api/v1/imports")
            body = json.loads(admission.content)
            assert body["actor"] == {"subject": "alice", "display_name": "alice", "roles": ["Operator"]}
            assert body["targets"] == [{"device_id": 1, "ip": "198.51.100.251"},
                                       {"device_id": 2, "ip": "198.51.100.251"},
                                       {"device_id": 2, "ip": "203.0.113.20"}]
            assert b"secret source" not in admission.content
            assert (await client.post("/imports/confirm", data=fields)).status_code == 200
            assert api.state.synchronizer.queue.status()["counts"] == {"QUEUED": 3}
            assert not api.state.synchronizer.queue.has_pending(), "Held ADD must not accelerate cycles"
            assert all(r.url.path != "/api/v1/refresh-hint" for r in calls)
    asyncio.run(scenario())


def test_review_and_confirm_require_identity_current_role_csrf_and_exact_count(lab):
    _, _, app, calls, _ = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": hidden(page.text, "review"), "confirm_count": "1"}
            for csrf in ("", "wrong", "неправильно"):
                assert (await client.post("/imports/confirm", data={**fields, "csrf": csrf})).status_code == 403
            for count in ("", "2", "01", "1 "):
                assert (await client.post("/imports/confirm", data={**fields, "confirm_count": count})).status_code == 422
            for extra in ({"actor": "forged"}, {"targets": "1"}, {"policy_revision": "0"}, {"confirmation_digest": "x"}, {"request_id": "x"}):
                assert (await client.post("/imports/confirm", data={**fields, **extra})).status_code == 422
            client.headers["Remote-User"] = "bob"
            assert (await client.post("/imports/confirm", data=fields)).status_code == 409
            client.headers["Remote-User"] = "alice"
            client.cookies.set("ftd_shun_csrf", "different", domain="lab.test", path="/")
            assert (await client.post("/imports/confirm", data={**fields, "csrf": "different"})).status_code == 409
            for group in ("ftd-shun-viewers", ""):
                client.headers["Remote-Groups"] = group
                assert (await client.post("/imports/review", data={})).status_code == 403
                assert (await client.post("/imports/confirm", data=fields)).status_code == 403
            del client.headers["Remote-User"]
            assert (await client.post("/imports/review", data={})).status_code == 401
            assert (await client.post("/imports/confirm", data=fields)).status_code == 401
            assert not any(r.url.path == "/api/v1/imports" for r in calls)
    asyncio.run(scenario())


def test_lost_reply_retries_original_key_and_body_without_reclassification(lab):
    store, api, app, calls, behavior = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": hidden(page.text, "review"), "confirm_count": "1"}
            behavior["lose_admission"] = True
            lost = await client.post("/imports/confirm", data=fields)
            assert lost.status_code == 503 and "not confirmed" in lost.text
            assert hidden(lost.text, "review") == fields["review"]
            policy = ProtectedPolicy(store)
            policy.change("add", IPv4Address("192.0.2.99"), policy.revision(), "fixture", "Fixture", ())
            retry = await client.post("/imports/confirm", data=fields)
            assert retry.status_code == 200 and "already accepted" in retry.text
            admissions = [r for r in calls if r.url.path == "/api/v1/imports"]
            assert len(admissions) == 2
            assert admissions[0].content == admissions[1].content
            assert admissions[0].headers["idempotency-key"] == admissions[1].headers["idempotency-key"]
            assert api.state.synchronizer.queue.status()["counts"] == {"QUEUED": 1}
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["policy", "disabled_device", "opposite"])
def test_atomic_api_recheck_rejects_changed_review_without_new_add_work(lab, change):
    store, api, app, _, _ = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            if change == "policy":
                policy = ProtectedPolicy(store)
                policy.change("add", IPv4Address("198.51.100.251"), policy.revision(), "fixture", "Fixture", ())
            elif change == "disabled_device":
                store.upsert_device(Device(1, "lab-1", IPv4Address("192.0.2.1"), False), "ssh-ed25519 AAAA")
            else:
                api.state.synchronizer.queue.enqueue("fixture", [(1, IPv4Address("198.51.100.251"))], "bob", "Bob", ("Operator",))
            before = store.list_events()
            result = await client.post("/imports/confirm", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                                      "review": hidden(page.text, "review"), "confirm_count": "1"})
            assert result.status_code in (409, 422)
            assert store.list_events() == before
            assert not any(j["action"] == "ADD" for j in api.state.synchronizer.queue.status()["items"])
    asyncio.run(scenario())


def test_disabled_intake_unknown_status_and_expired_or_restarted_reviews_fail_closed(lab, monkeypatch):
    _, _, app, calls, behavior = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": hidden(page.text, "review"), "confirm_count": "1"}
            behavior["intake_disabled"] = True
            disabled = await client.post("/imports/confirm", data=fields)
            assert disabled.status_code == 503 and "No admission request was sent" in disabled.text
            assert 'type="submit" disabled' in disabled.text
            behavior.clear()
            behavior["status_lost"] = True
            assert (await client.post("/imports/confirm", data=fields)).status_code == 503
            behavior.clear()
            with monkeypatch.context() as clock:
                now = import_review.time.monotonic()
                clock.setattr(import_review.time, "monotonic", lambda: now + 601)
                assert (await client.post("/imports/confirm", data=fields)).status_code == 409
            assert (await client.get("/imports/confirm")).status_code == 405
            assert (await client.post("/imports/confirm", content="x" * 4097,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})).status_code == 413
            assert not any(r.url.path == "/api/v1/imports" for r in calls)
    asyncio.run(scenario())


def test_malformed_reply_is_unknown_and_form_retains_original_review(lab):
    _, api, app, _, behavior = lab
    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": hidden(page.text, "review"), "confirm_count": "1"}
            behavior["malformed"] = True
            unknown = await client.post("/imports/confirm", data=fields)
            assert unknown.status_code == 503 and "uncertain" in unknown.text
            assert hidden(unknown.text, "review") == fields["review"]
            behavior.clear()
            replay = await client.post("/imports/confirm", data=fields)
            assert replay.status_code == 200 and "already accepted" in replay.text
            assert api.state.synchronizer.queue.status()["counts"] == {"QUEUED": 1}
    asyncio.run(scenario())


def test_review_capacity_expiry_and_whole_target_bound(lab, monkeypatch):
    store, _, _, _, _ = lab
    def preview(count=1):
        parsed = parse_blocklist("\n".join(str(IPv4Address(0xC6120000 + i)) for i in range(count)))
        return summarize_preview(parsed, classify_targets(store, [IPv4Address(ip) for ip in parsed["ips"]], [1]))
    cache = ImportReviews()
    data = preview()
    with ThreadPoolExecutor(max_workers=5) as pool:
        reviews = list(pool.map(lambda _: cache.prepare("alice", "cookie", data, "", ""), range(5)))
    with pytest.raises(ReviewUnavailable):
        cache.prepare("alice", "cookie", data, "", "")
    for i in range(251):
        cache.prepare(f"user{i}", "cookie", data, "", "")
    with pytest.raises(ReviewUnavailable):
        cache.prepare("new", "cookie", data, "", "")
    assert cache.get(reviews[0].token, "alice", "cookie") == reviews[0]
    assert len(ImportReviews().prepare("alice", "cookie", preview(1000), "", "").targets) == 1000
    with pytest.raises(ValueError, match="1000"):
        ImportReviews().prepare("alice", "cookie", preview(1001), "", "")
    with pytest.raises(ValueError):
        ImportReviews().prepare("alice", "cookie", preview(0), "", "")
    with pytest.raises(ReviewUnavailable):
        ImportReviews().get(reviews[0].token, "alice", "cookie")
    now = import_review.time.monotonic()
    monkeypatch.setattr(import_review.time, "monotonic", lambda: now + 601)
    with pytest.raises(ReviewUnavailable):
        cache.get(reviews[0].token, "alice", "cookie")
    assert cache.prepare("alice", "cookie", data, "", "")


def test_queued_eligibility_reason_keeps_real_deferrals_and_history(lab):
    _, api, _, _, _ = lab
    queue = api.state.synchronizer.queue
    from ftd_shun_manager.import_intent import canonical_import
    targets = [(1, IPv4Address("198.51.100.251"))]
    revision = ProtectedPolicy(queue.store).revision()
    queue.enqueue("reason-fixture", targets, "alice", "Alice", ("Operator",), source="manual_import", scope="import",
                  policy_revision=revision, confirmation_digest=canonical_import(targets, revision)[2])
    assert queue.status(addition_device_ids=frozenset({1}))["items"][0]["reason"] is None
    with queue.store._connection() as db:
        db.execute("UPDATE operation_jobs SET reason='ADD execution is not enabled'")
    before = queue.store.list_events()
    assert queue.status(addition_device_ids=frozenset({1}))["items"][0]["reason"] is None
    assert queue.status()["items"][0]["reason"] == "ADD execution is not enabled"
    with queue.store._connection() as db:
        db.execute("UPDATE operation_jobs SET reason='Final snapshot reserve'")
    assert queue.status(addition_device_ids=frozenset({1}))["items"][0]["reason"] == "Final snapshot reserve"
    assert queue.store.list_events() == before
