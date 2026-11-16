"""Current ownership is distinct from immutable import membership; no RPC/writes."""

from ipaddress import IPv4Address

import pytest
from test_bulk_policy import bulk as bulk  # noqa: PLC0414
from test_bulk_policy import confirm, dump, prepare, retire

from ftd_shun_manager.bulk_policy import BulkUnavailable
from ftd_shun_manager.import_ownership import ImportOwnership
from ftd_shun_manager.managed_shuns import ManagedPageChanged, ManagedPageInvalid
from ftd_shun_manager.protected_policy import ProtectedPolicy


def test_duplicate_import_does_not_own_another_imports_targets(bulk):
    first = confirm(bulk, prepare(bulk, '198.51.100.1')[1])
    second = confirm(bulk, prepare(bulk, '198.51.100.1\n198.51.100.2')[1])
    service = ImportOwnership(bulk[0].store)
    original = dump(bulk[0].store)
    a = service.page(first['operation_id'])
    b = service.page(second['operation_id'])
    assert a['owned_count'] == b['owned_count'] == 1
    assert [r['ip'] for r in b['targets']] == ['198.51.100.2']
    excluded = service.page(second['operation_id'], scope='excluded')
    assert excluded['targets'][0]['ownership'] == 'ALREADY_MANAGED'
    assert excluded['targets'][0]['current_import_id'] == first['operation_id']
    assert a['read_only'] and not a['can_execute'] and not a['device_work_admitted']
    assert dump(bulk[0].store) == original


def test_retirement_reimport_and_protection_do_not_expand_original_ownership(bulk):
    first = confirm(bulk, prepare(bulk, '198.51.100.1\n198.51.100.2')[1])
    service = ImportOwnership(bulk[0].store)
    previous = service.page(first['operation_id'])
    retire(bulk)
    second = confirm(bulk, prepare(bulk, '198.51.100.1')[1])
    policy = ProtectedPolicy(bulk[0].store)
    policy.change('add', IPv4Address('198.51.100.2'), policy.revision(), 'viewer', 'Viewer', ('Viewer',),
                  managed_revision=bulk[0].policy_page()['revision'])
    result = service.page(first['operation_id'], scope='all')
    assert result['owned_count'] == 0
    assert [r['ownership'] for r in result['targets']] == ['SUPERSEDED', 'RETIRED']
    assert result['targets'][0]['current_import_id'] == second['operation_id']
    assert result['scope_digest'] != previous['scope_digest']
    with pytest.raises(ManagedPageChanged): service.page(first['operation_id'], revision=previous['managed_revision'])


def test_adoption_absent_owned_and_protected_exclusion_are_separate(bulk):
    store = bulk[0].store
    store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')
    editor = ProtectedPolicy(store)
    editor.change('add', IPv4Address('198.51.100.3'), editor.revision(), 'viewer', 'Viewer', ('Viewer',), managed_revision=0)
    imported = confirm(bulk, prepare(bulk, '198.51.100.1\n198.51.100.2\n198.51.100.3', (1,2))[1])
    result = ImportOwnership(store).page(imported['operation_id'], scope='all')
    assert result['member_count'] == 6 and result['owned_count'] == 4
    assert result['counts']['OWNED_ADOPTED'] == result['observed_owned'] == 1
    assert result['absent_owned'] == 3 and result['counts']['EXCLUDED_PROTECTED'] == 2


def test_page_is_bounded_and_large_scope_is_counted_without_truncation(bulk):
    text = '\n'.join(str(IPv4Address(0xC6120000+i)) for i in range(1501))
    imported = confirm(bulk, prepare(bulk, text)[1])
    result = ImportOwnership(bulk[0].store).page(imported['operation_id'], page=16)
    assert result['owned_count'] == 1501 and result['pages'] == 16 and len(result['targets']) == 1
    with pytest.raises(ManagedPageInvalid): ImportOwnership(bulk[0].store).page(imported['operation_id'], page=17)


def test_observation_changes_do_not_change_ownership_or_authority_digest(bulk):
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    service = ImportOwnership(bulk[0].store)
    a = service.page(key)
    bulk[0].store.record_observed_shun(1, IPv4Address('198.51.100.1'), 'management')
    b = service.page(key)
    assert a['scope_digest'] == b['scope_digest']
    assert a['observed_owned'] == 0 and b['observed_owned'] == 1


def test_unresolved_outcome_is_visible_without_becoming_cleanup_authority(bulk):
    from uuid import uuid4

    from ftd_shun_manager.operation_queue import stamp

    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    with bulk[0].store._connection() as db:
        db.execute("INSERT INTO operation_jobs(id,device_id,ip,state,requested_at,action) VALUES (?,1,?,'UNVERIFIED',?,'ADD')",
                   (str(uuid4()), IPv4Address('198.51.100.1').packed, stamp(bulk[1][0])))
    before = dump(bulk[0].store)
    result = ImportOwnership(bulk[0].store).page(key)
    assert result['attention_owned'] == 1 and result['targets'][0]['attention']
    assert result['can_execute'] is False and dump(bulk[0].store) == before


def test_current_lists_include_readable_import_reference(bulk):
    from ftd_shun_manager.bulk_policy_views import BulkPolicyViews
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    entry = BulkPolicyViews(bulk[0].store).page()['entries'][0]
    assert entry['import']['id'] == key and entry['import']['label'] == 'Fixture'
    assert entry['import']['actor_display_name'] == 'Actual author'


def test_broken_membership_never_renders_as_an_empty_import(bulk):
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    with bulk[0].store._connection() as db:
        db.execute('CREATE TABLE managed_unrecognized_scope(value INTEGER)')
    with pytest.raises(BulkUnavailable): ImportOwnership(bulk[0].store).page(key)


def test_missing_policy_key_is_unavailable_not_a_successful_empty_scope(bulk):
    key = confirm(bulk, prepare(bulk)[1])['operation_id']
    with bulk[0].store._connection() as db:
        db.execute('DELETE FROM managed_shun_targets')
    with pytest.raises(BulkUnavailable, match='missing its retained policy key'):
        ImportOwnership(bulk[0].store).page(key)


def test_full_100000_pair_import_has_complete_counts_and_only_100_presented_rows(bulk):
    from time import monotonic

    text = '\n'.join(str(IPv4Address(0xC6120000+i)) for i in range(100000))
    key = confirm(bulk, prepare(bulk, text)[1])['operation_id']
    start = monotonic()
    result = ImportOwnership(bulk[0].store).page(key, page=1000)
    assert result['member_count'] == result['owned_count'] == 100000
    assert result['page'] == result['pages'] == 1000 and len(result['targets']) == 100
    assert result['targets'][-1]['ip'] == str(IPv4Address(0xC6120000+99999))
    # Evidence only; a loaded development host is not a performance SLA.
    print(f'100000-pair current ownership read: {monotonic()-start:.3f}s')
