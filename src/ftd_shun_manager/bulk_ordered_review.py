"""Strict frozen ordered consent and read-only outcome projections; no authority."""

import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .bulk_intent import _integer, _uuid
from .bulk_ordered_removals import _DOMAIN, _digest, _time
from .bulk_ordered_waits import canonical_ordered_removal, captured
from .bulk_removal_review import ReadyRemovalReview
from .bulk_removals import canonical_scope
from .managed_review import ManagedRemovalReviews

BLOCKERS = {'DEVICE_DISABLED', 'DEVICE_OUTSIDE_EXECUTOR_SCOPE', 'DEVICE_FENCE_ATTENTION',
    'DEVICE_CLOCK_REVERSED', 'DEVICE_FENCE_EXPIRED', 'DEVICE_OUTCOME_UNKNOWN',
    'PAIR_ADD_ATTENTION', 'PENDING_REMOVE', 'ADD_NOT_RUNNING', 'ADD_BINDING_UNAVAILABLE'}
JOB_STATES = {'QUEUED', 'RUNNING', 'VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'CANCELLED', 'EXPIRED', 'RECONCILED_ABSENT'}


def _equal(left, right):
    return type(left) is type(right) and left == right


def inspect_ordered(value, ip, *, device_id=None):
    fields = {'intent_format', 'mode', 'inspected_at', 'scope', 'scope_digest', 'targets',
              'global_blockers', 'blocked_target_count', 'waiting_target_count', 'disposition',
              'read_only', 'execution_available', 'device_work_admitted', 'preflight_digest'}
    if (type(value) is not dict or set(value) != fields or type(ip) is not IPv4Address
            or not _equal(value['intent_format'], 2) or value['mode'] != 'ordered-removal-preflight'
            or value['read_only'] is not True or value['execution_available'] is not False
            or value['device_work_admitted'] is not False):
        raise ValueError('Complete readonly ordered inspection is required.')
    _time(value['inspected_at'])
    scope = value['scope']
    _, digest = canonical_scope(scope)
    if (value['scope_digest'] != digest or scope['ip'] != str(ip)
            or scope['scope'] != ('device' if device_id is not None else 'fleet')
            or (device_id is not None and (type(device_id) is not int
                or [row['device_id'] for row in scope['targets']] != [device_id]))):
        raise ValueError('Ordered inspection scope was substituted.')
    rows = value['targets']
    if (type(rows) is not list or len(rows) != len(scope['targets'])
            or any(type(row) is not dict or set(row) != {'device_id', 'disposition', 'blockers', 'predecessor'} for row in rows)):
        raise ValueError('Complete ordered target inspection is required.')
    for row, target in zip(rows, scope['targets'], strict=True):
        blockers = row['blockers']
        if (not _equal(row['device_id'], target['device_id']) or type(blockers) is not list
                or any(type(code) is not str or code not in BLOCKERS for code in blockers)
                or len(set(blockers)) != len(blockers)
                or (blockers and row['predecessor'] is not None)
                or (not target['device_enabled'] and 'DEVICE_DISABLED' not in blockers)):
            raise ValueError('Invalid ordered target disposition/evidence.')
        expected = 'BLOCKED' if blockers else 'WAITING_ADD' if row['predecessor'] is not None else 'READY'
        if row['disposition'] != expected:
            raise ValueError('Inconsistent ordered target disposition.')
    predecessors = captured(value)
    if predecessors:
        canonical_ordered_removal(scope, predecessors)
        if any(row['evidence']['started_at'] > value['inspected_at']
               or min(row['evidence']['expires_at'], row['evidence']['lease_until']) <= value['inspected_at']
               for row in predecessors):
            raise ValueError('Predecessor was not live at inspection.')
    blocked = sum(row['disposition'] == 'BLOCKED' for row in rows)
    waiting = len(predecessors)
    if (type(value['global_blockers']) is not list or value['global_blockers'] not in ([], ['MUTATIONS_PAUSED'])
            or not _equal(value['blocked_target_count'], blocked) or not _equal(value['waiting_target_count'], waiting)
            or value['disposition'] != ('BLOCKED' if blocked or value['global_blockers'] else 'WAITING_ADD' if waiting else 'READY')):
        raise ValueError('Inconsistent whole-scope ordered inspection.')
    supplied = value['preflight_digest']
    unsigned = {key: item for key, item in value.items() if key != 'preflight_digest'}
    if type(supplied) is not str or not supplied.isascii() or not hmac.compare_digest(supplied, _digest(unsigned, _DOMAIN)):
        raise ValueError('Ordered inspection digest does not match.')
    return json.loads(json.dumps(value))


@dataclass(frozen=True)
class OrderedRemovalReview(ReadyRemovalReview):
    inspection_json: str

    @property
    def inspection(self):
        return json.loads(self.inspection_json)

    def payload(self):
        return {**super().payload(), 'predecessors': json.loads(self.payload_json)['predecessors']}


class OrderedRemovalReviews(ManagedRemovalReviews):
    def prepare(self, subject, cookie, inspection, ip, *, device_id=None, ttl_seconds=900, reason=''):
        value = inspect_ordered(inspection, ip, device_id=device_id)
        if value['disposition'] != 'WAITING_ADD':
            raise ValueError('Only explicit WAITING_ADD inspection can prepare ordered consent.')
        payload, digest = canonical_ordered_removal(value['scope'], captured(value), ttl_seconds, reason)
        return self._save(OrderedRemovalReview, subject, cookie, payload_json=payload, digest=digest,
                          inspection_json=json.dumps(value, sort_keys=True, separators=(',', ':')))


def validate_ordered_receipt(review, value):
    scope = review.scope
    retiring = sum(row['maintenance_enabled'] for row in scope['targets'])
    expected = {'operation_id': review.request_id, 'status': 'accepted', 'intent_format': 2,
        'action': 'STOP_AND_REMOVE_ORDERED', 'scope': scope['scope'], 'state': 'WAITING_ADD',
        'target_count': len(scope['targets']), 'predecessor_count': len(review.payload()['predecessors']),
        'retired_targets': retiring, 'managed_revision': scope['managed_revision'] + bool(retiring),
        'cleanup_reserved': True, 'policy_only': False, 'device_work_admitted': False, 'verified_removal': False}
    if (type(value) is not dict or set(value) != set(expected) | {'replayed', 'requested_at', 'expires_at'}
            or any(not _equal(value[key], item) for key, item in expected.items()) or type(value['replayed']) is not bool):
        raise ValueError('Original ordered reservation receipt is unconfirmed.')
    requested = datetime.fromisoformat(_time(value['requested_at']))
    expires = datetime.fromisoformat(_time(value['expires_at']))
    if (expires - requested != timedelta(seconds=review.payload()['ttl_seconds'])
            or value['requested_at'] < review.inspection['inspected_at']):
        raise ValueError('Original ordered reservation deadline is unconfirmed.')
    return value


def validate_ordered_status(key, value):
    _uuid(key)
    fields = {'operation_id', 'intent_format', 'action', 'owner_subject', 'predecessor_count', 'scope',
        'requested_at', 'state', 'expires_at', 'predecessors', 'cleanup_jobs', 'verified_removal',
        'cleanup_reserved', 'read_only', 'device_work_admitted', 'attention', 'decision'}
    if (type(value) is not dict or set(value) != fields or value['operation_id'] != key
            or not _equal(value['intent_format'], 2) or value['action'] != 'STOP_AND_REMOVE_ORDERED'
            or value['read_only'] is not True or type(value['owner_subject']) is not str
            or not 1 <= len(value['owner_subject']) <= 255
            or any(ord(char) < 32 for char in value['owner_subject'])):
        raise ValueError('Complete original ordered status is unavailable.')
    canonical_scope(value['scope'])
    devices = [row['device_id'] for row in value['scope']['targets']]
    lifetime = datetime.fromisoformat(_time(value['expires_at'])) - datetime.fromisoformat(_time(value['requested_at']))
    if not timedelta(seconds=1) <= lifetime <= timedelta(seconds=900):
        raise ValueError('Original ordered lifetime is unavailable.')
    _integer(value['predecessor_count'], 1, len(devices), 'predecessor count')
    rows = value['predecessors']
    if type(rows) is not list or len(rows) != value['predecessor_count']:
        raise ValueError('Complete original predecessor scope is unavailable.')
    previous, identities = 0, {key}
    for row in rows:
        if type(row) is not dict or set(row) != {'device_id', 'job_id', 'state', 'missing_evidence'}:
            raise ValueError('Original predecessor outcome is unavailable.')
        _integer(row['device_id'], previous + 1, 65535, 'predecessor device')
        previous = row['device_id']
        _uuid(row['job_id'])
        if (previous not in devices or not next(target['maintenance_enabled'] for target in value['scope']['targets'] if target['device_id'] == previous)
                or row['job_id'] in identities or row['missing_evidence'] is not False
                or type(row['state']) is not str or row['state'] not in JOB_STATES):
            raise ValueError('Missing or inconsistent original ADD evidence.')
        identities.add(row['job_id'])
    phase, decision, jobs = value['state'], value['decision'], value['cleanup_jobs']
    if type(phase) is not str or phase not in {'WAITING_ADD', 'ADMITTED', 'ATTENTION', 'CANCELLED', 'EXPIRED'} or type(jobs) is not list:
        raise ValueError('Ordered phase/outcomes are unavailable.')
    admitted, attention = phase == 'ADMITTED', decision is not None and phase != 'ADMITTED'
    if admitted:
        if (type(decision) is not dict or set(decision) != {'jobs', 'requested_at', 'expires_at'}
                or decision['requested_at'] != value['requested_at'] or decision['expires_at'] != value['expires_at']
                or len(jobs) != len(devices)):
            raise ValueError('Complete ordered REMOVE delegation is unavailable.')
        references = []
        for device, job in zip(devices, jobs, strict=True):
            if (type(job) is not dict or set(job) != {'device_id', 'job_id', 'state'}
                    or not _equal(job['device_id'], device) or type(job['state']) is not str or job['state'] not in JOB_STATES):
                raise ValueError('Original REMOVE outcome is unavailable.')
            _uuid(job['job_id'])
            if job['job_id'] in identities:
                raise ValueError('Repeated/aliased original job identity.')
            identities.add(job['job_id'])
            references.append({'device_id': device, 'job_id': job['job_id']})
        if (type(decision['jobs']) is not list or any(type(row) is not dict or set(row) != {'device_id', 'job_id'}
                or type(row['device_id']) is not int for row in decision['jobs']) or decision['jobs'] != references):
            raise ValueError('REMOVE outcomes do not match original delegation.')
    elif jobs or (phase in {'WAITING_ADD'} and decision is not None) or (phase == 'ATTENTION' and decision is None):
        raise ValueError('A waiting/attention receipt cannot imply device work.')
    if attention and (type(decision) is not dict or set(decision) != {'reason'} or decision['reason'] not in {
            'EVIDENCE_UNAVAILABLE', 'ADD_FAILED_OR_UNKNOWN', 'FENCE_UNSAFE', 'SCOPE_CHANGED', 'ADMISSION_CONFLICT'}):
        raise ValueError('Retained attention evidence is unavailable.')
    expected = {'device_work_admitted': admitted, 'attention': attention,
        'cleanup_reserved': phase in {'WAITING_ADD', 'ATTENTION'},
        'verified_removal': admitted and bool(jobs) and all(row['state'] == 'VERIFIED' for row in jobs)}
    if any(not _equal(value[field], item) for field, item in expected.items()):
        raise ValueError('Ordered admission/verification flags are inconsistent.')
    return value
