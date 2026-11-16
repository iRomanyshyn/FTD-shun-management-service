"""Durable whole-import scope and rolling REMOVE delegation on disposable state."""
from ipaddress import IPv4Address
from uuid import uuid4

import pytest
from test_bulk_ordered_promotion import bulk as bulk_fixture
from test_bulk_ordered_promotion import cancellation_controls as cancellation_fixture
from test_bulk_ordered_promotion import dispatch as dispatch_fixture
from test_bulk_ordered_promotion import journal as journal_fixture
from test_bulk_ordered_promotion import leases as leases_fixture
from test_bulk_ordered_promotion import ordered as ordered_fixture
from test_bulk_ordered_promotion import promoter as promoter_fixture
from test_bulk_ordered_promotion import waits as waits_fixture
from test_bulk_policy import confirm, dump, prepare

from ftd_shun_manager.import_unblock_worker import ImportUnblockWorker
from ftd_shun_manager.import_unblocks import ImportUnblocks
from ftd_shun_manager.managed_shuns import ManagedConflict
from ftd_shun_manager.operation_queue import QueueConflict

bulk=bulk_fixture
cancellation_controls=cancellation_fixture
dispatch=dispatch_fixture
journal=journal_fixture
leases=leases_fixture
ordered=ordered_fixture
promoter=promoter_fixture
waits=waits_fixture

@pytest.fixture
def cleanup(promoter,bulk):
    service=ImportUnblocks(promoter.store,promoter.queue)
    service.queue._now=lambda:bulk[1][0]
    service.initialize(enabled=True)
    return service


def accept(cleanup,import_id,**overrides):
    review=cleanup.review(import_id)
    args={'key':str(uuid4()),'import_id':import_id,'digest':review['scope_digest'],'count':review['owned_count'],
          'reviewed_at':review['reviewed_at'],'subject':'alice','display_name':'Alice','roles':('Operator',),'enabled':True}
    return cleanup.confirm(**(args|overrides))


def test_one_import_never_acquires_already_managed_members(cleanup,bulk):
    first=confirm(bulk,prepare(bulk,'198.51.100.1')[1])['operation_id']
    second=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    result=accept(cleanup,second)
    assert result['target_count']==result['retired_targets']==1 and not result['verified_removal']
    with cleanup.store._connection() as db:
        assert db.execute('SELECT enabled FROM managed_shun_targets WHERE ip=?',(IPv4Address('198.51.100.1').packed,)).fetchone()[0]==1
        assert db.execute('SELECT authorization_request_id FROM managed_shun_targets WHERE ip=?',(IPv4Address('198.51.100.1').packed,)).fetchone()[0]==first
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==1
    task=cleanup.status(result['operation_id'])['tasks'][0]
    assert task['counts']=={'QUEUED':1}
    with cleanup.store._connection() as db:
        assert db.execute('SELECT ip FROM operation_jobs').fetchone()[0]==IPv4Address('198.51.100.2').packed


def test_replay_and_changed_scope_never_retire_new_owner(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk)[1])['operation_id']
    view=cleanup.review(imported);key=str(uuid4())
    result=accept(cleanup,imported,key=key)
    replay=cleanup.confirm(key,imported,view['scope_digest'],view['owned_count'],view['reviewed_at'],'alice','Alice',('Operator',),enabled=True)
    assert replay==result|{'replayed':True}
    with pytest.raises(ManagedConflict): cleanup.confirm(key,imported,view['scope_digest'],view['owned_count'],view['reviewed_at'],'bob','Bob',('Operator',),enabled=True)
    assert cleanup.status(key)['tasks'][0]['counts']=={'WAITING':1}


def test_rolling_window_does_not_expand_queue_to_entire_import(cleanup,bulk):
    addresses='\n'.join(str(IPv4Address(0xc6120000+i)) for i in range(150))
    imported=confirm(bulk,prepare(bulk,addresses)[1])['operation_id']
    root=accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==16 and worker.advance()==16 and worker.advance()==0
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['target_count']==150 and task['counts']=={'WAITING':118,'QUEUED':32}
    assert len(task['targets'])==100
    assert all(t['state'] in {'WAITING','QUEUED'} for t in task['targets'])


