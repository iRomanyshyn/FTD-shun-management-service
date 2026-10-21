"""Prepared policy confirmation on disposable state; no live device work."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from ftd_shun_manager.agent_client import DisabledAgentClient
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_cancellations import ImportCancellations
from ftd_shun_manager.managed_imports import ManagedImports
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_restoration import ManagedRestorations
from ftd_shun_manager.managed_safety import ManagedStateUnavailable
from ftd_shun_manager.managed_shuns import ManagedCapacity, ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def lab(tmp_path, monkeypatch):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    queue = OperationQueue(store)
    queue.initialize()
    for device in (1, 2):
        store.upsert_device(Device(device, f"synthetic-{device}", IPv4Address(f"192.0.2.{device}"), True), "ssh-ed25519 AAAA")
    registry = ManagedShuns(store)
    registry.initialize()
    ManagedRestorations(store, queue).initialize()
    clock = [datetime(2026, 10, 21, 12, tzinfo=UTC)]
    monkeypatch.setattr("ftd_shun_manager.managed_shuns.now", lambda: clock[0].isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    imports = ManagedImports(store, clock=lambda: clock[0])
    imports.preparations.initialize()
    imports.initialize()
    ImportCancellations(store).initialize()
    return imports, clock


def stage(lab, text="198.51.100.1", *, devices=None, subject="alice"):
    return lab[0].preparations.create(text, devices or [1], subject, "Preparation author", ("Viewer",), label="<b>Private</b>")


def confirm(lab, plan, **changes):
    header = lab[0].preparations.page(plan["plan_id"], "alice")
    values = {"request_id": str(uuid4()), "preparation_id": plan["plan_id"], "digest": plan["digest"],
              "accepted_count": header["target_count"] - header["classification_counts"]["EXCLUDED_PROTECTED"],
              "subject": "alice", "display_name": "Current author", "roles": ("Operator",), "maintain_present": True,
              "enabled": True, "addition_device_ids": frozenset({1, 2})}
    values.update(changes)
    return lab[0].confirm(**values)


def dump(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def grant(registry, pairs, *, action="MAINTAIN"):
    with registry.store._connection() as db:
        revision = db.execute("SELECT revision FROM managed_shun_registry WHERE id=1").fetchone()[0]
        protected = db.execute("SELECT revision FROM protected_policy WHERE id=1").fetchone()[0]
    return registry.change(str(uuid4()), action, pairs, revision, protected,
                           canonical_managed_change(action, pairs, revision, protected)[2], "creator", "Creator", ("Operator",))


def test_constructor_optional_reads_and_explicit_migration_are_non_authoritative(lab, tmp_path):
    store = Store(tmp_path / "base.db")
    ManagedImports(store)
    assert not store.path.exists()
    store.initialize()
    imports = ManagedImports(store)
    before = dump(store)
    assert imports.list_for_owner("alice") == {"initialized": False, "read_only": True, "items": []}
    with pytest.raises(ManagedStateUnavailable):
        imports.initialize()
    assert dump(store) == before
    imports, _ = lab
    before = dump(imports.store)
    imports.initialize()
    assert dump(imports.store) == before
    assert imports.list_for_owner("alice")["items"] == []


def test_mixed_scope_atomic_adoption_exclusions_and_no_device_provenance(lab):
    imports, _ = lab
    pairs = [(1, IPv4Address("198.51.100.10"))]
    grant(imports.registry, pairs)
    old = imports.registry.snapshot()["entries"][0]
    imports.store.record_observed_shun(1, IPv4Address("198.51.100.11"), "management")
    ProtectedPolicy(imports.store).change("add", IPv4Address("198.51.100.13"), 0, "protector", "Protector", ())
    plan = stage(lab, """# private-comment
