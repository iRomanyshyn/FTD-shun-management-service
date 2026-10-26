"""Frozen standing-consent review and honest historical receipt projections."""

import json
from dataclasses import dataclass
from ipaddress import IPv4Address

from .bulk_intent import CLASSES, _integer, _uuid, decode_bulk_descriptor
from .bulk_intent import _digest as require_digest
from .bulk_ordered_removals import _time
from .bulk_preparation_view import _text, validate_proposal, validate_report
from .managed_review import ManagedRemovalReviews


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


@dataclass(frozen=True)
class BulkConfirmationReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str  # Cache identity, never the policy operation key.
    expires: float
    expires_at: str
    proposal_json: str
    summary_json: str
    concurrent: bool = False
    expected_suspended: bool = True

    @property
    def proposal(self): return json.loads(self.proposal_json)

    @property
    def summary(self): return json.loads(self.summary_json)

    @property
    def operation_id(self): return self.proposal['operation_id']

    def payload(self):
        value = self.proposal
        return {'canonical': value['canonical'], 'digest': value['digest'],
                'accepted_count': value['manifest']['accepted_count'], 'maintain_present': True,
                **({'expected_suspended': self.expected_suspended} if self.concurrent else {})}


class BulkConfirmationReviews(ManagedRemovalReviews):
    def prepare(self, subject, cookie, report, proposal, *, concurrent=False, expected_suspended=True):
        if type(concurrent) is not bool or type(expected_suspended) is not bool or (not concurrent and not expected_suspended):
            raise ValueError('Exact frozen admission mode and suspension required.')
        validate_report(report, report['plan_id'], subject, report['page'])
        validate_proposal(proposal, report)
        summary = {field: report[field] for field in ('plan_id', 'digest', 'devices', 'created_at', 'expires_at',
            'label', 'reason', 'managed_revision', 'protected_revision', 'classification_counts',
            'source_counts', 'target_count', 'address_count')}
        return self._save(BulkConfirmationReview, subject, cookie,
            proposal_json=json.dumps(proposal, sort_keys=True), summary_json=json.dumps(summary, sort_keys=True),
            concurrent=concurrent, expected_suspended=expected_suspended)


def validate_policy_receipt(value, descriptor, subject, *, actual_actor=None, concurrent=None, expected_suspended=None):
    manifest = descriptor['manifest']
    if concurrent is None: concurrent = type(value) is dict and 'admission_mode' in value
    suspension = value.get('restoration_suspended') if type(value) is dict else None
    if (type(suspension) is not bool or (not concurrent and suspension is not True)
            or (expected_suspended is not None and suspension is not expected_suspended)):
        raise ValueError('Original desired-suspension evidence is inconsistent.')
    expected = {'operation_id': descriptor['operation_id'], 'status': 'policy_saved', 'intent_format': 2,
        'managed_revision': descriptor['managed_revision'] + 1,
        'changed_targets': sum(manifest['classification_counts'][kind] for kind in ('PROPOSE_ADD', 'PROPOSE_ADOPT')),
        'accepted_pairs': manifest['accepted_count'], 'classification_counts': manifest['classification_counts'],
        'policy_only': True, 'device_work_admitted': False, 'restoration_suspended': suspension}
    if concurrent: expected['admission_mode'] = 'fenced'
    if (type(value) is not dict or set(value) != set(expected) | {'replayed', 'confirmation_actor'}
            or any(not _same(value[key], item) for key, item in expected.items()) or type(value['replayed']) is not bool):
        raise ValueError('Standing-policy historical receipt is unconfirmed.')
    actor = value['confirmation_actor']
    if type(actor) is not dict or set(actor) != {'subject', 'display_name', 'roles'} or actor['subject'] != subject:
        raise ValueError('Original confirmation actor is unavailable.')
    _text(actor['subject'], 255)
    _text(actor['display_name'], 255)
    roles = actor['roles']
    if (type(roles) is not list or not 1 <= len(roles) <= 3
            or any(type(role) is not str or role not in {'Viewer', 'Operator', 'Administrator'} for role in roles)
            or len(set(roles)) != len(roles) or not {'Operator', 'Administrator'}.intersection(roles)
            or (actual_actor is not None and not value['replayed'] and not _same(actor, actual_actor))):
        raise ValueError('Historical actual actor/roles are inconsistent.')
    return value


