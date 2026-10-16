"""A proposed addition contract must not accidentally become a live capability."""

import pytest

from ftd_shun_manager.agent_protocol import (
    CycleOperation,
    Operation,
    decode_cycle_response,
    decode_request,
    encode_cycle_request,
)


def test_no_live_addition_operation_or_cycle_opcode_exists():
    assert all("ADD" not in operation.name for operation in Operation)
    assert all("ADD" not in operation.name for operation in CycleOperation)
    with pytest.raises(ValueError):
        CycleOperation(0x14)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_draft_addition_frames_cannot_enter_legacy_agent_protocol(version):
    for packet in [bytes([0x14, version, 1, 198, 51, 100, 251]),
                   bytes([0x08, 0, 1, 198, 51, 100, 251])]:
        with pytest.raises(ValueError, match="unknown operation"):
            decode_request(packet)


def test_draft_cycle_version_is_rejected_not_negotiated_or_downgraded():
    with pytest.raises(ValueError, match="invalid cycle version"):
        encode_cycle_request(CycleOperation.BEGIN, 0, device_id=1, version=3)
    with pytest.raises(ValueError, match="invalid cycle version"):
        decode_cycle_response(bytes.fromhex("0003140100"), CycleOperation.REMOVE, 1, version=3)