def test_cancellation_keeps_retirement_and_never_delegates_remaining_work(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    root=accept(cleanup,imported)
    before=dump(cleanup.store)
    with pytest.raises(PermissionError):cleanup.cancel(root['operation_id'],'bob','Bob',('Operator',))
    assert dump(cleanup.store)==before
    cleanup.cancel(root['operation_id'],'alice','Alice',('Operator',))
    assert ImportUnblockWorker(cleanup.store,cleanup.queue).advance()==0
    assert cleanup.status(root['operation_id'])['tasks'][0]['counts']=={'CANCELLED':2}
    assert cleanup.review(imported)['owned_count']==0


def test_interactive_ready_removal_precedes_background_cleanup(cleanup,bulk,leases):
    from test_bulk_removals import admit
    from test_device_leases import acquire

    from ftd_shun_manager.bulk_removals import BulkRemovals
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    imported2=confirm(bulk,prepare(bulk,'198.51.100.4')[1])['operation_id'];accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    cleanup.store.record_observed_shun(1,IPv4Address('198.51.100.1'),'management')
    ready=BulkRemovals(cleanup.store,cleanup.queue)
    # A separate ordinary address must overtake older cleanup jobs.
    cleanup.store.record_observed_shun(1,IPv4Address('198.51.100.3'),'management')
    from ftd_shun_manager.bulk_removals import BulkRemovalScopes
    scope=BulkRemovalScopes(cleanup.store).snapshot(IPv4Address('198.51.100.3'),device_id=1)
    admit(ready,{key:scope[key] for key in ('version','scope','ip','managed_revision','protected_revision','protected','targets')})
    token,queue=acquire(leases)
    job=queue.claim_removal(1,token.owner,queue.cutoff())
    assert IPv4Address(job['ip'])==IPv4Address('198.51.100.3')
    queue.finish_removal(job['id'],token.owner,'VERIFIED');leases.release(token)
    # A target not delegated yet can also be unblocked interactively.
    accept(cleanup,imported2)
    scope=BulkRemovalScopes(cleanup.store).snapshot(IPv4Address('198.51.100.4'),device_id=1)
    assert admit(ready,{key:scope[key] for key in ('version','scope','ip','managed_revision','protected_revision','protected','targets')})['device_work_admitted']


def test_complete_verified_removals_use_actual_device_queue_claims(cleanup,bulk,leases):
    from test_device_leases import acquire
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    root=accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==2
    token,queue=acquire(leases)
    for _ in range(2):
        job=queue.claim_removal(1,token.owner,queue.cutoff())
        assert job is not None and job['action']=='REMOVE'
        queue.finish_removal(job['id'],token.owner,'VERIFIED')
    leases.release(token)
    assert worker.advance()>=2
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['state']=='COMPLETE' and task['verified']==2
    assert worker.advance()==0


def test_partial_completion_never_exceeds_32_delegated_members(cleanup,bulk,leases):
    from test_device_leases import acquire
    imported=confirm(bulk,prepare(bulk,'\n'.join(str(IPv4Address(0xc6120000+i)) for i in range(70)))[1])['operation_id']
    root=accept(cleanup,imported);worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    worker.advance();worker.advance()
    token,queue=acquire(leases)
    job=queue.claim_removal(1,token.owner,queue.cutoff());queue.finish_removal(job['id'],token.owner,'VERIFIED');leases.release(token)
    worker.advance()
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['counts']['QUEUED']==32 and task['verified']==1


def test_running_add_waits_for_original_settlement_not_only_its_result(cleanup,bulk,leases):
    from test_bulk_ordered_promotion import finish
    from test_bulk_ordered_removals import running
    from test_device_leases import grant
    imported=grant(bulk,devices=(1,));original=running(bulk,leases)
    root=accept(cleanup,imported);worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==0
    finish(leases,original,release=False)
    assert worker.advance()==0
    leases.release(original[0]);assert worker.advance()==1
    assert cleanup.status(root['operation_id'])['tasks'][0]['counts']=={'QUEUED':1}


def test_failed_add_is_not_replayed_or_inferred_success_after_observation(cleanup,bulk,leases):
    from test_bulk_ordered_promotion import finish
    from test_bulk_ordered_removals import running
    from test_device_leases import grant
    imported=grant(bulk,devices=(1,));original=running(bulk,leases)
    root=accept(cleanup,imported);finish(leases,original,'UNVERIFIED')
    cleanup.store.record_observed_shun(1,IPv4Address('198.51.100.1'),'management')
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==0
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['counts']=={'WAITING':1} and task['attention']==1


def test_cancelling_delegated_work_retains_results_and_never_readds(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    root=accept(cleanup,imported);worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    cleanup.cancel(root['operation_id'],'alice','Alice',('Operator',));worker.advance()
    assert cleanup.status(root['operation_id'])['tasks'][0]['counts']=={'CANCELLED':2}
    assert cleanup.review(imported)['owned_count']==0
    assert worker.advance()==0


def test_new_import_cannot_replace_a_reserved_target(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];accept(cleanup,imported)
    proposal=prepare(bulk)[1];before=dump(cleanup.store)
    with pytest.raises(ManagedConflict,match='cleanup reserves'):confirm(bulk,proposal)
    assert dump(cleanup.store)==before


def test_one_parent_counts_as_one_rate_limited_submission(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk,'\n'.join(str(IPv4Address(0xc6120000+i)) for i in range(35)))[1])['operation_id']
    accept(cleanup,imported);worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance();worker.advance()
    with cleanup.store._connection() as db:
        assert cleanup.queue._recent_request_count(db,'alice',bulk[1][0])==1
    grouped=cleanup.grouped_queue(cleanup.queue.status())
    assert grouped['counts']['QUEUED']==32 and not grouped['items'] and not grouped['progress']['requests']


def test_expiry_never_resumes_maintenance_or_silently_rearms(cleanup,bulk):
    from datetime import timedelta
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];root=accept(cleanup,imported)
    bulk[1][0]+=timedelta(days=7,seconds=1)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['state']=='EXPIRED' and task['counts']=={'EXPIRED':1}
    assert worker.advance()==0 and cleanup.review(imported)['owned_count']==0


