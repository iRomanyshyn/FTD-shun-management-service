"""Offline lifecycle controls on disposable state only; no FTD or live volume."""

import json
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_maintenance as maintenance
from ftd_shun_manager import managed_shuns
from ftd_shun_manager.maintenance import apply_recovery_control, checked_offline
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot, ManagedRestorations
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.schema import execute_schema
from ftd_shun_manager.store import Device, Store

NOW = datetime(2026, 10, 18, tzinfo=UTC)
IP = IPv4Address("198.51.100.251")


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    OperationQueue(store).initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    monkeypatch.setattr(managed_shuns, "now", lambda: stamp(NOW - timedelta(seconds=10)))
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "suspend", "synthetic-operator", now=NOW - timedelta(seconds=5))
    return store


def prepare(store, action, **kwargs):
    with store._connection() as db:
        db.execute("BEGIN")
        return maintenance.review(db, action, now=NOW, **kwargs)


def apply(store, frozen, **kwargs):
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return maintenance.apply_reviewed(db, store, frozen["action"], "synthetic-operator",
                                          datetime.fromisoformat(frozen["reviewed_at"]), frozen["confirmation_digest"],
                                          now=NOW, **kwargs)


def fingerprint(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def initialized(store):
    apply(store, prepare(store, "initialize"))
    return store


def standing(store):
    initialized(store)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "resume-mutations", "synthetic-operator", now=NOW)
    registry = ManagedShuns(store)
    registry.change(str(uuid4()), "MAINTAIN", [(1, IP)], 0, 0,
                    canonical_managed_change("MAINTAIN", [(1, IP)], 0, 0, "Fixture", "Standing consent")[2],
                    "alice", "Alice", ("Operator",), "Fixture", "Standing consent")
    return store


def test_review_is_read_only_and_empty_migration_does_not_adopt_observations(store):
    store.record_observed_shun(1, IP, "management")
    before = fingerprint(store)
    frozen = prepare(store, "initialize")
    assert frozen["ready"] and frozen["targets"] == []
    assert fingerprint(store) == before
    result = apply(store, frozen)
    assert result == {"action": "initialize", "managed_revision": 0, "restoration_suspended": True, "enabled_targets": 0}
    with store._connection() as db:
        assert maintenance._owned(maintenance._objects(db)) == maintenance._expected_schema()
        assert db.execute("SELECT COUNT(*) FROM managed_shun_targets").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM operation_jobs").fetchone()[0] == 0
        assert db.execute("SELECT mutations_suspended FROM operation_executor").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert store.list_active_shuns()[0].ip == IP
    event = next(row for row in store.list_events() if row["event_type"] == "MANAGED_SCHEMA_INITIALIZED")
    assert event["actor_subject"] == "maintenance:synthetic-operator"


@pytest.mark.parametrize("partial", [True, False])
def test_existing_partial_or_complete_schema_is_not_repaired_or_reinitialized(store, partial):
    if partial:
        with store._connection() as db:
            db.execute("CREATE TABLE managed_shun_registry(id INTEGER)")
    else:
        initialized(store)
    before = fingerprint(store)
    with pytest.raises(ValueError, match="Existing or partial"):
        prepare(store, "initialize")
    assert fingerprint(store) == before


@pytest.mark.parametrize("change", ["unpause", "lease", "queued"])
def test_migration_requires_settled_executor_and_pause(store, change):
    with store._connection() as db:
        if change == "unpause":
            db.execute("UPDATE operation_executor SET mutations_suspended=0")
        elif change == "lease":
            db.execute("UPDATE operation_executor SET owner='old-worker',lease_until=?", (stamp(NOW - timedelta(hours=1)),))
        else:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), IP.packed, stamp(NOW)))
    frozen = prepare(store, "initialize")
    before = fingerprint(store)
    assert not frozen["ready"]
    with pytest.raises(ValueError, match="blocked"):
        apply(store, frozen)
    assert fingerprint(store) == before


