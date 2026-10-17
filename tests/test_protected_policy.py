import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.10")
ADMIN = {"subject": "admin", "display_name": "Admin", "roles": ["Administrator"]}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    return ProtectedPolicy(store)


def edit(policy, action="add", ip=IP, **values):
    policy.change(action, ip, policy.snapshot()["revision"], "admin", "Admin", ("Administrator",), **values)


def test_legacy_import_is_atomic_once_only_even_after_delete_and_invalid_env(policy, monkeypatch):
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "198.51.100.10,198.51.100.10")
    policy.migrate_legacy_environment()
    assert policy.enabled_ips() == {IP}
    assert len(policy.snapshot()["entries"]) == 1
    edit(policy, "delete")
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "invalid-new-environment-value")
    restarted = ProtectedPolicy(policy.store)
    restarted.migrate_legacy_environment()
    assert restarted.snapshot()["entries"] == []
    assert [e["event_type"] for e in policy.store.list_events()].count("PROTECTED_IP_IMPORTED") == 1


def test_empty_migration_is_durable_and_runtime_settings_no_longer_parse_policy(policy, monkeypatch):
    policy.migrate_legacy_environment()
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "198.51.100.10")
    policy.migrate_legacy_environment()
    assert policy.enabled_ips() == set()
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "not-an-ip")
    assert not hasattr(Settings.from_environment(), "trusted_auto_remove_ips")


def test_invalid_legacy_import_rolls_back_and_can_be_corrected(policy, monkeypatch):
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "198.51.100.10,192.0.2.0/24")
    with pytest.raises(ValueError):
        policy.migrate_legacy_environment()
    assert policy.snapshot() == {"entries": [], "revision": 0, "limit": 1000,
                                 "managed_policy_available": True, "managed_revision": 0}
    assert policy.store.list_events() == []
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", "198.51.100.10")
    policy.migrate_legacy_environment()
    assert policy.enabled_ips() == {IP}


def test_audit_status_disable_delete_and_search(policy, capsys):
    edit(policy, name="Office", comment="Verified egress")
    policy.store.record_observed_shun(1, IP, "outside")
    entry = policy.snapshot()["entries"][0]
    assert entry["name"] == "Office" and entry["active_devices"] == 1
    assert entry["last_auto_removed_at"] is None
    policy.store.complete_trusted_auto_removal(1, IP, "verified-fixture")
    assert policy.snapshot()["entries"][0]["last_auto_removed_at"]
    edit(policy, "edit", enabled=False, name="Office", comment="Paused")
    assert not policy.enabled_ips()
    assert not policy.snapshot()["entries"][0]["enabled"]
    edit(policy, "delete")
    assert not policy.snapshot()["entries"]
    audit = [event for event in policy.store.list_events() if event["event_type"].startswith("PROTECTED_IP_")]
    assert len(audit) == 3
    assert all(e["actor_subject"] == "admin" and e["actor_roles"] == ["Administrator"] for e in audit)
    assert next(e for e in audit if e["event_type"] == "PROTECTED_IP_DELETED")["details"]["before"]["comment"] == "Paused"
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {log["request_id"] for log in logs} == {e["request_id"] for e in audit}


def test_concurrent_administrators_cannot_overwrite_each_other(policy):
    def add(address):
        try:
            policy.change("add", IPv4Address(address), 0, "admin", "Admin", ("Administrator",))
            return "saved"
        except QueueConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, ["198.51.100.10", "198.51.100.11"])) == ["conflict", "saved"]
    assert len(policy.snapshot()["entries"]) == 1
    assert len(policy.store.list_events()) == 1


def test_disabling_cancels_only_policy_intent_and_leaves_running_commands(policy):
    edit(policy)
    queue = policy.queue
    queue.enqueue(str(uuid4()), [(1, IP)], "system:trusted-ip-policy", "Policy", (), source="trusted_policy")
    queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",))
    edit(policy, "edit", enabled=False)
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert {r["state"] for r in queue.status()["items"][0]["requests"]} == {"ACTIVE", "CANCELLED"}
    assert queue.claim_cycle("worker", 120)
    assert queue.claim_removal(1, "worker", queue.cutoff())
    edit(policy, "delete")
    assert queue.status()["counts"] == {"RUNNING": 1}


