# Harris County Appointment Checker

A zero-cost appointment monitor that checks the Harris County Tax Office for available auto appointment slots every 15 minutes and emails you when one opens up.

Runs entirely on GitHub Actions. No local machine. No servers. No API keys.

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
  "branches": ["Spring Branch", "Clay Road", "Downtown"],
  "days_to_check": 30,
  "notify_subject": "🚨 Harris County Appointment Available!"
}
```

**transaction_type** — which service you need. Options from the site:
- `New Resident (First time TX registration)`
- `Title Transfer`
- `Special Plate`
- `NMVITS/State Rej`
- `Hold file/2nd floor`

**branches** — which locations to check. Remove any you don't want. All 16 branches are listed by default. Fewer branches = faster checks.

**days_to_check** — how far ahead to look (default: 30 days).

### Step 5: Enable the workflow

Go to the **Actions** tab and enable workflows if prompted. You can also click **"Run workflow"** to test it immediately.

## How It Works

1. Every 15 minutes, GitHub Actions spins up a headless Chrome browser
2. It navigates to the appointment page
3. Selects your transaction type
4. Checks each branch you configured, scanning dates for open time slots
5. If it finds any → you get an email with branch, date, and available times
6. If not → it quietly waits and checks again

## Cost

**$0.** GitHub Actions free tier gives you 2,000 minutes/month. Each run takes ~2-5 minutes depending on how many branches you check. Checking 4 branches every 15 min ≈ 800 min/month — well within free tier.

**Tip:** To stay comfortably in free tier, trim your branches list to just 3-5 preferred locations.

## Customizing

This pattern works for any appointment page that loads availability dynamically. Fork it and adapt `checker.py` for DMV sites, visa appointments, or anything with limited slots.

## Stopping It

Actions tab → click the workflow → **Disable workflow**.

## License

MIT — do whatever you want with it.