@pytest.mark.parametrize("where", ["ddl", "audit"])
def test_schema_and_audit_rollback_even_if_caller_catches_and_commits(store, monkeypatch, where):
    frozen = prepare(store, "initialize")
    before = fingerprint(store)
    if where == "ddl":
        original = maintenance._initialize

        def fail(db, target):
            original(db, target)
            raise RuntimeError("synthetic migration failure")

        monkeypatch.setattr(maintenance, "_initialize", fail)
    else:
        monkeypatch.setattr(store, "_insert_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic audit failure")))
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="synthetic"):
            maintenance.apply_reviewed(db, store, "initialize", "operator", NOW, frozen["confirmation_digest"], now=NOW)
        db.execute("UPDATE operation_executor SET revision=revision")
    assert fingerprint(store) == before


@pytest.mark.parametrize("age", [-1, 300, 301])
def test_expired_future_reviews_never_write(store, age):
    before = fingerprint(store)
    with pytest.raises(ValueError, match="expired or has a future"):
        prepare(store, "initialize", reviewed_at=NOW - timedelta(seconds=age))
    assert fingerprint(store) == before


@pytest.mark.parametrize("change", ["queue", "protection", "device", "schema"])
def test_review_digest_binds_state_without_rebase(store, change):
    frozen = prepare(store, "initialize")
    with store._connection() as db:
        db.execute({"queue": "UPDATE operation_executor SET revision=revision+1",
                    "protection": "UPDATE protected_policy SET revision=revision+1",
                    "device": "UPDATE devices SET enabled=0",
                    "schema": "CREATE TABLE unrelated_change(id INTEGER)"}[change])
    before = fingerprint(store)
    with pytest.raises(ValueError, match="state changed"):
        apply(store, frozen)
    assert fingerprint(store) == before


def test_resume_preserves_original_authority_and_never_creates_work(store):
    standing(store)
    with store._connection() as db:
        before = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
        requests = list(db.execute("SELECT * FROM managed_shun_requests"))
    frozen = prepare(store, "resume-policy")
    assert frozen["ready"] and frozen["targets"][0]["actor_subject"] == "alice"
    result = apply(store, frozen)
    assert not result["restoration_suspended"] and result["enabled_targets"] == 1
    with store._connection() as db:
        after = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
        assert {k: v for k, v in before.items() if k not in {"revision", "updated_at"}} == {
            k: v for k, v in after.items() if k not in {"revision", "updated_at"}}
        assert after["revision"] > before["revision"]
        assert after["updated_at"] == result["absence_not_before"] > stamp(NOW)
        assert requests == list(db.execute("SELECT * FROM managed_shun_requests"))
        assert db.execute("SELECT mutations_suspended FROM operation_executor").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM operation_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] == 0
    with pytest.raises(ValueError, match="state changed"):
        apply(store, frozen)


def test_resume_rejects_old_snapshot_but_new_snapshot_can_use_existing_gates(store, monkeypatch):
    standing(store)
    apply(store, prepare(store, "resume-policy"))
    queue = OperationQueue(store)
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(seconds=61))
    assert queue.claim_cycle("synthetic-worker", 135)
    source = ManagedRestorations(store, queue)
    old = CompleteSnapshot(str(uuid4()), 1, NOW, NOW + timedelta(seconds=1), frozenset())
    with pytest.raises(QueueConflict, match="predates policy"):
        source.admit_absence(old, IP, "synthetic-worker", enabled=True)
    new = CompleteSnapshot(str(uuid4()), 1, NOW + timedelta(seconds=60), NOW + timedelta(seconds=61), frozenset())
    assert source.admit_absence(new, IP, "synthetic-worker") is None  # Still default-off.
    assert not source.admit_absence(new, IP, "synthetic-worker", enabled=True)["replayed"]


