"""Unconfirmed durable preparation only: temporary SQLite, never lab/FTD work."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager.import_preparations import (
    ImportPreparations,
    PreparationCapacity,
    PreparationUnavailable,
)
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def journal(tmp_path):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    OperationQueue(store).initialize()
    for device in range(1, 11):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    clock = [datetime(2026, 10, 21, 12, tzinfo=UTC)]
    plans = ImportPreparations(store, clock=lambda: clock[0])
    plans.initialize()
    return plans, clock


def prepare(journal, *, text="198.51.100.1", devices=None, subject="alice", **kwargs):
    return journal[0].create(text, [1] if devices is None else devices, subject, "Synthetic author", ("Viewer",), **kwargs)


def outside(store):
    with store._connection() as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                  if not row[0].startswith("import_preparation_")]
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in tables}


def test_constructor_and_optional_reads_never_initialize_or_repair(journal, tmp_path):
    absent = Store(tmp_path / "not-created.db")
    ImportPreparations(absent)
    assert not absent.path.exists()
    store = Store(tmp_path / "base-only.db")
    store.initialize()
    plans = ImportPreparations(store)
    before = outside(store)
    with pytest.raises(PreparationUnavailable, match="not initialized"):
        plans.page(str(uuid4()), "alice")
    assert plans.list_for_owner("alice") == {"initialized": False, "can_execute": False, "plans": []}
    assert plans.prune_expired() == 0
    assert outside(store) == before
    with store._connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'import_preparation_*'").fetchall()
    plans.initialize()
    with store._connection() as db:
        db.execute("ALTER TABLE import_preparation_plans RENAME COLUMN digest TO broken_digest")
        broken = tuple(db.iterdump())
    with pytest.raises(PreparationUnavailable, match="partial"):
        plans.initialize()
    with store._connection() as db:
        assert tuple(db.iterdump()) == broken


def test_explicit_schema_initialization_composes_with_caller_rollback(journal, tmp_path):
    store = Store(tmp_path / "rollback.db")
    store.initialize()
    plans = ImportPreparations(store)
    with pytest.raises(RuntimeError), store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        plans.initialize(connection=db)
        raise RuntimeError("Synthetic outer failure")
    with store._connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'import_preparation_*'").fetchall()


def test_exact_proposals_exclusions_provenance_and_private_source_not_persisted(journal):
    plans, _ = journal
    registry = ManagedShuns(plans.store)
    registry.initialize()
    ip = IPv4Address("198.51.100.10")
    pairs = [(1, ip)]
    registry.change(str(uuid4()), "MAINTAIN", pairs, 0, 0,
                    canonical_managed_change("MAINTAIN", pairs, 0, 0)[2], "creator", "Creator", ("Operator",))
    plans.store.record_observed_shun(2, ip, "management")
    ProtectedPolicy(plans.store).change("add", IPv4Address("198.51.100.11"), 0, "protector", "Protector", ())
    before = outside(plans.store)
    saved = prepare(journal, devices=[2, 1], text="""# private-comment-marker
