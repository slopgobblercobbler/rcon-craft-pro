"""Interactive terminal REPL with autocompletion, history, and syntax hints."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from rcon_craft.client import RconClient
from rcon_craft.colors import minecraft_to_ansi
from rcon_craft.models import RconAuthenticationError, RconConnectionError, ServerProfile

DEFAULT_HISTORY_FILE = Path.home() / ".rcon-craft-history"

BUILTIN_COMMANDS = [
    "advancement", "ban", "ban-ip", "banlist", "bossbar", "clear",
    "clone", "data", "datapack", "debug", "defaultgamemode", "deop",
    "difficulty", "effect", "enchant", "execute", "experience", "fill",
    "forceload", "function", "gamemode", "gamerule", "give", "help",
    "item", "kick", "kill", "list", "locate", "loot", "me", "msg",
    "op", "pardon", "pardon-ip", "particle", "playsound", "recipe",
    "reload", "save-all", "save-off", "save-on", "say", "schedule",
    "scoreboard", "seed", "setblock", "setworldspawn", "spawnpoint",
    "spectate", "spreadplayers", "stop", "summon", "tag", "team",
    "teammsg", "teleport", "tell", "tellraw", "time", "title", "tm",
    "tp", "tps", "trigger", "weather", "whitelist", "worldborder", "xp",
    # Local REPL meta-commands
    ":help", ":exit", ":quit", ":clear", ":stats", ":status", ":server",
]

REPL_STYLE = Style.from_dict({
    "prompt": "#00aa00 bold",
    "server": "#55ffff bold",
    "bracket": "#aaaaaa",
})


class InteractiveREPL:
    """Provides a rich interactive shell for executing Minecraft RCON commands."""

    def __init__(
        self,
        client: RconClient,
        profile_name: Optional[str] = None,
        history_file: Optional[Path] = None,
        color: bool = True,
    ) -> None:
        self.client = client
        self.profile_name = profile_name or f"{client.host}:{client.port}"
        self.history_file = history_file or DEFAULT_HISTORY_FILE
        self.color = color
        self.commands: List[str] = list(BUILTIN_COMMANDS)
        self._session: Optional[PromptSession] = None

    def _setup_session(self) -> PromptSession:
        completer = WordCompleter(self.commands, ignore_case=True, sentence=True)
        return PromptSession(
            history=FileHistory(str(self.history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=completer,
        )

    def print_banner(self) -> None:
        banner = (
            f"\033[1;32m=== RCON-CRAFT-PRO Interactive Shell ===\033[0m\n"
            f"Connected to: \033[1;36m{self.client.host}:{self.client.port}\033[0m "
            f"(Profile: \033[1;33m{self.profile_name}\033[0m)\n"
            f"Type \033[1;37m:help\033[0m for shell commands, \033[1;37m:quit\033[0m or \033[1;37mCtrl+D\033[0m to exit.\n"
        )
        print(banner)

    def print_help(self) -> None:
        help_text = (
            "\n\033[1;36mShell Meta-Commands:\033[0m\n"
            "  \033[1;33m:help\033[0m              Show this help message\n"
            "  \033[1;33m:clear\033[0m             Clear terminal screen\n"
            "  \033[1;33m:server\033[0m            Display current connection profile info\n"
            "  \033[1;33m:stats\033[0m / \033[1;33m:status\033[0m   Query TPS and online players\n"
            "  \033[1;33m:quit\033[0m / \033[1;33m:exit\033[0m      Close session and return to OS\n\n"
            "\033[1;36mMinecraft Commands:\033[0m\n"
            "  Type any Minecraft command directly (e.g. 'list', 'say Hello', 'time set day').\n"
            "  Leading slashes ('/') are optional.\n"
        )
        print(help_text)

    async def _handle_meta_command(self, cmd: str) -> bool:
        """Handles shell meta-commands. Returns True if REPL should continue, False to exit."""
        cmd_lower = cmd.lower().strip()
        if cmd_lower in (":quit", ":exit"):
            print("Disconnecting. Goodbye!")
            return False

        if cmd_lower == ":help":
            self.print_help()
            return True

        if cmd_lower == ":clear":
            os.system("cls" if os.name == "nt" else "clear")
            return True

        if cmd_lower == ":server":
            print(
                f"Host: {self.client.host}\n"
                f"Port: {self.client.port}\n"
                f"Connected: {self.client.is_connected}\n"
                f"Authenticated: {self.client.is_authenticated}\n"
            )
            return True

        if cmd_lower in (":stats", ":status"):
            try:
                tps = await self.client.execute("tps")
                players = await self.client.execute("list")
                print("\033[1;34m[Server Stats]\033[0m")
                print(minecraft_to_ansi(tps))
                print(minecraft_to_ansi(players))
            except Exception as e:
                print(f"\033[1;31mError fetching server stats: {e}\033[0m")
            return True

        print(f"\033[1;31mUnknown meta-command: {cmd}. Type :help for commands.\033[0m")
        return True

    async def run(self) -> None:
        """Runs the interactive REPL loop."""
        self._session = self._setup_session()
        self.print_banner()

        prompt_str = f"rcon-craft [{self.profile_name}]> "

        while True:
            try:
                line = await self._session.prompt_async(prompt_str)
                line = line.strip()
                if not line:
                    continue

                if line.startswith(":"):
                    should_continue = await self._handle_meta_command(line)
                    if not should_continue:
                        break
                    continue

                # Strip leading slash
                clean_cmd = line.lstrip("/")
                try:
                    response = await self.client.execute(clean_cmd)
                    if response:
                        if self.color:
                            print(minecraft_to_ansi(response))
                        else:
                            print(response)
                except (RconConnectionError, RconAuthenticationError) as conn_err:
                    print(f"\033[1;31mConnection error: {conn_err}\033[0m")
                    print("Attempting to reconnect...")
                    try:
                        await self.client.reconnect()
                        print("\033[1;32mReconnected successfully!\033[0m")
                    except Exception as rec_err:
                        print(f"\033[1;31mReconnect failed: {rec_err}\033[0m")
                except Exception as err:
                    print(f"\033[1;31mCommand error: {err}\033[0m")

            except (KeyboardInterrupt, asyncio.CancelledError):
                # Ctrl+C clears line without terminating session
                print("\n(Interrupted. Use :quit or Ctrl+D to exit)")
                continue
            except EOFError:
                # Ctrl+D exits
                print("\nExiting...")
                break
