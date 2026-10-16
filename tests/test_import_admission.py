"""Synthetic staging/admission/origin tests; no device, socket or credentials."""

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

from ftd_shun_manager.agent_protocol import AdditionResult, ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, QueueFull
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store
from ftd_shun_manager.synchronizer import Synchronizer
from ftd_shun_manager.web import Identity, templates

IP = IPv4Address("198.51.100.251")
OTHER = IPv4Address("198.51.100.252")


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    store.upsert_device(Device(1, "lab", IPv4Address("192.0.2.1"), True), "ssh-ed25519 AAAA")
    queue = OperationQueue(store)
    queue.initialize()
    clock = [datetime(2026, 10, 16, tzinfo=UTC)]
    monkeypatch.setattr(queue, "_now", lambda: clock[0])
    queue.test_clock = clock
    return queue


def admit(
    queue,
    *,
    key=None,
    subject="alice",
    roles=("Operator",),
    targets=None,
    label="Office test",
    reason="Fixture only",
    **changes,
):
    targets = targets or [(1, IP)]
    revision = ProtectedPolicy(queue.store).revision()
    digest = canonical_import(targets, revision, label, reason)[2]
    values = {
        "source": "manual_import",
        "scope": "import",
        "batch_label": label,
        "batch_reason": reason,
        "policy_revision": revision,
        "confirmation_digest": digest,
    }
    values.update(changes)
    return queue.enqueue(key or str(uuid4()), targets, subject, subject.title(), roles, **values)


def claim(queue):
    assert queue.claim_cycle("worker", 120)
    return queue.claim_addition(1, "worker", queue.cutoff(), execution_enabled=True)


def test_parallel_imports_share_job_keep_actors_and_never_enter_removal_dispatch(queue):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: admit(queue, subject=f"user-{i}"), range(6)))
    status = queue.status()
    assert status["counts"] == {"QUEUED": 1}
    assert status["items"][0]["action"] == "ADD"
    assert {r["source"] for r in status["items"][0]["requests"]} == {"manual_import"}
    assert status["progress"]["total_requests"] == 6
    assert not queue.has_pending(), "Held additions must not cause minute-spaced polling"
    assert queue.claim_cycle("worker", 120)
    assert queue.claim_removal(1, "worker", queue.cutoff()) is None
    assert queue.claim_addition(1, "worker", queue.cutoff()) is None
    with (
        queue.store._connection() as db,
        pytest.raises(sqlite3.IntegrityError, match="explicit addition claimant"),
    ):
        db.execute(
            "UPDATE operation_jobs SET state='RUNNING' WHERE id=?", (status["items"][0]["id"],)
        )
    job = queue.claim_addition(1, "worker", queue.cutoff(), execution_enabled=True)
    with pytest.raises(QueueConflict):
        queue.finish_removal(job["id"], "worker", "VERIFIED")
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    origins = queue.store.list_active_shuns()[0].manual_imports
    assert len(origins) == 1
    assert queue.store.list_active_shuns()[0].manual_import_count == 6
    with queue.store._connection() as db:
        assert {row[0] for row in db.execute("SELECT batch_id FROM shun_import_origins")} == {
            r["operation_id"] for r in results
        }
    assert len(queue.store.list_events(IP)) == 6 * 5


@pytest.mark.parametrize("first_add", [True, False])
def test_opposite_intentions_reject_entire_batch_without_partial_audit(queue, first_add, capsys):
    if first_add:
        admit(queue)
    else:
        queue.enqueue(str(uuid4()), [(1, IP)], "bob", "Bob", ("Operator",))
    before = queue.store.list_events()
    capsys.readouterr()
    with pytest.raises(QueueConflict, match="Opposite"):
        if first_add:
            queue.enqueue(str(uuid4()), [(1, OTHER), (1, IP)], "bob", "Bob", ("Operator",))
        else:
            admit(queue, targets=[(1, OTHER), (1, IP)])
    assert queue.store.list_events() == before
    assert len(queue.status()["items"]) == 1
    assert capsys.readouterr().out == ""


