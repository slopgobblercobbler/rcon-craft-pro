"""Integration tests for RconClient using MockRconServer."""

import asyncio
import pytest

from rcon_craft.client import RconClient
from rcon_craft.models import (
    RconAuthenticationError,
    RconConnectionError,
    RconTimeoutError,
    ServerProfile,
)
from tests.mock_server import MockRconServer


@pytest.mark.asyncio
async def test_client_connect_and_authenticate():
    """Verify clean connection and authentication with correct credentials."""
    async with MockRconServer(password="secret123") as server:
        client = RconClient(host=server.host, port=server.port, password="secret123")
        assert not client.is_connected
        assert not client.is_authenticated

        await client.connect()
        assert client.is_connected
        assert not client.is_authenticated

        auth_ok = await client.authenticate()
        assert auth_ok is True
        assert client.is_authenticated

        await client.close()
        assert not client.is_connected
        assert not client.is_authenticated


@pytest.mark.asyncio
async def test_client_context_manager():
    """Verify async context manager automatically connects and authenticates."""
    async with MockRconServer(password="secret123") as server:
        async with RconClient(host=server.host, port=server.port, password="secret123") as client:
            assert client.is_connected
            assert client.is_authenticated
            resp = await client.execute("help")
            assert "Executed: help" in resp
        assert not client.is_connected


@pytest.mark.asyncio
async def test_client_authentication_failure():
    """Verify authentication failure raises RconAuthenticationError."""
    async with MockRconServer(password="correct_password") as server:
        client = RconClient(host=server.host, port=server.port, password="wrong_password")
        with pytest.raises(RconAuthenticationError, match="bad password"):
            await client.connect()
            await client.authenticate()
        assert not client.is_authenticated
        await client.close()


@pytest.mark.asyncio
async def test_client_spigot_dummy_packet():
    """Verify that Spigot's pre-auth dummy type-0 packet is cleanly ignored."""
    async with MockRconServer(password="spigot_pw") as server:
        server.send_spigot_dummy_packet = True

        async with RconClient(host=server.host, port=server.port, password="spigot_pw") as client:
            assert client.is_authenticated
            resp = await client.execute("version")
            assert "Executed: version" in resp


@pytest.mark.asyncio
async def test_client_single_command():
    """Verify command execution and response matching."""
    async with MockRconServer(password="pw") as server:
        server.register_command("say Hello World", "§b[Server] Hello World")

        async with RconClient(host=server.host, port=server.port, password="pw") as client:
            resp = await client.execute("say Hello World")
            assert resp == "§b[Server] Hello World"


@pytest.mark.asyncio
async def test_client_multi_packet_assembly():
    """Verify reassembling a long response split across multiple packets."""
    async with MockRconServer(password="pw") as server:
        # Simulate a 10KB response split into three packets
        chunk1 = "A" * 4096
        chunk2 = "B" * 4096
        chunk3 = "C" * 2000
        server.register_command("huge_command", [chunk1, chunk2, chunk3])

        async with RconClient(
            host=server.host,
            port=server.port,
            password="pw",
            multi_packet=True,
            multi_packet_timeout=0.05,
        ) as client:
            response = await client.execute("huge_command")
            assert len(response) == 4096 + 4096 + 2000
            assert response.startswith("AAAA")
            assert "BBBB" in response
            assert response.endswith("CCCC")


@pytest.mark.asyncio
async def test_client_streaming_chunks():
    """Verify execute_stream yields chunks sequentially."""
    async with MockRconServer(password="pw") as server:
        chunks = ["chunk_one_" * 400, "chunk_two_" * 400]
        server.register_command("stream_cmd", chunks)

        async with RconClient(
            host=server.host,
            port=server.port,
            password="pw",
            multi_packet=True,
            multi_packet_timeout=0.05,
        ) as client:
            received_chunks = []
            async for piece in client.execute_stream("stream_cmd"):
                received_chunks.append(piece)

            assert len(received_chunks) == 2
            assert received_chunks[0] == chunks[0]
            assert received_chunks[1] == chunks[1]


@pytest.mark.asyncio
async def test_client_reconnect():
    """Verify reconnecting after closing or connection reset."""
    async with MockRconServer(password="pw") as server:
        client = RconClient(host=server.host, port=server.port, password="pw")
        await client.connect()
        await client.authenticate()
        assert client.is_authenticated

        await client.reconnect()
        assert client.is_authenticated
        resp = await client.execute("time set day")
        assert "Executed: time set day" in resp
        await client.close()


@pytest.mark.asyncio
async def test_client_connection_refused():
    """Verify handling connection to an unavailable port."""
    client = RconClient(host="127.0.0.1", port=1, timeout=0.5)
    with pytest.raises(RconConnectionError):
        await client.connect()


@pytest.mark.asyncio
async def test_client_timeout():
    """Verify timeout when server hangs on response."""
    async with MockRconServer(password="pw") as server:
        server.simulate_cmd_hang = True
        client = RconClient(host=server.host, port=server.port, password="pw", timeout=0.1)
        await client.connect()
        await client.authenticate()

        with pytest.raises(RconTimeoutError):
            await client.execute("hang_cmd")
        await client.close()


@pytest.mark.asyncio
async def test_client_disconnect_during_command():
    """Verify clean error when server abruptly drops socket."""
    async with MockRconServer(password="pw") as server:
        server.disconnect_on_command = True
        async with RconClient(host=server.host, port=server.port, password="pw") as client:
            with pytest.raises(RconConnectionError):
                await client.execute("drop_me")


@pytest.mark.asyncio
async def test_client_from_profile():
    """Verify instantiating client from ServerProfile dataclass."""
    profile = ServerProfile(
        name="test_prof",
        host="127.0.0.1",
        port=25575,
        password="test_password",
        timeout=8.0,
        multi_packet=True,
    )
    client = RconClient.from_profile(profile)
    assert client.host == "127.0.0.1"
    assert client.port == 25575
    assert client.password == "test_password"
    assert client.timeout == 8.0
    assert client.multi_packet is True
