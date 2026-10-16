from ipaddress import IPv4Address

import pytest

from ftd_shun_manager.agent_protocol import (
    MAX_AGENT_RESPONSE_BYTES,
    CycleOperation,
    ObservedShun,
    Operation,
    decode_cycle_response,
    decode_list_shuns_response,
    decode_request,
    encode_request,
)


def test_remove_shun_packet_is_fixed_and_binary() -> None:
    packet = encode_request(Operation.REMOVE_SHUN, 7, IPv4Address("203.0.113.17"))
    assert packet == bytes.fromhex("03 00 07 CB 00 71 11")
    assert decode_request(packet) == (Operation.REMOVE_SHUN, 7, IPv4Address("203.0.113.17"))


@pytest.mark.parametrize("packet", [b"", b"\x03\x00\x07", b"\xff\x00\x01", b"\x01\x00\x00"])
def test_bad_packets_fail_closed(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode_request(packet)


def test_list_shuns_response_is_fixed_binary_and_complete() -> None:
    packet = bytes.fromhex(
        "00 00 02"
        " C6 33 64 FA 0A 6D 61 6E 61 67 65 6D 65 6E 74"
        " CB 00 71 11 07 6F 75 74 73 69 64 65"
    )

    assert decode_list_shuns_response(packet) == [
        ObservedShun(IPv4Address("198.51.100.250"), "management"),
        ObservedShun(IPv4Address("203.0.113.17"), "outside"),
    ]


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x01\x00\x00",
        b"\x00\x00\x01\xc6\x33\x64\xfa",
        b"\x00\x00\x01\xc6\x33\x64\xfa\x00",
        b"\x00\x00\x00\x00",
        b"\x00\x00\x01\xc6\x33\x64\xfa\x03\x24\x24\x24",
    ],
)
def test_bad_list_shuns_responses_fail_closed(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode_list_shuns_response(packet)


@pytest.mark.parametrize("count", [4368, 4369, 7307])
def test_management_snapshot_capacity_is_not_the_preview_capacity(count: int) -> None:
    entries = b"".join(IPv4Address(0xC6120000 + index).packed + b"\x0amanagement" for index in range(count))
    packet = b"\x00" + count.to_bytes(2, "big") + entries
    cycle_packet = bytes([0, 1, CycleOperation.BEGIN, 0]) + packet
    assert len(packet) == 3 + count * 15
    assert len(cycle_packet) == 7 + count * 15
    if count <= 4368:
        assert len(decode_list_shuns_response(packet)) == count
        assert len(decode_cycle_response(cycle_packet, CycleOperation.BEGIN, 0)) == count
    else:
        assert len(packet) > MAX_AGENT_RESPONSE_BYTES
        with pytest.raises(ValueError, match="maximum size"):
            decode_list_shuns_response(packet)
        with pytest.raises(ValueError, match="response size"):
            decode_cycle_response(cycle_packet, CycleOperation.BEGIN, 0)
