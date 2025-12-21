#!/usr/bin/env bash
########################################################################
# install-purr-view.sh
# ---------------------------------------------------------------------
# Installs Purr-View to /opt/PurrView, copies runtime files,
# sets up a venv, installs deps from a chosen requirements file located
# beside the installer, registers a systemd service that runs as the
# invoking (non-root) user, and configures mDNS with hostname 'purrview'.
########################################################################
set -euo pipefail

# 1. Variables you might tweak
RUN_USER="${SUDO_USER:-$USER}"                       # non-root account
INSTALL_DIR="/opt/PurrView"
SERVICE_FILE="/etc/systemd/system/purr-view.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"          # dir of this script
CONFIG_JSON="${SCRIPT_DIR}/src/config.json"          # config file to read
HOSTNAME_TARGET="purrview"                      # desired hostname (no .local)

# Ensure the config file is present before we go any further
if [[ ! -f "$CONFIG_JSON" ]]; then
    echo "ERROR: $CONFIG_JSON not found. Aborting." >&2
    exit 1
fi

# 2. Install system packages (add avahi-daemon for mDNS)
echo " > Updating APT index and installing python3-pip, libgl1, jq, avahi-daemon ..."
apt update
apt install -y python3-pip libgl1 jq avahi-daemon

# --- Set hostname to 'purrview' ---
echo " > Setting hostname to '${HOSTNAME_TARGET}' ..."

# Disable cloud-init hostname management if present
if [[ -d /etc/cloud ]]; then
  echo " > Disabling cloud-init hostname management ..."
  
  # Disable in main config
  if [[ -f /etc/cloud/cloud.cfg ]]; then
    sed -i 's/manage_etc_hosts: [Tt]rue/manage_etc_hosts: false/' /etc/cloud/cloud.cfg
  fi
  
  # Create override config
  mkdir -p /etc/cloud/cloud.cfg.d
  cat > /etc/cloud/cloud.cfg.d/99-disable-hostname.cfg <<EOF
# Disable cloud-init hostname management for Purr-View
preserve_hostname: true
manage_etc_hosts: false
EOF
fi

# Set hostname everywhere
echo "$HOSTNAME_TARGET" > /etc/hostname
if command -v hostnamectl >/dev/null 2>&1; then
  hostnamectl set-hostname "$HOSTNAME_TARGET"
fi

# Fix /etc/hosts - remove old entries and add new one
sed -i '/127\.0\.1\.1/d' /etc/hosts
echo "127.0.1.1   ${HOSTNAME_TARGET} ${HOSTNAME_TARGET}.local" >> /etc/hosts

# 3. Resolve log / video paths from config.json and create them
LOGGING_PATH=$(jq -r '.LOGGING_PATH' "$CONFIG_JSON")
VIDEO_PATH=$(jq -r '.VIDEO_PATH'   "$CONFIG_JSON")

echo " > Creating paths from config.json ..."
mkdir -p "$LOGGING_PATH" "$VIDEO_PATH"
chown -R "${RUN_USER}:${RUN_USER}" "$LOGGING_PATH" "$VIDEO_PATH"
chmod 750 "$LOGGING_PATH" "$VIDEO_PATH"

# 4. Copy runtime files (no requirements files)
echo " > Copying runtime files to ${INSTALL_DIR}/"
mkdir -p "$INSTALL_DIR"
cp "${SCRIPT_DIR}"/src/{config.json,logging_setup.py,main.py,hud.py,view.py,upload.py,cam.py,utils.py} "$INSTALL_DIR/"

# 5. Virtual environment + dependency install
echo " > Creating Python virtual environment ..."
python3 -m venv "${INSTALL_DIR}/venv"
# shellcheck disable=SC1091
source "${INSTALL_DIR}/venv/bin/activate"
pip install --upgrade pip

echo " > Checking requirements file ..."
REQ_FILE="requirements.txt"

REQ_PATH="${SCRIPT_DIR}/${REQ_FILE}"
if [[ ! -f "$REQ_PATH" ]]; then
    echo "ERROR: ${REQ_FILE} not found next to installer. Aborting." >&2
    exit 1
fi

echo " > Installing Python dependencies from ${REQ_PATH} ..."
pip install -r "$REQ_PATH"
deactivate

# 6. Create systemd unit
echo " > Writing systemd unit to ${SERVICE_FILE} ..."
cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=Purr View
After=network.target

[Service]
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/main.py

AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

Restart=on-failure
RestartSec=5

Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

# 7. Enable & start the app service
echo " > Enabling and starting purr-view.service ..."
systemctl daemon-reload
systemctl enable purr-view
systemctl start  purr-view

# 8. Enable mDNS responder (Avahi) so http://purrview.local/ works
echo " > Enabling mDNS (avahi-daemon) ..."
systemctl enable avahi-daemon
systemctl restart avahi-daemon

echo -e "\nAll done!"
echo "Local access (port 80) via mDNS:"
echo "    http://purrview.local/"
echo
echo "IMPORTANT: Reboot required for hostname change"
echo
echo "Check the service status with:"
echo "    sudo systemctl status purr-view"
