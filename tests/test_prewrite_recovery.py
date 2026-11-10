"""Exact offline pre-write proof on disposable real-worker fixtures, never FTD."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_batch_session import visit
from test_bulk_policy import dump
from test_extended_recovery import bulk as bulk_fixture
from test_extended_recovery import cancellation_controls as cancellation_fixture
from test_extended_recovery import dispatch as dispatch_fixture
from test_extended_recovery import extended as extended_fixture
from test_extended_recovery import journal as journal_fixture
from test_extended_recovery import leases as leases_fixture
from test_extended_recovery import waits as waits_fixture

from ftd_shun_manager import bulk_policy, prewrite_recovery
from ftd_shun_manager.agent_client import AgentUnavailable
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.device_recovery import inspect, recover

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
extended = extended_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def held(extended, bulk, leases):
    runner, agent = extended
    agent.defer_stage = 33
    original = agent.open_tracked_cycle

    def opening(device, owner):
        session = original(device, owner)

        def fail():
            raise AgentUnavailable('Synthetic final read failure after verified groups and pre-write DEFER')
        session.finish = fail
        return session
    agent.open_tracked_cycle = opening
    asyncio.run(visit(runner))
    bulk[1][0] += timedelta(seconds=1000)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    leases.queue.expire_requests()
    runner._workers[1].queue.cancel_obsolete_policy()
    with runner.store._connection() as db:
        assert dict(db.execute('SELECT state,COUNT(*) FROM operation_jobs GROUP BY state')) == {'VERIFIED': 32, 'CANCELLED': 16}
    bulk[1][0] += timedelta(seconds=1)
    return runner


def review(held, bulk, **changes):
    return inspect(held.store.path, 1, now=bulk[1][0], extended_v6=True, prewrite_defer=True, **changes)


def apply(held, bulk, reviewed, **changes):
    options = {'device_id': 1, 'key': str(uuid4()), 'actor': 'synthetic-prewrite',
        'reviewed_at': reviewed['reviewed_at'], 'review_digest': reviewed['review_digest'],
        'offline': True, 'now': bulk[1][0], 'extended_v6': True, 'prewrite_defer': True, **changes}
    with held.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return recover(db, held.store, **options)


def test_exact_scope_preserves_every_original_outcome_and_release_is_not_replay(held, bulk, leases):
    before = dump(held.store)
    with pytest.raises(ValueError): inspect(held.store.path, 1, now=bulk[1][0], extended_v6=True)
    inspected = review(held, bulk)
    assert dump(held.store) == before
    assert len(inspected['claims']) == 33
    assert sum(row['state'] == 'CANCELLED' for row in inspected['claims']) == 1
    with held.store._connection() as db:
        tables = ('operation_jobs', 'operation_requests', 'managed_bulk_attempts', 'managed_shun_targets', 'managed_shun_requests')
        originals = {table: list(map(tuple, db.execute('SELECT * FROM '+table))) for table in tables}
    receipt = apply(held, bulk, inspected)
    assert receipt['jobs_retried'] == 0 and receipt['original_outcomes_unchanged']
    with held.store._connection() as db:
        assert _state(db)
        assert originals == {table: list(map(tuple, db.execute('SELECT * FROM '+table))) for table in tables}
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'IDLE'
    assert leases.claim(1, str(uuid4()), 135, enabled=True)
    after = dump(held.store)
    assert apply(held, bulk, inspected, key=receipt['operation_id'])['replayed']
    assert dump(held.store) == after


@pytest.mark.parametrize('fault', ['write_sent', 'numeric_false', 'owner', 'epoch', 'version', 'source', 'missing', 'duplicate', 'ack', 'request', 'claim', 'cancel_audit', 'requeue', 'boolean_version'])
def test_ambiguous_or_missing_original_prewrite_proof_refuses_without_changes(held, bulk, fault):
    with held.store._connection() as db:
        event = db.execute("SELECT * FROM shun_events WHERE event_type='SHUN_OPERATION_DEFERRED'").fetchone()
        details = json.loads(event['details_json'])
        if fault == 'missing': db.execute('DELETE FROM shun_events WHERE id=?', (event['id'],))
        elif fault in {'duplicate', 'ack'}:
            values = dict(event)
            values['id'] = str(uuid4())
            if fault == 'ack': values['event_type'] = 'SHUN_ADDITION_ACKNOWLEDGED'
            db.execute('INSERT INTO shun_events VALUES ('+','.join('?' for _ in values)+')', tuple(values.values()))
        elif fault == 'request': db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?", (event['request_id'],))
        elif fault == 'claim': db.execute("DELETE FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_RUNNING'", (event['request_id'],))
        elif fault == 'cancel_audit': db.execute("UPDATE shun_events SET details_json='{}' WHERE request_id=? AND event_type='SHUN_OPERATION_CANCELLED'", (event['request_id'],))
        elif fault == 'requeue': db.execute("UPDATE shun_events SET details_json='{}' WHERE request_id=? AND event_type='MANAGED_BULK_ATTEMPT_QUEUED'", (event['request_id'],))
        else:
            if fault == 'write_sent': details['write_sent'] = True
            if fault == 'numeric_false': details['write_sent'] = 0
            if fault == 'owner': details['device_executor']['owner'] = str(uuid4())
            if fault == 'epoch': details['device_executor']['epoch'] += 1
            if fault == 'version': details['batch_session_version'] = 5
            if fault == 'boolean_version': details['batch_session_version'] = True
            if fault == 'source': details['source'] = 'manual'
            db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(details), event['id']))
    before = dump(held.store)
    with pytest.raises((ValueError, BulkUnavailable)): review(held, bulk)
    assert dump(held.store) == before


@pytest.mark.parametrize('fault', ['expired_review', 'offline', 'changed_db', 'late_audit', 'marker'])
def test_late_failure_rolls_back_schema_receipt_and_release(held, bulk, monkeypatch, fault):
    inspected = review(held, bulk)
    changes = {}
    if fault == 'expired_review': bulk[1][0] += timedelta(minutes=6)
    if fault == 'offline': changes['offline'] = False
    if fault == 'changed_db':
        with held.store._connection() as db: db.execute('UPDATE operation_executor SET revision=revision+1')
    if fault == 'late_audit':
        monkeypatch.setattr(held.store, '_insert_event', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('Synthetic audit failure')))
    if fault == 'marker':
        original = prewrite_recovery.record

        def missing(db, receipt):
            original(db, receipt)
            db.execute('DROP TRIGGER managed_bulk_prewrite_recovery_retained')
            db.execute('DELETE FROM managed_bulk_prewrite_recovery')
        monkeypatch.setattr(prewrite_recovery, 'record', missing)
    before = dump(held.store)
    with pytest.raises((ValueError, sqlite3.Error)): apply(held, bulk, inspected, **changes)
    assert dump(held.store) == before


def test_retention_keeps_original_prewrite_job_request_and_every_bound_audit(held, bulk):
    apply(held, bulk, review(held, bulk))
    bulk[1][0] += timedelta(days=367)
    held.queue.prune_completed(366)
    held.store.prune_expired_history(366, reference_time=bulk[1][0])
    with held.store._connection() as db:
        assert _state(db)
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_prewrite_recovery').fetchone()[0] == 1


def test_pre_profile_readers_and_damaged_marker_refuse(held, bulk, monkeypatch):
    apply(held, bulk, review(held, bulk))
    expected = bulk_policy._expected
    with monkeypatch.context() as old:
        old.setattr(bulk_policy, '_expected', lambda *args: expected(*args[:12]))
        with held.store._connection() as db, pytest.raises(BulkUnavailable): _state(db)
    with held.store._connection() as db:
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_prewrite_recovery_immutable'").fetchone()[0]
        db.execute('DROP TRIGGER managed_bulk_prewrite_recovery_immutable')
        db.execute("UPDATE managed_bulk_prewrite_recovery SET claims_digest=?", ('0'*64,))
        db.execute(trigger)
    with held.store._connection() as db, pytest.raises(BulkUnavailable): _state(db)
