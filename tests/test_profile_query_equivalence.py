"""Complete profile invariants on disposable, deliberately damaged databases."""

import sqlite3
from contextlib import closing

import pytest
from test_bulk_attempts import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_attempts import cancellation_controls as cancellation_controls  # noqa: PLC0414
from test_bulk_attempts import journal as journal  # noqa: PLC0414
from test_bulk_attempts import running
from test_bulk_policy import confirm, prepare

from ftd_shun_manager.bulk_attempts import validate
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state


def damage_disposable_database(store, sql, parameters=()):
    # Offline corruption fixture only: restore every exact trigger definition
    # before validation so a schema mismatch cannot mask a broken data binding.
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        triggers = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
        for name, _ in triggers:
            db.execute(f'DROP TRIGGER "{name}"')
        db.execute(sql, parameters)
        for _, definition in triggers:
            db.execute(definition)


@pytest.mark.parametrize('transaction', [False, True])
def test_request_chain_join_factoring_is_only_used_inside_an_existing_snapshot(bulk, transaction):
    policy, _ = bulk
    confirm(bulk, prepare(bulk)[1])
    with policy.store._connection() as db:
        if transaction:
            db.execute('BEGIN')
        queries = []
        db.set_trace_callback(queries.append)
        assert _state(db) is not None
        target_query = next(query for query in queries if query.startswith('SELECT 1 FROM managed_shun_targets t LEFT JOIN'))
        assert ('LEFT JOIN managed_shun_requests r' in target_query) is not transaction
        assert db.in_transaction is transaction  # Never create a hidden transaction.


@pytest.mark.parametrize('transaction', [False, True])
@pytest.mark.parametrize('sql', [
    'DELETE FROM managed_shun_requests',
    'DELETE FROM managed_bulk_manifests',
    'DELETE FROM managed_bulk_members',
    'DELETE FROM devices WHERE id=1',
    "UPDATE managed_shun_targets SET authorization_request_id='missing'",
    "UPDATE managed_shun_targets SET intent_id='different'",
    'UPDATE managed_shun_targets SET generation=generation+1',
    "UPDATE managed_bulk_members SET authorization_request_id='missing'",
])
def test_transitive_profile_validation_still_rejects_every_broken_link(bulk, sql, transaction):
    policy, _ = bulk
    confirm(bulk, prepare(bulk)[1])
    damage_disposable_database(policy.store, sql)
    with policy.store._connection() as db, pytest.raises(BulkUnavailable, match='membership is incomplete'):
        if transaction:
            db.execute('BEGIN')
        _state(db)


@pytest.mark.parametrize('state', ['QUEUED', 'RUNNING', 'VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'CANCELLED'])
def test_pending_job_presence_check_preserves_the_original_retention_contract(bulk, journal, state):
    _, job, _ = running(bulk, journal)
    store = journal[0].store
    completed = None if state in {'QUEUED', 'RUNNING'} else '2026-10-21T12:00:03.000Z'
    occurrence, interface = ('synthetic-occurrence', 'management') if state == 'VERIFIED' else (None, None)
    damage_disposable_database(store, '''UPDATE managed_bulk_attempts SET state=?,completed_at=?,occurrence_id=?,interface=?''',
                               (state, completed, occurrence, interface))
    damage_disposable_database(store, 'DELETE FROM operation_jobs WHERE id=?', (job,))
    with store._connection() as db:
        db.execute('BEGIN')
        if state in {'QUEUED', 'RUNNING'}:
            with pytest.raises(BulkUnavailable, match='attempt evidence'):
                validate(db)
        else:
            # Only this isolated predicate is unchanged. Retention/uncertainty
            # controls still forbid pruning UNVERIFIED or captured evidence.
            validate(db)
