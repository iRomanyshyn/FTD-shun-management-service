"""Explicit durable whole-import absence tasks; no SSH or automatic initialization."""

import hmac
import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .bulk_intent import _uuid
from .bulk_policy import BulkUnavailable, _actor, _atomic, _key_free, _quiescent, _state
from .bulk_policy_views import BulkPolicyViews
from .import_ownership import CATEGORY, ImportOwnership
from .managed_shuns import ManagedConflict
from .operation_queue import OperationQueue, QueueConflict, stamp
from .safety import mutations_suspended
from .schema import execute_schema, schema_connection

SCOPE = 'managed_v2_import_unblock'
LIFETIME = 7 * 86400
DDL = """
CREATE TABLE managed_import_unblocks (
 id TEXT PRIMARY KEY REFERENCES managed_shun_requests(id),
 import_id TEXT NOT NULL REFERENCES managed_bulk_manifests(id),
 scope_digest TEXT NOT NULL CHECK(length(scope_digest)=64),
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 100000),
 retired_revision INTEGER NOT NULL,requested_at TEXT NOT NULL,expires_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','COMPLETE','CANCELLED','EXPIRED'))
);
CREATE TABLE managed_import_unblock_members (
 root_id TEXT NOT NULL REFERENCES managed_import_unblocks(id) DEFERRABLE INITIALLY DEFERRED,
 device_id INTEGER NOT NULL REFERENCES devices(id),ip BLOB NOT NULL CHECK(typeof(ip)='blob' AND length(ip)=4),
 intent_id TEXT NOT NULL,generation INTEGER NOT NULL,authorization_request_id TEXT NOT NULL,
 target_revision INTEGER NOT NULL,predecessor_json TEXT,claim_json TEXT,
 child_id TEXT,job_id TEXT,
 state TEXT NOT NULL CHECK(state IN ('WAITING','ADMITTING','QUEUED','VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED','EXPIRED','SUPERSEDED')),
 PRIMARY KEY(root_id,device_id,ip)
);
CREATE INDEX idx_managed_import_unblock_work ON managed_import_unblock_members(state,device_id,root_id,ip);
CREATE INDEX idx_managed_import_unblock_pair ON managed_import_unblock_members(device_id,ip,root_id);
CREATE INDEX idx_managed_import_unblock_child ON managed_import_unblock_members(child_id,job_id);
CREATE TRIGGER managed_import_unblock_complete BEFORE INSERT ON managed_import_unblocks
WHEN NEW.target_count!=(SELECT COUNT(*) FROM managed_import_unblock_members WHERE root_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'import unblock membership is incomplete'); END;
CREATE TRIGGER managed_import_unblock_identity BEFORE UPDATE OF id,import_id,scope_digest,target_count,retired_revision,requested_at,expires_at ON managed_import_unblocks
BEGIN SELECT RAISE(ABORT,'import unblock authority is immutable'); END;
CREATE TRIGGER managed_import_unblock_transition BEFORE UPDATE OF state ON managed_import_unblocks
WHEN NOT (OLD.state='ACTIVE' AND NEW.state IN ('COMPLETE','CANCELLED','EXPIRED'))
BEGIN SELECT RAISE(ABORT,'import unblock cannot rearm'); END;
CREATE TRIGGER managed_import_unblock_retained BEFORE DELETE ON managed_import_unblocks
BEGIN SELECT RAISE(ABORT,'import unblock receipts are retained'); END;
CREATE TRIGGER managed_import_unblock_authority_identity BEFORE UPDATE ON managed_shun_requests
WHEN EXISTS(SELECT 1 FROM managed_import_unblocks WHERE id=OLD.id)
BEGIN SELECT RAISE(ABORT,'import unblock consent is immutable'); END;
CREATE TRIGGER managed_import_unblock_member_sealed BEFORE INSERT ON managed_import_unblock_members
WHEN EXISTS(SELECT 1 FROM managed_import_unblocks WHERE id=NEW.root_id)
BEGIN SELECT RAISE(ABORT,'import unblock scope is sealed'); END;
CREATE TRIGGER managed_import_unblock_member_identity BEFORE UPDATE OF root_id,device_id,ip,intent_id,generation,authorization_request_id,target_revision,predecessor_json,claim_json ON managed_import_unblock_members
BEGIN SELECT RAISE(ABORT,'import unblock target is immutable'); END;
CREATE TRIGGER managed_import_unblock_member_transition BEFORE UPDATE ON managed_import_unblock_members
WHEN NOT ((OLD.state='WAITING' AND ((NEW.state='ADMITTING' AND NEW.child_id IS NOT NULL AND NEW.job_id IS NULL)
 OR (NEW.state IN ('CANCELLED','EXPIRED','SUPERSEDED') AND NEW.child_id IS NULL AND NEW.job_id IS NULL)))
 OR (OLD.state='ADMITTING' AND NEW.state='QUEUED' AND NEW.child_id=OLD.child_id AND NEW.job_id IS NOT NULL)
 OR (OLD.state='QUEUED' AND NEW.state IN ('VERIFIED','NOOP','FAILED','UNVERIFIED','CANCELLED','EXPIRED')
     AND NEW.child_id IS OLD.child_id AND NEW.job_id IS OLD.job_id))
BEGIN SELECT RAISE(ABORT,'import unblock member cannot rearm'); END;
CREATE TRIGGER managed_import_unblock_member_retained BEFORE DELETE ON managed_import_unblock_members
BEGIN SELECT RAISE(ABORT,'import unblock scope is retained'); END;
"""


