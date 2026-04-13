#!/bin/bash
# One-command deploy: creates and configures a Proxmox LXC for carma-scrape.
# Run this from your local machine.
#
# Usage:
#   ./deploy.sh [PROXMOX_HOST] [LXC_ID]
#
# Defaults:
#   PROXMOX_HOST — value of $PROXMOX_HOST env var
#   LXC_ID       — value of $LXC_ID env var, or 200

set -euo pipefail

PROXMOX_HOST="${1:-${PROXMOX_HOST:?'Set PROXMOX_HOST or pass as first arg'}}"
LXC_ID="${2:-${LXC_ID:-200}}"
LXC_NAME="carma-scrape"
STORAGE="${PROXMOX_STORAGE:-local-lvm}"    # storage pool for the rootfs
TEMPLATE="debian-12-standard_12.7-1_amd64.tar.zst"  # adjust if needed
INSTALL_DIR="/opt/carma-scrape"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── helpers ──────────────────────────────────────────────────────────────────

# Multiplexing: authenticate once, reuse the socket for all subsequent calls.
SSH_OPTS=(-o StrictHostKeyChecking=no -o ControlMaster=auto -o ControlPath="/tmp/carma-deploy-%r@%h:%p" -o ControlPersist=60)
px()  { ssh "${SSH_OPTS[@]}" "root@${PROXMOX_HOST}" "$@"; }
scp_() { scp "${SSH_OPTS[@]}" "$@"; }

# Pipe a command string as stdin into bash running inside the LXC.
lxc() { px "pct exec ${LXC_ID} -- bash" <<< "$*"; }

# Ship a local file into the LXC: stage on Proxmox host, then pct push.
push_file() {
  local src="$1" dst="$2"
  local tmp="/tmp/carma_push_$$_$(basename "$src")"
  scp_ "$src" "root@${PROXMOX_HOST}:${tmp}"
  px "pct push ${LXC_ID} ${tmp} ${dst}; rm -f ${tmp}"
}

# Open the multiplexed connection now — user is prompted for a password once.
echo "Connecting to ${PROXMOX_HOST} (you may be prompted for the root password)..."
px true

# ── 1. Create container if it doesn't exist ───────────────────────────────────

if px pct status "$LXC_ID" &>/dev/null; then
  echo "Container $LXC_ID already exists — skipping creation."
else
  echo "Creating LXC $LXC_ID ($LXC_NAME)..."
  px pveam download local "$TEMPLATE" 2>/dev/null || true
  px pct create "$LXC_ID" "local:vztmpl/${TEMPLATE}" \
    --hostname "$LXC_NAME" \
    --storage "$STORAGE" \
    --rootfs "${STORAGE}:8" \
    --memory 512 \
    --swap 512 \
    --cores 1 \
    --net0 "name=eth0,bridge=vmbr0,ip=dhcp" \
    --unprivileged 1 \
    --features "nesting=1"
  echo "Starting container..."
  px pct start "$LXC_ID"
  sleep 5  # wait for network
  lxc "passwd -d root"  # no password required for console/pct exec
fi

# ── 2. Install system packages ────────────────────────────────────────────────

echo "Installing system packages..."
lxc "apt-get update -qq && apt-get install -y -qq python3 python3-venv chromium chromium-driver"

# ── 3. Sync code from local to LXC ───────────────────────────────────────────
# No GitHub auth needed — we tar the local files and ship them directly.

echo "Syncing code to ${INSTALL_DIR}..."
TARBALL="$(mktemp /tmp/carma-scrape.XXXX.tar.gz)"
COPYFILE_DISABLE=1 tar -czf "$TARBALL" -C "$SCRIPT_DIR" \
  --exclude='config.ini' \
  --exclude='data.csv' \
  --exclude='scrape_checkpoint.txt' \
  --exclude='upload_checkpoint.txt' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='.git' \
  .
lxc "mkdir -p ${INSTALL_DIR}"
push_file "$TARBALL" "/tmp/carma-deploy.tar.gz"
rm -f "$TARBALL"
lxc "tar -xzf /tmp/carma-deploy.tar.gz -C ${INSTALL_DIR} && rm /tmp/carma-deploy.tar.gz"

lxc "python3 -m venv ${INSTALL_DIR}/venv && ${INSTALL_DIR}/venv/bin/pip install -q -r ${INSTALL_DIR}/requirements.txt"
lxc "chmod +x ${INSTALL_DIR}/run.sh"

# ── 4. Copy config.ini ────────────────────────────────────────────────────────

CONFIG_SRC="${SCRIPT_DIR}/config.ini"
if [ -f "$CONFIG_SRC" ]; then
  echo "Copying config.ini..."
  push_file "$CONFIG_SRC" "${INSTALL_DIR}/config.ini"
else
  echo "WARNING: config.ini not found — copy it manually after deploy:"
  echo "  scp carma-scrape/config.ini root@${PROXMOX_HOST}:/tmp/ && ssh root@${PROXMOX_HOST} pct push ${LXC_ID} /tmp/config.ini ${INSTALL_DIR}/config.ini"
fi

# ── 5. Install cron job (daily at 07:00) ─────────────────────────────────────

echo "Installing cron job..."
CRON_LINE="0 7 * * 1 ${INSTALL_DIR}/run.sh >> /var/log/carma-scrape.log 2>&1"
lxc "(crontab -l 2>/dev/null | grep -v carma-scrape; echo '${CRON_LINE}') | crontab -"

echo ""
echo "Deployment complete!"
echo "  Container ID : $LXC_ID"
echo "  Install dir  : $INSTALL_DIR"
echo "  Cron schedule: daily at 07:00"
echo ""
echo "To run manually inside the container:"
echo "  pct exec $LXC_ID -- ${INSTALL_DIR}/run.sh"
