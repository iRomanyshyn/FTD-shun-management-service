"""Disposable fenced pending groups; no runtime/SSH or new policy authority."""

import json
from datetime import timedelta
from ipaddress import IPv4Address

import pytest
from test_bulk_policy import dump
from test_device_leases import acquire, claim, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager.agent_protocol import (
    AdditionResult,
    ObservedShun,
    PendingAddition,
    VerifiedAdditionBatch,
)
from ftd_shun_manager.batch_queue import BatchDeviceOperationQueue, PendingBatchMustFlush
from ftd_shun_manager.operation_queue import QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def group(bulk, leases):
    grant(bulk, (1,), count=10)
    token, ordinary = acquire(leases)
    assert discover(bulk, ordinary) == 10
    return BatchDeviceOperationQueue(leases.store, token, priority_removals=True), ordinary


def acknowledge(queue, sequence):
    job = claim(queue)
    assert job is not None
    queue.acknowledge_addition(job['id'], queue.token.owner, PendingAddition(IPv4Address(job['ip']), sequence))
    return job


def test_claim_keeps_both_executor_boundaries_without_an_adjacent_duplicate(group, monkeypatch):
    queue, _ = group
    calls = []
    original = queue._executor

    def checked(db, owner, device):
        calls.append((owner, device, db.in_transaction))
        return original(db, owner, device)

    monkeypatch.setattr(queue, '_executor', checked)
    assert claim(queue) is not None
    assert calls == [(queue.token.owner, queue.token.device_id, True)] * 2


def test_group_membership_probe_does_not_replace_final_event_profile_validation(group, monkeypatch):
    from ftd_shun_manager.bulk_policy import BulkUnavailable
    from ftd_shun_manager.operation_queue import OperationQueue

    queue, _ = group
    original = OperationQueue._event

    def corrupt_before_base_validation(self, db, event, request, job, details=None):
        if event == 'SHUN_OPERATION_RUNNING':
            db.execute('CREATE TABLE managed_unexpected_profile(value INTEGER)')
        return original(self, db, event, request, job, details)

    monkeypatch.setattr(OperationQueue, '_event', corrupt_before_base_validation)
    before = dump(queue.store)
    with pytest.raises(BulkUnavailable, match='Exact version-2 storage'):
        claim(queue)
    assert dump(queue.store) == before


def test_claim_and_finish_handoff_do_not_resolve_the_same_attempt_again(group, monkeypatch):
    from ftd_shun_manager import managed_restoration

    queue, _ = group
    calls = []
    original = managed_restoration.attempt_for_job

    def lookup(db, job_id):
        calls.append(job_id)
        return original(db, job_id)

    monkeypatch.setattr(managed_restoration, 'attempt_for_job', lookup)
    job = claim(queue)
    assert calls == [job['id']] * 2  # Original lookup and base claim audit.
    queue.acknowledge_addition(job['id'], queue.token.owner, PendingAddition(IPv4Address(job['ip']), 1))
    calls.clear()
    queue.finish_verified_group(queue.token.owner, result([job]), 2)
    assert calls == [job['id']] * 2  # Source lookup and base terminal audit.


@pytest.mark.parametrize('damage', ['stale_attempt', 'outside_transaction'])
def test_bound_result_handoff_refuses_stale_rows_and_missing_transaction(group, damage):
    from ftd_shun_manager.managed_restoration import _record_bound_result, attempt_for_job
    from ftd_shun_manager.managed_safety import ManagedStateUnavailable

    queue, _ = group
    job = claim(queue)
    before = dump(queue.store)
    with queue.store._connection() as db:
        attempt = dict(attempt_for_job(db, job['id']))
        if damage == 'stale_attempt':
            db.execute('BEGIN IMMEDIATE')
            attempt['target_revision'] += 1
            error, message = ManagedStateUnavailable, 'changed during'
        else:
            error, message = ValueError, 'owning write transaction'
        with pytest.raises(error, match=message):
            _record_bound_result(db, queue.store, job, attempt, 'UNVERIFIED', '2026-10-21T12:00:04.000Z')
    assert dump(queue.store) == before


def test_result_handoff_rechecks_delegation_and_rolls_back_occurrence_and_audit(group, monkeypatch):
    from ftd_shun_manager.managed_safety import ManagedStateUnavailable

    queue, _ = group
    job = acknowledge(queue, 1)
    original = queue._event

    def change_delegation(db, event, request, current, details=None):
        original(db, event, request, current, details)
        if event == 'SHUN_OPERATION_VERIFIED':
            db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]' WHERE id=?", (request['id'],))

    monkeypatch.setattr(queue, '_event', change_delegation)
    before = dump(queue.store)
    with pytest.raises(ManagedStateUnavailable, match='retained authority'):
        queue.finish_verified_group(queue.token.owner, result([job]), 2)
    assert dump(queue.store) == before
    assert queue.pending == [job['id']] and queue.settled == 0


def result(jobs):
    return VerifiedAdditionBatch(tuple((IPv4Address(job['ip']), AdditionResult(True, 'management')) for job in jobs),
                                 tuple(ObservedShun(IPv4Address(job['ip']), 'management') for job in jobs))


