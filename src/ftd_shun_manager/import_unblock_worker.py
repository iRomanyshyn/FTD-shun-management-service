"""Bounded SQL-only delegation to the existing verified REMOVE queue."""

import json
from datetime import datetime
from ipaddress import IPv4Address
from uuid import uuid4

from .bulk_policy import BulkUnavailable, _atomic, _state
from .import_unblocks import SCOPE, ImportUnblocks, present
from .managed_restoration import validate_binding
from .operation_queue import QueueConflict, QueueFull, stamp
from .safety import mutations_suspended
from .schema import schema_connection


def ticket(db,key,targets,subject,display_name,roles,now):
    """A scope label alone cannot bypass ordinary admission or its rate limit."""
    if not present(db): raise QueueConflict('Import-unblock authority is unavailable.')
    rows=db.execute('''SELECT m.*,u.requested_at,u.expires_at,u.retired_revision,u.state AS root_state,r.actor_subject,r.actor_display_name,r.actor_roles_json
      FROM managed_import_unblock_members m JOIN managed_import_unblocks u ON u.id=m.root_id
      JOIN managed_shun_requests r ON r.id=u.id WHERE m.child_id=? ORDER BY m.device_id,m.ip''',(key,)).fetchall()
    if (not 1<=len(rows)<=16 or [(r['device_id'],IPv4Address(r['ip'])) for r in rows]!=targets
            or any(r['state']!='ADMITTING' or r['root_state']!='ACTIVE' or r['actor_subject']!=subject
                   or r['actor_display_name']!=display_name or json.loads(r['actor_roles_json'])!=list(roles)
                   or not r['requested_at']<=stamp(now)<r['expires_at'] for r in rows)
            or len({r['root_id'] for r in rows})!=1):
        raise QueueConflict('An exact complete import-unblock delegation ticket is required.')
    for row in rows:
        current=db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?',(row['device_id'],row['ip'])).fetchone()
        if current is None or current['enabled'] or current['revision']!=row['retired_revision'] or any(current[f]!=row[f] for f in ('intent_id','generation','authorization_request_id')):
            raise QueueConflict('The original retired import target changed.')
    return rows[0]


def require_claim(db,request,job,now):
    if not present(db): return
    rows=db.execute('''SELECT m.*,u.state AS root_state,u.expires_at,u.requested_at,u.retired_revision,
      r.actor_subject,r.actor_display_name,r.actor_roles_json FROM managed_import_unblock_members m
      JOIN managed_import_unblocks u ON u.id=m.root_id JOIN managed_shun_requests r ON r.id=u.id
      WHERE m.child_id=? ORDER BY m.device_id,m.ip''',(request['id'],)).fetchall()
    if not rows: return
    expected={'scope':SCOPE,'targets':[[r['device_id'],str(IPv4Address(r['ip']))] for r in rows]}
    if (json.loads(request['payload_json'])!=expected or job['action']!='REMOVE'
            or any(request[f]!=rows[0][f] for f in ('actor_subject','actor_display_name','actor_roles_json'))
            or not rows[0]['requested_at']<=request['requested_at']<request['expires_at']<=rows[0]['expires_at']
            or any(r['job_id'] is None or r['state'] in {'WAITING','ADMITTING'} for r in rows)
            or not any(r['job_id']==job['id'] and r['state']=='QUEUED' and r['root_state']=='ACTIVE'
                       and r['requested_at']<=stamp(now)<r['expires_at'] for r in rows)):
        raise QueueConflict('Only an active committed import-unblock delegation may claim REMOVE.')
    target=next(r for r in rows if r['job_id']==job['id'])
    current=db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?',(target['device_id'],target['ip'])).fetchone()
    if current is None or current['enabled'] or current['revision']!=target['retired_revision'] or any(current[f]!=target[f] for f in ('intent_id','generation','authorization_request_id')):
        raise QueueConflict('Frozen retired ownership changed before REMOVE claim.')


