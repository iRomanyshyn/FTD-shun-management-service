"""Explicit v2 review/confirm routes, independent of legacy cleanup consent."""

from ipaddress import IPv4Address

import httpx
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .bulk_removal_review import ReadyRemovalReviews, validate_ready_receipt
from .import_review import ReviewUnavailable


def register_ready_removal_web(app, settings, *, enabled, render, identity_for, operator_for,
                               client_for, form_for, csrf_for):
    reviews = ReadyRemovalReviews(settings.sensitive_action_max_age_seconds)

    def compatible(state):
        return (type(state) is dict and type(state.get('managed_policy_format')) is int
                and state['managed_policy_format'] == 2 and state.get('runtime_mode') == 'continuous-observation'
                and state.get('ready_removal_review_available') is True)

    def view(request, identity, review, state=None, *, result=None, message=None, code=200, confirm_ip=''):
        return render(request, 'bulk-removal-review.html', {
            'identity': identity, 'review': review, 'refresh': state, 'result': result, 'message': message,
            'confirm_ip': confirm_ip, 'ready_removal_local_enabled': enabled,
            'active_page': 'managed', 'auto_request': False, 'frozen_view': True}, code)

    @app.post('/managed-shuns/v2/removal-review')
    async def device_review(request: Request):
        return await prepare(request, device=True)

    @app.post('/managed-shuns/v2/fleet-removal-review')
    async def fleet_review(request: Request):
        return await prepare(request, device=False)

    async def prepare(request, *, device):
        identity = identity_for(request, settings.development_auth)
        operator_for(identity)
        fields = await form_for(request, allowed={'csrf', 'target' if device else 'ip', 'reason'}, max_bytes=16384)
        csrf_for(request, fields.get('csrf', [''])[0])
        try:
            device_id = None
            raw_ip = fields.get('ip', [''])[0]
            if device:
                raw_device, raw_ip = fields.get('target', [''])[0].split(':')
                device_id = int(raw_device)
                if raw_device != str(device_id) or not 1 <= device_id <= 65535:
                    raise ValueError('Non-canonical device ID')
            ip = IPv4Address(raw_ip)
            if str(ip) != raw_ip:
                raise ValueError('Non-canonical IP')
        except ValueError as error:
            raise HTTPException(422, 'Select one exact device/IP or one exact fleet IPv4.') from error
        return await run_in_threadpool(prepare_review, request, identity, ip, device_id, fields.get('reason', [''])[0])

    def prepare_review(request, identity, ip, device_id, reason):
        try:
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                state = response.json()
                if response.status_code != 200 or not compatible(state):
                    raise httpx.RequestError('Compatible v2 status is unavailable')
                response = client.get(f'/api/v2/managed-removal-scope/{ip}',
                                      params={} if device_id is None else {'device_id': device_id})
                if response.status_code == 409:
                    raise ReviewUnavailable('Removal scope is empty or changed; inspect current state before reviewing.')
                if response.status_code != 200:
                    raise httpx.RequestError('Version-2 scope unavailable; no legacy fallback')
            review = reviews.prepare(identity.subject, request.cookies.get('ftd_shun_csrf', ''), response.json(), ip,
                device_id=device_id, ttl_seconds=min(900, settings.sensitive_action_max_age_seconds), reason=reason)
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, 'Invalid or substituted v2 review data; no change was submitted.') from error
        except httpx.HTTPError as error:
            raise HTTPException(503, 'Version-2 review unavailable; no change was submitted.') from error
        return view(request, identity, review, state)

    @app.post('/managed-shuns/v2/removal-confirm')
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
            raise HTTPException(422, 'Type the exact IPv4 from this frozen v2 review.')
        return await run_in_threadpool(save_review, request, identity, review)

    def save_review(request, identity, review):
        result, state, message, code = None, None, None, 200
        try:
            if not enabled:
                raise ReviewUnavailable('Web v2 removal admission is disabled. This attempt was not submitted; inspect any earlier outcome.')
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                state = response.json()
                if response.status_code != 200 or not compatible(state) or state.get('ready_removal_admission_enabled') is not True:
                    raise ReviewUnavailable('Compatible API v2 removal admission is unavailable. This attempt was not submitted; inspect any earlier outcome.')
                reviews.get(review.token, identity.subject, request.cookies.get('ftd_shun_csrf', ''))
                response = client.post('/api/v2/managed-removals/' + review.scope['scope'],
                    headers={'Idempotency-Key': review.request_id}, json={**review.payload(), 'actor': identity.__dict__})
                value = response.json()
                if response.status_code == 202:
                    result = validate_ready_receipt(review, value)
                elif response.status_code in {403, 409, 422, 429}:
                    detail = value.get('detail') if type(value) is dict else None
                    message, code = detail if type(detail) is str else 'Ready removal was rejected; inspect current state.', response.status_code
                else:
                    raise httpx.RequestError('Version-2 admission outcome unconfirmed')
        except ReviewUnavailable as error:
            message, code = str(error), 503
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            message, code = 'Removal admission outcome is unknown. Retry only this same review/key; do not rekey or shrink the scope.', 503
        # A later optional status failure never invalidates a checked receipt.
        try:
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                candidate = response.json()
                if response.status_code == 200 and compatible(candidate):
                    state = candidate
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        return view(request, identity, review, state if compatible(state) else None, result=result, message=message,
                    code=code, confirm_ip=review.scope['ip'])
