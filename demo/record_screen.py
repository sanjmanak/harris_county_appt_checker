#!/usr/bin/env python3
"""
Record real footage of the county site for B-roll.

This drives the actual appointment page in a real browser and records it, with a
drawn cursor so the viewer can follow what is being clicked. Use the output for
the "look how bad this is" shots — real footage beats a recreation.

    python record_screen.py                        # 1080x1920 portrait, real site
    python record_screen.py --landscape            # 1920x1080
    python record_screen.py --slow 2               # half speed, easier to cut
    python record_screen.py --url file://.../mock_appointment_page.html

Output: demo/out/screen.mp4 (plus the raw .webm Playwright writes).

Note: this is your own browsing, automated. Keep it to a couple of takes rather
than looping it — it is the county's server.
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

CURSOR_JS = """
() => {
  const c = document.createElement('div');
  c.id = '__cursor';
  c.style.cssText = `position:fixed;z-index:2147483647;width:34px;height:34px;
    margin:-17px 0 0 -17px;border-radius:50%;pointer-events:none;
    background:rgba(31,214,95,.25);border:3px solid #1FD65F;
    box-shadow:0 0 30px rgba(31,214,95,.6);transition:all .35s cubic-bezier(.16,1,.3,1);
    left:-100px;top:-100px;`;
  document.body.appendChild(c);
  window.__moveCursor = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
  window.__clickPulse = () => {
    c.animate([{ transform: 'scale(1)' }, { transform: 'scale(.6)' },
               { transform: 'scale(1)' }], { duration: 320, easing: 'ease-out' });
  };
}
"""


def point_at(page, selector, settle=900):
    """Move the drawn cursor onto an element, pause, then click it."""
    el = page.query_selector(selector)
    if not el:
        print(f"  (skipped, not on page: {selector})")
        return False
    box = el.bounding_box()
    if not box:
        return False
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.evaluate("([x, y]) => window.__moveCursor(x, y)", [x, y])
    page.wait_for_timeout(settle)
    page.evaluate("() => window.__clickPulse()")
    el.click()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="defaults to the url in config.json")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "screen.mp4"))
    ap.add_argument("--landscape", action="store_true")
    ap.add_argument("--slow", type=float, default=1.0, help="2 = half speed")
    ap.add_argument("--months", type=int, default=3, help="how many next-month clicks to film")
    args = ap.parse_args()

    import checker
    from playwright.sync_api import sync_playwright

    config = checker.load_config()
    url = args.url or config["url"]
    w, h = (1920, 1080) if args.landscape else (1080, 1920)
    raw_dir = os.path.join(HERE, "raw", "screen")
    shutil.rmtree(raw_dir, ignore_errors=True)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    pause = lambda ms: page.wait_for_timeout(int(ms * args.slow))  # noqa: E731

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--hide-scrollbars"])
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            record_video_dir=raw_dir,
            record_video_size={"width": w, "height": h},
            device_scale_factor=2,
        )
        page = ctx.new_page()
        print(f"Recording {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        page.evaluate(CURSOR_JS)
        # Zoom in so the calendar reads on a phone screen.
        page.evaluate("() => { document.body.style.zoom = '1.35'; }")
        pause(1200)

        try:
            checker.open_appointment_form(page, config.get("transaction_type", ""))
            page.evaluate(CURSOR_JS)          # popup may have replaced the body
            pause(1200)

            branch_sel = checker.find_branch_dropdown(page, config["branches"]) or "#ABranch"
            date_sel = checker.find_date_input(page) or "#DatePicker"
            resolved = checker.resolve_branch_options(page, branch_sel, config["branches"])

            for branch in resolved[:3]:
                print(f"  filming {branch['name']}")
                page.select_option(branch_sel, value=branch["value"])
                pause(1100)
                point_at(page, date_sel, settle=700)
                pause(1600)                    # let the red calendar sit on screen
                for _ in range(args.months - 1):
                    if not point_at(page, ".ui-datepicker-next", settle=500):
                        break
                    pause(1300)
                checker.close_calendar(page)
                pause(600)
        except Exception as e:
            print(f"  stopped early: {e}")

        video = page.video
        ctx.close()
        browser.close()
        src = video.path() if video else None

    if not src:
        src = next(iter(glob.glob(os.path.join(raw_dir, "*.webm"))), None)
    if not src:
        sys.exit("No video was captured.")

    from render_reel import find_ffmpeg
    print(f"\nConverting {src}")
    subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-i", src,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out], check=True)
    print(f"Done -> {args.out}")


if __name__ == "__main__":
    main()