@pytest.mark.parametrize('outcome',['VERIFIED','UNVERIFIED'])
def test_cancel_running_removal_keeps_actual_original_actor_result(cleanup,bulk,leases,outcome):
    from test_device_leases import acquire
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];root=accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    token,queue=acquire(leases);job=queue.claim_removal(1,token.owner,queue.cutoff())
    cleanup.cancel(root['operation_id'],'alice','Alice',('Operator',))
    queue.finish_removal(job['id'],token.owner,outcome);leases.release(token);worker.advance()
    with cleanup.store._connection() as db:
        child=db.execute('SELECT child_id FROM managed_import_unblock_members').fetchone()[0]
        event=db.execute('SELECT actor_subject FROM shun_events WHERE request_id=? AND event_type=?',(child,'SHUN_OPERATION_'+outcome)).fetchone()
        assert event[0]=='alice'
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['state']=='CANCELLED' and task['counts']=={outcome:1}


def test_cancel_shared_unstarted_removal_preserves_protected_request(cleanup,bulk,leases):
    from test_device_leases import acquire

    from ftd_shun_manager.protected_policy import ProtectedPolicy
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];root=accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    policy_key=str(uuid4())
    ProtectedPolicy(cleanup.store,initialize_queue=False).change('add',IPv4Address('198.51.100.1'),0,'alice','Alice',('Operator',),managed_revision=2)
    cleanup.queue.enqueue(policy_key,[(1,IPv4Address('198.51.100.1'))],'system:trusted-ip-policy','Policy',(),source='trusted_policy')
    cleanup.cancel(root['operation_id'],'alice','Alice',('Operator',))
    token,queue=acquire(leases);job=queue.claim_removal(1,token.owner,queue.cutoff())
    assert job is not None
    queue.finish_removal(job['id'],token.owner,'VERIFIED');leases.release(token);worker.advance()
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['counts']=={'CANCELLED':1} and task['verified']==0
    with cleanup.store._connection() as db:
        child=db.execute('SELECT child_id FROM managed_import_unblock_members').fetchone()[0]
        assert not db.execute("SELECT 1 FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_VERIFIED'",(child,)).fetchone()
        assert db.execute("SELECT 1 FROM shun_events WHERE request_id=? AND event_type='SHUN_OPERATION_VERIFIED'",(policy_key,)).fetchone()


def test_expired_root_revokes_already_delegated_removals(cleanup,bulk,leases):
    from datetime import timedelta

    from test_device_leases import acquire
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];root=accept(cleanup,imported)
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    bulk[1][0]+=timedelta(days=7,seconds=1)
    worker.advance();worker.advance()
    token,queue=acquire(leases)
    assert queue.claim_removal(1,token.owner,queue.cutoff()) is None
    leases.release(token)
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert task['state']=='EXPIRED' and task['counts']=={'CANCELLED':1}


