"""Mock asynchronous Minecraft RCON server for unit and integration testing."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, Dict, List, Optional, Union

from rcon_craft.models import PacketType
from rcon_craft.protocol import encode_packet, read_packet


class MockRconServer:
    """Mock TCP RCON Server that strictly implements the Minecraft RCON protocol."""

    def __init__(
        self,
        password: str = "correct_password",
        host: str = "127.0.0.1",
        port: int = 0,  # 0 binds to a random available port
    ) -> None:
        self.password = password
        self.host = host
        self.port = port
        self.server: Optional[asyncio.AbstractServer] = None
        self.handlers: Dict[str, Union[str, List[str], Callable[[str], Union[str, List[str]]]]] = {}

        # Chaos testing knobs
        self.send_spigot_dummy_packet = False
        self.simulate_auth_hang = False
        self.simulate_cmd_hang = False
        self.disconnect_on_command = False
        self.send_corrupt_null_bytes = False
        self.send_negative_auth_id = True

        # Recorded interactions
        self.received_commands: List[str] = []
        self.active_connections = 0

    def register_command(
        self, command: str, response: Union[str, List[str], Callable[[str], Union[str, List[str]]]]
    ) -> None:
        """Registers a predefined command handler."""
        self.handlers[command.lower().strip()] = response

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.active_connections += 1
        is_authenticated = False

        try:
            while True:
                try:
                    packet = await read_packet(reader, timeout=2.0)
                except (asyncio.IncompleteReadError, ConnectionResetError):
                    break

                # 1. AUTHENTICATION HANDSHAKE
                if packet.packet_type == PacketType.SERVERDATA_AUTH:
                    if self.simulate_auth_hang:
                        await asyncio.sleep(5.0)

                    if self.send_spigot_dummy_packet:
                        # Some Bukkit versions send an empty type 0 packet before type 2
                        dummy = encode_packet(0, PacketType.SERVERDATA_RESPONSE_VALUE, "")
                        writer.write(dummy)
                        await writer.drain()

                    if packet.payload == self.password:
                        is_authenticated = True
                        res = encode_packet(
                            packet.request_id,
                            PacketType.SERVERDATA_AUTH_RESPONSE,
                            "",
                        )
                    else:
                        is_authenticated = False
                        res_id = -1 if self.send_negative_auth_id else 9999
                        res = encode_packet(
                            res_id,
                            PacketType.SERVERDATA_AUTH_RESPONSE,
                            "",
                        )

                    writer.write(res)
                    await writer.drain()

                # 2. COMMAND EXECUTION
                elif packet.packet_type == PacketType.SERVERDATA_EXECCOMMAND:
                    if not is_authenticated:
                        # Unauthenticated command
                        res = encode_packet(
                            packet.request_id,
                            PacketType.SERVERDATA_RESPONSE_VALUE,
                            "You must authenticate first!",
                        )
                        writer.write(res)
                        await writer.drain()
                        continue

                    if self.disconnect_on_command:
                        writer.close()
                        await writer.wait_closed()
                        break

                    if self.simulate_cmd_hang:
                        await asyncio.sleep(5.0)

                    cmd = packet.payload.strip()
                    self.received_commands.append(cmd)
                    cmd_key = cmd.lower()

                    # Find handler or default echo
                    if cmd_key in self.handlers:
                        handler_val = self.handlers[cmd_key]
                        if callable(handler_val):
                            handler_val = handler_val(cmd)
                    else:
                        handler_val = f"Executed: {cmd}"

                    # Handle multi-packet response or single packet response
                    if isinstance(handler_val, list):
                        for chunk in handler_val:
                            pkt = encode_packet(
                                packet.request_id,
                                PacketType.SERVERDATA_RESPONSE_VALUE,
                                chunk,
                            )
                            writer.write(pkt)
                            await writer.drain()
                            # brief yield to test chunked streaming
                            await asyncio.sleep(0.001)
                    else:
                        if self.send_corrupt_null_bytes:
                            # Send corrupt trailing null bytes
                            raw = encode_packet(
                                packet.request_id,
                                PacketType.SERVERDATA_RESPONSE_VALUE,
                                handler_val,
                            )
                            # Corrupt the last byte
                            writer.write(raw[:-1] + b"\xFF")
                        else:
                            pkt = encode_packet(
                                packet.request_id,
                                PacketType.SERVERDATA_RESPONSE_VALUE,
                                handler_val,
                            )
                            writer.write(pkt)
                        await writer.drain()

                # Unknown packet type
                else:
                    err_pkt = encode_packet(
                        packet.request_id,
                        PacketType.SERVERDATA_RESPONSE_VALUE,
                        f"Unknown request {packet.packet_type}",
                    )
                    writer.write(err_pkt)
                    await writer.drain()

        except Exception:
            pass
        finally:
            self.active_connections -= 1
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> int:
        """Starts the mock server and returns the listening port."""
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        # Extract bound port
        sockets = self.server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        """Stops the mock server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def __aenter__(self) -> MockRconServer:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()


class ThreadedMockRconServer:
    """Threaded wrapper around MockRconServer for synchronous Click CliRunner tests."""

    def __init__(self, **kwargs) -> None:
        self.mock = MockRconServer(**kwargs)
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def host(self) -> str:
        return self.mock.host

    @property
    def port(self) -> int:
        return self.mock.port

    def register_command(
        self, command: str, response: Union[str, List[str], Callable[[str], Union[str, List[str]]]]
    ) -> None:
        self.mock.register_command(command, response)

    def start(self) -> int:
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run() -> None:
            assert self.loop is not None
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.mock.start())
            ready.set()
            try:
                self.loop.run_forever()
            finally:
                try:
                    self.loop.run_until_complete(self.mock.stop())
                except Exception:
                    pass
                try:
                    self.loop.close()
                except Exception:
                    pass

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(timeout=5.0)
        return self.port

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread:
                self.thread.join(timeout=3.0)

    def __enter__(self) -> ThreadedMockRconServer:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    async def __aenter__(self) -> ThreadedMockRconServer:
        self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

