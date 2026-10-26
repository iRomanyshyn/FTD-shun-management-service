"""Strict non-authoritative v2 draft/proposal views for the authenticated BFF."""

import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from uuid import UUID, uuid5

from .bulk_intent import CLASSES, _integer, _uuid, decode_bulk_descriptor
from .bulk_intent import _digest as require_digest
from .bulk_ordered_removals import _time

FLAGS = {'intent_format': 2, 'can_execute': False, 'policy_saved': False, 'device_work_admitted': False}
STATUSES = {'Ready', 'Duplicate', 'Invalid', 'Unsupported', 'Ambiguous'}
SUMMARY = {'plan_id', 'created_at', 'expires_at', 'label', 'target_count', 'address_count',
           'classification_counts', 'state', 'confirmed_operation_id', 'digest', 'can_execute'}


def operation_key(plan_id):
    _uuid(plan_id)
    return str(uuid5(UUID(plan_id), 'ftd-shun-manager:bulk-policy-proposal:v2'))


def _text(value, maximum, *, multiline=False):
    if (type(value) is not str or len(value) > maximum
            or any((ord(char) < 32 and not (multiline and char in '\t\n'))
                   or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ValueError('Invalid bounded plain metadata.')


def _flags(value):
    if type(value) is not dict or any(type(value.get(key)) is not type(item) or value[key] != item for key, item in FLAGS.items()):
        raise ValueError('Non-authoritative version-2 flags are unavailable.')


def _summary(value):
    _uuid(value['plan_id'])
    require_digest(value['digest'])
    _text(value['label'], 100, multiline=True)
    _integer(value['address_count'], 0, 10000, 'address count')
    _integer(value['target_count'], 0, 100000, 'pair count')
    counts = value['classification_counts']
    if type(counts) is not dict or set(counts) != set(CLASSES):
        raise ValueError('Complete classified totals are required.')
    for count in counts.values(): _integer(count, 0, 100000, 'classification count')
    if sum(counts.values()) != value['target_count']:
        raise ValueError('Classified totals do not match original scope.')
    if value['address_count'] == 0:
        if value['target_count'] != 0: raise ValueError('Empty input cannot contain targets.')
    elif not 1 <= value['target_count'] // value['address_count'] <= 10 or value['target_count'] % value['address_count']:
        raise ValueError('Incomplete selected-device product.')
    created = datetime.fromisoformat(_time(value['created_at']))
    if datetime.fromisoformat(_time(value['expires_at'])) - created != timedelta(minutes=10):
        raise ValueError('Original draft lifetime is unavailable.')
    if value['can_execute'] is not False or type(value['state']) is not str or value['state'] not in {'PREPARED', 'EXPIRED', 'CANCELLED', 'CONFIRMED'}:
        raise ValueError('Original draft state is unavailable.')
    if value['state'] == 'CONFIRMED': _uuid(value['confirmed_operation_id'])
    elif value['confirmed_operation_id'] is not None: raise ValueError('Unconfirmed draft cannot imply policy.')


def validate_creation(value, target_count):
    _flags(value)
    if set(value) != set(FLAGS) | {'plan_id', 'digest', 'target_count'}:
        raise ValueError('Exact draft creation receipt is unavailable.')
    _uuid(value['plan_id'])
    require_digest(value['digest'])
    _integer(value['target_count'], 0, 100000, 'target count')
    if value['target_count'] != target_count:
        raise ValueError('Draft receipt does not match the requested product.')
    return value


def validate_list(value):
    _flags(value)
    if (set(value) != set(FLAGS) | {'initialized', 'plans'} or type(value['initialized']) is not bool
            or type(value['plans']) is not list or len(value['plans']) > 4
            or (not value['initialized'] and value['plans'])):
        raise ValueError('Complete private owner-list state is unavailable.')
    seen = set()
    for plan in value['plans']:
        if type(plan) is not dict or set(plan) != SUMMARY: raise ValueError('Incomplete private draft reference.')
        _summary(plan)
        if plan['plan_id'] in seen: raise ValueError('Duplicated private draft reference.')
        seen.add(plan['plan_id'])
    return value


def validate_devices(value):
    if type(value) is not list or len(value) > 65535: raise ValueError('Configured devices are unavailable.')
    seen = set()
    for device in value:
        if type(device) is not dict or set(device) != {'id', 'hostname', 'enabled'}: raise ValueError('Invalid public device metadata.')
        _integer(device['id'], 1, 65535, 'device ID')
        _text(device['hostname'], 255)
        if not device['hostname'] or type(device['enabled']) is not bool or device['id'] in seen:
            raise ValueError('Invalid configured device identity.')
        seen.add(device['id'])
    return value


def validate_report(value, plan_id, subject, page):
    _flags(value)
    fields = SUMMARY | set(FLAGS) | {'version', 'scope', 'actor_subject', 'actor_display_name', 'actor_roles',
        'reason', 'managed_initialized', 'managed_revision', 'protected_revision', 'devices', 'ignored_lines',
        'source_row_count', 'source_counts', 'execution_started', 'page', 'pages', 'page_size', 'targets', 'report_rows'}
    if (set(value) != fields or type(value['version']) is not int or value['version'] != 1
            or value['scope'] != 'managed_import_preparation' or value['plan_id'] != plan_id
            or value['actor_subject'] != subject or value['managed_initialized'] is not True
            or value['execution_started'] is not False):
        raise ValueError('Original owner-bound bulk draft report is unavailable.')
    _summary(value)
    _text(value['actor_subject'], 255)
    _text(value['actor_display_name'], 255)
    _text(value['reason'], 500, multiline=True)
    roles = value['actor_roles']
    if (type(roles) is not list or len(roles) > 3 or any(type(role) is not str or role not in {'Viewer', 'Operator', 'Administrator'} for role in roles)
            or len(set(roles)) != len(roles)):
        raise ValueError('Historical roles are invalid; they cannot authorize work.')
    for key in ('managed_revision', 'protected_revision'): _integer(value[key], 0, 2**63 - 1, key)
    devices = value['devices']
    if type(devices) is not list or not 1 <= len(devices) <= 10: raise ValueError('Complete original device selection is required.')
    previous = 0
    for device in devices:
        if type(device) is not dict or set(device) != {'id', 'hostname'}: raise ValueError('Invalid frozen device metadata.')
        _integer(device['id'], previous + 1, 65535, 'frozen device ID')
        previous = device['id']
        _text(device['hostname'], 255)
        if not device['hostname']: raise ValueError('Original device label is required.')
    if value['target_count'] != value['address_count'] * len(devices): raise ValueError('Original device product is incomplete.')
    _integer(value['ignored_lines'], 0, 20000, 'ignored lines')
    _integer(value['source_row_count'], 0, 10000, 'source rows')
    counts = value['source_counts']
    if type(counts) is not dict or set(counts) - STATUSES: raise ValueError('Unknown source diagnostics.')
    for count in counts.values(): _integer(count, 0, 10000, 'source count')
    if sum(counts.values()) != value['source_row_count'] or counts.get('Ready', 0) != value['address_count']:
        raise ValueError('Source diagnostics do not match original input totals.')
    pages = max(1, (max(value['target_count'], value['source_row_count']) + 99) // 100)
    if (type(value['page']) is not int or value['page'] != page or not 1 <= page <= pages
            or type(value['pages']) is not int or value['pages'] != pages
            or type(value['page_size']) is not int or value['page_size'] != 100):
        raise ValueError('Frozen pagination is unavailable.')
    offset, previous_pair = (page - 1) * 100, (0, -1)
    targets, rows = value['targets'], value['report_rows']
    if (type(targets) is not list or len(targets) != max(0, min(100, value['target_count'] - offset))
            or type(rows) is not list or len(rows) != max(0, min(100, value['source_row_count'] - offset))):
        raise ValueError('The original report page is incomplete.')
    for target in targets:
        if type(target) is not dict or set(target) != {'device_id', 'ip', 'classification', 'observed_at', 'managed_enabled',
                'previous_intent_id', 'previous_generation', 'previous_authorization_request_id'}:
            raise ValueError('Exact original target metadata is required.')
        _integer(target['device_id'], 1, 65535, 'target device')
        ip = IPv4Address(target['ip'])
        pair = target['device_id'], int(ip)
        if (type(target['ip']) is not str or str(ip) != target['ip'] or pair <= previous_pair
                or target['device_id'] not in {device['id'] for device in devices}
                or type(target['classification']) is not str or target['classification'] not in CLASSES
                or type(target['managed_enabled']) is not bool):
            raise ValueError('Invalid original target/classification order.')
        previous_pair = pair
        if target['previous_intent_id'] is None:
            if target['managed_enabled'] or target['previous_generation'] is not None or target['previous_authorization_request_id'] is not None:
                raise ValueError('Missing previous authority cannot imply maintenance.')
        else:
            _uuid(target['previous_intent_id'])
            _uuid(target['previous_authorization_request_id'])
            _integer(target['previous_generation'], 1, 2**63 - 1, 'previous generation')
        observed = target['observed_at']
        if observed is not None:
            _text(observed, 40)
            if not observed.endswith('Z') or datetime.fromisoformat(observed).utcoffset() != timedelta(0):
                raise ValueError('Original observation timezone is unavailable.')
        kind = target['classification']
        if ((kind == 'ALREADY_MANAGED' and not target['managed_enabled'])
                or (kind in {'PROPOSE_ADD', 'PROPOSE_ADOPT'} and target['managed_enabled'])
                or (kind == 'PROPOSE_ADD' and observed is not None) or (kind == 'PROPOSE_ADOPT' and observed is None)):
            raise ValueError('Original observation/maintenance classification is inconsistent.')
    for row in rows:
        if type(row) is not dict or set(row) != {'line', 'ip', 'status', 'source_lines', 'reason'}:
            raise ValueError('Exact generated diagnostics are required; raw source is forbidden.')
        _integer(row['line'], 1, 20000, 'source line')
        if type(row['status']) is not str or row['status'] not in STATUSES: raise ValueError('Unknown source status.')
        if row['ip'] is not None:
            if type(row['ip']) is not str or str(IPv4Address(row['ip'])) != row['ip'] or row['status'] not in {'Ready', 'Duplicate'}:
                raise ValueError('Invalid diagnostic address.')
        elif row['status'] in {'Ready', 'Duplicate'}: raise ValueError('An exact diagnostic address is missing.')
        _text(row['reason'], 500)
        if type(row['source_lines']) is not list or not 1 <= len(row['source_lines']) <= 20000:
            raise ValueError('Original source line references are unavailable.')
        last = 0
        for number in row['source_lines']:
            _integer(number, last + 1, 20000, 'source line reference')
            last = number
        if row['line'] not in row['source_lines']: raise ValueError('Source line identity is inconsistent.')
    return value


def validate_proposal(value, report):
    _flags(value)
    if set(value) != set(FLAGS) | {'operation_id', 'preparation_id', 'canonical', 'digest', 'manifest'}:
        raise ValueError('Exact non-authoritative proposal is unavailable.')
    if value['operation_id'] != operation_key(report['plan_id']) or value['preparation_id'] != report['plan_id']:
        raise ValueError('Proposal identity was substituted.')
    descriptor = decode_bulk_descriptor(value['canonical'], value['digest'])
    for key, expected in {'operation_id': value['operation_id'], 'preparation_id': report['plan_id'],
            'preparation_digest': report['digest'], 'managed_revision': report['managed_revision'],
            'protected_revision': report['protected_revision'], 'label': report['label'], 'reason': report['reason']}.items():
        if type(descriptor[key]) is not type(expected) or descriptor[key] != expected: raise ValueError('Proposal does not match original draft metadata.')
    manifest = descriptor['manifest']
    if (type(value['manifest']) is not dict
            or json.dumps(value['manifest'], sort_keys=True) != json.dumps(manifest, sort_keys=True)
            or manifest['device_ids'] != [device['id'] for device in report['devices']]
            or manifest['address_count'] != report['address_count'] or manifest['pair_count'] != report['target_count']
            or manifest['classification_counts'] != report['classification_counts']):
        raise ValueError('Proposal does not bind the complete original classified scope.')
    if report['state'] != 'PREPARED': raise ValueError('Closed draft cannot supply a proposal.')
    return value
