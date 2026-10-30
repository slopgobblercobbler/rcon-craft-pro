"""Unit tests for binary RCON packet protocol framing, encoding, and decoding."""

import asyncio
import struct
import pytest

from rcon_craft.models import (
    PacketType,
    RconConnectionError,
    RconPacket,
    RconProtocolError,
    RconTimeoutError,
)
from rcon_craft.protocol import (
    HEADER_SIZE,
    MAX_PACKET_LENGTH,
    MIN_PACKET_LENGTH,
    PADDING,
    decode_packet,
    encode_packet,
    read_packet,
)


def test_encode_packet_structure():
    """Verify Little-Endian encoding of length, request ID, type, payload, and null pads."""
    req_id = 42
    p_type = PacketType.SERVERDATA_AUTH
    payload = "mypassword"

    encoded = encode_packet(req_id, p_type, payload)

    # Total length field should be len(payload) + 10 = 10 + 10 = 20
    length, decoded_id, decoded_type = struct.unpack("<iii", encoded[:12])
    assert length == len(payload.encode("utf-8")) + HEADER_SIZE
    assert decoded_id == req_id
    assert decoded_type == int(p_type)

    # Check payload bytes
    assert encoded[12:-2] == payload.encode("utf-8")
    # Check 2 null terminators
    assert encoded[-2:] == PADDING


def test_decode_complete_packet():
    """Verify decoding a standard packet from bytes."""
    payload = "list of players"
    raw = encode_packet(101, PacketType.SERVERDATA_RESPONSE_VALUE, payload)

    packet, consumed = decode_packet(raw)
    assert packet is not None
    assert consumed == len(raw)
    assert packet.request_id == 101
    assert packet.packet_type == PacketType.SERVERDATA_RESPONSE_VALUE
    assert packet.payload == payload
    assert packet.is_response is True
    assert packet.is_command is False
    assert packet.is_auth is False


def test_decode_incomplete_buffer():
    """Verify that buffer with insufficient bytes returns (None, 0)."""
    raw = encode_packet(1, PacketType.SERVERDATA_EXECCOMMAND, "help")

    # Buffer smaller than length field (4 bytes)
    pkt, consumed = decode_packet(raw[:2])
    assert pkt is None
    assert consumed == 0

    # Buffer has length field but not full body
    pkt, consumed = decode_packet(raw[:8])
    assert pkt is None
    assert consumed == 0


def test_decode_invalid_length_too_small():
    """Verify error when length field is less than 10 bytes."""
    corrupted = struct.pack("<iii", 5, 1, 2) + b"\x00\x00"
    with pytest.raises(RconProtocolError, match="Invalid packet length"):
        decode_packet(corrupted)


def test_decode_invalid_length_too_large():
    """Verify error when length field exceeds MAX_PACKET_LENGTH."""
    corrupted = struct.pack("<iii", MAX_PACKET_LENGTH + 100, 1, 2)
    with pytest.raises(RconProtocolError, match="exceeds maximum allowed size"):
        decode_packet(corrupted)


def test_decode_missing_null_padding():
    """Verify error when trailing null bytes are missing or corrupted."""
    length = 10 + len("bad")
    corrupted = struct.pack("<iii", length, 1, 2) + b"bad" + b"\x01\x02"
    with pytest.raises(RconProtocolError, match="missing required double null terminator"):
        decode_packet(corrupted)


def test_decode_multiple_packets_in_buffer():
    """Verify sequential decoding of multiple packets from a single buffer."""
    pkt1 = encode_packet(1, PacketType.SERVERDATA_EXECCOMMAND, "command 1")
    pkt2 = encode_packet(2, PacketType.SERVERDATA_EXECCOMMAND, "command 2")
    combined = pkt1 + pkt2

    p1, consumed1 = decode_packet(combined)
    assert p1 is not None
    assert p1.payload == "command 1"
    assert consumed1 == len(pkt1)

    p2, consumed2 = decode_packet(combined[consumed1:])
    assert p2 is not None
    assert p2.payload == "command 2"
    assert consumed2 == len(pkt2)


def test_decode_unknown_packet_type():
    """Verify handling of unknown packet type integer."""
    raw = encode_packet(55, 9999, "unknown")
    packet, consumed = decode_packet(raw)
    assert packet is not None
    assert packet.packet_type == 9999


@pytest.mark.asyncio
async def test_read_packet_from_stream():
    """Verify reading a packet asynchronously from asyncio.StreamReader."""
    reader = asyncio.StreamReader()
    raw = encode_packet(7, PacketType.SERVERDATA_AUTH_RESPONSE, "auth_ok")
    reader.feed_data(raw)
    reader.feed_eof()

    packet = await read_packet(reader)
    assert packet.request_id == 7
    assert packet.packet_type == PacketType.SERVERDATA_AUTH_RESPONSE
    assert packet.payload == "auth_ok"
    assert packet.is_auth_response is True


@pytest.mark.asyncio
async def test_read_packet_incomplete_stream():
    """Verify IncompleteReadError triggers RconConnectionError."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x05\x00")  # truncated
    reader.feed_eof()

    with pytest.raises(RconConnectionError, match="Server disconnected unexpectedly"):
        await read_packet(reader)


@pytest.mark.asyncio
async def test_read_packet_timeout():
    """Verify timeout triggers RconTimeoutError."""
    reader = asyncio.StreamReader()
    # Don't feed any data, wait with short timeout
    with pytest.raises(RconTimeoutError, match="timed out"):
        await read_packet(reader, timeout=0.01)


@pytest.mark.asyncio
async def test_read_packet_corrupt_padding():
    """Verify corrupt padding triggers RconProtocolError."""
    reader = asyncio.StreamReader()
    raw = encode_packet(7, PacketType.SERVERDATA_AUTH_RESPONSE, "test")
    corrupted = raw[:-1] + b"\xFF"
    reader.feed_data(corrupted)
    reader.feed_eof()

    with pytest.raises(RconProtocolError, match="missing required double null terminator"):
        await read_packet(reader)


@pytest.mark.asyncio
async def test_read_packet_invalid_length_too_small():
    """Verify invalid length in stream reader triggers RconProtocolError."""
    reader = asyncio.StreamReader()
    corrupted = struct.pack("<i", 4)  # length 4 < 10
    reader.feed_data(corrupted)
    with pytest.raises(RconProtocolError, match="Invalid packet length"):
        await read_packet(reader)


@pytest.mark.asyncio
async def test_read_packet_invalid_length_too_large():
    """Verify invalid length exceeding max size in stream reader triggers RconProtocolError."""
    reader = asyncio.StreamReader()
    corrupted = struct.pack("<i", 100000)
    reader.feed_data(corrupted)
    with pytest.raises(RconProtocolError, match="exceeds max allowed"):
        await read_packet(reader)
