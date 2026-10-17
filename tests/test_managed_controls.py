"""Policy revocation and waiting cancellation, using synthetic SQLite/ASGI only."""

import asyncio
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import managed_retirement_review, web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_removals import canonical_managed_removal
from ftd_shun_manager.managed_retirement_review import ManagedRetirementReviews
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


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
    maintain(registry)
    calls, behavior = [], {}

    def internal(request):
        calls.append(request)

        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        result = asyncio.run(send())
        if request.method == "POST" and behavior.pop("lose_reply", False):
            raise httpx.ReadTimeout("Synthetic committed response lost")
        if request.method == "POST" and behavior.pop("malformed", False):
            return httpx.Response(200, json={"status": "policy_saved"})
        if request.method == "POST" and behavior.pop("wrong_revision", False):
            return httpx.Response(200, json={**result.json(), "managed_revision": result.json()["managed_revision"] + 1})
        if request.method == "GET" and request.url.path == "/api/v1/status" and behavior.get("status_error"):
            return httpx.Response(503, json={"detail": "Synthetic status error"})
        return result

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, registry, api, web.create_app(settings), calls, behavior


def maintain(registry):
    revision = registry.snapshot()["revision"]
    with registry.store._connection() as db:
        protected_revision = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, protected_revision,
                    canonical_managed_change("MAINTAIN", [(1, IP)], revision, protected_revision)[2],
                    "creator", "Creator", ("Operator",))


def browser(app, *, subject="alice", group="ftd-shun-operators"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


def token(page):
    return re.search(r'name="review" value="([^"]+)"', page.text)[1]


async def prepare(client, **fields):
    await client.get("/managed-shuns")
    return await client.post("/managed-shuns/retirement-review", data={
        "csrf": client.cookies.get("ftd_shun_csrf"), "target": "1:198.51.100.251",
        "reason": "<img src=x onerror=alert(1)>", **fields,
    })


def retirement_body(registry, **overrides):
    revision = registry.snapshot()["revision"]
    return {"actor": ACTOR, "device_id": 1, "ip": str(IP), "managed_revision": revision,
            "confirmation_digest": canonical_managed_change("RETIRE", [(1, IP)], revision, 0)[2], **overrides}


def waiting(lab, *, finish=False):
    _, registry, api, _, _, _ = lab
    sync = api.state.synchronizer
    cleanup = sync.managed_removals
    cleanup.initialize()
    protected_revision = sync.policy.revision()
    sync.queue.enqueue(str(uuid4()), [(1, IP)], "creator", "Creator", ("Operator",), source="manual_import",
                       scope="import", policy_revision=protected_revision,
                       confirmation_digest=canonical_import([(1, IP)], protected_revision)[2])
    assert sync.queue.claim_cycle("synthetic-worker", 135)
    job = sync.queue.claim_addition(1, "synthetic-worker", sync.queue.cutoff(), execution_enabled=True)
    revision, key = registry.snapshot()["revision"], str(uuid4())
    cleanup.admit(key, 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                  "alice", "Alice", ("Operator",))
    if finish:
        sync.queue.finish_addition(job["id"], "synthetic-worker", "UNVERIFIED")
    return cleanup, key, job


def test_frozen_retirement_is_policy_only_audited_and_old_replay_never_retires_new_generation(lab):
    store, registry, api, app, calls, _ = lab
    initial = registry.snapshot(), store.list_events()

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            assert page.status_code == 200 and "No device command" in page.text
            assert "&lt;img" in page.text and "<img src=x" not in page.text
            assert 'data-frozen-view="true"' in page.text and 'data-auto-request="false"' in page.text
            assert (registry.snapshot(), store.list_events()) == initial
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            response = await client.post("/managed-shuns/retirement-confirm", data=fields)
            assert response.status_code == 200 and "Recorded policy-only result" in response.text
            assert 'action="/managed-shuns/retirement-confirm"' not in response.text
            assert not registry.snapshot()["entries"][0]["enabled"]
            event = next(e for e in store.list_events() if e["event_type"] == "MANAGED_SHUN_RETIRED")
            assert event["actor_subject"] == "alice" and event["actor_roles"] == ["Operator"]
            assert api.state.synchronizer.queue.status()["counts"] == {}
            maintain(registry)
            before = registry.snapshot(), store.list_events()
            replay = await client.post("/managed-shuns/retirement-confirm", data=fields)
            assert replay.status_code == 200 and "Original-key replay" in replay.text
            assert (registry.snapshot(), store.list_events()) == before
            posts = [r for r in calls if r.method == "POST"]
            assert len(posts) == 2 and all(r.url.path == "/api/v1/managed-shuns/retire" for r in posts)
            assert posts[0].content == posts[1].content
            assert posts[0].headers["Idempotency-Key"] == posts[1].headers["Idempotency-Key"]
            assert not api.state.synchronizer._activity.is_set()
            assert replay.headers["cache-control"] == "no-store"
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["lose_reply", "malformed", "wrong_revision"])
def test_unknown_reply_preserves_frozen_retry_key_and_never_submits_new_intent(lab, failure):
    store, registry, _, app, calls, behavior = lab

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            behavior[failure] = True
            lost = await client.post("/managed-shuns/retirement-confirm", data=fields)
            assert lost.status_code == 503 and "outcome is unknown" in lost.text
            assert token(lost) == fields["review"] and 'value="198.51.100.251"' in lost.text
            before = registry.snapshot(), store.list_events()
            retry = await client.post("/managed-shuns/retirement-confirm", data=fields)
            assert retry.status_code == 200 and "Original-key replay" in retry.text
            assert (registry.snapshot(), store.list_events()) == before
            assert len({r.headers["Idempotency-Key"] for r in calls if r.method == "POST"}) == 1
    asyncio.run(scenario())


