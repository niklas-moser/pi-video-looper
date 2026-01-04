#!/usr/bin/python3
import glob
import os
import signal
import subprocess
import time
import threading

from gpiozero import Button, RotaryEncoder

VIDEO_DIR = "/media/videos"
BRIGHTNESS_GLOB = "/sys/class/backlight/*/brightness"
MAX_GLOB = "/sys/class/backlight/*/max_brightness"

BTN_CONTROL = 17
ENC_A = 23
ENC_B = 24
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


def list_videos():
    files = []
    for ext in ("*.mp4", "*.mkv", "*.mov"):
        files += glob.glob(os.path.join(VIDEO_DIR, ext))
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

    files = list_videos()
    if not files:
        print("No videos found in", VIDEO_DIR)
        while True:
            time.sleep(5)

    idx = 0
    p = start_gst(files[idx])

    button_press_time = None
    btn = None
    enc = None

    # Button requests are handled by the main loop only (prevents races/double-starts).
    lock = threading.Lock()
    pending_delta = 0  # +N => next N, -N => previous N

    try:
        btn = Button(BTN_CONTROL, pull_up=True, bounce_time=0.05)
        enc = RotaryEncoder(ENC_A, ENC_B, max_steps=0)
        print("GPIO controls initialized")
    except Exception as e:
        print(f"GPIO init failed: {e}. Running video playback only.")
        btn = None
        enc = None

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
            request_switch(+1)  # Short press: next

    if btn:
        btn.when_pressed = on_btn_pressed
        btn.when_released = on_btn_released

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

        if delta != 0:
            files = list_videos()
            if files:
                idx = (idx + delta) % len(files)
                stop_proc(p)
                p = start_gst(files[idx])

        # If video ends for any reason, restart same file
        if p and p.poll() is not None:
            p = start_gst(files[idx])

        time.sleep(0.02)


if __name__ == "__main__":
    main()
