from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.store import Device, Store


def test_verified_removal_updates_every_matching_interface(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    target = IPv4Address("203.0.113.17")
    store.record_observed_shun(1, target, "outside")
    store.record_observed_shun(1, target, "vpn")

    assert store.complete_removal(1, target, "alice", "Alice", ("Operator",), "request-1")
    assert store.list_active_shuns(target) == []
    assert not store.complete_removal(1, target, "alice", "Alice", ("Operator",), "request-2")


def test_reconcile_snapshot_tracks_detection_disappearance_and_reappearance(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    target = IPv4Address("203.0.113.17")

    store.reconcile_snapshot(1, [(target, "outside")])
    assert [(str(shun.ip), shun.interface) for shun in store.list_active_shuns()] == [
        ("203.0.113.17", "outside")
    ]
    assert [event["event_type"] for event in store.list_events()] == ["SHUN_DETECTED"]

    store.reconcile_snapshot(1, [(target, "outside")])
    assert [event["event_type"] for event in store.list_events()] == ["SHUN_DETECTED"]

    store.reconcile_snapshot(1, [])
    assert store.list_active_shuns() == []
    disappeared = store.list_events()[0]
    assert disappeared["event_type"] == "SHUN_DISAPPEARED"
    assert disappeared["details"] == {"observed_during_reconciliation": True}

    store.reconcile_snapshot(1, [(target, "outside")])
    assert [event["event_type"] for event in store.list_events()] == [
        "SHUN_REAPPEARED",
        "SHUN_DISAPPEARED",
        "SHUN_DETECTED",
    ]


def test_trusted_policy_status_includes_never_and_last_verified_removal(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    removed = IPv4Address("198.51.100.10")
    never_removed = IPv4Address("203.0.113.11")
    store.record_observed_shun(1, removed, "outside")
    store.complete_trusted_auto_removal(1, removed, "policy-request-1")

    status = store.list_trusted_auto_removal_status({removed, never_removed})

    assert [entry["ip"] for entry in status] == ["198.51.100.10", "203.0.113.11"]
    assert status[0]["last_auto_removed_at"] is not None
    assert status[1]["last_auto_removed_at"] is None


def test_history_retention_purges_expired_events_and_inactive_state_only(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    reference = datetime(2026, 10, 14, tzinfo=UTC)
    old_timestamp = (reference - timedelta(days=367)).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    retained_timestamp = (reference - timedelta(days=365)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    inactive_ip = IPv4Address("198.51.100.10")
    active_ip = IPv4Address("198.51.100.11")
    retained_event_ip = IPv4Address("198.51.100.12")
    with store._connection() as db:
        store._insert_event(
            db, "SHUN_DETECTED", 1, inactive_ip, "outside", None, None, (), None, {}, old_timestamp
        )
        store._insert_event(
            db,
            "SHUN_DETECTED",
            1,
            retained_event_ip,
            "outside",
            None,
            None,
            (),
            None,
            {},
            retained_timestamp,
        )
        db.execute(
            """INSERT INTO shun_state
               (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, inactive_ip.packed, "outside", 0, old_timestamp, old_timestamp, old_timestamp),
        )
        db.execute(
            """INSERT INTO shun_state
               (device_id, ip, interface, active, first_seen_at, last_seen_at, last_changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, active_ip.packed, "outside", 1, old_timestamp, old_timestamp, old_timestamp),
        )

    result = store.prune_expired_history(366, reference)

    assert result["events_deleted"] == 1
    assert result["inactive_state_deleted"] == 1
    assert [(str(shun.ip), shun.active) for shun in store.list_active_shuns()] == [
        ("198.51.100.11", True)
    ]
    event_types = [event["event_type"] for event in store.list_events()]
    assert event_types == ["HISTORY_RETENTION_PURGED", "SHUN_DETECTED"]


def test_ip_history_search_returns_current_and_historical_state(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "ftd-01", IPv4Address("10.50.1.10"), True), "ssh-ed25519 AAAA")
    historical = IPv4Address("198.51.100.10")
    current = IPv4Address("198.51.100.20")
    store.record_observed_shun(1, historical, "outside")
    assert store.complete_removal(1, historical, "alice", "Alice", ("Operator",), "request-1")
    store.record_observed_shun(1, current, "outside")

    results = store.search_ip_history("198.51.100")

    assert [entry["ip"] for entry in results] == ["198.51.100.10", "198.51.100.20"]
    assert results[0]["active"] is False
    assert results[0]["last_seen_at"] is not None
    assert results[0]["last_removed_at"] is not None
    assert results[1]["active"] is True
    assert results[1]["last_removed_at"] is None


@pytest.mark.parametrize("query", ["", "198.51.100.999", "198.51.100/24", "host.example"])
def test_ip_history_search_rejects_non_ipv4_prefixes(tmp_path, query) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()

    with pytest.raises(ValueError, match="IPv4 address or dotted IPv4 prefix"):
        store.search_ip_history(query)
