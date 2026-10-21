"""Read-only version-2 proposals from existing disposable preparation journals."""

import json
from contextlib import contextmanager
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_import_preparations import journal as preparation_journal
from test_import_preparations import outside, prepare
from test_managed_imports import confirm, dump, stage
from test_managed_imports import lab as confirmation_lab

from ftd_shun_manager.bulk_intent import verify_bulk_intent
from ftd_shun_manager.import_preparations import ImportPreparations, PreparationUnavailable
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

journal = preparation_journal
confirmed = confirmation_lab


def read(journal, saved, key=None, owner="alice"):
    return journal[0].propose_bulk_intent(saved["plan_id"], owner, saved["digest"], key or str(uuid4()))


def test_mixed_classified_proposal_binds_original_scope_without_saving_authority(journal):
    plans, _ = journal
    store = plans.store
    registry = ManagedShuns(store)
    registry.initialize()
    ip = IPv4Address("198.51.100.10")
    pairs = [(1, ip)]
    registry.change(str(uuid4()), "MAINTAIN", pairs, 0, 0, canonical_managed_change("MAINTAIN", pairs, 0, 0)[2],
                    "original", "Original", ("Operator",))
    store.record_observed_shun(2, ip, "management")
    ProtectedPolicy(store).change("add", IPv4Address("198.51.100.11"), 0, "protector", "Protector", ())
    saved = prepare(journal, devices=[2, 1], text="source-marker 198.51.100.10 # comment-marker\n198.51.100.11\n198.51.100.12\ninvalid",
                    label="Label", reason="Reason")
    before = outside(store)
    value = read(journal, saved)
    assert value["intent_format"] == 2 and value["can_execute"] is value["policy_saved"] is value["device_work_admitted"] is False
    assert value["manifest"]["pair_count"] == 6 and value["manifest"]["accepted_count"] == 4
    assert value["manifest"]["classification_counts"] == {
        "PROPOSE_ADD": 2, "PROPOSE_ADOPT": 1, "ALREADY_MANAGED": 1, "EXCLUDED_PROTECTED": 2}
    header = json.loads(value["canonical"])
    assert header["preparation_id"] == saved["plan_id"] and header["preparation_digest"] == saved["digest"]
    assert header["operation_id"] == value["operation_id"] and header["label"] == "Label"
    assert not any(marker in json.dumps(value) for marker in ("source-marker", "comment-marker", "actor_roles"))
    page = plans.page(saved["plan_id"], "alice")
    rows = ((row["device_id"], IPv4Address(row["ip"]), row["classification"]) for row in page["targets"])
    assert verify_bulk_intent(value["canonical"], rows, value["digest"]).as_dict() == value["manifest"]
    assert plans.list_for_owner("alice")["plans"][0]["state"] == "PREPARED"
    assert outside(store) == before


def trace_read_only_chunks(monkeypatch, store):
    original, sizes, queries = store._connection, [], []

    class Cursor:
        def __init__(self, cursor, sql):
            self.cursor, self.sql = cursor, sql

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def fetchmany(self, size):
            assert 1 <= size <= 100
            rows = self.cursor.fetchmany(size)
            if "FROM import_preparation_targets" in self.sql:
                sizes.append(len(rows))
            return rows

        def __iter__(self):
            assert "FROM import_preparation_targets" not in self.sql
            return iter(self.cursor)

        def fetchall(self):
            assert "FROM import_preparation_targets" not in self.sql
            return self.cursor.fetchall()

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, parameters=()):
            assert sql.lstrip().upper().startswith(("SELECT", "BEGIN")), sql
            queries.append(sql)
            return Cursor(self.connection.execute(sql, parameters), sql)

    @contextmanager
    def connection():
        with original() as db:
            yield Connection(db)

    monkeypatch.setattr(store, "_connection", connection)
    return sizes, queries


def test_saved_100000_pair_journal_builds_bounded_restart_stable_intent_without_work(journal, monkeypatch):
    plans, clock = journal
    text = "\n".join(str(IPv4Address(0xC6120000 + i)) for i in range(10000))
    saved = prepare(journal, text=text, devices=list(range(1, 11)))
    before = outside(plans.store)
    key = str(uuid4())
    with monkeypatch.context() as patch:
        sizes, queries = trace_read_only_chunks(patch, plans.store)
        value = read(journal, saved, key)
    assert len([size for size in sizes if size == 100]) == 2000  # Integrity scan and classified manifest scan.
    assert all(size <= 100 for size in sizes) and not any("INSERT" in sql for sql in queries)
    assert value["manifest"]["accepted_count"] == value["manifest"]["pair_count"] == 100000
    assert value["manifest"]["address_count"] == 10000 and len(value["canonical"].encode()) < 1500
    restarted = ImportPreparations(Store(plans.store.path), clock=lambda: clock[0])
    assert restarted.propose_bulk_intent(saved["plan_id"], "alice", saved["digest"], key) == value
    assert outside(plans.store) == before


