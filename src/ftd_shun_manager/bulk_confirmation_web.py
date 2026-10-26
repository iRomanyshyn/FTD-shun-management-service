"""Explicit suspended standing consent and owner historical receipts; no FTD."""

from typing import Annotated

import httpx
from fastapi import HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from .bulk_confirmation_view import (
    BulkConfirmationReviews,
    validate_policy_receipt,
    validate_receipt_page,
)
from .bulk_intent import _uuid, decode_bulk_descriptor
from .bulk_preparation_view import operation_key, validate_proposal, validate_report
from .import_review import ReviewUnavailable

API, WEB = '/api/v2/managed-imports/', '/managed-imports/v2'


def register_bulk_confirmation_web(app, settings, *, enabled, concurrent_enabled=False,
                                   render, identity_for, operator_for, client_for, form_for, csrf_for):
    reviews = BulkConfirmationReviews(settings.sensitive_action_max_age_seconds)

    def actor(identity):
        return {'subject': identity.subject, 'display_name': identity.display_name, 'roles': list(identity.roles)}

    def state(client):
        response = client.get('/api/v1/status')
        value = response.json()
        if (response.status_code != 200 or type(value) is not dict or type(value.get('managed_policy_format')) is not int
                or value['managed_policy_format'] != 2 or value.get('runtime_mode') != 'continuous-observation'
                or value.get('bulk_import_preparation_available') is not True):
            raise httpx.RequestError('Compatible standing-import API unavailable')
        return value

    def read(client, name, body):
        response = client.post(API + name, json=body)
        if response.status_code in {403, 409, 422, 429}:
            raise HTTPException(response.status_code, 'Original import review/receipt is unavailable to the current actor or state.')
        if response.status_code != 200: raise httpx.RequestError('Original import review/receipt unavailable')
        return response.json()

    def view(request, identity, review, metadata=None, *, report=None, result=None, message=None, code=200, count='', consent=False):
        return render(request, 'bulk-confirmation-review.html', {'identity': identity, 'review': review,
            'refresh': metadata, 'draft': report, 'result': result, 'message': message,
            'typed_count': count, 'consent': consent, 'bulk_policy_local_enabled': enabled,
            'bulk_policy_local_concurrent': concurrent_enabled,
            'active_page': 'imports', 'auto_request': False, 'frozen_view': True}, code)

    @app.post(WEB + '/{preparation_id}/confirmation-review')
    async def prepare(request: Request, preparation_id: str):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        try: _uuid(preparation_id)
        except ValueError as error: raise HTTPException(422, 'Use the original canonical preparation UUID.') from error
        return await run_in_threadpool(prepare_review, request, identity, preparation_id)

    def prepare_review(request, identity, key):
        try:
            with client_for(settings) as client:
                metadata = state(client)
                report = validate_report(read(client, 'preparation', {'actor': actor(identity), 'preparation_id': key, 'page': 1}), key, identity.subject, 1)
                proposal = validate_proposal(read(client, 'proposal', {'actor': actor(identity), 'preparation_id': key,
                    'preparation_digest': report['digest'], 'operation_id': operation_key(key)}), report)
            mode = metadata.get('bulk_policy_concurrent_enabled', False)
            suspension = metadata.get('managed_execution_suspended') if mode is True else True
            review = reviews.prepare(identity.subject, request.cookies.get('ftd_shun_csrf', ''), report, proposal,
                                     concurrent=mode, expected_suspended=suspension)
        except ReviewUnavailable as error: raise HTTPException(409, str(error)) from error
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, 'Standing review invalid/unavailable; no policy was submitted.') from error
        return view(request, identity, review, metadata, report=report)

    async def fields_review(request, *, paging=False):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'review', 'page', 'accepted_count', 'maintain_present'} if paging else {'csrf', 'review', 'accepted_count', 'maintain_present'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        try:
            review = reviews.get(fields.get('review', [''])[0], identity.subject, request.cookies.get('ftd_shun_csrf', ''))
        except ReviewUnavailable as error: raise HTTPException(409, str(error)) from error
        return identity, review, fields

    @app.post(WEB + '/confirmation-review/page')
    async def page_review(request: Request):
        identity, review, fields = await fields_review(request, paging=True)
        try:
            raw = fields.get('page', [''])[0]
            page = int(raw)
            if str(page) != raw or not 1 <= page <= 1000: raise ValueError('Invalid canonical page')
        except ValueError as error: raise HTTPException(422, 'Use a page within this exact frozen review.') from error
        count = fields.get('accepted_count', [''])[0]
        consent = fields.get('maintain_present', [''])[0]
        if (count and (not count.isascii() or not count.isdecimal() or len(count) > 6)) or consent not in {'', 'true'}:
            raise HTTPException(422, 'Invalid confirmation draft fields; nothing was submitted.')
        return await run_in_threadpool(read_page, request, identity, review, page, count, consent == 'true')

    def read_page(request, identity, review, page, count, consent):
        try:
            with client_for(settings) as client:
                metadata = state(client)
                report = validate_report(read(client, 'preparation', {'actor': actor(identity),
                    'preparation_id': review.summary['plan_id'], 'page': page}), review.summary['plan_id'], identity.subject, page)
            if any(report[key] != value for key, value in review.summary.items()):
                raise ValueError('Original frozen review metadata changed')
            reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, ReviewUnavailable) as error:
            raise HTTPException(503, 'Frozen page unavailable; no scope was rebased or policy submitted.') from error
        return view(request, identity, review, metadata, report=report, count=count, consent=consent)

    @app.post(WEB + '/confirm')
    async def confirm(request: Request):
        identity, review, fields = await fields_review(request)
        count = fields.get('accepted_count', [''])[0]
        if count != str(review.payload()['accepted_count']) or fields.get('maintain_present', [''])[0] != 'true':
            raise HTTPException(422, 'Type the exact accepted pair count and explicitly consent to recurring maintenance.')
        return await run_in_threadpool(save, request, identity, review)

    def save(request, identity, review):
        metadata, result, message, code = None, None, None, 200
        try:
            if enabled is not True: raise ReviewUnavailable('Web standing-policy admission is disabled. This attempt was not submitted; inspect any earlier receipt.')
            with client_for(settings) as client:
                metadata = state(client)
                scope = metadata.get('bulk_policy_admission_device_ids')
                if (metadata.get('bulk_policy_admission_enabled') is not True or type(scope) is not list
                        or any(type(device) is not int for device in scope) or len(set(scope)) != len(scope)
                        or not set(review.proposal['manifest']['device_ids']).issubset(scope)):
                    raise ReviewUnavailable('API standing-policy admission/profile scope is unavailable. This attempt was not submitted; inspect any earlier receipt.')
                if (metadata.get('bulk_policy_concurrent_enabled', False) is not review.concurrent
                        or (review.concurrent and concurrent_enabled is not True)):
                    raise ReviewUnavailable('Frozen admission mode changed or concurrent Web consent is disabled. No fallback/submission; inspect original receipts.')
                reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))  # After I/O.
                response = client.post(API + ('confirm-concurrent' if review.concurrent else 'confirm'), headers={'Idempotency-Key': review.operation_id},
                                       json={**review.payload(), 'actor': actor(identity)})
                value = response.json()
                if response.status_code == 200:
                    descriptor = decode_bulk_descriptor(review.proposal['canonical'], review.proposal['digest'])
                    result = validate_policy_receipt(value, descriptor, identity.subject, actual_actor=actor(identity),
                        concurrent=review.concurrent, expected_suspended=review.expected_suspended)
                elif response.status_code in {403, 409, 422, 429}:
                    message, code = 'Standing policy was rejected: scope, roles, expiry, capacity or quiescence changed. No review was rebased; inspect current state.', response.status_code
                else: raise httpx.RequestError('Standing policy outcome unconfirmed')
        except ReviewUnavailable as error: message, code = str(error), 503
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Standing-policy outcome is unknown. Inspect saved receipts or retry only this same frozen review/key; never rekey, split or replay ADD.', 503
        # This is optional metadata only, not another confirmation or a device hint.
        try:
            with client_for(settings) as client: metadata = state(client)
        except (httpx.HTTPError, ValueError, TypeError, KeyError): pass
        return view(request, identity, review, metadata, result=result, message=message, code=code,
                    count=str(review.payload()['accepted_count']), consent=True)

    @app.get(WEB + '/receipts/{operation_id}')
    def receipt_page(request: Request, operation_id: str, page: Annotated[int, Query(ge=1, le=1000)] = 1):
        identity = identity_for(request, settings.development_auth)
        try: _uuid(operation_id)
        except ValueError as error: raise HTTPException(422, 'Use the exact original canonical operation UUID.') from error
        value, metadata, message, code = None, None, None, 200
        try:
            with client_for(settings) as client:
                metadata = state(client)
                value = validate_receipt_page(read(client, 'receipt', {'actor': actor(identity),
                    'operation_id': operation_id, 'page': page}), operation_id, identity.subject, page)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Original policy receipt is unavailable. No success, current policy state or rollback is inferred.', 503
        return render(request, 'bulk-policy-receipt.html', {'identity': identity, 'refresh': metadata,
            'receipt': value, 'operation_id': operation_id, 'message': message, 'active_page': 'imports',
            'auto_request': False, 'frozen_view': True}, code)
