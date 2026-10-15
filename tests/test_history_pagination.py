import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.store import HistoryWindowExpired, Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "history.db")
    value.initialize()
    return value


def append(store, count, prefix="EVENT"):
    with store._connection() as db:
        for index in range(count):
            store._insert_event(db, f"{prefix}_{index:03}", None, None, None, "fixture", "Fixture",
                                (), None, {}, "2026-10-15T10:00:00.000Z")


def test_empty_history_and_invalid_page_bounds(store):
    page = store.history_page()
    assert page == {"events": [], "page": 1, "pages": 1, "total": 0, "page_size": 100, "anchor": None}
    for value in [0, -1, 2**31]:
        with pytest.raises(ValueError, match="page"):
            store.history_page(value)


def test_fixed_size_deterministic_ties_and_no_overlap(store):
    append(store, 251)
    first = store.history_page()
    second = store.history_page(2, first["anchor"])
    third = store.history_page(3, first["anchor"])
    assert [len(page["events"]) for page in [first, second, third]] == [100, 100, 51]
    assert first["total"] == 251 and first["pages"] == 3
    events = first["events"] + second["events"] + third["events"]
    assert len({event["id"] for event in events}) == 251
    assert [event["event_type"] for event in events] == [f"EVENT_{index:03}" for index in reversed(range(251))]
    assert store.history_page(2**31 - 1, first["anchor"])["page"] == 3


def test_new_events_cannot_shift_anchored_pages_but_live_page_updates(store):
    append(store, 251)
    first = store.history_page()
    second = store.history_page(2, first["anchor"])
    append(store, 12, "NEW")
    assert store.history_page(2, first["anchor"]) == second
    assert store.history_page(1, first["anchor"]) == first
    live = store.history_page()
    assert live["total"] == 263 and live["events"][0]["event_type"] == "NEW_011"


def test_retention_shortens_pages_and_expired_anchor_is_explicit(store):
    append(store, 251)
    first = store.history_page()
    with store._connection() as db:
        db.execute("DELETE FROM shun_events WHERE rowid<=200")
    shortened = store.history_page(3, first["anchor"])
    assert shortened["page"] == shortened["pages"] == 1
    assert shortened["total"] == len(shortened["events"]) == 51
    with store._connection() as db:
        db.execute("DELETE FROM shun_events WHERE id=?", (first["anchor"],))
    with pytest.raises(HistoryWindowExpired):
        store.history_page(1, first["anchor"])


def test_restore_hex_uuid_anchor_survives_api_uuid_normalization(store):
    append(store, 1)
    anchor = uuid4()
    with store._connection() as db:
        db.execute("UPDATE shun_events SET id=?", (anchor.hex,))
    assert store.history_page(anchor=str(anchor))["anchor"] == anchor.hex


def test_counts_and_rows_share_snapshot_during_concurrent_append(store):
    append(store, 20)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(append, store, 200, "CONCURRENT")
        for _ in range(15):
            page = store.history_page()
            assert len(page["events"]) == min(100, page["total"])
            assert page["pages"] == max(1, (page["total"] + 99) // 100)
        writer.result()


def test_paged_api_is_readonly_bounded_and_legacy_history_stays_a_list(store, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    append(store, 251)
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None, agent_mode="disabled")
    app = create_app(config, store)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            for query in ["page=0", "page=-1", "page=2147483648", "page=1.5", "anchor=invalid"]:
                assert (await client.get("/api/v1/history-page?" + query)).status_code == 422
            first = (await client.get("/api/v1/history-page")).json()
            assert first["total"] == 251 and len(first["events"]) == 100
            second = await client.get("/api/v1/history-page", params={"page": 2, "anchor": first["anchor"]})
            assert second.status_code == 200 and second.json()["page"] == 2
            assert second.headers["cache-control"] == "no-store"
            assert (await client.get("/api/v1/history-page", params={"anchor": str(uuid4())})).status_code == 410
            legacy = (await client.get("/api/v1/history", params={"limit": 7})).json()
            assert isinstance(legacy, list) and len(legacy) == 7
            assert app.state.synchronizer.queue.status()["counts"] == {}
    asyncio.run(scenario())


def test_bff_pagination_auth_anchor_forwarding_and_expiration(store, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    append(store, 251)
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode="disabled", development_auth=False)
    api = create_app(config, store)
    status_route = next(r for r in api.routes if r.path == "/api/v1/status")
    requests = []

    def internal(request):
        requests.append(request)
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=asyncio.run(status_route.endpoint()))
        assert request.url.path == "/api/v1/history-page"
        try:
            page = store.history_page(int(request.url.params["page"]), request.url.params.get("anchor"))
            return httpx.Response(200, json=page)
        except HistoryWindowExpired:
            return httpx.Response(410, json={"detail": "expired"})

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://lab.test") as client:
            assert (await client.get("/history")).status_code == 401
            assert requests == []
            client.headers["Remote-User"] = "viewer"
            response = await client.get("/history")
            assert response.status_code == 200 and "Page 1 of 3" in response.text
            assert 'id="recent-events-details"' not in response.text
            assert 'data-auto-request="false"' in response.text
            assert "EVENT_250" in response.text and "EVENT_150" not in response.text
            second = await client.get("/history?page=2")
            assert second.status_code == 303 and "anchor=" in second.headers["location"]
            page = await client.get(second.headers["location"])
            assert page.status_code == 200 and "Page 2 of 3" in page.text
            assert "EVENT_150" in page.text and "EVENT_050" not in page.text
            assert requests[-1].url.params["page"] == "2"
            assert UUID(requests[-1].url.params["anchor"])
            assert (await client.get("/history?page=0")).status_code == 422
            expired = await client.get("/history", params={"page": 2, "anchor": str(uuid4())})
            assert expired.status_code == 200 and "no longer retained" in expired.text
            assert "Open Latest events" in expired.text
            assert page.headers["cache-control"] == "no-store"
            assert not any(r.method != "GET" for r in requests)
    asyncio.run(scenario())