def test_resume_does_not_touch_retired_target_or_renew_original_grant_replay(store):
    standing(store)
    registry = ManagedShuns(store)
    other = IPv4Address("198.51.100.250")
    for revision, action in [(1, "MAINTAIN"), (2, "RETIRE")]:
        registry.change(str(uuid4()), action, [(1, other)], revision, 0,
                        canonical_managed_change(action, [(1, other)], revision, 0)[2],
                        "alice", "Alice", ("Operator",))
    with store._connection() as db:
        retired = dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (other.packed,)).fetchone())
        original = db.execute("SELECT authorization_request_id FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone()[0]
    apply(store, prepare(store, "resume-policy"))
    before = fingerprint(store)
    receipt = registry.change(original, "MAINTAIN", [(1, IP)], 0, 0,
                              canonical_managed_change("MAINTAIN", [(1, IP)], 0, 0, "Fixture", "Standing consent")[2],
                              "alice", "Alice", ("Operator",), "Fixture", "Standing consent")
    assert receipt["replayed"] and fingerprint(store) == before
    with store._connection() as db:
        assert retired == dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (other.packed,)).fetchone())


@pytest.mark.parametrize("change", ["pause", "device", "protection", "clock", "empty", "running", "uncertain"])
def test_resume_blockers_do_not_modify_authority_or_results(store, change):
    standing(store)
    with store._connection() as db:
        if change == "protection":
            db.execute("INSERT INTO protected_ips(ip,name,comment,enabled,updated_at) VALUES (?,'Fixture','',1,?)", (IP.packed, stamp(NOW)))
        elif change in {"running", "uncertain"}:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,?,?,'ADD')",
                       (str(uuid4()), IP.packed, "RUNNING" if change == "running" else "UNVERIFIED", stamp(NOW)))
        else:
            db.execute({"pause": "UPDATE operation_executor SET mutations_suspended=1",
                        "device": "UPDATE devices SET enabled=0",
                        "clock": "UPDATE managed_shun_targets SET updated_at='2099-01-01T00:00:00.000Z'",
                        "empty": "UPDATE managed_shun_targets SET enabled=0,retired_at='2026-10-18T00:00:00.000Z'"}[change])
    frozen = prepare(store, "resume-policy")
    before = fingerprint(store)
    assert not frozen["ready"]
    with pytest.raises(ValueError, match="blocked"):
        apply(store, frozen)
    assert fingerprint(store) == before


@pytest.mark.parametrize("change", ["trigger", "column", "extra"])
def test_resume_refuses_unknown_schema_instead_of_interpreting_empty_state(store, change):
    standing(store)
    with store._connection() as db:
        db.execute({"trigger": "DROP TRIGGER managed_request_immutable_update",
                    "column": "ALTER TABLE managed_shun_targets ADD COLUMN unknown INTEGER",
                    "extra": "CREATE TABLE managed_unknown(id INTEGER)"}[change])
    before = fingerprint(store)
    with pytest.raises(ValueError, match="Exact complete"):
        prepare(store, "resume-policy")
    assert fingerprint(store) == before


def test_resume_audit_failure_rolls_back_barrier_and_pause(store, monkeypatch):
    standing(store)
    frozen = prepare(store, "resume-policy")
    before = fingerprint(store)
    monkeypatch.setattr(store, "_insert_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with pytest.raises(RuntimeError):
        apply(store, frozen)
    assert fingerprint(store) == before


@pytest.mark.parametrize("outcome", ["FAILED", "UNVERIFIED"])
def test_resume_never_clears_or_rearms_retained_restoration_attention(store, monkeypatch, outcome):
    standing(store)
    apply(store, prepare(store, "resume-policy"))
    queue = OperationQueue(store)
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(seconds=61))
    assert queue.claim_cycle("synthetic-worker", 135)
    source = ManagedRestorations(store, queue)
    evidence = CompleteSnapshot(str(uuid4()), 1, NOW + timedelta(seconds=60), NOW + timedelta(seconds=61), frozenset())
    source.admit_absence(evidence, IP, "synthetic-worker", enabled=True)
    job = queue.claim_addition(1, "synthetic-worker", queue.cutoff(), execution_enabled=True, managed_restoration_enabled=True)
    queue.finish_addition(job["id"], "synthetic-worker", outcome)
    queue.finish_cycle("synthetic-worker", 60)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "suspend", "operator", now=NOW + timedelta(seconds=70))
        apply_recovery_control(db, store, "resume-mutations", "operator", now=NOW + timedelta(seconds=71))
    frozen = prepare(store, "resume-policy")
    before = fingerprint(store)
    assert not frozen["ready"]
    assert any("resolution" in item for item in frozen["blockers"])
    with pytest.raises(ValueError, match="blocked"):
        apply(store, frozen)
    assert fingerprint(store) == before


