"""Whole-task progress over disposable journals, never live FTD writes."""

from datetime import timedelta

import pytest
from test_bulk_cancellations import cancel
from test_bulk_discovery import bulk as bulk_fixture
from test_bulk_discovery import cancellation_controls as cancellation_fixture
from test_bulk_discovery import controller
from test_bulk_discovery import dispatch as dispatch_fixture
from test_bulk_discovery import journal as journal_fixture
from test_bulk_discovery import waits as waits_fixture
from test_bulk_dispatch import OWNER, claim, setup
from test_bulk_policy import dump

from ftd_shun_manager import bulk_policy
from ftd_shun_manager.agent_protocol import AdditionResult

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
waits = waits_fixture


def task(dispatch):
    status = dispatch.queue.status(addition_device_ids=frozenset({1}), bulk_dispatch_enabled=True)
    assert status['progress']['requests'] == []  # Per-address delegations are not user tasks.
    assert len(status['imports']['tasks']) == 1
    return status['imports']['tasks'][0]


def test_complete_import_counts_include_unmaterialized_members_and_retained_receipts(bulk, dispatch):
    root, snapshot, _ = setup(bulk, dispatch, count=40)
    before = dump(dispatch.store)
    initial = task(dispatch)
    assert initial['total'] == initial['outstanding'] == 40
    assert initial['processed'] == 0 and initial['counts'] == {'pending': 40}
    assert initial['id'] == root and initial['cancellation_available']
    assert dump(dispatch.store) == before
    assert controller(dispatch).discover(snapshot, OWNER) == 16
    staged = task(dispatch)
    assert staged['counts'] == {'pending': 24, 'queued': 16}
    first = claim(dispatch)
    dispatch.queue.finish_addition(first['id'], OWNER, AdditionResult(True, 'management'))
    second = claim(dispatch)
    dispatch.queue.finish_addition(second['id'], OWNER, AdditionResult(False))
    applied = task(dispatch)
    assert applied['processed'] == 2 and applied['outstanding'] == 38
    assert applied['counts'] == {'pending': 24, 'queued': 14, 'verified': 1, 'noop': 1}
    bulk[1][0] += timedelta(days=2)
    dispatch.queue.prune_completed(1)
    retained = task(dispatch)
    assert retained['counts']['verified'] == retained['counts']['noop'] == 1


@pytest.mark.parametrize('outcome', ['FAILED', 'UNVERIFIED'])
def test_failure_is_attention_not_success_and_original_queue_evidence_remains(bulk, dispatch, outcome):
    _, snapshot, _ = setup(bulk, dispatch, count=4)
    assert controller(dispatch).discover(snapshot, OWNER) == 4
    job = claim(dispatch)
    dispatch.queue.finish_addition(job['id'], OWNER, outcome, reason='Synthetic failed verification')
    result = task(dispatch)
    assert result['active'] and result['attention'] == 1
    assert result['counts'][outcome.lower()] == 1 and not result['counts'].get('verified')
    assert result['processed'] == 1 and result['outstanding'] == 3


def test_whole_cancellation_keeps_applied_members_and_stops_unmaterialized_work(bulk, dispatch, cancellation_controls):
    key, snapshot, _ = setup(bulk, dispatch, count=40)
    controller(dispatch).discover(snapshot, OWNER)
    job = claim(dispatch)
    dispatch.queue.finish_addition(job['id'], OWNER, AdditionResult(True, 'management'))
    cancel(cancellation_controls, key)
    result = task(dispatch)
    assert result['cancelled'] and not result['cancellation_available']
    assert result['counts'] == {'verified': 1, 'stopped': 39}
    assert result['processed'] == result['total'] == 40 and result['outstanding'] == 0
    with dispatch.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets WHERE enabled=1').fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM operation_jobs WHERE action='REMOVE'").fetchone()


def test_queue_status_validates_profile_once_not_once_per_internal_job(bulk, dispatch, monkeypatch):
    _, snapshot, _ = setup(bulk, dispatch, count=40)
    controller(dispatch).discover(snapshot, OWNER)
    original, calls = bulk_policy._state, []

    def checked(db):
        calls.append(1)
        return original(db)
    monkeypatch.setattr(bulk_policy, '_state', checked)
    assert task(dispatch)['counts']['queued'] == 16
    assert len(calls) == 1
