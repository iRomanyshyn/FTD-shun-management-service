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