def test_confirmation_idempotency_scope_actor_and_expiry_are_immutable(queue):
    key = str(uuid4())
    admit(queue, key=key)
    assert admit(queue, key=key)["replayed"]
    for changes in [{"subject": "bob"}, {"label": "Changed"}, {"targets": [(1, OTHER)]}]:
        with pytest.raises(QueueConflict):
            admit(queue, key=key, **changes)
    with pytest.raises(ValueError, match="confirmation"):
        admit(queue, confirmation_digest="0" * 64)
    with pytest.raises(PermissionError):
        admit(queue, roles=("Viewer",))
    with pytest.raises(PermissionError):
        admit(queue, subject=" ")
    queue.test_clock[0] += timedelta(minutes=16)
    queue.expire_requests()
    assert queue.status()["counts"] == {"FAILED": 1}
    assert admit(queue, key=key)["replayed"], "Retry cannot renew an expired authorization"
    assert queue.status()["counts"] == {"FAILED": 1}


def test_policy_revision_admission_and_policy_change_cancel_only_matching_targets(queue):
    policy = ProtectedPolicy(queue.store)
    with pytest.raises(QueueConflict, match="changed"):
        admit(
            queue,
            policy_revision=policy.revision() + 1,
            confirmation_digest=canonical_import(
                [(1, IP)], policy.revision() + 1, "Office test", "Fixture only"
            )[2],
        )
    admit(queue, targets=[(1, IP), (1, OTHER)])
    policy.change("add", IP, policy.revision(), "admin", "Admin", ("Administrator",))
    assert queue.status()["counts"] == {"FAILED": 1, "QUEUED": 1}
    with pytest.raises(QueueConflict, match="Protected IP"):
        admit(queue)
    # Policy removal must no longer be blocked by a staged conflicting ADD.
    queue.enqueue(
        str(uuid4()), [(1, IP)], "system:trusted-ip-policy", "Policy", (), source="trusted_policy"
    )
    assert any(item["action"] == "REMOVE" for item in queue.status()["items"])


@pytest.mark.parametrize("result", [AdditionResult(False), "UNVERIFIED", "FAILED"])
def test_noop_uncertainty_or_failure_never_assign_origin_from_later_presence(queue, result):
    admit(queue)
    job = claim(queue)
    queue.finish_addition(job["id"], "worker", result)
    assert queue.store.list_active_shuns() == []
    queue.store.reconcile_snapshot(1, [(IP, "management")])
    queue.reconcile_unknown(1, {IP})
    assert queue.store.list_active_shuns()[0].manual_imports == ()
    assert queue.status()["counts"] == {"NOOP" if result == AdditionResult(False) else result: 1}


def test_verified_origin_survives_polling_restart_not_reappearance_or_retry(queue):
    key = str(uuid4())
    admit(queue, key=key, label="<script>label</script>")
    job = claim(queue)
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    first = queue.store.list_active_shuns()[0]
    queue.store.reconcile_snapshot(1, [(IP, "management")])
    queue.store.initialize()
    queue.initialize()
    assert queue.store.list_active_shuns()[0].manual_imports == first.manual_imports
    queue.store.reconcile_snapshot(1, [])
    queue.store.reconcile_snapshot(1, [(IP, "management")])
    assert queue.store.list_active_shuns()[0].manual_imports == ()
    assert queue.store.list_active_shuns()[0].first_seen_at == first.first_seen_at
    assert admit(queue, key=key, label="<script>label</script>")["replayed"]
    assert queue.status()["counts"] == {"VERIFIED": 1}
    assert (
        len([e for e in queue.store.list_events(IP) if e["event_type"] == "SHUN_ADDED_BY_IMPORT"])
        == 1
    )


