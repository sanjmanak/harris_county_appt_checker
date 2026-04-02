# Harris County Appointment Checker

A zero-cost automated monitor that checks the Harris County Tax Office website for available auto appointment slots and emails you the results — whether it finds openings or not.

Runs entirely on GitHub Actions. No local machine. No servers. No API keys.

## How It Works

```
GitHub Actions (cron every 30 min)
  └─> Playwright (headless Chromium)
        ├─ Navigates to hctax.net appointment page
        ├─ Clicks "Make Appointment" for your transaction type
        ├─ Dismisses the info popup
        └─ For each configured branch:
             ├─ Selects the branch from the dropdown (#ABranch)
             ├─ Clicks the date input (#DatePicker) to open the calendar
             ├─ Reads the jQuery UI datepicker in one DOM query:
             │     Available dates → <td data-handler="selectDay"><a>5</a></td>
             │     Unavailable (red) → <td class="ui-datepicker-unselectable"><span>12</span></td>
             ├─ Navigates to the next month via the ► arrow
             └─ Repeats for configured number of months
  └─> Gmail SMTP
        ├─ Slots found → styled HTML email with dates + "Book Now" link
        └─ No slots → "No Appointments Found" email so you know it ran
```

The calendar-reading approach checks all dates in a month with a single DOM query instead of testing each date individually. A full run across 5 branches typically completes in under 30 seconds.

## What You Need

1. A GitHub account (free)
2. A Gmail account with an App Password (2 minutes to set up)

That's it. No AI API keys. No paid services.

## Setup (5 minutes)

### Step 1: Get this repo on GitHub

Click **"Use this template"** or fork it. Or create a new repo and upload these files through the GitHub web interface.

### Step 2: Create a Gmail App Password

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Security → 2-Step Verification (enable if not already on)
3. Bottom of that page → **App passwords**
4. Create one for "Mail" / "Other" — name it whatever you want
5. Copy the 16-character password

### Step 3: Add secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions**

Add these three secrets:

| Secret Name | Value |
|---|---|
| `EMAIL_ADDRESS` | Your Gmail (e.g., `you@gmail.com`) |
| `EMAIL_APP_PASSWORD` | The 16-character app password |
| `NOTIFY_EMAIL` | Where alerts go (can be same Gmail or different) |

### Step 4: Configure your search

Edit `config.json`:

```json
{
  "url": "https://www.hctax.net/Auto/Appointments/Appointment",
  "transaction_type": "New Resident (First time TX registration)",
  "branches": [
    "Downtown",
    "Burnett Bayland",
    "Spring Branch",
    "Palm Center",
    "Mickey Leland"
  ],
  "months_to_check": 2,
  "notify_subject": "🚨 Harris County Auto Appointment Available!"
}
```

**transaction_type** — which service you need. Options from the site:
- `New Resident (First time TX registration)`
- `Title Transfer`
- `Special Plate`
- `NMVITS/State Rej`
- `Hold file/2nd floor`

**branches** — which locations to check. All 16 Harris County branches are supported. Fewer branches = faster checks. The default set covers locations near central Houston / Montrose.

**months_to_check** — how many calendar months to scan per branch (default: 2). The checker reads the current month, then clicks the next-month arrow to check additional months.

### Step 5: Enable the workflow

Go to the **Actions** tab and enable workflows if prompted. You can also click **"Run workflow"** to test it immediately.

## Email Notifications

You get an email every run:

- **Slots found** — styled HTML email listing each branch + available dates, with a direct "Book Now" link to the appointment page
- **No slots found** — brief email confirming the checker ran and found nothing, so you know it's still working

## Error Handling

| Scenario | Behavior |
|---|---|
| Missing/malformed `config.json` | Exits with clear error message |
| Missing or empty email secrets | Logs which variables are missing, skips email |
| Wrong Gmail app password | Specific "authentication failed" error (not generic) |
| Gmail SMTP down or slow | 30-second timeout, logs network error |
| Page load timeout | 30-second limit, logs and exits cleanly |
| Branch not found in dropdown | Auto-discovers dropdown by ID, then by content matching |
| Calendar doesn't open | Logs error, moves to next branch |

The workflow always exits cleanly (exit 0) so a temporary email failure doesn't show as a failed GitHub Actions run.

## Cost

**$0.** GitHub Actions free tier gives you 2,000 minutes/month. Each run takes ~30 seconds for 5 branches. Running every 30 minutes ≈ 24 min/month — well within free tier.

## Architecture

```
harris_county_appt_checker/
├── .github/workflows/check.yml   # GitHub Actions workflow (cron schedule)
├── checker.py                     # Main script (Playwright + SMTP)
├── config.json                    # User configuration (branches, transaction type)
├── README.md
└── LICENSE
```

- **checker.py** — Single-file Python script. Uses Playwright to drive a headless Chromium browser and Python's built-in `smtplib` for email. No external dependencies beyond Playwright.
- **check.yml** — GitHub Actions workflow that installs Python + Playwright, injects email secrets as env vars, and runs the checker on a cron schedule.
- **config.json** — All user-configurable options (URL, transaction type, branches, months to check, email subject).

## Customizing

This pattern works for any appointment page that uses a jQuery UI datepicker or similar calendar widget. Fork it and adapt `checker.py` for DMV sites, visa appointments, or anything with limited slots.

## Stopping It

Actions tab → click the workflow → **Disable workflow**.

## License

MIT — do whatever you want with it.
