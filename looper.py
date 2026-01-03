#!/usr/bin/python3
import glob, os, signal, subprocess, time
from gpiozero import Button, RotaryEncoder

VIDEO_DIR = "/media/videos"
BRIGHTNESS_GLOB = "/sys/class/backlight/*/brightness"
MAX_GLOB = "/sys/class/backlight/*/max_brightness"

BTN_NEXT = 17
BTN_PREV = 27
ENC_A = 23
ENC_B = 24

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
    for ext in ("*.mp4","*.mkv","*.mov"):
        files += glob.glob(os.path.join(VIDEO_DIR, ext))
    return sorted(files)

def start_gst(filepath):
    # Hardware decode H.264 via v4l2h264dec; render via KMS
    cmd = [
        "gst-launch-1.0", "-q",
        "filesrc", f"location={filepath}", "!", "qtdemux", "name=demux",
        "demux.video_0", "!", "h264parse", "!", "v4l2h264dec", "!",
        "videoconvert", "!", "kmssink"
    ]
    return subprocess.Popen(cmd, preexec_fn=os.setsid)

def stop_proc(p):
    if p and p.poll() is None:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)

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

    btn_next = Button(BTN_NEXT, pull_up=True, bounce_time=0.05)
    btn_prev = Button(BTN_PREV, pull_up=True, bounce_time=0.05)
    enc = RotaryEncoder(ENC_A, ENC_B, max_steps=0)

    last_steps = enc.steps

    def load(i):
        nonlocal idx, p, files
        files = list_videos()
        if not files:
            return
        idx = i % len(files)
        stop_proc(p)
        p = start_gst(files[idx])

    btn_next.when_pressed = lambda: load(idx + 1)
    btn_prev.when_pressed = lambda: load(idx - 1)

    while True:
        # Encoder controls brightness
        steps = enc.steps
        if steps != last_steps and bl_path:
            delta = steps - last_steps
            last_steps = steps
            cur_b = cur_b + delta * 8  # step size
            set_brightness(bl_path, cur_b, maxv)
        # If video ends for any reason, restart same file
        if p.poll() is not None:
            p = start_gst(files[idx])
        time.sleep(0.02)

if __name__ == "__main__":
    main()
