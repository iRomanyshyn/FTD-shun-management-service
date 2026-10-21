"""Whole legacy batch selection: bounded SQL in one synthetic read snapshot."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_managed_pagination import attempts, dump
from test_managed_pagination import lab as pagination_lab

from ftd_shun_manager import web
from ftd_shun_manager.import_preview import classify_targets
from ftd_shun_manager.import_review import ReviewUnavailable
from ftd_shun_manager.managed_batch_review import ManagedBatchReviews, parse_standing_list
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import ManagedRestorations
from ftd_shun_manager.managed_selection import require_selection
from ftd_shun_manager.managed_shuns import ManagedPageChanged, ManagedShuns
from ftd_shun_manager.store import Store

lab = pagination_lab
PATH = "/api/v1/managed-shuns/selection/batch"


def retire(registry, pairs, revision=1):
    registry.change(str(uuid4()), "RETIRE", pairs, revision, 0,
                    canonical_managed_change("RETIRE", pairs, revision, 0)[2], "synthetic", "Synthetic", ("Operator",))


def prepare(registry, store, ips):
    pairs = [(1, ip) for ip in ips]
    policy = registry.batch_selection(pairs)
    parsed = parse_standing_list("\n".join(map(str, ips)), [1])
    return ManagedBatchReviews().prepare("synthetic", "cookie", policy, classify_targets(store, ips, [1]), parsed, [1])


def test_batch_read_matches_full_view_and_keeps_missing_selectors_distinct(lab):
    store, _, api, registry, pairs = lab
    attempts(lab)
    context = api.state.synchronizer.managed_discovery.context
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    requested = list(reversed(pairs)) + [(1, IPv4Address("198.51.100.250")), (65535, IPv4Address("192.0.2.1"))]
    before = dump(store)
    value = registry.batch_selection(requested, revision=1, restoration_context=context, restoration_now=now)
    assert value["read_scope"] == "selected_batch" and value["total"] == value["selected_count"] == 251
    assert len(value["selection"]) == 253
    assert value["selection"] == [{"device_id": device, "ip": str(ip)} for device, ip in sorted(requested)]
    assert value["entries"] == registry.snapshot_if_present(restoration_context=context, restoration_now=now)["entries"]
    require_selection(value, requested, batch=True)
    assert ManagedShuns(Store(store.path)).batch_selection(requested, restoration_context=context, restoration_now=now) == value
    assert dump(store) == before


def test_maximum_thousand_selectors_use_ten_bounded_summary_chunks_in_one_transaction(lab, monkeypatch):
    store, _, api, registry, pairs = lab
    more = [(1, IPv4Address(0xC6120000 + i)) for i in range(251, 1000)]
    protected = api.state.synchronizer.policy.revision()
    registry.change(str(uuid4()), "MAINTAIN", more, 1, protected, canonical_managed_change("MAINTAIN", more, 1, protected)[2],
                    "synthetic", "Synthetic", ("Operator",))
    attempts(lab)
    import ftd_shun_manager.managed_restoration as restoration

    original = restoration.snapshot_targets
    chunks, queries, connections = [], [], set()

    def bounded(db, *, pairs=None):
        assert pairs is not None and len(pairs) == 100 and db.in_transaction
        chunks.append(pairs)
        connections.add(id(db))
        db.set_trace_callback(queries.append)
        return original(db, pairs=pairs)

    monkeypatch.setattr(restoration, "snapshot_targets", bounded)
    before = dump(store)
    value = registry.batch_selection(pairs + more, restoration_context=api.state.synchronizer.managed_discovery.context)
    assert value["selected_count"] == value["total"] == 1000 and len(value["entries"]) == 1000
    assert len(chunks) == 10 and len(connections) == 1 and len({pair for chunk in chunks for pair in chunk}) == 1000
    assert not any("LIMIT 10001" in query for query in queries)
    assert all(query.count("VALUES") == 1 for query in queries if "JOIN selected" in query)
    assert dump(store) == before


def test_concurrent_retirement_between_chunks_cannot_mix_policy_revisions(lab, monkeypatch):
    _, _, _, registry, pairs = lab
    original = registry._entries
    changed = []

    def convert(rows, restoration, holds):
        if not changed:
            changed.append(True)
            retire(registry, [pairs[0], pairs[-1]])
        return original(rows, restoration, holds)

    monkeypatch.setattr(registry, "_entries", convert)
    value = registry.batch_selection(pairs)
    assert value["revision"] == 1 and all(entry["enabled"] for entry in value["entries"])
    after = registry.batch_selection(pairs)
    assert after["revision"] == 2 and not after["entries"][0]["enabled"] and not after["entries"][-1]["enabled"]
    with pytest.raises(ManagedPageChanged):
        registry.batch_selection(pairs, revision=1)


def test_global_capacity_not_selected_membership_controls_new_batch(lab):
    store, _, _, registry, _ = lab
    ips = [IPv4Address(0xC6130000 + i) for i in range(750)]
    before = dump(store)
    selection = registry.batch_selection([(1, ip) for ip in ips])
    assert selection["total"] == 251 and selection["selected_count"] == 0
    with pytest.raises(ReviewUnavailable, match="capacity"):
        prepare(registry, store, ips)
    assert len(prepare(registry, store, ips[:-1]).targets) == 749
    assert dump(store) == before


def test_stopped_selected_key_does_not_consume_a_new_capacity_slot(lab):
    store, _, _, registry, pairs = lab
    retire(registry, [pairs[0]])
    ips = [pairs[0][1]] + [IPv4Address(0xC6130000 + i) for i in range(749)]
    before = dump(store)
    review = prepare(registry, store, ips)
    assert len(review.targets) == 750 and review.targets[0].generation == 1
    assert dump(store) == before


def test_one_enabled_or_uncertain_member_refuses_the_entire_selected_batch(lab):
    store, _, _, registry, pairs = lab
    ips = [IPv4Address("198.51.100.250"), pairs[-1][1]]
    before = dump(store)
    with pytest.raises(ReviewUnavailable, match="already maintained"):
        prepare(registry, store, ips)
    assert dump(store) == before
    retire(registry, [pairs[-1]])
    attempts(lab)
    before = dump(store)
    with pytest.raises(ReviewUnavailable, match="attention"):
        prepare(registry, store, ips)
    assert dump(store) == before


@pytest.mark.parametrize("change", ["single_scope", "wrong_pair", "missing_pair", "duplicate_pair", "duplicate_entry",
                                   "wrong_count", "coerced_total", "missing_scope", "page", "full"])
def test_batch_adapter_never_accepts_substituted_or_partial_views(lab, change):
    _, _, _, registry, pairs = lab
    requested = pairs[:2]
    value = deepcopy(registry.batch_selection(requested))
    if change == "single_scope": value["read_scope"] = "selected_pairs"
    elif change == "wrong_pair": value["selection"][0]["ip"] = "198.51.100.250"
    elif change == "missing_pair": value["selection"].pop()
    elif change == "duplicate_pair": value["selection"][1] = value["selection"][0]
    elif change == "duplicate_entry": value["entries"][1] = value["entries"][0]
    elif change == "wrong_count": value["selected_count"] = 1
    elif change == "coerced_total": value["total"] = True
    elif change == "missing_scope": value.pop("read_scope")
    elif change == "page": value = registry.page()
    else: value = registry.snapshot_if_present()
    with (httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)), base_url="http://synthetic") as client,
          pytest.raises(ValueError)):
        web.selected_policy_read(client, requested, batch=True)


@pytest.mark.parametrize("body", [
    {"targets": []}, {"targets": [{"device_id": True, "ip": "192.0.2.1"}]},
    {"targets": [{"device_id": "1", "ip": "192.0.2.1"}]},
    {"targets": [{"device_id": 1, "ip": 3221225985}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.01"}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1", "action": "MAINTAIN"}]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}] * 2},
    {"targets": [{"device_id": i + 1, "ip": "192.0.2.1"} for i in range(1001)]},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}], "revision": True},
    {"targets": [{"device_id": 1, "ip": "192.0.2.1"}], "actor": {"subject": "other"}},
])
def test_strict_batch_read_api_cannot_coerce_expand_or_gain_write_fields(lab, body):
    store, _, api, _, _ = lab
    before = dump(store)

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
            response = await client.post(PATH, json=body)
            assert response.status_code == 422 and response.headers["cache-control"] == "no-store"

    asyncio.run(call())
    assert dump(store) == before


def test_api_conflict_partial_schema_and_late_chunk_error_never_return_partial_success(lab, monkeypatch):
    store, _, api, _, pairs = lab
    body = {"targets": [{"device_id": device, "ip": str(ip)} for device, ip in pairs]}

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://synthetic") as client:
            assert (await client.post(PATH, json={**body, "revision": 0})).status_code == 409
            assert (await client.post(PATH, json=body)).json()["selected_count"] == 251
            original = ManagedShuns._entries
            chunks = []

            def fail_last(rows, restoration, holds):
                chunks.append(True)
                if len(chunks) == 3:
                    raise ValueError("Synthetic malformed last chunk")
                return original(rows, restoration, holds)

            with monkeypatch.context() as patch:
                patch.setattr(ManagedShuns, "_entries", staticmethod(fail_last))
                response = await client.post(PATH, json=body)
                assert response.status_code == 503 and "entries" not in response.json()
            ManagedRestorations(store, api.state.synchronizer.queue).initialize()
            with store._connection() as db:
                db.execute("ALTER TABLE managed_restoration_attempts RENAME COLUMN state TO broken")
            response = await client.post(PATH, json=body)
            assert response.status_code == 503 and "entries" not in response.json()

    asyncio.run(call())
    with store._connection() as db:
        assert db.execute("SELECT revision FROM managed_shun_registry").fetchone()[0] == 1


def test_absent_optional_state_returns_explicit_uninitialized_without_migration(tmp_path):
    store = Store(tmp_path / "empty.db")
    store.initialize()
    before = dump(store)
    value = ManagedShuns(store).batch_selection([(1, IPv4Address("192.0.2.1"))])
    assert not value["initialized"] and value["total"] == value["selected_count"] == 0
    assert value["read_scope"] == "selected_batch" and len(value["selection"]) == 1
    assert dump(store) == before


@pytest.mark.parametrize("count", [2, 1000])
def test_bff_prepares_whole_selected_batch_without_full_registry_or_individual_reads(lab, monkeypatch, count):
    store, settings, api, registry, _ = lab
    calls = []
    # Make room in disposable synthetic state; no live fixture or grant is used.
    if count == 1000:
        ips = [IPv4Address(0xC6120000 + i) for i in range(1000)]
        retire(registry, [(1, ip) for ip in ips[:251]])
    else:
        ips = [IPv4Address("198.51.100.250"), IPv4Address("198.51.100.251")]

    def forbidden(*args, **kwargs):
        raise AssertionError("Batch review cannot load a whole-registry snapshot")

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
                                    headers={"Remote-User": "synthetic", "Remote-Groups": "ftd-shun-operators"}) as client:
            await client.get("/managed-shuns/bulk")
            result = await client.post("/managed-shuns/bulk-review", data={"csrf": client.cookies.get("ftd_shun_csrf"),
                "device_ids": "1", "text": "\n".join(map(str, ips))})
            assert result.status_code == 200 and f"{count} device/IP pairs" in result.text, result.text
            assert len([request for request in calls if request.url.path == PATH]) == 1
            assert not any(request.url.path in {"/api/v1/managed-shuns", "/api/v1/managed-shuns/selection", "/api/v1/refresh-hint"}
                           or request.url.path.endswith("maintain-batch") for request in calls)

    asyncio.run(call())
    assert dump(store) == before