def test_legacy_reactivation_cannot_inherit_origin_and_legacy_claim_cannot_replay_add(queue):
    admit(queue)
    job = claim(queue)
    queue.defer_addition(job["id"], "worker")
    with queue.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE operation_jobs SET state='RUNNING' WHERE id=?", (job["id"],))
    job = queue.claim_addition(1, "worker", queue.cutoff(), execution_enabled=True)
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    with queue.store._connection() as db:
        old = db.execute("SELECT occurrence_id FROM shun_state").fetchone()[0]
        db.execute("UPDATE shun_state SET active=0")
        db.execute("UPDATE shun_state SET active=1")  # Old writer knows no new column.
        assert db.execute("SELECT occurrence_id FROM shun_state").fetchone()[0] != old
    assert queue.store.list_active_shuns()[0].manual_imports == ()


def test_conflicting_local_occurrence_and_invalid_results_fail_closed(queue):
    admit(queue)
    job = claim(queue)
    for bad in [
        AdditionResult(True),
        AdditionResult(False, "management"),
        AdditionResult(True, "bad;name"),
        "VERIFIED",
    ]:
        with pytest.raises(ValueError):
            queue.finish_addition(job["id"], "worker", bad)
    queue.store.record_observed_shun(1, IP, "management")
    before = queue.store.list_active_shuns()[0]
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    assert queue.status()["counts"] == {"UNVERIFIED": 1}
    assert queue.store.list_active_shuns()[0] == before


def test_later_import_noop_keeps_original_origin_and_metadata_cannot_be_rewritten(queue):
    admit(queue)
    job = claim(queue)
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    before = queue.store.list_active_shuns()[0].manual_imports
    admit(queue, subject="bob", label="Second request")
    second = queue.claim_addition(1, "worker", queue.cutoff(), execution_enabled=True)
    queue.finish_addition(second["id"], "worker", AdditionResult(False))
    assert queue.store.list_active_shuns()[0].manual_imports == before
    for statement in [
        "UPDATE manual_import_batches SET actor_subject='forged'",
        "UPDATE shun_import_origins SET occurrence_id='forged'",
    ]:
        with (
            queue.store._connection() as db,
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
        ):
            db.execute(statement)


def test_expired_worker_cannot_commit_or_replay_add_from_later_snapshot(queue):
    admit(queue)
    job = claim(queue)
    queue.test_clock[0] += timedelta(seconds=121)
    with pytest.raises(QueueConflict, match="lease lost"):
        queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    assert queue.claim_cycle("replacement", 120)
    assert queue.status()["counts"] == {"UNVERIFIED": 1}
    assert queue.claim_addition(1, "replacement", queue.cutoff(), execution_enabled=True) is None
    queue.store.reconcile_snapshot(1, [(IP, "management")])
    queue.reconcile_unknown(1, {IP})
    assert queue.store.list_active_shuns()[0].manual_imports == ()
    assert queue.status()["counts"] == {"UNVERIFIED": 1}


def test_ordinary_scheduler_observes_but_never_executes_held_add(queue, monkeypatch):
    class ReadOnlyAgent:
        reads = 0

        def list_shuns(self, device):
            self.reads += 1
            return [ObservedShun(IP, "management")]

        def remove_shun(self, *args):
            pytest.fail("Staged ADD reached ordinary removal dispatch")

    async def immediate(function, *args):
        return function(*args)

    agent = ReadOnlyAgent()
    synchronizer = Synchronizer(queue.store, agent, 300, 60)
    monkeypatch.setattr(synchronizer.queue, "_now", queue._now)
    monkeypatch.setattr(asyncio, "to_thread", immediate)
    admit(queue)
    asyncio.run(synchronizer._sweep())
    assert agent.reads == 1
    assert synchronizer.status()["last_error"] is None
    assert queue.status()["counts"] == {"QUEUED": 1}
    assert queue.store.list_active_shuns()[0].manual_imports == ()
    assert not queue.has_pending()