def _predecessor_ready(db,member,now):
    if member['predecessor_json'] is None: return True
    evidence=json.loads(member['predecessor_json'])
    job=db.execute('SELECT * FROM operation_jobs WHERE id=?',(evidence['job_id'],)).fetchone()
    attempt=db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?',(evidence['job_id'],)).fetchone()
    claim=db.execute('SELECT * FROM shun_events WHERE id=?',(evidence['claim_event_id'],)).fetchone()
    if job is None or attempt is None or claim is None: raise BulkUnavailable('Captured ADD evidence is missing.')
    actual={k:v.hex() if isinstance(v,bytes) else v for k,v in dict(claim).items()}
    if json.dumps(actual,sort_keys=True)!=member['claim_json']: raise BulkUnavailable('Captured ADD claim changed.')
    validate_binding(db,attempt,job)
    request=db.execute('SELECT expires_at FROM operation_requests WHERE id=?',(attempt['id'],)).fetchone()
    if request is None or attempt['id']!=evidence['request_id'] or request['expires_at']!=evidence['expires_at']:
        raise BulkUnavailable('Captured ADD request or deadline changed.')
    if evidence.get('kind')=='AWAITING_CONFIRMATION':
        from .pending_ordered import require_captured
        require_captured(db,evidence,job)
    if any(attempt[f]!=evidence[f] for f in ('intent_id','generation','authorization_request_id','target_revision','snapshot_id','snapshot_started_at','snapshot_at','requested_at')):
        raise BulkUnavailable('Captured ADD authority changed.')
    fence=db.execute('SELECT epoch,state FROM managed_bulk_device_executors WHERE device_id=?',(member['device_id'],)).fetchone()
    if fence is None or fence['epoch']<evidence['executor_epoch']:raise BulkUnavailable('Captured device epoch regressed.')
    if fence['epoch']==evidence['executor_epoch'] and fence['state']!='IDLE':return False
    if job['state'] in {'RUNNING','AWAITING_CONFIRMATION'}: return False
    if job['state'] in {'OBSERVED_PRESENT','CONFIRMED_ABSENT'}:
        from .pending_execution import ordered_predecessor_confirmed
        return ordered_predecessor_confirmed(db,member,evidence,job,stamp(now))
    if job['state']=='CANCELLED':
        from .bulk_ordered_promotion import _deferral
        _deferral(db,evidence,member,now)
        return job['dispatch_kind'] is None and job['started_at'] is None
    return job['state'] in {'VERIFIED','NOOP'}


