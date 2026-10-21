"""Pure proposed format: no database, policy, queue, HTTP or device authority."""

import hashlib
import json
import tracemalloc
from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address
from itertools import chain

import pytest

from ftd_shun_manager.bulk_intent import (
    CLASSES,
    DOMAIN,
    MAX_DESCRIPTOR_BYTES,
    canonical_bulk_intent,
    summarize_manifest,
    verify_bulk_intent,
)
from ftd_shun_manager.managed_intent import canonical_managed_change

OPERATION = "11111111-1111-4111-8111-111111111111"
PREPARATION = "22222222-2222-4222-8222-222222222222"
SOURCE_DIGEST = "a" * 64
ROWS = [(1, IPv4Address("192.0.2.2"), "PROPOSE_ADD"), (1, IPv4Address("192.0.2.10"), "EXCLUDED_PROTECTED"),
        (2, IPv4Address("192.0.2.2"), "PROPOSE_ADOPT"), (2, IPv4Address("192.0.2.10"), "ALREADY_MANAGED")]


def build(rows=None, devices=(1, 2), **changes):
    context = {"operation_id": OPERATION, "preparation_id": PREPARATION, "preparation_digest": SOURCE_DIGEST,
               "managed_revision": 4, "protected_revision": 7, "label": " Lab ", "reason": " Review "}
    return canonical_bulk_intent(iter(ROWS) if rows is None else rows, devices, **(context | changes))


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def maximum_rows():
    for device in range(1, 11):
        for number in range(10000):
            yield device, IPv4Address(0xC6120000 + number), CLASSES[number % 4]


def test_fixed_binary_and_descriptor_golden_vectors_are_versioned():
    summary, canonical, checksum = build()
    # Independent fixed record vector: u16 device, four address bytes, class1..4.
    records = bytes.fromhex("0001c0000202010001c000020a040002c0000202020002c000020a03")
    assert summary.digest == hashlib.sha256(DOMAIN + records).hexdigest()
    assert summary.digest == "105f591a83d6b1334815e04f41b1343d834666eb063dd337ac8e30d3110fbebb"
    assert checksum == "d87eb4cb45743f94700b0ce763935973b898c9dd1faddb5f9273445e55f3159a"
    assert checksum == digest(canonical) and verify_bulk_intent(canonical, iter(ROWS), checksum) == summary
    assert summary.accepted_count == 3 and summary.classification_counts == (1, 1, 1, 1)
    assert json.loads(canonical)["label"] == "Lab" and "targets" not in json.loads(canonical)
    with pytest.raises(FrozenInstanceError):
        summary.pair_count = 3


def test_maximum_stream_is_complete_bounded_in_memory_and_has_a_small_descriptor():
    tracemalloc.start()
    try:
        summary, canonical, checksum = build(maximum_rows(), tuple(range(1, 11)))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert summary.pair_count == 100000 and summary.address_count == 10000
    assert summary.accepted_count == 75000 and summary.classification_counts == (25000,) * 4
    assert len(canonical.encode()) < 1500 and len(canonical.encode()) < MAX_DESCRIPTOR_BYTES
    assert peak < 8 * 1024 * 1024  # No list/set of all 100000 pair records.
    assert verify_bulk_intent(canonical, maximum_rows(), checksum) == summary


def test_exact_ten_thousand_addresses_can_all_be_accepted():
    rows = ((device, ip, "PROPOSE_ADD") for device, ip, _ in maximum_rows())
    summary, canonical, checksum = build(rows, tuple(range(1, 11)))
    assert summary.accepted_count == summary.pair_count == 100000
    assert verify_bulk_intent(canonical, ((d, ip, "PROPOSE_ADD") for d, ip, _ in maximum_rows()), checksum) == summary


@pytest.mark.parametrize("devices", [(), (True,), (0,), (65536,), (1, 1), (2, 1), ("1",), list(range(1, 3)), tuple(range(1, 12))])
def test_device_scope_is_literal_explicit_distinct_and_bounded(devices):
    with pytest.raises(ValueError):
        build(devices=devices)


