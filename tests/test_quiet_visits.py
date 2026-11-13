"""Quiet successful checks discard only their temporary coordination evidence."""

import json
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_device_leases import acquire, dump
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager.device_leases import DeviceLeases
from ftd_shun_manager.operation_queue import QueueConflict

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


def events(leases):
    with leases.store._connection() as db:
        return [tuple(row) for row in db.execute('SELECT * FROM shun_events ORDER BY rowid')]


def test_repeated_empty_success_does_not_grow_audit_but_keeps_current_fence(leases):
    original = events(leases)
    for epoch in range(1, 11):
        token, queue = acquire(leases)
        assert token.epoch == epoch
        assert len(events(leases)) == len(original) + 1  # Crash evidence exists while leased.
        queue.finish_cycle(token.owner, 0)
        assert events(leases) == original
        assert leases.status()['devices'][0]['state'] == 'IDLE'


@pytest.mark.parametrize('activity', ['observation', 'global_policy', 'failure', 'tampered_claim'])
def test_changes_failures_and_noncanonical_claims_keep_the_original_audit(leases, activity):
    token, queue = acquire(leases)
    if activity == 'observation':
        leases.store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'outside')
    else:
        with leases.store._connection() as db:
            if activity == 'tampered_claim':
                db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.extra',1) WHERE event_type='DEVICE_LEASE_CLAIMED'")
            else:
                leases.store._insert_event(db, 'PROTECTED_IP_UPDATED' if activity == 'global_policy' else 'SHUN_OPERATION_FAILED',
                    None if activity == 'global_policy' else 1, None, None, 'fixture', 'Fixture', (), None, {})
    original = events(leases)
    queue.finish_cycle(token.owner, 0)
    after = events(leases)
    assert after[:-1] == original
    assert after[-1][2] == 'DEVICE_LEASE_RELEASED'


def test_failed_read_release_and_expired_fence_never_use_quiet_retention(leases, bulk):
    token, _ = acquire(leases)
    leases.release_unopened(token)
    retained = events(leases)
    assert [row[2] for row in retained][-3:] == ['DEVICE_LEASE_CLAIMED', 'DEVICE_LEASE_OPEN_FAILED', 'DEVICE_LEASE_RELEASED']
    token, queue = acquire(leases)
    before = dump(leases.store)
    bulk[1][0] += timedelta(seconds=136)
    with pytest.raises(QueueConflict): queue.finish_cycle(token.owner, 0)
    assert dump(leases.store) == before


def test_other_device_claim_is_preserved_when_this_empty_visit_finishes(leases):
    first, one = acquire(leases)
    second, two = acquire(leases, device=2)
    one.finish_cycle(first.owner, 0)
    remaining = events(leases)
    assert len(remaining) == 1
    assert json.loads(remaining[0][-1]) == {'owner': second.owner, 'epoch': second.epoch}
    two.finish_cycle(second.owner, 0)
    assert events(leases) == []


def test_expiry_after_temporary_claim_cleanup_rolls_back_whole_release(leases, bulk, monkeypatch):
    token, queue = acquire(leases)
    before = dump(leases.store)
    original = DeviceLeases._discard_quiet_claim

    def expired(db, selected):
        assert original(db, selected)
        bulk[1][0] += timedelta(seconds=136)
        return True

    monkeypatch.setattr(DeviceLeases, '_discard_quiet_claim', staticmethod(expired))
    with pytest.raises(QueueConflict): queue.finish_cycle(token.owner, 0)
    assert dump(leases.store) == before


def test_expired_unfinished_visit_keeps_claim_and_attention(leases, bulk):
    _token, _ = acquire(leases)
    original = events(leases)
    bulk[1][0] += timedelta(seconds=136)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    assert events(leases)[:-1] == original
    assert events(leases)[-1][2] == 'DEVICE_LEASE_ATTENTION'
