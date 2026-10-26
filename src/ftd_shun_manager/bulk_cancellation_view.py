"""Frozen whole-import revocation and strict historical/current projections."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .bulk_confirmation_view import _same
from .bulk_intent import _digest, _integer, _uuid
from .bulk_ordered_removals import _time
from .managed_review import ManagedRemovalReviews

STATES = frozenset({'STOPPED_UNSENT', 'STOPPED_FAILED', 'STOPPED_UNVERIFIED', 'RETAINED_ADOPTED',
    'RETAINED_EXISTING', 'RETAINED_APPLIED', 'ALREADY_STOPPED', 'SUPERSEDED', 'WAITING_OUTCOME'})
AUTHORITY = {'device_id', 'ip', 'classification', 'intent_id', 'generation', 'authorization_request_id'}


def counts_for(counts, count):
    if type(counts) is not dict or not counts or not set(counts).issubset(STATES):
        raise ValueError('Complete cancellation counts required.')
    for value in counts.values(): _integer(value, 1, 100000, 'disposition count')
    if sum(counts.values()) != count: raise ValueError('Whole accepted cancellation scope required.')


def validate_review(value, key):
    _uuid(key)
    if type(value) is not dict or value.get('operation_id') != key: raise ValueError('Original cancellation key required.')
    if set(value) == {'operation_id', 'can_cancel', 'already_requested'}:
        if value['can_cancel'] is not False or value['already_requested'] is not True: raise ValueError('Invalid closed review.')
        return value
    if (set(value) != {'operation_id', 'reviewed_at', 'review_digest', 'expires_at', 'accepted_count', 'counts',
            'scope_digest', 'can_cancel', 'device_work_admitted'} or value['can_cancel'] is not True
            or value['device_work_admitted'] is not False):
        raise ValueError('Exact non-executable cancellation review required.')
    _digest(value['review_digest']); _digest(value['scope_digest'])
    _integer(value['accepted_count'], 1, 100000, 'accepted count')
    counts_for(value['counts'], value['accepted_count'])
    if datetime.fromisoformat(_time(value['expires_at'])) - datetime.fromisoformat(_time(value['reviewed_at'])) != timedelta(minutes=5):
        raise ValueError('Original five-minute cancellation deadline required.')
    return value


def validate_result(value, key, *, review=None, historical=False):
    if (type(value) is not dict or set(value) != {'operation_id', 'intent_format', 'status', 'accepted_count', 'counts',
            'changed_targets', 'managed_revision', 'device_work_admitted', 'device_removal_requested', 'replayed'}
            or value['operation_id'] != key or type(value['intent_format']) is not int or value['intent_format'] != 2
            or value['status'] != 'cancelled_uncompleted' or value['device_work_admitted'] is not False
            or value['device_removal_requested'] is not False or type(value['replayed']) is not bool
            or (historical and value['replayed'])):
        raise ValueError('Cancellation receipt is unconfirmed.')
    _integer(value['accepted_count'], 1, 100000, 'accepted count')
    counts_for(value['counts'], value['accepted_count'])
    _integer(value['managed_revision'], 0, 2**63-1, 'historical revision')
    _integer(value['changed_targets'], 0, value['accepted_count'], 'stopped targets')
    if value['changed_targets'] != sum(n for state, n in value['counts'].items() if state.startswith('STOPPED_')):
        raise ValueError('Cancellation receipt does not match stopped scope.')
    if review is not None and (value['accepted_count'] != review['accepted_count'] or not _same(value['counts'], review['counts'])):
        raise ValueError('Cancellation receipt does not match frozen review.')
    return value


def members(value, key, page, count, *, review=False, captured=False):
    if type(value) is not list or len(value) != min(100, count-(page-1)*100): raise ValueError('Complete bounded member page required.')
    previous, initial_counts, current_counts, attention = (0, -1), Counter(), Counter(), 0
    for row in value:
        base = AUTHORITY | {'current_revision', 'state'}
        extras = {'job_id', 'attempt_digest'}
        if not review: base |= {'import_id'}
        if captured: base |= extras | {'initial_state', 'attention'}
        allowed = base | (extras if review else {'outcome', 'settled_at'} if captured else set())
        if type(row) is not dict or not base.issubset(row) or not set(row).issubset(allowed): raise ValueError('Original cancellation member required.')
        _integer(row['device_id'], 1, 65535, 'device')
        if type(row['ip']) is not str or str(IPv4Address(row['ip'])) != row['ip']: raise ValueError('Exact IPv4 required.')
        pair = row['device_id'], int(IPv4Address(row['ip']))
        if pair <= previous or (not review and row['import_id'] != key): raise ValueError('Original member order/key required.')
        previous = pair
        _uuid(row['intent_id']); _uuid(row['authorization_request_id'])
        _integer(row['generation'], 1, 2**63-1, 'original generation')
        _integer(row['current_revision'], 0, 2**63-1, 'reviewed revision')
        if type(row['classification']) is not str or row['classification'] not in {'PROPOSE_ADD', 'PROPOSE_ADOPT', 'ALREADY_MANAGED'}:
            raise ValueError('Only original accepted classes may be cancelled.')
        for field in ('state', 'initial_state') if captured else ('state',):
            if type(row[field]) is not str or row[field] not in STATES: raise ValueError('Unknown cancellation disposition.')
        initial = row['initial_state'] if captured else row['state']
        initial_counts[initial] += 1; current_counts[row['state']] += 1
        job, digest = row.get('job_id'), row.get('attempt_digest')
        # Completed owned history has a digest without a pending captured job.
        if job is not None:
            _uuid(job)
            if digest is None: raise ValueError('Captured job history binding is incomplete.')
        if digest is not None: _digest(digest)
        if initial == 'WAITING_OUTCOME' and (job is None or not captured and not review): raise ValueError('Original RUNNING binding required.')
        if captured:
            if type(row['attention']) not in (int, bool) or row['attention'] not in (0, 1): raise ValueError('Exact attention flag required.')
            attention += int(row['attention'])
            settled = 'outcome' in row or 'settled_at' in row
            if settled:
                if (not {'outcome', 'settled_at'}.issubset(row) or initial != 'WAITING_OUTCOME' or row['state'] == 'WAITING_OUTCOME'
                        or row['outcome'] not in {'VERIFIED', 'NOOP', 'FAILED', 'UNVERIFIED', 'QUEUED', 'CANCELLED'}):
                    raise ValueError('Exact original settlement required.')
                _time(row['settled_at'])
                if bool(row['attention']) != (row['outcome'] in {'FAILED', 'UNVERIFIED'}): raise ValueError('Settlement attention mismatch.')
            elif row['state'] != initial or bool(row['attention']) != (initial in {'STOPPED_FAILED', 'STOPPED_UNVERIFIED'}):
                raise ValueError('Missing settlement cannot imply a changed result.')
    return initial_counts, current_counts, attention


def pagination(value, count, page):
    pages = (count+99)//100
    if (type(value['page']) is not int or value['page'] != page or not 1 <= page <= pages
            or type(value['pages']) is not int or value['pages'] != pages): raise ValueError('Exact original page required.')


def validate_review_page(value, original, page):
    if type(value) is not dict or set(value) != {'review', 'page', 'pages', 'targets'} or not _same(value['review'], original):
        raise ValueError('Frozen cancellation review changed.')
    validate_review(original, original['operation_id'])
    if original['can_cancel'] is not True: raise ValueError('Closed review is not pageable consent.')
    pagination(value, original['accepted_count'], page)
    counts, _, _ = members(value['targets'], original['operation_id'], page, original['accepted_count'], review=True)
    if any(n > original['counts'].get(state, 0) for state, n in counts.items()): raise ValueError('Member dispositions exceed frozen counts.')
    return value


def validate_status(value, key, page):
    if type(value) is not dict or value.get('operation_id') != key or value.get('read_only') is not True or value.get('can_execute') is not False:
        raise ValueError('Read-only original cancellation status required.')
    if value.get('requested') is False:
        if set(value) != {'operation_id', 'requested', 'read_only', 'can_execute'}: raise ValueError('Invalid absent decision.')
        return value
    base = {'operation_id', 'requested', 'read_only', 'can_execute', 'historical_cancellation', 'settled', 'page', 'pages', 'result', 'targets'}
    # The exact continuous/device-fence profile always includes captured settlement.
    # Missing current counts/attention must never downgrade to a legacy projection.
    captured = True
    if (set(value) != base | {'current_counts', 'attention_count'} or value.get('requested') is not True
            or value.get('historical_cancellation') is not True or type(value.get('settled')) is not bool): raise ValueError('Complete original status required.')
    result = validate_result(value['result'], key, historical=True)
    count = result['accepted_count']
    pagination(value, count, page)
    initial, current, attention = members(value['targets'], key, page, count, captured=captured)
    current_counts = value['current_counts'] if captured else result['counts']
    counts_for(current_counts, count)
    if value['settled'] != (current_counts.get('WAITING_OUTCOME', 0) == 0): raise ValueError('Waiting is not settled.')
    if any(n > result['counts'].get(state, 0) for state, n in initial.items()) or any(n > current_counts.get(state, 0) for state, n in current.items()):
        raise ValueError('Current or historical member counts inconsistent.')
    if captured:
        _integer(value['attention_count'], 0, count, 'attention count')
        minimum = sum(current_counts.get(s, 0) for s in ('STOPPED_FAILED', 'STOPPED_UNVERIFIED'))
        if not minimum <= value['attention_count'] <= minimum + current_counts.get('SUPERSEDED', 0) + current_counts.get('ALREADY_STOPPED', 0) or attention > value['attention_count']:
            raise ValueError('Attention summary inconsistent.')
    return value


@dataclass(frozen=True)
class BulkCancellationReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str
    expires: float
    expires_at: str
    summary_json: str

    @property
    def summary(self): return json.loads(self.summary_json)

    @property
    def operation_id(self): return self.summary['operation_id']

    def payload(self): return {k: self.summary[k] for k in ('operation_id', 'reviewed_at', 'review_digest', 'accepted_count')}


class BulkCancellationReviews(ManagedRemovalReviews):
    def __init__(self, seconds=300): super().__init__(min(300, seconds))

    def prepare(self, subject, cookie, value):
        validate_review(value, value['operation_id'])
        if value['can_cancel'] is not True: raise ValueError('Cancellation already requested; inspect original status.')
        return self._save(BulkCancellationReview, subject, cookie, summary_json=json.dumps(value, sort_keys=True))