@pytest.mark.parametrize("row", [(True, IPv4Address("192.0.2.2"), "PROPOSE_ADD"),
    (3, IPv4Address("192.0.2.2"), "PROPOSE_ADD"), (1, "192.0.2.2", "PROPOSE_ADD"),
    (1, 3221225986, "PROPOSE_ADD"), (1, IPv4Address("192.0.2.2"), "ADD"),
    (1, IPv4Address("192.0.2.2"), 1), [1, IPv4Address("192.0.2.2"), "PROPOSE_ADD"],
    (1, IPv4Address("192.0.2.2"), "PROPOSE_ADD", "extra")])
def test_manifest_does_not_coerce_or_extract_fields(row):
    with pytest.raises(ValueError):
        build([row])


@pytest.mark.parametrize("rows", [[], ROWS[::-1], [ROWS[0], ROWS[0], *ROWS[1:]], ROWS[:-1], ROWS[:2],
                                   [ROWS[0], ROWS[2], ROWS[1], ROWS[3]]])
def test_missing_duplicate_or_non_numerically_sorted_cells_never_become_a_prefix(rows):
    with pytest.raises(ValueError):
        build(rows)


def test_limits_stop_before_an_unbounded_or_oversized_stream_is_materialized():
    def excessive_addresses():
        for number in range(10001):
            yield 1, IPv4Address(0xC6120000 + number), "PROPOSE_ADD"
        raise AssertionError("The reader should have refused the extra address")

    with pytest.raises(ValueError, match="10000"):
        build(excessive_addresses(), (1,))
    with pytest.raises(ValueError, match="100000"):
        build(chain(maximum_rows(), [ROWS[0]]), tuple(range(1, 11)))


def test_excluded_only_input_has_a_report_but_never_a_standing_proposal():
    rows = [(1, IPv4Address("192.0.2.2"), "EXCLUDED_PROTECTED")]
    assert summarize_manifest(rows, (1,)).accepted_count == 0
    with pytest.raises(ValueError, match="no accepted"):
        build(rows, (1,))


@pytest.mark.parametrize("change", ["classification_swap", "pair_swap", "complete_smaller_product", "last_cell", "duplicate"])
def test_complete_verification_binds_classification_and_every_pair_not_only_counts(change):
    summary, canonical, checksum = build()
    altered = list(ROWS)
    if change == "classification_swap":
        altered[0] = (*ROWS[0][:2], ROWS[1][2])
        altered[1] = (*ROWS[1][:2], ROWS[0][2])
    elif change == "pair_swap":
        altered[0] = (1, IPv4Address("192.0.2.1"), ROWS[0][2])
        altered[2] = (2, IPv4Address("192.0.2.1"), ROWS[2][2])
    elif change == "complete_smaller_product": altered = [ROWS[0], ROWS[2]]
    elif change == "last_cell": altered.pop()
    else: altered.insert(1, ROWS[0])
    with pytest.raises(ValueError):
        verify_bulk_intent(canonical, altered, checksum)
    assert summary.pair_count == 4


@pytest.mark.parametrize("field,value", [("operation_id", PREPARATION), ("operation_id", "not-a-uuid"),
    ("preparation_id", 1), ("preparation_digest", "A" * 64), ("managed_revision", True),
    ("protected_revision", "7"), ("managed_revision", -1), ("protected_revision", 2**63),
    ("label", "x" * 101), ("reason", "x" * 501), ("label", None), ("reason", "bad\x00text"),
    ("reason", "bad\ud800text")])
def test_binding_context_is_strict_and_not_an_arbitrary_operation(field, value):
    with pytest.raises(ValueError):
        build(**{field: value})


