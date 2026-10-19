"""Unrelated-policy recovery uses real local controls and synthetic SQLite only."""

import json
import sqlite3
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_managed_abandonment import IP, NOW, apply, fingerprint, migrate, prepare
from test_managed_abandonment import lab as lab  # noqa: PLC0414 -- Re-export the shared pytest fixture.
from test_managed_attention import attempt, fleet

from ftd_shun_manager import managed_isolation, managed_shuns
from ftd_shun_manager import managed_maintenance as maintenance
from ftd_shun_manager.maintenance import apply_recovery_control
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import QueueConflict, stamp

HEALTHY = IPv4Address("198.51.100.245")
RESUME = NOW + timedelta(seconds=2)
ACTION = "resume-unrelated-policy"


@pytest.fixture
def isolated(lab, monkeypatch):
    migrate(lab)
    lab["closure_review"] = prepare(lab)
    lab["closure"] = apply(lab, lab["closure_review"])
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, lab["store"], "resume-mutations", "operator", now=NOW + timedelta(seconds=1))
    monkeypatch.setattr(managed_shuns, "now", lambda: stamp(NOW + timedelta(seconds=1)))
    revision = lab["registry"].snapshot()["revision"]
    lab["registry"].change(str(uuid4()), "MAINTAIN", [(1, HEALTHY)], revision, 0,
                           canonical_managed_change("MAINTAIN", [(1, HEALTHY)], revision, 0)[2],
                           "alice", "Alice", ("Operator",))
    return lab


def review(lab, action=ACTION, **kwargs):
    with lab["store"]._connection() as db:
        db.execute("BEGIN")
        return maintenance.review(db, action, now=kwargs.pop("now", RESUME), **kwargs)


def resume(lab, frozen, **kwargs):
    with lab["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return maintenance.apply_reviewed(db, lab["store"], ACTION, "operator",
                                          datetime.fromisoformat(frozen["reviewed_at"]), frozen["confirmation_digest"],
                                          now=kwargs.pop("now", RESUME), **kwargs)


@pytest.mark.parametrize("lab", ["UNVERIFIED", "FAILED"], indirect=True)
def test_resume_only_healthy_policy_preserves_all_uncertainty_and_retired_authority(isolated):
    lab = isolated
    before = fingerprint(lab)
    frozen = review(lab)
    assert fingerprint(lab) == before and frozen["ready"]
    assert frozen["isolated_incidents"][0]["case_id"] == lab["case_id"]
    assert [target["ip"] for target in frozen["targets"]] == [str(HEALTHY)]
    assert not review(lab, "resume-policy")["ready"]  # No implicit exception in the old command.
    with lab["store"]._connection() as db:
        tables = ("managed_incident_closures", "managed_restoration_attempts", "managed_shun_requests", "operation_jobs", "operation_links")
        retained = {table: list(db.execute(f"SELECT * FROM {table}")) for table in tables}
        retired = dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone())
        healthy = dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (HEALTHY.packed,)).fetchone())
    receipt = resume(lab, frozen)
    assert receipt["isolated_incident_count"] == 1 and receipt["enabled_targets"] == 1
    assert receipt["absence_not_before"] > stamp(RESUME) and not receipt["restoration_suspended"]
    with lab["store"]._connection() as db:
        assert retained == {table: list(db.execute(f"SELECT * FROM {table}")) for table in tables}
        assert retired == dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone())
        after = dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (HEALTHY.packed,)).fetchone())
        assert {k: v for k, v in healthy.items() if k not in {"revision", "updated_at"}} == {
            k: v for k, v in after.items() if k not in {"revision", "updated_at"}}
    event = next(row for row in lab["store"].list_events() if row["event_type"] == "MANAGED_UNRELATED_POLICY_RESUMED")
    assert event["actor_subject"] == "maintenance:operator" and event["actor_roles"] == []
    assert event["details"]["isolation_digest"] == receipt["isolation_digest"]
    with pytest.raises(ValueError, match="state changed"):
        resume(lab, frozen)


def test_fresh_read_gates_and_abandoned_pair_latch_survive_resume(isolated, monkeypatch):
    lab = isolated
    resume(lab, review(lab))
    monkeypatch.setattr(lab["queue"], "_now", lambda: NOW + timedelta(seconds=61))
    assert lab["queue"].claim_cycle("synthetic-worker", 135)
    old = CompleteSnapshot(str(uuid4()), 1, RESUME, RESUME + timedelta(seconds=1), frozenset())
    with pytest.raises(QueueConflict, match="predates policy"):
        lab["source"].admit_absence(old, HEALTHY, "synthetic-worker", enabled=True)
    fresh = CompleteSnapshot(str(uuid4()), 1, NOW + timedelta(seconds=60), NOW + timedelta(seconds=61), frozenset())
    assert lab["source"].admit_absence(fresh, HEALTHY, "synthetic-worker") is None
    assert lab["source"].admit_absence(fresh, HEALTHY, "synthetic-worker", enabled=True)
    with pytest.raises(QueueConflict):
        lab["source"].admit_absence(fresh, IP, "synthetic-worker", enabled=True)
    revision = lab["registry"].snapshot()["revision"]
    with pytest.raises(ManagedConflict, match="abandoned"):
        lab["registry"].change(str(uuid4()), "MAINTAIN", [(1, IP)], revision, 0,
                               canonical_managed_change("MAINTAIN", [(1, IP)], revision, 0)[2], "alice", "Alice", ("Operator",))
    before = fingerprint(lab)
    assert apply(lab, lab["closure_review"])["replayed"]
    assert lab["registry"].change(lab["grant"], "MAINTAIN", [(1, IP)], 0, 0,
                                  canonical_managed_change("MAINTAIN", [(1, IP)], 0, 0)[2],
                                  "alice", "Alice", ("Operator",))["replayed"]
    assert fingerprint(lab) == before


