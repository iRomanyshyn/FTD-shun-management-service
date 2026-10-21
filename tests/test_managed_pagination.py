"""Bounded managed reads: synthetic SQLite/ASGI only, never lab authority."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.managed_discovery import RestorationContext
from ftd_shun_manager.managed_restoration import ManagedRestorations, read_scope, snapshot_targets
from ftd_shun_manager.managed_shuns import (
    ManagedConflict,
    ManagedPageChanged,
    ManagedShuns,
    canonical_managed_change,
)
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "synthetic.db")
    settings = replace(Settings.from_environment(), database_path=store.path,
                       device_inventory_path=None, development_auth=False, agent_mode="disabled")
    api = create_app(settings, store)
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    registry = ManagedShuns(store)
    registry.initialize()
    pairs = [(1, IPv4Address(0xC6120000 + i)) for i in range(251)]
    with store._connection() as db:
        protection = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), "MAINTAIN", pairs, 0, protection,
                    canonical_managed_change("MAINTAIN", pairs, 0, protection, "<b>Bulk</b>")[2],
                    "synthetic", "Synthetic", ("Operator",), "<b>Bulk</b>")
    return store, settings, api, registry, pairs


def dump(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def attempts(lab):
    store, _, api, registry, _ = lab
    ManagedRestorations(store, api.state.synchronizer.queue).initialize()
    targets = registry.snapshot()["entries"]
    with store._connection() as db:
        for index in (0, 100, 250):
            target = targets[index]
            # Disposable retained historical evidence, not a device success claim.
            for number, state in enumerate(("VERIFIED", "FAILED", "NOOP")):
                db.execute("""INSERT INTO managed_restoration_attempts(
                    id,job_id,device_id,ip,intent_id,generation,authorization_request_id,target_revision,
                    snapshot_id,snapshot_started_at,snapshot_at,requested_at,state,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        str(uuid4()), str(uuid4()), 1, IPv4Address(target["ip"]).packed,
                        target["intent_id"], target["generation"], target["authorization_request_id"], target["revision"],
                        str(uuid4()), "2026-10-21T10:00:00Z", "2026-10-21T10:00:01Z",
                        f"2026-10-21T10:0{number}:02Z", state, f"2026-10-21T10:0{number}:03Z"))


def test_pages_are_bounded_deterministic_and_equal_legacy_view(lab):
    store, _, api, registry, _ = lab
    attempts(lab)
    context = api.state.synchronizer.managed_discovery.context
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    before = dump(store)
    full = registry.snapshot_if_present(restoration_context=context, restoration_now=now)
    pages = [registry.page(i, revision=1, restoration_context=context, restoration_now=now) for i in (1, 2, 3)]
    assert [len(page["entries"]) for page in pages] == [100, 100, 51]
    assert all(page["total"] == 251 and page["pages"] == 3 and page["page_size"] == 100 for page in pages)
    assert [entry for page in pages for entry in page["entries"]] == full["entries"]
    assert len({entry["ip"] for page in pages for entry in page["entries"]}) == 251
    for page in pages:
        entry = next(entry for entry in page["entries"] if "restoration_state" in entry)
        assert entry["restoration_state"] == "NOOP" and entry["restoration_attention"]
        assert entry["last_verified_restoration_at"] == "2026-10-21T10:00:03Z"
    assert dump(store) == before


def test_restart_and_policy_revision_conflicts_never_rebase(lab):
    store, _, _, registry, pairs = lab
    first = registry.page()
    restarted = ManagedShuns(Store(store.path))
    assert restarted.page(2, revision=first["revision"]) == registry.page(2)
    target = [pairs[0]]
    registry.change(str(uuid4()), "RETIRE", target, 1, 0,
                    canonical_managed_change("RETIRE", target, 1, 0)[2], "synthetic", "Synthetic", ("Operator",))
    before = dump(store)
    with pytest.raises(ManagedPageChanged, match="changed"):
        restarted.page(2, revision=first["revision"])
    assert restarted.page(2)["revision"] == 2
    assert dump(store) == before


@pytest.mark.parametrize("page,revision", [(0, None), (-1, None), (True, None), (1.5, None),
                                          (2**31, None), (4, None), (1, True), (1, -1), (1, "1")])
def test_invalid_pages_refuse_without_clamping_or_mutation(lab, page, revision):
    store, _, _, registry, _ = lab
    before = dump(store)
    with pytest.raises(ValueError):
        registry.page(page, revision=revision)
    assert dump(store) == before


def test_absent_empty_and_partial_are_distinct(tmp_path):
    store = Store(tmp_path / "empty.db")
    store.initialize()
    registry = ManagedShuns(store)
    before = dump(store)
    page = registry.page()
    assert not page["initialized"] and page["total"] == 0 and page["entries"] == []
    assert page["pages"] == 1 and page["restoration_suspended"] and page["read_only"]
    assert dump(store) == before
    registry.initialize()
    assert registry.page()["initialized"]
    with store._connection() as db:
        db.execute("ALTER TABLE managed_shun_targets RENAME COLUMN authorization_request_id TO broken")
    before = dump(store)
    with pytest.raises(ValueError, match="unavailable"):
        registry.page()
    assert dump(store) == before


def test_orphaned_authority_outside_selected_page_is_not_hidden(lab):
    store, _, _, registry, pairs = lab
    # Only this private fixture disables foreign keys to model prior corruption.
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE managed_shun_targets SET authorization_request_id=? WHERE ip=?",
                   (str(uuid4()), pairs[-1][1].packed))
    before = dump(store)
    with pytest.raises(ManagedConflict, match="missing"):
        registry.page(1)
    assert dump(store) == before


