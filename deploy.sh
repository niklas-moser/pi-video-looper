#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
LOCAL_DIR="${SCRIPT_DIR}"
LOCAL_BIN_DIR="/usr/local/bin/looper.py"
SERVICE_SRC="${LOCAL_DIR}/looper.service"
SERVICE_DST="/etc/systemd/system/looper.service"

# Ensure sources exist before installing
if [ ! -f "${LOCAL_DIR}/looper.py" ]; then
	echo "looper.py not found at ${LOCAL_DIR}. Is the repo path correct?" >&2
	exit 1
fi
if [ ! -f "${SERVICE_SRC}" ]; then
	echo "looper.service not found at ${SERVICE_SRC}." >&2
	exit 1
fi

# Install system dependencies needed by looper.py and GStreamer pipeline
REQUIRED_PKGS=(
	python3-gpiozero
	gstreamer1.0-tools
	gstreamer1.0-plugins-base
	gstreamer1.0-plugins-good
	gstreamer1.0-plugins-bad
	gstreamer1.0-libav
)

MISSING=()
for pkg in "${REQUIRED_PKGS[@]}"; do
	if ! dpkg -s "$pkg" >/dev/null 2>&1; then
		MISSING+=("$pkg")
	fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
	echo "Installing missing packages: ${MISSING[*]}"
	sudo apt-get update
	sudo apt-get install -y "${MISSING[@]}"
else
	echo "All required packages already installed; skipping apt-get."
fi

# Install python script and service unit
sudo install -m 755 "${LOCAL_DIR}/looper.py" "${LOCAL_BIN_DIR}"
sudo install -m 644 "${SERVICE_SRC}" "${SERVICE_DST}"

# Reload and enable the service (starts immediately)
sudo systemctl daemon-reload
sudo systemctl enable --now looper.service
