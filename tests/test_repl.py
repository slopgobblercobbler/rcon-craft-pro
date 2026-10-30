"""Unit tests for the Interactive REPL shell and meta-command handlers."""

import pytest

from rcon_craft.client import RconClient
from rcon_craft.repl import BUILTIN_COMMANDS, InteractiveREPL
from tests.mock_server import MockRconServer


def test_builtin_commands_list():
    assert "help" in BUILTIN_COMMANDS
    assert "say" in BUILTIN_COMMANDS
    assert ":help" in BUILTIN_COMMANDS
    assert ":quit" in BUILTIN_COMMANDS


@pytest.mark.asyncio
async def test_repl_meta_commands():
    async with MockRconServer(password="secret") as server:
        server.register_command("tps", "TPS: 20.0")
        server.register_command("list", "There are 0 of a max of 20 players online.")

        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            repl = InteractiveREPL(client, profile_name="test_shell")

            # :help
            assert await repl._handle_meta_command(":help") is True

            # :server
            assert await repl._handle_meta_command(":server") is True

            # :stats
            assert await repl._handle_meta_command(":stats") is True

            # :clear
            assert await repl._handle_meta_command(":clear") is True

            # unknown
            assert await repl._handle_meta_command(":unknown_foo") is True

            # :quit and :exit return False (signal loop to break)
            assert await repl._handle_meta_command(":quit") is False
            assert await repl._handle_meta_command(":exit") is False


def test_repl_banner_and_help(capsys):
    client = RconClient(host="127.0.0.1", port=25575)
    repl = InteractiveREPL(client, profile_name="test_shell")

    repl.print_banner()
    out, _ = capsys.readouterr()
    assert "RCON-CRAFT-PRO" in out
    assert "test_shell" in out

    repl.print_help()
    out, _ = capsys.readouterr()
    assert "Shell Meta-Commands" in out
