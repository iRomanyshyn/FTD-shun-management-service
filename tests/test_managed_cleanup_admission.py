"""Gated combined device/fleet cleanup, synthetic local state and actors only."""

import asyncio
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.managed_fleet_removals import ManagedFleetRemovals
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_review import ManagedRemovalReviews
from ftd_shun_manager.managed_scope import ManagedRemovalScopes
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
ACTOR = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "synthetic.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       agent_mode="socket", development_auth=False, managed_removal_worker_enabled=True,
                       managed_removal_admission_enabled=True)
    api = create_app(settings, store, DisabledAgentClient())
    for device in (1, 2):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    registry = ManagedShuns(store)
    registry.initialize()
    maintain(registry, [(1, IP), (2, IP)])
    api.state.synchronizer.managed_removals.initialize()
    fleet = ManagedFleetRemovals(registry, api.state.synchronizer.queue)
    fleet.initialize()
    calls, behavior = [], {}
    def internal(request):
        calls.append(request)
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                reply = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)
        result = asyncio.run(send())
        if request.url.path.startswith("/api/v1/managed-removals/"):
            if behavior.pop("lost", False):
                raise httpx.ReadTimeout("Synthetic committed response lost")
            if behavior.pop("bad", False):
                return httpx.Response(202, json={**result.json(), "waiting_for_add": "false"})
            if behavior.pop("wrong_status", False):
                return httpx.Response(200, json=result.json())
            if behavior.get("status_fails_after"):
                behavior["status_error"] = True
        if request.url.path == "/api/v1/status":
            if behavior.get("status_error"):
                return httpx.Response(503, json={"detail": "Synthetic optional status error"})
            if behavior.get("gate_off"):
                return httpx.Response(200, json={**result.json(), "managed_removal_admission_enabled": False})
        return result
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    return store, registry, api, web.create_app(settings), calls, behavior, settings


def maintain(registry, pairs):
    revision = registry.snapshot()["revision"]
    with registry.store._connection() as db:
        protected = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), "MAINTAIN", pairs, revision, protected,
                    canonical_managed_change("MAINTAIN", pairs, revision, protected)[2], "creator", "Creator", ("Operator",))


def review(lab, scope="device", ordered=False, ttl=900):
    cache = ManagedRemovalReviews()
    if scope == "device":
        return cache.prepare("alice", "cookie", lab[1].snapshot_if_present(), 1, IP, ttl, "Fixture")
    return cache.prepare_fleet("alice", "cookie", ManagedRemovalScopes(lab[0]).snapshot(IP), IP, ttl, "Fixture", ordered_wait=ordered)


async def post(lab, frozen=None, *, payload=None, app=None, key=None, scope=None):
    frozen = frozen or review(lab)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app or lab[2]), base_url="http://internal") as client:
        return await client.post(f"/api/v1/managed-removals/{scope or frozen.scope}",
                                 headers={"Idempotency-Key": key if key is not None else frozen.request_id},
                                 json=payload or {"actor": ACTOR, **frozen.payload()})


def browser(lab, group="ftd-shun-operators", subject="alice"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=lab[3]), base_url="https://synthetic.test",
                             headers={"Remote-User": subject, "Remote-Groups": group})


async def prepare(client, scope="device", ordered=False):
    await client.get("/managed-shuns")
    fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "reason": "<b>Synthetic</b>"}
    if scope == "device":
        fields["target"] = f"1:{IP}"
        path = "/managed-shuns/removal-review"
    else:
        fields["ip"] = str(IP)
        if ordered:
            fields["ordered_wait"] = "yes"
        path = "/managed-shuns/fleet-removal-review"
    return await client.post(path, data=fields)


def token(page):
    return re.search(r'name="review" value="([^"]+)"', page.text)[1]


async def confirm(client, opaque, **changes):
    return await client.post("/managed-shuns/removal-confirm", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                             "review": opaque, "confirm_ip": str(IP), **changes})


