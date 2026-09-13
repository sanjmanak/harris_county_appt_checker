#!/usr/bin/env python3
"""
Render the checker's real alert email to a PNG, for use as a shot in the video.

It calls the same build_found_email() the live checker uses, so what you put on
screen is the email the tool actually sends -- not a mockup of it.

    python render_email.py
    python render_email.py --kind none     # the "nothing open" email
    python render_email.py --kind error    # the "checker broke" email
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import checker  # noqa: E402

SLOTS = [
    {"branch": "Downtown", "day": 7, "month_label": "April 2026", "iso": "2026-04-07"},
    {"branch": "Spring Branch", "day": 9, "month_label": "April 2026", "iso": "2026-04-09"},
    {"branch": "Burnett Bayland", "day": 21, "month_label": "April 2026", "iso": "2026-04-21"},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["found", "none", "error"], default="found")
    ap.add_argument("--out", default=None)
    ap.add_argument("--width", type=int, default=760)
    args = ap.parse_args()

    config = checker.load_config()
    url = config["url"]
    if args.kind == "found":
        _, _, html_body = checker.build_found_email(config, SLOTS, url)
    elif args.kind == "none":
        _, _, html_body = checker.build_none_found_email(config, config["branches"], url)
    else:
        _, _, html_body = checker.build_error_email(config, "Branch dropdown not found", url)

    out = args.out or os.path.join(HERE, "out", f"email_{args.kind}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": 900},
                                device_scale_factor=3)
        page.set_content(html_body)
        page.wait_for_timeout(300)
        # Crop to the email itself -- the body is full-viewport height otherwise.
        box = page.evaluate("""() => {
            const kids = [...document.body.children];
            const right = Math.max(...kids.map(e => e.getBoundingClientRect().right));
            const bottom = Math.max(...kids.map(e => e.getBoundingClientRect().bottom));
            const left = Math.min(...kids.map(e => e.getBoundingClientRect().left));
            return { x: left - 12, y: -12, width: right - left + 24, height: bottom + 24 };
        }""")
        page.screenshot(path=out, clip={k: max(0, v) if k in ('x', 'y') else v
                                        for k, v in box.items()})
        browser.close()
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
