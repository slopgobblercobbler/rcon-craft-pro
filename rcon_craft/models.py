"""Domain models, enums, dataclasses, and custom exceptions for rcon-craft."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import List, Optional, Union


class PacketType(IntEnum):
    """Minecraft RCON packet types according to the Valve RCON specification."""
    SERVERDATA_RESPONSE_VALUE = 0
    SERVERDATA_AUTH_RESPONSE = 2
    SERVERDATA_EXECCOMMAND = 2
    SERVERDATA_AUTH = 3


class RconError(Exception):
    """Base exception for all RCON errors."""
    pass


class RconConnectionError(RconError):
    """Raised when failing to connect, connection drops, or network error occurs."""
    pass


class RconAuthenticationError(RconError):
    """Raised when authentication with the Minecraft RCON server fails."""
    pass


class RconTimeoutError(RconConnectionError):
    """Raised when an RCON operation times out."""
    pass


class RconProtocolError(RconError):
    """Raised when a malformed or invalid packet is received from the server."""
    pass


class BatchExecutionError(RconError):
    """Raised when batch execution fails or an assertion is violated."""
    pass


class ConfigError(RconError):
    """Raised when configuration is invalid or missing."""
    pass


@dataclass(frozen=True)
class RconPacket:
    """Represents a single binary RCON packet."""
    request_id: int
    packet_type: Union[PacketType, int]
    payload: str

    @property
    def is_auth(self) -> bool:
        return self.packet_type == PacketType.SERVERDATA_AUTH

    @property
    def is_auth_response(self) -> bool:
        return self.packet_type == PacketType.SERVERDATA_AUTH_RESPONSE

    @property
    def is_command(self) -> bool:
        return self.packet_type == PacketType.SERVERDATA_EXECCOMMAND

    @property
    def is_response(self) -> bool:
        return self.packet_type == PacketType.SERVERDATA_RESPONSE_VALUE


@dataclass
class ServerProfile:
    """Configuration profile for a Minecraft server RCON endpoint."""
    name: str = "default"
    host: str = "127.0.0.1"
    port: int = 25575
    password: str = ""
    timeout: float = 5.0
    color: bool = True
    multi_packet: bool = True

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "timeout": self.timeout,
            "color": self.color,
            "multi_packet": self.multi_packet,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> ServerProfile:
        return cls(
            name=name,
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 25575)),
            password=str(data.get("password", "")),
            timeout=float(data.get("timeout", 5.0)),
            color=bool(data.get("color", True)),
            multi_packet=bool(data.get("multi_packet", True)),
        )


@dataclass
class MonitorMetrics:
    """Snapshot of Minecraft server health metrics."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tps_1m: Optional[float] = None
    tps_5m: Optional[float] = None
    tps_15m: Optional[float] = None
    players_online: int = 0
    players_max: int = 0
    player_names: List[str] = field(default_factory=list)
    memory_free_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    raw_tps_response: str = ""
    raw_list_response: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "tps_1m": self.tps_1m,
            "tps_5m": self.tps_5m,
            "tps_15m": self.tps_15m,
            "players_online": self.players_online,
            "players_max": self.players_max,
            "player_names": self.player_names,
            "memory_free_mb": self.memory_free_mb,
            "memory_total_mb": self.memory_total_mb,
            "raw_tps_response": self.raw_tps_response,
            "raw_list_response": self.raw_list_response,
        }


@dataclass
class BatchCommandResult:
    """Result of an individual command within a batch execution."""
    command: str
    line_number: int
    status: str  # "SUCCESS", "ERROR", "SKIPPED"
    response: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "line_number": self.line_number,
            "status": self.status,
            "response": self.response,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class BatchExecutionResult:
    """Aggregate result of a batch script execution."""
    script_path: str
    total_commands: int = 0
    successful_commands: int = 0
    failed_commands: int = 0
    skipped_commands: int = 0
    results: List[BatchCommandResult] = field(default_factory=list)
    total_duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "script_path": self.script_path,
            "total_commands": self.total_commands,
            "successful_commands": self.successful_commands,
            "failed_commands": self.failed_commands,
            "skipped_commands": self.skipped_commands,
            "total_duration_s": self.total_duration_s,
            "results": [r.to_dict() for r in self.results],
        }