def running_add(lab, device=1):
    queue = lab[2].state.synchronizer.queue
    protected = lab[2].state.synchronizer.policy.revision()
    queue.enqueue(str(uuid4()), [(device, IP)], "adder", "Adder", ("Operator",), source="manual_import", scope="import",
                  policy_revision=protected, confirmation_digest=canonical_import([(device, IP)], protected)[2])
    assert queue.claim_cycle("synthetic-worker", 135)
    job = queue.claim_addition(device, "synthetic-worker", queue.cutoff(), execution_enabled=True)
    assert job
    return job


def dump(lab):
    with lab[0]._connection() as db:
        return tuple(db.iterdump())


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_api_atomic_admission_and_historical_replay_never_stop_newer_generation(lab, scope):
    frozen = review(lab, scope)
    result = asyncio.run(post(lab, frozen))
    assert result.status_code == 202 and not result.json()["replayed"]
    entries = lab[1].snapshot()["entries"]
    assert entries[0]["enabled"] is False and entries[1]["enabled"] is (scope == "device")
    queue = lab[2].state.synchronizer.queue
    assert queue.status()["counts"] == {"QUEUED": 1 if scope == "device" else 2}
    assert lab[2].state.synchronizer._activity.is_set()
    queue.cancel(frozen.request_id, "alice", False)
    maintain(lab[1], [(1, IP)] if scope == "device" else [(1, IP), (2, IP)])
    before = dump(lab)
    lab[2].state.synchronizer._activity.clear()
    repeated = asyncio.run(post(lab, frozen))
    assert repeated.status_code == 202 and repeated.json()["replayed"]
    assert dump(lab) == before and all(e["enabled"] for e in lab[1].snapshot()["entries"])
    assert not lab[2].state.synchronizer._activity.is_set()


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_http_running_add_waits_then_promotes_under_original_deadline(lab, scope):
    job = running_add(lab)
    queue = lab[2].state.synchronizer.queue
    frozen = review(lab, scope, ordered=True)
    response = asyncio.run(post(lab, frozen))
    assert response.status_code == 202 and response.json()["waiting_for_add"]
    with lab[0]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "RUNNING"
        table = "managed_removal_handoffs" if scope == "device" else "managed_fleet_removals"
        original_deadline = db.execute(f"SELECT expires_at FROM {table} WHERE id=?", (frozen.request_id,)).fetchone()[0]
    queue.finish_addition(job["id"], "synthetic-worker", "UNVERIFIED")
    if scope == "device":
        assert lab[2].state.synchronizer.managed_removals.advance("synthetic-worker") == 1
    else:
        assert lab[2].state.synchronizer.managed_fleet_waits.advance("synthetic-worker") == 1
    with lab[0]._connection() as db:
        assert db.execute("SELECT expires_at FROM operation_requests WHERE id=?", (frozen.request_id,)).fetchone()[0] <= original_deadline
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "UNVERIFIED"
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == (1 if scope == "device" else 2)


def test_fleet_ready_review_never_silently_gains_ordered_semantics(lab):
    running_add(lab)
    frozen = review(lab, "fleet")
    before = dump(lab)
    assert asyncio.run(post(lab, frozen)).status_code == 409
    assert asyncio.run(post(lab, frozen, payload={"actor": ACTOR, **frozen.payload(), "ordered_wait": True})).status_code == 422
    assert dump(lab) == before


@pytest.mark.parametrize("scope", ["device", "fleet"])
@pytest.mark.parametrize("failure", ["lost", "bad", "wrong_status"])
def test_browser_keeps_scope_key_and_typed_ip_through_unknown_response(lab, scope, failure):
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client, scope, ordered=scope == "fleet")
            assert page.status_code == 200 and "Atomic local admission" in page.text and "&lt;b&gt;Synthetic&lt;/b&gt;" in page.text
            opaque = token(page)
            lab[5][failure] = True
            unknown = await confirm(client, opaque)
            assert unknown.status_code == 503 and "outcome is unknown" in unknown.text
            assert token(unknown) == opaque and f'value="{IP}"' in unknown.text
            before = dump(lab)
            replay = await confirm(client, opaque)
            assert replay.status_code == 200 and "Original-key receipt replay" in replay.text
            assert dump(lab) == before
            sent = [r for r in lab[4] if r.url.path.startswith("/api/v1/managed-removals/")]
            assert len(sent) == 2 and sent[0].content == sent[1].content
            assert sent[0].headers["Idempotency-Key"] == sent[1].headers["Idempotency-Key"]
            assert json.loads(sent[0].content)["actor"]["subject"] == "alice"
            assert not any("refresh-hint" in r.url.path for r in lab[4])
    asyncio.run(scenario())


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_browser_waiting_receipt_is_not_reported_as_verified_removal(lab, scope):
    running_add(lab)
    async def scenario():
        async with browser(lab) as client:
            page = await prepare(client, scope, ordered=True)
            receipt = await confirm(client, token(page))
            assert receipt.status_code == 200 and "Waiting for ADD settlement" in receipt.text
            assert "not verified removal" in receipt.text
            if scope == "fleet":
                assert "All reviewed devices wait together" in receipt.text
    asyncio.run(scenario())


