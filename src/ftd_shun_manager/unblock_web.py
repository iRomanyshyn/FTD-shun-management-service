"""Choose an unblock review before consent; never change an existing review's mode."""

from ipaddress import IPv4Address

import httpx
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .bulk_ordered_review import inspect_ordered


def register_unblock_web(app, settings, *, identity_for, operator_for, client_for,
                         form_for, csrf_for, ready_review, ordered_review):
    @app.post('/ip-actions/unblock')
    async def device(request: Request):
        return await prepare(request, device=True)

    @app.post('/ip-actions/unblock-everywhere')
    async def fleet(request: Request):
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
                    raise ValueError('Noncanonical device')
            ip = IPv4Address(raw_ip)
            if str(ip) != raw_ip:
                raise ValueError('Noncanonical address')
        except ValueError as error:
            raise HTTPException(422, 'Select one exact device/IP or complete fleet IPv4.') from error
        return await run_in_threadpool(inspect, request, identity, ip, device_id, fields.get('reason', [''])[0])

    def inspect(request, identity, ip, device_id, reason):
        try:
            with client_for(settings) as client:
                response = client.get('/api/v1/status')
                state = response.json()
                if (response.status_code != 200 or type(state) is not dict
                        or type(state.get('managed_policy_format')) is not int
                        or state['managed_policy_format'] != 2
                        or state.get('runtime_mode') not in ('continuous-observation', 'continuous-managed')
                        or state.get('ready_removal_review_available') is not True):
                    raise httpx.RequestError('Compatible unblock inspection unavailable')
                ordered = state.get('ordered_removal_review_available') is True
                path = 'managed-ordered-removal-scope' if ordered else 'managed-removal-scope'
                response = client.get(f'/api/v2/{path}/{ip}',
                                      params={} if device_id is None else {'device_id': device_id})
                if response.status_code == 409:
                    raise HTTPException(409, 'The device scope is empty or changed. Open the IP page again; nothing was submitted.')
                if response.status_code != 200:
                    raise httpx.RequestError('Unblock inspection unavailable')
                inspection = response.json()
            if ordered:
                inspection = inspect_ordered(inspection, ip, device_id=device_id)
                if inspection['disposition'] != 'READY':
                    return ordered_review(request, identity, ip, device_id, reason, state, inspection)
                # The same complete, validated preflight selects the ready contract
                # before any token exists. No ordered consent or request is converted.
                inspection = {**inspection['scope'], 'scope_digest': inspection['scope_digest'],
                              'read_only': True, 'execution_available': False, 'device_work_admitted': False}
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, 'Unable to check whether unblocking can proceed. Nothing was submitted; try the IP page again.') from error
        return ready_review(request, identity, ip, device_id, reason, state, inspection)
