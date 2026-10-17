"""Frozen fleet scope; disposable SQLite/identities only, no device writes."""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_intent import (
    canonical_managed_change,
    canonical_managed_fleet_removal,
    canonical_managed_fleet_scope,
    canonical_managed_removal,
)
from ftd_shun_manager.managed_review import ManagedRemovalReviews
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_scope import ManagedRemovalScopes
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       development_auth=False, agent_mode="disabled")
    api = create_app(settings, store)
    for device in range(1, 6):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    return store, api, settings


def change(registry, action, targets):
    revision = registry.metadata()["managed_policy_revision"]
    with registry.store._connection() as db:
        protected = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    return registry.change(str(uuid4()), action, [(device, IP) for device in targets], revision, protected,
                           canonical_managed_change(action, [(device, IP) for device in targets], revision, protected)[2],
                           "creator", "Creator", ("Operator",))


def populate(store):
    registry = ManagedShuns(store)
    registry.initialize()
    change(registry, "MAINTAIN", [1, 3, 4])
    change(registry, "RETIRE", [4])
    store.upsert_device(Device(3, "disabled-3", IPv4Address("192.0.2.3"), False), "ssh-ed25519 AAAA")
    store.record_observed_shun(2, IP, "outside")
    store.record_observed_shun(2, IP, "inside")
    return registry


def fingerprint(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def test_union_includes_missing_disabled_collapses_interfaces_and_excludes_retired_missing(state):
    store, _, _ = state
    populate(store)
    before = fingerprint(store)
    scope = ManagedRemovalScopes(store).snapshot(IP)
    assert [row["device_id"] for row in scope["targets"]] == [1, 2, 3]
    assert [(row["observed_present"], row["maintenance_enabled"], row["device_enabled"])
            for row in scope["targets"]] == [(False, True, True), (True, False, True), (False, True, False)]
    assert scope["targets"][1]["intent_id"] is None
    assert scope["read_only"] and not scope["execution_available"]
    assert not any(key in json.dumps(scope) for key in ("ssh_host_key", "management_ip", "actor_roles", "payload_json"))
    assert fingerprint(store) == before
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        assert ManagedRemovalScopes.require_current(db, scope) == scope


def test_absent_optional_state_is_not_migrated_and_empty_scope_is_not_authority(state):
    store, _, _ = state
    scopes = ManagedRemovalScopes(store)
    before = fingerprint(store)
    with pytest.raises(ManagedConflict, match="empty"):
        scopes.snapshot(IP)
    assert fingerprint(store) == before
    store.record_observed_shun(2, IP, "outside")
    before = fingerprint(store)
    scope = scopes.snapshot(IP)
    assert not scope["managed_initialized"] and scope["managed_revision"] == 0
    assert len(scope["targets"]) == 1 and not scope["targets"][0]["maintenance_enabled"]
    assert fingerprint(store) == before


@pytest.mark.parametrize("mutation", ["observed_add", "observed_remove", "retire", "disable", "rename", "protect", "generation"])
def test_transactional_comparison_rejects_changed_scope_without_writes(state, mutation):
    store, _, _ = state
    registry = populate(store)
    scopes = ManagedRemovalScopes(store)
    scope = scopes.snapshot(IP)
    if mutation == "observed_add":
        store.record_observed_shun(5, IP, "outside")
    elif mutation == "observed_remove":
        with store._connection() as db:
            db.execute("UPDATE shun_state SET active=0 WHERE device_id=2")
    elif mutation == "retire":
        change(registry, "RETIRE", [1])
    elif mutation == "generation":
        change(registry, "RETIRE", [1])
        change(registry, "MAINTAIN", [1])
    elif mutation == "protect":
        policy = ProtectedPolicy(store)
        policy.change("add", IP, policy.revision(), "viewer", "Viewer", ("Viewer",))
    else:
        store.upsert_device(Device(1, "renamed" if mutation == "rename" else "synthetic-1", IPv4Address("192.0.2.1"), mutation != "disable"), "ssh-ed25519 AAAA")
    before = fingerprint(store)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ManagedConflict, match="scope changed"):
            ManagedRemovalScopes.require_current(db, scope)
        assert db.in_transaction
    assert fingerprint(store) == before


def test_timestamps_and_additional_interfaces_do_not_change_target_scope(state):
    store, _, _ = state
    populate(store)
    scope = ManagedRemovalScopes(store).snapshot(IP)
    store.record_observed_shun(2, IP, "management")
    with store._connection() as db:
        db.execute("UPDATE shun_state SET last_seen_at='2030-01-01T00:00:00Z'")
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        assert ManagedRemovalScopes.require_current(db, scope) == scope


