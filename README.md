# carma-scrape

Scrapes daily energy readings from the [CARMA Smart Metering](http://www.carmasmartmetering.com) portal and imports them as long-term statistics into [Home Assistant](https://www.home-assistant.io/).

Useful if your building uses CARMA and you want your energy data in the Home Assistant Energy Dashboard with full historical backfill.

## How it works

1. **`scrape.py`** — logs into the CARMA portal using Selenium/Chrome, reads the daily consumption chart, and appends new readings to `data.csv`.
2. **`upload_websocket.py`** — reads `data.csv` and pushes cumulative statistics to Home Assistant via the WebSocket API.
3. **`run.sh`** — runs both scripts in sequence; intended to be called by cron.

Both scripts are incremental: they checkpoint their progress so re-runs only process new data.

## Setup

### Prerequisites

- Python 3.10+
- Chrome/Chromium + chromedriver
  - **macOS:** download from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/#stable), then:
    ```bash
    sudo cp ~/Desktop/chromedriver-mac-arm64/chromedriver /usr/local/bin
    sudo xattr -d com.apple.quarantine /usr/local/bin/chromedriver
    ```
  - **Debian/Ubuntu:** `apt install chromium chromium-driver`
- A Home Assistant instance with a [Long-Lived Access Token](https://my.home-assistant.io/redirect/profile/) (Profile → Security → Create Long-Lived Access Token)

### Install

```bash
git clone https://github.com/your-username/carma-scrape.git
cd carma-scrape

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp config.ini.example config.ini
# Edit config.ini with your CARMA credentials and Home Assistant details
```

`config.ini` is gitignored and must never be committed.

### Run

```bash
# Scrape new data from CARMA
python3 scrape.py

# Upload to Home Assistant
python3 upload_websocket.py

# Or run both at once
bash run.sh
```

On first run, `scrape.py` will backfill from `start_date` in `config.ini`.

## Deploying to a Proxmox LXC

`deploy.sh` automates creating and configuring a Debian 12 LXC container on a Proxmox host, with a weekly cron job.

### Prerequisites

- Proxmox host reachable over SSH as `root`
- A local `config.ini` (see above)

### Deploy

```bash
export PROXMOX_HOST=192.168.x.x   # your Proxmox host IP
export LXC_ID=200                  # container ID to create (pick a free one)

bash deploy.sh
```

The script will:
1. Create a Debian 12 LXC (512 MB RAM, 8 GB disk) — skipped if it already exists
2. Install Python 3, pip, Chromium, and chromedriver
3. Sync the project files into `/opt/carma-scrape`
4. Install Python dependencies into a venv
5. Copy your local `config.ini` into the container
6. Install a cron job to run at **07:00 every Monday**

Re-running on an existing container is safe — it pulls the latest code without touching `config.ini` or runtime data.

**Optional env vars:**

| Variable          | Default      | Description                        |
|-------------------|--------------|------------------------------------|
| `PROXMOX_HOST`    | *(required)* | Proxmox host IP or hostname        |
| `LXC_ID`          | `200`        | Container ID                       |
| `LXC_PASSWORD`    | `changeme`   | Root password inside the container |
| `PROXMOX_STORAGE` | `local-lvm`  | Storage pool for the rootfs        |

### Running manually inside the container

```bash
# Drop into the container
pct exec 200 -- bash

# Run the full pipeline
/opt/carma-scrape/run.sh

# Or run scripts individually
cd /opt/carma-scrape
python3 scrape.py
python3 upload_websocket.py
```

View logs:

```bash
pct exec 200 -- tail -f /var/log/carma-scrape.log
```

### Updating config.ini on the LXC

```bash
# From carma-scrape/ on your local machine
scp config.ini root@<PROXMOX_HOST>:/tmp/config.ini
ssh root@<PROXMOX_HOST> pct push <LXC_ID> /tmp/config.ini /opt/carma-scrape/config.ini
```

## Utility scripts

**`cleanup_sensor.py`** — removes the sensor entity, clears its statistics from the Home Assistant database, and deletes the upload checkpoint. Useful if you need to re-import from scratch.

```bash
python3 cleanup_sensor.py
```

## File layout

```
config.ini              ← credentials (gitignored, never commit)
data.csv                ← scraped readings (gitignored)
scrape_checkpoint.txt   ← last scraped date (gitignored)
upload_checkpoint.txt   ← last uploaded timestamp (gitignored)
```