def test_revocation_works_for_absent_protected_disabled_device_during_recovery(lab):
    store, registry, api, app, _, _ = lab
    with store._connection() as db:
        db.execute("UPDATE devices SET enabled=0 WHERE id=1")
        db.execute("UPDATE operation_executor SET mutations_suspended=1 WHERE id=1")
    # The snapshot exposes protection independently; no adoption or device write.
    api.state.synchronizer.policy.change("add", IP, api.state.synchronizer.policy.revision(),
                                         "policy-admin", "Policy Admin", ("Administrator",))

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            assert page.status_code == 200 and "Disabled — retirement is still allowed" in page.text
            assert "Not currently observed" in page.text and "Enabled protection takes priority" in page.text
            result = await client.post("/managed-shuns/retirement-confirm", data={
                "csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)})
            assert result.status_code == 200 and not registry.snapshot()["entries"][0]["enabled"]
            assert api.state.synchronizer.queue.status()["counts"] == {}
            assert api.state.synchronizer.queue.mutations_suspended()
    asyncio.run(scenario())


def test_review_rechecks_roles_csrf_scope_binding_and_cross_purpose_tokens(lab):
    _, registry, _, app, calls, _ = lab

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            for extra in ({"actor": "forged"}, {"managed_revision": "0"}, {"request_id": "x"}, {"action": "MAINTAIN"}):
                assert (await client.post("/managed-shuns/retirement-confirm", data={**fields, **extra})).status_code == 422
            assert (await client.post("/managed-shuns/retirement-confirm", data={**fields, "confirm_ip": "wrong"})).status_code == 422
            assert (await client.post("/managed-shuns/retirement-confirm", data={**fields, "csrf": "wrong"})).status_code == 403
            assert (await client.post("/managed-shuns/removal-confirm", data=fields)).status_code == 409
            removal = await client.post("/managed-shuns/removal-review", data={"csrf": fields["csrf"], "target": f"1:{IP}"})
            assert (await client.post("/managed-shuns/retirement-confirm", data={**fields, "review": token(removal)})).status_code == 409
            client.headers["Remote-User"] = "bob"
            assert (await client.post("/managed-shuns/retirement-confirm", data=fields)).status_code == 409
            client.headers["Remote-User"] = "alice"
            client.headers["Remote-Groups"] = "ftd-shun-viewers"
            assert (await client.post("/managed-shuns/retirement-confirm", data=fields)).status_code == 403
            assert (await client.post("/managed-shuns/retirement-review", data={})).status_code == 403
            del client.headers["Remote-User"]
            assert (await client.post("/managed-shuns/retirement-confirm", data=fields)).status_code == 401
    asyncio.run(scenario())
    assert registry.snapshot()["entries"][0]["enabled"]
    assert all(r.method == "GET" for r in calls)


def test_stale_review_conflict_has_no_partial_change_and_status_failure_does_not_negate_receipt(lab):
    store, registry, _, app, _, behavior = lab

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)}
            maintain(registry)  # Another reviewed request changes global revision.
            before = registry.snapshot(), store.list_events()
            response = await client.post("/managed-shuns/retirement-confirm", data=fields)
            assert response.status_code == 409 and token(response) == fields["review"]
            assert (registry.snapshot(), store.list_events()) == before
            page = await prepare(client)
            behavior["status_error"] = True
            response = await client.post("/managed-shuns/retirement-confirm", data={**fields, "review": token(page)})
            assert response.status_code == 200 and "Recorded policy-only result" in response.text
    asyncio.run(scenario())


