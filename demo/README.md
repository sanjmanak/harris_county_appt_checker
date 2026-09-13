# demo/ — making the video

Three tools. All of them run locally, all of them produce files in `demo/out/`.

```bash
pip install -r requirements-demo.txt
playwright install chromium
```

## 1. The reel — `render_reel.py`

Renders `reel.html` to a finished 1080×1920 MP4. It does **not** screen-record:
it seeks the page's animation timeline to each exact timestamp and screenshots
it, so every frame is perfect and the output is identical on any machine.

```bash
python render_reel.py                      # → out/reel.mp4  (32s, 30fps, H.264)
python render_reel.py --fps 60             # smoother, twice the render time
python render_reel.py --stills             # one PNG per second, to check framing
python render_reel.py --start 16 --end 22  # re-render one section while editing
```

A full 32s render takes about 15 minutes on a laptop. Use `--scale 0.5` for fast previews.

### Editing the reel

Everything lives in `reel.html`. To preview while you work, open it in a
browser: `reel.html?play=1` loops it, `reel.html?t=19.4` freezes one moment.

The timeline is at the bottom of the file. Each scene is a block:

```js
scene('s5', 16.15, 21.75);     // this scene is on screen from 16.15s to 21.75s
track('s5k', [...]);           // one element's animation, as waypoints in seconds
```

**One rule:** each element gets exactly one `track()` per property group. Two
animations on the same element will fight over the same property and one will
win at every timestamp — that is the bug that made every scene show at once the
first time around.

To change the copy, edit the HTML in the scene's `<div class="scene">` block.
To retime a beat, change the numbers in its `track()` call. Nothing else needs
to move.

## 2. Real footage of the site — `record_screen.py`

The reel is motion graphics. If you want the actual county page on screen —
and you should, it is more convincing than any recreation — this drives the
real site in a visible browser with a drawn cursor and records it.

```bash
python record_screen.py              # → out/screen.mp4, portrait
python record_screen.py --slow 2     # half speed, easier to cut on the beat
python record_screen.py --landscape
```

Cut the best 2–3 seconds of red calendar over the 0:07–0:10 section of the reel.

It is your own browsing, automated. Run it a couple of times, not in a loop.

## 3. The email shot — `render_email.py`

Renders the alert email the checker actually sends, as a transparent-edged PNG.
It calls the same `build_found_email()` the live tool uses, so what is on
screen is the real thing.

```bash
python render_email.py               # → out/email_found.png
python render_email.py --kind error  # the "checker broke" email
```

## Putting it together

The rendered `out/reel.mp4` is postable as-is — record the voiceover over it in
Instagram, or drop it into CapCut and lay the VO on top.

If you want to cut real footage in, the edit is:

| Reel time | Replace with |
|---|---|
| 7.0 – 11.4 | `screen.mp4` — the branch dropdown and red calendars |
| 22.0 – 25.8 | a screen recording of the real email on your phone |

Both sections are self-contained scenes, so you can cut them out without
breaking anything around them.

## The v2 reel — `reel_v2.html`

Same engine, new scenes, cut to `script_v2.txt`. Render it with:

```bash
python render_reel.py --page reel_v2.html --out out/reel_v2.mp4
```

Scripts and captions: [SCRIPTS.md](SCRIPTS.md).