def present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_import_unblock*' LIMIT 1").fetchone() is not None


def validate(db):
    if (db.execute('SELECT COUNT(*) FROM managed_import_unblocks').fetchone()[0] > 128
            or db.execute('SELECT COUNT(*) FROM managed_import_unblock_members').fetchone()[0] > 1000000
            or db.execute('''SELECT 1 FROM managed_import_unblocks u LEFT JOIN managed_shun_requests r ON r.id=u.id
              WHERE r.id IS NULL OR json_extract(r.payload_json,'$.action')!='UNBLOCK_IMPORT'
              OR u.target_count!=(SELECT COUNT(*) FROM managed_import_unblock_members m WHERE m.root_id=u.id) LIMIT 1''').fetchone()
            or db.execute('''SELECT 1 FROM managed_import_unblock_members m LEFT JOIN managed_import_unblocks u ON u.id=m.root_id
              WHERE u.id IS NULL OR (m.state='WAITING' AND (m.child_id IS NOT NULL OR m.job_id IS NOT NULL))
              OR (m.state='QUEUED' AND (m.child_id IS NULL OR m.job_id IS NULL)) LIMIT 1''').fetchone()):
        raise BulkUnavailable('Complete retained import-unblock authority is required.')
    if db.execute('''SELECT 1 FROM managed_import_unblock_members m JOIN managed_import_unblocks u ON u.id=m.root_id
      LEFT JOIN managed_bulk_members b ON b.request_id=u.import_id AND b.device_id=m.device_id AND b.ip=m.ip
      WHERE b.request_id IS NULL OR b.classification NOT IN ('PROPOSE_ADD','PROPOSE_ADOPT')
      OR b.intent_id!=m.intent_id OR b.generation!=m.generation OR b.authorization_request_id!=m.authorization_request_id
      OR (m.job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM operation_jobs j JOIN operation_links l ON l.job_id=j.id
          WHERE j.id=m.job_id AND l.request_id=m.child_id AND j.device_id=m.device_id AND j.ip=m.ip AND j.action='REMOVE'))
      LIMIT 1''').fetchone():
        raise BulkUnavailable('Import-unblock ownership or delegated REMOVE evidence is incomplete.')
    try:
        for root in db.execute('''SELECT u.*,r.payload_json,r.requested_at AS consent_at FROM managed_import_unblocks u
          JOIN managed_shun_requests r ON r.id=u.id'''):
            value=json.loads(root['payload_json'])
            if (canonical(root['import_id'],root['scope_digest'],root['target_count'],value['reviewed_at'])!=root['payload_json']
                    or root['consent_at']!=root['requested_at']
                    or datetime.fromisoformat(root['expires_at'])-datetime.fromisoformat(root['requested_at'])!=timedelta(seconds=LIFETIME)):
                raise ValueError('Changed consent or deadline.')
    except (ValueError,KeyError,TypeError) as error:
        raise BulkUnavailable('Original cleanup scope and lifetime must remain exact.') from error


