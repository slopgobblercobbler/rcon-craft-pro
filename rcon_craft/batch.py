"""Batch script runner for executing sequential Minecraft RCON command files."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from rcon_craft.client import RconClient
from rcon_craft.models import (
    BatchCommandResult,
    BatchExecutionError,
    BatchExecutionResult,
    RconError,
)

RE_VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)")


def substitute_variables(text: str, variables: Dict[str, str]) -> str:
    """Replaces ${VAR} and $VAR occurrences using the variables dictionary."""
    def _repl(m: re.Match) -> str:
        var_name = m.group(1) or m.group(2)
        return variables.get(var_name, m.group(0))

    return RE_VAR.sub(_repl, text)


class BatchRunner:
    """Executes a series of RCON commands from a file or text buffer."""

    def __init__(
        self,
        client: RconClient,
        delay_between_commands: float = 0.0,
        stop_on_error: bool = True,
        variables: Optional[Dict[str, str]] = None,
        on_progress: Optional[Callable[[BatchCommandResult], None]] = None,
    ) -> None:
        self.client = client
        self.delay = delay_between_commands
        self.stop_on_error = stop_on_error
        self.variables = variables or {}
        self.on_progress = on_progress

    async def run_file(self, script_path: Union[str, Path]) -> BatchExecutionResult:
        """Reads and executes commands from a script file (.rcon, .txt)."""
        path = Path(script_path)
        if not path.is_file():
            raise FileNotFoundError(f"Script file not found: {path}")

        content = path.read_text(encoding="utf-8")
        return await self.run_script(content, script_name=str(path))

    async def run_script(
        self, script_text: str, script_name: str = "<memory>"
    ) -> BatchExecutionResult:
        """Executes a script line by line with variable interpolation and delay control."""
        lines = script_text.splitlines()
        results: List[BatchCommandResult] = []
        start_time = time.time()
        last_response = ""

        total_lines = len(lines)
        aborted = False

        for line_idx, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            if aborted:
                results.append(
                    BatchCommandResult(
                        command=line,
                        line_number=line_idx,
                        status="SKIPPED",
                        error="Execution aborted after previous error",
                    )
                )
                continue

            # Interpolate variables
            command = substitute_variables(line, self.variables)

            # Handle directives
            parts = command.split(maxsplit=1)
            directive = parts[0].lower()

            if directive in ("sleep", "delay"):
                try:
                    sleep_sec = float(parts[1]) if len(parts) > 1 else 1.0
                    await asyncio.sleep(sleep_sec)
                    res = BatchCommandResult(
                        command=command,
                        line_number=line_idx,
                        status="SUCCESS",
                        response=f"Slept {sleep_sec}s",
                    )
                    results.append(res)
                    if self.on_progress:
                        self.on_progress(res)
                    continue
                except ValueError:
                    res = BatchCommandResult(
                        command=command,
                        line_number=line_idx,
                        status="ERROR",
                        error=f"Invalid sleep duration on line {line_idx}: {command}",
                    )
                    results.append(res)
                    if self.on_progress:
                        self.on_progress(res)
                    if self.stop_on_error:
                        aborted = True
                    continue

            if directive == "echo":
                msg = parts[1] if len(parts) > 1 else ""
                res = BatchCommandResult(
                    command=command,
                    line_number=line_idx,
                    status="SUCCESS",
                    response=msg,
                )
                results.append(res)
                if self.on_progress:
                    self.on_progress(res)
                continue

            if directive == "assert":
                expected_substr = parts[1] if len(parts) > 1 else ""
                if expected_substr not in last_response:
                    err_msg = (
                        f"Assertion failed at line {line_idx}: expected '{expected_substr}' "
                        f"in previous response ('{last_response}')"
                    )
                    res = BatchCommandResult(
                        command=command,
                        line_number=line_idx,
                        status="ERROR",
                        error=err_msg,
                    )
                    results.append(res)
                    if self.on_progress:
                        self.on_progress(res)
                    if self.stop_on_error:
                        aborted = True
                    continue
                else:
                    res = BatchCommandResult(
                        command=command,
                        line_number=line_idx,
                        status="SUCCESS",
                        response=f"Assertion passed: '{expected_substr}' matched",
                    )
                    results.append(res)
                    if self.on_progress:
                        self.on_progress(res)
                    continue

            # Execute RCON command
            cmd_start = time.perf_counter()
            try:
                # Strip leading slash if present (Minecraft server commands over RCON don't need '/')
                rcon_cmd = command.lstrip("/")
                response = await self.client.execute(rcon_cmd)
                cmd_duration_ms = (time.perf_counter() - cmd_start) * 1000.0
                last_response = response

                res = BatchCommandResult(
                    command=command,
                    line_number=line_idx,
                    status="SUCCESS",
                    response=response,
                    duration_ms=round(cmd_duration_ms, 2),
                )
                results.append(res)
                if self.on_progress:
                    self.on_progress(res)

            except (RconError, Exception) as err:
                cmd_duration_ms = (time.perf_counter() - cmd_start) * 1000.0
                res = BatchCommandResult(
                    command=command,
                    line_number=line_idx,
                    status="ERROR",
                    error=str(err),
                    duration_ms=round(cmd_duration_ms, 2),
                )
                results.append(res)
                if self.on_progress:
                    self.on_progress(res)
                if self.stop_on_error:
                    aborted = True

            # Apply delay between commands if configured
            if self.delay > 0 and line_idx < total_lines and not aborted:
                await asyncio.sleep(self.delay)

        total_duration = time.time() - start_time
        successful = sum(1 for r in results if r.status == "SUCCESS")
        failed = sum(1 for r in results if r.status == "ERROR")
        skipped = sum(1 for r in results if r.status == "SKIPPED")

        return BatchExecutionResult(
            script_path=script_name,
            total_commands=len(results),
            successful_commands=successful,
            failed_commands=failed,
            skipped_commands=skipped,
            results=results,
            total_duration_s=round(total_duration, 3),
        )