prefix-marker 198.51.100.10 suffix-marker # private-comment-marker
198.51.100.11
198.51.100.12
198.51.100.10
555.555.555.666
""")
    page = plans.page(saved["plan_id"], "alice")
    assert page["classification_counts"] == {
        "PROPOSE_ADD": 2, "PROPOSE_ADOPT": 1, "ALREADY_MANAGED": 1, "EXCLUDED_PROTECTED": 2}
    assert page["source_counts"] == {"Ready": 3, "Duplicate": 1, "Invalid": 1}
    assert page["state"] == "PREPARED" and not page["can_execute"] and not page["execution_started"]
    assert page["actor_roles"] == ["Viewer"] and page["managed_revision"] == 1
    assert page["target_count"] == 6 and page["address_count"] == 3
    adopted = next(row for row in page["targets"] if row["classification"] == "PROPOSE_ADOPT")
    assert adopted["observed_at"] and adopted["previous_authorization_request_id"] is None
    maintained = next(row for row in page["targets"] if row["classification"] == "ALREADY_MANAGED")
    assert maintained["previous_authorization_request_id"] == registry.snapshot()["entries"][0]["authorization_request_id"]
    serialized = json.dumps(page)
    assert not any(marker in serialized for marker in ("private-comment-marker", "prefix-marker", "suffix-marker"))
    assert outside(plans.store) == before
    assert plans.verify(saved["plan_id"], "alice", saved["digest"])["can_execute"] is False
    assert outside(plans.store) == before


def test_maximum_10000_addresses_100000_pairs_restart_pagination_and_streamed_integrity(journal):
    plans, clock = journal
    text = "\n".join(str(IPv4Address(0xC6120000 + i)) for i in range(10000))
    before = outside(plans.store)
    saved = prepare(journal, text=text, devices=list(range(10, 0, -1)))
    assert saved["target_count"] == 100000
    restarted = ImportPreparations(Store(plans.store.path), clock=lambda: clock[0])
    for number in (1, 501, 1000):
        page = restarted.page(saved["plan_id"], "alice", page=number)
        assert page["pages"] == 1000 and page["page_size"] == 100
        assert len(page["targets"]) == 100 and len(page["report_rows"]) <= 100
        assert page["classification_counts"]["PROPOSE_ADD"] == 100000
        assert not page["managed_initialized"] and not page["can_execute"]
    first = restarted.page(saved["plan_id"], "alice")["targets"][0]
    last = restarted.page(saved["plan_id"], "alice", page=1000)["targets"][-1]
    assert (first["device_id"], first["ip"]) == (1, "198.18.0.0")
    assert (last["device_id"], last["ip"]) == (10, str(IPv4Address(0xC6120000 + 9999)))
    assert restarted.verify(saved["plan_id"], "alice", saved["digest"])["integrity_verified"]
    assert outside(plans.store) == before


@pytest.mark.parametrize("devices", [[], [True], [0], [1, 1], [65536], list(range(1, 12)), [11]])
def test_device_selection_is_explicit_bounded_and_enabled(journal, devices):
    with pytest.raises((ValueError, PreparationUnavailable)):
        prepare(journal, devices=devices)


def test_all_invalid_or_empty_input_is_a_non_executable_report_not_fake_work(journal):
    plans, _ = journal
    for text in ("", "# comment", "555.555.555.666\n198.51.100.0/24"):
        saved = prepare(journal, text=text)
        page = plans.page(saved["plan_id"], "alice")
        assert page["target_count"] == 0 and page["targets"] == [] and not page["can_execute"]
        assert page["pages"] == 1
        assert plans.verify(saved["plan_id"], "alice", saved["digest"])["integrity_verified"]


def test_owner_checks_cancellation_expiry_and_pruning_never_touch_independent_work(journal):
    plans, clock = journal
    before = outside(plans.store)
    saved = prepare(journal)
    for owner in ("bob", "", "alice "):
        for operation in (lambda owner=owner: plans.page(saved["plan_id"], owner),
                          lambda owner=owner: plans.cancel(saved["plan_id"], owner),
                          lambda owner=owner: plans.verify(saved["plan_id"], owner, saved["digest"])):
            with pytest.raises(PreparationUnavailable, match="author"):
                operation()
    assert plans.cancel(saved["plan_id"], "alice")
    assert not plans.cancel(saved["plan_id"], "alice")
    assert plans.page(saved["plan_id"], "alice")["state"] == "CANCELLED"
    assert plans.verify(saved["plan_id"], "alice", saved["digest"])["integrity_verified"]
    assert plans.prune_expired() == 0
    clock[0] += timedelta(minutes=10)
    assert plans.prune_expired() == 1
    with pytest.raises(PreparationUnavailable):
        plans.page(saved["plan_id"], "alice")
    with plans.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM import_preparation_targets").fetchone()[0] == 0
    assert outside(plans.store) == before


def test_expired_read_stays_historical_and_does_not_delete_or_authorize(journal):
    plans, clock = journal
    saved = prepare(journal)
    clock[0] += timedelta(minutes=10)
    with plans.store._connection() as db:
        before = tuple(db.iterdump())
    page = plans.page(saved["plan_id"], "alice")
    assert page["state"] == "EXPIRED" and not page["can_execute"]
    assert plans.verify(saved["plan_id"], "alice", saved["digest"])["can_execute"] is False
    with plans.store._connection() as db:
        assert tuple(db.iterdump()) == before


def test_scope_is_frozen_not_rebased_when_live_policy_and_observations_change(journal):
    plans, _ = journal
    saved = prepare(journal)
    before = plans.page(saved["plan_id"], "alice")
    plans.store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    ProtectedPolicy(plans.store).change("add", IPv4Address("198.51.100.1"), 0, "protector", "Protector", ())
    assert plans.page(saved["plan_id"], "alice") == before
    assert plans.verify(saved["plan_id"], "alice", saved["digest"])["can_execute"] is False


def test_owner_can_recover_frozen_references_after_restart_without_other_authors_scope(journal):
    saved = prepare(journal, label="Own retained draft")
    other = prepare(journal, subject="bob")
    plans = ImportPreparations(Store(journal[0].store.path), clock=lambda: journal[1][0])
    own = plans.list_for_owner("alice")
    assert own["initialized"] and not own["can_execute"]
    assert [entry["plan_id"] for entry in own["plans"]] == [saved["plan_id"]]
    assert own["plans"][0]["label"] == "Own retained draft"
    assert other["plan_id"] not in json.dumps(own)
    assert plans.list_for_owner("unknown")["plans"] == []


def test_optional_managed_corruption_refuses_classification_without_initialization(journal):
    plans, _ = journal
    ManagedShuns(plans.store).initialize()
    with plans.store._connection() as db:
        db.execute("DELETE FROM managed_shun_registry")
        before = tuple(db.iterdump())
    with pytest.raises(ManagedStateUnavailable):
        prepare(journal)
    with plans.store._connection() as db:
        assert tuple(db.iterdump()) == before


def test_immutable_rows_wrong_digest_missing_member_and_tamper_fail_closed(journal):
    plans, _ = journal
    saved = prepare(journal)
    with plans.store._connection() as db:
        for statement in ("UPDATE import_preparation_targets SET observed_at='changed'",
                          "UPDATE import_preparation_plans SET actor_subject='bob'",
                          "UPDATE import_preparation_plans SET header_json='{}'"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
    with pytest.raises(PreparationUnavailable, match="digest"):
        plans.verify(saved["plan_id"], "alice", "0" * 64)
    # Deliberate disposable corruption, not a runtime mutation API.
    with plans.store._connection() as db:
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='import_preparation_target_immutable'").fetchone()[0]
        db.execute("DROP TRIGGER import_preparation_target_immutable")
        db.execute("UPDATE import_preparation_targets SET observed_at='synthetic corruption'")
        db.execute(trigger)
    with pytest.raises(PreparationUnavailable, match="digest"):
        plans.verify(saved["plan_id"], "alice", saved["digest"])
    with plans.store._connection() as db:
        db.execute("DELETE FROM import_preparation_targets")
    with pytest.raises(PreparationUnavailable, match="incomplete"):
        plans.page(saved["plan_id"], "alice")


def test_late_target_failure_rolls_back_entire_preparation(journal):
    plans, _ = journal
    with plans.store._connection() as db:
        db.execute("""CREATE TRIGGER synthetic_target_failure BEFORE INSERT ON import_preparation_targets
            WHEN NEW.device_id=2 BEGIN SELECT RAISE(ABORT,'synthetic late failure'); END""")
        before = tuple(db.iterdump())
    with pytest.raises(sqlite3.IntegrityError):
        prepare(journal, devices=[1, 2])
    with plans.store._connection() as db:
        assert tuple(db.iterdump()) == before


def test_per_owner_and_global_limits_are_atomic_and_explicitly_reclaimed(journal):
    plans, clock = journal
    for owner in ("alice", "bob", "charlie", "dana"):
        for _ in range(4):
            prepare(journal, subject=owner)
        with pytest.raises(PreparationCapacity):
            prepare(journal, subject=owner)
    with pytest.raises(PreparationCapacity):
        prepare(journal, subject="eve")
    clock[0] += timedelta(minutes=10)
    assert plans.prune_expired() == 16
    assert prepare(journal, subject="eve")["can_execute"] is False


def test_concurrent_preparation_cannot_overflow_owner_bound(journal):
    def create(_):
        try:
            return prepare(journal)["plan_id"]
        except PreparationCapacity:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert len({result for result in results if result}) == 4


@pytest.mark.parametrize("page", [0, -1, True, 1.5, 2])
def test_page_bounds_cannot_request_unbounded_or_silently_clamped_scope(journal, page):
    saved = prepare(journal)
    with pytest.raises(ValueError):
        journal[0].page(saved["plan_id"], "alice", page=page)


def test_paste_limits_and_timezone_validation_are_not_bypassed(journal):
    with pytest.raises(ValueError, match="1 MiB"):
        prepare(journal, text="ї" * 524289)
    journal[1][0] = datetime(2026, 10, 21, 12)  # Deliberately naive synthetic clock.
    with pytest.raises(ValueError, match="UTC"):
        prepare(journal)
