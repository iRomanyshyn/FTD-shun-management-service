"""Separate ordered consent/status/revocation BFF; no ready/legacy fallback."""

from ipaddress import IPv4Address

import httpx
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .bulk_intent import _uuid
from .bulk_ordered_review import (
    OrderedRemovalReviews,
    inspect_ordered,
    validate_ordered_receipt,
    validate_ordered_status,
)
from .import_review import ReviewUnavailable

API = '/api/v2/managed-ordered-removals/'
WEB = '/managed-shuns/v2/ordered-removals/'


def register_ordered_removal_web(app, settings, *, enabled, render, identity_for, operator_for,
                                 client_for, form_for, csrf_for):
    reviews = OrderedRemovalReviews(settings.sensitive_action_max_age_seconds)

    def compatible(state):
        return (type(state) is dict and type(state.get('managed_policy_format')) is int
                and state['managed_policy_format'] == 2 and state.get('runtime_mode') in ('continuous-observation', 'continuous-managed')
                and state.get('ordered_removal_review_available') is True)

    def metadata():
        try:
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                value = response.json()
                return value if response.status_code == 200 and compatible(value) else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    def review_view(request, identity, inspection, review=None, *, state=None, result=None, message=None, code=200):
        return render(request, 'bulk-ordered-review.html', {
            'identity': identity, 'inspection': inspection, 'review': review, 'result': result,
            'message': message, 'refresh': state, 'ordered_removal_local_enabled': enabled,
            'active_page': 'managed', 'auto_request': False, 'frozen_view': True}, code)

    @app.post('/managed-shuns/v2/ordered-removal-review')
    async def device_review(request: Request):
        return await prepare(request, device=True)

    @app.post('/managed-shuns/v2/ordered-fleet-removal-review')
    async def fleet_review(request: Request):
        return await prepare(request, device=False)

    async def prepare(request, *, device):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'target' if device else 'ip', 'reason'}, max_bytes=16384)
        csrf_for(request, fields.get('csrf', [''])[0])
        try:
            device_id, raw_ip = None, fields.get('ip', [''])[0]
            if device:
                raw_device, raw_ip = fields.get('target', [''])[0].split(':')
                device_id = int(raw_device)
                if raw_device != str(device_id) or not 1 <= device_id <= 65535:
                    raise ValueError('Noncanonical device ID')
            ip = IPv4Address(raw_ip)
            if str(ip) != raw_ip:
                raise ValueError('Noncanonical IPv4')
        except ValueError as error:
            raise HTTPException(422, 'Select one exact device/IP or complete fleet IPv4.') from error
        return await run_in_threadpool(prepare_review, request, identity, ip, device_id, fields.get('reason', [''])[0])

    def prepare_review(request, identity, ip, device_id, reason):
        state = metadata()
        if state is None:
            raise HTTPException(503, 'Compatible ordered inspection is unavailable; nothing was submitted.')
        try:
            with client_for(settings) as client:
                response = client.get(f'/api/v2/managed-ordered-removal-scope/{ip}',
                                      params={} if device_id is None else {'device_id': device_id})
            if response.status_code == 409:
                raise HTTPException(409, 'Scope is empty or changed; nothing was submitted.')
            if response.status_code != 200:
                raise httpx.RequestError('Ordered inspection unavailable')
            inspection = inspect_ordered(response.json(), ip, device_id=device_id)
            review = reviews.prepare(identity.subject, request.cookies.get('ftd_shun_csrf', ''), inspection, ip,
                device_id=device_id, ttl_seconds=min(900, settings.sensitive_action_max_age_seconds), reason=reason
                ) if inspection['disposition'] == 'WAITING_ADD' else None
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, 'Ordered inspection is invalid or unavailable; nothing was submitted.') from error
        return review_view(request, identity, inspection, review, state=state)

    @app.post('/managed-shuns/v2/ordered-removal-confirm')
    async def confirm(request: Request):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'review', 'confirm_ip'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        try:
            review = reviews.get(fields.get('review', [''])[0], identity.subject, request.cookies.get('ftd_shun_csrf', ''))
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        if fields.get('confirm_ip', [''])[0] != review.scope['ip']:
            raise HTTPException(422, 'Type the exact IPv4 from this frozen ordered review.')
        return await run_in_threadpool(save_review, request, identity, review)

    def save_review(request, identity, review):
        result, message, code = None, None, 200
        state = metadata() if enabled else None
        try:
            if (enabled is not True or not compatible(state)
                    or state.get('ordered_removal_admission_enabled') is not True
                    or state.get('ordered_removal_promotion_enabled') is not True):
                raise ReviewUnavailable('Ordered Web/API admission is disabled or unavailable. This attempt was not submitted; inspect any earlier outcome.')
            reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))  # After status I/O.
            with client_for(settings) as client:
                response = client.post(API + review.scope['scope'], headers={'Idempotency-Key': review.request_id},
                                       json={**review.payload(), 'actor': identity.__dict__})
            value = response.json()
            if response.status_code == 202:
                result = validate_ordered_receipt(review, value)
            elif response.status_code in {403, 409, 422, 429}:
                detail = value.get('detail') if type(value) is dict else None
                message, code = detail if type(detail) is str else 'Ordered reservation rejected; inspect current state.', response.status_code
            else:
                raise httpx.RequestError('Ordered reservation outcome unknown')
        except ReviewUnavailable as error:
            message, code = str(error), 503
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Ordered reservation outcome is unknown. Retry only this same review/key; never rekey or reduce the scope.', 503
        return review_view(request, identity, review.inspection, review, state=metadata() or state,
                           result=result, message=message, code=code)

    def load_status(key):
        with client_for(settings) as client:
            response = client.get(API + key)
        if response.status_code == 404:
            raise HTTPException(404, 'Original ordered request was not found. After an unknown reply, retry only the original review/key.')
        if response.status_code != 200:
            raise httpx.RequestError('Original ordered status unavailable')
        return validate_ordered_status(key, response.json())

    def status_view(request, identity, key, value, *, message=None, cancellation=None, code=200):
        return render(request, 'bulk-ordered-status.html', {'identity': identity, 'operation_id': key,
            'ordered': value, 'message': message, 'cancellation': cancellation, 'refresh': metadata(),
            'active_page': 'managed', 'auto_request': False}, code)

    def key_for(key):
        try:
            _uuid(key)
        except ValueError as error:
            raise HTTPException(422, 'An exact original canonical request UUID is required.') from error
        return key

    @app.get(WEB + '{operation_id}')
    async def status(request: Request, operation_id: str):
        identity = identity_for(request, settings.development_auth)
        return await run_in_threadpool(read_status, request, identity, key_for(operation_id))

    def read_status(request, identity, key):
        try:
            value = load_status(key)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return status_view(request, identity, key, None, message='Original ordered status is unavailable. No success or rollback is inferred.', code=503)
        return status_view(request, identity, key, value)

    @app.post(WEB + '{operation_id}/cancel')
    async def cancel(request: Request, operation_id: str):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'confirm_ip'}, max_bytes=4096)
        csrf_for(request, fields.get('csrf', [''])[0])
        return await run_in_threadpool(revoke, request, identity, key_for(operation_id), fields.get('confirm_ip', [''])[0])

    def revoke(request, identity, key, confirm_ip):
        result, value, message, code = None, None, None, 200
        try:
            value = load_status(key)
            if value['owner_subject'] != identity.subject and 'Administrator' not in identity.roles:
                raise HTTPException(403, 'Only the owner or Administrator may cancel ordered waiting.')
            if confirm_ip != value['scope']['ip']:
                raise HTTPException(422, 'Type the exact IPv4 to cancel this original waiting request.')
            with client_for(settings) as client:
                response = client.post(API + key + '/cancel', json={'actor': identity.__dict__})
            candidate = response.json()
            if response.status_code in {403, 409, 422, 429}:
                raise HTTPException(response.status_code, 'Waiting revocation rejected. Already admitted work remains governed by ordinary queue controls.')
            if (response.status_code != 200 or type(candidate) is not dict
                    or set(candidate) != {'operation_id', 'state', 'replayed'} or candidate['operation_id'] != key
                    or candidate['state'] not in {'CANCELLED', 'EXPIRED'} or type(candidate['replayed']) is not bool):
                raise ValueError('Revocation receipt unconfirmed')
            result = candidate
            value = None  # Do not render a pre-submission snapshot as current after a checked receipt.
            value = load_status(key)
        except HTTPException:
            if not result:
                raise
            value, message, code = None, 'Waiting revocation confirmed, but current status is unavailable. Retired policy stays stopped.', 503
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = ('Waiting revocation confirmed, but current status is unavailable. Retired policy stays stopped.'
                             if result else 'Waiting revocation outcome is unknown. Inspect or retry only this same original request.'), 503
            value = None
        return status_view(request, identity, key, value, message=message, cancellation=result, code=code)