def test_pruned_terminal_job_is_not_required_or_recreated(isolated):
    with isolated["store"]._connection() as db:
        db.execute("DELETE FROM operation_jobs WHERE id=?", (isolated["job_id"],))
    frozen = review(isolated)
    assert frozen["ready"] and not frozen["isolated_incidents"][0]["job_retained"]
    resume(isolated, frozen)
    with isolated["store"]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["pause", "lease", "pending", "device", "protection", "empty", "clock", "ordinary", "cleanup"])
def test_other_blockers_are_not_covered_by_a_closed_incident(isolated, change):
    with isolated["store"]._connection() as db:
        if change in {"pending", "ordinary"}:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,?,?,'REMOVE')",
                       (str(uuid4()), IP.packed, "QUEUED" if change == "pending" else "UNVERIFIED", stamp(NOW)))
        elif change == "protection":
            db.execute("INSERT INTO protected_ips VALUES (?,'','',1,?)", (HEALTHY.packed, stamp(NOW)))
        elif change == "cleanup":
            target = db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone()
            db.execute("""INSERT INTO managed_removal_handoffs VALUES (?,1,?,?,1,?,NULL,'a','A','[]','{}','{}',?,?,'ATTENTION',NULL)""",
                       (str(uuid4()), IP.packed, target["intent_id"], target["authorization_request_id"], stamp(NOW), stamp(NOW)))
        else:
            db.execute({"pause": "UPDATE operation_executor SET mutations_suspended=1",
                        "lease": "UPDATE operation_executor SET owner='old-worker'",
                        "device": "UPDATE devices SET enabled=0",
                        "empty": "UPDATE managed_shun_targets SET enabled=0,retired_at='2026-10-19T10:00:01Z' WHERE enabled=1",
                        "clock": "UPDATE managed_shun_targets SET updated_at='2099-01-01T00:00:00Z' WHERE enabled=1"}[change])
    frozen = review(isolated)
    before = fingerprint(isolated)
    assert not frozen["ready"]
    with pytest.raises(ValueError, match="blocked"):
        resume(isolated, frozen)
    assert fingerprint(isolated) == before


@pytest.mark.parametrize("change", ["reenabled", "generation", "missing", "outcome", "receipt", "evidence", "request"])
def test_inconsistent_closure_is_never_treated_as_isolation(isolated, change):
    with isolated["store"]._connection() as db:
        if change in {"receipt", "evidence", "request"}:
            db.execute("DROP TRIGGER managed_closure_immutable")
            column = {"receipt": "result_json", "evidence": "evidence_json", "request": "request_json"}[change]
            db.execute(f"UPDATE managed_incident_closures SET {column}='{{}}'")
            db.execute(next(row[3] for row in maintenance._expected_schema(True) if row[1] == "managed_closure_immutable"))
        elif change == "outcome":
            db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (isolated["job_id"],))
        elif change == "missing":
            db.execute("DELETE FROM managed_shun_targets WHERE ip=?", (IP.packed,))
        else:
            db.execute("UPDATE managed_shun_targets SET " + ("enabled=1,retired_at=NULL" if change == "reenabled" else "generation=generation+1") + " WHERE ip=?", (IP.packed,))
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="inconsistent"):
        review(isolated)
    assert fingerprint(isolated) == before


@pytest.mark.parametrize("change", ["observation", "revision", "job_identity", "delegation"])
def test_frozen_review_binds_evidence_not_just_counts(isolated, change):
    frozen = review(isolated)
    with isolated["store"]._connection() as db:
        if change == "revision":
            db.execute("UPDATE managed_shun_registry SET revision=revision+1")
        elif change == "job_identity":
            db.execute("UPDATE operation_jobs SET started_at=? WHERE id=?", (stamp(NOW + timedelta(seconds=1)), isolated["job_id"]))
        elif change == "delegation":
            db.execute("UPDATE operation_requests SET state='EXPIRED' WHERE id=?", (isolated["case_id"].split(":")[1],))
    if change == "observation":
        isolated["store"].record_observed_shun(1, IP, "management")
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="state changed|inconsistent"):
        resume(isolated, frozen)
    assert fingerprint(isolated) == before


@pytest.mark.parametrize("age", [-1, 300])
def test_expired_future_review_cannot_resume(isolated, age):
    frozen = review(isolated)
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="expired|future"):
        resume(isolated, frozen, now=RESUME + timedelta(seconds=age))
    assert fingerprint(isolated) == before


