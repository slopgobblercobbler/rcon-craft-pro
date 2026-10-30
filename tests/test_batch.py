"""Unit and integration tests for the batch script runner."""

import pytest

from rcon_craft.batch import BatchRunner, substitute_variables
from rcon_craft.client import RconClient
from tests.mock_server import MockRconServer


def test_substitute_variables():
    vars_dict = {"PLAYER": "Steve", "WORLD": "world_nether", "COUNT": "64"}
    text = "give ${PLAYER} diamond $COUNT in ${WORLD}"
    result = substitute_variables(text, vars_dict)
    assert result == "give Steve diamond 64 in world_nether"


@pytest.mark.asyncio
async def test_batch_runner_success(tmp_path):
    async with MockRconServer(password="secret") as server:
        server.register_command("say Welcome to the server!", "Welcome broadcast sent")
        server.register_command("give Steve diamond 5", "Gave 5 diamond to Steve")

        script_content = """
        # Setup test server
        // Initial broadcast
        echo Starting batch setup...
        sleep 0.01
        say Welcome to the server!
        assert broadcast sent
        give ${TARGET} diamond ${AMOUNT}
        assert Gave 5 diamond
        """
        script_file = tmp_path / "setup.rcon"
        script_file.write_text(script_content, encoding="utf-8")

        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            progress_events = []
            runner = BatchRunner(
                client=client,
                delay_between_commands=0.01,
                variables={"TARGET": "Steve", "AMOUNT": "5"},
                on_progress=lambda res: progress_events.append(res),
            )

            exec_result = await runner.run_file(script_file)

            assert exec_result.failed_commands == 0
            assert exec_result.successful_commands == 6
            assert exec_result.skipped_commands == 0
            assert len(progress_events) == 6
            assert exec_result.results[2].command == "say Welcome to the server!"
            assert "Welcome broadcast sent" in exec_result.results[2].response


@pytest.mark.asyncio
async def test_batch_runner_stop_on_error(tmp_path):
    async with MockRconServer(password="secret") as server:
        server.register_command("cmd1", "OK1")
        # cmd2 will fail assertion

        script_content = """
        cmd1
        assert FAIL_ASSERTION
        cmd3_should_be_skipped
        """
        script_file = tmp_path / "abort.rcon"
        script_file.write_text(script_content, encoding="utf-8")

        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            runner = BatchRunner(client=client, stop_on_error=True)
            result = await runner.run_file(script_file)

            assert result.successful_commands == 1  # cmd1
            assert result.failed_commands == 1      # assert FAIL_ASSERTION
            assert result.skipped_commands == 1     # cmd3
            assert result.results[1].status == "ERROR"
            assert result.results[2].status == "SKIPPED"


@pytest.mark.asyncio
async def test_batch_runner_continue_on_error(tmp_path):
    async with MockRconServer(password="secret") as server:
        server.register_command("cmd1", "OK1")
        server.register_command("cmd3", "OK3")

        script_content = """
        cmd1
        assert NON_EXISTENT
        cmd3
        """
        script_file = tmp_path / "continue.rcon"
        script_file.write_text(script_content, encoding="utf-8")

        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            runner = BatchRunner(client=client, stop_on_error=False)
            result = await runner.run_file(script_file)

            assert result.successful_commands == 2  # cmd1, cmd3
            assert result.failed_commands == 1      # assert NON_EXISTENT
            assert result.skipped_commands == 0


@pytest.mark.asyncio
async def test_batch_runner_invalid_sleep():
    async with MockRconServer(password="secret") as server:
        script = "sleep not_a_number\ncmd1"
        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            runner = BatchRunner(client=client, stop_on_error=True)
            res = await runner.run_script(script)
            assert res.failed_commands == 1
            assert "Invalid sleep duration" in res.results[0].error
            assert res.skipped_commands == 1


@pytest.mark.asyncio
async def test_batch_runner_missing_file():
    async with MockRconServer(password="secret") as server:
        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            runner = BatchRunner(client=client)
            with pytest.raises(FileNotFoundError):
                await runner.run_file("non_existent_file_xyz.rcon")