class ImportUnblockWorker:
    def __init__(self,store,queue): self.service=ImportUnblocks(store,queue);self.store=store;self.queue=queue

    def require_storage(self):
        with self.service.views._snapshot() as db:
            _state(db)
            if not present(db) or db.execute("SELECT 1 FROM managed_import_unblock_members WHERE state='ADMITTING' LIMIT 1").fetchone():
                raise BulkUnavailable('Complete existing import-unblock profile is required.')

    def advance(self):
        from .device_leases import device_uncertain
        with self.service.views._snapshot() as db:
            if not present(db):return 0
            if db.execute("SELECT 1 FROM managed_import_unblock_members WHERE state='ADMITTING' LIMIT 1").fetchone():
                raise BulkUnavailable('An incomplete committed delegation cannot be resumed.')
            if (not db.execute("SELECT 1 FROM managed_import_unblocks WHERE state='ACTIVE' LIMIT 1").fetchone()
                    and not db.execute("SELECT 1 FROM managed_import_unblock_members WHERE state='QUEUED' LIMIT 1").fetchone()): return 0
        logs=[];changed=0
        with schema_connection(self.store) as db, _atomic(db):
            _state(db);now=self.queue._now();timestamp=stamp(now)
            # Reflect committed queue results only; no inference from snapshots.
            for row in db.execute('''SELECT m.*,j.state AS outcome FROM managed_import_unblock_members m
              JOIN operation_jobs j ON j.id=m.job_id WHERE m.state='QUEUED'
              AND j.state NOT IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION') LIMIT 64''').fetchall():
                state=row['outcome']
                if state not in {'VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED'}: raise BulkUnavailable('Unknown REMOVE result.')
                db.execute('UPDATE managed_import_unblock_members SET state=? WHERE root_id=? AND device_id=? AND ip=?',
                           (state,row['root_id'],row['device_id'],row['ip']));changed+=1
            for root in db.execute('''SELECT u.*,r.actor_subject,r.actor_display_name,r.actor_roles_json FROM managed_import_unblocks u
              JOIN managed_shun_requests r ON r.id=u.id WHERE u.state='ACTIVE' ORDER BY u.requested_at LIMIT 128''').fetchall():
                if timestamp<root['requested_at']: raise QueueConflict('Cleanup clock moved backwards.')
                if timestamp>=root['expires_at']:
                    db.execute("UPDATE managed_import_unblocks SET state='EXPIRED' WHERE id=?",(root['id'],))
                    db.execute("UPDATE managed_import_unblock_members SET state='EXPIRED' WHERE root_id=? AND state='WAITING'",(root['id'],));changed+=1
                    self.service._cancel_unstarted(db,root['id'])
                    self._terminal_event(db,root,'EXPIRED',timestamp)
                elif not db.execute("SELECT 1 FROM managed_import_unblock_members WHERE root_id=? AND state NOT IN ('VERIFIED','NOOP','SUPERSEDED') LIMIT 1",(root['id'],)).fetchone():
                    db.execute("UPDATE managed_import_unblocks SET state='COMPLETE' WHERE id=?",(root['id'],));changed+=1
                    self._terminal_event(db,root,'COMPLETE',timestamp)
            if mutations_suspended(db): return changed
            slots=32-db.execute("SELECT COUNT(*) FROM managed_import_unblock_members WHERE state='QUEUED'").fetchone()[0]
            if slots<=0:return changed
            roots=db.execute('''SELECT u.*,r.actor_subject,r.actor_display_name,r.actor_roles_json FROM managed_import_unblocks u
              JOIN managed_shun_requests r ON r.id=u.id WHERE u.state='ACTIVE' AND u.expires_at>? ORDER BY u.requested_at LIMIT 128''',(timestamp,)).fetchall()
            for root in roots:
                eligible=[r[0] for r in db.execute('''SELECT DISTINCT m.device_id FROM managed_import_unblock_members m
                  JOIN devices d ON d.id=m.device_id JOIN managed_bulk_device_executors e ON e.device_id=m.device_id
                  WHERE m.root_id=? AND m.state='WAITING' AND d.enabled=1
                  AND (e.state='IDLE' OR (e.state='LEASED' AND e.lease_until>?))''',(root['id'],timestamp))
                  if not device_uncertain(db,r[0])]
                if not eligible:continue
                rows=db.execute('''SELECT m.* FROM managed_import_unblock_members m JOIN devices d ON d.id=m.device_id
                  JOIN managed_bulk_device_executors e ON e.device_id=m.device_id WHERE m.root_id=? AND m.state='WAITING'
                  AND d.enabled=1 AND (e.state='IDLE' OR (e.state='LEASED' AND e.lease_until>?))
                  AND m.device_id IN ('''+','.join('?' for _ in eligible)+') ORDER BY m.device_id,m.ip LIMIT 32',(root['id'],timestamp,*eligible)).fetchall()
                ready=[]
                for row in rows:
                    if len(ready)>=min(16,slots):break
                    if device_uncertain(db,row['device_id']):continue
                    current=db.execute('SELECT * FROM managed_shun_targets WHERE device_id=? AND ip=?',(row['device_id'],row['ip'])).fetchone()
                    if current is None or current['enabled'] or current['revision']!=root['retired_revision'] or any(current[f]!=row[f] for f in ('intent_id','generation','authorization_request_id')):
                        db.execute("UPDATE managed_import_unblock_members SET state='SUPERSEDED' WHERE root_id=? AND device_id=? AND ip=?",(root['id'],row['device_id'],row['ip']));changed+=1;continue
                    if not _predecessor_ready(db,row,now):continue
                    if db.execute("SELECT 1 FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION') LIMIT 1",(row['device_id'],row['ip'])).fetchone():continue
                    ready.append(row)
                if not ready:continue
                key=str(uuid4());roles=tuple(json.loads(root['actor_roles_json']))
                db.execute('SAVEPOINT import_unblock_delegate')
                try:
                    for row in ready: db.execute("UPDATE managed_import_unblock_members SET state='ADMITTING',child_id=? WHERE root_id=? AND device_id=? AND ip=?",(key,root['id'],row['device_id'],row['ip']))
                    ttl=min(900,int((datetime.fromisoformat(root['expires_at'])-now).total_seconds()))
                    if ttl<1:raise QueueConflict('Cleanup expired before delegation.')
                    result,accepted=self.queue.apply_enqueue(db,key,[(r['device_id'],IPv4Address(r['ip'])) for r in ready],
                        root['actor_subject'],root['actor_display_name'],roles,ttl,'manual',SCOPE,import_unblock_enabled=True)
                    if result['replayed']:raise QueueConflict('New delegation key was already consumed.')
                    if not now<=self.queue._now()<datetime.fromisoformat(root['expires_at']):
                        raise QueueConflict('Cleanup clock or deadline changed during delegation.')
                    for row in ready:
                        job=db.execute('SELECT j.id FROM operation_jobs j JOIN operation_links l ON l.job_id=j.id WHERE l.request_id=? AND j.device_id=? AND j.ip=?',(key,row['device_id'],row['ip'])).fetchone()
                        if job is None:raise BulkUnavailable('Complete removal delegation is missing.')
                        db.execute("UPDATE managed_import_unblock_members SET state='QUEUED',job_id=? WHERE root_id=? AND device_id=? AND ip=?",(job[0],root['id'],row['device_id'],row['ip']))
                    logs.extend(accepted);changed+=len(ready)
                except QueueFull:
                    db.execute('ROLLBACK TO import_unblock_delegate')
                finally: db.execute('RELEASE import_unblock_delegate')
                break
        for entry in logs: print(json.dumps(entry),flush=True)
        return changed

    def _terminal_event(self,db,root,state,timestamp):
        self.store._insert_event(db,'IMPORT_UNBLOCK_'+state,None,None,None,
            root['actor_subject'],root['actor_display_name'],tuple(json.loads(root['actor_roles_json'])),root['id'],
            {'import_id':root['import_id'],'target_count':root['target_count'],'maintenance_resumed':False},timestamp)
