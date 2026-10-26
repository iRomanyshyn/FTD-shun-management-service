"""Fenced standing admission on disposable SQLite/ASGI, never lab activation."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest
from test_bulk_cancellations import seed_job
from test_bulk_confirmation import bulk as bulk_fixture
from test_bulk_confirmation import cancellation_controls as cancellation_fixture
from test_bulk_confirmation import composition as composition_fixture
from test_bulk_confirmation import dispatch as dispatch_fixture
from test_bulk_confirmation import journal as journal_fixture
from test_bulk_confirmation import leases as leases_fixture
from test_bulk_confirmation import prepare_review
from test_bulk_confirmation import ten_device_composition as ten_fixture
from test_bulk_confirmation import waits as waits_fixture
from test_bulk_ordered_waits import ordered as ordered_fixture
from test_bulk_ordered_waits import reserve
from test_bulk_ordered_waits import review as ordered_review
from test_bulk_policy import dump, prepare, retire
from test_bulk_preparation_web import surface_for
from test_device_leases import acquire, claim, discover, grant

from ftd_shun_manager import bulk_waits, web
from ftd_shun_manager.agent_protocol import AdditionResult
from ftd_shun_manager.api import create_app
from ftd_shun_manager.bulk_cancellations import BulkCancellations
from ftd_shun_manager.bulk_dispatch import BulkCandidate, BulkDispatch
from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.bulk_preparation_view import operation_key
from ftd_shun_manager.managed_restoration import CompleteSnapshot
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.store import Store

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
composition = composition_fixture
dispatch = dispatch_fixture
journal = journal_fixture
leases = leases_fixture
waits = waits_fixture
ten_device_composition = ten_fixture
ordered = ordered_fixture
WEB, API = '/managed-imports/v2', '/api/v2/managed-imports/'


@pytest.fixture
def surface(composition, monkeypatch): return surface_for(composition, monkeypatch)


def confirm_concurrent(bulk, proposed, *, suspended=True, subject='alice', **changes):
    return bulk[0].confirm_concurrent(proposed['canonical'], proposed['digest'], proposed['manifest']['accepted_count'],
        subject, 'Actual operator', ('Operator',), expected_suspended=suspended, enabled=True,
        maintain_present=True, addition_device_ids=frozenset(proposed['manifest']['device_ids']), **changes)


def grants(store):
    with store._connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM managed_shun_targets ORDER BY device_id,ip')]


def test_active_fenced_add_continues_new_policy_requires_its_own_fresh_read_and_claim(composition, bulk, leases, surface):
    grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    original = claim(queue)
    old_snapshot = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    bulk[1][0] += timedelta(seconds=1)
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), concurrent_api=True, concurrent_web=True) as (client, calls, _):
            location, page, fields = await prepare_review(client, text='198.51.100.55')
            assert 'alongside active work' in page.text and 'already active when reviewed' in page.text
            result = await client.post(WEB + '/confirm', data=fields)
            assert result.status_code == 200 and 'desired execution was already active' in result.text, result.text[:500]
            key = operation_key(location.split('/')[-1])
            assert (await client.get(f'{WEB}/receipts/{key}')).status_code == 200
            with composition[1]._connection() as db:
                assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 1
                assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (original['id'],)).fetchone()[0] == 'RUNNING'
            submitted = [json.loads(body) for _, path, body in calls if path == API + 'confirm-concurrent']
            assert len(submitted) == 1 and submitted[0]['expected_suspended'] is False
            assert not composition[3]._wake.is_set()
    asyncio.run(scenario())
    assert queue.finish_addition(original['id'], token.owner, AdditionResult(True, 'management')) == 'VERIFIED'
    target = next(row for row in grants(composition[1]) if row['ip'] == IPv4Address('198.51.100.55').packed)
    candidate = BulkCandidate(1, IPv4Address('198.51.100.55'), target['intent_id'], target['generation'], target['authorization_request_id'], target['revision'])
    with pytest.raises(QueueConflict):
        BulkDispatch(composition[1], queue).admit(old_snapshot, (candidate,), token.owner, 2, 0, enabled=True, addition_device_ids=frozenset({1}))
    same_millisecond = CompleteSnapshot(str(uuid4()), 1, bulk[1][0], bulk[1][0], frozenset())
    with pytest.raises(QueueConflict):
        BulkDispatch(composition[1], queue).admit(same_millisecond, (candidate,), token.owner, 2, 0, enabled=True, addition_device_ids=frozenset({1}))
    bulk[1][0] += timedelta(seconds=1)
    assert discover(bulk, queue) == 1
    added = claim(queue)
    assert added['ip'] == IPv4Address('198.51.100.55').packed
    assert queue.finish_addition(added['id'], token.owner, AdditionResult(True, 'management')) == 'VERIFIED'
    leases.release(token)
    assert not composition[2].seen


@pytest.mark.parametrize('suspended', [True, False])
def test_independent_observation_lease_does_not_need_global_quiescence(composition, bulk, leases, suspended):
    if not suspended: grant(bulk, devices=(2,))
    token, _ = acquire(leases)
    _, proposal = prepare(bulk, '198.51.100.55')
    with pytest.raises(ManagedConflict):
        bulk[0].confirm(proposal['canonical'], proposal['digest'], 1, 'alice', 'Operator', ('Operator',),
                        enabled=True, maintain_present=True, addition_device_ids=frozenset({1}))
    before = leases.status()['devices']
    result = confirm_concurrent(bulk, proposal, suspended=suspended)
    assert result['admission_mode'] == 'fenced' and result['restoration_suspended'] is suspended
    assert result['device_work_admitted'] is False and leases.status()['devices'] == before
    leases.release(token)


@pytest.mark.parametrize('problem', ['pending_add', 'pending_remove', 'failed', 'unknown', 'device_unknown', 'unattributed', 'expired', 'attention', 'future', 'pause', 'suspension'])
def test_one_selected_conflict_refuses_all_members_without_touching_original_work(composition, bulk, leases, problem):
    grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    text = '198.51.100.1\n198.51.100.55'
    if problem == 'pending_remove':
        queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
        seed_job(composition[1], state='QUEUED', action='REMOVE')
    if problem in {'failed', 'unknown', 'device_unknown'}:
        queue.finish_addition(job['id'], token.owner, 'FAILED' if problem == 'failed' else 'UNVERIFIED')
        if problem == 'device_unknown': text = '198.51.100.55'
    if problem == 'unattributed':
        seed_job(composition[1], state='VERIFIED', ip=IPv4Address('198.51.100.55'))
        text = '198.51.100.55'
    if problem in {'expired', 'attention'}:
        bulk[1][0] += timedelta(seconds=136)
        if problem == 'attention': assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    if problem == 'future':
        with composition[1]._connection() as db:
            db.execute("UPDATE managed_bulk_device_executors SET updated_at='2099-01-01T00:00:00.000Z' WHERE device_id=1")
    if problem == 'pause':
        with composition[1]._connection() as db: db.execute('UPDATE operation_executor SET mutations_suspended=1')
    if problem in {'expired', 'attention', 'future', 'pause', 'suspension'}: text = '198.51.100.55'
    _, proposed = prepare(bulk, text)
    before = dump(composition[1])
    with pytest.raises(ManagedConflict): confirm_concurrent(bulk, proposed, suspended=problem == 'suspension')
    assert dump(composition[1]) == before


def test_unknown_on_unselected_device_retains_evidence_without_blocking_independent_scope(composition, bulk, leases):
    grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, 'UNVERIFIED')
    leases.release(token)
    _, proposed = prepare(bulk, '198.51.100.55', devices=(2,))
    result = confirm_concurrent(bulk, proposed, suspended=False)
    assert result['changed_targets'] == 1
    with composition[1]._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'UNVERIFIED'
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 1


@pytest.mark.parametrize('same_pair', [True, False])
def test_retained_ordered_cleanup_is_a_pair_barrier_even_after_add_finishes(composition, bulk, leases, ordered, same_pair):
    grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    reserve(ordered, ordered_review(ordered, bulk, device=1))
    queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    _, proposed = prepare(bulk, '198.51.100.1' if same_pair else '198.51.100.55')
    before = dump(composition[1])
    if same_pair:
        with pytest.raises(ManagedConflict, match='ordered cleanup'): confirm_concurrent(bulk, proposed, suspended=False)
        assert dump(composition[1]) == before
    else: assert confirm_concurrent(bulk, proposed, suspended=False)['changed_targets'] == 1
    leases.release(token)


def test_lease_expiring_during_whole_scope_apply_rolls_back_even_in_caught_outer_transaction(composition, bulk, leases, monkeypatch):
    acquire(leases, seconds=5)
    _, proposed = prepare(bulk, '198.51.100.55\n198.51.100.56')
    original = bulk[0]._apply_members
    def expire(*args):
        original(*args)
        bulk[1][0] += timedelta(seconds=6)
    monkeypatch.setattr(bulk[0], '_apply_members', expire)
    before = dump(composition[1])
    with composition[1]._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(ManagedConflict, match='fence'): confirm_concurrent(bulk, proposed, connection=db)
    assert dump(composition[1]) == before


def test_concurrent_requests_share_revision_cas_and_original_key_never_reenables(composition, bulk, leases):
    token, _ = acquire(leases)
    proposals = [prepare(bulk, f'198.51.100.{i}', subject=subject)[1] for i, subject in ((55, 'alice'), (56, 'bob'))]
    def run(args):
        proposed, subject = args
        try: return confirm_concurrent(bulk, proposed, subject=subject)
        except ManagedConflict: return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, zip(proposals, ('alice', 'bob'), strict=True)))
    assert sum(result is not None for result in results) == 1
    winner = results.index(next(result for result in results if result is not None))
    row = grants(composition[1])[0]
    subject = ('alice', 'bob')[winner]
    # Policy-only retirement does not require quiescence; replay stays historical.
    retire(bulk, [(row['device_id'], IPv4Address(row['ip']))])
    before = dump(composition[1])
    assert confirm_concurrent(bulk, proposals[winner], subject=subject)['replayed']
    assert dump(composition[1]) == before
    with pytest.raises(ManagedConflict, match='mode'):
        bulk[0].confirm(proposals[winner]['canonical'], proposals[winner]['digest'], 1, subject, 'Actual operator', ('Operator',),
                        enabled=True, maintain_present=True, addition_device_ids=frozenset({1}))
    leases.release(token)


@pytest.mark.parametrize('bad', [True, 1, 'true'])
def test_factory_concurrent_capability_cannot_initialize_or_bypass_standing_scope(tmp_path, bad):
    store = Store(tmp_path/'absent.db')
    with pytest.raises(ValueError): create_app(store=store, bulk_policy_concurrent_enabled=bad)
    assert not store.path.exists()
    with pytest.raises(ValueError): web.create_app(bulk_policy_concurrent_enabled=bad)


def test_bare_bulk_profile_cannot_gain_concurrent_authority(bulk):
    _, proposed = prepare(bulk)
    before = dump(bulk[0].store)
    with pytest.raises(BulkUnavailable): confirm_concurrent(bulk, proposed)
    assert dump(bulk[0].store) == before


@pytest.mark.parametrize('bad', ['missing', 'boolean', 'extra', 'header', 'disabled'])
def test_private_concurrent_route_binds_exact_expected_suspension_and_independent_capability(composition, bulk, bad):
    _, proposed = prepare(bulk)
    settings, store, agent, controller = composition
    app = create_app(settings, store, agent, continuous_dispatcher=controller,
        bulk_policy_admission_enabled=True, bulk_policy_device_ids=frozenset({1}), bulk_policy_concurrent_enabled=bad!='disabled')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:
            body = {'canonical': proposed['canonical'], 'digest': proposed['digest'], 'accepted_count': 1,
                'maintain_present': True, 'expected_suspended': True,
                'actor': {'subject': 'alice', 'display_name': 'Actual operator', 'roles': ['Operator']}}
            headers = {'Idempotency-Key': proposed['operation_id']}
            if bad == 'missing': body.pop('expected_suspended')
            if bad == 'boolean': body['expected_suspended'] = 1
            if bad == 'extra': body['concurrent'] = True
            if bad == 'header': headers['Idempotency-Key'] = str(uuid4())
            before = dump(store)
            response = await client.post(API+'confirm-concurrent', json=body, headers=headers)
            assert response.status_code == (503 if bad=='disabled' else 422) and dump(store) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('local', [False, True])
def test_new_web_capability_is_independent_and_mode_is_server_frozen(composition, bulk, leases, surface, local):
    acquire(leases)
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), concurrent_api=True, concurrent_web=local) as (client, calls, _):
            _, page, fields = await prepare_review(client)
            assert 'alongside active work' in page.text
            before = dump(composition[1])
            response = await client.post(WEB+'/confirm', data=fields)
            assert response.status_code == (200 if local else 503), response.text[:400]
            if not local:
                assert dump(composition[1]) == before
                assert not any(path in {API+'confirm', API+'confirm-concurrent'} for _, path, _ in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage', ['lost', 'mode', 'suspension', 'boolean', 'metadata_drift'])
def test_unknown_receipt_or_mode_drift_preserves_original_frozen_route_and_key(composition, bulk, leases, surface, damage):
    changed, drift = [False], [False]
    acquire(leases)
    def transform(request, response):
        if damage == 'metadata_drift' and drift[0] and request.url.path == '/api/v1/status':
            value = response.json(); value['bulk_policy_concurrent_enabled'] = False
            return httpx.Response(200, json=value)
        if request.url.path != API+'confirm-concurrent' or changed[0]: return response
        changed[0] = True
        if damage == 'lost': raise httpx.ReadTimeout('Synthetic lost post-commit reply', request=request)
        value = response.json()
        if damage == 'mode': value.pop('admission_mode')
        if damage == 'suspension': value['restoration_suspended'] = False
        if damage == 'boolean': value['restoration_suspended'] = 1
        return httpx.Response(200, json=value)
    async def scenario():
        async with surface(policy_api=True, policy_web=True, profile_ids=frozenset({1}), concurrent_api=True, concurrent_web=True, transform=transform) as (client, calls, _):
            _, _, fields = await prepare_review(client)
            drift[0] = True
            response = await client.post(WEB+'/confirm', data=fields)
            assert response.status_code == 503 and fields['review'] in response.text
            if damage == 'metadata_drift': assert not any(path == API+'confirm' or path == API+'confirm-concurrent' for _, path, _ in calls)
            else:
                before = dump(composition[1])
                replay = await client.post(WEB+'/confirm', data=fields)
                assert replay.status_code == 200 and 'Original-key replay' in replay.text and dump(composition[1]) == before
    asyncio.run(scenario())


def test_maximum_concurrent_scope_keeps_existing_lease_and_does_not_create_jobs(ten_device_composition, bulk, monkeypatch):
    composition = ten_device_composition
    leases = composition[3].runner.leases
    token, _ = acquire(leases, seconds=300)
    async def scenario():
        async with surface_for(composition, monkeypatch)(policy_api=True, policy_web=True, profile_ids=frozenset(range(1,11)),
                concurrent_api=True, concurrent_web=True) as (client, _, _):
            location, _, fields = await prepare_review(client, text='\n'.join(f'198.18.{i//256}.{i%256}' for i in range(10000)), devices=tuple(str(i) for i in range(1,11)))
            before = leases.status()['devices']
            response = await client.post(WEB+'/confirm', data=fields)
            assert response.status_code == 200 and '100000 accepted pairs' in response.text, response.text[:500]
            assert leases.status()['devices'] == before
            assert (await client.get(WEB+'/receipts/'+operation_key(location.split('/')[-1])+'?page=1000')).status_code == 200
    asyncio.run(scenario())
    with composition[1]._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM operation_jobs').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_members').fetchone()[0] == 100000
    leases.release(token)


def test_failed_attempt_stays_a_pair_latch_after_retirement_and_queue_retention(composition, bulk, leases):
    grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    queue.finish_addition(job['id'], token.owner, 'FAILED')
    leases.release(token)
    retire(bulk)
    bulk[1][0] += timedelta(days=367)
    composition[3].runner.queue.prune_completed(366)
    with composition[1]._connection() as db:
        assert db.execute('SELECT 1 FROM operation_jobs WHERE id=?', (job['id'],)).fetchone() is None
    _, proposed = prepare(bulk)
    before = dump(composition[1])
    with pytest.raises(ManagedConflict): confirm_concurrent(bulk, proposed, suspended=False)
    assert dump(composition[1]) == before


@pytest.mark.parametrize('same_pair', [True, False])
def test_missing_cancellation_settlement_is_not_inferred_from_a_terminal_add(composition, bulk, leases, monkeypatch, same_pair):
    root = grant(bulk, devices=(1,))
    token, queue = acquire(leases)
    assert discover(bulk, queue) == 1
    job = claim(queue)
    controls = BulkCancellations(composition[1], clock=bulk[0].clock)
    review = controls.review(root, 'alice', ('Operator',))
    controls.cancel(root, review['reviewed_at'], review['review_digest'], 1, 'alice', 'Actual operator', ('Operator',))
    monkeypatch.setattr(bulk_waits, 'settle_result', lambda *_: None)  # Incompatible old-writer gap, not resolution.
    queue.finish_addition(job['id'], token.owner, AdditionResult(True, 'management'))
    _, proposed = prepare(bulk, '198.51.100.1' if same_pair else '198.51.100.55')
    before = dump(composition[1])
    if same_pair:
        with pytest.raises(ManagedConflict): confirm_concurrent(bulk, proposed, suspended=False)
        assert dump(composition[1]) == before
    else: assert confirm_concurrent(bulk, proposed, suspended=False)['changed_targets'] == 1
    with composition[1]._connection() as db:
        assert db.execute('SELECT 1 FROM managed_bulk_wait_results').fetchone() is None
    leases.release(token)
