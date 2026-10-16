"""Active-list order is local policy/current-appearance state, not CLI order."""

import asyncio
import re
from dataclasses import replace
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

OLD = "2026-10-14T10:00:00.000Z"
RECENT = "2026-10-15T10:00:00.000Z"
NEW = "2026-10-16T10:00:00.000Z"
POLL = "2026-10-16T10:05:00.000Z"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    for device_id, hostname in [(1, "zeta"), (2, "alpha")]:
        store.upsert_device(Device(device_id, hostname, IPv4Address(f"192.0.2.{device_id}"), True),
                            "ssh-ed25519 AAAA")
    return store


def observe(store, monkeypatch, ip, timestamp, device_id=1, interface="outside"):
    monkeypatch.setattr("ftd_shun_manager.store.now", lambda: timestamp)
    store.record_observed_shun(device_id, IPv4Address(ip), interface)


def policy_change(store, action, ip, **values):
    policy = ProtectedPolicy(store)
    policy.change(action, IPv4Address(ip), policy.revision(), "test", "Test", ("Viewer",), **values)


def addresses(store):
    return [str(shun.ip) for shun in store.list_active_shuns()]


def test_policy_matches_first_then_newest_with_numeric_ip_hostname_interface_ties(state, monkeypatch):
    observe(state, monkeypatch, "198.51.100.200", OLD)
    observe(state, monkeypatch, "198.51.100.201", RECENT)
    policy_change(state, "add", "198.51.100.200", enabled=True)
    policy_change(state, "add", "198.51.100.201", enabled=False)
    # Deliberately reverse CLI/insertion order; equal observations have stable ties.
    observe(state, monkeypatch, "198.51.100.10", NEW)
    observe(state, monkeypatch, "198.51.100.2", NEW, interface="vpn")
    observe(state, monkeypatch, "198.51.100.2", NEW)
    observe(state, monkeypatch, "198.51.100.2", NEW, device_id=2)
    observe(state, monkeypatch, "198.51.100.1", OLD)
    expected = [
        ("198.51.100.201", "zeta", "outside"),
        ("198.51.100.200", "zeta", "outside"),
        ("198.51.100.2", "alpha", "outside"),
        ("198.51.100.2", "zeta", "outside"),
        ("198.51.100.2", "zeta", "vpn"),
        ("198.51.100.10", "zeta", "outside"),
        ("198.51.100.1", "zeta", "outside"),
    ]
    assert [(str(s.ip), s.device_hostname, s.interface) for s in state.list_active_shuns()] == expected
    assert [s.device_hostname for s in state.list_active_shuns(IPv4Address("198.51.100.2"))] == [
        "alpha", "zeta", "zeta",
    ]
    assert ProtectedPolicy(state).enabled_ips() == {IPv4Address("198.51.100.200")}
    assert ProtectedPolicy(state).queue.status()["counts"] == {}, "Sorting must not create work"


@pytest.mark.parametrize("use_snapshot", [False, True])
def test_polling_preserves_order_but_reappearance_moves_up_without_rewriting_first_seen(state, monkeypatch, use_snapshot):
    older, newer = IPv4Address("198.51.100.1"), IPv4Address("198.51.100.2")

    def seen(ips, timestamp):
        monkeypatch.setattr("ftd_shun_manager.store.now", lambda: timestamp)
        if use_snapshot:
            state.reconcile_snapshot(1, [(ip, "outside") for ip in ips])
        else:
            for ip in ips:
                state.record_observed_shun(1, ip, "outside")

    seen([older], OLD)
    seen([older, newer], RECENT)
    assert addresses(state) == [str(newer), str(older)]
    seen([newer, older], NEW)
    assert addresses(state) == [str(newer), str(older)]
    assert [s.active_since_at for s in state.list_active_shuns()] == [RECENT, OLD]
    assert all(s.last_seen_at == NEW for s in state.list_active_shuns())
    state.reconcile_snapshot(1, [(newer, "outside")])
    assert addresses(state) == [str(newer)]
    seen([older, newer], POLL)
    assert addresses(state) == [str(older), str(newer)]
    shun = state.list_active_shuns()[0]
    assert shun.active_since_at == POLL and shun.first_seen_at == OLD


def test_policy_edits_reorder_locally_and_inactive_policy_entries_are_not_listed(state, monkeypatch):
    observe(state, monkeypatch, "198.51.100.1", OLD)
    observe(state, monkeypatch, "198.51.100.2", NEW)
    policy_change(state, "add", "198.51.100.3")
    assert addresses(state) == ["198.51.100.2", "198.51.100.1"]
    policy_change(state, "add", "198.51.100.1")
    assert addresses(state) == ["198.51.100.1", "198.51.100.2"]
    policy_change(state, "edit", "198.51.100.1", enabled=False)
    assert addresses(state) == ["198.51.100.1", "198.51.100.2"]
    policy_change(state, "delete", "198.51.100.1")
    assert addresses(state) == ["198.51.100.2", "198.51.100.1"]


def test_complete_twenty_thousand_row_snapshot_keeps_all_rows_in_sorted_groups(state, monkeypatch):
    base = int(IPv4Address("198.18.0.0"))
    ips = [IPv4Address(base + index) for index in range(1, 20001)]
    monkeypatch.setattr("ftd_shun_manager.store.now", lambda: OLD)
    state.reconcile_snapshot(1, [(ip, "outside") for ip in ips[:10000]])
    policy_change(state, "add", str(ips[0]))
    policy_change(state, "add", str(ips[1]), enabled=False)
    monkeypatch.setattr("ftd_shun_manager.store.now", lambda: NEW)
    state.reconcile_snapshot(1, [(ip, "outside") for ip in reversed(ips)])
    rows = state.list_active_shuns()
    assert [s.ip for s in rows] == ips[:2] + ips[10000:] + ips[2:10000]
    assert len(rows) == 20000
    assert rows[2].active_since_at == NEW and rows[-1].active_since_at == OLD


def test_api_and_bff_preserve_active_order_and_current_appearance_timestamp(state, monkeypatch):
    observe(state, monkeypatch, "198.51.100.1", OLD)
    observe(state, monkeypatch, "198.51.100.2", RECENT)
    policy_change(state, "add", "198.51.100.1", enabled=False)
    config = replace(Settings.from_environment(), database_path=state.path,
                     device_inventory_path=None, agent_mode="disabled", development_auth=False)
    app = create_app(config, store=state)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as api:
            response = await api.get("/api/v1/shuns")
            assert response.status_code == 200
            shuns = response.json()
            assert [s["ip"] for s in shuns] == ["198.51.100.1", "198.51.100.2"]
            assert [s["active_since_at"] for s in shuns] == [OLD, RECENT]
            assert (await api.get("/api/v1/shuns/198.51.100.1")).json() == [shuns[0]]
            refresh = (await api.get("/api/v1/status")).json()

        def internal(request):
            assert request.method == "GET", "Rendering must not dispatch work"
            return httpx.Response(200, json=shuns if request.url.path == "/api/v1/shuns" else refresh)

        monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(
            transport=httpx.MockTransport(internal), base_url="http://internal"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)),
                                     base_url="https://lab.test", headers={"Remote-User": "viewer"}) as client:
            page = await client.get("/")
            assert page.status_code == 200
            active = page.text.split('<section id="active-shuns"', 1)[1]
            assert re.findall(r'<a href="/shuns/([0-9.]+)">', active) == ["198.51.100.1", "198.51.100.2"]
            assert "Observed since" in active and f'datetime="{OLD}"' in active
            assert 'class="disabled-protection-shun"' in active

    asyncio.run(scenario())