@pytest.mark.parametrize("block", ["owner", "digest", "cancelled", "expired", "future", "same_key", "empty", "excluded"])
def test_ineligible_journal_never_yields_a_proposal_or_writes_anything(journal, block):
    plans, clock = journal
    if block == "excluded":
        ProtectedPolicy(plans.store).change("add", IPv4Address("198.51.100.1"), 0, "protector", "Protector", ())
    saved = prepare(journal, text="invalid" if block == "empty" else "198.51.100.1")
    if block == "cancelled": plans.cancel(saved["plan_id"], "alice")
    elif block == "expired": clock[0] += timedelta(minutes=10)
    elif block == "future": clock[0] -= timedelta(seconds=1)
    before = outside(plans.store)
    with plans.store._connection() as db:
        preparation_before = tuple(db.iterdump())
    expected = {**saved, "digest": "b" * 64} if block == "digest" else saved
    with pytest.raises(ValueError):
        read(journal, expected, saved["plan_id"] if block == "same_key" else None, "bob" if block == "owner" else "alice")
    assert outside(plans.store) == before
    with plans.store._connection() as db:
        assert tuple(db.iterdump()) == preparation_before


def test_absent_optional_journal_is_not_initialized_by_proposal_read(tmp_path):
    store = Store(tmp_path / "empty.db")
    store.initialize()
    before = outside(store)
    with pytest.raises(PreparationUnavailable, match="not initialized"):
        ImportPreparations(store).propose_bulk_intent(str(uuid4()), "alice", "a" * 64, str(uuid4()))
    assert outside(store) == before
    with store._connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'import_preparation_*'").fetchall()


@pytest.mark.parametrize("clock_change", [timedelta(minutes=10), timedelta(seconds=-1)])
def test_expiry_or_clock_change_during_stream_cannot_return_a_late_proposal(journal, monkeypatch, clock_change):
    from ftd_shun_manager import bulk_intent

    plans, clock = journal
    saved = prepare(journal)
    original = bulk_intent.canonical_bulk_intent

    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += clock_change
        return result

    monkeypatch.setattr(bulk_intent, "canonical_bulk_intent", late)
    before = outside(plans.store)
    with pytest.raises(PreparationUnavailable, match="expired or clock"):
        read(journal, saved)
    assert outside(plans.store) == before


def test_header_membership_digest_corruption_is_not_repackaged_as_a_new_format(journal):
    plans, _ = journal
    saved = prepare(journal)
    with plans.store._connection() as db:
        db.execute("DROP TRIGGER import_preparation_target_immutable")
        db.execute("UPDATE import_preparation_targets SET classification='PROPOSE_ADOPT'")
        before = tuple(db.iterdump())
    with pytest.raises(PreparationUnavailable):
        read(journal, saved)
    with plans.store._connection() as db:
        assert tuple(db.iterdump()) == before


def test_confirmed_legacy_preparation_never_acquires_new_format_meaning(confirmed):
    imports, _ = confirmed
    saved = stage(confirmed)
    receipt = confirm(confirmed, saved)
    before = dump(imports.store)
    with pytest.raises(PreparationUnavailable, match="unconfirmed"):
        imports.preparations.propose_bulk_intent(saved["plan_id"], "alice", saved["digest"], str(uuid4()))
    assert imports.page(receipt["operation_id"], "alice")["result"] == receipt
    assert dump(imports.store) == before


def test_live_observation_and_policy_changes_do_not_rebase_the_frozen_proposal(journal):
    plans, _ = journal
    saved = prepare(journal)
    key = str(uuid4())
    original = read(journal, saved, key)
    plans.store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    ProtectedPolicy(plans.store).change("add", IPv4Address("198.51.100.1"), 0, "protector", "Protector", ())
    before = outside(plans.store)
    assert read(journal, saved, key) == original
    assert original["manifest"]["classification_counts"]["PROPOSE_ADD"] == 1
    assert outside(plans.store) == before  # A future admission must reject changed live scope separately.