@pytest.mark.parametrize("scope", ["device", "fleet"])
@pytest.mark.parametrize("blocker", ["paused", "queued_add", "disabled", "stale", "audit"])
def test_conflicts_or_late_failure_never_partially_retire_or_admit(lab, monkeypatch, scope, blocker):
    frozen = review(lab, scope)
    sync = lab[2].state.synchronizer
    if blocker == "paused":
        with lab[0]._connection() as db:
            db.execute("UPDATE operation_executor SET mutations_suspended=1")
    elif blocker == "queued_add":
        protected = sync.policy.revision()
        sync.queue.enqueue(str(uuid4()), [(1, IP)], "other", "Other", ("Operator",), source="manual_import", scope="import",
                           policy_revision=protected, confirmation_digest=canonical_import([(1, IP)], protected)[2])
    elif blocker == "disabled":
        with lab[0]._connection() as db:
            db.execute("UPDATE devices SET enabled=0 WHERE id=1")
    elif blocker == "stale":
        with lab[0]._connection() as db:
            db.execute("UPDATE managed_shun_registry SET revision=revision+1")
    else:
        original = lab[0]._insert_event
        def fail(db, event, *args, **kwargs):
            if event in {"MANAGED_SHUN_REMOVAL_ADMITTED", "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED"}:
                raise sqlite3.OperationalError("synthetic late audit failure")
            return original(db, event, *args, **kwargs)
        monkeypatch.setattr(lab[0], "_insert_event", fail)
    before = dump(lab)
    response = asyncio.run(post(lab, frozen))
    assert response.status_code == (503 if blocker == "audit" else 409)
    assert dump(lab) == before and not sync._activity.is_set()


def test_changed_fleet_membership_or_protection_rejects_whole_scope(lab):
    frozen = review(lab, "fleet")
    lab[0].upsert_device(Device(3, "new-observed", IPv4Address("192.0.2.3"), True), "ssh-ed25519 AAAA")
    lab[0].record_observed_shun(3, IP, "management")
    before = dump(lab)
    assert asyncio.run(post(lab, frozen)).status_code == 409
    assert dump(lab) == before
    frozen = review(lab, "fleet")
    policy = lab[2].state.synchronizer.policy
    policy.change("add", IP, policy.revision(), "protector", "Protector", ("Operator",),
                  managed_revision=lab[1].snapshot()["revision"])
    before = dump(lab)
    assert asyncio.run(post(lab, frozen)).status_code == 409
    assert dump(lab) == before
    # A separately prepared protected cleanup is still allowed; removal implements protection.
    assert asyncio.run(post(lab, review(lab, "fleet"))).status_code == 202


def test_disabled_gate_unknown_reply_and_optional_status_failure_stay_honest(lab):
    async def scenario():
        async with browser(lab) as client:
            opaque = token(await prepare(client))
            lab[5]["lost"] = True
            assert (await confirm(client, opaque)).status_code == 503
            lab[5]["gate_off"] = True
            stopped = await confirm(client, opaque)
            assert stopped.status_code == 503 and "earlier unknown outcome" in stopped.text
            assert token(stopped) == opaque
            lab[5]["gate_off"] = False
            lab[5]["status_fails_after"] = True
            assert "Cleanup plan accepted" in (await confirm(client, opaque)).text
    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", [("actor", {**ACTOR, "roles": ["Viewer"]}), ("device_id", True),
                                         ("generation", True), ("intent_id", str(uuid4())), ("ttl_seconds", 901),
                                         ("ttl_seconds", "900"), ("ip", 0xC63364FB), ("action", "ADD")])
