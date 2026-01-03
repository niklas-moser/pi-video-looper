#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
LOCAL_DIR="${SCRIPT_DIR}"
LOCAL_BIN_DIR="/usr/local/bin/looper.py"
SERVICE_SRC="${LOCAL_DIR}/looper.service"
SERVICE_DST="/etc/systemd/system/looper.service"
VIDEO_DIR="${VIDEO_DIR:-/media/videos}"
REENCODE="${REENCODE:-0}"

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
sudo apt-get update
sudo apt-get install -y \
	python3-gpiozero \
	gstreamer1.0-tools \
	gstreamer1.0-plugins-base \
	gstreamer1.0-plugins-good \
	gstreamer1.0-plugins-bad \
	gstreamer1.0-libav \
	ffmpeg

if [ "${REENCODE}" = "1" ]; then
	echo "Re-encoding videos in ${VIDEO_DIR} to H.264 mp4 (suffix -h264.mp4)"
	shopt -s nullglob
	found=0
	for src in "${VIDEO_DIR}"/*.mp4 "${VIDEO_DIR}"/*.mkv "${VIDEO_DIR}"/*.mov; do
		[ -e "$src" ] || continue
		found=1
		base="$(basename -- "$src")"
		out="${VIDEO_DIR}/${base%.*}-h264.mp4"
		if [ -f "$out" ]; then
			echo "Skip ${src} (already have ${out})"
			continue
		fi
		echo "Transcoding ${src} -> ${out}"
		if ! ffmpeg -hide_banner -loglevel warning -y -i "$src" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k "$out"; then
			echo "Re-encode failed for ${src}" >&2
		fi
	done
	if [ "$found" -eq 0 ]; then
		echo "No source videos found in ${VIDEO_DIR}"
	fi
fi

# Install python script and service unit
sudo install -m 755 "${LOCAL_DIR}/looper.py" "${LOCAL_BIN_DIR}"
sudo install -m 644 "${SERVICE_SRC}" "${SERVICE_DST}"

# Reload and enable the service (starts immediately)
sudo systemctl daemon-reload
sudo systemctl enable --now looper.service
