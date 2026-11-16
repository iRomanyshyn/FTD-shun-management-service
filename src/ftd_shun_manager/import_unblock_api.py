"""Explicit whole-import cleanup API over its optional durable profile."""
import sqlite3
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import Field

from .bulk_preparation_api import PreparationOwner
from .managed_safety import ManagedStateUnavailable
from .managed_shuns import ManagedConflict


class Confirmation(PreparationOwner):
    import_id: str = Field(min_length=36,max_length=36)
    scope_digest: str = Field(min_length=64,max_length=64)
    target_count: int = Field(strict=True,ge=1,le=100000)
    reviewed_at: str = Field(min_length=20,max_length=40)


def register(app,runtime):
    def service(write=False):
        if runtime is None or (write and not runtime.settings.import_unblocks_enabled):
            raise HTTPException(503,'Import unblocking is not enabled in this service profile.')
        return runtime.import_unblocks

    def failure(error):
        if isinstance(error,PermissionError):return HTTPException(403,str(error))
        if isinstance(error,ManagedStateUnavailable):return HTTPException(503,'Retained cleanup evidence is unavailable.')
        if isinstance(error,ManagedConflict):return HTTPException(409,str(error))
        if isinstance(error,sqlite3.Error):return HTTPException(503,'Cleanup outcome is unconfirmed. Inspect the original task or retry the same key.')
        return HTTPException(409,str(error))

    @app.get('/api/v2/import-unblocks/review/{import_id}')
    def review(import_id:UUID):
        try:
            result=service().review(str(import_id))
            result['can_confirm']=result['can_confirm'] and runtime.settings.import_unblocks_enabled and not result['attention_owned']
            return result
        except (ValueError,sqlite3.Error) as error:raise failure(error) from error

    @app.get('/api/v2/import-unblocks')
    def tasks():
        try:return service().status()
        except (ValueError,sqlite3.Error) as error:raise failure(error) from error

    @app.get('/api/v2/import-unblocks/{key}')
    def task(key:UUID,page:int=1):
        try:return service().status(str(key),page)
        except (ValueError,sqlite3.Error) as error:raise failure(error) from error

    @app.post('/api/v2/import-unblocks',status_code=202)
    def confirm(change:Confirmation,request:Request):
        try:
            result=service(True).confirm(request.headers.get('Idempotency-Key',''),change.import_id,change.scope_digest,
                change.target_count,change.reviewed_at,change.actor.subject,change.actor.display_name,tuple(change.actor.roles),enabled=True)
        except (PermissionError,ValueError,sqlite3.Error) as error:raise failure(error) from error
        runtime.note_state_change()
        return result

    @app.post('/api/v2/import-unblocks/{key}/cancel')
    def cancel(key:UUID,change:PreparationOwner):
        try:result=service(True).cancel(str(key),change.actor.subject,change.actor.display_name,tuple(change.actor.roles))
        except (PermissionError,ValueError,sqlite3.Error) as error:raise failure(error) from error
        runtime.note_state_change()
        return result