def test_wait_cancel_is_visible_to_owner_or_admin_idempotent_and_never_cancels_add(lab):
    store, registry, api, app, _, _ = lab
    cleanup, key, job = waiting(lab)

    async def scenario():
        async with browser(app, subject="bob") as other:
            assert "Cancel waiting cleanup only" not in (await other.get("/managed-shuns")).text
            assert (await other.post(f"/managed-shuns/handoffs/{key}/cancel", data={"csrf": other.cookies.get("ftd_shun_csrf")})).status_code == 403
        async with browser(app) as owner:
            page = await owner.get("/managed-shuns")
            assert "Cancel waiting cleanup only" in page.text and "ADD may still finish" in page.text
            fields = {"csrf": owner.cookies.get("ftd_shun_csrf")}
            assert (await owner.post(f"/managed-shuns/handoffs/{key}/cancel", files={"csrf": (None, fields["csrf"])})).status_code == 415
            assert (await owner.post(f"/managed-shuns/handoffs/{key}/cancel", data={**fields, "actor": "forged"})).status_code == 422
            assert (await owner.post(f"/managed-shuns/handoffs/{key}/cancel", data={"csrf": "wrong"})).status_code == 403
            assert (await owner.post(f"/managed-shuns/handoffs/{key}/cancel", data=fields)).status_code == 303
            before = store.list_events(), api.state.synchronizer.queue.status()
            assert (await owner.post(f"/managed-shuns/handoffs/{key}/cancel", data=fields)).status_code == 303
            assert (store.list_events(), api.state.synchronizer.queue.status()) == before
            assert "Cancel waiting cleanup only" not in (await owner.get("/managed-shuns")).text
    asyncio.run(scenario())
    assert cleanup.snapshot()["items"][0]["state"] == "CANCELLED"
    assert not registry.snapshot()["entries"][0]["enabled"]
    with store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "RUNNING"
    assert not api.state.synchronizer._activity.is_set()


def test_wait_cancel_race_with_promotion_returns_conflict_without_cancelling_admitted_job(lab):
    _, _, api, app, _, _ = lab
    cleanup, key, _ = waiting(lab, finish=True)
    assert cleanup.advance("synthetic-worker") == 1

    async def scenario():
        async with browser(app) as client:
            await client.get("/managed-shuns")
            response = await client.post(f"/managed-shuns/handoffs/{key}/cancel", data={"csrf": client.cookies.get("ftd_shun_csrf")})
            assert response.status_code == 409 and "admitted queue" in response.text
    asyncio.run(scenario())
    assert cleanup.snapshot()["items"][0]["queue_state"] == "QUEUED"
    assert api.state.synchronizer.queue.status()["counts"] == {"UNVERIFIED": 1, "QUEUED": 1}


