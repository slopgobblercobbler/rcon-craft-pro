"""Configuration management for multi-server profiles in TOML format."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from rcon_craft.models import ConfigError, ServerProfile

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "rcon-craft"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "servers.toml"
LOCAL_CONFIG_PATH = Path("./servers.toml")

RE_ENV_VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def resolve_env_value(value: str) -> str:
    """Expands environment variables in the form 'env:VAR' or '${VAR}'."""
    if not isinstance(value, str):
        return value

    if value.startswith("env:"):
        var_name = value[4:].strip()
        return os.environ.get(var_name, "")

    def _replace_env(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return RE_ENV_VAR.sub(_replace_env, value)


def _load_toml(content: str) -> dict:
    """Parses TOML string using standard library or available third-party parsers."""
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(content)
    except ImportError:
        pass

    try:
        import tomli  # Fast PEP-680 reader
        return tomli.loads(content)
    except ImportError:
        pass

    try:
        import toml
        return toml.loads(content)
    except ImportError as err:
        raise ConfigError(
            "No TOML parser available. Please install 'tomli' or 'toml'."
        ) from err


def _dump_toml(data: dict) -> str:
    """Serializes a dictionary to TOML format."""
    lines = []
    if "default_server" in data and data["default_server"] is not None:
        lines.append(f'default_server = "{data["default_server"]}"\n')

    servers = data.get("servers", {})
    for server_name, server_data in servers.items():
        lines.append(f"[servers.{server_name}]")
        for k, v in server_data.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                escaped = str(v).replace('"', '\\"')
                lines.append(f'{k} = "{escaped}"')
        lines.append("")

    return "\n".join(lines)


def get_default_config_path(explicit_path: Optional[Union[str, Path]] = None) -> Path:
    """Determines config file path checking explicit path, ./servers.toml, or ~/.config/rcon-craft/servers.toml."""
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    if LOCAL_CONFIG_PATH.exists():
        return LOCAL_CONFIG_PATH.resolve()
    return DEFAULT_CONFIG_PATH.expanduser().resolve()


def load_config(
    path: Optional[Union[str, Path]] = None,
) -> Tuple[Dict[str, ServerProfile], Optional[str]]:
    """Loads profiles and default_server from configuration file."""
    config_file = get_default_config_path(path)
    if not config_file.exists():
        return {}, None

    try:
        content = config_file.read_text(encoding="utf-8")
        data = _load_toml(content)
    except Exception as err:
        raise ConfigError(f"Failed to parse config file at {config_file}: {err}") from err

    default_server = data.get("default_server")
    raw_servers = data.get("servers", {})

    profiles: Dict[str, ServerProfile] = {}
    for name, s_data in raw_servers.items():
        if not isinstance(s_data, dict):
            continue
        # Resolve any environment variables in host and password
        resolved_data = dict(s_data)
        if "password" in resolved_data:
            resolved_data["password"] = resolve_env_value(str(resolved_data["password"]))
        if "host" in resolved_data:
            resolved_data["host"] = resolve_env_value(str(resolved_data["host"]))

        profiles[name] = ServerProfile.from_dict(name, resolved_data)

    return profiles, default_server


def save_config(
    profiles: Dict[str, ServerProfile],
    default_server: Optional[str] = None,
    path: Optional[Union[str, Path]] = None,
) -> Path:
    """Saves profiles and default_server to configuration file."""
    config_file = get_default_config_path(path)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "default_server": default_server,
        "servers": {name: prof.to_dict() for name, prof in profiles.items()},
    }

    content = _dump_toml(data)
    config_file.write_text(content, encoding="utf-8")
    return config_file


def get_profile(
    name: Optional[str] = None,
    config_path: Optional[Union[str, Path]] = None,
) -> ServerProfile:
    """Finds a profile by name, or falls back to default_server or single existing profile."""
    profiles, default_server = load_config(config_path)

    if not profiles:
        raise ConfigError(
            f"No server profiles found in configuration ({get_default_config_path(config_path)}). "
            "Please create a profile using 'rcon-craft profile add' or specify --host, --port, and --password."
        )

    target_name = name or default_server
    if not target_name:
        if len(profiles) == 1:
            target_name = next(iter(profiles.keys()))
        else:
            raise ConfigError(
                f"Multiple server profiles available: {', '.join(profiles.keys())}. "
                "Specify one using --profile <name> or set a default_server."
            )

    if target_name not in profiles:
        raise ConfigError(
            f"Server profile '{target_name}' not found. Available profiles: {', '.join(profiles.keys())}"
        )

    return profiles[target_name]


def add_profile(
    profile: ServerProfile,
    set_as_default: bool = False,
    config_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Adds or updates a server profile."""
    profiles, default_server = load_config(config_path)
    profiles[profile.name] = profile

    if set_as_default or not default_server:
        default_server = profile.name

    return save_config(profiles, default_server, config_path)


def remove_profile(
    name: str,
    config_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Removes a server profile by name."""
    profiles, default_server = load_config(config_path)
    if name not in profiles:
        return False

    del profiles[name]
    if default_server == name:
        default_server = next(iter(profiles.keys())) if profiles else None

    save_config(profiles, default_server, config_path)
    return True