@pytest.mark.parametrize("phase,state", [("ADMITTING", None), ("ADMITTED", "WAITING_ADD"), ("ADMITTED", "ATTENTION")])
def test_resume_rejects_unfinished_or_attention_fleet_barrier(store, phase, state):
    standing(store)
    with store._connection() as db:
        key = str(uuid4())
        db.execute("""INSERT INTO managed_fleet_removals VALUES (?,NULL,'alice','Alice','["Operator"]',
            '{}','{}',?,?,?)""", (key, stamp(NOW), stamp(NOW + timedelta(minutes=10)), phase))
        if state:
            db.execute("INSERT INTO managed_fleet_waits VALUES (?,1,'[]',?,NULL)", (key, state))
    frozen = prepare(store, "resume-policy")
    before = fingerprint(store)
    assert not frozen["ready"]
    with pytest.raises(ValueError, match="cleanup requires"):
        apply(store, frozen)
    assert fingerprint(store) == before


def test_checked_backup_contains_before_migration_state_and_never_overwrites(store, tmp_path):
    frozen = prepare(store, "initialize")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "before.sqlite3"
    result = checked_offline(store.path, path, lambda db, target:
                             maintenance.apply_reviewed(db, target, "initialize", "operator", NOW,
                                                        frozen["confirmation_digest"], now=NOW))
    assert result["backup"] == str(path) and stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(FileExistsError):
        checked_offline(store.path, path, lambda *args: pytest.fail("Must not run"))


def test_cli_review_then_initialize_and_consumed_review_no_replay(store, tmp_path, capsys):
    common = ["--database", str(store.path), "--actor", "operator", "--confirm-offline"]
    assert maintenance.main(["review-initialize", *common]) == 0
    frozen = json.loads(capsys.readouterr().out)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    args = ["initialize", *common, "--backup", str(private / "before.sqlite3"), "--confirm-reviewed",
            "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]
    assert maintenance.main(args) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "maintenance.managed.committed"
    with pytest.raises(SystemExit) as error:
        maintenance.main(["initialize", *common, "--backup", str(private / "retry.sqlite3"), "--confirm-reviewed",
                          "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]])
    assert error.value.code == 2
    assert (private / "retry.sqlite3").exists()


@pytest.mark.parametrize("action", ["initialize", "resume-policy", "review-initialize", "review-resume"])
def test_cli_missing_confirmations_do_not_open_or_create_database(tmp_path, action):
    target = tmp_path / "does-not-exist.db"
    with pytest.raises(SystemExit) as error:
        maintenance.main([action, "--database", str(target), "--actor", "operator"])
    assert error.value.code == 2 and not target.exists()


def test_ddl_helper_handles_trigger_semicolons_without_implicit_commit(store):
    with store._connection() as db:
        with pytest.raises(ValueError, match="transaction"):
            execute_schema(db, "CREATE TABLE no_commit(id INTEGER);\n")
        db.execute("BEGIN IMMEDIATE")
        execute_schema(db, """CREATE TABLE synthetic(id INTEGER);
CREATE TRIGGER synthetic_guard BEFORE DELETE ON synthetic BEGIN
 SELECT RAISE(ABORT,'no; deletion');
END;
""")
        db.rollback()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='synthetic'").fetchone()
