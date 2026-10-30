"""Minecraft RCON protocol packet framing, serialization, and stream decoding."""

from __future__ import annotations

import asyncio
import struct
from typing import Optional, Tuple, Union

from rcon_craft.models import (
    PacketType,
    RconConnectionError,
    RconPacket,
    RconProtocolError,
    RconTimeoutError,
)

HEADER_SIZE = 10  # 4 bytes Request ID + 4 bytes Packet Type + 2 bytes null padding
LENGTH_FIELD_SIZE = 4
MIN_PACKET_LENGTH = 10
MAX_PACKET_LENGTH = 65536  # Upper sanity limit to protect against corrupted frames
PADDING = b"\x00\x00"


def encode_packet(
    request_id: int,
    packet_type: Union[int, PacketType],
    payload: str = "",
    encoding: str = "utf-8",
) -> bytes:
    """Serializes an RCON packet into wire format.

    Format:
        Length: 32-bit little-endian int (len(payload) + 10)
        Request ID: 32-bit little-endian int
        Packet Type: 32-bit little-endian int
        Payload: ASCII/UTF-8 encoded string
        Padding: 2 null bytes (\\x00\\x00)
    """
    payload_bytes = payload.encode(encoding)
    packet_length = len(payload_bytes) + HEADER_SIZE
    header = struct.pack("<iii", packet_length, request_id, int(packet_type))
    return header + payload_bytes + PADDING


def decode_packet(
    buffer: bytes,
    encoding: str = "utf-8",
) -> Tuple[Optional[RconPacket], int]:
    """Decodes a single packet from a raw bytes buffer.

    Returns:
        A tuple of (RconPacket, bytes_consumed).
        If the buffer does not yet contain a complete packet, returns (None, 0).

    Raises:
        RconProtocolError: If the packet header or framing is malformed.
    """
    if len(buffer) < LENGTH_FIELD_SIZE:
        return None, 0

    (packet_length,) = struct.unpack("<i", buffer[:LENGTH_FIELD_SIZE])

    if packet_length < MIN_PACKET_LENGTH:
        raise RconProtocolError(
            f"Invalid packet length: {packet_length} bytes (minimum is {MIN_PACKET_LENGTH})"
        )
    if packet_length > MAX_PACKET_LENGTH:
        raise RconProtocolError(
            f"Packet length {packet_length} exceeds maximum allowed size ({MAX_PACKET_LENGTH})"
        )

    total_size = LENGTH_FIELD_SIZE + packet_length
    if len(buffer) < total_size:
        return None, 0

    packet_body = buffer[LENGTH_FIELD_SIZE:total_size]
    request_id, raw_packet_type = struct.unpack("<ii", packet_body[:8])

    # Validate trailing null padding
    if not packet_body.endswith(PADDING):
        raise RconProtocolError("Packet missing required double null terminator (\\x00\\x00)")

    raw_payload = packet_body[8:-2]
    try:
        payload = raw_payload.decode(encoding)
    except UnicodeDecodeError:
        payload = raw_payload.decode(encoding, errors="replace")

    try:
        packet_type = PacketType(raw_packet_type)
    except ValueError:
        packet_type = raw_packet_type

    packet = RconPacket(
        request_id=request_id,
        packet_type=packet_type,
        payload=payload,
    )
    return packet, total_size


async def read_packet(
    reader: asyncio.StreamReader,
    timeout: Optional[float] = None,
    encoding: str = "utf-8",
) -> RconPacket:
    """Reads exactly one complete RCON packet from an asyncio StreamReader.

    Raises:
        RconTimeoutError: If reading times out.
        RconConnectionError: If the remote end disconnects prematurely.
        RconProtocolError: If the packet length or framing is malformed.
    """
    try:
        async def _read():
            # Read 4-byte length prefix
            raw_length = await reader.readexactly(LENGTH_FIELD_SIZE)
            (packet_length,) = struct.unpack("<i", raw_length)

            if packet_length < MIN_PACKET_LENGTH:
                raise RconProtocolError(
                    f"Invalid packet length: {packet_length} (min {MIN_PACKET_LENGTH})"
                )
            if packet_length > MAX_PACKET_LENGTH:
                raise RconProtocolError(
                    f"Packet length {packet_length} exceeds max allowed ({MAX_PACKET_LENGTH})"
                )

            # Read packet body
            body = await reader.readexactly(packet_length)
            if not body.endswith(PADDING):
                raise RconProtocolError("Packet missing required double null terminator")

            request_id, raw_packet_type = struct.unpack("<ii", body[:8])
            raw_payload = body[8:-2]

            try:
                payload = raw_payload.decode(encoding)
            except UnicodeDecodeError:
                payload = raw_payload.decode(encoding, errors="replace")

            try:
                packet_type = PacketType(raw_packet_type)
            except ValueError:
                packet_type = raw_packet_type

            return RconPacket(
                request_id=request_id,
                packet_type=packet_type,
                payload=payload,
            )

        if timeout is not None:
            return await asyncio.wait_for(_read(), timeout=timeout)
        return await _read()

    except asyncio.TimeoutError as err:
        raise RconTimeoutError(f"RCON read operation timed out after {timeout} seconds") from err
    except asyncio.IncompleteReadError as err:
        raise RconConnectionError("Server disconnected unexpectedly during packet read") from err
    except ConnectionResetError as err:
        raise RconConnectionError("Connection reset by peer") from err