def test_acknowledged_same_epoch_group_can_claim_but_ordinary_queue_stays_serial(group):
    queue, ordinary = group
    jobs = [acknowledge(queue, n) for n in range(1, 9)]
    assert claim(ordinary) is None
    with pytest.raises(PendingBatchMustFlush): claim(queue)
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='RUNNING'").fetchone()[0] == 8
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='VERIFIED'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_state WHERE active=1').fetchone()[0] == 0
    original_group = queue.group
    queue.finish_verified_group(queue.token.owner, result(jobs), 9)
    assert queue.pending == [] and queue.settled == 8 and queue.group != original_group
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_bulk_attempts WHERE state='VERIFIED'").fetchone()[0] == 8
        assert db.execute('SELECT COUNT(*) FROM shun_state WHERE active=1').fetchone()[0] == 8
        events = db.execute("SELECT details_json FROM shun_events WHERE event_type='SHUN_OPERATION_VERIFIED'").fetchall()
        assert all(json.loads(row[0])['verification_sequence'] == 9 for row in events)
    assert claim(queue) is not None


def test_unacknowledged_claim_cannot_gain_parallelism(group):
    queue, _ = group
    first = claim(queue)
    assert first is not None
    assert claim(queue) is None
    with pytest.raises(QueueConflict):
        queue.acknowledge_addition(first['id'], queue.token.owner,
                                   PendingAddition(IPv4Address('192.0.2.9'), 1))
    assert queue.pending == []


def test_a_new_queue_cannot_adopt_an_acknowledged_group_even_with_same_owner(group):
    queue, _ = group
    first = acknowledge(queue, 1)
    replacement = BatchDeviceOperationQueue(queue.store, queue.token)
    assert claim(replacement) is None
    with pytest.raises(QueueConflict):
        replacement.acknowledge_addition(first['id'], queue.token.owner, PendingAddition(IPv4Address(first['ip']), 1))
    assert queue.pending == [first['id']]


def test_exact_prewrite_deferral_history_is_not_current_epoch_authority(group, leases):
    from uuid import uuid4

    queue, _ = group
    first = claim(queue)
    queue.defer_addition(first['id'], queue.token.owner)
    queue.finish_cycle(queue.token.owner, 0)
    token = leases.claim(1, str(uuid4()), 135, enabled=True)
    successor = BatchDeviceOperationQueue(queue.store, token)
    next_job = acknowledge(successor, 1)
    assert next_job['id'] == first['id']
    successor.finish_verified_group(token.owner, result([next_job]), 2)
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING' AND json_extract(details_json,'$.operation_id')=?",
                          (first['id'],)).fetchone()[0] == 2


@pytest.mark.parametrize('fault', ['missing_member', 'reverse', 'wrong_scope', 'noop', 'no_snapshot', 'extra_scope'])
def test_group_receipt_is_validated_whole_before_any_success(group, fault):
    queue, _ = group
    jobs = [acknowledge(queue, n) for n in range(1, 3)]
    verified = result(jobs)
    additions, snapshot = verified.additions, verified.snapshot
    if fault == 'missing_member': additions = additions[:1]
    elif fault == 'reverse': additions = additions[::-1]
    elif fault == 'wrong_scope': additions = tuple((ip, AdditionResult(True, 'outside')) for ip, _ in additions)
    elif fault == 'noop': additions = tuple((ip, AdditionResult(False)) for ip, _ in additions)
    elif fault == 'no_snapshot': snapshot = ()
    else: snapshot += (ObservedShun(snapshot[0].ip, 'outside'),)
    before = dump(queue.store)
    with pytest.raises(QueueConflict):
        queue.finish_verified_group(queue.token.owner, VerifiedAdditionBatch(additions, snapshot), 3)
    assert dump(queue.store) == before
    queue.fail_pending_group(queue.token.owner, 'Synthetic invalid group receipt')
    with queue.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='UNVERIFIED'").fetchone()[0] == 2


def test_later_settlement_failure_retains_earlier_verified_results(group, monkeypatch):
    from ftd_shun_manager.device_leases import DeviceOperationQueue

    queue, _ = group
    jobs = [acknowledge(queue, n) for n in range(1, 4)]
    original = DeviceOperationQueue.finish_addition

    def finish(self, job_id, *args, **kwargs):
        if job_id == jobs[1]['id']: raise ValueError('Synthetic local result failure')
        return original(self, job_id, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(DeviceOperationQueue, 'finish_addition', finish)
        with pytest.raises(ValueError): queue.finish_verified_group(queue.token.owner, result(jobs), 4)
    queue.fail_pending_group(queue.token.owner, 'Synthetic later local error')
    with queue.store._connection() as db:
        states = [db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] for job in jobs]
        assert states == ['VERIFIED', 'UNVERIFIED', 'UNVERIFIED']
        assert db.execute('SELECT COUNT(*) FROM shun_state WHERE active=1').fetchone()[0] == 1


def test_pending_expiry_keeps_uncertainty_and_original_audits(group, bulk, leases):
    from uuid import uuid4

    queue, _ = group
    jobs = [acknowledge(queue, n) for n in range(1, 3)]
    bulk[1][0] += timedelta(seconds=200)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    with queue.store._connection() as db:
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'ATTENTION'
        assert [db.execute('SELECT state FROM operation_jobs WHERE id=?', (j['id'],)).fetchone()[0] for j in jobs] == ['UNVERIFIED'] * 2
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'").fetchone()[0] == 2
