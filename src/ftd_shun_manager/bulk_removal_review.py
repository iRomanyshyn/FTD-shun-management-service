"""Immutable, session-bound v2 ready-removal reviews; never legacy authority."""

import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address

from .bulk_intent import _uuid
from .bulk_removals import _FIELDS, canonical_removal, canonical_scope
from .managed_review import ManagedRemovalReviews
from .operation_queue import stamp


@dataclass(frozen=True)
class ReadyRemovalReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    payload_json: str
    digest: str

    @property
    def scope(self):
        return json.loads(self.payload_json)['reviewed']

    @property
    def reason(self):
        return json.loads(self.payload_json)['reason']

    def payload(self):
        value = json.loads(self.payload_json)
        return {'reviewed': value['reviewed'], 'ttl_seconds': value['ttl_seconds'],
                'reason': value['reason'], 'confirmation_digest': self.digest}


class ReadyRemovalReviews(ManagedRemovalReviews):
    def prepare(self, subject, cookie, inspection, ip, *, device_id=None, ttl_seconds=900, reason=''):
        if (type(inspection) is not dict or set(inspection) != _FIELDS | {
                'scope_digest', 'read_only', 'execution_available', 'device_work_admitted'}
                or inspection['read_only'] is not True or inspection['execution_available'] is not False
                or inspection['device_work_admitted'] is not False or type(ip) is not IPv4Address):
            raise ValueError('A complete readonly version-2 removal inspection is required.')
        scope = {field: inspection[field] for field in _FIELDS}
        _, scope_digest = canonical_scope(scope)
        supplied = inspection['scope_digest']
        if (type(supplied) is not str or not supplied.isascii() or not hmac.compare_digest(supplied, scope_digest)
                or scope['ip'] != str(ip) or scope['scope'] != ('device' if device_id is not None else 'fleet')
                or (device_id is not None and (type(device_id) is not int
                    or [row['device_id'] for row in scope['targets']] != [device_id]))):
            raise ValueError('Inspection was substituted or does not match the requested exact mode/target.')
        payload, digest = canonical_removal(scope, ttl_seconds, reason)
        return self._save(ReadyRemovalReview, subject, cookie, payload_json=payload, digest=digest)


def validate_ready_receipt(review, value):
    """Only a strict historical admission receipt, never device verification."""
    scope = review.scope
    retiring = sum(row['maintenance_enabled'] for row in scope['targets'])
    expected = {'operation_id': review.request_id, 'status': 'accepted', 'intent_format': 2,
                'action': 'STOP_AND_REMOVE_READY', 'scope': scope['scope'],
                'target_count': len(scope['targets']), 'retired_targets': retiring,
                'managed_revision': scope['managed_revision'] + bool(retiring),
                'policy_only': False, 'device_work_admitted': True, 'verified_removal': False}
    if (type(value) is not dict or any(type(value.get(key)) is not type(item) or value[key] != item
            for key, item in expected.items()) or type(value.get('replayed')) is not bool):
        raise ValueError('Version-2 ready-removal admission was not confirmed.')
    jobs = value.get('jobs')
    if (type(jobs) is not list or len(jobs) != len(scope['targets'])
            or any(type(row) is not dict or set(row) != {'device_id', 'job_id'} or type(row['device_id']) is not int for row in jobs)
            or [row['device_id'] for row in jobs] != [row['device_id'] for row in scope['targets']]):
        raise ValueError('Admission receipt is missing the exact original job scope.')
    for row in jobs:
        _uuid(row['job_id'])
    if len({row['job_id'] for row in jobs}) != len(jobs) or any(row['job_id'] == review.request_id for row in jobs):
        raise ValueError('Admission job identities overlap or duplicate the request key.')
    expiry = value.get('expires_at')
    if type(expiry) is not str or len(expiry) > 40 or not expiry.endswith('Z') or stamp(datetime.fromisoformat(expiry)) != expiry:
        raise ValueError('Original removal delegation expiry is unavailable.')
    return value