def test_staging_gate_is_strict_default_off(monkeypatch):
    monkeypatch.delenv("FTD_SHUN_IMPORT_ADMISSION_ENABLED", raising=False)
    assert Settings.from_environment().import_admission_enabled is False
    monkeypatch.setenv("FTD_SHUN_IMPORT_ADMISSION_ENABLED", "true")
    assert Settings.from_environment().import_admission_enabled is True
    monkeypatch.setenv("FTD_SHUN_IMPORT_ADMISSION_ENABLED", "1")
    with pytest.raises(ValueError, match="true or false"):
        Settings.from_environment()


def test_bulk_origins_decode_batch_once_and_bound_metadata_per_occurrence(queue, monkeypatch):
    targets = [(1, IPv4Address(int(IP) + index)) for index in range(1000)]
    key = admit(queue, targets=targets)["operation_id"]
    # Synthetic verified rows only: no live admission, sender or device write.
    with queue.store._connection() as db:
        for index, (_, ip) in enumerate(targets):
            occurrence = f"fixture-{index}"
            db.execute(
                """INSERT INTO shun_state VALUES (1,?,'management',1,?,?,?,?)""",
                (ip.packed, "first", "last", "changed", occurrence),
            )
            db.execute(
                """INSERT INTO shun_import_origins VALUES (?, ?,1,?,'management',?,?)""",
                (key, f"job-{index}", ip.packed, occurrence, "verified"),
            )
    original = json.loads
    decoded_batches = []

    def decode(value, *args, **kwargs):
        if '"scope":"import"' in value:
            decoded_batches.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", decode)
    rows = queue.store.list_active_shuns()
    assert len(rows) == 1000
    assert all(row.manual_import_count == 1 and len(row.manual_imports) == 1 for row in rows)
    assert len(decoded_batches) == 1
    decoded_batches.clear()
    status = queue.status()
    assert len(status["items"]) == 100
    assert all(item["requests"][0]["target_count"] == 1000 for item in status["items"])
    assert status["progress"]["requests"][0]["total"] == 1000
    assert decoded_batches == [], "Status must not copy full batch payload per job/actor"


def test_retention_keeps_active_origin_after_queue_pruning_then_expires_inactive_origin(queue):
    admit(queue)
    job = claim(queue)
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    queue.test_clock[0] += timedelta(days=367)
    queue.store.prune_expired_history(366, queue._now())
    queue.prune_completed(366)
    assert queue.status()["counts"] == {}
    assert len(queue.store.list_active_shuns()[0].manual_imports) == 1
    queue.store.reconcile_snapshot(1, [])
    result = queue.store.prune_expired_history(366, queue._now())
    assert result["import_origins_deleted"] == 1
    queue.prune_completed(366)
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM manual_import_batches").fetchone()[0] == 0


def test_whole_batch_capacity_rate_and_target_validation(queue):
    with pytest.raises(ValueError):
        canonical_import([(1, IP)] * 2, 0)
    with pytest.raises(ValueError):
        canonical_import([(1, IPv4Address(i + 1)) for i in range(1001)], 0)
    with pytest.raises(ValueError):
        admit(queue, targets=[(1, IP), (2, OTHER)])
    assert queue.status()["counts"] == {}
    for i in range(10):
        admit(queue, targets=[(1, IPv4Address(i + 1))])
    with pytest.raises(QueueFull):
        admit(queue)


def test_origin_rendering_is_current_only_and_escaped(queue):
    admit(queue, label="<img src=x onerror=alert(1)>", reason="<script>reason</script>")
    job = claim(queue)
    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
    shun = queue.store.list_active_shuns()[0]
    # BFF receives canonical strings, not the Python IPv4 DTO.
    value = {**shun.__dict__, "ip": str(shun.ip)}
    context = {
        "identity": Identity("viewer", "Viewer", ("Viewer",)),
        "refresh": None,
        "ip": str(IP),
        "csrf_token": "fixture",
        "shuns": [value],
        "events": [],
        "is_trusted_policy_ip": False,
        "is_disabled_policy_ip": False,
    }
    html = templates.get_template("detail.html").render(**context)
    assert "Manually imported" in html and "Import provenance" in html
    assert "<img" not in html and "<script>reason" not in html
    assert "&lt;img" in html and "&lt;script&gt;reason" in html
    value["manual_imports"] = []
    assert "Manually imported" not in templates.get_template("detail.html").render(**context)


