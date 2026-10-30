"""Owner-bound v2 draft workspace, frozen reports and pure proposal inspection."""

from typing import Annotated

import httpx
from fastapi import HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .bulk_confirmation_view import validate_receipts
from .bulk_intent import _uuid
from .bulk_preparation_api import PreparationInput
from .bulk_preparation_view import (
    operation_key,
    validate_creation,
    validate_devices,
    validate_list,
    validate_proposal,
    validate_report,
)
from .import_preview import MAX_FORM_BYTES, parse_blocklist

WEB = '/managed-imports/v2'
API = '/api/v2/managed-imports/'


def register_bulk_preparation_web(app, settings, *, render, identity_for, operator_for, client_for, form_for, csrf_for):
    def actor(identity):
        return {'subject': identity.subject, 'display_name': identity.display_name, 'roles': list(identity.roles)}

    def metadata(client):
        response = client.get('/api/v1/status')
        value = response.json()
        if (response.status_code != 200 or type(value) is not dict or type(value.get('managed_policy_format')) is not int
                or value['managed_policy_format'] != 2 or value.get('runtime_mode') not in ('continuous-observation', 'continuous-managed')
                or value.get('bulk_import_preparation_available') is not True):
            raise httpx.RequestError('Compatible v2 preparation workspace unavailable; no legacy fallback')
        return value

    def read_json(client, name, body):
        response = client.post(API + name, json=body)
        if response.status_code in {403, 409, 422, 429}:
            raise HTTPException(response.status_code, 'This private draft or requested page is unavailable to the current owner/state. No device work was admitted.')
        if response.status_code != 200: raise httpx.RequestError('Private v2 draft state unavailable')
        return response.json()

    def workspace_data(identity):
        with client_for(settings) as client:
            state = metadata(client)
            drafts = validate_list(read_json(client, 'preparations', {'actor': actor(identity)}))
            response = client.get('/api/v1/import-devices')
            if response.status_code != 200: raise httpx.RequestError('Public device list unavailable')
            devices = validate_devices(response.json())
            receipts = None
            if state.get('bulk_policy_receipts_available') is True:
                try: receipts = validate_receipts(read_json(client, 'receipts', {'actor': actor(identity)}))
                except (httpx.HTTPError, ValueError, TypeError, KeyError, HTTPException): pass
        return state, drafts, devices, receipts

    def workspace(request, identity, *, message=None, code=200, fields=None, unknown=False):
        fields = fields or {}
        state, drafts, devices, receipts = None, None, [], None
        try:
            state, drafts, devices, receipts = workspace_data(identity)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, HTTPException):
            message = message or 'Private draft workspace is unavailable. No empty/healthy state or successful creation is inferred.'
            code = 503
        return render(request, 'bulk-import-workspace.html', {'identity': identity, 'refresh': state,
            'drafts': drafts, 'devices': devices, 'message': message, 'creation_unknown': unknown,
            'receipts': receipts,
            'source_text': fields.get('text', [''])[0], 'draft_label': fields.get('label', [''])[0],
            'draft_reason': fields.get('reason', [''])[0], 'selected_devices': fields.get('device_ids', []),
            'active_page': 'imports', 'auto_request': False, 'frozen_view': True}, code)

    def canonical_key(key):
        try:
            _uuid(key)
        except ValueError as error:
            raise HTTPException(422, 'Use the exact original canonical preparation UUID.') from error
        return key

    @app.get(WEB)
    def index(request: Request):
        return workspace(request, identity_for(request, settings.development_auth))

    @app.post(WEB + '/prepare')
    async def prepare(request: Request):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'text', 'device_ids', 'label', 'reason'}, max_bytes=MAX_FORM_BYTES)
        csrf_for(request, fields.get('csrf', [''])[0])
        try:
            raw_devices = fields.get('device_ids', [])
            devices = [int(value) for value in raw_devices]
            if [str(value) for value in devices] != raw_devices: raise ValueError('Use canonical device IDs.')
            change = PreparationInput.model_validate({'actor': actor(identity), 'text': fields.get('text', [''])[0],
                'device_ids': devices, 'label': fields.get('label', [''])[0], 'reason': fields.get('reason', [''])[0]})
            parsed = parse_blocklist(change.text)
        except (ValueError, TypeError):
            return await run_in_threadpool(workspace, request, identity,
                message='Invalid draft input. Select 1–10 distinct devices and use at most 1 MiB UTF-8, 20000 lines and 10000 parsed rows; label/reason limits are 100/500 characters.',
                code=422, fields=fields)
        return await run_in_threadpool(save, request, identity, change, len(parsed['ips']) * len(devices), fields)

    def save(request, identity, change, expected_count, fields):
        attempted = False
        try:
            with client_for(settings) as client:
                metadata(client)
                # No automatic retry. A lost response may have committed a harmless draft.
                attempted = True
                response = client.post(API + 'prepare', json=change.model_dump())
            if response.status_code == 201:
                saved = validate_creation(response.json(), expected_count)
                return RedirectResponse(WEB + '/' + saved['plan_id'], status_code=303)
            if response.status_code in {403, 409, 422, 429}:
                return workspace(request, identity, message='Draft creation was rejected. Inspect saved drafts and current input before another attempt.',
                                 code=response.status_code, fields=fields)
            raise httpx.RequestError('Draft creation outcome unconfirmed')
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return workspace(request, identity, message=('Draft creation outcome is unknown. Inspect your saved preparations before explicitly starting another draft.'
                if attempted else 'Compatible draft API unavailable. This attempt was not submitted; inspect any earlier outcome.'),
                code=503, fields=fields, unknown=attempted)

    def load_report(client, identity, key, page):
        value = read_json(client, 'preparation', {'actor': actor(identity), 'preparation_id': key, 'page': page})
        return validate_report(value, key, identity.subject, page)

    def report_view(request, identity, key, page, *, review=False, cancellation=None, message=None, code=200):
        value, proposed, state = None, None, None
        try:
            with client_for(settings) as client:
                state = metadata(client)
                value = load_report(client, identity, key, page)
                if review:
                    operator_for(identity)
                    raw = read_json(client, 'proposal', {'actor': actor(identity), 'preparation_id': key,
                        'preparation_digest': value['digest'], 'operation_id': operation_key(key)})
                    proposed = validate_proposal(raw, value)
        except HTTPException:
            if cancellation is None: raise
            value, message, code = None, 'Draft cancellation confirmed, but current report is unavailable. No standing policy or device work was cancelled.', 503
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            value, proposed = None, None
            message = ('Draft cancellation confirmed, but current report is unavailable. No standing policy or device work was cancelled.'
                       if cancellation is not None else 'Original draft/proposal report is unavailable or invalid. No policy or device success is inferred.')
            code = 503
        return render(request, 'bulk-import-report.html', {'identity': identity, 'refresh': state, 'draft': value,
            'proposal': proposed, 'review_mode': review, 'preparation_id': key, 'message': message,
            'cancellation': cancellation, 'active_page': 'imports', 'auto_request': False, 'frozen_view': True}, code)

    @app.get(WEB + '/{preparation_id}')
    def report(request: Request, preparation_id: str, page: Annotated[int, Query(ge=1, le=1000)] = 1):
        return report_view(request, identity_for(request, settings.development_auth), canonical_key(preparation_id), page)

    @app.get(WEB + '/{preparation_id}/review')
    def review(request: Request, preparation_id: str, page: Annotated[int, Query(ge=1, le=1000)] = 1):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        return report_view(request, identity, canonical_key(preparation_id), page, review=True)

    @app.post(WEB + '/{preparation_id}/cancel')
    async def cancel(request: Request, preparation_id: str):
        identity = identity_for(request, settings.development_auth)  # Owner may revoke after role loss.
        fields = await form_for(request, allowed={'csrf'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        return await run_in_threadpool(revoke, request, identity, canonical_key(preparation_id))

    def revoke(request, identity, key):
        try:
            with client_for(settings) as client:
                metadata(client)
                result = read_json(client, 'cancel-preparation', {'actor': actor(identity), 'preparation_id': key})
            expected = {'intent_format': 2, 'preparation_id': key, 'can_execute': False,
                        'policy_saved': False, 'device_work_admitted': False}
            if (type(result) is not dict or set(result) != set(expected) | {'cancelled'}
                    or type(result['cancelled']) is not bool or any(type(result[field]) is not type(item)
                        or result[field] != item for field, item in expected.items())):
                raise ValueError('Draft-only cancellation receipt unconfirmed')
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return report_view(request, identity, key, 1, message='Draft cancellation outcome is unknown. Inspect or retry only this original draft.', code=503)
        return report_view(request, identity, key, 1, cancellation=result)
