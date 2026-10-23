"""Actual bounded v2 reads; no standing admission, schema creation or device RPC."""

import sqlite3
from contextlib import contextmanager
from ipaddress import IPv4Address

import pytest
from test_bulk_attempts import journal as journal_fixture
from test_bulk_attempts import running
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_policy import bulk as bulk_fixture
from test_bulk_policy import confirm, dump, prepare, retire

from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_policy_views import BulkPolicyViews
from ftd_shun_manager.managed_selection import require_selection
from ftd_shun_manager.managed_shuns import ManagedPageChanged, ManagedPageInvalid
from ftd_shun_manager.store import Store

bulk = bulk_fixture
journal = journal_fixture
cancellation_controls = cancellation_fixture


def test_missing_database_and_legacy_profile_are_not_created_or_reinterpreted(tmp_path):
    store = Store(tmp_path / 'absent.db')
    view = BulkPolicyViews(store)
    with pytest.raises(sqlite3.OperationalError): view.page()
    assert not store.path.exists()
    store.initialize()
    before = dump(store)
    with pytest.raises(BulkUnavailable): view.page()
    assert dump(store) == before


def test_empty_profile_is_explicit_and_read_only(bulk):
    view = BulkPolicyViews(bulk[0].store)
    before = dump(view.store)
    result = view.page()
    assert result['intent_format'] == 2 and result['initialized']
    assert result['entries'] == [] and result['total'] == 0 and result['pages'] == 1
    assert result['attempt_ledger_initialized'] is False
    assert result['device_work_admitted'] is False and result['read_only']
    assert dump(view.store) == before
    with view._snapshot() as db, pytest.raises(sqlite3.OperationalError, match='readonly'):
        db.execute('UPDATE protected_policy SET revision=revision+1')


@pytest.mark.parametrize('page,revision', [(0, None), (True, None), (2**31, None), (1, True), (1, -1)])
def test_invalid_literal_selector_has_no_storage_effect(bulk, page, revision):
    before = dump(bulk[0].store)
    with pytest.raises(ManagedPageInvalid): BulkPolicyViews(bulk[0].store).page(page, revision=revision)
    assert dump(bulk[0].store) == before


def test_thousand_pair_policy_is_read_in_100_row_pages_without_legacy_cap_or_fallback(bulk, monkeypatch):
    text = '\n'.join(str(IPv4Address(int(IPv4Address('198.18.0.1')) + i)) for i in range(1001))
    confirm(bulk, prepare(bulk, text)[1])
    view = BulkPolicyViews(bulk[0].store)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('No whole/raw policy view fallback is permitted.')
    monkeypatch.setattr(bulk[0], 'policy_page', forbidden)
    first, last = view.page(), view.page(11, revision=1)
    assert first['total'] == 1001 and first['limit'] == 200000
    assert first['pages'] == 11 and len(first['entries']) == 100
    assert len(last['entries']) == 1 and last['entries'][0]['ip'] == str(IPv4Address(int(IPv4Address('198.18.0.1')) + 1000))
    assert first['entries'][0]['actor_subject'] == 'alice'
    assert first['entries'][0]['actor_roles'] == ['Operator']
    assert type(first['entries'][0]['enabled']) is bool
    assert first['entries'][0]['last_attempt_state'] is None
    assert 'payload_json' not in first['entries'][0]
    assert 'actor_roles_json' not in first['entries'][0]
    with pytest.raises(ManagedPageInvalid): view.page(12)


def test_exact_selection_includes_missing_descriptor_without_full_registry(bulk):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    view = BulkPolicyViews(bulk[0].store)
    pairs = [(2, IPv4Address('198.51.100.1')), (1, IPv4Address('198.51.100.2'))]
    before = dump(view.store)
    result = view.selection(pairs, revision=1)
    require_selection(result, pairs)
    assert result['total'] == 2 and result['selected_count'] == 1
    assert result['entries'][0]['device_id'] == 2
    assert len(result['selection']) == 2 and result['read_scope'] == 'selected_pairs'
    assert dump(view.store) == before


@pytest.mark.parametrize('pairs', [[], [(True, IPv4Address('198.51.100.1'))],
    [(1, IPv4Address('198.51.100.1'))] * 2,
    [(1, IPv4Address(i + 1)) for i in range(101)]])
def test_selection_never_truncates_or_accepts_ambiguous_pairs(bulk, pairs):
    with pytest.raises(ValueError): BulkPolicyViews(bulk[0].store).selection(pairs)


def test_policy_change_conflict_and_single_snapshot_during_concurrent_retirement(bulk, monkeypatch):
    confirm(bulk, prepare(bulk)[1])
    view = BulkPolicyViews(bulk[0].store)
    original = view._snapshot
    changed = False

    @contextmanager
    def snapshot():
        nonlocal changed
        with original() as db:
            def trace(sql):
                nonlocal changed
                if not changed and sql.startswith('SELECT t.*,d.hostname'):
                    changed = True
                    retire(bulk)
            db.set_trace_callback(trace)
            yield db
    monkeypatch.setattr(view, '_snapshot', snapshot)
    first = view.page(revision=1)
    assert first['revision'] == 1 and first['entries'][0]['enabled']
    second = view.page()
    assert second['revision'] == 2 and second['entries'][0]['enabled'] is False
    with pytest.raises(ManagedPageChanged): view.page(revision=1)
    with pytest.raises(ManagedPageChanged): view.selection([(1, IPv4Address('198.51.100.1'))], revision=1)


def test_orphan_elsewhere_is_not_hidden_by_selected_join(bulk):
    confirm(bulk, prepare(bulk, devices=(1, 2))[1])
    with sqlite3.connect(bulk[0].store.path) as db:
        db.execute('DELETE FROM devices WHERE id=2')  # Synthetic FK-off corruption.
    with pytest.raises(BulkUnavailable):
        BulkPolicyViews(bulk[0].store).selection([(1, IPv4Address('198.51.100.1'))])


@pytest.mark.parametrize('outcome', ['VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED'])
def test_actual_attempts_keep_results_and_do_not_invent_service_creation(bulk, journal, outcome):
    from ftd_shun_manager.agent_protocol import AdditionResult
    _, job, _ = running(bulk, journal)
    result = AdditionResult(True, 'management') if outcome == 'VERIFIED' else AdditionResult(False, None) if outcome == 'NOOP' else outcome
    journal[1].finish_addition(job, 'synthetic-bulk-result-worker', result)
    view = BulkPolicyViews(bulk[0].store)
    before = dump(view.store)
    row = view.page()['entries'][0]
    assert row['last_attempt_state'] == outcome and row['last_attempt_generation'] == 1
    assert bool(row['last_verified_application_at']) is (outcome == 'VERIFIED')
    assert row['attention'] is (outcome in {'FAILED', 'UNVERIFIED'})
    assert dump(view.store) == before
