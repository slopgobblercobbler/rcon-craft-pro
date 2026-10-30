"""Command Line Interface (CLI) for rcon-craft-pro."""

from __future__ import annotations

import asyncio
import json
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table

from rcon_craft.batch import BatchRunner
from rcon_craft.client import RconClient
from rcon_craft.colors import minecraft_to_ansi, strip_minecraft_formatting
from rcon_craft.config import (
    add_profile,
    get_profile,
    load_config,
    remove_profile,
    save_config,
)
from rcon_craft.models import (
    BatchExecutionResult,
    ConfigError,
    MonitorMetrics,
    RconAuthenticationError,
    RconConnectionError,
    RconError,
    ServerProfile,
)
from rcon_craft.monitor import ServerMonitor
from rcon_craft.repl import InteractiveREPL

console = Console()


def coro(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to run an async click command with asyncio.run()."""
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(f(*args, **kwargs)))
                return future.result()
        else:
            return asyncio.run(f(*args, **kwargs))

    return wrapper


def resolve_connection_parameters(
    profile_name: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
    timeout: Optional[float] = None,
    config_path: Optional[str] = None,
    no_color: bool = False,
) -> Tuple[ServerProfile, bool]:
    """Resolves server configuration from command-line overrides, profiles, or environment."""
    profile: Optional[ServerProfile] = None

    try:
        profile = get_profile(profile_name, config_path=config_path)
    except ConfigError:
        if profile_name:
            raise
        # Fallback to local default if no profile exists
        profile = ServerProfile(name="cli-direct")

    # Command-line options override profile values
    if host:
        profile.host = host
    if port:
        profile.port = port
    if password is not None:
        profile.password = password
    if timeout:
        profile.timeout = timeout

    use_color = (not no_color) and profile.color
    return profile, use_color


# Global click group
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version="1.0.0", prog_name="rcon-craft-pro")
def cli() -> None:
    """rcon-craft-pro: Advanced async Minecraft Server RCON administration tool."""
    pass


@cli.command(name="exec")
@click.argument("command", nargs=-1, required=True)
@click.option("-p", "--profile", help="Named server profile from config")
@click.option("-H", "--host", help="Server hostname or IP")
@click.option("-P", "--port", type=int, help="Server RCON port (default 25575)")
@click.option("-w", "--password", help="RCON password")
@click.option("-t", "--timeout", type=float, help="Connection/command timeout in seconds")
@click.option("--no-color", is_flag=True, help="Disable Minecraft color translation")
@click.option("--raw", is_flag=True, help="Output raw response without stripping or formatting")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
@coro
async def exec_cmd(
    command: Tuple[str, ...],
    profile: Optional[str],
    host: Optional[str],
    port: Optional[int],
    password: Optional[str],
    timeout: Optional[float],
    no_color: bool,
    raw: bool,
    config: Optional[str],
) -> None:
    """Execute a single command on the Minecraft server."""
    full_cmd = " ".join(command).lstrip("/")
    prof, use_color = resolve_connection_parameters(
        profile, host, port, password, timeout, config, no_color
    )

    client = RconClient.from_profile(prof)
    try:
        async with client:
            response = await client.execute(full_cmd)
            if raw:
                sys.stdout.write(response + "\n")
            elif not use_color:
                sys.stdout.write(strip_minecraft_formatting(response) + "\n")
            else:
                sys.stdout.write(minecraft_to_ansi(response) + "\n")
    except RconError as err:
        console.print(f"[bold red]RCON Error:[/bold red] {err}", style="red")
        sys.exit(1)


@cli.command(name="repl")
@click.option("-p", "--profile", help="Named server profile from config")
@click.option("-H", "--host", help="Server hostname or IP")
@click.option("-P", "--port", type=int, help="Server RCON port (default 25575)")
@click.option("-w", "--password", help="RCON password")
@click.option("-t", "--timeout", type=float, help="Connection/command timeout in seconds")
@click.option("--no-color", is_flag=True, help="Disable Minecraft color translation")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
@coro
async def repl_cmd(
    profile: Optional[str],
    host: Optional[str],
    port: Optional[int],
    password: Optional[str],
    timeout: Optional[float],
    no_color: bool,
    config: Optional[str],
) -> None:
    """Start an interactive RCON shell with autocompletion and syntax hints."""
    prof, use_color = resolve_connection_parameters(
        profile, host, port, password, timeout, config, no_color
    )

    client = RconClient.from_profile(prof)
    try:
        await client.connect()
        await client.authenticate()
    except RconError as err:
        console.print(f"[bold red]Connection failed:[/bold red] {err}")
        sys.exit(1)

    repl = InteractiveREPL(client, profile_name=prof.name, color=use_color)
    try:
        await repl.run()
    finally:
        await client.close()


@cli.command(name="batch")
@click.argument("script_file", type=click.Path(exists=True, readable=True))
@click.option("-p", "--profile", help="Named server profile from config")
@click.option("-H", "--host", help="Server hostname or IP")
@click.option("-P", "--port", type=int, help="Server RCON port (default 25575)")
@click.option("-w", "--password", help="RCON password")
@click.option("-d", "--delay", type=float, default=0.0, help="Delay between commands in seconds")
@click.option("--stop-on-error/--continue-on-error", default=True, help="Stop execution on error")
@click.option("--var", "vars_list", multiple=True, help="Variables in KEY=VALUE format")
@click.option("--json", "json_output", is_flag=True, help="Output results as JSON")
@click.option("--no-color", is_flag=True, help="Disable color formatting")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
@coro
async def batch_cmd(
    script_file: str,
    profile: Optional[str],
    host: Optional[str],
    port: Optional[int],
    password: Optional[str],
    delay: float,
    stop_on_error: bool,
    vars_list: Tuple[str, ...],
    json_output: bool,
    no_color: bool,
    config: Optional[str],
) -> None:
    """Execute a batch script file containing RCON commands sequentially."""
    prof, use_color = resolve_connection_parameters(
        profile, host, port, password, None, config, no_color
    )

    variables: Dict[str, str] = {}
    for var in vars_list:
        if "=" in var:
            k, v = var.split("=", 1)
            variables[k.strip()] = v.strip()

    client = RconClient.from_profile(prof)

    def on_progress(cmd_result):
        if not json_output:
            if cmd_result.status == "SUCCESS":
                console.print(
                    f"  [green]✔[/green] Line {cmd_result.line_number}: [bold]{cmd_result.command}[/bold]"
                )
                if cmd_result.response:
                    resp = (
                        minecraft_to_ansi(cmd_result.response)
                        if use_color
                        else strip_minecraft_formatting(cmd_result.response)
                    )
                    console.print(f"    {resp}")
            elif cmd_result.status == "ERROR":
                console.print(
                    f"  [red]✖[/red] Line {cmd_result.line_number}: [bold]{cmd_result.command}[/bold] - [red]{cmd_result.error}[/red]"
                )

    runner = BatchRunner(
        client=client,
        delay_between_commands=delay,
        stop_on_error=stop_on_error,
        variables=variables,
        on_progress=on_progress,
    )

    try:
        async with client:
            result = await runner.run_file(script_file)
    except Exception as err:
        console.print(f"[bold red]Batch Runner Failure:[/bold red] {err}")
        sys.exit(1)

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        console.print(
            f"\n[bold]Batch Summary:[/bold] {result.successful_commands} succeeded, "
            f"{result.failed_commands} failed, {result.skipped_commands} skipped "
            f"in {result.total_duration_s:.2f}s"
        )

    if result.failed_commands > 0:
        sys.exit(1)


@cli.command(name="monitor")
@click.option("-p", "--profile", help="Named server profile from config")
@click.option("-H", "--host", help="Server hostname or IP")
@click.option("-P", "--port", type=int, help="Server RCON port (default 25575)")
@click.option("-w", "--password", help="RCON password")
@click.option("-i", "--interval", type=float, default=5.0, help="Polling interval in seconds")
@click.option("-n", "--iterations", type=int, default=None, help="Maximum number of polling cycles")
@click.option("--alert-tps", type=float, default=18.0, help="Alert when 1m TPS drops below this")
@click.option("--alert-players", type=int, default=None, help="Alert when player count exceeds this")
@click.option("--csv-out", type=click.Path(), help="Append metrics to CSV file")
@click.option("--jsonl-out", type=click.Path(), help="Append metrics to JSON Lines file")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
@coro
async def monitor_cmd(
    profile: Optional[str],
    host: Optional[str],
    port: Optional[int],
    password: Optional[str],
    interval: float,
    iterations: Optional[int],
    alert_tps: Optional[float],
    alert_players: Optional[int],
    csv_out: Optional[str],
    jsonl_out: Optional[str],
    config: Optional[str],
) -> None:
    """Headless monitoring mode: periodically poll TPS, players, and log alerts."""
    prof, _ = resolve_connection_parameters(
        profile, host, port, password, None, config, no_color=False
    )
    client = RconClient.from_profile(prof)

    def on_metrics(m: MonitorMetrics) -> None:
        tps_str = f"{m.tps_1m:.2f}" if m.tps_1m is not None else "N/A"
        time_str = m.timestamp.strftime("%H:%M:%S")
        players_str = f"{m.players_online}/{m.players_max}"
        names = f" ({', '.join(m.player_names)})" if m.player_names else ""
        console.print(
            f"[{time_str}] [cyan]TPS(1m):[/cyan] [bold]{tps_str}[/bold] | "
            f"[cyan]Players:[/cyan] [bold]{players_str}[/bold]{names}"
        )

    def on_alert(msg: str, m: MonitorMetrics) -> None:
        console.print(f"[bold red]>>> ALERT: {msg}[/bold red]")

    monitor = ServerMonitor(
        client=client,
        interval=interval,
        alert_tps_below=alert_tps,
        alert_players_above=alert_players,
        csv_file=csv_out,
        jsonl_file=jsonl_out,
        on_metrics=on_metrics,
        on_alert=on_alert,
    )

    try:
        async with client:
            console.print(f"[green]Starting monitoring for {prof.host}:{prof.port} (interval {interval}s)...[/green]")
            await monitor.run_loop(max_iterations=iterations)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("[yellow]Monitoring stopped by user.[/yellow]")
    except Exception as err:
        console.print(f"[bold red]Monitoring error:[/bold red] {err}")
        sys.exit(1)


@cli.group(name="profile")
def profile_group() -> None:
    """Manage multi-server connection profiles."""
    pass


@profile_group.command(name="list")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
def profile_list(config: Optional[str]) -> None:
    """List all configured server profiles."""
    profiles, default_server = load_config(config)
    if not profiles:
        console.print("No profiles found.")
        return

    table = Table(title="Server Profiles")
    table.add_column("Profile", style="cyan", no_wrap=True)
    table.add_column("Host", style="magenta")
    table.add_column("Port", style="green")
    table.add_column("Default", style="yellow")
    table.add_column("Timeout", style="blue")

    for name, p in profiles.items():
        is_default = "★ Yes" if name == default_server else "No"
        table.add_row(name, p.host, str(p.port), is_default, f"{p.timeout}s")

    console.print(table)


@profile_group.command(name="add")
@click.argument("name")
@click.option("-H", "--host", default="127.0.0.1", help="Server hostname or IP")
@click.option("-P", "--port", type=int, default=25575, help="RCON port")
@click.option("-w", "--password", default="", help="RCON password (can use env:VAR)")
@click.option("-t", "--timeout", type=float, default=5.0, help="Timeout in seconds")
@click.option("--default", "set_default", is_flag=True, help="Set as default profile")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
def profile_add(
    name: str,
    host: str,
    port: int,
    password: str,
    timeout: float,
    set_default: bool,
    config: Optional[str],
) -> None:
    """Add or update a server profile."""
    prof = ServerProfile(
        name=name,
        host=host,
        port=port,
        password=password,
        timeout=timeout,
    )
    saved_path = add_profile(prof, set_as_default=set_default, config_path=config)
    console.print(f"[green]Profile '{name}' saved to {saved_path}[/green]")


@profile_group.command(name="remove")
@click.argument("name")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
def profile_remove(name: str, config: Optional[str]) -> None:
    """Remove a server profile."""
    removed = remove_profile(name, config_path=config)
    if removed:
        console.print(f"[green]Profile '{name}' removed successfully.[/green]")
    else:
        console.print(f"[red]Profile '{name}' not found.[/red]")
        sys.exit(1)


@profile_group.command(name="test")
@click.argument("name", required=False)
@click.option("-c", "--config", help="Custom path to servers.toml config file")
@coro
async def profile_test(name: Optional[str], config: Optional[str]) -> None:
    """Test connection and authentication for a profile."""
    try:
        prof = get_profile(name, config_path=config)
    except ConfigError as err:
        console.print(f"[red]{err}[/red]")
        sys.exit(1)

    console.print(f"Testing connection to [cyan]{prof.name}[/cyan] ({prof.host}:{prof.port})...")
    client = RconClient.from_profile(prof)
    try:
        async with client:
            # Run quick ping/command
            response = await client.execute("help")
            console.print(f"[green]✔ Connection & authentication successful![/green]")
    except RconAuthenticationError:
        console.print("[red]✖ Authentication failed: Invalid RCON password[/red]")
        sys.exit(1)
    except RconConnectionError as err:
        console.print(f"[red]✖ Connection failed: {err}[/red]")
        sys.exit(1)
    except Exception as err:
        console.print(f"[red]✖ Unexpected error: {err}[/red]")
        sys.exit(1)


@profile_group.command(name="default")
@click.argument("name")
@click.option("-c", "--config", help="Custom path to servers.toml config file")
def profile_set_default(name: str, config: Optional[str]) -> None:
    """Set the default server profile."""
    profiles, _ = load_config(config)
    if name not in profiles:
        console.print(f"[red]Profile '{name}' not found.[/red]")
        sys.exit(1)
    save_config(profiles, default_server=name, path=config)
    console.print(f"[green]Profile '{name}' set as default.[/green]")


def main() -> None:
    """Main CLI entrypoint."""
    cli()


if __name__ == "__main__":
    main()
