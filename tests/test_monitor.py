"""Unit and integration tests for headless server performance monitoring and alert system."""

import json
from pathlib import Path
import pytest

from rcon_craft.client import RconClient
from rcon_craft.models import MonitorMetrics
from rcon_craft.monitor import ServerMonitor, parse_player_list, parse_tps
from tests.mock_server import MockRconServer


def test_parse_tps_paper_spigot():
    raw_spigot = "§6TPS from last 1m, 5m, 15m: §a20.0, §a19.98, §a19.95"
    t1, t5, t15 = parse_tps(raw_spigot)
    assert t1 == 20.0
    assert t5 == 19.98
    assert t15 == 19.95


def test_parse_tps_asterisks():
    raw = "TPS from last 1m, 5m, 15m: *20.0, *20.0, *19.8"
    t1, t5, t15 = parse_tps(raw)
    assert t1 == 20.0
    assert t5 == 20.0
    assert t15 == 19.8


def test_parse_tps_fallback_single():
    raw = "Current Server TPS: 18.50"
    t1, t5, t15 = parse_tps(raw)
    assert t1 == 18.50
    assert t5 is None
    assert t15 is None


def test_parse_tps_invalid():
    t1, t5, t15 = parse_tps("Unknown command or server output without numbers")
    assert t1 is None
    assert t5 is None
    assert t15 is None


def test_parse_player_list_standard():
    raw = "There are 3 of a max of 50 players online: Alex, Steve, Notch"
    online, max_p, names = parse_player_list(raw)
    assert online == 3
    assert max_p == 50
    assert names == ["Alex", "Steve", "Notch"]


def test_parse_player_list_empty():
    raw = "There are 0 of a max of 20 players online."
    online, max_p, names = parse_player_list(raw)
    assert online == 0
    assert max_p == 20
    assert names == []


def test_parse_player_list_slash():
    raw = "There are 2/100 players online: PlayerOne, PlayerTwo"
    online, max_p, names = parse_player_list(raw)
    assert online == 2
    assert max_p == 100
    assert names == ["PlayerOne", "PlayerTwo"]


def test_parse_player_list_unparseable():
    online, max_p, names = parse_player_list("No player info here")
    assert online == 0
    assert max_p == 0
    assert names == []


@pytest.mark.asyncio
async def test_server_monitor_metrics_and_alerts(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    jsonl_file = tmp_path / "metrics.jsonl"

    async with MockRconServer(password="secret") as server:
        # Register simulated tps and list
        server.register_command("tps", "TPS from last 1m, 5m, 15m: 14.50, 16.00, 18.00")
        server.register_command("list", "There are 15 of a max of 20 players online: Alice, Bob")

        alerts = []
        metrics_received = []

        async with RconClient(host=server.host, port=server.port, password="secret") as client:
            monitor = ServerMonitor(
                client=client,
                interval=0.01,
                alert_tps_below=16.0,
                alert_players_above=10,
                csv_file=csv_file,
                jsonl_file=jsonl_file,
                on_metrics=lambda m: metrics_received.append(m),
                on_alert=lambda msg, m: alerts.append(msg),
            )

            await monitor.run_loop(max_iterations=2)

            assert len(metrics_received) == 2
            assert metrics_received[0].tps_1m == 14.50
            assert metrics_received[0].players_online == 15
            assert metrics_received[0].player_names == ["Alice", "Bob"]

            # Both alerts should have fired for each iteration
            assert len(alerts) == 4
            assert any("CRITICAL: 1m TPS dropped" in a for a in alerts)
            assert any("WARNING: Online players exceeded" in a for a in alerts)

            # Verify CSV file written
            assert csv_file.exists()
            lines = csv_file.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 3  # Header + 2 data rows
            assert "timestamp,tps_1m" in lines[0]

            # Verify JSONL file written
            assert jsonl_file.exists()
            j_lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
            assert len(j_lines) == 2
            entry = json.loads(j_lines[0])
            assert entry["tps_1m"] == 14.50
            assert entry["players_online"] == 15
