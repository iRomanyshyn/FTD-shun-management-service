"""Cancellation is local revocation, with real shared-queue synthetic settlement."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_managed_imports import confirm, dump, grant, stage
from test_managed_imports import lab as import_lab

from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_cancellations import ImportCancellations, held
from ftd_shun_manager.managed_restoration import CompleteSnapshot, ManagedRestorations
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

IP = IPv4Address("198.51.100.1")
OWNER = "synthetic-cancellation-worker"
lab = import_lab


@pytest.fixture
def controls(lab, monkeypatch):
    imports, clock = lab
    monkeypatch.setattr(OperationQueue, "_now", lambda self: clock[0])
    return ImportCancellations(imports.store, clock=lambda: clock[0])


def request(controls, operation_id, **changes):
    review = controls.review(operation_id, "alice", ("Operator",))
    args = {"import_id": operation_id, "reviewed_at": review["reviewed_at"], "review_digest": review["review_digest"],
            "accepted_count": review["accepted_count"], "subject": "alice", "display_name": "Alice", "roles": ("Operator",)}
    args.update(changes)
    return controls.cancel(**args), args


def report(controls, operation_id):
    return controls.page(operation_id, "alice", ("Operator",))


def pending(lab, *, running=False):
    imports, clock = lab
    queue = OperationQueue(imports.store)
    with imports.store._connection() as db:
        db.execute("UPDATE managed_shun_registry SET restoration_suspended=0")  # Disposable state only.
    assert queue.claim_cycle(OWNER, 135)
    clock[0] += timedelta(seconds=1)
    source = ManagedRestorations(imports.store, queue)
    snapshot = CompleteSnapshot(str(uuid4()), 1, clock[0], clock[0], frozenset())
    receipt = source.admit_absence(snapshot, IP, OWNER, enabled=True)
    assert receipt
    job = queue.claim_addition(1, OWNER, queue.cutoff(), execution_enabled=True, managed_restoration_enabled=True) if running else None
    return queue, receipt, job


def test_constructor_and_explicit_schema_do_not_initialize_prerequisites(controls, tmp_path):
    store = Store(tmp_path / "empty.db")
    ImportCancellations(store)
    assert not store.path.exists()
    store.initialize()
    before = dump(store)
    with pytest.raises(ManagedStateUnavailable):
        ImportCancellations(store).initialize()
    assert dump(store) == before
    before = dump(controls.store)
    controls.initialize()
    assert dump(controls.store) == before


def test_mixed_scope_keeps_adopted_existing_and_excluded_protection(lab, controls):
    imports, _ = lab
    grant(imports.registry, [(1, IPv4Address("198.51.100.2"))])
    imports.store.record_observed_shun(1, IPv4Address("198.51.100.3"), "management")
    ProtectedPolicy(imports.store).change("add", IPv4Address("198.51.100.4"), 0, "protector", "Protector", ())
    result = confirm(lab, stage(lab, "198.51.100.1\n198.51.100.2\n198.51.100.3\n198.51.100.4\ninvalid"))
    original = imports.page(result["operation_id"], "alice")
    outcome, args = request(controls, result["operation_id"])
    assert outcome["counts"] == {"STOPPED_UNSENT": 1, "RETAINED_EXISTING": 1, "RETAINED_ADOPTED": 1}
    assert outcome["device_removal_requested"] is False and not outcome["device_work_admitted"]
    assert report(controls, result["operation_id"])["settled"]
    entries = imports.registry.snapshot()["entries"]
    assert {row["ip"]: row["enabled"] for row in entries} == {str(IP): False, "198.51.100.2": True, "198.51.100.3": True}
    with imports.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs").fetchall()
        assert db.execute("SELECT COUNT(*) FROM shun_state WHERE active=1").fetchone()[0] == 1
    assert imports.page(result["operation_id"], "alice") == original
    before = dump(imports.store)
    assert controls.cancel(**args) == {**outcome, "replayed": True}
    assert dump(imports.store) == before


def test_queued_add_cancelled_atomically_without_dispatch(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, _ = pending(lab)
    request(controls, operation_id)
    with controls.store._connection() as db:
        assert db.execute("SELECT state FROM managed_restoration_attempts").fetchone()[0] == "CANCELLED"
        assert db.execute("SELECT state FROM operation_jobs").fetchone()[0] == "CANCELLED"
    assert queue.claim_addition(1, OWNER, queue.cutoff(), execution_enabled=True, managed_restoration_enabled=True) is None
    assert report(controls, operation_id)["counts"] == {"STOPPED_UNSENT": 1}


@pytest.mark.parametrize("outcome,expected,enabled,attention", [
    (AdditionResult(True, "management"), "RETAINED_APPLIED", True, False),
    (AdditionResult(False, None), "RETAINED_APPLIED", True, False),
    ("FAILED", "STOPPED_FAILED", False, True),
    ("UNVERIFIED", "STOPPED_UNVERIFIED", False, True),
])
def test_running_settlement_same_transaction_no_interrupt_or_replay(lab, controls, outcome, expected, enabled, attention):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    initial, args = request(controls, operation_id)
    assert initial["counts"] == {"WAITING_OUTCOME": 1}
    assert not report(controls, operation_id)["settled"]
    with controls.store._connection() as db:
        attempt = db.execute("SELECT * FROM managed_restoration_attempts").fetchone()
        assert attempt["state"] == "RUNNING" and held(db, attempt)
        assert db.execute("SELECT enabled FROM managed_shun_targets").fetchone()[0] == 1
    queue.finish_addition(job["id"], OWNER, outcome)
    current = report(controls, operation_id)
    assert current["settled"] and current["counts"] == {expected: 1} and current["attention_count"] == int(attention)
    assert controls.cancel(**args) == {**initial, "replayed": True}  # Initial receipt is not live progress.
    assert lab[0].registry.snapshot()["entries"][0]["enabled"] is enabled
    with controls.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='REMOVE'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM managed_restoration_attempts").fetchone()[0] == 1


def test_exact_prewrite_deferral_stops_without_resending(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    request(controls, operation_id)
    queue.defer_addition(job["id"], OWNER)
    assert report(controls, operation_id)["counts"] == {"STOPPED_UNSENT": 1}
    with controls.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs").fetchone()[0] == "CANCELLED"
        assert db.execute("SELECT state FROM managed_restoration_attempts").fetchone()[0] == "CANCELLED"


def test_restart_lost_lease_keeps_uncertainty_and_retires_uncompleted_policy(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    _, _, job = pending(lab, running=True)
    request(controls, operation_id)
    lab[1][0] += timedelta(seconds=136)
    queue = OperationQueue(Store(controls.store.path))
    assert queue.claim_cycle("replacement-worker", 135)
    assert report(controls, operation_id)["counts"] == {"STOPPED_UNVERIFIED": 1}
    assert not lab[0].registry.snapshot()["entries"][0]["enabled"]
    with controls.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "UNVERIFIED"


@pytest.mark.parametrize("prior", ["VERIFIED", "NOOP", "FAILED", "UNVERIFIED"])
def test_already_settled_work_uses_retained_outcomes_not_cached_presence(lab, controls, prior):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    queue.finish_addition(job["id"], OWNER, AdditionResult(True, "management") if prior == "VERIFIED" else
                          AdditionResult(False, None) if prior == "NOOP" else prior)
    outcome, _ = request(controls, operation_id)
    expected = "RETAINED_APPLIED" if prior in {"VERIFIED", "NOOP"} else "STOPPED_" + prior
    assert outcome["counts"] == {expected: 1}
    assert lab[0].registry.snapshot()["entries"][0]["enabled"] == (prior in {"VERIFIED", "NOOP"})


def test_observation_alone_never_claims_service_application(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    controls.store.record_observed_shun(1, IP, "management")
    request(controls, operation_id)
    assert report(controls, operation_id)["counts"] == {"STOPPED_UNSENT": 1}
    with controls.store._connection() as db:
        assert db.execute("SELECT active FROM shun_state").fetchone()[0] == 1


def test_protection_during_running_add_cannot_be_reenabled(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    request(controls, operation_id)
    ProtectedPolicy(controls.store).change("add", IP, 0, "protector", "Protector", (),
                                           managed_revision=lab[0].registry.snapshot()["revision"])
    queue.finish_addition(job["id"], OWNER, AdditionResult(True, "management"))
    assert report(controls, operation_id)["counts"] == {"ALREADY_STOPPED": 1}
    assert not lab[0].registry.snapshot()["entries"][0]["enabled"]


def test_newer_generation_and_original_retry_never_touched(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    grant(lab[0].registry, [(1, IP)], action="RETIRE")
    grant(lab[0].registry, [(1, IP)])
    outcome, args = request(controls, operation_id)
    assert outcome["counts"] == {"SUPERSEDED": 1}
    lab[1][0] += timedelta(days=1)
    before = dump(controls.store)
    assert controls.cancel(**args)["replayed"]
    assert dump(controls.store) == before
    assert lab[0].registry.snapshot()["entries"][0]["generation"] == 2


@pytest.mark.parametrize("change", ["expired", "backwards", "revision", "protection", "outcome", "count", "digest"])
def test_whole_scope_changed_or_expired_review_has_no_partial_effect(lab, controls, change):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True) if change == "outcome" else (None, None, None)
    review = controls.review(operation_id, "alice", ("Operator",))
    if change == "expired":
        lab[1][0] += timedelta(minutes=5)
    elif change == "backwards":
        lab[1][0] -= timedelta(seconds=1)
    elif change == "revision":
        grant(lab[0].registry, [(1, IPv4Address("198.51.100.2"))])
    elif change == "protection":
        ProtectedPolicy(controls.store).change("add", IPv4Address("198.51.100.2"), 0, "protector", "Protector", ())
    elif change == "outcome":
        queue.finish_addition(job["id"], OWNER, AdditionResult(True, "management"))
    before = dump(controls.store)
    with pytest.raises(ManagedConflict):
        controls.cancel(operation_id, review["reviewed_at"], "0" * 64 if change == "digest" else review["review_digest"],
                        2 if change == "count" else 1, "alice", "Alice", ("Operator",))
    assert dump(controls.store) == before


@pytest.mark.parametrize("subject,roles,allowed", [
    ("alice", ("Operator",), True), ("alice", ("Viewer",), False), ("other", ("Operator",), False),
    ("other", ("Administrator",), True), ("", ("Administrator",), False),
])
def test_current_owner_or_admin_authority_required(lab, controls, subject, roles, allowed):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    before = dump(controls.store)
    if allowed:
        review = controls.review(operation_id, subject, roles)
        controls.cancel(operation_id, review["reviewed_at"], review["review_digest"], 1, subject, "Current actor", roles)
        with controls.store._connection() as db:
            row = db.execute("SELECT * FROM import_cancellation_decisions").fetchone()
            assert row["actor_subject"] == subject and json.loads(row["actor_roles_json"]) == list(roles)
    else:
        with pytest.raises((PermissionError, ValueError)):
            controls.review(operation_id, subject, roles)
        assert dump(controls.store) == before


def test_late_audit_failure_rolls_back_retirement_queued_job_and_decision(lab, controls, monkeypatch):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    pending(lab)
    original = controls.store._insert_event

    def fail(db, event_type, *args, **kwargs):
        if event_type == "MANAGED_IMPORT_CANCELLATION_REQUESTED":
            raise RuntimeError("synthetic audit failure")
        return original(db, event_type, *args, **kwargs)

    monkeypatch.setattr(controls.store, "_insert_event", fail)
    before = dump(controls.store)
    with pytest.raises(RuntimeError, match="synthetic"):
        request(controls, operation_id)
    assert dump(controls.store) == before


def test_late_settlement_audit_failure_rolls_back_original_queue_outcome(lab, controls, monkeypatch):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    request(controls, operation_id)
    original = controls.store._insert_event

    def fail(db, event_type, *args, **kwargs):
        if event_type == "MANAGED_IMPORT_CANCELLATION_SETTLED":
            raise RuntimeError("synthetic settlement failure")
        return original(db, event_type, *args, **kwargs)

    monkeypatch.setattr(controls.store, "_insert_event", fail)
    before = dump(controls.store)
    with pytest.raises(RuntimeError):
        queue.finish_addition(job["id"], OWNER, AdditionResult(True, "management"))
    assert dump(controls.store) == before


def test_retention_preserves_captured_terminal_evidence_if_old_writer_missed_hook(lab, controls, monkeypatch):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    request(controls, operation_id)
    monkeypatch.setattr("ftd_shun_manager.import_cancellations.settle_result", lambda *args: None)
    queue.finish_addition(job["id"], OWNER, "FAILED")  # Simulates unsupported old writer; never recommended rollback.
    lab[1][0] += timedelta(days=367)
    queue.prune_completed(366)
    with controls.store._connection() as db:
        assert db.execute("SELECT state FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "FAILED"
        assert db.execute("SELECT COUNT(*) FROM operation_links WHERE job_id=?", (job["id"],)).fetchone()[0] == 1
    assert not report(controls, operation_id)["settled"]


def test_partial_schema_never_repaired_and_pruning_refuses(lab, controls):
    with controls.store._connection() as db:
        db.execute("DROP TRIGGER import_cancellation_target_retained")
    before = dump(controls.store)
    with pytest.raises(ManagedStateUnavailable):
        controls.initialize()
    with pytest.raises(ManagedStateUnavailable):
        OperationQueue(controls.store).prune_completed(366)
    assert dump(controls.store) == before


def test_cancellation_controls_required_for_new_confirmation_not_old_replay(lab, controls):
    plan = stage(lab)
    result = confirm(lab, plan)
    next_plan = stage(lab, "198.51.100.2")
    with controls.store._connection() as db:
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'import_cancellation_*'").fetchall():
            db.execute(f'DROP TRIGGER "{name}"')
        db.execute("DROP TABLE import_cancellation_targets")
        db.execute("DROP TABLE import_cancellation_decisions")
    before = dump(controls.store)
    assert confirm(lab, plan, request_id=result["operation_id"])["replayed"]
    with pytest.raises(ManagedStateUnavailable, match="cancellation"):
        confirm(lab, next_plan)
    assert dump(controls.store) == before


def test_private_api_cancellation_with_admission_off_and_strict_models(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    settings = replace(Settings.from_environment(), database_path=controls.store.path, device_inventory_path=None,
                       agent_mode="disabled", managed_policy_admission_enabled=False)
    app = create_app(settings, controls.store, DisabledAgentClient())
    actor = {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
            body = {"actor": actor, "operation_id": operation_id}
            review = await client.post("/api/v1/managed-imports/cancellation-review", json=body)
            assert review.status_code == 200
            values = review.json()
            confirmation = {**body, **{key: values[key] for key in ("reviewed_at", "review_digest", "accepted_count")}}
            invalid = await client.post("/api/v1/managed-imports/cancel-confirmed", json={**confirmation, "action": "REMOVE"})
            assert invalid.status_code == 422
            response = await client.post("/api/v1/managed-imports/cancel-confirmed", json=confirmation)
            assert response.status_code == 200 and not response.json()["device_removal_requested"]
            assert "no-store" in response.headers["cache-control"]
            replay = await client.post("/api/v1/managed-imports/cancel-confirmed", json=confirmation)
            assert replay.json()["replayed"]
            status = await client.post("/api/v1/managed-imports/cancellation", json=body)
            assert status.json()["counts"] == {"STOPPED_UNSENT": 1}
            denied = await client.post("/api/v1/managed-imports/cancellation", json={**body, "actor": {**actor, "subject": "other"}})
            assert denied.status_code == 403

    asyncio.run(run())


def test_concurrent_same_review_has_one_decision_and_one_retirement(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    review = controls.review(operation_id, "alice", ("Operator",))

    def cancel():
        return controls.cancel(operation_id, review["reviewed_at"], review["review_digest"], 1, "alice", "Alice", ("Operator",))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: cancel(), range(2)))
    assert sorted(item["replayed"] for item in outcomes) == [False, True]
    with controls.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM import_cancellation_decisions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='MANAGED_SHUN_RETIRED'").fetchone()[0] == 1


def test_success_evidence_survives_queue_pruning_and_draft_expiry(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    queue, _, job = pending(lab, running=True)
    queue.finish_addition(job["id"], OWNER, AdditionResult(True, "management"))
    lab[1][0] += timedelta(days=367)
    queue.prune_completed(366)
    lab[0].preparations.prune_expired()
    with controls.store._connection() as db:
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()
        assert db.execute("SELECT state FROM managed_restoration_attempts").fetchone()[0] == "VERIFIED"
    assert request(controls, operation_id)[0]["counts"] == {"RETAINED_APPLIED": 1}


def test_current_1000_pair_cancellation_is_one_decision_with_bounded_pages(lab, controls):
    base = int(IPv4Address("198.51.96.0"))
    text = "\n".join(str(IPv4Address(base + index)) for index in range(1000))
    operation_id = confirm(lab, stage(lab, text))["operation_id"]
    assert request(controls, operation_id)[0]["counts"] == {"STOPPED_UNSENT": 1000}
    for page in (1, 10):
        result = controls.page(operation_id, "alice", ("Operator",), page=page)
        assert len(result["targets"]) == 100 and result["pages"] == 10
    assert not any(row["enabled"] for row in lab[0].registry.snapshot()["entries"])
    with controls.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_shun_requests").fetchone()[0] == 1
        assert db.execute("SELECT revision FROM managed_shun_registry").fetchone()[0] == 2
        assert not db.execute("SELECT 1 FROM operation_jobs").fetchall()


def test_cancel_does_not_need_another_policy_ledger_slot(lab, controls, monkeypatch):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    monkeypatch.setattr("ftd_shun_manager.managed_shuns.MAX_MANAGED_REQUESTS", 1)
    assert request(controls, operation_id)[0]["counts"] == {"STOPPED_UNSENT": 1}


@pytest.mark.parametrize("statement", [
    "UPDATE import_cancellation_decisions SET actor_subject='other'",
    "DELETE FROM import_cancellation_decisions",
    "UPDATE import_cancellation_targets SET generation=2",
    "UPDATE import_cancellation_targets SET state='WAITING_OUTCOME'",
    "DELETE FROM import_cancellation_targets",
])
def test_decision_identity_and_settled_rows_are_immutable(lab, controls, statement):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    request(controls, operation_id)
    before = dump(controls.store)
    with pytest.raises(sqlite3.IntegrityError), controls.store._connection() as db:
        db.execute(statement)
    assert dump(controls.store) == before


def test_malformed_missing_predecessor_refuses_pruning(lab, controls):
    operation_id = confirm(lab, stage(lab))["operation_id"]
    pending(lab, running=True)
    request(controls, operation_id)
    with controls.store._connection() as db:
        triggers = [row[0] for row in db.execute("""SELECT sql FROM sqlite_master WHERE name IN
            ('import_cancellation_identity_immutable','import_cancellation_target_monotonic') ORDER BY name""")]
        db.execute("DROP TRIGGER import_cancellation_identity_immutable")
        db.execute("DROP TRIGGER import_cancellation_target_monotonic")
        db.execute("UPDATE import_cancellation_targets SET job_id=?", (str(uuid4()),))
        for trigger in triggers:
            db.execute(trigger)
    before = dump(controls.store)
    with pytest.raises(ManagedStateUnavailable):
        OperationQueue(controls.store).prune_completed(366)
    assert dump(controls.store) == before


def test_outer_schema_transaction_can_roll_back_without_effective_policy_changes(lab, controls):
    with controls.store._connection() as db:
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'import_cancellation_*'").fetchall():
            db.execute(f'DROP TRIGGER "{name}"')
        db.execute("DROP TABLE import_cancellation_targets")
        db.execute("DROP TABLE import_cancellation_decisions")
    before = dump(controls.store)
    with pytest.raises(RuntimeError), controls.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        controls.initialize(connection=db)
        raise RuntimeError("synthetic migration rollback")
    assert dump(controls.store) == before
