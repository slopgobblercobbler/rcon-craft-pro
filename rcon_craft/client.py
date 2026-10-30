"""Asynchronous RCON client for Minecraft servers."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

from rcon_craft.models import (
    PacketType,
    RconAuthenticationError,
    RconConnectionError,
    RconPacket,
    RconTimeoutError,
    ServerProfile,
)
from rcon_craft.protocol import encode_packet, read_packet


class RconClient:
    """Async IO client implementing the Minecraft RCON protocol.

    Features:
        - Asynchronous connection and request handling using asyncio.
        - Full authentication lifecycle with failed attempt detection.
        - Multi-packet response reassembly for long outputs (>4096 bytes).
        - Streaming execution mode (`execute_stream`).
        - Context manager interface (`async with`).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25575,
        password: str = "",
        timeout: float = 5.0,
        encoding: str = "utf-8",
        multi_packet: bool = True,
        multi_packet_timeout: float = 0.05,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.encoding = encoding
        self.multi_packet = multi_packet
        self.multi_packet_timeout = multi_packet_timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_counter = 1
        self._authenticated = False
        self._lock = asyncio.Lock()

    @classmethod
    def from_profile(cls, profile: ServerProfile) -> RconClient:
        """Instantiates an RconClient from a ServerProfile."""
        return cls(
            host=profile.host,
            port=profile.port,
            password=profile.password,
            timeout=profile.timeout,
            multi_packet=profile.multi_packet,
        )

    @property
    def is_connected(self) -> bool:
        """Returns True if the client is currently connected."""
        return self._writer is not None and not self._writer.is_closing()

    @property
    def is_authenticated(self) -> bool:
        """Returns True if the client has successfully authenticated."""
        return self.is_connected and self._authenticated

    def _next_request_id(self) -> int:
        """Generates a sequential 31-bit positive request ID."""
        req_id = self._request_counter
        self._request_counter = (self._request_counter + 1) & 0x7FFFFFFF
        if self._request_counter == 0:
            self._request_counter = 1
        return req_id

    async def connect(self) -> None:
        """Opens a TCP connection to the Minecraft server."""
        if self.is_connected:
            return

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            self._authenticated = False
        except asyncio.TimeoutError as err:
            raise RconTimeoutError(
                f"Connection to {self.host}:{self.port} timed out after {self.timeout}s"
            ) from err
        except (OSError, ConnectionError) as err:
            raise RconConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {err}"
            ) from err

    async def authenticate(self, password: Optional[str] = None) -> bool:
        """Performs RCON authentication handshake.

        Raises:
            RconAuthenticationError: If the password is rejected by the server.
            RconConnectionError: If connection is broken.
            RconTimeoutError: If handshake times out.
        """
        if not self.is_connected:
            await self.connect()

        pw = self.password if password is None else password
        req_id = self._next_request_id()
        auth_packet = encode_packet(req_id, PacketType.SERVERDATA_AUTH, pw, self.encoding)

        assert self._writer is not None
        assert self._reader is not None

        try:
            self._writer.write(auth_packet)
            await self._writer.drain()

            # Read response. Some Bukkit/Spigot servers send an empty SERVERDATA_RESPONSE_VALUE
            # before the SERVERDATA_AUTH_RESPONSE packet.
            while True:
                response = await read_packet(self._reader, timeout=self.timeout, encoding=self.encoding)
                if response.packet_type == PacketType.SERVERDATA_RESPONSE_VALUE:
                    # Ignore Bukkit 0-type greeting / pre-auth bounce packet
                    continue
                break

            if response.request_id == -1:
                self._authenticated = False
                raise RconAuthenticationError(
                    f"Authentication failed for server {self.host}:{self.port} (bad password)"
                )

            if response.request_id != req_id:
                self._authenticated = False
                raise RconAuthenticationError(
                    f"Authentication error: expected request ID {req_id}, got {response.request_id}"
                )

            self._authenticated = True
            return True

        except (asyncio.IncompleteReadError, ConnectionResetError) as err:
            await self.close()
            raise RconConnectionError(f"Connection dropped during authentication: {err}") from err

    async def execute(self, command: str, auto_reconnect: bool = True) -> str:
        """Executes a command on the Minecraft server and returns the response string.

        Supports multi-packet reassembly for responses exceeding standard RCON packet size.
        """
        chunks = []
        async for chunk in self.execute_stream(command, auto_reconnect=auto_reconnect):
            chunks.append(chunk)
        return "".join(chunks)

    async def execute_stream(
        self, command: str, auto_reconnect: bool = True
    ) -> AsyncGenerator[str, None]:
        """Executes a command and yields response string chunks as they arrive.

        Useful for streaming output or handling large multi-packet outputs.
        """
        async with self._lock:
            if not self.is_authenticated:
                if auto_reconnect:
                    await self.connect()
                    await self.authenticate()
                else:
                    raise RconConnectionError("Not connected or authenticated to RCON server")

            assert self._writer is not None
            assert self._reader is not None

            req_id = self._next_request_id()
            packet_bytes = encode_packet(
                req_id, PacketType.SERVERDATA_EXECCOMMAND, command, self.encoding
            )

            try:
                self._writer.write(packet_bytes)
                await self._writer.drain()
            except (ConnectionError, OSError) as err:
                await self.close()
                raise RconConnectionError(f"Failed to send command to server: {err}") from err

            # Read the first response packet
            first_packet = await read_packet(
                self._reader, timeout=self.timeout, encoding=self.encoding
            )

            if first_packet.request_id != req_id:
                # Some servers might send an unexpected ID
                pass

            yield first_packet.payload

            if not self.multi_packet:
                return

            # Multi-packet detection & assembly:
            # If the payload is long (>= 4000 bytes) or more data is queued,
            # we read subsequent chunks until no further packets arrive within multi_packet_timeout.
            raw_len = len(first_packet.payload.encode(self.encoding))
            if raw_len >= 4000 or (
                hasattr(self._reader, "_buffer") and bool(self._reader._buffer)
            ):
                while True:
                    try:
                        next_packet = await read_packet(
                            self._reader,
                            timeout=self.multi_packet_timeout,
                            encoding=self.encoding,
                        )
                        if next_packet.request_id == req_id:
                            yield next_packet.payload
                        else:
                            break
                    except (RconTimeoutError, asyncio.TimeoutError):
                        # No more chunks waiting in the pipeline
                        break
                    except (RconConnectionError, ConnectionResetError):
                        break

    async def reconnect(self) -> None:
        """Closes the current session and re-establishes connection and authentication."""
        await self.close()
        await self.connect()
        await self.authenticate()

    async def close(self) -> None:
        """Closes the connection cleanly."""
        self._authenticated = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            finally:
                self._writer = None
                self._reader = None

    async def __aenter__(self) -> RconClient:
        await self.connect()
        await self.authenticate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
