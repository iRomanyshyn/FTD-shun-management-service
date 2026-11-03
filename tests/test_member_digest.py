"""Formatting reuse must produce every original canonical byte, never cached proof."""

import hashlib
from ipaddress import IPv4Address
from random import Random

import pytest

from ftd_shun_manager import member_digest
from ftd_shun_manager.import_preparations import _feed, _member
from ftd_shun_manager.member_digest import MemberDigest


def row(**changes):
    return {'device_id': 1, 'ip': IPv4Address('198.51.100.1').packed,
            'classification': 'PROPOSE_ADD', 'managed_enabled': 0, 'observed_at': None,
            'previous_intent_id': None, 'previous_generation': None,
            'previous_authorization_request_id': None, **changes}


class Bytes:
    def __init__(self):
        self.data = bytearray()

    def update(self, data):
        self.data.extend(data)


@pytest.mark.parametrize('changes', [
    {}, {'device_id': 65535}, {'device_id': '1'}, {'device_id': True},
    {'classification': 'PROPOSE_ADOPT'}, {'classification': 'ALREADY_MANAGED'},
    {'classification': 'EXCLUDED_PROTECTED'}, {'managed_enabled': 1},
    {'observed_at': '2026-11-03T12:00:00.000Z'},
    {'observed_at': '\"ip\":\"\" \\ \n café 🦊'},
    {'previous_intent_id': 'one'}, {'previous_generation': 1},
    {'previous_authorization_request_id': 'two'},
])
def test_each_encoded_byte_matches_original_canonical_feed(changes):
    expected, actual = Bytes(), Bytes()
    writer = MemberDigest(actual)
    # A preceding common row must not make a different shape share its template.
    for value in (row(), row(**changes), row(ip=IPv4Address('255.255.255.255').packed)):
        _feed(expected, _member(value))
        writer.feed(value)
    assert actual.data == expected.data


def test_mixed_stream_exact_digest_and_template_bound():
    rng = Random(71)
    expected, actual = hashlib.sha256(), hashlib.sha256()
    writer = MemberDigest(actual)
    for i in range(2000):
        value = row(device_id=1 + i % 20, ip=IPv4Address(rng.getrandbits(32)).packed)
        if i % 4 == 0:
            value.update(observed_at=f'2026-11-03T12:00:{i % 60:02d}Z', managed_enabled=1)
        _feed(expected, _member(value))
        writer.feed(value)
        assert len(writer._templates) <= 10
    assert actual.digest() == expected.digest()


def test_common_shapes_reuse_only_framing_not_previous_member_or_result(monkeypatch):
    calls, original = [], member_digest._json

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(member_digest, '_json', counted)
    expected, actual = Bytes(), Bytes()
    writer = MemberDigest(actual)
    for i in range(1000):
        value = row(ip=IPv4Address(i).packed)
        _feed(expected, _member(value))
        writer.feed(value)
    assert len(calls) == 1 and actual.data == expected.data
    # Even after template creation, invalid IP input is not accepted/cached.
    with pytest.raises(ValueError):
        writer.feed(row(ip=b'invalid'))
    other = MemberDigest(Bytes())
    assert not other._templates


def test_future_source_fields_fall_back_instead_of_reusing_an_incomplete_template(monkeypatch):
    def expanded(value):
        return {**_member(value), 'future_metadata': value['ip'].hex()}

    monkeypatch.setattr(member_digest, '_member', expanded)
    expected, actual = Bytes(), Bytes()
    writer = MemberDigest(actual)
    for i in range(3):
        value = row(ip=IPv4Address(i).packed)
        _feed(expected, expanded(value))
        writer.feed(value)
    assert actual.data == expected.data and not writer._templates
