"""Offline administrative acknowledgment, using disposable SQLite and no device IO."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_managed_attention import (
    IP,
    authority,
    detail,
    fingerprint,
    fleet,
    initialize,
    job,
    report,
    stamp,
)

from ftd_shun_manager import incident_acknowledgements as acknowledgements
from ftd_shun_manager import managed_maintenance
from ftd_shun_manager.maintenance import apply_recovery_control
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Device, Store

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)


@pytest.fixture
def paused(tmp_path):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    OperationQueue(store).initialize()
    store.upsert_device(Device(1, "synthetic-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 PRIVATE_HOSTKEY_MARKER")
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "suspend", "operator", now=NOW)
    return store


def migrate(store):
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        frozen = acknowledgements.review_migration(db, now=NOW)
        assert frozen["ready"]
        return acknowledgements.enable(db, store, "operator", NOW, frozen["confirmation_digest"], now=NOW)


def prepare(store, case_id, **overrides):
    values = {"request_id": str(uuid4()), "case_id": case_id, "actor": "operator",
              "reason": "Reviewed incident; retain unresolved outcome", "now": NOW}
    values.update(overrides)
    with store._connection() as db:
        db.execute("BEGIN")
        return acknowledgements.prepare(db, **values)


def apply(store, frozen, **overrides):
    values = {key: frozen[key] for key in ("request_id", "case_id", "reason")}
    values.update(actor="operator", reviewed_at=datetime.fromisoformat(frozen["reviewed_at"]),
                  digest=frozen["confirmation_digest"], confirm_ip=frozen["evidence"]["ip"],
                  confirm_target_count=frozen["evidence"]["target_count"], now=NOW)
    values.update(overrides)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return acknowledgements.apply(db, store, **values)


def unchanged_tables(store):
    with store._connection() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM "{table}"')]
                for table in tables if table not in {"incident_acknowledgements", "shun_events", "sqlite_sequence"}}


def test_read_only_and_base_initialization_never_create_ledger(paused):
    before = fingerprint(paused)
    with paused._connection() as db:
        db.execute("BEGIN")
        frozen = acknowledgements.review_migration(db, now=NOW)
        assert frozen["ready"] and not acknowledgements.present(db)
    assert fingerprint(paused) == before
    result = report(paused)
    assert result["offline_acknowledgment_available"] is False
    assert result["acknowledged_case_count"] is None
    assert fingerprint(paused) == before
    with pytest.raises(ValueError, match="migration"):
        prepare(paused, "operation:" + job(paused))
    migrate(paused)
    before = unchanged_tables(paused)
    OperationQueue(paused).initialize()
    assert unchanged_tables(paused) == before
    with paused._connection() as db:
        assert acknowledgements.present(db)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_shun_registry'").fetchone()


@pytest.mark.parametrize("action", ["ADD", "REMOVE"])
def test_ordinary_acknowledgment_preserves_all_controls_and_original_unknown_outcome(paused, action):
    key = job(paused, action=action)
    migrate(paused)
    original = unchanged_tables(paused)
    before = fingerprint(paused)
    frozen = prepare(paused, "operation:" + key)
    assert frozen["ready"] and fingerprint(paused) == before
    receipt = apply(paused, frozen)
    assert receipt["outcome_unchanged"] == "UNVERIFIED" and receipt["controls_unchanged"]
    assert unchanged_tables(paused) == original
    result = report(paused)
    assert result["counts"]["operation"] == 1 and result["retained_case_count"] == 1
    assert result["acknowledged_case_count"] == 1 and result["retained_acknowledgement_count"] == 1
    item = detail(paused, "operation:" + key)["case"]
    assert item["acknowledgment"]["request_id"] == frozen["request_id"]
    assert item["outcome"] == "UNVERIFIED" and not item["resolution_available"]
    assert "PRIVATE" not in json.dumps(frozen)
    with paused._connection() as db:
        audit = db.execute("SELECT * FROM shun_events WHERE event_type='INCIDENT_ACKNOWLEDGED'").fetchone()
        assert audit["actor_subject"] == "maintenance:operator"
        assert json.loads(audit["actor_roles_json"]) == []


def test_acknowledgment_does_not_prevent_real_absence_reconciliation(paused):
    key = job(paused, action="REMOVE")
    migrate(paused)
    frozen = prepare(paused, "operation:" + key)
    apply(paused, frozen)
    OperationQueue(paused).reconcile_unknown(1, [])
    result = report(paused)
    assert result["counts"]["operation"] == 0 and result["acknowledged_case_count"] == 0
    assert result["retained_acknowledgement_count"] == 1
    assert apply(paused, frozen, now=NOW + timedelta(days=367))["replayed"]


def test_fleet_acknowledgment_captures_entire_scope_not_only_first_page(paused):
    initialize(paused)
    predecessor = job(paused, state="FAILED")
    key = fleet(paused, devices=205, predecessors=[{"device_id": 1, "job_id": predecessor}])
    migrate(paused)
    before = unchanged_tables(paused)
    frozen = prepare(paused, "fleet_cleanup:" + key)
    evidence = frozen["evidence"]
    assert evidence["target_count"] == len(evidence["targets"]) == 205
    assert evidence["targets"][-1]["reviewed"]["device_id"] == 205
    assert evidence["targets"][-1]["current"]["hostname"] is None
    assert evidence["targets"][0]["predecessor"]["outcome"] == "FAILED"
    assert "PRIVATE" not in json.dumps(frozen)
    with pytest.raises(ValueError, match="entire reviewed scope"):
        apply(paused, frozen, confirm_target_count=100)
    assert unchanged_tables(paused) == before
    apply(paused, frozen)
    assert unchanged_tables(paused) == before
    assert report(paused)["counts"]["fleet_cleanup"] == 1
    with paused._connection() as db:
        retained = json.loads(db.execute("SELECT evidence_json FROM incident_acknowledgements").fetchone()[0])
        assert len(retained["targets"]) == 205


def test_single_cleanup_retains_policy_and_captured_add_outcome(paused):
    initialize(paused)
    request, intent = authority(paused, enabled=False)
    predecessor = job(paused)
    key = str(uuid4())
    with paused._connection() as db:
        db.execute("""INSERT INTO managed_removal_handoffs VALUES (?,1,?,?,1,?,?,'alice','Alice','[]',
            '{}','{}',?,?,'ATTENTION','PRIVATE_RAW_ERROR')""",
                   (key, IP.packed, intent, request, predecessor, stamp(NOW), stamp(NOW + timedelta(minutes=10))))
    migrate(paused)
    before = unchanged_tables(paused)
    frozen = prepare(paused, "device_cleanup:" + key)
    assert frozen["evidence"]["case"]["related_job"]["outcome"] == "UNVERIFIED"
    assert apply(paused, frozen)["outcome_unchanged"] == "ATTENTION"
    assert unchanged_tables(paused) == before
    assert report(paused)["retained_case_count"] == 2


@pytest.mark.parametrize("change", ["device", "observation", "predecessor", "protection", "requests"])
def test_changed_state_invalidates_review_without_rebase(paused, change):
    initialize(paused)
    predecessor = job(paused, state="NOOP")
    root = fleet(paused, predecessors=[{"device_id": 1, "job_id": predecessor}])
    migrate(paused)
    frozen = prepare(paused, "fleet_cleanup:" + root)
    if change == "observation":
        paused.record_observed_shun(1, IP, "management")
    else:
        with paused._connection() as db:
            if change == "device":
                db.execute("UPDATE devices SET enabled=0")
            elif change == "predecessor":
                db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (predecessor,))
            elif change == "protection":
                db.execute("UPDATE protected_policy SET revision=revision+1")
            else:
                db.execute("INSERT INTO operation_requests VALUES (?,'alice','Alice','[]','manual','{}',?,?,'CANCELLED')",
                           (str(uuid4()), stamp(NOW), stamp(NOW)))
    before = fingerprint(paused)
    with pytest.raises(ValueError, match="state changed"):
        apply(paused, frozen)
    assert fingerprint(paused) == before


@pytest.mark.parametrize("change", ["ordinary_pause", "desired_pause", "lease", "pending"])
def test_quiescence_is_required_even_for_administrative_receipt(paused, change):
    initialize(paused)
    key = job(paused)
    migrate(paused)
    if change == "pending":
        job(paused, state="RUNNING", ip=IPv4Address("198.51.100.252"))
    else:
        with paused._connection() as db:
            if change == "ordinary_pause":
                db.execute("UPDATE operation_executor SET mutations_suspended=0")
            elif change == "desired_pause":
                db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")
            else:
                db.execute("UPDATE operation_executor SET owner='unsettled',lease_until=?", (stamp(NOW),))
    frozen = prepare(paused, "operation:" + key)
    assert not frozen["ready"]
    before = fingerprint(paused)
    with pytest.raises(ValueError, match="blocked"):
        apply(paused, frozen)
    assert fingerprint(paused) == before


@pytest.mark.parametrize("age", [timedelta(minutes=5), timedelta(seconds=-1)])
def test_frozen_review_rejects_expiry_and_future_time(paused, age):
    key = job(paused)
    migrate(paused)
    frozen = prepare(paused, "operation:" + key)
    with pytest.raises(ValueError, match="expired|future"):
        apply(paused, frozen, now=NOW + age)


def test_original_key_replay_never_creates_second_receipt_or_changes_controls(paused):
    key = job(paused)
    migrate(paused)
    frozen = prepare(paused, "operation:" + key)
    first = apply(paused, frozen)
    before = fingerprint(paused)
    replay = apply(paused, frozen, now=NOW + timedelta(days=1))
    assert replay == {**first, "replayed": True} and fingerprint(paused) == before
    for overrides in ({"reason": "different"}, {"actor": "other"}, {"digest": "0" * 64}):
        with pytest.raises(ValueError, match="different reviewed inputs"):
            apply(paused, frozen, **overrides)
    assert not prepare(paused, "operation:" + key)["ready"]


def test_concurrent_same_case_commits_one_receipt_with_one_audit(paused):
    key = job(paused)
    migrate(paused)
    frozen = prepare(paused, "operation:" + key)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: apply(paused, frozen), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    with paused._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM incident_acknowledgements").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='INCIDENT_ACKNOWLEDGED'").fetchone()[0] == 1


@pytest.mark.parametrize("migration", [True, False])
def test_audit_failure_rolls_back_even_if_caller_commits_outer_transaction(paused, monkeypatch, migration):
    key = job(paused)
    if not migration:
        migrate(paused)
        frozen = prepare(paused, "operation:" + key)
    with paused._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        before = tuple(db.iterdump())
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic audit failure")
        monkeypatch.setattr(paused, "_insert_event", fail)
        with pytest.raises(RuntimeError, match="audit failure"):
            if migration:
                review = acknowledgements.review_migration(db, now=NOW)
                acknowledgements.enable(db, paused, "operator", NOW, review["confirmation_digest"], now=NOW)
            else:
                acknowledgements.apply(db, paused, frozen["request_id"], frozen["case_id"], "operator", frozen["reason"],
                    NOW, frozen["confirmation_digest"], str(IP), 1, now=NOW)
        assert tuple(db.iterdump()) == before


def test_missing_predecessor_is_explicit_but_inconsistent_fleet_refuses(paused):
    initialize(paused)
    root = fleet(paused)
    migrate(paused)
    frozen = prepare(paused, "fleet_cleanup:" + root)
    assert frozen["evidence"]["targets"][0]["predecessor"]["state"] == "not_retained"
    malformed = fleet(paused, predecessors=[])
    before = fingerprint(paused)
    with pytest.raises(ValueError, match="inconsistent"):
        prepare(paused, "fleet_cleanup:" + malformed)
    assert fingerprint(paused) == before


@pytest.mark.parametrize("mutation", ["update", "delete", "trigger"])
def test_immutable_and_partial_ledgers_cannot_hide_evidence(paused, mutation):
    migrate(paused)
    apply(paused, prepare(paused, "operation:" + job(paused)))
    with paused._connection() as db:
        if mutation in {"update", "delete"}:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE incident_acknowledgements SET reason='changed'" if mutation == "update"
                           else "DELETE FROM incident_acknowledgements")
        else:
            db.execute("DROP TRIGGER incident_ack_retained")
    if mutation == "trigger":
        with pytest.raises(ValueError, match="incomplete"):
            report(paused)


def test_new_ack_key_is_reserved_against_ordinary_admission_and_old_key_cannot_be_acknowledged(paused):
    queue = OperationQueue(paused)
    key = job(paused)
    migrate(paused)
    assert not prepare(paused, "operation:" + key, request_id=key)["ready"]
    frozen = prepare(paused, "operation:" + key)
    apply(paused, frozen)
    with paused._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, paused, "resume-mutations", "operator", now=NOW)
    with pytest.raises(QueueConflict, match="cannot acquire"):
        queue.enqueue(frozen["request_id"], [(1, IP)], "alice", "Alice", ("Operator",))


def test_retention_keeps_receipt_and_unknown_job_independently_of_audit_age(paused, monkeypatch):
    queue = OperationQueue(paused)
    migrate(paused)
    frozen = prepare(paused, "operation:" + job(paused))
    apply(paused, frozen)
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(days=367))
    queue.prune_completed(366)
    assert report(paused)["acknowledged_case_count"] == 1
    assert apply(paused, frozen, now=NOW + timedelta(days=367))["replayed"]


@pytest.mark.parametrize("field,value", [("confirm_ip", "198.51.100.252"), ("confirm_target_count", True),
                                        ("case_id", "restoration:" + str(uuid4())), ("reason", "bad\nreason")])
def test_invalid_or_different_confirmation_cannot_commit(paused, field, value):
    migrate(paused)
    frozen = prepare(paused, "operation:" + job(paused))
    before = fingerprint(paused)
    with pytest.raises(ValueError):
        apply(paused, frozen, **{field: value})
    assert fingerprint(paused) == before


def test_cross_case_or_catalog_digest_cannot_authorize_acknowledgment(paused):
    migrate(paused)
    one = prepare(paused, "operation:" + job(paused))
    other = prepare(paused, "operation:" + job(paused, ip=IPv4Address("198.51.100.252")))
    before = fingerprint(paused)
    for digest in [one["confirmation_digest"], report(paused)["snapshot_digest"]]:
        with pytest.raises(ValueError, match="state changed"):
            apply(paused, other, digest=digest)
    assert fingerprint(paused) == before


def test_late_expiry_rolls_back_decision_and_audit(paused, monkeypatch):
    migrate(paused)
    current = datetime.now(UTC)
    frozen = prepare(paused, "operation:" + job(paused), now=current)
    before = fingerprint(paused)
    def expire(*args):
        raise ValueError("Review expired before commit")
    monkeypatch.setattr(acknowledgements, "_check_commit_expiry", expire)
    with pytest.raises(ValueError, match="expired before commit"):
        apply(paused, frozen, now=None)
    assert fingerprint(paused) == before


def test_acknowledged_fleet_still_blocks_policy_resume(paused):
    initialize(paused)
    root = fleet(paused)
    migrate(paused)
    apply(paused, prepare(paused, "fleet_cleanup:" + root))
    with paused._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, paused, "resume-mutations", "operator", now=NOW)
        frozen = managed_maintenance.review(db, "resume-policy", now=NOW)
        assert any("attention cleanup" in blocker for blocker in frozen["blockers"])


def test_cli_checked_backup_and_historical_replay(paused, tmp_path, capsys):
    key = job(paused)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    base = ["--database", str(paused.path), "--actor", "operator", "--confirm-offline"]
    assert acknowledgements.main(["review-enable", *base]) == 0
    review = json.loads(capsys.readouterr().out)
    assert acknowledgements.main(["enable", *base, "--backup", str(private / "before-enable.sqlite3"),
        "--confirm-reviewed", "--reviewed-at", review["reviewed_at"], "--review-digest", review["confirmation_digest"]]) == 0
    capsys.readouterr()
    case = ["--case-id", "operation:" + key, "--reason", "Reviewed unknown write"]
    assert acknowledgements.main(["review", *base, *case]) == 0
    frozen = json.loads(capsys.readouterr().out)
    confirm = ["--confirm-reviewed", "--request-id", frozen["request_id"], "--confirm-ip", str(IP),
        "--confirm-target-count", "1", "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]
    assert acknowledgements.main(["acknowledge", *base, *case, *confirm, "--backup", str(private / "before-ack.sqlite3")]) == 0
    assert not json.loads(capsys.readouterr().out)["replayed"]
    with sqlite3.connect(private / "before-ack.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM incident_acknowledgements").fetchone()[0] == 0
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert acknowledgements.main(["acknowledge", *base, *case, *confirm, "--backup", str(private / "before-replay.sqlite3")]) == 0
    assert json.loads(capsys.readouterr().out)["replayed"]


def test_cli_rejects_missing_database_and_migration_decision_fields(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(SystemExit):
        acknowledgements.main(["review-enable", "--database", str(missing), "--actor", "operator", "--confirm-offline"])
    assert not missing.exists()
    with pytest.raises(SystemExit):
        acknowledgements.main(["review-enable", "--database", str(missing), "--actor", "operator", "--confirm-offline",
                               "--case-id", "operation:" + str(uuid4())])
