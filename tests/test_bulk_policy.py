"""Version-2 policy storage on disposable SQLite, never the lab or an executor."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

from ftd_shun_manager import bulk_policy
from ftd_shun_manager.bulk_policy import BulkPolicies, BulkUnavailable
from ftd_shun_manager.managed_intent import canonical_managed_change
from ftd_shun_manager.managed_safety import ManagedStateUnavailable, managed_state
from ftd_shun_manager.managed_shuns import ManagedCapacity, ManagedConflict, ManagedShuns
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.store import Device, Store


@pytest.fixture
def bulk(tmp_path):
    store = Store(tmp_path / 'synthetic.db')
    store.initialize()
    OperationQueue(store).initialize()
    for device in range(1, 11):
        store.upsert_device(Device(device, f'synthetic-{device}', IPv4Address(f'192.0.2.{device}'), True), 'ssh-ed25519 AAAA')
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=1')
    clock = [datetime(2026, 10, 21, 12, tzinfo=UTC)]
    policy = BulkPolicies(store, clock=lambda: clock[0])
    policy.initialize_empty()
    policy.preparations.initialize()
    # Synthetic ordinary-resume state; never invokes recovery or activation in the lab.
    with store._connection() as db:
        db.execute('UPDATE operation_executor SET mutations_suspended=0')
    return policy, clock


def prepare(bulk, text='198.51.100.1', devices=(1,), *, key=None, subject='alice'):
    policy, _ = bulk
    saved = policy.preparations.create(text, list(devices), subject, 'Draft author', ('Viewer',), label='Fixture', reason='Synthetic')
    proposal = policy.preparations.propose_bulk_intent(saved['plan_id'], subject, saved['digest'], key or str(uuid4()))
    return saved, proposal


def confirm(bulk, proposal, **changes):
    policy, _ = bulk
    kwargs = {'accepted_count': proposal['manifest']['accepted_count'], 'subject': 'alice', 'display_name': 'Actual author',
              'roles': ('Operator',), 'maintain_present': True, 'enabled': True,
              'addition_device_ids': frozenset(proposal['manifest']['device_ids'])}
    return policy.confirm(proposal['canonical'], proposal['digest'], **(kwargs | changes))


def retire(bulk, pairs=None, *, key=None, revision=None, **changes):
    policy, _ = bulk
    pairs = [(1, IPv4Address('198.51.100.1'))] if pairs is None else pairs
    revision = policy.policy_page()['revision'] if revision is None else revision
    digest = canonical_managed_change('RETIRE', pairs, revision, 0)[2]
    return policy.retire(key or str(uuid4()), pairs, revision, digest, 'alice', 'Actual author', ('Operator',), **changes)


def dump(store):
    with store._connection() as db:
        return tuple(db.iterdump())


def no_work(policy):
    with policy.store._connection() as db:
        for table in ('operation_requests', 'operation_jobs', 'manual_import_batches', 'shun_import_origins'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert db.execute('SELECT restoration_suspended FROM managed_bulk_registry').fetchone()[0] == 1
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_constructor_optional_reads_and_failed_init_never_create_or_repair_state(tmp_path):
    absent = Store(tmp_path / 'absent.db')
    BulkPolicies(absent)
    assert not absent.path.exists()
    store = Store(tmp_path / 'base.db')
    store.initialize()
    OperationQueue(store).initialize()
    policy = BulkPolicies(store)
    before = dump(store)
    assert not policy.list_for_owner('alice')['initialized']
    with pytest.raises(BulkUnavailable): policy.policy_page()
    with pytest.raises(ManagedConflict, match='Pause'): policy.initialize_empty()
    assert dump(store) == before
    ManagedShuns(store).initialize()
    before = dump(store)
    with pytest.raises(BulkUnavailable): policy.initialize_empty()
    assert dump(store) == before


def test_init_savepoint_rollback_survives_caught_error_and_outer_commit(tmp_path, monkeypatch):
    store = Store(tmp_path / 'failed.db')
    store.initialize()
    OperationQueue(store).initialize()
    with store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    before = dump(store)
    original = bulk_policy._state

    def fail(db):
        original(db)
        raise ValueError('Synthetic final schema check failure')

    with monkeypatch.context() as patch:
        patch.setattr(bulk_policy, '_state', fail)
        with store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with pytest.raises(ValueError): BulkPolicies(store).initialize_empty(connection=db)
    assert dump(store) == before


def test_legacy_services_and_initializers_refuse_even_small_bulk_state(bulk):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    before = dump(policy.store)
    with policy.store._connection() as db, pytest.raises(ManagedStateUnavailable): managed_state(db)
    with pytest.raises(ManagedConflict): ManagedShuns(policy.store).initialize()
    with pytest.raises(ManagedStateUnavailable): ManagedShuns(policy.store).snapshot()
    assert dump(policy.store) == before


def test_exact_root_members_actor_audit_and_no_provenance_or_jobs(bulk):
    policy, _ = bulk
    saved, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2\ninvalid', (1, 2))
    result = confirm(bulk, proposal)
    assert result['changed_targets'] == result['accepted_pairs'] == 4
    assert result['policy_only'] and not result['device_work_admitted'] and result['restoration_suspended']
    receipt = policy.page(result['operation_id'], 'alice')
    assert receipt['historical_confirmation'] and len(receipt['targets']) == 4 and receipt['result'] == result
    assert all(row['generation'] == 1 and row['authorization_request_id'] == result['operation_id'] for row in receipt['targets'])
    assert policy.preparations.page(saved['plan_id'], 'alice')['state'] == 'CONFIRMED'
    with pytest.raises(ValueError):
        policy.preparations.propose_bulk_intent(saved['plan_id'], 'alice', saved['digest'], str(uuid4()))
    with policy.store._connection() as db:
        actor = db.execute('SELECT actor_roles_json,actor_display_name FROM managed_shun_requests').fetchone()
        assert tuple(actor) == ('["Operator"]', 'Actual author')
        assert db.execute("SELECT COUNT(*) FROM shun_events WHERE event_type='MANAGED_SHUN_AUTHORIZED'").fetchone()[0] == 4
    no_work(policy)


def test_adoption_and_protection_exclusion_never_create_fake_add_or_replace_existing_authority(bulk):
    policy, _ = bulk
    _, first = prepare(bulk)
    confirm(bulk, first)
    original = policy.policy_page()['entries'][0]
    policy.store.record_observed_shun(2, IPv4Address('198.51.100.1'), 'management')
    with policy.store._connection() as db:
        db.execute("INSERT INTO protected_ips VALUES (?,'Protected','',1,'2026-10-21T12:00:00Z')", (IPv4Address('198.51.100.2').packed,))
        db.execute('UPDATE protected_policy SET revision=revision+1')
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2\n198.51.100.3', (1, 2))
    result = confirm(bulk, proposal)
    assert result['classification_counts'] == {'PROPOSE_ADD': 2, 'PROPOSE_ADOPT': 1, 'ALREADY_MANAGED': 1, 'EXCLUDED_PROTECTED': 2}
    assert result['changed_targets'] == 3 and policy.policy_page()['total'] == 4
    assert policy.policy_page()['entries'][0] == original
    assert all(row['intent_id'] is None for row in policy.page(result['operation_id'], 'alice')['targets'] if row['classification'] == 'EXCLUDED_PROTECTED')
    no_work(policy)


def test_receipt_survives_pruning_retirement_new_generation_restart_and_original_key_replay(bulk):
    policy, clock = bulk
    _, proposal = prepare(bulk)
    result = confirm(bulk, proposal)
    old = policy.policy_page()['entries'][0]
    retire(bulk)
    _, newer = prepare(bulk)
    confirm(bulk, newer)
    current = policy.policy_page()['entries'][0]
    assert current['generation'] == 2 and current['intent_id'] != old['intent_id']
    clock[0] += timedelta(minutes=10)
    assert policy.preparations.prune_expired() == 2
    restarted = BulkPolicies(Store(policy.store.path), clock=lambda: clock[0])
    before = dump(policy.store)
    assert restarted.page(result['operation_id'], 'alice')['result'] == result
    assert confirm((restarted, clock), proposal) == {**result, 'replayed': True}
    assert restarted.list_for_owner('alice')['items'][0]['accepted_count'] == 1
    assert policy.policy_page()['entries'][0] == current and dump(policy.store) == before


@pytest.mark.parametrize('block', ['observed', 'protected_revision', 'managed_revision', 'device_disabled', 'device_name',
                                   'pending', 'uncertain', 'lease', 'paused', 'expired', 'cancelled', 'profiles', 'owner', 'count', 'gate', 'consent'])
def test_whole_scope_conflicts_never_partially_write(bulk, block):
    policy, clock = bulk
    saved, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2', (1, 2))
    changes = {}
    with policy.store._connection() as db:
        if block == 'protected_revision': db.execute('UPDATE protected_policy SET revision=revision+1')
        elif block == 'managed_revision': db.execute('UPDATE managed_bulk_registry SET revision=revision+1')
        elif block == 'device_disabled': db.execute('UPDATE devices SET enabled=0 WHERE id=2')
        elif block == 'device_name': db.execute("UPDATE devices SET hostname='changed' WHERE id=2")
        elif block in {'pending', 'uncertain'}:
            db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,2,?,?,'2026-10-21T12:00:00Z','ADD')",
                       (str(uuid4()), IPv4Address('198.51.100.2').packed, 'QUEUED' if block == 'pending' else 'UNVERIFIED'))
        elif block == 'lease': db.execute("UPDATE operation_executor SET owner='synthetic',lease_until='2026-10-21T12:10:00Z'")
        elif block == 'paused': db.execute('UPDATE operation_executor SET mutations_suspended=1')
    if block == 'observed': policy.store.record_observed_shun(2, IPv4Address('198.51.100.2'), 'management')
    elif block == 'expired': clock[0] += timedelta(minutes=10)
    elif block == 'cancelled': policy.preparations.cancel(saved['plan_id'], 'alice')
    elif block == 'profiles': changes['addition_device_ids'] = frozenset({1})
    elif block == 'owner': changes['subject'] = 'bob'
    elif block == 'count': changes['accepted_count'] = 3
    elif block == 'gate': changes['enabled'] = False
    elif block == 'consent': changes['maintain_present'] = False
    before = dump(policy.store)
    with pytest.raises((ValueError, PermissionError)): confirm(bulk, proposal, **changes)
    assert dump(policy.store) == before


def test_late_audit_failure_rolls_back_root_members_policy_and_request_even_if_outer_commits(bulk, monkeypatch):
    policy, _ = bulk
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2')
    before = dump(policy.store)
    original = policy.store._insert_event

    def fail(db, kind, *args, **kwargs):
        if kind == 'MANAGED_BULK_IMPORT_CONFIRMED': raise sqlite3.OperationalError('Synthetic final audit failure')
        return original(db, kind, *args, **kwargs)

    monkeypatch.setattr(policy.store, '_insert_event', fail)
    with policy.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError): confirm(bulk, proposal, connection=db)
    assert dump(policy.store) == before


def test_concurrent_original_key_has_one_atomic_commit_and_other_key_cannot_reconfirm(bulk):
    policy, _ = bulk
    saved, proposal = prepare(bulk)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: confirm(bulk, proposal), range(3)))
    assert sum(not result['replayed'] for result in results) == 1
    assert policy.policy_page()['total'] == 1
    with pytest.raises(ValueError):
        policy.preparations.propose_bulk_intent(saved['plan_id'], 'alice', saved['digest'], str(uuid4()))
    no_work(policy)


def test_fixed_retirement_reserve_is_positive_and_revocation_works_with_admission_paused(bulk, monkeypatch):
    policy, _ = bulk
    assert bulk_policy.MAX_REQUESTS - bulk_policy.MAX_KEYS == 200000
    monkeypatch.setattr(bulk_policy, 'MAX_KEYS', 2)
    monkeypatch.setattr(bulk_policy, 'MAX_REQUESTS', 4)
    _, proposal = prepare(bulk, '198.51.100.1\n198.51.100.2')
    confirm(bulk, proposal)
    _, noop = prepare(bulk, '198.51.100.1\n198.51.100.2')
    confirm(bulk, noop)
    _, refused = prepare(bulk)
    before = dump(policy.store)
    with pytest.raises(ManagedCapacity): confirm(bulk, refused)
    assert dump(policy.store) == before
    with policy.store._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    assert retire(bulk)['changed_targets'] == 1
    assert retire(bulk, [(1, IPv4Address('198.51.100.2'))])['changed_targets'] == 1
    assert not any(row['enabled'] for row in policy.policy_page()['entries'])
    with policy.store._connection() as db: assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 4
    no_work(policy)


def test_frozen_retirement_all_or_nothing_and_original_key_replay_never_reenables(bulk):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict): retire(bulk, [(1, IPv4Address('198.51.100.1')), (1, IPv4Address('198.51.100.2'))])
    assert dump(policy.store) == before
    key = str(uuid4())
    receipt = retire(bulk, key=key)
    before = dump(policy.store)
    assert retire(bulk, key=key, revision=1) == {**receipt, 'replayed': True}
    assert dump(policy.store) == before


def test_immutable_sealed_membership_and_partial_schema_are_not_repaired(bulk):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    with policy.store._connection() as db:
        for sql in ("UPDATE managed_bulk_members SET classification='PROPOSE_ADOPT'", 'DELETE FROM managed_bulk_members',
                    'UPDATE managed_bulk_manifests SET accepted_count=1', 'DELETE FROM managed_bulk_manifests',
                    'UPDATE managed_bulk_registry SET restoration_suspended=0',
                    'INSERT INTO managed_bulk_members SELECT * FROM managed_bulk_members'):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
        db.execute('ALTER TABLE managed_bulk_members RENAME COLUMN classification TO broken')
    before = dump(policy.store)
    with pytest.raises(BulkUnavailable): policy.policy_page()
    with pytest.raises(BulkUnavailable): policy.page(proposal['operation_id'], 'alice')
    with pytest.raises(BulkUnavailable): policy.initialize_empty()
    assert dump(policy.store) == before


def test_owner_paging_and_revision_guards_never_change_authority(bulk):
    policy, _ = bulk
    text = '\n'.join(str(IPv4Address(0xC6120000 + i)) for i in range(251))
    _, proposal = prepare(bulk, text)
    result = confirm(bulk, proposal)
    before = dump(policy.store)
    assert [len(policy.page(result['operation_id'], 'alice', page=page)['targets']) for page in (1,2,3)] == [100,100,51]
    assert [len(policy.policy_page(page, revision=1)['entries']) for page in (1,2,3)] == [100,100,51]
    assert policy.list_for_owner('bob')['items'] == []
    with pytest.raises(BulkUnavailable): policy.page(result['operation_id'], 'bob')
    with pytest.raises(ManagedConflict): policy.policy_page(revision=0)
    for page in (0, True, 4):
        with pytest.raises(ValueError): policy.policy_page(page)
    assert dump(policy.store) == before


@pytest.mark.parametrize('changes', [{'roles': ('Viewer',)}, {'roles': ('Operator', 'Operator')}, {'roles': ('Operator', {})},
    {'enabled': 'yes'}, {'maintain_present': 'yes'}, {'accepted_count': True}, {'addition_device_ids': frozenset({True})}])
def test_strict_current_identity_consent_capability_and_counts_do_not_write(bulk, changes):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    before = dump(policy.store)
    with pytest.raises((ValueError, PermissionError)): confirm(bulk, proposal, **changes)
    assert dump(policy.store) == before


@pytest.mark.parametrize('quota', ['keys', 'roots', 'members'])
def test_retained_capacity_overflow_is_whole_scope_and_keeps_stopped_keys(bulk, monkeypatch, quota):
    policy, _ = bulk
    _, first = prepare(bulk)
    confirm(bulk, first)
    retire(bulk)
    _, next_proposal = prepare(bulk, '198.51.100.2')
    monkeypatch.setattr(bulk_policy, {'keys':'MAX_KEYS', 'roots':'MAX_ROOTS', 'members':'MAX_MEMBERS'}[quota], 1)
    before = dump(policy.store)
    with pytest.raises(ManagedCapacity): confirm(bulk, next_proposal)
    assert dump(policy.store) == before


def test_policy_retirement_preserves_uncertainty_and_never_permits_regrant(bulk):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    job = str(uuid4())
    with policy.store._connection() as db:
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'UNVERIFIED','2026-10-21T12:00:00Z','ADD')",
                   (job, IPv4Address('198.51.100.1').packed))
    assert retire(bulk)['changed_targets'] == 1
    with policy.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job,)).fetchone()[0] == 'UNVERIFIED'
    _, next_proposal = prepare(bulk)
    before = dump(policy.store)
    with pytest.raises(ManagedConflict): confirm(bulk, next_proposal)
    assert dump(policy.store) == before


def test_same_count_retained_classification_corruption_is_not_historical_success(bulk):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    confirm(bulk, proposal)
    with policy.store._connection() as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='managed_bulk_member_immutable'").fetchone()[0]
        db.execute('DROP TRIGGER managed_bulk_member_immutable')
        db.execute("UPDATE managed_bulk_members SET classification='PROPOSE_ADOPT'")
        db.execute(sql)
    before = dump(policy.store)
    with pytest.raises(ValueError): policy.page(proposal['operation_id'], 'alice')
    with pytest.raises(ValueError): confirm(bulk, proposal)
    assert dump(policy.store) == before


def test_maximum_100000_pairs_persist_without_jobs_and_survive_restart_pruning_and_paged_reads(bulk):
    policy, clock = bulk
    text = '\n'.join(str(IPv4Address(0xC6120000 + i)) for i in range(10000))
    _, proposal = prepare(bulk, text, tuple(range(1,11)))
    result = confirm(bulk, proposal)
    assert result['accepted_pairs'] == result['changed_targets'] == 100000
    clock[0] += timedelta(minutes=10)
    assert policy.preparations.prune_expired() == 1
    restarted = BulkPolicies(Store(policy.store.path), clock=lambda: clock[0])
    for page in (1, 501, 1000):
        assert len(restarted.page(result['operation_id'], 'alice', page=page)['targets']) == 100
        current = restarted.policy_page(page, revision=1)
        assert current['total'] == 100000 and current['pages'] == 1000 and len(current['entries']) == 100
    with policy.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_shun_requests').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM managed_shun_targets').fetchone()[0] == 100000
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_members').fetchone()[0] == 100000
    assert confirm((restarted, clock), proposal)['replayed']
    no_work(policy)
