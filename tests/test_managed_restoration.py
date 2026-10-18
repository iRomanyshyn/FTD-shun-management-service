"""System restoration lifecycle on disposable SQLite; no device or live stack."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_shuns
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.maintenance import apply_recovery_control
from ftd_shun_manager.managed_fleet_removals import ManagedFleetRemovals
from ftd_shun_manager.managed_intent import (
    canonical_managed_change,
    canonical_managed_fleet_removal,
    canonical_managed_removal,
)
from ftd_shun_manager.managed_removals import ManagedRemovals
from ftd_shun_manager.managed_restoration import (
    ACTOR,
    CompleteSnapshot,
    ManagedRestorations,
    present,
)
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_scope import ManagedRemovalScopes
from ftd_shun_manager.managed_shuns import ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    queue, registry = OperationQueue(store), ManagedShuns(store)
    queue.initialize()
    registry.initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    clock = [datetime.now(UTC) + timedelta(seconds=1)]
    monkeypatch.setattr(OperationQueue, "_now", lambda self: clock[0])
    monkeypatch.setattr(managed_shuns, "now", lambda: clock[0].isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    change(registry)
    restoration = ManagedRestorations(store, queue)
    restoration.initialize()
    with store._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")  # Isolated fixture, never a runtime resume.
    assert queue.claim_cycle("synthetic-worker", 135)
    return restoration, registry, clock


def change(registry, action="MAINTAIN"):
    revision = registry.snapshot()["revision"]
    with registry.store._connection() as db:
        protected = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    return registry.change(str(uuid4()), action, [(1, IP)], revision, protected,
                           canonical_managed_change(action, [(1, IP)], revision, protected)[2],
                           "authorizer", "Authorizer", ("Operator",))


def evidence(lab, **overrides):
    return CompleteSnapshot(**{"id": str(uuid4()), "device_id": 1, "started_at": lab[2][0], "completed_at": lab[2][0],
                               "present_ips": frozenset(), **overrides})


def admit(lab, snapshot=None):
    return lab[0].admit_absence(snapshot or evidence(lab), IP, "synthetic-worker", enabled=True)


def claim(lab, **overrides):
    queue = lab[0].queue
    return queue.claim_addition(1, "synthetic-worker", queue.cutoff(), execution_enabled=True,
                                **{"managed_restoration_enabled": True, **overrides})


def attempt(lab):
    with lab[0].store._connection() as db:
        return dict(db.execute("SELECT * FROM managed_restoration_attempts ORDER BY requested_at DESC LIMIT 1").fetchone())


def fingerprint(lab):
    with lab[0].store._connection() as db:
        return tuple(db.iterdump())


def advance_clock(lab, seconds=301):
    lab[0].queue.finish_cycle("synthetic-worker", 60)
    lab[2][0] += timedelta(seconds=seconds)
    assert lab[0].queue.claim_cycle("synthetic-worker", 135)


def test_runtime_startup_reads_and_default_hooks_never_initialize_or_dispatch(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "empty.db")
    app = create_app(replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                             agent_mode="disabled"), store)
    coordinator = ManagedRestorations(store, app.state.synchronizer.queue)
    assert coordinator.admit_absence(None, None, None) is None
    app.state.synchronizer.queue.status()
    with store._connection() as db:
        assert not present(db)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'managed_%'").fetchone()
    assert not any("restoration" in route.path for route in app.routes)


def test_source_is_system_policy_not_renewed_manual_authority_or_import(lab):
    snapshot = evidence(lab)
    receipt = admit(lab, snapshot)
    before = fingerprint(lab)
    assert admit(lab, snapshot) == {**receipt, "replayed": True}
    assert fingerprint(lab) == before
    with lab[0].store._connection() as db:
        request = db.execute("SELECT * FROM operation_requests WHERE id=?", (receipt["operation_id"],)).fetchone()
        assert request["actor_subject"] == ACTOR and json.loads(request["actor_roles_json"]) == []
        assert request["source"] == "trusted_policy" and json.loads(request["payload_json"])["scope"] == "managed_restoration"
        assert datetime.fromisoformat(request["expires_at"]) - datetime.fromisoformat(request["requested_at"]) == timedelta(seconds=900)
        assert not db.execute("SELECT 1 FROM manual_import_batches").fetchone()
    assert claim(lab, managed_restoration_enabled=False) is None
    assert not lab[0].queue.has_pending(addition_device_ids=frozenset({1}))
    status = lab[0].queue.status(addition_device_ids=frozenset({1}))
    assert not status["items"][0]["execution_enabled"]
    assert status["items"][0]["requests"][0]["source"] == "managed_shun_policy"
    assert status["progress"]["requests"][0]["source"] == "managed_shun_policy"
    assert lab[0].queue.claim_next_mutation(1, "synthetic-worker", lab[0].queue.cutoff(), managed_restoration_enabled=True) is None


@pytest.mark.parametrize("created", [True, False])
def test_typed_success_or_noop_keeps_occurrence_provenance_honest(lab, created):
    receipt = admit(lab)
    job = claim(lab)
    assert job and attempt(lab)["state"] == "RUNNING"
    result = lab[0].queue.finish_addition(job["id"], "synthetic-worker", AdditionResult(created, "management" if created else None))
    assert result == ("VERIFIED" if created else "NOOP")
    row = attempt(lab)
    assert row["state"] == result and bool(row["occurrence_id"]) is created
    entry = lab[1].snapshot()["entries"][0]
    assert entry["restoration_state"] == result and not entry["restoration_attention"]
    assert bool(entry["last_verified_restoration_at"]) is created
    with lab[0].store._connection() as db:
        assert not db.execute("SELECT 1 FROM shun_import_origins").fetchone()
        events = db.execute("SELECT * FROM shun_events WHERE request_id=?", (receipt["operation_id"],)).fetchall()
        assert all(event["actor_subject"] == ACTOR and json.loads(event["actor_roles_json"]) == [] for event in events)
        recorded = [e for e in events if e["event_type"] == "MANAGED_SHUN_RESTORATION_" + result]
        assert len(recorded) == 1
        assert bool(json.loads(recorded[0]["details_json"])["occurrence_id"]) is created


@pytest.mark.parametrize("overrides", [
    {"complete": False}, {"present_ips": frozenset({IP})}, {"present_ips": set()},
    {"device_id": True}, {"id": "not-a-uuid"}, {"started_at": "not-a-date"},
])
def test_invalid_or_present_snapshot_cannot_authorize_absence(lab, overrides):
    before = fingerprint(lab)
    with pytest.raises((ValueError, QueueConflict)):
        admit(lab, evidence(lab, **overrides))
    assert fingerprint(lab) == before


@pytest.mark.parametrize("offset_start,offset_end", [(-121, 0), (0, 1), (1, 0), (-1, 0)])
def test_stale_future_reversed_or_pre_authorization_evidence_is_rejected(lab, offset_start, offset_end):
    before = fingerprint(lab)
    with pytest.raises(QueueConflict):
        admit(lab, evidence(lab, started_at=lab[2][0]+timedelta(seconds=offset_start),
                            completed_at=lab[2][0]+timedelta(seconds=offset_end)))
    assert fingerprint(lab) == before


def test_any_observed_interface_prevents_restoration(lab):
    lab[0].store.record_observed_shun(1, IP, "outside")
    with pytest.raises(QueueConflict, match="interface"):
        admit(lab)


def test_new_snapshot_does_not_multiply_pending_attempts_and_manual_work_does_not_coalesce(lab):
    receipt = admit(lab)
    with pytest.raises(QueueConflict, match="already pending"):
        admit(lab)
    with pytest.raises(QueueConflict, match="cannot coalesce"):
        lab[0].queue.enqueue(str(uuid4()), [(1, IP)], "other", "Other", ("Operator",), source="manual_import",
                            scope="import", policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
    with pytest.raises(PermissionError):
        lab[0].queue.cancel(receipt["operation_id"], "authorizer", True)


def test_concurrent_same_snapshot_admission_is_one_system_attempt(lab):
    snapshot = evidence(lab)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: admit(lab, snapshot), range(4)))
    assert sum(not row["replayed"] for row in receipts) == 1
    assert len({row["operation_id"] for row in receipts}) == 1


def test_cutoff_and_both_explicit_capabilities_are_required(lab):
    cutoff = lab[0].queue.cutoff()
    admit(lab)
    assert lab[0].queue.claim_addition(1, "synthetic-worker", cutoff, execution_enabled=True, managed_restoration_enabled=True) is None
    assert lab[0].queue.claim_addition(1, "synthetic-worker", lab[0].queue.cutoff(), managed_restoration_enabled=True) is None
    assert claim(lab) is not None


@pytest.mark.parametrize("outcome", ["FAILED", "UNVERIFIED"])
def test_failure_attention_survives_retirement_new_generation_and_queue_pruning(lab, outcome):
    receipt = admit(lab)
    job = claim(lab)
    lab[0].queue.finish_addition(job["id"], "synthetic-worker", outcome)
    change(lab[1], "RETIRE")
    advance_clock(lab, 400 * 86400)
    lab[0].queue.prune_completed(366)
    change(lab[1])
    with pytest.raises(QueueConflict, match="blocked|resolution"):
        admit(lab)
    with pytest.raises(QueueConflict, match="Restoration keys"):
        lab[0].queue.enqueue(receipt["operation_id"], [(1, IP)], "other", "Other", ("Operator",))
    assert attempt(lab)["state"] == outcome
    assert lab[1].snapshot()["entries"][0]["restoration_attention"]


def test_deferral_reuses_same_job_without_renewing_authority(lab):
    receipt = admit(lab)
    job = claim(lab)
    with lab[0].store._connection() as db:
        original = db.execute("SELECT expires_at FROM operation_requests WHERE id=?", (receipt["operation_id"],)).fetchone()[0]
    lab[0].queue.defer_addition(job["id"], "synthetic-worker")
    assert attempt(lab)["state"] == "QUEUED"
    assert claim(lab)["id"] == job["id"]
    with lab[0].store._connection() as db:
        assert db.execute("SELECT expires_at FROM operation_requests WHERE id=?", (receipt["operation_id"],)).fetchone()[0] == original


def test_expired_delegation_is_not_renewed_or_automatically_recreated(lab):
    snapshot = evidence(lab)
    receipt = admit(lab, snapshot)
    advance_clock(lab, 901)
    lab[0].queue.expire_requests()
    assert attempt(lab)["state"] == "FAILED"
    assert admit(lab, snapshot) == {**receipt, "replayed": True}
    with pytest.raises(QueueConflict):
        admit(lab)


@pytest.mark.parametrize("running", [False, True])
def test_retirement_cancels_only_unstarted_restoration(lab, running):
    admit(lab)
    if running:
        claim(lab)
    change(lab[1], "RETIRE")
    assert attempt(lab)["state"] == ("RUNNING" if running else "CANCELLED")
    if running:
        row = attempt(lab)
        assert lab[0].queue.finish_addition(row["job_id"], "synthetic-worker", AdditionResult(True, "management")) == "VERIFIED"
        assert not lab[1].snapshot()["entries"][0]["enabled"]


@pytest.mark.parametrize("running", [False, True])
def test_protection_has_atomic_priority_without_retiring_policy(lab, running):
    admit(lab)
    if running:
        claim(lab)
    policy = ProtectedPolicy(lab[0].store)
    policy.change("add", IP, policy.revision(), "protector", "Protector", ("Operator",))
    assert attempt(lab)["state"] == ("RUNNING" if running else "CANCELLED")
    assert lab[1].snapshot()["entries"][0]["enabled"]


def test_initial_legacy_protection_cancels_system_work_in_the_same_transaction(lab, monkeypatch):
    admit(lab)
    monkeypatch.setenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", str(IP))
    ProtectedPolicy(lab[0].store).migrate_legacy_environment()
    assert attempt(lab)["state"] == "CANCELLED"
    assert lab[1].snapshot()["entries"][0]["protected"]


def test_single_combined_removal_atomically_supersedes_queued_system_add(lab):
    admit(lab)
    cleanup = ManagedRemovals(lab[1], lab[0].queue)
    cleanup.initialize()
    revision = lab[1].snapshot()["revision"]
    receipt = cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                            "operator", "Operator", ("Operator",))
    assert not receipt["waiting_for_add"] and attempt(lab)["state"] == "CANCELLED"
    assert lab[0].queue.status()["counts"] == {"CANCELLED": 1, "QUEUED": 1}


def test_fleet_combined_removal_supersedes_system_add_in_one_transaction(lab):
    admit(lab)
    cleanup = ManagedFleetRemovals(lab[1], lab[0].queue)
    cleanup.initialize()
    scope = ManagedRemovalScopes(lab[0].store).snapshot(IP)
    canonical = {key: value for key, value in scope.items() if key not in {"scope_digest", "execution_available", "read_only"}}
    cleanup.admit(str(uuid4()), scope, canonical_managed_fleet_removal(canonical)[1], "operator", "Operator", ("Operator",))
    assert attempt(lab)["state"] == "CANCELLED"
    assert not lab[1].snapshot()["entries"][0]["enabled"]


def test_running_restoration_uses_ordered_cleanup_and_never_overlaps(lab):
    admit(lab)
    job = claim(lab)
    cleanup = ManagedRemovals(lab[1], lab[0].queue)
    cleanup.initialize()
    revision = lab[1].snapshot()["revision"]
    receipt = cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                            "operator", "Operator", ("Operator",))
    assert receipt["waiting_for_add"] and cleanup.advance("synthetic-worker") == 0
    lab[0].queue.finish_addition(job["id"], "synthetic-worker", "UNVERIFIED")
    assert cleanup.advance("synthetic-worker") == 1
    assert attempt(lab)["state"] == "UNVERIFIED" and not lab[1].snapshot()["entries"][0]["enabled"]


@pytest.mark.parametrize("running", [False, True])
def test_composite_recovery_retains_uncertainty_and_never_resumes_restoration(lab, running):
    admit(lab)
    if running:
        claim(lab)
    with lab[0].store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, lab[0].store, "suspend", "synthetic", now=lab[2][0])
    assert attempt(lab)["state"] == ("UNVERIFIED" if running else "CANCELLED")
    assert lab[1].snapshot()["restoration_suspended"]
    with lab[0].store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        apply_recovery_control(db, lab[0].store, "resume-mutations", "synthetic", now=lab[2][0])
    assert lab[1].snapshot()["restoration_suspended"]


def test_lost_lease_latches_attention_instead_of_replaying(lab):
    admit(lab)
    claim(lab)
    lab[2][0] += timedelta(seconds=136)
    assert lab[0].queue.claim_cycle("replacement-worker", 135)
    assert attempt(lab)["state"] == "UNVERIFIED"


def test_new_snapshot_after_verified_creation_requires_real_later_absence_and_backoff(lab):
    snapshot = evidence(lab)
    admit(lab, snapshot)
    job = claim(lab)
    lab[0].queue.finish_addition(job["id"], "synthetic-worker", AdditionResult(True, "management"))
    with lab[0].store._connection() as db:
        db.execute("UPDATE shun_state SET active=0")  # Synthetic complete later disappearance.
    with pytest.raises(QueueConflict, match="newer snapshot|backoff|predates"):
        admit(lab)
    advance_clock(lab)
    assert not admit(lab)["replayed"]


def test_churn_limit_bounds_a_reboot_like_repeated_disappearance(lab):
    for _ in range(3):
        admit(lab)
        job = claim(lab)
        lab[0].queue.finish_addition(job["id"], "synthetic-worker", AdditionResult(False, None))
        advance_clock(lab)
    with pytest.raises(QueueConflict, match="churn"):
        admit(lab)


@pytest.mark.parametrize("stage", ["admit", "claim", "retire", "protection", "finish"])
def test_audit_failure_rolls_back_every_domain_change(lab, monkeypatch, stage):
    if stage != "admit":
        admit(lab)
    if stage == "finish":
        job = claim(lab)
    before = fingerprint(lab)
    original = lab[0].store._insert_event

    def fail(db, event, *args, **kwargs):
        if event.startswith("MANAGED_SHUN_RESTORATION_"):
            raise sqlite3.OperationalError("Synthetic audit failure")
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(lab[0].store, "_insert_event", fail)
    # ProtectedPolicy owns another Store reference only through its queue, sharing
    # this same injected store instance.
    with pytest.raises(sqlite3.OperationalError):
        if stage == "admit":
            admit(lab)
        elif stage == "claim":
            claim(lab)
        elif stage == "retire":
            change(lab[1], "RETIRE")
        elif stage == "protection":
            policy = ProtectedPolicy(lab[0].store)
            policy.change("add", IP, policy.revision(), "protector", "Protector", ("Operator",))
        else:
            lab[0].queue.finish_addition(job["id"], "synthetic-worker", AdditionResult(True, "management"))
    assert fingerprint(lab) == before


def test_malformed_optional_state_fails_closed_without_initialization(lab):
    with lab[0].store._connection() as db:
        db.execute("DROP TABLE managed_restoration_attempts")
        db.execute("CREATE TABLE managed_restoration_attempts(id TEXT)")
    with pytest.raises(ManagedStateUnavailable):
        admit(lab)


@pytest.mark.parametrize("blocked", ["pause", "suspension", "device"])
def test_claim_rechecks_current_revocable_authority(lab, blocked):
    admit(lab)
    with lab[0].store._connection() as db:
        if blocked == "pause":
            db.execute("UPDATE operation_executor SET mutations_suspended=1")
        elif blocked == "suspension":
            db.execute("UPDATE managed_shun_registry SET restoration_suspended=1")
        else:
            db.execute("UPDATE devices SET enabled=0")
    assert claim(lab) is None
    assert attempt(lab)["state"] == ("QUEUED" if blocked == "pause" else "CANCELLED")


def test_system_source_does_not_bypass_independent_manual_work(lab):
    lab[0].queue.enqueue(str(uuid4()), [(1, IP)], "manual", "Manual", ("Operator",), source="manual_import",
                        scope="import", policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
    before = fingerprint(lab)
    with pytest.raises(QueueConflict, match="Independent work"):
        admit(lab)
    assert fingerprint(lab) == before


def test_pre_write_snapshot_cannot_recreate_a_newer_independent_add(lab):
    snapshot = evidence(lab)
    lab[0].queue.enqueue(str(uuid4()), [(1, IP)], "manual", "Manual", ("Operator",), source="manual_import",
                        scope="import", policy_revision=0, confirmation_digest=canonical_import([(1, IP)], 0)[2])
    job = lab[0].queue.claim_addition(1, "synthetic-worker", lab[0].queue.cutoff(), execution_enabled=True)
    lab[0].queue.finish_addition(job["id"], "synthetic-worker", AdditionResult(False, None))
    with pytest.raises(QueueConflict, match="predates"):
        admit(lab, snapshot)


@pytest.mark.parametrize("stage,seconds", [("admit", 136), ("admit", 121), ("claim", 136)])
def test_late_lease_or_evidence_expiry_rolls_back_without_dispatch(lab, monkeypatch, stage, seconds):
    if stage == "claim":
        admit(lab)
    before = fingerprint(lab)
    original = lab[0].store._insert_event

    def advance(db, event, *args, **kwargs):
        value = original(db, event, *args, **kwargs)
        if event == "MANAGED_SHUN_RESTORATION_" + ("QUEUED" if stage == "admit" else "RUNNING"):
            lab[2][0] += timedelta(seconds=seconds)
        return value
    monkeypatch.setattr(lab[0].store, "_insert_event", advance)
    with pytest.raises(QueueConflict, match="expired"):
        admit(lab) if stage == "admit" else claim(lab)
    assert fingerprint(lab) == before


def test_mutable_delegation_cannot_spoof_a_user_or_expand_the_system_source(lab):
    receipt = admit(lab)
    with lab[0].store._connection() as db:
        db.execute("UPDATE operation_requests SET actor_subject='forged',actor_roles_json='[\"Operator\"]' WHERE id=?", (receipt["operation_id"],))
    before = fingerprint(lab)
    with pytest.raises(ManagedStateUnavailable):
        claim(lab)
    assert fingerprint(lab) == before


def test_ledger_authority_keys_and_terminal_outcomes_are_retained_and_monotonic(lab):
    admit(lab)
    job = claim(lab)
    lab[0].queue.finish_addition(job["id"], "synthetic-worker", "UNVERIFIED")
    for sql in ("DELETE FROM managed_restoration_attempts", "UPDATE managed_restoration_attempts SET generation=2",
                "UPDATE managed_restoration_attempts SET state='QUEUED'", "UPDATE managed_restoration_attempts SET occurrence_id='forged'"):
        with pytest.raises(sqlite3.IntegrityError), lab[0].store._connection() as db:
            db.execute(sql)


def test_shared_pending_capacity_is_not_bypassed_by_system_authority(lab):
    with lab[0].store._connection() as db:
        db.executemany("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                       [(str(uuid4()), IPv4Address(int(IPv4Address('192.0.2.0')) + number).packed, lab[2][0].isoformat())
                        for number in range(1000)])
    before = fingerprint(lab)
    with pytest.raises(QueueFull):
        admit(lab)
    assert fingerprint(lab) == before


def test_late_combined_removal_failure_restores_policy_and_queued_restoration(lab, monkeypatch):
    admit(lab)
    cleanup = ManagedRemovals(lab[1], lab[0].queue)
    cleanup.initialize()
    before = fingerprint(lab)
    original = lab[0].store._insert_event

    def fail(db, event, *args, **kwargs):
        if event == "SHUN_REMOVE_REQUESTED":
            raise sqlite3.OperationalError("Synthetic late cleanup failure")
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(lab[0].store, "_insert_event", fail)
    revision = lab[1].snapshot()["revision"]
    with pytest.raises(sqlite3.OperationalError):
        cleanup.admit(str(uuid4()), 1, IP, revision, canonical_managed_removal(1, IP, revision)[1],
                      "operator", "Operator", ("Operator",))
    assert fingerprint(lab) == before
