"""Bounded read selectors and single-pair BFF reviews on disposable state."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_managed_pagination import attempts, dump
from test_managed_pagination import lab as pagination_lab

from ftd_shun_manager import web
from ftd_shun_manager.managed_grant_review import ManagedGrantReviews
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import ManagedRestorations
from ftd_shun_manager.managed_review import select_managed_target
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_selection import require_selection
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedPageChanged, ManagedShuns
from ftd_shun_manager.store import Store

lab = pagination_lab


def test_exact_selection_is_bounded_sorted_and_not_global_membership(lab):
    store, _, api, registry, pairs = lab
    attempts(lab)
    context = api.state.synchronizer.managed_discovery.context
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    missing = (1, IPv4Address("198.51.100.1"))
    selected = [pairs[250], missing, pairs[0]]
    before = dump(store)
    result = registry.selection(selected, revision=1, restoration_context=context, restoration_now=now)
    assert result["read_only"] and result["read_scope"] == "selected_pairs"
    assert result["total"] == 251 and result["selected_count"] == 2 and len(result["selection"]) == 3
    assert result["selection"] == [{"device_id": device, "ip": str(ip)} for device, ip in sorted(selected)]
    assert len(result["entries"]) == 2
    full = registry.snapshot_if_present(restoration_context=context, restoration_now=now)
    assert result["entries"] == [full["entries"][index] for index in (0, 250)]
    assert all(row["restoration_attention"] and row["restoration_state"] == "NOOP" for row in result["entries"])
    assert dump(store) == before


def test_restarted_reader_and_revision_conflict_do_not_rebase(lab):
    store, _, _, registry, pairs = lab
    before = registry.selection([pairs[0]])
    assert ManagedShuns(Store(store.path)).selection([pairs[0]]) == before
    registry.change(str(uuid4()), "RETIRE", [pairs[0]], 1, 0,
                    canonical_managed_change("RETIRE", [pairs[0]], 1, 0)[2], "synthetic", "Synthetic", ("Operator",))
    state = dump(store)
    with pytest.raises(ManagedPageChanged):
        registry.selection([pairs[0]], revision=before["revision"])
    assert not registry.selection([pairs[0]])["entries"][0]["enabled"]
    assert dump(store) == state


@pytest.mark.parametrize("pairs", [[], [(True, IPv4Address("192.0.2.1"))], [(1, "192.0.2.1")],
                                   [(0, IPv4Address("192.0.2.1"))], [[1, IPv4Address("192.0.2.1")]],
                                   [(1, IPv4Address("192.0.2.1"))] * 2,
                                   [(i + 1, IPv4Address("192.0.2.1")) for i in range(101)]])
def test_bad_or_unbounded_selector_never_reads_as_a_valid_scope(lab, pairs):
    store, _, _, registry, _ = lab
    before = dump(store)
    with pytest.raises(ValueError):
        registry.selection(pairs)
    assert dump(store) == before


def test_maximum_selection_returns_100_not_full_251_and_scopes_attempt_queries(lab, monkeypatch):
    _, _, api, registry, pairs = lab
    attempts(lab)
    import ftd_shun_manager.managed_restoration as restoration

    original = restoration.snapshot_targets
    seen = []

    def bounded(db, *, pairs=None):
        assert pairs is not None and len(pairs) == 100
        db.set_trace_callback(seen.append)
        return original(db, pairs=pairs)

    monkeypatch.setattr(restoration, "snapshot_targets", bounded)
    value = registry.selection(pairs[:100], restoration_context=api.state.synchronizer.managed_discovery.context)
    assert value["selected_count"] == 100 and value["total"] == 251
    assert any("JOIN selected" in sql and "managed_restoration_attempts" in sql for sql in seen)
    assert any("JOIN selected" in sql and "operation_jobs" in sql for sql in seen)
    assert not any("LIMIT 10001" in sql for sql in seen)


def test_absent_missing_and_partial_state_are_distinct_without_initialization(tmp_path):
    store = Store(tmp_path / "base.db")
    store.initialize()
    registry = ManagedShuns(store)
    before = dump(store)
    pair = [(1, IPv4Address("198.51.100.1"))]
    value = registry.selection(pair)
    assert not value["initialized"] and value["total"] == 0 and value["selected_count"] == 0
    assert len(value["selection"]) == 1 and value["entries"] == []
    assert dump(store) == before
    registry.initialize()
    assert registry.selection(pair)["initialized"]
    with store._connection() as db:
        db.execute("ALTER TABLE managed_shun_targets RENAME COLUMN enabled TO broken")
    before = dump(store)
    with pytest.raises(ManagedStateUnavailable):
        registry.selection(pair)
    assert dump(store) == before


def test_orphan_outside_selection_never_hidden_as_valid_empty_result(lab):
    store, _, _, registry, pairs = lab
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE managed_shun_targets SET authorization_request_id=? WHERE ip=?",
                   (str(uuid4()), pairs[-1][1].packed))
    before = dump(store)
    with pytest.raises(ManagedConflict, match="missing"):
        registry.selection([pairs[0]])
    assert dump(store) == before


def test_read_metadata_and_membership_stay_in_one_snapshot_during_concurrent_retirement(lab, monkeypatch):
    _, _, _, registry, pairs = lab
    original = registry._entries
    changed = []

    def convert(rows, restoration, holds):
        if not changed:
            changed.append(True)
            registry.change(str(uuid4()), "RETIRE", [pairs[0]], 1, 0,
                            canonical_managed_change("RETIRE", [pairs[0]], 1, 0)[2], "synthetic", "Synthetic", ("Operator",))
        return original(rows, restoration, holds)

    monkeypatch.setattr(registry, "_entries", convert)
    value = registry.selection([pairs[0]])
    assert value["revision"] == 1 and value["entries"][0]["enabled"]
    assert registry.selection([pairs[0]])["revision"] == 2


def test_single_review_rejects_partial_or_wrong_selection_instead_of_treating_it_as_global(lab):
    _, _, _, registry, pairs = lab
    value = registry.selection([pairs[0]])
    assert select_managed_target(value, *pairs[0])["ip"] == str(pairs[0][1])
    with pytest.raises(ValueError, match="selection"):
        select_managed_target(value, *pairs[1])
    with pytest.raises(ValueError, match="page"):
        select_managed_target(registry.page(), *pairs[0])
    with pytest.raises(ValueError, match="selection"):
        require_selection({**value, "total": 0}, [pairs[0]])
    with pytest.raises(ValueError, match="selection"):
        require_selection({**value, "selected_count": True}, [pairs[0]])


def test_single_grant_accepts_absent_selected_pair_without_adopting_an_unrelated_policy(lab):
    _, _, _, registry, _ = lab
    ip = IPv4Address("198.51.100.1")
    selection = registry.selection([(1, ip)])
    classification = {"policy_revision": 0, "addresses": [{"ip": str(ip), "protected": False,
                        "devices": [{"id": 1, "hostname": "synthetic", "already_shunned": False}]}]}
    result = ManagedGrantReviews.validate(selection, classification, 1, ip)
    assert result["intent_id"] is None and not result["enabled"] and result["managed_revision"] == 1


@pytest.mark.parametrize("change", ["missing_scope", "wrong_scope", "wrong_pair", "coerced_device", "wrong_count", "duplicate_entry"])
def test_bff_adapter_refuses_partial_or_substituted_read_contracts(lab, change):
    _, _, _, registry, pairs = lab
    value = registry.selection([pairs[0]])
    if change == "missing_scope":
        value.pop("read_scope")
        value.pop("selection")
    elif change == "wrong_scope":
        value["read_scope"] = "page"
    elif change == "wrong_pair":
        value["selection"][0]["ip"] = "198.51.100.1"
    elif change == "coerced_device":
        value["selection"][0]["device_id"] = True
    elif change == "wrong_count":
        value["selected_count"] = 0
    else:
        value["entries"].append(value["entries"][0])
        value["selected_count"] = 2
    with (httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)), base_url="http://synthetic") as client,
          pytest.raises(ValueError)):
        web.selected_policy_response(client, *pairs[0])


@pytest.mark.parametrize("body", [
    {"targets": []}, {"targets": [{"device_id": True, "ip": "192.0.2.1"}]},
    {"targets": [{"device_id": "1", "ip": "192.0.2.1"}]},
    {"targets": [{"device_id": 1, "ip": 3221225985}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.01"}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1", "action": "RETIRE"}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}] * 2},
    {"targets": [{"device_id": i + 1, "ip": "192.0.2.1"} for i in range(101)]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}], "revision": True},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}], "actor": {"subject": "other"}},
])
def test_api_rejects_nonliteral_coerced_duplicate_and_unknown_read_fields(lab, body):
    store, _, api, _, _ = lab
    before = dump(store)

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
            response = await client.post("/api/v1/managed-shuns/selection", json=body)
            assert response.status_code == 422 and response.headers["cache-control"] == "no-store"

    asyncio.run(call())
    assert dump(store) == before


def test_api_reports_conflict_and_partial_attempt_state_honestly(lab):
    store, _, api, _, pairs = lab

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
            body = {"targets": [{"device_id": pairs[0][0], "ip": str(pairs[0][1])}]}
            response = await client.post("/api/v1/managed-shuns/selection", json={**body, "revision": 0})
            assert response.status_code == 409
            response = await client.post("/api/v1/managed-shuns/selection", json=body)
            assert response.status_code == 200 and response.json()["total"] == 251
            ManagedRestorations(store, api.state.synchronizer.queue).initialize()
            with store._connection() as db:
                db.execute("ALTER TABLE managed_restoration_attempts RENAME COLUMN state TO broken")
            response = await client.post("/api/v1/managed-shuns/selection", json=body)
            assert response.status_code == 503 and "entries" not in response.json()

    asyncio.run(call())


@pytest.mark.parametrize("kind", ["grant", "retirement", "removal"])
def test_bff_single_pair_reviews_use_only_exact_read_and_never_full_registry(lab, monkeypatch, kind):
    store, settings, api, _, pairs = lab
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Single-pair browser review must not load the whole registry")

    monkeypatch.setattr(ManagedShuns, "snapshot", forbidden)

    def internal(request):
        calls.append(request)

        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
                response = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        return asyncio.run(call())

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://synthetic"))
    app = web.create_app(settings)
    before = dump(store)

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test",
                                    headers={"Remote-User": "operator", "Remote-Groups": "ftd-shun-operators"}) as client:
            assert (await client.get("/managed-shuns")).status_code == 200
            fields = {"csrf": client.cookies.get("ftd_shun_csrf"), "reason": "Synthetic only"}
            if kind == "grant":
                fields.update(device_id="1", ip="198.51.100.1")
            else:
                fields["target"] = f"1:{pairs[0][1]}"
            response = await client.post(f"/managed-shuns/{kind}-review", data=fields)
            assert response.status_code == 200, response.text
            selected = [r for r in calls if r.url.path.endswith("/selection")]
            assert len(selected) == 1 and len(json.loads(selected[0].content)["targets"]) == 1
            assert not any(r.url.path == "/api/v1/managed-shuns" or "refresh-hint" in r.url.path for r in calls)
            assert not any(r.url.path.endswith(("/maintain", "/retire", "/device")) for r in calls)

    asyncio.run(call())
    assert dump(store) == before