def test_private_retirement_is_strict_current_role_atomic_and_has_no_create_action(lab, monkeypatch):
    store, registry, api, _, _, _ = lab
    body = retirement_body(registry)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            for override in ({"action": "MAINTAIN"}, {"mode": "maintain_present"}, {"device_id": True}, {"managed_revision": True}):
                assert (await client.post("/api/v1/managed-shuns/retire", json={**body, **override}, headers={"Idempotency-Key": str(uuid4())})).status_code == 422
            for roles in ([], ["Viewer"]):
                assert (await client.post("/api/v1/managed-shuns/retire", json={**body, "actor": {**ACTOR, "roles": roles}}, headers={"Idempotency-Key": str(uuid4())})).status_code == 403
            assert (await client.post("/api/v1/managed-shuns/retire", json=body)).status_code == 422
            before = registry.snapshot(), store.list_events()

            def fail(*args, **kwargs):
                raise sqlite3.OperationalError("Synthetic audit failure")

            monkeypatch.setattr(store, "_insert_event", fail)
            response = await client.post("/api/v1/managed-shuns/retire", json=body, headers={"Idempotency-Key": str(uuid4())})
            assert response.status_code == 503 and "Synthetic audit" not in response.text
            assert (registry.snapshot(), store.list_events()) == before
    asyncio.run(scenario())


def test_revocation_endpoints_never_initialize_absent_schemas(tmp_path):
    store = Store(tmp_path / "state.db")
    api = create_app(replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                             agent_mode="disabled"), store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            digest = canonical_managed_change("RETIRE", [(1, IP)], 0, 0)[2]
            assert (await client.post("/api/v1/managed-shuns/retire", headers={"Idempotency-Key": str(uuid4())},
                                      json={"actor": ACTOR, "device_id": 1, "ip": str(IP), "managed_revision": 0, "confirmation_digest": digest})).status_code == 503
            assert (await client.post(f"/api/v1/managed-removal-handoffs/{uuid4()}/cancel", json=ACTOR)).status_code == 503
    asyncio.run(scenario())
    with store._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()
    assert store.list_events() == []


def test_retirement_review_cache_expiry_cookie_restart_and_concurrent_bounds(lab, monkeypatch):
    _, registry, _, _, _, _ = lab
    policy = registry.snapshot_if_present()
    reviews = ManagedRetirementReviews(ttl=60)
    review = reviews.prepare("alice", "cookie", policy, 1, IP)
    policy["entries"][0]["hostname"] = "Changed"
    assert review.hostname == "lab-1"
    with pytest.raises(ReviewUnavailable):
        reviews.get(review.token, "alice", "different")

    def attempt(_):
        try:
            return reviews.prepare("alice", "cookie", policy, 1, IP)
        except ReviewUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(r is not None for r in pool.map(attempt, range(10))) == 4
    for i in range(251):
        reviews.prepare(f"user-{i}", "cookie", policy, 1, IP)
    with pytest.raises(ReviewUnavailable, match="Too many"):
        reviews.prepare("overflow", "cookie", policy, 1, IP)
    original = managed_retirement_review.time.monotonic
    monkeypatch.setattr(managed_retirement_review.time, "monotonic", lambda: original() + 61)
    with pytest.raises(ReviewUnavailable):
        reviews.get(review.token, "alice", "cookie")
    with pytest.raises(ReviewUnavailable):
        ManagedRetirementReviews().get(review.token, "alice", "cookie")
    assert review.digest != canonical_managed_removal(1, IP, review.managed_revision)[1]


@pytest.mark.parametrize("target", ["", "01:198.51.100.251", "1:198.51.100.251:more", "1:invalid", "0:198.51.100.251", "2:198.51.100.251"])
def test_retirement_review_rejects_malformed_or_unmanaged_selection(lab, target):
    _, _, _, app, calls, _ = lab

    async def scenario():
        async with browser(app) as client:
            assert (await prepare(client, target=target)).status_code in (409, 422)
    asyncio.run(scenario())
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("failure", ["lose_reply", "malformed"])
def test_cancel_uncertain_reply_retries_same_root_without_extra_audit(lab, failure):
    store, _, _, app, calls, behavior = lab
    cleanup, key, _ = waiting(lab)

    async def scenario():
        async with browser(app, subject="admin", group="ftd-shun-administrators") as client:
            page = await client.get("/managed-shuns")
            assert "Cancel waiting cleanup only" in page.text
            fields = {"csrf": client.cookies.get("ftd_shun_csrf")}
            behavior[failure] = True
            path = f"/managed-shuns/handoffs/{key}/cancel"
            assert (await client.post(path, data=fields)).status_code == 503
            assert cleanup.snapshot()["items"][0]["state"] == "CANCELLED"
            before = store.list_events()
            assert (await client.post(path, data=fields)).status_code == 303
            assert store.list_events() == before
            event = next(e for e in before if e["event_type"] == "MANAGED_SHUN_CLEANUP_CANCELLED")
            assert event["actor_subject"] == "admin" and event["actor_roles"] == ["Administrator"]
            assert len({r.url.path for r in calls if r.method == "POST"}) == 1
    asyncio.run(scenario())


