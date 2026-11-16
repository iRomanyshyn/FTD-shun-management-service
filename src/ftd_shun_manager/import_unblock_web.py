"""Cookie/actor-bound import cleanup consent; original-key retry only."""
import json
from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .import_unblocks import canonical
from .managed_review import ManagedRemovalReviews


@dataclass(frozen=True)
class Review:
    token:str
    subject:str
    cookie_hash:str
    request_id:str
    expires:float
    expires_at:str
    payload_json:str
    summary_json:str


def register(app,settings,*,render,identity_for,operator_for,client_for,form_for,csrf_for):
    reviews=ManagedRemovalReviews(ttl=300)

    def read(path):
        try:
            with client_for(settings) as client:response=client.get(path)
            response.raise_for_status();return response.json()
        except httpx.HTTPError as error:raise HTTPException(503,'Cleanup state is temporarily unavailable. No new operation was submitted.') from error

    async def fields_for(request,allowed):
        raw=await form_for(request,allowed=allowed,max_bytes=4096)
        if any(len(values)!=1 for values in raw.values()):raise HTTPException(422,'Submit each form field once.')
        return {key:values[0] for key,values in raw.items()}

    def view(request,identity,review,message=None,code=200,result=None):
        try:state=read('/api/v1/status')
        except HTTPException:state=None
        return render(request,'import-unblock-review.html',{'identity':identity,'review':review,
            'summary':json.loads(review.summary_json),'message':message,'result':result,
            'refresh':state,'active_page':'imports','auto_request':False,'frozen_view':True},code)

    @app.post('/import-unblocks/review')
    async def prepare(request:Request):
        identity=identity_for(request,settings.development_auth);operator_for(identity)
        fields=await fields_for(request,{'csrf','import_id'});csrf_for(request,fields.get('csrf',''))
        try:import_id=str(UUID(fields.get('import_id','')))
        except ValueError as error:raise HTTPException(422,'Select an exact import reference.') from error
        return await run_in_threadpool(prepare_review,request,identity,import_id)

    def prepare_review(request,identity,import_id):
        summary=read('/api/v2/import-unblocks/review/'+import_id)
        if summary.get('can_confirm') is not True:raise HTTPException(409,'No currently owned addresses are available, or cleanup storage is not initialized.')
        payload=canonical(import_id,summary['scope_digest'],summary['owned_count'],summary['reviewed_at'])
        try:
            review=reviews._save(Review,identity.subject,request.cookies.get('ftd_shun_csrf',''),
                                 payload_json=payload,summary_json=json.dumps(summary))
        except ValueError as error:raise HTTPException(409,str(error)) from error
        return view(request,identity,review)

    @app.post('/import-unblocks/confirm')
    async def confirm(request:Request):
        identity=identity_for(request,settings.development_auth);operator_for(identity)
        fields=await fields_for(request,{'csrf','review_token','confirm_action'});csrf_for(request,fields.get('csrf',''))
        try:review=reviews.get(fields.get('review_token',''),identity.subject,request.cookies.get('ftd_shun_csrf',''))
        except ValueError as error:raise HTTPException(409,'This confirmation expired or belongs to another session. Open a fresh review.') from error
        return await run_in_threadpool(submit,request,identity,review,fields)

    def submit(request,identity,review,fields):
        if fields.get('confirm_action')!='unblock-import':return view(request,identity,review,'Confirm the reviewed import cleanup explicitly.',422)
        payload=json.loads(review.payload_json)
        body={'actor':identity.__dict__,'import_id':payload['import_id'],'scope_digest':payload['scope_digest'],
              'target_count':payload['target_count'],'reviewed_at':payload['reviewed_at']}
        try:
            with client_for(settings) as client:
                response=client.post('/api/v2/import-unblocks',json=body,headers={'Idempotency-Key':review.request_id})
        except httpx.HTTPError:
            return view(request,identity,review,'Cleanup acceptance is unknown. Check the original task or retry this same confirmation.',503)
        if response.status_code!=202:
            try:detail=response.json().get('detail','Check the original task before retrying.')
            except ValueError:detail='State API is unavailable. Check the original task before retrying.'
            return view(request,identity,review,'Cleanup was not confirmed. '+str(detail)[:500],response.status_code if response.status_code>=400 else 503)
        try:result=response.json()
        except ValueError:return view(request,identity,review,'Cleanup acceptance is unconfirmed. Retry only this same confirmation.',503)
        if result.get('operation_id')!=review.request_id or result.get('target_count')!=payload['target_count'] or result.get('verified_removal') is not False:
            raise HTTPException(503,'Cleanup acceptance could not be verified. Inspect the original task.')
        return view(request,identity,review,result=result)

    @app.get('/import-unblocks/{key}')
    def task(request:Request,key:UUID,page:int=1):
        identity=identity_for(request,settings.development_auth)
        result=read('/api/v2/import-unblocks/'+str(key)+'?page='+str(page))
        if len(result.get('tasks',[]))!=1:raise HTTPException(404,'Cleanup task not found.')
        return render(request,'import-unblock-status.html',{'identity':identity,'task':result['tasks'][0],
            'refresh':read('/api/v1/status'),'active_page':'imports','auto_request':False})

    @app.post('/import-unblocks/{key}/cancel-remaining')
    async def cancel_remaining(request:Request,key:UUID):
        identity=identity_for(request,settings.development_auth);operator_for(identity)
        fields=await fields_for(request,{'csrf'});csrf_for(request,fields.get('csrf',''))
        return await run_in_threadpool(cancel_task,identity,key)

    def cancel_task(identity,key):
        try:
            with client_for(settings) as client:response=client.post('/api/v2/import-unblocks/'+str(key)+'/cancel',json={'actor':identity.__dict__})
            response.raise_for_status()
        except httpx.HTTPError as error:raise HTTPException(503,'Cancellation could not be confirmed. Open the original task before retrying.') from error
        return RedirectResponse('/import-unblocks/'+str(key),303)