def test_every_claim_rechecks_database_policy_not_worker_memory(policy):
    edit(policy)
    queue = policy.queue
    queue.enqueue(str(uuid4()), [(1, IP)], "system:trusted-ip-policy", "Policy", (), source="trusted_policy")
    assert queue.claim_cycle("worker", 120)
    # Simulate another policy writer immediately before dispatch, without calling
    # the UI helper: the executor must independently revalidate its authorization.
    with policy.store._connection() as db:
        db.execute("UPDATE protected_ips SET enabled=0 WHERE ip=?", (IP.packed,))
    assert queue.claim_removal(1, "worker", queue.cutoff()) is None
    assert queue.status()["counts"] == {"CANCELLED": 1}


def test_policy_only_address_is_searchable_without_fake_observation(policy):
    edit(policy)
    result = policy.store.search_ip_history("198.51.100.")
    assert len(result) == 1 and result[0]["ip"] == str(IP)
    assert not result[0]["active"] and result[0]["last_seen_at"] is None


@pytest.mark.parametrize("roles", [["Viewer"], ["Operator"], ["Administrator"], []])
def test_policy_api_authorization_revision_validation_and_no_device_dispatch(policy, roles):
    config = replace(Settings.from_environment(), database_path=policy.store.path,
                     device_inventory_path=None, agent_mode="disabled")
    app = create_app(config, policy.store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            state = (await client.get("/api/v1/protected-ips")).json()
            payload = {"actor": {**ADMIN, "roles": roles}, "revision": state["revision"], "name": "Office", "enabled": True}
            for subject in ["", "   "]:
                denied = await client.post(f"/api/v1/protected-ips/{IP}/add", json={**payload, "actor": {**ADMIN, "subject": subject}})
                assert denied.status_code == 403
            for address in ["hostname", "2001:db8::1"]:
                assert (await client.post(f"/api/v1/protected-ips/{address}/add", json=payload)).status_code == 422
            assert (await client.post(f"/api/v1/protected-ips/{IP}/add", json={**payload, "enabled": "true"})).status_code == 422
            assert (await client.post(f"/api/v1/protected-ips/{IP}/add", json=payload)).status_code == 200
            assert (await client.post(f"/api/v1/protected-ips/{IP}/edit", json=payload)).status_code == 409
            new = (await client.get("/api/v1/protected-ips")).json()
            payload["revision"] = new["revision"]
            assert (await client.post(f"/api/v1/protected-ips/{IP}/delete", json=payload)).status_code == 422
            status = (await client.get("/api/v1/status")).json()
            assert status["policy_revision"] == new["revision"]
            assert status["trusted_auto_remove_ip_count"] == 1
            assert (await client.get("/api/v1/search", params={"ip": str(IP)})).json()[0]["protected"]
            assert (await client.post(f"/api/v1/protected-ips/{IP}/delete", json={**payload, "confirm_ip": str(IP)})).status_code == 200
            if not {"Operator", "Administrator"}.intersection(roles):
                assert (await client.post(f"/api/v1/shuns/{IP}/remove-all", json=payload["actor"])).status_code == 403
            assert app.state.synchronizer.queue.status()["counts"] == {}
            audit = [e for e in policy.store.list_events() if e["event_type"].startswith("PROTECTED_IP_")]
            assert len(audit) == 2 and all(e["actor_roles"] == roles for e in audit)
    asyncio.run(scenario())


@pytest.mark.parametrize("group,roles", [("ftd-shun-viewers", ["Viewer"]),
    ("ftd-shun-operators", ["Operator"]), ("ftd-shun-administrators", ["Administrator"]), ("", [])])
def test_policy_bff_all_authenticated_users_csrf_and_identity_cannot_be_forged(policy, monkeypatch, group, roles):
    config = replace(Settings.from_environment(), database_path=policy.store.path,
                     device_inventory_path=None, agent_mode="disabled", development_auth=False)
    app = create_app(config, policy.store)
    edit(policy)
    status_route = next(r for r in app.routes if r.path == "/api/v1/status")
    captured = []

    def internal(request):
        captured.append(request)
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=asyncio.run(status_route.endpoint()))
        if request.url.path == "/api/v1/protected-ips":
            return httpx.Response(200, json=policy.snapshot())
        return httpx.Response(200, json={"status": "saved"})

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://lab.test") as client:
            assert (await client.get("/protected-ips")).status_code == 401
            assert (await client.get("/history")).status_code == 401
            assert not captured
            client.cookies.set("ftd_shun_csrf", "token")
            data = {"csrf": "token", "ip": str(IP), "revision": policy.revision(),
                    "enabled": "true", "roles": "Administrator", "subject": "forged"}
            assert (await client.post("/protected-ips/add", data=data)).status_code == 401
            client.headers["Remote-User"] = "   "
            assert (await client.post("/protected-ips/add", data=data)).status_code == 401
            assert not captured
            client.headers.update({"Remote-User": "alice", "Remote-Groups": group})
            page = await client.get("/protected-ips")
            assert page.status_code == 200 and "Read-only" not in page.text
            assert 'id="add-policy-form"' in page.text
            assert f'id="edit-policy-form-{IP}"' in page.text
            assert f'id="delete-policy-form-{IP}"' in page.text
            client.cookies.clear()
            assert (await client.post("/protected-ips/add", data=data)).status_code == 403
            client.cookies.set("ftd_shun_csrf", "token")
            assert (await client.post("/protected-ips/add", data={k: v for k, v in data.items() if k != "csrf"})).status_code == 422
            assert (await client.post("/protected-ips/add", data={**data, "csrf": "bad"})).status_code == 403
            response = await client.post("/protected-ips/add", data=data, headers={"Accept": "application/json"})
            assert response.status_code == 200
            sent = next(r for r in captured if r.method == "POST")
            assert json.loads(sent.content)["actor"] == {"subject": "alice", "display_name": "alice", "roles": roles}
            assert response.headers["cache-control"] == "no-store"
    asyncio.run(scenario())