def test_private_device_schema_role_and_reviewed_generation_are_enforced(lab, field, value):
    frozen = review(lab)
    before = dump(lab)
    response = asyncio.run(post(lab, frozen, payload={"actor": ACTOR, **frozen.payload(), field: value}))
    assert response.status_code == (403 if field == "actor" else 409 if field == "intent_id" else 422)
    assert dump(lab) == before


def test_sensitive_age_caps_cleanup_and_explicit_key_is_required(lab):
    frozen = review(lab, ttl=61)
    capped = create_app(replace(lab[6], sensitive_action_max_age_seconds=60), lab[0], DisabledAgentClient())
    before = dump(lab)
    assert asyncio.run(post(lab, frozen, app=capped)).status_code == 422
    assert asyncio.run(post(lab, frozen, key="")).status_code == 422
    assert dump(lab) == before


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_concurrent_original_key_is_one_atomic_plan(lab, scope):
    frozen = review(lab, scope)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: asyncio.run(post(lab, frozen)), range(4)))
    assert all(r.status_code == 202 for r in responses)
    assert sum(not r.json()["replayed"] for r in responses) == 1
    assert lab[1].snapshot()["revision"] == frozen.managed_revision+1


@pytest.mark.parametrize("waiting", [False, True])
def test_single_deadline_expiry_rolls_back_waiting_or_ready_admission(lab, monkeypatch, waiting):
    if waiting:
        running_add(lab)
    frozen = review(lab, ttl=1)
    sync = lab[2].state.synchronizer
    current = datetime.now(UTC)
    clock = [current]
    monkeypatch.setattr(sync.queue, "_now", lambda: clock[0])
    original = lab[0]._insert_event
    def delay(db, event, *args, **kwargs):
        result = original(db, event, *args, **kwargs)
        if event == "MANAGED_SHUN_REMOVAL_ADMITTED":
            clock[0] = current+timedelta(seconds=1)
        return result
    monkeypatch.setattr(lab[0], "_insert_event", delay)
    before = dump(lab)
    assert asyncio.run(post(lab, frozen)).status_code == 409
    assert dump(lab) == before


@pytest.mark.parametrize("value", ["yes", "1", "TRUE", "", "False"])
def test_cleanup_configuration_requires_explicit_boolean_and_worker(monkeypatch, value):
    monkeypatch.setenv("FTD_SHUN_MANAGED_REMOVAL_ADMISSION_ENABLED", value)
    with pytest.raises(ValueError, match="REMOVAL_ADMISSION"):
        Settings.from_environment()


def test_gate_requires_worker_and_never_initializes_absent_schema(lab):
    with pytest.raises(ValueError, match="cleanup worker"):
        replace(lab[6], managed_removal_worker_enabled=False)
    frozen = review(lab)
    with lab[0]._connection() as db:
        db.execute("DROP TABLE managed_removal_handoffs")
    assert asyncio.run(post(lab, frozen)).status_code == 503
    assert all(e["enabled"] for e in lab[1].snapshot()["entries"])
    with lab[0]._connection() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_removal_handoffs'").fetchone()


def test_mixed_fleet_keeps_observed_only_member_without_adoption(lab):
    lab[0].upsert_device(Device(3, "observed-only", IPv4Address("192.0.2.3"), True), "ssh-ed25519 AAAA")
    lab[0].record_observed_shun(3, IP, "management")
    frozen = review(lab, "fleet")
    result = asyncio.run(post(lab, frozen))
    assert result.status_code == 202 and result.json()["target_count"] == 3 and result.json()["retired_targets"] == 2
    assert len(lab[1].snapshot()["entries"]) == 2
    assert lab[2].state.synchronizer.queue.status()["counts"] == {"QUEUED": 3}


@pytest.mark.parametrize("override", [{"csrf": "wrong"}, {"confirm_ip": "198.51.100.250"},
                                      {"actor": "spoofed"}, {"ordered_wait": "yes"}, {"ttl_seconds": "900"}])