def test_audit_failure_rolls_back_even_when_caught(isolated, monkeypatch):
    frozen = review(isolated)
    before = fingerprint(isolated)
    monkeypatch.setattr(isolated["store"], "_insert_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with isolated["store"]._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError):
            maintenance.apply_reviewed(db, isolated["store"], ACTION, "operator", RESUME,
                                       frozen["confirmation_digest"], now=RESUME)
    assert fingerprint(isolated) == before


def test_no_implicit_closure_migration(lab):
    before = fingerprint(lab)
    with pytest.raises(ValueError, match="existing closure ledger"):
        review(lab)
    assert fingerprint(lab) == before


def test_one_closure_does_not_cover_another_failed_attempt_on_the_same_pair(isolated):
    with isolated["store"]._connection() as db:
        target = db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone()
    attempt(isolated["store"], target["authorization_request_id"], target["intent_id"], state="FAILED")
    frozen = review(isolated)
    before = fingerprint(isolated)
    assert not frozen["ready"] and any("own retained abandonment" in value for value in frozen["blockers"])
    with pytest.raises(ValueError, match="blocked"):
        resume(isolated, frozen)
    assert fingerprint(isolated) == before


@pytest.mark.parametrize("state,phase", [("ATTENTION", "ADMITTED"), ("WAITING_ADD", "ADMITTED"), (None, "ADMITTING")])
def test_no_partial_fleet_exception(isolated, state, phase):
    fleet(isolated["store"], devices=5, state=state, phase=phase)
    frozen = review(isolated)
    before = fingerprint(isolated)
    assert not frozen["ready"]
    with pytest.raises(ValueError, match="blocked"):
        resume(isolated, frozen)
    assert fingerprint(isolated) == before


@pytest.mark.parametrize("field", ["actor_subject", "actor_roles_json", "payload_json", "state"])
def test_retained_delegation_cannot_be_reinterpreted_as_closed_system_work(isolated, field):
    value = {"actor_subject": "someone-else", "actor_roles_json": '["Operator"]', "payload_json": '{}', "state": "ACTIVE"}[field]
    with isolated["store"]._connection() as db:
        db.execute(f"UPDATE operation_requests SET {field}=? WHERE id=?", (value, isolated["case_id"].split(":")[1]))
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="inconsistent"):
        review(isolated)
    assert fingerprint(isolated) == before


def test_extra_request_link_is_not_exempted(isolated):
    with isolated["store"]._connection() as db:
        db.execute("""INSERT INTO operation_requests SELECT ?,actor_subject,actor_display_name,actor_roles_json,source,
            payload_json,requested_at,expires_at,state FROM operation_requests WHERE id=?""",
                   ("additional-request", isolated["case_id"].split(":")[1]))
        db.execute("INSERT INTO operation_links VALUES (?,?)", ("additional-request", isolated["job_id"]))
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="inconsistent"):
        review(isolated)
    assert fingerprint(isolated) == before


def test_pruned_delegation_preserves_incident_and_never_gets_recreated(isolated):
    with isolated["store"]._connection() as db:
        db.execute("DELETE FROM operation_requests WHERE id=?", (isolated["case_id"].split(":")[1],))
    frozen = review(isolated)
    assert frozen["ready"] and not frozen["isolated_incidents"][0]["delegation_retained"]
    resume(isolated, frozen)
    with isolated["store"]._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 0
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (isolated["job_id"],)).fetchone()[0] == "UNVERIFIED"


def test_normal_resume_digest_is_not_an_unrelated_resume_confirmation(isolated):
    frozen = review(isolated, "resume-policy")
    before = fingerprint(isolated)
    with pytest.raises(ValueError, match="state changed"):
        resume(isolated, frozen)
    assert fingerprint(isolated) == before


def test_late_expiry_rolls_back_new_resume(isolated, monkeypatch):
    frozen = review(isolated)
    before = fingerprint(isolated)
    times = iter((RESUME, RESUME + timedelta(seconds=301)))

    class ClockMeta(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(maintenance, "datetime", Clock)
    with pytest.raises(ValueError, match="expired during maintenance"):
        resume(isolated, frozen, now=None)
    assert fingerprint(isolated) == before


def test_cli_review_and_checked_backup_are_separate_from_normal_resume(isolated, tmp_path, monkeypatch, capsys):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(RESUME.isoformat())

    monkeypatch.setattr(maintenance, "datetime", Clock)
    monkeypatch.setattr(managed_isolation, "datetime", Clock)
    common = ["--database", str(isolated["store"].path), "--actor", "operator", "--confirm-offline"]
    assert maintenance.main(["review-resume-unrelated", *common]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert frozen["ready"]
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    backup = directory / "before.sqlite3"
    assert maintenance.main([ACTION, *common, "--backup", str(backup), "--confirm-reviewed",
                             "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["isolated_incident_count"] == 1
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT restoration_suspended FROM managed_shun_registry").fetchone()[0] == 1
    assert backup.stat().st_mode & 0o777 == 0o600
