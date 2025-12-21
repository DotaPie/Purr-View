#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/PurrView"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "  > Stopping purr-view.service ..."
systemctl stop    purr-view.service || true

echo "  > Copying src files ..."
cp "${SCRIPT_DIR}"/src/{config.json,logging_setup.py,main.py,hud.py,view.py,upload.py,cam.py,utils.py} "${INSTALL_DIR}/"

echo "  > Starting purr-view.service ..."
systemctl start purr-view.service || true

echo "  > Re-deploy complete"