def test_scope_comparison_requires_caller_transaction_and_exact_binding(state):
    store, _, _ = state
    populate(store)
    scope = ManagedRemovalScopes(store).snapshot(IP)
    with store._connection() as db:
        with pytest.raises(ValueError, match="transaction"):
            ManagedRemovalScopes.require_current(db, scope)
        db.execute("BEGIN IMMEDIATE")
        for wrong in ("0" * 64, "неправильно", None):
            with pytest.raises(ValueError, match="binding"):
                ManagedRemovalScopes.require_current(db, {**scope, "scope_digest": wrong})


def test_snapshot_transaction_cannot_mix_concurrent_inventory_change(state):
    store, _, _ = state
    populate(store)
    with store._connection() as db:
        db.execute("BEGIN")
        first = ManagedRemovalScopes.read(db, IP)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(store.upsert_device, Device(1, "renamed", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA").result()
        assert ManagedRemovalScopes.read(db, IP) == first
    assert ManagedRemovalScopes(store).snapshot(IP)["scope_digest"] != first["scope_digest"]


@pytest.mark.parametrize("corrupt", ["partial", "generation", "device", "orphan"])
def test_unknown_optional_or_target_state_fails_closed_not_silently_omitted(state, corrupt):
    store, _, _ = state
    populate(store)
    with store._connection() as db:
        if corrupt == "partial":
            db.execute("DROP TABLE managed_shun_registry")
        elif corrupt == "generation":
            db.execute("UPDATE managed_shun_targets SET intent_id='invalid' WHERE device_id=1")
        elif corrupt == "device":
            db.execute("UPDATE devices SET hostname='' WHERE id=1")
        else:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM devices WHERE id=1")
    before = fingerprint(store)
    with pytest.raises((ManagedStateUnavailable, ValueError)):
        ManagedRemovalScopes(store).snapshot(IP)
    assert fingerprint(store) == before


def test_overflow_rejects_whole_union_without_truncating(state):
    store, _, _ = state
    with store._connection() as db:
        for device in range(6, 1002):
            db.execute("INSERT INTO devices VALUES (?,?,?,?,1)", (device, f"synthetic-{device}", IPv4Address(0xC0000200 + device).packed, "ssh-ed25519 AAAA"))
        db.execute("""INSERT INTO shun_state(device_id,ip,interface,active,first_seen_at,last_seen_at,last_changed_at)
            SELECT id,?,'outside',1,'t','t','t' FROM devices""", (IP.packed,))
    before = fingerprint(store)
    with pytest.raises(ManagedConflict, match="exceeds"):
        ManagedRemovalScopes(store).snapshot(IP)
    assert fingerprint(store) == before


def test_canonical_scope_order_strictness_and_action_separation(state):
    store, _, _ = state
    populate(store)
    view = ManagedRemovalScopes(store).snapshot(IP)
    scope = {key: value for key, value in view.items() if key not in {"scope_digest", "read_only", "execution_available"}}
    payload, digest = canonical_managed_fleet_scope(scope)
    assert canonical_managed_fleet_scope({**scope, "targets": scope["targets"][::-1]}) == (payload, digest)
    action, action_digest = canonical_managed_fleet_removal(scope, 120, " reason ")
    assert json.loads(action)["reason"] == "reason"
    assert action_digest != digest and action_digest != canonical_managed_removal(1, IP, scope["managed_revision"], 120, "reason")[1]
    for bad in ({**scope, "unexpected": True}, {**scope, "managed_revision": True},
                {**scope, "targets": scope["targets"] * 2}, {**scope, "targets": []}):
        with pytest.raises(ValueError):
            canonical_managed_fleet_scope(bad)
    for ttl, reason in ((0, ""), (901, ""), (True, ""), (60, "x" * 501), (60, "bad\x00")):
        with pytest.raises(ValueError):
            canonical_managed_fleet_removal(scope, ttl, reason)


def test_fleet_cache_is_deeply_frozen_bound_and_shares_single_target_capacity(state):
    store, _, _ = state
    registry = populate(store)
    view = ManagedRemovalScopes(store).snapshot(IP)
    reviews = ManagedRemovalReviews()
    review = reviews.prepare_fleet("alice", "cookie", view, IP, 120, "reason")
    view["targets"][0]["hostname"] = "changed"
    assert review.targets[0].hostname == "synthetic-1"
    with pytest.raises(FrozenInstanceError):
        review.targets[0].hostname = "changed"
    for _ in range(4):
        reviews.prepare("alice", "cookie", registry.snapshot_if_present(), 1, IP, 120)
    with pytest.raises(ReviewUnavailable):
        reviews.prepare_fleet("alice", "cookie", ManagedRemovalScopes(store).snapshot(IP), IP, 120)
    with pytest.raises(ReviewUnavailable):
        reviews.get(review.token, "alice", "wrong")
    with pytest.raises(ReviewUnavailable):
        ManagedRemovalReviews().get(review.token, "alice", "cookie")
    for bad in ({**view, "scope_digest": "0" * 64}, {**view, "targets": []}):
        with pytest.raises(ValueError):
            ManagedRemovalReviews().prepare_fleet("alice", "cookie", bad, IP, 120)


def test_private_resource_and_bff_review_never_execute_or_migrate(state, monkeypatch):
    store, api, settings = state
    populate(store)
    store.upsert_device(Device(1, "<script>device</script>", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    calls = []
    def internal(request):
        calls.append((request.method, request.url.path))
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, request.url.path)
                if request.url.path == "/api/v1/status":
                    return httpx.Response(200, json={**response.json(), "managed_removal_admission_enabled": True})
                return httpx.Response(response.status_code, json=response.json())
        return asyncio.run(send())
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    app = web.create_app(settings)
    before = fingerprint(store)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            assert (await client.get(f"/api/v1/managed-removal-scope/{IP}")).status_code == 200
            assert (await client.get("/api/v1/managed-removal-scope/not-an-ip")).status_code == 422
            assert (await client.get("/api/v1/managed-removal-scope/198.51.100.252")).status_code == 409
            assert (await client.post(f"/api/v1/managed-removal-scope/{IP}")).status_code == 405
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lab.test",
                                     headers={"Remote-User": "alice", "Remote-Groups": "ftd-shun-operators"}) as client:
            await client.get("/managed-shuns")
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "ip": str(IP), "reason": "<img src=x>"}
            page = await client.post("/managed-shuns/fleet-removal-review", data=fields)
            assert page.status_code == 200
            assert "3 exact device/IP targets" in page.text and "Disabled devices are included" in page.text
            assert "No managed intent; no adoption" in page.text and "retained scope" in page.text
            assert "&lt;script&gt;device" in page.text and "<script>device" not in page.text
            assert "&lt;img" in page.text and 'data-frozen-view="true"' in page.text
            token = re.search(r'name="review" value="([^"]+)"', page.text)[1]
            confirm = {"csrf": fields["csrf"], "review": token, "confirm_ip": str(IP)}
            for _ in range(2):
                result = await client.post("/managed-shuns/removal-confirm", data=confirm)
                assert result.status_code == 503 and token in result.text and "3 exact device/IP targets" in result.text
            for extra in ({"device_ids": "1"}, {"managed_revision": "0"}, {"actor": "forged"}):
                assert (await client.post("/managed-shuns/fleet-removal-review", data={**fields, **extra})).status_code == 422
            assert (await client.post("/managed-shuns/removal-confirm", data={**confirm, "confirm_ip": "wrong"})).status_code == 422
            assert (await client.post("/managed-shuns/fleet-removal-review", data={**fields, "csrf": "wrong"})).status_code == 403
            client.headers["Remote-User"] = "bob"
            assert (await client.post("/managed-shuns/removal-confirm", data=confirm)).status_code == 409
            client.headers["Remote-Groups"] = "ftd-shun-viewers"
            assert (await client.post("/managed-shuns/fleet-removal-review", data=fields)).status_code == 403
            del client.headers["Remote-User"]
            assert (await client.post("/managed-shuns/fleet-removal-review", data=fields)).status_code == 401
    asyncio.run(scenario())
    assert all(method == "GET" and path != "/api/v1/refresh-hint" for method, path in calls)
    assert fingerprint(store) == before


def test_scope_resource_absence_and_corruption_do_not_initialize_or_break_monitoring(state):
    store, api, _ = state
    store.record_observed_shun(1, IP, "outside")
    before = fingerprint(store)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            result = await client.get(f"/api/v1/managed-removal-scope/{IP}")
            assert result.status_code == 200 and not result.json()["managed_initialized"]
            assert fingerprint(store) == before
            with store._connection() as db:
                db.execute("CREATE TABLE managed_shun_registry(id INTEGER)")
            response = await client.get(f"/api/v1/managed-removal-scope/{IP}")
            assert response.status_code == 503 and "unavailable" in response.text
            assert (await client.get("/api/v1/shuns")).status_code == 200
    asyncio.run(scenario())
