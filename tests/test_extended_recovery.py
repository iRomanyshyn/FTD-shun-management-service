"""Explicit extended offline review; disposable real worker evidence, no SSH."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_batch_session import bulk as bulk_fixture
from test_batch_session import cancellation_controls as cancellation_fixture
from test_batch_session import dispatch as dispatch_fixture
from test_batch_session import extended as extended_fixture
from test_batch_session import journal as journal_fixture
from test_batch_session import leases as leases_fixture
from test_batch_session import visit
from test_batch_session import waits as waits_fixture
from test_bulk_policy import dump

from ftd_shun_manager import bulk_policy, extended_recovery
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.device_reconciliation import inspect, reconcile
from ftd_shun_manager.device_recovery import inspect as verified_inspect
from ftd_shun_manager.device_recovery import recover

extended = extended_fixture
bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


def hold(extended, bulk, leases, count):
    runner, agent = extended
    agent.fail_stage = count
    asyncio.run(visit(runner))
    bulk[1][0] += timedelta(seconds=156)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    runner._workers[1].queue.cancel_obsolete_policy()
    bulk[1][0] += timedelta(seconds=1)
    return runner, agent


def apply(bulk, reviewed, *, verified=False, **changes):
    args = {'device_id': 1, 'key': str(uuid4()), 'actor': 'synthetic-extended-recovery',
            'reviewed_at': reviewed['reviewed_at'], 'review_digest': reviewed['review_digest'],
            'offline': True, 'now': bulk[1][0], 'extended_v6': True}
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return (recover if verified else reconcile)(db, bulk[0].store, **(args | changes))


@pytest.mark.parametrize('count', [17, 26, 64])
def test_extended_reconciliation_retains_all_outcomes_and_compact_exact_scope(extended, bulk, leases, count):
    runner, _ = hold(extended, bulk, leases, count)
    store = runner.store
    before = dump(store)
    with pytest.raises(ValueError): inspect(store.path, 1, now=bulk[1][0])
    with pytest.raises(ValueError): verified_inspect(store.path, 1, now=bulk[1][0], extended_v6=True)
    reviewed = inspect(store.path, 1, now=bulk[1][0], extended_v6=True)
    assert len(reviewed['claims']) == count
    assert dump(store) == before
    tables = ('operation_jobs', 'operation_requests', 'managed_bulk_attempts', 'managed_shun_targets',
              'managed_shun_requests', 'protected_ips', 'managed_bulk_members')
    with store._connection() as db:
        original = {table: list(map(tuple, db.execute('SELECT * FROM ' + table))) for table in tables}
    receipt = apply(bulk, reviewed)
    assert len(receipt['claims']) == count and receipt['jobs_retried'] == 0
    assert receipt['original_outcomes_unchanged'] is True
    with store._connection() as db:
        assert _state(db)
        assert original == {table: list(map(tuple, db.execute('SELECT * FROM ' + table))) for table in tables}
        text = db.execute('SELECT receipt_json FROM managed_bulk_device_recovery').fetchone()[0]
        stored = json.loads(text)
        assert len(text.encode()) <= 16384 and 'claims' not in stored
        assert extended_recovery.claims(stored) == receipt['claims']
        assert db.execute('SELECT claim_count FROM managed_bulk_extended_recovery').fetchone()[0] == count
        assert db.execute('SELECT state FROM managed_bulk_device_executors WHERE device_id=1').fetchone()[0] == 'IDLE'
        for statement in ('DELETE FROM managed_bulk_extended_recovery',
                          'UPDATE managed_bulk_extended_recovery SET claim_count=17'):
            with pytest.raises(sqlite3.IntegrityError): db.execute(statement)
    successor = leases.claim(1, str(uuid4()), 135, enabled=True)
    assert successor is not None
    snapshot = dump(store)
    assert apply(bulk, reviewed, key=receipt['operation_id'])['replayed']
    with pytest.raises(ValueError): apply(bulk, reviewed, key=receipt['operation_id'], extended_v6=False)
    assert dump(store) == snapshot


@pytest.mark.parametrize('fault', ['legacy_audit', 'wrong_group', 'missing_terminal', 'failed', 'stale', 'offline', 'audit_failure'])
def test_extended_refuses_incomplete_or_foreign_proof_and_rolls_back(extended, bulk, leases, monkeypatch, fault):
    runner, _ = hold(extended, bulk, leases, 26)
    store = runner.store
    if fault in {'legacy_audit', 'wrong_group', 'missing_terminal', 'failed'}:
        with store._connection() as db:
            if fault == 'missing_terminal':
                db.execute("DELETE FROM shun_events WHERE id=(SELECT id FROM shun_events WHERE event_type='SHUN_OPERATION_UNVERIFIED' LIMIT 1)")
            elif fault == 'failed':
                db.execute("UPDATE operation_jobs SET state='FAILED' WHERE id=(SELECT id FROM operation_jobs WHERE state='UNVERIFIED' LIMIT 1)")
            else:
                event = db.execute("SELECT id,details_json FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING' LIMIT 1").fetchone()
                details = json.loads(event['details_json'])
                details['batch_session_version' if fault == 'legacy_audit' else 'addition_group'] = 5 if fault == 'legacy_audit' else str(uuid4())
                db.execute('UPDATE shun_events SET details_json=? WHERE id=?', (json.dumps(details), event['id']))
        before = dump(store)
        with pytest.raises(ValueError): inspect(store.path, 1, now=bulk[1][0], extended_v6=True)
        assert dump(store) == before
        return
    reviewed = inspect(store.path, 1, now=bulk[1][0], extended_v6=True)
    changes = {}
    if fault == 'stale': bulk[1][0] += timedelta(minutes=6)
    elif fault == 'offline': changes['offline'] = False
    else:
        def fail(*_args, **_kwargs): raise ValueError('Synthetic audit failure')
        monkeypatch.setattr(store, '_insert_event', fail)
    before = dump(store)
    with pytest.raises(ValueError): apply(bulk, reviewed, **changes)
    assert dump(store) == before


def test_old_expected_profile_refuses_extended_marker_and_damaged_marker_still_blocks(extended, bulk, leases, monkeypatch):
    runner, _ = hold(extended, bulk, leases, 26)
    apply(bulk, inspect(runner.store.path, 1, now=bulk[1][0], extended_v6=True))
    expected = bulk_policy._expected
    with monkeypatch.context() as context:
        # Simulate the pre-extended reader, not "whatever was the last option";
        # later optional profiles must not accidentally make this old-reader
        # check accept the extended marker it is supposed to refuse.
        context.setattr(bulk_policy, '_expected', lambda *args: expected(*args[:9]))
        with runner.store._connection() as db, pytest.raises(BulkUnavailable): _state(db)
    with runner.store._connection() as db:
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_extended_recovery_immutable'").fetchone()[0]
        db.execute('DROP TRIGGER managed_bulk_extended_recovery_immutable')
        db.execute("UPDATE managed_bulk_extended_recovery SET claims_digest=?", ('0' * 64,))
        db.execute(trigger)
    with runner.store._connection() as db, pytest.raises(BulkUnavailable): _state(db)


def test_extended_verified_only_recovery_accepts_real_sixty_four_verified_claims(extended, bulk, leases, monkeypatch):
    runner, _ = extended
    with monkeypatch.context() as context:
        def lose_local_release(*_args, **_kwargs): raise ValueError('Synthetic local release failure')
        context.setattr(type(leases), 'release', lose_local_release)
        asyncio.run(visit(runner))
    bulk[1][0] += timedelta(seconds=156)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    runner._workers[1].queue.cancel_obsolete_policy()
    bulk[1][0] += timedelta(seconds=1)
    reviewed = verified_inspect(runner.store.path, 1, now=bulk[1][0], extended_v6=True)
    assert len(reviewed['claims']) == 64 and all(c['state'] == 'VERIFIED' for c in reviewed['claims'])
    receipt = apply(bulk, reviewed, verified=True)
    assert len(receipt['claims']) == 64 and receipt['jobs_retried'] == 0


def test_sql_release_guard_refuses_missing_extended_marker_and_rolls_back(extended, bulk, leases, monkeypatch):
    from ftd_shun_manager import device_reconciliation
    from ftd_shun_manager.schema import execute_schema

    runner, _ = hold(extended, bulk, leases, 26)
    reviewed = inspect(runner.store.path, 1, now=bulk[1][0], extended_v6=True)
    before = dump(runner.store)

    def omit_marker(db, _receipt):
        execute_schema(db, extended_recovery.DDL)

    monkeypatch.setattr(device_reconciliation, 'record', omit_marker)
    with pytest.raises(sqlite3.IntegrityError, match='exact retained marker'):
        apply(bulk, reviewed)
    assert dump(runner.store) == before


@pytest.mark.parametrize('fault', ['format', 'dual', 'empty', 'duplicate', 'order', 'action', 'state', 'id', 'digest', 'shape', 'type'])
def test_compact_decoder_never_accepts_ambiguous_or_incomplete_claim_scope(fault):
    claims = [{'job_id': f'00000000-0000-4000-8000-{n:012d}', 'action': 'ADD', 'state': 'VERIFIED',
               'running_event_id': str(uuid4()), 'terminal_event_id': str(uuid4()), 'evidence_digest': 'a' * 64}
              for n in range(17)]
    stored, _ = extended_recovery.encode({'claims': claims, 'recovery_profile': 'tracked-v6'}, True)
    if fault == 'format': stored['claims_format'] = 'unknown'
    elif fault == 'dual': stored['claims'] = claims
    elif fault == 'empty': stored['compact_claims'] = []
    elif fault == 'duplicate': stored['compact_claims'][1] = stored['compact_claims'][0]
    elif fault == 'order': stored['compact_claims'].reverse()
    elif fault == 'action': stored['compact_claims'][0][1] = 'REMOVE'
    elif fault == 'state': stored['compact_claims'][0][2] = 'FAILED'
    elif fault == 'id': stored['compact_claims'][0][3] = 'invalid'
    elif fault == 'digest': stored['compact_claims'][0][5] = 'x' * 64
    elif fault == 'shape': stored['compact_claims'][0].pop()
    else: stored['compact_claims'][0][2] = True
    with pytest.raises(BulkUnavailable): extended_recovery.claims(stored)