def test_valid_context_changes_cannot_reuse_the_original_review_digest():
    _, original, old = build()
    for changes in ({"managed_revision": 5}, {"protected_revision": 8}, {"label": "Other"}, {"reason": "Other"},
                    {"preparation_digest": "b" * 64}, {"operation_id": "33333333-3333-4333-8333-333333333333"}):
        _, changed, checksum = build(**changes)
        assert checksum != old and changed != original
        with pytest.raises(ValueError, match="digest"):
            verify_bulk_intent(changed, iter(ROWS), old)


@pytest.mark.parametrize("change", ["version", "float_version", "scope", "action", "mode", "root_extra", "manifest_extra",
                                   "format", "coerced_count", "wrong_count", "wrong_accepted", "count_extra", "device_order",
                                   "untrimmed", "whitespace", "duplicate_root", "duplicate_counts", "too_long", "null", "nested"])
def test_invalid_or_noncanonical_descriptors_refuse_before_consuming_membership(change):
    _, canonical, _ = build()
    value = json.loads(canonical)
    if change in {"version", "scope", "action", "mode"}:
        value[change] = {"version": 1, "scope": "import", "action": "REMOVE", "mode": "one_time"}[change]
    elif change == "float_version": value["version"] = 2.0
    elif change == "root_extra": value["actor"] = "spoofed"
    elif change == "manifest_extra": value["manifest"]["route"] = "arbitrary"
    elif change == "format": value["manifest"]["format"] = "other"
    elif change == "coerced_count": value["manifest"]["classification_counts"]["PROPOSE_ADD"] = True
    elif change == "wrong_count": value["manifest"]["pair_count"] = 3
    elif change == "wrong_accepted": value["manifest"]["accepted_count"] = 4
    elif change == "count_extra": value["manifest"]["classification_counts"]["OTHER"] = 0
    elif change == "device_order": value["manifest"]["device_ids"] = [2, 1]
    elif change == "untrimmed": value["label"] = " Lab "
    altered = encoded(value)
    if change == "whitespace": altered = json.dumps(value)
    elif change == "duplicate_root": altered = altered[:-1] + ',"version":2}'
    elif change == "duplicate_counts": altered = altered.replace('"PROPOSE_ADD":1', '"PROPOSE_ADD":1,"PROPOSE_ADD":1')
    elif change == "too_long": altered += " " * MAX_DESCRIPTOR_BYTES
    elif change == "null": altered = "null"
    elif change == "nested": altered = "[" * 1500 + "0" + "]" * 1500

    def forbidden():
        raise AssertionError("Invalid descriptor must fail before the membership iterator is consumed")
        yield

    with pytest.raises(ValueError):
        verify_bulk_intent(altered, forbidden(), digest(altered))


def test_summary_is_validated_but_still_requires_complete_membership_verification():
    summary, _, _ = build()
    for changes in ({"address_count": True}, {"pair_count": 3}, {"classification_counts": (1, 1, 1, True)},
                    {"classification_counts": [1, 1, 1, 1]}, {"digest": "wrong"}):
        with pytest.raises(ValueError):
            replace(summary, **changes)
    other = replace(summary, digest="b" * 64)
    assert other != summary  # A constructible descriptor is not membership proof or authority.


def test_legacy_canonical_request_and_its_limit_are_not_reinterpreted():
    pairs = [(1, IPv4Address("192.0.2.2"))]
    old = canonical_managed_change("MAINTAIN", pairs, 4, 7, "Lab", "Review")
    assert old[2] == "5f373c7d2f853f8e5d035d861425dca199eb938fdd394a20c198dbc99a99aabd"
    assert "manifest" not in json.loads(old[1]) and "version" not in json.loads(old[1])
    with pytest.raises(ValueError):
        verify_bulk_intent(old[1], iter(ROWS), old[2])
    with pytest.raises(ValueError, match="1000"):
        canonical_managed_change("MAINTAIN", [(1, IPv4Address(0xC6120000 + i)) for i in range(1001)], 4, 7)
