"""Non-executable attention reports use disposable SQLite only."""

import json
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import managed_maintenance as maintenance
from ftd_shun_manager.managed_attention import attention_report
from ftd_shun_manager.managed_intent import canonical_managed_change, canonical_managed_fleet_scope
from ftd_shun_manager.operation_queue import OperationQueue, stamp
from ftd_shun_manager.store import Device, Store

IP = IPv4Address("198.51.100.251")
NOW = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "synthetic.db")
    store.initialize()
    OperationQueue(store).initialize()
    store.upsert_device(Device(1, "synthetic-1", IPv4Address("192.0.2.1"), True), "ssh-ed25519 PRIVATE_HOSTKEY_MARKER")
    return store


def report(store, **kwargs):
    with store._connection() as db:
        db.execute("BEGIN")
        return attention_report(db, **kwargs)


def fingerprint(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def initialize(store):
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        maintenance._initialize(db, store)


def job(store, *, ip=IP, state="UNVERIFIED", action="ADD", when=NOW, key=None):
    key = key or str(uuid4())
    with store._connection() as db:
        db.execute("""INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,completed_at,action,reason)
            VALUES (?,1,?,?,?,?,?,'PRIVATE_RAW_ERROR')""", (key, ip.packed, state, stamp(when), stamp(when), action))
    return key


def authority(store, *, ip=IP, enabled=True, generation=1):
    request, intent = str(uuid4()), str(uuid4())
    payload = canonical_managed_change("MAINTAIN", [(1, ip)], 0, 0, "PRIVATE_LABEL", "PRIVATE_COMMENT")[1]
    with store._connection() as db:
        db.execute("INSERT INTO managed_shun_requests VALUES (?,'alice','Alice','[\"Operator\"]',?,'{}',?)",
                   (request, payload, stamp(NOW)))
        db.execute("INSERT INTO managed_shun_targets VALUES (?,?,?,?,?,1,?,?,?,?)",
                   (1, ip.packed, intent, generation, int(enabled), request, stamp(NOW), stamp(NOW), None if enabled else stamp(NOW)))
    return request, intent


def attempt(store, request, intent, *, state="UNVERIFIED", job_id=None, ip=IP, generation=1):
    key, job_id = str(uuid4()), job_id or str(uuid4())
    with store._connection() as db:
        db.execute("""INSERT INTO managed_restoration_attempts VALUES (?,?,1,?,?,?, ?,1,?,?,?,?,?, ?,NULL,NULL)""",
                   (key, job_id, ip.packed, intent, generation, request, str(uuid4()), stamp(NOW), stamp(NOW), stamp(NOW), state, stamp(NOW)))
    return key


def fleet(store, *, devices=1, state="ATTENTION", phase="ADMITTED", malformed=False):
    scope = {"ip": str(IP), "managed_initialized": True, "managed_revision": 0, "protected_revision": 0,
             "protected": False, "targets": [{"device_id": device, "hostname": f"synthetic-{device}", "device_enabled": True,
                 "observed_present": True, "maintenance_enabled": False, "intent_id": None, "generation": None}
                for device in range(1, devices + 1)]}
    payload = "PRIVATE_MALFORMED_PAYLOAD" if malformed else canonical_managed_fleet_scope(scope)[0]
    key = str(uuid4())
    with store._connection() as db:
        db.execute("INSERT INTO managed_fleet_removals VALUES (?,NULL,'alice','Alice','[]',?,'{}',?,?,?)",
                   (key, payload, stamp(NOW), stamp(NOW + timedelta(minutes=10)), phase))
        if state:
            db.execute("INSERT INTO managed_fleet_waits VALUES (?,?,'[]',?,'PRIVATE_RAW_ERROR')", (key, devices, state))
    return key


def test_absent_optional_state_is_honest_and_inspection_never_initializes_it(store):
    before = fingerprint(store)
    result = report(store)
    assert not result["managed_initialized"] and result["read_only"] and not result["resolution_available"]
    assert result["restoration_suspended"] is None and result["pending_managed"] is None
    assert result["counts"] == {"operation": 0, "restoration": None, "device_cleanup": None, "fleet_cleanup": None}
    assert result["items"] == [] and result["retained_case_count"] == 0
    assert fingerprint(store) == before


@pytest.mark.parametrize("action", ["ADD", "REMOVE"])
def test_ordinary_uncertainty_is_visible_without_optional_state_and_no_private_output(store, action):
    key = job(store, action=action)
    store.record_observed_shun(1, IP, "management")
    before = fingerprint(store)
    result = report(store)
    assert result["retained_case_count"] == 1
    item = result["items"][0]
    assert item["case_id"] == f"operation:{key}" and item["action"] == action
    assert item["related_job"]["state"] == "retained" and item["related_job"]["retained_request_count"] == 0
    assert item["target"]["maintenance"] == "not_initialized"
    assert item["target"]["cached_present"] and item["target"]["observation_basis"] == "cached_not_write_verification"
    assert "PRIVATE" not in json.dumps(result)
    assert fingerprint(store) == before


@pytest.mark.parametrize("job_state", ["UNVERIFIED", "FAILED", None])
def test_restoration_latch_survives_missing_job_and_is_not_double_counted(store, job_state):
    initialize(store)
    request, intent = authority(store, enabled=False)
    key = job(store, state=job_state) if job_state else None
    case = attempt(store, request, intent, state=job_state or "UNVERIFIED", job_id=key)
    before = fingerprint(store)
    result = report(store)
    assert result["retained_case_count"] == 1 and result["counts"]["operation"] == 0
    item = result["items"][0]
    assert item["case_id"] == f"restoration:{case}" and item["pair_latch_retained"]
    assert item["target"]["maintenance"] == "retired"
    assert item["related_job"]["state"] == ("retained" if job_state else "not_retained")
    assert "PRIVATE" not in json.dumps(result)
    assert fingerprint(store) == before


def test_new_generation_or_observed_absence_does_not_disguise_historical_latch(store):
    initialize(store)
    request, intent = authority(store, generation=2)
    attempt(store, request, str(uuid4()), generation=1)
    result = report(store)["items"][0]
    assert result["generation"] == 1 and result["target"]["current_generation"] == 2
    assert result["target"]["current_intent_id"] == intent
    assert not result["target"]["cached_present"] and result["pair_latch_retained"]
    assert not result["resolution_available"]


def test_inconsistent_restoration_job_does_not_hide_different_uncertain_work(store):
    initialize(store)
    request, intent = authority(store)
    key = job(store, action="REMOVE")
    attempt(store, request, intent, job_id=key)
    result = report(store)
    assert result["counts"]["operation"] == result["counts"]["restoration"] == 1
    item = next(item for item in result["items"] if item["kind"] == "restoration")
    assert item["related_job"]["state"] == "inconsistent"


def test_inconsistent_outcome_is_not_labelled_verified_or_hidden(store):
    initialize(store)
    request, intent = authority(store)
    key = job(store, state="UNVERIFIED")
    attempt(store, request, intent, state="FAILED", job_id=key)
    result = report(store)
    assert result["retained_case_count"] == 1
    assert result["items"][0]["related_job"]["state"] == "inconsistent"


def test_single_cleanup_keeps_predecessor_uncertainty_separate_and_displays_context(store):
    initialize(store)
    request, intent = authority(store, enabled=False)
    predecessor = job(store)
    key = str(uuid4())
    with store._connection() as db:
        db.execute("""INSERT INTO managed_removal_handoffs VALUES (?,1,?,?,1,?,?,'alice','Alice','[]',
            '{}','{}',?,?,'ATTENTION','PRIVATE_RAW_ERROR')""",
                   (key, IP.packed, intent, request, predecessor, stamp(NOW), stamp(NOW + timedelta(minutes=10))))
        db.execute("INSERT INTO protected_ips VALUES (?,'PRIVATE_LABEL','PRIVATE_COMMENT',1,?)", (IP.packed, stamp(NOW)))
    result = report(store)
    assert result["retained_case_count"] == 2
    item = next(item for item in result["items"] if item["kind"] == "device_cleanup")
    assert item["related_job"]["outcome"] == "UNVERIFIED" and item["target"]["protected"]
    assert item["target"]["maintenance"] == "retired" and "PRIVATE" not in json.dumps(result)


def test_large_fleet_scope_has_exact_count_but_only_five_targets(store):
    initialize(store)
    fleet(store, devices=1000)
    before = fingerprint(store)
    result = report(store)
    item = result["items"][0]
    assert item["kind"] == "fleet_cleanup" and item["scope_state"] == "retained"
    assert item["target_count"] == 1000 and item["targets_truncated"] and len(item["targets"]) == 5
    assert item["targets"][0]["hostname"] == "synthetic-1"
    assert item["targets"][1]["device_enabled"] is None
    assert "PRIVATE" not in json.dumps(result) and fingerprint(store) == before


def test_malformed_fleet_evidence_is_unknown_not_zero_targets_or_raw_payload(store):
    initialize(store)
    fleet(store, malformed=True)
    item = report(store)["items"][0]
    assert item["scope_state"] == "inconsistent" and item["target_count"] is None
    assert item["targets_truncated"] is None and "PRIVATE" not in json.dumps(item)


def test_pending_work_is_separate_from_terminal_attention(store):
    initialize(store)
    job(store, state="QUEUED")
    request, intent = authority(store)
    pending_id = job(store, ip=IPv4Address("198.51.100.250"), state="RUNNING")
    attempt(store, request, intent, state="RUNNING", job_id=pending_id)
    fleet(store, state="WAITING_ADD")
    fleet(store, state=None, phase="ADMITTING")
    result = report(store)
    assert result["retained_case_count"] == 0
    assert result["pending_jobs"] == {"QUEUED": 1, "RUNNING": 1}
    assert result["pending_managed"]["restoration"] == {"RUNNING": 1}
    assert result["pending_managed"]["fleet_cleanup"] == {"WAITING_ADD": 1}
    assert result["pending_managed"]["inconsistent_fleet_admissions"] == 1


def test_pagination_is_bounded_stable_and_requires_the_same_snapshot(store):
    for i in range(205):
        job(store, ip=IPv4Address(int(IP) + i), when=NOW + timedelta(seconds=i))
    before = fingerprint(store)
    first = report(store)
    second = report(store, page=2, snapshot_digest=first["snapshot_digest"])
    third = report(store, page=3, snapshot_digest=first["snapshot_digest"])
    assert first["retained_case_count"] == 205 and first["total_pages"] == 3
    assert len(first["items"]) == len(second["items"]) == 100 and len(third["items"]) == 5
    assert first["has_next"] and second["has_next"] and not third["has_next"]
    cases = [item["case_id"] for page in (first, second, third) for item in page["items"]]
    assert len(set(cases)) == 205 and fingerprint(store) == before
    with pytest.raises(ValueError, match="previous snapshot"):
        report(store, page=2)
    job(store, ip=IPv4Address("203.0.113.1"), when=NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="snapshot changed"):
        report(store, page=2, snapshot_digest=first["snapshot_digest"])


@pytest.mark.parametrize("change", ["observation", "protection", "device", "pause", "outcome"])
def test_snapshot_binds_context_as_well_as_case_ids(store, change):
    key = job(store)
    first = report(store)
    with store._connection() as db:
        if change == "observation":
            pass
        elif change == "protection":
            db.execute("INSERT INTO protected_ips VALUES (?,'','',1,?)", (IP.packed, stamp(NOW)))
        elif change == "device":
            db.execute("UPDATE devices SET enabled=0")
        elif change == "pause":
            db.execute("UPDATE operation_executor SET mutations_suspended=1")
        else:
            db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=?", (key,))
    if change == "observation":
        store.record_observed_shun(1, IP, "management")
    with pytest.raises(ValueError, match="snapshot changed"):
        report(store, snapshot_digest=first["snapshot_digest"])


@pytest.mark.parametrize("page", [True, 0, -1, 1.5, "2", 1000001])
def test_invalid_page_refuses_without_mutation(store, page):
    before = fingerprint(store)
    with pytest.raises(ValueError, match="page must"):
        report(store, page=page)
    assert fingerprint(store) == before


@pytest.mark.parametrize("partial", ["registry", "trigger", "unknown"])
def test_partial_or_unknown_optional_state_is_not_presented_as_empty(store, partial):
    if partial == "registry":
        with store._connection() as db:
            db.execute("CREATE TABLE managed_shun_registry(id INTEGER)")
    else:
        initialize(store)
        with store._connection() as db:
            db.execute("DROP TRIGGER managed_request_immutable_update" if partial == "trigger" else "CREATE TABLE managed_unknown(id INTEGER)")
    before = fingerprint(store)
    with pytest.raises(ValueError, match="partial state is not empty"):
        report(store)
    assert fingerprint(store) == before


def test_read_transaction_required_and_lease_without_owner_is_not_hidden(store):
    with store._connection() as db:
        with pytest.raises(ValueError, match="read transaction"):
            attention_report(db)
        db.execute("UPDATE operation_executor SET lease_until=?", (stamp(NOW),))
    assert report(store)["executor_lease_present"]


def test_cli_attention_reads_existing_file_without_backup_or_audit(store, capsys):
    job(store)
    before = fingerprint(store)
    assert maintenance.main(["attention", "--database", str(store.path), "--actor", "operator", "--confirm-offline"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["event"] == "maintenance.managed.attention" and result["retained_case_count"] == 1
    assert fingerprint(store) == before


def test_cli_requires_offline_assertion_and_never_creates_a_database(tmp_path):
    path = tmp_path / "missing.db"
    for flags in ([], ["--confirm-offline"]):
        with pytest.raises(SystemExit) as error:
            maintenance.main(["attention", "--database", str(path), "--actor", "operator", *flags])
        assert error.value.code == 2 and not path.exists()


def test_pagination_arguments_cannot_be_misapplied_to_writes(store):
    before = fingerprint(store)
    with pytest.raises(SystemExit) as error:
        maintenance.main(["initialize", "--database", str(store.path), "--actor", "operator", "--page", "2"])
    assert error.value.code == 2 and fingerprint(store) == before


@pytest.mark.parametrize("value", [False, [], "not-a-digest", "\u043d\u0435-ascii"])
def test_invalid_snapshot_binding_is_a_read_only_refusal(store, value):
    before = fingerprint(store)
    with pytest.raises(ValueError, match="snapshot changed"):
        report(store, snapshot_digest=value)
    assert fingerprint(store) == before


def test_supplied_connection_can_be_strictly_read_only(store):
    initialize(store)
    request, intent = authority(store)
    attempt(store, request, intent)
    before = fingerprint(store)
    with store._connection() as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        assert attention_report(db)["retained_case_count"] == 1
        assert db.total_changes == 0
    assert fingerprint(store) == before


def test_missing_pending_restoration_evidence_is_not_ignored(store):
    initialize(store)
    request, intent = authority(store)
    attempt(store, request, intent, state="QUEUED")
    before = fingerprint(store)
    with pytest.raises(ValueError, match="missing its queue evidence"):
        report(store)
    assert fingerprint(store) == before


def test_mismatched_retained_fleet_count_is_unknown_not_a_smaller_scope(store):
    initialize(store)
    key = fleet(store)
    with store._connection() as db:
        db.execute("DROP TRIGGER fleet_wait_authority_immutable")
        db.execute("UPDATE managed_fleet_waits SET target_count=2 WHERE id=?", (key,))
        # Restore the exact declared protection, emulating inconsistent restored data rather than schema.
        script = next(row[3] for row in maintenance._expected_schema() if row[1] == "fleet_wait_authority_immutable")
        db.execute(script)
    result = report(store)["items"][0]
    assert result["scope_state"] == "inconsistent" and result["target_count"] is None


def test_unknown_over_capacity_state_is_a_refusal_not_truncated_success(store):
    initialize(store)
    with store._connection() as db:
        db.executemany("INSERT INTO managed_shun_requests VALUES (?,'a','A','[]','{}','{}',?)",
                       [(str(uuid4()), stamp(NOW)) for _ in range(10001)])
    before = fingerprint(store)
    with pytest.raises(ValueError, match="exceeds this version"):
        report(store)
    assert fingerprint(store) == before
