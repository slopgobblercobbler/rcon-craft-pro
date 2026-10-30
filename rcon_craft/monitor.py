"""Headless monitoring mode for Minecraft server performance and player metrics."""

from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from rcon_craft.client import RconClient
from rcon_craft.colors import strip_minecraft_formatting
from rcon_craft.models import MonitorMetrics, RconError

RE_TPS = re.compile(
    r"(?:TPS\s*(?:from\s*last\s*1m,\s*5m,\s*15m)?:?\s*)+([*0-9.]+)(?:,\s*([*0-9.]+))?(?:,\s*([*0-9.]+))?",
    re.IGNORECASE,
)
RE_PLAYERS = re.compile(
    r"There are\s+([0-9]+)\s*(?:of a max (?:of)?\s+|/\s*)([0-9]+)\s+players? online\.?(?::?\s*(.*))?",
    re.IGNORECASE,
)
RE_MEM = re.compile(
    r"(?:Free|Allocated)\s*memory:?\s*([0-9,.]+)\s*(?:MB|GB|KB)?.*?of\s*([0-9,.]+)\s*(?:MB|GB|KB)?",
    re.IGNORECASE,
)


def parse_tps(raw_text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Extracts 1m, 5m, and 15m TPS from server response string."""
    clean = strip_minecraft_formatting(raw_text)
    # Strip any asterisks sometimes outputted by Paper (e.g. *20.0)
    clean = clean.replace("*", "")

    m = RE_TPS.search(clean)
    if not m:
        # Fallback: find any floating points after "tps"
        floats = re.findall(r"\b([0-9]{1,2}\.[0-9]+)\b", clean)
        if floats:
            tps_vals = [float(f) for f in floats[:3]]
            while len(tps_vals) < 3:
                tps_vals.append(None)
            return tps_vals[0], tps_vals[1], tps_vals[2]
        return None, None, None

    t1 = float(m.group(1)) if m.group(1) else None
    t5 = float(m.group(2)) if m.group(2) else None
    t15 = float(m.group(3)) if m.group(3) else None
    return t1, t5, t15


def parse_player_list(raw_text: str) -> Tuple[int, int, List[str]]:
    """Extracts online count, max players, and player names from '/list' command output."""
    clean = strip_minecraft_formatting(raw_text).strip()
    m = RE_PLAYERS.search(clean)
    if not m:
        return 0, 0, []

    online = int(m.group(1))
    max_p = int(m.group(2))
    names_str = (m.group(3) or "").strip(". ")
    names = [name.strip() for name in names_str.split(",") if name.strip()]
    return online, max_p, names


class ServerMonitor:
    """Monitors Minecraft server metrics via periodic RCON queries."""

    def __init__(
        self,
        client: RconClient,
        interval: float = 5.0,
        alert_tps_below: Optional[float] = 18.0,
        alert_players_above: Optional[int] = None,
        csv_file: Optional[Union[str, Path]] = None,
        jsonl_file: Optional[Union[str, Path]] = None,
        on_metrics: Optional[Callable[[MonitorMetrics], None]] = None,
        on_alert: Optional[Callable[[str, MonitorMetrics], None]] = None,
    ) -> None:
        self.client = client
        self.interval = interval
        self.alert_tps_below = alert_tps_below
        self.alert_players_above = alert_players_above
        self.csv_file = Path(csv_file) if csv_file else None
        self.jsonl_file = Path(jsonl_file) if jsonl_file else None
        self.on_metrics = on_metrics
        self.on_alert = on_alert
        self._running = False
        self._init_files()

    def _init_files(self) -> None:
        if self.csv_file and not self.csv_file.exists():
            self.csv_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "tps_1m",
                    "tps_5m",
                    "tps_15m",
                    "players_online",
                    "players_max",
                    "player_names",
                ])

        if self.jsonl_file and not self.jsonl_file.exists():
            self.jsonl_file.parent.mkdir(parents=True, exist_ok=True)

    def _record_metrics(self, m: MonitorMetrics) -> None:
        if self.csv_file:
            with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    m.timestamp.isoformat(),
                    m.tps_1m if m.tps_1m is not None else "",
                    m.tps_5m if m.tps_5m is not None else "",
                    m.tps_15m if m.tps_15m is not None else "",
                    m.players_online,
                    m.players_max,
                    ";".join(m.player_names),
                ])

        if self.jsonl_file:
            with open(self.jsonl_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(m.to_dict()) + "\n")

    def _check_alerts(self, m: MonitorMetrics) -> None:
        if not self.on_alert:
            return

        if self.alert_tps_below is not None and m.tps_1m is not None:
            if m.tps_1m < self.alert_tps_below:
                self.on_alert(
                    f"CRITICAL: 1m TPS dropped below threshold ({m.tps_1m:.2f} < {self.alert_tps_below:.2f})",
                    m,
                )

        if self.alert_players_above is not None:
            if m.players_online > self.alert_players_above:
                self.on_alert(
                    f"WARNING: Online players exceeded threshold ({m.players_online} > {self.alert_players_above})",
                    m,
                )

    async def poll_once(self) -> MonitorMetrics:
        """Polls server once for TPS and player list."""
        tps_raw = ""
        list_raw = ""

        try:
            tps_raw = await self.client.execute("tps")
        except RconError:
            tps_raw = ""

        try:
            list_raw = await self.client.execute("list")
        except RconError:
            list_raw = ""

        t1, t5, t15 = parse_tps(tps_raw)
        online, max_p, names = parse_player_list(list_raw)

        metrics = MonitorMetrics(
            timestamp=datetime.utcnow(),
            tps_1m=t1,
            tps_5m=t5,
            tps_15m=t15,
            players_online=online,
            players_max=max_p,
            player_names=names,
            raw_tps_response=tps_raw,
            raw_list_response=list_raw,
        )

        self._record_metrics(metrics)
        self._check_alerts(metrics)

        if self.on_metrics:
            self.on_metrics(metrics)

        return metrics

    async def run_loop(self, max_iterations: Optional[int] = None) -> None:
        """Runs periodic monitoring loop."""
        self._running = True
        iterations = 0

        while self._running:
            await self.poll_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        """Stops the monitoring loop."""
        self._running = False
