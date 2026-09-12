# Harris County Appointment Checker

The Harris County Tax Office appointment page shows you one branch and one month
at a time, with no way to see what is open anywhere else, and no waitlist. Slots
get released and taken within minutes, so checking by hand means refreshing a
calendar widget forever and hoping you catch one.

This checks all of it for you every 30 minutes and emails you the moment
something opens up.

Runs entirely on GitHub Actions. No server, no API keys, no cost.

## How it works

```
GitHub Actions (cron, every 30 min)
  └─> Playwright (headless Chromium)
        ├─ Loads the hctax.net appointment page
        ├─ Clicks "Make Appointment" for your transaction type
        ├─ Dismisses the info popup
        └─ For each configured branch:
             ├─ Selects it from the dropdown (#ABranch)
             ├─ Clicks the date field (#DatePicker) to open the calendar
             ├─ Reads the whole month in one DOM query:
             │     open   → <td data-handler="selectDay"><a>7</a></td>
             │     taken  → <td class="ui-datepicker-unselectable"><span>8</span></td>
             ├─ Steps forward a month and repeats
             └─ Closes the calendar before the next branch
  └─> Diffs against the last run
  └─> Gmail SMTP → emails only the slots you have not already been told about
```

Reading the calendar's DOM means one query per month instead of probing each
date individually. Five branches × two months takes about 30 seconds.

## What you need

1. A GitHub account (free)
2. A Gmail account with an App Password (2 minutes to set up)

## Setup

### 1. Get the repo

Fork it, or click **Use this template**.

### 2. Create a Gmail App Password

1. [myaccount.google.com](https://myaccount.google.com) → Security
2. Turn on 2-Step Verification if it is not already on
3. **App passwords** → create one for "Mail"
4. Copy the 16-character password

### 3. Add repo secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|---|---|
| `EMAIL_ADDRESS` | The Gmail that sends the alert, e.g. `you@gmail.com` |
| `EMAIL_APP_PASSWORD` | The 16-character App Password (not your login password) |
| `NOTIFY_EMAIL` | Where alerts go — same address is fine |

### 4. Configure the search

Edit `config.json`:

| Key | Meaning |
|---|---|
| `url` | The appointment page. Leave as-is unless the county moves it. |
| `transaction_type` | `New Resident (First time TX registration)`, `Title Transfer`, `Special Plate`, `NMVITS/State Rej`, or `Hold file/2nd floor` |
| `branches` | Locations to watch. Partial names work — `"Downtown"` matches `"Downtown (1001 Preston St)"`. Fewer branches = faster runs. |
| `months_to_check` | Calendar months to scan per branch (1–12, default 2) |
| `notify_subject` | Subject line for the "found something" email |
| `only_notify_on_new` | `true` (default) emails you only about slots you have not already been told about |
| `notify_when_none` | `false` (default). Set `true` if you want a heartbeat email on every empty run. |

### 5. Turn it on

**Actions** tab → enable workflows → **Run workflow** to test it immediately.

## The emails

| Result | What you get |
|---|---|
| New slots | Green email: branches and dates grouped by month, with a **Book Now** link |
| Same slots as last run | Nothing — you were already told |
| Nothing open | Nothing, unless `notify_when_none` is `true` |
| The check itself broke | Red "Checker Could Not Run" email, so a site redesign never looks like "no availability" |

That last row is the important one. A scraper that silently reports "no slots"
when it is actually broken is worse than no scraper at all.

## Running it locally

```bash
pip install -r requirements-dev.txt
playwright install chromium

python checker.py --no-email                # check for real, print, send nothing
python checker.py --headful                 # watch the browser do it
python checker.py --json results.json       # also dump results as JSON
```

| Flag | Effect |
|---|---|
| `--no-email` | Print results, send no email |
| `--headful` | Show the browser window |
| `--no-state` | Ignore the seen-slots file (report everything as new) |
| `--url` | Point at a different page — used by the tests |
| `--json PATH` | Write the slot list to a JSON file |
| `--config PATH` | Use a different config file |

Exit codes: `0` ran fine, `2` the check failed (a failure email was attempted).

## Tests

```bash
python -m pytest tests -v
```

27 tests, no network required. `tests/fixtures/mock_appointment_page.html` is a
local stand-in that reproduces the DOM shape of the real page — the verbose
dropdown labels, the red unselectable days, the greyed padding days from
adjacent months — so the scraping logic is tested without hammering the county's
server. Tests also run on every push via `.github/workflows/tests.yml`.

## Error handling

| Scenario | Behavior |
|---|---|
| Missing or malformed `config.json` | Exits listing every problem at once |
| Missing email secrets | Names which ones are missing, keeps going |
| Wrong app password | "Gmail rejected the login" rather than a generic SMTP trace |
| Page slow or flaky | 3 load attempts, 30s each |
| Branch name not in the dropdown | Warns, prints the real option list, checks the rest |
| Site layout changed | Error email + debug screenshot uploaded as an Actions artifact |
| One branch errors mid-run | Logged, remaining branches still checked |

## Cost

$0. GitHub Actions gives 2,000 free minutes/month. A run is roughly 1 minute
including setup; every 30 minutes is about 1,400 minutes/month. If you want more
headroom, widen the cron or trim `branches`.

## Layout

```
├── .github/workflows/check.yml   # the scheduled checker
├── .github/workflows/tests.yml   # CI
├── checker.py                    # everything: scrape + email
├── config.json                   # what to watch
├── requirements.txt
├── tests/
│   ├── test_checker.py
│   └── fixtures/mock_appointment_page.html
└── demo/                         # tooling for the demo video (see demo/README.md)
```

## Adapting it

The calendar-reading logic works on any page using a jQuery UI datepicker —
other county DMV sites, visa appointments, anything with scarce slots. Point
`url` at the page, adjust the selectors in `find_branch_dropdown()` and
`find_date_input()`, and the rest carries over.

## Stopping it

Actions tab → the workflow → **Disable workflow**.

## A note on being a good citizen

This checks a public page on a modest schedule — the same page you would be
refreshing by hand, just less often than you would refresh it. Keep the cadence
reasonable and the branch list short. Do not turn it into a booking bot.

## License

MIT.
