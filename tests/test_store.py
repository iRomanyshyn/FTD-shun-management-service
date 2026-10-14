from ipaddress import IPv4Address

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
