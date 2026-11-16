"""Configured ranges exclude ADD and use normal verified unblock scheduling."""

import asyncio
import json
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_policy import bulk as bulk_fixture
from test_bulk_policy import confirm, prepare
from test_synchronizer import AutoRemovingAgent, _store

from ftd_shun_manager.agent_protocol import ObservedShun
from ftd_shun_manager.environment_protection import VARIABLE, EnvironmentProtection
from ftd_shun_manager.import_intent import canonical_import
from ftd_shun_manager.import_preview import classify_targets, parse_blocklist, summarize_preview
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import OperationQueue
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Store
from ftd_shun_manager.synchronizer import Synchronizer
from ftd_shun_manager.web import Identity, templates

bulk = bulk_fixture


@pytest.mark.parametrize('text', ['10.0.0.1/8', '10/8', '::1', '10.0.0.0/08', '10.0.0.0/33',
    '10.0.0.0/8,', '010.0.0.1', ',10.0.0.0/8', ','.join(['10.0.0.0/8'] * 65)])
def test_invalid_configuration_never_silently_disables_protection(text):
    with pytest.raises(ValueError, match=VARIABLE):
        EnvironmentProtection.parse(text)


def test_boundaries_exact_addresses_and_restart_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, '10.0.0.0/8,192.168.0.0/16,198.51.100.251')
    store = Store(tmp_path / 'state.db')
    for ip in ('10.0.0.0', '10.255.255.255', '192.168.1.1', '198.51.100.251'):
        assert store.environment_protection.contains(ip)
    for ip in ('11.0.0.0', '192.169.0.0', '198.51.100.250'):
        assert not store.environment_protection.contains(ip)
    monkeypatch.setenv(VARIABLE, '')
    assert store.environment_protection.contains('10.1.1.1')  # immutable until restart
    assert not Store(store.path).environment_protection.contains('10.1.1.1')
    assert EnvironmentProtection.parse('0.0.0.0/0').contains('255.255.255.255')


def test_preview_explains_env_configuration_and_never_expands_networks(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, '10.0.0.0/8')
    store = _store(tmp_path)
    parsed = parse_blocklist('10.1.2.3\n198.51.100.251')
    report = summarize_preview(parsed, classify_targets(store, [IPv4Address(ip) for ip in parsed['ips']], [1]))
    assert report['rows'][0]['status'] == 'Protected'
    assert VARIABLE in report['rows'][0]['reason'] and '.env' in report['rows'][0]['reason']
    assert report['rows'][1]['status'] == 'Ready'
    assert ProtectedPolicy(store).snapshot()['entries'] == []  # separate from editable exact IPs


def test_bulk_admission_skips_configured_ips_and_retirement_does_not_resume(bulk, monkeypatch):
    policy, _ = bulk
    # Activate protection on a fresh process/store over the same disposable DB.
    monkeypatch.setenv(VARIABLE, '198.51.100.1')
    policy.store.environment_protection = EnvironmentProtection.from_environment()
    _saved, proposal = prepare(bulk, text='198.51.100.1\n198.51.100.2')
    assert proposal['manifest']['classification_counts']['EXCLUDED_PROTECTED'] == 1
    confirm(bulk, proposal)
    with policy.store._connection() as db:
        assert [str(IPv4Address(row[0])) for row in db.execute('SELECT ip FROM managed_shun_targets WHERE enabled=1')] == ['198.51.100.2']
    monkeypatch.setenv(VARIABLE, '198.51.100.2')
    restarted = Store(policy.store.path)
    protection = ProtectedPolicy(restarted)
    protection.retire_environment_managed()
    monkeypatch.setenv(VARIABLE, '')
    with Store(restarted.path)._connection() as db:
        assert not db.execute('SELECT 1 FROM managed_shun_targets WHERE enabled=1').fetchone()


@pytest.mark.parametrize('fail', [False, True])
def test_detected_address_is_unblocked_with_distinct_committed_logs(tmp_path, monkeypatch, capsys, fail):
    monkeypatch.setenv(VARIABLE, '10.0.0.0/8')
    store = _store(tmp_path)
    target = IPv4Address('10.1.2.3')
    agent = AutoRemovingAgent([ObservedShun(target, 'management')], fail=fail)
    sync = Synchronizer(store, agent, 300, 60)
    asyncio.run(sync._sweep())
    assert agent.removals == [(1, target)]
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
    detected = next(row for row in messages if row['event'] == 'environment_protection.shun_detected')
    assert detected['network'] == '10.0.0.0/8' and detected['ip'] == str(target)
    result = next(row for row in messages if row['event'] == 'environment_protection.unblock_result')
    assert result['outcome'] == ('UNVERIFIED' if fail else 'VERIFIED')
    events = store.list_events(target)
    assert any(event['actor_subject'] == 'system:environment-ip-policy' for event in events)
    assert not ProtectedPolicy(store).snapshot()['entries']


def test_removing_configuration_cancels_unstarted_policy_removals(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, '10.0.0.0/8')
    store = _store(tmp_path)
    target = IPv4Address('10.1.2.3')
    sync = Synchronizer(store, AutoRemovingAgent(), 300, 60)
    sync._publish_snapshot(1, [ObservedShun(target, 'management')])
    sync._admit_trusted(1, [target])
    sync.queue.cancel_obsolete_policy()
    assert sync.queue.has_target(1, target)
    monkeypatch.setenv(VARIABLE, '')
    queue = OperationQueue(Store(store.path))
    queue.cancel_obsolete_policy()
    assert not queue.has_target(1, target)


def test_missing_device_status_renders_a_partial_status_without_500():
    html = templates.get_template('refresh-panel.html').render(
        refresh={}, identity=Identity('viewer', 'Viewer', ('Viewer',)), csrf_token='fixture')
    assert 'Service status' in html


def test_new_guard_prevents_confirmation_of_an_older_import_review(bulk, monkeypatch):
    policy, _ = bulk
    _, proposal = prepare(bulk)
    monkeypatch.setenv(VARIABLE, '198.51.100.0/24')
    policy.store.environment_protection = EnvironmentProtection.from_environment()
    with pytest.raises(ManagedConflict):
        confirm(bulk, proposal)
    with policy.store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_bulk_manifests').fetchone()[0] == 0


def test_queued_add_is_cancelled_before_claim_when_configuration_becomes_protective(tmp_path, monkeypatch):
    store = _store(tmp_path)
    queue = OperationQueue(store)
    queue.initialize()
    target = IPv4Address('10.1.2.3')
    targets = [(1, target)]
    key = str(uuid4())
    queue.enqueue(key, targets, 'alice', 'Alice', ('Operator',), source='manual_import', scope='import',
                  policy_revision=0, confirmation_digest=canonical_import(targets, 0)[2])
    monkeypatch.setenv(VARIABLE, '10.0.0.0/8')
    restarted = OperationQueue(Store(store.path))
    owner = str(uuid4())
    assert restarted.claim_cycle(owner, 120)
    assert restarted.claim_addition(1, owner, restarted.cutoff(), execution_enabled=True) is None
    with restarted.store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs').fetchone()[0] == 'FAILED'
