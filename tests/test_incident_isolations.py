"""Durable offline exclusion and healthy-policy resume, with disposable state only."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_incident_acknowledgements import apply as acknowledge
from test_incident_acknowledgements import migrate as enable_ack
from test_incident_acknowledgements import prepare as review_ack
from test_managed_attention import IP, authority, fingerprint, fleet, initialize, job, report, stamp

from ftd_shun_manager import incident_acknowledgements as ack
from ftd_shun_manager import incident_isolations as isolation
from ftd_shun_manager import managed_maintenance as maintenance
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.maintenance import apply_recovery_control
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_shuns import ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict
from ftd_shun_manager.store import Device, Store

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
HEALTHY = IPv4Address("198.51.100.100")


@pytest.fixture
def state(tmp_path):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    OperationQueue(store).initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "suspend", "operator", now=NOW)
    enable_ack(store)
    return store


def migrate(store):
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        review = isolation.review_migration(db, now=NOW)
        assert review["ready"]
        return isolation.enable(db, store, "operator", NOW, review["confirmation_digest"], now=NOW)


def prepare(store, case_id, **kwargs):
    with store._connection() as db:
        db.execute("BEGIN")
        return isolation.prepare(db, kwargs.pop("request_id", str(uuid4())), case_id, "operator",
                                 "Exclude this complete incident scope; preserve unknown outcomes", now=NOW, **kwargs)


def apply(store, frozen, **overrides):
    values = {key: frozen[key] for key in ("request_id", "case_id", "reason")}
    values.update(actor="operator", reviewed_at=datetime.fromisoformat(frozen["reviewed_at"]), digest=frozen["confirmation_digest"],
                  confirm_ip=frozen["evidence"]["ip"], confirm_target_count=frozen["evidence"]["target_count"], now=NOW)
    values.update(overrides)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return isolation.apply(db, store, **values)


def isolate(store, case_id):
    acknowledge(store, review_ack(store, case_id))
    return apply(store, prepare(store, case_id))


def resume_review(store, action="resume-isolated-policy"):
    with store._connection() as db:
        db.execute("BEGIN")
        return maintenance.review(db, action, now=NOW + timedelta(seconds=1))


def resume_ordinary(store):
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, store, "resume-mutations", "operator", now=NOW)


def test_separate_migration_read_only_and_no_implicit_initialization(state):
    before = fingerprint(state)
    with state._connection() as db:
        db.execute("BEGIN")
        assert isolation.review_migration(db, now=NOW)["ready"]
        assert not isolation.present(db)
    assert fingerprint(state) == before
    migrate(state)
    before = fingerprint(state)
    report(state)
    assert fingerprint(state) == before
    with state._connection() as db:
        assert isolation.present(db)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_shun_registry'").fetchone()


@pytest.mark.parametrize("action", ["ADD", "REMOVE"])
def test_ordinary_isolation_preserves_outcome_and_blocks_manual_work(state, action):
    migrate(state)
    key = job(state, action=action)
    frozen = prepare(state, "operation:" + key)
    assert not frozen["ready"]  # Administrative review alone never grants isolation.
    result = isolate(state, "operation:" + key)
    assert result["outcome_unchanged"] == "UNVERIFIED" and result["target_count"] == 1
    resume_ordinary(state)
    queue = OperationQueue(state)
    with pytest.raises(QueueConflict, match="isolated"):
        queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",))
    with pytest.raises(QueueConflict, match="isolated"):
        queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",), source="manual_import", scope="import",
                      policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
    with state._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (key,)).fetchone()[0] == "UNVERIFIED"
    item = report(state)["items"][0]
    assert item["isolation"]["decision"] == "ISOLATE_INCIDENT" and item["target"]["incident_isolated"]


def test_managed_policy_is_retired_and_new_generation_cannot_bypass_latch(state):
    initialize(state)
    authority(state)
    migrate(state)
    key = job(state)
    isolate(state, "operation:" + key)
    with state._connection() as db:
        target = dict(db.execute("SELECT * FROM managed_shun_targets").fetchone())
        assert not target["enabled"] and target["retired_at"] == stamp(NOW)
    resume_ordinary(state)
    digest = canonical_managed_change("MAINTAIN", [(1, IP)], 1, 0)[2]
    with pytest.raises(ManagedConflict, match="abandoned"):
        ManagedShuns(state).change(str(uuid4()), "MAINTAIN", [(1, IP)], 1, 0, digest, "alice", "Alice", ("Operator",))


def test_whole_fleet_receipt_includes_missing_devices_and_all_latches(state):
    initialize(state)
    migrate(state)
    root = fleet(state, devices=205)
    acknowledge(state, review_ack(state, "fleet_cleanup:" + root))
    frozen = prepare(state, "fleet_cleanup:" + root)
    before = fingerprint(state)
    with pytest.raises(ValueError, match="entire reviewed"):
        apply(state, frozen, confirm_target_count=100)
    assert fingerprint(state) == before
    apply(state, frozen)
    with state._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM incident_isolation_targets").fetchone()[0] == 205
        assert isolation.pair_isolated(db, 205, IP)
        assert db.execute("SELECT state FROM managed_fleet_waits").fetchone()[0] == "ATTENTION"


def test_healthy_policy_resume_requires_exact_case_isolation_not_just_acknowledgment(state):
    initialize(state)
    authority(state, ip=HEALTHY)
    migrate(state)
    key = job(state)
    acknowledge(state, review_ack(state, "operation:" + key))
    frozen = prepare(state, "operation:" + key)
    apply(state, frozen)
    resume_ordinary(state)
    assert not resume_review(state, "resume-policy")["ready"]
    review = resume_review(state)
    assert review["ready"], review["blockers"]
    with state._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result = maintenance.apply_reviewed(db, state, "resume-isolated-policy", "operator", NOW + timedelta(seconds=1),
                                           review["confirmation_digest"], now=NOW + timedelta(seconds=1))
        assert result["isolated_scope_count"] == 1
        assert db.execute("SELECT restoration_suspended FROM managed_shun_registry").fetchone()[0] == 0
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (key,)).fetchone()[0] == "UNVERIFIED"
        assert isolation.pair_isolated(db, 1, IP)


def test_fleet_isolation_never_covers_independent_uncertain_predecessor_case(state):
    initialize(state)
    authority(state, ip=HEALTHY)
    predecessor = job(state)
    root = fleet(state, predecessors=[{"device_id": 1, "job_id": predecessor}])
    migrate(state)
    isolate(state, "fleet_cleanup:" + root)
    resume_ordinary(state)
    review = resume_review(state)
    assert not review["ready"] and any("uncertain operations" in item for item in review["blockers"])
    with state._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, state, "suspend", "operator", now=NOW)
    isolate(state, "operation:" + predecessor)
    resume_ordinary(state)
    assert resume_review(state)["ready"]


@pytest.mark.parametrize("mutation", ["job", "policy", "links", "latch"])
def test_changed_retained_evidence_refuses_resume(state, mutation):
    initialize(state)
    authority(state, ip=HEALTHY)
    authority(state)
    migrate(state)
    key = job(state)
    isolate(state, "operation:" + key)
    resume_ordinary(state)
    with state._connection() as db:
        if mutation == "job":
            db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (key,))
        elif mutation == "policy":
            db.execute("UPDATE managed_shun_targets SET enabled=1,retired_at=NULL WHERE ip=?", (IP.packed,))
        elif mutation == "links":
            new = str(uuid4())
            db.execute("INSERT INTO operation_requests VALUES (?,'alice','Alice','[]','manual','{}',?,?,'CANCELLED')", (new, stamp(NOW), stamp(NOW)))
            db.execute("INSERT INTO operation_links VALUES (?,?)", (new, key))
        else:
            db.execute("DROP TRIGGER incident_isolation_target_retained")
    before = fingerprint(state)
    with pytest.raises(ValueError, match="isolation"):
        resume_review(state)
    assert fingerprint(state) == before


def test_protected_removal_keeps_priority_and_fleet_manual_checks_missing_members(state, monkeypatch):
    initialize(state)
    migrate(state)
    root = fleet(state, devices=2)
    isolate(state, "fleet_cleanup:" + root)
    resume_ordinary(state)
    queue = OperationQueue(state)
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(seconds=61))
    with pytest.raises(QueueConflict, match="isolated"):
        queue.enqueue(str(uuid4()), [(1, IP)], "alice", "Alice", ("Operator",), scope="all")
    # Trusted protected-policy removal remains independent of manual isolation.
    with state._connection() as db:
        db.execute("INSERT INTO protected_ips VALUES (?,'test','',1,?)", (IP.packed, stamp(NOW)))
    queue.enqueue(str(uuid4()), [(1, IP)], "system:trusted-ip-policy", "Trusted policy", (), source="trusted_policy")
    assert queue.claim_cycle("worker", 135)
    assert queue.claim_removal(1, "worker", queue.cutoff()) is not None


def test_audit_failure_rolls_back_policy_latches_and_receipt(state, monkeypatch):
    initialize(state)
    authority(state)
    migrate(state)
    case = "operation:" + job(state)
    acknowledge(state, review_ack(state, case))
    frozen = prepare(state, case)
    before = fingerprint(state)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(state, "_insert_event", fail)
    with pytest.raises(RuntimeError, match="audit"):
        apply(state, frozen)
    assert fingerprint(state) == before


def test_concurrent_original_key_replay_is_observational(state):
    migrate(state)
    case = "operation:" + job(state)
    acknowledge(state, review_ack(state, case))
    frozen = prepare(state, case)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: apply(state, frozen), range(2)))
    assert sorted(row["replayed"] for row in results) == [False, True]
    before = fingerprint(state)
    assert apply(state, frozen, now=NOW + timedelta(days=367))["replayed"]
    assert fingerprint(state) == before
    with pytest.raises(ValueError, match="different reviewed"):
        apply(state, frozen, reason="changed")


def test_complete_absence_reconciliation_does_not_drop_isolation_evidence(state, monkeypatch):
    initialize(state)
    authority(state, ip=HEALTHY)
    migrate(state)
    key = job(state, action="REMOVE")
    isolate(state, "operation:" + key)
    queue = OperationQueue(state)
    queue.reconcile_unknown(1, [])
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(days=367))
    queue.prune_completed(366)
    with state._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (key,)).fetchone()[0] == "RECONCILED_ABSENT"
    resume_ordinary(state)
    assert resume_review(state)["ready"]


def test_cli_separate_checked_migration_isolation_and_replay(state, tmp_path, capsys):
    private = tmp_path / "backups"
    private.mkdir(mode=0o700)
    base = ["--database", str(state.path), "--actor", "operator", "--confirm-offline"]
    assert ack.main(["review-enable-isolation", *base]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert ack.main(["enable-isolation", *base, "--backup", str(private / "before-enable.sqlite3"), "--confirm-reviewed",
        "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]) == 0
    capsys.readouterr()
    case = "operation:" + job(state)
    acknowledge(state, review_ack(state, case))
    args = ["--case-id", case, "--reason", "Exclude this unresolved incident"]
    assert ack.main(["review-isolate", *base, *args]) == 0
    frozen = json.loads(capsys.readouterr().out)
    confirm = ["--request-id", frozen["request_id"], "--confirm-ip", str(IP), "--confirm-target-count", "1", "--confirm-reviewed",
               "--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]
    assert ack.main(["isolate", *base, *args, *confirm, "--backup", str(private / "before-isolate.sqlite3")]) == 0
    assert not json.loads(capsys.readouterr().out)["replayed"]
    with sqlite3.connect(private / "before-isolate.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM incident_isolations").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["observation", "protection", "device"])
def test_stale_isolation_review_refuses_without_partial_retirement(state, change):
    initialize(state)
    authority(state)
    migrate(state)
    case = "operation:" + job(state)
    acknowledge(state, review_ack(state, case))
    frozen = prepare(state, case)
    if change == "observation":
        state.record_observed_shun(1, IP, "management")
    else:
        with state._connection() as db:
            db.execute("UPDATE protected_policy SET revision=revision+1" if change == "protection" else "UPDATE devices SET enabled=0")
    before = fingerprint(state)
    with pytest.raises(ValueError, match="state changed"):
        apply(state, frozen)
    assert fingerprint(state) == before


@pytest.mark.parametrize("age", [timedelta(minutes=5), timedelta(seconds=-1)])
def test_expired_or_future_isolation_review_cannot_commit(state, age):
    migrate(state)
    case = "operation:" + job(state)
    acknowledge(state, review_ack(state, case))
    frozen = prepare(state, case)
    before = fingerprint(state)
    with pytest.raises(ValueError, match="expired|future"):
        apply(state, frozen, now=NOW + age)
    assert fingerprint(state) == before


def test_missing_isolated_fleet_member_cannot_be_silently_removed_from_latches(state):
    initialize(state)
    migrate(state)
    root = fleet(state, devices=205)
    isolate(state, "fleet_cleanup:" + root)
    with state._connection() as db:
        db.execute("DROP TRIGGER incident_isolation_target_retained")
        db.execute("DELETE FROM incident_isolation_targets WHERE device_id=205")
        # Recreate the original schema to exercise the count/content guard too.
        db.execute("""CREATE TRIGGER incident_isolation_target_retained BEFORE DELETE ON incident_isolation_targets
