#!/bin/bash
set -uo pipefail

# Convert each video in this folder to H.264 (no scaling) and build ~30 minute loops

OUTPUT_DIR="converted_pi"
TARGET_SECONDS=1800

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found" >&2; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "ffprobe not found" >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"
shopt -s nullglob

count=0

for video in *.mp4 *.MP4 *.avi *.AVI *.mov *.MOV *.mkv *.MKV; do
    [ -e "$video" ] || continue
    [[ "$video" == "$OUTPUT_DIR"* ]] && continue

    filename="${video%.*}"
    single="$OUTPUT_DIR/${filename}_pi.mp4"
    output="$OUTPUT_DIR/${filename}_pi_30min.mp4"

    if [ -f "$output" ]; then
        echo "Skipping $video (already converted to 30 min)."
        # Clean up any lingering single-encode to save space
        [ -f "$single" ] && rm -f "$single"
        continue
    fi

    echo "========================================="
    echo "Processing: $video"
    echo "Single encode: $single"
    echo "Target (30 min): $output"
    echo "========================================="

    if [ ! -f "$single" ]; then
        echo "Encoding source to H.264 once..."
        if ! ffmpeg -i "$video" \
            -c:v libx264 -preset slow -profile:v high -level 4.0 -crf 23 -pix_fmt yuvj420p \
            -c:a aac -b:a 192k -ac 2 -ar 44100 \
            -movflags +faststart \
            "$single"; then
            echo "✗ Failed initial encode: $video"
            echo ""
            continue
        fi
    else
        echo "Single encode already exists; reusing."
    fi

    duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$single" || true)
    if [[ -z "$duration" ]]; then
        echo "✗ Could not read duration, skipping: $video"
        echo ""
        continue
    fi

    repeats=$(python3 - <<PY
import math
d = float("${duration}") if "${duration}" else 0.0
print(max(1, math.ceil(${TARGET_SECONDS} / d))) if d > 0 else print(0)
PY
)

    if [[ "$repeats" -le 0 ]]; then
        echo "✗ Invalid duration, skipping: $video"
        echo ""
        continue
    fi

    concat_list=$(mktemp)
    single_path=$(realpath "$single")
    for ((i=0; i<repeats; i++)); do
        printf "file '%s'\n" "$single_path" >> "$concat_list"
    done

    echo "Concatenating $repeats times to reach ~30 minutes..."
    if ffmpeg -f concat -safe 0 -i "$concat_list" -c copy -movflags +faststart "$output"; then
        echo "✓ Created 30-minute loop: $output"
        ((count++))
        rm -f "$single"  # drop intermediate to save space; re-created next run if needed
    else
        echo "✗ Failed concat: $video"
    fi

    rm -f "$concat_list"
    echo ""
done

echo "========================================="
echo "Conversion complete!"
echo "Processed $count video(s)"
echo "Converted videos are in: $OUTPUT_DIR/"
echo "========================================="

# Final cleanup: remove any leftover single encodes when a 30-minute output exists
for tmp in "$OUTPUT_DIR"/*_pi.mp4; do
    [ -e "$tmp" ] || continue
    base="${tmp%_pi.mp4}"
    if [ -f "${base}_pi_30min.mp4" ]; then
        rm -f "$tmp"
    fi
done
