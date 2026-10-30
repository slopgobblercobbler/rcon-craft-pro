"""Unit and integration tests for Click CLI subcommands."""

import json
from click.testing import CliRunner
import pytest

from rcon_craft.cli import cli
from tests.mock_server import ThreadedMockRconServer


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "rcon-craft-pro" in result.output
    assert "exec" in result.output
    assert "batch" in result.output
    assert "monitor" in result.output
    assert "profile" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "1.0.0" in result.output


def test_cli_profile_lifecycle(tmp_path):
    cfg_file = str(tmp_path / "servers.toml")
    runner = CliRunner()

    # Add profile
    res = runner.invoke(
        cli,
        [
            "profile",
            "add",
            "my_server",
            "-H",
            "192.168.1.50",
            "-P",
            "25575",
            "-w",
            "pass123",
            "--default",
            "-c",
            cfg_file,
        ],
    )
    assert res.exit_code == 0
    assert "Profile 'my_server' saved" in res.output

    # List profiles
    res = runner.invoke(cli, ["profile", "list", "-c", cfg_file])
    assert res.exit_code == 0
    assert "my_server" in res.output
    assert "192.168.1.50" in res.output

    # Set default
    res = runner.invoke(cli, ["profile", "default", "my_server", "-c", cfg_file])
    assert res.exit_code == 0
    assert "set as default" in res.output

    # Remove profile
    res = runner.invoke(cli, ["profile", "remove", "my_server", "-c", cfg_file])
    assert res.exit_code == 0
    assert "removed successfully" in res.output


@pytest.mark.asyncio
async def test_cli_exec_success(tmp_path):
    async with ThreadedMockRconServer(password="mypass") as server:
        server.register_command("say Test CLI", "§a[Server] Test CLI")

        runner = CliRunner()
        res = runner.invoke(
            cli,
            [
                "exec",
                "say",
                "Test",
                "CLI",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "mypass",
            ],
        )
        assert res.exit_code == 0
        assert "[Server] Test CLI" in res.output


@pytest.mark.asyncio
async def test_cli_exec_raw_and_no_color(tmp_path):
    async with ThreadedMockRconServer(password="mypass") as server:
        server.register_command("say Test Raw", "§cRed")

        runner = CliRunner()
        # With --no-color, colors are stripped
        res_no_color = runner.invoke(
            cli,
            [
                "exec",
                "say",
                "Test",
                "Raw",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "mypass",
                "--no-color",
            ],
        )
        assert res_no_color.exit_code == 0
        assert "Red" in res_no_color.output
        assert "\033[" not in res_no_color.output

        # With --raw, section sign preserved
        res_raw = runner.invoke(
            cli,
            [
                "exec",
                "say",
                "Test",
                "Raw",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "mypass",
                "--raw",
            ],
        )
        assert res_raw.exit_code == 0
        assert "§cRed" in res_raw.output


@pytest.mark.asyncio
async def test_cli_exec_auth_failure():
    async with ThreadedMockRconServer(password="mypass") as server:
        runner = CliRunner()
        res = runner.invoke(
            cli,
            [
                "exec",
                "help",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "wrong_pass",
            ],
        )
        assert res.exit_code != 0
        assert "Authentication failed" in res.output


@pytest.mark.asyncio
async def test_cli_profile_test_command(tmp_path):
    cfg_file = str(tmp_path / "servers.toml")
    async with ThreadedMockRconServer(password="mypass") as server:
        runner = CliRunner()

        # Add profile pointing to mock server
        runner.invoke(
            cli,
            [
                "profile",
                "add",
                "test_srv",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "mypass",
                "-c",
                cfg_file,
            ],
        )

        res = runner.invoke(cli, ["profile", "test", "test_srv", "-c", cfg_file])
        assert res.exit_code == 0
        assert "successful" in res.output


@pytest.mark.asyncio
async def test_cli_batch_command(tmp_path):
    cfg_file = str(tmp_path / "servers.toml")
    script = tmp_path / "commands.rcon"
    script.write_text("say ${MSG}\necho Done\n", encoding="utf-8")

    async with ThreadedMockRconServer(password="secret") as server:
        runner = CliRunner()
        res = runner.invoke(
            cli,
            [
                "batch",
                str(script),
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "secret",
                "--var",
                "MSG=HelloFromBatch",
                "--json",
            ],
        )
        assert res.exit_code == 0
        parsed = json.loads(res.output)
        assert parsed["successful_commands"] == 2
        assert parsed["failed_commands"] == 0


@pytest.mark.asyncio
async def test_cli_monitor_command(tmp_path):
    csv_file = str(tmp_path / "out.csv")
    async with ThreadedMockRconServer(password="secret") as server:
        server.register_command("tps", "TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0")
        server.register_command("list", "There are 1 of a max of 20 players online: Alex")

        runner = CliRunner()
        res = runner.invoke(
            cli,
            [
                "monitor",
                "-H",
                server.host,
                "-P",
                str(server.port),
                "-w",
                "secret",
                "-i",
                "0.01",
                "-n",
                "1",
                "--csv-out",
                csv_file,
            ],
        )
        assert res.exit_code == 0
        assert "TPS(1m):" in res.output
        assert "Alex" in res.output