def test_private_api_admission_is_gated_typed_role_bound_and_never_dispatches(queue, monkeypatch):
    class NoAgent:
        def list_shuns(self, *args):
            raise AssertionError("Admission must not issue a read")

        def remove_shun(self, *args):
            raise AssertionError("ADD must never reach removal dispatch")

        def open_cycle(self, *args):
            raise AssertionError("Admission must not issue a cycle")

    async def scenario():
        config = replace(
            Settings.from_environment(),
            database_path=queue.store.path,
            device_inventory_path=None,
            agent_mode="mock",
            import_admission_enabled=False,
        )
        for enabled in [False, True]:
            app = create_app(
                replace(config, import_admission_enabled=enabled),
                store=queue.store,
                agent_client=NoAgent(),
            )
            monkeypatch.setattr(
                app.state.synchronizer,
                "signal_work",
                lambda: pytest.fail("No scheduling from staged admission"),
            )
            revision = ProtectedPolicy(queue.store).revision()
            digest = canonical_import([(1, IP)], revision, "", "Fixture")[2]
            body = {
                "actor": {"subject": "alice", "display_name": "Alice", "roles": ["Operator"]},
                "targets": [{"device_id": 1, "ip": str(IP)}],
                "policy_revision": revision,
                "confirmation_digest": digest,
                "reason": "Fixture",
            }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://internal"
            ) as client:
                headers = {"Idempotency-Key": str(uuid4())}
                response = await client.post("/api/v1/imports", json=body, headers=headers)
                assert response.status_code == (202 if enabled else 503)
                if enabled:
                    assert response.json()["execution_enabled"] is False
                    assert (
                        await client.post("/api/v1/imports", json=body, headers=headers)
                    ).json()["replayed"]
                    assert (await client.post("/api/v1/imports", json=body)).status_code == 422
                    assert (
                        await client.post(
                            "/api/v1/imports", json={**body, "raw_text": "shun..."}, headers=headers
                        )
                    ).status_code == 422
                    viewer = {**body, "actor": {**body["actor"], "roles": ["Viewer"]}}
                    assert (
                        await client.post("/api/v1/imports", json=viewer, headers=headers)
                    ).status_code == 403
                    assert (await client.get("/api/v1/shuns")).json() == []
                    status = (await client.get("/api/v1/status")).json()
                    assert status["import_execution_enabled"] is False
                    assert status["queue"]["items"][0]["action"] == "ADD"
                    job = claim(queue)  # Synthetic domain completion, never HTTP/agent dispatch.
                    queue.finish_addition(job["id"], "worker", AdditionResult(True, "management"))
                    rows = (await client.get("/api/v1/shuns")).json()
                    assert rows[0]["manual_import_count"] == 1
                    assert rows[0]["manual_imports"][0]["source"] == "manual_import"
                    assert rows[0]["manual_imports"][0]["reason"] == "Fixture"

    asyncio.run(scenario())