def test_cancel_audit_failure_rolls_back_wait_and_suppresses_success(lab, monkeypatch, capsys):
    store, _, _, app, _, _ = lab
    cleanup, key, _ = waiting(lab)
    before = store.list_events(), cleanup.snapshot()
    original = store._insert_event

    def fail(*args, **kwargs):
        if args[1] == "MANAGED_SHUN_CLEANUP_CANCELLED":
            raise sqlite3.OperationalError("Synthetic cancellation audit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "_insert_event", fail)
    capsys.readouterr()

    async def scenario():
        async with browser(app) as client:
            await client.get("/managed-shuns")
            response = await client.post(f"/managed-shuns/handoffs/{key}/cancel", data={"csrf": client.cookies.get("ftd_shun_csrf")})
            assert response.status_code == 503 and "Synthetic cancellation" not in response.text
    asyncio.run(scenario())
    assert (store.list_events(), cleanup.snapshot()) == before
    assert "managed_shun.cleanup.cancelled" not in capsys.readouterr().out


def test_simultaneous_retirements_share_revision_and_only_one_commits(lab):
    store, registry, _, app, _, _ = lab

    async def scenario():
        async with browser(app) as alice, browser(app, subject="bob") as bob:
            first, second = await prepare(alice), await prepare(bob)
            async def confirm(client, page):
                return await client.post("/managed-shuns/retirement-confirm", data={
                    "csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)})
            responses = await asyncio.gather(confirm(alice, first), confirm(bob, second))
            assert sorted(r.status_code for r in responses) == [200, 409]
    asyncio.run(scenario())
    assert len([e for e in store.list_events() if e["event_type"] == "MANAGED_SHUN_RETIRED"]) == 1
    assert not registry.snapshot()["entries"][0]["enabled"]


def test_policy_retirement_keeps_unrelated_admitted_one_time_add_and_snapshot(lab):
    store, registry, api, app, _, _ = lab
    queue = api.state.synchronizer.queue
    revision = api.state.synchronizer.policy.revision()
    queue.enqueue(str(uuid4()), [(1, IP)], "creator", "Creator", ("Operator",), source="manual_import",
                  scope="import", policy_revision=revision, confirmation_digest=canonical_import([(1, IP)], revision)[2])
    store.reconcile_snapshot(1, [(IP, "management")])
    before = queue.status(), store.list_active_shuns()

    async def scenario():
        async with browser(app) as client:
            page = await prepare(client)
            assert "already submitted one-time jobs" in page.text
            response = await client.post("/managed-shuns/retirement-confirm", data={
                "csrf": client.cookies.get("ftd_shun_csrf"), "review": token(page), "confirm_ip": str(IP)})
            assert response.status_code == 200
    asyncio.run(scenario())
    assert (queue.status(), store.list_active_shuns()) == before
    assert not registry.snapshot()["entries"][0]["enabled"]


@pytest.mark.parametrize("reason", ["x" * 501, "invalid\x00reason"])
def test_retirement_reason_validation_has_no_side_effects(lab, reason):
    store, registry, _, app, calls, _ = lab
    before = registry.snapshot(), store.list_events()

    async def scenario():
        async with browser(app) as client:
            assert (await prepare(client, reason=reason)).status_code == 422
    asyncio.run(scenario())
    assert (registry.snapshot(), store.list_events()) == before
    assert all(r.method == "GET" for r in calls)
