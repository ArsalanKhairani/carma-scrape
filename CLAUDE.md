# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Scrapes daily energy readings from the CARMA Smart Metering portal and imports them as long-term statistics into Home Assistant's Energy Dashboard, with full historical backfill support.

## Commands

```bash
# Setup (first time)
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cp config.ini.example config.ini  # then edit with real credentials

# Run the full pipeline
bash run.sh

# Run scripts individually (must be in project root so config.ini is found)
source venv/bin/activate
python3 scrape.py
python3 upload_websocket.py

# Reset a sensor and its statistics in Home Assistant (to re-import from scratch)
python3 cleanup_sensor.py
```

## Architecture

The pipeline has two independent, checkpointed stages:

**Stage 1 — `scrape.py`**
Drives headless Chrome via Selenium to log into the CARMA portal and extract daily kWh readings from the chart's JS data (`chart1.series[0].data`). It navigates backward through monthly pages recursively until it reaches the checkpoint date, then writes new rows (Unix timestamp, kWh) to `data.csv`. The checkpoint (`scrape_checkpoint.txt`) stores the last-scraped date in `dd/Mon/YYYY` format matching the portal's format.

**Stage 2 — `upload_websocket.py`**
Reads `data.csv`, filters rows newer than `upload_checkpoint.txt`, converts the daily delta values into a running cumulative total (required for HA's `total_increasing` state class), then:
1. Creates/updates the sensor entity via the HA REST API (`POST /api/states/<sensor_name>`)
2. Bulk-imports statistics via the HA WebSocket API (`recorder/import_statistics`) in batches of 100

Each row's timestamp is shifted +82800 seconds (to 23:00 of that day) because HA requires statistics timestamps to be on the hour. The upload checkpoint stores the last-uploaded Unix timestamp as an integer.

**`cleanup_sensor.py`** reverses an upload: deletes the HA entity, calls `recorder/clear_statistics` over WebSocket, and removes `upload_checkpoint.txt` so `upload_websocket.py` will re-upload everything on next run.

## Configuration

All secrets and paths live in `config.ini` (gitignored). See `config.ini.example` for the structure. Scripts must be run from the project root so `config.ini` is found via relative path.

## Deployment

`deploy.sh` provisions a Debian 12 LXC on Proxmox and installs a weekly cron job. Re-running is idempotent — it won't touch `config.ini` or runtime data files.