def validate_receipts(value):
    if (type(value) is not dict or set(value) != {'initialized', 'read_only', 'can_execute', 'items', 'intent_format', 'device_work_admitted'}
            or value['initialized'] is not True or value['read_only'] is not True or value['can_execute'] is not False
            or value['device_work_admitted'] is not False or type(value['intent_format']) is not int or value['intent_format'] != 2
            or type(value['items']) is not list or len(value['items']) > 128):
        raise ValueError('Owner historical receipt list is unavailable.')
    seen = set()
    for row in value['items']:
        if type(row) is not dict or set(row) != {'id', 'preparation_id', 'payload_digest', 'pair_count', 'accepted_count', 'requested_at'}:
            raise ValueError('Exact original receipt reference is required.')
        _uuid(row['id'])
        _uuid(row['preparation_id'])
        require_digest(row['payload_digest'])
        _time(row['requested_at'])
        _integer(row['pair_count'], 1, 100000, 'historical pair count')
        _integer(row['accepted_count'], 1, row['pair_count'], 'historical accepted count')
        if row['id'] in seen or row['id'] == row['preparation_id']: raise ValueError('Historical keys alias or duplicate.')
        seen.add(row['id'])
    return value


def validate_receipt_page(value, operation_id, subject, page):
    fields = {'intent_format', 'historical_confirmation', 'read_only', 'can_execute', 'operation_id',
        'preparation_id', 'result', 'manifest', 'page', 'pages', 'targets', 'canonical', 'digest'}
    if (type(value) is not dict or set(value) != fields or type(value['intent_format']) is not int or value['intent_format'] != 2
            or value['historical_confirmation'] is not True or value['read_only'] is not True or value['can_execute'] is not False
            or value['operation_id'] != operation_id):
        raise ValueError('Exact historical receipt page is unavailable.')
    descriptor = decode_bulk_descriptor(value['canonical'], value['digest'])
    if (descriptor['operation_id'] != operation_id or descriptor['preparation_id'] != value['preparation_id']
            or not _same(value['manifest'], descriptor['manifest'])):
        raise ValueError('Original receipt binding is unavailable.')
    manifest = value['manifest']
    # decode_bulk_descriptor already validates the complete typed ManifestSummary.
    pages = (manifest['pair_count'] + 99) // 100
    if (type(value['page']) is not int or value['page'] != page or not 1 <= page <= pages
            or type(value['pages']) is not int or value['pages'] != pages
            or type(value['targets']) is not list or len(value['targets']) != min(100, manifest['pair_count'] - (page - 1) * 100)):
        raise ValueError('Historical whole-scope pagination is incomplete.')
    validate_policy_receipt(value['result'], descriptor, subject)
    previous = (0, -1)
    for target in value['targets']:
        if type(target) is not dict or set(target) != {'request_id', 'device_id', 'ip', 'classification', 'observed_at', 'managed_enabled',
                'previous_intent_id', 'previous_generation', 'previous_authorization_request_id', 'intent_id', 'generation', 'authorization_request_id'}:
            raise ValueError('Original retained member evidence is incomplete.')
        _integer(target['device_id'], 1, 65535, 'original member device')
        ip = IPv4Address(target['ip'])
        pair = target['device_id'], int(ip)
        if (target['request_id'] != operation_id or type(target['ip']) is not str or str(ip) != target['ip']
                or pair <= previous or target['device_id'] not in manifest['device_ids']
                or type(target['classification']) is not str or target['classification'] not in CLASSES
                or type(target['managed_enabled']) is not int or target['managed_enabled'] not in (0, 1)):
            raise ValueError('Original member identity/order is inconsistent.')
        previous = pair
        prior = tuple(target[key] for key in ('previous_intent_id', 'previous_generation', 'previous_authorization_request_id'))
        assigned = tuple(target[key] for key in ('intent_id', 'generation', 'authorization_request_id'))
        if prior[0] is None:
            if prior != (None, None, None) or target['managed_enabled'] != 0: raise ValueError('Missing original authority is not zero.')
        else:
            _uuid(prior[0]); _uuid(prior[2])
            _integer(prior[1], 1, 2**63 - 1, 'original generation')
        if target['classification'] == 'EXCLUDED_PROTECTED':
            if assigned != (None, None, None): raise ValueError('Protected exclusions cannot acquire authority.')
        else:
            _uuid(assigned[0]); _uuid(assigned[2])
            _integer(assigned[1], 1, 2**63 - 1, 'assigned generation')
            if target['classification'] == 'ALREADY_MANAGED':
                if assigned != prior or target['managed_enabled'] != 1: raise ValueError('Original managed authority was replaced.')
            elif assigned[2] != operation_id or assigned[1] != (prior[1] or 0) + 1:
                raise ValueError('Assigned authority does not match original import.')
    return value
