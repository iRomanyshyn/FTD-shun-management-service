"""Operational pause with real SQLite/claims, semantic fakes and no lab writes."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_policy import dump
from test_device_leases import acquire, claim, discover, grant
from test_device_leases import bulk as bulk_fixture
from test_device_leases import cancellation_controls as cancellation_fixture
from test_device_leases import dispatch as dispatch_fixture
from test_device_leases import journal as journal_fixture
from test_device_leases import leases as leases_fixture
from test_device_leases import waits as waits_fixture

from ftd_shun_manager import bulk_policy
from ftd_shun_manager.bulk_discovery import BulkDiscovery
from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
from ftd_shun_manager.managed_addition_controls import ManagedAdditionControls, read
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import stamp
from ftd_shun_manager.protected_policy import ProtectedPolicy

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture


@pytest.fixture
def controls(bulk, leases):
    result = ManagedAdditionControls(leases.store, clock=lambda: bulk[1][0])
    result.initialize()
    return result


def change(controls, action='PAUSE', revision=0, *, kind='imports', key=None, roles=('Operator',)):
    return controls.change(key or str(uuid4()), kind, action, revision, 'alice', 'Actual operator', roles)


def test_explicit_initialization_is_idempotent_and_preserves_original_policy(bulk, leases):
    grant(bulk, devices=(1,), count=2)
    with leases.store._connection() as db:
        original = tuple(map(tuple, db.execute('SELECT * FROM managed_shun_targets')))
        assert not read(db)['available']
    controls = ManagedAdditionControls(leases.store)
    controls.initialize()
    snapshot = dump(leases.store)
    controls.initialize()
    assert dump(leases.store) == snapshot
    with leases.store._connection() as db:
        assert tuple(map(tuple, db.execute('SELECT * FROM managed_shun_targets'))) == original
        assert read(db) == {'available': True, **{kind: {'paused': False, 'revision': 0, 'resume_after': None}
                                                for kind in ('imports', 'restoration')}}


def test_control_profile_is_not_silently_accepted_by_old_writer(bulk, controls, monkeypatch):
    original = bulk_policy._expected
    # This simulated writer predates both controls and the later offline-v7 flag.
    monkeypatch.setattr(bulk_policy, '_expected', lambda *args: original(*args[:13]))
    with controls.store._connection() as db, pytest.raises(BulkUnavailable):
        _state(db)


def test_cannot_initialize_during_device_session(bulk, leases):
    acquire(leases)
    before = dump(leases.store)
    with pytest.raises(ManagedConflict): ManagedAdditionControls(leases.store).initialize()
    assert dump(leases.store) == before


def test_pause_retains_policy_and_queued_adds_without_sending_or_claiming(bulk, leases, controls):
    grant(bulk, devices=(1,), count=2)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 2
    key = str(uuid4())
    result = change(controls, key=key)
    assert result['imports']['paused'] and not result['restoration']['paused'] and not result['device_work_admitted']
    assert claim(queue) is None
    with controls.store._connection() as db:
        _state(db)
        assert db.execute('SELECT SUM(enabled) FROM managed_shun_targets').fetchone()[0] == 2
        assert [r[0] for r in db.execute('SELECT state FROM operation_jobs')] == ['QUEUED', 'QUEUED']
    source = BulkDiscovery(queue.store, queue, enabled=True, addition_device_ids=frozenset({1}))
    snapshot = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    assert source.discover(snapshot, token.owner) == 0
    assert source.status()['devices']['1']['state'] == 'scanned'
    assert change(controls, key=key)['replayed']


def test_running_add_can_settle_after_pause_and_resume_requires_new_read(bulk, leases, controls):
    from ftd_shun_manager.agent_protocol import AdditionResult

    grant(bulk, devices=(1,), count=2)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 2
    running = claim(queue)
    change(controls)
    queue.finish_addition(running['id'], token.owner, AdditionResult(True, 'management'))
    assert claim(queue) is None
    bulk[1][0] += timedelta(seconds=2)
    result = change(controls, 'RESUME', 1)
    assert not result['imports']['paused'] and result['imports']['resume_after']
    assert claim(queue) is None  # Old queued absence is not a post-resume read.
    with controls.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (running['id'],)).fetchone()[0] == 'VERIFIED'
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE state='CANCELLED'").fetchone()[0] == 1
        assert db.execute('SELECT SUM(enabled) FROM managed_shun_targets').fetchone()[0] == 2


def test_protected_automatic_removal_is_claimable_while_additions_paused(bulk, leases, controls):
    change(controls)
    ip = IPv4Address('198.51.100.8')
    policy = ProtectedPolicy(leases.store)
    policy.change('add', ip, 0, 'bob', 'Actual protector', ('Operator',), enabled=True)
    leases.store.record_observed_shun(1, ip, 'management')
    leases.queue.enqueue(str(uuid4()), [(1, ip)], 'system:trusted-ip-policy', 'Trusted IP policy', (), source='trusted_policy')
    token, queue = acquire(leases)
    job = queue.claim_next_mutation(1, token.owner, queue.cutoff(), additions_enabled=True, bulk_dispatch_enabled=True)
    assert job and job['action'] == 'REMOVE'


@pytest.mark.parametrize('roles', [(), ('Viewer',)])
def test_read_only_actors_cannot_pause(controls, roles):
    before = dump(controls.store)
    with pytest.raises(PermissionError): change(controls, roles=roles)
    assert dump(controls.store) == before


def test_conflicts_and_historical_replay_never_toggle_new_state(bulk, controls):
    key = str(uuid4())
    change(controls, key=key)
    bulk[1][0] += timedelta(seconds=1)
    change(controls, 'RESUME', 1)
    before = dump(controls.store)
    assert not change(controls, key=key)['imports']['paused']  # CURRENT state; no replayed pause.
    with pytest.raises(ManagedConflict): change(controls, revision=0)
    with pytest.raises(ManagedConflict): change(controls, 'RESUME', 0, key=key)
    assert dump(controls.store) == before


def test_simultaneous_operators_change_one_revision_once(controls):
    def submit(_):
        try:
            return change(controls)['imports']['revision']
        except ManagedConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(submit, range(2)))) == ['1', 'conflict']
    with controls.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_control_requests').fetchone()[0] == 1
        event = db.execute("SELECT * FROM shun_events WHERE event_type='MANAGED_ADDITIONS_PAUSED'").fetchone()
        assert event['actor_subject'] == 'alice' and json.loads(event['actor_roles_json']) == ['Operator']


def test_resume_does_not_release_recovery_or_offline_pause(bulk, leases, controls):
    change(controls)
    with controls.store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    bulk[1][0] += timedelta(seconds=1)
    change(controls, 'RESUME', 1)
    with controls.store._connection() as db:
        assert db.execute('SELECT mutations_suspended FROM operation_executor').fetchone()[0] == 1
        assert db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0] == 1


def test_control_history_is_immutable_and_partial_profile_refused(controls):
    change(controls)
    with controls.store._connection() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM managed_bulk_control_requests')
        with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE managed_bulk_controls SET additions_paused=0')
        db.execute('DROP TRIGGER managed_bulk_controls_retained')
        with pytest.raises(BulkUnavailable): _state(db)


@pytest.mark.parametrize('paused_kind,expected', [('imports', '198.51.100.70'), ('restoration', '198.51.100.1')])
def test_independent_pauses_filter_before_scan_limit_and_do_not_starve_other_kind(bulk, leases, controls, monkeypatch, paused_kind, expected):
    grant(bulk, devices=(1,), count=70)
    bulk[1][0] += timedelta(seconds=1)
    monkeypatch.setattr('ftd_shun_manager.store.now', lambda: stamp(bulk[1][0]))
    leases.store.record_observed_shun(1, IPv4Address('198.51.100.70'), 'management')
    leases.store.reconcile_snapshot(1, [])
    change(controls, kind=paused_kind)
    token, queue = acquire(leases)
    assert discover(bulk, queue) == (1 if paused_kind == 'imports' else 16)
    job = claim(queue)
    assert str(IPv4Address(job['ip'])) == expected
    assert job['action'] == 'ADD'
    assert token.owner


def test_each_control_has_its_own_revision_barrier_and_idempotency(bulk, controls):
    key = str(uuid4())
    change(controls, key=key)
    change(controls, kind='restoration')
    with pytest.raises(ManagedConflict): change(controls, kind='restoration', key=key)
    bulk[1][0] += timedelta(seconds=1)
    result = change(controls, 'RESUME', 1)
    assert result['imports']['revision'] == 2 and not result['imports']['paused']
    assert result['restoration'] == {'revision': 1, 'paused': True, 'resume_after': None}


def test_extra_null_control_row_is_not_an_empty_or_third_control(controls):
    with controls.store._connection() as db:
        db.execute('INSERT INTO managed_bulk_controls VALUES (NULL,0,0,NULL,NULL)')
        with pytest.raises(BulkUnavailable): _state(db)