prefix-private 198.51.100.10 suffix-private
198.51.100.11
198.51.100.12
198.51.100.13
198.51.100.12 # private-comment
555.555.555.666
""", devices=[2, 1])
    with imports.store._connection() as db:
        independent = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in (
            "shun_state", "manual_import_batches", "operation_jobs", "operation_requests", "operation_links")}
    result = confirm(lab, plan)
    assert result["source"] == "prepared_managed_import" and result["policy_only"]
    assert not result["device_work_admitted"] and not result["replayed"]
    assert result["accepted_pairs"] == 6 and result["changed_targets"] == 5
    assert result["adopted_pairs"] == 1 and result["proposed_adds"] == 4 and result["already_managed_pairs"] == 1
    assert result["excluded_protected_pairs"] == 2
    assert result["source_counts"] == {"Ready": 4, "Duplicate": 1, "Invalid": 1}
    page = imports.page(result["operation_id"], "alice")
    assert page["historical_confirmation"] and page["read_only"] and len(page["targets"]) == 8
    assert page["header"]["actor_roles"] == ["Viewer"]
    assert page["result"]["confirmation_actor"] == {"subject": "alice", "display_name": "Current author", "roles": ["Operator"]}
    for member in page["targets"]:
        if member["classification"] == "EXCLUDED_PROTECTED":
            assert member["intent_id"] is None
        elif member["classification"] == "ALREADY_MANAGED":
            assert member["intent_id"] == old["intent_id"] and member["authorization_request_id"] == old["authorization_request_id"]
        else:
            assert member["generation"] == 1 and member["authorization_request_id"] == result["operation_id"]
    with imports.store._connection() as db:
        assert {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in independent} == independent
        authority = db.execute("SELECT * FROM managed_shun_requests WHERE id=?", (result["operation_id"],)).fetchone()
        assert json.loads(authority["actor_roles_json"]) == ["Operator"]
        assert authority["actor_display_name"] == "Current author"
        assert len(db.execute("SELECT 1 FROM shun_events WHERE event_type='MANAGED_SHUN_ADOPTED'").fetchall()) == 1
        serialized = "\n".join(line for line in db.iterdump() if "confirmed_import_" in line)
        assert serialized
        assert all(value not in serialized for value in ("private-comment", "prefix-private", "suffix-private"))


def test_receipt_outlives_pruned_draft_restart_retirement_and_new_generation(lab):
    imports, clock = lab
    plan = stage(lab)
    result = confirm(lab, plan)
    original = imports.page(result["operation_id"], "alice")
    pair = [(1, IPv4Address("198.51.100.1"))]
    grant(imports.registry, pair, action="RETIRE")
    grant(imports.registry, pair)
    clock[0] += timedelta(minutes=11)
    assert imports.preparations.prune_expired() == 1
    restarted = ManagedImports(Store(imports.store.path), clock=lambda: clock[0])
    before = dump(imports.store)
    assert restarted.page(result["operation_id"], "alice") == original
    assert restarted.list_for_owner("alice")["items"][0]["id"] == result["operation_id"]
    replay = restarted.confirm(result["operation_id"], plan["plan_id"], plan["digest"], 1, "alice", "Changed name",
                               ("Administrator",), enabled=True, maintain_present=True)
    assert replay == {**result, "replayed": True}
    assert restarted.registry.snapshot()["entries"][0]["generation"] == 2
    assert dump(imports.store) == before


@pytest.mark.parametrize("change", ["expired", "cancelled", "clock_backwards", "protected", "managed", "device", "presence"])
def test_changed_whole_scope_never_silently_rebases(lab, change):
    imports, clock = lab
    plan = stage(lab)
    if change == "expired":
        clock[0] += timedelta(minutes=10)
    elif change == "cancelled":
        imports.preparations.cancel(plan["plan_id"], "alice")
    elif change == "clock_backwards":
        clock[0] -= timedelta(seconds=1)
    elif change == "protected":
        ProtectedPolicy(imports.store).change("add", IPv4Address("198.51.100.1"), 0, "protector", "Protector", ())
    elif change == "managed":
        grant(imports.registry, [(1, IPv4Address("198.51.100.2"))])
    elif change == "device":
        imports.store.upsert_device(Device(1, "renamed", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    else:
        imports.store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    before = dump(imports.store)
    with pytest.raises(ManagedConflict):
        confirm(lab, plan)
    assert dump(imports.store) == before


def test_lost_adoption_observation_conflicts_but_heartbeat_does_not(lab):
    imports, _ = lab
    ip = IPv4Address("198.51.100.1")
    imports.store.record_observed_shun(1, ip, "management")
    plan = stage(lab)
    imports.store.reconcile_snapshot(1, [])
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="membership"):
        confirm(lab, plan)
    assert dump(imports.store) == before
    imports.store.record_observed_shun(1, ip, "management")
    imports.store.record_observed_shun(1, ip, "management")
    assert confirm(lab, plan)["adopted_pairs"] == 1


@pytest.mark.parametrize("changes,exception", [
    ({"enabled": False}, PermissionError), ({"enabled": "true"}, ValueError),
    ({"maintain_present": False}, ValueError), ({"maintain_present": 1}, ValueError),
    ({"roles": ("Viewer",)}, PermissionError), ({"accepted_count": True}, ValueError),
    ({"accepted_count": 2}, ManagedConflict), ({"addition_device_ids": frozenset()}, ManagedConflict),
    ({"addition_device_ids": frozenset({True})}, ValueError), ({"digest": "f" * 64}, ValueError),
    ({"subject": "bob"}, ValueError),
])
def test_confirmation_requires_current_authority_exact_count_and_capability(lab, changes, exception):
    plan = stage(lab)
    before = dump(lab[0].store)
    with pytest.raises(exception):
        confirm(lab, plan, **changes)
    assert dump(lab[0].store) == before


def test_no_pending_work_uncertainty_or_late_audit_failure_is_cleared(lab, monkeypatch):
    imports, _ = lab
    plan = stage(lab)
    original = imports.store._insert_event
    def fail(db, event, *args, **kwargs):
        if event == "MANAGED_IMPORT_CONFIRMED":
            raise RuntimeError("Synthetic late receipt audit failure")
        return original(db, event, *args, **kwargs)
    monkeypatch.setattr(imports.store, "_insert_event", fail)
    before = dump(imports.store)
    with pytest.raises(RuntimeError, match="Synthetic late"):
        confirm(lab, plan)
    assert dump(imports.store) == before
    monkeypatch.setattr(imports.store, "_insert_event", original)
    with imports.store._connection() as db:
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,?,?,'UNVERIFIED',?,'ADD')",
                   (str(uuid4()), 1, IPv4Address("198.51.100.1").packed, "2026-10-21T11:59:00Z"))
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="uncertain"):
        confirm(lab, plan)
    assert dump(imports.store) == before


def test_expiry_during_transaction_rolls_policy_receipt_and_audit_back(lab):
    imports, clock = lab
    plan = stage(lab)
    moments = iter((clock[0], clock[0] + timedelta(minutes=10)))
    imports.clock = lambda: next(moments)
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="during confirmation"):
        confirm(lab, plan)
    assert dump(imports.store) == before


def test_two_confirmations_of_one_plan_require_original_operation_key(lab):
    imports, _ = lab
    plan = stage(lab)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(lab, plan, request_id=key), range(2)))
    assert sorted(result["replayed"] for result in results) == [False, True]
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="already confirmed"):
        confirm(lab, plan)
    with pytest.raises(ManagedConflict, match="different confirmed"):
        confirm(lab, plan, request_id=key, accepted_count=2)
    with pytest.raises(ValueError, match="operation key"):
        confirm(lab, plan, request_id=plan["plan_id"])
    assert dump(imports.store) == before
    assert imports.list_for_owner("bob")["items"] == []
    with pytest.raises(ManagedConflict, match="unavailable"):
        imports.page(key, "bob")


def test_confirmed_report_is_retained_immutable_and_detects_corruption(lab):
    imports, _ = lab
    result = confirm(lab, stage(lab))
    with imports.store._connection() as db:
        for table in ("confirmed_import_receipts", "confirmed_import_members"):
            for sql in (f"UPDATE {table} SET actor_subject='bad'" if table.endswith("receipts") else f"UPDATE {table} SET generation=99",
                        f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="immutable|retained"):
                    db.execute(sql)
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='confirmed_import_member_immutable'").fetchone()[0]
        db.execute("DROP TRIGGER confirmed_import_member_immutable")
        db.execute("UPDATE confirmed_import_members SET intent_id=?", (str(uuid4()),))
        db.execute(trigger)
    before = dump(imports.store)
    with pytest.raises(ManagedStateUnavailable, match="integrity"):
        imports.page(result["operation_id"], "alice")
    assert dump(imports.store) == before


def test_old_plan_without_registry_never_becomes_confirmable_after_initialization(lab, tmp_path):
    store = Store(tmp_path / "uninitialized.db")
    store.initialize()
    OperationQueue(store).initialize()
    store.upsert_device(Device(1, "synthetic", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    imports = ManagedImports(store)
    imports.preparations.initialize()
    plan = imports.preparations.create("198.51.100.1", [1], "alice", "Alice", ("Operator",))
    imports.registry.initialize()
    ManagedRestorations(store, OperationQueue(store)).initialize()
    imports.initialize()
    ImportCancellations(store).initialize()
    before = dump(store)
    with pytest.raises(ManagedStateUnavailable, match="already initialized"):
        confirm((imports, None), plan)
    assert dump(store) == before


def test_maximum_current_capacity_is_atomic_paged_and_larger_scope_is_not_split(lab):
    imports, clock = lab
    text = "\n".join(str(IPv4Address(0xC6120000 + index)) for index in range(1001))
    oversized = stage(lab, text)
    before = dump(imports.store)
    with pytest.raises(ManagedCapacity, match="nothing was split"):
        confirm(lab, oversized, accepted_count=1000)
    assert dump(imports.store) == before
    plan = stage(lab, "\n".join(text.splitlines()[:1000]))
    result = confirm(lab, plan)
    assert result["accepted_pairs"] == result["changed_targets"] == 1000
    assert imports.registry.page()["total"] == 1000
    pages = [imports.page(result["operation_id"], "alice", page=page) for page in range(1, 11)]
    assert all(len(page["targets"]) == 100 and page["pages"] == 10 for page in pages)
    assert len({target["ip"] for page in pages for target in page["targets"]}) == 1000
    clock[0] += timedelta(minutes=11)
    assert imports.preparations.prune_expired() == 2
    assert imports.page(result["operation_id"], "alice", page=10) == pages[-1]


def test_receipt_capacity_and_revocation_reserve_never_evict_or_partially_grant(lab, monkeypatch):
    imports, _ = lab
    monkeypatch.setattr("ftd_shun_manager.managed_imports.MAX_RECEIPTS", 1)
    confirm(lab, stage(lab))
    plan = stage(lab, "198.51.100.2")
    before = dump(imports.store)
    with pytest.raises(ManagedCapacity, match="journal is full"):
        confirm(lab, plan)
    assert dump(imports.store) == before
    monkeypatch.setattr("ftd_shun_manager.managed_imports.MAX_RECEIPTS", 128)
    monkeypatch.setattr("ftd_shun_manager.managed_shuns.MAX_MANAGED_REQUESTS", 1001)
    before = dump(imports.store)
    with pytest.raises(ManagedCapacity, match="retirement only"):
        confirm(lab, plan)
    assert dump(imports.store) == before


def test_existing_request_key_cannot_gain_import_meaning_and_old_grants_cannot_adopt(lab):
    imports, _ = lab
    result = grant(imports.registry, [(1, IPv4Address("198.51.100.2"))])
    plan = stage(lab)
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="reinterpreted"):
        confirm(lab, plan, request_id=result["operation_id"])
    assert dump(imports.store) == before
    imports.store.record_observed_shun(1, IPv4Address("198.51.100.3"), "management")
    before = dump(imports.store)
    with pytest.raises(ManagedConflict, match="adoption"):
        grant(imports.registry, [(1, IPv4Address("198.51.100.3"))])
    assert dump(imports.store) == before


def test_partial_receipt_schema_is_not_repaired_and_reads_do_not_initialize(lab):
    imports, _ = lab
    with imports.store._connection() as db:
        db.execute("DROP TRIGGER confirmed_import_member_retained")
    before = dump(imports.store)
    for operation in (imports.initialize, lambda: imports.list_for_owner("alice")):
        with pytest.raises(ManagedStateUnavailable, match="partial"):
            operation()
    assert dump(imports.store) == before


def test_receipt_initialization_is_atomic_with_outer_transaction(lab, tmp_path):
    store = Store(tmp_path / "outer-rollback.db")
    store.initialize()
    queue = OperationQueue(store)
    queue.initialize()
    ManagedShuns(store).initialize()
    ManagedRestorations(store, queue).initialize()
    imports = ManagedImports(store)
    before = dump(store)
    with pytest.raises(RuntimeError), store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        imports.initialize(connection=db)
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='confirmed_import_receipts'").fetchone()
        raise RuntimeError("Synthetic outer rollback")
    assert dump(store) == before


def test_canonical_adoption_remains_compatible_with_exact_managed_maintenance(lab):
    from ftd_shun_manager.managed_maintenance import _initialize, recognized_schema, review

    imports, clock = lab
    with imports.store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _initialize(db, imports.store)  # Disposable full legacy schema only.
    imports.store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    confirm(lab, stage(lab))
    before = dump(imports.store)
    with imports.store._connection() as db:
        db.execute("BEGIN")
        assert recognized_schema(db) is False  # No optional closure ledger.
        result = review(db, "resume-policy", now=clock[0] + timedelta(seconds=1))
        assert len(result["targets"]) == 1 and result["targets"][0]["ip"] == "198.51.100.1"
    assert dump(imports.store) == before


def test_already_managed_only_preserves_author_and_is_not_adopted(lab):
    imports, _ = lab
    grant(imports.registry, [(1, IPv4Address("198.51.100.1"))])
    before = imports.registry.snapshot()["entries"]
    result = confirm(lab, stage(lab))
    assert result["changed_targets"] == result["adopted_pairs"] == result["proposed_adds"] == 0
    assert result["already_managed_pairs"] == 1
    assert imports.registry.snapshot()["entries"] == before


def test_protection_permanently_retires_import_and_replay_never_reenables(lab):
    imports, _ = lab
    plan = stage(lab)
    result = confirm(lab, plan)
    policy = ProtectedPolicy(imports.store)
    ip = IPv4Address("198.51.100.1")
    policy.change("add", ip, 0, "protector", "Protector", ("Viewer",), managed_revision=1)
    assert not imports.registry.snapshot()["entries"][0]["enabled"]
    policy.change("delete", ip, 1, "protector", "Protector", ("Viewer",), managed_revision=2)
    before = dump(imports.store)
    assert confirm(lab, plan, request_id=result["operation_id"])["replayed"]
    assert dump(imports.store) == before
    assert not imports.registry.snapshot()["entries"][0]["enabled"]


@pytest.fixture
def private_api(lab, tmp_path, monkeypatch):
    imports, clock = lab
    clock[0] = datetime.now(UTC)
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    inventory = tmp_path / "synthetic.json"
    inventory.write_text(json.dumps([{"id": device, "hostname": f"synthetic-{device}", "management_ip": f"192.0.2.{device}",
        "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"],
        "addition_profile": "fpr1010-766-single-vf-management-v1"} for device in (1, 2)]))
    settings = replace(Settings.from_environment(), database_path=imports.store.path, device_inventory_path=inventory,
                       agent_mode="socket", development_auth=False, managed_policy_admission_enabled=True)
    app = create_app(settings, imports.store, DisabledAgentClient())
    return imports, app, settings


ACTOR = {"subject": "alice", "display_name": "Current author", "roles": ["Operator"]}


async def post(client, path, body, *, key=None):
    return await client.post("/api/v1/managed-imports/" + path, json=body,
                             headers={"Idempotency-Key": key or str(uuid4())})


def test_private_api_full_flow_recovery_and_disabled_admission_report_reads(private_api):
    imports, app, settings = private_api
    imports.store.record_observed_shun(1, IPv4Address("198.51.100.1"), "management")
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            plan = await post(client, "prepare", {"actor": ACTOR, "device_ids": [1], "text": "198.51.100.1\n555.555.555.666"})
            assert plan.status_code == 200 and plan.headers["cache-control"] == "no-store"
            value = plan.json()
            body = {"actor": ACTOR, "preparation_id": value["plan_id"], "preparation_digest": value["digest"],
                    "accepted_count": 1, "maintain_present": True}
            key = str(uuid4())
            before_jobs = app.state.synchronizer.queue.status()["counts"]
            first = await post(client, "confirm", body, key=key)
            assert first.status_code == 200 and first.json()["adopted_pairs"] == 1
            assert (await post(client, "confirm", body, key=key)).json() == {**first.json(), "replayed": True}
            assert app.state.synchronizer.queue.status()["counts"] == before_jobs
            assert (await post(client, "preparations", ACTOR)).json()["plans"][0]["plan_id"] == value["plan_id"]
            page = await post(client, "preparation", {"actor": ACTOR, "preparation_id": value["plan_id"]})
            assert page.status_code == 200 and not page.json()["can_execute"]
            assert page.json()["state"] == "CONFIRMED" and page.json()["confirmed_operation_id"] == key
            before = dump(imports.store)
            cancellation = await post(client, "cancel-preparation", {"actor": ACTOR, "preparation_id": value["plan_id"]})
            assert cancellation.status_code == 409 and "already confirmed" in cancellation.text
            assert dump(imports.store) == before
            assert (await post(client, "receipt", {"actor": {**ACTOR, "subject": "bob"}, "operation_id": key})).status_code == 409
            disabled = create_app(replace(settings, managed_policy_admission_enabled=False), imports.store, DisabledAgentClient())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled), base_url="http://internal") as client:
            before = dump(imports.store)
            assert (await post(client, "confirm", body, key=key)).status_code == 503
            assert (await post(client, "receipts", ACTOR)).json()["items"][0]["id"] == key
            report = await post(client, "receipt", {"actor": ACTOR, "operation_id": key})
            assert report.status_code == 200 and report.json()["historical_confirmation"]
            assert dump(imports.store) == before
    asyncio.run(scenario())


@pytest.mark.parametrize("changes", [{"enabled": True}, {"targets": []}, {"action": "ADD"},
                                    {"accepted_count": True}, {"maintain_present": "true"}, {"maintain_present": False}])
def test_private_api_rejects_unreviewed_fields_and_coerced_consent(private_api, changes):
    imports, app, _ = private_api
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            plan = (await post(client, "prepare", {"actor": ACTOR, "device_ids": [1], "text": "198.51.100.1"})).json()
            body = {"actor": ACTOR, "preparation_id": plan["plan_id"], "preparation_digest": plan["digest"],
                    "accepted_count": 1, "maintain_present": True, **changes}
            before = dump(imports.store)
            response = await post(client, "confirm", body)
            assert response.status_code == 422 and dump(imports.store) == before
    asyncio.run(scenario())


def test_private_api_startup_and_disabled_confirmation_never_initialize_optional_tables(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "base-only.db")
    settings = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                       agent_mode="disabled", managed_policy_admission_enabled=False)
    app = create_app(settings, store)
    before = dump(store)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            for path in ("preparations", "receipts"):
                response = await post(client, path, ACTOR)
                assert response.status_code == 200 and response.json()["initialized"] is False
            body = {"actor": ACTOR, "preparation_id": str(uuid4()), "preparation_digest": "0" * 64,
                    "accepted_count": 1, "maintain_present": True}
            assert (await post(client, "confirm", body)).status_code == 503
            assert (await post(client, "prepare", {"actor": {**ACTOR, "roles": ["Viewer"]}, "text": "198.51.100.1", "device_ids": [1]})).status_code == 403
            assert (await client.get("/api/v1/managed-imports/confirm")).status_code == 405
    asyncio.run(scenario())
    assert dump(store) == before
