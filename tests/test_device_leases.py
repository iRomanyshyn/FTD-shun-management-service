"""Fenced device leases/shared queue on disposable SQLite; no runtime or FTD."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_bulk_attempts import journal as journal_fixture
from test_bulk_cancellations import cancel
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_dispatch import dispatch as dispatch_fixture
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, dump, prepare
from test_bulk_waits import waits as waits_fixture

from ftd_shun_manager import device_leases
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.bulk_discovery import BulkDiscovery
from ftd_shun_manager.bulk_policy import BulkUnavailable, _quiescent
from ftd_shun_manager.device_leases import DeviceLeases, DeviceOperationQueue
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue, QueueConflict, stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store

journal = journal_fixture
cancellation_controls = cancellation_fixture
waits = waits_fixture
dispatch = dispatch_fixture


@pytest.fixture
def leases(bulk, dispatch):
    service = DeviceLeases(dispatch.store, dispatch.queue)
    with dispatch.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service.initialize(frozenset({1, 2, 3, 4}), concurrency=2)
    with dispatch.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return service


def grant(bulk, devices=(1, 2), count=1):
    _, proposal = prepare(bulk, '\n'.join(f'198.51.100.{i}' for i in range(1, count + 1)), devices)
    confirm(bulk, proposal)
    with bulk[0].store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
        db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0,dispatch_resume_after=?', (stamp(bulk[1][0]),))
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    bulk[1][0] += timedelta(seconds=2)
    return proposal['operation_id']


def acquire(leases, device=1, seconds=135):
    token = leases.claim(device, str(uuid4()), seconds, enabled=True)
    assert token is not None
    return token, DeviceOperationQueue(leases.store, token)


def discover(bulk, queue):
    evidence = CompleteSnapshot(str(uuid4()), queue.token.device_id, bulk[1][0], bulk[1][0], frozenset())
    source = BulkDiscovery(queue.store, queue, enabled=True, addition_device_ids=frozenset({queue.token.device_id}))
    return source.discover(evidence, queue.token.owner)


def claim(queue):
    return queue.claim_addition(queue.token.device_id, queue.token.owner, queue.cutoff(),
                                execution_enabled=True, bulk_dispatch_enabled=True)


def test_explicit_profile_preserves_history_and_rejects_legacy_global_leases(bulk, dispatch):
    policy, _ = bulk
    root = prepare(bulk)[1]
    confirm(bulk, root)
    with policy.store._connection() as db:
        original = tuple(db.execute('SELECT * FROM managed_shun_requests').fetchone())
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    service = DeviceLeases(policy.store, dispatch.queue)
    service.initialize(frozenset({1, 2}), concurrency=2)
    with policy.store._connection() as db:
        assert tuple(db.execute('SELECT * FROM managed_shun_requests').fetchone()) == original
        assert db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE operation_executor SET owner='unsupported',lease_until='2026-10-21T12:01:00.000Z'")
    with pytest.raises(QueueConflict): dispatch.queue.claim_cycle('legacy', 135)
    before = dump(policy.store)
    service.initialize(frozenset({1, 2}), concurrency=2)
    assert dump(policy.store) == before
    with pytest.raises(QueueConflict): service.initialize(frozenset({1}), concurrency=2)


def test_default_off_constructor_read_and_missing_profile_never_initialize(bulk, tmp_path):
    absent = Store(tmp_path / 'absent.db')
    service = DeviceLeases(absent, OperationQueue(absent))
    assert service.claim(None, None, None) is None and not absent.path.exists()
    before = dump(bulk[0].store)
    with pytest.raises(BulkUnavailable): DeviceLeases(bulk[0].store, OperationQueue(bulk[0].store)).status()
    assert dump(bulk[0].store) == before


def test_profile_initialization_failure_rolls_back_ddl_and_scope(bulk, dispatch, monkeypatch):
    service = DeviceLeases(dispatch.store, dispatch.queue)
    with dispatch.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(dispatch.store)
    original = device_leases._state

    def fail(db):
        result = original(db)
        if device_leases.present(db): raise ValueError('Synthetic profile validation failure')
        return result

    monkeypatch.setattr(device_leases, '_state', fail)
    with dispatch.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError): service.initialize(frozenset({1, 2}), connection=db)
    assert dump(dispatch.store) == before


def test_distinct_devices_claim_and_settle_concurrently_through_shared_queue(bulk, leases):
    grant(bulk)
    first, one = acquire(leases)
    second, two = acquire(leases, 2)
    assert discover(bulk, one) == discover(bulk, two) == 1
    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs = list(workers.map(claim, (one, two)))
    assert [job['device_id'] for job in jobs] == [1, 2]
    assert claim(one) is None
    assert two.finish_addition(jobs[1]['id'], second.owner, AdditionResult(True, 'management')) == 'VERIFIED'
    assert one.finish_addition(jobs[0]['id'], first.owner, AdditionResult(False, None)) == 'NOOP'
    leases.release(first)
    leases.release(second)
    assert all(row['state'] == 'IDLE' for row in leases.status()['devices'])


def test_concurrency_limit_and_same_device_competitors_never_double_own(leases):
    with ThreadPoolExecutor(max_workers=4) as workers:
        tokens = list(workers.map(lambda _: leases.claim(1, str(uuid4()), 135, enabled=True), range(4)))
    assert sum(token is not None for token in tokens) == 1
    acquire(leases, 2)
    assert leases.claim(3, str(uuid4()), 135, enabled=True) is None
    leases.release(next(token for token in tokens if token))
    assert acquire(leases, 3)[0].device_id == 3


def test_epoch_fences_original_owner_even_when_nonce_is_reused(leases):
    old, queue = acquire(leases)
    leases.release(old)
    new = leases.claim(1, old.owner, 135, enabled=True)
    assert new.epoch == old.epoch + 1
    before = dump(leases.store)
    for operation in (lambda: leases.renew(old, 135), lambda: leases.release(old),
                      lambda: queue.renew(old.owner, 135), lambda: queue.finish_cycle(old.owner, 60)):
        with pytest.raises(QueueConflict): operation()
    assert dump(leases.store) == before


@pytest.mark.parametrize('action', ['result', 'deferral', 'claim', 'renew'])
def test_wrong_device_or_epoch_cannot_publish_or_claim_other_jobs(bulk, leases, action):
    grant(bulk)
    one_token, one = acquire(leases)
    two_token, two = acquire(leases, 2)
    discover(bulk, two)
    job = claim(two)
    before = dump(leases.store)
    with pytest.raises(QueueConflict):
        if action == 'result': one.finish_addition(job['id'], one_token.owner, AdditionResult(True, 'management'))
        if action == 'deferral': one.defer_addition(job['id'], one_token.owner)
        if action == 'claim': one.claim_removal(2, one_token.owner, one.cutoff())
        if action == 'renew': leases.renew(replace(two_token, epoch=two_token.epoch + 1), 135)
    assert dump(leases.store) == before


def test_expiry_retains_unknown_attention_without_steal_and_other_device_continues(bulk, leases):
    grant(bulk)
    token, one = acquire(leases, seconds=10)
    other, two = acquire(leases, 2)
    discover(bulk, one)
    discover(bulk, two)
    first_job, second_job = claim(one), claim(two)
    bulk[1][0] += timedelta(seconds=11)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    assert leases.status()['devices'][0]['state'] == 'ATTENTION'
    with leases.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (first_job['id'],)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT state FROM managed_bulk_attempts WHERE job_id=?', (first_job['id'],)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (second_job['id'],)).fetchone()[0] == 'RUNNING'
    with pytest.raises(QueueConflict): one.finish_addition(first_job['id'], token.owner, AdditionResult(True, 'management'))
    assert two.finish_addition(second_job['id'], other.owner, AdditionResult(True, 'management')) == 'VERIFIED'
    before = dump(leases.store)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    assert dump(leases.store) == before


def test_read_only_expiry_also_requires_attention_and_survives_restart_retention(bulk, leases):
    token, _ = acquire(leases, seconds=5)
    bulk[1][0] += timedelta(days=400)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    leases.queue.prune_completed(366)
    restarted = DeviceLeases(leases.store, OperationQueue(leases.store))
    assert restarted.status()['devices'][0]['state'] == 'ATTENTION'
    with pytest.raises(QueueConflict): restarted.release(token)
    with leases.store._connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")


def test_running_release_is_refused_and_renewal_changes_no_epoch(bulk, leases):
    grant(bulk, (1,))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    with pytest.raises(QueueConflict): leases.release(token)
    leases.renew(token, 200)
    assert leases.status()['devices'][0]['epoch'] == token.epoch
    queue.finish_addition(job['id'], token.owner, 'UNVERIFIED')
    leases.release(token)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None


@pytest.mark.parametrize('control', ['protection', 'cancel'])
def test_standing_revocation_and_wait_settlement_remain_atomic(bulk, leases, cancellation_controls, control):
    root = grant(bulk, (1,))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    if control == 'protection':
        from ipaddress import IPv4Address

        ProtectedPolicy(leases.store).change('add', IPv4Address(job['ip']), 0, 'viewer', 'Viewer', ('Viewer',), managed_revision=1)
    else:
        cancel(cancellation_controls, root)
    queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    enabled = bulk[0].policy_page()['entries'][0]['enabled']
    assert bool(enabled) == (control == 'cancel')
    if control == 'cancel': assert cancellation_controls.page(root, 'alice', ('Operator',))['settled']


def test_global_queue_cannot_bypass_device_token_for_results_or_admission(bulk, leases):
    grant(bulk, (1,))
    token, queue = acquire(leases)
    discover(bulk, queue)
    job = claim(queue)
    before = dump(leases.store)
    with pytest.raises(QueueConflict): leases.queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    with pytest.raises(QueueConflict): leases.queue.claim_addition(1, token.owner, queue.cutoff(), execution_enabled=True, bulk_dispatch_enabled=True)
    assert dump(leases.store) == before


@pytest.mark.parametrize('phase', ['claim', 'release', 'result', 'recovery'])
def test_late_audit_failure_rolls_back_full_lease_job_and_journal_state(bulk, leases, monkeypatch, phase):
    grant(bulk, (1,))
    token = queue = job = None
    if phase != 'claim': token, queue = acquire(leases, seconds=10)
    if phase in {'result', 'recovery'}:
        discover(bulk, queue)
        job = claim(queue)
    if phase == 'recovery': bulk[1][0] += timedelta(seconds=11)
    before = dump(leases.store)

    def fail(*args): raise ValueError('Synthetic late audit failure')

    monkeypatch.setattr(leases.store, '_insert_event', fail)
    with pytest.raises(ValueError):
        if phase == 'claim': leases.claim(1, str(uuid4()), 135, enabled=True)
        if phase == 'release': leases.release(token)
        if phase == 'result': queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
        if phase == 'recovery': leases.claim(1, str(uuid4()), 135, enabled=True)
    assert dump(leases.store) == before


def test_late_clock_expiry_rolls_back_verified_result_and_occurrence(bulk, leases, monkeypatch):
    grant(bulk, (1,))
    token, queue = acquire(leases, seconds=10)
    discover(bulk, queue)
    job = claim(queue)
    original = leases.store._insert_event

    def slow(*args):
        result = original(*args)
        bulk[1][0] += timedelta(seconds=11)
        return result

    monkeypatch.setattr(leases.store, '_insert_event', slow)
    before = dump(leases.store)
    with pytest.raises(QueueConflict): queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    assert dump(leases.store) == before and not leases.store.list_active_shuns()


def test_offline_quiescence_and_resume_do_not_ignore_device_read_lease(leases, bulk):
    acquire(leases)
    with leases.store._connection() as db:
        with pytest.raises(ManagedConflict): _quiescent(db)
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE managed_bulk_registry SET restoration_suspended=0,dispatch_resume_after=?', (stamp(bulk[1][0]),))


def test_partial_or_missing_scope_is_not_repaired_and_status_is_read_only(leases):
    before = dump(leases.store)
    view = leases.status()
    assert view['read_only'] and len(view['devices']) == 4
    assert dump(leases.store) == before
    with leases.store._connection() as db:
        db.execute('DROP TRIGGER managed_bulk_device_retained')
        db.execute('DELETE FROM managed_bulk_device_executors WHERE device_id=1')
    before = dump(leases.store)
    with pytest.raises(BulkUnavailable): leases.status()
    with pytest.raises(BulkUnavailable): leases.initialize(frozenset({1, 2, 3, 4}), concurrency=2)
    assert dump(leases.store) == before


@pytest.mark.parametrize('kwargs', [{'device_ids': frozenset({True})}, {'device_ids': [1]},
    {'device_ids': frozenset()}, {'concurrency': True}, {'concurrency': 11}])
def test_literal_configuration_never_migrates_on_error(bulk, dispatch, kwargs):
    service = DeviceLeases(dispatch.store, dispatch.queue)
    before = dump(dispatch.store)
    with pytest.raises(ValueError): service.initialize(**({'device_ids': frozenset({1})} | kwargs))
    assert dump(dispatch.store) == before


def removal(bulk, queue):
    """Synthetic already-admitted ordinary REMOVE; never a Web identity or live mutation."""
    from ipaddress import IPv4Address

    key, job = str(uuid4()), str(uuid4())
    with queue.store._connection() as db:
        db.execute("INSERT INTO operation_requests VALUES (?,'synthetic:removal','Removal','[\"Operator\"]','manual','{}',?,?,'ACTIVE')",
                   (key, stamp(bulk[1][0]), stamp(bulk[1][0] + timedelta(seconds=900))))
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'QUEUED',?,'REMOVE')",
                   (job, IPv4Address('203.0.113.250').packed, stamp(bulk[1][0])))
        db.execute('INSERT INTO operation_links VALUES (?,?)', (key, job))
    assert queue.claim_removal(1, queue.token.owner, queue.cutoff())['id'] == job
    return job


@pytest.mark.parametrize('method', ['result', 'deferral'])
def test_remove_paths_are_device_fenced_and_refuse_expired_results(bulk, leases, method):
    token, queue = acquire(leases, seconds=10)
    job = removal(bulk, queue)
    bulk[1][0] += timedelta(seconds=11)
    before = dump(leases.store)
    with pytest.raises(QueueConflict):
        if method == 'result': queue.finish_removal(job, token.owner, 'NOOP')
        else: queue.defer_removal(job, token.owner)
    assert dump(leases.store) == before


def test_current_remove_finishes_and_audit_binds_exact_executor_epoch(bulk, leases):
    token, queue = acquire(leases)
    job = removal(bulk, queue)
    queue.finish_removal(job, token.owner, 'NOOP')
    with leases.store._connection() as db:
        rows = db.execute("SELECT actor_subject,details_json FROM shun_events WHERE event_type IN ('SHUN_OPERATION_RUNNING','SHUN_OPERATION_NOOP')").fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row['actor_subject'] == 'synthetic:removal'
            assert json.loads(row['details_json'])['device_executor'] == {'owner': token.owner, 'epoch': token.epoch}


@pytest.mark.parametrize('phase', ['claim', 'release', 'deferral'])
def test_expiry_during_audit_cannot_commit_or_advance_lease_generation(bulk, leases, monkeypatch, phase):
    token = queue = job = None
    if phase != 'claim': token, queue = acquire(leases, seconds=10)
    if phase == 'deferral': job = removal(bulk, queue)
    original = leases.store._insert_event

    def slow(*args):
        result = original(*args)
        bulk[1][0] += timedelta(seconds=301)
        return result

    monkeypatch.setattr(leases.store, '_insert_event', slow)
    before = dump(leases.store)
    with pytest.raises(QueueConflict):
        if phase == 'claim': leases.claim(1, str(uuid4()), 10, enabled=True)
        if phase == 'release': leases.release(token)
        if phase == 'deferral': queue.defer_removal(job, token.owner)
    assert dump(leases.store) == before


def test_global_read_cooldown_neither_blocks_nor_is_rewritten_by_device_ownership(bulk, leases):
    with leases.store._connection() as db:
        deadline = stamp(bulk[1][0] + timedelta(days=1))
        db.execute('UPDATE operation_executor SET next_eligible_at=?', (deadline,))
    token, _ = acquire(leases)
    leases.release(token)
    with leases.store._connection() as db:
        row = db.execute('SELECT owner,lease_until,next_eligible_at FROM operation_executor').fetchone()
        assert tuple(row) == (None, None, deadline)


@pytest.mark.parametrize('bad', ['device_bool', 'owner', 'seconds_bool', 'too_short', 'too_long', 'enabled_int', 'scope'])
def test_bad_claims_cannot_touch_scope_or_authority(leases, bad):
    args = {'device_id': 1, 'owner': str(uuid4()), 'seconds': 135, 'enabled': True}
    if bad == 'device_bool': args['device_id'] = True
    if bad == 'owner': args['owner'] = 'not-a-canonical-worker'
    if bad == 'seconds_bool': args['seconds'] = True
    if bad == 'too_short': args['seconds'] = 4
    if bad == 'too_long': args['seconds'] = 301
    if bad == 'enabled_int': args['enabled'] = 1
    if bad == 'scope': args['device_id'] = 10
    before = dump(leases.store)
    with pytest.raises(ValueError): leases.claim(**args)
    assert dump(leases.store) == before


def test_device_disabled_after_scope_sealing_is_not_forgotten_or_claimed(leases):
    with leases.store._connection() as db: db.execute('UPDATE devices SET enabled=0 WHERE id=1')
    before = dump(leases.store)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    assert leases.status()['devices'][0]['device_id'] == 1
    assert dump(leases.store) == before


def test_malformed_original_running_evidence_refuses_recovery_without_partial_attention(bulk, leases):
    grant(bulk, (1,))
    _, queue = acquire(leases, seconds=5)
    discover(bulk, queue)
    job = claim(queue)
    with leases.store._connection() as db:
        db.execute("UPDATE operation_requests SET actor_roles_json='[\"Operator\"]'")
    bulk[1][0] += timedelta(seconds=6)
    before = dump(leases.store)
    with pytest.raises(ValueError): leases.claim(1, str(uuid4()), 135, enabled=True)
    assert dump(leases.store) == before
    with leases.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'RUNNING'
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'LEASED'


def test_missing_base_executor_and_changed_profile_scope_fail_closed(leases):
    with leases.store._connection() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE managed_bulk_device_profile SET concurrency=4')
        with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM managed_bulk_device_profile')
        db.execute('DELETE FROM operation_executor WHERE id=1')
    before = dump(leases.store)
    with pytest.raises(BulkUnavailable): leases.claim(1, str(uuid4()), 135, enabled=True)
    assert dump(leases.store) == before
