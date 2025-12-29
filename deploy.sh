#!/usr/bin/env bash
set -euo pipefail

LOCAL_DIR="/home/niklas-pi/pi-video-looper"
LOCAL_BIN_DIR="/usr/local/bin/looper.py"

# looper.service
# to do
# copy looper.service to /etc/systemd/system/looper.service
# then
# sudo systemctl daemon-reload
# sudo systemctl enable --now looper.service


# install python script and restart looper.service
sudo install -m 755 ${LOCAL_DIR}/looper.py ${LOCAL_BIN_DIR} && sudo systemctl restart looper.service
