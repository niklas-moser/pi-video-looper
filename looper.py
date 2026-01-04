#!/usr/bin/python3
import glob, os, signal, subprocess, time
from gpiozero import Button, RotaryEncoder

VIDEO_DIR = "/media/videos"
BRIGHTNESS_GLOB = "/sys/class/backlight/*/brightness"
MAX_GLOB = "/sys/class/backlight/*/max_brightness"

BTN_CONTROL = 17
ENC_A = 23
ENC_B = 24
LONG_PRESS_TIME = 1.0  # seconds

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

    btn_next = btn_prev = enc = None
    button_press_time = None
    try:
        btn = Button(BTN_CONTROL, pull_up=True, bounce_time=0.05)
        enc = RotaryEncoder(ENC_A, ENC_B, max_steps=0)
        print("GPIO controls initialized")
    except Exception as e:
        print(f"GPIO init failed: {e}. Running video playback only.")
        btn = None

    last_steps = enc.steps if enc else 0

    def load(i):
        nonlocal idx, p, files
        files = list_videos()
        if not files:
            return
        idx = i % len(files)
        stop_proc(p)
        p = start_gst(files[idx])

    def on_btn_pressed():
        nonlocal button_press_time
        button_press_time = time.time()

    def on_btn_released():
        nonlocal button_press_time
        if button_press_time is not None:
            press_duration = time.time() - button_press_time
            if press_duration >= LONG_PRESS_TIME:
                load(idx - 1)  # Long press: previous
            else:
                load(idx + 1)  # Short press: next
            button_press_time = None

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
        # If video ends for any reason, restart same file
        if p.poll() is not None:
            p = start_gst(files[idx])
        time.sleep(0.02)

if __name__ == "__main__":
    main()
