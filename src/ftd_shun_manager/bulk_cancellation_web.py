"""Whole-root frozen revocation and local status; no legacy or device fallback."""

from typing import Annotated

import httpx
from fastapi import HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .bulk_cancellation_view import (
    BulkCancellationReviews,
    validate_result,
    validate_review,
    validate_review_page,
    validate_status,
)
from .bulk_intent import _uuid
from .import_review import ReviewUnavailable

API, WEB = '/api/v2/managed-imports/', '/managed-imports/v2'


def register_bulk_cancellation_web(app, settings, *, render, identity_for, operator_for, client_for, form_for, csrf_for):
    reviews = BulkCancellationReviews(settings.sensitive_action_max_age_seconds)

    def actor(identity):
        return {'subject': identity.subject, 'display_name': identity.display_name, 'roles': list(identity.roles)}

    def key_for(key):
        try: _uuid(key)
        except ValueError as error: raise HTTPException(422, 'Use the exact original import UUID.') from error
        return key

    def metadata():
        try:
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                value = response.json()
                if (response.status_code == 200 and type(value) is dict and type(value.get('managed_policy_format')) is int
                        and value['managed_policy_format'] == 2 and value.get('runtime_mode') == 'continuous-observation'
                        and value.get('bulk_import_cancellation_available') is True): return value
        except (httpx.HTTPError, ValueError, TypeError, KeyError): pass
        return None

    def post(name, identity, **body):
        with client_for(settings) as client:
            response = client.post(API + name, json={'actor': actor(identity), **body})
        if response.status_code in {403, 409, 422, 429}:
            raise HTTPException(response.status_code, 'Original cancellation refused: current permission, scope or review changed. Inspect local status.')
        if response.status_code != 200: raise httpx.RequestError('Original cancellation unavailable')
        return response.json()

    def read_status(identity, key, page=1):
        return validate_status(post('cancellation', identity, operation_id=key, page=page), key, page)

    def review_view(request, identity, review, *, report=None, result=None, message=None, code=200, count='', state=None):
        return render(request, 'bulk-cancellation-review.html', {'identity': identity, 'review': review,
            'report': report, 'result': result, 'message': message, 'typed_count': count, 'refresh': state,
            'active_page': 'imports', 'auto_request': False, 'frozen_view': True}, code)

    @app.post(WEB + '/{operation_id}/cancellation-review')
    async def prepare(request: Request, operation_id: str):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        return await run_in_threadpool(prepare_review, request, identity, key_for(operation_id))

    def prepare_review(request, identity, key):
        state = metadata()
        if state is None: raise HTTPException(503, 'Compatible cancellation interface unavailable; no revocation submitted.')
        try:
            value = validate_review(post('cancellation-review', identity, operation_id=key), key)
            if value['can_cancel'] is False: return RedirectResponse(WEB + '/cancellations/' + key, status_code=303)
            body = {k: value[k] for k in ('operation_id', 'reviewed_at', 'review_digest', 'accepted_count')}
            report = validate_review_page(post('cancellation-targets', identity, **body, page=1), value, 1)
            review = reviews.prepare(identity.subject, request.cookies.get('ftd_shun_csrf', ''), value)
        except ReviewUnavailable as error: raise HTTPException(409, str(error)) from error
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, 'Whole cancellation review unavailable; no scope was rebased or submitted.') from error
        return review_view(request, identity, review, report=report, state=state)

    async def frozen_fields(request, *, paging=False):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'review', 'accepted_count'} | ({'page'} if paging else set()), max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        try: review = reviews.get(fields.get('review', [''])[0], identity.subject, request.cookies.get('ftd_shun_csrf', ''))
        except ReviewUnavailable as error: raise HTTPException(409, str(error)) from error
        count = fields.get('accepted_count', [''])[0]
        if count and (len(count) > 6 or not count.isascii() or not count.isdecimal()):
            raise HTTPException(422, 'Use the exact accepted-pair count.')
        return identity, review, fields, count

    @app.post(WEB + '/cancellation-review/page')
    async def page_review(request: Request):
        identity, review, fields, count = await frozen_fields(request, paging=True)
        raw = fields.get('page', [''])[0]
        try:
            page = int(raw)
            if str(page) != raw or not 1 <= page <= 1000: raise ValueError('Noncanonical page')
        except ValueError as error: raise HTTPException(422, 'Select an original cancellation-review page.') from error
        return await run_in_threadpool(page_view, request, identity, review, page, count)

    def page_view(request, identity, review, page, count):
        try:
            report = validate_review_page(post('cancellation-targets', identity, **review.payload(), page=page), review.summary, page)
            reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, ReviewUnavailable) as error:
            raise HTTPException(503, 'Original frozen page unavailable; no revocation was submitted.') from error
        return review_view(request, identity, review, report=report, count=count, state=metadata())

    @app.post(WEB + '/cancel')
    async def cancel(request: Request):
        identity, review, _, count = await frozen_fields(request)
        if count != str(review.summary['accepted_count']):
            raise HTTPException(422, 'Type the exact accepted-pair count from this frozen cancellation review.')
        return await run_in_threadpool(revoke, request, identity, review, count)

    def revoke(request, identity, review, count):
        state, result, message, code = metadata(), None, None, 200
        try:
            if state is None: raise ReviewUnavailable('Compatible cancellation interface unavailable; this attempt was not submitted. Inspect earlier outcomes.')
            reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))  # After I/O.
            result = validate_result(post('cancel', identity, **review.payload()), review.operation_id, review=review.summary)
        except ReviewUnavailable as error: message, code = str(error), 503
        except HTTPException as error: message, code = error.detail, error.status_code
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Cancellation outcome is unknown. Inspect its original local status or retry only this same review/actual actor; never rekey or submit REMOVE.', 503
        return review_view(request, identity, review, result=result, message=message, code=code, count=count, state=metadata() or state)

    @app.get(WEB + '/cancellations/{operation_id}')
    def status_page(request: Request, operation_id: str, page: Annotated[int, Query(ge=1, le=1000)] = 1):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        key, value, message, code = key_for(operation_id), None, None, 200
        try: value = read_status(identity, key, page)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Retained cancellation status unavailable. No success, empty scope, rollback or settlement is inferred.', 503
        return render(request, 'bulk-cancellation-status.html', {'identity': identity, 'operation_id': key,
            'cancellation': value, 'message': message, 'refresh': metadata(), 'active_page': 'imports', 'auto_request': False}, code)