BEGIN SELECT RAISE(ABORT,'incident isolation target is retained'); END""")
    with pytest.raises(ValueError, match="latches"):
        report(state)


@pytest.mark.parametrize("migration", [True, False])
def test_late_expiry_rolls_back_even_if_outer_caller_commits(state, monkeypatch, migration):
    initialize(state)
    authority(state)
    if not migration:
        migrate(state)
        case = "operation:" + job(state)
        acknowledge(state, review_ack(state, case))
        frozen = prepare(state, case)
    with state._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        before = tuple(db.iterdump())
        def expire(*args):
            raise ValueError("expired before commit")
        monkeypatch.setattr(ack, "_check_commit_expiry", expire)
        with pytest.raises(ValueError, match="expired before commit"):
            if migration:
                review = isolation.review_migration(db, now=NOW)
                isolation.enable(db, state, "operator", NOW, review["confirmation_digest"], now=NOW)
            else:
                isolation.apply(db, state, frozen["request_id"], frozen["case_id"], "operator", frozen["reason"], NOW,
                                frozen["confirmation_digest"], str(IP), 1, now=NOW)
        assert tuple(db.iterdump()) == before


def test_acknowledgment_and_isolation_keys_cannot_cross_authority(state):
    initialize(state)
    migrate(state)
    case = "operation:" + job(state)
    receipt = isolate(state, case)
    other = "operation:" + job(state, ip=HEALTHY)
    assert not review_ack(state, other, request_id=receipt["request_id"])["ready"]
    resume_ordinary(state)
    with pytest.raises(QueueConflict, match="cannot acquire"):
        OperationQueue(state).enqueue(receipt["request_id"], [(1, HEALTHY)], "alice", "Alice", ("Operator",))


def test_frozen_resume_refuses_new_uncertainty_and_audit_failure_preserves_pause(state, monkeypatch):
    initialize(state)
    authority(state, ip=HEALTHY)
    migrate(state)
    isolate(state, "operation:" + job(state))
    resume_ordinary(state)
    frozen = resume_review(state)
    with state._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        before = tuple(db.iterdump())
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic audit")
        monkeypatch.setattr(state, "_insert_event", fail)
        with pytest.raises(RuntimeError, match="audit"):
            maintenance.apply_reviewed(db, state, "resume-isolated-policy", "operator", NOW + timedelta(seconds=1),
                                       frozen["confirmation_digest"], now=NOW + timedelta(seconds=1))
        assert tuple(db.iterdump()) == before
    job(state, ip=IPv4Address("198.51.100.250"))
    assert not resume_review(state)["ready"]


def test_manual_claim_rechecks_isolation_before_dispatch(state, monkeypatch):
    migrate(state)
    isolate(state, "operation:" + job(state))
    resume_ordinary(state)
    queue = OperationQueue(state)
    monkeypatch.setattr(queue, "_now", lambda: NOW + timedelta(seconds=61))
    key, request = str(uuid4()), str(uuid4())
    # Simulate restored queued evidence from an older writer; current admission already refuses it.
    with state._connection() as db:
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                   (key, IP.packed, stamp(NOW)))
        db.execute("INSERT INTO operation_requests VALUES (?,'alice','Alice','[\"Operator\"]','manual','{}',?,?,'ACTIVE')",
                   (request, stamp(NOW), stamp(NOW + timedelta(minutes=10))))
        db.execute("INSERT INTO operation_links VALUES (?,?)", (request, key))
    assert queue.claim_cycle("worker", 135)
    assert queue.claim_removal(1, "worker", queue.cutoff()) is None
    with state._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (key,)).fetchone()[0] == "CANCELLED"


def test_single_cleanup_isolation_preserves_retired_policy_dates_and_predecessor(state):
    initialize(state)
    authority(state, ip=HEALTHY)
    request, intent = authority(state, enabled=False)
    predecessor = job(state, state="FAILED")
    key = str(uuid4())
    with state._connection() as db:
        db.execute("""INSERT INTO managed_removal_handoffs VALUES (?,1,?,?,1,?,?,'alice','Alice','[]',
            '{}','{}',?,?,'ATTENTION','synthetic failure')""",
                   (key, IP.packed, intent, request, predecessor, stamp(NOW), stamp(NOW + timedelta(minutes=10))))
        retired = dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone())
    migrate(state)
    isolate(state, "device_cleanup:" + key)
    with state._connection() as db:
        assert dict(db.execute("SELECT * FROM managed_shun_targets WHERE ip=?", (IP.packed,)).fetchone()) == retired
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (predecessor,)).fetchone()[0] == "FAILED"
    resume_ordinary(state)
    assert resume_review(state)["ready"]


def test_isolation_migration_audit_failure_rolls_back_both_tables(state, monkeypatch):
    before = fingerprint(state)
    with state._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        frozen = isolation.review_migration(db, now=NOW)
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic audit")
        monkeypatch.setattr(state, "_insert_event", fail)
        with pytest.raises(RuntimeError, match="audit"):
            isolation.enable(db, state, "operator", NOW, frozen["confirmation_digest"], now=NOW)
    assert fingerprint(state) == before