def test_additive_queue_migration_preserves_legacy_jobs_and_nine_column_request_writes(queue):
    store = Store(queue.store.path.with_name("legacy.db"))
    store.initialize()
    store.upsert_device(Device(1, "legacy", IPv4Address("192.0.2.2"), True), "ssh-ed25519 AAAA")
    with store._connection() as db:
        db.executescript("""
            CREATE TABLE operation_requests (
                id TEXT PRIMARY KEY,actor_subject TEXT NOT NULL,actor_display_name TEXT NOT NULL,
                actor_roles_json TEXT NOT NULL,source TEXT NOT NULL,payload_json TEXT NOT NULL,
                requested_at TEXT NOT NULL,expires_at TEXT NOT NULL,state TEXT NOT NULL);
            CREATE TABLE operation_jobs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,device_id INTEGER NOT NULL,
                ip BLOB NOT NULL,state TEXT NOT NULL,requested_at TEXT NOT NULL,started_at TEXT,completed_at TEXT,reason TEXT);
            CREATE TABLE operation_links (
                request_id TEXT NOT NULL REFERENCES operation_requests(id) ON DELETE CASCADE,
                job_id TEXT NOT NULL REFERENCES operation_jobs(id) ON DELETE CASCADE,
                PRIMARY KEY(request_id,job_id));
        """)
        for index, state in enumerate(["QUEUED", "RUNNING", "VERIFIED"]):
            key = f"legacy-{index}"
            db.execute(
                "INSERT INTO operation_requests VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    "alice",
                    "Alice",
                    '["Operator"]',
                    "manual",
                    json.dumps({"scope": "device", "targets": [[1, str(IP)]]}),
                    "2026-10-16T00:00:00Z",
                    "2026-10-16T00:15:00Z",
                    "ACTIVE",
                ),
            )
            db.execute(
                "INSERT INTO operation_jobs(id,device_id,ip,state,requested_at) VALUES (?,1,?,?,?)",
                (key, IPv4Address(int(IP) + index).packed, state, "2026-10-16T00:00:00Z"),
            )
            db.execute("INSERT INTO operation_links VALUES (?,?)", (key, key))
        before = [tuple(row) for row in db.execute("SELECT * FROM operation_jobs ORDER BY seq")]
    migrated = OperationQueue(store)
    migrated.initialize()
    migrated.initialize()
    with store._connection() as db:
        rows = db.execute("SELECT * FROM operation_jobs ORDER BY seq").fetchall()
        assert [tuple(row)[:9] for row in rows] == before
        assert all(row["action"] == "REMOVE" and row["dispatch_kind"] is None for row in rows)
        assert len(db.execute("PRAGMA table_info(operation_requests)").fetchall()) == 9
        db.execute(
            "INSERT INTO operation_requests VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "old-writer",
                "bob",
                "Bob",
                '["Operator"]',
                "manual",
                "{}",
                "2026-10-16T00:00:00Z",
                "2026-10-16T00:15:00Z",
                "ACTIVE",
            ),
        )
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_old_state_migration_preserves_dates_and_backfills_occurrence_once(tmp_path):
    path = tmp_path / "old-state.db"
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE devices(id INTEGER PRIMARY KEY,hostname TEXT UNIQUE,management_ip BLOB UNIQUE,
            ssh_host_key TEXT,enabled INTEGER);
            CREATE TABLE shun_state(device_id INTEGER,ip BLOB,interface TEXT,active INTEGER,
            first_seen_at TEXT,last_seen_at TEXT,last_changed_at TEXT,PRIMARY KEY(device_id,ip,interface));""")
        db.execute(
            "INSERT INTO devices VALUES (1,'old',?,'ssh-ed25519 AAAA',1)",
            (IPv4Address("192.0.2.1").packed,),
        )
        db.execute(
            "INSERT INTO shun_state VALUES (1,?,'management',1,?,?,?)",
            (IP.packed, "first", "last", "changed"),
        )
    store = Store(path)
    store.initialize()
    with store._connection() as db:
        occurrence = db.execute("SELECT occurrence_id FROM shun_state").fetchone()[0]
    store.initialize()
    with store._connection() as db:
        row = db.execute("SELECT * FROM shun_state").fetchone()
        assert row["occurrence_id"] == occurrence and occurrence
        assert (row["first_seen_at"], row["last_seen_at"], row["last_changed_at"]) == (
            "first",
            "last",
            "changed",
        )
    assert store.list_active_shuns()[0].manual_imports == ()
