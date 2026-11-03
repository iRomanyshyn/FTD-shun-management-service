"""Canonical assigned IDs remain exact; no skipped root or authority checks."""

from random import Random
from uuid import UUID

import pytest
from test_bulk_policy import bulk as bulk  # noqa: PLC0414 -- Shared disposable fixture.
from test_bulk_policy import confirm, prepare
from test_profile_query_equivalence import damage_disposable_database

from ftd_shun_manager.bulk_policy import BulkUnavailable, _assigned_intent_valid


def previous_predicate(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def test_canonical_checker_matches_uuid_roundtrip_for_all_bits_and_format_variants():
    rng = Random(166)
    values = [str(UUID(int=0)), str(UUID(int=2**128 - 1))]
    values += [str(UUID(int=rng.getrandbits(128))) for _ in range(2000)]
    for value in values:
        assert _assigned_intent_valid(value)
        for candidate in (value, value.upper(), value.replace('-', ''), '{' + value + '}',
                          'urn:uuid:' + value, value + '\n', ' ' + value, value + ' ',
                          value[:8] + '--' + value[9:], value[:-1], value + '0'):
            assert _assigned_intent_valid(candidate) == previous_predicate(candidate)


@pytest.mark.parametrize('value', [None, 0, True, b'0' * 36, UUID(int=0), '', 'g' * 36, '0' * 100000,
                                  '００００００００-0000-0000-0000-000000000000',
                                  '00000000\x000000-0000-0000-000000000000'])
def test_noncanonical_and_wrong_type_ids_fail_closed(value):
    assert not _assigned_intent_valid(value)
    assert not previous_predicate(value)


@pytest.mark.parametrize('value', ['not-a-uuid', 'ABCDEF01-2345-6789-ABCD-EF0123456789',
                                  '00000000000000000000000000000000',
                                  '00000000-0000-0000-0000-000000000000\n'])
def test_complete_root_still_refuses_noncanonical_assigned_ids_with_valid_source_digest(bulk, value):
    policy, _ = bulk
    operation = confirm(bulk, prepare(bulk)[1])['operation_id']
    # Assigned identity is not in the source preparation or pair/class digest.
    # Keep target/member bindings consistent so only the root's ID check catches it.
    damage_disposable_database(policy.store, 'UPDATE managed_bulk_members SET intent_id=?', (value,))
    damage_disposable_database(policy.store, 'UPDATE managed_shun_targets SET intent_id=?', (value,))
    with policy.store._connection() as db, pytest.raises(BulkUnavailable, match='assigned intent identity'):
        db.execute('BEGIN')
        policy._root(db, operation, 'alice')