def test_scoped_summaries_do_not_load_other_pairs_or_unbounded_rows(lab, monkeypatch):
    store, _, _, registry, _ = lab
    attempts(lab)
    import ftd_shun_manager.managed_restoration as restoration

    original = restoration.snapshot_targets
    seen = []
    def bounded(db, *, pairs=None):
        assert pairs is not None and len(pairs) == 100
        db.set_trace_callback(seen.append)
        result = original(db, pairs=pairs)
        assert len(result) == 1
        return result
    monkeypatch.setattr(restoration, "snapshot_targets", bounded)
    value = registry.page(2, restoration_context=RestorationContext())
    assert len(value["entries"]) == 100
    assert any("JOIN selected" in sql and "managed_restoration_attempts" in sql for sql in seen)
    assert any("JOIN selected" in sql and "operation_jobs" in sql for sql in seen)
    assert not any("LIMIT 10001" in sql for sql in seen)
    with store._connection() as db:
        assert snapshot_targets(db, pairs=[]) == {}
        assert len(snapshot_targets(db)) == 3


@pytest.mark.parametrize("pairs", [[(True, b"1234")], [(1, b"123")], [(1, b"1234")] * 2,
                                   [(i + 1, b"1234") for i in range(101)]])
def test_summary_scope_is_not_an_unbounded_or_coerced_field(pairs):
    with pytest.raises(ValueError):
        read_scope(pairs)


def test_api_and_web_pagination_auth_conflict_and_no_full_fallback(lab, monkeypatch):
    store, settings, api, registry, pairs = lab
    calls = []
    def internal(request):
        calls.append(request)
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
                response = await client.request(request.method, str(request.url))
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        return asyncio.run(send())
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    app = web.create_app(settings)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test") as client:
            assert (await client.get("/managed-shuns")).status_code == 401 and not calls
            client.headers["Remote-User"] = "viewer"
            before = dump(store)
            response = await client.get("/managed-shuns?page=2&revision=1")
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            assert "Page 2 of 3" in response.text and "251 / 1000" in response.text
            assert 'page=3&amp;revision=1' in response.text and 'page=1&amp;revision=1' in response.text
            assert "&lt;b&gt;Bulk&lt;/b&gt;" in response.text
            assert str(pairs[100][1]) in response.text and str(pairs[0][1]) not in response.text
            assert not any(call.url.path == "/api/v1/managed-shuns" for call in calls)
            assert all(call.method == "GET" for call in calls) and dump(store) == before
            target = [pairs[0]]
            registry.change(str(uuid4()), "RETIRE", target, 1, 0,
                            canonical_managed_change("RETIRE", target, 1, 0)[2], "synthetic", "Synthetic", ("Operator",))
            response = await client.get("/managed-shuns?page=2&revision=1")
            assert response.status_code == 200 and "Managed policy changed while" in response.text
            assert "has not been initialized" not in response.text and '<select id="managed-review-target"' not in response.text
            assert 'id="managed-shun-state" data-live-region' in response.text
            assert (await client.get("/managed-shuns?page=4")).status_code == 422
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://internal") as client:
            response = await client.get("/api/v1/managed-shuns/page?page=2&revision=1")
            assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
            for query in ("page=0", "page=4", "revision=-1", "page=true"):
                assert (await client.get("/api/v1/managed-shuns/page?" + query)).status_code == 422
            assert (await client.post("/api/v1/managed-shuns/page", json={})).status_code == 405
    asyncio.run(scenario())


def test_web_refuses_truncated_page_instead_of_showing_empty_state(lab, monkeypatch):
    _, settings, _, registry, _ = lab
    def internal(request):
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json={})
        value = registry.page()
        value["entries"] = value["entries"][:1]
        return httpx.Response(200, json=value)
    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(settings)),
                                     base_url="https://synthetic.test", headers={"Remote-User": "viewer"}) as client:
            response = await client.get("/managed-shuns")
            assert response.status_code == 503 and "incomplete" in response.text
            assert "No managed targets" not in response.text
    asyncio.run(scenario())


def test_paging_does_not_raise_the_policy_or_request_limits(lab):
    store, _, _, registry, _ = lab
    assert registry.page()["limit"] == 1000
    assert len(json.dumps(registry.page()["entries"])) < len(json.dumps(registry.snapshot()["entries"]))
    pairs = [(1, IPv4Address(0xC6120000 + i)) for i in range(251, 1000)]
    with store._connection() as db:
        protection = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    registry.change(str(uuid4()), "MAINTAIN", pairs, 1, protection,
                    canonical_managed_change("MAINTAIN", pairs, 1, protection)[2],
                    "synthetic", "Synthetic", ("Operator",))
    before = dump(store)
    pages = [registry.page(i, revision=2) for i in range(1, 11)]
    assert all(page["total"] == 1000 and len(page["entries"]) == 100 for page in pages)
    assert len({row["ip"] for page in pages for row in page["entries"]}) == 1000
    assert dump(store) == before
    with store._connection() as db:
        old = db.execute("SELECT * FROM managed_shun_targets LIMIT 1").fetchone()
        db.execute("INSERT INTO managed_shun_targets VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (1, IPv4Address("203.0.113.1").packed, str(uuid4()), 1, 1, 2,
                    old["authorization_request_id"], old["authorized_at"], old["updated_at"], None))
    with pytest.raises(ValueError, match="unavailable"):
        registry.page()