@pytest.mark.parametrize("subject", ["", "   "])
def test_policy_store_rejects_missing_identity_even_with_administrator_role(policy, subject):
    with pytest.raises(PermissionError, match="authenticated user"):
        policy.change("add", IP, policy.revision(), subject, "Display name", ("Administrator",))
    assert policy.snapshot()["entries"] == [] and policy.store.list_events() == []


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("active", [True, False])
def test_policy_state_badges_and_disabled_shun_warnings_are_read_only(policy, monkeypatch, enabled, active):
    edit(policy, enabled=enabled)
    if active:
        policy.store.record_observed_shun(1, IP, "outside")
    config = replace(Settings.from_environment(), database_path=policy.store.path,
                     device_inventory_path=None, agent_mode="disabled", development_auth=False)
    api = create_app(config, policy.store)
    events_before = policy.store.list_events()

    def internal(request):
        async def read():
            assert request.method == "GET", "Display must not mutate policy or request refresh"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.get(str(request.url))
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        return asyncio.run(read())

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            status = (await client.get("/api/v1/status")).json()
            assert [entry["ip"] for entry in status["trusted_auto_remove_ips"]] == ([str(IP)] if enabled else [])
            assert status["disabled_protected_ips"] == ([] if enabled else [{"ip": str(IP)}])
            assert status["trusted_auto_remove_ip_count"] == int(enabled)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://lab.test",
                                     headers={"Remote-User": "viewer", "Remote-Groups": "ftd-shun-viewers"}) as client:
            listing = await client.get("/protected-ips")
            assert listing.status_code == 200
            badge = 'class="state-badge policy-enabled">Enabled' if enabled else 'class="state-badge policy-disabled">Disabled'
            assert badge in listing.text
            assert ('class="disabled-protection-summary"' in listing.text) == (active and not enabled)
            assert ('policy-disabled-warning' in listing.text) == (active and not enabled)
            index = await client.get("/", params={"q": str(IP)})
            assert index.status_code == 200
            assert ('class="disabled-protection-shun"' in index.text) == (active and not enabled)
            assert ('class="protected-shun"' in index.text) == enabled
            if active and not enabled:
                assert index.text.count('class="state-badge policy-disabled"') == 2, "Both search and active row must warn"
            detail = await client.get(f"/shuns/{IP}")
            assert detail.status_code == 200
            assert ('class="disabled-protection-notice"' in detail.text) == (not enabled)
            assert ('Protection disabled — currently shunned.' in detail.text) == (active and not enabled)
            assert ('class="protected-ip-notice"' in detail.text) == enabled
    asyncio.run(scenario())
    assert policy.store.list_events() == events_before
    assert policy.queue.status()["counts"] == {}
    assert policy.enabled_ips() == ({IP} if enabled else set())


@pytest.mark.parametrize("refresh", [None, {}, {"disabled_protected_ips": None},
    {"disabled_protected_ips": [None, {"ip": 12}, {"name": "Missing IP"}]}])
def test_missing_or_malformed_disabled_display_metadata_is_not_invented(refresh):
    assert web.protected_policy_ips(refresh, enabled=False) == frozenset()
