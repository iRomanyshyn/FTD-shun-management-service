"""Offline revocation uses synthetic authority and disposable SQLite, never FTD."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_abandonment as abandonment
from ftd_shun_manager import managed_closures as closures
from ftd_shun_manager import managed_maintenance as maintenance
from ftd_shun_manager import managed_shuns
from ftd_shun_manager.maintenance import apply_recovery_control
from ftd_shun_manager.managed_attention import attention_report
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot, ManagedRestorations
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.store import Device, Store

NOW = datetime(2026, 10, 19, 10, tzinfo=UTC)
IP = IPv4Address("198.51.100.251")


@pytest.fixture
def lab(tmp_path, monkeypatch, request):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    queue, registry = OperationQueue(store), ManagedShuns(store)
    queue.initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    monkeypatch.setattr(queue, "_now", lambda: NOW)
    monkeypatch.setattr(managed_shuns, "now", lambda: stamp(NOW - timedelta(seconds=10)))
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        maintenance._initialize(db, store)
    grant = str(uuid4())
    registry.change(grant, "MAINTAIN", [(1, IP)], 0, 0, canonical_managed_change("MAINTAIN", [(1, IP)], 0, 0)[2],
                    "alice", "Alice", ("Operator",))
    with store._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")
    assert queue.claim_cycle("synthetic-worker", 135)
    source = ManagedRestorations(store, queue)
    snapshot = CompleteSnapshot(str(uuid4()), 1, NOW - timedelta(seconds=1), NOW, frozenset())
    incident = source.admit_absence(snapshot, IP, "synthetic-worker", enabled=True)["operation_id"]
    job = queue.claim_addition(1, "synthetic-worker", queue.cutoff(), execution_enabled=True, managed_restoration_enabled=True)
    outcome = getattr(request, "param", "UNVERIFIED")
    queue.finish_addition(job["id"], "synthetic-worker", outcome)
    queue.finish_cycle("synthetic-worker", 60)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "suspend", "operator", now=NOW)
    return {"store": store, "queue": queue, "registry": registry, "source": source,
            "case_id": "restoration:" + incident, "grant": grant, "job_id": job["id"], "outcome": outcome}


def fingerprint(lab):
    with lab["store"]._connection() as db:
        return tuple(db.iterdump())


def migrate(lab):
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        frozen = maintenance.review(db, "enable-closures", now=NOW)
        assert frozen["ready"]
        return maintenance.apply_reviewed(db, lab["store"], "enable-closures", "operator", NOW,
                                          frozen["confirmation_digest"], now=NOW)


def prepare(lab, **overrides):
    values = {"request_id": str(uuid4()), "case_id": lab["case_id"], "actor": "operator",
              "reason": "Abandon future maintenance, retain unknown outcome", "now": NOW}
    values.update(overrides)
    with lab["store"]._connection() as db:
        db.execute("BEGIN")
        return abandonment.prepare(db, **values)


def apply(lab, frozen, **overrides):
    values = {"request_id": frozen["request_id"], "case_id": frozen["case_id"], "actor": "operator",
              "reason": frozen["reason"], "reviewed_at": datetime.fromisoformat(frozen["reviewed_at"]),
              "digest": frozen["confirmation_digest"], "confirm_ip": str(IP), "now": NOW}
    values.update(overrides)
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return abandonment.apply(db, lab["store"], **values)


def test_separate_migration_is_empty_and_preserves_all_prior_state(lab):
    with lab["store"]._connection() as db:
        before = {table: list(db.execute(f"SELECT * FROM {table}")) for table in maintenance.TABLES}
        jobs = list(db.execute("SELECT * FROM operation_jobs"))
    migrate(lab)
    with lab["store"]._connection() as db:
        assert closures.present(db) and maintenance.recognized_schema(db)
        assert before == {table: list(db.execute(f"SELECT * FROM {table}")) for table in before}
        assert jobs == list(db.execute("SELECT * FROM operation_jobs"))
        assert db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0] == 0
    assert lab["queue"].mutations_suspended()


def test_without_explicit_migration_prepare_fails_without_writes(lab):
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="closure migration"):
        prepare(lab)
    assert fingerprint(lab) == before


@pytest.mark.parametrize("lab", ["FAILED", "UNVERIFIED"], indirect=True)
def test_review_is_read_only_and_abandonment_preserves_unknown_outcome_authority_and_queue(lab):
    migrate(lab)
    before = fingerprint(lab)
    frozen = prepare(lab)
    assert frozen["ready"] and fingerprint(lab) == before
    with lab["store"]._connection() as db:
        old = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
        jobs = list(db.execute("SELECT * FROM operation_jobs"))
        requests = list(db.execute("SELECT * FROM managed_shun_requests"))
        attempts = list(db.execute("SELECT * FROM managed_restoration_attempts"))
    receipt = apply(lab, frozen)
    assert receipt["retired_now"] and receipt["outcome_unchanged"] == lab["outcome"]
    with lab["store"]._connection() as db:
        after = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
        assert not after["enabled"]
        for key in ("intent_id", "generation", "authorization_request_id", "authorized_at"):
            assert after[key] == old[key]
        assert jobs == list(db.execute("SELECT * FROM operation_jobs"))
        assert requests == list(db.execute("SELECT * FROM managed_shun_requests"))
        assert attempts == list(db.execute("SELECT * FROM managed_restoration_attempts"))
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    event = next(event for event in lab["store"].list_events() if event["event_type"] == "MANAGED_RESTORATION_ABANDONED")
    assert event["actor_subject"] == "maintenance:operator" and event["actor_roles"] == []
    assert lab["queue"].mutations_suspended()
    with lab["store"]._connection() as db:
        db.execute("BEGIN")
        report = attention_report(db)
    assert report["abandoned_case_count"] == 1 and report["retained_case_count"] == 1
    assert report["items"][0]["outcome"] == lab["outcome"] and report["items"][0]["pair_latch_retained"]
    assert report["items"][0]["abandonment"]["decision"] == "ABANDON_MAINTENANCE"


def test_identical_replay_after_expiry_is_observational_and_mismatch_is_rejected(lab):
    migrate(lab)
    frozen = prepare(lab)
    receipt = apply(lab, frozen)
    before = fingerprint(lab)
    assert apply(lab, frozen, now=NOW + timedelta(days=2)) == {**receipt, "replayed": True}
    assert fingerprint(lab) == before
    for change in ({"reason": "Different"}, {"actor": "other"}, {"confirm_ip": "198.51.100.250"}, {"digest": "0" * 64}):
        with pytest.raises(ValueError, match="different reviewed inputs"):
            apply(lab, frozen, **change)
        assert fingerprint(lab) == before


def test_original_grant_replay_never_reenables_abandoned_policy_and_new_grants_refuse(lab):
    migrate(lab)
    apply(lab, prepare(lab))
    before = fingerprint(lab)
    receipt = lab["registry"].change(lab["grant"], "MAINTAIN", [(1, IP)], 0, 0,
                                    canonical_managed_change("MAINTAIN", [(1, IP)], 0, 0)[2], "alice", "Alice", ("Operator",))
    assert receipt["replayed"] and fingerprint(lab) == before
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, lab["store"], "resume-mutations", "operator", now=NOW)
    revision = lab["registry"].snapshot()["revision"]
    with pytest.raises(ManagedConflict, match="abandoned"):
        lab["registry"].change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, 0,
                               canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)[2], "alice", "Alice", ("Operator",))
    with lab["store"]._connection() as db:
        db.execute("BEGIN")
        frozen = maintenance.review(db, "resume-policy", now=NOW + timedelta(seconds=1))
    assert not frozen["ready"] and any("resolution" in value for value in frozen["blockers"])


@pytest.mark.parametrize("change", ["protection", "generation", "device", "observation", "revision"])
def test_reviewed_state_changes_do_not_rebase_or_retire_new_policy(lab, change):
    migrate(lab)
    frozen = prepare(lab)
    with lab["store"]._connection() as db:
        if change == "protection":
            db.execute("INSERT INTO protected_ips VALUES (?,'','',1,?)", (IP.packed, stamp(NOW)))
        elif change == "generation":
            db.execute("UPDATE managed_shun_targets SET generation=generation+1,intent_id=?", (str(uuid4()),))
        elif change == "device":
            db.execute("UPDATE devices SET enabled=0")
        elif change == "revision":
            db.execute("UPDATE managed_shun_registry SET revision=revision+1")
    if change == "observation":
        lab["store"].record_observed_shun(1, IP, "management")
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="state changed"):
        apply(lab, frozen)
    assert fingerprint(lab) == before


@pytest.mark.parametrize("change", ["unpaused", "desired", "lease", "job", "future", "cleanup"])
def test_unsafe_offline_conditions_block_abandonment_without_changes(lab, change):
    migrate(lab)
    with lab["store"]._connection() as db:
        if change == "cleanup":
            target = db.execute("SELECT * FROM managed_shun_targets").fetchone()
            db.execute("""INSERT INTO managed_removal_handoffs VALUES (?,1,?,?,1,?,NULL,'a','A','[]','{}','{}',?,?,'ATTENTION',NULL)""",
                       (str(uuid4()), IP.packed, target["intent_id"], target["authorization_request_id"], stamp(NOW), stamp(NOW)))
        elif change == "job":
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), IP.packed, stamp(NOW)))
        else:
            db.execute({"unpaused": "UPDATE operation_executor SET mutations_suspended=0",
                        "desired": "UPDATE managed_shun_registry SET restoration_suspended=0",
                        "lease": "UPDATE operation_executor SET owner='old-worker'",
                        "future": "UPDATE managed_shun_targets SET updated_at='2099-01-01T00:00:00Z'"}[change])
    frozen = prepare(lab)
    assert not frozen["ready"]
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="blocked"):
        apply(lab, frozen)
    assert fingerprint(lab) == before


@pytest.mark.parametrize("age", [-1, 300, 301])
def test_new_expired_or_future_confirmation_never_writes(lab, age):
    migrate(lab)
    frozen = prepare(lab)
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="expired or is in the future"):
        apply(lab, frozen, now=NOW + timedelta(seconds=age))
    assert fingerprint(lab) == before


def test_malformed_and_unsupported_scope_is_not_a_partial_fleet_action(lab):
    migrate(lab)
    before = fingerprint(lab)
    for case in ("operation:" + str(uuid4()), "fleet_cleanup:" + str(uuid4()), "restoration:bad", "restoration:" + str(uuid4()).upper()):
        with pytest.raises(ValueError):
            prepare(lab, case_id=case)
    for reason in ("", "x" * 501, "control\nline"):
        with pytest.raises(ValueError):
            prepare(lab, reason=reason)
    assert fingerprint(lab) == before


def test_typed_ip_mismatch_and_other_authority_keys_refuse(lab):
    migrate(lab)
    frozen = prepare(lab)
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="Typed IPv4"):
        apply(lab, frozen, confirm_ip="198.51.100.250")
    assert not prepare(lab, request_id=lab["grant"])["ready"]
    assert fingerprint(lab) == before


def test_audit_failure_rolls_back_retirement_receipt_and_revision_even_if_caught(lab, monkeypatch):
    migrate(lab)
    frozen = prepare(lab)
    before = fingerprint(lab)
    monkeypatch.setattr(lab["store"], "_insert_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError):
            abandonment.apply(db, lab["store"], frozen["request_id"], frozen["case_id"], "operator", frozen["reason"],
                              NOW, frozen["confirmation_digest"], str(IP), now=NOW)
    assert fingerprint(lab) == before


def test_migration_audit_failure_rolls_back_ddl(lab, monkeypatch):
    with lab["store"]._connection() as db:
        db.execute("BEGIN")
        frozen = maintenance.review(db, "enable-closures", now=NOW)
    before = fingerprint(lab)
    monkeypatch.setattr(lab["store"], "_insert_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with pytest.raises(RuntimeError), lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        maintenance.apply_reviewed(db, lab["store"], "enable-closures", "operator", NOW, frozen["confirmation_digest"], now=NOW)
    assert fingerprint(lab) == before


def test_retired_target_dates_and_pruned_job_evidence_survive_closure(lab):
    migrate(lab)
    with lab["store"]._connection() as db:
        db.execute("UPDATE managed_shun_targets SET enabled=0,retired_at=?,updated_at=?", (stamp(NOW - timedelta(seconds=1)), stamp(NOW - timedelta(seconds=1))))
        db.execute("DELETE FROM operation_links WHERE job_id=?", (lab["job_id"],))
        db.execute("DELETE FROM operation_jobs WHERE id=?", (lab["job_id"],))
        before = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
    receipt = apply(lab, prepare(lab))
    assert not receipt["retired_now"]
    with lab["store"]._connection() as db:
        assert before == dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())


def test_closure_is_immutable_and_key_cannot_gain_queue_or_policy_authority(lab):
    migrate(lab)
    receipt = apply(lab, prepare(lab))
    with lab["store"]._connection() as db:
        for sql in ("UPDATE managed_incident_closures SET reason='different'", "DELETE FROM managed_incident_closures"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, lab["store"], "resume-mutations", "operator", now=NOW)
    with pytest.raises(QueueConflict, match="keys"):
        lab["queue"].enqueue(receipt["operation_id"], [(1, IP)], "alice", "Alice", ("Operator",))
    revision = lab["registry"].snapshot()["revision"]
    with pytest.raises(ManagedConflict, match="keys"):
        lab["registry"].change(receipt["operation_id"], "RETIRE", [(1, IP)], revision, 0,
                               canonical_managed_change("RETIRE", [(1, IP)], revision, 0)[2],
                               "alice", "Alice", ("Operator",))


def test_concurrent_original_key_is_one_retirement_and_one_receipt(lab):
    migrate(lab)
    frozen = prepare(lab)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: apply(lab, frozen), range(3)))
    assert sum(not result["replayed"] for result in results) == 1
    with lab["store"]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0] == 1


def test_cli_review_then_abandon_uses_checked_backup_and_original_receipt(lab, tmp_path, capsys, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(seconds=30)

    monkeypatch.setattr(abandonment, "datetime", Clock)
    migrate(lab)
    common = ["--database", str(lab["store"].path), "--actor", "operator", "--confirm-offline",
              "--case-id", lab["case_id"], "--reason", "Abandon maintenance"]
    assert maintenance.main(["review-abandon", *common]) == 0
    frozen = json.loads(capsys.readouterr().out.splitlines()[-1])
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    args = ["abandon", *common, "--backup", str(private / "before.sqlite3"), "--confirm-reviewed",
            "--request-id", frozen["request_id"], "--confirm-ip", str(IP),
            "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]
    assert maintenance.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["decision"] == "ABANDON_MAINTENANCE"
    with sqlite3.connect(private / "before.sqlite3") as db:
        assert db.execute("SELECT enabled FROM managed_shun_targets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM managed_incident_closures").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["pause", "desired", "lease", "pending"])
def test_migration_refuses_unsafe_conditions_without_initializing(lab, change):
    with lab["store"]._connection() as db:
        if change == "pending":
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       (str(uuid4()), IP.packed, stamp(NOW)))
        else:
            db.execute({"pause": "UPDATE operation_executor SET mutations_suspended=0",
                        "desired": "UPDATE managed_shun_registry SET restoration_suspended=0",
                        "lease": "UPDATE operation_executor SET owner='stale-worker'"}[change])
    before = fingerprint(lab)
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        frozen = maintenance.review(db, "enable-closures", now=NOW)
        assert not frozen["ready"]
        with pytest.raises(ValueError, match="blocked"):
            maintenance.apply_reviewed(db, lab["store"], "enable-closures", "operator", NOW,
                                      frozen["confirmation_digest"], now=NOW)
    assert fingerprint(lab) == before


def test_partial_closure_schema_is_not_empty_or_repaired(lab):
    with lab["store"]._connection() as db:
        db.execute("CREATE TABLE managed_incident_closures(id TEXT)")
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="Exact complete"):
        prepare(lab)
    with lab["store"]._connection() as db, pytest.raises(ValueError):
        db.execute("BEGIN")
        maintenance.review(db, "enable-closures", now=NOW)
    assert fingerprint(lab) == before


def test_inconsistent_terminal_job_is_not_acknowledged_as_known_evidence(lab):
    migrate(lab)
    with lab["store"]._connection() as db:
        db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (lab["job_id"],))
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="disagrees"):
        prepare(lab)
    assert fingerprint(lab) == before


def test_late_expiry_rolls_back_all_abandonment_changes(lab, monkeypatch):
    migrate(lab)
    frozen = prepare(lab)
    before = fingerprint(lab)
    times = iter((NOW, NOW + timedelta(seconds=301)))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(abandonment, "datetime", Clock)
    with pytest.raises(ValueError, match="expired before commit"):
        apply(lab, frozen, now=None)
    assert fingerprint(lab) == before


def test_original_receipt_cannot_retire_a_later_generation(lab):
    migrate(lab)
    frozen = prepare(lab)
    apply(lab, frozen)
    # Synthetic future-authority fixture only; no route permits this rearm.
    with lab["store"]._connection() as db:
        db.execute("UPDATE managed_shun_targets SET enabled=1,retired_at=NULL,generation=generation+1,intent_id=?", (str(uuid4()),))
    before = fingerprint(lab)
    assert apply(lab, frozen)["replayed"]
    assert fingerprint(lab) == before


def test_different_request_for_same_incident_cannot_create_second_decision(lab):
    migrate(lab)
    first, second = prepare(lab), prepare(lab)
    apply(lab, first)
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="state changed"):
        apply(lab, second)
    assert fingerprint(lab) == before


def test_full_ledger_blocks_new_abandonment_without_recycling_keys(lab, monkeypatch):
    migrate(lab)
    monkeypatch.setattr(closures, "LIMIT", 0)
    monkeypatch.setattr(abandonment, "LIMIT", 0)
    frozen = prepare(lab)
    assert not frozen["ready"] and any("full" in item for item in frozen["blockers"])
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="blocked"):
        apply(lab, frozen)
    assert fingerprint(lab) == before