def test_disabled_device_does_not_block_other_device(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk,devices=(1,2))[1])['operation_id']
    with cleanup.store._connection() as db:db.execute('UPDATE devices SET enabled=0 WHERE id=1')
    root=accept(cleanup,imported);worker=ImportUnblockWorker(cleanup.store,cleanup.queue)
    assert worker.advance()==1
    task=cleanup.status(root['operation_id'])['tasks'][0]
    assert [(t['device_id'],t['state']) for t in task['targets']]==[(1,'WAITING'),(2,'QUEUED')]


def test_stale_review_and_viewer_cannot_change_policy(cleanup,bulk):
    from datetime import timedelta
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];review=cleanup.review(imported)
    before=dump(cleanup.store)
    with pytest.raises(PermissionError):accept(cleanup,imported,roles=('Viewer',))
    assert dump(cleanup.store)==before
    bulk[1][0]+=timedelta(minutes=5)
    with pytest.raises(ManagedConflict,match='expired'):
        accept(cleanup,imported,reviewed_at=review['reviewed_at'])
    assert dump(cleanup.store)==before


def test_post_retirement_failure_rolls_back_complete_scope(cleanup,bulk,monkeypatch):
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    before=dump(cleanup.store);original=cleanup.store._insert_event
    def fail(db,event,*args):
        original(db,event,*args)
        if event=='IMPORT_UNBLOCK_REQUESTED':raise ValueError('Synthetic audit failure')
    monkeypatch.setattr(cleanup.store,'_insert_event',fail)
    with pytest.raises(ValueError,match='audit failure'):accept(cleanup,imported)
    assert dump(cleanup.store)==before


def test_restart_retains_original_scope_and_completed_receipt(cleanup,bulk):
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];root=accept(cleanup,imported)
    restarted=ImportUnblocks(cleanup.store,cleanup.queue)
    assert restarted.status(root['operation_id'])==cleanup.status(root['operation_id'])
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance()
    assert ImportUnblockWorker(cleanup.store,cleanup.queue).advance()==0
    assert restarted.status(root['operation_id'])['tasks'][0]['counts']=={'QUEUED':1}


def test_complete_100000_target_scope_has_bounded_status_and_queue(cleanup,bulk):
    from time import monotonic
    text='\n'.join(str(IPv4Address(0xc6120000+i)) for i in range(100000))
    imported=confirm(bulk,prepare(bulk,text)[1])['operation_id']
    start=monotonic();root=accept(cleanup,imported)
    confirmation_time=monotonic()-start
    worker=ImportUnblockWorker(cleanup.store,cleanup.queue);worker.advance();worker.advance()
    task=cleanup.status(root['operation_id'],page=1000)['tasks'][0]
    assert task['target_count']==100000 and task['counts']=={'WAITING':99968,'QUEUED':32}
    assert len(task['targets'])==100 and task['targets'][-1]['ip']==str(IPv4Address(0xc6120000+99999))
    print(f'100000-target cleanup confirmation: {confirmation_time:.3f}s; rolling window remains 32')


def test_unsealed_ticket_and_changed_claim_refuse_work(cleanup,bulk,leases):
    from test_bulk_ordered_removals import running
    from test_device_leases import grant

    from ftd_shun_manager.bulk_policy import BulkUnavailable
    imported=grant(bulk,devices=(1,));original=running(bulk,leases)
    accept(cleanup,imported)
    with cleanup.store._connection() as db:
        db.execute('DELETE FROM shun_events WHERE id=(SELECT json_extract(predecessor_json,\'$.claim_event_id\') FROM managed_import_unblock_members)')
    with pytest.raises(BulkUnavailable,match='missing'):ImportUnblockWorker(cleanup.store,cleanup.queue).advance()
    assert original[2]['action']=='ADD'


def test_initializer_requires_exact_existing_quiescent_profile(cleanup,bulk):
    from ftd_shun_manager.bulk_policy import BulkUnavailable
    from ftd_shun_manager.store import Store
    missing=Store(cleanup.store.path.parent/'missing.db')
    with pytest.raises(PermissionError):ImportUnblocks(missing).initialize()
    with pytest.raises(BulkUnavailable):ImportUnblocks(missing).initialize(enabled=True)
    assert not missing.path.exists()
    with pytest.raises(PermissionError):cleanup.initialize(enabled=1)
    before=dump(cleanup.store);cleanup.initialize(enabled=True)
    assert dump(cleanup.store)==before


