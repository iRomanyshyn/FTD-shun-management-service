"""Whole-import cleanup waits for actual v7 settlement and causal observation."""
from datetime import timedelta

import pytest
import test_pending_ordered_capture as fixtures
from test_import_unblocks import accept

from ftd_shun_manager.import_unblock_worker import ImportUnblockWorker
from ftd_shun_manager.import_unblocks import ImportUnblocks

bulk=fixtures.bulk
cancellation_controls=fixtures.cancellation_controls
dispatch=fixtures.dispatch
execution=fixtures.execution
journal=fixtures.journal
leases=fixtures.leases
ledger=fixtures.ledger
ordered=fixtures.ordered
waits=fixtures.waits


@pytest.mark.parametrize('already_pending',[False,True])
@pytest.mark.parametrize('present',[False,True])
def test_captured_add_needs_its_original_pending_read(ordered,bulk,leases,execution,already_pending,present):
    service=ImportUnblocks(execution.store,execution.queue)
    service.queue._now=lambda:bulk[1][0]
    service.initialize(enabled=True)
    if already_pending:
        queue,jobs,session=fixtures.awaiting(bulk,leases,execution)
    else:
        fixtures.grant(bulk,(1,))
        queue,jobs,terminal=fixtures.stage_device(leases,bulk)
    with service.store._connection() as db:
        imported=db.execute('SELECT authorization_request_id FROM managed_shun_targets').fetchone()[0]
    root=accept(service,imported);worker=ImportUnblockWorker(service.store,service.queue)
    assert worker.advance()==0
    if not already_pending:
        session=execution.await_confirmation(queue.token,terminal,tuple(j['id'] for j in jobs),enabled=True)
        assert worker.advance()==0
    bulk[1][0]+=timedelta(seconds=1)
    token,_=fixtures.acquire(leases)
    execution.confirm(token,session,fixtures.read(bulk,present=(str(fixtures.IP),) if present else ()),enabled=True)
    # The original ADD visit is settled. Its causal read can admit REMOVE for
    # the current serialized visit; admission itself sends no command.
    assert worker.advance()==1
    leases.release(token)
    assert worker.advance()==0
    task=service.status(root['operation_id'])['tasks'][0]
    assert task['counts']=={'QUEUED':1}
    with service.store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operation_jobs WHERE action='ADD'").fetchone()[0]==1


@pytest.mark.parametrize('held',[False,True])
def test_interrupted_recovery_does_not_ignore_active_import_cleanup(ordered,bulk,leases,execution,held):
    from uuid import uuid4

    from test_bulk_policy import dump

    from ftd_shun_manager import device_reconciliation, pending_offline
    from ftd_shun_manager.queue_recovery import report
    from ftd_shun_manager.web import Identity, templates

    service=ImportUnblocks(execution.store,execution.queue)
    service.queue._now=lambda:bulk[1][0]
    service.initialize(enabled=True)
    imported=fixtures.grant(bulk,(1,))
    fixtures.stage_device(leases,bulk)
    root=accept(service,imported)
    assert not report(service.store,now=bulk[1][0])['import_cleanup_tasks']
    bulk[1][0]+=timedelta(seconds=901)
    if held:
        assert leases.claim(1,str(uuid4()),135,enabled=True) is None
        bulk[1][0]+=timedelta(seconds=1)
    before=dump(service.store)
    with pytest.raises(ValueError,match='[Cc]leanup'):
        pending_offline.inspect(service.store.path,1,now=bulk[1][0])
    with pytest.raises(ValueError,match='[Cc]leanup' if held else 'ATTENTION'):
        device_reconciliation.inspect(service.store.path,1,now=bulk[1][0],pending_v7=True)
    guidance=report(service.store,now=bulk[1][0])
    assert guidance['import_cleanup_tasks'][0]['id']==root['operation_id']
    assert not guidance['devices'][0].get('pending_v7_phase') and not guidance['devices'][0]['eligible']
    html=templates.get_template('queue-recovery.html').render(report=guidance,identity=Identity('alice','Alice',('Operator',)))
    assert '/import-unblocks/'+root['operation_id'] in html
    assert 'Cancellation leaves restoration off' in html
    assert dump(service.store)==before
    service.cancel(root['operation_id'],'alice','Alice',('Operator',))
    reviewed=pending_offline.inspect(service.store.path,1,now=bulk[1][0])
    assert reviewed['running_to_unknown']+reviewed['existing_unknown']==1 and not reviewed['releases_fence']
    assert not report(service.store,now=bulk[1][0])['import_cleanup_tasks']
