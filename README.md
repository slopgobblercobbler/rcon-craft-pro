# RCON Craft Pro

Production-grade asynchronous Minecraft RCON CLI and performance monitoring tool.

## Features
- **Strict RCON Protocol**: Robust client implementation conforming to Valve RCON specifications with multi-packet reassembly, Spigot 1.14+ dummy packet handling, and connection keep-alives.
- **Batch Automation Engine**: Execute `.rcon` command scripts with variable substitution (`${VAR}`), delay directives (`sleep <seconds>`), assertions (`assert <substring>`), and error handling (`stop-on-error`).
- **Real-Time Performance Monitor**: Periodic server telemetry polling with TPS extraction (1m, 5m, 15m), player count and roster parsing, and threshold alerts exported to CSV/JSONL.
- **Interactive REPL**: Full-featured interactive terminal console with Minecraft color code conversion (`§` and `&` to ANSI 256-color / RGB).
- **Server Profiles**: Configuration management via TOML profiles with environment variable resolution and authentication caching.

## Installation
```bash
pip install .
```

## CLI Usage
```bash
# Execute a single command
rcon-craft exec "say Hello Minecraft" -H 127.0.0.1 -P 25575 -w secret

# Run an automated batch script
rcon-craft batch maintenance.rcon -H 127.0.0.1 -P 25575 -w secret --var MSG=Restarting

# Real-time server telemetry monitoring
rcon-craft monitor -H 127.0.0.1 -P 25575 -w secret --interval 5.0 --csv-out stats.csv

# Save server profile
rcon-craft profile add survival -H 192.168.1.10 -P 25575 -w mypass --default
```

## License
MIT
