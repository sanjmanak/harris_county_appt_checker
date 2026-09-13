# Three reel scripts

All three are 27–30s, built for the same retention shape:

| Seconds | Job |
|---|---|
| 0–3 | A concrete, visual complaint. No setup, no "so basically". |
| 3–7 | The payoff stated as a number, so the viewer has a reason to stay. |
| 7–12 | Twist the knife on the problem — this is the part people relate to. |
| 12–19 | How it works, in one sentence they could repeat to a friend. |
| 19–25 | The moment it pays off. The single most satisfying beat in the video. |
| 25–29 | The takeaway + one clear ask. |

Read the VO fast and flat. Do not pause between lines — the cuts do the
pacing. `[ ]` is what is on screen; **bold** is the burned-in caption.

---

## Script 1 — "Every single day" (this is what `reel.mp4` is cut to)

Best cold-open of the three. The visual does the complaining for you.

| Time | VO | Screen |
|---|---|---|
| 0:00 | "Every single day at the Harris County tax office was booked." | [ calendar fills in red, day by day ] **EVERY SINGLE DAY.** |
| 0:03 | "Four months out. For a ten-minute vehicle registration." | [ hold on the red wall ] |
| 0:04 | "I had one in twenty-nine minutes." | [ hard cut to black, timer runs up to 29:14 ] **29:14** |
| 0:07 | "Here's the thing about that site — you can only see one branch, one month at a time." | [ branch dropdown cycling, each calendar red ] |
| 0:10 | "Five locations, two months. That's ten calendars you're refreshing by hand." | **= 10 calendars. By hand.** |
| 0:12 | "So I stopped." | [ cut to code ] |
| 0:13 | "I wrote about forty lines of Python that opens every calendar and reads every day." | [ code types in ] |
| 0:16 | "GitHub runs it free, every thirty minutes, forever. No server. No app." | [ chips light up: runs on GitHub / no server / $0 ] |
| 0:19 | "It checked a hundred and forty-three times while I slept." | [ log rows stack, all ✗, counter climbing ] |
| 0:21 | "Then at 6am —" | [ one row snaps green, punch in ] **2 slots — Downtown** |
| 0:22 | "— it emailed me." | [ email card slides up ] |
| 0:24 | "Two slots. Downtown. April seventh." | [ Book Now, tap ] **Booked in 4 taps.** |
| 0:26 | "The site never changed. I just stopped watching it." | [ end card ] **Same site. Same wait.** |
| 0:28 | "It's open source — comment SLOT and I'll send it." | **comment SLOT** |

---

## Script 2 — "I got beat by a guy with a bot" (self-aware, funnier)

Same footage, different edit. Leads with the absurdity instead of the pain.
Cut S1 (`0–3.35`) shorter and open on the terminal instead.

| Time | VO | Screen |
|---|---|---|
| 0:00 | "There is no waitlist for a Houston vehicle registration appointment." | [ red calendar wall ] **NO WAITLIST.** |
| 0:03 | "There's no alert. No 'notify me.' Nothing." | [ hold ] |
| 0:04 | "The system is: refresh the page and be lucky." | **refresh & be lucky** |
| 0:07 | "So I automated being lucky." | [ cut to code ] |
| 0:09 | "Forty lines of Python. It opens the appointment page, picks each branch, opens the calendar, and reads which days aren't red." | [ code types in ] |
| 0:14 | "That's it. That's the whole trick." | [ chips light up ] |
| 0:16 | "GitHub Actions runs it every thirty minutes for free — I don't own a server, it's not an app, it costs zero dollars." | [ log rows stacking ] |
| 0:20 | "A hundred and forty-three checks later, 6:02 in the morning —" | [ green row, punch in ] |
| 0:22 | "— my phone buzzes. Two slots." | [ email card ] |
| 0:24 | "Booked before I got out of bed." | **Booked in 4 taps.** |
| 0:26 | "I didn't hack anything. I just refused to refresh a webpage nine hundred times." | [ end card ] |
| 0:28 | "Code's free — comment SLOT." | **comment SLOT** |

---

## Script 3 — "Do this for anything" (the one that travels furthest)

Same story, but the last third generalizes. Post this one if you want reach
beyond Houston — it works for anyone who has ever fought a booking page.

| Time | VO | Screen |
|---|---|---|
| 0:00 | "This calendar is why I almost drove to Katy to register a car." | [ red calendar wall ] |
| 0:02 | "Every day booked, four months out." | **EVERY SINGLE DAY.** |
| 0:04 | "I got an appointment in twenty-nine minutes instead. Here's the whole thing." | [ 29:14 ] |
| 0:07 | "Step one: the site only shows one branch and one month at a time — that's the actual problem." | [ dropdown cycling ] |
| 0:10 | "Step two: a script that clicks through all of them and reads the calendar." | [ code ] |
| 0:13 | "Step three: GitHub runs that script every thirty minutes, free, forever." | [ chips ] |
| 0:16 | "Step four: when a day isn't red, it emails me." | [ log rows → green row ] |
| 0:19 | "That's the entire system. Four steps." | [ punch in ] |
| 0:21 | "6:02am, two slots, booked from bed." | [ email → Booked ] |
| 0:24 | "And it's not a Houston thing — this works on any booking page with a calendar. DMV, visa appointments, campsites, doctors." | [ end card ] |
| 0:27 | "Same trick. Comment SLOT and I'll send you the code." | **comment SLOT** |

---

## Caption + cover

**Caption (any of the three):**

> Harris County had zero appointments for four months. I got one in 29 minutes.
> The site only lets you see one branch and one month at a time — so a script
> checks all of them every 30 minutes and emails me when a day opens up. Runs
> free on GitHub. No server, no app, no $49 "expediter."
>
> Comment SLOT and I'll send you the repo.
>
> #houston #htx #htxlife #vehicleregistration #python #automation #buildinpublic
> #codingtips #lifehack #texasdmv

**Cover frame:** `demo/out/stills/t003.0.png` — the red wall under **EVERY SINGLE DAY.**

## Two notes before you post

- Everything in the reel is motion graphics. If you want the real site on
  screen — and it is more convincing — shoot it with `record_screen.py` and cut
  it in over 0:07–0:10. Real footage of the actual calendar beats a recreation.
- Don't imply the tool books the appointment. It watches and emails; you book.
  "It emailed me and I booked it" is both true and a better line anyway.
