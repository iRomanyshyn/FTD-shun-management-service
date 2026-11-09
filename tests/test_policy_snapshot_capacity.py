"""Transport-sized policy evidence on disposable state, never real FTD work."""

from dataclasses import replace
from ipaddress import IPv4Address

import pytest
from test_bulk_attempts import OWNER, running
from test_bulk_attempts import journal as journal_fixture
from test_bulk_cancellations import controls as cancellation_fixture
from test_bulk_dispatch import admit as bulk_admit
from test_bulk_dispatch import dispatch as dispatch_fixture
from test_bulk_dispatch import setup as setup_bulk
from test_bulk_policy import bulk as bulk_fixture
from test_bulk_policy import dump
from test_bulk_waits import waits as waits_fixture
from test_managed_restoration import IP, admit, evidence
from test_managed_restoration import lab as lab_fixture

from ftd_shun_manager.bulk_discovery import BulkDiscovery
from ftd_shun_manager.bulk_dispatch import _snapshot
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.snapshot_protocol import MAX_SNAPSHOT_ENTRIES

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
journal = journal_fixture
waits = waits_fixture
dispatch = dispatch_fixture
lab = lab_fixture


@pytest.fixture(scope='module', params=(65537, 95081, MAX_SNAPSHOT_ENTRIES))
def large_ips(request):
    # Unrelated observations, not additional managed authority or DB rows.
    return frozenset(IPv4Address(0x0A000000 + value) for value in range(request.param))


def test_bulk_discovery_accepts_transport_sized_evidence_without_widening_work(bulk, dispatch, large_ips):
    _, snapshot, _ = setup_bulk(bulk, dispatch)
    snapshot = replace(snapshot, present_ips=large_ips)
    discovery = BulkDiscovery(dispatch.store, dispatch.queue, enabled=True, addition_device_ids=frozenset({1}))
    assert discovery.discover(snapshot, OWNER) == 1
    status = discovery.status()
    assert status['admitted_this_cycle'] == 1 and status['admission_limit'] == 16
    assert status['check_limit'] == 64 and status['device_window'] == 16
    with dispatch.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0


def test_bulk_large_snapshot_presence_still_refuses_addition(bulk, dispatch, large_ips):
    _, snapshot, candidates = setup_bulk(bulk, dispatch)
    present = (large_ips - {next(iter(large_ips))}) | {candidates[0].ip}
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict, match='still contains'):
        bulk_admit(dispatch, replace(snapshot, present_ips=present), candidates)
    assert dump(dispatch.store) == before


def test_legacy_restoration_accepts_transport_sized_evidence(lab, large_ips):
    receipt = admit(lab, evidence(lab, present_ips=large_ips))
    with lab[0].store._connection() as db:
        row = db.execute('SELECT j.state,j.ip FROM operation_jobs j JOIN operation_links l ON l.job_id=j.id '
                         'WHERE l.request_id=?', (receipt['operation_id'],)).fetchone()
        assert row['state'] == 'QUEUED' and row['ip'] == IP.packed
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 1


def test_capture_accepts_transport_sized_evidence_without_authorizing_dispatch(bulk, journal, large_ips):
    key, job, snapshot = running(bulk, journal, capture=False)
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        result = journal[0].capture_running(key, job, replace(snapshot, present_ips=large_ips), OWNER,
                                            enabled=True, connection=db)
        assert result['evidence_captured'] and result['dispatch_authorized'] is False


def test_large_evidence_never_resumes_suspended_policy(bulk, dispatch):
    _, snapshot, candidates = setup_bulk(bulk, dispatch, activate=False)
    present = frozenset(IPv4Address(0x0A000000 + value) for value in range(95081))
    before = dump(dispatch.store)
    with pytest.raises(QueueConflict, match='suspended'):
        bulk_admit(dispatch, replace(snapshot, present_ips=present), candidates)
    assert dump(dispatch.store) == before


@pytest.fixture(scope='module')
def oversized_ips():
    return frozenset(IPv4Address(0x0A000000 + value) for value in range(MAX_SNAPSHOT_ENTRIES + 1))


def test_bulk_refuses_over_transport_cap_before_work(bulk, dispatch, oversized_ips):
    _, snapshot, candidates = setup_bulk(bulk, dispatch)
    before = dump(dispatch.store)
    with pytest.raises(ValueError, match='complete bounded'):
        bulk_admit(dispatch, replace(snapshot, present_ips=oversized_ips), candidates)
    assert dump(dispatch.store) == before


def test_legacy_restoration_refuses_over_transport_cap_without_changes(lab, oversized_ips):
    before = dump(lab[0].store)
    with pytest.raises(ValueError, match='validated snapshot'):
        admit(lab, evidence(lab, present_ips=oversized_ips))
    assert dump(lab[0].store) == before


def test_capture_refuses_over_transport_cap_without_changes(bulk, journal, oversized_ips):
    key, job, snapshot = running(bulk, journal, capture=False)
    before = dump(bulk[0].store)
    with bulk[0].store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError, match='Complete bounded'):
            journal[0].capture_running(key, job, replace(snapshot, present_ips=oversized_ips), OWNER,
                                        enabled=True, connection=db)
    assert dump(bulk[0].store) == before


@pytest.mark.parametrize('invalid', ['mutable', 'non_ip', 'incomplete'])
def test_bulk_retains_literal_snapshot_validation(bulk, dispatch, invalid):
    _, snapshot, _ = setup_bulk(bulk, dispatch)
    changes = {'mutable': {'present_ips': {IPv4Address('10.0.0.1')}},
               'non_ip': {'present_ips': frozenset({'10.0.0.1'})}, 'incomplete': {'complete': False}}
    before = dump(dispatch.store)
    with pytest.raises(ValueError):
        _snapshot(replace(snapshot, **changes[invalid]))
    assert dump(dispatch.store) == before
