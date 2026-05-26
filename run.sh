#!/bin/bash
# Runs the full scrape → upload pipeline.
# Intended to be called by cron.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PYTHON="${DIR}/venv/bin/python3"

notify() { "$PYTHON" -c "from akutils import notify; notify('$1', title='CARMA')" 2>/dev/null || true; }

trap 'notify "Pipeline failed"' ERR

echo "=== $(date) ==="
echo "--- Scraping ---"
"$PYTHON" scrape.py

echo "--- Uploading ---"
"$PYTHON" upload_websocket.py

echo "--- Done ---"
notify "Scrape and upload complete"