def pair_held(db, device, ip):
    return present(db) and db.execute('''SELECT 1 FROM managed_import_unblock_members m
      JOIN managed_import_unblocks u ON u.id=m.root_id WHERE m.device_id=? AND m.ip=?
      AND u.state='ACTIVE' AND m.state IN ('WAITING','ADMITTING','QUEUED','FAILED','UNVERIFIED') LIMIT 1''',
      (device, ip.packed)).fetchone() is not None


class ActiveImportCleanup(ValueError):
    """Saved cleanup authority prevents a separate offline recovery decision."""


def require_no_active_cleanup(db):
    """Offline epoch recovery cannot inherit a still-authorized cleanup task."""
    if present(db) and db.execute("SELECT 1 FROM managed_import_unblocks WHERE state='ACTIVE' LIMIT 1").fetchone():
        raise ActiveImportCleanup('Import cleanup is still active. Settle it or cancel its remaining removals before reviewing offline recovery. Cancellation does not resolve the interrupted command.')


def claimed_cancelled_request(db):
    """SQL predicate for a real in-flight cleanup claim revoked after dispatch."""
    if not present(db):return '0'
    return """(r.state='CANCELLED' AND EXISTS(SELECT 1 FROM managed_import_unblock_members m
      WHERE m.child_id=r.id AND m.job_id=l.job_id AND EXISTS(SELECT 1 FROM shun_events e
        WHERE e.request_id=r.id AND e.event_type='SHUN_OPERATION_RUNNING'
        AND json_extract(e.details_json,'$.operation_id')=m.job_id)))"""


def canonical(import_id, digest, count, reviewed_at):
    _uuid(import_id)
    if (type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)
            or type(count) is not int or not 1<=count<=100000 or type(reviewed_at) is not str
            or not reviewed_at.endswith('Z') or stamp(datetime.fromisoformat(reviewed_at)) != reviewed_at):
        raise ValueError('An exact current import scope and UTC review are required.')
    return json.dumps({'action':'UNBLOCK_IMPORT','import_id':import_id,'scope_digest':digest,
                       'target_count':count,'reviewed_at':reviewed_at,'lifetime_seconds':LIFETIME},sort_keys=True,separators=(',',':'))


