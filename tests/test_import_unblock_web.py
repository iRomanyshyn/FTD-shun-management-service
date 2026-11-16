"""Actual cleanup API/BFF consent on disposable state, without SSH or lab access."""
import asyncio
import re
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from test_bulk_policy import confirm, dump, prepare
from test_import_unblocks import bulk as bulk_fixture
from test_import_unblocks import cancellation_controls as cancellation_fixture
from test_import_unblocks import cleanup as cleanup_fixture
from test_import_unblocks import dispatch as dispatch_fixture
from test_import_unblocks import journal as journal_fixture
from test_import_unblocks import leases as leases_fixture
from test_import_unblocks import ordered as ordered_fixture
from test_import_unblocks import promoter as promoter_fixture
from test_import_unblocks import waits as waits_fixture

from ftd_shun_manager import web
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_unblock_api import register

bulk=bulk_fixture
cancellation_controls=cancellation_fixture
cleanup=cleanup_fixture
dispatch=dispatch_fixture
journal=journal_fixture
leases=leases_fixture
ordered=ordered_fixture
promoter=promoter_fixture
waits=waits_fixture


def test_html_review_original_key_retry_status_and_cancel(cleanup,bulk,monkeypatch):
    imported=confirm(bulk,prepare(bulk,'198.51.100.1\n198.51.100.2')[1])['operation_id']
    api=FastAPI()
    runtime=SimpleNamespace(settings=SimpleNamespace(import_unblocks_enabled=True),import_unblocks=cleanup,note_state_change=lambda:None)
    register(api,runtime)
    @api.get('/api/v1/status')
    def state():return {'runtime_mode':'continuous-managed','managed_policy_format':2,'devices':{},'queue':{'counts':{},'items':[]},'import_unblocks_available':True}
    settings=replace(Settings.from_environment(),agent_mode='disabled',device_inventory_path=None)
    calls=[];lost=[True]
    async def scenario():
        loop=asyncio.get_running_loop()
        def transport(request):
            calls.append((request.method,request.url.path,request.content,request.headers.get('Idempotency-Key')))
            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(api),base_url='http://internal') as client:
                    return await client.request(request.method,str(request.url),content=request.content,headers=request.headers)
            response=asyncio.run_coroutine_threadsafe(send(),loop).result(15)
            if request.method=='POST' and request.url.path=='/api/v2/import-unblocks' and lost[0]:
                lost[0]=False
                return httpx.Response(503,json={'detail':'Synthetic lost reply after commit'})
            return httpx.Response(response.status_code,content=response.content,headers=response.headers)
        monkeypatch.setattr(web,'api_client',lambda _:httpx.Client(transport=httpx.MockTransport(transport),base_url='http://internal'))
        app=web.create_app(settings)
        headers={'Remote-User':'alice','Remote-Groups':'ftd-shun-operators','Accept':'text/html'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://fixture.test',headers=headers) as client:
            await client.get('/import-unblocks/'+str(uuid4()))
            csrf=client.cookies.get('ftd_shun_csrf');assert csrf
            before=dump(cleanup.store)
            review=await client.post('/import-unblocks/review',data={'csrf':csrf,'import_id':imported})
            assert review.status_code==200 and '2 device/IP pairs' in review.text
            assert dump(cleanup.store)==before
            token=re.search('name="review_token" value="([^"]+)"',review.text)[1]
            fields={'csrf':csrf,'review_token':token}
            invalid=await client.post('/import-unblocks/confirm',data=fields|{'confirm_action':'nonsense'})
            assert invalid.status_code==422 and 'text/html' in invalid.headers['content-type']
            uncertain=await client.post('/import-unblocks/confirm',data=fields|{'confirm_action':'unblock-import'})
            assert uncertain.status_code==503 and token in uncertain.text
            replay=await client.post('/import-unblocks/confirm',data=fields|{'confirm_action':'unblock-import'})
            assert replay.status_code==200 and 'Cleanup task accepted' in replay.text
            submissions=[call for call in calls if call[:2]==('POST','/api/v2/import-unblocks')]
            assert len(submissions)==2 and submissions[0][2:]==submissions[1][2:]
            key=submissions[0][3]
            page=await client.get('/import-unblocks/'+key)
            assert page.status_code==200 and 'Cancel remaining removals' in page.text and 'Synthetic' not in page.text
            cancelled=await client.post('/import-unblocks/'+key+'/cancel-remaining',data={'csrf':csrf})
            assert cancelled.status_code==303
            assert cleanup.status(key)['tasks'][0]['state']=='CANCELLED'
    asyncio.run(scenario())
