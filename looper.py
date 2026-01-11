#!/usr/bin/python3
import glob
import os
import signal
import subprocess
import time
import threading

from gpiozero import Button, RotaryEncoder

VIDEO_DIR = "/media/videos"
DOUBLE_PRESS_WINDOW = 0.35  # seconds for detecting double-tap on BTN_CONTROL
BRIGHTNESS_GLOB = "/sys/class/backlight/*/brightness"
MAX_GLOB = "/sys/class/backlight/*/max_brightness"

BTN_CONTROL = 17
ENC_A = 23
ENC_B = 24
ENC_BTN = 27  # Encoder button (push to power off)
LONG_PRESS_TIME = 1.0  # seconds

# After stopping playback, wait a moment so the decoder/sink can release resources.
# If you still see flaky behavior, try 2.0–5.0 seconds.
STOP_DELAY_S = 1.0


def pick_backlight():
    b = glob.glob(BRIGHTNESS_GLOB)
    m = glob.glob(MAX_GLOB)
    if not b or not m:
        return None, None
    # Use the first backlight device found
    return b[0], m[0]


def set_brightness(path, value, maxv):
    v = max(0, min(int(value), int(maxv)))
    with open(path, "w") as f:
        f.write(str(v))


def list_categories():
    # Immediate subdirectories under VIDEO_DIR define categories; include root if none exist
    subs = []
    try:
        for entry in sorted(os.listdir(VIDEO_DIR)):
            full = os.path.join(VIDEO_DIR, entry)
            if os.path.isdir(full):
                subs.append(entry)
    except FileNotFoundError:
        pass
    return subs if subs else [""]


def list_videos(category):
    base = os.path.join(VIDEO_DIR, category) if category else VIDEO_DIR
    files = []
    for ext in ("*.mp4", "*.mkv", "*.mov"):
        files += glob.glob(os.path.join(base, ext))
    return sorted(files)


def start_gst(filepath):
    # Hardware decode H.264 via v4l2h264dec; render via KMS
    cmd = [
        "gst-launch-1.0",
        "-q",
        "filesrc",
        f"location={filepath}",
        "!",
        "qtdemux",
        "name=demux",
        "demux.video_0",
        "!",
        "h264parse",
        "!",
        "v4l2h264dec",
        "!",
        "videoconvert",
        "!",
        "kmssink",
    ]
    return subprocess.Popen(cmd, preexec_fn=os.setsid)


def stop_proc(p):
    if p and p.poll() is None:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            p.wait()  # Wait for SIGKILL to complete
    time.sleep(STOP_DELAY_S)


def main():
    bl_path, max_path = pick_backlight()
    maxv = int(open(max_path).read().strip()) if max_path else 255
    cur_b = int(open(bl_path).read().strip()) if bl_path else 128

    categories = list_categories()
    if not categories:
        print("No categories found in", VIDEO_DIR)
        while True:
            time.sleep(5)

    cat_idx = 0
    current_cat = categories[cat_idx]

    # Find first category that has videos; otherwise wait
    attempt = 0
    files = []
    while attempt < len(categories):
        files = list_videos(current_cat)
        if files:
            break
        cat_idx = (cat_idx + 1) % len(categories)
        current_cat = categories[cat_idx]
        attempt += 1

    if not files:
        print("No videos found in any category under", VIDEO_DIR)
        while True:
            time.sleep(5)

    idx = 0
    p = start_gst(files[idx])

    button_press_time = None
    btn = None
    enc = None
    enc_btn = None

    # Button requests are handled by the main loop only (prevents races/double-starts).
    lock = threading.Lock()
    pending_delta = 0  # +N => next N, -N => previous N
    pending_cat_delta = 0  # +1 => next category, -1 => previous category
    last_short_release = 0.0

    try:
        btn = Button(BTN_CONTROL, pull_up=True, bounce_time=0.05)
        enc = RotaryEncoder(ENC_A, ENC_B, max_steps=0)
        enc_btn = Button(ENC_BTN, pull_up=True, bounce_time=0.05)
        print("GPIO controls initialized")
    except Exception as e:
        print(f"GPIO init failed: {e}. Running video playback only.")
        btn = None
        enc = None
        enc_btn = None

    last_steps = enc.steps if enc else 0

    def request_switch(delta):
        nonlocal pending_delta
        with lock:
            pending_delta += int(delta)

    def on_btn_pressed():
        nonlocal button_press_time
        button_press_time = time.time()

    def on_btn_released():
        nonlocal button_press_time
        if button_press_time is None:
            return
        press_duration = time.time() - button_press_time
        button_press_time = None

        if press_duration >= LONG_PRESS_TIME:
            request_switch(-1)  # Long press: previous
        else:
            # Short press: immediate next; second short within window switches category
            now = time.time()
            with lock:
                if last_short_release and (now - last_short_release) <= DOUBLE_PRESS_WINDOW:
                    pending_cat_delta += 1
                else:
                    pending_delta += 1
                last_short_release = now

    def on_enc_btn_pressed():
        # Power off the Pi when encoder button is pressed
        print("Encoder button pressed - powering off...")
        stop_proc(p)
        subprocess.run(["sudo", "poweroff"])

    if btn:
        btn.when_pressed = on_btn_pressed
        btn.when_released = on_btn_released

    if enc_btn:
        enc_btn.when_pressed = on_enc_btn_pressed

    while True:
        # Encoder controls brightness
        if enc:
            steps = enc.steps
            if steps != last_steps and bl_path:
                delta = steps - last_steps
                last_steps = steps
                cur_b = cur_b + delta * 8  # step size
                set_brightness(bl_path, cur_b, maxv)

        # Apply any pending button-requested switches (main loop only)
        with lock:
            delta = pending_delta
            pending_delta = 0

            cat_delta = pending_cat_delta
            pending_cat_delta = 0

        if cat_delta != 0:
            categories = list_categories()
            if categories:
                tried = 0
                while tried < len(categories):
                    cat_idx = (cat_idx + cat_delta) % len(categories)
                    current_cat = categories[cat_idx]
                    files = list_videos(current_cat)
                    if files:
                        idx = 0
                        stop_proc(p)
                        p = start_gst(files[idx])
                        break
                    tried += 1
                if tried >= len(categories):
                    stop_proc(p)
                    p = None
                    print("No playable videos found in any category")

        if delta != 0:
            files = list_videos(current_cat)
            if files:
                idx = (idx + delta) % len(files)
                stop_proc(p)
                p = start_gst(files[idx])
            else:
                print(f"No videos in category '{current_cat}'")

        # If video ends for any reason, restart same file
        if p and p.poll() is not None:
            p = start_gst(files[idx])

        time.sleep(0.02)


if __name__ == "__main__":
    main()