def test_concurrent_confirmations_cannot_retire_scope_twice(cleanup,bulk):
    from concurrent.futures import ThreadPoolExecutor
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];review=cleanup.review(imported)
    def submit(_):
        try:return cleanup.confirm(str(uuid4()),imported,review['scope_digest'],1,review['reviewed_at'],'alice','Alice',('Operator',),enabled=True)
        except ManagedConflict:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
    assert sum(value is not None for value in results)==1
    assert len(cleanup.status()['tasks'])==1


def test_scope_label_cannot_forge_internal_rate_limit_ticket(cleanup,bulk):
    from ftd_shun_manager.import_unblocks import SCOPE
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];accept(cleanup,imported)
    before=dump(cleanup.store)
    with cleanup.store._connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(QueueConflict,match='ticket'):
            cleanup.queue.apply_enqueue(db,str(uuid4()),[(1,IPv4Address('198.51.100.1'))],'alice','Alice',('Operator',),900,'manual',SCOPE,import_unblock_enabled=True)
    assert dump(cleanup.store)==before


def test_parent_expiry_during_claim_rolls_back_before_submission(cleanup,bulk,leases,monkeypatch):
    from datetime import timedelta

    from test_device_leases import acquire

    from ftd_shun_manager.operation_queue import ClaimNotSubmitted
    imported=confirm(bulk,prepare(bulk)[1])['operation_id'];accept(cleanup,imported)
    bulk[1][0]+=timedelta(days=7,seconds=-10)
    ImportUnblockWorker(cleanup.store,cleanup.queue).advance()
    token,queue=acquire(leases);original=queue._event
    def event(db,name,*args,**kwargs):
        original(db,name,*args,**kwargs)
        if name=='SHUN_OPERATION_RUNNING':bulk[1][0]+=timedelta(seconds=11)
    monkeypatch.setattr(queue,'_event',event)
    before=dump(cleanup.store)
    with pytest.raises(ClaimNotSubmitted):queue.claim_removal(1,token.owner,queue.cutoff())
    assert dump(cleanup.store)==before


@pytest.mark.parametrize('value',['','True','1',' true','FALSE'])
def test_cleanup_configuration_is_literal_default_off(monkeypatch,value):
    from ftd_shun_manager.config import Settings
    monkeypatch.setenv('FTD_SHUN_IMPORT_UNBLOCKS_ENABLED',value)
    with pytest.raises(ValueError,match='IMPORT_UNBLOCKS'):Settings.from_environment()


def test_previous_writer_refuses_even_empty_cleanup_profile(cleanup,monkeypatch):
    from ftd_shun_manager import bulk_policy
    from ftd_shun_manager.bulk_policy import BulkUnavailable, _state
    original=bulk_policy._expected
    monkeypatch.setattr(bulk_policy,'_expected',lambda *args:original(*args[:-1]))
    with cleanup.store._connection() as db,pytest.raises(BulkUnavailable):_state(db)


@pytest.mark.parametrize('damage',[False,True])
def test_retention_preserves_captured_add_and_cleanup_evidence(cleanup,bulk,leases,damage):
    from datetime import timedelta

    from test_bulk_ordered_promotion import finish
    from test_bulk_ordered_removals import running
    from test_device_leases import grant

    from ftd_shun_manager.bulk_policy import BulkUnavailable
    imported=grant(bulk,devices=(1,));original=running(bulk,leases)
    root=accept(cleanup,imported);finish(leases,original)
    with cleanup.store._connection() as db:
        claim=db.execute('SELECT json_extract(predecessor_json,\'$.claim_event_id\') FROM managed_import_unblock_members').fetchone()[0]
        if damage:db.execute('DELETE FROM shun_events WHERE id=?',(claim,))
    bulk[1][0]+=timedelta(days=2)
    before=dump(cleanup.store)
    if damage:
        with pytest.raises(BulkUnavailable):cleanup.store.prune_expired_history(1,bulk[1][0])
        assert dump(cleanup.store)==before
    else:
        cleanup.store.prune_expired_history(1,bulk[1][0]);cleanup.queue.prune_completed(1)
        with cleanup.store._connection() as db:
            assert db.execute('SELECT 1 FROM shun_events WHERE id=?',(claim,)).fetchone()
            assert db.execute("SELECT 1 FROM shun_events WHERE request_id=? AND event_type='IMPORT_UNBLOCK_REQUESTED'",(root['operation_id'],)).fetchone()
        assert ImportUnblockWorker(cleanup.store,cleanup.queue).advance()==1