def test_confirmation_accepts_no_injected_authority_or_mode(lab, override):
    async def scenario():
        async with browser(lab) as client:
            opaque = token(await prepare(client, "fleet", ordered=False))
            before = dump(lab)
            assert (await confirm(client, opaque, **override)).status_code in (403, 422)
            assert dump(lab) == before
    asyncio.run(scenario())
    assert not any(r.url.path.startswith("/api/v1/managed-removals/") for r in lab[4])


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_current_role_loss_and_gate_disable_prevent_new_admission(lab, scope):
    frozen = review(lab, scope)
    disabled = create_app(replace(lab[6], managed_removal_admission_enabled=False), lab[0], DisabledAgentClient())
    before = dump(lab)
    assert asyncio.run(post(lab, frozen, app=disabled)).status_code == 503
    payload = {"actor": {**ACTOR, "roles": ["Viewer"]}, **frozen.payload()}
    assert asyncio.run(post(lab, frozen, payload=payload)).status_code == 403
    async def scenario():
        async with browser(lab) as client:
            opaque = token(await prepare(client, scope))
            client.headers["Remote-Groups"] = "ftd-shun-viewers"
            assert (await confirm(client, opaque)).status_code == 403
    asyncio.run(scenario())
    assert dump(lab) == before


def test_single_replay_binds_original_intent_and_generation(lab):
    frozen = review(lab)
    assert asyncio.run(post(lab, frozen)).status_code == 202
    before = dump(lab)
    for changes in ({"generation": frozen.generation+1}, {"intent_id": str(uuid4())}):
        assert asyncio.run(post(lab, frozen, payload={"actor": ACTOR, **frozen.payload(), **changes})).status_code == 409
    assert dump(lab) == before


@pytest.mark.parametrize("scope", ["device", "fleet"])
def test_concurrent_users_with_distinct_keys_cannot_both_retire_the_same_revision(lab, scope):
    frozen = review(lab, scope)
    def submit(index):
        payload = {"actor": {**ACTOR, "subject": f"operator-{index}"}, **frozen.payload()}
        return asyncio.run(post(lab, frozen, payload=payload, key=str(uuid4())))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert sorted(r.status_code for r in results) == [202, 409, 409, 409]
    assert lab[1].snapshot()["revision"] == frozen.managed_revision+1


def test_fleet_http_never_loops_single_target_coordinator(lab, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Fleet atomicity must not be simulated by per-device commits")
    monkeypatch.setattr(lab[2].state.synchronizer.managed_removals, "admit", forbidden)
    assert asyncio.run(post(lab, review(lab, "fleet"))).status_code == 202


@pytest.mark.parametrize("scope", ["device", "fleet"])
@pytest.mark.parametrize("audit_fails", [False, True])
def test_cleanup_cancels_only_unstarted_system_restoration_atomically(lab, monkeypatch, scope, audit_fails):
    sync = lab[2].state.synchronizer
    sync.managed_discovery.source.initialize()
    with lab[0]._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")  # Disposable fixture only.
    assert sync.queue.claim_cycle("synthetic-worker", 135)
    current = datetime.now(UTC)
    sync.managed_discovery.source.admit_absence(CompleteSnapshot(str(uuid4()), 1, current, current, frozenset()),
                                               IP, "synthetic-worker", enabled=True)
    frozen = review(lab, scope)
    if audit_fails:
        original = lab[0]._insert_event
        def fail(db, event, *args, **kwargs):
            if event in {"MANAGED_SHUN_REMOVAL_ADMITTED", "MANAGED_SHUN_FLEET_REMOVAL_ADMITTED"}:
                raise sqlite3.OperationalError("synthetic rollback after system cancellation")
            return original(db, event, *args, **kwargs)
        monkeypatch.setattr(lab[0], "_insert_event", fail)
    before = dump(lab)
    response = asyncio.run(post(lab, frozen))
    assert response.status_code == (503 if audit_fails else 202)
    if audit_fails:
        assert dump(lab) == before
    else:
        with lab[0]._connection() as db:
            assert db.execute("SELECT state FROM managed_restoration_attempts").fetchone()[0] == "CANCELLED"
            assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == (1 if scope == "device" else 2)
