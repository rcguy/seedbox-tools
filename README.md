# Seedbox Tools

Lightweight Python utilities to manage torrents across Deluge, qBittorrent and rTorrent.

## Overview

This repository provides a small command-line toolkit (`seedbox.py`) and client implementations in `clients/` to:
- list and summarize torrents
- add/upload `.torrent` files
- export `.torrent` files (optionally zipped)
- move content from fast NVMe storage to spinning Rust
- remove torrents that have seeded long enough, and clean unregistered torrents

The default client is `rTorrent`, and additional clients implemented are `Deluge` and `qBittorrent`.

## Quick Start

1. Create and activate a Python virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy the example config and edit it:

```bash
cp cfg/config.example.yaml cfg/seedbox.yaml
# Edit cfg/seedbox.yaml to set host/credentials and paths for your environment
```

## Usage

Run the main script with `-c`/`--client` to choose a client.

- List torrents (client default: `rtorrent`):

```bash
python seedbox.py -c deluge -L
```

- Add `.torrent` files (with optional save path and label/tag):

```bash
python seedbox.py -c qbittorrent -A '/path/to/*.torrent' --path '/mnt/downloads/Movies' --label movies-1080p
```

- Export `.torrent` files (optionally zip exports):

```bash
python seedbox.py -c rtorrent -E --export-dir /tmp/exported --zip
```

- Move torrents from NVMe to spinning rust (honors NVMe cache time):

```bash
python seedbox.py -c rtorrent -M
```

- Remove torrents that have seeded longer than the configured time:

```bash
python seedbox.py -c deluge -R --seed-time 72
```

- Summary table (category counts & sizes):

```bash
python seedbox.py -c rtorrent --summary --summary-sort size desc
```

Common flags:
- `--dry-run` : show what would be done without making changes
- `--zip` : create a zip archive when exporting torrents
- `--nvme-time` / `--seed-time` : override timings from the config file

See `python seedbox.py -h` for the full list of flags and commands.

## Configuration

- Default config path: `cfg/seedbox.yaml` (the script will use this if `-C`/`--config` is not provided).
- A sample configuration is provided at `cfg/config.example.yaml` — copy it to `cfg/seedbox.yaml` and update credentials, paths, and category seed times.

Key configuration areas:
- global settings: `nvme_dir`, `rust_dir`, `nvme_cache_time`, `minimum_seed_time`, `export_dir`
- client sections: `Deluge`, `qBittorrent`, `rTorrent` (connection info and any client-specific settings)

## Project Layout

- `seedbox.py` — main CLI entrypoint
- `cfg/` — configuration files (`config.example.yaml` included)
- `clients/` — client implementations for Deluge, qBittorrent, rTorrent and shared client utilities
- `models/` — configuration dataclasses and helpers

## Notes & Troubleshooting

- Logs are written to `logs/seedbox_tools.log` relative to the script directory.
- If you see configuration errors, double-check `cfg/seedbox.yaml` matches the keys expected by `models/config.py`.

## Contributing

Contributions are welcome. Open an issue or a pull request with a description of your changes.

## License

This project is provided under the terms in the `LICENSE` file.
