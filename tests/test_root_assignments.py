"""Assigned authority comparisons still bind every classification and field."""

from ipaddress import IPv4Address

import pytest
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Disposable storage only.
from test_bulk_policy import confirm, prepare
from test_profile_query_equivalence import damage_disposable_database

from ftd_shun_manager.bulk_policy import BulkUnavailable


@pytest.mark.parametrize('classification', ['PROPOSE_ADD', 'PROPOSE_ADOPT', 'ALREADY_MANAGED'])
@pytest.mark.parametrize('field,value', [
    ('generation', None), ('generation', 99),
    ('authorization_request_id', '11111111-1111-4111-8111-111111111111'),
])
def test_root_rejects_assigned_field_changes_without_changing_source_digest(bulk, classification, field, value):
    policy, _ = bulk
    confirm(bulk, prepare(bulk)[1])
    policy.store.record_observed_shun(2, IPv4Address('198.51.100.1'), 'management')
    root = confirm(bulk, prepare(bulk, '198.51.100.1\n198.51.100.2', (1, 2))[1])['operation_id']
    with policy.store._connection() as db:
        assert policy._root(db, root, 'alice')[2].pair_count == 4
    # Only the derived assignment is damaged. Header/source members and the
    # original descriptor/digests stay unchanged, so hash checks cannot mask it.
    damage_disposable_database(policy.store,
        f'UPDATE managed_bulk_members SET {field}=? WHERE request_id=? AND classification=?',
        (value, root, classification))
    with policy.store._connection() as db, pytest.raises(BulkUnavailable, match='Assigned bulk authority'):
        db.execute('BEGIN')
        policy._root(db, root, 'alice')
