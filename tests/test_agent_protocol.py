from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.agent_protocol import Operation, decode_request, encode_request


def test_remove_shun_packet_is_fixed_and_binary() -> None:
    packet = encode_request(Operation.REMOVE_SHUN, 7, IPv4Address("203.0.113.17"))
    assert packet == bytes.fromhex("03 00 07 CB 00 71 11")
    assert decode_request(packet) == (Operation.REMOVE_SHUN, 7, IPv4Address("203.0.113.17"))


@pytest.mark.parametrize("packet", [b"", b"\x03\x00\x07", b"\xff\x00\x01", b"\x01\x00\x00"])
def test_bad_packets_fail_closed(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode_request(packet)
