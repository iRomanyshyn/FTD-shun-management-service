"""API crash after completed v7 END, using disposable DB/journal peers only."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_batch_session import states, visit
from test_bulk_policy import dump
from test_deferred_worker import Agent, runner
from test_deferred_worker import runtime as runtime_fixture
from test_pending_confirmation import read, stage
from test_pending_execution import bulk as bulk_fixture
from test_pending_execution import cancellation_controls as cancellation_fixture
from test_pending_execution import dispatch as dispatch_fixture
from test_pending_execution import execution as execution_fixture
from test_pending_execution import journal as journal_fixture
from test_pending_execution import leases as leases_fixture
from test_pending_execution import ledger as ledger_fixture
from test_pending_execution import waits as waits_fixture

from ftd_shun_manager import pending_restart
from ftd_shun_manager.agent_client import AgentUnavailable
from ftd_shun_manager.device_leases import DeviceLeases
from ftd_shun_manager.operation_queue import QueueConflict
from ftd_shun_manager.pending_execution import PendingExecution
from ftd_shun_manager.pending_restart import PendingRestart, prepare

bulk = bulk_fixture
cancellation_controls = cancellation_fixture
dispatch = dispatch_fixture
execution = execution_fixture
journal = journal_fixture
leases = leases_fixture
ledger = ledger_fixture
waits = waits_fixture
runtime = runtime_fixture


@pytest.mark.parametrize('proof', ['complete', 'missing', 'foreign', 'corrupt'])
def test_real_agent_process_restart_uses_persisted_proof_without_cisco(crash, tmp_path, proof):
    """Optional cross-language acceptance, explicitly using built local binaries.

    The seed runs only a cfg(test) Rust helper through the actual Sessions writer;
    the production binary has no seeding switch or test-only fixture code.
    """
    import os
    import subprocess
    import time
    from pathlib import Path

    from ftd_shun_manager.agent_client import UnixAgentClient

    binary = os.environ.get('FTD_TEST_AGENT_BINARY')
    seed = os.environ.get('FTD_TEST_AGENT_JOURNAL_SEED')
    if not binary or not seed:
        pytest.skip('Set FTD_TEST_AGENT_BINARY and FTD_TEST_AGENT_JOURNAL_SEED for real-agent acceptance')
    _, jobs, receipt, recovery = crash
    directory = tmp_path / 'agent-private'
    directory.mkdir(mode=0o700)
    scope = {'device': receipt.device_id, 'id': list(receipt.session_id), 'sequence': receipt.sequence,
             'targets': [str(ack.ip) for ack in receipt.acknowledgements]}
    if proof == 'foreign':
        scope['targets'][0] = '198.51.100.200'
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith('FTD_')}
    if proof != 'missing':
        subprocess.run([seed, '--exact', 'pending_journal::tests::subprocess_write', '--ignored'],
            env={**clean_env, 'FTD_TEST_PENDING_JOURNAL': str(directory),
                 'FTD_TEST_PENDING_SCOPE': json.dumps(scope)}, check=True, capture_output=True, timeout=10)
    if proof == 'corrupt':
        (directory / 'pending-completions.bin').write_bytes(b'corrupt committed evidence')
    inventory = tmp_path / 'synthetic-agent.json'
    inventory.write_text(json.dumps([{'id': 1, 'hostname': 'synthetic-no-cisco', 'management_ip': '192.0.2.1',
        'ssh_host_key': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
        'allowed_interfaces': ['management']}]))
    password = tmp_path / 'synthetic-password'
    password.write_text('synthetic-only-never-used')
    # Keep AF_UNIX pathname below the system limit, independently of pytest IDs.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='ftd-journal-') as sockets:
        socket = str(Path(sockets) / 'agent.sock')
        environment = {**clean_env, 'FTD_SHUN_DEVICE_INVENTORY': str(inventory),
            'FTD_SHUN_SSH_USERNAME': 'synthetic', 'FTD_SHUN_SSH_PASSWORD_FILE': str(password),
            'FTD_SHUN_AGENT_SOCKET': socket, 'FTD_SHUN_AGENT_PEER_UID': str(os.getuid()),
            'FTD_SHUN_AGENT_CYCLES_ENABLED': 'true', 'FTD_SHUN_LARGE_SNAPSHOTS_ENABLED': 'true',
            'FTD_SHUN_AGENT_ADDITIONS_ENABLED': 'true', 'FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED': 'true',
            'FTD_SHUN_AGENT_BATCH_SESSION_VERSION': '7', 'FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED': 'true',
            'FTD_SHUN_AGENT_PENDING_JOURNAL_DIRECTORY': str(directory)}
        before = dump(recovery.store)
        # A corrupted committed record refuses startup without repairing it.
        if proof == 'corrupt':
            result = subprocess.run([binary], env=environment, capture_output=True, timeout=10, check=False)
            assert result.returncode != 0 and not Path(socket).exists()
            assert (directory / 'pending-completions.bin').read_bytes() == b'corrupt committed evidence'
            assert dump(recovery.store) == before
            return
        client = UnixAgentClient(socket, 2, large_snapshots=True, additions_enabled=True,
            addition_device_ids=frozenset({1}), settled_cycles=True, recoverable_cycles=True,
            tracked_cycles=True, batch_additions=True, batch_session_version=7, deferred_confirmation=True)
        baseline = (directory / 'pending-completions.bin').read_bytes() if proof != 'missing' else None
        for attempt in range(2):
            if attempt and Path(socket).exists():
                # Stale socket cleanup belongs to the restarted production agent.
                assert Path(socket).is_socket()
            with (tmp_path / f'agent-{attempt}.log').open('w+') as log:
                process = subprocess.Popen([binary], env=environment, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while 'agent.listener.ready' not in Path(log.name).read_text():
                        assert process.poll() is None
                        assert time.monotonic() < deadline
                        time.sleep(0.01)
                    if proof == 'complete':
                        assert client.pending_session_completed(receipt.device_id,
                            str(UUID(bytes=receipt.session_id)), receipt.sequence,
                            receipt.acknowledgements) == receipt
                        if attempt:
                            assert pending_restart.recover(recovery.store, 1, client)
                    else:
                        with pytest.raises(AgentUnavailable): pending_restart.recover(recovery.store, 1, client)
                        assert dump(recovery.store) == before
                finally:
                    process.kill()  # Hard restart, not graceful receipt reconstruction.
                    process.wait(timeout=5)
                assert 'agent.cycle.' not in Path(log.name).read_text()  # Lookup did not enter SSH.
        if proof == 'complete':
            assert recovery.inspect(1) is None
            with recovery.store._connection() as db:
                assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['AWAITING_CONFIRMATION'] * len(jobs)
                assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
                assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0
        if baseline is not None:
            assert (directory / 'pending-completions.bin').read_bytes() == baseline


@pytest.fixture
def crash(bulk, leases, execution):
    queue, jobs, receipt = stage(bulk, leases)
    prepare(queue, receipt.sequence)
    bulk[1][0] += timedelta(seconds=136)
    return queue, jobs, receipt, PendingRestart(execution.store, leases.queue)


def test_completed_journal_handoff_does_not_renew_or_attribute_creation(crash, bulk, execution, leases):
    _queue, jobs, receipt, recovery = crash
    checkpoint = recovery.inspect(1)
    assert checkpoint.jobs == tuple(job['id'] for job in jobs)
    with execution.store._connection() as db:
        original = list(map(tuple, db.execute("SELECT * FROM shun_events WHERE event_type IN "
                        "('SHUN_OPERATION_RUNNING','SHUN_ADDITION_ACKNOWLEDGED') ORDER BY id")))
        requests = list(map(tuple, db.execute('SELECT * FROM managed_shun_requests ORDER BY id')))
    session = recovery.complete(checkpoint, receipt)
    assert leases.status()['devices'][0]['state'] == 'IDLE'
    with execution.store._connection() as db:
        assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['AWAITING_CONFIRMATION'] * 2
        assert list(map(tuple, db.execute("SELECT * FROM shun_events WHERE event_type IN "
                    "('SHUN_OPERATION_RUNNING','SHUN_ADDITION_ACKNOWLEDGED') ORDER BY id"))) == original
        assert list(map(tuple, db.execute('SELECT * FROM managed_shun_requests ORDER BY id'))) == requests
        assert db.execute('SELECT COUNT(*) FROM shun_import_origins').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM shun_state').fetchone()[0] == 0
    assert recovery.inspect(1) is None
    before = dump(execution.store)
    with pytest.raises(QueueConflict): recovery.complete(checkpoint, receipt)
    assert dump(execution.store) == before
    bulk[1][0] += timedelta(seconds=1)
    token = leases.claim(1, str(uuid4()), 135, enabled=True)
    outcome = execution.confirm(token, session, read(bulk, present=('198.51.100.1',)), enabled=True)
    assert [state for _, state in outcome] == ['OBSERVED_PRESENT', 'CONFIRMED_ABSENT']
    leases.release(token)


def test_checkpoint_is_exact_idempotent_intent_and_live_lease_is_not_recovery(bulk, leases, execution):
    queue, jobs, receipt = stage(bulk, leases)
    recovery = PendingRestart(execution.store, leases.queue)
    before = dump(execution.store)
    assert recovery.inspect(1) is None
    assert dump(execution.store) == before
    prepare(queue, receipt.sequence)
    prepared = dump(execution.store)
    prepare(queue, receipt.sequence)
    assert dump(execution.store) == prepared
    with pytest.raises(QueueConflict): prepare(queue, receipt.sequence + 1)
    assert dump(execution.store) == prepared
    assert recovery.inspect(1) is None
    # Ordinary live handoff remains the strict original path.
    execution.await_confirmation(queue.token, receipt, tuple(job['id'] for job in jobs), enabled=True)
    assert recovery.inspect(1) is None


@pytest.mark.parametrize('fault', ['device', 'session', 'sequence', 'order', 'missing', 'untyped'])
def test_foreign_or_partial_terminal_receipt_never_changes_storage(crash, fault):
    _, _, receipt, recovery = crash
    checkpoint = recovery.inspect(1)
    if fault == 'device': receipt = replace(receipt, device_id=2)
    elif fault == 'session': receipt = replace(receipt, session_id=uuid4().bytes)
    elif fault == 'sequence': receipt = replace(receipt, sequence=receipt.sequence + 1)
    elif fault == 'order': receipt = replace(receipt, acknowledgements=receipt.acknowledgements[::-1])
    elif fault == 'missing': receipt = replace(receipt, acknowledgements=receipt.acknowledgements[:1])
    elif fault == 'untyped': receipt = True
    before = dump(recovery.store)
    with pytest.raises(QueueConflict): recovery.complete(checkpoint, receipt)
    assert dump(recovery.store) == before


@pytest.mark.parametrize('fault', ['inventory', 'disabled', 'checkpoint', 'duplicate', 'ack', 'unknown', 'owner', 'epoch'])
def test_changed_evidence_during_lookup_keeps_original_fence(crash, fault):
    queue, jobs, receipt, recovery = crash
    checkpoint = recovery.inspect(1)
    with recovery.store._connection() as db:
        if fault == 'inventory': db.execute("UPDATE devices SET hostname='changed' WHERE id=1")
        elif fault == 'disabled': db.execute('UPDATE devices SET enabled=0 WHERE id=1')
        elif fault == 'checkpoint':
            db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.sequence',99) WHERE event_type=?", (pending_restart.EVENT,))
        elif fault == 'duplicate':
            db.execute('''INSERT INTO shun_events SELECT ?,timestamp,event_type,device_id,ip,interface,actor_subject,
                actor_display_name,actor_roles_json,request_id,details_json FROM shun_events WHERE event_type=?''',
                       (str(uuid4()), pending_restart.EVENT))
        elif fault == 'ack':
            db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.sequence',99) WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'")
        elif fault == 'unknown':
            db.execute("UPDATE operation_jobs SET state='UNVERIFIED' WHERE id=?", (jobs[0]['id'],))
            db.execute("UPDATE managed_bulk_attempts SET state='UNVERIFIED',completed_at=requested_at WHERE job_id=?", (jobs[0]['id'],))
        else:
            # A legitimate sibling advances/releases the expired lease before
            # our lookup returns; the stale completion cannot touch its fence.
            db.execute("UPDATE managed_bulk_device_executors SET state='IDLE',owner=NULL,lease_until=NULL WHERE device_id=1")
            if fault == 'owner':
                db.execute("UPDATE managed_bulk_device_executors SET state='LEASED',epoch=epoch+1,owner=?,lease_until=? WHERE device_id=1",
                           (str(uuid4()), checkpoint.fence['lease_until']))
    before = dump(recovery.store)
    with pytest.raises((QueueConflict, ValueError)): recovery.complete(checkpoint, receipt)
    assert dump(recovery.store) == before
    assert queue.pending == [job['id'] for job in jobs]


def test_attention_and_unknown_results_are_never_reclassified(crash, leases):
    queue, _, receipt, recovery = crash
    checkpoint = recovery.inspect(1)
    assert leases.claim(1, str(uuid4()), 135, enabled=True) is None
    before = dump(recovery.store)
    assert recovery.inspect(1) is None
    with pytest.raises(QueueConflict): recovery.complete(checkpoint, receipt)
    assert dump(recovery.store) == before
    assert leases.status()['devices'][0]['state'] == 'ATTENTION'
    assert queue.pending


@pytest.mark.parametrize('phase', ['ledger', 'transition', 'audit'])
def test_local_failure_rolls_back_whole_handoff_without_expiring_original_jobs(crash, monkeypatch, phase):
    _, _, receipt, recovery = crash
    checkpoint = recovery.inspect(1)
    before = dump(recovery.store)
    if phase == 'ledger':
        from ftd_shun_manager.pending_confirmation import PendingConfirmations
        cls, name = PendingConfirmations, '_record'
    elif phase == 'transition': cls, name = PendingExecution, '_transition_awaiting'
    else: cls, name = DeviceLeases, '_event'
    original = getattr(cls, name)

    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise sqlite3.OperationalError('Synthetic interrupted persistence')

    with monkeypatch.context() as context:
        context.setattr(cls, name, fail)
        with pytest.raises(sqlite3.OperationalError): recovery.complete(checkpoint, receipt)
    assert dump(recovery.store) == before
    recovery.complete(checkpoint, receipt)  # Same exact local receipt; no device command.


def test_restart_hook_recovers_before_generic_lease_expiry_and_confirms_without_add(crash, bulk):
    _, _, receipt, recovery = crash
    agent = Agent()
    from ftd_shun_manager.agent_protocol import ObservedShun
    agent.entries[1] = [ObservedShun(ack.ip, 'outside') for ack in receipt.acknowledgements]
    lookups = []

    def lookup(device, owner, sequence, acks):
        lookups.append((device, owner, sequence, acks))
        return receipt

    agent.pending_session_completed = lookup
    service = runner(recovery.store, agent)
    asyncio.run(visit(service))
    assert len(lookups) == 1
    assert states(service) == {'AWAITING_CONFIRMATION': 2}
    assert service._results['1']['state'] == 'pending_recovered'
    assert not agent.seen
    bulk[1][0] += timedelta(seconds=1)
    asyncio.run(visit(service))
    assert len(lookups) == 1
    assert states(service) == {'OBSERVED_PRESENT': 2}
    assert not agent.writes
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'


@pytest.mark.parametrize('fault', ['missing', 'malformed', 'storage'])
def test_failed_restart_hook_never_falls_through_to_expiry_or_new_ssh(crash, monkeypatch, fault):
    _, _, receipt, recovery = crash
    agent = Agent()

    def lookup(*args):
        if fault == 'missing': raise AgentUnavailable('Synthetic journal entry unavailable')
        return replace(receipt, sequence=99) if fault == 'malformed' else receipt

    agent.pending_session_completed = lookup
    if fault == 'storage':
        monkeypatch.setattr(PendingRestart, 'complete', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('Synthetic busy')))
    before = dump(recovery.store)
    service = runner(recovery.store, agent)
    asyncio.run(visit(service))
    assert service._results['1']['state'] == 'held'
    assert not agent.seen and not agent.writes
    assert dump(recovery.store) == before


def test_preparation_failure_prevents_end_pending(runtime, monkeypatch):
    service, agent = runtime

    def fail(*_args):
        raise sqlite3.OperationalError('Synthetic checkpoint storage unavailable')

    monkeypatch.setattr('ftd_shun_manager.deferred_worker.prepare', fail)
    asyncio.run(visit(service))
    assert not any(step[0] == 'end_pending' for step in agent.trace)
    assert states(service) == {'UNVERIFIED': 12}


def test_full_visit_prefix_and_checkpoint_survive_retention_until_handoff(bulk, leases, execution):
    from test_batch_queue import acknowledge, result
    from test_device_leases import acquire, grant

    from ftd_shun_manager.bulk_discovery import BulkDiscovery
    from ftd_shun_manager.deferred_worker import DeferredDeviceOperationQueue

    grant(bulk, (1,), count=64)
    token, ordinary = acquire(leases)
    source = BulkDiscovery(execution.store, ordinary, enabled=True, addition_device_ids=frozenset({1}),
                           admission_limit=64, check_limit=256)
    assert source.discover(read(bulk), token.owner) == 16
    queue = DeferredDeviceOperationQueue(execution.store, token)
    sequence = 1
    for _ in range(3):
        prefix = [acknowledge(queue, step) for step in range(sequence, sequence + 16)]
        sequence += 16
        queue.finish_verified_group(token.owner, result(prefix), sequence)
        sequence += 1
        assert source.discover(read(bulk), token.owner) == 16
    pending = [acknowledge(queue, step) for step in range(sequence, sequence + 16)]
    sequence += 16
    prepare(queue, sequence)
    recovery = PendingRestart(execution.store, leases.queue)
    bulk[1][0] += timedelta(days=367)
    checkpoint = recovery.inspect(1)
    assert len(checkpoint.jobs) == 16
    before = dump(execution.store)
    queue.prune_completed(366)
    execution.store.prune_expired_history(366, reference_time=bulk[1][0])
    assert recovery.inspect(1) == checkpoint
    # History unrelated to the held visit may expire; every original member,
    # ACK, claim, requester and known prefix result remains available.
    assert dump(execution.store) != before
    from uuid import UUID

    from ftd_shun_manager.agent_protocol import SettledPendingAdditions

    receipt = SettledPendingAdditions(1, UUID(token.owner).bytes, sequence, checkpoint.acknowledgements)
    recovery.complete(checkpoint, receipt)
    with execution.store._connection() as db:
        assert dict(db.execute('SELECT state,COUNT(*) FROM operation_jobs GROUP BY state')) == {
            'VERIFIED': 48, 'AWAITING_CONFIRMATION': 16}
        assert [row[0] for row in db.execute("SELECT id FROM operation_jobs WHERE state='AWAITING_CONFIRMATION' ORDER BY seq")] == [job['id'] for job in pending]


@pytest.mark.parametrize('fault', ['missing_ack', 'duplicate_ack', 'sequence', 'changed_job', 'missing_prefix_result'])
def test_checkpoint_refuses_incomplete_or_substituted_pre_end_evidence(bulk, leases, execution, fault):
    queue, jobs, receipt = stage(bulk, leases)
    with execution.store._connection() as db:
        if fault == 'missing_ack': db.execute("DELETE FROM shun_events WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'")
        elif fault == 'duplicate_ack':
            db.execute('''INSERT INTO shun_events SELECT ?,timestamp,event_type,device_id,ip,interface,actor_subject,
                actor_display_name,actor_roles_json,request_id,details_json FROM shun_events
                WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED' LIMIT 1''', (str(uuid4()),))
        elif fault == 'sequence':
            db.execute("UPDATE shun_events SET details_json=json_set(details_json,'$.sequence',99) WHERE event_type='SHUN_ADDITION_ACKNOWLEDGED'")
        elif fault == 'changed_job':
            db.execute("UPDATE operation_jobs SET reason='changed' WHERE id=?", (jobs[0]['id'],))
            # A merely different diagnostic is legal before checkpoint, but
            # the original mutable requester binding still must be exact.
            db.execute('UPDATE operation_requests SET expires_at=requested_at WHERE id=(SELECT id FROM managed_bulk_attempts WHERE job_id=?)', (jobs[0]['id'],))
        elif fault == 'missing_prefix_result':
            claim = db.execute("SELECT * FROM shun_events WHERE event_type='SHUN_OPERATION_RUNNING' LIMIT 1").fetchone()
            details = json.loads(claim['details_json'])
            details['operation_id'] = str(uuid4())
            db.execute('''INSERT INTO shun_events VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                       (str(uuid4()), claim['timestamp'], claim['event_type'], claim['device_id'], claim['ip'],
                        claim['interface'], claim['actor_subject'], claim['actor_display_name'],
                        claim['actor_roles_json'], claim['request_id'], json.dumps(details)))
    before = dump(execution.store)
    with pytest.raises(ValueError): prepare(queue, receipt.sequence)
    assert dump(execution.store) == before


@pytest.mark.parametrize('state', ['complete', 'unknown', 'foreign'])
def test_restart_recovery_uses_real_bound_seqpacket_receipt(crash, tmp_path, state):
    from test_session_completion_lookup import serve_many

    from ftd_shun_manager.agent_client import UnixAgentClient
    from ftd_shun_manager.agent_protocol import PENDING_SESSION_LOOKUP, encode_session_request

    queue, _, receipt, recovery = crash

    def handler(connection, index):
        assert index == 0
        request = encode_session_request(PENDING_SESSION_LOOKUP, 7, 1, receipt.session_id)
        assert connection.recv(100) == request
        header = bytes([0 if state != 'unknown' else 1, 7, 0x1e, 0, 1]) + receipt.session_id
        terminal = bytes([6, 7, 0x1d, receipt.sequence, len(receipt.acknowledgements)])
        terminal += b''.join(ack.ip.packed for ack in receipt.acknowledgements)
        packet = header if state == 'unknown' else header + terminal
        if state == 'foreign': packet = packet[:-1] + bytes([packet[-1] ^ 1])
        connection.send(packet)
        assert connection.recv(100) == b''

    path, pool, server = serve_many(tmp_path, handler, count=1)
    agent = UnixAgentClient(path, 1, large_snapshots=True, additions_enabled=True, addition_device_ids=frozenset({1}),
                            settled_cycles=True, recoverable_cycles=True, tracked_cycles=True, batch_additions=True,
                            batch_session_version=7, deferred_confirmation=True)
    before = dump(recovery.store)
    try:
        if state == 'complete':
            assert pending_restart.recover(recovery.store, 1, agent) is True
            with recovery.store._connection() as db:
                assert [row[0] for row in db.execute('SELECT state FROM operation_jobs')] == ['AWAITING_CONFIRMATION'] * 2
            assert DeviceLeases(recovery.store, queue).status()['devices'][0]['state'] == 'IDLE'
        else:
            with pytest.raises(AgentUnavailable): pending_restart.recover(recovery.store, 1, agent)
            assert dump(recovery.store) == before
        server.result(5)
    finally:
        pool.shutdown(wait=True)


def test_cancellation_drains_lookup_and_atomic_handoff_without_opening_new_session(crash):
    from threading import Event

    _, _, receipt, recovery = crash
    entered, release = Event(), Event()
    agent = Agent()

    def lookup(*_args):
        entered.set()
        assert release.wait(3)
        return receipt

    agent.pending_session_completed = lookup
    service = runner(recovery.store, agent)

    async def interrupted():
        task = asyncio.create_task(visit(service))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError): await task

    asyncio.run(interrupted())
    assert states(service) == {'AWAITING_CONFIRMATION': 2}
    assert not agent.seen
    assert service.leases.status()['devices'][0]['state'] == 'IDLE'


@pytest.mark.parametrize('path,value', [('$.format_version', True), ('$.epoch', 1.0), ('$.sequence', 4.0),
                                      ('$.acknowledgements[0].sequence', True)])
def test_checkpoint_protocol_fields_require_literal_types(crash, path, value):
    _, _, _, recovery = crash
    with recovery.store._connection() as db:
        event = db.execute('SELECT * FROM shun_events WHERE event_type=?', (pending_restart.EVENT,)).fetchone()
        # json(?) preserves a JSON boolean instead of SQLite's integer adaptation.
        db.execute('UPDATE shun_events SET details_json=json_set(details_json,?,json(?)) WHERE id=?',
                   (path, json.dumps(value), event['id']))
    before = dump(recovery.store)
    with pytest.raises(ValueError): recovery.inspect(1)
    assert dump(recovery.store) == before