class ImportUnblocks:
    def __init__(self, store, queue=None):
        self.store=store;self.queue=queue or OperationQueue(store);self.views=BulkPolicyViews(store)

    def initialize(self, *, enabled=False, connection=None):
        if enabled is not True: raise PermissionError('Explicit import-unblock profile initialization is required.')
        if not self.store.path.is_file():raise BulkUnavailable('Existing managed storage is required; no file was created.')
        with schema_connection(self.store,connection) as db, _atomic(db):
            if _state(db) is None: raise BulkUnavailable('Existing managed storage is required.')
            if present(db): return
            _quiescent(db)
            if db.execute("SELECT 1 FROM managed_bulk_device_executors WHERE state!='IDLE' LIMIT 1").fetchone():
                raise QueueConflict('Stop device writers before initializing import unblocking.')
            execute_schema(db,DDL);_state(db)

    def review(self, import_id):
        with self.views._snapshot() as db:
            view=ImportOwnership(self.store).read(db,import_id)
            return {**view,'reviewed_at':stamp(self.queue._now()),'can_confirm':present(db) and view['owned_count']>0,
                    'lifetime_seconds':LIFETIME}

    def confirm(self,key,import_id,digest,count,reviewed_at,subject,display_name,roles,*,enabled=False):
        if enabled is not True: raise PermissionError('Import unblocking is disabled.')
        _actor(subject,display_name,roles);_uuid(key)
        payload=canonical(import_id,digest,count,reviewed_at)
        with schema_connection(self.store) as db, _atomic(db):
            _state(db)
            if not present(db): raise BulkUnavailable('Initialize import-unblock storage explicitly.')
            old=db.execute('SELECT * FROM managed_shun_requests WHERE id=?',(key,)).fetchone()
            if old:
                if old['actor_subject']!=subject or old['payload_json']!=payload: raise ManagedConflict('Key belongs to another actor or scope.')
                return {**json.loads(old['result_json']),'replayed':True}
            _key_free(db,key)
            now=self.queue._now();timestamp=stamp(now)
            if not datetime.fromisoformat(reviewed_at)<=now<datetime.fromisoformat(reviewed_at)+timedelta(minutes=5):
                raise ManagedConflict('Review expired; inspect the current import again.')
            if mutations_suspended(db): raise QueueConflict('Mutations are suspended; no cleanup was accepted.')
            view=ImportOwnership(self.store).read(db,import_id)
            if not hmac.compare_digest(view['scope_digest'],digest) or view['owned_count']!=count:
                raise ManagedConflict('Import ownership changed; review again.')
            if view['attention_owned']: raise QueueConflict('Resolve uncertain owned operations before confirming cleanup.')
            if self.queue._recent_request_count(db,subject,now)>=10: raise QueueConflict('At most ten submissions per minute.')
            if (db.execute('SELECT COUNT(*) FROM managed_import_unblocks').fetchone()[0]>=128
                    or db.execute('SELECT COUNT(*) FROM managed_import_unblock_members').fetchone()[0]+count>1000000):
                raise QueueConflict('Retained import-unblock capacity is full; no task was saved.')
            rows=db.execute(f'''SELECT t.* FROM managed_bulk_members b JOIN managed_shun_targets t
              ON t.device_id=b.device_id AND t.ip=b.ip WHERE b.request_id=? AND {CATEGORY} IN ('OWNED_ADDED','OWNED_ADOPTED')
              ORDER BY b.device_id,b.ip''',(import_id,)).fetchall()
            if len(rows)!=count: raise BulkUnavailable('Complete current owned scope is required.')
            from .bulk_ordered_removals import BulkOrderedRemovalScopes
            frozen=[]
            for row in rows:
                address=IPv4Address(row['ip'])
                if pair_held(db,row['device_id'],address): raise ManagedConflict('Another cleanup already owns a target.')
                job=db.execute("SELECT * FROM operation_jobs WHERE device_id=? AND ip=? AND state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION')",(row['device_id'],row['ip'])).fetchone()
                evidence=claim=None
                if job and job['action']=='ADD':
                    if job['state']=='QUEUED':
                        from .managed_restoration import validate_binding
                        attempt=db.execute('SELECT * FROM managed_bulk_attempts WHERE job_id=?',(job['id'],)).fetchone()
                        if attempt is None or any(attempt[f]!=row[f] for f in ('intent_id','generation','authorization_request_id')):
                            raise QueueConflict('Unstarted addition is not owned by this import.')
                        validate_binding(db,attempt,job)
                        self.queue._finish(db,job,'CANCELLED','Import unblocking stopped this unstarted addition')
                    else:
                        inspected=BulkOrderedRemovalScopes(self.store).read(db,address,device_id=row['device_id'],now=now)
                        target=inspected['targets'][0]
                        if target['disposition']!='WAITING_ADD': raise QueueConflict('Running addition lacks exact settlement evidence.')
                        evidence=target['predecessor']
                        claim=dict(db.execute('SELECT * FROM shun_events WHERE id=?',(evidence['claim_event_id'],)).fetchone())
                        claim={k:v.hex() if isinstance(v,bytes) else v for k,v in claim.items()}
                frozen.append((row,evidence,claim))
            revision=view['managed_revision']+1
            result={'operation_id':key,'import_id':import_id,'status':'accepted','target_count':count,
                    'retired_targets':count,'verified_removal':False,'replayed':False,'expires_at':stamp(now+timedelta(seconds=LIFETIME))}
            db.execute('INSERT INTO managed_shun_requests VALUES (?,?,?,?,?,?,?)',(key,subject,display_name,json.dumps(roles),payload,json.dumps(result),timestamp))
            for row,evidence,claim in frozen:
                db.execute('INSERT INTO managed_import_unblock_members VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key,row['device_id'],row['ip'],row['intent_id'],row['generation'],row['authorization_request_id'],row['revision'],
                     json.dumps(evidence) if evidence else None,json.dumps(claim,sort_keys=True) if claim else None,None,None,'WAITING'))
                db.execute('UPDATE managed_shun_targets SET enabled=0,revision=?,updated_at=?,retired_at=? WHERE device_id=? AND ip=?',
                           (revision,timestamp,timestamp,row['device_id'],row['ip']))
                self.store._insert_event(db,'MANAGED_SHUN_RETIRED',row['device_id'],IPv4Address(row['ip']),None,subject,display_name,roles,key,
                                         {'source':SCOPE,'import_id':import_id,'intent_id':row['intent_id'],'generation':row['generation']},timestamp)
            db.execute('UPDATE managed_bulk_registry SET revision=? WHERE id=1',(revision,))
            db.execute('INSERT INTO managed_import_unblocks VALUES (?,?,?,?,?,?,?,?)',
                       (key,import_id,digest,count,revision,timestamp,result['expires_at'],'ACTIVE'))
            self.store._insert_event(db,'IMPORT_UNBLOCK_REQUESTED',None,None,None,subject,display_name,roles,key,
                                     {'import_id':import_id,'target_count':count,'verified_removal':False},timestamp)
            if not now<=self.queue._now()<datetime.fromisoformat(reviewed_at)+timedelta(minutes=5):
                raise ManagedConflict('Review expired during confirmation; nothing was committed.')
            _state(db);self.queue._bump(db)
            return result

    def status(self,key=None,page=1,*,import_id=None):
        with self.views._snapshot() as db:
            _state(db)
            if not present(db): return {'available':False,'tasks':[],'read_only':True}
            roots=db.execute('''SELECT u.*,r.actor_subject,r.actor_display_name FROM managed_import_unblocks u
              JOIN managed_shun_requests r ON r.id=u.id '''+('WHERE u.id=? ' if key else 'WHERE u.import_id=? ' if import_id else "WHERE u.state='ACTIVE' ")+
              'ORDER BY u.requested_at DESC LIMIT 20', (key,) if key else (import_id,) if import_id else ()).fetchall()
            tasks=[]
            from .import_ownership import import_labels
            labels=import_labels(db,[row['import_id'] for row in roots])
            for root in roots:
                counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM managed_import_unblock_members WHERE root_id=? GROUP BY state',(root['id'],))}
                task={**dict(root),'counts':counts,'verified':counts.get('VERIFIED',0)+counts.get('NOOP',0)}
                task['import_label']=labels[root['import_id']]['label']
                task['attention']=sum(counts.get(s,0) for s in ('FAILED','UNVERIFIED'))+db.execute('''SELECT COUNT(*) FROM managed_import_unblock_members m
                  JOIN operation_jobs j ON j.id=json_extract(m.predecessor_json,'$.job_id') WHERE m.root_id=? AND m.state='WAITING'
                  AND j.state IN ('FAILED','UNVERIFIED')''',(root['id'],)).fetchone()[0]
                if key:
                    if type(page) is not int or not 1<=page<=max(1,(root['target_count']+99)//100): raise ValueError('Select a valid task page.')
                    task['targets']=[{**dict(r),'ip':str(IPv4Address(r['ip']))} for r in db.execute('''SELECT m.device_id,m.ip,m.state,d.hostname AS device_hostname
                      FROM managed_import_unblock_members m JOIN devices d ON d.id=m.device_id WHERE root_id=? ORDER BY m.device_id,m.ip LIMIT 100 OFFSET ?''',(key,(page-1)*100))]
                    task.update(page=page,pages=max(1,(root['target_count']+99)//100))
                tasks.append(task)
            return {'available':True,'tasks':tasks,'read_only':True}

    def grouped_queue(self,queue):
        """Hide active internal batch cards, retaining ordinary attention rows/counts."""
        with self.views._snapshot() as db:
            if not present(db):return queue
            visible=list(queue.get('items',[]));progress=queue.get('progress',{})
            job_ids=[row['id'] for row in visible]
            requests=list(progress.get('requests',[]));request_ids=[row['id'] for row in requests]
            def refs(column,ids):
                if not ids:return set()
                return {row[0] for row in db.execute('SELECT DISTINCT '+column+' FROM managed_import_unblock_members WHERE '+column+' IN ('+','.join('?' for _ in ids)+')',ids)}
            jobs=refs('job_id',job_ids);children=refs('child_id',request_ids)
            internal=db.execute('''SELECT COUNT(DISTINCT r.id) FROM operation_requests r
              JOIN operation_links l ON l.request_id=r.id JOIN operation_jobs j ON j.id=l.job_id
              WHERE r.state='ACTIVE' AND j.state IN ('QUEUED','RUNNING')
              AND EXISTS(SELECT 1 FROM managed_import_unblock_members m WHERE m.child_id=r.id)''').fetchone()[0]
            grouped=db.execute('''SELECT COUNT(*) FROM operation_jobs j WHERE j.state IN ('QUEUED','RUNNING','AWAITING_CONFIRMATION')
              AND EXISTS(SELECT 1 FROM managed_import_unblock_members m WHERE m.job_id=j.id)''').fetchone()[0]
            return {**queue,'items':[row for row in visible if row['id'] not in jobs or row['state'] not in ('QUEUED','RUNNING','AWAITING_CONFIRMATION')],
                    'grouped_cleanup_operations':grouped,
                    'progress':{**progress,'requests':[row for row in requests if row['id'] not in children],
                                'total_requests':max(0,progress.get('total_requests',0)-internal)}}

    def cancel(self,key,subject,display_name,roles):
        _actor(subject,display_name,roles);_uuid(key)
        with schema_connection(self.store) as db, _atomic(db):
            _state(db)
            root=db.execute('''SELECT u.*,r.actor_subject FROM managed_import_unblocks u
              JOIN managed_shun_requests r ON r.id=u.id WHERE u.id=?''',(key,)).fetchone()
            if root is None:raise ManagedConflict('Cleanup task not found.')
            if root['actor_subject']!=subject and 'Administrator' not in roles:raise PermissionError('Only its owner or Administrator can cancel this task.')
            if root['state']!='ACTIVE':return {'operation_id':key,'state':root['state'],'replayed':True}
            db.execute("UPDATE managed_import_unblocks SET state='CANCELLED' WHERE id=?",(key,))
            db.execute("UPDATE managed_import_unblock_members SET state='CANCELLED' WHERE root_id=? AND state='WAITING'",(key,))
            self._cancel_unstarted(db,key)
            self.store._insert_event(db,'IMPORT_UNBLOCK_CANCELLED',None,None,None,subject,display_name,roles,key,
                                     {'maintenance_resumed':False,'running_commands_interrupted':False},stamp(self.queue._now()))
            self.queue._bump(db)
            return {'operation_id':key,'state':'CANCELLED','replayed':False}

    def _cancel_unstarted(self,db,key):
        """Revoke this task, preserving independent requesters and claimed audit."""
        children=[r[0] for r in db.execute('''SELECT DISTINCT m.child_id FROM managed_import_unblock_members m
          JOIN operation_jobs j ON j.id=m.job_id WHERE m.root_id=? AND j.state IN ('QUEUED','RUNNING')''',(key,))]
        for job in db.execute('''SELECT j.* FROM managed_import_unblock_members m JOIN operation_jobs j ON j.id=m.job_id
          WHERE m.root_id=? AND j.state='QUEUED' ''',(key,)).fetchall():
            other=db.execute('''SELECT 1 FROM operation_links l JOIN operation_requests r ON r.id=l.request_id
              WHERE l.job_id=? AND r.state='ACTIVE' AND r.expires_at>? AND r.id NOT IN ('''+','.join('?' for _ in children)+') LIMIT 1',
              (job['id'],stamp(self.queue._now()),*children)).fetchone()
            if not other:self.queue._finish(db,job,'CANCELLED','Import-unblock authority ended before dispatch')
            else:db.execute("UPDATE managed_import_unblock_members SET state='CANCELLED' WHERE root_id=? AND job_id=? AND state='QUEUED'",(key,job['id']))
        for child in children:db.execute("UPDATE operation_requests SET state='CANCELLED' WHERE id=?",(child,))


if __name__=='__main__':
    import argparse
    from pathlib import Path

    from .store import Store
    parser=argparse.ArgumentParser(description='Explicit quiescent initialization of optional import-cleanup storage. Stop API/Web first.')
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--initialize',action='store_true',required=True)
    args=parser.parse_args()
    ImportUnblocks(Store(args.database)).initialize(enabled=args.initialize)
    print(json.dumps({'profile':'import-unblocks-v1','initialized':True,'device_work_admitted':False}))
