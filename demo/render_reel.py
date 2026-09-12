#!/usr/bin/env python3
"""
Render reel.html to an MP4, frame by frame.

Instead of screen-recording (which drops frames and depends on your machine's
mood), this seeks the page's timeline to each exact timestamp and screenshots
it. Every frame is perfect, and the output is identical on every machine.

    python render_reel.py                      # 1080x1920, 30fps, full reel
    python render_reel.py --fps 60 --scale 1   # smoother
    python render_reel.py --start 16 --end 22  # just one section, while editing
    python render_reel.py --stills             # one PNG per second, to review

Needs: pip install playwright && playwright install chromium
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920


def find_ffmpeg():
    """
    A full ffmpeg with libx264. Playwright ships an ffmpeg too, but it is a
    cut-down build with only VP8, which Instagram will not take.
    """
    found = shutil.which("ffmpeg")
    if found and _has_x264(found):
        return found
    try:
        import imageio_ffmpeg
        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if _has_x264(candidate):
            return candidate
    except Exception:
        pass
    sys.exit("No ffmpeg with H.264 support found.\n"
             "  macOS:  brew install ffmpeg\n"
             "  or:     pip install imageio-ffmpeg")


def _has_x264(binary):
    try:
        out = subprocess.run([binary, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=30).stdout
        return "libx264" in out
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=os.path.join(HERE, "reel.html"))
    ap.add_argument("--out", default=os.path.join(HERE, "out", "reel.mp4"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=1.0, help="0.5 renders 2x faster for previews")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--stills", action="store_true", help="write one PNG per second instead of video")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    frames_dir = os.path.join(HERE, "raw", "frames")
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    width, height = int(W * args.scale), int(H * args.scale)
    started = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--force-color-profile=srgb", "--font-render-hinting=none",
                  "--disable-lcd-text", "--hide-scrollbars"],
        )
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=1)
        page.goto("file://" + os.path.abspath(args.page) + "?fit=0")
        page.wait_for_function("() => typeof window.__seek === 'function'")
        page.evaluate(f"() => document.getElementById('stage').style.transform = 'scale({args.scale})'")
        duration = args.end if args.end is not None else page.evaluate("() => window.__duration")

        if args.stills:
            out_dir = os.path.join(HERE, "out", "stills")
            os.makedirs(out_dir, exist_ok=True)
            t = args.start
            while t <= duration:
                page.evaluate("t => window.__seek(t)", t)
                page.screenshot(path=os.path.join(out_dir, f"t{t:05.1f}.png"))
                print(f"  still t={t:.1f}s")
                t += 1.0
            browser.close()
            print(f"\nStills in {out_dir}")
            return

        total = int(round((duration - args.start) * args.fps))
        print(f"Rendering {total} frames at {width}x{height}, {args.fps}fps")
        for i in range(total):
            t = args.start + i / args.fps
            page.evaluate("t => window.__seek(t)", t)
            page.screenshot(path=os.path.join(frames_dir, f"f{i:05d}.png"))
            if i % 30 == 0:
                elapsed = time.time() - started
                done = (i + 1) / total
                eta = elapsed / done - elapsed if done else 0
                print(f"  {i:>4}/{total}  t={t:5.2f}s  eta {eta:4.0f}s")
        browser.close()

    ffmpeg = find_ffmpeg()
    print(f"\nEncoding with {ffmpeg}")
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error",
        "-framerate", str(args.fps), "-i", os.path.join(frames_dir, "f%05d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        # Instagram wants even dimensions and a standard profile.
        "-profile:v", "high", "-level", "4.2",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        args.out,
    ], check=True)

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    size_mb = os.path.getsize(args.out) / 1e6
    print(f"\nDone in {time.time() - started:.0f}s -> {args.out}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
